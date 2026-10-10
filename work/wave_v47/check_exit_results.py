"""出口実験の保存台帳だけから会計・対応差・集中・集計を別式で再計算する。"""

import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent


def digest(path: Path) -> str:
    """機能: 検査対象の内容指紋を返す。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def near(a: float, b: float) -> None:
    """機能: 円換算の独立演算の丸め範囲で一致を要求する。

    引数: a/b(float)。返り値: なし。
    """
    assert np.isfinite(a) and np.isfinite(b) and abs(a-b)<1e-6,(a,b)


def main() -> dict:
    """機能: 全元組の売買・含み・損益統計と全区間集計を独立再計算する。

    引数: なし。返り値: 監査証跡(dict)。注文器・集計器を呼び出さない。
    """
    source=HERE/'exit_campaign_results.json.gz';header_path=HERE/'exit_results.json'
    header=json.loads(header_path.read_text(encoding='utf8'))
    rows=json.loads(gzip.decompress(source.read_bytes()))
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    old=json.loads(gzip.decompress((HERE.parent/'wave_v45/ledgers/A0__V000.json.gz').read_bytes()))
    baselines={(r['session'],r['symbol'],int(c[0])):c for r in old for c in r['cycles']}
    assert header['全合格'] and len(rows)==1326 and len(baselines)==102
    unique={(r['id'],r['session'],r['symbol'],r['campaign']) for r in rows};assert len(unique)==1326
    records=[];observations=0
    for r in rows:
        ready=inputs[(r['session'],r['symbol'])];n=len(ready['last']);mult=1000. if r['symbol']=='TOPIX' else 10.
        orders=np.array(r['orders']);trades=np.array(r['trades']);base=baselines[(r['session'],r['symbol'],r['campaign'])]
        cash=np.zeros(n);qty=np.zeros(n);real=np.zeros(n)
        np.add.at(cash,orders[:,0].astype(int),-orders[:,3]*orders[:,4]*orders[:,5])
        np.add.at(qty,orders[:,0].astype(int),orders[:,3]*orders[:,4])
        gain=(trades[:,5]-trades[:,4])*trades[:,2]*trades[:,3]
        np.testing.assert_allclose(gain,trades[:,10],rtol=0,atol=1e-8)
        np.add.at(real,trades[:,7].astype(int),gain)
        cash=np.cumsum(cash);qty=np.cumsum(qty);real=np.cumsum(real)
        assert qty[-1]==0 and (orders[:,1]<orders[:,0]).all()
        assert np.max(np.abs(qty))<=r['entry']['qty'] and len(orders[orders[:,7]==1])==1
        eq=cash+qty*ready['last'];net=float(gain.sum()*mult)
        dd=float(np.max(np.maximum.accumulate(eq)-eq)*mult)
        peak=float(np.max(eq));giveback=(peak-gain.sum())*mult if peak>0 else 0.
        near(net,r['net_yen']);near(dd,r['dd_yen']);near(giveback,r['giveback_yen'])
        near(real[-1]*mult,net);near(eq[-1]*mult,net)
        near(net-base[3]*mult,r['delta_yen']);near(max(0.,-gain.sum()-base[4])*mult,r['excess_yen'])
        wins=gain>1e-8;losses=gain<-1e-8
        near(gain[wins].sum()*mult,r['profit_yen']);near(-gain[losses].sum()*mult,r['loss_yen'])
        assert int(trades[wins,3].sum())==r['profit_units'] and int(trades[losses,3].sum())==r['loss_units']
        assert int(trades[~(wins|losses),3].sum())==r['zero_units']
        assert int(trades[-1,7])==r['exit_row'] and int(base[2])==r['baseline_exit_row']
        records.append(r);observations+=n
    # ----------------------------------------
    # 全期間と部分期間の集計を、個別台帳から確定した値だけで照合する。
    sessions=sorted({s for s,_ in inputs});periods={'全13':sessions,'前6':sessions[:6],'後7':sessions[6:],**{s:[s] for s in sessions}}
    cells=0
    for result in header['結果']:
        for symbol in ('TOPIX','NK225'):
            for label,chosen in periods.items():
                group=[r for r in records if r['id']==result['id'] and r['symbol']==symbol and r['session'] in chosen]
                actual=result['symbols'][symbol][label]
                net=np.array([r['net_yen'] for r in group]);delta=np.array([r['delta_yen'] for r in group])
                for out,key in [('利益円','profit_yen'),('損失円','loss_yen'),('診断収支円','net_yen'),
                                ('利益枚数','profit_units'),('損失枚数','loss_units'),('同値枚数','zero_units'),('基準差円','delta_yen')]:
                    near(actual[out],sum(r[key] for r in group))
                near(actual['最大増益一組除外差円'],delta.sum()-max(0.,max(delta,default=0.)))
                near(actual['最大利益一組除外収支円'],net.sum()-max(0.,max(net,default=0.)))
                cp=net[net>0].sum();cl=-net[net<0].sum();nw=int((net>0).sum());nl=int((net<0).sum())
                expected=cp/cl if cl>0 else None
                if expected is None:assert actual['元組PF'] is None
                else:near(actual['元組PF'],expected)
                expected=(cp/nw)/(cl/nl) if nw and nl else None
                if expected is None:assert actual['元組平均勝敗比'] is None
                else:near(actual['元組平均勝敗比'],expected)
                wu=actual['利益枚数'];lu=actual['損失枚数']
                expected=(actual['利益円']/wu)/(actual['損失円']/lu) if wu and lu else None
                if expected is None:assert actual['一枚平均勝敗比'] is None
                else:near(actual['一枚平均勝敗比'],expected)
                cells+=1
    proof=dict(全合格=True,全元組数=len(rows),全行会計数=observations,集計セル数=cells,
               注文器と元集計関数を呼ばない=True,新ナイト使用=False,
               参照資料SHA256={p.name:digest(p) for p in [source,header_path,HERE/'exit_fixed.json',Path(__file__)]})
    (HERE/'check_exit_results.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False));return proof


if __name__=='__main__':main()
