"""市場データ専用のGETと受信専用WebSocket。注文APIは実装しない。"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import websocket


READ_PATHS = frozenset({
    '/api/v1/sys/registrations/future', '/api/v1/history/status',
    *('/api/v1/history/' + s + '/candles/' + p
      for s in ('NK225', 'TOPIX') for p in ('1min', '5min')),
})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """許可した市場情報URL以外への自動移動を拒否する。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """機能: HTTPの転送を拒否する。

        引数: req等(HTTP標準引数)。返り値: なし。常にHTTPErrorを送出。
        """
        raise urllib.error.HTTPError(req.full_url, code, '転送は禁止です', headers, fp)


class MarketClient:
    """接続先を固定し、仕様で確認した市場GETだけを許可する。"""

    def __init__(self, base_url: str, timeout: float = 5):
        """機能: 認証情報を使わない市場接続を設定する。

        引数: base_url(str)、timeout(float:秒)。返り値: なし(None)。
        """
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('接続先にはhttp(s)のサーバーURLを指定してください')
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('接続先に認証情報・パス・クエリは指定できません')
        self.base_url = base_url.rstrip('/')
        self.ws_url = ('wss' if parsed.scheme == 'https' else 'ws') + '://' + parsed.netloc + '/kabusapi/websocket'
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(self, path: str) -> dict:
        """機能: 許可済み市場データをGETする。

        引数: path(str:固定パス)。返り値: JSONオブジェクト(dict)。
        """
        if path not in READ_PATHS:
            raise ValueError('許可されていない市場データパス: ' + path)
        request = urllib.request.Request(self.base_url + path, method='GET', headers={'Accept': 'application/json'})
        with self.opener.open(request, timeout=self.timeout) as response:
            body = response.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise ValueError('市場データの応答が上限を超えました')
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError('市場データの応答形式が不正です')
            return value

    def registration(self) -> dict:
        """機能: 大型先物のコードを現在の登録銘柄番号へ対応させる。

        引数: なし。返り値: コードをキーとする登録情報(dict)。
        """
        data = self.get('/api/v1/sys/registrations/future')
        rows = data.get('data', {}).get('futures', [])
        mapped = {row['futureCode']: row for row in rows if row.get('futureCode') in ('NK225', 'TOPIX')}
        if set(mapped) != {'NK225', 'TOPIX'}:
            raise ValueError('NK225とTOPIXの登録情報が揃っていません')
        return mapped


class Feed:
    """受信と足取得を別スレッドで行い、判定は主スレッドへ渡す。"""

    def __init__(self, client: MarketClient, poll_seconds: float = 10):
        """機能: 有界の受信キューと停止信号を準備する。

        引数: client(MarketClient)、poll_seconds(float)。返り値: なし(None)。
        """
        self.client = client
        self.poll_seconds = poll_seconds
        self.events = queue.Queue(maxsize=10000)
        self.stop = threading.Event()
        self.overflow = threading.Event()
        self.threads = []

    def emit(self, kind: str, payload: object, received_at: float | None = None) -> None:
        """機能: 受信時刻付きで主スレッドへ通知する。

        引数: kind(str)、payload(object)、received_at(float|None)。返り値: なし(None)。
        """
        try:
            self.events.put_nowait((kind, time.time() if received_at is None else received_at, payload))
        except queue.Full:
            self.overflow.set()

    def candle_loop(self) -> None:
        """機能: 両銘柄・両足の整合したスナップショットを取得し続ける。

        引数: なし。返り値: なし(None)。
        """
        while not self.stop.is_set():
            try:
                registration = self.client.registration()
                batch = {}
                for symbol in ('NK225', 'TOPIX'):
                    for period in ('1min', '5min'):
                        batch[symbol, period] = self.client.get(f'/api/v1/history/{symbol}/candles/{period}')
                identities = {(v['snapshot']['sessionId'], v['snapshot']['generation']) for v in batch.values()}
                if len(identities) != 1:
                    raise ValueError('足取得中にセッションまたは世代が切り替わりました')
                self.emit('candles', {'registration': registration, 'batch': batch})
            except Exception as exc:
                self.emit('candle_error', str(exc))
            self.stop.wait(self.poll_seconds)

    def websocket_loop(self) -> None:
        """機能: 購読操作を送らず、市場PUSHの受信・再接続を続ける。

        引数: なし。返り値: なし(None)。
        """
        while not self.stop.is_set():
            connection = None
            try:
                connection = websocket.create_connection(
                    self.client.ws_url, timeout=2, suppress_origin=True,
                    enable_multithread=True, http_no_proxy=['*'], redirect_limit=0,
                )
                if connection.getstatus() != 101:
                    raise ConnectionError('WebSocketへ正常に切り替わっていません。転送には追従しません')
                self.emit('connected', None)
                while not self.stop.is_set():
                    try:
                        data = connection.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    received = time.time()
                    if not data:
                        raise ConnectionError('市場WebSocketが切断されました')
                    if len(data) > 4 * 1024 * 1024:
                        raise ValueError('市場PUSHが上限を超えました')
                    payload = json.loads(data)
                    if isinstance(payload, dict):
                        self.emit('book', payload, received)
            except Exception as exc:
                if not self.stop.is_set():
                    self.emit('disconnected', str(exc))
            finally:
                if connection is not None:
                    connection.close(timeout=1)
            self.stop.wait(3)

    def start(self) -> None:
        """機能: 市場受信と足取得を開始する。

        引数: なし。返り値: なし(None)。
        """
        for target in (self.candle_loop, self.websocket_loop):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self) -> None:
        """機能: 再接続・取得を停止し、スレッド終了を有限時間待つ。

        引数: なし。返り値: なし(None)。
        """
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=6)
