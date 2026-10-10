# 作業 00052 の独立監査

最初に [独立監査まとめ.md](独立監査まとめ.md) を読む。その後、必要な証拠だけを確認する。

1. [事前の独立監査設計](事前の独立監査設計.md)：成績を読む前に定めた検査項目。
2. [入力系列](入力系列の独立監査.json)：旧 ATR 準備条件で価格を間引いていないか、観測始値の時刻。
3. [合成事例](入口と常時追跡の合成監査.json)：12 項目の手作り価格による確認。
4. [特徴・入口](特徴と入口の独立監査.json)：原本からの再計算と未来不変性。
5. [注文・会計](全注文と損益の独立監査.json)：全 920 口座の独立会計、追跡条件、幅単位の損益。
6. [表示](HTML表示の独立検査.json)：実ブラウザーでの全条件・全口座照合。画面画像は `visual/`。

再実行はプロジェクトルートで以下を用いる。すべて既存原本・売買結果は読取りのみで、現在 API や注文 API を使用しない。

```text
python -X utf8 work/wave_v55/review/check_input_lineage.py
python -X utf8 work/wave_v55/review/check_core.py
python -X utf8 work/wave_v55/review/check_features.py
python -X utf8 work/wave_v55/review/check_accounts.py
python -X utf8 work/wave_v55/review/verify_report.py --links
```
