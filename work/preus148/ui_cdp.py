"""全商品OFFのローカル画面だけをHeadless Edgeで確認する。実注文操作は行わない。"""

from pathlib import Path
import base64
import json
import subprocess
import time
import urllib.request
import websocket


def main():
    """
    機能: ローカル画面の時間帯編集・保存・狭幅表示を実ブラウザで検査する。
    引数: なし。
    返り値: None。画面と確認結果を当ファイル隣へ保存する。
    """
    here = Path(__file__).resolve().parent
    browser = subprocess.Popen([
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        '--headless=new', '--disable-gpu', '--remote-debugging-port=19248',
        '--remote-allow-origins=*', '--window-size=1440,1100',
        '--user-data-dir=' + str(here / 'ui-edge-profile'), 'about:blank',
    ], creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    channel = None
    sequence = 0

    def command(method, params=None):
        """
        機能: CDP命令を同期送信する。
        引数: method(str), params(dict)。返り値: dictは応答。
        """
        nonlocal sequence
        sequence += 1
        channel.send(json.dumps({'id': sequence, 'method': method, 'params': params or {}}))
        while True:
            reply = json.loads(channel.recv())
            if reply.get('id') == sequence:
                assert 'error' not in reply, reply
                return reply.get('result', {})

    def evaluate(expression):
        """
        機能: ローカル画面で検査式を評価する。
        引数: expression(str)。返り値: objectは式の値。
        """
        result = command('Runtime.evaluate', {'expression': expression, 'awaitPromise': True, 'returnByValue': True})
        assert 'exceptionDetails' not in result, result
        return result['result'].get('value')

    def wait_for(expression):
        """
        機能: 最大15秒の画面準備を待つ。
        引数: expression(str)。返り値: None。
        """
        until = time.monotonic() + 15
        while time.monotonic() < until:
            if evaluate(expression):
                return
            time.sleep(.1)
        raise AssertionError(expression)

    def screenshot(name):
        """
        機能: 現表示を保存する。
        引数: name(str)はPNG名。返り値: None。
        """
        image = command('Page.captureScreenshot', {'format': 'png'})['data']
        (here / name).write_bytes(base64.b64decode(image))

    try:
        until = time.monotonic() + 15
        while True:
            try:
                with urllib.request.urlopen('http://127.0.0.1:19248/json/list') as response:
                    pages = json.load(response)
                channel = websocket.create_connection(pages[0]['webSocketDebuggerUrl'], timeout=15)
                break
            except (OSError, IndexError):
                if time.monotonic() >= until:
                    raise
                time.sleep(.1)
        command('Page.enable')
        command('Page.navigate', {'url': 'http://127.0.0.1:18098/'})
        wait_for('document.querySelector(\'[data-product="NK225mini"] .settings-button\') && !document.querySelector(\'[data-product="NK225mini"] .settings-button\').disabled')
        evaluate('document.querySelector(\'[data-product="NK225mini"] .settings-button\').click()')
        wait_for('document.getElementById("product-dialog").open')
        assert evaluate('document.querySelectorAll(".window-editor").length') == 2
        assert evaluate('document.getElementById("product-save").disabled')
        screenshot('時間帯編集_標準.png')
        evaluate('document.getElementById("product-window-add").click()')
        assert evaluate('document.querySelectorAll(".window-editor").length') == 3
        evaluate('document.querySelectorAll(".window-editor")[2].querySelector(".window-row-top button").click()')
        assert evaluate('document.querySelectorAll(".window-editor").length') == 2
        evaluate('(() => { const c=document.querySelectorAll(".window-editor")[1].querySelectorAll(".window-clock")[1].querySelector("select"); c.value="US_BEFORE"; c.dispatchEvent(new Event("change",{bubbles:true})); })()')
        evaluate('document.getElementById("product-window-add").click()')
        evaluate('(() => { const r=document.querySelectorAll(".window-editor")[2]; const c=r.querySelectorAll(".window-clock")[0].querySelector("select"); c.value="US_AFTER"; c.dispatchEvent(new Event("change",{bubbles:true})); const m=r.querySelector("label.field select"); m.value="NK225_PG04"; m.dispatchEvent(new Event("change",{bubbles:true})); })()')
        evaluate('document.getElementById("product-save").click()')
        wait_for('!document.getElementById("product-dialog").open')
        settings = evaluate('fetch("/api/settings").then(r=>r.json())')
        item = next(x for x in settings['instruments'] if x['product'] == 'NK225mini')
        assert item['mode'] == 'off'
        assert len(item['windows']) == 3
        assert item['windows'][1]['end'] == 'US_OPEN-00:15'
        assert item['windows'][2]['start'] == 'US_OPEN+00:15'
        evaluate('document.querySelector(\'[data-product="NK225mini"] .settings-button\').click()')
        screenshot('時間帯編集_米国前後.png')
        command('Emulation.setDeviceMetricsOverride', {'width': 420, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
        screenshot('時間帯編集_狭幅.png')
        no_overflow = evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert no_overflow
        (here / '画面確認.json').write_text(json.dumps({'saved': item, 'horizontal_overflow': not no_overflow}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('UI_SMOKE_OK')
    except Exception:
        if channel is not None:
            screenshot('時間帯編集_失敗.png')
            print(evaluate('document.body.innerText'))
            print(evaluate('({settings:typeof latestSettings,connected:typeof connected!=="undefined"?connected:null,rules:typeof rulesLoaded!=="undefined"?rulesLoaded:null})'))
        raise
    finally:
        if channel is not None:
            channel.close()
        browser.terminate()
        browser.wait(timeout=10)


if __name__ == '__main__':
    main()
