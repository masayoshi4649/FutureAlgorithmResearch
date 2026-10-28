# E01 配布版

Windows / Linux 用の実行ファイルと設定を同梱しています。初期設定は **TOPIXmini・片方向上限10枚・dryrun** です。

## 起動

この `dist` フォルダを作業ディレクトリにしてください。Go・Python・PowerShell のインストールは不要です。

Windows：

```text
.\e01.exe -check
.\e01.exe
```

Linux（amd64）：

```sh
chmod +x ./e01-linux-amd64
./e01-linux-amd64 -check
./e01-linux-amd64
```

`-check` は設定の確認だけを行います。通常の停止は `Ctrl+C` です。

## 設定と記録

編集するファイルは [conf/trade.toml](conf/trade.toml) などの `conf/*.toml` です。`*.toml.sample` は雛形で、実行時には読み込みません。`DryRun = false` にすると実注文を送信します。

記録は `log/2026-10-02_Day_dryrun.csv` の形式で保存します。実注文では `_dryrun` が付きません。再開用の `state` も同じフォルダ内に保存します。保有中・注文照合中に `state` を削除せず、同じ設定・保存先で再起動してください。

ソース側で `go run ./cmd/build-dist` を再実行すると、実行ファイルとサンプルを更新します。既存の実設定・`log`・`state` は保持し、存在しない実設定だけサンプルから補います。新しい設定項目はサンプルとの差分を確認して実設定へ反映してください。

以前の `App/E01/conf` を使う運転から移行する場合、保有・注文照合中は保存先を切り替えず、`-conf ../conf` で既存設定・記録・状態を引き続き使えます。
