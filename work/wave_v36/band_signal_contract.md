# 価格帯信号の入出力と時刻境界

`band_signals.build(spec, inputs, features, events, clock_scale=1.0)` は注文や損益を計算せず、キー `(session, symbol)` ごとに次を返す。配列長は同じキーの `ready['seq']` の長さ。

| 欄 | 型・意味 |
| --- | --- |
| direction | int8。買い方向1・売り方向−1・中立0 |
| source_episode | int64。共通価格準備のローカルID。中立時−1 |
| source_row | int64。初回反応を確認した解放原本seq。ready配列の位置ではない。中立時−1 |
| episodes | 日本語説明に対応するPython型の辞書一覧。未取得の数値はNone |
| activity | 準備・採否・反応の件数、方向ごとの有効原本行数と観測間秒数。約定回数や保有時間ではない |

`catalog()` は設計の90条件、`clear_cache()` は共通準備の再利用解除。入力は呼出間に変更しない。未来変更・切断を調べる場合は必ず先にキャッシュを解除する。共通準備はWと窓倍率だけで決まり、出来高代理・反応の枝・相手の扱いでは変えない。

## 価格窓

使う価格は解放ブロックの `source_mid_last/source_bid_last/source_ask_last`。`source_last_seq` はそのブロックの参照上限であり、途中に無効板があれば価格の厳密な素材行ではない。有効な最後の板を使い、解放原本行の新しい価格列は使わない。

W前・W/4前の参照は、その時刻以下で最新の解放行。参照の余分な古さは60秒以内。短窓のレンジには、その開始時点で既知だったasof価格も含める。このため最大60秒前の既知価格がレンジに含まれる場合がある。W区間内は両端包含で最低5解放ブロックを要し、長窓参照から現在までの有効endpoint・公開遅れ60秒以内・隣接解放の穴60秒以内を確認する。公開ATRは現在の解放seq以下のready行から参照し、有限正を要する。過去アンカーのATRは計算に使わない。

途中の `continuity_reset_count` は診断の合計として残す。最後の有効endpointがあるブロックを、途中の不正板が存在したという理由だけで窓全体から除かない。不正原本を跨ぐ出来高差分は、別のイベント抽出側が解除済み。

## 準備と反応

準備時の中値・側s・帯価格・ATR・確認幅・出来高スコア・期限は固定。別の後続解放で初めて反転又は突破を観測した時に消費する。期限は等号を含め先に失効。データの欠損・古さ・穴・現在ATR不正でも失効するが、停滞条件が崩れたこと自体では捨てない。

終了した行では再準備しない。その後の有効解放行で準備条件falseを一度観測し、さらに後のtrue行から再準備可能になる。新しい過去進行方向で、未解決の準備のsを上書きしない。

出来高の窓は解放時刻の `[準備時刻−W, 準備時刻]`。加えて解放seqが準備seq以下であることを要する。同じ価格帯と側の各個別イベントを合計し、複数価格を一価格へ集約しない。区間内の約定が全てその価格・側で起きたことや、真の補充量は保証しない。

比率の合計は窓内項への `math.fsum` を使う。窓外の累積量との差ではKの等号や「気配維持部分≤全体」が浮動小数の差引き誤差で壊れるため。閾値へ任意の許容幅を加える処理は行わない。

相手は解放時刻＋60秒以下の最新行を参照。その後の古さが60秒以内で、相手価格窓が有効であることを、相手を使う両条件で要する。欠測と有効中立は `peer_available` で区別する。後の同意を待ち直さない。

採用方向は確認から120秒未満の原本行だけに展開する。別の新しい共通準備が採用されれば、同方向でも根拠と期限を置き換える。不採用の準備は、以前に採用した方向を延命も撤回もしない。実約定は旧注文器の次行ルールに委ねる。

## 明細の主要欄

`setup_seq/time_s/side/mid/bid/ask/atr`、`band_price`、`setup_source_first_seq/last_seq`、長短の `anchor_seq/time_s`、`stall_range`、`continuity_reset_count`、全量と気配維持の `volume_score/count` は準備時に固定する。

`resolution` は `pending/confirmed/expired/data_unavailable`。確認なら `response_branch/direction` と `confirmation_seq/time_s` を記録。確認以外のこれらはNone又は方向0。`peer_available/direction/seq/available_time_s/age_seconds`、`proxy_pass/branch_pass/peer_pass`、`accepted/rejection_reasons` は各方式の採否証拠。`signal_expiry_time_s` は採用時だけ数値。

明細・活動量は `json.dumps(..., allow_nan=False)` を合成と全条件で検査する。方向・根拠配列はNPZに別保存し、原本seqと配列位置を混同しない。
