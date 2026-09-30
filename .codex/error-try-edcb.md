# KonomiTV 録画中判定エラー確認と対策案

## 試験1: KonomiTV 録画ファイル監視・メタデータ解析

60秒を超える録画中ファイルで `RecordedScanTask` の挙動を確認した。

試験条件は次。

- 日時: 2026-06-27 22:07:55 JST から約150秒
- 放送局: NHK総合1・東京
- 予約名: `CodexRecordedScanTest_20260627_220640`
- EDCB 予約 ID: `230`
- 録画先: `/mnt/recording`
- 録画ファイル: `/mnt/recording/20260627_CodexRecordedScanTest_20260627_220640.ts`
- 録画プラグイン: `Write_Default.so`

録画中の EDCB 側状態は正常だった。

- `sendGetNotifySrvStatus()` 相当の状態で `notify_param1=1`
- `sendGetRecFilePath(230)` 相当の呼び出しで録画中ファイルパスを取得できた
- ファイルサイズは録画中に継続して増加した

確認できたサイズ変化は次。

```text
22:08:01  11,550,720 bytes
22:08:11  30,801,920 bytes
22:08:21  50,823,168 bytes
22:09:11 150,159,360 bytes
22:10:21 287,997,952 bytes
録画終了後 296,683,928 bytes
```

一方、KonomiTV 側では録画中に次のログが繰り返された。

```text
20260627_CodexRecordedScanTest_20260627_220640.ts: File is not recording. ignored.
```

このログは同一ファイルで386回出ていた。録画中に `File size changed.` は出ているが、`Saved metadata to DB. (status: Recording)` は出ず、`/api/videos` にも録画中ファイルは含まれなかった。

ログは~/git/KonomiTV/.codex/log_mpeg2.txt

録画終了後は次の流れで正常に保存された。

```text
Recording or copying has just completed or has already completed.
Saved metadata to DB. (status: Recorded)
```

その後、録画ファイル削除後に KonomiTV も DB レコードを削除し、`/api/videos` から対象ファイルは消えた。

##試験2: bs4k で試す

BSテレ東4Kの録画ファイルで実験したところ、録画中は同様のログが流れたものの、エンコード中にKonomiTV GUIで「録画中」のファイルが確認できた。

元ファイル：/mnt/recording/20260627_わたしのヒュッゲ【パラサーファー・高尾千香子（後編）】[字].ts
エンコードファイル：/mnt/recording/20260627_わたしのヒュッゲ【パラサーファー・高尾千香子（後編）】[字].hevc.ts

したがって、`/api/videos` にエンコード中ファイルが含まれたと推測できる。

エンコードは外部ソフト:Amatsukazeによって、tsreplaceを用いてエンコードしているため、形式はtsファイルであり、「録画ファイル」と誤認する可能性のある形式である。

ただし、「誤認識」は問題ではなく、本当の問題は「録画ファイルの未認識」であることに留意する必要がある。

ログは~/git/KonomiTV/.codex/log_hevc.txt

##当初のcodexの推定

問題は KonomiTV の `server/app/metadata/RecordedScanTask.py` 側にある可能性が高い。

該当する流れは次。

1. `__handleFileChange()` が録画中ファイルのサイズ変化を検知する
2. 同じ関数内で `recording_info.file_size` を現在サイズへ更新する
3. その直後に `processRecordedFile()` を呼ぶ
4. `processRecordedFile()` は更新済みの `recording_info.file_size` を前回サイズとして読む
5. 結果として `file_size == last_size` になり、`mtime_continuous_start_at is None` のまま `File is not recording. ignored.` で戻る

つまり、呼び出し元では「サイズが変わった」と判定しているのに、解析関数に入る直前に前回サイズを現在サイズへ上書きしてしまうため、解析関数からは「サイズが変わっていない」ように見える。

このため、録画中ファイルが正常に伸び続けていても、録画中メタデータが保存されず、録画終了後にだけ `Recorded` として登録される。

##私（ユーザー:oomugi413）の反証

そもそも録画中ファイルのサイズ変化検知に用いる関数が間違っているのなら、エンコード中のファイルを、6分中の1分17秒がエンコードされた段階で認識できるはずがなく、関数そのものが間違っているという考えは誤り。

##仮説1:ffprobe

認識に成功したエンコードファイルのログは、

[2026/06/27 23:02:01.950] INFO:     /mnt/recording/20260627_わたしのヒュッゲ【パラサーファー・高尾千香子（後編）】[字].hevc.ts: New recording or copying file detected.
[2026/06/27 23:02:01.950] WARNING:  /mnt/recording/20260627_わたしのヒュッゲ【パラサーファー・高尾千香子（後編）】[字].hevc.ts: File size is 0. ignored.
[2026/06/27 23:02:02.401] DEBUG:    /mnt/recording/20260627_わたしのヒュッゲ【パラサーファー・高尾千香子（後編）】[字].hevc.ts: FFprobe analysis completed.

となっており、録画中にffprobeのスキャンに成功している。

仮説は、「録画ファイルの録画途中ではffprobeが通らないのでサイズ認識に失敗している」というものである。

##検証案1

この仮説1を検証するため、次の検証を提案する。

NHK総合1・東京の番組を、録画先は/mnt/recordingとし、5-10分録画。

録画設定プリセット"Amatsukaze_NVENC-HEVC-2K-auto-auto"を使用してエンコード。

録画中とエンコード中で、KonomiTVの録画ファイル監視・メタデータ解析コマンドと、ffprobeを実行し、エラーの有無を調べる。

必ず録画ファイルは作業終了後に消すこと。

必要に応じて、~/git/EDCBも確認すること。ただし、この検証とは関係のない録画中の番組への影響を避けるため、**systemctl restart edcbは絶対に行わない**こと

この問題のcodexが考える原因と対処法を
~/git/KonomiTV/.codex/error-meta1.md
にまとめる。



