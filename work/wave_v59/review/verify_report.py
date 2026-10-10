"""全表示表とローカル案内を照合し、暗色報告を広狭画面で確認する。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
TASK=HERE.parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00056_小幅回収と移動平均の比較'
MAIN=OUT/'小幅回収と移動平均の説明と損益.html'
FULL=OUT/'全72条件.html'
SPEC=importlib.util.spec_from_file_location('browser_v59',ROOT/'work/wave_v52/review/verify_report.py')
BROWSER=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)
BROWSER.OUT=OUT
BROWSER.VISUAL=HERE/'visual'


def number(cell: object) -> float | None:
    """機能: HTMLの数値を表示符号・桁区切りから復元する。

    引数: cell(HTML要素)。返り値: 数値または未定義(float|None)。
    """
    value=cell.get_text(strip=True).replace(',','').replace('−','-').replace('%','')
    return None if value=='—' else float(value)


def equal(cell: object,value: float | None,decimals: int = 0) -> None:
    """機能: 表示丸めの範囲内で元の値と照合する。

    引数: cell(HTML要素)、value(float|None)、decimals(int)。返り値: なし(None)。
    """
    actual=number(cell)
    if value is None:
        assert actual is None
    else:
        assert actual is not None and abs(actual-value)<=.500001*10**(-decimals),(actual,value)


def aggregate(accounts: list,quote: bool=False) -> dict:
    """機能: 表示用合計の損益と枚数を原口座から別計算する。

    引数: accounts(list)、quote(bool)。返り値: 合計辞書(dict)。
    """
    views=[a['sensitivity']['売買気配'] if quote else a for a in accounts]
    out={k:sum(a[k] for a in views) for k in ('profit','loss','net','win_qty','loss_qty','flat_qty','wins','cycles')}
    out['win_rate']=out['wins']/out['cycles'] if out['cycles'] else None
    pw=out['profit']/out['win_qty'] if out['win_qty'] else None
    pl=out['loss']/out['loss_qty'] if out['loss_qty'] else None
    out['payoff']=pw/pl if pw is not None and pl else None
    return out


def main() -> None:
    """機能: 全表示表・リンクを検査し、3画面と最終SHAを保存する。

    引数: なし。返り値: なし(None)。売買結果と報告原本は変更しない。
    """
    originals={p.name:p.read_bytes() for p in (MAIN,FULL)}
    docs={name:BeautifulSoup(data.decode('utf-8'),'html.parser') for name,data in originals.items()}
    dev=json.loads((TASK/'dev/売買結果.json').read_text(encoding='utf-8'))
    hold=json.loads((TASK/'holdout/売買結果.json').read_text(encoding='utf-8'))
    selection=json.loads((TASK/'追加場適用前固定.json').read_text(encoding='utf-8'))
    dm={m['id']:m for m in dev['methods']};hm={m['id']:m for m in hold['methods']}
    allacc={key:m['accounts']+hm[key]['accounts'] for key,m in dm.items()}
    links=[]
    for name,doc in docs.items():
        assert not doc.select('script')
        for tag in doc.select('a[href]'):
            target=tag['href']
            if target.startswith('http'):
                continue
            if target.startswith('#'):
                assert doc.select_one(target) is not None,target
                continue
            assert (OUT/unquote(target.split('#')[0])).exists(),target
            links.append(target)
    assert 'README.md' in links and '../index.html' in links
    assert MAIN.name in (OUT/'README.md').read_text(encoding='utf-8')
    assert f'{OUT.name}/{MAIN.name}' in (OUT.parent/'index.html').read_text(encoding='utf-8')
    count=0
    for section in docs[MAIN.name].select('section'):
        method_id=selection['採用候補'][0] if section['id']=='candidate' else section.select_one('code').get_text(strip=True)
        accounts=allacc[method_id]
        tables=[t for t in section.select('table') if t.select_one('th').get_text()=='セッション']
        assert len(tables)==3
        for table_index,table in enumerate(tables):
            quote=table_index==2
            rows=table.select('tbody tr')
            assert len(rows)==(1 if table_index==0 else 26)
            for row in rows:
                cells=row.select('td');label=cells[0].get_text(strip=True)
                session=label.replace('〈追加〉','').replace(' 昼','_Day').replace(' 夜','_Night')
                for j,symbol in enumerate(('TOPIX','NK225')):
                    selected=[a for a in accounts if a['symbol']==symbol and (label=='合計' or a['session']==session)]
                    assert len(selected)==(25 if label=='合計' else 1)
                    v=aggregate(selected,quote)
                    for k,field in enumerate(('profit','loss','net')):
                        equal(cells[1+j*4+k],v[field]);count+=1
                    quantities=[int(x) for x in cells[4+j*4].get_text().split('/')]
                    assert quantities==[v[k] for k in ('win_qty','loss_qty','flat_qty')]
                    count+=3
    # ----------------------------------------
    # 主6条件および研究候補の冒頭比較。
    overview=next(t for t in docs[MAIN.name].select('table') if t.select_one('th').get_text()=='主手法')
    assert len(overview.select('tbody tr'))==12
    for row in overview.select('tbody tr'):
        c=row.select('td');family=c[0].get_text().split()[0];symbol='TOPIX' if c[1].get_text().startswith('TOPIX') else 'NK225'
        key=next(k for k in selection['主6条件'] if dm[k]['family']==family)
        accounts=[a for a in allacc[key] if a['symbol']==symbol];v=aggregate(accounts);q=aggregate(accounts,True)
        for i,value in enumerate((dm[key]['summary'][symbol]['net'],hm[key]['summary'][symbol]['net'],v['net'],q['net'])):
            equal(c[i+2],value);count+=1
        equal(c[6],v['win_rate']*100 if v['win_rate'] is not None else None,1);equal(c[7],v['payoff'],2);count+=2
    candidate=docs[MAIN.name].select_one('#candidate')
    if candidate:
        key=selection['採用候補'][0]
        for row in candidate.select_one('table').select('tbody tr'):
            c=row.select('td');symbol='TOPIX' if c[0].get_text().startswith('TOPIX') else 'NK225'
            selected=[a for a in allacc[key] if a['symbol']==symbol];v=aggregate(selected);q=aggregate(selected,True)
            for i,value in enumerate((dm[key]['summary'][symbol]['net'],dm[key]['summary'][symbol]['without_best'],
                                      hm[key]['summary'][symbol]['net'],v['net'],q['net'])):
                equal(c[1+i],value);count+=1
            equal(c[6],v['win_rate']*100 if v['win_rate'] is not None else None,1);equal(c[7],v['payoff'],2);count+=2
    # ----------------------------------------
    # 別画面の72条件を最高値だけでなく全行照合する。
    rows=docs[FULL.name].select('tbody tr');assert len(rows)==72
    for row in rows:
        c=row.select('td');key=c[0].get_text().split()[0]
        for j,symbol in enumerate(('TOPIX','NK225')):
            acc=[a for a in allacc[key] if a['symbol']==symbol];v=aggregate(acc);q=aggregate(acc,True)
            for k,value in enumerate((dm[key]['summary'][symbol]['net'],hm[key]['summary'][symbol]['net'],v['net'],q['net'],v['cycles'])):
                equal(c[1+j*5+k],value);count+=1
    BROWSER.PROBE=r'''<script>
try{
 if(document.documentElement.scrollWidth>innerWidth+2)throw Error('画面横溢れ');
 if(/undefined|NaN|__DATA__/.test(document.body.innerText))throw Error('未定義表示');
 document.body.dataset.check=JSON.stringify({全合格:true,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth,背景:getComputedStyle(document.body).backgroundColor});
}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''
    sources={name:data.decode('utf-8').replace('\r\n','\n') for name,data in originals.items()}
    screens=[BROWSER.render(sources[MAIN.name],'主報告_広幅',1500,1600),
             BROWSER.render(sources[MAIN.name],'主報告_狭幅',520,1600),
             BROWSER.render(sources[FULL.name],'全条件_広幅',1500,1600)]
    assert all((OUT/name).read_bytes()==data for name,data in originals.items())
    evidence={'合格':True,'表示数値照合数':count,'全条件表行数':72,'手法詳細数':7,
              'ローカルリンク数':len(links),'CSVリンク種類数':len({x for x in links if x.endswith('.csv')}),
              'READMEとindex往復案内':True,'JavaScriptなし':True,'目視確認':False,'画面':screens,
              'HTML_SHA256':{name:hashlib.sha256(data).hexdigest() for name,data in originals.items()}}
    (HERE/'HTML表示の独立検査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':
    main()
