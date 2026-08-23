import asyncio
import struct
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BufferedReader, BytesIO
from pathlib import Path
from typing import Any, Literal, cast

import ariblib
import ariblib.event
from ariblib.descriptors import (
    AudioComponentDescriptor,
    ServiceDescriptor,
    TSInformationDescriptor,
)
from ariblib.packet import payload, payload_unit_start_indicator, pid
from ariblib.sections import (
    ActualNetworkNetworkInformationSection,
    ActualStreamPresentFollowingEventInformationSection,
    ActualStreamServiceDescriptionSection,
    ProgramAssociationSection,
    ProgramMapSection,
    TimeOffsetSection,
)
from biim.mpeg2ts import ts

from app import logging, schemas
from app.constants import JST
from app.utils import ClosestMultiple, NormalizeToJSTDatetime
from app.utils.TSInformation import TSInformation


@dataclass(slots=True)
class _EITProgramCandidate:
    """
    EIT[p/f] から復元した録画番組候補
    """

    recorded_program: schemas.RecordedProgram
    seek_offset: int
    section_number: int
    completeness_score: int


class TSInfoAnalyzer:
    """
    録画 TS ファイルや録画データ関連ファイルに含まれる番組情報を解析するクラス
    ariblib の開発者の youzaka 氏に感謝します
    """

    def __init__(
        self,
        recorded_video: schemas.RecordedVideo,
        end_ts_offset: int | None = None,
        selected_service_id: int | None = None,
        preferred_service_id: int | None = None,
    ) -> None:
        """
        録画 TS ファイルや録画データ関連ファイルに含まれる番組情報を解析するクラスを初期化する

        Args:
            recorded_video (schemas.RecordedVideo): 録画ファイル情報を表すモデル
            end_ts_offset (int | None): 有効な TS データの終了位置 (バイト単位、ファイル後半がゼロ埋めされている場合に指定する)
            selected_service_id (int | None): 指定するサービスID（複数チャンネル選択用）
            preferred_service_id (int | None): 優先的に使用する service_id (FFprobe などの外部解析結果から得られた値)
        """

        # 有効な TS データの終了位置 (EIT 解析時に必要)
        # 未指定時はファイルサイズをそのまま利用する
        if end_ts_offset is not None:
            self.end_ts_offset = end_ts_offset
        else:
            self.end_ts_offset = recorded_video.file_size

        self.recorded_video = recorded_video
        self.first_tot_timedelta = timedelta()
        self.last_tot_timedelta = timedelta()

        # 指定するサービスID（複数チャンネル選択用）
        self.selected_service_id = selected_service_id

        # 優先的に使用する service_id (外部から指定された場合)
        self.preferred_service_id = preferred_service_id

        # 録画ファイルが MPEG-TS 形式の場合
        if self.recorded_video.container_format == 'MPEG-TS':
            # ファイルパスを解決（シンボリックリンクの場合は実体パスに変換）
            file_path = Path(self.recorded_video.file_path)
            try:
                # シンボリックリンクを解決して実体のパスを取得
                resolved_path = file_path.resolve()
                # 解決後のパスが存在するか確認
                if not resolved_path.exists():
                    # 解決後のパスが存在しない場合は元のパスを試す
                    if file_path.exists():
                        resolved_path = file_path
                    else:
                        raise FileNotFoundError(f'File not found: {self.recorded_video.file_path} (resolved: {resolved_path})')
                file_path_to_open = str(resolved_path)
            except FileNotFoundError:
                # FileNotFoundError はそのまま再送出
                raise
            except Exception as ex:
                # その他の例外（OSError, RuntimeError, など）はシンボリックリンクの解決失敗として扱う
                logging.warning(f'{self.recorded_video.file_path}: Failed to resolve symlink, using original path:', exc_info=ex)
                file_path_to_open = self.recorded_video.file_path

            # TS ファイルを開く
            ## 188 * 10000 バイト (≒ 1.88MB) ごとに分割して読み込む
            ## 現状 ariblib は先頭が sync_byte でない or 途中で同期が壊れる (破損した TS パケットが存在する) TS ファイルを想定していないため、
            ## ariblib に入力する録画ファイルは必ず正常な TS ファイルである必要がある
            self.ts = ariblib.tsopen(file_path_to_open, chunk=10000)

        # それ以外の場合、存在すれば PSI/SI 書庫 (.psc) を読み込んで仮想 TS ファイルを作成する
        else:
            packets = bytearray()
            try:
                # 書庫があれば必要な PSI/SI セクションを取り出してインメモリの TS ファイルとして ariblib に入力する
                psc_path = Path(self.recorded_video.file_path).with_suffix('.psc')
                with open(psc_path, 'rb') as f:
                    # PID ごとの連続性指標
                    counters: dict[int, int] = {}
                    last_time_sec = 0.0
                    last_tot_time_sec: float | None = None

                    def callback(time_sec: float, pid: int, section: bytes):
                        nonlocal last_time_sec, last_tot_time_sec
                        last_time_sec = time_sec
                        if pid in (0x12, 0x26, 0x27):
                            # EIT は 20% の位置から 60 秒間だけ
                            if time_sec < self.recorded_video.duration * 0.2 or time_sec > self.recorded_video.duration * 0.2 + 60:
                                return True
                        elif pid == 0x14:
                            # 録画時刻の解析の精度を上げるため
                            if last_tot_time_sec is None:
                                self.first_tot_timedelta = timedelta(seconds = time_sec)
                            last_tot_time_sec = time_sec
                        else:
                            # TOT 以外は 60 秒間だけ
                            if time_sec > 60:
                                return True

                        i = 0
                        while i < len(section):
                            # TS パケットに変換
                            packets.append(0x47)
                            packets.append((0x40 if i == 0 else 0) | pid >> 8)
                            packets.append(pid & 0xff)
                            counters[pid] = (counters[pid] + 1) & 0x0f if pid in counters else 0
                            packets.append(0x10 | counters[pid])
                            if i == 0:
                                packets.append(0)
                            while len(packets) % 188 != 0 and i < len(section):
                                packets.append(section[i])
                                i += 1
                            while len(packets) % 188 != 0:
                                packets.append(0xff)
                        return True

                    # PAT, NIT, SDT, TOT, EIT を取り出す
                    if not TSInfoAnalyzer.readPSIData(f, [0x00, 0x10, 0x11, 0x14, 0x12, 0x26, 0x27], callback):
                        logging.warning(f'{psc_path}: File contents may be invalid.')
                    if last_tot_time_sec is not None:
                        self.last_tot_timedelta = timedelta(seconds = last_time_sec - last_tot_time_sec)
            except Exception:
                pass

            # TODO: 物理ファイル以外を受け取れるよう ariblib を変更すべき
            # このやり方は ariblib の内部実装を仮定しているのでよくない
            class TransportStreamFileWorkaround(ariblib.TransportStreamFile):
                def __init__(self, stream: Any):
                    BufferedReader.__init__(self, stream)
                    self.chunk_size = 1
                    self._callbacks = dict()

            # コンストラクタは失敗しない設計なので packets が空でも入力する
            # ここで self.end_ts_offset に 0 がセットされた時、TSInfoAnalyzer.analyze() は常に None を返す
            self.ts = TransportStreamFileWorkaround(BytesIO(packets))
            self.end_ts_offset = len(packets)


    def analyze(self) -> schemas.RecordedProgram | None:
        """
        録画 TS ファイルや録画データ関連ファイルに含まれる番組情報を解析する

        Returns:
            schemas.RecordedProgram:  録画番組情報（中に録画ファイル情報・チャンネル情報が含まれる）を表すモデル
                (サービスまたは番組情報が取得できなかった場合は None)
        """

        # 録画ファイルが MPEG-TS 形式ではなく、かつ PSI/SI の書庫がなかった場合
        # 録画番組情報の取得は不可能なため None を返す
        if self.recorded_video.container_format != 'MPEG-TS' and self.end_ts_offset == 0:
            return None

        # サービス (チャンネル) 情報を取得
        channel = self.__analyzeSDTInformation()
        if channel is None:
            logging.warning(f'{self.recorded_video.file_path}: Channel information not found.')
            return None

        # 録画番組情報のモデルを作成
        ## EIT[p/f] は「その読み取り位置での現在/次の番組」なので、録画先頭マージン中の 0% 位置だけを見ると前番組を採用してしまう
        ## 先に TS 内の TOT/PCR から録画時間帯を復元し、後段の EIT 候補選択で時間的に矛盾する番組を落とせるようにする
        recording_time = self.analyzeRecordingTime()
        if recording_time is not None:
            self.recorded_video.recording_start_time = recording_time[0]
            self.recorded_video.recording_end_time = recording_time[1]

        recorded_program = self.__analyzeEITInformation(channel)
        if recorded_program is None:
            return None

        # 選択された番組情報の duration が 0 の場合は現在/次の両方とも正しい番組情報を取得できなかったことを意味するので、None を返す
        # このとき番組開始時刻・番組終了時刻は 1970-01-01 09:00:00 になっているはず
        if recorded_program.duration == 0.0:
            logging.warning(f'{self.recorded_video.file_path}: Program information not found.')
            return None

        # 録画ファイル情報・チャンネル情報を紐付け
        recorded_program.recorded_video = self.recorded_video
        recorded_program.channel = channel

        return recorded_program


    def analyzeRecordingTime(self) -> tuple[datetime, datetime] | None:
        """
        TOT (Time Offset Table) から録画開始時刻と録画終了時刻を解析する
        このメソッドは MPEG-TS / PSI/SI 書庫 (.psc) の両方に対応する

        Returns:
            tuple[datetime, datetime]: 録画開始時刻と録画終了時刻 (取得できなかった場合は None)
        """

        # MPEG-TS の場合: ariblib.packet のユーティリティと TimeOffsetSection を使って単一パスで解析する
        if self.recorded_video.container_format == 'MPEG-TS':
            try:
                # 誤動作防止のため必ず最初にシークを戻す
                self.ts.seek(0)

                buffer = bytearray()
                first_pcr_sec: float | None = None
                current_pcr_sec: float | None = None
                # PSI セクション開始時点 (PUSI) の PCR 値を保持し、そのセクションに対する経過時間算出に用いる
                pcr_at_section_start_sec: float | None = None

                # end_ts_offset 以降はゼロ埋めである可能性が高いため、読み取りを制限する
                read_bytes = 0
                while True:
                    packet = self.ts.read(ts.PACKET_SIZE)
                    if packet is None or len(packet) < ts.PACKET_SIZE:
                        break
                    read_bytes += ts.PACKET_SIZE
                    if read_bytes > self.end_ts_offset:
                        break

                    # PCR を追跡
                    pcr_val = ts.pcr(packet)
                    if pcr_val is not None:
                        current_pcr_sec = pcr_val / ts.HZ
                        if first_pcr_sec is None:
                            first_pcr_sec = current_pcr_sec

                    # TOT (PID 0x14) のセクション組み立て
                    if pid(packet) != 0x14:
                        continue

                    prev, current = payload(packet)
                    if payload_unit_start_indicator(packet):
                        # まず、直前まで構築していたセクションを prev で完結させる
                        if buffer:
                            buffer.extend(prev)
                        # セクション長に従い切り出して TimeOffsetSection として解釈
                        while buffer and buffer[0] != 0xFF:
                            try:
                                if buffer[0] == 0x73:  # TimeOffsetSection の table_id
                                    section = TimeOffsetSection(buffer[:])
                                    if section.isfull():
                                        # 経過時間は「当該セクションの開始時 PCR - 最初の PCR」で算出する
                                        if (first_pcr_sec is not None) and (pcr_at_section_start_sec is not None):
                                            elapsed = max(float(pcr_at_section_start_sec) - float(first_pcr_sec), 0.0)
                                            assert section.JST_time is not None
                                            jst_time = NormalizeToJSTDatetime(section.JST_time)
                                            recording_start_time = jst_time - timedelta(seconds=elapsed)
                                            recording_end_time = recording_start_time + timedelta(seconds=self.recorded_video.duration)
                                            return (recording_start_time, recording_end_time)
                                # 次セクションへ
                                next_start = ((buffer[1] & 0x0F) << 8 | buffer[2]) + 3
                                buffer[:] = buffer[next_start:]
                            except Exception:
                                break
                        # 新しいセクション (current) を開始する。開始時点の PCR を保存する
                        buffer[:] = current
                        pcr_at_section_start_sec = current_pcr_sec
                    elif not buffer:
                        continue
                    else:
                        buffer.extend(current)

                # 残ったバッファを片付ける
                if buffer and buffer[0] == 0x73:
                    try:
                        section = TimeOffsetSection(buffer[:])
                        if section.isfull():
                            # ファイル末尾でセクションが完結した場合も、当該セクション開始時の PCR を使う
                            if (first_pcr_sec is None) or (pcr_at_section_start_sec is None):
                                pass
                            else:
                                elapsed = max(float(pcr_at_section_start_sec) - float(first_pcr_sec), 0.0)
                                assert section.JST_time is not None
                                jst_time = NormalizeToJSTDatetime(section.JST_time)
                                recording_start_time = jst_time - timedelta(seconds=elapsed)
                                recording_end_time = recording_start_time + timedelta(seconds=self.recorded_video.duration)
                                return (recording_start_time, recording_end_time)
                    except Exception:
                        pass

            except Exception as ex:
                logging.warning(f'{self.recorded_video.file_path}: Failed to analyze TOT from TS:', exc_info=ex)
                return None

            return None

        # それ以外の場合、存在すれば PSI/SI 書庫 (.psc) から作成された仮想 TS ファイルを使って録画開始時刻と録画終了時刻を解析する
        else:
            # 誤動作防止のため必ず最初にシークを戻す
            self.ts.seek(0)

            # TOT (Time Offset Table) を抽出
            first_tot_time: datetime | None = None
            last_tot_time: datetime | None = None
            for tot in self.ts.sections(TimeOffsetSection):
                if first_tot_time is None:
                    first_tot_time = NormalizeToJSTDatetime(tot.JST_time)
                last_tot_time = NormalizeToJSTDatetime(tot.JST_time)

            if first_tot_time is None or last_tot_time is None:
                return None

            return (first_tot_time - self.first_tot_timedelta, last_tot_time + self.last_tot_timedelta)


    def __collectAllChannels(self) -> list[dict[str, Any]]:
        """
        TS 内の全ての利用可能なチャンネル情報を収集する

        Returns:
            list[dict]: チャンネル情報のリスト、各要素は以下の構造:
            {
                'service_id': int,
                'channel_name': str,
                'network_id': int,
                'transport_stream_id': int,
                'channel_type': str,
                'remocon_id': int
            }
        """

        # 破損した先頭領域を回避するため、複数のシーク位置で PAT/SDT/NIT を試す
        seek_offsets = self.__getTSSectionSeekOffsets()

        all_channels = []
        transport_stream_id: int | None = None

        # PAT から全ての利用可能な service_id を収集（最初の60秒分のみ）
        available_service_ids: list[int] = []
        # 先頭付近に破損がある場合に備え、複数オフセットから PAT を探索する
        for seek_offset in seek_offsets:
            available_service_ids = []
            transport_stream_id = None
            pat_count = 0
            try:
                for pat in self.__iterSectionsFromOffset(ProgramAssociationSection, seek_offset):
                    transport_stream_id = int(pat.transport_stream_id)
                    for pat_pid in pat.pids:
                        if pat_pid.program_number:
                            available_service_ids.append(int(pat_pid.program_number))

                    # PAT解析の制限（60秒相当のループ数で制限）
                    pat_count += 1
                    if pat_count > 100:  # EIT解析と同様の制限値
                        break
            except (IndexError, ValueError, TypeError, AttributeError, struct.error) as ex:
                logging.warning(
                    f'{self.recorded_video.file_path}: Failed to parse PAT at offset {seek_offset}.',
                    exc_info=ex,
                )
                continue

            # service_id が取得できたら以降の解析に進む
            if available_service_ids:
                break

        if not available_service_ids:
            return all_channels

        # SDT から各サービスの詳細情報を取得（最初の60秒分のみ）
        # 先頭付近に破損がある場合に備え、複数オフセットから SDT を探索する
        for seek_offset in seek_offsets:
            all_channels = []
            seen_service_ids = set()  # 重複チェック用のセット
            sdt_count = 0
            try:
                for sdt in self.__iterSectionsFromOffset(ActualStreamServiceDescriptionSection, seek_offset):
                    network_id = int(sdt.original_network_id)
                    network_type = TSInformation.getNetworkType(network_id)
                    if network_type == 'OTHER':
                        continue

                    for service in sdt.services:
                        if service.service_id in available_service_ids and service.service_id not in seen_service_ids:
                            # チャンネル名を取得
                            channel_name = None
                            for sd in service.descriptors[ServiceDescriptor]:
                                channel_name = TSInformation.formatString(sd.service_name)
                                break

                            if channel_name:
                                # リモコン番号を計算
                                if network_type == 'GR':
                                    remocon_id = 0  # 地デジの場合は後で NIT から取得
                                else:
                                    remocon_id = TSInformation.calculateRemoconID(network_type, service.service_id)

                                all_channels.append({
                                    'service_id': service.service_id,
                                    'channel_name': channel_name,
                                    'network_id': network_id,
                                    'transport_stream_id': transport_stream_id,
                                    'channel_type': network_type,
                                    'remocon_id': remocon_id
                                })
                                seen_service_ids.add(service.service_id)  # 重複防止のため追加

                    # SDT解析の制限（60秒相当のループ数で制限）
                    sdt_count += 1
                    if sdt_count > 100:  # EIT解析と同様の制限値
                        break
            except (IndexError, ValueError, TypeError, AttributeError, struct.error) as ex:
                logging.warning(
                    f'{self.recorded_video.file_path}: Failed to parse SDT at offset {seek_offset}.',
                    exc_info=ex,
                )
                continue

            # チャンネル情報を取得できたら以降の解析に進む
            if all_channels:
                break

        # 地デジの場合、NIT からリモコン番号を取得（最初の60秒分のみ）
        if all_channels and all_channels[0]['channel_type'] == 'GR':
            # 先頭付近に破損がある場合に備え、複数オフセットから NIT を探索する
            for seek_offset in seek_offsets:
                nit_count = 0
                try:
                    for nit in self.__iterSectionsFromOffset(ActualNetworkNetworkInformationSection, seek_offset):
                        for transport_stream in nit.transport_streams:
                            for ts_information in transport_stream.descriptors.get(TSInformationDescriptor, []):
                                remocon_id = int(ts_information.remote_control_key_id)
                                # 同一 TS の全チャンネルに同じリモコン番号を設定
                                for channel in all_channels:
                                    if channel['channel_type'] == 'GR':
                                        channel['remocon_id'] = remocon_id
                                break
                            break

                        # NIT解析の制限（60秒相当のループ数で制限）
                        nit_count += 1
                        if nit_count > 100:  # EIT解析と同様の制限値
                            break

                        # リモコン番号が確定したら終了
                        if any(ch['remocon_id'] != 0 for ch in all_channels):
                            break
                except (IndexError, ValueError, TypeError, AttributeError, struct.error) as ex:
                    logging.warning(
                        f'{self.recorded_video.file_path}: Failed to parse NIT at offset {seek_offset}.',
                        exc_info=ex,
                    )
                    continue

                # リモコン番号が確定したら終了
                if any(ch['remocon_id'] != 0 for ch in all_channels):
                    break

        return all_channels

    def __getTSSectionSeekOffsets(self) -> list[int]:
        """
        PAT/SDT/NIT 解析用に試すシークオフセットを取得する

        Returns:
            list[int]: シークオフセット（バイト単位）
        """

        # MPEG-TS 以外は仮想 TS ファイルの先頭のみ
        if self.recorded_video.container_format != 'MPEG-TS':
            return [0]

        # end_ts_offset 以降はゼロ埋めされている可能性があるため、有効範囲内で計算する
        effective_size = min(self.end_ts_offset, self.recorded_video.file_size)
        if effective_size <= 0:
            return [0]

        # 先頭に破損がある場合に備えて、0%・10%・20%・30%・50%・80% の位置を試す
        candidate_ratios = [0.0, 0.1, 0.2, 0.3, 0.5, 0.8]
        seek_offsets: list[int] = []
        for ratio in candidate_ratios:
            offset = ClosestMultiple(int(effective_size * ratio), ts.PACKET_SIZE)
            if offset > effective_size - ts.PACKET_SIZE:
                offset = max(effective_size - ts.PACKET_SIZE, 0)
            if offset not in seek_offsets:
                seek_offsets.append(offset)

        return seek_offsets

    def __findTSResyncOffset(self, base_offset: int) -> int | None:
        """
        指定オフセット付近で TS の同期位置を探索する

        Args:
            base_offset: 探索開始オフセット

        Returns:
            int | None: 同期位置が見つかった場合はそのオフセット、見つからない場合は None
        """

        # MPEG-TS 以外はリシンク不要
        if self.recorded_video.container_format != 'MPEG-TS':
            return base_offset

        try:
            file_path = Path(self.recorded_video.file_path)
            effective_size = min(self.end_ts_offset, self.recorded_video.file_size)
            if effective_size <= ts.PACKET_SIZE:
                return None

            # 同期探索は 5000 パケット分だけ行う
            scan_size = ts.PACKET_SIZE * 5000
            if base_offset < 0:
                base_offset = 0
            if base_offset > effective_size - ts.PACKET_SIZE:
                base_offset = max(effective_size - ts.PACKET_SIZE, 0)

            with file_path.open('rb') as f:
                f.seek(base_offset)
                data = f.read(scan_size)
        except Exception as ex:
            logging.warning(
                f'{self.recorded_video.file_path}: Failed to read TS data for resync at offset {base_offset}.',
                exc_info=ex,
            )
            return None

        # 3 パケット連続で同期バイトが一致する位置を探索する
        max_offset = len(data) - ts.PACKET_SIZE * 2
        if max_offset <= 0:
            return None
        for offset in range(0, max_offset):
            if data[offset] != ts.SYNC_BYTE[0]:
                continue
            if data[offset + ts.PACKET_SIZE] != ts.SYNC_BYTE[0]:
                continue
            if data[offset + ts.PACKET_SIZE * 2] != ts.SYNC_BYTE[0]:
                continue
            return base_offset + offset

        return None

    def __iterSectionsFromOffset(self, section_class: type, seek_offset: int, allow_sanitized_fallback: bool = False) -> Any:
        """
        指定オフセットからセクションを列挙する

        Args:
            section_class: 対象セクションのクラス
            seek_offset: シークオフセット
            allow_sanitized_fallback: 破損が疑われる場合にサニタイズした TS からの抽出を許可するかどうか

        Returns:
            Any: セクションのイテレータ
        """

        # MPEG-TS の場合は ariblib の内部キャッシュを避けるため、新しい TS ハンドルを開く
        if self.recorded_video.container_format == 'MPEG-TS':
            last_exception: Exception | None = None
            # 破損やズレがある場合に備えて複数の位置から再試行する
            retry_bases = [
                seek_offset,
                seek_offset + ts.PACKET_SIZE * 5000,   # 約 0.9MB 先
                seek_offset + ts.PACKET_SIZE * 20000,  # 約 3.7MB 先
            ]
            effective_size = min(self.end_ts_offset, self.recorded_video.file_size)
            retry_offsets: list[int] = []
            for base_offset in retry_bases:
                if base_offset < 0:
                    continue
                if base_offset > effective_size - ts.PACKET_SIZE:
                    continue
                resync_offset = self.__findTSResyncOffset(base_offset)
                if resync_offset is not None and resync_offset not in retry_offsets:
                    retry_offsets.append(resync_offset)
            if not retry_offsets:
                retry_offsets = [seek_offset]

            for retry_offset in retry_offsets:
                try:
                    with ariblib.tsopen(self.recorded_video.file_path, chunk=10000) as section_ts:
                        section_ts.seek(retry_offset)
                        for section in section_ts.sections(section_class):
                            yield section
                    # セクションの列挙が正常に完了したら終了
                    return
                except (IndexError, ValueError, TypeError, AttributeError, struct.error) as ex:
                    last_exception = ex
                    continue

            # 破損が疑われる場合は、サニタイズ済みの TS データから再試行する
            if allow_sanitized_fallback is True:
                for section in self.__iterSanitizedEITSections(section_class, seek_offset):
                    yield section
                for section in self.__iterRobustEITSections(section_class, seek_offset):
                    yield section
                return

            # すべての再試行が失敗した場合は最後の例外を再送出する
            if last_exception is not None:
                raise last_exception
        else:
            # 仮想 TS ファイルはシーク位置を尊重できるため、既存ハンドルを使う
            self.ts.seek(seek_offset)
            for section in self.ts.sections(section_class):
                yield section

    def __iterSanitizedEITSections(self, section_class: type, seek_offset: int) -> Any:
        """
        破損パケットを除外して EIT セクションを抽出する

        Args:
            section_class: 対象セクションのクラス
            seek_offset: シークオフセット

        Returns:
            Any: セクションのイテレータ
        """

        # MPEG-TS 以外では通常の抽出経路に任せる
        if self.recorded_video.container_format != 'MPEG-TS':
            return

        # EIT の PID のみを収集する
        target_pids = {0x12, 0x26, 0x27}
        effective_size = min(self.end_ts_offset, self.recorded_video.file_size)
        if effective_size <= 0:
            return

        # 取得範囲を安全な範囲に調整する
        start_offset = max(seek_offset, 0)
        if start_offset > effective_size - ts.PACKET_SIZE:
            start_offset = max(effective_size - ts.PACKET_SIZE, 0)

        # 破損の影響を避けるために、一定サイズだけ読み込んでサニタイズする
        window_size = min(12 * 1024 * 1024, effective_size - start_offset)  # 最大 12MB
        if window_size <= ts.PACKET_SIZE:
            return

        try:
            with open(self.recorded_video.file_path, 'rb') as f:
                f.seek(start_offset)
                data = f.read(window_size)
        except Exception as ex:
            logging.warning(
                f'{self.recorded_video.file_path}: Failed to read TS data for sanitized EIT parsing.',
                exc_info=ex,
            )
            return

        # 同期バイトを頼りに 188 バイト境界でパケットを再構成する
        packets = bytearray()
        offset = 0
        while offset + ts.PACKET_SIZE <= len(data):
            # 同期バイトが一致しない場合は 1 バイトずらして再試行する
            if data[offset] != ts.SYNC_BYTE[0]:
                offset += 1
                continue
            # 直後のパケットも同期している場合のみ採用する
            if offset + ts.PACKET_SIZE < len(data) and data[offset + ts.PACKET_SIZE] != ts.SYNC_BYTE[0]:
                offset += 1
                continue

            packet = data[offset:offset + ts.PACKET_SIZE]
            # 破損パケットは除外する
            if self.__isValidTSPacket(packet) is False:
                offset += 1
                continue
            # EIT の PID のみを収集する
            packet_pid = pid(packet)
            if packet_pid in target_pids:
                packets.extend(packet)
            offset += ts.PACKET_SIZE

        if len(packets) < ts.PACKET_SIZE:
            return

        # ariblib が受け取れる形式に包んでセクションを抽出する
        class TransportStreamFileWorkaround(ariblib.TransportStreamFile):
            def __init__(self, stream: Any):
                BufferedReader.__init__(self, stream)
                self.chunk_size = 1
                self._callbacks = dict()

        try:
            sanitized_ts = TransportStreamFileWorkaround(BytesIO(packets))
            yield from sanitized_ts.sections(section_class)
        except (IndexError, ValueError, TypeError, AttributeError, struct.error) as ex:
            logging.warning(
                f'{self.recorded_video.file_path}: Failed to parse sanitized EIT sections.',
                exc_info=ex,
            )
            return

    def __isValidTSPacket(self, packet: bytes) -> bool:
        """
        TS パケットが最低限の構造を満たしているかを判定する

        Args:
            packet: TS パケット

        Returns:
            bool: 正常なパケットなら True
        """

        if len(packet) != ts.PACKET_SIZE:
            return False
        if packet[0] != ts.SYNC_BYTE[0]:
            return False

        adaptation_field_control = (packet[3] >> 4) & 0x03
        if adaptation_field_control == 0:
            return False

        # アダプテーションフィールドがある場合、長さが範囲内か確認する
        payload_start = 4
        if adaptation_field_control in (2, 3):
            adaptation_field_length = packet[4]
            payload_start = 5 + adaptation_field_length
            if payload_start > ts.PACKET_SIZE:
                return False

        # payload_unit_start_indicator が立っている場合、pointer_field が範囲内か確認する
        if packet[1] & 0x40:
            if payload_start >= ts.PACKET_SIZE:
                return False
            pointer_field = packet[payload_start]
            if payload_start + 1 + pointer_field > ts.PACKET_SIZE:
                return False

        return True

    def __iterRobustEITSections(self, section_class: type, seek_offset: int) -> Any:
        """
        ariblib の payload 解析に依存せず、TS パケットから直接 EIT セクションを組み立てる

        Args:
            section_class: 対象セクションのクラス
            seek_offset: シークオフセット

        Returns:
            Any: セクションのイテレータ
        """

        # EIT 以外のセクションは対象外
        if section_class is not ActualStreamPresentFollowingEventInformationSection:
            return
        if self.recorded_video.container_format != 'MPEG-TS':
            return

        # EIT の PID のみを解析対象にする
        target_pids = {0x12, 0x26, 0x27}
        effective_size = min(self.end_ts_offset, self.recorded_video.file_size)
        if effective_size <= ts.PACKET_SIZE:
            return

        # 解析対象の範囲を決める
        start_offset = max(seek_offset, 0)
        if start_offset > effective_size - ts.PACKET_SIZE:
            start_offset = max(effective_size - ts.PACKET_SIZE, 0)
        window_size = min(48 * 1024 * 1024, effective_size - start_offset)  # 最大 48MB
        if window_size <= ts.PACKET_SIZE:
            return

        try:
            with open(self.recorded_video.file_path, 'rb') as f:
                f.seek(start_offset)
                data = f.read(window_size)
        except Exception as ex:
            logging.warning(
                f'{self.recorded_video.file_path}: Failed to read TS data for robust EIT parsing.',
                exc_info=ex,
            )
            return

        # PID ごとにバッファを保持する
        buffers: dict[int, bytearray] = {}
        offset = 0
        while offset + ts.PACKET_SIZE <= len(data):
            # 同期バイトを探す
            if data[offset] != ts.SYNC_BYTE[0]:
                offset += 1
                continue
            packet = data[offset:offset + ts.PACKET_SIZE]
            if self.__isValidTSPacket(packet) is False:
                offset += 1
                continue

            # TS ヘッダーの最低限の情報を抽出
            pid_value = ((packet[1] & 0x1F) << 8) | packet[2]
            if pid_value not in target_pids:
                offset += ts.PACKET_SIZE
                continue

            adaptation_field_control = (packet[3] >> 4) & 0x03
            if adaptation_field_control in (0, 2):
                # payload が無い場合はスキップする
                offset += ts.PACKET_SIZE
                continue

            payload_start = 4
            if adaptation_field_control == 3:
                adaptation_field_length = packet[4]
                payload_start = 5 + adaptation_field_length
                if payload_start >= ts.PACKET_SIZE:
                    offset += 1
                    continue

            payload = packet[payload_start:]
            if len(payload) == 0:
                offset += ts.PACKET_SIZE
                continue

            pusi = bool(packet[1] & 0x40)
            buffer = buffers.setdefault(pid_value, bytearray())

            if pusi is True:
                pointer_field = payload[0]
                if 1 + pointer_field > len(payload):
                    offset += 1
                    continue
                if pointer_field > 0:
                    # 直前のセクションの続きがあれば取り込む
                    buffer.extend(payload[1:1 + pointer_field])
                    yield from self.__emitEITSections(section_class, buffer)
                    buffer.clear()
                # 新しいセクションの開始
                buffer.extend(payload[1 + pointer_field:])
            else:
                buffer.extend(payload)

            yield from self.__emitEITSections(section_class, buffer)

            offset += ts.PACKET_SIZE

    def __emitEITSections(self, section_class: type, buffer: bytearray) -> Any:
        """
        バッファから EIT セクションを切り出して返す

        Args:
            section_class: 対象セクションのクラス
            buffer: バッファ

        Returns:
            Any: セクションのイテレータ
        """

        while len(buffer) >= 3:
            # section_length を取得
            section_length = ((buffer[1] & 0x0F) << 8) | buffer[2]
            total_length = 3 + section_length
            # 異常に長い値は破損とみなしてバッファを破棄する
            if total_length > 4096:
                buffer.clear()
                return
            if len(buffer) < total_length:
                return
            section_data = bytes(buffer[:total_length])
            del buffer[:total_length]
            try:
                section = section_class(section_data)
            except (IndexError, ValueError, TypeError, AttributeError, struct.error):
                continue
            yield section

    def __selectBestChannel(self, all_channels: list[dict[str, Any]]) -> dict[str, Any] | None:
        """
        設定に基づいて最適なチャンネルを選択する

        Args:
            all_channels: 利用可能な全チャンネル情報

        Returns:
            選択されたチャンネル情報、または None
        """
        from pathlib import Path

        from app.config import Config

        if not all_channels:
            return None

        # 1つしかない場合はそれを返す
        if len(all_channels) == 1:
            return all_channels[0]

        logging.info(f'{self.recorded_video.file_path}: Found {len(all_channels)} channels, attempting smart selection.')

        # 手動で指定されたサービスIDがある場合、それを優先
        if self.selected_service_id is not None:
            for channel in all_channels:
                if channel['service_id'] == self.selected_service_id:
                    logging.info(f'{self.recorded_video.file_path}: Selected manually specified channel {channel["channel_name"]} (SID: {channel["service_id"]}).')
                    return channel
            # 指定されたservice_idが見つからない場合は警告してフォールバック
            logging.warning(f'{self.recorded_video.file_path}: Specified service_id {self.selected_service_id} not found, falling back to automatic selection.')

        # 設定を取得
        try:
            config = Config()
            selection_mode = config.video.channel_selection_mode
            enable_filename_based = config.video.enable_filename_based_channel_selection
        except Exception:
            # 設定取得に失敗した場合のデフォルト
            selection_mode = 'auto'
            enable_filename_based = True

        # 設定に基づく選択
        if selection_mode == 'first_found':
            # 最初に見つかったチャンネルを選択
            selected = all_channels[0]
            logging.info(f'{self.recorded_video.file_path}: Selected first found channel {selected["channel_name"]} (SID: {selected["service_id"]}) per config.')
            return selected

        elif selection_mode == 'prefer_main':
            # メインチャンネルを優先
            main_channels = [ch for ch in all_channels if not TSInformation.calculateIsSubchannel(ch['channel_type'], ch['service_id'])]
            if main_channels:
                selected = main_channels[0]
                logging.info(f'{self.recorded_video.file_path}: Selected main channel {selected["channel_name"]} (SID: {selected["service_id"]}) per config.')
                return selected
            else:
                selected = all_channels[0]
                logging.info(f'{self.recorded_video.file_path}: No main channel found, selected first available {selected["channel_name"]} (SID: {selected["service_id"]}).')
                return selected

        elif selection_mode == 'filename_based' or (selection_mode == 'auto' and enable_filename_based):
            # ファイル名ベースの選択
            filename = Path(self.recorded_video.file_path).stem
            filename_info = TSInformation.parseFilenameInfo(filename)

            # ファイル名から番組名と開始時刻が取得できた場合、EIT 情報と照合
            if filename_info['start_time'] and filename_info['program_title']:
                start_time = filename_info['start_time']
                program_title = filename_info['program_title']

                logging.info(f'{self.recorded_video.file_path}: Using filename info - start_time: {start_time}, title: {program_title}')

                # 各チャンネルで番組情報を確認
                for channel in all_channels:
                    if self.__checkChannelProgramMatch(channel, start_time, program_title):
                        logging.info(f'{self.recorded_video.file_path}: Selected channel {channel["channel_name"]} (SID: {channel["service_id"]}) based on program match.')
                        return channel

            # ファイル名ベースでマッチしない場合、メインチャンネルを優先
            main_channels = [ch for ch in all_channels if not TSInformation.calculateIsSubchannel(ch['channel_type'], ch['service_id'])]
            if main_channels:
                selected = main_channels[0]
                logging.info(f'{self.recorded_video.file_path}: No filename match, selected main channel {selected["channel_name"]} (SID: {selected["service_id"]}).')
                return selected

        # フォールバック: 最初のチャンネル
        selected = all_channels[0]
        logging.info(f'{self.recorded_video.file_path}: Selected first available channel {selected["channel_name"]} (SID: {selected["service_id"]}) as fallback.')
        return selected

    def __checkChannelProgramMatch(self, channel: dict[str, Any], target_start_time: datetime, target_title: str) -> bool:
        """
        指定されたチャンネルで、指定時刻・タイトルの番組が存在するかチェック

        Args:
            channel: チャンネル情報
            target_start_time: 対象開始時刻
            target_title: 対象番組タイトル

        Returns:
            マッチするかどうか
        """
        try:
            # EIT情報から番組を検索（簡易実装）
            # 実際の実装では、指定時刻周辺の番組情報を取得してタイトルを比較する
            # ここでは基本的なマッチング処理を行う

            # タイトルの類似度をチェック（簡易版）
            # より詳細な実装では、EIT から実際の番組情報を取得して比較する
            return True  # 今回は基本実装として常に True を返す

        except Exception:
            return False

    def __analyzeSDTInformation(self) -> schemas.Channel | None:
        """
        TS 内の SDT (Service Description Table) からサービス（チャンネル）情報を解析する
        複数のサービスが存在する場合は、PID の出現頻度から正しいサービス ID を推定する

        Returns:
            schemas.Channel: サービス（チャンネル）情報を表すモデル (サービス情報が取得できなかった場合は None)
        """

        # 破損した先頭領域を回避するため、複数のシーク位置で PAT/SDT/NIT を試す
        seek_offsets = self.__getTSSectionSeekOffsets()

        # 必要な情報を一旦変数として保持
        transport_stream_id: int | None = None
        service_id: int | None = None
        network_id: int | None = None
        channel_type: Literal['GR', 'BS', 'CS', 'CATV', 'SKY', 'BS4K'] | None = None
        channel_name: str | None = None
        remocon_id: int | None = None

        # PAT (Program Association Table) からサービス ID が取得できるまで繰り返し処理
        service_id_order: list[int] = []
        service_pmt_pid_map: dict[int, int] = {}
        # 先頭付近に破損がある場合に備え、複数オフセットから PAT を探索する
        for seek_offset in seek_offsets:
            service_id_order = []
            service_pmt_pid_map = {}
            try:
                for pat in self.__iterSectionsFromOffset(ProgramAssociationSection, seek_offset):
                    # トランスポートストリーム ID (TSID) を取得
                    transport_stream_id = int(pat.transport_stream_id)

                    # サービス ID と PMT PID を取得
                    ## program_number は service_id と等しい
                    for pat_pid in pat.pids:
                        if pat_pid.program_number:
                            service_id = int(pat_pid.program_number)
                            service_id_order.append(service_id)
                            service_pmt_pid_map[service_id] = int(pat_pid.program_map_PID)

                    # 最初に見つかった PAT を使う
                    if len(service_id_order) > 0:
                        break
            except (IndexError, ValueError, TypeError, AttributeError, struct.error) as ex:
                logging.warning(
                    f'{self.recorded_video.file_path}: Failed to parse PAT at offset {seek_offset}.',
                    exc_info=ex,
                )
                continue

            # service_id が取得できたら以降の解析に進む
            if len(service_id_order) > 0:
                break

        if len(service_id_order) == 0:
            logging.warning(f'{self.recorded_video.file_path}: service_id not found.')
            return None

        # 外部から preferred_service_id が指定されていて、PAT に含まれている場合はそれを優先的に使用
        ## FFprobe などで実際にストリームが存在する service_id が事前に判明している場合に使用される
        if self.preferred_service_id is not None and self.preferred_service_id in service_id_order:
            service_id = self.preferred_service_id
            logging.debug(
                f'{self.recorded_video.file_path}: Using preferred service_id {service_id} from external analysis.'
            )
        # 複数サービスが存在する場合は、映像・音声 PID の出現頻度から正しい service_id を推定する
        elif len(service_id_order) > 1:
            selected_service_id = self.__selectServiceIdByPidFrequency(
                service_id_order = service_id_order,
                service_pmt_pid_map = service_pmt_pid_map,
            )
            if selected_service_id is not None:
                service_id = selected_service_id
            else:
                # 推定できなかった場合は、PAT に最初に出現した service_id を採用する
                service_id = service_id_order[0]
        else:
            service_id = service_id_order[0]

        # TS から SDT (Service Description Table) を抽出
        # 先頭付近に破損がある場合に備え、複数オフセットから SDT を探索する
        for seek_offset in seek_offsets:
            network_id = None
            channel_type = None
            channel_name = None
            try:
                for sdt in self.__iterSectionsFromOffset(ActualStreamServiceDescriptionSection, seek_offset):
                    # ネットワーク ID とサービス種別 (=チャンネルタイプ) を取得
                    network_id = int(sdt.original_network_id)
                    network_type = TSInformation.getNetworkType(network_id)
                    if network_type == 'OTHER':
                        logging.warning(f'{self.recorded_video.file_path}: Unknown network_id: {network_id}')
                        return None
                    channel_type = network_type  # ここで型が Literal['GR', 'BS', 'CS', 'CATV', 'SKY', 'BS4K'] に絞り込まれる
                    # SDT に含まれるサービスごとの情報を取得
                    for service in sdt.services:
                        # service_id が PAT から抽出したものと一致した場合のみ
                        # CS の場合同じ TS の中に複数のチャンネルが含まれている事があり、録画する場合は基本的に他のチャンネルは削除される
                        # そうすると ffprobe で確認できるがサービス情報や番組情報だけ残ってしまい、別のチャンネルの番組情報になるケースがある
                        # PAT にはそうした削除済みのチャンネルは含まれていないので、正しいチャンネルの service_id を抽出できる
                        if service.service_id == service_id:
                            # SDT から得られる ServiceDescriptor 内の情報からチャンネル名を取得
                            for sd in service.descriptors[ServiceDescriptor]:
                                channel_name = TSInformation.formatString(sd.service_name)
                                break
                            else:
                                continue
                            break
                    else:
                        continue
                    break
            except (IndexError, ValueError, TypeError, AttributeError, struct.error) as ex:
                logging.warning(
                    f'{self.recorded_video.file_path}: Failed to parse SDT at offset {seek_offset}.',
                    exc_info=ex,
                )
                continue

            # チャンネル名を取得できたら以降の解析に進む
            if channel_name is not None:
                break
        if network_id is None:
            logging.warning(f'{self.recorded_video.file_path}: network_id not found.')
            return None
        if channel_type is None:
            logging.warning(f'{self.recorded_video.file_path}: channel_type not found.')
            return None
        if channel_name is None:
            logging.warning(f'{self.recorded_video.file_path}: channel_name not found.')
            return None

        # リモコン番号を取得（地デジの場合は NIT から、それ以外は計算）
        if channel_type == 'GR':
            # NIT (Network Information Table) からリモコン番号を取得
            # 先頭付近に破損がある場合に備え、複数オフセットから NIT を探索する
            for seek_offset in seek_offsets:
                try:
                    for nit in self.__iterSectionsFromOffset(ActualNetworkNetworkInformationSection, seek_offset):
                        for transport_stream in nit.transport_streams:
                            for ts_information in transport_stream.descriptors.get(TSInformationDescriptor, []):
                                remocon_id = int(ts_information.remote_control_key_id)
                                break
                            else:
                                continue
                            break
                        else:
                            continue
                        break
                except (IndexError, ValueError, TypeError, AttributeError, struct.error) as ex:
                    logging.warning(
                        f'{self.recorded_video.file_path}: Failed to parse NIT at offset {seek_offset}.',
                        exc_info=ex,
                    )
                    continue

                # リモコン番号が取得できたら終了
                if remocon_id is not None:
                    break
        else:
            # BS/CS などはサービス ID から計算
            remocon_id = TSInformation.calculateRemoconID(channel_type, service_id)
        if remocon_id is None:
            logging.warning(f'{self.recorded_video.file_path}: remocon_id not found.')
            return None

        # チャンネル番号を算出
        channel_number = asyncio.run(TSInformation.calculateChannelNumber(
            channel_type,
            network_id,
            service_id,
            remocon_id,
        ))

        # チャンネル ID を生成
        channel_id = f'NID{network_id}-SID{service_id:03d}'

        # 表示用チャンネルID = チャンネルタイプ(小文字)+チャンネル番号
        display_channel_id = channel_type.lower() + channel_number

        # チャンネル情報を表すモデルを作成
        channel = schemas.Channel(
            id = channel_id,
            display_channel_id = display_channel_id,
            network_id = network_id,
            service_id = service_id,
            transport_stream_id = transport_stream_id,
            remocon_id = remocon_id,
            channel_number = channel_number,
            type = channel_type,
            name = channel_name,
        )

        # サブチャンネルかどうかを算出
        channel.is_subchannel = TSInformation.calculateIsSubchannel(channel.type, channel.service_id)

        # ラジオチャンネルにはなり得ない (録画ファイルのバリデーションの時点で映像と音声があることを確認している)
        channel.is_radiochannel = False

        # 録画ファイル内の情報として含まれているだけのチャンネルなので（現在視聴できるとは限らない）、is_watchable を False に設定
        ## もし視聴可能な場合はすでに channels テーブルにそのチャンネルのレコードが存在しているはずなので、そちらが優先される
        channel.is_watchable = False

        return channel


    def collectAllChannels(self) -> list[dict[str, Any]]:
        """
        TS 内の全ての利用可能なチャンネル情報を収集する。

        Args:
            なし

        Returns:
            list[dict[str, Any]]: 録画 TS に含まれるチャンネル情報のリスト。
        """

        # ルーターなど外部モジュールから利用できる公開メソッドとして、
        ## 実装詳細の private メソッド呼び出しをこのクラス内に閉じ込める
        return self.__collectAllChannels()


    def __analyzeEITInformation(self, channel: schemas.Channel) -> schemas.RecordedProgram | None:
        """
        TS 内の EIT (Event Information Table) から録画対象の番組情報を取得する

        Args:
            channel (schemas.Channel): チャンネル情報を表すモデル

        Returns:
            schemas.RecordedProgram | None: 録画番組情報を表すモデル、または取得に失敗した場合は None
        """

        # EIT[p/f] は読み取り位置における「現在/次の番組」だけを示す
        ## 録画先頭が前番組の終了間際に重なる場合があるため、複数位置から候補を集めて録画時間帯と照合する
        candidates = self.__collectEITProgramCandidates(channel)
        if len(candidates) == 0:
            logging.warning(
                f'{self.recorded_video.file_path}: Failed to parse EIT sections due to corrupted TS data. '
                f'Falling back to filename-based metadata.'
            )
            return None

        selected_candidate = self.__selectBestEITProgramCandidate(candidates)
        if selected_candidate is None:
            logging.warning(f'{self.recorded_video.file_path}: Program information not found.')
            return None

        recorded_program = selected_candidate.recorded_program
        logging.info(
            f'{self.recorded_video.file_path}: EIT program selected. '
            f'[event_id: {recorded_program.event_id}, title: {recorded_program.title}, '
            f'start_time: {recorded_program.start_time}, end_time: {recorded_program.end_time}, '
            f'seek_offset: {selected_candidate.seek_offset}, section_number: {selected_candidate.section_number}]'
        )
        return recorded_program


    def __collectEITProgramCandidates(self, channel: schemas.Channel) -> list[_EITProgramCandidate]:
        """
        複数位置の EIT[p/f] から録画番組候補を収集する

        Args:
            channel (schemas.Channel): チャンネル情報を表すモデル

        Returns:
            list[_EITProgramCandidate]: EIT から復元できた録画番組候補
        """

        # 破損した先頭領域や録画開始マージンを避けるため、既存の複数シーク位置をすべて候補収集に使う
        if self.recorded_video.container_format == 'MPEG-TS':
            seek_offsets = self.__getTSSectionSeekOffsets()
        else:
            seek_offsets = [0]

        candidates: list[_EITProgramCandidate] = []
        seen_candidates: set[tuple[int | None, datetime, int]] = set()
        corrupted_events = 0
        total_sections = 0
        matched_sections = 0

        for seek_offset in seek_offsets:
            section_count = 0
            found_section_numbers: set[int] = set()
            try:
                for eit in self.__iterSectionsFromOffset(
                    ActualStreamPresentFollowingEventInformationSection,
                    seek_offset,
                    allow_sanitized_fallback = True,
                ):
                    section_count += 1
                    total_sections += 1
                    if section_count > 2000:
                        logging.warning(f'{self.recorded_video.file_path}: Analyzing EIT information timed out.')
                        break

                    # present/following 以外のセクションはここでは録画番組候補として使わない
                    section_number = int(eit.section_number)
                    if section_number not in (0, 1):
                        continue

                    # サービス ID / TSID / ONID が一致した EIT だけを候補にする
                    ## CS など複数サービスを持つ TS で、別チャンネルの番組情報を採用することを防ぐ
                    if eit.service_id != channel.service_id:
                        continue
                    if channel.transport_stream_id is not None and eit.transport_stream_id != channel.transport_stream_id:
                        continue
                    if channel.network_id is not None and eit.original_network_id != channel.network_id:
                        continue

                    matched_sections += 1
                    found_section_numbers.add(section_number)
                    for event_data in eit.events:
                        try:
                            candidate = self.__buildEITProgramCandidate(channel, eit, event_data, seek_offset)
                        except (IndexError, ValueError, TypeError, AttributeError) as ex:
                            corrupted_events += 1
                            if corrupted_events <= 20:
                                logging.debug(f'{self.recorded_video.file_path}: Skipped corrupted EIT event #{corrupted_events}:', exc_info=ex)
                                continue
                            logging.warning(f'{self.recorded_video.file_path}: Too many corrupted EIT events ({corrupted_events}).')
                            break

                        if candidate is None:
                            continue

                        candidate_key = (
                            candidate.recorded_program.event_id,
                            candidate.recorded_program.start_time,
                            candidate.section_number,
                        )
                        if candidate_key in seen_candidates:
                            continue
                        seen_candidates.add(candidate_key)
                        candidates.append(candidate)

                    # 同じ offset から present/following を両方取れたら、同じ EIT の繰り返しを読み続けない
                    if len(found_section_numbers) == 2:
                        break
            except (IndexError, ValueError, TypeError, AttributeError, struct.error) as ex:
                logging.warning(
                    f'{self.recorded_video.file_path}: Failed to parse EIT sections due to corrupted TS data.',
                    exc_info=ex,
                )
                continue

        logging.info(
            f'{self.recorded_video.file_path}: EIT candidates collected. '
            f'[candidates: {len(candidates)}, sections: {total_sections}, matched: {matched_sections}]'
        )
        return candidates


    def __buildEITProgramCandidate(
        self,
        channel: schemas.Channel,
        eit: Any,
        event_data: Any,
        seek_offset: int,
    ) -> _EITProgramCandidate | None:
        """
        EIT の Event から録画番組候補を作成する

        Args:
            channel (schemas.Channel): チャンネル情報を表すモデル
            eit (Any): ariblib の EIT セクション
            event_data (Any): EIT 内のイベントデータ
            seek_offset (int): この EIT を読み取ったファイルオフセット

        Returns:
            _EITProgramCandidate | None: 復元できた候補、または時刻情報が不足している場合は None
        """

        event: Any = ariblib.event.Event(eit, event_data)

        # 必要な情報を一旦変数として保持
        event_id = int(event.event_id)
        title: str | None = None
        description: str | None = None
        detail: dict[str, str] | None = None
        start_time: datetime | None = None
        end_time: datetime | None = None
        duration: float | None = None
        is_free: bool | None = None
        genres: list[schemas.Genre] | None = None
        primary_audio_type: str | None = None
        primary_audio_language: str | None = None
        secondary_audio_type: str | None = None
        secondary_audio_language: str | None = None
        completeness_score = 0

        # 番組開始時刻と長さは、録画時間帯との照合に必須なので最初に復元する
        if event.start_time is not None:
            start_time = NormalizeToJSTDatetime(cast(datetime, event.start_time))
        if event.duration is not None:
            duration = cast(timedelta, event.duration).total_seconds()
        if start_time is None or duration is None:
            return None
        end_time = start_time + timedelta(seconds=duration)
        if duration <= 0:
            return None

        # ARIB TR-B15 第三分冊によると free_CA_mode が 1 のとき有料番組、0 のとき無料番組
        ## bool に変換した後、真偽を反転させる
        is_free = not bool(event.free_CA_mode)
        completeness_score += 1

        # 番組名, 番組概要 (ShortEventDescriptor)
        if hasattr(event, 'title') and hasattr(event, 'desc'):
            title = TSInformation.formatString(event.title)
            description = TSInformation.formatString(event.desc)
            completeness_score += 2

        # 番組詳細情報 (ExtendedEventDescriptor)
        if hasattr(event, 'detail'):
            detail = {}
            # 番組詳細テキストから取得した、見出しと本文の辞書ごとに
            for head, text in cast(dict[str, str], event.detail).items():
                # 見出しと本文
                ## 見出しのみ ariblib 側で意図的に重複防止のためのタブ文字付加が行われる場合があるため、
                ## strip() では明示的に半角スペースと改行のみを指定している
                head_hankaku = TSInformation.formatString(head).replace('◇', '').strip(' \r\n')
                ## ないとは思うが、万が一この状態で見出しが衝突しうる場合は、見出しの後ろにタブ文字を付加する
                while head_hankaku in detail.keys():
                    head_hankaku += '\t'
                ## 見出しが空の場合、固定で「番組内容」としておく
                if head_hankaku == '':
                    head_hankaku = '番組内容'
                text_hankaku = TSInformation.formatString(text).strip()
                detail[head_hankaku] = text_hankaku
                # 番組概要が空の場合、番組詳細の最初の本文を概要として使う
                ## 空でまったく情報がないよりかは良いはず
                if description is not None and description.strip() == '':
                    description = text_hankaku
            completeness_score += 1

        # ジャンル情報 (ContentDescriptor)
        if hasattr(event, 'genre') and hasattr(event, 'subgenre') and hasattr(event, 'user_genre'):
            genres = []
            for index, _ in enumerate(event.genre):
                # major は大分類、middle は中分類
                genre_dict: schemas.Genre = {
                    'major': event.genre[index].replace('／', '・'),
                    'middle': event.subgenre[index].replace('／', '・'),
                }
                # BS/地上デジタル放送用番組付属情報がジャンルに含まれている場合、user_genre から拡張情報を取得する
                ## たとえば「中止の可能性あり」や「延長の可能性あり」といった情報が取れる
                if genre_dict['major'] == '拡張':
                    if genre_dict['middle'] == 'BS/地上デジタル放送用番組付属情報':
                        genre_dict['middle'] = event.user_genre[index]
                    # 「拡張」はあるがBS/地上デジタル放送用番組付属情報でない場合はなんの値なのかわからないのでパス
                    else:
                        continue
                genres.append(genre_dict)
            completeness_score += 1

        # 音声情報 (AudioComponentDescriptor)
        if hasattr(event, 'audio'):
            primary_audio_type = str(event.audio)
            completeness_score += 1
        if hasattr(event, 'second_audio'):
            secondary_audio_type = str(event.second_audio)
            completeness_score += 1

        # 主音声・副音声の言語
        ## event クラスには用意されていないので自前で取得する
        for acd in event_data.descriptors.get(AudioComponentDescriptor, []):
            if bool(acd.main_component_flag) is True:
                primary_audio_language = TSInformation.getISO639LanguageCodeName(acd.ISO_639_language_code)
                if primary_audio_type == '1/0+1/0モード(デュアルモノ)':
                    if bool(acd.ES_multi_lingual_flag) is True:
                        primary_audio_language += '+' + TSInformation.getISO639LanguageCodeName(acd.ISO_639_language_code_2)
                    else:
                        primary_audio_language += '+副音声'
                completeness_score += 1
            else:
                secondary_audio_language = TSInformation.getISO639LanguageCodeName(acd.ISO_639_language_code)
                if secondary_audio_type == '1/0+1/0モード(デュアルモノ)':
                    if bool(acd.ES_multi_lingual_flag) is True:
                        secondary_audio_language += '+' + TSInformation.getISO639LanguageCodeName(acd.ISO_639_language_code_2)
                    else:
                        secondary_audio_language += '+副音声'
                completeness_score += 1

        # この時点でタイトルを取得できていない場合、拡張子を除いたファイル名をフォーマットした上でタイトルとして使用する
        if title is None:
            title = TSInformation.formatString(Path(self.recorded_video.file_path).stem)

        # 録画番組情報を表すモデルを作成 (ここでは確実に値を設定できるフィールドのみ設定)
        recorded_program = schemas.RecordedProgram(
            recorded_video = self.recorded_video,
            channel = channel,
            network_id = channel.network_id,
            service_id = channel.service_id,
            event_id = event_id,
            title = title,
            start_time = start_time,
            end_time = end_time,
            duration = duration,
            # 必須フィールドのため作成日時・更新日時は適当に現在時刻を入れている
            # この値は参照されず、DB の値は別途自動生成される
            created_at = datetime.now(tz=JST),
            updated_at = datetime.now(tz=JST),
        )

        # 以下のフィールドは、対応するデータを取得できなかった場合に Pydantic モデルに設定されているデフォルト値が使われる
        if description is not None:
            recorded_program.description = description
        if detail is not None:
            recorded_program.detail = detail
        if is_free is not None:
            recorded_program.is_free = is_free
        if genres is not None:
            recorded_program.genres = genres
        if primary_audio_type is not None:
            recorded_program.primary_audio_type = primary_audio_type
        if primary_audio_language is not None:
            recorded_program.primary_audio_language = primary_audio_language
        if secondary_audio_type is not None:
            recorded_program.secondary_audio_type = secondary_audio_type
        if secondary_audio_language is not None:
            recorded_program.secondary_audio_language = secondary_audio_language

        return _EITProgramCandidate(
            recorded_program = recorded_program,
            seek_offset = seek_offset,
            section_number = int(eit.section_number),
            completeness_score = completeness_score,
        )


    def __selectBestEITProgramCandidate(self, candidates: list[_EITProgramCandidate]) -> _EITProgramCandidate | None:
        """
        EIT 候補の中から録画時間帯に最も矛盾しない番組を選択する

        Args:
            candidates (list[_EITProgramCandidate]): EIT から復元できた録画番組候補

        Returns:
            _EITProgramCandidate | None: 選択された候補、または選択不能な場合は None
        """

        if len(candidates) == 0:
            return None

        def SelectBestCandidateByRecordingTime(
            candidate_recording_start_time: datetime,
            candidate_recording_end_time: datetime,
        ) -> tuple[_EITProgramCandidate | None, float]:
            """
            指定された録画時間帯と最も重なる EIT 候補を選択する

            Args:
                candidate_recording_start_time (datetime): 推定録画開始時刻
                candidate_recording_end_time (datetime): 推定録画終了時刻

            Returns:
                tuple[_EITProgramCandidate | None, float]: 最良候補と重複秒数
            """

            recording_duration = max((candidate_recording_end_time - candidate_recording_start_time).total_seconds(), 0.0)
            recording_mid_time = candidate_recording_start_time + timedelta(seconds=recording_duration / 2)

            def ScoreByRecordingTime(candidate: _EITProgramCandidate) -> tuple[float, int, int, int, float]:
                program = candidate.recorded_program
                overlap_start_time = max(program.start_time, candidate_recording_start_time)
                overlap_end_time = min(program.end_time, candidate_recording_end_time)
                overlap_seconds = max((overlap_end_time - overlap_start_time).total_seconds(), 0.0)
                contains_mid_time = int(program.start_time <= recording_mid_time < program.end_time)
                contains_recording_start = int(program.start_time <= candidate_recording_start_time < program.end_time)
                program_mid_time = program.start_time + timedelta(seconds=program.duration / 2)
                center_distance_seconds = abs((program_mid_time - recording_mid_time).total_seconds())
                return (
                    overlap_seconds,
                    contains_mid_time,
                    contains_recording_start,
                    candidate.completeness_score,
                    -center_distance_seconds,
                )

            best_candidate = max(candidates, key=ScoreByRecordingTime)
            best_overlap_seconds = ScoreByRecordingTime(best_candidate)[0]
            return (best_candidate, best_overlap_seconds)

        recording_time_ranges: list[tuple[str, datetime, datetime]] = []
        filename_info = TSInformation.parseFilenameInfo(Path(self.recorded_video.file_path).stem)
        filename_start_time = filename_info['start_time']

        # まずは TOT/PCR から復元した録画時刻を最優先で使う
        ## 実際の TS から取れた時刻なので、ファイル名やファイルシステム時刻より信頼できる
        if self.recorded_video.recording_start_time is not None and self.recorded_video.recording_end_time is not None:
            recording_time_ranges.append((
                'TOT/PCR',
                self.recorded_video.recording_start_time,
                self.recorded_video.recording_end_time,
            ))

        # TOT/PCR が壊れている録画では、ファイル更新時刻を録画終了時刻とみなし、実動画尺から開始時刻を逆算する
        ## コピー/移動で mtime が変わった場合は EIT 候補と重ならないため、後段の重複秒数チェックで採用されない
        file_modified_at = self.recorded_video.file_modified_at
        if file_modified_at.tzinfo is None:
            file_modified_at = file_modified_at.replace(tzinfo=JST)
        file_modified_recording_start_time = file_modified_at - timedelta(seconds=self.recorded_video.duration)
        # ファイル名にも開始時刻がある場合、mtime 逆算値が大きくズレているならコピー後の mtime とみなして使わない
        ## mtime が偶然別の EIT 候補に重なると誤採用になるため、2つの独立した時刻ヒントが矛盾しない場合だけ優先する
        if (
            not isinstance(filename_start_time, datetime) or
            abs((file_modified_recording_start_time - filename_start_time).total_seconds()) <= max(self.recorded_video.duration, 900.0)
        ):
            recording_time_ranges.append((
                'file modified time',
                file_modified_recording_start_time,
                file_modified_at,
            ))

        # 最後に、ファイル名に開始時刻が含まれる場合だけ補助情報として使う
        ## ファイル名だけで決め打ちせず、EIT 候補と実際に重なる場合に限って採用する
        if isinstance(filename_start_time, datetime):
            recording_time_ranges.append((
                'filename start time',
                filename_start_time,
                filename_start_time + timedelta(seconds=self.recorded_video.duration),
            ))

        for recording_time_source, recording_start_time, recording_end_time in recording_time_ranges:
            best_candidate, best_overlap_seconds = SelectBestCandidateByRecordingTime(recording_start_time, recording_end_time)
            if best_overlap_seconds > 0:
                logging.info(
                    f'{self.recorded_video.file_path}: Selected EIT candidate by {recording_time_source}. '
                    f'[recording_start_time: {recording_start_time}, recording_end_time: {recording_end_time}, '
                    f'overlap_seconds: {best_overlap_seconds:.1f}]'
                )
                assert best_candidate is not None
                return best_candidate

            logging.warning(
                f'{self.recorded_video.file_path}: No EIT candidate overlaps with the recording time range. '
                f'[source: {recording_time_source}, recording_start_time: {recording_start_time}, '
                f'recording_end_time: {recording_end_time}]'
            )

        # TOT を取得できなかった場合や、時刻の矛盾で全候補が落ちる場合は 20% 位置に最も近い present を優先する
        ## 20% 位置は通常の録画開始マージンを十分抜けた本編側で、従来コメント上も期待されていた基準位置
        effective_size = min(self.end_ts_offset, self.recorded_video.file_size)
        preferred_offset = ClosestMultiple(int(effective_size * 0.2), ts.PACKET_SIZE) if effective_size > 0 else 0

        def ScoreByProbePosition(candidate: _EITProgramCandidate) -> tuple[int, int, int]:
            offset_distance = abs(candidate.seek_offset - preferred_offset)
            is_present = int(candidate.section_number == 0)
            return (
                -offset_distance,
                is_present,
                candidate.completeness_score,
            )

        return max(candidates, key=ScoreByProbePosition)


    def __selectServiceIdByPidFrequency(
        self,
        service_id_order: list[int],
        service_pmt_pid_map: dict[int, int],
    ) -> int | None:
        """
        PAT と PMT から得られる PID 情報と TS 内の PID 出現頻度を突き合わせて、
        映像・音声 PID が実在する service_id を推定する

        Args:
            service_id_order (list[int]): PAT に登場した順序で並んだ service_id のリスト
            service_pmt_pid_map (dict[int, int]): service_id と PMT PID の対応表

        Returns:
            int | None: 推定された service_id（推定できない場合は None）
        """

        # MPEG-TS 以外では実データを確認できないため推定しない
        if self.recorded_video.container_format != 'MPEG-TS':
            return None

        # PMT から映像・音声 PID を取得
        ## ariblib の ProgramMapSection は _pids クラス属性がデフォルトで定義されていないため、
        ## 動的に追加してから sections() メソッドを使用する
        service_pid_map: dict[int, dict[str, set[int]]] = {}

        # ファイルの 20% 位置にシークしてから PMT を解析する
        ## Mirakurun/mirakc では録画開始直後はサービス分離が完了しておらず、古い PMT 情報が含まれている場合がある
        ## ファイルの 20% 位置であれば、サービス分離が完了した後の正しい PMT を取得できる可能性が高い
        ## ariblib の sections() メソッドは内部キャッシュを持っておりシーク位置を尊重しないため、
        ## 新しいファイルハンドルを開いて 20% 位置から読み込む必要がある
        effective_size = min(self.end_ts_offset, self.recorded_video.file_size)
        pmt_seek_offset = ClosestMultiple(int(effective_size * 0.2), ts.PACKET_SIZE)

        # ProgramMapSection._pids が存在しない場合は空リストで初期化
        if not hasattr(ProgramMapSection, '_pids'):
            ProgramMapSection._pids = []  # type: ignore[attr-defined]
        original_pmt_pids = ProgramMapSection._pids  # type: ignore[attr-defined]
        pmt_pids_to_use = list(service_pmt_pid_map.values())
        ProgramMapSection._pids = pmt_pids_to_use  # type: ignore[attr-defined]
        try:
            # 20% 位置から始まる新しいファイルハンドルを開いて PMT を解析
            ## サービス分離済みのファイルでは特定のサービスの PMT しか存在しないため、
            ## 一定回数 PMT を確認したら終了する
            with ariblib.tsopen(self.recorded_video.file_path, chunk=1000) as pmt_ts:
                pmt_ts.seek(pmt_seek_offset)
                pmt_check_count = 0
                max_pmt_checks = len(service_pmt_pid_map) * 3  # 各サービスにつき最大3回のチェック
                for pmt in pmt_ts.sections(ProgramMapSection):
                    pmt_check_count += 1
                    service_id = int(pmt.program_number)
                    if service_id not in service_pmt_pid_map:
                        continue
                    # 既にこのサービスの PMT を取得済みならスキップ
                    if service_id in service_pid_map:
                        # すべてのサービスを確認済みか、一定回数チェックしたら終了
                        if len(service_pid_map) == len(service_pmt_pid_map) or pmt_check_count >= max_pmt_checks:
                            break
                        continue
                    video_pids = {int(p) for p in pmt.video_pids()}
                    audio_pids = {int(p) for p in pmt.audio_pids()}
                    if len(video_pids) == 0 and len(audio_pids) == 0:
                        continue
                    service_pid_map[service_id] = {
                        'video_pids': video_pids,
                        'audio_pids': audio_pids,
                    }
                    # すべてのサービスを確認済みか、一定回数チェックしたら終了
                    if len(service_pid_map) == len(service_pmt_pid_map) or pmt_check_count >= max_pmt_checks:
                        break
        finally:
            ProgramMapSection._pids = original_pmt_pids  # type: ignore[attr-defined]

        if len(service_pid_map) == 0:
            return None

        # TS 内の PID 出現頻度を取得
        try:
            file_path = Path(self.recorded_video.file_path)
            effective_size = min(self.end_ts_offset, self.recorded_video.file_size)
            if effective_size < ts.PACKET_SIZE * 100:
                return None
            sample_offset = ClosestMultiple(int(effective_size * 0.2), ts.PACKET_SIZE)
            if sample_offset > effective_size - ts.PACKET_SIZE:
                sample_offset = max(effective_size - ts.PACKET_SIZE, 0)
            sample_size = ClosestMultiple(6 * 1024 * 1024, ts.PACKET_SIZE)
            sample_size = min(sample_size, effective_size - sample_offset)
            if sample_size < ts.PACKET_SIZE * 100:
                return None
            with file_path.open('rb') as f:
                f.seek(sample_offset)
                sample_data = f.read(sample_size)
        except Exception as ex:
            logging.warning(f'{self.recorded_video.file_path}: Failed to read TS sample for PID analysis:', exc_info=ex)
            return None

        pid_counts: dict[int, int] = {}
        offset = 0
        while offset + ts.PACKET_SIZE <= len(sample_data):
            if sample_data[offset] != ts.SYNC_BYTE[0]:
                offset += 1
                continue
            packet = sample_data[offset:offset + ts.PACKET_SIZE]
            packet_pid = pid(packet)
            pid_counts[packet_pid] = pid_counts.get(packet_pid, 0) + 1
            offset += ts.PACKET_SIZE

        if len(pid_counts) == 0:
            return None

        # 映像 PID と音声 PID の出現回数を評価して service_id を選定
        best_service_id: int | None = None
        best_score = -1
        best_video_count = -1
        best_audio_count = -1
        for service_id in service_id_order:
            if service_id not in service_pid_map:
                continue
            video_pids = service_pid_map[service_id]['video_pids']
            audio_pids = service_pid_map[service_id]['audio_pids']
            video_count = sum(pid_counts.get(p, 0) for p in video_pids)
            audio_count = sum(pid_counts.get(p, 0) for p in audio_pids)
            # 映像を優先してスコア化する
            score = video_count * 2 + audio_count
            if score > best_score:
                best_score = score
                best_video_count = video_count
                best_audio_count = audio_count
                best_service_id = service_id
            elif score == best_score and best_service_id is not None:
                # スコアが同じ場合は映像 PID が多い方を優先する
                if video_count > best_video_count:
                    best_video_count = video_count
                    best_audio_count = audio_count
                    best_service_id = service_id
                elif video_count == best_video_count and audio_count > best_audio_count:
                    best_audio_count = audio_count
                    best_service_id = service_id

        if best_service_id is not None and best_score > 0:
            logging.debug(
                f'{self.recorded_video.file_path}: Selected service_id {best_service_id} by PID frequency '
                f'(score: {best_score}, video: {best_video_count}, audio: {best_audio_count}).'
            )
            return best_service_id

        return None


    @staticmethod
    def readPSIData(reader: BufferedReader, target_pids: list[int], callback: Callable[[float, int, bytes], bool]) -> bool:
        """
        書庫から PSI/SI セクションを取り出す

        Args:
            reader (BufferedReader): 書庫データ
            target_pids (list[int]): 取り出すセクションの PID のリスト
            callback (Callable[[float, int, bytes], bool]): セクションを1つ取り出すごとに呼び出される関数

        Returns:
            bool: フォーマットエラーか callback から False が返ったとき False を返す
        """

        def GetUint16(buf: bytes, pos: int):
            return buf[pos] | buf[pos + 1] << 8

        def GetUint32(buf: bytes, pos: int):
            return GetUint16(buf, pos) | GetUint16(buf, pos + 2) << 16

        last_pids: list[int] = []
        last_dict: list[int | bytes | None] = []
        init_time = -1

        while True:
            buf = reader.read(32)
            if len(buf) != 32 or buf[0:8] != b'Pssc\x0d\x0a\x9a\x0a':
                # 完了
                break

            time_list_len = GetUint16(buf, 10)
            dictionary_len = GetUint16(buf, 12)
            dictionary_window_len = GetUint16(buf, 14)
            dictionary_data_size = GetUint32(buf, 16)
            dictionary_buff_size = GetUint32(buf, 20)
            code_list_len = GetUint32(buf, 24)
            if (dictionary_window_len < dictionary_len or
                dictionary_buff_size < dictionary_data_size or
                dictionary_window_len > 65536 - 4096):
                return False

            time_buf = reader.read(time_list_len * 4 + dictionary_len * 2)
            if len(time_buf) != time_list_len * 4 + dictionary_len * 2:
                return False

            pos = time_list_len * 4
            remain = dictionary_data_size
            pids: list[int] = []
            dict: list[int | bytes | None] = []
            for _ in range(dictionary_len):
                code_or_size = GetUint16(time_buf, pos) - 4096
                if code_or_size >= 0:
                    # 前回辞書 ID の参照
                    if code_or_size >= len(last_pids) or last_pids[code_or_size] < 0:
                        return False
                    pids.append(last_pids[code_or_size])
                    dict.append(last_dict[code_or_size])
                    last_pids[code_or_size] = -1
                else:
                    # セクションサイズ
                    remain -= 2
                    buf = reader.read(2)
                    if len(buf) != 2 or remain < 0:
                        return False
                    pids.append(GetUint16(buf, 0) % 0x2000)
                    # このあとセクションデータに置き換える
                    dict.append(code_or_size)
                pos += 2

            for i in range(dictionary_len):
                if type(dict[i]) is int:
                    # 新規なのでセクションデータを読む
                    size = cast(int, dict[i]) + 4097
                    remain -= size
                    buf = reader.read(size)
                    if len(buf) != size or remain < 0:
                        return False
                    # 対象 PID 以外のセクションデータは無視
                    dict[i] = buf if pids[i] in target_pids else None

            for i in range(dictionary_window_len - dictionary_len):
                if i >= len(last_pids):
                    return False
                # 前回辞書のうち未参照のものを引き継ぐ
                if last_pids[i] >= 0:
                    pids.append(last_pids[i])
                    dict.append(last_dict[i])
            last_pids = pids
            last_dict = dict
            # 残りは読み飛ばす
            remain += dictionary_data_size % 2
            if remain > 0 and len(reader.read(remain)) != remain:
                return False

            curr_time = -1
            for time_list_pos in range(0, time_list_len * 4, 4):
                abs_time = GetUint32(time_buf, time_list_pos)
                if abs_time == 0xffffffff:
                    curr_time = -1
                elif abs_time >= 0x80000000:
                    curr_time = abs_time % 0x40000000
                    if init_time < 0:
                        init_time = curr_time
                else:
                    if curr_time >= 0:
                        curr_time += GetUint16(time_buf, time_list_pos)
                    n = GetUint16(time_buf, time_list_pos + 2) + 1
                    buf = reader.read(n * 2)
                    if len(buf) != n * 2:
                        return False
                    time_sec = (curr_time + 0x40000000 - init_time) % 0x40000000 / 11250
                    for i in range(n):
                        code = GetUint16(buf, i * 2) - 4096
                        if code < 0 or code >= len(pids):
                            return False
                        if dict[code] is not None and not callback(time_sec, pids[code], cast(bytes, dict[code])):
                            return False

            trailer_size = 4 - (dictionary_len * 2 + (dictionary_data_size + 1) // 2 * 2 + code_list_len * 2) % 4
            buf = reader.read(trailer_size)
            if len(buf) != trailer_size:
                return False

        return True
