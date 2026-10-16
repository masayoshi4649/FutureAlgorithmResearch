"""防止条件の境界、欠測、相手更新、未来切断を人工格子で独立確認する。"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(HERE.parent))
spec=importlib.util.spec_from_file_location('防止信号の独立人工確認79',HERE.parent/'prevention.py')
prevention=importlib.util.module_from_spec(spec);sys.modules[spec.name]=prevention;spec.loader.exec_module(prevention)


def fixture(sign: int, count: int=16) -> dict:
    """機能: 両板支持と両価格反転を持つ人工格子を作る。

    引数: sign/count(int)。返り値: 素材辞書(dict)。
    """
    markets={}
    for name in ('TOPIX','NK225'):
        markets[name]=dict(current=dict(index=np.arange(count),valid=np.ones(count,dtype=bool),q_valid=np.ones(count,dtype=bool),
            depth_imbalance=np.full(count,.2*sign),bid=np.full(count,100.),ask=np.full(count,101.)),
            flow={15:dict(source_valid=np.ones(count,dtype=bool),valid=np.ones(count,dtype=bool),
                missing_ofi=np.zeros(count,dtype=bool),nonzero_ofi_count=np.full(count,3),ofi_ratio=np.full(count,.1*sign))},
            windows={30:dict(source_valid=np.ones(count,dtype=bool),ret_bp=np.full(count,-1.*sign),
                bid_change_ticks=np.full(count,-1.*sign),ask_change_ticks=np.full(count,-1.*sign)),
                300:dict(source_valid=np.ones(count,dtype=bool),efficiency=np.full(count,.2))})
    return dict(grid=np.arange(count)*5.,markets=markets)


def check_prefix(value: dict) -> int:
    """機能: 元素材を切断・未来改変し、過去のすべての防止旗が不変か検査する。

    引数: value(dict)。返り値: 比較回数(int)。
    """
    full=prevention.session_state(value);n=len(value['grid']);compared=0
    for end in (1,3,4,7,n-1):
        def truncate(v: object) -> object:
            """機能: 配列だけを指定格子数に切る。

            引数: v(object)。返り値: 切断内容(object)。
            """
            if isinstance(v,dict):return {k:truncate(x) for k,x in v.items()}
            if isinstance(v,np.ndarray):return v[:end].copy()
            return v
        partial=prevention.session_state(truncate(value))
        mutant=copy.deepcopy(value)
        for m in mutant['markets'].values():
            m['current']['valid'][end:]=False;m['current']['q_valid'][end:]=False
            m['current']['index'][end:]+=1000;m['current']['depth_imbalance'][end:]*=-1
            m['flow'][15]['ofi_ratio'][end:]*=-1;m['flow'][15]['missing_ofi'][end:]=True
            m['windows'][30]['ret_bp'][end:]*=-1;m['windows'][30]['bid_change_ticks'][end:]*=-1
            m['windows'][30]['ask_change_ticks'][end:]*=-1;m['windows'][300]['efficiency'][end:]=np.nan
        changed=prevention.session_state(mutant)
        for symbol,fields in full['markets'].items():
            for name,expected in fields.items():
                np.testing.assert_array_equal(partial['markets'][symbol][name],expected[:end])
                np.testing.assert_array_equal(changed['markets'][symbol][name][:end],expected[:end]);compared+=2
    return compared


def main() -> None:
    """機能: 入口3証拠と二市場・片市場の出口確認を損益なしで点検する。

    引数: なし。返り値: なし(None)。
    """
    cases=[]
    for sign,label in ((1,'long'),(-1,'short')):
        a=fixture(sign);r=prevention.session_state(a)
        for m in r['markets'].values():
            assert np.all(m[f'support_{label}']) and np.all(m[f'efficient_{label}']) and np.all(m[f'depth_{label}'])
            assert not np.any(m[f'x1_{label}'][:3]) and np.all(m[f'x1_{label}'][3:])
            assert np.array_equal(m[f'x1_{label}'],m[f'x2_{label}'])
        cases.append(a)
        for field,number in (('nonzero_ofi_count',2),('ofi_ratio',.099*sign),('missing_ofi',True),('valid',False)):
            b=copy.deepcopy(a);b['markets']['NK225']['flow'][15][field][:]=number
            r=prevention.session_state(b);assert not np.any(r['markets']['TOPIX'][f'support_{label}']);cases.append(b)
        b=copy.deepcopy(a);b['markets']['NK225']['windows'][300]['efficiency'][:]=np.nan
        assert not np.any(prevention.session_state(b)['markets']['TOPIX'][f'efficient_{label}']);cases.append(b)
        b=copy.deepcopy(a);b['markets']['NK225']['current']['depth_imbalance'][:]=0.
        assert np.all(prevention.session_state(b)['markets']['TOPIX'][f'depth_{label}']);cases.append(b)
        for field,number in (('depth_imbalance',-.01*sign),('q_valid',False)):
            b=copy.deepcopy(a);b['markets']['NK225']['current'][field][:]=number
            assert not np.any(prevention.session_state(b)['markets']['TOPIX'][f'depth_{label}']);cases.append(b)
        b=copy.deepcopy(a);b['markets']['NK225']['windows'][30]['ret_bp'][:]=0.
        b['markets']['NK225']['windows'][30]['bid_change_ticks'][:]=0.;b['markets']['NK225']['windows'][30]['ask_change_ticks'][:]=0.
        r=prevention.session_state(b);assert not np.any(r['markets']['TOPIX'][f'x1_{label}'])
        assert np.all(r['markets']['TOPIX'][f'x2_{label}'][3:]) and not np.any(r['markets']['NK225'][f'x2_{label}']);cases.append(b)
        b=copy.deepcopy(a);b['markets']['NK225']['current']['index'][:]=0
        for m in prevention.session_state(b)['markets'].values():assert not np.any(m[f'x1_{label}']) and not np.any(m[f'x2_{label}'])
        cases.append(b)
        b=copy.deepcopy(a);b['markets']['TOPIX']['windows'][30]['source_valid'][2]=False
        r=prevention.session_state(b);assert not np.any(r['markets']['TOPIX'][f'x1_{label}'][:6]) and np.all(r['markets']['TOPIX'][f'x1_{label}'][6:]);cases.append(b)
    total=sum(check_prefix(case) for case in cases)
    proof=dict(合格=True,人工経路数=len(cases),未来配列比較数=total,
        検査='OFI十分性/閾値/不明、効率無効、板符号と品質、X1/X2の中立差、相手更新なし、欠測を跨ぐ持続、切断と未来改変。',
        prevention_SHA256=hashlib.sha256((HERE.parent/'prevention.py').read_bytes()).hexdigest(),
        新損益再生=0,API取得=0,実注文=0)
    (HERE/'防止信号の人工境界と未来不変監査.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
