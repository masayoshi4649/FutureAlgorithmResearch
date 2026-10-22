# 00139 入力と実行経路の所在確認

金融再生・API接続・実注文はいずれも0。原本は変更せず、保存目録・配列の形・SQLiteのメタデータだけを確認した。

## 同一45セッションの二市場比較

全90商品場の入力・通知の位置を `data_inventory139.json` の `references` に記録した。各通知配列は12列で、core_orders / extra_orders の存在を確認済み。

|対象|旧43場の通知|prefix|
|---|---|---|
|NK225 日中|work/regime131_20261020/round3/measurement/NK225_{session}.npz|T06__|
|NK225 夜間|work/regime131_20261020/round4/measurement/NK225_{session}.npz|U06__|
|TOPIX 日中|work/regime131_20261020/round3/measurement/TOPIX_{session}.npz|T06__|
|TOPIX 夜間|work/regime131_20261020/round3/measurement/TOPIX_{session}.npz|T04__|

追加2場（2026-10-20_Night、2026-10-21_Day）は work/update132_20261021/results/measurement/{symbol}_{session}.npz、prefixなし。TOPIX夜間はU06ではない。

preparedは両市場を含むため共用できる。旧43場は work/daynight128_20261020/入力準備.json、追加2場は work/update132_20261021/inputs_v1/input_manifest.json。旧43場preparedにgatesキーはないが、価格・ATR・気配・二市場特徴は含む。今回の通知overlayはgatesを必要としない。

TOPIXの元通知は主担当5枚・補完最大5枚で、日経元micro10枚を半分へ換算する処理を流用してはならない。ラージtickはTOPIX0.5、NK225 10。日経専用R=max(20,ATR)をTOPIXにも用いず、2tick下限に一般化するならmax(1,ATR)として事前計画に明記する。

## 新しい2セッション

- 2026-10-22_Day: work/update134_20261022/inputs/prepared/2026-10-22_Day.pkl に二市場preparedあり。NK225 168,153行、TOPIX 152,478行。保存金融通知はTOPIX T06のみ（core5注文、extra0注文）。NK225通知の新規再生は登録後に必要。
- 2026-10-21_Night: 二市場の原板・1分足・5分足あり。workの対象名pkl/npz検索ではpreparedと金融通知なし。入力準備は work/update132_20261021/prepare_inputs132.py の prepare(output,sessions,inventory_path) を別の今回所有域へ接続できる。棚卸しに6原本のbytes/mtime/hash、終端到達を登録してから準備する。
- 10月22日入力は既存の原時計・公開時計の変換済み。原板を自分の都合で時刻補正していない。

## mini実板

book直下にはNK225とTOPIXのラージ、およびオプションしかない。NK225miniの全場実板は存在を確認できなかった。

TOPIXminiは過去接続試験のmarket.sqliteに短い断片がある。10月21日00:28～00:36に1,479行、10:08～10:09に512行、14:00～14:01に357行、21:55に4行。NK225microの断片もあるがNK225miniとは異なる。これらは全45場の約定価格検証に使える連続資料ではない。詳しいパス・受信時計はJSONを参照。履歴取得の受信時計は原価格時計と区別する。

## Goアプリのオフライン検査と数量フィードバック

`App/SessionTrader` で `go test ./internal/strategy -run TestSelectedSavedOrders -count=1` が保存注文との照合口。全体は `go test ./...` と `go vet ./...`。現ゴールデンはDV07/DV05/NV01/NV25の4商品場であり、全45場の二市場原板からの再現ではない。今回は試験を実行していない。

逐次接続は `Portfolio.Observe` → 発注意図 `Signal` → 次正常気配で `OnFill` → `OnOrderDone`。一括金融再生CLIはない。現在Positionはcore/extra担当ごとの平均建値管理で、追撃ごとの独立トレールは未実装。

- config.go:254: capの半分を主担当・補完へ自動割当。
- portfolio.go:109: 実数量と未約定の予約を枠から控除。
- portfolio.go:225: 実約定で平均建値・数量・初期数量・実現損益・費用を更新。
- portfolio.go:287 と cores.go:57: 実約定数量で部分返済残数を整数丸め。
- cores.go:91: 実現損益と残数量を加味したequityで停止判定。
- portfolio.go:271: 全返済した時計から待機時間を更新。

このため、今回の元通知を固定した数量・出口overlayはGoの改修版そのものの全状態再生ではない。改修採用には独立玉IDと約定別状態、注文予約、部分約定、再起動復元まで別途実装・検証が必要。
