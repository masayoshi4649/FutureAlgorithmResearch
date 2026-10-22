"""固定四比較の架空会計だけで、短い表示の母数と全場表を確認する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics

from bs4 import BeautifulSoup

import render121 as R


HERE=Path(__file__).resolve().parent


def fixture() -> dict:
    """
    機能: 金融・市場・保存結果を使わず四条件の架空40場会計を作る。
    引数: なし。
    返り値: dictは欠行・未清算と無取引の境界確認用の完全合成。
    """
    sessions=[R.EXAMPLE,*[f'合成場{i:02d}' for i in range(2,41)]]
    rows=[]
    for index,ident in enumerate(R.IDS):
        for i,scene in enumerate(sessions):
            active=i%10!=0;net=((i%5)-2)*(index+1)*1000 if active else 0
            rows.append(dict(method=ident,session=scene,symbol='TOPIX',profit=max(net,0),loss=max(-net,0),
                net=net,cash=net,fees=82*int(active),wins=int(net>0),losses=int(net<0),
                closed_lots=int(active),entries=int(active),unclosed=0,max_long=int(active),max_short=0))
    specs=[dict(id=ident,spacing=spacing,trail=5.,reset_after_profit=reset)
        for ident,spacing,reset in ((R.IDS[1],1.,False),(R.IDS[2],3.,False),(R.IDS[3],3.,True))]
    return dict(passed=True,sessions=sessions,specs=specs,runs=rows[40:],
        baseline=dict(method=R.IDS[0],rows=rows[:40]),sources={'完全合成.py':'a'*64},
        financial_accounts=120,reused_baseline_accounts=40,original_market_reads=0,API=0,実注文=0)


def main() -> None:
    """
    機能: 全40行の四netと提案P/L・枚数、集計と拒否境界だけを確認する。
    引数: なし。
    返り値: None。私有合成HTMLと証跡だけ保存し、正式公開は行わない。
    """
    output=HERE/'artificial_v2';assert not output.exists();output.mkdir()
    data=fixture();text,metrics=R.render(data,'b'*64,True)
    page=BeautifulSoup(text,'html.parser');tables=page.select('table');assert len(tables)==3
    assert [len(t.select('tbody tr')) for t in tables]==[4,4,40]
    allrows=data['baseline']['rows']+data['runs'];rowmap={(r['method'],r['session']):r for r in allrows}
    checks=0
    for tr,scene in zip(tables[2].select('tbody tr'),data['sessions']):
        p=rowmap[R.IDS[3],scene]
        expected=[scene,*[R.yen(rowmap[ident,scene]['net'],True) for ident in R.IDS],R.yen(p['profit']),R.yen(p['loss']),f"{p['wins']}/{p['losses']}"]
        assert [c.get_text(strip=True) for c in tr.select('th,td')]==expected;checks+=1
    for ident in R.IDS:
        rows=[r for r in allrows if r['method']==ident];nets=[r['net'] for r in rows]
        m=metrics[ident]
        assert m['net']==sum(nets) and m['median']==statistics.median(nets) and m['worst']==min(nets)
        assert m['black']+m['red']+m['inactive']+m['flat']==40
        assert m['inactive']==4 and m['flat']==8
        assert m['top3_removed']==sum(nets)-sum(sorted([n for n in nets if n>0],reverse=True)[:3]);checks+=1
    for kind in ('欠行','重複基準','P_L不一致','再起算設定不一致'):
        broken=deepcopy(data)
        if kind=='欠行':broken['runs'].pop()
        elif kind=='重複基準':broken['baseline']['rows'][1]=broken['baseline']['rows'][0]
        elif kind=='P_L不一致':broken['runs'][1]['profit']+=1
        else:broken['specs'][2]['reset_after_profit']=False
        try:R.validate(broken)
        except AssertionError:checks+=1
        else:raise AssertionError(kind)
    assert R.contains(dict(result='b'*64),'b'*64) and not R.contains(dict(result='c'*64),'b'*64)
    assert '完全合成' in page.get_text() and '既知40場' in page.get_text() and not page.select('script')
    html=output/'完全合成の比較.html';html.write_text(text,encoding='utf8')
    proof=dict(passed=True,fixture=True,checks=checks,
        report_SHA256=hashlib.sha256((HERE/'render121.py').read_bytes()).hexdigest(),
        artificial_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        HTML_SHA256=hashlib.sha256(html.read_bytes()).hexdigest(),financial_result_reads=0,market_reads=0,NPZ_reads=0,
        financial_replay=0,registry_reads=0,API=0,正式公開=False)
    target=output/'固定四比較と全四十行の純表示確認.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=checks,report_SHA256=proof['report_SHA256'],proof_SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


# ----------------------------------------


if __name__=='__main__':
    main()
