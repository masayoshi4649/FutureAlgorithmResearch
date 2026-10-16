# 仮説価格境界の最小執行接口

根の [数値設計案.json](../数値設計案.json) に基づくsourceと人工検査を準備しました。正式104金融は未実行です。初期の接口草案は履歴として保持しています。

新B/T出口は、同一raw行から投影された自己C/R候補と当時の固定支持価格を受けます。flat、新規予約、保有、返済予約だけを持ち、判断後の別正常quoteで約定します。新規予約後の支持悪化、量不明、後の反発を使って過去の約定を取り消しません。

途中判断は支持境界、始値比の初期保険、価格高安の追尾、費用回収床を分離し、各hitと有効線の所有者を記録します。量の取消・補充や入口期限だけを保有の反転証拠にしません。入口を作る部分と、保有を降りる部分の情報資格は別にします。

旧対照Oは103のfinance_adapterとadapterのexact-bytes snapshotを104だけに置き、旧S/D/30分を保持します。104の同じnormal event/entry_quality/entry_resetを直接旧執行へ渡し、Oだけ旧qualifiedから作り直しません。旧103 sourceは不変更で、JIT cacheは104専用です。人工OWN同入口の注文・会計nullを確認済みで、正式32の旧経済nullは別検査です。

共通呼出しは `interface.play(prepared_value, normal_case, exit_id, quantity=1, finish=True, python=False)` です。prepared_valueは一度準備したrecord/signal/reference_open、normal_caseはpeer APIのnormalをそのまま渡します。配分は同入口を各実数量で再生し、`interface.join`で物理注文と同原行時価を合算します。

coreの返り値は旧accounting互換のorders/trades/growth_cohorts、含み損と残玉料込みcurve/source_curve、6列target_traceに、支持/初期保険/広trail/利益trail/費用床の独立hit・有効線所有者・候補消費・stale評価flagを加えています。`initial_risk_yen`は停止線での費用後予定損失のsigned値であり、次quoteでの実損失上限ではありません。

人工はPython/JIT一致880、旧独立会計86例、両商品買売の全5新出口20、利益床8、予約/cut/不明quote4ずつ、実配分12、接頭2を確認しています。広trailの実発動、120秒超保有と支持固定、保有中消費、返済後30秒、未来変更の過去不変も追加人工で確認しました。初回source/proofと補助scriptの構文Falseは履歴保存しています。

条件121、順位指標、全セッション金融のループは根の所有です。新engine単独には正式全金融を自動開始するCLIを作っていません。
