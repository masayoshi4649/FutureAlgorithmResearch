"""表示された全売買・全原本曲線・構成票を、生成器とは別の足上げで検算する。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
import pickle
import subprocess

from bs4 import BeautifulSoup
import numpy as np

import chart_report as report

HERE,ROOT=report.HERE,report.ROOT


def ui_check(payload: dict) -> dict:
    """機能: 人工DOMで全104選択・全表・使用方向の説明・有限描画を検査する。

    引数: payload (dict)。返り値: 表示検査結果 (dict)。実Chrome目視は別実施。
    """
    before='const payload='+json.dumps(payload,ensure_ascii=False,allow_nan=False)+';'
    before+='''const elements={};const context=new Proxy({}, {get(target,key){if(key in target)return target[key];return (...args)=>{for(const v of args)if(typeof v==='number'&&!Number.isFinite(v))throw Error('非有限描画 '+String(key))}},set(target,key,value){target[key]=value;return true}});function element(id){if(!elements[id])elements[id]={value:'',options:[],innerHTML:'',textContent:id==='chart-data'?JSON.stringify(payload):'',appendChild(v){this.options.push(v);if(!this.value)this.value=v.value},addEventListener(){},getBoundingClientRect(){return {width:1180}},getContext(){return context}};return elements[id]}global.window={devicePixelRatio:1,addEventListener(){}};global.document={getElementById:element,createElement(){return {value:'',textContent:''}}};'''
    after='''let checked=0;for(const m of Object.keys(payload.methods))for(const s of ['TOPIX','NK225'])for(const k of payload.sessions){window.chartSelect(m,s,k);const key=m+'|'+k+'|'+s,r=payload.records[key];if(window.chartRenderedKey!==key||!window.chartViewReady)throw Error('選択不一致');for(const [id,rows] of [['order-table',r.orders],['trade-table',r.trades]]){const lines=(element(id).innerHTML.match(/<tr>/g)||[]).length;if(lines!==(rows.length?rows.length+1:0))throw Error('表行欠落')}const description=element('method-description').textContent;if(r.signal==='S100'&&!description.includes('中央1.0倍だけ'))throw Error('単一を3票と誤表示');if(r.signal==='M2_100'&&!description.includes('同方向2票以上'))throw Error('合議の誤表示');checked++}process.stdout.write(JSON.stringify({全合格:true,選択数:checked,非有限描画なし:true,全注文返済表確認:true,単一合議の説明区別:true}));'''
    result=subprocess.run(['node','-'],input=before+(HERE/'chart.js').read_text(encoding='utf-8')+after,
        text=True,encoding='utf-8',capture_output=True,timeout=60)
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout);assert value['全合格'] and value['選択数']==104
    return value


def artificial() -> dict:
    """機能: 売買結果を読まず、空口座と5枚人工注文の全104画面を検査する。

    引数: なし。返り値: 人工描画の証跡 (dict)。
    """
    sessions=[f'人工{i:02d}' for i in range(13)]
    payload=dict(methods=report.METHODS,sessions=sessions,candles={},records={},reason_names=report.REASONS,preview=True)
    ready=dict(start=0.,limit=600.,time_s=np.array([0.,60.,60.,120.,180.]),last=np.array([100.,101.,102.,103.,103.]))
    members=[np.array([0,1,1,-1,0],np.int8),np.array([0,0,1,-1,0],np.int8),np.array([0,0,0,-1,0],np.int8)]
    for session in sessions:
        for symbol in report.FACTORS:
            payload['candles'][session+'|'+symbol]=[[0.,100.,104.,99.,103.]]
            for method in report.METHODS:
                ledger=dict(orders=[],trades=[],config=dict(point_value=report.FACTORS[symbol],audit_cap=20))
                if session!=sessions[0]:
                    ledger['orders']=[[1,0,0,1,5,101,20,1],[3,2,0,-1,5,103,2,0]]
                    ledger['trades']=[[0,0,1,5,101,103,1,3,0,2,10]]
                signal=method.split('__')[0]
                state=members[1] if signal=='S100' else np.median(np.column_stack(members),axis=1).astype(np.int8)
                record,_=report.records(ready,ledger,members,state,signal)
                payload['records'][method+'|'+session+'|'+symbol]=record
    return ui_check(payload)


def main() -> None:
    """機能: 人工のみ又は正式全104画面を、原本・保存台帳・票列へ照合する。

    引数: --selftest (bool)。返り値: なし (None)。新しい注文を再生しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--selftest',action='store_true');args=parser.parse_args()
    proof=artificial()
    if args.selftest:
        report.save(HERE/'chart_ui_synthetic.json',proof);print('人工104図の全表と票説明が一致。',flush=True);return
    complete=report.read(HERE/'完備監査.json');assert complete['全合格']
    fixed=report.read(HERE/'chart_fixed.json')
    for path,value in fixed['SHA256'].items():assert report.digest(ROOT/path)==value,path
    generation=report.read(HERE/'chart_generation.json');assert generation['全合格'] and generation['全図示数']==104
    page=report.OUT/'５分足と売買.html';assert report.digest(page)==generation['HTML_SHA256']
    soup=BeautifulSoup(page.read_text(encoding='utf-8'),'html.parser')
    scripts=soup.find_all('script');assert len(scripts)==2 and all(not s.get('src') for s in scripts)
    payload=json.loads(soup.select_one('#chart-data').get_text())
    assert scripts[1].get_text()==(HERE/'chart.js').read_text(encoding='utf-8')
    assert payload['methods']==report.METHODS and not payload['preview']
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    assert payload['sessions']==sorted({key[0] for key in inputs})
    assert set(payload['records'])=={m+'|'+'|'.join(k) for m in report.METHODS for k in inputs}
    sources={};members={};entries={}
    inputs_path=HERE.parent/'wave_v23/inputs.pkl';sources[inputs_path.relative_to(ROOT).as_posix()]=report.digest(inputs_path)
    for folder,names,target in (('members',('C080','C100','C120'),members),('entries',('S100','M2_100'),entries)):
        for name in names:
            path=HERE/folder/(name+'.npz')
            with np.load(path) as data:target[name]={tuple(key.split('|')):data[key] for key in data.files}
            sources[path.relative_to(ROOT).as_posix()]=report.digest(path)
    for key,ready in sorted(inputs.items()):
        path=ROOT/'candle_5min'/key[1]/(key[0]+'.csv');actual=[]
        with path.open(encoding='utf-8-sig',newline='') as stream:
            for row in csv.DictReader(stream):
                stamp=datetime.fromisoformat(row['time']).timestamp()
                if row['closed'].strip().lower()=='true' and ready['start']<=stamp<=ready['limit']:
                    actual.append([stamp,*[float(row[column]) for column in ('open','high','low','close')]])
        assert actual==payload['candles']['|'.join(key)]
        sources[path.relative_to(ROOT).as_posix()]=report.digest(path)
    results=[]
    for method in report.METHODS:
        stores={}
        for folder in ('ledgers','sessions','audits'):
            path=HERE/folder/(method+'.json.gz');rows=report.read(path)
            stores[folder]={(r['session'],r['symbol']):r for r in rows}
            assert len(rows)==26 and set(stores[folder])==set(inputs)
            sources[path.relative_to(ROOT).as_posix()]=report.digest(path)
        for key,ready in sorted(inputs.items()):
            record=payload['records'][method+'|'+'|'.join(key)];ledger=stores['ledgers'][key]
            orders=np.asarray(ledger['orders'],float).reshape((-1,8));trades=np.asarray(ledger['trades'],float).reshape((-1,11))
            n=len(ready['last']);time=ready['time_s'];factor=ledger['config']['point_value']
            assert record['orders']==[[float(time[int(o[0])]),*o.tolist()] for o in orders]
            normalized=[[float(time[int(t[6])]),float(time[int(t[7])]),int(t[2]),int(t[3]),float(t[4]),float(t[5]),
                float(t[10]*factor),int(t[9]),int(t[6]),int(t[7]),int(t[0]),int(t[1])] for t in trades]
            assert record['trades']==normalized and record['factor']==factor
            # ----------------------------------------
            # 生成器の差分cumsumを使わず、全注文を後続原本行へ直接足し込む。
            cash=np.zeros(n);longs=np.zeros(n);shorts=np.zeros(n);realized=np.zeros(n);campaign=np.full(n,-1.)
            for order in orders:
                row=int(order[0]);cash[row:]-=order[3]*order[4]*order[5]
                if order[7]:
                    (longs if order[3]>0 else shorts)[row:]+=order[4]
                    if order[6]==20:campaign[row:]=order[2]
                else:(longs if order[3]<0 else shorts)[row:]-=order[4]
            for trade in trades:realized[int(trade[7]):]+=trade[2]*trade[3]*(trade[5]-trade[4])
            equity=cash+(longs-shorts)*ready['last'];dd=np.maximum.accumulate(np.maximum.accumulate(np.maximum(0.,equity))-equity)
            curve=np.column_stack([equity,realized,longs,shorts,dd,cash,longs-shorts,campaign])
            assert report.fingerprint(curve)==ledger['result_fingerprints']['curve']
            assert hashlib.sha256(equity.tobytes()).hexdigest()==stores['audits'][key]['時価SHA256']
            assert longs[-1]==shorts[-1]==0
            pnl=np.array([t[2]*t[3]*(t[5]-t[4])*factor for t in trades])
            quantities=trades[:,3]
            totals=dict(net_yen=float(pnl.sum()),gross_profit_yen=float(pnl[pnl>0].sum()),gross_loss_yen=float(-pnl[pnl<0].sum()),
                profit_units=int(quantities[pnl>0].sum()),loss_units=int(quantities[pnl<0].sum()),zero_units=int(quantities[pnl==0].sum()),closed_units=int(quantities.sum()))
            assert set(totals)==set(record['totals'])
            for name,value in totals.items():
                np.testing.assert_allclose(value,record['totals'][name],rtol=0,atol=1e-6)
                np.testing.assert_allclose(value,stores['sessions'][key][name],rtol=0,atol=1e-6)
            indices={n-1,*map(int,orders[:,0])};stamp=ready['start']
            while stamp<=time[-1]:
                i=int(np.searchsorted(time,stamp,side='right')-1)
                if i>=0:indices.add(i)
                stamp+=300
            assert [r[1] for r in record['tracking']]==[-1,*sorted(indices)]
            expected_tracking=[[float(ready['start']),-1,0.,0.,0.]]+[[float(time[i]),i,float(longs[i]),float(shorts[i]),float(equity[i]*factor)] for i in sorted(indices)]
            np.testing.assert_array_equal(record['tracking'],expected_tracking)
            positions=[[float(ready['start']),-1,0.,0.]]+[[float(time[int(o[0])]),int(o[0]),float(longs[int(o[0])]),float(shorts[int(o[0])])] for o in orders]+[[float(time[-1]),n-1,0.,0.]]
            assert record['position']==positions
            # ----------------------------------------
            # 票は全原本行へ展開して全変化の欠落と中央票取り違えを独立に検査する。
            matrix=np.column_stack([members[name][key] for name in ('C080','C100','C120')])
            signal=method.split('__')[0];state=entries[signal][key]
            positive=(matrix==1).sum(axis=1);negative=(matrix==-1).sum(axis=1)
            expected_state=np.where(positive>=2,1,np.where(negative>=2,-1,0)).astype(np.int8) if signal=='M2_100' else matrix[:,1]
            np.testing.assert_array_equal(state,expected_state)
            full=np.column_stack([matrix,state]);changed=np.flatnonzero((full[1:]!=full[:-1]).any(axis=1))+1
            locations=sorted({0,n-1,*changed.tolist()})
            assert record['votes']==[[float(time[i]),i,*map(int,full[i])] for i in locations]
            assert record['signal']==signal
            results.append(dict(id=method,session=key[0],symbol=key[1],全合格=True,orders=len(orders),trades=len(trades),
                全原本曲線指紋一致=True,全金額枚数一致=True,全4方向帯一致=True))
    ui=ui_check(payload)
    assert sources==generation['参照SHA256'] and len(results)==104
    for path,value in sources.items():assert report.digest(ROOT/path)==value,path
    report.save(HERE/'chart_audit.json',dict(全合格=True,全図示数=104,全原本足一致=True,全注文返済一致=True,
        全原本曲線指紋一致=True,全金額枚数一致=True,全4方向帯一致=True,結果=results,UI=ui,
        HTML_SHA256=report.digest(page),固定SHA256=report.digest(HERE/'chart_fixed.json'),参照SHA256=sources,
        新売買再生=False,API取得数=0,現在保存物使用=False))
    print('全104図の原本足・全台帳・全原本曲線・3票と使用方向が一致。',flush=True)


if __name__=='__main__':main()
