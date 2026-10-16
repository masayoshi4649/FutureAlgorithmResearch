"""実市場へ接続せず、本文後HTTPトレーラーをcurlが取得することを確認する。"""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import capture


HERE=Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    """ローカル人工専用の分割本文と完結トレーラーを返す。"""

    def log_message(self, format: str, *args: object) -> None:
        """
        機能: 人工HTTPの通常アクセス表示を省く。
        引数: format(str)、args(tuple[object])はHTTP部品のログ値。
        返り値: None。市場データや通信を扱わない。
        """
        return None

    def do_GET(self) -> None:
        """
        機能: スナップショット通常ヘッダーと本文後trueトレーラーを人工生成する。
        引数: self(Handler)はローカル人工要求。
        返り値: None。原板を読まず、ループバックへ小さい本文だけ返す。
        """
        symbol=self.path.split('/')[-2]
        self.protocol_version='HTTP/1.1'
        self.send_response(200)
        for name,value in (
            ('Content-Type','application/x-ndjson'),('Transfer-Encoding','chunked'),('Trailer','X-History-Complete'),
            ('X-History-Session-Id',capture.SESSION),('X-History-Code',symbol),('X-History-Generation','人工領域'),
            ('X-History-As-Of','2026-10-14T01:00:00+09:00'),('X-History-Sequence','1')):
            self.send_header(name,value if name!='X-History-Generation' else 'fixture')
        self.end_headers()
        self.wfile.write(b'3\r\n{}\n\r\n0\r\nX-History-Complete: true\r\n\r\n')


def main() -> None:
    """
    機能: curlの本文と末尾true受領、false/欠落/通常ヘッダーだけの拒否を検査する。
    引数: なし。ローカル人工サーバー以外へ接続しない。
    返り値: None。現API0、金融0の検査証跡を保存する。
    """
    proof=HERE/'最後の応答と完結トレーラーのローカル人工検査.json';assert not proof.exists()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    checks=[]
    try:
        value=capture.download(f'http://127.0.0.1:{server.server_port}','TOPIX',HERE/'artificial_v2')
        assert value['snapshot']['complete']=='true' and value['bytes']==3
        checks.append('curlのdump-headerへ本文後のtrueトレーラーが保存される')
        text=(HERE/'artificial_v2/TOPIX_headers.txt').read_bytes().decode('iso-8859-1')
        interim='HTTP/1.1 100 Continue\r\nX-History-Code: 先行情報\r\n\r\n'
        path=HERE/'artificial_v2/100後の真のトレーラー.txt'
        path.write_bytes((interim.replace('先行情報','ignored')+text).encode('iso-8859-1'))
        assert capture.headers(path,'TOPIX')['complete']=='true'
        checks.append('先行100を分離し最終200の真のトレーラーを受理')
        variants={
            'false':text.replace('X-History-Complete: true','X-History-Complete: false'),
            '欠落':text.replace('X-History-Complete: true\r\n',''),
            '通常ヘッダーだけ':text.replace('X-History-Complete: true\r\n','').replace('\r\n\r\n','\r\nX-History-Complete: true\r\n\r\n',1),
            '別セッション':text.replace(capture.SESSION,'2026-10-14_Day'),
            '100後の通常ヘッダー偽Complete':interim.replace('先行情報','ignored')+text.replace('X-History-Complete: true\r\n','').replace('\r\n\r\n','\r\nX-History-Complete: true\r\n\r\n',1),
        }
        for name,body in variants.items():
            path=HERE/'artificial_v2'/f'{name}.txt';assert not path.exists();path.write_bytes(body.encode('iso-8859-1'))
            try:capture.headers(path,'TOPIX')
            except AssertionError:checks.append(name+'を拒否')
            else:raise AssertionError(name+'を受理してしまいました')
    finally:
        server.shutdown();server.server_close();worker.join(timeout=2)
    capture.save(proof,dict(全合格=True,検査件数=len(checks),検査=checks,市場API取得=0,金融再生=0,
        source_SHA256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('capture.py','artificial.py')}))
    print('最終応答と本文後トレーラーの人工検査7件合格。現API0。',flush=True)


if __name__=='__main__':main()
