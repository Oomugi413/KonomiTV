# KonomiTV 録画中 TS 未認識の原因分析

## 結論

問題の主因は、`RecordedScanTask.__handleFileChange()` が録画中ファイルの状態を更新してから `processRecordedFile()` を呼んでいることにある。

`__handleFileChange()` は、既に `_recording_files` に入っているファイルでサイズ変化を検出すると、`mtime_continuous_start_at` を `None` に戻し、そのうえで `recording_info.file_size` を現在のファイルサイズへ更新する。その直後に `processRecordedFile()` を呼ぶ。

一方 `processRecordedFile()` は、`_recording_files[file_path].file_size` を「前回サイズ」として読んで録画中判定を行う。呼び出し直前に現在サイズで上書きされているため、通常は `file_size == last_size` になり、かつ `mtime_continuous_start_at is None` なので `File is not recording. ignored.` で解析前に戻る。

つまり、録画中ファイルが正しく伸びていても、KonomiTV 内部では「サイズ変化なし・継続 mtime 更新なし」と見えてしまう。

重要なのは、これは「サイズ変化検知の関数そのものが常に間違っている」という意味ではないこと。`__handleFileChange()` は実際にサイズ変化を検知できており、ログにも `File size changed.` が出ている。`.hevc.ts` が録画中として登録できたことも、サイズ変化検知が機能し得ることを示している。問題は、検知した結果を `_recording_files` に現在値として保存した直後に、`processRecordedFile()` がその保存済み値を「前回サイズ」として再利用している点にある。

このため、`__handleFileChange()` の stat と `processRecordedFile()` の再 stat の間にさらにサイズが変われば録画中として解析に進める。一方、その2回の stat で同じサイズが見えると、直前にサイズ変化を検知していても `File is not recording. ignored.` へ落ちる。したがって問題はサイズ変化検知関数の存在や能力ではなく、検知後の状態更新タイミングと後段の判定条件が衝突していること。

## ソースコード上の確認点

- `server/app/metadata/RecordedScanTask.py:1355` 付近
  - ファイルサイズが変化していると `mtime_continuous_start_at = None` にする。
- `server/app/metadata/RecordedScanTask.py:1375` 付近
  - `recording_info.file_size = file_size` で現在サイズへ更新する。
- `server/app/metadata/RecordedScanTask.py:1379` 付近
  - その後で `processRecordedFile()` を呼ぶ。
- `server/app/metadata/RecordedScanTask.py:611` 付近
  - `processRecordedFile()` は `file_size == last_size` のときだけ mtime 継続更新を確認する。
- `server/app/metadata/RecordedScanTask.py:613` 付近
  - `mtime_continuous_start_at is None` なら `File is not recording. ignored.` で戻る。
- `server/app/metadata/RecordedScanTask.py:629` 付近
  - ffprobe を使う `MetadataAnalyzer` はこの判定の後で起動される。

このため、ログに `File is not recording. ignored.` が出ているケースは、ffprobe の成否以前に `RecordedScanTask` 側の録画中判定で止まっている。

## MPEG-2 録画中 TS のログと経路

`log_mpeg2.txt` と `log_hevc.txt` 内の元録画 `.ts` では、次の流れになっている。

1. `New recording or copying file detected.`
2. `File size is 0. ignored.`
3. 以後、録画中に `File is not recording. ignored.` が繰り返される。
4. 30秒ごと程度に `File size changed.` が出ても、その直後に `File is not recording. ignored.` が出る。
5. 録画終了後にだけ `Recording or copying has just completed or has already completed.` から ffprobe / TS 解析へ進む。

これは、サイズ変化を検出したイベントで `__handleFileChange()` が現在サイズを `_recording_files` に保存し、その同じサイズを `processRecordedFile()` が前回サイズとして読んでしまっている挙動と一致する。

## `.hevc.ts` が録画中として認識された理由

`.hevc.ts` では次のログになっている。

```text
23:02:01.950 New recording or copying file detected.
23:02:01.950 File size is 0. ignored.
23:02:02.401 FFprobe analysis completed.
23:02:02.437 This file is recording or copying. (duration 76.2s >= 60s)
23:02:02.441 Saved metadata to DB. (status: Recording)
```

この差は、KonomiTV のソースコード上では `processRecordedFile()` の分岐で説明できる。`processRecordedFile()` が ffprobe へ進む条件は次のいずれか。

- `is_recording` が `False` で、`File is not recording. ignored.` の判定自体を通らない。
- `is_recording` が `True` でも、`processRecordedFile()` 内で再取得した `file_size` が `_recording_files[file_path].file_size` と異なり、`file_size == last_size` の内側に入らない。
- `is_recording` が `True` かつ `file_size == last_size` でも、`mtime_continuous_start_at` があり、継続時間が 60 秒以上になっている。

今回の `.hevc.ts` は `New recording...` の直後に `File size is 0. ignored.` が出ている。この初回イベントでは、`__handleFileChange()` の「まだ `_recording_files` にないファイル」分岐で `_recording_files` に登録され、`processRecordedFile()` は 0 バイトチェックで戻っている。

その次に ffprobe へ進むには、KonomiTV のソースコード上は次のいずれかしかない。

1. 2回目のイベント処理前に `_recording_files` から消えていた。
2. 2回目のイベントで `__handleFileChange()` が stat したサイズと、直後に `processRecordedFile()` が stat したサイズが異なっていた。
3. 2回目のイベント時点で `mtime_continuous_start_at` から 60 秒以上経っていた。

1 は、`__handleFileDeletion()` が `_recording_files.pop(file_path, None)` を無条件に実行するため、削除イベントを挟めばログなしで起こり得る。ただし、削除イベント後に再追加されたファイルでも、`__handleFileChange()` は再び現在サイズを `_recording_files` に保存してから `processRecordedFile()` を呼ぶ。直後の `processRecordedFile()` で ffprobe へ進むには、結局 2 または 3 が必要になる。

3 は、`New recording...` から `FFprobe analysis completed.` まで 0.451 秒しかないログとは通常合わない。初回登録時の `mtime_continuous_start_at` が現在付近なら 60 秒を超えないため、単独では説明しにくい。

したがって、ソースコードだけで最も整合する説明は 2。`__handleFileChange()` は一度 stat して `_recording_files[file_path].file_size` を現在サイズへ更新するが、`processRecordedFile()` はその中で再度 stat する。2回の stat の間にファイルサイズがさらに増えていれば、`processRecordedFile()` から見ると `file_size != last_size` になり、`File is not recording. ignored.` の早期 return を通らず ffprobe へ進む。

## 「別経路」の意味

ここでの「別経路」は、KonomiTV に HEVC 専用の別処理があるという意味ではない。`RecordedScanTask` には ffprobe 前の段階で MPEG-2 と HEVC を分ける処理はない。

KonomiTV のソースコード上の差は、同じ `processRecordedFile()` 内で次のどちらの分岐に入るかだけ。

- MPEG-2 録画中 TS:
  - `__handleFileChange()` が `_recording_files[file_path].file_size` を現在サイズへ更新する。
  - 直後の `processRecordedFile()` の stat でも同じサイズが見える。
  - `file_size == last_size` かつ `mtime_continuous_start_at is None` となり、`File is not recording. ignored.` で戻る。

- `.hevc.ts`:
  - `__handleFileChange()` が `_recording_files[file_path].file_size` を現在サイズへ更新する。
  - 直後の `processRecordedFile()` の stat では、保存済みサイズと違うサイズが見えた。
  - `file_size == last_size` の内側に入らないため、ffprobe へ進む。

つまり `.hevc.ts` の成功は、録画中判定ロジックが正しいことの証明ではない。同じ KonomiTV ソースコード内の「2回目の stat でサイズが変わっている場合だけ早期 return を回避できる」という分岐に入った結果と見るべき。

## 原因としての整理

原因は ffprobe ではない。`File is not recording. ignored.` は ffprobe 実行前のログであり、録画中 TS に対して ffprobe が失敗していることを示していない。

原因は EDCB でもない。EDCB 側では録画中状態・録画中ファイルパス・ファイルサイズ増加が確認できている。

原因は KonomiTV の録画中判定で、ファイル監視ハンドラが検知したサイズ変化を解析前に現在値として保存し、その保存済み現在値を `processRecordedFile()` が前回値として読んでしまうこと。サイズ変化検知そのものは動いている。元録画 TS では `__handleFileChange()` の stat と `processRecordedFile()` の stat が同じサイズになり、`.hevc.ts` では `processRecordedFile()` 側の再 stat で保存済みサイズと違うサイズが見えたため、同じソースコード内のガードをすり抜けたと考えられる。
