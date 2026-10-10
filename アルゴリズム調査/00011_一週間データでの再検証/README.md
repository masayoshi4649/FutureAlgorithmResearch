# 00011 一週間データでの再検証

**最初に見るファイル：[検証結果と５分足図](一週間データでの再検証.html)**

読む順序：

1. 最初の表で、前回２候補の追加分の利益・損失・枚数を確認する。
2. 必要なら「５分足で売買を見る」を押す。詳細は自動で開く。
3. 全週成績・再選択・監査は、閉じた「詳しい検証」内に残している。

先頭表は１枚単位。追加期間は9/25 03:01以降＋9/25デイ＋9/25ナイト。
NK225の継続１枚は前回評価から−１万円として計上する（元の取引の確定利益は＋30万円）。

[文字版](検証結果.md)

<details><summary>再現手順・監査資料</summary>

再生成：`python work/wave_v16/report.py`。資料のコードは参照用コピーです。

売買から全計算を再実行する場合の順序：

1. `python work/wave_v16/details.py --final`
2. `python work/wave_v16/audit_nt_holdout.py`
3. `python work/wave_v16/correct_nt_drawdown.py`
4. `python work/wave_v16/audit_nt_holdout.py`
5. `python work/wave_v16/report.py`

凍結済み `details.py` はNTの区間極値を間引き曲線から出力するため、最初のNT監査で差を記録し、原本全行の極値へ独立補正してから報告します。
現在の配布済み表は補正後です。訂正はNTの極値と期間最大下落だけで、売買・損益・選定は変更していません。
[NT訂正記録](資料/NT期間下落_訂正記録.json) ／ [NT独立監査](資料/NT最終保留_独立監査.json)

</details>
