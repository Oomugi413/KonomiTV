# Safari MPEG-TS Playback Fix Report

作成日: 2026-06-24

対象:

- KonomiTV ライブ視聴画面
- URL: `https://192-168-154-2.local.konomi.tv:7000/tv/watch/gr011`
- 対象ブラウザ: macOS Safari / iOS Safari
- 対象 codec: H.264 / H.265
- 主な修正対象: `/Users/oomugi413/Documents/Test1/PlayerController.ts`

## 結論

Safari で映像が出ない、または `バッファリングしています...` のまま進まない問題は、サーバー側のストリーム生成失敗や codec 選択ミスではなく、Safari の MSE + MPEG-TS live playback における `HTMLVideoElement` 状態値の不安定さと、KonomiTV / DPlayer 側の再生開始判定の相性問題だった。

最終的に、`PlayerController.ts` だけで以下を組み合わせることで、H.264 / H.265 とも macOS Safari / iOS Safari で再生成功した。

- Safari live MPEG-TS では `mpegts.js` の MSE in Worker を無効化する。
- Safari live では DPlayer の再生直前 live sync (`syncWhenPlayingLive`) を無効化する。
- Safari の `readyState` / `currentTime` を成功判定として過信しない。
- `requestVideoFrameCallback()` により、実際に video frame が提示されたかを追跡する。
- buffered range はあるが `readyState` が低い場合でも、Safari では起動処理を先へ進める。
- 起動処理後に frame presentation が確認できない場合は、UI を成功扱いせず、startup stall recovery または player restart に戻す。
- startup timeout は `is_video_buffering` だけでなく `is_loading` も見る。

## 観測されたエラー

### Safari 初期失敗

H.264 に設定した状態で Safari を開くと、MPEG-TS の demux と MSE append は進んでいた。

代表ログ:

```text
[MSEController] > Received Initialization Segment, mimeType: video/mp4;codecs=avc1.640028
[MSEController] > Received Initialization Segment, mimeType: audio/mp4;codecs=mp4a.40.5
[TSDemuxer] > Parsed first PMT: ... "common_pids":{"h264":256,"adts_aac":257}
```

一方、Safari の `HTMLVideoElement` は再生可能状態へ進まなかった。

代表状態:

```text
readyState=1
networkState=2
paused=false
muted=true
currentTime=null
buffered=0.182-205.772
error=none
videoWidth=1920
videoHeight=1080
requestVideoFrameCallback=true
visible text=バッファリングしています... / 閉じる / 011
```

重要なのは、`video.error === null` で、buffered range も動画寸法も存在する点である。つまり「メディアが取得できていない」「H.264 が選ばれていない」「TS demux が壊れている」とは言いにくい。

### Safari で見えていた console error

Safari Web Inspector には次のような error が出ていた。

```text
Viewport argument key "interactive-widget" not recognized and ignored.
[web-bml][resource] component not found failed to fetch - "/60/0000/startup.bml"
[web-bml][resource] module not found - "/60/0201"
[web-bml][resource] module not found - "/60/0201/city-yubin.btb"
```

これらは再生不能の主因ではないと判断した。理由は次の通り。

- MPEG-TS / H.264 / AAC の初期化ログは error 後も出ている。
- `HTMLVideoElement.error` は `null` のままだった。
- Chrome の正常再生時にも類似の BML/resource 系ログは存在した。
- 問題の本体は `readyState=1` / `currentTime` 非有限 / buffered 非空という Safari media element 状態の矛盾だった。

### Chrome との差分

同じ URL を Chrome で開き、手動で再生ボタンを押すと正常再生できた。

Chrome 側の代表状態:

```json
{
  "readyState": 4,
  "paused": false,
  "muted": false,
  "currentTime": 75.866041,
  "buffered": [[0.013, 76.543]],
  "error": null
}
```

Chrome では `Playback started successfully` と `Buffering completed` まで到達している。これにより、ストリーム URL・基本的な H.264/AAC 生成・MPEG-TS demux は成立しており、Safari 固有の MSE / media element 挙動が主因だと切り分けられた。

## 原因モデル

最終的な原因モデルは次の通り。

1. KonomiTV が Safari に MPEG-TS live stream を渡す。
2. `mpegts.js` が MPEG-TS を fragmented MP4 に transmux し、MSE へ append する。
3. Safari は init segment / media segment を受け取り、`buffered` や `videoWidth/videoHeight` は更新する。
4. しかし Safari の `HTMLVideoElement.readyState` は `HAVE_METADATA` (`1`) のまま残り、`currentTime` は非有限値になることがある。
5. KonomiTV は `canplay` / `canplaythrough` / `readyState` / buffer 秒数を起点に UI を解除するため、Safari の矛盾した状態で `バッファリングしています...` が残る。
6. DPlayer は live 再生時に `play()` 前に live sync を実行し、`video.currentTime = duration - liveSyncMinBufferSize` を直接実行する。この direct seek が Safari MSE 起動直後の不安定状態を悪化させる可能性が高い。
7. `mpegts.js` 側には Safari の 0 秒 seek を避ける workaround があるが、DPlayer の direct `video.currentTime` 書き換えは `mpegts.js` の seek handler を経由しない。
8. `videoWidth/videoHeight` と `buffered` だけでは、実フレームが提示されているか判定できない。実際、寸法と buffer があるのに画面はスピナーのままというケースを確認した。

このため、成功判定には `readyState` よりも実フレーム提示の有無を優先する必要があった。

## 実施した修正

すべて `PlayerController.ts` のみで実装した。`node_modules` 配下の `StartupStallJumper` / `SeekingHandler` は修正していない。

### 1. Safari live MPEG-TS で MSE in Worker を無効化

対象:

- `/Users/oomugi413/Documents/Test1/PlayerController.ts:81`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:259`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:610`

Safari の live MPEG-TS では `enableWorkerForMSE` を `false` にした。

目的:

- Safari の `MediaSourceHandle + DedicatedWorker` 経路を避ける。
- main thread MSE 経路に戻す。
- 初期症状である「buffered は伸びるが映像が出ない」状態を回避する。

### 2. Safari live で DPlayer の `syncWhenPlayingLive` を無効化

対象:

- `/Users/oomugi413/Documents/Test1/PlayerController.ts:354`

追加内容:

```ts
syncWhenPlayingLive: Utils.isSafari() === true ? false : true,
```

目的:

- DPlayer の `play()` 前 live sync による direct `video.currentTime = ...` を Safari で避ける。
- Safari MSE 起動直後の `currentTime` 非有限状態に対して、さらに seek を重ねることを避ける。
- live 遅延追従は mpegts.js の `liveSync` 側に任せる。

### 3. buffer 秒数計算で `currentTime` 非有限値に耐える

対象:

- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1021`

`getPlaybackBufferSeconds()` で `video.currentTime` が finite でない場合、`buffered.start(0)` を基準にして buffer 秒数を計算するようにした。

目的:

- Safari の `currentTime=NaN` 相当で buffer 秒数が `NaN` になるのを避ける。
- `on_canplay()` 内の buffer 調整ループが永久に抜けないリスクを下げる。

### 4. `requestVideoFrameCallback()` による frame presentation 診断

対象:

- `/Users/oomugi413/Documents/Test1/PlayerController.ts:34`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1064`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1082`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1118`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1519`

`requestVideoFrameCallback()` をループ登録し、直近に video frame が提示された時刻・mediaTime・presentedFrames を保持するようにした。

目的:

- `buffered` / `videoWidth` / `videoHeight` ではなく、実フレーム提示を成功判定に使う。
- Safari の `readyState=1` false positive を吸収する。
- 逆に、buffer と寸法があっても frame callback が来ない場合は失敗として扱う。

### 5. Safari startup frame verification を追加

対象:

- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1144`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1593`

`on_canplay()` 相当の起動処理後、Safari では UI を解除する前に frame presentation を確認するようにした。

動作:

- `requestVideoFrameCallback()` が直近に発火していれば成功。
- `readyState >= 3` かつ `currentTime` が finite なら成功扱い。
- 一定時間 frame が提示されなければ `recoverStartupStall()` を試す。
- それでも frame が提示されなければ loading / buffering UI を維持し、ONAir なら `PlayerRestartRequired` へ戻す。

目的:

- 「buffer と寸法はあるが画面はスピナー」のケースを成功扱いしない。
- 「映像は出ているが Safari の `readyState` だけ低い」ケースは成功扱いできる。

### 6. Safari で readyState が低くても buffer 十分なら起動処理へ進める

対象:

- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1127`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1695`

`hasEnoughBufferedDataForSafariStartup()` を追加し、Safari では次の条件を満たす場合に `readyState` polling を抜けて起動処理へ進めるようにした。

- Safari
- live 再生
- `video.error === null`
- `buffered.length > 0`
- `getPlaybackBufferSeconds() >= live_playback_buffer_seconds`

目的:

- Safari が `readyState < 4` のまま止まる場合でも、十分な buffer があるなら `on_canplay()` 相当の処理へ進める。
- ただし UI 成功扱いは frame verification 後に限定する。

### 7. startup stall recovery を強化

対象:

- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1245`

`recoverStartupStall()` では、Safari の場合、seek target を `first_buffered_position + 0.1` 以上にした。

目的:

- Safari で 0 秒近傍 seek が詰まる既知傾向を避ける。
- `node_modules/mpegts.js` の `SeekingHandler` を直接修正せず、KonomiTV 側から安全側の seek target を与える。

### 8. timeout 条件を `is_loading` も見るように変更

対象:

- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1726`

変更後の意味:

```ts
player_store.live_stream_status === 'ONAir' &&
on_canplay_called === false &&
(player_store.is_loading === true || player_store.is_video_buffering === true)
```

目的:

- `is_video_buffering` だけ false になったが `is_loading` が残っているケースを取り逃がさない。
- 「背景またはスピナーが残っているのに startup timeout が発火しない」状態を避ける。

### 9. 診断ログを拡充

対象:

- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1206`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1220`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1521`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1524`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1564`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1570`
- `/Users/oomugi413/Documents/Test1/PlayerController.ts:1739`

追加した主な診断値:

- `syncWhenPlayingLive`
- `playbackBufferSeconds`
- `videoFrameCallbackSupported`
- `lastVideoFrameCallbackAt`
- `lastVideoFrameCallbackAge`
- `lastVideoFrameMediaTime`
- `lastVideoFramePresentedFrames`
- `hasRecentVideoFrame`
- `is_loading`
- `is_video_buffering`
- `on_canplay_called`

目的:

- `readyState` が低いだけなのか、実フレームが本当に出ていないのかを切り分ける。
- startup timeout / restart に入る直前の UI state と media state を確認できるようにする。

## 修正結果

修正後、以下の再生成功が確認された。

- macOS Safari + H.264: 成功
- macOS Safari + H.265: 成功
- iOS Safari + H.264: 成功
- iOS Safari + H.265: 成功

この結果から、少なくとも今回の Safari 再生不能は codec そのものの非対応ではなく、Safari MSE live playback と KonomiTV/DPlayer の起動処理の組み合わせに起因していたと判断できる。

H.264 で失敗していた時点では `avc1.640028` の init segment まで受信できていた。H.265 でも最終的に再生できたため、H.265 の単独問題でもない。

## 修正しなかったもの

今回は以下を修正していない。

- `/Users/oomugi413/Documents/KonomiTV/client/node_modules/mpegts.js/src/player/startup-stall-jumper.ts`
- `/Users/oomugi413/Documents/KonomiTV/client/node_modules/mpegts.js/src/player/seeking-handler.ts`
- その他 `node_modules` 配下の依存ライブラリ

理由:

- `node_modules` 内の直接修正は KonomiTV のソースコードだけで完結しない。
- dependency patch / fork / upstream PR / package manager patching など、別の管理方針が必要になる。
- 今回は `PlayerController.ts` のみで macOS/iOS Safari の H.264/H.265 再生に成功したため、まずアプリ側の回避策として完結させた。

## 今後の注意点

Safari では、修正後も `HTMLVideoElement.readyState` や `currentTime` が Chrome と同じ意味を持つとは限らない。したがって、今後も Safari 向けの再生開始・復旧処理では次の方針を維持するべき。

- `readyState >= 3` だけを成功条件にしない。
- `videoWidth/videoHeight` と `buffered.length` だけを可視再生成功の根拠にしない。
- `requestVideoFrameCallback()` による frame presentation を優先する。
- `currentTime` が finite である前提の計算には fallback を入れる。
- Safari で direct `video.currentTime` seek を行う経路は慎重に扱う。
- player restart 後も同じ初期化条件を通るため、初回再生だけでなく再起動後も検証対象にする。

## 参照

- 詳細な観測ログ: `/Users/oomugi413/Documents/Test1/safari-h264-current-error-log.md`
- 調査中の原因推定と対策メモ: `/Users/oomugi413/Documents/Test1/safari-h264-root-cause-and-fix.md`
- 修正版 `PlayerController.ts`: `/Users/oomugi413/Documents/Test1/PlayerController.ts`
