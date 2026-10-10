"""図の全104画面を、生成器の売買復元とは別に保存台帳から検算する。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import pickle
import subprocess

from bs4 import BeautifulSoup
import numpy as np

import chart_report as report

HERE, ROOT = report.HERE, report.ROOT


def ui_check(payload: dict) -> dict:
    """機能: 外部通信なしの描画代替DOMで全選択と表行数を検査する。

    引数: payload (dict)。返り値: 選択件数と有限座標の確認 (dict)。実画面の視認確認とは別。
    """
    before = 'const payload='+json.dumps(payload,ensure_ascii=False,allow_nan=False)+';'
    before += '''const elements={};const context=new Proxy({}, {get(target,key){if(key in target)return target[key];return (...args)=>{for(const v of args)if(typeof v==='number'&&!Number.isFinite(v))throw Error('非有限描画 '+String(key))}},set(target,key,value){target[key]=value;return true}});function element(id){if(!elements[id])elements[id]={value:'',options:[],innerHTML:'',textContent:id==='chart-data'?JSON.stringify(payload):'',appendChild(v){this.options.push(v);if(!this.value)this.value=v.value},addEventListener(){},getBoundingClientRect(){return {width:1180}},getContext(){return context}};return elements[id]}global.window={devicePixelRatio:1,addEventListener(){}};global.document={getElementById:element,createElement(){return {value:'',textContent:''}}};'''
    after = '''let checked=0;for(const m of Object.keys(payload.methods)){for(const s of ['TOPIX','NK225']){for(const k of payload.sessions){window.chartSelect(m,s,k);const key=m+'|'+k+'|'+s,r=payload.records[key];if(window.chartRenderedKey!==key||!window.chartViewReady)throw Error('選択不一致');const training=element('chart-summary').innerHTML.includes('学習専用・取引0');if(training!==r.training)throw Error('学習表示不一致');for(const [id,rows] of [['order-table',r.orders],['trade-table',r.trades]]){const count=(element(id).innerHTML.match(/<tbody>/g)||[]).length;if(count!==(rows.length?1:0))throw Error('空台帳不一致');const lines=(element(id).innerHTML.match(/<tr>/g)||[]).length;if(lines!==(rows.length?rows.length+1:0))throw Error('表行欠落')}checked++}}}process.stdout.write(JSON.stringify({全合格:true,選択数:checked,非有限描画なし:true}));'''
    result = subprocess.run(['node','-'],input=before+(HERE/'chart.js').read_text(encoding='utf-8')+after,
        text=True,encoding='utf-8',capture_output=True,timeout=60)
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout);assert value['全合格']
    return value


def artificial() -> dict:
    """機能: 104空画面と一例の注文を使い、表示操作を成績なしで確認する。

    引数: なし。返り値: 人工表示の証拠 (dict)。
    """
    sessions=[f'人工{i:02d}' for i in range(13)]
    payload=dict(methods=report.METHODS,sessions=sessions,training_sessions=sessions[:2],
        candles={},records={},reason_names=report.REASONS,preview=True)
    ready=dict(start=0.,limit=150.,time_s=np.array([0.,60.,60.,120.,180.]),
        last=np.array([100.,101.,102.,104.,103.]))
    for session in sessions:
        for symbol in report.FACTORS:
            payload['candles'][session+'|'+symbol]=[[0.,100.,105.,99.,103.]]
            for method in report.METHODS:
                ledger=dict(orders=[],trades=[])
                if session not in sessions[:2]:
                    ledger=dict(orders=[[1,0,1,1,101,0,1],[3,1,-1,1,103,2,0]],
                        trades=[[1,3,1,101,103,1,2,2,0,1]])
                row=report.records(ready,ledger,report.FACTORS[symbol]);row['training']=session in sessions[:2]
                payload['records'][method+'|'+session+'|'+symbol]=row
    result=ui_check(payload);assert result['選択数']==104
    return result


def main() -> None:
    """機能: 人工だけ、又は生成済み全図を独立の注文集計から監査する。

    引数: --selftest (bool)。返り値: なし (None)。売買の再生と条件選択は行わない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--selftest',action='store_true');args=parser.parse_args()
    synthetic=artificial()
    if args.selftest:
        report.save(HERE/'chart_ui_synthetic.json',synthetic)
        print('人工104画面の選択・全表・有限描画を確認。',flush=True);return
    fixed=report.read(HERE/'chart_fixed.json')
    for path,sha in fixed['SHA256'].items():assert report.digest(ROOT/path)==sha,path
    generation=report.read(HERE/'chart_generation.json')
    path=report.OUT/'５分足と売買.html'
    assert generation['全合格'] and generation['全図示数']==104
    assert generation['HTML_SHA256']==report.digest(path)
    soup=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
    tags=soup.select('#chart-data');assert len(tags)==1
    payload=json.loads(tags[0].get_text());assert payload['methods']==report.METHODS
    scripts=soup.find_all('script');assert len(scripts)==2 and all(not s.get('src') for s in scripts)
    assert scripts[1].get_text()==(HERE/'chart.js').read_text(encoding='utf-8')
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    sessions=sorted({k[0] for k in inputs})
    assert payload['sessions']==sessions and payload['training_sessions']==sessions[:2]
    expected={m+'|'+'|'.join(k) for m in report.METHODS for k in inputs}
    assert len(payload['records'])==104 and set(payload['records'])==expected
    assert set(payload['candles'])=={'|'.join(k) for k in inputs}
    totals=[];source_hashes={}
    for key,ready in sorted(inputs.items()):
        source=ROOT/'candle_5min'/key[1]/(key[0]+'.csv')
        actual=[]
        with source.open(encoding='utf-8-sig',newline='') as stream:
            for row in csv.DictReader(stream):
                stamp=datetime.fromisoformat(row['time']).timestamp()
                if row['closed'].lower()=='true' and ready['start']<=stamp<=ready['limit']:
                    actual.append([stamp,float(row['open']),float(row['high']),float(row['low']),float(row['close'])])
        assert payload['candles']['|'.join(key)]==actual
        source_hashes[source.relative_to(ROOT).as_posix()]=report.digest(source)
    for method in report.METHODS:
        ledger_path=HERE/'ledgers'/(method+'.json.gz');session_path=HERE/'sessions'/(method+'.json.gz')
        ledgers={(v['session'],v['symbol']):v for v in report.read(ledger_path)}
        values={(v['session'],v['symbol']):v for v in report.read(session_path)}
        assert set(ledgers)==set(values)==set(inputs)
        for key,ready in sorted(inputs.items()):
            row=payload['records'][method+'|'+'|'.join(key)];saved=ledgers[key]
            orders=np.asarray(saved['orders'],float).reshape((-1,7))
            trades=np.asarray(saved['trades'],float).reshape((-1,10));factor=report.FACTORS[key[1]]
            assert row['factor']==factor
            assert row['orders']==[[float(ready['time_s'][int(o[0])]),*o.tolist()] for o in orders]
            assert row['trades']==[[float(ready['time_s'][int(t[0])]),float(ready['time_s'][int(t[1])]),*t.tolist()] for t in trades]
            assert row['training']==(key[0] in sessions[:2])
            if row['training']:assert not len(orders) and not len(trades)
            profits=[float(t[2]*(t[4]-t[3])*factor) for t in trades]
            expected_totals=dict(net_yen=sum(profits),profit_yen=sum(p for p in profits if p>0),
                loss_yen=-sum(p for p in profits if p<0),trades=len(profits),
                profit_units=sum(p>0 for p in profits),loss_units=sum(p<0 for p in profits),zero_units=sum(p==0 for p in profits))
            assert set(row['totals'])==set(expected_totals)
            for name,value in expected_totals.items():
                np.testing.assert_allclose(row['totals'][name],value,rtol=0,atol=1e-7)
                np.testing.assert_allclose(values[key][name],value,rtol=0,atol=1e-7)
            # ----------------------------------------
            # 全約定行の包含と、時点以前の注文だけによる符号付き在庫・現金を別計算する。
            indices={len(ready['seq'])-1,*[int(o[0]) for o in orders]}
            tick=float(ready['start'])
            while tick<=ready['time_s'][-1]:
                index=int(np.searchsorted(ready['time_s'],tick,side='right')-1)
                if index>=0:indices.add(index)
                tick+=300
            assert [int(s[1]) for s in row['tracking']]==[-1,*sorted(indices)]
            for stamp,index,quantity,equity in row['tracking']:
                if index<0:assert stamp==ready['start'] and quantity==equity==0;continue
                assert stamp==ready['time_s'][index]
                past=orders[orders[:,0]<=index]
                q=sum(float(o[2]*o[3]) for o in past)
                cash=-sum(float(o[2]*o[3]*o[4]) for o in past)
                assert q==quantity and quantity in (-1,0,1)
                np.testing.assert_allclose(equity,(cash+q*ready['last'][index])*factor,rtol=0,atol=1e-7)
            positions=[[float(ready['start']),-1,0]];quantity=0
            for order in orders:
                quantity+=int(order[2]*order[3]);positions.append([float(ready['time_s'][int(order[0])]),int(order[0]),quantity])
            assert quantity==0
            positions.append([float(ready['time_s'][-1]),len(ready['seq'])-1,0]);assert row['position']==positions
            totals.append(dict(id=method,session=key[0],symbol=key[1],全合格=True,
                orders=len(orders),trades=len(trades),学習専用=row['training']))
        for path in (ledger_path,session_path):source_hashes[path.relative_to(ROOT).as_posix()]=report.digest(path)
    ui=ui_check(payload);assert ui['選択数']==104
    assert source_hashes==generation['参照SHA256']
    report.save(HERE/'chart_audit.json',dict(全合格=True,全図示数=104,全注文一致=True,全返済一致=True,
        全数量一致=True,全損益一致=True,学習専用16画面の取引ゼロ=True,結果=totals,
        UI=ui,実画面の視認検査は別=True,暫定=payload['preview'],
        HTML_SHA256=report.digest(report.OUT/'５分足と売買.html'),固定SHA256=report.digest(HERE/'chart_fixed.json'),
        探索固定SHA256=report.digest(HERE/'探索条件の固定.json'),参照SHA256=source_hashes,
        API取得数=0,現在保存物使用=False))
    print('全104図の全売買・数量・金額・選択が一致。',flush=True)


if __name__=='__main__':main()
