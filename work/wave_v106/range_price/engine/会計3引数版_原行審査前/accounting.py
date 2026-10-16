"""市場と待機指値の約定規則を分離し、実注文から全行清算を独立検算する。"""

import importlib.util
import math
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def account_module() -> object:
    """
    機能: 旧102の純会計を固有名で読取り、注文経済へ再利用する。
    引数: なし。
    返り値: objectは旧account部品。旧source/cacheや金融結果を書換えない。
    """
    name='106R_PRICEの不変102注文会計'
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,ROOT/'work/wave_v102/accounting.py')
        value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return sys.modules[name]


def quote_valid(record: dict) -> np.ndarray:
    """
    機能: 執行の正常quoteを価格/時計/明示quote_validから算定する。
    引数: record(dict)は同normal価格列。
    返り値: np.ndarray[bool]はqok。Rの状態資格とC数量資格へ代用しない。
    """
    return (record['quote_valid']&np.isfinite(record['time_s'])&np.isfinite(record['bid'])&np.isfinite(record['ask'])&
        (record['bid']>0)&(record['ask']>record['bid']))


def first_fill(record: dict, order: np.ndarray, normal_rows: np.ndarray) -> int:
    """
    機能: 当該実注文の公表原row後の初qok又は初指値到達rowを独立に求める。
    引数: record(dict)、order(np.ndarray[float])、normal_rows(np.ndarray[int64])は正常列と物理注文。
    返り値: intは期待fill row。実fillまでの接頭だけを調べ、先に到達済み又は未到達なら不正約定を拒否する。
    """
    decision=int(order[1]);actual=int(order[0])
    available=normal_rows[np.searchsorted(normal_rows,decision,side='right'):np.searchsorted(normal_rows,actual,side='right')]
    if not order[7]:
        available=available[record['time_s'][available]>=order[10]]
    elif int(order[3])==1 and int(order[14])==12:
        price=float(order[12]);assert np.isfinite(price) and price>0
        epsilon=float(record['tick'])*1e-8
        reached=record['ask'][available]<=price+epsilon if order[4]==1 else record['bid'][available]>=price-epsilon
        available=available[reached]
    else:
        assert int(order[3])==0 or int(order[14])==11
    assert len(available)>0,'実注文に対応する公表後の正常約定がありません'
    return int(available[0])


def inspect(key: tuple, record: dict, output: dict) -> dict:
    """
    機能: C/R市場の次qok、R指値の初到達、手数料と全行清算時価を検算する。
    引数: key(tuple[str,str])、record/output(dict)は場商品と保存価格・注文経済。
    返り値: dictは旧互換会計と注文規則の確認件数。短い未決済prefixの会計には使用しない。
    """
    n=len(record['seq']);qok=quote_valid(record);normal_rows=np.flatnonzero(qok)
    multiplier,fee_unit,cap=(1000.,41.8,10) if key[1]=='TOPIX' else (10.,11.,20)
    cash_changes,long_changes,short_changes=(np.zeros(n) for _ in range(3))
    counts={'C_market':0,'R_market':0,'R_limit':0,'exit':0}
    diagnostics={int(d['parent_id']):d for d in output['raw_entry_diagnostics']}
    for order in output['orders']:
        row,decision,action,q=int(order[0]),int(order[1]),int(order[4]),int(order[5])
        assert row>decision and qok[row] and 0<q<=cap
        assert first_fill(record,order,normal_rows)==row,'初quote/初指値到達より遅い又は早い架空約定です'
        expected=record['ask'][row] if action==1 else record['bid'][row]
        assert abs(order[6]-expected)<1e-8 and order[9]==math.floor(q*fee_unit+1e-8)
        if order[7]:
            diagnostic=diagnostics[int(order[2])]
            assert diagnostic['decision_row']==decision and diagnostic['fill_row']==row
            assert diagnostic['decision_raw_seq']==int(record['seq'][decision]) and diagnostic['fill_raw_seq']==int(record['seq'][row])
            kind='C_market' if int(order[3])==0 else 'R_limit' if int(order[14])==12 else 'R_market'
            counts[kind]+=1
            if kind=='R_limit':assert diagnostic['entry_mode']=='LIMIT' and diagnostic['posted_limit']==order[12]
        else:counts['exit']+=1
        cash_changes[row]-=action*q*expected*multiplier+order[9]
        direction=int(order[15]);change=q if order[7] else -q
        (long_changes if direction==1 else short_changes)[row]+=change
    # ----------------------------------------
    # 実保有だけを価格と返済料で清算し、未約定指値には架空の含み損益や料を付けない。
    longs,shorts=np.cumsum(long_changes),np.cumsum(short_changes)
    assert np.all((longs>=0)&(shorts>=0)&(longs<=cap)&(shorts<=cap))
    assert not np.any((longs>0)&(shorts>0))
    held=(longs+shorts)>0;last=np.maximum.accumulate(np.where(qok,np.arange(n),-1))
    assert np.all(last[held]>=0)
    expected_curve=np.cumsum(cash_changes);rows=last[held]
    expected_curve[held]+=(longs[held]*record['bid'][rows]-shorts[held]*record['ask'][rows])*multiplier
    expected_curve[held]-=np.floor((longs[held]+shorts[held])*fee_unit+1e-8)
    np.testing.assert_allclose(output['curve'],expected_curve,atol=1e-4,rtol=0)
    np.testing.assert_array_equal(output['target_trace'][:,0],longs)
    np.testing.assert_array_equal(output['target_trace'][:,1],shorts)
    assert output['target_trace'][:,:4].max(initial=0)<=cap
    row=account_module().account(key,output)
    row.update(独立全行会計検算=True,約定規則件数=counts,
        約定監査='実公表row後の初quote又は初指値到達を価格列から直接検算。取消済parentの未来fillは存在しない。',
        源名対応={'J2':'C支持B4','O06':'R_PRICE価格往復'})
    return row
