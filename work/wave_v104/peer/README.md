最初に [interface_plan.json](interface_plan.json)、次に2つの人工証跡を読む。

入口の公開接口は `api.prepared_session(activity_payload, execution_records)`。暗黙の正式cache読取は行わない。rootが一度ロードした103活動一場と旧baseの正常recordを渡す。正常recordには `quote_valid` と `price_valid` が必須。

`cases[entry_id][symbol].normal` は同じ原行のevent・固定support・入口qualification/reset・当時lineageに加え、`entry_id` と `execution_to_raw_index` を持つ。そのまま104 engineの `interface.play` に渡す。O/B/Tは同じ入口列を使い、legacy_accountは不要。

入口資格と実返済quote資格は別。量だけ不明でも、旧quote_validがTrueでBBO正常なら返済quoteを維持する。peer観測にも旧quote_validを要求し、非対応rawはNaNで将来行へ埋めない。

`artificial.py` は人工103状態からC/R入口を作り、全19接口と未来不変を確認する。`protocol_artificial.py` は価格窓境界と抽象ready部品のU競合・消費を孤立確認する。抽象readyの市場出現や利益を主張しない。`state_fixture_source.py` は人工専用のexact複製で、production APIはこの状態を再計算しない。

正式32preparedと新金融は、rootのsource・人工レビュー後の別指示まで実行しない。旧source/cache、原本、NPZ、APIを変更・再読しない。
