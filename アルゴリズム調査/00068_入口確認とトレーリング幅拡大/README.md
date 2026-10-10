# 作業00068：入口確認とトレーリング幅拡大

**最初に見るファイル：[入口確認と幅拡大の説明と損益](入口確認と幅拡大の説明と損益.html)。** 入口のみ・幅のみ・同時変更の3比較、少数黒字参考、全場／週損益・枚数、方向先着率、五分足売買図。

読む順序：

1. [主HTML](入口確認と幅拡大の説明と損益.html)：短い説明と対照、全29場・週会計。
2. [全432条件の比較](全432条件の比較.html)：全条件と前16／後12／追加デイの分離会計。
3. [短い検証結果](検証結果.md)：入口確度、幅単独の効果、少数黒字例の限界。
4. [事前固定](../../work/wave_v71/事前固定.json)・[前半選定](../../work/wave_v71/前半選定.json)・[事前仮説](../../work/wave_v71/theory/入口確認と幅拡大の事前仮説.md)。
5. [監査の読む順](../../work/wave_v71/audit/README.md)・[公開説明と会計の監査](../../work/wave_v71/audit/公開説明と会計の最終監査.json)・[全HTML表示検査](../../work/wave_v71/review/HTML表示の独立検査.json)。

## 実装と証跡

- [入口確認の読む順](../../work/wave_v71/inputs/README.md)・[確認仕様](../../work/wave_v71/inputs/入口確認の事前固定.json)・[確認エンジン](../../work/wave_v71/inputs/core.py)。
- [比較と会計](../../work/wave_v71/study.py)・[選定](../../work/wave_v71/select.py)。管理は[旧00067エンジン](../../work/wave_v70/engine.py)と[縮小復帰写像](../../work/wave_v70/net.py)を変更せず使用。
- [入口の方向診断](../../work/wave_v71/analysis/入口方向の独立診断.json)・[追加デイ入力](../../work/wave_v71/prepared/追加デイの入力照合.json)。
- [レポート生成](../../work/wave_v71/report.py)・[表示検査](../../work/wave_v71/verify.py)。

成果と台帳はwork/wave_v71/resultsとledgersへ保存。既知28場はwave_v69/preparedとwave_v70/inputsを読取り再利用、追加10/09デイはwave_v71/preparedへ独立抽出。book・candle_1min・candle_5minは読取専用、現在API取得0、実注文0。実注文アプリの変更ではなく研究用の保存板再生。

## 再現

プロジェクトルートから（Python・numpy・numba・pandas、表示検査にはBeautifulSoupとChrome）：

```text
python -X utf8 work/wave_v71/study.py
python -X utf8 work/wave_v71/select.py
python -X utf8 work/wave_v71/report.py
python -X utf8 work/wave_v71/verify.py
```

study.pyは既存結果を再利用する。--sourceで6入口の一つを指定して分割できる。既存の入口や固定を再作成しないため--freeze、inputs/prepare.py、prepare_extra.pyは再現時に実行しない。新条件や追加場の研究は別作業へ分け、今回の前半順位は後半損益で変えない。

verify.pyは目視欄を未確認へ戻す。生成画像を見た後に目視確認を記録する。未知期間の収益性や実商品約定を保証する検査ではない。
