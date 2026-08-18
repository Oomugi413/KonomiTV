# ariblib 解析失敗の原因と修正内容

## 追跡情報

- 調査対象: `/mnt/recording/20260728_＜アニメギルド＞最強出涸らし皇子の暗躍帝位争い　#4.hevc.ts`
- エラーログ: [KonomiTV-error.log](/home/oomugi413/git/KonomiTV/.codex/KonomiTV-error.log)
- Codex session ID: `01a01422-cae8-7a13-981a-1dc1e5a19f6e`
- 修正版リポジトリ: [Oomugi413/ariblib](https://github.com/Oomugi413/ariblib)
- ariblib 修正コミット: [`ca080d5`](https://github.com/Oomugi413/ariblib/commit/ca080d5)

## 原因

TS ファイル自体の破損が原因ではない。`ffprobe` では MPEG-TS として正常に認識でき、映像・音声・字幕・ EPG のストリームも取得できた。

KonomiTV の録画メタデータ解析は、優先サービス `service_id=181` の EIT を `ariblib.event.Event` で解析する。その中に、次の音声コンポーネント記述子が含まれていた。

```text
stream_content = 0x02
component_type = 0x23  # 35 (decimal)
```

これは対象番組の次番組情報に含まれる副音声側の記述子で、AAC 音声として記録されている。`ariblib` の音声用 `COMPONENT_TYPE[0x02]` には `0x23` の定義が存在しなかった。

`ariblib/event.py` は未知の値に対するフォールバックを持たず、次の辞書参照で `KeyError: 35` を発生させていた。

```python
COMPONENT_TYPE[acd.stream_content][acd.component_type]
```

該当箇所は [ariblib/event.py](/home/oomugi413/git/KonomiTV/server/.venv/lib/python3.11/site-packages/ariblib/event.py:73)、呼び出し元は [TSInfoAnalyzer.py](/home/oomugi413/git/KonomiTV/server/app/metadata/TSInfoAnalyzer.py:541) である。`TSInfoAnalyzer` の例外処理は `KeyError` を捕捉しないため、1 件の未知の音声コンポーネント記述子によって録画全体のメタデータ解析が失敗していた。

## 変更内容

### KonomiTV の実行環境での確認用変更

解析動作を確認するため、KonomiTV の仮想環境内にある次のファイルへ一時的に追加した。

[server/.venv/lib/python3.11/site-packages/ariblib/constants.py](/home/oomugi413/git/KonomiTV/server/.venv/lib/python3.11/site-packages/ariblib/constants.py:215)

```python
COMPONENT_TYPE[0x02][0x23] = '未定義'
```

この定義名は、実際の意味を推測して別の音声種別名を付けるのではなく、放送データ上の未定義値をそのまま表すためのもの。これにより `Event` は未知値で停止せず、イベント情報の解析を継続できる。

### Oomugi413/ariblib への修正

[ariblib/constants.py](/home/oomugi413/git/ariblib/ariblib/constants.py:215) に同じ定義を追加した。

```python
0x23: '未定義',
```

このリポジトリには、今回の音声定義に加えて、先行して追加した 8K 映像 `0x83` と H.265 用の `0x09` 系コンポーネント定義も含まれている。

パッケージバージョンは `0.1.5` に更新した。

- [ariblib/__init__.py](/home/oomugi413/git/ariblib/ariblib/__init__.py)
- [VERSION.md](/home/oomugi413/git/ariblib/VERSION.md)

## KonomiTV 側の変更ファイル

- [.codex/AriblibFix.md](/home/oomugi413/git/KonomiTV/.codex/AriblibFix.md): 原因・修正内容・検証結果の記録
- [server/pyproject.toml](/home/oomugi413/git/KonomiTV/server/pyproject.toml:19): ariblib v0.1.5 wheel のダウンロード URL
- [server/poetry.lock](/home/oomugi413/git/KonomiTV/server/poetry.lock:270): ariblib v0.1.5 のバージョン・URL・SHA256

なお、`server/.venv/lib/python3.11/site-packages/ariblib/constants.py` の変更は動作確認用の仮想環境内だけの変更であり、Git 管理対象ではない。

### wheel

次の wheel を `python3 setup.py bdist_wheel` で生成した。

[ariblib-0.1.5-py3-none-any.whl](/home/oomugi413/git/ariblib/dist/ariblib-0.1.5-py3-none-any.whl)

- wheel 内のメタデータでバージョン `0.1.5` を確認
- wheel 内の `constants.py` に `0x23: '未定義'` が含まれることを確認
- zip 整合性検査に成功
- SHA256: `356a2101fe37ed5507aaf3d156bf01efd93e574265befa2148bedfded465edf4`

## 修正後の確認

フォーク側の `ariblib` を読み込んで対象 TS を再解析し、サービス 181 の EIT 1,821 セクション・イベントを全件処理できることを確認した。`KeyError: 35` は再発していない。

## 今後の反映に関する注意

KonomiTV の `.venv/site-packages` へ直接加えた変更は、依存パッケージの再インストールで失われる可能性がある。永続的に反映するには、`Oomugi413/ariblib` の変更をコミット・プッシュしたうえで、KonomiTV 側の依存先または配布 wheel を `ariblib 0.1.5` に切り替える必要がある。

`~/git/ariblib` の変更はコミット `ca080d5` としてコミット済みで、[Oomugi413/ariblib の master ブランチ](https://github.com/Oomugi413/ariblib/tree/master)へプッシュ済み。
