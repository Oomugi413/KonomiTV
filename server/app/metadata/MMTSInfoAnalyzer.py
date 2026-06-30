from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from app import logging, schemas
from app.constants import JST
from app.utils import NormalizeToJSTDatetime
from app.utils.TSInformation import TSInformation


_SatelliteChannelType = Literal['BS', 'CS', 'CATV', 'SKY', 'BS4K']
_MMTSMediaType = Literal['video', 'audio', 'unknown']
_AudioChannel = Literal['Monaural', 'Stereo', '5.1ch']


@dataclass(slots=True)
class _MMTSTable:
    """
    MMT-SI のテーブルデータ
    """

    table_id: int
    data: bytes


@dataclass(slots=True)
class _MMTSService:
    """
    MMT-SI から復元したサービス情報
    """

    network_id: int
    service_id: int
    transport_stream_id: int | None
    name: str


@dataclass(slots=True)
class _MMTSEvent:
    """
    MH-EIT から復元した番組情報
    """

    network_id: int
    service_id: int
    transport_stream_id: int | None
    event_id: int
    section_number: int
    title: str
    description: str
    detail: dict[str, str]
    start_time: datetime
    duration: float
    is_free: bool
    primary_audio_type: str | None
    primary_audio_language: str | None
    secondary_audio_type: str | None
    secondary_audio_language: str | None


@dataclass(slots=True)
class _MMTSMediaInfo:
    """
    MPT と MH-EIT から推定した録画ファイルのメディア情報
    """

    duration: float
    video_resolution_width: int
    video_resolution_height: int
    video_frame_rate: float
    primary_audio_channel: _AudioChannel
    primary_audio_sampling_rate: int
    secondary_audio_channel: _AudioChannel | None
    secondary_audio_sampling_rate: int | None


class MMTSInfoAnalyzer:
    """
    BS4K/BS8K の MMT/TLV 録画ファイルから録画メタデータを解析するクラス
    """

    # TLV / MMT-SI はファイル先頭と末尾の短い範囲に十分繰り返し出現するため、
    # 大容量録画の全体走査を避ける目的で解析範囲を限定する。
    READ_WINDOW_SIZE = 64 * 1024 * 1024

    # TLV の packet_type。BS4K/BS8K の MMT は Compressed IP Packet として運ばれる。
    TLV_SYNC_BYTE = 0x7F
    TLV_PACKET_TYPE_COMPRESSED_IP = 0x03

    # MMTP payload_type。
    MMTP_PAYLOAD_TYPE_MPU = 0x00
    MMTP_PAYLOAD_TYPE_CONTROL_MESSAGE = 0x02

    # MMT-SI message_id / table_id。
    MESSAGE_ID_PA = 0x0000
    MESSAGE_ID_M2_SECTION = 0x8000
    TABLE_ID_MPT = 0x20
    TABLE_ID_PLT = 0x80
    TABLE_ID_MH_EIT_PF = 0x8B
    TABLE_ID_MH_EIT_SCHEDULE = 0x8C
    TABLE_ID_MH_SDT = 0x9F

    # MH descriptor tag。
    DESCRIPTOR_VIDEO_COMPONENT = 0x8010
    DESCRIPTOR_AUDIO_COMPONENT = 0x8014
    DESCRIPTOR_SERVICE = 0x8019
    DESCRIPTOR_SHORT_EVENT = 0xF001
    DESCRIPTOR_EXTENDED_EVENT = 0xF002

    def __init__(self, file_path: Path, selected_service_id: int | None = None) -> None:
        """
        MMT/TLV 録画ファイルの解析器を初期化する

        Args:
            file_path (Path): 解析対象の MMT/TLV 録画ファイルパス
            selected_service_id (int | None): 指定するサービスID（複数チャンネル選択用）
        """

        # 解析対象ファイルのパス。probe / table 抽出 / メディア情報推定の全メソッドで参照する。
        # Path は呼び出し元で存在確認済みであることを前提にする。
        self.file_path = file_path

        # 複数サービスを含む MMT/TLV でユーザーが指定したサービス ID。
        # 指定されている場合、MH-EIT / MH-SDT の選択時に最優先で使用する。
        self.selected_service_id = selected_service_id

    @classmethod
    def probe(cls, file_path: Path) -> bool:
        """
        指定ファイルが MMT/TLV として解析可能かを判定する

        Args:
            file_path (Path): 判定対象のファイルパス

        Returns:
            bool: MMT/TLV として解析できる可能性が高い場合 True
        """

        try:
            with file_path.open('rb') as file:
                data = file.read(4 * 1024 * 1024)
        except Exception as ex:
            logging.warning(f'{file_path}: Failed to read data for MMT/TLV probe:', exc_info=ex)
            return False

        # 少なくとも 1 個の TLV 0x03 + MMTP control message が取れれば MMT/TLV とみなす。
        for payload in cls.__iterTLVCompressedIPPayloads(data):
            mmtp_packet = cls.__parseMMTPPacket(payload)
            if mmtp_packet is None:
                continue
            payload_type, _, _, _ = mmtp_packet
            if payload_type == cls.MMTP_PAYLOAD_TYPE_CONTROL_MESSAGE:
                return True
        return False

    def analyze(self, file_hash: str, file_size: int, file_created_at: datetime, file_modified_at: datetime) -> schemas.RecordedProgram | None:
        """
        MMT/TLV 録画ファイルから録画番組メタデータを解析する

        Args:
            file_hash (str): 録画ファイルのハッシュ値
            file_size (int): 録画ファイルサイズ
            file_created_at (datetime): 録画ファイル作成日時
            file_modified_at (datetime): 録画ファイル更新日時

        Returns:
            schemas.RecordedProgram | None: 録画番組情報、取得できなかった場合は None
        """

        tables = self.__collectTables()
        if len(tables) == 0:
            logging.warning(f'{self.file_path}: MMT-SI tables were not found.')
            return None

        service = self.__selectService(tables)
        if service is None:
            logging.warning(f'{self.file_path}: MMT/TLV service information was not found.')
            return None

        events = self.__collectEvents(tables, service)
        if len(events) == 0:
            logging.warning(f'{self.file_path}: MMT/TLV event information was not found.')
            return None

        event = self.__selectBestEvent(events, file_modified_at)
        media_info = self.__analyzeMediaInfo(tables, event.duration)
        channel = self.__buildChannel(service)

        # MMT/TLV 本体は FFprobe で扱えないため、MPT と MH-EIT から KonomiTV が必要とする最小メディア情報を復元する。
        recorded_video = schemas.RecordedVideo(
            status = 'Recorded',
            file_path = str(self.file_path),
            file_hash = file_hash,
            file_size = file_size,
            file_created_at = file_created_at,
            file_modified_at = file_modified_at,
            recording_start_time = event.start_time,
            recording_end_time = event.start_time + timedelta(seconds=media_info.duration),
            duration = media_info.duration,
            container_format = 'MMT/TLV',
            video_codec = 'H.265',
            video_codec_profile = 'Main 10',
            video_scan_type = 'Progressive',
            video_frame_rate = media_info.video_frame_rate,
            video_resolution_width = media_info.video_resolution_width,
            video_resolution_height = media_info.video_resolution_height,
            has_video_stream_changes = False,
            primary_audio_codec = 'AAC-LC',
            primary_audio_channel = media_info.primary_audio_channel,
            primary_audio_sampling_rate = media_info.primary_audio_sampling_rate,
            secondary_audio_codec = 'AAC-LC' if media_info.secondary_audio_channel is not None else None,
            secondary_audio_channel = media_info.secondary_audio_channel,
            secondary_audio_sampling_rate = media_info.secondary_audio_sampling_rate,
            # 必須フィールドのため作成日時・更新日時は適当に現在時刻を入れている
            # この値は参照されず、DB の値は別途自動生成される
            created_at = datetime.now(tz=JST),
            updated_at = datetime.now(tz=JST),
        )

        recorded_program = schemas.RecordedProgram(
            recorded_video = recorded_video,
            channel = channel,
            network_id = service.network_id,
            service_id = service.service_id,
            event_id = event.event_id,
            title = event.title,
            description = event.description,
            detail = event.detail,
            start_time = event.start_time,
            end_time = event.start_time + timedelta(seconds=event.duration),
            duration = event.duration,
            is_free = event.is_free,
            primary_audio_type = event.primary_audio_type,
            primary_audio_language = event.primary_audio_language,
            secondary_audio_type = event.secondary_audio_type,
            secondary_audio_language = event.secondary_audio_language,
            recording_start_margin = 0.0,
            recording_end_margin = max(media_info.duration - event.duration, 0.0),
            is_partially_recorded = False,
            # 必須フィールドのため作成日時・更新日時は適当に現在時刻を入れている
            # この値は参照されず、DB の値は別途自動生成される
            created_at = datetime.now(tz=JST),
            updated_at = datetime.now(tz=JST),
        )

        logging.info(
            f'{self.file_path}: MMT/TLV event selected. '
            f'[event_id: {event.event_id}, title: {event.title}, '
            f'start_time: {event.start_time}, duration: {event.duration}]'
        )
        return recorded_program

    def __collectTables(self) -> list[_MMTSTable]:
        """
        解析範囲から MMT-SI テーブルを収集する

        Returns:
            list[_MMTSTable]: 収集した MMT-SI テーブル
        """

        tables: list[_MMTSTable] = []
        for data in self.__readAnalysisWindows():
            for payload in self.__iterTLVCompressedIPPayloads(data):
                mmtp_packet = self.__parseMMTPPacket(payload)
                if mmtp_packet is None:
                    continue
                payload_type, _, packet_sequence_number, mmtp_payload = mmtp_packet
                if payload_type != self.MMTP_PAYLOAD_TYPE_CONTROL_MESSAGE:
                    continue
                tables.extend(self.__parseSignalingPayload(mmtp_payload, packet_sequence_number))
        return tables

    def __readAnalysisWindows(self) -> list[bytes]:
        """
        ファイル先頭と末尾の解析ウィンドウを読み込む

        Returns:
            list[bytes]: 解析対象データ
        """

        file_size = self.file_path.stat().st_size
        windows: list[bytes] = []
        with self.file_path.open('rb') as file:
            windows.append(file.read(min(self.READ_WINDOW_SIZE, file_size)))
            if file_size > self.READ_WINDOW_SIZE:
                file.seek(max(file_size - self.READ_WINDOW_SIZE, 0))
                windows.append(file.read(self.READ_WINDOW_SIZE))
        return windows

    @classmethod
    def __iterTLVCompressedIPPayloads(cls, data: bytes) -> Iterator[bytes]:
        """
        TLV から Compressed IP packet payload を列挙する

        Args:
            data (bytes): TLV データ

        Yields:
            bytes: Compressed IP の MMTP payload 部分
        """

        offset = 0
        while offset + 4 <= len(data):
            if data[offset] != cls.TLV_SYNC_BYTE:
                offset += 1
                continue

            packet_type = data[offset + 1]
            packet_length = int.from_bytes(data[offset + 2:offset + 4], 'big')
            packet_end = offset + 4 + packet_length
            if packet_length <= 0 or packet_length > 65535 or packet_end > len(data):
                offset += 1
                continue

            payload = data[offset + 4:packet_end]
            offset = packet_end
            if packet_type != cls.TLV_PACKET_TYPE_COMPRESSED_IP:
                continue

            # Compressed IP header は mmts.js と同じく context_id/sequence/header_type の 3 バイトから始まる。
            # header_type 0x60 だけ IPv6/UDP の省略ヘッダー分を飛ばす必要がある。
            if len(payload) < 3:
                continue
            header_type = payload[2]
            payload_offset = 3
            if header_type == 0x60:
                payload_offset += 38 + 4
            elif header_type not in (0x20, 0x21, 0x61):
                continue
            if payload_offset > len(payload):
                continue
            yield payload[payload_offset:]

    @classmethod
    def __parseMMTPPacket(cls, data: bytes) -> tuple[int, int, int, bytes] | None:
        """
        MMTP packet の最低限のヘッダーを解析する

        Args:
            data (bytes): MMTP packet データ

        Returns:
            tuple[int, int, int, bytes] | None: payload_type, packet_id, sequence_number, payload
        """

        if len(data) < 12:
            return None
        offset = 0
        first_byte = data[offset]
        offset += 1
        second_byte = data[offset]
        offset += 1
        payload_type = second_byte & 0x3F
        packet_id = int.from_bytes(data[offset:offset + 2], 'big')
        offset += 2
        offset += 4  # delivery_timestamp
        packet_sequence_number = int.from_bytes(data[offset:offset + 4], 'big')
        offset += 4

        if first_byte & 0x20:
            offset += 4
        if first_byte & 0x02:
            if offset + 4 > len(data):
                return None
            extension_header_length = int.from_bytes(data[offset + 2:offset + 4], 'big')
            offset += 4 + extension_header_length
        if offset > len(data):
            return None
        return (payload_type, packet_id, packet_sequence_number, data[offset:])

    def __parseSignalingPayload(self, payload: bytes, packet_sequence_number: int) -> list[_MMTSTable]:
        """
        MMTP control message payload から MMT-SI テーブルを抽出する

        Args:
            payload (bytes): MMTP control message payload
            packet_sequence_number (int): MMTP packet sequence number

        Returns:
            list[_MMTSTable]: 抽出したテーブル
        """

        # 現状の録画メタデータ用途では、非分割または aggregation された signaling message のみを扱う。
        # MH-EIT / MH-SDT は高頻度に繰り返し出るため、分割中の一部を落としても次の完全な message で復元できる。
        _ = packet_sequence_number
        if len(payload) < 2:
            return []
        flags = payload[0]
        fragmentation_indicator = flags >> 6
        aggregation_flag = bool(flags & 0x01)
        offset = 2
        tables: list[_MMTSTable] = []

        if aggregation_flag is True and fragmentation_indicator == 0:
            while offset + 2 <= len(payload):
                message_length = int.from_bytes(payload[offset:offset + 2], 'big')
                offset += 2
                if offset + message_length > len(payload):
                    break
                tables.extend(self.__parseSignalingMessage(payload[offset:offset + message_length]))
                offset += message_length
        elif aggregation_flag is False and fragmentation_indicator == 0:
            tables.extend(self.__parseSignalingMessage(payload[offset:]))

        return tables

    def __parseSignalingMessage(self, message: bytes) -> list[_MMTSTable]:
        """
        signaling message から MMT-SI テーブルを抽出する

        Args:
            message (bytes): signaling message データ

        Returns:
            list[_MMTSTable]: 抽出したテーブル
        """

        if len(message) < 5:
            return []
        message_id = int.from_bytes(message[0:2], 'big')
        tables: list[_MMTSTable] = []

        if message_id == self.MESSAGE_ID_M2_SECTION:
            table_length = int.from_bytes(message[3:5], 'big')
            table = message[5:5 + table_length]
            if len(table) > 0:
                tables.append(_MMTSTable(table_id=table[0], data=table))

        elif message_id == self.MESSAGE_ID_PA and len(message) >= 7:
            payload_length = int.from_bytes(message[3:7], 'big')
            payload = message[7:7 + payload_length]
            if len(payload) == 0:
                return tables
            table_count = payload[0]
            offset = 1 + table_count * 4
            while offset + 4 <= len(payload):
                table_id = payload[offset]
                table_length = int.from_bytes(payload[offset + 2:offset + 4], 'big')
                table_end = offset + 4 + table_length
                if table_end > len(payload):
                    break
                tables.append(_MMTSTable(table_id=table_id, data=payload[offset:table_end]))
                offset = table_end

        return tables

    def __selectService(self, tables: list[_MMTSTable]) -> _MMTSService | None:
        """
        MH-SDT / MH-EIT から対象サービスを選択する

        Args:
            tables (list[_MMTSTable]): MMT-SI テーブル

        Returns:
            _MMTSService | None: 選択されたサービス情報
        """

        services = self.__parseServices(tables)
        if self.selected_service_id is not None:
            for service in services:
                if service.service_id == self.selected_service_id:
                    return service

        # MH-SDT が取れない場合でも、MH-EIT のヘッダーから最低限の service_id / network_id は復元できる。
        if len(services) == 0:
            for table in tables:
                if table.table_id not in (self.TABLE_ID_MH_EIT_PF, self.TABLE_ID_MH_EIT_SCHEDULE):
                    continue
                if len(table.data) < 14:
                    continue
                network_id = int.from_bytes(table.data[10:12], 'big')
                service_id = int.from_bytes(table.data[3:5], 'big')
                transport_stream_id = int.from_bytes(table.data[8:10], 'big')
                return _MMTSService(
                    network_id = network_id,
                    service_id = service_id,
                    transport_stream_id = transport_stream_id,
                    name = f'BS4K {service_id}',
                )

        if len(services) == 0:
            return None
        return services[0]

    def __parseServices(self, tables: list[_MMTSTable]) -> list[_MMTSService]:
        """
        MH-SDT からサービス情報を解析する

        Args:
            tables (list[_MMTSTable]): MMT-SI テーブル

        Returns:
            list[_MMTSService]: サービス情報一覧
        """

        services: list[_MMTSService] = []
        seen_service_ids: set[int] = set()

        for table in tables:
            if table.table_id != self.TABLE_ID_MH_SDT or len(table.data) < 16:
                continue
            data = table.data
            section_length = ((data[1] & 0x0F) << 8) | data[2]
            section_end = min(3 + section_length - 4, len(data))
            transport_stream_id = int.from_bytes(data[3:5], 'big')
            network_id = int.from_bytes(data[8:10], 'big')
            offset = 11
            while offset + 5 <= section_end:
                service_id = int.from_bytes(data[offset:offset + 2], 'big')
                descriptors_loop_length = ((data[offset + 3] & 0x0F) << 8) | data[offset + 4]
                descriptors = data[offset + 5:offset + 5 + descriptors_loop_length]
                service_name = self.__parseServiceName(descriptors)
                if service_name is not None and service_id not in seen_service_ids:
                    services.append(_MMTSService(
                        network_id = network_id,
                        service_id = service_id,
                        transport_stream_id = transport_stream_id,
                        name = service_name,
                    ))
                    seen_service_ids.add(service_id)
                offset += 5 + descriptors_loop_length
        return services

    def __parseServiceName(self, descriptors: bytes) -> str | None:
        """
        MH service descriptor からサービス名を解析する

        Args:
            descriptors (bytes): descriptor loop

        Returns:
            str | None: サービス名
        """

        for tag, payload in self.__iterDescriptors(descriptors):
            if tag != self.DESCRIPTOR_SERVICE or len(payload) < 3:
                continue
            provider_name_length = payload[1]
            service_name_length_offset = 2 + provider_name_length
            if service_name_length_offset >= len(payload):
                continue
            service_name_length = payload[service_name_length_offset]
            service_name = payload[service_name_length_offset + 1:service_name_length_offset + 1 + service_name_length]
            if len(service_name) == 0:
                continue
            return TSInformation.formatString(self.__decodeText(service_name))
        return None

    def __collectEvents(self, tables: list[_MMTSTable], service: _MMTSService) -> list[_MMTSEvent]:
        """
        MH-EIT から番組候補を収集する

        Args:
            tables (list[_MMTSTable]): MMT-SI テーブル
            service (_MMTSService): 対象サービス情報

        Returns:
            list[_MMTSEvent]: 番組候補一覧
        """

        events: list[_MMTSEvent] = []
        seen: set[tuple[int, datetime]] = set()
        for table in tables:
            if table.table_id not in (self.TABLE_ID_MH_EIT_PF, self.TABLE_ID_MH_EIT_SCHEDULE):
                continue
            for event in self.__parseEITTable(table.data):
                if event.service_id != service.service_id:
                    continue
                if event.network_id != service.network_id:
                    continue
                key = (event.event_id, event.start_time)
                if key in seen:
                    continue
                seen.add(key)
                events.append(event)
        return events

    def __parseEITTable(self, data: bytes) -> list[_MMTSEvent]:
        """
        MH-EIT テーブルから番組情報を解析する

        Args:
            data (bytes): MH-EIT テーブル

        Returns:
            list[_MMTSEvent]: 番組情報一覧
        """

        if len(data) < 18:
            return []
        section_length = ((data[1] & 0x0F) << 8) | data[2]
        section_end = min(3 + section_length - 4, len(data))
        service_id = int.from_bytes(data[3:5], 'big')
        section_number = data[6]
        transport_stream_id = int.from_bytes(data[8:10], 'big')
        network_id = int.from_bytes(data[10:12], 'big')
        offset = 14
        events: list[_MMTSEvent] = []
        while offset + 12 <= section_end:
            event_id = int.from_bytes(data[offset:offset + 2], 'big')
            start_time = self.__parseMJDTime(data[offset + 2:offset + 7])
            duration = self.__parseBCDDuration(data[offset + 7:offset + 10])
            is_free = not bool(data[offset + 10] & 0x10)
            descriptors_loop_length = ((data[offset + 10] & 0x0F) << 8) | data[offset + 11]
            descriptor_start = offset + 12
            descriptor_end = min(descriptor_start + descriptors_loop_length, section_end)
            descriptors = data[descriptor_start:descriptor_end]
            offset = descriptor_end

            if start_time is None or duration <= 0:
                continue

            event = self.__buildEventFromDescriptors(
                network_id = network_id,
                service_id = service_id,
                transport_stream_id = transport_stream_id,
                event_id = event_id,
                section_number = section_number,
                start_time = start_time,
                duration = duration,
                is_free = is_free,
                descriptors = descriptors,
            )
            events.append(event)
        return events

    def __buildEventFromDescriptors(
        self,
        network_id: int,
        service_id: int,
        transport_stream_id: int,
        event_id: int,
        section_number: int,
        start_time: datetime,
        duration: float,
        is_free: bool,
        descriptors: bytes,
    ) -> _MMTSEvent:
        """
        descriptor loop から番組情報を組み立てる

        Args:
            network_id (int): network_id
            service_id (int): service_id
            transport_stream_id (int): transport_stream_id
            event_id (int): event_id
            section_number (int): section_number
            start_time (datetime): 番組開始時刻
            duration (float): 番組長
            is_free (bool): 無料番組かどうか
            descriptors (bytes): descriptor loop

        Returns:
            _MMTSEvent: 番組情報
        """

        title = TSInformation.formatString(self.file_path.stem)
        description = ''
        detail: dict[str, str] = {}
        primary_audio_type: str | None = None
        primary_audio_language: str | None = None
        secondary_audio_type: str | None = None
        secondary_audio_language: str | None = None

        for tag, payload in self.__iterDescriptors(descriptors):
            if tag == self.DESCRIPTOR_SHORT_EVENT:
                parsed_title, parsed_description = self.__parseShortEventDescriptor(payload)
                if parsed_title:
                    title = parsed_title
                if parsed_description:
                    description = parsed_description
            elif tag == self.DESCRIPTOR_EXTENDED_EVENT:
                detail.update(self.__parseExtendedEventDescriptor(payload))
            elif tag == self.DESCRIPTOR_AUDIO_COMPONENT:
                audio_info = self.__parseAudioComponentDescriptor(payload)
                if audio_info is None:
                    continue
                audio_type, audio_language, is_main = audio_info
                if is_main is True and primary_audio_type is None:
                    primary_audio_type = audio_type
                    primary_audio_language = audio_language
                elif is_main is False and secondary_audio_type is None:
                    secondary_audio_type = audio_type
                    secondary_audio_language = audio_language

        if description == '' and len(detail) > 0:
            description = next(iter(detail.values()))

        return _MMTSEvent(
            network_id = network_id,
            service_id = service_id,
            transport_stream_id = transport_stream_id,
            event_id = event_id,
            section_number = section_number,
            title = title,
            description = description,
            detail = detail,
            start_time = start_time,
            duration = duration,
            is_free = is_free,
            primary_audio_type = primary_audio_type,
            primary_audio_language = primary_audio_language,
            secondary_audio_type = secondary_audio_type,
            secondary_audio_language = secondary_audio_language,
        )

    def __selectBestEvent(self, events: list[_MMTSEvent], file_modified_at: datetime) -> _MMTSEvent:
        """
        録画ファイルに最も近い番組候補を選択する

        Args:
            events (list[_MMTSEvent]): 番組候補一覧
            file_modified_at (datetime): ファイル更新日時

        Returns:
            _MMTSEvent: 選択した番組情報
        """

        # present/following がある場合は present を優先する。
        present_events = [event for event in events if event.section_number == 0]
        if len(present_events) > 0:
            return present_events[0]

        # 長時間録画などで schedule しか取れない場合は、ファイル更新時刻から最も近い番組を選ぶ。
        return min(events, key=lambda event: abs((file_modified_at - event.start_time).total_seconds()))

    def __analyzeMediaInfo(self, tables: list[_MMTSTable], fallback_duration: float) -> _MMTSMediaInfo:
        """
        MPT からメディア情報を推定する

        Args:
            tables (list[_MMTSTable]): MMT-SI テーブル
            fallback_duration (float): MPT から時長を推定できない場合のフォールバック時長

        Returns:
            _MMTSMediaInfo: メディア情報
        """

        video_width = 3840
        video_height = 2160
        video_frame_rate = 59.94
        audio_channels: list[_AudioChannel] = []
        audio_sampling_rates: list[int] = []

        for table in tables:
            if table.table_id != self.TABLE_ID_MPT:
                continue
            for media_type, descriptor_payloads in self.__parseMPTAssets(table.data):
                if media_type == 'video':
                    for tag, payload in descriptor_payloads:
                        if tag != self.DESCRIPTOR_VIDEO_COMPONENT or len(payload) < 2:
                            continue
                        resolution_code = (payload[0] >> 4) & 0x0F
                        frame_rate_code = payload[1] & 0x1F
                        video_width, video_height = self.__resolveVideoResolution(resolution_code)
                        video_frame_rate = self.__resolveVideoFrameRate(frame_rate_code)
                elif media_type == 'audio':
                    for tag, payload in descriptor_payloads:
                        if tag != self.DESCRIPTOR_AUDIO_COMPONENT:
                            continue
                        audio_info = self.__parseAudioComponentDescriptor(payload)
                        if audio_info is None:
                            continue
                        audio_type, _, _ = audio_info
                        audio_channels.append(self.__resolveAudioChannel(audio_type))
                        audio_sampling_rates.append(48000)

        primary_audio_channel = audio_channels[0] if len(audio_channels) > 0 else 'Stereo'
        primary_audio_sampling_rate = audio_sampling_rates[0] if len(audio_sampling_rates) > 0 else 48000
        secondary_audio_channel = audio_channels[1] if len(audio_channels) > 1 else None
        secondary_audio_sampling_rate = audio_sampling_rates[1] if len(audio_sampling_rates) > 1 else None

        return _MMTSMediaInfo(
            duration = fallback_duration,
            video_resolution_width = video_width,
            video_resolution_height = video_height,
            video_frame_rate = video_frame_rate,
            primary_audio_channel = primary_audio_channel,
            primary_audio_sampling_rate = primary_audio_sampling_rate,
            secondary_audio_channel = secondary_audio_channel,
            secondary_audio_sampling_rate = secondary_audio_sampling_rate,
        )

    def __parseMPTAssets(self, data: bytes) -> list[tuple[_MMTSMediaType, list[tuple[int, bytes]]]]:
        """
        MPT から asset type と descriptor loop を解析する

        Args:
            data (bytes): MPT table

        Returns:
            list[tuple[_MMTSMediaType, list[tuple[int, bytes]]]]: media_type と descriptor 一覧
        """

        assets: list[tuple[_MMTSMediaType, list[tuple[int, bytes]]]] = []
        if len(data) < 8 or data[0] != self.TABLE_ID_MPT:
            return assets
        table_length = int.from_bytes(data[2:4], 'big')
        payload = data[4:4 + table_length]
        if len(payload) < 2:
            return assets

        offset = 1
        package_id_length = payload[offset]
        offset += 1 + package_id_length
        if offset + 2 > len(payload):
            return assets
        descriptors_length = int.from_bytes(payload[offset:offset + 2], 'big')
        offset += 2 + descriptors_length
        if offset >= len(payload):
            return assets
        asset_count = payload[offset]
        offset += 1

        for _ in range(asset_count):
            if offset + 6 > len(payload):
                break
            offset += 5
            asset_id_length = payload[offset]
            offset += 1 + asset_id_length
            if offset + 6 > len(payload):
                break
            asset_type = payload[offset:offset + 4].decode('ascii', errors='ignore')
            offset += 4
            offset += 1
            location_count = payload[offset]
            offset += 1
            for _ in range(location_count):
                offset = self.__skipLocation(payload, offset)
            if offset + 2 > len(payload):
                break
            descriptors_length = int.from_bytes(payload[offset:offset + 2], 'big')
            offset += 2
            descriptors = payload[offset:offset + descriptors_length]
            offset += descriptors_length

            if asset_type == 'hev1':
                media_type = 'video'
            elif asset_type == 'mp4a':
                media_type = 'audio'
            else:
                media_type = 'unknown'
            assets.append((media_type, list(self.__iterDescriptors(descriptors))))
        return assets

    def __skipLocation(self, data: bytes, offset: int) -> int:
        """
        MMT location 情報をスキップする

        Args:
            data (bytes): MPT payload
            offset (int): location 開始位置

        Returns:
            int: location 終端位置
        """

        if offset >= len(data):
            return offset
        location_type = data[offset]
        offset += 1
        if location_type == 0x00:
            return min(offset + 2, len(data))
        if location_type == 0x01:
            return min(offset + 12, len(data))
        if location_type == 0x02:
            return min(offset + 36, len(data))
        if location_type == 0x03:
            return min(offset + 6, len(data))
        if location_type == 0x04:
            return min(offset + 36, len(data))
        if location_type == 0x05:
            if offset >= len(data):
                return offset
            url_length = data[offset]
            return min(offset + 1 + url_length, len(data))
        return len(data)

    def __buildChannel(self, service: _MMTSService) -> schemas.Channel:
        """
        MMT/TLV のサービス情報から Channel schema を構築する

        Args:
            service (_MMTSService): サービス情報

        Returns:
            schemas.Channel: チャンネル情報
        """

        network_type = TSInformation.getNetworkType(service.network_id)
        if network_type == 'BS':
            channel_type: _SatelliteChannelType = 'BS'
        elif network_type == 'CS':
            channel_type = 'CS'
        elif network_type == 'CATV':
            channel_type = 'CATV'
        elif network_type == 'SKY':
            channel_type = 'SKY'
        else:
            channel_type = 'BS4K'
        remocon_id = TSInformation.calculateRemoconID(channel_type, service.service_id)
        channel_number = f'{remocon_id:03d}'
        channel = schemas.Channel(
            id = f'NID{service.network_id}-SID{service.service_id:03d}',
            display_channel_id = channel_type.lower() + channel_number,
            network_id = service.network_id,
            service_id = service.service_id,
            transport_stream_id = service.transport_stream_id,
            remocon_id = remocon_id,
            channel_number = channel_number,
            type = channel_type,
            name = service.name,
        )
        channel.is_subchannel = TSInformation.calculateIsSubchannel(channel.type, channel.service_id)
        channel.is_radiochannel = False
        channel.is_watchable = False
        return channel

    def __parseShortEventDescriptor(self, payload: bytes) -> tuple[str | None, str | None]:
        """
        MH short event descriptor を解析する

        Args:
            payload (bytes): descriptor payload

        Returns:
            tuple[str | None, str | None]: 番組名, 番組概要
        """

        if len(payload) < 5:
            return (None, None)
        offset = 3
        event_name_length = payload[offset]
        offset += 1
        event_name = payload[offset:offset + event_name_length]
        offset += event_name_length
        if offset >= len(payload):
            return (TSInformation.formatString(self.__decodeText(event_name)), None)
        text_length = payload[offset]
        offset += 1
        text = payload[offset:offset + text_length]
        return (
            TSInformation.formatString(self.__decodeText(event_name)),
            TSInformation.formatString(self.__decodeText(text)).strip(),
        )

    def __parseExtendedEventDescriptor(self, payload: bytes) -> dict[str, str]:
        """
        MH extended event descriptor を解析する

        Args:
            payload (bytes): descriptor payload

        Returns:
            dict[str, str]: 見出しと本文
        """

        if len(payload) < 6:
            return {}
        detail: dict[str, str] = {}
        offset = 4
        items_length = int.from_bytes(payload[offset:offset + 2], 'big')
        offset += 2
        items_end = min(offset + items_length, len(payload))
        while offset + 2 <= items_end:
            item_description_length = payload[offset]
            offset += 1
            item_description = payload[offset:offset + item_description_length]
            offset += item_description_length
            if offset >= items_end:
                break
            item_length = payload[offset]
            offset += 1
            item = payload[offset:offset + item_length]
            offset += item_length
            head = TSInformation.formatString(self.__decodeText(item_description)).replace('◇', '').strip(' \r\n')
            text = TSInformation.formatString(self.__decodeText(item)).strip()
            if head == '':
                head = '番組内容'
            while head in detail:
                head += '\t'
            if text != '':
                detail[head] = text

        # item loop 以外の text_char も fallback として拾う。
        if offset < len(payload):
            text_length = int.from_bytes(payload[offset:offset + 2], 'big') if offset + 2 <= len(payload) else 0
            text = payload[offset + 2:offset + 2 + text_length]
            if len(text) > 0 and '番組内容' not in detail:
                detail['番組内容'] = TSInformation.formatString(self.__decodeText(text)).strip()
        return detail

    def __parseAudioComponentDescriptor(self, payload: bytes) -> tuple[str, str, bool] | None:
        """
        MH audio component descriptor を解析する

        Args:
            payload (bytes): descriptor payload

        Returns:
            tuple[str, str, bool] | None: 音声形式, 言語, 主音声かどうか
        """

        if len(payload) < 10:
            return None
        component_type = payload[1]
        flags = payload[6]
        is_main = bool((flags >> 6) & 0x01)
        language = TSInformation.getISO639LanguageCodeName(payload[7:10].decode('ascii', errors='ignore'))
        return (self.__resolveAudioType(component_type), language, is_main)

    def __iterDescriptors(self, descriptors: bytes) -> Iterator[tuple[int, bytes]]:
        """
        MMT-SI descriptor loop を列挙する

        Args:
            descriptors (bytes): descriptor loop

        Yields:
            tuple[int, bytes]: descriptor tag と payload
        """

        offset = 0
        while offset + 3 <= len(descriptors):
            tag = int.from_bytes(descriptors[offset:offset + 2], 'big')
            offset += 2
            length_bytes = 1
            if (0x4000 <= tag <= 0x6FFF) or tag >= 0xF000:
                length_bytes = 2
            elif 0x7000 <= tag <= 0x7FFF:
                length_bytes = 4
            if offset + length_bytes > len(descriptors):
                break
            if length_bytes == 1:
                length = descriptors[offset]
            elif length_bytes == 2:
                length = int.from_bytes(descriptors[offset:offset + 2], 'big')
            else:
                length = int.from_bytes(descriptors[offset:offset + 4], 'big')
            offset += length_bytes
            if offset + length > len(descriptors):
                break
            yield (tag, descriptors[offset:offset + length])
            offset += length

    def __parseMJDTime(self, data: bytes) -> datetime | None:
        """
        MJD + BCD の日時表現を datetime に変換する

        Args:
            data (bytes): 5 バイトの日時データ

        Returns:
            datetime | None: JST の datetime
        """

        if len(data) != 5 or data == b'\xff\xff\xff\xff\xff':
            return None
        mjd = int.from_bytes(data[0:2], 'big')
        y = int((mjd - 15078.2) / 365.25)
        m = int((mjd - 14956.1 - int(y * 365.25)) / 30.6001)
        day = int(mjd - 14956 - int(y * 365.25) - int(m * 30.6001))
        k = 1 if m in (14, 15) else 0
        year = 1900 + y + k
        month = m - 1 - k * 12
        hour = self.__decodeBCD(data[2])
        minute = self.__decodeBCD(data[3])
        second = self.__decodeBCD(data[4])
        try:
            return NormalizeToJSTDatetime(datetime(year, month, day, hour, minute, second, tzinfo=JST))
        except ValueError:
            return None

    def __parseBCDDuration(self, data: bytes) -> float:
        """
        BCD の HH:MM:SS を秒数に変換する

        Args:
            data (bytes): 3 バイトの duration

        Returns:
            float: 秒数
        """

        if len(data) != 3:
            return 0.0
        hours = self.__decodeBCD(data[0])
        minutes = self.__decodeBCD(data[1])
        seconds = self.__decodeBCD(data[2])
        return float(hours * 3600 + minutes * 60 + seconds)

    def __decodeBCD(self, value: int) -> int:
        """
        BCD 1 バイトを整数に変換する

        Args:
            value (int): BCD 値

        Returns:
            int: 整数
        """

        return ((value >> 4) * 10) + (value & 0x0F)

    def __resolveVideoResolution(self, resolution_code: int) -> tuple[int, int]:
        """
        video_component_descriptor の解像度コードを幅・高さに変換する

        Args:
            resolution_code (int): 解像度コード

        Returns:
            tuple[int, int]: 幅, 高さ
        """

        if resolution_code == 0x07:
            return (7680, 4320)
        if resolution_code == 0x06:
            return (3840, 2160)
        if resolution_code == 0x05:
            return (1920, 1080)
        return (3840, 2160)

    def __resolveVideoFrameRate(self, frame_rate_code: int) -> float:
        """
        video_component_descriptor のフレームレートコードを fps に変換する

        Args:
            frame_rate_code (int): フレームレートコード

        Returns:
            float: fps
        """

        if frame_rate_code == 0x08:
            return 59.94
        if frame_rate_code == 0x06:
            return 29.97
        return 59.94

    def __resolveAudioType(self, component_type: int) -> str:
        """
        audio_component_descriptor の component_type を表示文字列に変換する

        Args:
            component_type (int): component_type

        Returns:
            str: 音声形式
        """

        if component_type == 0x09:
            return '3/2+LFEモード(5.1ch)'
        if component_type in (0x01, 0x03):
            return '2/0モード(ステレオ)'
        if component_type == 0x02:
            return '1/0モード(モノ)'
        return '2/0モード(ステレオ)'

    def __resolveAudioChannel(self, audio_type: str) -> _AudioChannel:
        """
        音声形式の表示文字列を RecordedVideo のチャンネル表現に変換する

        Args:
            audio_type (str): 音声形式

        Returns:
            str: RecordedVideo 用の音声チャンネル
        """

        if '5.1' in audio_type:
            return '5.1ch'
        if 'モノ' in audio_type:
            return 'Monaural'
        return 'Stereo'

    def __decodeText(self, data: bytes) -> str:
        """
        MH descriptor 内の UTF-8 文字列をデコードする

        Args:
            data (bytes): 文字列データ

        Returns:
            str: デコード済み文字列
        """

        return data.decode('utf-8', errors='ignore')
