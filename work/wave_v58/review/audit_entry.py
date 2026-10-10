"""実入口固定の未来ラベル・欠測・各場平均を別に検算する。"""

from collections import defaultdict
from pathlib import Path
import hashlib
import importlib.util
import json
import pickle

import numpy as np


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
OLD=BASE.parent/'wave_v57'
SPEC=importlib.util.spec_from_file_location('entry_diagnosis_audit',BASE/'entry/diagnose_entry.py')
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def close(actual: object, expected: object) -> None:
    """機能: 未測定値を区別して浮動小数の一致を検査する。

    引数: actual/expected(object)。返り値: なし(None)。
    """
    if expected is None:
        assert actual is None
    else:
        np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-10)


def main() -> None:
    """機能: 全固定時点ラベルと集計を再構成し、返済情報の不使用を検査する。

    引数: なし。返り値: なし(None)。既存の診断値は変更しない。
    """
    result=json.loads((OLD/'売買結果.json').read_text(encoding='utf8'))
    frames=pickle.loads((OLD/'features.pkl').read_bytes())
    inputs=pickle.loads((BASE.parent/'wave_v55/clean_inputs.pkl').read_bytes())
    labels=pickle.loads((BASE/'entry/入口別将来診断ラベル.pkl').read_bytes())
    report=json.loads((BASE/'entry/入口固定時点の診断.json').read_text(encoding='utf8'))
    entries={}
    for method in result['methods']:
        if not method['primary']:
            continue
        for account in method['accounts']:
            for order in account['orders']:
                if order[4]==1:
                    entries[method['id'],account['session'],account['symbol'],int(order[10])]=order
    grouped=defaultdict(list);seen=set()
    for row in labels:
        key=(row['手法ID'],row['セッション'],row['銘柄'],row['組'])
        identity=(*key,row['観測秒']);assert identity not in seen;seen.add(identity)
        order=entries[key];frame=frames[key[1:3]];ready=inputs[key[1:3]]
        seq,times,mids=frame['seq'],frame['time_s'],frame['mid']
        i=int(np.searchsorted(seq,order[3]));assert seq[i]==order[3]
        assert row['入口原本行']==seq[i] and row['入口時計']==times[i] and row['入口中値']==mids[i]
        assert row['方向']==order[5] and row['観測秒'] in (60,300,900,1800)
        target=times[i]+row['観測秒'];assert row['target時計']==target
        if target>ready['limit']:
            assert not row['有効'] and row['欠測理由']=='場の返済判断時刻を超過' and row['asof原本行'] is None
        else:
            j=int(np.searchsorted(seq,row['asof原本行']))
            assert seq[j]==row['asof原本行'] and times[j]<=target and (j==len(seq)-1 or times[j+1]>target)
            assert row['asof時計']==times[j] and row['古さ秒']==target-times[j]
            assert row['有効']==(target-times[j]<=5)
            target_rows=np.searchsorted(times,target,side='right')-np.searchsorted(times,target,side='left')
            assert row['target同時計の有効原本行数']==target_rows
            if row['有効']:
                delta=order[5]*(mids[j]-mids[i]);assert row['時点中値']==mids[j]
                close(row['方向付き変化呼値'],delta/ready['tick']);close(row['方向付き変化bps'],delta/mids[i]*10000.)
            else:
                assert row['欠測理由']=='約定時計が5秒より古い'
                assert row['方向付き変化呼値'] is None and row['方向付き変化bps'] is None
        grouped[row['手法ID'],row['銘柄'],str(row['観測秒'])].append(row)
    assert len(labels)==len(entries)*4==report['固定将来ラベル行数']
    # ----------------------------------------
    # 入口数加重と場を等分した平均を、それぞれ元ラベルから再集計する。
    aggregates=0
    for method in report['手法別']:
        for symbol,data in method['銘柄別'].items():
            for seconds,expected in data['固定時点別'].items():
                rows=grouped[method['手法ID'],symbol,seconds];valid=[r for r in rows if r['有効']]
                assert expected['入口数']==len(rows) and expected['有効入口数']==len(valid)
                assert expected['欠測数']==len(rows)-len(valid)
                for reason,count in expected['欠測理由別'].items():
                    assert count==sum(r['欠測理由']==reason for r in rows)
                for name,column in (('呼値','方向付き変化呼値'),('bps','方向付き変化bps')):
                    v=np.array([r[column] for r in valid]);a=expected[name]
                    close(a['entry加重平均'],v.mean() if len(v) else None)
                    close(a['entry中央値'],np.median(v) if len(v) else None)
                    assert a['正方向数']==(v>0).sum() and a['逆方向数']==(v<0).sum() and a['同値数']==(v==0).sum()
                    per=[]
                    for session in result['sessions']:
                        sv=np.array([r[column] for r in valid if r['セッション']==session])
                        saved=next(x for x in expected['各場'] if x['セッション']==session)
                        close(saved['平均'+name],sv.mean() if len(sv) else None)
                        assert saved['有効入口数']==len(sv)
                        if len(sv):per.append(sv.mean())
                    close(a['場平均の等ウェイト平均'],np.mean(per) if per else None)
                    assert a['二十三場中で場平均が正の場数']==sum(x>0 for x in per)
                    assert a['二十三場中で場平均が負の場数']==sum(x<0 for x in per)
                    assert a['二十三場中で場平均が同値の場数']==sum(x==0 for x in per)
                    aggregates+=1
    # ----------------------------------------
    # 返済を消し損益を破壊しても、固定入口の未来ラベルが変化しない。
    separation=0
    for method in result['methods']:
        if not method['primary']:continue
        for account in method['accounts']:
            key=account['session'],account['symbol']
            poisoned=dict(account,orders=[o for o in account['orders'] if o[4]==1],trades=['使用禁止'],net=1e100)
            fresh=MODULE.labeled_entries(method['id'],poisoned,frames[key],inputs[key])
            expected=[r for r in labels if r['手法ID']==method['id'] and (r['セッション'],r['銘柄'])==key]
            assert fresh==expected
            separation+=1
    audit=dict(合格=True,実入口数=len(entries),固定将来ラベル数=len(labels),集計比較数=aggregates,
               返済損益情報破壊比較数=separation,asof最終原本行一致=True,場末欠測古さ5秒一致=True,
               時計の限定='同約定時計の最終行は診断専用の事後ラベル。受信時刻は分からず、新規判断には使わない。',
               コードSHA256=hashlib.sha256((BASE/'entry/diagnose_entry.py').read_bytes()).hexdigest())
    (HERE/'入口固定診断の独立監査.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(audit,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
