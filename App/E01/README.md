# E01 自動売買

kabus-controller から価格・板・確定足を受信し、E01 の新規・返済を判断する Go プログラムです。Windows / Linux に対応します。**同梱設定は実注文を送らない dryrun です。**

最初にこのファイルを読み、[設定](conf/trade.toml)、[詳しい仕様](docs/仕様.md)、[検証結果](docs/検証結果.md) の順に確認してください。

## 実行

Go 1.23 以降を使用し、この `App/E01` フォルダから実行します。

```text
go run . -conf conf
```

実サーバーのデータを使い、180秒だけ仮想実行する場合：

```text
go run . -conf conf -dryrun -duration 180s -log-dir log/check -state-dir state/check
```

`-dryrun` は設定にかかわらず仮想実行を指定します。`-duration` 省略時は継続実行です。保存先の相対パスは設定フォルダの親を基準に解決します。

設定だけを検査する場合は `go run . -check` を使います。指標やトレーリング幅は `conf/strategy.toml`、通信・保存・終了前返済は `conf/system.toml` で変更できます。

## 銘柄と枚数

`conf/trade.toml` の指定例です。

```toml
[TRADE]
Symbol = "TOPIXmini"
MaxPositionPerSide = 10
InitialQuantity = 0
DryRun = true
FillMode = "observed"
```

- `Symbol`：`NK225` / `NK225mini` / `NK225micro` / `TOPIX` / `TOPIXmini` の1つ。
- `MaxPositionPerSide`：片方向の同時保有上限。累計売買枚数ではありません。
- `InitialQuantity = 0`：上限の半分、端数切捨て・最低1枚。明示した枚数も上限以下に制限します。
- `FillMode = "observed"`：選択商品の観測価格で仮想約定。`"specified"` は条件価格で約定させる理想比較用です。

実注文に切り替える場合は `DryRun = false`、`FillMode = "observed"` とし、`-dryrun` を付けず実行します。controller の認証・接続・銘柄登録が必要です。

## 記録

仮想実行は `log/2026-10-02_Day_dryrun.csv`、実注文は `log/2026-10-02_Day.csv` のように保存します。夜間の日付は立会開始日です。実注文では**受付ではなく確認できた約定だけ**を記録します。

再開用の `state` も保存されます。保有中・注文照合中に削除せず、同じ設定・保存先で再起動してください。銘柄や戦略設定を変える比較では、別の `log` / `state` 保存先を使います。

## 配布・ビルド

配布物は **[dist](dist/README.md)** にあります。実行だけなら Go・Python・PowerShell は不要です。

```text
dist/
  e01.exe
  e01-linux-amd64
  README.md
  conf/
    products.toml / products.toml.sample
    strategy.toml / strategy.toml.sample
    system.toml / system.toml.sample
    trade.toml / trade.toml.sample
```

`dist` に移動し、Windows は `.\e01.exe`、Linux は `chmod +x ./e01-linux-amd64` の後に `./e01-linux-amd64` で起動します。`-check` を付けると設定検査のみです。配布版の設定は `dist/conf/*.toml`、記録・状態は既定で `dist/log`・`dist/state` に保存します。

両環境の配布物を再作成する場合は、Go 1.23 以降を使用し、`App/E01` から次を実行します。

```text
go run ./cmd/build-dist
```

サンプルの元はソース側の `conf/*.toml.sample` です。配布先のサンプルと実行ファイルを更新し、**既存の `dist/conf/*.toml` は上書きしません**。存在しない実設定だけサンプルから補います。`*.toml.sample` 自体は実行時に読み込みません。新しい設定項目はサンプルとの差分を確認して反映してください。

従来のソース側設定・状態をそのまま使う場合は、`dist` 内で `-conf ../conf` を付けて起動してください。保有・注文照合中に新しい保存先へ切り替えないでください。

検証コマンドは `go test ./...` です。通常の停止は `Ctrl+C` を使用します。停止時・終場前の返済も約定確認が必要で、通信断時の返済完了を仮定しません。Linuxはビルド確認済み、実機での連続運転は未実施です。
