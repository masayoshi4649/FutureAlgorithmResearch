# 再現方法

最終結果は `検証結果.md`。主候補は当日の指定下落を逃したため、運用採用とはしない。

プロジェクトルートで次を実行する。Python、numpy、pandas、matplotlibを使用。再生・報告・試験はネットワークに接続しない。

```powershell
python -X utf8 work/wave_v4/report.py
python -X utf8 work/wave_v4/diagnostics.py
python -X utf8 work/wave_v4/plot_results.py
python -X utf8 work/wave_v4/plot_results.py --reference-cusum
python -X utf8 -m unittest discover -s work/wave_v4 -p "test_*.py"
```

保存済み当日を同じ固定条件で再生するだけなら `python -X utf8 work/wave_v4/current_check.py replay`。実行の都度取得する処理ではない。

`current_check.py fetch` は今回一度だけ使用済み。取得開始記録が存在すれば再取得を拒否する。記録を消して取り直さない。固定時刻・コード／入力ハッシュは `固定設定.json`、取得時刻・URL・結果・SHA-256は `一度取得_2026-09-23_Day/取得記録.json`。

全探索のコードは `research.py search` → `extend_search.py` → `regime_search.py` → `opening_search.py`。これらは各段階の探索成果物を再生成する。現在側は探索に含めない。凍結後のコードを変更すると答え合わせ処理は停止する。元データにアクセスするだけで原本には書き込まない。

`python -X utf8 work/wave_v4/run_null.py work/wave_v4/固定設定.json` はコイントスの再現。`python -X utf8 work/wave_v4/duration_check.py` は評価期間、`python -X utf8 work/wave_v4/raw_candidate_check.py` は生板観測の診断。コマンドの引数詳細は各スクリプトを参照。

名前に「採用」を含むファイルは固定時の主候補の記録を意味し、最終的な実運用採用を意味しない。主候補の正本は `固定設定.json`、全取引は `主候補_全取引.csv`。
