"""旧26入力を固定し、共通初回の出口13方式を口座と混同せず対応比較する。"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import exit_design as design
import engine_exit_campaign as engine
from check_exit_campaign import account

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
INPUT=HERE.parent/'wave_v23/inputs.pkl'
LEDGER=HERE.parent/'wave_v45/ledgers/A0__V000.json.gz'
FIXED=HERE/'exit_fixed.json'
MULT={'TOPIX':1000.,'NK225':10.}


def sha(path: Path) -> str:
    """機能: 読取対象又は生成物の内容指紋を返す。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを非有限値なしで新領域へ保存する。

    引数: path(Path)、value(object)。返り値: なし。
    """
    raw=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')
    path.write_bytes(gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw)


def prepare() -> dict:
    """機能: 条件・既知入力・実装・人工監査を実再生より先に固定する。

    引数: なし。返り値: 固定記録(dict)。既存の異なる固定は上書きしない。
    """
    proof=json.loads((HERE/'check_exit_campaign.json').read_text(encoding='utf8'))
    assert proof['全合格'] and proof['人工条件入力数']==208 and proof['旧A0人工組一致数']>=1
    for name,digest in proof['参照資料SHA256'].items():assert sha(HERE/name)==digest
    paths=[INPUT,LEDGER,HERE.parent/'wave_v45/完備監査.json',HERE/'exit_design.py',
           HERE/'engine_exit_campaign.py',Path(__file__),HERE/'check_exit_campaign.py',
           HERE/'check_exit_campaign.json',HERE/'出口比較の実装契約.md']
    fixed=dict(条件=design.catalog(),規則=design.rules(),参照資料SHA256={p.relative_to(ROOT).as_posix():sha(p) for p in paths})
    if FIXED.exists():assert json.loads(FIXED.read_text(encoding='utf8'))==fixed
    else:save(FIXED,fixed)
    return fixed


def verify() -> dict:
    """機能: 固定内容と全参照指紋を再確認する。

    引数: なし。返り値: 固定記録(dict)。
    """
    fixed=json.loads(FIXED.read_text(encoding='utf8'))
    assert fixed['条件']==design.catalog() and fixed['規則']==design.rules()
    for p,digest in fixed['参照資料SHA256'].items():assert sha(ROOT/p)==digest,p
    return fixed


def entry_from(order: np.ndarray, cycle: np.ndarray) -> dict:
    """機能: 元初回の8項目だけを渡し、終了行や未来損益を含めない。

    引数: order/cycle(ndarray)。返り値: 共通初回(dict)。
    """
    return dict(row=int(order[0]),decision_row=int(order[1]),side=int(order[3]),qty=int(order[4]),
                price=float(order[5]),initial_atr=float(cycle[5]),initial_risk=float(cycle[4]),campaign=int(order[2]))


def ratio(a: float, b: float) -> float | None:
    """機能: 定義できる有限比率だけを返す。

    引数: a/b(float)。返り値: 比率(float)又は未定義(None)。
    """
    return float(a/b) if b>0 and np.isfinite(a/b) else None


def summary(rows: list[dict]) -> dict:
    """機能: 重複し得る元組実験の損益を診断集計し、口座DDを作らない。

    引数: rows(list[dict])。返り値: 診断値(dict)。
    """
    net=[r['net_yen'] for r in rows];delta=[r['delta_yen'] for r in rows]
    profit=sum(r['profit_yen'] for r in rows);loss=sum(r['loss_yen'] for r in rows)
    wu=sum(r['profit_units'] for r in rows);lu=sum(r['loss_units'] for r in rows)
    cp=sum(max(x,0) for x in net);cl=sum(max(-x,0) for x in net)
    cw=sum(x>1e-8 for x in net);cc=sum(x<-1e-8 for x in net)
    return dict(元組数=len(rows),利益円=profit,損失円=loss,診断収支円=sum(net),利益枚数=wu,損失枚数=lu,
                同値枚数=sum(r['zero_units'] for r in rows),元組PF=ratio(cp,cl),
                元組平均勝敗比=ratio(cp/cw,cl/cc) if cw and cc else None,
                一枚平均勝敗比=ratio(profit/wu,loss/lu) if wu and lu else None,
                基準差円=sum(delta),増益組数=sum(x>1e-8 for x in delta),減益組数=sum(x<-1e-8 for x in delta),
                同値組数=sum(abs(x)<=1e-8 for x in delta),最大増益一組除外差円=sum(delta)-max([0.]+delta),
                最大利益一組除外収支円=sum(net)-max([0.]+net),元組DD最大円=max([0.]+[r['dd_yen'] for r in rows]),
                最高利益返却合計円=sum(r['giveback_yen'] for r in rows),
                R超過組数=sum(r['excess_yen']>1e-8 for r in rows),R超過合計円=sum(r['excess_yen'] for r in rows),
                旧退出より後の組数=sum(r['exit_row']>r['baseline_exit_row'] for r in rows),実運用口座PLではない=True)


def overlap(rows: list[dict], inputs: dict) -> dict:
    """機能: 独立実験の保有が重なる量を原本行で計測する。

    引数: rows(list[dict])、inputs(dict)。返り値: 最大枚数と重複秒(dict)。
    """
    maximum=0;seconds=0.;campaign_max=0
    for key,ready in inputs.items():
        relevant=[r for r in rows if (r['session'],r['symbol'])==key]
        qty=np.zeros(len(ready['last'])+1);active=np.zeros_like(qty)
        for r in relevant:
            active[r['entry_row']]+=1;active[r['exit_row']]-=1
            for o in r['orders']:
                qty[int(o[0])]+=o[4] if o[7] else -o[4]
        qty=np.cumsum(qty[:-1]);active=np.cumsum(active[:-1]);dt=np.diff(ready['time_s'],append=ready['time_s'][-1])
        maximum=max(maximum,int(np.max(qty)));campaign_max=max(campaign_max,int(np.max(active)))
        seconds+=float(np.sum(dt[active>1]))
    return dict(同時枚数最大=maximum,同時元組数最大=campaign_max,複数元組保有秒=seconds,
                説明='独立実験を同時運用したと仮定した必要数量。運用可能性の合格ではない。')


def run() -> dict:
    """機能: 旧26入力の全共通初回×13方式を再生・検算し、対応差を保存する。

    引数: なし。返り値: 全検算・比較結果(dict)。新ナイトは入力禁止。
    """
    fixed=verify();inputs=pickle.loads(INPUT.read_bytes());ledgers=json.loads(gzip.decompress(LEDGER.read_bytes()))
    keys={(r['session'],r['symbol']) for r in ledgers}
    assert len(keys)==len(ledgers)==len(inputs)==26 and keys==set(inputs)
    assert all(s<='2026-09-29_Day' for s,_ in keys)
    sessions=sorted({s for s,_ in keys});assert len(sessions)==13
    results=[];baseline_count=0;audited_rows=0;prefix_count=0
    for ledger in ledgers:
        key=(ledger['session'],ledger['symbol']);ready=inputs[key];mult=MULT[key[1]]
        oo=np.asarray(ledger['orders'],float).reshape(-1,8);tt=np.asarray(ledger['trades'],float).reshape(-1,11)
        cycles=np.asarray(ledger['cycles'],float).reshape(-1,10)
        for cycle in cycles:
            cid=int(cycle[0]);openings=oo[(oo[:,2]==cid)&(oo[:,7]==1)]
            assert len(openings)==1 and int(openings[0,6])==20
            e=entry_from(openings[0],cycle)
            for spec in fixed['条件']:
                got=engine.run(ready,e,spec);account(ready,e,got);audited_rows+=len(ready['last'])
                if spec['id']==design.BASELINE:
                    np.testing.assert_array_equal(got['orders'],oo[oo[:,2]==cid])
                    want=tt[tt[:,0]==cid].copy();want[:,1]=0
                    np.testing.assert_array_equal(got['trades'],want)
                    np.testing.assert_array_equal(got['cycles'],cycle[None,:]);baseline_count+=1
                trades=got['trades'];gains=trades[:,10]*mult;pos=gains>1e-8;neg=gains<-1e-8
                exit_row=int(got['cycles'][0,2]);net=float(got['stats'][0]*mult)
                # ----------------------------------------
                # 台帳による会計検算とは別に、各組中点で過去出力が未来末尾に依存しないことを確認する。
                cut=max(e['row']+1,(e['row']+exit_row)//2+1)
                short={k:(v[:cut] if isinstance(v,np.ndarray) and len(v)==len(ready['last']) else v) for k,v in ready.items()}
                prefix=engine.run(short,e,spec,require_complete=False)
                np.testing.assert_array_equal(prefix['orders'],got['orders'][got['orders'][:,0]<cut])
                np.testing.assert_array_equal(prefix['curve'],got['curve'][:cut]);prefix_count+=1
                results.append(dict(id=spec['id'],session=key[0],symbol=key[1],campaign=cid,entry=e,
                    entry_row=e['row'],exit_row=exit_row,baseline_exit_row=int(cycle[2]),
                    baseline_net_yen=float(cycle[3]*mult),net_yen=net,delta_yen=float(net-cycle[3]*mult),
                    profit_yen=float(gains[pos].sum()),loss_yen=float(-gains[neg].sum()),
                    profit_units=int(trades[pos,3].sum()),loss_units=int(trades[neg,3].sum()),
                    zero_units=int(trades[~(pos|neg),3].sum()),dd_yen=float(got['stats'][1]*mult),
                    giveback_yen=float((max(0.,got['stats'][8])-got['stats'][0])*mult) if got['stats'][8]>0 else 0.,
                    excess_yen=float(max(0.,-got['stats'][0]-e['initial_risk'])*mult),
                    trades=trades.tolist(),orders=got['orders'].tolist()))
        print(key,'完了',flush=True)
    assert baseline_count==102 and len(results)==13*102
    aggregate=[]
    for spec in fixed['条件']:
        row=dict(id=spec['id'],name=spec['name'],symbols={})
        for symbol in MULT:
            group=[r for r in results if r['id']==spec['id'] and r['symbol']==symbol]
            periods={'全13':sessions,'前6':sessions[:6],'後7':sessions[6:],**{s:[s] for s in sessions}}
            row['symbols'][symbol]={label:summary([r for r in group if r['session'] in ss]) for label,ss in periods.items()}
            row['symbols'][symbol]['重複診断']=overlap(group,{k:v for k,v in inputs.items() if k[1]==symbol})
        both=[row['symbols'][s]['全13'] for s in MULT]
        row['対応比較フラグ']=dict(両市場増益=all(x['基準差円']>0 for x in both),
            最大増益一組除外も両市場差正=all(x['最大増益一組除外差円']>0 for x in both),
            最大利益一組除外も両市場黒字=all(x['最大利益一組除外収支円']>0 for x in both),
            両市場元組平均勝敗比超一=all(x['元組平均勝敗比'] is not None and x['元組平均勝敗比']>1 for x in both),
            自動採用=False)
        aggregate.append(row)
    save(HERE/'exit_campaign_results.json.gz',results)
    proof=dict(全合格=True,条件数=13,旧入力数=26,共通元組数=baseline_count,全元組実験数=len(results),
               全行会計数=audited_rows,原A0全元組経済配列一致=True,全元組prefix一致数=prefix_count,
               元終了行を実装へ入力しない=True,重複を実運用損益へ合算しない=True,
               新ナイト使用=False,API取得数=0,固定SHA256=sha(FIXED),結果=aggregate,
               全元組明細SHA256=sha(HERE/'exit_campaign_results.json.gz'))
    verify();save(HERE/'exit_results.json',proof)
    print('全元組実験数',len(results),'基準一致',baseline_count)
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
    prepare() if args.prepare else run()
