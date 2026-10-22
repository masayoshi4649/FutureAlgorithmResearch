"""実描画領域を指定して公開画面を再確認する。"""

import base64
import json
import socket
import subprocess
import time
import urllib.request
import websocket
from common129 import HERE, PUBLIC, reference, save


def main():
    """
    機能: 隔離Chromeで実幅390/1600の全セル確認とスクリーンショットを保存する。
    引数: なし。既存の全選択QAページを利用する。
    返り値: None。実売買・金融再生・利用者ブラウザーの操作は行わない。
    """
    folder = HERE / "表示確認_最終"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    profile = folder / ("精密画面profile_" + str(time.time_ns()))
    target = folder / "全体.html"
    command = [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--disable-extensions", "--hide-scrollbars",
        "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=" + str(port),
        "--remote-allow-origins=http://127.0.0.1:" + str(port),
        "--user-data-dir=" + str(profile), target.as_uri(),
    ]
    records = []
    connection = None
    with (folder / "精密画面_ブラウザー記録.txt").open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            address = None
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
                        tabs = json.load(response)
                    address = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                    break
                except (OSError, StopIteration):
                    time.sleep(.1)
            assert address is not None
            connection = websocket.create_connection(address, origin=f"http://127.0.0.1:{port}", timeout=30)
            sequence = 0

            def call(method, parameters=None):
                """
                機能: 隔離したページだけへ描画検査要求を送る。
                引数: method(str)はCDP操作、parameters(dict又はNone)は引数。
                返り値: dictは対応する処理結果。
                """
                nonlocal sequence
                sequence += 1
                connection.send(json.dumps(dict(id=sequence, method=method, params=parameters or {})))
                while True:
                    answer = json.loads(connection.recv())
                    if answer.get("id") == sequence:
                        assert "error" not in answer, answer
                        return answer["result"]

            def evaluate(expression):
                """
                機能: 画面検査用の式を実行し、完了まで待つ。
                引数: expression(str)は検査式。
                返り値: objectは式の返り値。
                """
                answer = call("Runtime.evaluate", dict(expression=expression, awaitPromise=True, returnByValue=True))
                assert "exceptionDetails" not in answer, answer
                return answer["result"].get("value")

            call("Page.enable")
            for _ in range(100):
                if evaluate('document.readyState==="complete" && typeof verifyAll==="function"'):
                    break
                time.sleep(.1)
            else:
                raise AssertionError("公開画面の読み込み未完了")
            # ----------------------------------------
            # 起動時ウィンドウ幅ではなく、実際のCSS表示領域を明示する。
            for name, width, height, scroll in [
                ("全体_実幅", 1600, 1250, False),
                ("損益表_実幅", 1600, 1050, True),
                ("狭幅_実幅", 390, 1000, False),
            ]:
                call("Emulation.setDeviceMetricsOverride", dict(width=width, height=height, deviceScaleFactor=1, mobile=False))
                proof = evaluate('verifyAll(); JSON.parse(document.getElementById("qa-result").textContent)')
                assert proof["passed"] and proof["viewport"] == [width, height], proof
                if scroll:
                    evaluate('window.scrollTo(0,document.getElementById("selected-summary").getBoundingClientRect().top+window.scrollY-12)')
                else:
                    evaluate("window.scrollTo(0,0)")
                evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))")
                time.sleep(.2)
                encoded = call("Page.captureScreenshot", dict(format="png", fromSurface=True, captureBeyondViewport=False))["data"]
                path = folder / (name + ".png")
                path.write_bytes(base64.b64decode(encoded))
                records.append(dict(name=name, **proof, image=reference(path)))
                print(name, proof["viewport"], proof["checks"], "確認", flush=True)
        finally:
            if connection:
                connection.close()
            process.terminate()
            process.wait(timeout=10)
    save(folder / "実表示幅と描画の確認.json", dict(passed=True, records=records, financial_replays=0,
         note="先行CLI画像の狭幅は実幅500だったため、実幅390で再確認。空白の合成画像も再描画して確認。",
         report=reference(PUBLIC / "チャートで検証した改修と全セッション損益.html")))


if __name__ == "__main__":
    main()
