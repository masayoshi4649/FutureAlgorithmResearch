"""原入力を読まず、再利用契約と読取・保存の結線を人工列で検査する。"""

from io import BytesIO
import json
from pathlib import Path
import tempfile

import numpy as np

import input_contract
import measure
import plan


def main() -> None:
    """
    機能: 44列の順逆写像、指定列だけの読取、NaN保存、登録表示の独立性を確かめる。
    引数: なし。小目録だけを使い、市場本文を読まない。
    返り値: None。所有域へ人工証跡を保存し、新金融・原NPZ読取は0。
    """
    fixed=plan.read(plan.HERE/'入力と保存公開の固定.json')
    checks=[]
    assert plan.digest(plan.HERE/'input_contract.py')==plan.digest(plan.OLD/'input_contract.py')
    checks.append('生成元115と入力契約の同bytes再利用')
    arrays={}
    for name,item in fixed['schema'].items():
        shape=tuple(4 if size=='N' else 2 if size=='M' else size for size in item['shape'])
        arrays[name]=np.zeros(shape,dtype=item['dtype'])
    arrays['raw_seq'][:]=np.arange(4)
    arrays['execution_to_raw_index'][:]=[1,3]
    arrays['normal_execution_row'][:]=[-1,0,-1,1]
    input_contract.validate(arrays,fixed['schema'])
    assert all(not value.flags.writeable for value in arrays.values())
    wrong={key:value.copy() for key,value in arrays.items()}
    wrong['normal_execution_row'][:]=[-1,1,-1,0]
    rejected=False
    try:input_contract.validate(wrong,fixed['schema'])
    except AssertionError:rejected=True
    assert rejected
    checks.append('正常行0を偽としない順逆写像・不一致拒否・44列読取専用')
    original=json.dumps(fixed,ensure_ascii=False,allow_nan=False)
    registered=plan.registration_inputs(fixed)
    assert json.dumps(fixed,ensure_ascii=False,allow_nan=False)==original
    for source,row in zip(fixed['inputs'],registered):
        if source['time_policy']['quiet_windows']==[]:
            assert isinstance(row['time_policy']['quiet_windows'],str)
        else:assert row['time_policy']['quiet_windows']==source['time_policy']['quiet_windows']
    registered[0]['raw']['path']='人工変更'
    assert fixed['inputs'][0]['raw']['path']!='人工変更'
    checks.append('登録の空窓明示は深いコピーに限定、実行小固定を変更しない')
    with tempfile.TemporaryDirectory(prefix='方向採点の人工_') as temporary:
        folder=Path(temporary)
        memory=BytesIO()
        wanted=np.arange(62,dtype=np.float64).reshape(2,31)
        np.savez_compressed(memory,events=wanted,未来結果=np.array([object()],dtype=object))
        path=folder/'人工保存.npz'
        path.write_bytes(memory.getvalue())
        info=dict(path=str(path),bytes=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns,SHA256=plan.digest(path))
        counts=dict(保存eventNPZ=0)
        loaded=measure.load_once(info,counts,'保存eventNPZ',('events',))
        assert list(loaded)==['events'] and counts==dict(保存eventNPZ=1)
        np.testing.assert_array_equal(loaded['events'],wanted)
        assert not loaded['events'].flags.writeable
        checks.append('同bytesの指紋と配列検査、保存NPZの未来結果object列をdecodeしない')
        old=measure.OUT
        try:
            measure.OUT=folder
            observation=dict(events=wanted,labels=np.array([1],np.int8),terminal_rows=np.array([3],np.int64),
                eligible=np.array([True]),nonoverlap=np.array([True]),mfe=np.array([np.nan,-2.]),
                mae=np.array([np.nan,-4.]),metadata='配列に含めない')
            # 保存先だけを所有域として扱い、元の公開場所・入力を触らない。
            old_root=plan.ROOT
            plan.ROOT=folder
            saved=measure.save_observations(observation,folder/'人工観測.npz')
            with np.load(folder/saved['path'],allow_pickle=False) as archive:
                assert 'metadata' not in archive.files
                np.testing.assert_array_equal(archive['mfe'],observation['mfe'])
        finally:
            measure.OUT=old
            plan.ROOT=old_root
        checks.append('純観測NPZのNaNと負MFEを保持、objectや説明文字列を混ぜない')
    plan.write(plan.HERE/'結線の人工検証.json',dict(全合格=True,checks=checks,
        対象指紋={name:plan.digest(plan.HERE/name) for name in ('plan.py','measure.py','input_contract.py','artificial_root.py')},
        実市場本文=0,新金融=0,API=0))
    print(json.dumps(dict(全合格=True,人工検査=len(checks),実市場本文=0,新金融=0),ensure_ascii=False))


if __name__=='__main__':
    main()
