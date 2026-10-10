# 作業00023：保有撤回と損失予算の再設計

最初に [保有撤回と損失上限.html](保有撤回と損失上限.html) を開いてください。

第４反復の目標「利益75%維持＋最大下落20%削減」は、両銘柄同時には達成できませんでした。

読む順序：

1. [HTMLの結論・手法別損益](保有撤回と損失上限.html)：全期間・開始週・各セッションの利益／損失／収支と勝ち・負け・差・同値の決済枚数。
2. [管理条件](管理設計の固定.json) と [研究候補の事前基準](研究候補選抜の事前規則.json)。
3. [表示値](表示データ.json) と [合算・リンク検査](報告検査.json)。

[５分足と売買](５分足と売買.html)：入口と中期方向の状態帯も表示します。状態帯は保有量ではありません。[旧主案の図解](../00022_中期方向と板の入口を分離/５分足と売買.html)と比較できます。

同じ既知13セッションに対する96入口×288管理＝27,648条件です。初回TOPIXミニ5枚／NKマイクロ10枚、追加玉なし、上限は片方向10枚／20枚。開始週は9/21の10区間と9/28の3区間。利益玉・損失玉・同値返済をすべて含み、枚数差は残玉ではありません。

損失予算は退出を始動する基準で、次行価格や呼値丸めにより超過します。部分利確後も組全体の予算を維持するため、残玉１枚の許容逆行幅が広がる場合があります。

現在APIは追加取得せず、[00022の一回照合](../00022_中期方向と板の入口を分離/中期方向と入口の検証.html#current)も探索・再生・順位・合計へ算入しません。未知検証ではありません。

追加確認：[検証付き選抜](select_verified.md)／[独立会計](selected_accounting_audit.md)／[退出と損失制限の全対応](exit_component_audit.md)／[全103,868条件の対照](探索全体対照の結果.json)。選抜の閾値や候補順位は変更していません。

次反復の設計だけを読む場合は[手法選択の反証案](../../work/wave_v28/次反復の選択設計案.md)へ。未実装・未実験・未採用の案で、今回の結果とは別です。

再現手順（プロジェクトルート、既知データだけ）：

```powershell
python -X utf8 work/wave_v28/context_runner.py --workers 12
python -X utf8 work/wave_v28/validation_round4.py --workers 8
python -X utf8 work/wave_v28/validation_round4.py --random --workers 8
python -X utf8 work/wave_v28/episode_audit.py --first-stage
python -X utf8 work/wave_v28/select_verified.py
python -X utf8 work/wave_v28/chart_report.py
python -X utf8 work/wave_v28/report_round4.py
```

結果が保存済みなら最後の報告生成だけで再作成できます。報告生成は売買・通信を行わず、00023と調査ルート目次を更新します。00022の成果、原計算、固定規則、原本は変更しません。

コード：[探索](../../work/wave_v28/context_runner.py) / [二入力エンジン](../../work/wave_v28/engine_context.py) / [反証](../../work/wave_v28/validation_round4.py) / [波診断](../../work/wave_v28/episode_audit.py) / [検証付き選抜](../../work/wave_v28/select_verified.py) / [報告](../../work/wave_v28/report_round4.py)。
