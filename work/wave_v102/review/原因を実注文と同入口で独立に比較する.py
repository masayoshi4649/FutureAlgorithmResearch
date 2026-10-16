"""102全31完了の明示後だけ、量・増玉資格・実線変更と同入口の実収支を分ける。"""

import argparse
from datetime import datetime, timedelta, timezone
from fractions import Fraction as F
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys

sys.dont_write_bytecode=True
import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
SYMBOLS=('TOPIX','NK225')
IDS=('B1_T0_Q1_X1','G0_Q1_X1','G1_Q1_X1','B1_T1_Q1_X1','G0_QFULL_X1')
JST=timezone(timedelta(hours=9))
EPSILON=1e-5


def read(path: Path) -> object:
    """
    機能: 許可段階の保存資料を読取専用で読む。
    引数: path(Path)。
    返り値: object。JSON又はpickle。モジュール接続時には読まない。
    """
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix=='.pkl' else json.loads(stream.read().decode('utf-8'))


def digest(path: Path) -> str:
    """
    機能: 根拠資料の現在指紋を算出する。
    引数: path(Path)。
    返り値: str。SHA256。保存内容を変更しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def module(name: str, path: Path) -> object:
    """
    機能: mainを実行せず私有の純関数又は保存入力読取へ接続する。
    引数: name(str)、path(Path)。
    返り値: object。根の金融採点と売買実行は接続しない。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 実一注文の料金を十進有理数で計算する。
    引数: quantity(int)、symbol(str)。
    返り値: int。複数新規注文の料金を最終数量一注文へ置換しない。
    """
    return math.floor(quantity*(F('41.8') if symbol=='TOPIX' else F(11)))


def guard(base: Path, fixed: dict) -> list[Path]:
    """
    機能: 正式20条件の前16・後15と全31集計が全部保存されていることを確認する。
    引数: base(Path)、fixed(dict)。
    返り値: list[Path]。完了根拠。欠落時は金融pickleを開く前に拒否する。
    """
    identifiers={value['id'] for value in fixed['条件']}
    assert len(identifiers)==len(fixed['条件'])==20
    assert len(fixed['全31'])==len(set(fixed['全31']))==31
    assert len(fixed['前16'])==16 and len(fixed['後15'])==15
    assert set(fixed['前16']).isdisjoint(fixed['後15'])
    assert set(fixed['全31'])==set(fixed['前16'])|set(fixed['後15'])
    assert fixed['主']==IDS[0] and fixed['全31既知'] and fixed['新未見確認場数']==0
    assert set(IDS)<=identifiers
    paths=[]
    for part in ('front','back'):
        for kind,suffix in (('results','.json'),('ledgers','.pkl')):
            current=sorted((base/part/kind).glob('*'+suffix))
            assert {path.stem for path in current}==identifiers,part+'/'+kind+'未完了'
            paths.extend(current)
    for relative in ('事前固定.json','前16参考代表.json','analysis/比較結果.json'):
        path=base/relative
        assert path.is_file(),relative+'未完了'
        paths.append(path)
    return paths


def expand(ledger: dict, prefix: str, width: int) -> np.ndarray:
    """
    機能: 保存した変化行から全原行状態を復元して指紋を確認する。
    引数: ledger(dict)、prefix(str)、width(int)。
    返り値: ndarray[float]。疎行数を原行数や拒否回数へ取り違えない。
    """
    values=np.asarray(ledger[prefix+'_changes'],float); rows=int(ledger['input_rows'])
    indexes=values[:,0].astype(np.int64)
    assert values.shape[1]==width+1 and len(indexes)>0 and indexes[0]==0
    assert np.array_equal(indexes,values[:,0]) and np.all(np.diff(indexes)>0)
    assert np.all((indexes>=0)&(indexes<rows))
    dense=values[np.searchsorted(indexes,np.arange(rows),side='right')-1,1:]
    assert hashlib.sha256(dense.tobytes()).hexdigest()==ledger[prefix+'_SHA256']
    return dense


def timestamp(value: float) -> str:
    """
    機能: 保存価格代理時計を日本時間へ表示する。
    引数: value(float)。
    返り値: str。真受信時刻の認定ではない。小さな人工値は秒値として表示する。
    """
    return datetime.fromtimestamp(float(value),JST).isoformat() if value>=1e9 else f'人工時計{value:g}秒'


def parents(ledger: dict, session: str, symbol: str) -> list[dict]:
    """
    機能: 実初回と全追加及び全量返済の物理注文から親ごとの収支を再計算する。
    引数: ledger(dict)、session/symbol(str)。
    返り値: list[dict]。同入口比較用の実事実。仮の出口や未保有過去peakを使わない。
    """
    orders=np.asarray(ledger['orders']); groups=np.asarray(ledger['growth_cohorts'])
    positions={name:i for i,name in enumerate(ledger['growth_cohort_columns'])}
    multiplier=1000 if symbol=='TOPIX' else 10
    result=[]
    for parent in np.asarray(ledger['trades']):
        pid=int(parent[0]); side=int(parent[4])
        entries=sorted((order for order in orders if int(order[2])==pid and order[7]==1),key=lambda order:int(order[16]))
        exits=[order for order in orders if int(order[2])==pid and order[7]==0]
        assert len(entries)>0 and len(exits)==1
        first,exit_order=entries[0],exits[0]
        initial=[group for group in groups if int(group[positions['parent_id']])==pid and group[positions['entry_kind']]==0]
        assert len(initial)==1
        cohort=initial[0]
        q=sum(int(order[5]) for order in entries)
        assert q==exit_order[5] and all(order[4]==side for order in entries) and exit_order[4]==-side
        gross=side*sum(int(order[5])*(F(str(exit_order[6]))-F(str(order[6]))) for order in entries)*multiplier
        fees=sum(fee(int(order[5]),symbol) for order in (*entries,exit_order))
        net=gross-fees
        assert float(net)==parent[11] and float(gross)==parent[10]
        assert sum(int(order[9]) for order in (*entries,exit_order))==fees
        key=(session,symbol,side,int(cohort[positions['decision_row']]),int(cohort[positions['decision_seq']]),
            float(cohort[positions['decision_time']]),int(cohort[positions['entry_row']]),
            int(cohort[positions['entry_seq']]),float(cohort[positions['entry_time']]),float(cohort[positions['entry_price']]))
        result.append(dict(session=session,symbol=symbol,parent_id=pid,side=side,initial_key=key,
            initial_quantity=int(first[5]),final_quantity=q,adding_orders=len(entries)-1,
            entry_row=int(first[0]),entry_time=float(first[11]),entry_time_text=timestamp(first[11]),
            entry_price=float(first[6]),exit_row=int(exit_order[0]),exit_time=float(exit_order[11]),
            exit_time_text=timestamp(exit_order[11]),exit_price=float(exit_order[6]),exit_reason=int(exit_order[8]),
            gross=float(gross),fees=fees,net=float(net)))
    assert len({row['initial_key'] for row in result})==len(result)
    return result


def episodes(mask: np.ndarray, ids: np.ndarray) -> int:
    """
    機能: 連続拒否行と親の切替を区切って拒否エピソード数を算出する。
    引数: mask(ndarray[bool])、ids(ndarray[float])。
    返り値: int。エピソードを独立した新規注文回数とは呼ばない。
    """
    previous=np.r_[False,mask[:-1]]
    same_parent=np.r_[False,ids[1:]==ids[:-1]]
    return int(np.sum(mask&(~previous|~same_parent)))


def gates(ledger: dict, config: dict, record: dict) -> dict:
    """
    機能: 追加余裕と据置の拒否数、実追加と次約定の線変更を全原行で再計算する。
    引数: ledger/config/record(dict)。
    返り値: dict。基本資格は監査対象の保存列、B/T数理と件数は独立計算。
    """
    state=expand(ledger,'growth_state',70); gate=expand(ledger,'growth_gate_state',19)
    assert len(state)==len(record['time_s'])==len(gate)
    positions={name:i for i,name in enumerate(ledger['growth_state_columns'])}
    names={name:i for i,name in enumerate(ledger['growth_gate_state_columns'])}
    assert len(positions)==70 and len(names)==19
    symbol=record['symbol']; multiplier=1000 if symbol=='TOPIX' else 10
    ids=gate[:,names['parent_id']]; evaluated=np.isfinite(gate[:,names['old_stop_after_normal_update']])
    cushion_ok=np.zeros(len(gate),bool); budget_ok=cushion_ok.copy(); preserved=cushion_ok.copy()
    parent_side={int(parent[0]):int(parent[4]) for parent in ledger['trades']}
    for row in np.flatnonzero(evaluated):
        pid=int(ids[row]); side=parent_side[pid]; q=int(state[row,positions['held_quantity']])
        delta=min(q,int(state[row,positions['maximum_quantity']])-q); total=q+delta
        quote=F(str(record['bid' if side==1 else 'ask'][row]))
        entry=F(str(record['ask' if side==1 else 'bid'][row]))
        cash=F(str(state[row,positions['entry_cash']]))+delta*entry*multiplier
        costs=int(state[row,positions['entry_fees']])+fee(delta,symbol)+fee(total,symbol)
        line=F(str(gate[row,names['old_stop_after_normal_update']]))
        planned=F(str(gate[row,names['planned_stop']]))
        risk=F(str(gate[row,names['risk_budget']]))
        net_at_old=side*(total*line*multiplier-cash)-costs
        assert float(net_at_old)==gate[row,names['planned_net_at_old_stop']]
        cushion=side*(quote-planned)
        required=F(str(config.get('trend_growth_cushion_initial_multiple',0.)))*F(str(gate[row,names['initial_width']])) \
            if config.get('trend_growth_cushion_basis','ticks')=='initial_width' \
            else F(str(config['trend_growth_mode']*record['tick']))
        assert float(required)==gate[row,names['required_cushion']]
        cushion_ok[row]=cushion>=required; budget_ok[row]=net_at_old>=-risk; preserved[row]=line==planned
        assert cushion_ok[row]==bool(gate[row,names['cushion_allowed']])
        assert budget_ok[row]==bool(gate[row,names['budget_at_old_allowed']])
        assert preserved[row]==bool(gate[row,names['stop_preserved']])
    base=gate[:,names['base_eligible']]==1
    preserve_required=bool(config.get('trend_growth_preserve_stop',False))
    accepted=base&cushion_ok&((budget_ok&preserved) if preserve_required else True)
    assert np.array_equal(accepted,gate[:,names['eligible']]==1)
    b_rejected=base&~cushion_ok
    t_rejected=base&cushion_ok&(~budget_ok|~preserved)&preserve_required
    rejected=b_rejected|t_rejected
    actual=gate[:,names['actual_added_quantity']]>0
    tighter=actual&(gate[:,names['actual_fill_tightened']]==1)
    events=np.asarray(ledger['growth_events']); groups=np.asarray(ledger['growth_cohorts'])
    column={name:i for i,name in enumerate(ledger['growth_cohort_columns'])}
    additions=groups[groups[:,column['entry_kind']]==1]
    assert len(additions)==int(actual.sum())
    assert np.array_equal(np.sort(additions[:,column['entry_row']].astype(int)),np.flatnonzero(actual))
    for row in np.flatnonzero(actual):
        pid=int(ids[row]); side=parent_side[pid]
        assert bool(gate[row,names['actual_fill_tightened']])==(side*(gate[row,names['actual_fill_new_stop']]-gate[row,names['actual_fill_old_stop']])>0)
    samples=[]
    for row in np.flatnonzero(tighter):
        pid=int(ids[row]); side=parent_side[pid]
        cohort=additions[additions[:,column['entry_row']]==row]; assert len(cohort)==1
        first=float(ledger['growth_parent_diagnostics'][ledger['growth_parent_diagnostics'][:,0]==pid,4][0])
        samples.append(dict(parent_id=pid,行=int(row),原seq=int(record['seq'][row]),
            時刻=timestamp(record['time_s'][row]),判断時刻=timestamp(cohort[0,column['decision_time']]),
            初回価格=first,実追加価格=float(cohort[0,column['entry_price']]),
            実追加枚数=int(gate[row,names['actual_added_quantity']]),
            実追加直前線=float(gate[row,names['actual_fill_old_stop']]),
            実追加直後線=float(gate[row,names['actual_fill_new_stop']]),
            短縮幅=side*(float(gate[row,names['actual_fill_new_stop']])-float(gate[row,names['actual_fill_old_stop']])),
            短縮S=side*(float(gate[row,names['actual_fill_new_stop']])-float(gate[row,names['actual_fill_old_stop']]))/float(gate[row,names['initial_width']])))
    cancel=events[events[:,1]==4]
    return dict(基本資格原行数=int(base.sum()),余裕拒否原行数=int(b_rejected.sum()),据置拒否原行数=int(t_rejected.sum()),
        全拒否原行数=int(rejected.sum()),余裕拒否エピソード数=episodes(b_rejected,ids),据置拒否エピソード数=episodes(t_rejected,ids),
        全拒否親数=len(set(ids[rejected].astype(int))),追加予約数=int(np.sum(events[:,1]==2)),実追加注文数=len(additions),
        実追加親数=len(set(additions[:,column['parent_id']].astype(int))),
        実追加枚数=int(sum(additions[:,column['quantity']])),未約定追加取消数=len(cancel),
        未約定取消理由別={str(int(reason)):int(np.sum(cancel[:,2]==reason)) for reason in np.unique(cancel[:,2])},
        実fill停止線短縮数=int(tighter.sum()),実fill停止線短縮割合=float(tighter.sum()/actual.sum()) if actual.any() else None,
        実fill短縮例=samples,
        件数の定義='拒否原行は正常な追加判定の反復であり、取引回数ではない。連続同親の拒否はエピソードも併記。'
                     '予算と余裕及び据置の数理は原板/実E,Q,Fから再計算。基本資格13列のraw生成は全監査の対象。')


def stability(rows: list[dict], parent_rows: list[dict], symbol: str, prices: dict, sessions: list[str]) -> dict:
    """
    機能: 実円損失と共通10/20枚の正規化を同時に評価する。
    引数: rows/parent_rows(list[dict])、symbol(str)、prices(dict)、sessions(list[str])。
    返り値: dict。赤字頻度・平均最大・親と建玉群の金額割合。無取引を勝ちに含めない。
    """
    selected=[row for row in rows if row['symbol']==symbol and row['session'] in sessions]
    selected_parents=[row for row in parent_rows if row['symbol']==symbol and row['session'] in sessions]
    active=[row for row in selected if row['campaigns']>0]
    black=[row for row in active if row['net']>EPSILON]
    red=[row for row in active if row['net']< -EPSILON]
    losers=[row for row in selected_parents if row['net']< -EPSILON]
    cap,multiplier=(10,1000) if symbol=='TOPIX' else (20,10)
    units={session:cap*multiplier*float(prices[session,symbol]['price'][0])*.001 for session in sessions}
    assert all(math.isfinite(value) and value>0 for value in units.values())
    nets=[row['net']/units[row['session']] for row in selected]
    profit=sum(row['profit'] for row in selected); loss=sum(row['loss'] for row in selected)
    cohort_profit=sum(row['cohorts']['profit'] for row in selected); cohort_loss=sum(row['cohorts']['loss'] for row in selected)
    add_parents=[row for row in selected_parents if row['adding_orders']>0]
    return dict(利益=profit,損失=loss,収支=profit-loss,手数料=sum(row['fees'] for row in selected),
        親金額利益割合=profit/(profit+loss) if profit+loss else None,
        建玉群利益=cohort_profit,建玉群損失=cohort_loss,
        建玉群金額利益割合=cohort_profit/(cohort_profit+cohort_loss) if cohort_profit+cohort_loss else None,
        全セッション数=len(selected),活動セッション数=len(active),黒字セッション数=len(black),赤字セッション数=len(red),
        無取引セッション数=len(selected)-len(active),活動黒字割合=len(black)/len(active) if active else None,
        平均赤字セッション円=sum(-row['net'] for row in red)/len(red) if red else 0.,
        最大赤字セッション円=max((-row['net'] for row in red),default=0.),
        親数=len(selected_parents),赤字親数=len(losers),赤字親割合=len(losers)/len(selected_parents) if selected_parents else None,
        平均赤字親円=sum(-row['net'] for row in losers)/len(losers) if losers else 0.,
        最大赤字親円=max((-row['net'] for row in losers),default=0.),
        実追加親数=len(add_parents),実追加親割合=len(add_parents)/len(selected_parents) if selected_parents else None,
        全量返済枚数=sum(row['lots'] for row in selected),最大実保有枚数=max((row['actual_peak_quantity'] for row in selected),default=0),
        共通cap=cap,共通分母場数=len(selected),共通単位円=units,
        下方RMS共通単位=math.sqrt(sum(min(value,0.)**2 for value in nets)/len(selected)) if selected else None,
        最大赤字共通単位=max((-row['net']/units[row['session']] for row in red),default=0.),
        セッション中央値共通単位=float(np.median(nets)) if nets else None,
        セッション下位25共通単位=float(np.quantile(nets,.25)) if nets else None,
        少数量解釈='共通capと評価場数を分母に固定。少枚数で円赤字が小さいだけを方向確度又は黒字頻度の改善と呼ばない。')


def matched(left: list[dict], right: list[dict], symbol: str, left_id: str, right_id: str) -> dict:
    """
    機能: 実初回の一致する親と両側の未一致親を分け、全収支差へ戻す。
    引数: left/right(list[dict])、symbol/left_id/right_id(str)。
    返り値: dict。同入口差と未一致残差。親IDだけの一致や仮出口損益を使わない。
    """
    a={row['initial_key']:row for row in left if row['symbol']==symbol}
    b={row['initial_key']:row for row in right if row['symbol']==symbol}
    keys=set(a)&set(b); only_a=set(a)-keys; only_b=set(b)-keys
    comparisons=[]
    for key in sorted(keys):
        x,y=a[key],b[key]
        comparisons.append(dict(session=x['session'],symbol=symbol,方向=x['side'],入口時刻=x['entry_time_text'],
            初回価格=x['entry_price'],初回一致キー=key,
            左親=x['parent_id'],右親=y['parent_id'],左初回枚数=x['initial_quantity'],右初回枚数=y['initial_quantity'],
            左追加注文数=x['adding_orders'],右追加注文数=y['adding_orders'],左最終枚数=x['final_quantity'],右最終枚数=y['final_quantity'],
            左返済時刻=x['exit_time_text'],右返済時刻=y['exit_time_text'],左返済価格=x['exit_price'],右返済価格=y['exit_price'],
            左費用=x['fees'],右費用=y['fees'],左収支=x['net'],右収支=y['net'],収支差=x['net']-y['net'],
            左出口理由=x['exit_reason'],右出口理由=y['exit_reason']))
    same_difference=sum(row['収支差'] for row in comparisons)
    left_unmatched=sum(a[key]['net'] for key in only_a); right_unmatched=sum(b[key]['net'] for key in only_b)
    difference=sum(row['net'] for row in a.values())-sum(row['net'] for row in b.values())
    assert math.isclose(difference,same_difference+left_unmatched-right_unmatched,rel_tol=0.,abs_tol=1e-6)
    untouched=[row for row in comparisons if row['左追加注文数']==0 and row['左初回枚数']==row['右初回枚数']]
    identical_untouched=all(row['収支差']==0 and row['左返済時刻']==row['右返済時刻'] and row['左返済価格']==row['右返済価格'] for row in untouched)
    negatives=sorted((row for row in comparisons if row['収支差']< -EPSILON),key=lambda row:row['収支差'])
    positives=sorted((row for row in comparisons if row['収支差']>EPSILON),key=lambda row:-row['収支差'])
    return dict(左手法=left_id,右手法=right_id,商品=symbol,左親数=len(a),右親数=len(b),同入口親数=len(keys),
        左未一致親数=len(only_a),右未一致親数=len(only_b),同入口収支差=same_difference,
        左未一致親収支=left_unmatched,右未一致親収支=right_unmatched,全収支差=difference,
        同入口差と未一致残差が全額差に一致=True,左未追加同数量親数=len(untouched),
        左未追加同数量の実出口及び金融同値=identical_untouched,
        左赤字右黒字の同入口数=sum(row['左収支']< -EPSILON and row['右収支']>EPSILON for row in comparisons),
        左黒字右赤字の同入口数=sum(row['左収支']>EPSILON and row['右収支']< -EPSILON for row in comparisons),
        同入口悪化上位=negatives[:5],同入口改善上位=positives[:5],全同入口比較=comparisons,
        左未一致親=[a[key] for key in sorted(only_a)],右未一致親=[b[key] for key in sorted(only_b)],
        比較の限界='同じ初回原行・判断源・方向・価格だけを一致キーにする。前の返済差で生じた次の不一致入口も全額差へ残す。'
                    'これは二つの実行済み策略の事後原因比較であり、同じ仮出口を採用した追加玉の反実仮想ではない。')


def main() -> None:
    """
    機能: 全31完了の明示後だけ5対照の実注文会計・追加門・同入口差を検算保存する。
    引数: CLI --root-all31-complete(bool)。根から全31完了を受領した場合だけ指定する。
    返り値: None。新しい売買、金融source変更、参考選定差替え、API取得を行わない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--root-all31-complete',action='store_true');args=parser.parse_args()
    assert args.root_all31_complete,'全31正式再生完了の明示通知前は新金融原因を読みません'
    fixed_path=WORK/'事前固定.json';fixed=read(fixed_path); all_paths=guard(WORK,fixed)
    for relative,expected in fixed['SHA256'].items(): assert digest(ROOT/relative)==expected,relative
    source_paths=[Path(__file__),HERE/'selection.py',WORK/'catalog.py',WORK/'data.py']
    before={path.relative_to(ROOT).as_posix():digest(path) for path in (*all_paths,*source_paths)}
    selection=module('102原因だけの独立実注文会計',HERE/'selection.py')
    assembled=read(WORK/'analysis/比較結果.json')
    assert assembled['primary']==fixed['主'] and assembled['全31既知'] and assembled['新未見確認場数']==0
    assert set(assembled['results'])=={value['id'] for value in fixed['条件']}
    data=module('102原因の既知保存入力だけ',WORK/'data.py'); material=data.load_inputs()
    prices=material['prices']; assert len(prices)==62
    conditions={value['id']:value for value in fixed['条件']}
    period_map={name:fixed[name] for name in ('全31','前16','後15')}
    period_map.update(デイ=[session for session in fixed['全31'] if session.endswith('_Day')],
        ナイト=[session for session in fixed['全31'] if session.endswith('_Night')])
    answers={}; ledgers_by_id={}; parent_by_id={}
    counts=dict(条件=5,口座=0,実注文=0,決済親=0,建玉群=0,門19全原行=0,門19数学判定行=0,同入口親=0,商品期間=0)
    for ident in IDS:
        ledger={}; saved_rows={}
        for part,period in (('front','前16'),('back','後15')):
            path=WORK/part/'ledgers'/(ident+'.pkl');saved=read(WORK/part/'results'/(ident+'.json'))
            assert saved['config']==conditions[ident] and saved['ledger_SHA256']==digest(path)
            current=read(path);assert set(current)=={(session,symbol) for session in fixed[period] for symbol in SYMBOLS}
            ledger.update(current);saved_rows.update({(row['session'],row['symbol']):row for row in saved['rows']})
        assert len(ledger)==62
        rows=[];parent_rows=[];observations=[]
        for session,symbol in sorted(ledger):
            key=session,symbol; independent=selection.account(ledger[key],symbol)
            for name in ('profit','loss','net','fees','campaigns','lots','winning_lots','losing_lots'):
                selection.close(saved_rows[key][name],independent[name],ident+'/'+session+'/'+symbol+'/'+name)
            for name in ('profit','loss','net','fees','lots','winning_lots','losing_lots'):
                selection.close(saved_rows[key]['cohorts'][name],independent['cohorts'][name],ident+'/'+session+'/'+symbol+'/cohort/'+name)
            rows.append(dict(session=session,symbol=symbol,**independent))
            counts['口座']+=1;counts['実注文']+=independent['order_count']
            counts['決済親']+=independent['campaigns'];counts['建玉群']+=independent['cohorts']['cohorts']
            counts['門19全原行']+=ledger[key]['input_rows']
            sparse=np.asarray(ledger[key]['growth_gate_state_changes'])
            starts=sparse[:,0].astype(int);lengths=np.diff(np.r_[starts,ledger[key]['input_rows']])
            counts['門19数学判定行']+=int(np.sum(lengths[np.isfinite(sparse[:,7])]))
            parent_rows.extend(parents(ledger[key],session,symbol))
            observations.append(dict(session=session,symbol=symbol,**gates(ledger[key],conditions[ident],prices[key])))
        periods={name:{symbol:stability(rows,parent_rows,symbol,prices,sessions) for symbol in SYMBOLS} for name,sessions in period_map.items()}
        counts['商品期間']+=len(periods)*len(SYMBOLS)
        for symbol in SYMBOLS:
            current=periods['全31'][symbol]; expected=assembled['results'][ident]['periods']['全31'][symbol]
            for left,right in (('利益','profit'),('損失','loss'),('収支','net'),('手数料','fees'),('親数','campaigns'),
                ('全量返済枚数','lots'),('活動セッション数','active_sessions'),('赤字セッション数','losing_sessions'),
                ('黒字セッション数','positive_sessions'),('無取引セッション数','no_trade_sessions')):
                selection.close(expected[right],current[left],ident+'/全31/'+symbol+'/'+left)
            for left,right in (('建玉群利益','profit'),('建玉群損失','loss'),('建玉群金額利益割合','profit_share')):
                selection.close(expected['cohorts'][right],current[left],ident+'/全31/'+symbol+'/'+left)
        count_summary={}
        for symbol in SYMBOLS:
            selected=[row for row in observations if row['symbol']==symbol]
            count_names=('基本資格原行数','余裕拒否原行数','据置拒否原行数','全拒否原行数','余裕拒否エピソード数','据置拒否エピソード数',
                '全拒否親数','追加予約数','実追加注文数','実追加親数','実追加枚数','未約定追加取消数','実fill停止線短縮数')
            values={name:sum(row[name] for row in selected) for name in count_names}
            values['実fill停止線短縮割合']=values['実fill停止線短縮数']/values['実追加注文数'] if values['実追加注文数'] else None
            count_summary[symbol]=values
        answers[ident]=dict(config=conditions[ident],各セッション=rows,親別=parent_rows,追加診断各セッション=observations,
            追加診断全31=count_summary,期間=periods)
        # ----------------------------------------
        # 同値比較には物理注文と親だけを保持し、5条件の大きな疎状態を同時常駐させない。
        ledgers_by_id[ident]={key:{name:value[name] for name in ('orders','trades')} for key,value in ledger.items()}
        parent_by_id[ident]=parent_rows
    comparisons={}
    for ident in (IDS[0],IDS[2],IDS[3]):
        comparisons[ident]={symbol:matched(parent_by_id[ident],parent_by_id[IDS[1]],symbol,ident,IDS[1]) for symbol in SYMBOLS}
    comparisons['小1枚固定と旧全量固定']={symbol:matched(parent_by_id[IDS[1]],parent_by_id[IDS[4]],symbol,IDS[1],IDS[4]) for symbol in SYMBOLS}
    counts['同入口親']=sum(value['同入口親数'] for by_symbol in comparisons.values() for value in by_symbol.values())
    assert counts['口座']==310 and counts['商品期間']==50
    equivalence={}
    for ident in (IDS[0],IDS[2],IDS[3]):
        equivalence[ident]={}
        for symbol in SYMBOLS:
            selected=[session for session in fixed['全31']]
            order_equal=all(np.array_equal(ledgers_by_id[ident][session,symbol]['orders'],ledgers_by_id[IDS[1]][session,symbol]['orders']) for session in selected)
            trade_equal=all(np.array_equal(ledgers_by_id[ident][session,symbol]['trades'],ledgers_by_id[IDS[1]][session,symbol]['trades']) for session in selected)
            diagnostic=answers[ident]['追加診断全31'][symbol]
            equivalence[ident][symbol]=dict(実追加0=diagnostic['実追加注文数']==0,
                G0全31実注文完全同値=order_equal,G0全31実親完全同値=trade_equal,
                増玉不実施だけの互換=diagnostic['実追加注文数']==0 and order_equal and trade_equal,
                解釈='増玉0かつG0と実注文及び実出口が全同値なら、新しい安定収益効果とは呼ばない。')
    ending={path.relative_to(ROOT).as_posix():digest(path) for path in (*all_paths,*source_paths)};assert before==ending
    signatures=dict(ending,**{path.relative_to(ROOT).as_posix():digest(path) for path in material['paths']})
    proof=dict(全合格=True,主=fixed['主'],手法一覧=list(IDS),対象口座数=5*62,検査件数=counts,全31既知=True,新未見確認場数=0,
        全計算=answers,同入口比較=comparisons,固定1枚との実金融同値=equivalence,
        scope='5条件の310口座。物理注文別費用と親/建玉群を独立再会計。19列を全行復元してB/Tの条件及び拒否を再計算。'
              '実fillの新旧線と初回一致親を実事実のまま比較。全原板時価と19列のraw基本資格は別の全監査で検証する。',
        因果の限界='全31は既知期間の事後分析。価格代理時計は真受信時計ではない。原因比較の出口値や完成親netを売買へ戻さない。',
        根accounting及びscore及びselect呼出=0,新正式売買実行=0,現在API取得=0,実注文=0,
        過去成果編集=0,参考代表差替え=0,開始終端全依存一致=True,SHA256=signatures)
    target=HERE/'全31の余裕と据置及び同入口の独立原因比較.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,対象口座数=5*62,追加診断={ident:value['追加診断全31'] for ident,value in answers.items()},
        主全31=answers[IDS[0]]['期間']['全31'],固定1枚との実金融同値=equivalence),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
