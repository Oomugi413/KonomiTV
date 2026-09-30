# TSA1 実装修正メモ

作成日時: 2026-06-28

## 結論

`ts-analysis2.md` の対処方針 1 に従い、録画中ファイルのサイズ比較で使う「前回観測値」を `processRecordedFile()` に明示的に渡すよう修正した。

これにより、ファイル変更ハンドラが `_recording_files` の状態を現在値に更新した後でも、`processRecordedFile()` は更新前のサイズ・mtime 状態を基準に録画中判定できる。

## 修正前の問題

修正前は、既に `_recording_files` に入っている録画中ファイルに対して、次の順序で処理していた。

1. `__handleFileChange()` がファイルを stat する。
2. `file_size != last_size` なら `mtime_continuous_start_at = None` にする。
3. `_recording_files[file_path].file_size` を現在サイズに更新する。
4. `processRecordedFile()` を呼ぶ。
5. `processRecordedFile()` が `_recording_files[file_path].file_size` を `last_size` として読み直す。

この結果、`processRecordedFile()` 側の `last_size` は「前回サイズ」ではなく、直前に更新された「現在サイズ」になっていた。

そのため、録画中 raw TS のように、ハンドラ側 stat と `processRecordedFile()` 内 stat の短い間でサイズが増えなかった場合、`file_size == last_size` と判定される。さらにサイズ変化時に `mtime_continuous_start_at` が None に戻っているため、`File is not recording. ignored.` で ffprobe 前に return していた。

## 修正内容

`FileRecordingInfoSnapshot` を追加した。

保持する値:

- `last_modified`
- `file_size`
- `mtime_continuous_start_at`

`__handleFileChange()` では、既に録画中とマークされているファイルについて、`_recording_files` を更新する前にこのスナップショットを作る。

```text
recording_info_snapshot = FileRecordingInfoSnapshot(
    last_modified = recording_info.last_modified,
    file_size = last_size,
    mtime_continuous_start_at = mtime_continuous_start_at,
)
```

その後、従来通り `_recording_files` の状態は現在値へ更新する。

`processRecordedFile()` には `recording_info_snapshot` 引数を追加し、スナップショットが渡された場合はそれを比較対象にする。

```text
recording_info_for_comparison = recording_info_snapshot
if recording_info_for_comparison is None:
    recording_info_for_comparison = FileRecordingInfoSnapshot(...)
last_size = recording_info_for_comparison.file_size
mtime_continuous_start_at = recording_info_for_comparison.mtime_continuous_start_at
```

これで、ファイル変更イベント経由では「更新前の観測値」と `processRecordedFile()` 内の現在 stat を比較できる。

## 期待される挙動

録画中 raw TS で、前回イベントから今回イベントまでにファイルサイズが増えている場合、`processRecordedFile()` は更新前スナップショットの `file_size` と現在 stat の `file_size` を比較する。

そのため、`__handleFileChange()` が先に `_recording_files` を現在サイズへ更新していても、`processRecordedFile()` 内で誤って `file_size == last_size` と判定される可能性が下がる。

具体的には、今回問題になっていた以下の早期 return を避けやすくなる。

```text
File is not recording. ignored.
```

HEVC エンコード出力のようなコピー・mux 中ファイルも、従来と同じ `processRecordedFile()` を通る。スナップショットが渡されない呼び出しでは、従来通り `_recording_files` の現在状態を比較対象にするため、一括スキャン・録画完了チェック・既知ハッシュ衝突再解析の呼び出しは影響を受けにくい。

## 変更しなかった点

`__checkRecordingCompletion()` の完了判定は変更していない。

録画・コピー完了時は従来通り `_recording_files` から対象ファイルを `pop()` してから `processRecordedFile()` を呼ぶ。この経路では `file_path in self._recording_files` が false になり、録画中ファイル向けの早期 return を通らない。

`MINIMUM_RECORDING_SECONDS` や `CONTINUOUS_UPDATE_THRESHOLD_SECONDS` などの閾値も変更していない。

## 検証

`server/` で `poetry run task lint` を実行し、Ruff と Pyright のチェックを通した。

結果:

```text
All checks passed!
0 errors, 6 warnings, 0 informations
```

warning 6 件は今回変更していない既存箇所の非推奨警告。

## 反映について

KonomiTV の再起動は実施していない。

実行中サーバーがリロードモードでなければ、この修正を実行中プロセスへ反映するにはユーザー側で KonomiTV サーバーを再起動する必要がある。
