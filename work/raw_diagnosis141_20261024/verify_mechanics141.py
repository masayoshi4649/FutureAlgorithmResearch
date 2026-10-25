"""登録済み条件の旧実装同値・未来改変・上下反転を独立に検査する。"""

import hashlib
import json
import pickle
import sys
import traceback
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=ROOT/'work/aggressive140_20261024'
SCENE='2026-10-23_Day'
OUTPUT=HERE/'実データ機械整合の独立検査141.json'
sys.path.insert(0,str(OLD))


def read(path):
    """
    機能: 保存済みのJSONを読む。
    引数: path(Path)は資料位置。
    返り値: dict/listは保存内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    """
    機能: 読み取る入力・実装の指紋を計算する。
    引数: path(Path)はファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(report):
    """
    機能: 独立検査の結果を新しいJSONへ記録する。
    引数: report(dict)は機械整合の記録。成績改善の証拠とはしない。
    返り値: None。既存の金融結果・登録資料を変更しない。
    """
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def mirror(data, center, peer_center):
    """
    機能: 自他の価格水準を鏡像化し、方向と板圧力だけ符号反転する。
    引数: data(dict)、center/peer_center(float)は原資料と自他の反転中心。
    返り値: dictは原資料を変更しない人工鏡像。R・効率・時計・正常板資格は不変。
    """
    result=dict(data)
    result['ready']=dict(data['ready'])
    result['quotes']=dict(data['quotes'])
    result['quotes']['bid']=2.*center-np.asarray(data['quotes']['ask'])
    result['quotes']['ask']=2.*center-np.asarray(data['quotes']['bid'])
    a=np.asarray(data['features']);b=a.copy()
    b[:,0],b[:,1]=2.*center-a[:,1],2.*center-a[:,0]
    for column in (5,6,7,10):b[:,column]=2.*center-a[:,column]
    for column in (17,19):b[:,column]=2.*peer_center-a[:,column]
    for column in (3,4,12,13,14,15,20,21,24,25,26,27):b[:,column]=-a[:,column]
    result['features']=b
    return result


def future_only(data, mirrored, cutoff):
    """
    機能: 後半の気配と特徴だけを大きく改変した人工入力を作る。
    引数: data/mirrored(dict)、cutoff(int)は原資料・鏡像・変更開始原行。
    返り値: dictは前半とreadyを原資料のまま保持した入力。
    """
    result=dict(data);result['quotes']=dict(data['quotes'])
    for name in ('bid','ask'):
        result['quotes'][name]=np.asarray(data['quotes'][name]).copy()
        result['quotes'][name][cutoff:]=mirrored['quotes'][name][cutoff:]
    result['features']=np.asarray(data['features']).copy()
    result['features'][cutoff:]=mirrored['features'][cutoff:]
    return result


def check_orders(orders, data, maximum):
    """
    機能: 約定が次正常原行であり、数量・手数料・最終残玉が整合することを確認する。
    引数: orders(ndarray)、data(dict)、maximum(int)は保存約定模型と上限。
    返り値: intは検査した注文数。金融的な有効性や約定可能枚数を証明しない。
    """
    q=data['quotes'];fee=385 if data['ready']['symbol']=='NK225' else 418
    good=q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0.)&(q['ask']>q['bid'])
    normal=np.flatnonzero(good);held={};total=0
    assert np.isfinite(orders).all()
    for order in orders:
        fill,source,parent,side,qty=map(int,order[:5]);new,uid,cost=map(int,order[7:])
        assert fill>source
        assert fill==int(normal[np.searchsorted(normal,source,side='right')]),(fill,source)
        expected=q['ask'][fill] if side>0 else q['bid'][fill]
        assert abs(order[5]-expected)<1.e-8
        assert cost==qty*fee//10
        key=parent,uid
        held[key]=held.get(key,0)+(qty if new else -qty)
        total+=qty if new else -qty
        assert held[key]>=0 and 0<=total<=maximum
    assert total==0 and all(value==0 for value in held.values())
    return len(orders)


def main():
    """
    機能: 登録確認後だけ、一場二銘柄の同値と12条件の因果・対称性を検査する。
    引数: なし。
    返り値: None。未登録なら再生前に停止し、条件探索や比較損益の選択は行わない。
    """
    registration_path=HERE/'登録141_v2.json'
    if not registration_path.exists():
        raise SystemExit('登録141_v2.json未作成のため、実データ検査は実行しません。')
    registration=read(registration_path)
    assert registration['returncode']==0
    plan_path=ROOT/registration['plan']['path']
    assert digest(plan_path)==registration['plan']['sha256']
    plan=read(plan_path)
    assert plan['id']==registration['id']
    assert '独立検査' in plan['spec']['data']['検査']
    for file in (HERE/'active141.py',HERE/'evidence141_v2.py',OLD/'active140_v2.py'):
        assert digest(file)==plan['spec']['implementation'][file.relative_to(ROOT).as_posix()]
    # ----------------------------------------
    # モジュール読込と実入力再生は登録・実装指紋の確認後に限る。
    import active140_v2 as original
    import active141 as revised
    import evidence141_v2 as evidence
    manifest=read(OLD/'inputs/input_manifest.json')
    item=next(x for x in manifest['packets'] if x['session']==SCENE)
    path=ROOT/item['path'];assert digest(path)==item['sha256']
    packet=pickle.loads(path.read_bytes())
    old_prepared=original.prepare(packet,40)
    new_prepared=revised.prepare(packet,40)
    for symbol in old_prepared:
        np.testing.assert_allclose(old_prepared[symbol]['features'],new_prepared[symbol]['features'],rtol=0,atol=0,equal_nan=True)
    prepared=evidence.attach(packet,old_prepared)
    centers={s:float((d['quotes']['bid'][0]+d['quotes']['ask'][0])*.5) for s,d in prepared.items()}
    report=dict(purpose='登録済み独立機械検査。利益・条件の選択をせず、有効性の新証拠に数えない。',
                session=SCENE,registration=registration,script_sha256=digest(Path(__file__)),
                packet=item,results=[],status='実行中',financial_search=0)
    try:
        for symbol in ('NK225','TOPIX'):
            data=prepared[symbol];peer='TOPIX' if symbol=='NK225' else 'NK225'
            template=original.configurations()[35 if symbol=='NK225' else 32]
            reference,curve=original.replay(data,template)
            no_change,new_curve=revised.replay(data,template)
            np.testing.assert_array_equal(reference,no_change)
            np.testing.assert_allclose(curve,new_curve,rtol=0,atol=1.e-8)
            check_orders(no_change,data,template['maximum'])
            report['results'].append(dict(symbol=symbol,method='修正なし',orders=len(reference),
                                          equal_orders=True,equal_equity=True,equal_features=True))
            reflected=mirror(data,centers[symbol],centers[peer])
            cutoff=len(data['ready']['time_s'])//2
            changed=future_only(data,reflected,cutoff)
            for case in plan['configs']['active']:
                config=dict(template,**case['changes'])
                orders,_=revised.replay(data,config)
                future,_=revised.replay(changed,config)
                opposite,_=revised.replay(reflected,config)
                np.testing.assert_array_equal(orders[orders[:,0]<cutoff],future[future[:,0]<cutoff])
                assert orders.shape==opposite.shape,(symbol,case['id'],orders.shape,opposite.shape)
                stable=[0,1,2,4,6,7,8,9]
                np.testing.assert_array_equal(orders[:,stable],opposite[:,stable])
                np.testing.assert_array_equal(orders[:,3],-opposite[:,3])
                np.testing.assert_allclose(2.*centers[symbol]-orders[:,5],opposite[:,5],rtol=0,atol=1.e-8)
                tested=check_orders(orders,data,template['maximum'])
                check_orders(future,changed,template['maximum']);check_orders(opposite,reflected,template['maximum'])
                report['results'].append(dict(symbol=symbol,method=case['id'],orders=tested,
                    prefix_orders=int(np.count_nonzero(orders[:,0]<cutoff)),cutoff_row=cutoff,
                    cutoff_price_clock=float(data['ready']['time_s'][cutoff]),future_prefix_unchanged=True,
                    mirror_orders_equal=True,mirror_prices_equal=True,next_quote_fee_quantity_flat=True))
                print(symbol,case['id'],'独立機械検査合格',flush=True)
        report['status']='全件合格'
        report['case_count']=len(report['results'])
        report['limitation']='保存価格時計・原行順の模型内の検査。受信時計の正しさ、実mini約定、未見収益性は検査していない。'
        save(report)
    except Exception:
        report['status']='失敗';report['error']=traceback.format_exc();save(report)
        raise


if __name__=='__main__':
    main()
