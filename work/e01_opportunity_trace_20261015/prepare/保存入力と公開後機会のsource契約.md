# 元公開と継続中の参加機会を調べる準備

この段階はソース契約の調査だけです。新アルゴリズム、金融、登録、原板・packet・cache・NPZ・台帳本文・APIの読取は行っていません。00111の17源は不変です。機会数と効果は未測定です。

現在の元新規はpaperの公開行で一度だけ審査します。静観、開始後300秒、票の未知・不足・釣合い、忙しい実玉、公開費用余裕などで拒否されても、FAKが最初の正常気配で失効しても、ORIGIN型は同方向の継続中に再審査しません。TOPの16実親・23無取引という不足がどの理由で生じたかは、まだここでは数えていません。

## 現在票を計算できる保存範囲

| 保存素材 | 保存されるもの | できないこと |
| --- | --- | --- |
| TradeGateの33cache | 全normalのLast・原seq・価格時計、同原行BBO・資格、paper feed、quiet、原行mapping。出来高票10/30/60秒は元公開行だけ | このcache単独で公開後の出来高代理を再算定できない。raw・出来高差・量・reset・深板を破棄している |
| TradeExitの別33cache | 同normalのrecord/quotesと、全normalの10/30/60秒known/reason/up/down/unsigned balance・窓系譜 | feed/quietや全raw、出来高量・深板は無い。最後に実発生した方向票のseqも無い |
| 既SourceWindows | first公表の端点価格差とseq/時計不正prefix | 途中全経路、出来高票、量、深板の代用にはならない |
| 修正済み原行NPZ66 | Last/BBO、usable出来高差とreset、累計volumeと別時計、十段価格・数量と資格、normal mapなど44列 | 真の約定テープ、主体、取消と消費の区別、実受信順や実ミニ・マイクロ板を復元できない |

**現在窓の再審査は既TradeExit全normal票を再利用できる可能性があります。** 元公開票を後へ持ち越す方法とは違います。ただし「現在窓が適格」と「前の失敗後にdistinctな新根拠が発生した」は別です。`first_vote_raw_row`は窓始の原行境界であり、最後の実方向票の時刻ではありません。freshな更新seqを要求するなら、別原列の射影が必要です。

TradeExit最終目録は `全33場の保有中取引更新票.json` です。非有限候補時計の系譜をsentinelへ修正し、finite normalで旧保存値が同値だった補完が `非有限clock系譜修正と完成全33入力の同値補完.json` に結ばれます。archive旧目録単独を使いません。今回、目録やcache本文の内容自体は未読です。

## 異なるcacheを結ぶ前の必須確認

1. session/symbolとrecord/quotesの原seq・価格時計・Last・BBO・資格を全一致させます。normal row番号だけで結びません。
2. 全normal票の候補raw rowをTradeGate mappingへ、候補raw seq/時計をrecordへ一致させます。
3. 元PUBではcorrected votesのknown/reason/up/down/count・window起点を照合します。PUBLICのbalanceはpaper方向を掛け済み、全normalのbalanceはunsignedです。当時paper方向を一度だけ掛けます。
4. 未知のdebug票を採用しません。既知・総票0のPUBLIC Noneと全normal NaNも、中立の価格票balance0と区別します。

## 元公開を理由と時刻へ分ける

feedは10列です。公開normal行、旧判断行、paper CID、方向、paper枚数、公開Last、理由、新規flag、役割、公開時ATRを持ちます。実新規の審査行は列0であり、列1へ巻き戻しません。影枚数5/10とNative容量10/20を分けます。

111の最初の拒否理由は、予定静観・場停止・期限、実保有/予約busy、同行paper撤回、`[start+300, limit−300)`、normal/Last/ATR、入口情報、公開spreadと往復料の余裕の順です。複数原因は併記し、最初のreasonを唯一原因にしません。111は固定全量なので、旧risk sizingのqty0を混ぜません。

FAKは公開価格上限を固定し、最初goodquoteで一回fillまたは失効します。未正常なら待機し、既知timerはfill前に取消、後の有利価格で旧予約は復活しません。goodquoteが公開と同じPriceTimeでも原seqは後です。PriceTimeは板受信時刻ではありません。

実busyや予約、場停止、firstgoodQuoteの個別理由は、record/flowだけでは確定できません。既111の選択SEL_TARGET台帳が別途授権されれば、PUB/執行/判断/曲線の保存イベントを接頭から参照する案です。金融を同じ条件で再運転して状態を作り直しません。

## 水準・コストを見る算定枠

SMA/EMA、当時までのセッション高安はnormal Last又はmidと時計から算術可能です。同clockの多数行を単純に平均すると更新密度の重みが変わるため、価格、確定足、asof、欠測の扱いを結果前に決めます。未来の戻りでpivotを認定しません。5/15分の形や指標交差だけで売買を決めません。

VWAPproxyや参加コストproxyには量が必要です。`sum(Last×usableΔV)/sum(usableΔV)`は集約出来高を最後の価格へ配賦した代理で、真の保有平均コストではありません。NPZにTradingValue/Volumeと各時計は宣言されますが、単位・対象範囲・当時性を検査するまで、その比をVWAPと断言しません。

深板には十段価格・表示数量と資格があります。量差は約定、取消、並べ替え、同主体の補充を識別しません。実受信時刻は値が保存されず、存在boolだけです。VolumeTimeやTradingValueTimeをPriceTimeと合成して受信時計を作りません。保有者の心理・平均取得コストを観測したように補完しません。

「多くの人が見る水準に注文が集中し得る」「平均コスト付近で行動が変わり得る」は仮説です。頭と尻尾を予測せず、**当時水準＋現在のtradeflow＋quote反応＋二市場の共通方向**から波の中間を確認する枠に留めます。Monex/kabu01の説明確認は根担当が行い、指標値だけの成功へ置き換えません。

## 次の非金融読取案

第一段はTradeGate33とTradeExit33各1読の厳密結合を優先します。元公開と継続中の現在資格を、紙上方向の継続区間・normal観測行・連続適格区間で分けます。必要なら別許可された選択111台帳66を各1読し、busy/予約/静観/場停止を重ねます。行数を独立機会や勝率の分母にしません。

distinct fresh票、量加重、深板、clock/reset原因が必要なら、修正NPZ66の必要列だけを一目的射影する第二段を別固定します。元板・API・金融再生は0の案です。根の目録・人工署名・読取scope確定までは本文readerを実装・実行しません。

9/21Day10:45long、9/22Day09:20short、9/23Day09:05short、9/22Night00:40longは事後診断ラベルだけです。Nightの場名と実暦日を分け、00:40を価格proxy時計で確認します。入口の日付・時刻・方向へハードコードしません。

00108の価格PULL/BREAK追加群は料金前から赤字でした。その価格geometryをそのまま再金融せず、現在出来高代理を使える保存範囲から確認します。新参加・収支効果は未測。目標はTOPの損失/無取引込み全場平均net10万円と従来三基準、NK円額床は未指定のままです。

根拠sourceと行番号・SHAは同じ領域の [source契約と非金融機会診断の準備案.json](source契約と非金融機会診断の準備案.json) に保存します。主なsourceは [PUB cache生成](../../../work/wave_v106/e01_trade_gate/prepare.py)、[全normal票](../../../work/wave_v106/e01_trade_exit/features.py)、[corrected代理](../../../work/wave_v106/trade_gate/votes.py)、[元feed](../../../work/wave_v87/round10/strategy.py)、[111制御](../../../work/e01_fak_evidence_20261014/engine/core.py) です。
