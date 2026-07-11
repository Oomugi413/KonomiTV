# PlayerController 2026-06-12 版から現在版への変更点

作成日: 2026-07-11

比較対象:

- 変更前: `.codex/PlayerController_20260612.ts`（2195行）
- 現在版: `client/src/services/player/PlayerController.ts`（2665行）
- 現在版のコピー: `.codex/PlayerController_27.ts`

現在版は変更前より470行増えている。以下の行番号は、すべて現在版 `client/src/services/player/PlayerController.ts` の行番号である。

## 概要

差分の中心は、Safari / WebKit におけるライブ MPEG-TS 再生開始の不安定さへの対策である。

主な方針:

1. Safari live では MSE in Worker と DPlayer の direct live sync を避ける。
2. Safari の `readyState` / `currentTime` を成功判定として過信しない。
3. `requestVideoFrameCallback()` で実際のフレーム提示を追跡する。
4. 十分な buffer があれば低い `readyState` のままでも起動処理へ進める。
5. `play()` Promise が保留されても、後続のハンドラーや watchdog を停止させない。
6. 起動失敗時は buffered range 内を seek して復旧し、最終的にフレーム提示または PlayerController 再起動へ進める。
7. 成功・失敗時の media element 状態を比較できる診断ログを追加する。

## 1. `requestVideoFrameCallback()` 用の型定義

現在版: 26〜38行

追加した型:

- `VideoFrameRequestMetadataLike`
- `VideoFrameRequestCallbackLike`
- `HTMLVideoElementWithFrameCallback`

目的:

- Safari の `readyState` や `currentTime` が不正確でも、実際に映像フレームが提示されたかを判断する。
- `requestVideoFrameCallback()` / `cancelVideoFrameCallback()` を型安全に扱う。

## 2. Safari 再生診断用のクラスフィールド

現在版: 80〜89行

追加したフィールド:

- `enable_worker_for_mse`
- `video_frame_callback_handle`
- `video_frame_callback_source`
- `last_video_frame_callback_at`
- `last_video_frame_media_time`
- `last_video_frame_presented_frames`

変更前は MSE in Worker の選択結果や、直近のフレーム提示情報を PlayerController 内で保持していなかった。

## 3. MSE in Worker の選択と初期診断ログ

現在版: 268〜282行

変更内容:

- Safari のライブ MPEG-TS 再生では `enable_worker_for_mse = false` にする。
- HEVC の Worker 対応状況だけでなく、Safari と再生モードを含めて選択する。
- 選択結果と codec 情報を `MPEG-TS playback configuration` としてログ出力する。

診断項目:

- `playback_mode`
- `is_safari`
- `is_hevc_playback`
- `is_hevc_10bit_playback`
- `is_hevc_video_supported_in_worker`
- `enable_worker_for_mse`
- `live_playback_buffer_seconds`

mpegts.js への設定反映箇所は621行で、変更前のローカル条件式から `this.enable_worker_for_mse` 参照へ変更した。

## 4. Safari で DPlayer の live sync を無効化

現在版: 364〜365行

追加設定:

```ts
syncWhenPlayingLive: Utils.isSafari() === true ? false : true,
```

目的:

- DPlayer が `play()` 前に `video.currentTime` を直接変更する経路をSafariで止める。
- MSE 起動直後の非有限 `currentTime` に対する direct seek を避ける。
- ライブ遅延追従は mpegts.js 側の処理へ任せる。

## 5. ライブバッファ秒数計算の安全化

現在版: 1051〜1065行

変更内容:

- `buffered.length === 0` の場合は0を返す。
- `currentTime` が finite でない場合は `buffered.start(0)` を計算基準に使う。
- 計算結果が finite でない場合は0を返す。

変更前は次の単純な計算だった。

```ts
buffered.end(last) - video.currentTime
```

Safari で `currentTime=NaN` 相当になると、起動時のbuffer待機ループが終了できない問題を防ぐ。

## 6. buffered range の診断変換

現在版: 1068〜1088行

追加メソッド:

```ts
getBufferedRangesForLog()
```

`TimeRanges` をログ向けの `[start, end]` 配列へ変換する。読み出し中の例外も診断処理内で吸収する。

## 7. 実フレーム提示の追跡

現在版:

- 1091〜1106行: `resetVideoFrameDiagnostics()`
- 1109〜1140行: `startVideoFrameDiagnostics()`
- 1143〜1149行: `hasRecentlyPresentedVideoFrame()`

変更内容:

- `requestVideoFrameCallback()` を再帰登録して、最後に提示されたフレームを追跡する。
- `mediaTime`、`presentedFrames`、callback時刻を保持する。
- PlayerController の破棄・video要素交換時は追跡を停止する。
- 直近2秒以内にフレームが提示されたかを判定できるようにする。

## 8. Safari の低い `readyState` を迂回するbuffer判定

現在版: 1152〜1165行

追加メソッド:

```ts
hasEnoughBufferedDataForSafariStartup()
```

条件:

- Safari
- ライブ再生
- `video.error === null`
- buffered range が存在
- buffer秒数が `live_playback_buffer_seconds` 以上

この条件を満たした場合、`readyState` が低いままでも起動ハンドラーを実行できる。

## 9. Safari 起動時のフレーム提示検証

現在版: 1168〜1211行

追加メソッド:

```ts
waitForSafariStartupFramePresentation()
```

動作:

1. 最大2.5秒、直近のframe callbackを待つ。
2. `readyState >= 3` かつ finiteな `currentTime` も補助的な成功条件にする。
3. フレームが出なければ `recoverStartupStall()` を実行する。
4. さらに1秒待って再判定する。
5. 最終的に失敗した場合は `false` を返す。

変更前はbufferと再生イベントだけで loading UI を解除しており、実映像が出ていない状態を成功扱いする可能性があった。

## 10. HTMLVideoElement の統合診断ログ

現在版: 1214〜1267行

追加メソッド:

```ts
getVideoPlaybackStateForLog()
```

主な診断項目:

- 選択画質とストリームURL
- `syncWhenPlayingLive`
- `readyState` / `networkState`
- `paused` / `muted` / `playbackRate`
- `currentTime` / `duration` とfinite判定
- 動画幅・高さ
- buffered ranges / buffer秒数
- seekable range数
- `MediaError`
- `currentSrc`
- document visibility
- frame callback対応状況
- 最終frame callback時刻・経過時間・`mediaTime`・`presentedFrames`
- 直近フレームの有無

現在のSafari調査ログの大半はこのメソッドから生成される。

## 11. startup stall recovery

現在版: 1270〜1350行

追加メソッド:

```ts
recoverStartupStall()
```

復旧条件:

- ライブ再生
- buffered range が存在
- `readyState < 2`
- `currentTime` が非有限、または最初のbuffer位置より前

seek target:

- Safari: `buffered.end(last) - live_playback_buffer_seconds`
- Safari以外: `buffered.start(0) + 0.001`

Safariでは最古のbuffer位置ではなく、ライブ末尾から通常の再生buffer分だけ戻した位置を使う。mpegts.js pluginがあれば、その `currentTime` setter経由でseekする。

Safariの `play()` Promiseは保留される可能性があるため、recoveryでは完了を待たず再生要求を送り、0.5秒後に呼び出し元へ戻る。これによりframe verificationやPlayerController再起動を無期限に停止させない。

## 12. 通常のbuffering recoveryにframe判定を追加

現在版: 1357〜1419行

変更内容:

- 直近フレームが提示されていれば、低い `readyState` をbuffering失敗と扱わずUI状態だけ解除する。
- `pause()` / `play()` 再試行後にもframe callbackを確認する。
- 復旧ログへ統合media状態を付加する。

追加された主要ログ:

- `Safari reports low readyState, but video frames are being presented.`
- `Safari recovered after play retry and video frames are being presented.`

## 13. ライブ開始時にframe diagnosticsを開始

現在版: 1582〜1590行

変更内容:

- 一時ミュート後に `startVideoFrameDiagnostics()` を開始する。
- `Initial live playback state` ログへMSE Worker、buffer秒数、live sync設定を出力する。

## 14. 初回 `play()` を起動フローから非ブロッキング化

現在版: 1593〜1633行

変更内容:

- 再生対象のvideo要素をローカルに保持し、PlayerController再作成後の古いPromiseを無視する。
- `video.play()` 自体はresolve/rejectを待つが、`attemptPlay()` の呼び出し元では `await` せず `void attemptPlay()` とする。
- Safariで `play()` Promiseが保留されても、後続の `canplay` / `MEDIA_INFO` ハンドラーとwatchdogを登録できる。
- 破棄後に古いPlayerControllerが成功ログや再試行を出さない。

変更前は `await attemptPlay()` の完了後にしか起動ハンドラーを登録しなかった。

## 15. `on_canplay()` の診断・Safari固有処理

現在版: 1637〜1731行

主な変更:

- 1645〜1647行: `canplay handler invoked` とmedia状態を記録。
- 1651〜1653行: `Buffering...` にbuffer秒数を付加。
- 1654〜1658行: Safariではbuffer調整中に `playbackRate=0` を設定しない。
- 1672〜1678行: Safari以外だけ `playbackRate` を1へ戻し、完了時状態を記録。
- 1679〜1685行: Safariでbuffer確保後に非破壊的な `video.play()` を再要求。
- 1687〜1705行: 実フレームが出なければloading UIを維持し、ONAirならPlayerController再起動を要求。

SafariではMSE開始中の `play()` が保留されている状態で `playbackRate=0` を設定すると、WebKitの再生開始自体を止める可能性があるため分岐した。

## 16. mpegts.js `MEDIA_INFO` ログの強化

現在版: 1752〜1761行

変更内容:

- media infoだけでなく `getVideoPlaybackStateForLog()` の結果も同時に出力する。
- `canplay(through)` が発火しない場合の手動開始経路は維持する。

## 17. `readyState` pollingとstartup recovery

現在版: 1766〜1821行

追加・変更内容:

- recovery試行回数と診断回数を保持する。
- 直近フレームがあれば低い `readyState` のままpollingを終了する。
- buffered rangeがあるのに `readyState < 2` の場合、最大3回 `recoverStartupStall()` を実行する。
- Safariでbufferが十分なら `readyState` を待たず起動ハンドラーへ進む。
- 手動開始ログへmedia状態を付加する。

## 18. 15秒 startup timeout の強化

現在版: 1823〜1852行

変更内容:

- timeout条件を `is_video_buffering` だけでなく `is_loading` も対象にする。
- Safariでフレームが提示されている場合、再起動せず `on_canplay()` を実行する。
- timeout時にrecovery回数、診断回数、UI状態、frame状態をログへ出す。

変更前は `is_video_buffering === false` でもloading背景だけ残るケースを検出できなかった。

## 19. destroy時のframe diagnostics解放

現在版: 2605行

追加処理:

```ts
this.resetVideoFrameDiagnostics();
```

PlayerController破棄後に古いvideo要素へframe callbackを登録し続けないようにする。

## 差分の性質

比較上の実質的な変更は、ほぼすべてライブ再生、特にSafari / WebKitの起動・復旧・診断に集中している。ビデオ再生、コメント、キャプチャ、キーボード操作などの既存機能に対する大規模な構造変更はない。

変更前ファイルは比較用として読み取りのみ行い、編集していない。

項目番号1, 6, 10, 16 は純粋なログ取り目的の変更で、その他の変更は何らかの動作に関連している。
