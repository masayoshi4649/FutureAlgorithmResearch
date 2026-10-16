# 試行履歴と事前照合

試行条件・重複点検・登録履歴と照合ツールを、共通領域からこちらへ移しました。知見本文の更新先は [共通のMarkdown](../../共通/知見台帳/README.md) です。

- [data/trials.json](data/trials.json)：既存の試行と変更理由。
- [proposal.sample.json](proposal.sample.json)：新しい計画の形式。
- `manage.py`、`duplicate_check.py`：計画の事前照合・登録。
- `data/rules.json`、`knowledge.json`、`studies.json`：移行前の知見・資料索引。過去の根拠を確認するために保持。
- `data/history/`：登録時の履歴。検査資料とテストコードも保持。

プロジェクトルートから実行します。

```text
python -X utf8 アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py check --proposal work/新計画.json
python -X utf8 アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py register --proposal work/新計画.json
```

照合・登録は金融検証を実行しません。登録時の旧形式の生成物もこのフォルダ内に限られ、共通のMarkdownには書き込みません。知見の追記に旧ビューの生成は不要です。
