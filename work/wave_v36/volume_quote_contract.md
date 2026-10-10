# 出来高通過イベント表の契約

`events.pkl` は `dict[(session, symbol)] → pandas.DataFrame`。既知13セッション×2銘柄だけを対象にする。`volume_quote_fixed.json` を全量抽出前に保存し、全原本26・旧特徴・入力・実装SHAを固定した。`volume_quote_audit.json` は全量抽出と接頭部検査の完了後にのみ作る。

1行は、隣接する有効な原本間の正の累積出来高差である。側不明、気配不安定のイベントも保存し、結果が良かった条件だけへ入力を絞らない。

|列|意味|
|---|---|
|`prev_seq/current_seq`|直前と現在の原本行。0始まり。差は必ず1|
|`prev_time_s/current_time_s`|それぞれの `CurrentPriceTime`。タイムゾーンを解釈した秒|
|`prev_volume_time_s/current_volume_time_s`|それぞれの `TradingVolumeTime`|
|`release_seq/release_time_s`|既存 `features_depth.pkl` と同じ公開行・公開時刻|
|`source_first_seq/source_last_seq/feature_row`|対応する既存素材ブロックと、その表の行位置|
|`current_price/prev_price`|両観測の現在値。全出来高がこの価格で約定したとは限らない|
|`bid/ask/bid_qty/ask_qty`|**current_seq時点**の `Buy1/Sell1` 価格・数量|
|`prev_bid/prev_ask/prev_bid_qty/prev_ask_qty`|直前行の同じ4値|
|`prev_volume/current_volume/volume_delta`|累積出来高の前後と正の差|
|`side`|現在値が現在のSell1なら+1、Buy1なら−1、他0。保有方向でも、区間全約定の主導側でもない|
|`side_qty/volume_to_side_qty`|該当側の現在最良数量と出来高差/同数量。側0は数量0・比率NaN|
|`stable`|現在値と最良両側の価格・数量が直前行と完全一致|

価格を `source_mid_last` に集約しない。同じ公開行でも複数の素材行・価格が残る。準備価格帯に使う価格・数量はイベントの `current_seq` に属し、既存素材ブロックの末尾気配と混同しない。

集計窓を後段で作る際には **公開時刻で窓を切り、実注文入力へは公開行を過去参照**する。素材時刻を使ってイベントを過去に遡らせない。同じ公開時刻の複数イベントをどうまとめるかは後段の固定仕様で決める。記録された `feature_row` は対応の証拠であり、価格情報を将来の素材末尾へ置き換える許可ではない。

板の有効性は旧 `raw_features.parse_snapshot` と同じ。これに加え、現在値・累積出来高・両時刻の欠損や不正、場外、累積量/時刻の逆行では差分履歴を解除する。逆行行を差分の基準にせず、次の有効行から再準備する。不正を跨ぐ差分は作らない。板不正・欠損と、単に正の出来高差がないことを別計数する。

`current_seq <= source_last_seq < release_seq`、両出来高時刻が公開時刻以下であることを必須とする。公開時刻より未来の出来高時刻を含むイベントは捨て、除外件数を残す。原本の接頭部だけを読んだ場合は、その末尾までに公開行が実在しないイベントを使わない。側0の比率NaNはpickle内だけで許容し、JSON監査は集計のみで非有限値を拒否する。

人工15機能群、全26原本の2境界ずつの接頭部一致と未来改変不変を検査する。実接頭部の未来改変では、境界以降の価格・数量・累積出来高・時刻を同時に変える。これは因果性と保存内容の検査で、代理の予測力を証明するものではない。注文器の再生、新損益、現在API、保存ライブは用いない。
