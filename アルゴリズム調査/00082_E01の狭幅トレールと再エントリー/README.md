# 狭いトレールと再エントリーの比較

最初に [狭いトレールと再エントリーの結果.html](狭いトレールと再エントリーの結果.html) を開いてください。結論と基準比較を先頭に置き、全30場と全30条件は折り畳みで掲載しています。

1. 主HTMLの結論と比較表。
2. 必要なら全30セッション損益・全30条件を開く。
3. 数値の再利用は [公開会計.json](公開会計.json)。実装と再現資料は `../../work/wave_v86`。

既存00081の戦略と結果は変更していません。現在セッション取得・実注文は行っていません。

再現コマンド（プロジェクトルート）:

```text
python -X utf8 work/wave_v86/research.py --run
python -X utf8 work/wave_v86/phase2/research.py --run
python -X utf8 work/wave_v86/analysis/analyze.py
python -X utf8 work/wave_v86/report/build.py
```
