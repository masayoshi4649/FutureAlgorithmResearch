"""共同方向の主報告と全条件を、独立した実ブラウザ表示で照合する。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00071_二指数の共同方向と先行追随'
NAMES=('二指数を同時に見る手法と全セッション損益.html','全336条件の比較.html')


def independent_data(data: dict,all_conditions: bool) -> int:
    """機能: HTMLの埋込会計と元結果・台帳を独立に照合する。

    引数: data(dict)、all_conditions(bool)。返り値: 照合した会計条件数(int)。
    """
    work=HERE.parent
    count=0
    variants=data['methods'] if all_conditions else [v for m in data['methods'] for v in (m,m['single'])]
    if not all_conditions:
        matched=json.loads((work/'analysis/同じ新規機会での相手確認診断.json').read_text(encoding='utf8'))
        assert data['sharedOpportunity']['比較']==matched['比較']
        assert data['sharedOpportunity']['全明細数']==142
    for value in variants:
        saved=json.loads((work/'results'/(value['id']+'.json')).read_text(encoding='utf8'))
        assert value['config']==saved['config'] and value['periods']==saved['periods']
        lookup={(r['session'],r['symbol']):r for r in saved['rows']}
        for row in value['rows']:
            assert all(lookup[(row['session'],row['symbol'])][k]==v for k,v in row.items())
        assert len(value['rows'])==58
        count+=1
    return count


def main() -> None:
    """機能: 会計・操作・座標を検査し、広幅・狭幅と拡大図を保存する。

    引数: --all(bool)。返り値: なし(None)。公開HTMLは変更しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--all',action='store_true');args=parser.parse_args()
    idx=int(args.all);prefix='全一覧' if args.all else '主報告';source_path=OUT/NAMES[idx]
    initial_hash=hashlib.sha256(source_path.read_bytes()).hexdigest()
    source=source_path.read_text(encoding='utf8');soup=BeautifulSoup(source,'html.parser')
    assert not soup.select('script[src],iframe,link[rel=stylesheet],img[src^=http]')
    count=independent_data(json.loads(soup.select_one('#report-data').string),args.all)
    sys.dont_write_bytecode=True
    spec=importlib.util.spec_from_file_location('隔離表示',ROOT/'work/wave_v52/review/verify_report.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    helper.OUT=OUT;helper.VISUAL=HERE/'visual';helper.VISUAL.mkdir(exist_ok=True)
    probe=(HERE/('probe_all.js' if args.all else 'probe_main.js')).read_text(encoding='utf8')
    helper.PROBE='<script>'+probe+'</script>'
    results=[helper.render(source,prefix+'_全体',1450,1500),helper.render(source,prefix+'_狭幅',520,1350)]
    if not args.all:
        results.append(helper.render(source,'共同方向_全場表',1450,1600,'<script>const e=document.querySelector("#method-1");document.querySelector("main").replaceChildren(e.querySelector("h2"),e.querySelector(".session-table"));window.scrollTo(0,0);</script>'))
        results.append(helper.render(source,'共同方向_売買図',1450,1100,'<script>const e=document.querySelector("#method-1");const select=e.querySelector(".session-select");select.value="2026-10-07_Day";select.dispatchEvent(new Event("change"));document.querySelector("main").replaceChildren(e.querySelector("h2"),e.querySelector(".chart-box"),e.querySelector(".history"));window.scrollTo(0,0);</script>'))
    assert initial_hash==hashlib.sha256(source_path.read_bytes()).hexdigest(),'検査中に公開HTMLが変更されました'
    proof=dict(全合格=True,目視確認=False,HTML_SHA256=initial_hash,元結果との一致条件数=count,結果=results)
    (HERE/(prefix+'_表示の独立検査.json')).write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
