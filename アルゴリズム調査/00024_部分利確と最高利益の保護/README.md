# 作業00024：部分利確と最高利益の保護

最初に [部分利確と利益保護.html](部分利確と利益保護.html) を開いてください。

第５反復も、両銘柄同時の「利益75%維持＋最大下落20%削減」には届きませんでした。

読む順序：

1. [HTMLの結論・手法別損益](部分利確と利益保護.html)：全期間・開始週・各セッションの利益／損失／収支と勝ち・負け・差・同値の決済枚数。
2. [管理条件](管理設計の固定.json) と [研究候補の事前基準](研究候補選抜の事前規則.json)。
3. [表示値](表示データ.json) と [合算・リンク検査](報告検査.json)。

[５分足と売買](５分足と売買.html)：入口と参考中期方向の状態帯も表示します。中期は保有撤回には使わず、状態帯は保有量でもありません。[旧主案の図解](../00022_中期方向と板の入口を分離/５分足と売買.html)と比較できます。

同じ既知13セッションに対する96入口×50管理＝4,800条件です。初回TOPIXミニ5枚／NKマイクロ10枚、追加玉なし、上限は片方向10枚／20枚。開始週は9/21の10区間と9/28の3区間。利益玉・損失玉・同値返済をすべて含み、枚数差は残玉ではありません。

K000は同じ入口の旧D273を再現する基準で、新しい改善として数えません。旧H019__D273と同一入口K000の両方に対し、各銘柄の収支75%以上・最大下落80%以下を要求します。

割合保護のRは初回枚数×初回ATR×初期損切り幅の予定損失。組の実現＋含み利益の過去最高額を保護し、部分利確前にも作動します。床は発注基準で、次行価格や呼値丸めで下回り得ます。残玉初回幅capは既存追跡に含まれるため探索から除外し、全50管理で0としています。

現在APIは追加取得せず、[00022の一回照合](../00022_中期方向と板の入口を分離/中期方向と入口の検証.html#current)も探索・再生・順位・合計へ算入しません。未知検証ではありません。

追加確認：[検証付き選抜](select_verified.md)／[独立会計](selected_accounting_audit.md)／[利益保護の全対応](protection_component_audit.md)／[探索全体の対照](探索全体対照の結果.json)／[TOPIXとNKの部分利確比率](partial_rounding_diagnostic.md)／[旧主案の最大下落の内訳](最大下落の帰属.md)。保存済み資料だけを表示しています。

再現手順（プロジェクトルート、既知データだけ）：

```powershell
python -X utf8 work/wave_v29/protection_runner.py --workers 12
python -X utf8 work/wave_v29/validation_round5.py --workers 8
python -X utf8 work/wave_v29/validation_round5.py --random --workers 8
python -X utf8 work/wave_v29/episode_audit.py --first-stage
python -X utf8 work/wave_v29/select_verified.py
python -X utf8 work/wave_v29/chart_report.py
python -X utf8 work/wave_v29/report_round5.py
```

結果が保存済みなら最後の報告生成だけで再作成できます。報告生成は売買・通信を行わず、00024と調査ルート目次を更新します。00023以前の成果、原計算、固定規則、原本は変更しません。

コード：[探索](../../work/wave_v29/protection_runner.py) / [利益保護エンジン](../../work/wave_v29/engine_protection.py) / [反証](../../work/wave_v29/validation_round5.py) / [波診断](../../work/wave_v29/episode_audit.py) / [検証付き選抜](../../work/wave_v29/select_verified.py) / [報告](../../work/wave_v29/report_round5.py)。
