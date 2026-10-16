"""共通知見台帳を非表示ブラウザーで開き、検索・タブ・狭幅表示を確認する。"""

import base64
import json
from pathlib import Path
import subprocess
import time
import urllib.request

import websocket


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VIEW = ROOT/'アルゴリズム調査/共通/知見台帳/index.html'


def main() -> None:
    """
    機能: file方式の読込、データ分離、検索、リンクと表示を確認する。
    引数: なし。
    返り値: None。専用Chromeだけを終了し、ユーザーのブラウザーには接続しない。
    """
    visual = HERE/'visual'
    visual.mkdir(exist_ok=True)
    profile = visual/'profile'
    assert not profile.exists(), '専用プロファイルは毎回分離してください'
    process = subprocess.Popen(['C:/Program Files/Google/Chrome/Application/chrome.exe', '--headless=new',
        '--disable-gpu', '--disable-background-networking', '--disable-component-update', '--disable-extensions',
        '--no-first-run', '--no-default-browser-check', '--remote-debugging-address=127.0.0.1',
        '--remote-debugging-port=0', '--remote-allow-origins=http://localhost', '--user-data-dir='+str(profile),
        'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    connection = None
    try:
        port_file = profile/'DevToolsActivePort'
        deadline = time.monotonic()+20
        while not port_file.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        port = int(port_file.read_text().splitlines()[0])
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as response:
            page = next(item for item in json.load(response) if item['type'] == 'page')
        connection = websocket.create_connection(page['webSocketDebuggerUrl'], origin='http://localhost', timeout=20)
        sequence = 0
        errors = []

        def command(method: str, params: dict | None = None) -> dict:
            """
            機能: 自分の非表示タブへCDP要求を送り、同じ要求の返り値を受け取る。
            引数: method(str)、params(dict|None)はCDP操作。
            返り値: dictは操作結果。JavaScript例外は別記する。
            """
            nonlocal sequence
            sequence += 1
            current = sequence
            connection.send(json.dumps(dict(id=current, method=method, params=params or {})))
            while True:
                value = json.loads(connection.recv())
                if value.get('method') == 'Runtime.exceptionThrown':
                    errors.append(value['params'])
                if value.get('id') == current:
                    assert 'error' not in value, value
                    return value.get('result', {})

        def evaluate(expression: str) -> object:
            """
            機能: 表示確認のJavaScriptを実行して値だけを受け取る。
            引数: expression(str)は確認式。
            返り値: objectはJSON互換の実行結果。
            """
            result = command('Runtime.evaluate', dict(expression=expression, returnByValue=True, awaitPromise=True))
            assert 'exceptionDetails' not in result, result
            return result['result'].get('value')

        command('Runtime.enable')
        command('Page.enable')
        command('Emulation.setDeviceMetricsOverride', dict(width=1400, height=1200, deviceScaleFactor=1, mobile=False))
        command('Page.navigate', dict(url=VIEW.as_uri()))
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            if evaluate('document.querySelectorAll(".record").length'):
                break
            time.sleep(.1)
        assert evaluate('document.querySelectorAll(".record").length') == 14
        assert evaluate('document.getElementById("load-error").hidden') is True
        results = dict(file方式の初回知見件数=14)
        for tab, expected in (('trials', 188), ('studies', 100)):
            evaluate('document.querySelector(\'[data-tab="'+tab+'"]\').click()')
            actual = evaluate('document.querySelectorAll(".record").length')
            assert actual == expected, (tab, actual)
            results[tab+'件数'] = actual
        evaluate('document.querySelector(\'[data-tab="trials"]\').click();document.getElementById("query").value="C_N30_B4";document.getElementById("query").dispatchEvent(new Event("input"))')
        found = evaluate('Array.from(document.querySelectorAll(".record"),n=>n.dataset.id)')
        assert '104_C_N30_B4' in found and '105_C_N30_B4' in found
        results['同名で数量の異なる新旧試行を検索'] = found
        evaluate('document.getElementById("state").value="金融未実行";document.getElementById("state").dispatchEvent(new Event("change"))')
        ids = evaluate('Array.from(document.querySelectorAll(".record"),n=>n.dataset.id)')
        assert ids and all(item.startswith('105_') for item in ids)
        results['未実行の絞込み'] = ids
        evaluate('document.getElementById("query").value="<script>存在しない検索</script>";document.getElementById("query").dispatchEvent(new Event("input"))')
        assert evaluate('document.querySelectorAll(".record").length') == 0
        assert evaluate('document.querySelector(".empty").textContent.includes("未登録")')
        results['該当なしを不存在の証明にしない表示'] = True
        evaluate('document.getElementById("query").value="";document.querySelector(\'[data-tab="findings"]\').click()')
        for name, width, height in (('知見の広幅', 1400, 1200), ('知見の狭幅', 430, 1000)):
            command('Emulation.setDeviceMetricsOverride', dict(width=width, height=height, deviceScaleFactor=1, mobile=False))
            assert evaluate('document.documentElement.scrollWidth<=innerWidth'), name
            capture = command('Page.captureScreenshot', dict(format='png', captureBeyondViewport=False))
            (visual/(name+'.png')).write_bytes(base64.b64decode(capture['data']))
        assert not errors, errors
        results.update(全合格=True, JavaScript例外=errors, 原本読取=0, 金融再生=0)
        (HERE/'共通知見ビューの動作検査.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(dict(全合格=True, 検索件数=len(found), 狭幅横溢れ=False), ensure_ascii=False))
    finally:
        if connection:
            connection.close()
        process.terminate()
        process.wait(timeout=10)


if __name__ == '__main__':
    main()
