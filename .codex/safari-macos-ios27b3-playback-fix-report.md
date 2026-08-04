# Safari macOS / iOS 27 MPEG-TS Playback Fix Report

作成日: 2026-07-11

対象:

- KonomiTV ライブ視聴画面
- URL: `https://192-168-154-2.local.konomi.tv:7000/tv/watch/gr011`
- 対象ブラウザ: macOS 27 Safari / iOS 27 Safari / iPadOS 27 Safari（WebKit 全般）
- 確認 codec: HEVC 10-bit (`hvc1.2.1.L120.B0`) / AAC (`mp4a.40.5`)
- 修正対象: `client/src/services/player/PlayerController.ts`
- 参考: `.codex/safari-macos-ios-playback-fix-report.md`（macOS / iOS 26.5 時点）

## 結論

macOS 27 Safari で約 50% の確率で再生開始に失敗する直接原因は、ライブ再生開始時に呼び出した `HTMLVideoElement.play()` の Promise が resolve / reject のどちらにも進まず、保留されたままになることだった。

現行実装はこの Promise を `await` してから、以下の起動・復旧処理を登録していた。

- `canplay` / `canplaythrough` ハンドラー
- mpegts.js `MEDIA_INFO` フォールバック
- `readyState` polling と startup stall recovery
- 15 秒の startup timeout と PlayerController 再起動

したがって `play()` が保留された失敗試行では、Safari 向けに実装済みの復旧処理そのものが一切セットアップされなかった。`play()` の再生開始試行をバックグラウンド実行へ変更し、Promise の完了を待たず後続のハンドラーと watchdog を必ず登録するよう修正した。

## 調査方法

Safari の Web Inspector を対象ページに接続し、試行ごとにコンソールを消去してからページ遷移または再読み込みを行った。画面上の再生成否はユーザー報告で確定し、コンソールログと照合した。

- 1 回目: ユーザー報告により正常再生と確定
- 2 回目: 15 秒以上ローディング状態が継続し、ユーザー報告により失敗と確定

Chrome は使用していない。

## 成功時ログ

成功試行では、ストリームが `Offline` から新規起動され、`Standby` を経て `ONAir` になった。

```text
[PlayerController] Initializing...
[PlayerController] MPEG-TS playback configuration:
  playback_mode: Live
  is_safari: true
  is_hevc_playback: true
[PlayerController] Video frame diagnostics started.
[PlayerController] Initial live playback state:
  sync_when_playing_live: false
[MSEController] > MediaSource onSourceOpen
[LiveEventManager][initial_update] Status: Offline
[LiveEventManager][status_update] Status: Standby
[TSDemuxer] > Parsed first PAT: {"program_pmt_pid":{"1":4096},"version_number":0}
[TSDemuxer] > Parsed first PMT: ... "common_pids":{"h265":256,"adts_aac":257}
[TSDemuxer] > Generated first HEVCDecoderConfigurationRecord for mimeType: hvc1.2.1.L120.B0
[MSEController] > Received Initialization Segment, mimeType: video/mp4;codecs=hvc1.2.1.L120.B0
[TSDemuxer] > Generated first AudioSpecificConfig for mimeType: mp4a.40.5
[MSEController] > Received Initialization Segment, mimeType: audio/mp4;codecs=mp4a.40.5
[PlayerController] Playback started successfully.
[PlayerController] mpegts.js media info:
  mimeType: video/mp2t; codecs="hvc1.2.1.L120.B0,mp4a.40.2"
  syncWhenPlayingLive: false
[PlayerController] canplay handler invoked.
[PlayerController] Buffering...
[PlayerController] Buffering completed.
[LiveEventManager][status_update] Status: ONAir
```

成功時は `play()` が resolve し、その直後から `MEDIA_INFO`、`canplay`、バッファ調整完了まで連続して進んでいる。

## 失敗時ログ

失敗試行は直前の成功試行で起動したストリームへ再接続したため、初期状態は `Idling`、直後に `ONAir` へ復帰した。

```text
[PlayerController] Initializing...
[PlayerController] MPEG-TS playback configuration:
  playback_mode: Live
  is_safari: true
  is_hevc_playback: true
[PlayerController] Video frame diagnostics started.
[PlayerController] Initial live playback state:
  sync_when_playing_live: false
[MSEController] > MediaSource onSourceOpen
[LiveEventManager][initial_update] Status: Idling
[LiveEventManager][status_update] Status: ONAir
[TSDemuxer] > Parsed first PAT: {"program_pmt_pid":{"1":4096},"version_number":0}
[TSDemuxer] > Parsed first PMT: ... "common_pids":{"h265":256,"adts_aac":257}
[TSDemuxer] > Generated first HEVCDecoderConfigurationRecord for mimeType: hvc1.2.1.L120.B0
[MSEController] > Received Initialization Segment, mimeType: video/mp4;codecs=hvc1.2.1.L120.B0
[TSDemuxer] > Generated first AudioSpecificConfig for mimeType: mp4a.40.5
[MSEController] > Received Initialization Segment, mimeType: audio/mp4;codecs=mp4a.40.5
```

この後、長時間待っても以下は一度も出力されなかった。

```text
[PlayerController] Playback started successfully.
[PlayerController] Attempt N to start playback failed:
[PlayerController] mpegts.js media info:
[PlayerController] canplay handler invoked.
[PlayerController] Video has buffered ranges but is still not ready.
[PlayerController] Startup timed out while the live stream is ONAir.
```

画面は Progress Circular が表示されたままで、再生には至らなかった。

## 成功時と失敗時の比較

| 観測点 | 成功 | 失敗 | 判断 |
| --- | --- | --- | --- |
| Safari 判定 | `true` | `true` | 同一 |
| codec | HEVC 10-bit + AAC | HEVC 10-bit + AAC | 同一 |
| MediaSource `sourceopen` | 発火 | 発火 | MSE 自体の生成失敗ではない |
| PAT / PMT | 解析成功 | 解析成功 | TS 入力は到達している |
| video / audio init segment | 受信 | 受信 | codec 選択・初期 demux は成功 |
| `play()` 成功ログ | あり | なし | 最初の分岐点 |
| `play()` reject ログ | なし | なし | 失敗時 Promise は reject もしていない |
| `MEDIA_INFO` | あり | なし | `play()` 待機より後の登録へ未到達 |
| `canplay` | あり | なし | 同上 |
| startup timeout | 不要 | 出ない | watchdog 登録へ未到達 |
| 画面 | 再生 | ローディング継続 | ユーザー報告と一致 |

## 根本原因

ライブ再生の初期化処理には次の直列依存があった。

```text
await video.play()
  ↓ Promise が完了した場合のみ
canplay / MEDIA_INFO ハンドラー登録
  ↓
readyState polling / startup stall recovery
  ↓
15 秒 startup timeout
```

Safari 27 の失敗試行では `video.play()` が resolve も reject もせず保留された。この挙動は例外ではないため `catch` に入らず、再試行回数も増えない。結果として `setupVideoPlaybackHandler()` の実行がその位置で永久に止まった。

このモデルは、失敗時に次の 3 種類が同時に欠落したことを説明できる。

1. resolve 側の `Playback started successfully`
2. reject 側の `Attempt N ... failed`
3. `await attemptPlay()` より後で登録される全フォールバック／timeout ログ

ストリームの `Offline` / `Idling` の違いは再現タイミングと相関したが、TS、PAT/PMT、init segment は両方で到達している。今回確認できた直接の停止点はクライアント側の保留中 `play()` Promise である。

## 前回の macOS / iOS 26.5 バグとの差

前回は `buffered` が伸び、動画寸法も得られた後に `readyState=1` や非 finite な `currentTime` が残る問題だった。今回はそれより前の初期化処理が `await video.play()` で止まり、既存の frame presentation 診断、buffered 判定、startup stall recovery へ到達できていない。

したがって、前回追加した以下の対策が間違っていたわけではなく、その入口まで実行されない新しい WebKit の挙動が問題だった。

- Safari live で MSE in Worker を無効化
- DPlayer `syncWhenPlayingLive` の無効化
- `requestVideoFrameCallback()` による実フレーム確認
- Safari の低い `readyState` と非 finite な `currentTime` への耐性
- startup stall recovery と 15 秒 watchdog

## 実施した修正

対象: `client/src/services/player/PlayerController.ts`

変更前:

```ts
await attemptPlay();
```

変更後:

```ts
// Safari では MediaSource の初期化タイミングによって video.play() の Promise が
// resolve / reject のどちらにも進まず、保留されたままになることがある
// ここで完了を待つと、直後にある canplay / MEDIA_INFO ハンドラーや起動タイムアウトの登録まで止まり、
// 本来の Safari 向け復旧処理が一切動かなくなるため、再生開始試行はバックグラウンドで継続する
void attemptPlay();
```

`attemptPlay()` 自体は引き続き Promise の resolve / reject を監視する。呼び出し元だけが完了を待たないため、通常の成功ログや明示的 reject 時の再試行は維持される。一方、Promise が保留されても後続処理は即座に登録される。

この変更は Safari の User-Agent バージョンに依存せず、同じ WebKit media element 実装を利用する macOS / iOS / iPadOS Safari 全般に有効である。他ブラウザでも起動ハンドラーを早く登録するだけで、通常の `play()` 成功経路を変更しない。

## 検証結果

静的検証:

```text
yarn lint      成功
yarn typecheck 成功
```

調査対象 URL は port 7000 で配信中のビルド済みアセット (`PlayerController-CZ_Qvic-.js`) を使用しているため、ソース修正後の Safari 実動作確認にはクライアントの再ビルド／配信反映が必要である。今回の調査中にユーザー管理のサーバー API は起動・停止・再起動していない。

修正反映後に確認すべきログ:

- 失敗パターンでも `Initial live playback state` の後に `MEDIA_INFO` または readyState polling が進むこと
- 15 秒以内に再生できない場合は `Startup timed out while the live stream is ONAir.` が必ず出ること
- timeout 後に `PlayerRestartRequired` が発火し、次の試行へ復旧すること
- `requestVideoFrameCallback()` による frame presentation 確認後に loading UI が解除されること
- macOS 27 Safari だけでなく iOS 27 / iPadOS 27 Safari でも同じ経路が動くこと

## 追加確認: gr021 の失敗ログ

2026-07-11、同じ Safari セッションで `gr021` の再生失敗を追加確認した。画面は `バッファリングしています…` のまま停止し、Progress Circular が表示され続けた。

`gr021` は既存ストリームへの再接続ではなく、`Offline` からエンコードタスクを新規起動した試行だった。

```text
[PlayerController] Initializing...
[PlayerController] MPEG-TS playback configuration:
  playback_mode: Live
  is_safari: true
  is_hevc_playback: true
[PlayerController] Video frame diagnostics started.
[PlayerController] Initial live playback state.
[MSEController] > MediaSource onSourceOpen
[LiveEventManager][initial_update] Status: Offline
[LiveEventManager][status_update] Status: Standby
[LiveEventManager][detail_update] チューナーを起動しています…
[LiveEventManager][detail_update] エンコードを開始しています…
[LiveEventManager][detail_update] バッファリングしています…
[TSDemuxer] > Parsed first PAT: {"program_pmt_pid":{"1":4096},"version_number":0}
[TSDemuxer] > Parsed first PMT: ... "common_pids":{"h265":256,"adts_aac":257}
[TSDemuxer] > Generated first HEVCDecoderConfigurationRecord for mimeType: hvc1.2.1.L120.B0
[MSEController] > Received Initialization Segment, mimeType: video/mp4;codecs=hvc1.2.1.L120.B0
[TSDemuxer] > Generated first AudioSpecificConfig for mimeType: mp4a.40.5
[MSEController] > Received Initialization Segment, mimeType: audio/mp4;codecs=mp4a.40.5
[LiveEventManager][status_update] Status: ONAir
```

15 秒以上待機した後も、`gr011` の失敗時と同じく以下のログはすべて欠落した。

```text
[PlayerController] Playback started successfully.
[PlayerController] Attempt N to start playback failed:
[PlayerController] mpegts.js media info:
[PlayerController] canplay handler invoked.
[PlayerController] Startup timed out while the live stream is ONAir.
```

さらに、チャンネル切り替えで以前の失敗 PlayerController が破棄された直後、以前から保留されていた `play()` が遅れて resolve するログを複数確認した。

```text
[PlayerController] Destroying...
[PlayerController] Destroyed.
[PlayerController] Playback started successfully. – {player_exists: false, attempt: 5}

[PlayerController] Destroying...
[PlayerController] Destroyed.
[PlayerController] Playback started successfully. – {player_exists: false, attempt: 3}
```

`player_exists: false` は、再生開始時に呼び出した `play()` が PlayerController の生存中には完了せず、動画要素と MediaSource の破棄による状態変化の後になって初めて resolve したことを示す。これは `play()` Promise が resolve / reject せず保留され、`await attemptPlay()` より後のセットアップを停止させる原因モデルの直接的な裏付けである。

`gr021` は `Offline` から開始したにもかかわらず同じ停止パターンになったため、`gr011` 調査時に見られた `Idling` ストリームへの再接続は必要条件ではない。チャンネル、番組、既存エンコードタスクへの再接続に依存せず、Safari 27 の MSE ライブ再生開始時に発生しうる共通問題と判断する。

以上から、実施済みの `await attemptPlay()` → `void attemptPlay()` 修正は `gr021` に対しても同じ根本原因を解消する。修正済みソースが port 7000 のビルド済みアセットへまだ反映されていないため、今回観測した失敗は修正前コードの挙動である。

## 修正反映後の追加確認: gr093

Linux 側へ最初の修正を反映してアプリを再起動した後、macOS 27 Safari の `gr093` で再生失敗を確認した。

配信アセットは修正前の `PlayerController-CZ_Qvic-.js` から `PlayerController-Cf0pvLc3.js` に変わっており、画面にも次の復旧メッセージが表示された。このことから、`void attemptPlay()` と既存の frame verification が反映済みであることを確認できた。

```text
Safari で映像フレームの表示を確認できません。プレイヤーを再起動しています…
```

試行単位で Safari Web Inspector のコンソールを消去し、`gr093` を再読み込みして25秒間観測した。主要ログは次のとおり。

```text
[PlayerController] Initializing...
[PlayerController] MPEG-TS playback configuration:
  playback_mode: Live
  is_safari: true
  is_hevc_playback: true
[PlayerController] Video frame diagnostics started.
[PlayerController] Initial live playback state.
[MSEController] > MediaSource onSourceOpen
[LiveEventManager][initial_update] Status: ONAir
[TSDemuxer] > Parsed first PAT: {"program_pmt_pid":{"1":4096},"version_number":0}
[TSDemuxer] > Parsed first PMT: ... "common_pids":{"h265":256,"adts_aac":257}
[TSDemuxer] > Generated first HEVCDecoderConfigurationRecord for mimeType: hvc1.2.1.L120.B0
[MSEController] > Received Initialization Segment, mimeType: video/mp4;codecs=hvc1.2.1.L120.B0
[TSDemuxer] > Generated first AudioSpecificConfig for mimeType: mp4a.40.5
[MSEController] > Received Initialization Segment, mimeType: audio/mp4;codecs=mp4a.40.5
[PlayerController] mpegts.js media info:
[PlayerController] canplay handler invoked.
[PlayerController] Buffering...
[PlayerController] Buffering completed.
```

最初の修正により、以前は `await video.play()` で到達できなかった `MEDIA_INFO`、`canplay`、バッファ調整、frame verification まで実行されるようになった。一方で `Playback started successfully` は出ず、実フレームも提示されなかったため、frame verification が PlayerController の再起動を要求した。

再起動時には、今回も破棄後に保留中の `play()` が遅延 resolve していた。

```text
[PlayerController] Destroyed.
[PlayerController] Playback started successfully. – {player_exists: false, attempt: 3}
```

### gr093 で判明した第二の問題

最初の `void attemptPlay()` 修正は後続の watchdog を動かせるようにしたが、保留中の `play()` 自体は解除していなかった。そのため次の状態になった。

1. mpegts.js は init/media 情報を処理し、`canplay` と十分な buffer を報告する。
2. Safari の `play()` Promise は保留されたままで、実フレームは提示されない。
3. 既存の `recoverStartupStall()` は主に低い `readyState` を条件としているため、高い `readyState` / `canplay` が成立した今回の状態では保留中の再生開始を解除できない。
4. frame verification が失敗し、PlayerController を再起動する。
5. 新しい PlayerController でも同じ状態になり、再起動ループする可能性がある。

### 第二段階の修正

Safari の `play()` Promise に1秒のタイムアウトを設けた。タイムアウト時は `pause()` で保留中の再生開始を明示的に解除し、最大5回まで `play()` を再試行する。

概略:

```ts
const playResult = await Promise.race([
    video.play().then(() => 'Started' as const),
    ...(Utils.isSafari() === true ?
        [Utils.sleep(safariPlayTimeout).then(() => 'TimedOut' as const)] : []),
]);

if (playResult === 'TimedOut') {
    video.pause();
    attempts++;
    await Utils.sleep(attemptInterval);
    await attemptPlay();
    return;
}
```

あわせて、再生開始試行中に PlayerController が破棄・再作成された場合、古い `HTMLVideoElement` を操作し続けないよう video 要素の同一性を確認する。

このタイムアウトは Safari の場合だけ有効であり、通常ブラウザがデータ到着まで `play()` Promise を待つ挙動は変更しない。`void attemptPlay()` も維持するため、5回の再試行と並行して `MEDIA_INFO`、`canplay`、readyState polling、frame verification、startup timeout は引き続き動作する。

追加修正後の静的検証:

```text
yarn lint      成功
yarn typecheck 成功
```

第二段階の修正はまだ Linux 側の配信アセットへ反映されていない。再ビルド／再起動後、Safari で次の新規ログが出ることと、その後フレーム提示が始まることを確認する必要がある。

```text
[PlayerController] Attempt N to start playback timed out. Retrying.
[PlayerController] Playback started successfully.
```

## 第二段階修正の再検証と撤回

Linux 側へ第二段階修正を反映した後、macOS 27 Safari の `gr093` で再び失敗ログを採取した。配信アセットは `PlayerController-NJdnrtAE.js` に更新されており、1秒 timeout が実際に動作していた。

```text
[PlayerController] Attempt 1 to start playback timed out. Retrying.
[PlayerController] mpegts.js media info fired, but canplay(through) event not fired. Trying to manually start playback.
[PlayerController] Video has buffered ranges but is still not ready.
[PlayerController] Startup playback stall detected. Seeking to first buffered range.
[PlayerController] Attempt 2 to start playback timed out. Retrying.
[PlayerController] Startup playback stall recovery failed:
  AbortError: The operation was aborted.
[PlayerController] Safari has enough buffered data while readyState is low. Running startup handler anyway.
[PlayerController] Attempt 3 to start playback timed out. Retrying.
[PlayerController] Attempt 4 to start playback timed out. Retrying.
[PlayerController] Safari did not present video frames after startup handler.
[PlayerController] Startup playback stall detected. Seeking to first buffered range.
[PlayerController] Attempt 5 to start playback timed out. Retrying.
[PlayerController] Startup playback stall recovery failed:
  AbortError: The operation was aborted.
[PlayerController] Failed to start playback after 5 attempts.
[PlayerController] Safari startup frame verification failed after recovery.
[PlayerController] Safari startup completed without visible frame presentation. Keeping loading UI and restarting if ONAir.
[PlayerController] PlayerRestartRequired event received.
```

このログから、1秒 timeout 後の `pause()` は保留中の `play()` だけでなく、同時進行している `recoverStartupStall()` の seek / `play()` も `AbortError` で中断していることが分かった。PlayerController 再作成後も同じログ列が繰り返され、再起動ループになった。

### macOS 26.5 調査ログとの比較

参考タスク: `codex://threads/019ef65b-a504-75e0-a661-10f9336f960f`

macOS 26.5 時点では、再生成功中にも次の矛盾した状態が観測されていた。

```text
readyState: 1
currentTime: null
paused: false
buffered: [[0.182, 205.772]]
videoWidth: 1920
videoHeight: 1080
error: null
```

同じ `readyState: 1` / `currentTime: null` / buffered 非空の状態で、映像が表示される場合とスピナーに固定される場合があった。このため、Safari では一定時間 `play()` が resolve しないことだけを失敗根拠にできない。正常にフレーム提示へ進んでいる途中でも1秒後に `pause()` してしまう可能性がある。

以上により、第二段階で追加した「1秒 timeout → `pause()` → 最大5回再試行」は不適切と判断し、撤回した。

## 第三段階の修正

第三段階では、時間基準で Safari の再生を破壊せず、MSE の再生準備と WebKit のフレーム提示を競合させない方針へ変更した。

### 1. `play()` の timeout / `pause()` 再試行を撤回

`attemptPlay()` 内では再び Safari 自身の resolve / reject を待つ。ただし呼び出し元は引き続き `void attemptPlay()` とし、`MEDIA_INFO`、`canplay`、startup recovery、watchdog の登録をブロックしない。

また、Promise 完了時に現在の video 要素と一致するか確認し、破棄後に古い PlayerController が `Playback started successfully – {player_exists: false}` を出したり再試行したりしないようにした。

### 2. Safari ではバッファ調整中に `playbackRate=0` を設定しない

`MEDIA_INFO` から `on_canplay()` を手動実行した時点では、Safari の `play()` がまだ保留中の場合がある。従来はその直後にバッファ調整目的で次を実行していた。

```ts
video.playbackRate = 0;
```

これは WebKit がまさに開始しようとしている再生をアプリ側から停止させ、フレーム提示を妨げる競合になり得る。Safari では通常速度のままバッファを貯め、ローディング UI によって準備中の映像を隠す。Safari 以外では従来どおり `playbackRate=0` / `1` によるバッファ調整を維持する。

### 3. バッファ確保後に非破壊的な `play()` を再要求

`Buffering completed` の時点では init segment、media info、必要な buffer が揃っている。Safari に再生可能状態を再評価させるため、`pause()` や seek を挟まず、もう一度 `video.play()` を非同期で要求する。その後は既存の `requestVideoFrameCallback()` による frame verification を行う。

```ts
if (Utils.isSafari() === true) {
    void video.play().catch((error) => {
        // 診断ログ
    });
}
```

この構成では、Safari 固有の不正確な `readyState` / `currentTime` や経過時間ではなく、最終的に実フレームが提示されたかを成功条件として維持できる。

第三段階修正後の静的検証:

```text
yarn lint      成功
yarn typecheck 成功
git diff --check 成功
```

第三段階修正は Linux 側の配信アセットへまだ反映されていない。再ビルド／再起動後、以下を確認する。

- `Attempt N to start playback timed out. Retrying.` が出なくなったこと
- startup recovery の `play()` が `pause()` による `AbortError` で中断されないこと
- `Buffering completed.` 後に `requestVideoFrameCallback()` が発火すること
- frame presentation 確認後に loading / buffering UI が解除されること
- PlayerController の再起動ループへ入らないこと

## 第三段階修正反映後の追加確認

Linux 側へ第三段階修正を反映した後、macOS 27 Safari の `gr093` で再び失敗ログを採取した。配信アセットは `PlayerController-C67f-aRU.js` に更新されていた。

試行単位でコンソールを消去して18秒間観測した主要ログ:

```text
[PlayerController] mpegts.js media info fired, but canplay(through) event not fired. Trying to manually start playback.
[PlayerController] Video has buffered ranges but is still not ready.
[PlayerController] Startup playback stall detected. Seeking to first buffered range.
[PlayerController] Safari did not present video frames after startup handler.
[PlayerController] Startup playback stall detected. Seeking to first buffered range.
```

第三段階で撤回した次のログは出なくなった。

```text
[PlayerController] Attempt N to start playback timed out. Retrying.
AbortError: The operation was aborted.
```

このため、時間基準の `pause()` が startup recovery を中断する競合は解消した。また、`playbackRate=0` を使わないビルドへ更新されたものの、実フレーム提示には至らなかった。

### 新たに確認した停止点

`recoverStartupStall()` は buffered range の先頭付近へ seek した後、次を直列に待っていた。

```ts
await video.play();
```

Safari 27 ではこの recovery 側の `play()` も resolve / reject のどちらにも進まず保留された。ログが `Startup playback stall detected. Seeking to first buffered range.` で止まり、直後にある次のログが出なかったことが根拠である。

```text
[PlayerController] Startup playback stall recovery attempted.
```

最初の `attemptPlay()` を `void` 化しても、frame verification から呼ぶ recovery 内に別の無期限 `await video.play()` が残っていたため、次の処理が停止していた。

- recovery 後のフレーム再確認
- `Safari startup frame verification failed after recovery.`
- `PlayerRestartRequired`

## 第四段階の修正

Safari の `recoverStartupStall()` では `video.play()` を await せず再生要求だけを送る。`pause()` は行わず、0.5秒間だけフレーム提示の機会を与えてから呼び出し元へ戻す。

```ts
if (Utils.isSafari() === true) {
    void video.play().catch((error) => {
        // 現在の PlayerController に紐づく video 要素である場合だけ診断ログを出す
    });
    await Utils.sleep(0.5);
} else {
    await video.play();
}
```

待機中に PlayerController が破棄・再作成された場合は、古い video 要素の復旧成功ログを出さないよう同一性も確認する。

この修正により、Safari の recovery `play()` が保留されても、必ず次のいずれかへ進める。

1. `requestVideoFrameCallback()` が発火し、再生成功と判定する。
2. フレームが提示されず、frame verification failure と PlayerController 再起動へ進む。

第四段階修正後の静的検証:

```text
yarn lint      成功
yarn typecheck 成功
git diff --check 成功
```

第四段階修正は Linux 側の配信アセットへまだ反映されていない。次回は以下を確認する。

- seek 後に `Startup playback stall recovery attempted.` が出ること
- その後 `requestVideoFrameCallback()` によるフレーム提示が確認できること
- フレームが出ない場合も frame verification failure と PlayerController 再起動へ必ず進むこと
- recovery の `play()` Promise 保留だけで起動処理全体が停止しないこと

## 第四段階修正反映後の追加確認

第四段階修正を Linux 側へ反映した後、macOS 27 Safari の `gr093` で20秒間の失敗ログを採取した。配信アセットは `PlayerController-D8_pQaG2.js` だった。

```text
[PlayerController] mpegts.js media info fired, but canplay(through) event not fired. Trying to manually start playback.
[PlayerController] Video has buffered ranges but is still not ready.
[PlayerController] Startup playback stall detected. Seeking to first buffered range.
[PlayerController] Startup playback stall recovery attempted.
[PlayerController] Safari has enough buffered data while readyState is low. Running startup handler anyway.
[PlayerController] Safari did not present video frames after startup handler.
[PlayerController] Startup playback stall detected. Seeking to first buffered range.
[PlayerController] Startup playback stall recovery attempted.
[PlayerController] Safari startup frame verification failed after recovery.
[PlayerController] Safari startup completed without visible frame presentation. Keeping loading UI and restarting if ONAir.
[PlayerController] PlayerRestartRequired event received.
```

第四段階の目的だった「recovery の保留中 `play()` によって起動処理全体を停止させない」は達成した。seek、recovery 後の再評価、frame verification failure、PlayerController 再起動まで完走している。一方、同じ処理を新しい PlayerController で繰り返してもフレームは提示されず、再起動ループになった。

### ビルド済みクライアントの照合

ユーザーがプロジェクトの `client/dist` 以下に配置したビルド成果物を調査した。

```text
client/dist/assets/PlayerController-D8_pQaG2.js
```

Safari Web Inspector が読み込んだファイル名と一致した。minified asset 内には以下が含まれていた。

- `void` 相当の非同期 `attemptPlay()`
- Safari で `playbackRate=0` を設定しない分岐
- バッファ確保後の非破壊的 `play()` 再要求
- Safari recovery `play()` の非同期化と0.5秒待機
- `Startup playback stall recovery attempted.` ログ

したがって、今回の失敗は古いキャッシュやビルド反映漏れではなく、第四段階修正そのものを実行した結果である。source map (`PlayerController-D8_pQaG2.js.map`) は配置されていなかったため、minified asset の文字列と処理フローを元ソースと直接照合した。

### 第五段階で見直した seek target

macOS 26.5 調査ログでは、Safari の失敗時に buffered range が次のように数百秒へ伸びていた。

```text
buffered: [[0.182, 205.772]]
currentTime: null
readyState: 1
```

第四段階までの `recoverStartupStall()` は、buffered range の長さに関係なく `buffered.start(0) + 0.1` を seek target にしていた。つまり上記なら約0.282秒という、ライブバッファの最古位置へ戻していた。

Safari 27 では、時間軸が未確立の状態から数百秒前の古い端へ seek しても、現在再生可能なランダムアクセスポイントを選べず、デコード開始点を確立できない可能性が高い。第四段階ログで seek 自体は完了しているのにフレームが一度も提示されないこととも整合する。

## 第五段階の修正

Safari の startup recovery seek target を、最古の buffered position ではなくライブ末尾付近へ変更した。

```ts
const seek_target = Math.max(
    last_buffered_position - this.live_playback_buffer_seconds,
    first_buffered_position + 0.1,
    0.1,
);
```

通常モードならライブ末尾から約4.3秒、低遅延モードなら約1.2秒戻した位置になる。seek は HTMLVideoElement への direct assignment ではなく、引き続き `this.player.plugins.mpegts.currentTime` を優先する。これにより mpegts.js の seek handler に最新のランダムアクセスポイントを選ばせる。

DPlayer の `syncWhenPlayingLive` は引き続き Safari で無効とするため、MSE 初期化直後に DPlayer が direct `video.currentTime` seek を行う経路は復活させない。

診断ログには次を追加した。

- `first_buffered_position`
- `last_buffered_position`
- `seek_target`

ログメッセージも実際の処理に合わせて変更した。

```text
[PlayerController] Startup playback stall detected. Seeking within buffered range.
```

第五段階修正後の静的検証:

```text
yarn lint      成功
yarn typecheck 成功
git diff --check 成功
```

第五段階修正は `client/src/services/player/PlayerController.ts` にのみ存在し、確認時点の `client/dist/assets/PlayerController-D8_pQaG2.js` にはまだ含まれていない。Linux 側で再ビルドした後、新しい asset 名と seek 診断値を確認する必要がある。

## Git の扱い

依頼どおり Git 追跡対象の `client/src/services/player/PlayerController.ts` を編集したが、stage / commit / push は行っていない。
