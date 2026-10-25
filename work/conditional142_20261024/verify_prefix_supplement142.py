"""最初の半分に約定がなかった5条件だけ、約定後に未来改変して再確認する。"""

import pickle
import numpy as np
import verify_mechanics142 as audit


def main():
    """
    機能: 前半無約定で空集合だった検査を、最初の実約定を含むprefixへ補強する。
    引数: なし。
    返り値: None。登録済み条件を変えず、切断原行だけを変更した機械検査を保存する。
    """
    record,plan=audit.registration()
    import run142 as runner
    import active_trader142 as active
    original=audit.read(audit.HERE/'実データ機械整合の独立検査142.json')
    targets=[x for x in original['results'] if x['method']!='旧同値' and x['prefix_orders']==0]
    inputs={x['session']:x for x in audit.read(audit.OLD/'inputs/input_manifest.json')['packets']}
    cases={x['id']:x for x in plan['configs']['active']}
    result=[]
    for scene in sorted({x['session'] for x in targets}):
        item=inputs[scene];path=audit.ROOT/item['path'];assert audit.digest(path)==item['sha256']
        data,_,_,_=runner.prepared(pickle.loads(path.read_bytes()))
        centers={s:float((d['quotes']['bid'][0]+d['quotes']['ask'][0])*.5) for s,d in data.items()}
        for target in [x for x in targets if x['session']==scene]:
            symbol,method=target['symbol'],target['method'];source=data[symbol]
            template=active.configurations()[35 if symbol=='NK225' else 32]
            config=dict(template,**cases[method]['changes'])
            orders,curve,trace=active.replay(source,config)
            assert len(orders)>0
            cutoff=int(orders[0,0])+1
            assert cutoff<len(source['features'])
            reflected=audit.mirror(source,centers[symbol],centers['TOPIX' if symbol=='NK225' else 'NK225'])
            changed=audit.future_only(source,reflected,cutoff)
            other,ocurve,otrace=active.replay(changed,config)
            before=orders[orders[:,0]<cutoff]
            assert len(before)>0
            np.testing.assert_array_equal(before,other[other[:,0]<cutoff])
            np.testing.assert_array_equal(trace[trace[:,0]<cutoff],otrace[otrace[:,0]<cutoff])
            np.testing.assert_allclose(curve[:cutoff],ocurve[:cutoff],rtol=0,atol=1e-8)
            audit.audit_orders(other,changed,template['maximum'])
            result.append(dict(session=scene,symbol=symbol,method=method,cutoff=cutoff,
                               prefix_orders=len(before),passed=True))
    audit.save(audit.HERE/'未来prefix不足の補足検査142.json',dict(登録=record,条件変更なし=True,results=result,全件合格=True))
    print('補足未来検査合格',len(result),'条件')


if __name__=='__main__':
    main()
