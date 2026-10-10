"""中期・グリッド報告の表、案内リンクと暗色の広狭表示を独立照合する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
WORK=HERE.parent
OUT=ROOT/'アルゴリズム調査/00057_中期売買と週内グリッドの手数料込み検証'
MAIN=OUT/'30〜60分売買と週内グリッドの説明と損益.html'
FULL=OUT/'全160条件.html'


def equal(cell: object,value: object,digits: int=0) -> None:
    """機能: 表示上の桁丸めだけを許容し、元台帳の数値と照合する。

    引数: cell(HTML要素)、value(object)、digits(int)。返り値: なし(None)。
    """
    text=cell.get_text(strip=True).replace(',','').replace('−','-').replace('%','')
    if value is None:assert text=='—',text
    else:assert abs(float(text)-value)<=.500001*10**(-digits),(text,value)


def main() -> None:
    """機能: 主要条件全表・160比較行を照合し、実Chromeで画面を保存する。

    引数: なし。返り値: なし(None)。原報告を編集しない。
    """
    originals={p.name:p.read_bytes() for p in (MAIN,FULL)}
    docs={name:BeautifulSoup(raw.decode('utf-8'),'html.parser') for name,raw in originals.items()}
    medium=json.loads((WORK/'medium/売買結果.json').read_text(encoding='utf-8'))['methods']
    grid=json.loads((WORK/'grid/売買結果.json').read_text(encoding='utf-8'))['methods']
    variants={(m['condition_id'],m['price_mode']):m for m in grid}
    methods={m['id']:m for m in medium+grid}
    symbols={'TOPIX mini':'TOPIX','NK225 micro':'NK225'}
    links=numbers=periods=accountrows=compare=0
    for name,doc in docs.items():
        ids=[v['id'] for v in doc.select('[id]')];assert len(ids)==len(set(ids))
        assert not any(v in doc.get_text() for v in ('undefined','NaN','Infinity','__DATA__'))
        for a in doc.select('a[href]'):
            target=a['href']
            if target.startswith(('http:','https:')):continue
            if target.startswith('#'):assert doc.select_one('[id="'+target[1:]+'"]') is not None
            else:assert (OUT/unquote(target.split('#')[0])).exists(),target
            links+=1
    main_doc=docs[MAIN.name]
    for section in main_doc.select('section[id]'):
        method=methods[section['id']];isgrid='condition_id' in method
        for table in section.select('table'):
            header=table.select_one('th').get_text(strip=True)
            if header not in ('期間','セッション'):continue
            mode='passive' if '待機指値' in table.find_parent('details').select_one('summary').get_text() else 'quote'
            accounts=(variants[(method['condition_id'],mode)]['accounts'] if isgrid else
                      [a for a in method['accounts'] if a['price_mode']==mode])
            for row in table.select('tbody tr'):
                cells=row.select('td');label=cells[0].get_text(strip=True);symbol=symbols[cells[1].get_text(strip=True)]
                chosen=[a for a in accounts if a['symbol']==symbol]
                if header=='期間':
                    if not label.startswith('全25場'):chosen=[a for a in chosen if a['week']==label[:10]]
                    periods+=1
                else:
                    session=label.replace(' 昼','_Day').replace(' 夜','_Night');chosen=[a for a in chosen if a['session']==session]
                    assert len(chosen)==1;accountrows+=1
                expected=[sum(a['gross_profit'] for a in chosen),sum(a['gross_loss'] for a in chosen),
                          sum(a['fees'] for a in chosen),sum(a['unrealized_end']-a['unrealized_start'] for a in chosen),
                          sum(a['net'] for a in chosen)]
                for cell,val in zip(cells[2:7],expected):equal(cell,val);numbers+=1
                assert cells[7].get_text(strip=True)=='/'.join(str(sum(a[k] for a in chosen)) for k in ('win_qty','loss_qty','flat_qty'))
                if header=='セッション':assert cells[8].get_text(strip=True)==f'{chosen[0].get("end_long_qty",0)}/{chosen[0].get("end_short_qty",0)}'
    for row in main_doc.select('table tbody tr'):
        anchor=row.select_one('a[href^="#"]')
        if not anchor:continue
        method=methods[anchor['href'][1:]];cells=row.select('td');symbol=symbols[cells[1].get_text(strip=True)]
        stats=method['summary'][symbol];isgrid='condition_id' in method
        for index,key,digits in ((2,'net',0),(3,'fees',0),(4,'drawdown',0),(6,'payoff',2)):
            equal(cells[index],stats[key],digits);numbers+=1
        equal(cells[5],None if stats['win_rate'] is None else stats['win_rate']*100,1);numbers+=1
        if isgrid:
            assert cells[7].get_text(strip=True)==f'{stats["max_long_qty"]}/{stats["max_short_qty"]}'
            reference=variants[(method['condition_id'],'passive')]['summary'][symbol]['net']
        else:
            equal(cells[7],stats['hold_median_minutes'],1);numbers+=1
            reference=method['mid_summary'][symbol]['net']
        equal(cells[8],reference);numbers+=1
    for row in docs[FULL.name].select('table tbody tr'):
        cells=row.select('td');key=cells[0].get_text(strip=True).split()[0];method=methods[key];isgrid='condition_id' in method
        cursor=1
        for symbol in ('TOPIX','NK225'):
            values=[method['summary'][symbol]['net'],variants[(method['condition_id'],'mid')]['summary'][symbol]['net'] if isgrid else method['mid_summary'][symbol]['net']]
            if isgrid:values.append(variants[(method['condition_id'],'passive')]['summary'][symbol]['net'])
            values += [method['summary'][symbol]['drawdown'],method['summary'][symbol]['cycles']]
            for value in values:equal(cells[cursor],value);cursor+=1;numbers+=1
        compare+=1
    assert compare==160
    # ----------------------------------------
    # 元HTMLの複製だけを、外部通信を遮断した実ブラウザーで表示する。
    spec=importlib.util.spec_from_file_location('chrome_v60',ROOT/'work/wave_v52/review/verify_report.py')
    browser=importlib.util.module_from_spec(spec);spec.loader.exec_module(browser)
    browser.OUT=OUT;browser.VISUAL=HERE/'visual'
    browser.PROBE='''<script>try{if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');document.body.dataset.check=JSON.stringify({全合格:true,幅:innerWidth,文書幅:document.documentElement.scrollWidth,背景:getComputedStyle(document.body).backgroundColor});}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e)});}</script>'''
    main_source=originals[MAIN.name].decode('utf-8');full_source=originals[FULL.name].decode('utf-8')
    shots=[browser.render(main_source,'全体',1500,1500),browser.render(main_source,'狭幅',520,1500),
           browser.render(full_source,'全160条件',1500,1450)]
    evidence=dict(合格=True,目視確認=False,静的リンク=links,数値照合=numbers,期間行=periods,場行=accountrows,全比較行=compare,
                  画面=shots,HTML_SHA256={name:hashlib.sha256(raw).hexdigest() for name,raw in originals.items()})
    (HERE/'HTML表示の独立検査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
