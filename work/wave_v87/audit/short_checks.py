"""最新支持と追跡極値の順序を、人工列と保存原本の未来切断で監査する。"""

import argparse
import hashlib
import os
import pickle
import numpy as np
from diagnose import ROOT,HERE,save
from boundaries import module,fixture,old_boundary
from support import clip,compare_prefix

ROUND=ROOT/'work/wave_v87/round3'


def load():
    """
    機能: 検証対象を読取り、コンパイルだけ監査領域へ向ける。
    引数: なし。
    返り値: tuple[module,dict]。
    """
    strategy=module('監査87短期支持戦略',ROUND/'strategy.py')
    catalog=module('監査87短期支持条件',ROUND/'catalog.py')
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache');os.environ['NUMBA_CACHE_DIR']=str(HERE/'cache')
    strategy.base.integration.reference.initialize()
    return strategy,{c['id']:c for c in catalog.catalog()}


def hashes():
    """
    機能: 売買・特徴コードの監査開始終了の指紋を得る。
    引数: なし。
    返り値: dict[str,str]。
    """
    names=('core.py','signals.py','prepare.py','strategy.py','catalog.py','build_engine.py','engine.py','shadow_engine.py')
    return {name:hashlib.sha256((ROUND/name).read_bytes()).hexdigest() for name in names}


def material(prices,offsets,reflected=False,symbol='TOPIX',**kwargs):
    """
    機能: 原本前行まで公開した支持だけを持つ人工素材を作る。
    引数: prices/offsets(list)、reflected(bool)、symbol(str)、kwargs(dict)。
    返り値: tuple[dict,dict]。
    """
    ready,feature=fixture(prices,offsets,reflected=reflected,**kwargs)
    if symbol=='NK225':
        ready['last']*=20.;ready['atr']*=20.;ready['tick']*=20.;ready['symbol']=symbol
    n=len(prices);sign=-1 if reflected else 1
    feature['short']=dict(self_value=np.full(n,.1*sign),self_valid=np.ones(n,bool),
        self_source_seq=np.arange(n,dtype=np.int64)-1,peer_value=np.full(n,.1*sign),
        peer_valid=np.ones(n,bool),peer_source_time=ready['time_s']-1.)
    return ready,feature


def rules(result,ready,feature,config):
    """
    機能: 公開許可と極値の由来を、実装の判定関数を使わず再計算する。
    引数: result/ready/feature/config(dict)。
    返り値: intの照合行数。
    """
    old_boundary.check_source_order(result)
    mode=config['support_mode'];short=feature['short'];count=0
    for name in ('normal_shadow','shadow'):
        shadow=result[name];curve=shadow['support_curve'];plans=shadow['plans']
        preparations=shadow['prepare_events']
        for row in np.flatnonzero(curve[:,0]):
            side=int(curve[row,0]);extreme=int(curve[row,1])
            assert 0<=extreme<=row
            available=preparations[preparations[:,1]<=row]
            start=int(available[-1,1]);path=ready['last'][start:row+1]
            expected=start+int(np.nanargmin(path) if side>0 else np.nanargmax(path))
            assert extreme==expected,(name,row,extreme,expected)
            permit=True
            if mode:
                permit=bool(short['self_valid'][row] and side*short['self_value'][row]>.05)
                if mode in (2,4):permit=permit and short['self_source_seq'][row]>ready['seq'][extreme]
                if mode in (3,4):permit=permit and short['peer_valid'][row] and side*short['peer_value'][row]>.05
                if mode==4:permit=permit and short['peer_source_time'][row]>ready['time_s'][extreme]
            assert bool(curve[row,2])==bool(permit)
            assert plans[row,21]==(side if permit else 0)
            assert curve[row,3]==plans[row,22]
            count+=1
        for entry in result['orders'][result['orders'][:,7]==1]:
            row=int(entry[0]);plan=result['shadow']['execution_plans'][row]
            assert plan[21]==entry[3]
            assert plan[27]<row and plan[29]<row
    return count


def run(strategy,config,ready,feature,observed):
    """
    機能: 人工一列を再生し、公開判定を独立照合する。
    引数: strategy(module)、config/ready/feature(dict)、observed(bool)。
    返り値: dict。
    """
    result,_=strategy.play(config,ready,feature,observed=observed)
    rules(result,ready,feature,config)
    return result


def entries(result):
    """
    機能: 新規約定した原本行番号を順に取り出す。
    引数: result(dict)。
    返り値: list[int]。
    """
    return result['orders'][result['orders'][:,7]==1,0].astype(int).tolist()


def artificial(strategy,configs):
    """
    機能: 支持撤回・同値境界・次観測成行を価格反射と両商品で検証する。
    引数: strategy(module)、configs(dict)。
    返り値: None。人工の利益は手法評価に使わない。
    """
    before=hashes();records=[]
    for parent in ('GU','P1'):
        for symbol in ('TOPIX','NK225'):
            for reflected in (False,True):
                sign=-1 if reflected else 1
                for observed in (False,True):
                    def check(label,mode,prices,values,expected,*,source=None,peer_times=None,valid=None,peer_values=None):
                        """
                        機能: 一つの支持境界を構成し期待する入口行と照合する。
                        引数: label(str)、mode(int)、prices/values/expected(list)、任意の支持列。
                        返り値: tuple[dict,dict]。
                        """
                        ready,f=material(prices,list(range(len(prices))),reflected,symbol)
                        f['short']['self_value']=np.asarray(values)*sign
                        if source is not None:f['short']['self_source_seq']=np.asarray(source,dtype=np.int64)
                        if peer_times is not None:f['short']['peer_source_time']=ready['time_s'][0]+np.asarray(peer_times)
                        if valid is not None:f['short']['self_valid']=np.asarray(valid,bool)
                        if peer_values is not None:f['short']['peer_value']=np.asarray(peer_values)*sign
                        out=run(strategy,configs[f'{parent}_F{mode}'],ready,f,observed)
                        assert entries(out)==expected,(label,parent,symbol,reflected,observed,entries(out),out['support_curve'])
                        records.append(dict(検査=label,系統=parent,商品=symbol,ショート=reflected,観測約定=observed,新規行=expected))
                        return out,ready
                    # ----------------------------------------
                    # 旧注文の現行判定と、今観測した支持低下の順序を逆にしない。
                    check('最新非支持で次行から公開停止',1,[100,100.5,100.5,101.5,102],[.1,.1,0,0,0],[])
                    check('支持境界0.05ちょうどは許可しない',1,[100,100.5,100.5,101.5,102],[.1,.1,.05,.05,.05],[])
                    check('欠測支持でも次行から公開停止',1,[100,100.5,100.5,101.5,102],[.1]*5,[],valid=[1,1,0,0,0])
                    check('当行の支持低下で旧注文成立を取り消さない',1,[100,101.5,102],[.1,0,0],[1])
                    out,r=check('支持復活時の旧線越えは次行成行',1,[100,100.5,102,103,104],[.1,0,0,.1,.1],[4])
                    assert out['orders'][0,5]==r['last'][4] and out['shadow']['plans'][3,26]==1
                    out,r=check('不正価格の後は有効観測で再公開して次行約定',1,[100,100.5,np.nan,102,103],[.1]*5,[4])
                    assert out['orders'][0,5]==r['last'][4] and out['shadow']['plans'][2,21]==0
                    # ----------------------------------------
                    # 極値の同価格再観測は時計を更新せず、支持終端の等号を許さない。
                    out,r=check('自己極値後の終端と同値極値維持',2,[100,99,99,99,100.5,101],[.1]*6,[4])
                    assert out['support_curve'][2,1]==1 and out['support_curve'][2,2]==0
                    check('自己終端が極値と同じなら公開しない',2,[100,99,99,99,100.5,101],[.1]*6,[],source=[-1,0,1,1,1,1])
                    check('相手非支持なら双方条件を満たさない',3,[100,100.5,100.5,101.5,102],[.1]*5,[],peer_values=[.1,.1,0,0,0])
                    out,r=check('双方極値後は相手終端同時計を除外',4,[100,99,99,99,100.5,101],[.1]*6,[5],peer_times=[-1,0,1,1,2,3])
                    assert out['support_curve'][3,2]==0 and out['orders'][0,5]==r['last'][5]
                    # ----------------------------------------
                    # 公開を止めている間も待機期限は延長せず、新しい準備へ切り替える。
                    r,f=material([100,100.5,102,103.5,104],[0,1,302,303,304],reflected,symbol)
                    f['short']['self_value']=sign*np.asarray([.1,0,0,.1,.1])
                    out=run(strategy,configs[f'{parent}_F1'],r,f,observed)
                    assert entries(out)==[4]
                    assert out['prepare_events'][:,1].astype(int).tolist()==[0,2]
                    assert out['entry_preparations'][0,3]==2 and out['orders'][0,5]==r['last'][4]
                    records.append(dict(検査='支持無効中もTTL保持し新準備を参照',系統=parent,商品=symbol,
                        ショート=reflected,観測約定=observed,新規行=[4]))
                    print('支持人工',parent,symbol,reflected,observed,len(records),flush=True)
    assert before==hashes()
    save('最新支持と極値後根拠の人工境界.json',dict(全合格=True,検査数=len(records),検査=records,実装SHA256=before))


def prefix(strategy,configs):
    """
    機能: 両商品の日夜と二つの親方式で、将来行を切って公開・注文の不変を確かめる。
    引数: strategy(module)、configs(dict)。
    返り値: None。全場の新損益評価は行わない。
    """
    before=hashes();sessions=('2026-09-25_Day','2026-09-28_Night')
    inputs=pickle.loads((ROOT/'work/wave_v67/prepared/old23/new_inputs.pkl').read_bytes())
    inputs={k:v for k,v in inputs.items() if k[0] in sessions}
    signals=pickle.loads((ROOT/'work/wave_v67/prepared/old23/signals.pkl').read_bytes())
    signals={name:{k:v for k,v in values.items() if k in inputs} for name,values in signals.items()}
    features=strategy.initialize(inputs,signals)
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache')
    records=[]
    for key,ready in sorted(inputs.items()):
        feature=features[key];n=len(ready['last'])
        for observed in (False,True):
            for ident in ('GU_F2','GU_F4','P1_F2','P1_F4'):
                full,_=strategy.play(configs[ident],ready,feature,observed=observed)
                checked=rules(full,ready,feature,configs[ident]);cuts={int(n*.37),int(n*.78)}
                curve=full['support_curve'];changed=np.flatnonzero((curve[1:,2]!=curve[:-1,2])&(curve[1:,0]!=0))+1
                for row in changed[:3]:cuts.update((max(2,int(row)),min(n-1,int(row)+1)))
                for event in full['orders'][:2]:cuts.update((max(2,int(event[0])),min(n-1,int(event[0])+1)))
                comparisons=0
                for count in sorted(cuts):
                    part,_=strategy.play(configs[ident],clip(ready,count,n),clip(feature,count,n),observed=observed)
                    comparisons+=compare_prefix(full,part,count)
                    for name in ('support_curve','normal_support_curve'):
                        np.testing.assert_array_equal(full[name][:count],part[name][:count]);comparisons+=1
                    if 'profit_reentry_events' in full:
                        a,b=full['profit_reentry_events'],part['profit_reentry_events']
                        np.testing.assert_array_equal(a[a[:,0]<count],b[b[:,0]<count]);comparisons+=1
                    for name in ('support_events','normal_support_events'):
                        a,b=full[name],part[name]
                        np.testing.assert_array_equal(a[a[:,0]<count],b[b[:,0]<count]);comparisons+=1
                records.append(dict(セッション=key[0],商品=key[1],条件=ident,観測約定=observed,
                    切断地点=len(cuts),配列照合数=comparisons,公開と極値照合行数=checked,合格=True))
                print(key,ident,observed,len(cuts),comparisons,'支持prefix一致',flush=True)
    assert before==hashes()
    save('最新支持と極値後根拠の未来切断.json',dict(全合格=True,条件口座数=len(records),
        切断地点=sum(r['切断地点'] for r in records),配列照合数=sum(r['配列照合数'] for r in records),
        検査=records,実装SHA256=before,
        限界='準備済み特徴を原本行と同じ箇所で切り、発注・追跡極値・支持許可の因果性を検査。特徴抽出自体は別の公開時刻対応照合で確認する。'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prefix',action='store_true');args=parser.parse_args()
    strategy,configs=load()
    prefix(strategy,configs) if args.prefix else artificial(strategy,configs)
