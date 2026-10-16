# 追加Dayの未読入力

最初に読む資料は [追加Day未読入力の固定計画.json](追加Day未読入力の固定計画.json) です。次に [入力schema.json](入力schema.json)、[旧normal独立LPと完全prepareの人工検査.json](旧normal独立LPと完全prepareの人工検査.json)、[core.py](core.py) の順に確認します。

対象は `2026-10-13_Day` のTOPIXとNK225だけです。既知32原本・大型cacheは読みません。原行の価格代理時計、独立LP、公開出来高時計、旧正常執行の気配資格を分離し、全原行44配列は旧103v2と同じ定義です。原本対応は今回の新2原本で確認し、旧64原本の検査へ委譲しません。

`core.extract_rows(rows, session, symbol)` は一原行iteratorを一度だけ進め、訂正済み全原行・旧77/91正常系列・旧94独立LPを返します。旧77の実抽出関数へ人工バイト列を渡した対照で一致を確認済みです。`core.build_material(extracted)` は両商品の完全旧materialと、不変102の `prepare` の返り値を作ります。入口候補と経済対照を簡易signalへ置換せず、金融の `play / execute` は呼びません。

現在場の始値は利用開始が正常系列0行目のものだけです。後に公表された始値を補完しません。固定旧G0の `prepare` は前場参照を要求せず、人工も `ref_prev` なしで完全接続できたため、前場Nightの値は読んでいません。

正式完成後の消費APIは次のとおりです。

- `data.load_account(session, symbol, verify=True)`：全原行44配列と口座診断。
- `data.load_inputs(verify=True)`：一場だけの完全旧material。
- `data.load_prepared(verify=True)`：一場2商品の完全旧 `record / signal / reference_open`。
- `data.load_bundle(verify=True)`：materialとpreparedを一度に読み出す。

消費APIは出力を指紋照合して配列を読取専用にします。生原本を再hashせず、今回の一回読取終端へ由来を結びます。

人工確認のコマンドです。新Day本文は読みません。

```text
python -B -X utf8 work/wave_v104/holdout_input/artificial.py
```

次は値未読のsource/stat固定です。正式走査の明示許可があるまで、二つ目のコマンドは実行しません。

```text
python -B -X utf8 work/wave_v104/holdout_input/prepare.py --register-only
python -B -X utf8 work/wave_v104/holdout_input/prepare.py --root-additional-input-reviewed --workers 2
```

実受信時計は不明です。表示数量減少の約定/取消や同主体の再発注は同定せず、出来高方向も代理です。入力互換性や活動の確認は収益性の証明ではありません。

# 活動と19入口の追加接続

[activity_peer.py](activity_peer.py) は、新NPZ2口座を各一回、新bundleを一回だけ読み、不変103の `build_session` と不変104の `prepared_session` へ接続します。旧103の19routeと新104の19入口は別の欄です。旧32cache、旧64base、生原本は読みません。

保存packetの欄は `schema_version / session / activity / peer / prepared` です。`prepared` は同じ新bundleの完全旧102.prepareの2口座をそのまま保持し、peerの執行recordも同じobjectを参照します。rootはこの一pickleから全121条件と旧G0を再生できます。活動処理では金融を実行しません。

`activity_peer.load_complete(verify=True)` は完成した新packetを一回読む消費APIです。普通名のcore/dataを使う他の研究が同じprocessにいても、固有名で同所有域の入力部品を読みます。

計画は [追加Day活動と19入口の保存前固定.json](追加Day活動と19入口の保存前固定.json)、小人工は [追加Day活動peer接続の人工検査.json](追加Day活動peer接続の人工検査.json) です。活動sourceを確認した根の別通知があるまで、正式活動コマンドは実行しません。

```text
python -B -X utf8 work/wave_v104/holdout_input/activity_peer.py --artificial
python -B -X utf8 work/wave_v104/holdout_input/activity_peer.py --plan
python -B -X utf8 work/wave_v104/holdout_input/activity_peer.py --root-activity-peer-reviewed
```
