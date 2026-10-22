"""Chrome最小ウィンドウ幅を避け、実viewport440の所有表示をCDPで撮影する。"""

import base64
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time
import urllib.request

import websocket

import verify_visual as V


HERE=Path(__file__).resolve().parent


class Connection:
    """隔離Chromeのローカル描画操作だけへ接続する。"""

    def __init__(self, url: str) -> None:
        """
        機能: 所有ChromeのDevTools接続を開く。
        引数: url(str)は127.0.0.1のWebSocket接続先。
        返り値: None。市場又は取引APIへ接続しない。
        """
        assert url.startswith('ws://127.0.0.1:')
        self.socket=websocket.create_connection(url,timeout=20,suppress_origin=True)
        self.serial=0

    def call(self, method: str, params: dict|None=None) -> dict:
        """
        機能: 一つの描画命令の終端を待ち、対応する応答だけ返す。
        引数: method(str)はDevTools命令、params(dict|None)は引数。
        返り値: dictは応答結果。待機は20秒以下で失敗を停止する。
        """
        self.serial+=1;serial=self.serial
        self.socket.send(json.dumps(dict(id=serial,method=method,params=params or {})))
        while True:
            result=json.loads(self.socket.recv())
            if result.get('id')==serial:
                assert 'error' not in result,result
                return result.get('result',{})


def evaluate(connection: Connection, expression: str) -> object:
    """
    機能: 所有画面のDOM状態を取得し、JavaScript例外を無視しない。
    引数: connection(Connection)は隔離Chrome、expression(str)は表示検査。
    返り値: objectはJSON原始値。金融や市場データを取得しない。
    """
    answer=connection.call('Runtime.evaluate',dict(expression=expression,returnByValue=True))
    assert 'exceptionDetails' not in answer,answer
    return answer['result'].get('value')


def main() -> None:
    """
    機能: 同一所有HTMLで71操作を再確認し、viewportとPNGを440×1000へ揃える。
    引数: なし。前回の公開HTML同bytes保全だけを入力にする。
    返り値: None。旧画像・旧証跡を保持し、CDP版と差分説明を新規保存する。
    """
    folder=HERE/'mobile_cdp440';assert not folder.exists();folder.mkdir()
    raw=(HERE/'公開HTMLの同bytes保全.html').read_bytes();assert V.digest(raw)==V.EXPECTED
    capture,probe=V.probe()
    probe=probe.replace('documentWidth:document.documentElement.scrollWidth',
        'documentWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth,visualWidth:visualViewport.width,screenWidth:screen.width')
    source=raw.decode('utf8').replace('<head>','<head>'+capture,1).replace('</body>',probe+'</body>',1)
    target=folder/'所有検査画面.html';target.write_text(source,encoding='utf8')
    profile=folder/'profile'
    command=[str(V.CHROME),'--headless=new','--disable-gpu','--no-first-run',
        '--disable-background-networking','--disable-component-update','--disable-sync',
        '--proxy-server=http://127.0.0.1:9','--remote-debugging-port=0',
        '--window-size=800,1100','--user-data-dir='+str(profile.resolve()),'about:blank']
    stderr=(folder/'描画stderr.txt').open('wb')
    process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
    connection=None
    try:
        deadline=time.monotonic()+12;portfile=profile/'DevToolsActivePort'
        while not portfile.exists():
            assert time.monotonic()<deadline and process.poll() is None,'DevTools起動終端なし'
            time.sleep(.05)
        port=int(portfile.read_text(encoding='utf8').splitlines()[0])
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/json/list',timeout=5) as response:tabs=json.load(response)
        tab=next(t for t in tabs if t['type']=='page')
        connection=Connection(tab['webSocketDebuggerUrl'])
        connection.call('Page.enable');connection.call('Runtime.enable')
        connection.call('Emulation.setDeviceMetricsOverride',dict(width=440,height=1000,deviceScaleFactor=1,mobile=True))
        connection.call('Page.navigate',dict(url=target.resolve().as_uri()))
        answer=None;deadline=time.monotonic()+15
        while not answer:
            answer=evaluate(connection,"document.body&&document.body.dataset.visualQa||null")
            assert time.monotonic()<deadline,'表示検査の終端なし'
            if not answer:time.sleep(.05)
        result=json.loads(answer);assert result['passed'],result
        viewport=result['viewport']
        assert viewport['width']==viewport['visualWidth']==viewport['screenWidth']==440,viewport
        assert viewport['documentWidth']<=viewport['clientWidth']<=440,viewport
        assert viewport['height']==1000 and result['errors']==[]
        assert result['selectedUIDs']==[1] and result['weightedFills']==630
        screenshot=connection.call('Page.captureScreenshot',dict(format='png',fromSurface=True,
            captureBeyondViewport=False,clip=dict(x=0,y=0,width=440,height=1000,scale=1)))
        image=folder/'画面.png';payload=base64.b64decode(screenshot['data'])
        assert payload[:8]==b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II',payload[16:24])==(440,1000)
        image.write_bytes(payload)
        old=json.loads((HERE/'mobile/DOM検査.json').read_text(encoding='utf8'))
        proof=dict(passed=True,source_SHA256=V.EXPECTED,source='公開HTMLの同bytes保全.html',
            result=result,PNG_size=[440,1000],image_path=image.relative_to(V.ROOT).as_posix(),
            image_SHA256=V.digest(payload),old_mobile_viewport=old['viewport'],old_mobile_PNG_size=[440,1000],
            初版mobile判定='innerWidth500に対しPNG440だったため画面幅一致と横切れなしの結論を撤回。旧画像と旧証跡は保全。',
            対応='CDP EmulationでCSS viewport440とPNG440を一致させ、同じ71操作を実施。元HTMLや数値は変更しない。',
            元HTML追加読取=0,financial_result_reads=0,NPZ_reads=0,market_reads=0,financial_replay=0,market_API=0,
            browser_CDP=True,担当画像目視=False,根画像目視=False)
        path=folder/'実viewport440とPNG幅を揃えた二銘柄表示確認.json'
        path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
        print(json.dumps(dict(passed=True,checks=len(result['checks']),viewport=viewport,image=proof['image_path'],proof=str(path),SHA256=V.digest(path.read_bytes())),ensure_ascii=False))
    finally:
        if connection is not None:connection.socket.close()
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        stderr.close()


# ----------------------------------------


if __name__=='__main__':
    main()
