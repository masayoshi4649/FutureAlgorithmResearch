# 独立監査の読み順

最初に [独立監査まとめ.md](独立監査まとめ.md) を参照してください。

1. [事前の敵対的設計.md](事前の敵対的設計.md)：成績を見る前の監査提案。採用仕様とは区別します。
2. [状態と固定Rの合成監査.json](状態と固定Rの合成監査.json)：固定線・期限・状態消費・異常約定。
3. [特徴の独立監査.json](特徴の独立監査.json)：非重複の数量、過去中央値、単位変換、未来改変。
4. [入口の独立監査.json](入口の独立監査.json)：全銘柄名入替・価格単位変換・未来切断。
5. [金額と固定Rの独立監査.json](金額と固定Rの独立監査.json)：全644口座の円・実効R・計画R。
6. [説明用結果の独立監査.json](説明用結果の独立監査.json)：中値価格置換・固定障壁先着・確認後反応。
7. [HTML表示の独立検査.json](HTML表示の独立検査.json)：ブラウザの全選択と数値・図。

再実行はプロジェクトルートから行います。

```powershell
python -X utf8 work/wave_v54/review/check_core.py
python -X utf8 work/wave_v54/review/check_features.py
python -X utf8 work/wave_v54/review/check_signals.py
python -X utf8 work/wave_v54/review/check_accounts.py
python -X utf8 work/wave_v54/review/check_analysis.py
python -X utf8 work/wave_v54/review/verify_report.py --links
```

原本・既存結果・APIは変更しません。表示検査は旧監査の描画補助関数を読み取り利用します。ローカルChromeをネットワーク遮断プロキシ付きで起動し、画像を `visual/` へ保存します。
