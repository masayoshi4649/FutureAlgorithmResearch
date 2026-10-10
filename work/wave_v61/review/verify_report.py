"""00058の金額・枚数・期間表・全条件表と広狭画面を独立検証する。"""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import statistics
import sys
from urllib.parse import unquote

from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00058_場内完結の時間軸と積極度の再検証'
MAIN=OUT/'場内完結450条件の説明と損益.html'
FULL=OUT/'全450条件.html'
SYMBOLS={'TOPIX mini':'TOPIX','NK225 micro':'NK225'}
MODES={'売買気配・主評価':'quote','中値参考':'mid','待機指値の仮定':'passive'}


def equal(cell: object,value: object,digits: int=0) -> None:
    """機能: 表示丸めだけを許して金額や比率を元数値と照合する。

    引数: cell(HTML要素)、value(object)、digits(int)。返り値: なし(None)。
    """
    text=cell.get_text(strip=True).replace(',','').replace('−','-')
    if value is None:assert text=='—',text
    else:assert abs(float(text)-value)<=.500001*10**(-digits),(text,value)


def stats(chosen: list[dict]) -> dict:
    """機能: 銘柄内の費用後利益・損失、保有数量・資産下落を独立集計する。

    引数: chosen(list[dict])。返り値: 表示用独立数値(dict)。
    """
    result={key:sum(a[key] for a in chosen) for key in ('net','gross_profit','gross_loss','fees','win_qty','loss_qty','flat_qty','cycles')}
    profit=sum(a.get('profit',a.get('closed_net_profit',0)) for a in chosen)
    loss=sum(a.get('loss',a.get('closed_net_loss',0)) for a in chosen)
    result['pf']=profit/loss if loss else None
    result['payoff']=(profit/result['win_qty'])/(loss/result['loss_qty']) if result['win_qty'] and result['loss_qty'] and loss else None
    result['without_best']=result['net']-max(0.,max((a['net'] for a in chosen),default=0))
    result['positive_sessions']=sum(a['net']>0 for a in chosen)
    result['max_long_qty']=max((a['max_long_qty'] for a in chosen),default=0)
    result['max_short_qty']=max((a['max_short_qty'] for a in chosen),default=0)
    level=peak=dd=0.
    for a in sorted(chosen,key=lambda x:x['session']):
        dd=max(dd,a['drawdown'],peak-level-a['equity_min'])
        peak=max(peak,level+a['equity_max']);level+=a['net']
    result['drawdown']=dd
    holds=[x for a in chosen for x in a.get('group_hold_minutes',a.get('holding_values',[]))]
    result['hold_median_minutes']=statistics.median(holds) if holds else None
    return result


def main() -> None:
    """機能: 全CSVとHTML表を元結果へ照合し、通信遮断Chromeの画面を保存する。

    引数: なし。返り値: なし(None)。目視確認は画像を読んだ後で別途記録する。
    """
    methods={}
    for branch in ('directional','inventory'):
        raw=json.loads((WORK/branch/'集計結果.json').read_text(encoding='utf-8'))
        for method in raw['methods']:
            key=method.get('condition_id',method['id'])
            item=methods.setdefault(key,{'family':method['family'],'accounts':[],'hold':{}})
            item['accounts'].extend(method['accounts'])
            if branch=='directional':
                for mode,field in [('quote','summary'),('mid','mid_summary')]:
                    for symbol in ('TOPIX','NK225'):item['hold'][(mode,symbol)]=method[field][symbol]['hold_median_minutes']
            else:
                for symbol in ('TOPIX','NK225'):item['hold'][(method['price_mode'],symbol)]=method['summary'][symbol]['hold_median_minutes']
    assert len(methods)==450
    originals={p.name:p.read_bytes() for p in (MAIN,FULL)}
    docs={name:BeautifulSoup(raw.decode('utf-8'),'html.parser') for name,raw in originals.items()}
    links=numbers=periods=compares=matrix=0
    missing=[]
    preliminary='--preliminary' in sys.argv
    for name,doc in docs.items():
        ids=[v['id'] for v in doc.select('[id]')];assert len(ids)==len(set(ids))
        assert not any(x in doc.get_text() for x in ('undefined','NaN','Infinity','__DATA__'))
        for a in doc.select('a[href]'):
            url=a['href']
            if url.startswith(('http:','https:')):continue
            if url.startswith('#'):assert doc.find(id=url[1:]) is not None,url
            elif not (OUT/unquote(url.split('#')[0])).exists():
                if preliminary:missing.append(url)
                else:raise AssertionError(url)
            links+=1
    # ----------------------------------------
    # 全54,000口座の公開CSVが、同じ条件と価格モデルの元結果を指すことを確認する。
    index={(key,a['session'],a['symbol'],a['price_mode']):a for key,m in methods.items() for a in m['accounts']}
    csvrows=0
    with (OUT/'全450条件のセッション損益.csv').open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            key=(row['手法ID'],row['セッション'],row['銘柄'],MODES[row['約定モデル']]);a=index.pop(key)
            for label,field in [('実現利益円','gross_profit'),('実現損失円','gross_loss'),('手数料円','fees'),('純収支円','net'),
                                ('勝ち枚数','win_qty'),('負け枚数','loss_qty'),('同値枚数','flat_qty'),
                                ('最大買枚数','max_long_qty'),('最大売枚数','max_short_qty'),('最大資産下落円','drawdown'),('決済数','cycles')]:
                assert abs(float(row[label])-a[field])<1e-6,(key,label)
                numbers+=1
            csvrows+=1
    assert not index and csvrows==54000
    weekrows=0
    with (OUT/'全450条件の週と全体損益.csv').open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            chosen=[a for a in methods[row['手法ID']]['accounts'] if a['symbol']==row['銘柄'] and a['price_mode']==MODES[row['約定モデル']]]
            if row['期間']!='全25場':chosen=[a for a in chosen if a['week']==row['期間']]
            v=stats(chosen)
            for label,field in [('実現利益円','gross_profit'),('実現損失円','gross_loss'),('手数料円','fees'),('純収支円','net'),
                                ('勝ち枚数','win_qty'),('負け枚数','loss_qty'),('同値枚数','flat_qty'),('利益損失比','pf'),
                                ('平均勝ち負け比','payoff'),('最大資産下落円','drawdown')]:
                if v[field] is None:assert row[label]==''
                else:assert abs(float(row[label])-v[field])<1e-6,(row['手法ID'],label)
                numbers+=1
            weekrows+=1
    assert weekrows==8640
    for row in docs[MAIN.name].select('table tbody tr'):
        anchor=row.select_one('a[href^="#"]')
        if not anchor:continue
        key=anchor['href'][1:]
        if key not in methods:continue
        cells=row.select('td');symbol=SYMBOLS[cells[1].get_text(strip=True)]
        v=stats([a for a in methods[key]['accounts'] if a['symbol']==symbol and a['price_mode']=='quote'])
        if len(cells)==7:
            for column,field in [(3,'net'),(4,'drawdown'),(5,'without_best')]:equal(cells[column],v[field]);numbers+=1
            other='NK225' if symbol=='TOPIX' else 'TOPIX'
            equal(cells[6],stats([a for a in methods[key]['accounts'] if a['symbol']==other and a['price_mode']=='quote'])['net'])
            numbers+=1
            continue
        for column,field,digits in [(2,'net',0),(3,'pf',2),(4,'payoff',2),(5,'drawdown',0),(7,'without_best',0),(9,'cycles',0)]:
            equal(cells[column],v[field],digits);numbers+=1
        assert cells[6].get_text(strip=True)==f'{v["positive_sessions"]}/25'
        assert cells[8].get_text(strip=True)==f'{v["win_qty"]}/{v["loss_qty"]}'
        if len(cells)>10:equal(cells[10],methods[key]['hold'][('quote',symbol)],1);numbers+=1
    # ----------------------------------------
    # 各章の期間・場別損益は選択されている方式だけを独立に合算する。
    for section in docs[MAIN.name].select('section[id]'):
        key=section['id'].removeprefix('主_')
        if key not in methods:continue
        method=methods[key]
        for table in section.select('table'):
            head=table.select_one('th').get_text(strip=True)
            if head!='期間':continue
            for row in table.select('tbody tr'):
                cells=row.select('td');label=cells[0].get_text(strip=True);symbol=SYMBOLS[cells[1].get_text(strip=True)]
                chosen=[a for a in method['accounts'] if a['symbol']==symbol and a['price_mode']=='quote']
                if ' 昼' in label or ' 夜' in label:
                    session=label.replace(' 昼','_Day').replace(' 夜','_Night');chosen=[a for a in chosen if a['session']==session]
                    assert len(chosen)==1
                elif not label.startswith('全25場'):chosen=[a for a in chosen if a['week']==label[:10]]
                v=stats(chosen)
                for cell,field in zip(cells[2:6],('gross_profit','gross_loss','fees','net')):equal(cell,v[field]);numbers+=1
                assert cells[6].get_text(strip=True)=='/'.join(str(v[k]) for k in ('win_qty','loss_qty','flat_qty'))
                assert cells[7].get_text(strip=True)==f'{v["max_long_qty"]}/{v["max_short_qty"]}'
                periods+=1
        # 同幅の時間・積極度比較を18行ずつ照合する。
        for table in section.select('table'):
            if table.select_one('th').get_text(strip=True)!='保有上限':continue
            for row in table.select('tbody tr'):
                cells=row.select('td');minutes=int(cells[0].get_text(strip=True).replace('分',''));aggression=cells[1].get_text(strip=True)
                family=method['family'];width='W10' if family.startswith('D') else 'D075'
                target=f'{family}_H{minutes}_{width}_{aggression}' if family.startswith('D') else f'{family}_H{minutes:03d}_{width}_{aggression}'
                cursor=2
                for symbol in ('TOPIX','NK225'):
                    v=stats([a for a in methods[target]['accounts'] if a['symbol']==symbol and a['price_mode']=='quote'])
                    v['hold_median_minutes']=methods[target]['hold'][('quote',symbol)]
                    for field,digits in [('net',0),('pf',2),('cycles',0),('drawdown',0),('hold_median_minutes',1)]:
                        equal(cells[cursor],v[field],digits);numbers+=1;cursor+=1
                matrix+=1
    for row in docs[FULL.name].select('table tbody tr'):
        cells=row.select('td');key=cells[0].get_text(strip=True).split()[0];method=methods[key];cursor=1
        for symbol in ('TOPIX','NK225'):
            chosen=lambda mode:[a for a in method['accounts'] if a['symbol']==symbol and a['price_mode']==mode]
            v=stats(chosen('quote'))
            for mode in ('quote','mid')+(('passive',) if method['family'].startswith('I') else ()):
                equal(cells[cursor],stats(chosen(mode))['net']);cursor+=1;numbers+=1
            for field,digits in [('pf',2),('payoff',2),('drawdown',0),('cycles',0)]:
                equal(cells[cursor],v[field],digits);cursor+=1;numbers+=1
        compares+=1
    assert compares==450 and matrix==180
    # ----------------------------------------
    # HTMLの複製を実Chromeで表示し、文書全体の横溢れ・暗色背景を検査する。
    spec=importlib.util.spec_from_file_location('描画監査',ROOT/'work/wave_v52/review/verify_report.py')
    browser=importlib.util.module_from_spec(spec);spec.loader.exec_module(browser)
    browser.OUT=OUT;browser.VISUAL=HERE/'visual'
    browser.PROBE='''<script>try{if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');document.body.dataset.check=JSON.stringify({全合格:true,幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:getComputedStyle(document.body).backgroundColor});}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e)});}</script>'''
    shots=[browser.render(originals[MAIN.name].decode('utf-8'),'全体',1500,1600),
           browser.render(originals[MAIN.name].decode('utf-8'),'狭幅',520,1600),
           browser.render(originals[FULL.name].decode('utf-8'),'全450条件',1500,1450)]
    record=dict(合格=True,暫定確認=preliminary,未生成リンク=missing,目視確認=False,数値照合=numbers,CSV口座行=csvrows,CSV期間行=weekrows,期間と場行=periods,
                時間積極度比較=matrix,全条件比較=compares,リンク=links,画面=shots,
                HTML_SHA256={name:hashlib.sha256(raw).hexdigest() for name,raw in originals.items()})
    name='HTML表示の暫定検査.json' if preliminary else 'HTML表示の独立検査.json'
    (HERE/name).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
