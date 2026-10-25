# SessionTrader 商品一覧

**売買する商品のフォルダを開き、その中の設定と実行ファイルを使います。** 1プロセスで1商品を売買し、判断にはTOPIX・日経225のラージ板を使います。

| 商品フォルダ・説明 | 設定ファイル | 実行ID | 片方向上限 | 日中ID | 夜間ID |
|---|---|---|---:|---|---|
| [TOPIX](./TOPIX/README.md) | [設定](./TOPIX/conf/settings.toml) | `topix` | 2枚 | T06 | T04 |
| [TOPIXmini](./TOPIXmini/README.md) | [設定](./TOPIXmini/conf/settings.toml) | `topix-mini` | 10枚 | T06 | T04 |
| [NK225](./NK225/README.md) | [設定](./NK225/conf/settings.toml) | `nk225` | 2枚 | TG04 | TG04 |
| [NK225mini](./NK225mini/README.md) | [設定](./NK225mini/conf/settings.toml) | `nk225mini` | 10枚 | TG04 | TG04 |
| [NK225micro](./NK225micro/README.md) | [設定](./NK225micro/conf/settings.toml) | `nk-micro` | 20枚 | TG04 | TG04 |

表は新規配布の設定です。全商品 `dryrun=true` から始めます。上限枚数は準備値であり、実運用の推奨枚数ではありません。通常の再ビルドは既存の実設定・`data`・`log` を保持します。手法だけを更新する場合も、利用者が指定した枚数とdryrunは変更しません。

日経のTG04は上限を主担当・追加担当・独立担当へ5:3:2で配分します。PG04へ変更する場合は主担当・独立担当へ5:5で配分します。端数は余りの大きい担当から、同率は記載順で配ります。0枚の担当は停止します。TG04は上限2枚で1/1/0、10枚で5/3/2、11枚で6/3/2です。少枚数は部分返済や担当停止が変わるため、研究10枚の単純な損益縮小ではありません。

同じTG04/PG04でも昼夜で内部の手法が切り替わります。手法IDを省略した旧設定は日経T06/U06、TOPIX T06/T04のままで、新手法へ自動変更しません。

Windowsは商品フォルダ内の `sessiontrader.exe`、Linuxは同じ場所の `./sessiontrader` を引数なしで起動します。複数商品を動かす場合は、それぞれのフォルダから起動します。実行ファイル隣の `conf/*.toml` だけを読みます。

通常の設定は13項目です。`startup.action="check"` で設定検査、`"probe"` で読取接続検査、`"run"` で運転します。`dryrun=false` にすると実注文を行います。時刻は日本時間で、米国・英国に連動する時刻は冬時間を基準に、夏時間を自動補正します。

このOS別フォルダ直下には、このREADMEと5商品フォルダだけを置きます。共通の実行ファイル・`conf`・`docs`・`conf-topix`・`conf-nk` は使いません。詳しい仕様と旧版からの移行手順は、各商品フォルダの `docs/仕様.md` にあります。

運転済みの商品は同じ実行IDとSQLiteを引き継いで再開します。所有状態が入った `data`・`log` を複製して並行運転しないでください。
