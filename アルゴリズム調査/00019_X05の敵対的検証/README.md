# 作業00019：X05の敵対的検証

**最初に見るファイル：[敵対的検証.html](敵対的検証.html)**。冒頭に結論と主要反証、展開欄に週・セッション別の損益を掲載。

読む順序：

1. [敵対的検証.html](敵対的検証.html) または [短い報告](検証結果.md)
2. [論理監査](logical_audit.md)、[注文執行監査](exec_adversarial.md)、[統計監査](statistical_adversarial_結論.md)
3. 詳細JSONと再現コード。`枝除去と感度.json` は30条件、`対応を入れ替える検査.json` は24順列、`無関係な選択の全結果.json` は２方式×128乱数。それぞれ銘柄別・セッション別集計を含む。

同じ作業の元コードは `work/wave_v24`。このフォルダの `.py` は記録用コピーで、実行時の相対依存先を変更していない。プロジェクトルートから以下を実行する。

```powershell
python work/wave_v24/counterfactual.py
python work/wave_v24/exec_adversarial.py
python work/wave_v24/branch_attribution.py
python work/wave_v24/statistical_adversarial.py
python work/wave_v24/build_report.py
```

依存：既存のPython環境（NumPy、pandas、Numba等）、`work/wave_v23` のコード・保存済み入力・信号・前回結果。旧コード・入力のSHA256を監査JSONに記録。生データを重複コピーせず、現在APIの再取得も行わない。報告の再生成だけなら最後のコマンドのみ。

主前提は費用０・指定価格約定・各１枚・場内返済。約定価格変更と遅延は補足診断。最大勝ち除外や再抽出は既知標本の依存性検査で、未知相場の保証ではない。今回の診断条件から新しい最良手法は選ばない。

[前回00018](../00018_市場原理からの再探索/README.md)を上書きせず、今回の評価修正を別記録とした。
