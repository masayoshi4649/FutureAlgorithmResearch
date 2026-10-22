"""固定十九条件の全場表と保存基準の読替えを、架空会計だけで確認する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

import render123 as R


HERE=Path(__file__).resolve().parent


def fixture() -> dict:
    """
    機能: 無取引・活動零・正負を含む十九条件の架空760会計を作る。
    引数: なし。
    返り値: dictは新720と旧40引用を区別した完全合成。実入力は使わない。
    """
    sessions=[f'合成場{i+1:02d}' for i in range(40)]
    parameters=[(3,g) for g in R.GAPS]+[(g,g) for g in R.GAPS if g!=3]
    specs=[];runs=[];baseline=[]
    for index,(initial,gap) in enumerate(parameters):
        ident=f'I{initial}_G{gap}';reused=ident==R.BASELINE
        specs.append(dict(id=ident,name=f'初回{initial}pt・間隔{gap}pt',initial=float(initial),spacing=float(gap),reused=reused))
        for i,scene in enumerate(sessions):
            active=i%10!=0 and index!=18;quantity=(2+index%3)*int(active)
            net=((i%5)-2)*(index+1)*100 if active else 0
            context=dict(measured=True,approximation=True,base_unclosed=quantity,scheduled_time=1790232300.,
                reference_time=1790232000.,age_seconds=300.,reference_last=4000.,reference_bid=3999.5,reference_ask=4000.,last_price_reference_net=net+quantity*500)
            row=dict(method='HOLD_CLOSE_6M' if reused else ident,session=scene,symbol='TOPIX',
                profit=max(net,0),loss=max(-net,0),net=net,cash=net,fees=82*quantity,
                long_net=net,short_net=0,wins=int(net>0),losses=int(net<0),closed_lots=quantity,entries=quantity,
                max_long=quantity,max_short=0,unclosed=0,regular_closed=0,proxy_count=quantity,context=context)
            (baseline if reused else runs).append(row)
    return dict(passed=True,sessions=sessions,specs=specs,runs=runs,
        baseline=dict(source_method='HOLD_CLOSE_6M',mapped_method=R.BASELINE,rows=baseline),
        sources={'完全合成.py':'a'*64},financial_accounts=720,reused_baseline_accounts=40,original_market_reads=0,API=0,実注文=0)


def main() -> None:
    """
    機能: 固定順一覧・全760行・基準既定・無取引と活動零の分離を調べる。
    引数: なし。
    返り値: None。私有合成HTMLと証跡だけ保存し、正式公開しない。
    """
    output=HERE/'artificial';assert not output.exists();output.mkdir()
    data=fixture();text,metrics=R.render(data,'b'*64,True);page=BeautifulSoup(text,'html.parser')
    specs=data['specs'];panels=page.select('.case');checks=0
    assert len(page.select('#overview tbody tr'))==len(page.select('#condition option'))==len(panels)==19
    assert page.select_one('#condition option[selected]')['value']==R.BASELINE
    assert [p['data-id'] for p in panels if not p.has_attr('hidden')]==[R.BASELINE]
    rows={(r['method'],r['session']):r for r in data['runs']}
    rows.update({(R.BASELINE,r['session']):r for r in data['baseline']['rows']})
    for panel,spec in zip(panels,specs):
        ident=spec['id'];assert panel['data-id']==ident
        trs=panel.select('tbody tr');assert len(trs)==40
        for tr,scene in zip(trs,data['sessions']):
            r=rows[ident,scene];base=rows[R.BASELINE,scene]
            cells=[e.get_text(strip=True) for e in tr.select('th,td')]
            assert cells[:8]==[scene,R.yen(r['profit']),R.yen(r['loss']),R.yen(r['net'],True),str(r['closed_lots']),f"{r['wins']}/{r['losses']}/{r['closed_lots']-r['wins']-r['losses']}",R.yen(base['net'],True),R.yen(r['net']-base['net'],True)]
            assert cells[8:]==['15:40:00','300'];checks+=1
        footer=[e.get_text(strip=True) for e in panel.select('tfoot td')]
        assert footer[2]==R.yen(sum(rows[ident,s]['net'] for s in data['sessions']),True)
        assert footer[5]==R.yen(sum(rows[R.BASELINE,s]['net'] for s in data['sessions']),True);checks+=1
    inactive=metrics['I15_G15'];assert inactive['inactive']==40 and inactive['black']==inactive['red']==inactive['flat']==0
    assert metrics[R.BASELINE]['flat']>0 and metrics[R.BASELINE]['inactive']>0
    assert '—（未定義）' in page.get_text() and '同じ玉をLastで評価した感応度' in page.get_text()
    for kind in ('重複3_3','保存元method違い','不正な枚数課金','無取引利益捏造'):
        bad=deepcopy(data)
        if kind=='重複3_3':bad['runs'][0]['method']=R.BASELINE
        elif kind=='保存元method違い':bad['baseline']['rows'][0]['method']=R.BASELINE
        elif kind=='不正な枚数課金':bad['runs'][0]['fees']+=82
        else:bad['runs'][0]['net']=bad['runs'][0]['cash']=bad['runs'][0]['profit']=bad['runs'][0]['long_net']=1
        try:R.validate(bad)
        except AssertionError:checks+=1
        else:raise AssertionError(kind)
    path=output/'完全合成の十九比較.html';path.write_text(text,encoding='utf8')
    proof=dict(passed=True,fixture=True,checks=checks,report_SHA256=hashlib.sha256((HERE/'render123.py').read_bytes()).hexdigest(),
        HTML_SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),financial_result_reads=0,NPZ_reads=0,market_reads=0,financial_replay=0,registry_reads=0,API=0,正式公開=False)
    target=output/'十九固定順と全760行及び無取引分離の純表示確認.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=checks,report_SHA256=proof['report_SHA256'],proof_SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


# ----------------------------------------


if __name__=='__main__':
    main()
