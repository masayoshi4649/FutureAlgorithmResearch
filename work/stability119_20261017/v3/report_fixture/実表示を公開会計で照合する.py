"""完成元を再読せず、三配分の全公開小会計とHTML表示を独立に照合する。"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
PUBLIC=HERE.parents[1]/'privatev3/public'
TARGET=HERE/'三配分全三十六と全四十場の実表示照合.json'
COUNTS=Counter()


def check(value: bool,label: str) -> None:
    """
    機能: 公開済み小会計と表示の一致を件数付きで記録する。
    引数: value(bool)は一致条件、label(str)は検査名。
    返り値: None。不一致はAssertionErrorとする。
    """
    assert value,label
    COUNTS[label]+=1


def show(value: float|None,signed: bool=False) -> str:
    """
    機能: 小会計から表の期待文字列を独立に作る。
    引数: value(float|None)は保存値、signed(bool)は符号指定。
    返り値: strは表示値又は未評価記号。
    """
    if value is None:return '—'
    if abs(value)<1e-7:return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def main() -> None:
    """
    機能: 全三十六条件と三方式の表示を自身の小会計だけから検算する。
    引数: なし。
    返り値: None。別証跡だけ保存し、完成元・市場・金融は再読しない。
    """
    assert not TARGET.exists()
    names=('data.json','小枚数と順行増加の比較と全セッション損益.html','README.md','生成証跡.json')
    raw={name:(PUBLIC/name).read_bytes() for name in names}
    data=json.loads(raw['data.json']);page=BeautifulSoup(raw[names[1]].decode('utf8'),'html.parser')
    expected_sha='0e027e11a03e4f6a8c0bf9f1166e9f7487505ab91be5ea12b0d76eb9a88b0ca5'
    check(data['source_SHA256']==expected_sha,'指定元SHAの転載')
    cases=data['cases'];scenes=data['sessions'];allrows={};calculated={}
    check(len(cases)==36 and len(scenes)==40,'全条件全場')
    for ident,case in cases.items():
        check(len(case['rows'])==80,'商品場八十行')
        for r in case['rows']:
            key=ident,r['session'],r['symbol']
            check(key not in allrows,'同条件同場同商品重複なし');allrows[key]=r
        for symbol in ('TOPIX','NK225'):
            rr=[allrows[ident,scene,symbol] for scene in scenes];net=[r['net'] for r in rr]
            black=[v for v in net if v>1e-7];red=[v for v in net if v<-1e-7]
            absent=sum(r['fills']==0 for r in rr);p=sum(r['profit'] for r in rr);loss=sum(r['loss'] for r in rr)
            m=dict(net=sum(net),profit=p,loss=loss,fees=sum(r['fees'] for r in rr),parents=sum(r['parents'] for r in rr),
                black=len(black),red=len(red),inactive=absent,median=statistics.median(net),mean=statistics.mean(net),worst=min(net),
                top3_removed=sum(net)-sum(sorted(black,reverse=True)[:3]),mean_abs_net=statistics.mean(abs(v) for v in net),
                share=p/(p+loss) if p+loss else None,unclosed_sessions=sum(r['unclosed']>0 for r in rr),
                max_quantity=max(r['max_quantity'] for r in rr),add_fills=sum(r['add_fills'] for r in rr),
                initial_quantity_min=min((r['initial_quantity_min'] for r in rr if r['initial_quantity_min'] is not None),default=None),
                initial_quantity_max=max((r['initial_quantity_max'] for r in rr if r['initial_quantity_max'] is not None),default=None))
            for key,value in m.items():
                observed=case['metrics'][symbol][key]
                check(observed is None if value is None else math.isclose(value,observed,abs_tol=1e-7,rel_tol=0),'会計と実枚数の独立集計')
            calculated[ident,symbol]=m
    # ----------------------------------------
    # 主三表の再掲も含め、各表の全行と全フッターを確認する。
    tables=page.select('table.sessions')
    check(len(tables)==39 and {t['data-method'] for t in tables}==set(cases),'主三再掲と全三十六表')
    for table in tables:
        ident=table['data-method'];trs=table.select('tbody tr');check(len(trs)==40,'全四十場を省略しない')
        for scene,tr in zip(scenes,trs):
            expected=[]
            check(tr['data-session']==scene,'場の順序')
            for symbol in ('TOPIX','NK225'):
                r=allrows[ident,scene,symbol]
                expected.extend([show(r['profit']),show(r['loss']),show(r['net'],True),str(r['parents']),show(r['fees']),str(r['unclosed'])])
            check([td.get_text(strip=True) for td in tr.select('td')]==expected,'全場金額親数料金未返済')
        expected=[]
        for symbol in ('TOPIX','NK225'):
            m=calculated[ident,symbol]
            expected.extend([show(m['profit']),show(m['loss']),show(m['net'],True),str(m['parents']),show(m['fees']),str(m['unclosed_sessions'])+'場'])
        check([td.get_text(strip=True) for td in table.select('tfoot td')]==expected,'全場合計')
    # ----------------------------------------
    # 同じ入口・追尾幅の三方式を、商品内だけで直接対照する。
    groups={}
    for ident,case in cases.items():
        spec=case['spec'];groups.setdefault((spec['entry_id'],spec['trail_multiple']),{})[spec['allocation_mode']]=ident
    check(len(groups)==12 and all(set(v)=={0,1,2} for v in groups.values()),'十二組の三方式が一意')
    pairmap={(v['family'],v['trail_r'],v['symbol']):v for v in data['sizing_comparisons']}
    check(len(pairmap)==24,'商品別比較二十四件')
    expected_size=[]
    for (family,trail),ids in sorted(groups.items()):
        for symbol in ('TOPIX','NK225'):
            comparison=pairmap[family,trail,symbol]
            nets={mode:calculated[ident,symbol]['net'] for mode,ident in ids.items()}
            check(comparison['grow_minus_scout']==nets[2]-nets[0] and comparison['grow_minus_full']==nets[2]-nets[1],'増加と両固定方式の差')
            for scene in scenes:
                budgets=[allrows[ids[mode],scene,symbol]['session_loss_budget_yen'] for mode in range(3)]
                check(budgets[0]==budgets[1]==budgets[2],'全方式の場予算が同円額')
            for mode in range(3):
                m=calculated[ids[mode],symbol]
                initial='無取引' if m['initial_quantity_min'] is None else str(m['initial_quantity_min']) if m['initial_quantity_min']==m['initial_quantity_max'] else str(m['initial_quantity_min'])+'〜'+str(m['initial_quantity_max'])
                expected_size.append([family,show(trail),symbol,('20%固定','100%固定','20→40→70→100%')[mode],show(m['net'],True),
                    f"{m['black']}/{m['red']}/{m['inactive']}",show(m['median'],True),show(m['worst'],True),show(m['top3_removed'],True),show(m['max_quantity']),initial,show(m['add_fills'])])
    size_tables=[t for t in page.select('table') if t.find('th',string='実最大枚数')]
    check(len(size_tables)==1 and len(size_tables[0].select('tbody tr'))==72,'実枚数対照七十二行')
    for tr,expected in zip(size_tables[0].select('tbody tr'),expected_size):
        check([td.get_text(strip=True) for td in tr.select('td')]==expected,'対照の収支と実枚数')
    # 集計二表は主三・全三十六を掲載する。
    summaries=[t for t in page.select('table') if t.caption]
    check(len(summaries)==2,'主表と全三十六集計表')
    for table,ids in zip(summaries,[data['main_ids'],[r['id'] for r in data['common_ranking']]]):
        pairs=[(ident,symbol) for ident in ids for symbol in ('TOPIX','NK225')]
        check(len(table.select('tbody tr'))==len(pairs),'集計表行数')
        for tr,(ident,symbol) in zip(table.select('tbody tr'),pairs):
            m=cases[ident]['metrics'][symbol]
            expected=[show(m['net'],True),f"{m['black']}/{m['red']}/{m['inactive']}",show(m['median'],True),show(m['worst'],True),show(m['top3_removed'],True),show(m['fees']),str(m['unclosed_sessions']),str(m['flat']),'—' if m['share'] is None else f"{m['share']*100:.1f}%"]
            check([td.get_text(strip=True) for td in tr.select('td')][2:]==expected,'全集計表金額と頻度')
    check(len(data['common_ranking'])==36 and set(r['id'] for r in data['common_ranking'])==set(cases),'全三十六共通順位')
    qualified=sum(all(calculated[ident,s]['net']>0 and calculated[ident,s]['median']>0 and calculated[ident,s]['top3_removed']>0 and calculated[ident,s]['unclosed_sessions']==0 for s in ('TOPIX','NK225')) for ident in cases)
    check(qualified==data['qualification_count']==0,'共通資格達成なし')
    text=page.get_text(' ',strip=True)
    check(page.find('strong',string='毎セッションの安定黒字は未達です。') is not None,'太字未達')
    check('未知検証ではありません' in text and '全方式共通' in text and '全量方式は親の1幅損切りより先' in text,'既知開発と同一場予算の限界')
    check('追加だけの独立寄与ではありません' in text and '未保存は—' in text,'増加法の限界')
    check(not page.select('script[src],img[src]'),'外部通信なし')
    proof=dict(全合格=True,範囲='自身の生成済み公開小会計と表示の一致。金融エンジンの正当性監査ではない。',検査件数=dict(COUNTS),総検査件数=sum(COUNTS.values()),
        商品場行=2880,全場表=39,配分比較行=72,元結果SHA256=expected_sha,
        生成物SHA256={name:hashlib.sha256(value).hexdigest() for name,value in raw.items()},
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),元結果追加読取=0,原市場読取=0,金融再生=0,API=0,
        結論='資格0/36。共通順位は参考で、無取引を勝ちにせず、増加単独の改善を証明しない。')
    TARGET.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(全合格=True,検査件数=sum(COUNTS.values()),SHA256=hashlib.sha256(TARGET.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
