"""順逆と時刻の表示を実結果未読の四十八政策だけで検査する。"""

from copy import deepcopy
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

import report_v4 as R


HERE=Path(__file__).resolve().parent
COUNTS={}


def check(value: bool,label: str) -> None:
    """
    機能: 合成期待の成否を項目別に記録する。
    引数: value(bool)は期待、label(str)は項目。
    返り値: None。不一致は停止する。
    """
    assert value,label
    COUNTS[label]=COUNTS.get(label,0)+1


def fixture() -> dict:
    """
    機能: 市場と無関係な三入口・順逆・二出口・二執行・二時刻の会計を作る。
    引数: なし。
    返り値: dictは48政策×40場×2商品を含む予定schema。
    """
    scenes=[str(date(2033,1,1)+timedelta(days=i//2))+('_Day' if i%2==0 else '_Night') for i in range(40)]
    specs=[]
    for family in ('COMMON20','OPEN20','LAG20'):
        for direction in ('direct','reverse'):
            for xm in (5,4):
                for em in (0,3):
                    for tm in (0,1):
                        ident=f'{family}_{direction}_X{xm}_P{em}_T{tm}'
                        specs.append(dict(id=ident,family=family,entry_id=family,name='合成'+ident,description='保存元の候補で同時点に参加する。',
                            direction_mode=direction,exit_mode=xm,execution_mode=em,time_mode=tm,guard=2))
    runs=[]
    for k,spec in enumerate(specs):
        for i,scene in enumerate(scenes):
            for symbol in R.SYMBOLS:
                active=i>=4;net=(100.+k if i<32 else -40.) if active else 0.
                runs.append(dict(method=spec['id'],session=scene,symbol=symbol,net=net,realized=net,
                    profit=max(net,0),loss=max(-net,0),fees=836. if active else 0,max_drawdown=40.,parents=int(active),
                    wins=int(net>0),losses=int(net<0),closed_quantity=(10 if symbol=='TOPIX' else 20) if active else 0,
                    canceled=0,fills=2 if active else 0,halted=0,unclosed=0))
    return dict(sessions=scenes,splits={'全40':scenes},specs=specs,runs=runs,source_SHA256={'完全合成源':'f'*64})


def display(value: float,signed: bool=False) -> str:
    """
    機能: 合成値の期待表示を独立に作る。
    引数: value(float)は数値、signed(bool)は符号指定。
    返り値: strは表示値。
    """
    if abs(value)<1e-7:return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def main() -> None:
    """
    機能: 全場・因子比較・順位・未達の人工だけを確認して別証跡を保存する。
    引数: なし。
    返り値: None。金融・原市場・実結果・登録の読取又は変更は0。
    """
    target=HERE/'report_fixture/全四十八規則と順逆時刻及び全場の純表示検査.json';assert not target.exists()
    data=fixture();folder=HERE/'report_fixture/public'
    generation=R.generate(data,folder,'a'*64,'合成専用/順逆時刻.json',fixture=True)
    public=json.loads((folder/'data.json').read_text(encoding='utf8'));page=BeautifulSoup((folder/R.HTML_NAME).read_text(encoding='utf8'),'html.parser')
    check(len(public['cases'])==len(public['common_ranking'])==48,'全四十八を共通順位対象')
    check(len(public['main_ids'])==len({public['cases'][i]['spec']['family'] for i in public['main_ids']})==3,'異なる元入口三家族')
    source={(r['method'],r['session'],r['symbol']):r for r in data['runs']}
    tables=page.select('table.sessions');check(len(tables)==51 and {t['data-method'] for t in tables}==set(public['cases']),'主三再掲と全四十八の表')
    for table in tables:
        ident=table['data-method'];check(len(table.select('tbody tr'))==40,'各表四十場')
        for tr,scene in zip(table.select('tbody tr'),data['sessions']):
            expected=[]
            for symbol in R.SYMBOLS:
                r=source[ident,scene,symbol]
                expected.extend([display(r['profit']),display(r['loss']),display(r['net'],True),str(r['parents']),display(r['fees']),str(r['unclosed'])])
            check([td.get_text(strip=True) for td in tr.select('td')]==expected,'全表示金額親数料金未返済')
        expected=[]
        for symbol in R.SYMBOLS:
            rr=[source[ident,scene,symbol] for scene in data['sessions']]
            expected.extend([display(sum(r['profit'] for r in rr)),display(sum(r['loss'] for r in rr)),display(sum(r['net'] for r in rr),True),str(sum(r['parents'] for r in rr)),display(sum(r['fees'] for r in rr)),'0場'])
        check([td.get_text(strip=True) for td in table.select('tfoot td')]==expected,'全場合計独立足算')
    check(len(public['factor_comparisons'])==24,'四通りを二十四商品別組で比較')
    factor_rows=page.select('table.factors tbody tr');check(len(factor_rows)==24,'因子表の全二十四行')
    for item,tr in zip(public['factor_comparisons'],factor_rows):
        symbol=item['symbol'];nets={key:sum(source[ident,scene,symbol]['net'] for scene in data['sessions']) for key,ident in item['methods'].items()}
        expected=[item['entry_id'],'対称1幅' if item['exit_mode']==5 else '0.5幅追尾','保護なし' if item['execution_mode']==0 else '両保護',symbol]
        expected.extend(display(nets[k],True) for k in ('direct_T0','reverse_T0','direct_T1','reverse_T1'))
        values=(nets['reverse_T0']-nets['direct_T0'],nets['reverse_T1']-nets['direct_T1'],nets['direct_T1']-nets['direct_T0'],nets['reverse_T1']-nets['reverse_T0'])
        expected.extend(display(v,True) for v in values)
        check([td.get_text(strip=True) for td in tr.select('td')]==expected,'順逆差と時刻差を別の対照で算出')
    text=page.get_text(' ',strip=True)
    check('未知検証ではありません' in text and '最初の有効Rも後ろへずれ' in text,'既知開発と予算尺度変化の留保')
    check('実際の入口時刻の集合は一致しません' in text and '窓開始そのもののtimerではなく' in text,'公開時点と実受理集合を混同しない')
    check('休日例外は設けない' in text and 'ニュースの数値は使いません' in text,'固定窓とニュース値の区別')
    scaled=deepcopy(data)
    for row in scaled['runs']:
        if row['symbol']=='NK225':
            for key in R.MONEY:row[key]*=1000000
    _,p,_=R.render(scaled,'b'*64,'完全合成')
    check([r['id'] for r in p['common_ranking']]==[r['id'] for r in public['common_ranking']],'円倍率で共通順位を変えない')
    failed=deepcopy(data)
    for row in failed['runs']:
        row.update(net=0.,realized=0.,profit=0.,loss=0.,fees=0.,parents=0,wins=0,losses=0,closed_quantity=0,fills=0)
    doc,p,_=R.render(failed,'c'*64,'完全合成')
    check(p['qualification_count']==0 and '<strong>毎セッションの安定黒字は未達です。</strong>' in doc,'無活動成功を避け未達太字')
    check(all(v['metrics'][s]['black']==0 and v['metrics'][s]['inactive']==40 for v in p['cases'].values() for s in R.SYMBOLS),'無取引は勝ちでない')
    check(not page.select('script[src],img[src]'),'外部通信なし')
    proof=dict(全合格=True,範囲='完全合成48政策の表示だけ。実結果・原入力・金融の読取又は実行0。',検査件数=COUNTS,総検査件数=sum(COUNTS.values()),生成証跡=generation,
        source_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'report_v4.py',Path(__file__))},実結果読取=0,市場読取=0,金融再生=0,API=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(全合格=True,検査件数=sum(COUNTS.values()),SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
