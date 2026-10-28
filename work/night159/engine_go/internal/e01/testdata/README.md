# 一致検証用の固定入力

通常運転ではこのフォルダを読みません。`go test ./...` だけでPythonなしに照合できます。

- `historical_orders.json.gz`：2026/10/01 Night・10/02 DayのNK225/TOPIXから準備済みの因果的入力と、既存Pythonの期待注文。683,854観測・67注文。
- `python_orders.json.gz`：上昇・下降・往復・急変を組み合わせた人工系列。29,600観測・448注文。
- `python_features.json.gz`：確定足の実受信時刻、二市場、中値変化から求めたPythonの期待指標。1,800観測。

生成元は既存 `00045_E01リアルタイム仮想トレード/papertrade` です。作業時の生成スクリプトはリポジトリルートの `work/go_e01_validation/export_parity.py` にあります。期待値の生成にGoの実装は使っていません。
