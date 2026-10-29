# AI・外部ツールから画像を取得する

Web画面と同じポートで利用できます。仕様は`GET /api/openapi.json`です。画像は要求時にメモリで作り、画像ファイル・原板コピー・新しいDBを保存しません。

| API | 内容 |
| --- | --- |
| `GET /api/resources?catalog_path=一覧パス` | セッション・手法とresource IDの一覧。省略時は初期一覧 |
| `GET /api/chart?...` | PNG／SVG／数値の取得URL、指紋、表示範囲、損益、約定、参照ファイル |
| `GET /api/chart.png?...` | 5段グラフのPNG。AIへ直接画像として渡せます |
| `GET /api/chart.svg?...` | 同じ5段のベクター画像 |
| `GET /api/data?...` | 同じ範囲の価格・OHLC・保有・損益・約定の数値 |

対象は`catalog_path`と`resource`で指定します。既存のPOSTで取得した`catalog` IDも使えます。価格だけなら`symbol`と`session`です。

共通指定は`from,to`（エポックミリ秒）、`interval=raw|1|5|15`、`price=last|mid|bid|ask`。画像は`width=800〜2400`、`height=700〜2400`、既定1600×1200です。分足の保有・損益は区間最後値、損益の軸は中央0・正負対称です。

`summary`は`summary_at_ms`（要求した`to`）までの最後の既知状態です。分足の配列は完全区間を返すため、途中の足や区間境界では`summary`と最後の足の末値が異なる場合があります。足の値は`states`の区間終了時刻で照合してください。

## 取得例

```python
import requests
from urllib.parse import urljoin

base = "http://127.0.0.1:8091"
params = {
    "catalog_path": "S:/稼働フォルダ/log/sessionviewer.resources.json",
    "resource": "NK225mini/2026-10-29_Day/dryrun/all",
    "interval": "1",
}
response = requests.get(base + "/api/chart", params=params, timeout=30)
response.raise_for_status()
view = response.json()
png = requests.get(urljoin(base, view["png_url"]), timeout=30)
png.raise_for_status()
data = requests.get(urljoin(base, view["data_url"]), timeout=30)
data.raise_for_status()
# png.contentが画像、data.json()が同じ根拠の数値・約定・参照パスです。
```

resource IDは先に`/api/resources`で確認してください。PNGだけを直接取得することもできますが、AIが損失区間を検証する時は`/api/chart`の約定・出所と一緒に扱うのが便利です。画像から推測した時刻を`from,to`へ渡し、狭い範囲で再取得できます。

`data_sha256`と`X-Chart-Data-SHA256`で元の数値応答を照合できます。メタ情報の取得URLには期待指紋が入ります。途中で原板や約定が更新された場合は409となるため、メタ情報から取得し直してください。古い画像と新しい数値を黙って混ぜません。

`catalog` IDは実行中の一時IDです。再起動や保持上限で失効した場合は一覧を再取得してください。継続利用には`catalog_path`の直接指定も使えます。

PNGはOSの日本語フォントを読み取り専用で利用します。空の`viewer.font_path`なら自動探索し、必要な場合だけ日本語TTF/TTCのパスを指定してください。フォントがなければPNGは422で理由を返し、SVG・数値は利用できます。フォントの同梱・コピーやブラウザの起動は不要です。
