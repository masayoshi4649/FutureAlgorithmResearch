# 作業00066：ティック入口とIFDトレール

**最初に見るファイル：[ティック入口とIFDトレールの損益](ティック入口とIFDトレールの損益.html)。** 四機構の短い説明、前半選定結果、全場・週会計、五分足と新規／返済記録、事後黒字例を掲載。

読む順序：

1. [主HTML](ティック入口とIFDトレールの損益.html)：4手法と各セッションの損益・枚数。
2. [全192条件の比較](全192条件の比較.html)：全条件の一覧と条件別の全28場会計。
3. [短い検証結果](検証結果.md)：黒字例の正確な入口・出口、赤字の原因、検証範囲。
4. [事前固定](../../work/wave_v69/事前固定.json)・[入口仕様](../../work/wave_v69/signals/入口仕様.json)・[選定証跡](../../work/wave_v69/機構別の前半選定.json)。
5. [監査の資料順](../../work/wave_v69/audit/README.md)・[報告説明の点検](../../work/wave_v69/audit/報告説明の点検.json)・[HTML照合](../../work/wave_v69/HTML表示の独立検査.json)。

## 実装と入力

- [ティック入口](../../work/wave_v69/signals/core.py)：中値反転・再開・表示補充反転・補充突破の8系列。
- [IFDと返済エンジン](../../work/wave_v69/engine.py)：親子の次観測監視、次行気配約定、IFD-OCO、保有期限・場内返済。
- [再生と会計](../../work/wave_v69/study.py)・[前半選定](../../work/wave_v69/select.py)・[レポート生成](../../work/wave_v69/report.py)。
- [入力照合](../../work/wave_v69/prepared/入力と特徴の照合.json)・[途中切断](../../work/wave_v69/prepared/追加特徴の途中切断検査.json)・[入口の因果検査](../../work/wave_v69/signals/入口の実原本因果照合.json)。
- [損失構造](../../work/wave_v69/analysis/損失構造.json)・[現在場の一回確認](../../work/wave_v69/current/現在場の確認.json)。

原本はbook、図はcandle_5min。全192の保存結果はwork/wave_v69/results、注文・決済台帳はledgers、固定入力はprepared。保存領域以外へ書き込まない。

再現用コマンド（プロジェクトルートから。Python・numpy・numbaが必要）：

```text
python -X utf8 work/wave_v69/study.py
python -X utf8 work/wave_v69/select.py
python -X utf8 work/wave_v69/report.py
```

study.pyは既存結果を再利用する。特定条件は--idsで指定。実装を変えた探索は新しい作業に分け、今回の事前固定を上書きしない。ネットワークを遮断して保存再生し、実注文は行わない。追加セッションは今回の既知28へ混ぜず、条件を固定した別検証として扱う。
