"""ALIGNEDの既知無発火を、保存C_ONLYの実数量半量へ正確に派生する。"""

from copy import deepcopy
import math

import numpy as np

import common

C_ID='C_ONLY_B2_ER40_B4'
RANGE_RESULTS=common.ROOT/'work/wave_v106/range_price/finance/results.json'
C_RESULTS=common.ROOT/'work/wave_v106/regime_price/finance/results.json'


def c_normal(packet: dict, symbol: str) -> dict:
    """
    機能: 保存six状態と元C根拠から、旧C_ONLY ER40/B2の同一イベントを再構成する。
    引数: packet(dict)、symbol(str)は既知normal入力と商品。
    返り値: dictはCだけの参照normal。売買/会計を再生しない。
    """
    original=packet['cases'][symbol]['C_OWN'];state=packet['measured'][symbol]['states']['0.4']
    n=len(original['event']);chosen=((state==2)&(original['event']==1))|((state==-2)&(original['event']==-1))
    normal=dict(entry_id=C_ID,event=np.where(chosen,original['event'],0).astype(np.int8),
        support_price=np.where(chosen,original['support_price'],np.nan),entry_quality=original['entry_quality'],
        entry_reset=original['entry_reset'],execution_to_raw_index=original['execution_to_raw_index'],
        decisions=[deepcopy(d) for d in original['decisions'] if chosen[int(d['row'])]],
        entry_families=np.where(chosen,1,0).astype(np.int8),target_prices=np.full(n,np.nan),
        entry_stop_prices=np.full(n,np.nan),entry_limit_prices=np.full(n,np.nan),entry_modes=np.where(chosen,1,0).astype(np.int8),
        range_pending_trend=(state==2)|(state==-2),local_cancel_buy=np.zeros(n,bool),local_cancel_sell=np.zeros(n,bool),
        quiet=packet['quiet'][symbol]['active'],quiet_start_s=packet['quiet'][symbol]['start_s'])
    assert len(normal['decisions'])==int(chosen.sum())
    return normal


def verify_alias(packet: dict, symbol: str, normal: dict) -> dict:
    """
    機能: 無RのALIGNEDとC_ONLYの全イベント、C根拠、予定静観/タイマー入力を照合する。
    引数: packet(dict)、symbol(str)、normal(dict)は同場の入力とALIGNED選択。
    返り値: dictは一致数/無イベントの未使用字段差数。全行全字段の同値を捏造しない。
    """
    reference=c_normal(packet,symbol);rows=np.flatnonzero(reference['event']);n=len(reference['event'])
    assert not np.any((normal['event']!=0)&(normal['entry_families']==2))
    for name in ('event','execution_to_raw_index','quiet','quiet_start_s'):
        np.testing.assert_array_equal(normal[name],reference[name])
    for name in ('support_price','entry_quality','entry_reset','entry_families','entry_modes'):
        np.testing.assert_array_equal(normal[name][rows],reference[name][rows])
    assert normal['decisions']==reference['decisions']
    assert len(normal['event'])==n and packet['prepared'][symbol]['record']['time_s'].shape==(n,)
    inactive=reference['event']==0
    return dict(C候補数=len(rows),R候補数=0,全event静観map一致=True,C当行資格根拠一致=True,
        未使用字段差=dict(support=int(np.count_nonzero(inactive&np.isfinite(normal['support_price']))),
            quality=int(np.count_nonzero(inactive&(normal['entry_quality']!=reference['entry_quality']))),
            reset=int(np.count_nonzero(inactive&(normal['entry_reset']!=reference['entry_reset'])))),
        限界='R拒否行の未使用字段は異なり得る。C pendingはqokで約定、部品offでは未使用字段を保有判断へ使わないことをsource/人工で照合。')


def expand(array: object, n: int) -> np.ndarray:
    """
    機能: 保存変化行の配列を同じnormal全行へ展開する。
    引数: array(dict|ndarray)、n(int)は既保存の疎値と行数。
    返り値: ndarrayは元値。不足行へ将来価格を補完する処理ではない。
    """
    if isinstance(array,np.ndarray):assert len(array)==n;return array.copy()
    rows=array['rows'];values=array['values'];assert len(rows)>0 and rows[0]==0 and rows[-1]<n
    position=np.searchsorted(rows,np.arange(n),side='right')-1
    return values[position].copy()


def scale_columns(output: dict, key: str, columns_key: str, names: tuple[str,...]) -> None:
    """
    機能: 注文/親/玉/判断の数量又は円欄だけを半量へ変換する。
    引数: output(dict)、key/columns_key(str)、names(tuple[str,...])は配列と欄名。
    返り値: None。価格・原行・時刻・親IDを変えない。
    """
    if key not in output:return
    columns=output[columns_key]
    for name in names:
        if name in columns:output[key][:,columns.index(name)]/=2.


def half_output(ledger: dict, record: dict, source: dict) -> dict:
    """
    機能: 旧C_ONLY全量の実約定を、整数半量と注文別料金の完全比例へ派生する。
    引数: ledger/record/source(dict)は旧台帳、同じ正常価格、元path/SHA参照。
    返り値: dictは同価格/時刻/親で5枚又は10枚の会計入力。新金融再生ではない。
    """
    symbol=record['symbol'];q=5 if symbol=='TOPIX' else 10;fee=math.floor(q*(41.8 if symbol=='TOPIX' else 11.)+1e-8)
    assert int(ledger['row_count'])==len(record['seq'])
    assert np.all(ledger['orders'][:,5]==2*q) and np.all(ledger['orders'][:,9]==2*fee)
    assert np.all(ledger['trades'][:,1]==0) and np.all(ledger['trades'][:,5]==2*q)
    result=deepcopy(ledger);n=len(record['seq'])
    for key in ('curve','source_curve','target_trace'):result[key]=expand(ledger[key],n)/2.
    scale_columns(result,'orders','order_columns',('quantity','fee'))
    scale_columns(result,'trades','trade_columns',('quantity','entry_fee','exit_fee','gross','net'))
    scale_columns(result,'growth_cohorts','growth_cohort_columns',('quantity','entry_fee','exit_fee_share','gross','net','risk_budget','initial_quantity','parent_final_quantity'))
    scale_columns(result,'events','event_columns',('quantity',))
    scale_columns(result,'judgments','judgment_columns',('initial_risk_yen',))
    scale_columns(result,'control_judgments','control_columns',('equity','session_budget'))
    if 'control_events' in result:
        columns=result['control_event_columns'];events=result['control_events']
        selected=np.isin(events[:,columns.index('code')],(1,2,10))
        events[selected,columns.index('detail')]/=2.
    stats=result['stat_columns']
    for name in ('max_held_long','max_held_short','max_occupied_long','max_occupied_short','held_long','held_short','pending_entry','pending_exit','max_total_held','cash'):
        result['stats'][stats.index(name)]/=2.
    for diagnostic in result['raw_entry_diagnostics']:
        assert diagnostic['quantity']==2*q
        diagnostic['quantity']=q;diagnostic['fee']/=2
    assert np.all(result['orders'][:,5]==q) and np.all(result['orders'][:,9]==fee)
    assert np.all(result['target_trace']==np.floor(result['target_trace']))
    assert not np.any(result['target_trace'][-1])
    result.update(quantity=q,derived=True,derivation=dict(kind='C_ONLY整数半量',source_id=C_ID,source=source,
        source_quantity=2*q,quantity=q,source_oneway_fee=2*fee,oneway_fee=fee,financial_replays=0,
        definition='この数量では注文料が厳密半分。同価格/同時刻の旧C_ONLY約定と保有を保存派生し、新有効性の証拠に加えない。'))
    return result


def baseline_metadata(sessions: list[str], configs: list[dict]) -> tuple[dict,dict]:
    """
    機能: 旧6AUTOと旧C_ONLYの参照ID/33場66行/実数量を小結果目録で確認する。
    引数: sessions(list[str])、configs(list[dict])は固定対象と18設定。
    返り値: tuple[dict,dict]は旧range/旧C_ONLY結果。台帳や注文再生はしない。
    """
    range_result=common.read(RANGE_RESULTS);c_result=common.read(C_RESULTS)
    assert range_result['全合格'] and c_result['全合格']
    assert range_result['sessions']==c_result['sessions']==sessions and len(sessions)==33
    bases={cfg['base_id'] for cfg in configs};assert len(bases)==6
    for result,ids,quantity in ((range_result,bases,{'TOPIX':5,'NK225':10}),(c_result,{C_ID},{'TOPIX':10,'NK225':20})):
        config_map={cfg['id']:cfg for cfg in result['configs']}
        for ident in ids:
            assert ident in result['cases'] and config_map[ident]['quantity']==quantity,ident
            rows=result['cases'][ident]['rows'];assert len(rows)==66
            assert {(r['session'],r['symbol']) for r in rows}=={(s,p) for s in sessions for p in ('TOPIX','NK225')}
            for s in sessions:assert set(result['cases'][ident]['ledgers'][s])=={'TOPIX','NK225'}
    return range_result,c_result
