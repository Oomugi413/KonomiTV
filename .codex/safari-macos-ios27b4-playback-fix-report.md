# Safari macOS / iOS 27 Beta 4 Live Playback Audio Fix Report

作成日: 2026-07-21

対象:

- KonomiTV ライブ視聴画面
- macOS 27 beta 4 Safari / iOS 27 beta 4 Safari
- `client/src/services/player/PlayerController.ts`
- 関連変更: `PlayerController_20260612-to-current-diff.md` 項目15

## 症状

ライブ放送では映像が再生される一方、すべてのチャンネルで音声が出力されない場合があった。Picture-in-Pictureの開始・解除後に音声が復旧する場合もあったが、必ず復旧するわけではなかった。

## 原因

ライブ再生開始時、KonomiTVは準備中の音声を出さないため、`HTMLVideoElement` を一時的にミュートしている。ミュート解除は、起動時のbuffer調整と実フレーム提示検証が完了した後に実行される。

iOS 27 beta 3時点の変更では、SafariのMSE再生開始を妨げないように `playbackRate=0` を設定せず、通常速度で再生しながらbufferが目標秒数へ増えるのを待つようにしていた。しかしbeta 4では `currentTime` と `buffered.end()` がほぼ同じ速度で進み、再生bufferが約0.8秒のまま目標値へ到達しない場合がある。このため待機ループを抜けられず、一時ミュートの解除処理へ到達していなかった。

実機確認では、音声トラックが有効で映像も再生中である一方、`muted=true`、再生buffer約0.8秒の状態を確認した。診断目的で再生を一時停止してbufferを増やすと、待機ループ完了後に `muted=false` へ変化したため、音声codecやSafariの音声デコーダーではなく、起動処理の待機条件が直接原因と判断した。

Picture-in-Pictureで復旧する場合があったのは、切り替え中に再生クロックが一時停止し、bufferが偶然目標値を超えたためと考えられる。

## 修正

- Safariでは起動時のbuffer目標秒数到達を待たない。
- MSE初期化後に再度 `video.play()` を要求する既存処理は維持する。
- buffer秒数の代わりに、既存の `requestVideoFrameCallback()` を使った実フレーム提示検証へ進む。
- Safari以外では従来どおり `playbackRate=0` でbufferを確保する。
- Safari以外のbuffer待機中にPlayerControllerが破棄された場合、古い待機処理を終了する。

## 検証

```text
yarn lint       成功
yarn typecheck  成功
git diff --check 問題なし
```

macOS上のリポジトリには配信対象のUbuntuサーバーがないため、修正版の実再生確認にはUbuntu側でのクライアント再ビルドと配信反映が必要である。

## 2026-08-04追補: mpegts.js更新後の一時停止・再生スタール

mpegts.jsを `c69a71c809b6e0a53f7101455333f8b3d98460d0` へ更新後、PlayerControllerのSafari対策を差し戻した状態で、正常再生中に「一時停止→即再生」を行うと後続映像・音声が止まる症状をmacOS Safariで再現した。

mpegts.js側の更新本体は、Safariだけ無効化されていたAAC silent frame挿入を有効化する1行の修正である。これは音声timestamp gapの累積を直すが、PlayerControllerにあったMSE in Worker、DPlayer live sync、`play()` Promise、`readyState`、起動buffer待機の対策を置き換えるものではない。

再現直後のWeb Inspectorでは、`recoverPlayback()` が低い `readyState` を検出し、内部の `pause()` が進行中の `play()` を中断して `AbortError` を発生させる状態を確認した。この競合が、ユーザー操作による再生再開後に後続フレームが止まる直接原因だった。

修正内容:

- Safari LiveではMSE in WorkerとDPlayer direct live syncを再び無効化した（差分資料の項目3・4）。
- 非finiteな `currentTime` を安全に扱うbuffer計算を再適用した（項目5）。
- Safari Liveのbuffering recoveryから追加の `pause()` を除外し、実フレーム待機、非破壊的な `play()` 再要求、最終手段のライブ末尾付近seekの順で復旧するよう変更した（項目12）。
- 初回 `play()` を非ブロッキング化し、Safariの起動buffer停止を避ける処理を再適用した（項目14・15）。

静的検証では `yarn lint`、`yarn typecheck`、`yarn build` が成功した。OobuntuPC25への自動反映は、この実行環境から既存の対話型SSHセッションを引き継げず実施できなかったため、Ubuntu側へソースを反映してクライアントを再ビルドした後、実機で再確認する必要がある。
