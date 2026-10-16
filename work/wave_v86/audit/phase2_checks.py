"""料金後の親組黒字に限る再参加を、人工境界と原本切断で確認する。"""

import argparse
import math
import numpy as np

from boundaries import fixture, check_source_order
from support import WORK, ROOT, module, clip, compare_prefix, digest, save
from prefix import verify_original_gate


PHASE=WORK/'phase2'


def load():
    """
    機能: 第2段階だけを別モジュール名で読み込む。
    引数: なし。
    返り値: tuple[module,module,module]の戦略・条件・入力準備。
    """
    runner=module('wave86_phase2_audit_runner',PHASE/'research.py')
    strategy=runner.strategy_module()
    return strategy,runner.catalog,runner.prepare


def hashes():
    """
    機能: 第2段階の売買コードと参照する第1段階を指紋化する。
    引数: なし。
    返り値: dict[str,str]。
    """
    paths=list(WORK.glob('*.py'))+list(PHASE.glob('*.py'))
    return {str(p.relative_to(ROOT)):digest(p) for p in sorted(paths)}


def check_profit(result,config):
    """
    機能: 全返済ごとの判定が、部分返済を含む実注文料金後の親組額と一致するか調べる。
    引数: result/config (dict)。
    返り値: None。
    """
    events=result['profit_reentry_events']
    assert len(events)==len(result['cycles'])
    for event,cycle in zip(events,result['cycles']):
        row,cid,yen,allowed=event[:4]
        assert row==cycle[2] and cid==cycle[0]
        orders=result['orders'][result['orders'][:,2]==cid]
        gross=-math.fsum(o[3]*o[4]*o[5]*1000 for o in orders)
        fees=sum(int(o[4]*418)//10 for o in orders)
        expected=gross-fees
        assert abs(yen-expected)<1e-6
        assert bool(allowed)==bool(config.get('profit_fast_enabled',True) and expected>1e-7)
    reset_rows=set(result['reentry_events'][:,0].astype(int))
    positive=set(events[events[:,3]==1,0].astype(int))
    assert reset_rows<=positive


def synthetic(strategy,configs):
    """
    機能: 利益・損失・料後ゼロ、最後の脚と親組の逆符号、静観の境界を検査する。
    引数: strategy (module)、configs (dict)。
    返り値: list[dict]の合格証跡。
    """
    strategy.base.integration.reference.initialize()
    records=[]
    for clock,cooldown in (('P0',0),('P1',60)):
        for reflected in (False,True):
            # ----------------------------------------
            # 黒字後は次の原本観測以降に新準備。非黒字は通常影の自然終了＋300秒。
            offsets=[0,1,2,3,3+cooldown,4+cooldown,5+cooldown,6+cooldown]
            ready,feature=fixture([100,101,106,104,100,101,106,104],offsets,reflected=reflected)
            c=configs['T2_'+clock]
            result,_=strategy.play(c,ready,feature,observed=True)
            check_source_order(result);check_profit(result,c)
            assert result['orders'][result['orders'][:,7]==1,0].tolist()==[1,5]
            assert result['prepare_events'][:,1].tolist()==[0,4]
            assert result['reentry_events'][0,2]==ready['time_s'][3]+cooldown
            records.append(dict(検査='黒字親組後だけ0/60秒で次観測から新準備',条件=c['id'],ショート=reflected,合格=True))
            ready,feature=fixture([100,101,98,100,101,97,100,100,101,106,104],
                [0,1,2,3,60,100,399,400,401,402,403],reflected=reflected)
            result,_=strategy.play(c,ready,feature,observed=True)
            check_source_order(result);check_profit(result,c)
            assert result['orders'][result['orders'][:,7]==1,0].tolist()==[1,8]
            assert result['prepare_events'][:,1].tolist()==[0,7]
            assert result['profit_reentry_events'][0,3]==0
            assert 2 not in result['reentry_events'][:,0]
            records.append(dict(検査='赤字後は元通常影の100秒時点自然終了＋300秒を待つ',条件=c['id'],ショート=reflected,合格=True))
            # ----------------------------------------
            # 金額ゼロ境界は、人工現在値で往復418円ちょうどを回収する。
            for price,expected in ((101.,False),(101.0836,False),(101.1,True)):
                ready,feature=fixture([100,101,price,100,101], [0,1,5,1806,1807],
                    reflected=reflected,anchor='2026-10-02T22:14:55+09:00')
                result,_=strategy.play(c,ready,feature,observed=True)
                check_source_order(result);check_profit(result,c)
                assert bool(result['profit_reentry_events'][0,3])==expected
                count=int(np.sum(result['orders'][:,7]))
                assert count==(2 if expected else 1)
                records.append(dict(検査='U全返済も親組料金後の負/ゼロ/正で区別',条件=c['id'],
                    ショート=reflected,人工返済値=price,早期許可=expected,合格=True))
            # ----------------------------------------
            # 最後の脚の損益では判定しない。
            ready,feature=fixture([100,101,109,97,100,101],[0,1,2,3,3+cooldown,4+cooldown],reflected=reflected)
            c0=configs['T0_'+clock]
            result,_=strategy.play(c0,ready,feature,observed=True)
            check_profit(result,c0)
            assert result['trades'][1,10]<0 and result['profit_reentry_events'][0,2]>0
            assert result['orders'][result['orders'][:,7]==1,0].tolist()==[1,5]
            records.append(dict(検査='最後の返済脚が赤字でも親組3582円黒字なら対象',条件=c0['id'],ショート=reflected,合格=True))
            ready,feature=fixture([100,101,107,100,99,102,100,101],[0,1,2,3,4,5,1806,1807],
                reflected=reflected,anchor='2026-10-02T22:14:55+09:00',
                source=[-1,-1,-1,3,3,3,3,3],bad=[0,0,0,-1,-1,-1,-1,-1])
            result,_=strategy.play(c0,ready,feature,observed=True)
            check_profit(result,c0)
            assert result['trades'][-1,10]>0 and result['profit_reentry_events'][0,2]<0
            assert result['orders'][result['orders'][:,7]==1,0].tolist()==[1]
            records.append(dict(検査='最後の返済脚が黒字でも親組1418円赤字なら対象外',条件=c0['id'],ショート=reflected,合格=True))
    return records


def prefix(strategy,configs,prepare):
    """
    機能: 日夜両商品・両モデルで親組損益判定の前後を切断し、過去を一致させる。
    引数: strategy/prepare (module)、configs (dict)。
    返り値: list[dict]の合格証跡。
    """
    inputs,signals,_=prepare.load_inputs(verify=False)
    features=strategy.initialize(inputs,signals)
    keys=[(session,symbol) for session in ('2026-10-05_Day','2026-10-09_Night') for symbol in ('TOPIX','NK225')]
    records=[]
    first_catalog=module('wave86_phase2_audit_first_catalog',WORK/'catalog.py')
    original_configs={c['id']:c for c in first_catalog.catalog()}
    for key in keys:
        ready,feature=inputs[key],features[key]
        n=len(ready['last'])
        for observed in (False,True):
            for ident in ('T3_P1','T4_P0'):
                config=configs[ident]
                disabled,_=strategy.play(dict(config,profit_fast_enabled=False),ready,feature,observed=observed)
                original,_=strategy.old.play(original_configs[config['exit_id']+'_S'],ready,feature,observed=observed)
                # ----------------------------------------
                # 架空の影組番号は比較せず、実入口順へ正規化した売買と時価を比較する。
                mappings=[]
                for data in (disabled,original):
                    entries=data['orders'][data['orders'][:,7]==1]
                    mappings.append({int(o[2]):j for j,o in enumerate(entries)})
                for name,col in (('orders',2),('trades',0),('cycles',0)):
                    arrays=[]
                    for data,mapping in zip((disabled,original),mappings):
                        array=data[name].copy()
                        array[:,col]=[mapping[int(v)] for v in array[:,col]]
                        arrays.append(array)
                    np.testing.assert_array_equal(*arrays,err_msg='早期無効化の実玉 '+name)
                np.testing.assert_array_equal(disabled['curve'][:,:7],original['curve'][:,:7],err_msg='早期無効化の全行時価')
                np.testing.assert_array_equal(disabled['normal_shadow']['plans'],original['normal_shadow']['plans'],err_msg='元の通常影を維持')
                full,_=strategy.play(config,ready,feature,observed=observed)
                verify_original_gate(strategy,full,ready,feature)
                cuts={int(n*.29),int(n*.71)}
                for name,col in (('profit_reentry_events',0),('reentry_events',1),('dynamic_events',0),('time_events',0)):
                    for event in full[name][:2]:
                        i=int(event[col]);cuts.update((max(2,i),min(n-1,i+1),min(n-1,i+2)))
                checks=0
                for count in sorted(cuts):
                    part,_=strategy.play(config,clip(ready,count,n),clip(feature,count,n),observed=observed)
                    checks+=compare_prefix(full,part,count)
                    a,b=full['profit_reentry_events'],part['profit_reentry_events']
                    np.testing.assert_array_equal(a[a[:,0]<count],b[b[:,0]<count])
                    checks+=1
                records.append(dict(セッション=key[0],銘柄=key[1],条件=ident,観測約定=observed,
                    切断数=len(cuts),配列照合数=checks,親組判定と過去注文一致=True,
                    早期無効化時の実玉と通常影は元Sと一致=True))
                print('P切断',key,ident,observed,len(cuts),'一致',flush=True)
    return records


def main():
    """
    機能: 人工境界又は実原板の未来切断を実行して監査証跡を保存する。
    引数: --prefix (bool) は原板切断を指定する。
    返り値: None。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prefix',action='store_true');args=parser.parse_args()
    strategy,catalog,prepare=load()
    configs={c['id']:c for c in catalog.catalog()}
    before=hashes()
    records=prefix(strategy,configs,prepare) if args.prefix else synthetic(strategy,configs)
    assert before==hashes()
    name='利確後だけ再参加の未来切断.json' if args.prefix else '利確後だけ再参加の人工境界.json'
    save(name,dict(全合格=True,検査=records,実装SHA256=before,監査器SHA256=digest(__import__('pathlib').Path(__file__))))
    print(name,len(records),'検査合格',flush=True)


if __name__=='__main__':
    main()
