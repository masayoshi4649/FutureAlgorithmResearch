# 価格形成の観測から新手法を構築

最初に [価格形成から組んだ新手法の検証.html](価格形成から組んだ新手法の検証.html) を開く。結論、主案の入口・途中・出口、14条件の比較、各セッション・週・30分区間の損益を1画面系統にまとめた。

## 読む順序

1. [主HTML](価格形成から組んだ新手法の検証.html)：短い説明と全損益。手法・銘柄・場を切り替えられる。
2. [規則と判定](規則と判定.md)：主案P01の正確な機械条件と結論。
3. [原理から観測への対応](../../work/wave_v52/theory/価格形成から観測へ.md)：8仮説と反証。
4. [先頭10場の観測](../../work/wave_v52/theory/前10場で確認した範囲.md)、[固定後の後半照合](../../work/wave_v52/theory/後半での照合.md)。
5. [独立監査](../../work/wave_v52/review/README.md)：未来情報の混入、状態、約定、全玉会計。
6. [確認待ちの効果を分解](../../work/wave_v52/theory/売買後の反証.md)：待つ間の戻り幅と保有中の順行。売買後の原因分析であり、入口に将来値を使用していない。

## ファイル

- [固定売買仕様](../../work/wave_v52/売買仕様固定.json)・[全損益JSON](../../work/wave_v52/売買結果.json)
- [測定定義](../../work/wave_v52/measurement/README.md)・[観測結果JSON](../../work/wave_v52/theory/観測結果.json)
- [信号と再生コード](../../work/wave_v52/backtest.py)・[原本順の約定器](../../work/wave_v52/replay.py)
- 約定CSV：`../../work/wave_v52/台帳/{手法}/{セッション}_{TOPIX|NK225}.csv`
- 判断CSV：`../../work/wave_v52/判断/{手法}/{セッション}_{TOPIX|NK225}.csv`
- 30分会計CSV：`../../work/wave_v52/区間/{手法}/{セッション}_{TOPIX|NK225}.csv`
- 例：[P01・10/06昼・TOPIXの約定](../../work/wave_v52/台帳/P01/2026-10-06_Day_TOPIX.csv)
- [約定価格だけを置換した参考感度](../../work/wave_v52/measurement/約定価格感度.json)

## 再実行

プロジェクトルートから実行する。Python、numpy、pandas、numba、orjsonを使用。画面検査には別途BeautifulSoupとChromeを使用する。

```text
python -X utf8 work/wave_v52/backtest.py
python -X utf8 work/wave_v52/review/check_backtest.py
python -X utf8 work/wave_v52/review/check_pressure_state.py
python -X utf8 work/wave_v52/build_report.py
```

原本から観測を作り直す場合は先に以下を実行する。保存済みの尺度・固定仕様は上書きしない。

```text
python -X utf8 work/wave_v52/measurement/extract.py
python -X utf8 work/wave_v52/measurement/quality.py
python -X utf8 work/wave_v52/theory/analyze.py
python -X utf8 work/wave_v52/review/check_observation.py
```

現在の入力一覧は既存の監査済み23場キャッシュを `load_ready()` から読み込む。未知の新セッションを自動で取り込む実運用プログラムではない。追加場を検証する際は入力キャッシュを作成し、固定済みの尺度を変えずに別作業として評価する。

## 範囲と数量

- 2026/09/21昼から2026/10/06昼まで23場、2銘柄。
- 主表はTOPIXミニ5枚・NK225マイクロ10枚。上限10枚・20枚以内、追加なし。最大枚数まで常に持つという意味ではない。
- 費用0、判断の次有効原本行の最終価格で約定。大口の自身の価格影響、ミニ／マイクロ固有の気配・待ち行列は再現しない。
- 全玉を各セッション内で返済。損失玉を翌場へ持ち越したり、損失玉を集計から外したりしない。
- 先頭10場を尺度算出に使用。次9場・既知最後4場は固定後の時間順再検証だが、以前の研究で既閲覧であり真の未見ではない。
- 今回の市場API取得は0回、実注文0回。原本・過去作業・App/E01は変更していない。
