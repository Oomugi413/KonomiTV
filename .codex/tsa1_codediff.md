# TSA1 コード差分・復旧手順

作成日時: 2026-06-28

## 変更したファイル

今回変更した実装ファイルは 1 件。

| 用途 | パス |
| --- | --- |
| 元ファイル退避 | `server/app/metadata/RecordedScanTask.py.tsa1_original` |
| 新ファイル | `server/app/metadata/RecordedScanTask.py` |

ユーザー指定に従い、元ファイルはファイル名を変更して保持し、新ファイルは元と同じファイル名で作成している。

## 差分の概要

`server/app/metadata/RecordedScanTask.py` に以下を追加・変更した。

- `FileRecordingInfoSnapshot` を追加した。
- `processRecordedFile()` に `recording_info_snapshot` 引数を追加した。
- `__handleFileChange()` の既存録画中ファイル処理で、`_recording_files` を現在値へ更新する前の状態を `FileRecordingInfoSnapshot` として保存するようにした。
- `processRecordedFile()` の録画中判定では、スナップショットが渡された場合、その更新前状態を「前回観測値」として比較するようにした。

これにより、`__handleFileChange()` が `_recording_files[file_path].file_size` を現在値に更新した後でも、`processRecordedFile()` 側は更新前のサイズと現在 stat のサイズを比較できる。

## 復旧方法

元のコードへ戻す場合は、KonomiTV リポジトリ直下で以下を実行する。

```bash
cd ~/git/KonomiTV
sudo rm server/app/metadata/RecordedScanTask.py
sudo mv server/app/metadata/RecordedScanTask.py.tsa1_original server/app/metadata/RecordedScanTask.py
```

上記の `mv` は退避済みの元ファイルを元のファイル名へ戻す。退避ファイルは root 所有のまま保持されているため、通常は `sudo` が必要。

復旧後、実行中の KonomiTV に反映するには、KonomiTV サーバーがリロードモードでなければユーザー側でサーバー再起動が必要。

## 検証結果

`server/` ディレクトリで以下を実行した。

```bash
poetry run task lint
```

結果:

```text
All checks passed!
0 errors, 6 warnings, 0 informations
```

Pyright の warning 6 件は既存コードの FastAPI `on_event` / `asyncio.iscoroutinefunction` 非推奨警告で、今回変更した `RecordedScanTask.py` に対するエラーではない。

## 再起動について

KonomiTV の再起動は実施していない。

現在起動中の KonomiTV がリロードモードでなければ、今回の修正を実行中プロセスに反映するにはユーザー側で KonomiTV サーバーの再起動が必要。
