"""全104図の売買と初回ATR到達を、生成器と別の計算経路で検査する。"""
from __future__ import annotations
import argparse
from copy import deepcopy
import csv
from datetime import datetime
import hashlib
import json
import pickle
import subprocess
import numpy as np
from bs4 import BeautifulSoup
import chart_report as report
HERE,ROOT=report.HERE,report.ROOT


def ui_check(payload: dict) -> dict:
    """機能: 全選択・表の全件・有限座標を人工DOMで確認する。

    引数: payload (dict)。返り値: 104選択の結果 (dict)。実Chromeは別検査。
    """
    before='const payload='+json.dumps(payload,ensure_ascii=False,allow_nan=False)+';'
    before+='''const elements={};const context=new Proxy({}, {get(target,key){if(key in target)return target[key];return (...args)=>{for(const v of args)if(typeof v==='number'&&!Number.isFinite(v))throw Error('非有限描画')}},set(target,key,value){target[key]=value;return true}});function element(id){if(!elements[id])elements[id]={value:'',options:[],innerHTML:'',textContent:id==='chart-data'?JSON.stringify(payload):'',appendChild(v){this.options.push(v);if(!this.value)this.value=v.value},addEventListener(){},getBoundingClientRect(){return {width:1180}},getContext(){return context}};return elements[id]}global.window={devicePixelRatio:1,addEventListener(){}};global.document={getElementById:element,createElement(){return {value:'',textContent:''}}};'''
    after='''let checked=0;for(const m of Object.keys(payload.methods))for(const s of ['TOPIX','NK225'])for(const k of payload.sessions){window.chartSelect(m,s,k);const key=m+'|'+k+'|'+s,r=payload.records[key];if(window.chartRenderedKey!==key||!window.chartViewReady)throw Error('選択不一致');for(const [id,rows] of [['order-table',r.orders],['trade-table',r.trades],['arm-table',r.arms]]){const lines=(element(id).innerHTML.match(/<tr>/g)||[]).length;if(lines!==(rows.length?rows.length+1:0))throw Error('表行欠落')}if(m.startsWith('G150_')&&!element('method-description').textContent.includes('さらに新しいB00'))throw Error('到達を約定と誤表示');if(m.includes('F50')&&!element('method-description').textContent.includes('残存枠50%'))throw Error('50%の方式説明');if(m.includes('F25')&&!element('method-description').textContent.includes('残存枠25%'))throw Error('25%の方式説明');checked++}process.stdout.write(JSON.stringify({全合格:true,選択数:checked,非有限描画なし:true,全注文返済到達表確認:true}));'''
    completed=subprocess.run(['node','-'],input=before+(HERE/'chart.js').read_text(encoding='utf-8')+after,
                             text=True,encoding='utf-8',capture_output=True,timeout=60)
    assert completed.returncode==0,completed.stderr
    value=json.loads(completed.stdout);assert value['全合格'] and value['選択数']==104
    return value


def artificial() -> dict:
    """機能: 空口座と減量復元の人工だけで104画面を検査する。

    引数: なし。返り値: 描画検査 (dict)。実データ収支は使用しない。
    """
    sessions=[f'人工{i:02d}' for i in range(13)]
    payload=dict(methods=report.METHODS,sessions=sessions,candles={},records={},reason_names=report.REASONS,preview=True)
    for session in sessions:
        for symbol,factor in report.FACTORS.items():
            payload['candles'][session+'|'+symbol]=[[0.,100.,104.,99.,103.]]
            for method in report.METHODS:
                ready,ledger=report.artificial_fixture(2 if 'F50' in method else 1);ledger['config']['point_value']=factor
                if session==sessions[0]:
                    ledger.update(orders=[],trades=[],shadow_cycles=[],shadow_orders=[])
                elif method in report.GATED_METHODS:
                    ledger['arm_events']=[dict(row=4,seq=12,time_s=180.,campaign=0,direction=1,initial_atr=2.,
                        anchor=100.,extreme=104.,mfe_atr=2.,original_source_row=4,plan_source_row=4)]
                value,_=report.records(ready,ledger,method)
                payload['records'][method+'|'+session+'|'+symbol]=value
    return ui_check(payload)


def main() -> None:
    """機能: 人工だけ又は正式104図を、原本と保存配列へ厳密照合する。

    引数: --selftest (bool)。返り値: なし (None)。売買の再生なし。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--selftest',action='store_true');args=parser.parse_args()
    artificial_proof=artificial()
    if args.selftest:
        report.save(HERE/'chart_ui_synthetic.json',artificial_proof);print('人工104図が一致。',flush=True);return
    assert report.read(HERE/'完備監査.json')['全合格']
    fixed=report.read(HERE/'chart_fixed.json')
    for name,value in fixed['SHA256'].items():assert report.digest(ROOT/name)==value,name
    generation=report.read(HERE/'chart_generation.json');assert generation['全合格'] and generation['全図示数']==104
    page=report.OUT/'５分足と売買.html';assert report.digest(page)==generation['HTML_SHA256']
    soup=BeautifulSoup(page.read_text(encoding='utf-8'),'html.parser');scripts=soup.find_all('script')
    assert len(scripts)==2 and not any(s.get('src') for s in scripts)
    assert scripts[1].get_text()==(HERE/'chart.js').read_text(encoding='utf-8')
    payload=json.loads(soup.select_one('#chart-data').get_text())
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    assert payload['methods']==report.METHODS and not payload['preview']
    assert set(payload['records'])=={m+'|'+'|'.join(k) for m in report.METHODS for k in inputs}
    sourcepaths=[HERE.parent/'wave_v23/inputs.pkl'];checks=[]
    for key,ready in sorted(inputs.items()):
        path=ROOT/'candle_5min'/key[1]/(key[0]+'.csv');sourcepaths.append(path);values=[]
        with path.open(encoding='utf-8-sig',newline='') as stream:
            for line in csv.DictReader(stream):
                t=datetime.fromisoformat(line['time']).timestamp()
                if line['closed'].strip().lower()=='true' and ready['start']<=t<=ready['limit']:
                    values.append([t,*[float(line[c]) for c in ('open','high','low','close')]])
        assert values==payload['candles']['|'.join(key)]
    for method in report.METHODS:
        stores={}
        for folder in ('ledgers','sessions','audits','gate_use'):
            path=HERE/folder/(method+('.json' if folder=='gate_use' else '.json.gz'));sourcepaths.append(path)
            rows=report.read(path);stores[folder]={(r['session'],r['symbol']):r for r in rows}
            assert len(rows)==26 and set(stores[folder])==set(inputs)
        for key,ready in sorted(inputs.items()):
            ledger=stores['ledgers'][key];record=payload['records'][method+'|'+'|'.join(key)];time=ready['time_s'];n=len(time)
            orders=np.asarray(ledger['orders'],float).reshape((-1,8));trades=np.asarray(ledger['trades'],float).reshape((-1,11))
            factor=ledger['config']['point_value']
            assert record['orders']==[[float(time[int(o[0])]),*o.tolist()] for o in orders]
            assert record['trades']==[[float(time[int(t[6])]),float(time[int(t[7])]),int(t[2]),int(t[3]),float(t[4]),float(t[5]),
                float(t[10]*factor),int(t[9]),int(t[6]),int(t[7]),int(t[0]),int(t[1])] for t in trades]
            cash=np.zeros(n);longs=np.zeros(n);shorts=np.zeros(n);realized=np.zeros(n);campaign=np.full(n,-1.)
            for o in orders:
                row=int(o[0]);cash[row:]-=o[3]*o[4]*o[5]
                if o[7]:
                    (longs if o[3]>0 else shorts)[row:]+=o[4]
                    if o[6]==20:campaign[row:]=o[2]
                else:(longs if o[3]<0 else shorts)[row:]-=o[4]
            for t in trades:realized[int(t[7]):]+=t[2]*t[3]*(t[5]-t[4])
            equity=cash+(longs-shorts)*ready['last'];dd=np.maximum.accumulate(np.maximum.accumulate(np.maximum(0.,equity))-equity)
            curve=np.column_stack([equity,realized,longs,shorts,dd,cash,longs-shorts,campaign])
            assert report.fingerprint(curve)==ledger['result_fingerprints']['curve']
            assert hashlib.sha256(equity.tobytes()).hexdigest()==stores['audits'][key]['時価SHA256']
            for t,row,q1,q2,value in record['tracking']:
                if row<0:assert value==q1==q2==0;continue
                assert t==time[row] and [q1,q2,value]==[longs[row],shorts[row],equity[row]*factor]
            expected_position=[[float(ready['start']),-1,0.,0.]]+[
                [float(time[int(o[0])]),int(o[0]),float(longs[int(o[0])]),float(shorts[int(o[0])])] for o in orders]
            expected_position.append([float(time[-1]),n-1,0.,0.]);assert expected_position==record['position']
            pnl=(trades[:,5]-trades[:,4])*trades[:,2]*trades[:,3]*factor
            totals=dict(net_yen=float(sum(pnl)),gross_profit_yen=float(sum(pnl[pnl>0])),gross_loss_yen=float(-sum(pnl[pnl<0])),
                        profit_units=int(sum(trades[pnl>0,3])),loss_units=int(sum(trades[pnl<0,3])),
                        zero_units=int(sum(trades[pnl==0,3])),closed_units=int(sum(trades[:,3])))
            assert totals.keys()==record['totals'].keys()
            for name,value in totals.items():
                np.testing.assert_allclose(value,record['totals'][name],rtol=0,atol=1e-6)
                np.testing.assert_allclose(value,stores['sessions'][key][name],rtol=0,atol=1e-6)
            # ----------------------------------------
            # 影組ごとの実観測価格を直接走査し、最初の到達を保存印と比較する。
            levels=[];expected_arms=[]
            openings={int(o[2]):o for o in ledger['shadow_orders'] if o[6]==20 and o[7]==1}
            for cycle in sorted(ledger['shadow_cycles']):
                group,begin,end=int(cycle[0]),int(cycle[1]),int(cycle[2]);entry=openings[group];d=int(cycle[8]);a0=cycle[5]
                levels.append([float(time[begin]),float(time[end]),float(entry[5]+d*1.5*a0),group,begin,end,d,float(a0),float(entry[5])])
                if method in report.GATED_METHODS:
                    reached=None
                    for row in range(begin,end):
                        if np.isfinite(ready['last'][row]) and d*(ready['last'][row]-entry[5])/a0>=1.5:
                            reached=row;break
                    if reached is not None:expected_arms.append((group,reached))
            assert levels==record['levels']
            events=ledger['arm_events'];assert events==stores['gate_use'][key]['arm_events']
            assert expected_arms==[(int(e['campaign']),int(e['row'])) for e in events]
            expected_rendered=[[float(e['time_s']),int(e['row']),int(e['campaign']),float(ready['last'][int(e['row'])]),
                int(e['direction']),float(e['initial_atr']),float(e['anchor']),float(e['mfe_atr']),int(e['original_source_row'])] for e in events]
            assert expected_rendered==record['arms']
            checks.append(dict(id=method,session=key[0],symbol=key[1],全合格=True,全原本足一致=True,全売買一致=True,
                               全原本曲線指紋一致=True,全金額枚数一致=True,共通価格基準一致=True,初回到達別計算一致=True))
    assert len(checks)==104;ui=ui_check(payload)
    report.save(HERE/'chart_audit.json',dict(全合格=True,全図示数=104,結果=checks,UI=ui,HTML_SHA256=report.digest(page),
        固定SHA256=report.digest(HERE/'chart_fixed.json'),参照SHA256={p.relative_to(ROOT).as_posix():report.digest(p) for p in sourcepaths},
        新売買再生=False,API取得数=0))
    print('全104図の全売買・原本曲線・到達が一致。',flush=True)


if __name__=='__main__':main()
