# 秒単位売買と発注遅延の独立監査

最初に読む資料は [final_delay5の全口座独立会計監査.json](final_delay5の全口座独立会計監査.json) です。主条件は新規・返済の両方を判断から5秒待つ方式です。情報源の鮮度とは区別します。

1. [遅延スキャルピングの事前敵対設計.json](遅延スキャルピングの事前敵対設計.json)：損益を見る前に定めた、時計・約定・未処理注文・未来参照の監査条件。
2. [遅延エンジンの人工境界と未来監査.json](遅延エンジンの人工境界と未来監査.json)：86検査。0秒でも判断行では約定しない、指値接触だけでは約定しない、取消到達まで残る、期限は無観測でも時計で発火する、返済待ちの損失を残すことを確認。
3. [料金と欠測タイマーの人工独立会計監査.json](料金と欠測タイマーの人工独立会計監査.json)：両商品38人工口座・1,482項目。税込料金の切捨て、無効気配後の最終既知気配、全行清算時価を独立計算。
4. [原本からの独立特徴と八入口未来監査.json](原本からの独立特徴と八入口未来監査.json)：60商品場・2,113,200商品格子。一意時計から参照を再計算し、106,745原本窓、13,316配列、236途中切断を確認。
5. 全会計：[初回288条件](firstの全口座独立会計監査.json)、[改修42条件](repairの全口座独立会計監査.json)、[最終0秒](final_delay0の全口座独立会計監査.json)、[最終1秒](final_delay1の全口座独立会計監査.json)、[最終5秒](final_delay5の全口座独立会計監査.json)、[厳格3秒鮮度](quality_strict3の全口座独立会計監査.json)。374条件実行・13,200口座・182,142注文・91,071決済・600,769項目と全口座の全行清算時価SHAが一致。
6. [前半選定と固定入力の独立監査.json](前半選定と固定入力の独立監査.json)：343指紋、前16だけで計算した330探索条件、初回代表3・改修代表3・少数黒字4・無方向対照1の固定を再現。
7. [改修入口の人工境界と未来監査.json](改修入口の人工境界と未来監査.json)：47検査。欠測で同方向の再準備をしないこと、確認待ちを省いた入口、方向反転、途中切断を確認。
8. [全最終代表と三遅延の実注文未来監査.json](全最終代表と三遅延の実注文未来監査.json)：11代表・3遅延・195実原本口座、2,271切断地点・18,168配列。保有中867、新規待ち661、返済待ち528、待機指値151地点を含む。
9. [初回主3の損失分解と表示時計監査.json](初回主3の損失分解と表示時計監査.json)：849組・16,980項目。中値経路の分解と発注判断気配の分解を独立照合し、遅延費用を二重控除していないことを確認。
10. [最終数値の解釈と過剰断定の独立レビュー.json](最終数値の解釈と過剰断定の独立レビュー.json)：全11代表×3遅延×2商品が全30場合計赤字。S3からA6への総赤字縮小と1組平均の悪化を分離し、希少黒字4設定の経済経路が全3遅延で同じだったことを確認。
11. [公開二HTMLと最大損失例の最終内容監査.json](公開二HTMLと最大損失例の最終内容監査.json)：公開11方法・3遅延・1,980口座、前半330条件、厳格鮮度11条件が保存会計と一致。公開READMEの結論、最大損失60,836円の95原本行と内訳、実際の代理再生待機分布を再計算。

初回人工検査で指値取消期限が次の観測まで遅れる問題を指摘し、損益計算前に時計独立のタイマーへ修正されました。注文配列の範囲外書込みを防ぐ明示ガード、欠測時の遅延費用の最終既知気配参照も損益計算前に追加されました。監査対象の実装指紋は各JSONに残しています。

監査合格は、固定した約定仮定と保存資料内の計算が一致し、参照未来を切断しても過去記録が変わらないという意味です。CurrentPriceTimeは真の板受信時計ではありません。現実の二市場同時性、ミニ・マイクロ自身の流動性、指値の待ち順位・部分約定、表示数量変化の原因は証明しません。全30場は既知資料です。

M2は対向気配が指値を1呼値通過した後、元指値で全量約定する厳しい代理仮定です。この約定対中値の不利には、通常の気配差以外の仮定上の負担が含まれます。実際の指値注文が同じ成績になるという保証ではありません。

再現コマンド：

```text
python -X utf8 work/wave_v80/audit/engine_synthetic.py
python -X utf8 work/wave_v80/audit/accounts.py
python -X utf8 work/wave_v80/audit/signals_real.py
python -X utf8 work/wave_v80/audit/pdca_synthetic.py
python -X utf8 work/wave_v80/audit/selection.py
python -X utf8 work/wave_v80/audit/accounts.py --stage first --count 288
python -X utf8 work/wave_v80/audit/accounts.py --stage repair --count 42
python -X utf8 work/wave_v80/audit/accounts.py --stage final/delay0 --count 11
python -X utf8 work/wave_v80/audit/accounts.py --stage final/delay1 --count 11
python -X utf8 work/wave_v80/audit/accounts.py --stage final/delay5 --count 11
python -X utf8 work/wave_v80/audit/accounts.py --stage quality_strict3 --count 11
python -X utf8 work/wave_v80/audit/order_prefix.py
python -X utf8 work/wave_v80/audit/diagnosis.py
python -X utf8 work/wave_v80/audit/interpretation.py
python -X utf8 work/wave_v80/audit/public_report.py
```

監査は原本・旧成果・凍結済み主実装を変更しません。現在API取得・実注文は0です。
