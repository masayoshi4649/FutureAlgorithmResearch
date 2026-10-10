# 同じ価格帯の防御変化と突破

最初に[比較と結論](同じ価格帯の防御変化と突破.html)を見てください。**今回の主案は活動不足と赤字で不採用です。** 89比較・感度＋192方向乱数、全281条件を検算しました。

読む順序：

1. [比較と結論](同じ価格帯の防御変化と突破.html) — 固定12方式、帯から実取引へ減る理由。
2. [全281条件の損益](全条件損益.html) — 各週・各セッションの利益／損失／収支、勝ち／負け／同値決済枚数。
3. [5分足と売買](５分足と売買.html) — 固定4方式×26入力、注文と返済、採用した価格帯と試行確定時刻。
4. [今回の到達点](../../work/wave_v40/今回の到達点.md) — 不採用の理由を短く説明。

各市場1枚、TOPIXミニ／NK225マイクロ倍率への換算、費用0・指定価格約定・場内全返済。全13セッションは既知で、全方式を同じ期間で評価しました。初期2セッションの学習除外はありません。現在API・保存ライブは使用していません。

## 再現と証跡

既存の固定入力が一致する環境で、ルートから実行します。

```powershell
$env:PYTHONIOENCODING='utf-8'
python work/wave_v40/runner.py --workers 6
python work/wave_v40/complete.py
python work/wave_v40/chart_report.py
python work/wave_v40/chart_audit.py
python work/wave_v40/report.py
python work/wave_v40/report_audit.py
```

- [収支前の比較計画](比較計画.html)・[機械規則](../../work/wave_v40/状態機械の草案.md)・[独立した批判](../../work/wave_v40/実装前の独立批判.md)
- [固定した281条件](../../work/wave_v40/探索条件の固定.json)・[採否の全内訳](../../work/wave_v40/assess_results.json)
- [公開10段の照合](../../work/wave_v40/released_depth_audit.json)・[帯状態の因果](../../work/wave_v40/check_band_causality.json)・[入口の因果](../../work/wave_v40/check_entry_signals.json)
- [全7,306口座の完備監査](../../work/wave_v40/完備監査.json)・[全数表の監査](../../work/wave_v40/report_audit.json)・[全104図の監査](../../work/wave_v40/chart_audit.json)
- [公表確認](../../work/wave_v40/公表確認.json)
