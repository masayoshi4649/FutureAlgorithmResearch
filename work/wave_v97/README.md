# 候補後の待機入口を比較する調査

旧J8の方向候補を起点に、即時、両気配の再進行、価格の順行、新規追尾、押しと回復の9入口を、既検証の4出口と組み合わせる。36条件すべてTOPIXミニ8枚・日経マイクロ16枚。手数料を含め、全玉を場内で返済する。

Wは既知始値0.1%の呼値切上げで、出口の初期幅Sと独立。押しは候補以後の局所高値・安値から測るため、即時新規より有利に入れるとは限らない。300秒の待機と保有は別であり、待機中の値動きを建玉利益に計上しない。

正式計算前の固定は `結果前の設計案.json`、検証完了後の凍結は `事前固定.json`。前16で参考を固定してから後15を確認するが、全31は既知の再探索であり未知性能ではない。現在API取得・実注文は行わない。

実行順は次のとおり。新しい結果ファイルがすでにあれば上書きせず停止する。

```powershell
python -X utf8 -B work/wave_v97/research.py --freeze
python -X utf8 -B work/wave_v97/research.py --run-front --workers 3
python -X utf8 -B work/wave_v97/research.py --select
python -X utf8 -B work/wave_v97/root_preflight/selection.py --root-front-select-complete
python -X utf8 -B work/wave_v97/research.py --run-back --workers 3
python -X utf8 -B work/wave_v97/analysis/assemble.py
python -X utf8 -B work/wave_v97/analysis/入口価格と取り逃しを分ける.py
python -X utf8 -B work/wave_v97/audit/full.py --formal
```

全36の注文・料金・親会計・全原板の清算時価と期間会計を独立検算する。最初の触発と全待機経路の独立再生は意味の異なる代表に限定し、その範囲を監査JSONへ保存する。最大利益より、赤字場数・平均最大赤字・共通上限単位での下方偏差を優先し、無取引は勝ちへ含めない。

生成した報告HTMLは独立会計の確認、全条件の表示照合、根の目視が揃うまで公開しない。公開後の案内は `アルゴリズム調査` の最新作業を参照する。
