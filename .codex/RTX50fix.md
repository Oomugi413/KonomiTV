# RTX 50 シリーズ向け NVEncC 対応まとめ

## 原因

従来の NVEncC 配布バイナリでは、NVIDIA GeForce RTX 50 シリーズ（Blackwell）でエンコードが正常に進まない問題があった。

## 現在の対応

- Blackwell 対応を加えた [`Oomugi413/NVEnc`](https://github.com/Oomugi413/NVEnc) のリリースを使用する。
- NVEncC のバージョンは `9.25.1` に固定する。
- Windows x64 では `NVEncC_9.25.1_x64.7z`、Linux x64 では `nvencc_9.25.1_amd64.deb` をダウンロードする。
- Windows / Linux ともに、ライセンスファイルを含めてフォークリポジトリから取得する。
- `.github/workflows/build_thirdparty.yaml` で配布アーカイブを展開し、KonomiTV の Thirdparty アーカイブへ収録する。
- Linux 版では、展開した `nvencc` を `NVEncC.elf` として配置し、同梱ライブラリを参照できるよう RPATH を設定する。

## GitHub Actions の実行環境

- Windows x64: `windows-2025`
- Linux x64: `ubuntu-26.04`
- Linux arm64: `ubuntu-26.04-arm`
- Ubuntu 26.04 では実パッケージ名の `7zip` と `patchelf` を明示的にインストールする。
- Linux 向け成果物の実行環境互換性を維持するため、tsreadex・psisiarc・psisimux・Intel Media Stack などのビルドには、引き続き Ubuntu 20.04 ベースのコンテナを使用する。

## Linux 版パッケージの展開

`nvencc_9.25.1_amd64.deb` のデータアーカイブは `data.tar.zst` 形式で格納されている。

GitHub Actions `Build Thirdparty Libraries #33` では、Ubuntu 22.04 の p7zip 16.02 が Zstandard を展開できず、直前に展開した QSVEncC の `data.tar` が再利用された。その結果、`usr/bin/nvencc` が作成されず、コピー処理が失敗した。

Ubuntu 26.04 に収録される 7-Zip 26.00 は、この Debian パッケージ内の `data.tar.zst` を展開できる。これに合わせて Linux x64 / arm64 の runner を Ubuntu 26.04 へ更新した。

## 検証状況

- フォークリポジトリの Windows x64 / Linux x64 向け `9.25.1` リリースアセットが取得可能であることを確認済み。
- Linux の Debian パッケージに `usr/bin/nvencc` が含まれることを確認済み。
- Windows ジョブでは、NVEncC `9.25.1` のダウンロード・展開を含む Thirdparty アーカイブ生成に成功済み。
- 7-Zip 26.00 で Linux の Debian パッケージを展開できることを確認済み。
- Ubuntu 26.04 runner へ更新したワークフロー全体の完走確認は、次回の GitHub Actions 実行で行う。
