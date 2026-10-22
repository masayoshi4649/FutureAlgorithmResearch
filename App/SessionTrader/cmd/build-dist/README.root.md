# SessionTrader 商品一覧

**売買する商品のフォルダを開き、その中の設定と実行ファイルを使います。** 1プロセスで1商品を売買し、判断にはTOPIX・日経225のラージ板を使います。

| 商品フォルダ・説明 | 設定ファイル | 実行ID | 片方向上限 | 日中ID | 夜間ID |
|---|---|---|---:|---|---|
| [TOPIX](./TOPIX/README.md) | [設定](./TOPIX/conf/settings.toml) | `topix` | 2枚 | T06 | T04 |
| [TOPIXmini](./TOPIXmini/README.md) | [設定](./TOPIXmini/conf/settings.toml) | `topix-mini` | 10枚 | T06 | T04 |
| [NK225](./NK225/README.md) | [設定](./NK225/conf/settings.toml) | `nk225` | 2枚 | T06 | U06 |
| [NK225mini](./NK225mini/README.md) | [設定](./NK225mini/conf/settings.toml) | `nk225mini` | 2枚 | T06 | U06 |
| [NK225micro](./NK225micro/README.md) | [設定](./NK225micro/conf/settings.toml) | `nk-micro` | 20枚 | T06 | U06 |

表は新規配布の設定です。全商品 `dryrun=true` から始めます。TOPIXラージ・日経ラージ・日経ミニの上限2枚は、主担当1枚・未参加補完1枚の準備値であり、実運用の推奨枚数ではありません。既存の実設定・`data`・`log` は更新時も保持するため、運転前に各商品の設定を確認してください。

主担当1枚では日中の部分利確・悪化時の半減が行われないため、研究時の初回5枚・10枚から損益を単純に倍率換算したものではありません。

Windowsは商品フォルダ内の `sessiontrader.exe`、Linuxは同じ場所の `./sessiontrader` を引数なしで起動します。複数商品を動かす場合は、それぞれのフォルダから起動します。実行ファイル隣の `conf/*.toml` だけを読みます。

通常の設定は13項目です。`startup.action="check"` で設定検査、`"probe"` で読取接続検査、`"run"` で運転します。`dryrun=false` にすると実注文を行います。時刻は日本時間で、米国・英国に連動する時刻は冬時間を基準に、夏時間を自動補正します。

このOS別フォルダ直下には、このREADMEと5商品フォルダだけを置きます。共通の実行ファイル・`conf`・`docs`・`conf-topix`・`conf-nk` は使いません。詳しい仕様と旧版からの移行手順は、各商品フォルダの `docs/仕様.md` にあります。

運転済みの商品は同じ実行IDとSQLiteを引き継いで再開します。所有状態が入った `data`・`log` を複製して並行運転しないでください。
