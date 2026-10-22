"""通常返済と引け代理を分離した三比較を、架空小会計だけで確認する。"""

from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

import render122 as R


HERE=Path(__file__).resolve().parent


def fixture() -> dict:
    """
    機能: 実入力を読まず、新80会計と旧40引用及び代理参照時計を作る。
    引数: なし。
    返り値: dictは完全合成。通常返済に未保存の参照時計を追加しない。
    """
    sessions=[R.EXAMPLE,*[f'合成場{i:02d}' for i in range(2,41)]]
    rows=[];target=datetime(2026,9,24,15,45,tzinfo=timezone(timedelta(hours=9))).timestamp()
    for index,ident in enumerate(R.IDS):
        for i,scene in enumerate(sessions):
            active=i%10!=0;quantity=(1 if index==0 else 2)*int(active)
            net=((i%5)-2)*(index+1)*1000 if active else 0
            row=dict(method=ident,session=scene,symbol='TOPIX',profit=max(net,0),loss=max(-net,0),net=net,cash=net,
                fees=82*quantity,wins=int(net>0),losses=int(net<0),closed_lots=quantity,entries=quantity,
                unclosed=0,max_long=quantity,max_short=0,long_net=net,short_net=0)
            if index==1:
                row.update(context=dict(kind='EARLY',scheduled_time=target-1500,approximation=False,base_unclosed=0),
                    regular_closed=quantity,proxy_count=0)
            elif index==2:
                age=360 if i==39 else i+1
                row.update(context=dict(kind='CLOSE_PROXY',scheduled_time=target,reference_time=target-age,age_seconds=age,
                    reference_last=4000.,reference_bid=3999.5,reference_ask=4000.,approximation=True,measured=True,
                    base_unclosed=quantity,last_price_reference_net=net+500,terminal_event=dict(scheduled_time=target)),regular_closed=0,proxy_count=quantity)
            rows.append(row)
    return dict(passed=True,sessions=sessions,specs=[dict(id=R.IDS[1],kind='EARLY'),dict(id=R.IDS[2],kind='CLOSE_PROXY')],
        runs=rows[40:],baseline=dict(method=R.IDS[0],rows=rows[:40]),sources={'完全合成.py':'a'*64},
        financial_accounts=80,reused_baseline_accounts=40,original_market_reads=0,API=0,実注文=0)


def main() -> None:
    """
    機能: 三比較・全40行・代理参照JSTと6分境界を確認する。
    引数: なし。
    返り値: None。私有合成HTMLと小証跡だけ保存し、正式公開しない。
    """
    output=HERE/'artificial_last';assert not output.exists();output.mkdir()
    data=fixture();text,metrics=R.render(data,'b'*64,True);page=BeautifulSoup(text,'html.parser')
    tables=page.select('table');assert [len(t.select('tbody tr')) for t in tables]==[3,3,40]
    rows={(r['method'],r['session']):r for r in data['baseline']['rows']+data['runs']};checks=0
    for tr,scene in zip(tables[2].select('tbody tr'),data['sessions']):
        p=rows[R.IDS[2],scene];c=p['context']
        clock=datetime.fromtimestamp(c['reference_time'],timezone(timedelta(hours=9))).strftime('%H:%M:%S')
        expected=[scene,*[R.yen(rows[ident,scene]['net'],True) for ident in R.IDS],R.yen(p['profit']),R.yen(p['loss']),f"{p['wins']}/{p['losses']}",clock,f"{c['age_seconds']:g}"]
        assert [e.get_text(strip=True) for e in tr.select('th,td')]==expected;checks+=1
    assert '15:45／06:00の直前6分' in page.select_one('strong').get_text()
    assert '同じ保有玉を最後のLastで評価' in page.get_text()
    assert '通常返済の約定時刻ではない' in page.get_text() and not page.select('script')
    assert all('reference_time' not in r['context'] for r in data['runs'] if r['method']==R.IDS[1])
    for kind in ('代理未測定','6分超過','代理を実約定化','通常を代理化','入口枚数差','会計不一致'):
        broken=deepcopy(data);proxy=next(r for r in broken['runs'] if r['method']==R.IDS[2]);early=broken['runs'][0]
        if kind=='代理未測定':proxy['context']['measured']=False
        elif kind=='6分超過':proxy['context']['age_seconds']=361
        elif kind=='代理を実約定化':proxy['context']['approximation']=False
        elif kind=='通常を代理化':early['context']['approximation']=True
        elif kind=='入口枚数差':early['entries']+=1
        else:proxy['profit']+=1
        try:R.validate(broken)
        except AssertionError:checks+=1
        else:raise AssertionError(kind)
    html=output/'完全合成の三条件比較.html';html.write_text(text,encoding='utf8')
    proof=dict(passed=True,fixture=True,checks=checks,
        report_SHA256=hashlib.sha256((HERE/'render122.py').read_bytes()).hexdigest(),
        artificial_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        HTML_SHA256=hashlib.sha256(html.read_bytes()).hexdigest(),financial_result_reads=0,NPZ_reads=0,
        market_reads=0,financial_replay=0,registry_reads=0,API=0,正式公開=False)
    target=output/'通常返済と引け代理及び全四十行の純表示確認.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=checks,report_SHA256=proof['report_SHA256'],proof_SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


# ----------------------------------------


if __name__=='__main__':
    main()
