"""停止通知と処理例外の保存境界、接続先転送の拒否を故障注入で検証する。"""

from __future__ import annotations

from contextlib import contextmanager
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import signal
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error

from . import runtime
from .storage import Store
from .transport import Feed, MarketClient


class SingleEventFeed:
    """実ネットワークを使わず、故障注入用の一イベントだけを渡す。"""

    def __init__(self, client: MarketClient, poll_seconds: float):
        """機能: 実接続しない受信待ち行列を用意する。

        引数: client(MarketClient)、poll_seconds(float)。返り値: なし(None)。
        """
        self.events = queue.Queue()
        self.events.put(("book", time.time(), {}))
        self.overflow = threading.Event()

    def start(self) -> None:
        """機能: 事前投入済みイベントをそのまま利用可能にする。

        引数: なし。返り値: なし(None)。
        """

    def close(self) -> None:
        """機能: 接続資源を持たない試験用受信器を閉じる。

        引数: なし。返り値: なし(None)。
        """


def fault_runner(fault):
    """機能: 状態更新と売買記録追加の間に指定故障を注入する運転器を作る。

    引数: fault(callable) は途中で実行する処理。返り値: 運転器クラス(type)。
    戦略計算ではなく、実際のmain・保存・停止制御の原子性を試験する。
    """
    class FaultRunner(runtime.PaperRunner):
        """イベント途中の停止要求又は例外を実行する運転器。"""

        def accept_book(self, payload: dict, received: float, now: float) -> None:
            """機能: メモリ状態を更新した直後、CSV行追加前に故障を発生させる。

            引数: payload(dict)、received/now(float)。返り値: なし(None)。
            """
            self.registration = {"故障検査": "イベントの状態変更済み"}
            fault()
            self.pending.append(("trade", {"区分": "新規", "枚数": 5,
                                           "理由": "状態更新後の停止要求を検査"}))

    return FaultRunner


@contextmanager
def redirect_server():
    """機能: 全要求を禁止先へ転送するローカル試験サーバーを起動する。

    引数: なし。返り値: 接続先と受信パス一覧をyieldする生成器(Iterator)。
    実controllerへは接続せず、転送先にも注文処理は実装しない。
    """
    requested = []

    class RedirectHandler(BaseHTTPRequestHandler):
        """転送を試み、クライアントが二件目へ進まないことを確かめる。"""

        def do_GET(self) -> None:
            """機能: 要求を記録し、禁止先への302を返す。

            引数: なし。返り値: なし(None)。
            """
            requested.append(self.path)
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/kabus/login")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

        def log_message(self, format: str, *args) -> None:
            """機能: 故障注入サーバーの定型アクセス出力を抑える。

            引数: format(str)、args(tuple)。返り値: なし(None)。
            """

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requested
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class SafetyTests(unittest.TestCase):
    """完了イベントだけを保存し、許可URLから外へ進まないことを確認する。"""

    def read_rows(self, path: Path) -> list[dict]:
        """機能: 売買CSVを正本再出力後の比較に使う。

        引数: path(Path)。返り値: 売買行(list[dict])。
        """
        with (path / "売買記録.csv").open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_sigint_between_state_and_trade_preserves_completed_event(self) -> None:
        """機能: 建玉相当の更新後にCtrl+C通知が届いても対応売買を失わない。

        引数: なし。返り値: なし(None)。OS通知と同じ登録済ハンドラを直接呼ぶ。
        """
        previous = signal.getsignal(signal.SIGINT)

        def interrupt() -> None:
            """機能: 現在登録されたSIGINT停止要求ハンドラを呼び出す。

            引数: なし。返り値: なし(None)。例外でイベントを分断しない。
            """
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)

        with tempfile.TemporaryDirectory(prefix="停止原子性_") as folder:
            path = Path(folder)
            with patch.object(runtime, "Feed", SingleEventFeed), \
                    patch.object(runtime, "PaperRunner", fault_runner(interrupt)), patch("builtins.print"):
                self.assertEqual(runtime.main(["--output", str(path), "--seconds", "5"]), 0)
            store = Store(path)
            try:
                saved = store.load()
                self.assertEqual(saved["registration"], {"故障検査": "イベントの状態変更済み"})
                rows = self.read_rows(path)
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["区分"], rows[0]["枚数"]), ("新規", "5"))
            finally:
                store.close()
            status = json.loads((path / "現在状態.json").read_text(encoding="utf-8"))
            self.assertIs(status["稼働中"], False)
            self.assertIs(status["終了処理中"], False)
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)

    def test_exception_does_not_commit_partial_event(self) -> None:
        """機能: 通常例外と直接KeyboardInterruptの途中状態がDBへ入らない。

        引数: なし。返り値: なし(None)。終了finallyも含めて旧状態を確認する。
        """
        previous = signal.getsignal(signal.SIGINT)
        for exception_type in (ValueError, KeyboardInterrupt):
            with self.subTest(exception=exception_type.__name__), tempfile.TemporaryDirectory(prefix="異常原子性_") as folder:
                path = Path(folder)

                def fail() -> None:
                    """機能: 状態更新後、売買行追加前に処理を異常終了させる。

                    引数: なし。返り値: なし(None)。検査対象の例外を送出する。
                    """
                    raise exception_type("イベント途中の故障注入")

                with patch.object(runtime, "Feed", SingleEventFeed), \
                        patch.object(runtime, "PaperRunner", fault_runner(fail)), patch("builtins.print"):
                    with self.assertRaises(exception_type):
                        runtime.main(["--output", str(path), "--seconds", "5"])
                store = Store(path)
                try:
                    self.assertEqual(store.load()["registration"], {})
                    self.assertEqual(self.read_rows(path), [])
                finally:
                    store.close()
                self.assertEqual(signal.getsignal(signal.SIGINT), previous)

    def test_http_redirect_never_reaches_forbidden_path(self) -> None:
        """機能: 市場GETから禁止先へのHTTP転送を実通信で拒否する。

        引数: なし。返り値: なし(None)。通信はローカル試験サーバーだけに限定。
        """
        with redirect_server() as (base, requested):
            client = MarketClient(base)
            with self.assertRaises(urllib.error.HTTPError) as caught:
                client.get("/api/v1/history/status")
            self.assertEqual(caught.exception.code, 302)
            caught.exception.close()
            self.assertEqual(requested, ["/api/v1/history/status"])

    def test_websocket_redirect_never_reaches_forbidden_path(self) -> None:
        """機能: WSハンドシェイクのHTTP転送でも禁止先へ進まない。

        引数: なし。返り値: なし(None)。実装の接続ループを一試行で終了させる。
        """
        with redirect_server() as (base, requested):
            feed = Feed(MarketClient(base))
            original_emit = feed.emit

            def one_attempt(kind: str, payload: object, received_at: float | None = None) -> None:
                """機能: 接続結果を記録し、試験中の再接続を止める。

                引数: kind(str)、payload(object)、received_at(float|None)。返り値: なし(None)。
                """
                original_emit(kind, payload, received_at)
                if kind in ("connected", "disconnected"):
                    feed.stop.set()

            with patch.object(feed, "emit", side_effect=one_attempt):
                feed.websocket_loop()
            self.assertEqual(requested, ["/kabusapi/websocket"])


if __name__ == "__main__":
    unittest.main()
