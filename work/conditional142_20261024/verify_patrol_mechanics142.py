"""第二巡登録後だけ、巡回12政策の未来不変・上下対称と併用会計を検査する。"""

import argparse
import pickle
import traceback
from pathlib import Path
import numpy as np
import verify_mechanics142 as base


HERE,ROOT,OLD=base.HERE,base.ROOT,base.OLD
SCENES=('2026-10-23_Day','2026-10-22_Night')


def registration(path):
    """
    機能: 指定された第二巡登録と計画・全実装の内容指紋を確認する。
    引数: path(Path)は明示する登録JSON。
    返り値: tuple[dict,dict]は確認済み登録と計画。未登録なら金融再生前に失敗する。
    """
    if not path.exists():raise SystemExit('第二巡未登録のため実データ検査は実行しません。')
    record=base.read(path);assert record['returncode']==0
    plan_path=ROOT/record['plan']['path'];assert base.digest(plan_path)==record['plan']['sha256']
    plan=base.read(plan_path);assert record['id']==plan['id']
    assert len(plan['configs']['patrol'])==12
    for source,sha in plan['spec']['implementation'].items():assert base.digest(ROOT/source)==sha,source
    return record,plan


def reversals(orders):
    """
    機能: 巡回単体の反対方向新規が前親の最終返済より後の原行にあることを確認する。
    引数: orders(ndarray)は次正常板約定の十列列。
    返り値: intは確認した逆方向再参加数。同原行の反転約定は失敗する。
    """
    parents={}
    for o in orders:
        pid=int(o[2])
        if pid not in parents:
            assert o[7]==1.
            parents[pid]=dict(first=int(o[0]),last=int(o[0]),side=int(o[3]))
        if o[7]==0.:parents[pid]['last']=int(o[0])
    ordered=sorted(parents.values(),key=lambda p:p['first']);count=0
    for previous,current in zip(ordered,ordered[1:]):
        assert current['first']>previous['last']
        if current['side']!=previous['side']:count+=1
    return count


def mechanics(registry):
    """
    機能: 昼夜各一場×二市場×12政策の注文・判断履歴・時価を機械的に確認する。
    引数: registry(Path)は第二巡登録。
    返り値: None。条件探索・実運用・利益の採否を行わない。
    """
    record,plan=registration(registry)
    import run142
    import patrol_features142 as features
    import patrol_trader142 as trader
    manifest={x['session']:x for x in base.read(OLD/'inputs/input_manifest.json')['packets']}
    report=dict(登録=record,条件探索=0,results=[],status='実行中',script_sha256=base.digest(Path(__file__)))
    output=HERE/'巡回売買の実データ独立検査142.json'
    try:
        for scene in SCENES:
            item=manifest[scene];path=ROOT/item['path'];assert base.digest(path)==item['sha256']
            packet=pickle.loads(path.read_bytes());standard,_,_,_=run142.prepared(packet)
            data=features.prepare(packet,standard)
            centers={s:float((d['quotes']['bid'][0]+d['quotes']['ask'][0])*.5) for s,d in data.items()}
            for symbol in ('NK225','TOPIX'):
                source=data[symbol];peer='TOPIX' if symbol=='NK225' else 'NK225'
                opposite=base.mirror(source,centers[symbol],centers[peer])
                np.testing.assert_array_equal(source['features'][:,30:],opposite['features'][:,30:])
                for config in plan['configs']['patrol']:
                    orders,curve,trace=trader.replay(source,config)
                    assert len(orders)>0,(scene,symbol,config['id'],'無注文なので未来検査の実質がない')
                    cutoff=max(len(source['features'])//2,int(orders[0,0])+1)
                    assert cutoff<len(source['features'])
                    changed=base.future_only(source,opposite,cutoff)
                    future,fc,ft=trader.replay(changed,config)
                    mirrored,mc,mt=trader.replay(opposite,config)
                    prefix=orders[orders[:,0]<cutoff];assert len(prefix)>0
                    np.testing.assert_array_equal(prefix,future[future[:,0]<cutoff])
                    np.testing.assert_array_equal(trace[trace[:,0]<cutoff],ft[ft[:,0]<cutoff])
                    np.testing.assert_allclose(curve[:cutoff],fc[:cutoff],rtol=0,atol=1e-8)
                    np.testing.assert_array_equal(orders[:,[0,1,2,4,6,7,8,9]],mirrored[:,[0,1,2,4,6,7,8,9]])
                    np.testing.assert_array_equal(orders[:,3],-mirrored[:,3])
                    np.testing.assert_allclose(orders[:,5],2.*centers[symbol]-mirrored[:,5],rtol=0,atol=1e-8)
                    np.testing.assert_array_equal(trace[:,[0,1,3,4,5,6]],mt[:,[0,1,3,4,5,6]])
                    np.testing.assert_array_equal(trace[:,2],-mt[:,2])
                    np.testing.assert_allclose(trace[:,7:],mt[:,7:],rtol=0,atol=1e-8)
                    np.testing.assert_allclose(curve,mc,rtol=0,atol=1e-6)
                    for o,d,c in ((orders,source,curve),(future,changed,fc),(mirrored,opposite,mc)):
                        cash=base.audit_orders(o,d,5)
                        np.testing.assert_allclose(cash,c[-1],rtol=0,atol=1e-6)
                        reversals(o)
                    report['results'].append(dict(session=scene,symbol=symbol,method=config['id'],orders=len(orders),
                        prefix_orders=len(prefix),cutoff=cutoff,reversals=reversals(orders),
                        mirror=True,future=True,quantity_fee_nextquote_flat=True,same_row_reversal=0))
                    print(scene,symbol,config['id'],'巡回独立検査合格',flush=True)
        report['status']='全件合格';report['cases']=len(report['results'])
        report['限界']='原価格時計・代理BBO模型の機械検査。実mini約定・受信時計・未見収益性は未証明。'
        base.save(output,report)
    except Exception:
        report['status']='失敗';report['error']=traceback.format_exc();base.save(output,report)
        raise


def saved(registry,result_file):
    """
    機能: 第二巡全50場の保存列を、親識別子・次正常気配・費用・上限枚数から独立会計する。
    引数: registry/result_file(Path)は登録と第二巡結果JSON。
    返り値: None。保存済み注文だけを検査し、新しい売買判断をしない。
    """
    record,_=registration(registry);result=base.read(result_file)
    stats={(x['session'],x['symbol'],x['method']):x for x in result['rows']}
    packets={x['session']:x for f in (OLD/'known_manifest140.json',OLD/'inputs/input_manifest.json') for x in base.read(f)['packets']}
    cache={(x['session'],x['symbol']):x for x in result['cache']}
    checked=[]
    for scene in sorted(packets):
        item=packets[scene];path=Path(item['path']);path=path if path.is_absolute() else ROOT/path
        assert base.digest(path)==item['sha256'];packet=pickle.loads(path.read_bytes())
        for symbol in ('NK225','TOPIX'):
            key=scene,symbol;ref=cache[key];path=ROOT/ref['path'];assert base.digest(path)==ref['sha256']
            data=dict(ready=packet['inputs'][key],quotes=packet['quotes'][key])
            with np.load(path) as z:
                for method in z.files:
                    orders=z[method];standalone=method.startswith('P')
                    cash=base.audit_orders(orders,data,5 if standalone else 10)
                    expected=stats[scene,symbol,method]['net']
                    assert abs(cash-expected)<1e-6,(scene,symbol,method,cash,expected)
                    if standalone:reversals(orders)
                    checked.append(dict(session=scene,symbol=symbol,method=method,orders=len(orders),会計一致=True))
        print(scene,'第二巡保存会計の独立検査合格',flush=True)
    base.save(HERE/'第二巡保存全注文の独立検査142.json',dict(登録=record,新金融再生=0,status='全件合格',
             件数=len(checked),注文数=sum(x['orders'] for x in checked),results=checked))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=('mechanics','saved'),nargs='?',default='mechanics')
    parser.add_argument('--registration',type=Path,default=HERE/'第二巡登録142.json')
    parser.add_argument('--results',type=Path,default=HERE/'第二巡結果142.json')
    arguments=parser.parse_args()
    if arguments.stage=='saved':saved(arguments.registration,arguments.results)
    else:mechanics(arguments.registration)
