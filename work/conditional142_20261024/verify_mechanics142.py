"""登録後だけ旧同値・未来不変・上下反転と保存注文の会計を独立確認する。"""

import hashlib
import json
import pickle
import sys
import traceback
from pathlib import Path
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT/'work/raw_diagnosis141_20261024'
OLD = ROOT/'work/aggressive140_20261024'
SCENES = ('2026-10-23_Day','2026-10-22_Night')


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)は入力位置。
    返り値: dict/listは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    """
    機能: 保存資料の内容指紋を計算する。
    引数: path(Path)はファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, report):
    """
    機能: 独立検査の結果を新規資料へ保存する。
    引数: path(Path)、report(dict)は保存先と検査記録。
    返り値: None。金融結果と登録資料は変更しない。
    """
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def registration():
    """
    機能: 登録・計画・凍結実装のSHAを確認し、未登録なら実入力再生前に止める。
    引数: なし。
    返り値: tuple[dict,dict]は登録と計画。
    """
    path = HERE/'登録142.json'
    if not path.exists():
        raise SystemExit('登録142.json未作成のため実データ検査は実行しません。')
    record=read(path)
    assert record['returncode']==0
    plan_path=ROOT/record['plan']['path']
    assert digest(plan_path)==record['plan']['sha256']
    plan=read(plan_path)
    assert record['id']==plan['id']
    for source,sha in plan['spec']['implementation'].items():
        assert digest(ROOT/source)==sha,source
    return record,plan


def mirror(data, center, peer_center):
    """
    機能: 価格水準と30列特徴を上下反転し、時計・R・効率は保持する。
    引数: data(dict)、center/peer_center(float)は入力と自他の中心。
    返り値: dictは元資料を変更しない鏡像。20分差28/29も符号反転する。
    """
    result=dict(data,ready=dict(data['ready']),quotes=dict(data['quotes']))
    result['quotes']['bid']=2.*center-data['quotes']['ask']
    result['quotes']['ask']=2.*center-data['quotes']['bid']
    a=data['features'];b=a.copy()
    b[:,0],b[:,1]=2.*center-a[:,1],2.*center-a[:,0]
    for col in (5,6,7,10):b[:,col]=2.*center-a[:,col]
    for col in (17,19):b[:,col]=2.*peer_center-a[:,col]
    for col in (3,4,12,13,14,15,20,21,24,25,26,27,28,29):b[:,col]=-a[:,col]
    result['features']=b
    return result


def future_only(data, reflected, cutoff):
    """
    機能: 変更開始原行以後の気配と特徴だけを鏡像へ差し替える。
    引数: data/reflected(dict)、cutoff(int)は元入力・鏡像・変更開始行。
    返り値: dictは前半を保持した人工反証入力。
    """
    result=dict(data,quotes=dict(data['quotes']))
    for name in ('bid','ask'):
        result['quotes'][name]=data['quotes'][name].copy()
        result['quotes'][name][cutoff:]=reflected['quotes'][name][cutoff:]
    result['features']=data['features'].copy()
    result['features'][cutoff:]=reflected['features'][cutoff:]
    return result


def audit_orders(orders, data, cap):
    """
    機能: 次正常板・売買気配・注文別費用・片方向枚数・終端返済を独立会計する。
    引数: orders(ndarray)、data(dict)、cap(int)は注文・入力・片方向上限。
    返り値: floatは手数料後の最終現金。板の約定可能数量や受信時計は証明しない。
    """
    q=data['quotes'];symbol=data['ready']['symbol']
    fee,mult=(385,100.) if symbol=='NK225' else (418,1000.)
    valid=q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0.)&(q['bid']<q['ask'])
    normal=np.flatnonzero(valid);held={};long=short=0;cash=0.
    assert orders.ndim==2 and orders.shape[1]==10 and np.isfinite(orders).all()
    assert np.all(np.diff(orders[:,0])>=0)
    for o in orders:
        row,source,parent,side,qty=map(int,o[:5]);new,uid,cost=map(int,o[7:])
        assert side in (-1,1) and qty>0 and new in (0,1)
        assert row==int(normal[np.searchsorted(normal,source,side='right')])
        assert abs(o[5]-(q['ask'][row] if side>0 else q['bid'][row]))<1e-8
        assert cost==qty*fee//10
        key=parent,uid
        if new:
            assert key not in held
            held[key]=[side,qty]
            if side>0:long+=qty
            else:short+=qty
        else:
            assert key in held and held[key][0]==-side and held[key][1]>=qty
            held[key][1]-=qty
            if side<0:long-=qty
            else:short-=qty
        assert 0<=long<=cap and 0<=short<=cap
        cash-=side*qty*o[5]*mult+cost
    assert long==short==0 and all(qty==0 for side,qty in held.values())
    return float(cash)


def mechanics():
    """
    機能: 日中・夜間各一場の二市場で旧同値と全14条件の因果・対称性を検査する。
    引数: なし。
    返り値: None。登録後の機械検査であり、条件探索や新しい採否には使わない。
    """
    record,plan=registration()
    sys.path.insert(0,str(PREVIOUS))
    import active141_v3 as original
    import active_trader142 as revised
    import run142 as runner
    packets={x['session']:x for x in read(OLD/'inputs/input_manifest.json')['packets']}
    result=dict(目的='登録後の独立機械検査。有効性の新証拠ではない。',登録=record,
                script_sha256=digest(Path(__file__)),results=[],status='実行中',条件探索=0)
    output=HERE/'実データ機械整合の独立検査142.json'
    try:
        for scene in SCENES:
            item=packets[scene];path=ROOT/item['path'];assert digest(path)==item['sha256']
            packet=pickle.loads(path.read_bytes())
            prepared,_,_,_=runner.prepared(packet)
            centers={s:float((d['quotes']['bid'][0]+d['quotes']['ask'][0])*.5) for s,d in prepared.items()}
            for symbol in ('NK225','TOPIX'):
                data=prepared[symbol];peer='TOPIX' if symbol=='NK225' else 'NK225'
                template=original.configurations()[35 if symbol=='NK225' else 32]
                before,bcurve=original.replay(data,template)
                unchanged,ucurve,utrace=revised.replay(data,template)
                np.testing.assert_array_equal(before,unchanged)
                np.testing.assert_allclose(bcurve,ucurve,rtol=0,atol=1e-8)
                assert len(utrace)==0
                cash=audit_orders(unchanged,data,template['maximum'])
                np.testing.assert_allclose(cash,ucurve[-1],rtol=0,atol=1e-6)
                result['results'].append(dict(session=scene,symbol=symbol,method='旧同値',orders=len(before),passed=True))
                opposite=mirror(data,centers[symbol],centers[peer])
                cutoff=len(data['features'])//2
                altered=future_only(data,opposite,cutoff)
                for case in plan['configs']['active']:
                    config=dict(template,**case['changes'])
                    orders,curve,trace=revised.replay(data,config)
                    future,fcurve,ftrace=revised.replay(altered,config)
                    reflected,rcurve,rtrace=revised.replay(opposite,config)
                    np.testing.assert_array_equal(orders[orders[:,0]<cutoff],future[future[:,0]<cutoff])
                    np.testing.assert_array_equal(trace[trace[:,0]<cutoff],ftrace[ftrace[:,0]<cutoff])
                    np.testing.assert_allclose(curve[:cutoff],fcurve[:cutoff],rtol=0,atol=1e-8)
                    np.testing.assert_array_equal(orders[:,[0,1,2,4,6,7,8,9]],reflected[:,[0,1,2,4,6,7,8,9]])
                    np.testing.assert_array_equal(orders[:,3],-reflected[:,3])
                    np.testing.assert_allclose(orders[:,5],2.*centers[symbol]-reflected[:,5],rtol=0,atol=1e-8)
                    np.testing.assert_array_equal(trace[:,[0,1,3,4,5,8]],rtrace[:,[0,1,3,4,5,8]])
                    np.testing.assert_array_equal(trace[:,2],-rtrace[:,2])
                    np.testing.assert_allclose(trace[:,6:8],rtrace[:,6:8],rtol=0,atol=1e-8)
                    np.testing.assert_allclose(curve,rcurve,rtol=0,atol=1e-6)
                    for rows,input_data,values in ((orders,data,curve),(future,altered,fcurve),(reflected,opposite,rcurve)):
                        cash=audit_orders(rows,input_data,template['maximum'])
                        np.testing.assert_allclose(cash,values[-1],rtol=0,atol=1e-6)
                    result['results'].append(dict(session=scene,symbol=symbol,method=case['id'],orders=len(orders),
                        prefix_orders=int(np.count_nonzero(orders[:,0]<cutoff)),trace_rows=len(trace),
                        future_unchanged=True,mirror_equal=True,quantity_fee_nextquote_flat=True))
                    print(scene,symbol,case['id'],'独立機械検査合格',flush=True)
        result['status']='全件合格'
        result['case_count']=len(result['results'])
        result['限界']='価格時計と代理気配模型内の検査。実miniの約定品質、受信時計、未見収益性の証明ではない。'
        save(output,result)
    except Exception:
        result['status']='失敗';result['error']=traceback.format_exc();save(output,result)
        raise


def saved_orders():
    """
    機能: 完成した全50場の保存注文だけを再会計し、数量・費用・残玉を確認する。
    引数: なし。
    返り値: None。新しい売買判断を一切実行しない。
    """
    record,_=registration()
    saved=read(HERE/'結果142.json')
    rows={(x['symbol'],x['session'],x['method']):x for x in saved['rows']}
    packets={x['session']:x for f in (OLD/'known_manifest140.json',OLD/'inputs/input_manifest.json') for x in read(f)['packets']}
    cache={(x['session'],x['symbol']):x for x in saved['cache']}
    results=[]
    for scene in sorted(packets):
        item=packets[scene];path=Path(item['path']);path=path if path.is_absolute() else ROOT/path
        assert digest(path)==item['sha256'];packet=pickle.loads(path.read_bytes())
        for symbol in ('NK225','TOPIX'):
            key=scene,symbol;ref=cache[key];target=ROOT/ref['path'];assert digest(target)==ref['sha256']
            data=dict(ready=packet['inputs'][key],quotes=packet['quotes'][key])
            with np.load(target) as z:
                for method in z.files:
                    orders=z[method]
                    cash=audit_orders(orders,data,10)
                    expected=rows[symbol,scene,method]['net']
                    assert abs(cash-expected)<1e-6,(symbol,scene,method,cash,expected)
                    results.append(dict(session=scene,symbol=symbol,method=method,orders=len(orders),会計一致=True))
        print(scene,'保存注文の独立会計合格',flush=True)
    save(HERE/'保存全注文の独立検査142.json',dict(登録=record,新金融再生=0,results=results,
         件数=len(results),注文数=sum(x['orders'] for x in results),status='全件合格'))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='saved':saved_orders()
    else:mechanics()
