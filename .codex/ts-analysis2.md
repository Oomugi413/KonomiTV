# TS 監視・エンコード検証メモ

作成日時: 2026-06-28

## 結論

今回の事象は、ffprobe や TS 解析関数そのものが MPEG-2 の録画中 TS を認識できないことが原因ではない。

録画中 raw TS は、実際には手動 ffprobe で解析できていた。13:48:45 時点で 470,499,328 bytes / duration 236.189s、13:52:00 時点で 860,143,616 bytes / duration 431.584s として取得できていたため、少なくともこの録画ファイルでは「録画中 MPEG-2 TS だから ffprobe できない」という説明は成り立たない。

KonomiTV 側の原因は、`RecordedScanTask.__handleFileChange()` が `_recording_files[file_path].file_size` を現在サイズに更新してから `processRecordedFile()` を呼び、`processRecordedFile()` 側がその更新済みサイズを「前回サイズ」として比較していることにある。録画中 raw TS ではこの比較が `file_size == last_size` になりやすく、`mtime_continuous_start_at is None` のため `File is not recording. ignored.` で ffprobe 前に return していた。

一方、HEVC エンコード出力は完全に別の監視関数を通っているわけではない。0 bytes の追加イベントで `_recording_files` に入った後、tsreplace による連続書き込み中に `processRecordedFile()` 内の再 stat がハンドラ側 stat より新しいサイズを拾い、`file_size != last_size` になったため、早期 return を抜けて ffprobe まで進んでいた。つまり「別経路」に見えた差は、KonomiTV の同じ監視ロジック内で発生するサイズ観測タイミングの差で説明できる。

## 予約検証の結果

最初に作成した検証予約は、録画開始処理自体に失敗して録画ファイルが生成されなかった。

- 13:22 台の手動検証予約は EDCB 側で `録画開始処理に失敗しました` となり、録画ファイルパスは空だった。
- 13:40 の NHK 総合 1・東京の実番組予約も同じく `録画開始処理に失敗しました` で、録画ファイルは作成されなかった。
- このため、これらの予約では KonomiTV の録画ファイル監視・メタデータ解析の検証対象となるファイルは存在しなかった。

EDCB ソース上も、これは KonomiTV の監視以前の失敗として説明できる。

- `TunerBankCtrl.cpp` では `RecStart(r, now)` が false の場合に `CHECK_ERR_RECSTART` になる。
- `ReserveManager.cpp` では `CHECK_ERR_RECSTART` / `CHECK_ERR_CTRL` が `REC_END_STATUS_ERR_RECSTART` に変換される。
- `EpgDataCap_BonDlg.cpp` の `CMD2_VIEW_APP_REC_START_CTRL` は `bonCtrl.StartSave(...)` が true のときだけ `CMD_SUCCESS` を返す。

したがって、予約開始失敗は EDCB 側で録画ファイル生成に到達していない問題であり、今回の raw TS / HEVC TS の監視差とは別件。

## 現在録画ファイルで確認した事実

対象:

`/mnt/recording/20260628_第７４回　ＮＨＫ杯テレビ囲碁トーナメント　１回戦第１３局　富士田八段×平田八段[字].ts`

この録画は EDCB 上では 13:44:49 頃から 14:00:02 頃までの一部録画として生成された。KonomiTV ログでは、録画中に以下のような挙動だった。

```text
[2026/06/28 13:44:49.176] ... .ts: New recording or copying file detected.
[2026/06/28 13:44:49.177] ... .ts: File size is 0. ignored.
[2026/06/28 13:44:49.581] ... .ts: File is not recording. ignored.
[2026/06/28 13:44:49.984] ... .ts: File is not recording. ignored.
...
[2026/06/28 14:00:02.223] ... .ts: File is not recording. ignored.
```

一方、録画完了後は同じ raw TS が正常に解析されている。

```text
[2026/06/28 14:00:19.111] ... .ts: Recording or copying has just completed or has already completed.
[2026/06/28 14:00:19.335] ... .ts: FFprobe analysis completed.
[2026/06/28 14:00:19.360] ... .ts: MPEG-TS SDT/EIT analysis completed.
[2026/06/28 14:00:19.392] ... .ts: Saved metadata to DB. (status: Recorded)
```

このログは、録画中に ffprobe が失敗したのではなく、ffprobe へ到達する前に `File is not recording. ignored.` で捨てられていたことを示している。

## エンコード再実行で確認した事実

ユーザー操作で一度エンコード出力が削除され、14:10:40 に KonomiTV が旧 `.hevc.ts` レコード削除を検出した。その後、再実行分の Amatsukaze / NVEnc が動作した。

再実行分のエンコードログでは、NVEnc が 27,353 frames を encode し、tsreplace が以下の出力を生成していた。

```text
AMT [info] "/usr/bin/tsreplace" ... -o "/mnt/recording/EDCB/20260628_...富士田八段×平田八段[字].hevc.ts"
AMT [info] [出力ファイル]
AMT [info] 0: /mnt/recording/EDCB/20260628_...富士田八段×平田八段[字].hevc.ts
```

生成後のファイル:

```text
/mnt/recording/EDCB/20260628_第７４回　ＮＨＫ杯テレビ囲碁トーナメント　１回戦第１３局　富士田八段×平田八段[字].hevc.ts
size=348,964,848
ffprobe duration=913.266078
ffprobe bit_rate=3056851
```

KonomiTV は再実行分の `.hevc.ts` を次のように処理した。

```text
[2026/06/28 14:13:36.749] ... .hevc.ts: New recording or copying file detected.
[2026/06/28 14:13:36.750] ... .hevc.ts: File size is 0. ignored.
[2026/06/28 14:13:36.970] ... .hevc.ts: FFprobe analysis completed.
[2026/06/28 14:13:36.992] ... .hevc.ts: MPEG-TS SDT/EIT analysis completed.
[2026/06/28 14:13:37.006] ... .hevc.ts: This file is recording or copying. (duration 64.5s >= 60s)
[2026/06/28 14:13:37.013] ... .hevc.ts: Saved metadata to DB. (status: Recording)
[2026/06/28 14:13:55.356] ... .hevc.ts: Recording or copying has just completed or has already completed.
[2026/06/28 14:13:55.707] ... .hevc.ts: FFprobe analysis completed.
[2026/06/28 14:13:55.748] ... .hevc.ts: Updated metadata to DB. (status: Recorded)
```

この時点ではまだ `.hevc.ts` の全体が確定していないが、すでに duration 64.5s 以上として ffprobe できているため、KonomiTV は Recording として DB 保存できている。

## ソースコード上の原因

該当箇所は `server/app/metadata/RecordedScanTask.py`。

`__handleFileChange()` の既存録画中ファイル処理では、ファイルサイズが変化した場合に `mtime_continuous_start_at` を None に戻し、その後で状態を現在値に更新してから `processRecordedFile()` を呼んでいる。

```text
1354: # ファイルサイズが変化している場合は継続更新判定をリセット
1355: if file_size != last_size:
1356:     mtime_continuous_start_at = None
...
1371: # 状態を更新
1372: recording_info.last_modified = last_modified
1375: recording_info.file_size = file_size
1376: recording_info.mtime_continuous_start_at = mtime_continuous_start_at
1379: await self.processRecordedFile(file_path, original_file_path)
```

`processRecordedFile()` 側は、ファイルが `_recording_files` にある場合、`recording_info.file_size` を前回サイズとして使っている。

```text
600: is_recording = file_path in self._recording_files
607: # まだ DB に登録されていない＆ファイルサイズが前回から変化していない場合
608: recording_info = self._recording_files[file_path]
609: last_size = recording_info.file_size
610: mtime_continuous_start_at = recording_info.mtime_continuous_start_at
611: if file_size == last_size:
612:     # 最終更新日時の継続更新中でない場合はスキップ
613:     if mtime_continuous_start_at is None:
614:         logging.warning(f'{file_path}: File is not recording. ignored.')
615:         return
```

ここで `last_size` と呼ばれている値は、直前の `__handleFileChange()` で現在サイズに上書きされた後の値になっている。このため、`processRecordedFile()` 内で再取得した `file_size` が同じ値なら「前回から変化していない」と誤判定される。

raw TS ではこの再 stat の短い間にファイルサイズが変わらないタイミングが多く、`file_size == last_size` かつ `mtime_continuous_start_at is None` になり、ffprobe 前に return していた。

HEVC TS では tsreplace が短時間に連続して大きく書き込むため、`__handleFileChange()` で記録したサイズと `processRecordedFile()` 内で再 stat したサイズがズレやすい。その場合 `file_size == last_size` に入らず、ffprobe に進む。これが raw TS と HEVC TS の挙動差。

録画完了後に raw TS が解析される理由もソース上説明できる。`__checkRecordingCompletion()` では更新停止したファイルを `_recording_files` から削除してから `processRecordedFile()` を呼ぶ。

```text
1486: self._recording_files.pop(file_path, None)
1492: logging.info(f'{file_path}: Recording or copying has just completed or has already completed.')
1493: await self.processRecordedFile(file_path)
```

この経路では `file_path in self._recording_files` が false になるため、600-615 行目の録画中ファイル向け早期 return を通らない。そのため録画完了後の raw TS は正常に ffprobe / メタデータ保存まで進む。

## 対処方針

根本対策は、`processRecordedFile()` が比較に使う「前回観測値」と、監視ハンドラが取得した「現在値」を混同しないようにすること。

候補は次のいずれか。

1. `__handleFileChange()` で `_recording_files` を更新する前の `last_size` / `last_modified` / `mtime_continuous_start_at` をスナップショットとして `processRecordedFile()` に渡し、録画中判定はそのスナップショットと現在 stat の差で行う。
2. `processRecordedFile()` を呼ぶ前には `recording_info.file_size` を更新せず、`processRecordedFile()` の録画中判定が終わった後に状態を更新する。
3. 既存構造を維持する場合でも、`file_size != last_size` を検出した直後のイベントでは `mtime_continuous_start_at is None` を理由に `File is not recording. ignored.` へ落とさず、少なくとも ffprobe に進める条件を明示する。

設計としては 1 が一番安全。監視イベントで見た値と、解析処理開始時点の値を明示的に分けられるため、今回のような「更新済み現在値を前回値として扱う」バグを避けられる。

追加で入れるべき検証:

- 0 bytes で追加されたファイルが、その後サイズ増加した modified event を受けたとき、raw MPEG-2 TS でも ffprobe まで到達すること。
- modified event のハンドラ stat と `processRecordedFile()` 内 stat が同じサイズだった場合でも、録画中ファイルとして不当に捨てられないこと。
- HEVC TS のようなコピー・mux 中ファイルは、従来通り duration 60 秒以上で Recording として DB 保存され、更新停止後に Recorded へ更新されること。
- 録画完了後に `_recording_files` から pop して再解析される既存経路が壊れないこと。

## 作業中の注意点

この検証では `systemctl restart edcb` は実行していない。

予約検証で作成しようとした録画ファイルは、EDCB の録画開始処理失敗により生成されなかったため削除対象は存在しない。後半で使用した囲碁トーナメントの raw TS / HEVC TS は、ユーザーが「今録画しているファイル」として指定した実録画・再エンコード結果なので、こちらでは削除していない。
