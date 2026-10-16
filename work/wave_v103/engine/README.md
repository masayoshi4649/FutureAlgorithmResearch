# 新raw入口と旧固定1枚出口の接続案

正式rawの読取・正式金融再生はまだ行っていません。

旧102の`G0_Q1_X1`から、1枚・初期幅・追尾幅・初回実約定から30分・料金・場内返済を保持します。新しい状態判定の入口だけを比較します。途中の方向崩れによる返済・ドテン・増玉は追加しません。

`adapter.py`では旧`strategy.play`を通さず、旧`engine.execute`へ接続します。入口は`entry_wait_kind=0`、時計政策は`C0`、旧価格上限は無効、旧BBO追加確認は無効です。新状態が既に方向と資格を判断した後で、旧A1待機・L1の5分LP支持・C1の気配進行を再び課すと、入口比較が別の二重判定に変わります。

入力の`event`は当時判断可能になった原行の±1 pulse、`quality`と`reset`は新raw状態の既知資格です。旧5分特徴の資格をここへ再利用しません。状態の計算が遅れたら、遅い準備完了行を判断行とし、過去のsource行へ注文を逆挿入しません。

判断行の自己quoteが正常なら、その行で成行を予約し、以後の最初の正常自己quoteで実約定します。予約後の支持・品質・reset悪化だけでは取り消さず、実約定を保持します。新規受付cutでは取消が約定より先です。判断行のquoteが不明な一回pulseは予約されません。正常quoteが戻った時に状態を再確認して新しく判断する必要があり、将来の正常行を先に検索してpulseを移してはいけません。

現在案は開始後300秒、返済後30秒、新規cut300秒前の共通受付を保持します。これを変える場合は別の比較軸として結果前に固定します。

旧即時入口には、45列入口親のquantity欄だけ旧枠8／16を記録する差があります。実注文・実親・料金は1枚です。正式接続では別のraw入口診断を付け、旧quantity欄を実1枚の正答として使いません。旧金融本体の変更はありません。

`artificial.py`は両商品・買売において24人工再生、9事項36照合を行い、`新raw入口と旧固定1枚出口の人工接続.json`に結果を保存しました。これは接続と注文順の検査であり、予測の正答率・収益性・実受信順の認定ではありません。

## 独立状態の接口

`states.run(raw, item, config, python=False)` は入力 v2 の44列から必要列を読み、固定10段価格の C/R 状態を原行順に進めます。処理本体は JIT で、Python 対照も同じ接口です。配列は変更しません。`item['tick']` と条件の family、strength、use_supply、use_volume を用います。

返り値は `qualified`、`volume_direction_proxy`、`ready[N,2]`、`anchor_raw_seq[N,2]`、`phases[N,2]`、疎な22列 `events` とその列/理由定義です。列0は買いの実参加方向、列1は売りの実参加方向です。状態の想定方向は R では参加方向の反対です。`event_raw_seq` と `event_anchor_raw_seq` は int64 で保存し、float の段階表から原 seq を復元しません。

`states.pulses(own, peer, own_raw, peer_raw, use_peer=True)` は、同じ入口思想の相手の厳密過去・最初公表源を照合し、`event[N]`、`peer_rows[N]`、当時の `decisions` を返します。自己 episode は一度だけ消費します。相手なし対照は同じ自己資格のまま相手照合だけを省きます。

`states.union_pulses(components, own_raw)` の components は C/R ごとに own、peer、peer_raw を持ちます。消費済を含む現在の全 ready を競合判断へ使い、現在の有効方向が一つかつ未消費 episode がある時にだけ単一 pulse を返します。

状態台帳の22列は、判断原行、想定方向、参加方向、出来事、破棄理由、段階、基準/準備/回復/移動/確認/初回価格移動の各原行、基準時計、基準 bid/ask、固定 p、初回反対側数量 Q0、固定支持 r、初回同側数量、活動付き表示減少、初期代理出来高、移動後代理出来高です。C/R の ID と寿命は独立です。分母は初回量へ固定し、数量不足の間の出来高を確認段階へ遡及しません。

## 実数量配分の接口

`adapter.raw_config(previous, quantity=1, symbol=None)` は各腿の実数量を旧固定出口へ接続する設定を返します。`adapter.raw_entry_diagnostics(record, output, decisions=None)` は物理新規から正しい枚数と判断/約定の原行を作り、旧45列の枠枚数診断を正答に使いません。

`adapter.join_portfolio_outputs(legs, allocations, symbol)` は、C/R の実再生結果から物理注文・親・玉を結合します。C=0/R=1、親/玉/UID は偶奇の衝突しない名前空間です。料金は各腿の注文で切り捨てた実額を足し、合計枚数を一注文へまとめ直しません。`curve` と `source_curve` は同じ自己執行原行で全玉時価を足します。6列 `target_trace` と同時最大値を用い、個別最大値の足算を実際の最大保有とはしません。会計の旧内部名 J2/O06 はそれぞれ C/R に対応し、意味を表示資料へ明記する必要があります。

`state_artificial.py` の補足07確定証跡は、状態105素材の Python/JIT 一致、単一14条件の売買28例、厳密過去接続、支持回復後の消費、実配分12例の旧独立会計、両建てと非同時最大の整合を確認しています。準備・回復行の同時価格移動は観測だけ記録し、移動段階を次別行へ分ける48例も含みます。初回人工証跡とその source は履歴として保持しています。正式原行での活動・接頭不変と金融収益はこの証跡の範囲に含みません。

`prefix_preflight.py` は計画保存と許可後実行を別引数にしています。固定2場・C1/R1・両商品を用い、準備/移動/確認/paired pulse の境界を切断して比べます。不成立の場合は固定60/300/900秒の接頭を選び、不成立の事実を保存します。各接頭後512行への6未来改変を検査し、後方全場の改変完了とは称しません。`prefix_artificial.py` はこの helper の人工6境界・36未来局所及びpair比較を完了しています。

実接頭は根の指示により指定2場の4口座・8単一・44接頭で完了しました。局所/pair/union の切断各44と未来変更各264が一致しました。ただし指定2場の全単一 paired pulse は0で、非ゼロ実pulseの接頭は未検証です。その不存在と自己状態の成立範囲を `固定2場の実状態と二市場pulseの接頭不変.json` に保存しています。

## 金融接続の共通呼出し

`finance_adapter.play(prepared_value, activity_account, pulse_id, quantity=1, finish=True)` を根の研究runnerから呼びます。prepared_value は一度準備した `record`、`signal`、`reference_open` です。活動cacheを再計算せず、同じraw原行の `normal_event` と共通資格を渡します。四reset理由のORを normal_reset に使い、非対応raw候補を将来normalへ移しません。判断台帳は normal行と元raw行・raw_seq・時計・自己相手lineageを分離して実新規へ結びます。

`signal['trend_width']` は旧Dのまま浅いcopyで保持します。Sは保存始値×旧 `trend_initial_stop_bp`/10000 を旧と同じ呼値式で切り上げ、最低2呼値とします。固定1枚又は各腿の実数量・増玉なし・初回fill後30分・料金・場内返済を旧102本体へ渡します。受付外pulseも入力に残し、旧execute自身が同じ開始300秒後/停止300秒前とcut優先で拒否します。

人工Pythonは prepared_value の `人工Python=True` と明示人工recordだけに限定します。`finish=False` は根が用意した接頭recordで未来の場末清算を作りません。rootの正式金融事前固定後の呼出し以外に、全32損益を自動実行するCLIやloopはありません。接口人工では単一買売4、実配分12、非normal投影・保有中消費・受付外・cut優先・予約後悪化・料金丸め・flat及び旧会計を確認しています。
