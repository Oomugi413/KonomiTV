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
