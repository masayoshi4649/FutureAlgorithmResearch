# 00104の公開と表示QA

**正式結果と公開は完成し、reportのcheck-onlyは合格済み。Chrome実行と目視は根が行う。** 金融の再実行、packet/台帳/raw/NPZ/API読取はこの手順に含まない。

作業ディレクトリ：`S:\GitHub\masayoshi4649\FutureAlgorithmResearch`

## 1. 根の指示後、小会計だけを確認

```text
python -B work/e01_cross_market_20261014/report.py --check-only --result work/e01_cross_market_20261014/engine/finance/結果.json --fixed work/e01_cross_market_20261014/engine/金融事前固定.json --plan work/e01_cross_market_20261014/engine/試行計画.json
```

出力ファイルは作らない。正式20源、全16条件のcase指紋、計画・固定・完成結果、基準同値、五寄与、全33/前16/後17/上位三場除外、買売と境界を照合する。台帳は読まない。

成功時は `全合格:true`、`表示条件:17`、`全場口座:1122`、`全場金額枚数セル:5780`、`公開:false`。修正16条件の両商品黒字数・三基準達成数は完成結果から動的に求める。未達を成功に数えない。

## 2. 根のレビュー後だけ公開

```text
python -B work/e01_cross_market_20261014/report.py --root-publish --result work/e01_cross_market_20261014/engine/finance/結果.json --fixed work/e01_cross_market_20261014/engine/金融事前固定.json --plan work/e01_cross_market_20261014/engine/試行計画.json
```

既定の出力先：`アルゴリズム調査/00104_E01の銘柄差の原因と修正検証`

- `E01の銘柄差と修正後の全セッション損益.html`
- `E01の銘柄差と固定16対照の公開会計.json`

公開直前にも同じ検算を行う。公開先を変える場合だけ `--output-dir` を追加する。正式source・金融結果・共通知見は変更しない。

## 3. 表示QAの導線

新HTMLと同じフォルダの公開会計JSONを正解資料にする。既存の `work/wave_v106/loss_anchor_view.py` の隔離Chrome方式を参考にするが、四切替固定の旧QAを新HTMLへそのまま実行しない。今回の選択要素は `#case`（初期B03）、全場領域は `[data-case]`、概要は `#main-overview`、四群の折畳みは `#selected-overview`、全条件の折畳みは `#all-overview`。

prepared QA：`python -B work/e01_cross_market_20261014/report_view.py --root-reviewed`。その前に `--check-only` なら公開2小資料の静的照合だけ行いChromeは0。`--prepare-only` は公開の有無にかかわらず実行予定だけ表示する。QA sourceは旧 `work/wave_v52/review/verify_report.py` の隔離rendererをメモリ上で利用し、旧sourceへ書かない。

1. 1450px・520pxで暗色、本文の横はみ出し、表内横スクロール、タイトル・冒頭四原因を確認。
2. `#case` の基準＋16選択肢を全て切り替える。各表の33場名＋合計、TOPIX/NKの利益・負の損失・収支・勝ち決済枚数・負け決済枚数、**17×34×10＝5,780セル**を公開会計の同IDへ照合。
3. 主表は基準/B01/B03の3条件×2商品＝6行。四群代表は基準＋4代表の10行、全一覧は17条件×2商品＝34行で、両方折畳み。全11列と両商品共通判定を同IDへ照合。群代表の選択は全場の事後選択であることを確認。
4. 各条件の上位三場除外・前16/後17・買売を展開して同会計へ照合。買売の枚数は勝敗**親の建玉総数**、主表は**決済玉の勝敗枚数**であり、両者が常に同じとは扱わない。
5. `NaN`、`Infinity`、空の未定義額、外部通信、条件切替時の別条件混入が無いことを確認。未定義は「—」又は「未定義」。
6. 1450px・520px・補足展開の画像を保存し、根が目視してからQA完了とする。証跡にはHTML/公開会計/report/QA sourceのSHA、照合件数、画像位置、根の目視状態を記す。

**原因の扱い：** TOPIX7敗中6敗の黒字不経験・元GUの拘束、NK買＋4/売＋3,382は旧基準の保存診断。公開後の不利価格/拡幅は旧43親の資格測定であり、新条件の収益や避けた損失へ置き換えない。修正後損益は正式16会計だけから掲載する。

## 小会計確認済みのsource

`report.py` SHA256：`f5e2f4467dcaeed9c36a0a02b0ee174e730255dbb3d27f0d3c477397409446a5`

check-onlyは17条件・1,122口座・5,780数値セルの会計照合に合格。修正16中、両商品黒字4・両商品三基準1（B03）。公開は根が完了。Chrome実行、画像作成、目視は未実施。固定dailyの円単位往復による1ULP差の初回失敗と、表示変更前source・追補の変数名衝突失敗は `report_archive` に保持した。金融source・結果は変更していない。
