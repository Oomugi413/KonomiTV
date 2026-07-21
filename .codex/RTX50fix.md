# RTX 50 シリーズ向け NVEncC 対応まとめ

- Codex セッション ID: `019f8353-44ae-7bb0-a00c-75d4f18ccdb8`
- 対象: KonomiTV Linux x64 / Ubuntu 24.04 / NVIDIA GeForce RTX 50 シリーズ
- 実装コミット: `0f031493 Build NVEncC 9.25 with configurable CUDA`
- GitHub への push: 未実施（ローカルは `origin/master` より1コミット先行）

## 原因

従来の NVEncC 9.17 / CUDA 11.2 ビルドは動作した一方、手動配置した新版は KonomiTV の「エンコードを開始しています」で停止した。RTX 50 シリーズ向けのネイティブ CUDA コードを含む、依存関係が整合したスタンドアローン版を作り直す必要があった。

## 修正内容

- `.github/workflows/build_thirdparty.yaml` の Linux amd64 Thirdparty ビルドで、NVEncC のソースビルドを配置・圧縮より前に実行するよう変更。
- NVEncC は数値タグ `9.25`、FFmpeg は `8.1.2` に固定。SVT-AV1 の個別バージョン固定は撤廃し、SVT-AV1 4.1.0 でビルドを確認。
- CUDA は `NVENCC_CUDA_VERSION` 一か所で変更可能にし、現在は `12.8.1`。厳密な CUDA バージョン一致検査は設けていない。
- Ubuntu 24.04 の NVIDIA CUDA devel イメージでビルドし、`sm_120` cubin、NVEncC バージョン、共有ライブラリ依存を検証。
- upstream `build_scripts` の Linux Vulkan Loader 静的リンク不備を Dockerfile 内で補正。
- `.build/NVEncC/` に成果物・ログ・再利用可能な BuildKit キャッシュを保存し、Git/Docker コンテキストから除外。
- ローカル再現用 `build_nvencc_local.sh` と成果物検証用 `verify_nvencc.sh` を追加。

## 検証結果

- NVEncC 9.25 / CUDA 12.8 / FFmpeg 8.1.2 の通しビルドに成功。
- `sm_120` cubin を84個検出し、必須ライブラリの静的リンクを確認。
- RTX 5070 Ti と実録画 TS を使った KonomiTV 相当のエンコード試験で、5,570フレームを約9秒・568.19fpsで処理し、正常終了（終了コード0）。
- KonomiTV でのユーザーによる再生試験も成功。
- `server/thirdparty/NVEncC/NVEncC.elf` を9.25へ更新し、旧9.17は `NVEncC.elf.old` に退避。
- GitHub Actions の処理順が `NVEncC build → x64 deploy → Thirdparty compress → artifact upload` であること、および Dockerfile の BuildKit 静的検査が警告なしであることを再確認。

## 主なローカル成果物

- ビルド済みバイナリ: `.build/NVEncC/output/NVEncC.elf`
- ビルド情報: `.build/NVEncC/output/BuildInfo.txt`
- 成功した通しビルドログ: `.build/NVEncC/logs/build-20260721-213955.log`
- 実 GPU 試験ログ: `.build/NVEncC/logs/runtime-smoke.log`
