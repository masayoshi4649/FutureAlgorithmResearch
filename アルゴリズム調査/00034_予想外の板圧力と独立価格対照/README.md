# 予想外の板圧力と独立価格対照

最初に[比較と結論](予想外の板圧力と独立価格対照.html)を見てください。**板圧力の予想外の成分に、利益を増やす効果は確認できず、今回の主案は不採用です。**

読む順序：

1. [比較と結論](予想外の板圧力と独立価格対照.html) — 固定8方式の比較、入口と返済の短い説明。
2. [全240条件の損益](全条件損益.html) — 手法ごとの各週・各セッションの利益／損失／収支、勝ち／負け／同値決済枚数。
3. [5分足と売買](５分足と売買.html) — 固定4方式×26市場セッション、全エントリーと返済。
4. [今回の到達点](../../work/wave_v39/今回の到達点.md) — 何が否定され、何を次に調べるか。

各市場1枚。TOPIXミニ・NK225マイクロの価格倍率へ換算、費用0・指定価格約定・場内全返済。初めの2セッションは学習のみで取引0。評価11セッションも既知です。新しい未知データや現在APIを取得していません。

検証は全240条件・6,240口座、代表960入力の因果確認まで完了。損益表は全32,009返済から別に集計して照合しています。多数の派生条件を独立した発見数とは扱いません。

## 再現と証跡

固定原本・実装が一致する環境で、ルートから次の順です。

```powershell
$env:PYTHONIOENCODING='utf-8'
python work/wave_v39/runner.py --workers 6
python work/wave_v39/complete.py
python work/wave_v39/chart_report.py
python work/wave_v39/chart_audit.py
python work/wave_v39/report.py
python work/wave_v39/report_audit.py
```

- [実装前の研究範囲](../../work/wave_v39/実装前の研究範囲.md)
- [全条件の固定](../../work/wave_v39/探索条件の固定.json)
- [完備監査](../../work/wave_v39/完備監査.json)
- [採否の内訳](../../work/wave_v39/assess_results.json)
- [全数表の独立監査](../../work/wave_v39/report_audit.json)
- [全売買図の独立監査](../../work/wave_v39/chart_audit.json)
- [公表確認](../../work/wave_v39/公表確認.json)
