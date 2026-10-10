# 作業00067：両建て保険と途中管理

**最初に見るファイル：[両建て保険と途中管理の説明と損益](両建て保険と途中管理の説明と損益.html)。** 3比較代表の短い説明、全28場・週の利益／損失／収支・枚数、5分足の新規／返済図を掲載。

読む順序：

1. [主HTML](両建て保険と途中管理の説明と損益.html)：段階両建て・同判断の縮小復帰・利益固定。
2. [全条件の途中管理比較](全条件の途中管理比較.html)：主要192と追加診断30の全条件・全28場会計。
3. [短い検証結果](検証結果.md)：保険の改善／悪化例、同幅対照、未検証の管理。
4. [主要の事前固定](../../work/wave_v70/事前固定.json)・[前半選定](../../work/wave_v70/前半選定.json)・[追加診断の事前固定](../../work/wave_v70/追加対照の事前固定.json)。
5. [独立監査の資料順](../../work/wave_v70/audit/README.md)・[公開説明の監査](../../work/wave_v70/audit/公開説明と会計の最終監査.json)・[全HTML表示照合](../../work/wave_v70/HTML表示の独立検査.json)。

## 実装と証跡

- [共通入口の資料順](../../work/wave_v70/inputs/README.md)・[入口仕様](../../work/wave_v70/inputs/入口仕様.json)・[共通入口スケジュール仕様](../../work/wave_v70/inputs/共通入口スケジュール仕様.json)。
- [途中管理エンジン](../../work/wave_v70/engine.py)：逆行グリッド、保険全体トレール、持ち替え、分割、時間短縮、利益固定、全玉の損失／利益枠。
- [縮小復帰の写像](../../work/wave_v70/net.py)・[再生と会計](../../work/wave_v70/study.py)・[保険を外した同幅診断](../../work/wave_v70/controls.py)。
- [理論と事前仮説](../../work/wave_v70/theory/管理手法の事前仮説.md)・[管理の効果と限界](../../work/wave_v70/analysis/管理の効果と限界.json)。
- [レポート生成](../../work/wave_v70/report.py)・[表示検査](../../work/wave_v70/verify.py)。

原本bookと図candle_5minは読取専用。主要結果はwork/wave_v70/results、注文・部分決済台帳はledgers。追加診断はcontrols/resultsとcontrols/ledgersへ分離。現在API取得0、実注文0。App/E01と過去の成果は変更していません。

## 再現

プロジェクトルートから実行（Python・numpy・numbaが必要。ブラウザ表示検査にはBeautifulSoupとChromeも使用）：

```text
python -X utf8 work/wave_v70/study.py
python -X utf8 work/wave_v70/controls.py
python -X utf8 work/wave_v70/select.py
python -X utf8 work/wave_v70/report.py
python -X utf8 work/wave_v70/verify.py
```

既存結果を再利用します。--freezeは今回の固定ファイルを再作成するので再現時には付けません。実装を変える研究と追加セッションは新しい作業に分けます。前16で選んだ代表を後12や追加診断の収支で入れ替えません。verify.pyは目視欄を未確認へ戻すため、画像を見てから目視確認を記録します。

実注文用アプリの改修ではなく、保存板の因果的な途中管理比較です。複数管理条件の更新を実注文へ移す際の取消・照合・部分約定は未実装です。
