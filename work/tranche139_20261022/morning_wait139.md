# 朝と夜の待機理由

**日中固定準備**: 場開始後1200秒。08:45開始なら09:05。

**ATR準備**: 確定5分足3本と公開遅延60秒。08:45開始なら最速09:01。

**方向準備**: 1分足のEMA60と3本差傾きで両市場63本が必要。最初の63本目は09:47足、確定09:48・公開遅延後09:49・相手遅延後09:50。受信遅れや欠足でさらに遅くなる。

**結論**: 09:50そのものの固定禁止ではなく、同セッションの指標必要本数が実質的下限を作る。warmup秒だけ短くしても改善しない。

**準備後の入口**: 両市場EMA方向一致とG再成立、短期支持、0.25ATRの追跡反発、気配差・価格距離、既存波の状態を順に満たす必要がある。

**夜間固定準備**: USOpen+1320秒。夏時間22:52/冬23:52日本時間から主担当の新規準備候補。USOpen前後900秒は別の静観制約。

**初期入口の研究上の選択肢**: 63本EMAから独立する短期二市場確認・最低ティック幅を使う少量入口なら09:50以前に参加可能。Rを公開ATRのみに依存すると09:01以前は参加できないため、早期幅基準を別途因果的に定義する。

**status表示の注意**: 主担当は米国開始後の準備待ちは、米国開始より何時間も前にも同じ文言。実際には主担当はUS開始まで休止する条件。

根拠: App/SessionTrader/internal/e01/features.go:32, App/SessionTrader/internal/e01/features.go:359, App/SessionTrader/internal/e01/features.go:360, App/SessionTrader/internal/e01/features.go:406, App/SessionTrader/internal/e01/features.go:430, App/SessionTrader/internal/runner/status.go:210, App/SessionTrader/internal/strategy/types.go:112

コード読取のみ。金融再生・API接続0。
