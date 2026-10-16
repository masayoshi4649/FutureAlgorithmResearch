# 元JSONLとNPZ及びcontrollerの時計の区別

2026-10-15確認。価格・数量を統計せず、値の保存・出力も0。元bookは読取のみ。金融・NPZ・大型cache・現在API・公開・共通知見編集は0。

## 実際に確認した範囲

[固定計画](先頭時計schemaの目的別読取固定.json)の33場×TOPIX/NK225について、先頭一JSON行を各1回だけ読んだ。[キー型と時計候補の射影](三十三場六十六先頭のキーと時計候補.json)へキー名・型、時計/seq候補の値だけ保存した。**66ファイルopen・66行・102,367 bytes**、各行最大8,192 bytes。原行全体の保存・原全文hashは0。既非金融metadata120KBは場名一覧の目的で一読。追加済みの33場外データは読んでいない。

頭部の時計候補は以下の6キーで、いずれも66頭部にキーがある。値が`null`の頭部も含むので、キー存在を有効時計とは呼ばない。

| 項目 | 定義と今回の観測 |
|---|---|
| `CurrentPriceTime` | 上流仕様の現値時刻。受信時刻ではない。値が変わった瞬間だけの時刻か、同値での新約定でも進む時刻かを、名前だけから断定しない。 |
| `TradingVolumeTime` | 上流仕様の売買高時刻。現値時計とは別のフィールド。 |
| `PreviousCloseTime` | 前日終値の日付。新しい板の更新時刻として使わない。 |
| `OpeningPriceTime` / `HighPriceTime` / `LowPriceTime` | 始値・高値・安値に対応する時刻。板全体の更新や受信時刻ではない。 |

この66頭部には、`ReceivedAt`/`ReceivedTime`/`received_at`/`receivedAt`/`collectedAt`/`capturedAt`/`timestamp`/`SourceClockTime`、共通seq、`BidTime`/`AskTime`/`Buy1.Time`/`Sell1.Time`/`TradingValueTime`は見つからなかった。**後の行にもないことは今回未確認。** 初行は寄前等を含み、別の行でキー集合が変わる可能性は排除しない。

## controllerと上流仕様

上流の[公式PUSH仕様](https://kabucom.github.io/kabusapi/ptal/push.html)を自分で閲覧した。`BidTime`（上流では最良売気配時刻）、`AskTime`（同最良買気配時刻）と`Sell1.Time`/`Buy1.Time`は**株式のみ**で、先物欄は対象外。今回頭部で未観測だったことと整合する。上流のBid/Ask名称を、研究側の金融用語bid=`Buy1`・ask=`Sell1`へそのまま対応させない。

[controller履歴仕様](S:/GitHub/masayoshi4649/kabus-controller/docs/future-history.md:46)はJSONLに独自項目を付けず受信JSONをそのまま保存すると説明する。一方、履歴の`from/to`はアプリ受信時刻で絞る。**メモリに受信時計があることと、保存JSONLにその時計があることは別。** [OpenAPIのsnapshot](S:/GitHub/masayoshi4649/kabus-controller/docs/kabus-controller-openapi.yaml:8436)の`asOf`は公開状態の最終更新時刻、`sequence`は対象商品の取得開始時点の受信件数で、原文へ追加しない。snapshot/HTTPヘッダーの値を各保存行の受信時計・共通seqとして復元しない。

[注文仕様の`quoteReceivedAt`](S:/GitHub/masayoshi4649/kabus-controller/docs/08-future-orders.md:159)はPUSHのローカル受信時刻だが、現在の注文・鮮度判定用の値。これが過去book各行に保存されていたとの証拠ではない。`SourceClockTime`は今回の頭部と指定controller資料では意味を確認できないため、真受信clockとの対応を仮定しない。

## NPZに関する旧主張の限定

[NPZ生成源](S:/GitHub/masayoshi4649/FutureAlgorithmResearch/work/wave_v103/input/core.py:124)の`received_at_present`は`ReceivedAt`/`received_at`/`receivedAt`の**3名の存在フラグだけ**。値の解析・時刻保存を行わず、他のキー名の受信時計まで網羅していない。したがって「NPZに受信時計値がない」はsource契約から言えるが、そこから「元book全行にあらゆる受信時計がない」とは言えない。今回の追加証拠は66先頭のキー確認までである。

また、Buy/Sell表示やその他フィールドの独自clockがNPZで捨てられた可能性と、元先物PUSHにフィールド自体がない可能性を分ける。今回の上流仕様＋66先頭では、株式専用Bid/Ask時計を先物の改善部品に使える証拠は得なかった。各市場ファイルの原行番号はファイル内の保存順だけで、二市場共通の受信順ではない。

## 出来高時計が現値時計より後という問題

同じ保存snapshot行で出来高の値と時計が既に届いていたなら、`TradingVolumeTime > CurrentPriceTime`を**それだけで未来情報の混入と断定しない**。現値の項目時計が停滞したまま別項目が更新される説明と、配信項目の時間整合が悪い説明を分ける必要がある。ただし、原seqだけでは真の約定発生時刻や二市場受信先後は証明できず、両時計のmaxを受信clockへ合成しない。

現NPZは、出来高差`known`とは別に、両原行で出来高時計が現値時計以下であることなどを`usable`へ要求する。現定義で不使用となった行は「取引なし」ではない。時計整合の保守的条件としての妥当性と、未来情報そのものの証明を混同しない。これを緩めた場合の代理方向・可用性・損益は**未測定**で、今回旧定義を変更していない。

理由番号も部品ごとに異なる。NPZの`volume_reset_reason`のbit16は出来高時計の場外、修正`trade_gate.votes`のreason16は正増行のLast/直前BBO不明。別診断が「出来高時計が現値時計より後」を16とする場合、同じ数値でもこれらと同じ意味として集計しない。

今後に必要なのは、当時snapshotの公表済み状態・項目時計の意味を固定して別目的の可用性測定をすること。**先頭確認だけで既存金融の原因を証明した、二市場の厳密な先後を復元した、という結論は出していない。**
