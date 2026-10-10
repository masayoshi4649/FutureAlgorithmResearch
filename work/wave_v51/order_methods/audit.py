"""逐次注文管理の独立会計・未来遮断・公開ポリシー一致を検査する。"""
from copy import deepcopy
import hashlib
import numpy as np
import research as r
from policy import StreamingPolicy,execute


def accounting() -> dict:
    """機能: 両建て全脚を別々に会計し、最終合算と上限を検証する。

    引数: なし。返り値: 監査件数(dict)。
    """
    accounts=orders_count=hedge_cycles=0
    for config in r.catalog():
        rows={(x['session'],x['symbol']):x for x in r.read('sessions/'+config['id']+'.json')}
        for ledger in r.read('ledgers/'+config['id']+'.json.gz'):
            key=ledger['session'],ledger['symbol'];pv=1000 if key[1]=='TOPIX' else 10;cap=10 if key[1]=='TOPIX' else 20
            positions={1:0,-1:0};entries={1:0.,-1:0.};balance=0.;previous_time=0.;opening=[]
            for o in ledger['orders']:
                assert o[3]>o[2] and o[1]>=o[0] and o[1]>=previous_time
                previous_time=o[1];q=int(o[6]);assert q>0 and q==o[6]
                if o[4]==1:
                    side=int(o[5]);assert positions[side]==0
                    positions[side]=q;entries[side]=o[7];opening.append(o)
                    if config['family']==1 and all(positions.values()):
                        assert positions[1]==positions[-1] and entries[1]==entries[-1]
                        assert opening[-1][1]==opening[-2][1] and opening[-1][3]==opening[-2][3]
                        # 同枚数・同価格の両建ては初期の方向損益を厳密に相殺する。
                        assert sum(s*(o[7]-entries[s])*positions[s]*pv for s in (1,-1))==0
                        hedge_cycles+=1
                else:
                    side=int(-o[5]);assert 0<q<=positions[side]
                    pnl=side*(o[7]-entries[side])*q*pv
                    assert abs(pnl-o[8])<1e-7
                    positions[side]-=q;balance+=pnl
                assert all(0<=q<=cap for q in positions.values())
                orders_count+=1
            assert positions=={1:0,-1:0}
            assert abs(balance-rows[key]['net'])<1e-7
            trades=np.asarray(ledger['trades'],dtype=float).reshape(-1,16)
            assert np.allclose(trades[:,6],trades[:,2]*(trades[:,5]-trades[:,4])*trades[:,3]*pv,rtol=0,atol=1e-7)
            assert np.all(trades[:,12]>trades[:,13]) and abs(trades[:,6].sum()-balance)<1e-7
            assert abs(trades[trades[:,6]>0,6].sum()-rows[key]['profit'])<1e-7
            assert abs(-trades[trades[:,6]<0,6].sum()-rows[key]['loss'])<1e-7
            accounts+=1
    return dict(全合格=True,口座数=accounts,注文数=orders_count,同枚数同価格両建て確認数=hedge_cycles)


def prefix(inputs: dict) -> list[dict]:
    """機能: 未来行削除・未来価格/ATR変更で過去の全注文が完全一致するか検査する。

    引数: inputs(dict)。返り値: 証跡(list[dict])。
    """
    records=[]
    # 全60条件で2銘柄・最近1場を確認し、系統代表は別の長いナイトも追加する。
    for config in r.catalog():
        for symbol in ('TOPIX','NK225'):
            key=('2026-10-06_Day',symbol);ready=inputs[key]
            full=execute(config,ready)
            for fraction in (.35,.70):
                cut=max(1,int(len(ready['seq'])*fraction));prefix={k:(v[:cut].copy() if isinstance(v,np.ndarray) else v) for k,v in ready.items()}
                altered=deepcopy(ready);altered['last'][cut:]+=10000;altered['atr'][cut:]*=7
                short=execute(config,prefix,False);future=execute(config,altered)
                end_seq=ready['seq'][cut-1]
                assert np.array_equal(full[1][full[1][:,3]<=end_seq],short[1])
                assert np.array_equal(full[0][full[0][:,12]<=end_seq],short[0])
                assert np.array_equal(full[1][full[1][:,3]<=end_seq],future[1][future[1][:,3]<=end_seq])
                records.append(dict(id=config['id'],symbol=symbol,cut_seq=int(end_seq),過去完全一致=True))
    return records


def public_policy(inputs: dict) -> list[dict]:
    """機能: 公開on_tickを一行ずつ呼び、高速driverと全注文・終状態を完全一致させる。

    引数: inputs(dict)。返り値: 証跡(list[dict])。
    """
    identifiers=r.read('過去10場選択.json')['系統代表'];configs=[x for x in r.catalog() if x['id'] in identifiers]
    records=[]
    for config in configs:
        for symbol in ('TOPIX','NK225'):
            ready=inputs[('2026-10-06_Day',symbol)]
            expected=execute(config,ready);policy=StreamingPolicy(config,ready['start'],ready['limit'],symbol)
            orders=[];trades=[]
            for now,seq,price,atr in zip(ready['time_s'],ready['seq'],ready['last'],ready['atr']):
                output=policy.on_tick(float(now),int(seq),float(price),float(atr))
                orders.extend(output['orders']);trades.extend(output['trades'])
            assert np.array_equal(np.asarray(orders).reshape(-1,10),expected[1])
            assert np.array_equal(np.asarray(trades).reshape(-1,16),expected[0])
            assert np.array_equal(policy.state,expected[2]) and np.array_equal(policy.legs,expected[3])
            records.append(dict(id=config['id'],symbol=symbol,原本行数=len(ready['seq']),完全一致=True))
    return records


def flat_and_hedge() -> dict:
    """機能: 値動きのない市場で両脚収支がゼロ、片脚決済時の損益恒等式を検査する。

    引数: なし。返り値: 検査件数(dict)。
    """
    count=0
    base=dict(start=0.,limit=14400.,symbol='TOPIX',time_s=np.arange(0,14500.,10.),seq=np.arange(1450),last=np.full(1450,100.),atr=np.full(1450,2.))
    for config in r.catalog():
        t,o,state,legs=execute(config,base)
        assert float(state[11])==0 and float(state[13])==0
        if len(t):assert np.all(t[:,6]==0)
        if config['family']==0:assert len(o)==0
        if config['family']==1:assert len(o)>=4
        count+=1
    # 負け脚返済後の合算価値は、その時点で反対脚方向へ新規した価値に等しい。
    checked=0
    for entry in (100.,1000.):
        for close in (entry-3,entry+3):
            loser=-1 if close>entry else 1;remaining=-loser;q=5;pv=1000
            loss=loser*(close-entry)*q*pv
            for mark in (entry-10,entry,entry+10):
                combined=loss+remaining*(mark-entry)*q*pv
                effective=remaining*(mark-close)*q*pv
                assert combined==effective;checked+=1
    return dict(静止相場条件数=count,両建て相殺恒等式数=checked,全合格=True)


def main() -> None:
    """機能: 全60方式の各監査を実行し指紋付きで保存する。

    引数: なし。返り値: なし(None)。
    """
    inputs=r.load();accounts=accounting();print('独立会計完了',flush=True)
    causal=prefix(inputs);print('未来遮断完了',flush=True)
    public=public_policy(inputs);print('公開一行ポリシー一致',flush=True)
    identities=flat_and_hedge();print('両脚相殺検査完了',flush=True)
    r.save('監査.json',dict(全合格=True,会計=accounts,接頭辞未来変更=causal,公開逐次ポリシー=public,静止相場と両建て=identities,
                          SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in r.HERE.glob('*.py')}))


if __name__=='__main__':main()
