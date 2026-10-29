"""SessionViewerの数値とPNGを同じ指紋で取得し、作業領域だけに保存する。"""
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path


def fetch(path):
    """
    機能: 読取API応答を取得。引数:path(str)。返り値:tuple[bytes,str]。
    """
    with urllib.request.urlopen('http://127.0.0.1:8091'+path,timeout=120) as r:
        return r.read(),r.headers.get('X-Chart-Data-SHA256','')


def main():
    """
    機能: 大きい損失の5段チャートを確認用に取得。引数:なし。返り値:None。
    """
    here=Path(__file__).resolve().parent;study=here.parents[1]/'アルゴリズム調査/00170_複数時間足のテクニカルと指標出口'
    catalog=str(study/'比較.resources.json');examples=json.loads((here/'loss-evidence.json').read_text(encoding='utf-8'))
    raw,_=fetch('/api/resources?'+urllib.parse.urlencode({'catalog_path':catalog}));resources=json.loads(raw)['resources']
    known={r['id'] for r in resources};chosen=[]
    for symbol,mid in [('NK225','F09A_I'),('NK225','F10B_I'),('TOPIX','F03B_F')]:
        e=next(x for x in examples if x['symbol']==symbol and x['config_id']==mid)
        assert e['resource'] in known
        start=e['episode']['entry_ns']//1000000-5*60000;end=e['episode']['exit_ns']//1000000+5*60000
        query={'catalog_path':catalog,'resource':e['resource'],'interval':'1','price':'last','width':1600,'height':1200,'from':start,'to':end}
        raw,_=fetch('/api/chart?'+urllib.parse.urlencode(query));meta=json.loads(raw)
        png,psha=fetch(meta['png_url']);data,dsha=fetch(meta['data_url'])
        assert meta['data_sha256']==psha==dsha,(psha,dsha)
        name=f"{symbol}_{e['session']}_{mid}"
        (here/(name+'.png')).write_bytes(png);(here/(name+'.visual.json')).write_bytes(data)
        obj=json.loads(data)
        chosen.append({'resource':e['resource'],'from':start,'to':end,'data_sha256':psha,'png_sha256':hashlib.sha256(png).hexdigest(),'summary':obj.get('summary'),'entry':e['entry'],'close':e['close'],'visual_file':name+'.png'})
        print(json.dumps({'画像':name,'同指紋':psha,'会計':obj.get('summary')},ensure_ascii=False),flush=True)
    (here/'visual-checks.json').write_text(json.dumps(chosen,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
