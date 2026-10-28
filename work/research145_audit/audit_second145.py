"""第二段階と固定組合せの保存約定を独立会計する。金融再生は呼ばない。"""

import json
from pathlib import Path
import pickle
import numpy as np
from audit_results145 import verify, summary, load, ROOT, HERE, ENGINE


def main():
    """
    機能: 追加2条件・役割8条件・固定組合せ3条件の保存650会計を検算する。
    引数: なし。
    返り値: None。既存約定列だけを読み、選択や市場判断を再生成しない。
    """
    roles=ROOT/'work/research145_roles'
    combination=ROOT/'work/research145_report'
    extra=load(roles/'ドテン確認の全場結果145.json')
    selected=load(roles/'役割分離の全場結果145.json')
    combined=load(combination/'組合せ結果145.json')
    index={(row['session'],row['method']):row for row in extra['rows']+selected['rows']+combined['rows']}
    scenes=sorted({scene for scene,_ in index})
    assert len(index)==650 and len(scenes)==50
    records=[]
    for scene in scenes:
        with (ENGINE/'cache'/f'{scene}.pkl').open('rb') as stream:
            _,data,*_=pickle.load(stream)
        with np.load(roles/'new_addon'/f'{scene}.npz') as va, np.load(roles/'orders'/f'{scene}.npz') as da, np.load(combination/'combined_orders'/f'{scene}.npz') as ca:
            assert np.array_equal(va['V16'],va['V17'])
            assert np.array_equal(da['D07'],da['D08'])
            methods=sorted(method for session,method in index if session==scene)
            for method in methods:
                orders=(va if method.startswith('V') else da if method.startswith('D') else ca)[method]
                records.append(verify(orders,data['ready'],data['quotes'],index[scene,method]))
        print(scene+' 第二段階の独立会計一致',flush=True)
    methods=sorted({row['method'] for row in records})
    groups=[]
    for method in methods:
        for kind in ('All','Day','Night'):
            chosen=[row for row in records if row['method']==method and (kind=='All' or row['session'].endswith('_'+kind))]
            groups.append(dict(method=method,kind=kind,**summary(chosen)))
    result=dict(financial_replays=0,all_passed=True,accounts=len(records),orders=sum(row['orders'] for row in records),
                V16_V17_orders_exact=True,D07_D08_orders_exact=True,
                rows=records,summaries=groups,
                limitation='旧基本源の場末判断例外を継承するため、境界到達後の次正常気配への差額を別集計した。')
    (HERE/'第二段階と組合せの独立監査145.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
