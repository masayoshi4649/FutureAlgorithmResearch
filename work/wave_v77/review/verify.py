"""公開HTMLの会計と注文を保存結果へ照合し、実ブラウザの全場操作を検査する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np
from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
OUT=ROOT/'アルゴリズム調査/00073_二市場判断と金額利益8割への改善'
NAMES=('金額利益8割を目指す改善と全セッション損益.html','全492条件の比較.html')


def load(path: Path) -> object:
    """機能: 検査元資料を読み込む。

    引数: path(Path)。返り値: 内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def data_check(data: dict,all_conditions: bool) -> int:
    """機能: 埋込会計・全場・注文価格・数量・時刻を元結果と照合する。

    引数: data(dict)、all_conditions(bool)。返り値: 照合ID数(int)。
    """
    spec=importlib.util.spec_from_file_location('会計表示検査77',WORK/'accounting.py');account=importlib.util.module_from_spec(spec);spec.loader.exec_module(account)
    fixed=load(WORK/'事前固定.json');meta=load(WORK/'inputs/metadata.json');ready={}
    for p in meta['input_paths']['ready']:ready.update(load(ROOT/p))
    ready.update(load(WORK/'inputs/extra_inputs.pkl'))
    values=data['methods'] if all_conditions else [data['benchmark']]+[v for m in data['methods'] for v in (m,*m['controls'])]
    seen=set()
    for v in values:
        ident=v['id']
        if ident in seen:continue
        seen.add(ident);saved=load(WORK/'results'/(ident+'.json'));rows=list(saved['rows']);periods=dict(saved['periods'])
        assert saved['config']==v['config']
        path=WORK/'unseen/results'/(ident+'.json')
        if path.exists():
            extra=load(path);rows+=extra['rows'];periods.update(extra['periods']);periods['全30']={s:account.aggregate(rows,s,fixed['全30']) for s in ('TOPIX','NK225')}
        for name,period in periods.items():assert period==v['periods'][name],(ident,name)
        lookup={(r['session'],r['symbol']):r for r in rows}
        assert len(v['rows'])==len(rows)
        for r in v['rows']:assert all(lookup[(r['session'],r['symbol'])][k]==x for k,x in r.items())
        if all_conditions:continue
        ledgers=load(WORK/'ledgers'/(ident+'.pkl'));path=WORK/'unseen/ledgers'/(ident+'.pkl')
        if path.exists():ledgers.update(load(path))
        for key,ledger in ledgers.items():
            name='|'.join(key);o=np.asarray(v['orders'][name]);original=ledger['orders']
            assert len(o)==len(original)
            if not len(o):continue
            assert np.array_equal(o[:,:10],original)
            times=ready[key]['time_s'];assert np.array_equal(o[:,11],times[original[:,0].astype(int)])
            assert np.array_equal(v['decisionTimes'][name],times[original[:,1].astype(int)])
            t=ledger['trades'];nets=[None if order[7] else float(t[t[:,0]==order[2],10].sum()) for order in original]
            assert nets==v['orderNet'][name]
    return len(seen)


def main() -> None:
    """機能: 会計検査と広幅・狭幅・売買図の操作検査を実行する。

    引数: CLI --all(bool)。返り値: なし(None)。
    """
    p=argparse.ArgumentParser();p.add_argument('--all',action='store_true');a=p.parse_args();name=NAMES[int(a.all)]
    source=(OUT/name).read_text(encoding='utf8');soup=BeautifulSoup(source,'html.parser')
    assert not soup.select('script[src],iframe,link[rel=stylesheet],img[src^=http]')
    count=data_check(json.loads(soup.select_one('#report-data').string),a.all)
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location('隔離ブラウザ77',ROOT/'work/wave_v52/review/verify_report.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    helper.OUT=OUT;helper.VISUAL=HERE/'visual';helper.VISUAL.mkdir(exist_ok=True)
    helper.PROBE='<script>'+(HERE/('probe_all.js' if a.all else 'probe_main.js')).read_text(encoding='utf8')+'</script>'
    prefix='全一覧' if a.all else '主報告'
    results=[helper.render(source,prefix+'_全体',1450,1500),helper.render(source,prefix+'_狭幅',520,1350)]
    if not a.all:
        results.append(helper.render(source,'全場表',1450,1400,'<script>const e=document.querySelector("#method-0");e.querySelector(".sessions-details").open=true;document.querySelector("main").replaceChildren(e.querySelector("h2"),e.querySelector(".session-table"));window.scrollTo(0,0);</script>'))
        results.append(helper.render(source,'売買図',1450,1200,'<script>const e=document.querySelector("#method-0");const s=e.querySelector(".session-select");s.value="2026-10-07_Day";s.dispatchEvent(new Event("change"));document.querySelector("main").replaceChildren(e.querySelector("h2"),e.querySelector(".chart-box"),e.querySelector(".order-history"));window.scrollTo(0,0);</script>'))
    proof=dict(全合格=True,目視確認=False,HTML_SHA256=hashlib.sha256((OUT/name).read_bytes()).hexdigest(),一致条件数=count,結果=results)
    (HERE/(prefix+'_表示検査.json')).write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
