# 再集計資料

条件一覧・全条件集計・選択記録・全売買数値とその形式・独立監査を保存しています。

Pythonファイルは参照用です。実行する場合は元プロジェクトルートの `work/wave_v10` を使用してください。価格原本、過去版の監査済み特徴、確定足は元の保存場所を参照します。

保存データの再計算：`python work/wave_v10/research.py`

取得済み現在照合の再計算：`python work/wave_v10/live_check.py --evaluate`

報告生成：`python work/wave_v10/prepare_report.py` の後に `python work/wave_v10/report.py`
