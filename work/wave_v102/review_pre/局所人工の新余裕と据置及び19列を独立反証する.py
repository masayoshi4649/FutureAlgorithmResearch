"""102新正式損益を開かず、私有人工と有理数で本体の余裕・据置・次約定を反証する。"""

from copy import deepcopy
from fractions import Fraction as F
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pickle
import sys

os.environ['NUMBA_DISABLE_JIT'] = '1'
sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: 正式結果を開かず指定された局所実装だけを接続する。
    引数: name(str)、path(Path)。
    返り値: object。main は呼ばず過去領域のキャッシュを書かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 検査中の実装と期待仕様の同一性を確認する。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 一注文ごとの立会費用を十進有理数で切り捨てる。
    引数: quantity(int)、symbol(str)。
    返り値: int。追加注文を単一の新規費用へ合算しない。
    """
    return math.floor(quantity * (F('41.8') if symbol == 'TOPIX' else F(11)))


def fixture(symbol: str, side: int, units: list[float] | None = None,
            times: list[float] | None = None, change: object = None) -> dict:
    """
    機能: 初回1呼値で入り、複数S順行と逆行を含む短い私有人工を作る。
    引数: symbol(str)、side(int)、units/times(list[float]|None)、change(callable|None)。
    返り値: dict。LP支持は人工bool注入であり、実原本の窓の認定ではない。
    """
    tick, base, peer_tick, peer_base = (.5, 4000., 10., 70000.) if symbol == 'TOPIX' else (10., 70000., .5, 4000.)
    width = max(2, math.ceil(base * .001 / tick - 1e-10)) * tick
    sequence = [0., tick / width, tick / width, .5, 1.5, 3., 6., 10., 12., 13.5, 14., 20., 18., -40., -40.]
    progress = np.asarray(sequence if units is None else units, float) * width
    progress = np.round(progress / tick) * tick
    size = len(progress)
    stamps = np.asarray(np.arange(size) + 300. if times is None else times, float)
    quote = base + side * progress
    bid = quote - tick if side == 1 else quote.copy()
    ask = quote.copy() if side == 1 else quote + tick
    record = dict(symbol=symbol, tick=tick, start=0., limit=10000., time_s=stamps,
        price=.5*(bid+ask), bid=bid, ask=ask, price_valid=np.ones(size,bool),
        quote_valid=np.ones(size,bool), seq=np.arange(size,dtype=np.int64)+100)
    peer_progress = np.arange(size, dtype=float) * peer_tick
    peer_bid = peer_base + side * peer_progress
    peer = np.column_stack((np.arange(size), np.arange(size)+200, stamps-.25,
        peer_bid, peer_bid+peer_tick, np.ones(size)))
    event = np.zeros(size,np.int8); event[0] = side
    signal = dict(grid=stamps.copy(), mapped=np.arange(size), mode=np.zeros(size,np.int8),
        event=event, quality=np.ones(size,bool), reset=np.zeros(size,bool),
        trend_width=max(2,math.ceil(base*.004/tick-1e-10))*tick, peer_tick=peer_tick,
        entry_wait_width=width, entry_advance_width=0., entry_pullback_width=0., entry_recovery_width=0.,
        entry_j2_long=np.full(size,side==1,bool), entry_j2_short=np.full(size,side==-1,bool),
        wait_opposite_long=np.zeros(size,bool), wait_opposite_short=np.zeros(size,bool), entry_peer_bbo=peer)
    basis=np.full((size,59),np.nan); basis[:,0]=np.arange(size); basis[:,1]=stamps
    value=dict(record=record, signal=signal, reference_open=base,
        trend_lp_allowed={1:np.full(size,side==1,bool), -1:np.full(size,side==-1,bool)},
        entry_support_base=basis)
    if change is not None: change(value)
    return {('2000-01-03_人工',symbol):value}


def run(strategy: object, config: dict, prepared: dict) -> dict:
    """
    機能: 私有人工を実行し、共有入力と設定が書き換わらないことを確認する。
    引数: strategy(object)、config/prepared(dict)。
    返り値: dict。人工出力だけ。
    """
    before=hashlib.sha256(pickle.dumps((config,prepared),protocol=5)).hexdigest()
    output=strategy.play(config,next(iter(prepared)),prepared,finish=False)
    assert before==hashlib.sha256(pickle.dumps((config,prepared),protocol=5)).hexdigest()
    return output


def named(row: np.ndarray, columns: list[str]) -> dict:
    """
    機能: 保存列を意味と数値へ写す。
    引数: row(ndarray)、columns(list[str])。
    返り値: dict。
    """
    assert len(row)==len(columns)
    return dict(zip(columns,row))


def protect(price: F, side: int, tick: float) -> F:
    """
    機能: 価格全体を有理数で保護丸めする。
    引数: price(F)、side(int)、tick(float)。
    返り値: F。ロングceil、ショートfloor。
    """
    quantum=F(str(tick)); ratio=price/quantum
    return (math.ceil(ratio) if side==1 else math.floor(ratio))*quantum


def lines(side: int, quantity: int, cash: F, fees: int, risk: F, initial: F,
          peak: F, trail: F, old: F, active: bool, quote: F, initial_q: int,
          width: F, value: F, tick: float, protection: bool) -> tuple:
    """
    機能: 旧線・初期線・追尾・R0・実gross起動の費用床を独立合成する。
    引数: side/quantity/fees/initial_q(int)、価格金額幅(F)、active/protection(bool)、tick(float)。
    返り値: tuple。予算線、費用床、有効線、起動状態。engine helper は使わない。
    """
    weighted=cash/(quantity*value)
    budget=protect(weighted-side*(risk-fees)/(quantity*value),side,tick)
    floor=protect(weighted+side*fees/(quantity*value),side,tick)+side*F(str(tick))
    activate=active or protection and side*(quantity*quote*value-cash)>=initial_q*2*width*value
    candidates=[old,initial,peak-side*trail,budget]+([floor] if activate else [])
    result=max(candidates) if side==1 else min(candidates)
    return budget,floor,result,bool(activate)


def check19(config: dict, prepared: dict, output: dict) -> dict:
    """
    機能: 19列の数理値・真偽・実追加前後の線を全人工行で独立照合する。
    引数: config/prepared/output(dict)。
    返り値: dict。判定行と実追加行数。金融収益の合格判定ではない。
    """
    key=next(iter(prepared)); symbol=key[1]; item=prepared[key]; record=item['record']; signal=item['signal']
    side=int(output['growth_cohorts'][0,3]) if len(output['growth_cohorts']) else 1
    value=F(1000 if symbol=='TOPIX' else 10); tick=record['tick']
    gates=output['growth_gate_state_trace']; states=output['growth_state_trace']
    assert gates.shape==(len(record['time_s']),19) and len(output['growth_gate_state_columns'])==19
    expected_columns=['parent_id','cushion_basis','cushion_initial_multiple','preserve_stop','initial_width',
        'required_cushion','old_stop_after_normal_update','planned_stop','planned_net_at_old_stop','risk_budget',
        'cushion_allowed','budget_at_old_allowed','stop_preserved','base_eligible','eligible',
        'actual_added_quantity','actual_fill_old_stop','actual_fill_new_stop','actual_fill_tightened']
    assert output['growth_gate_state_columns']==expected_columns
    width=F(str(max(2,math.ceil(item['reference_open']*.001/tick-1e-10))*tick))
    trail=F(str(signal['trend_width'])); basis=int(config.get('trend_growth_cushion_basis','ticks')=='initial_width')
    multiple=F(str(config.get('trend_growth_cushion_initial_multiple',0.)))
    required=multiple*width if basis else F(str(config['trend_growth_mode']*tick))
    preserve=bool(config.get('trend_growth_preserve_stop',False))
    judged=filled=0; details=[]
    for row,(raw_gate,raw_state) in enumerate(zip(gates,states)):
        gate=named(raw_gate,expected_columns); state=named(raw_state,output['growth_state_columns'])
        assert gate['parent_id']==state['parent_id']
        assert gate['risk_budget']==state['risk_budget'] or np.isnan(gate['risk_budget']) and np.isnan(state['risk_budget'])
        assert gate['cushion_basis']==basis
        assert gate['cushion_initial_multiple']==float(multiple) if basis else np.isnan(gate['cushion_initial_multiple'])
        assert gate['preserve_stop']==preserve and gate['initial_width']==float(width)
        assert gate['required_cushion']==float(required)
        assert gate['actual_added_quantity']>=0 and int(gate['actual_added_quantity'])==gate['actual_added_quantity']
        if gate['actual_added_quantity']:
            assert row>0
            prior=named(states[row-1],output['growth_state_columns'])
            assert gate['actual_fill_old_stop']==prior['effective_stop']
            cash=F(str(state['entry_cash'])); q=int(state['held_quantity']); cost=int(state['total_fees'])
            expected=lines(side,q,cash,cost,F(str(state['risk_budget'])),F(str(state['initial_line'])),
                F(str(prior['price_peak'])),trail,F(str(prior['effective_stop'])),bool(prior['protection_active']),
                F(str(state['liquidation_quote'])),int(state['initial_quantity']),width,value,tick,
                bool(config['trend_protection_mode']))
            assert gate['actual_fill_new_stop']==float(expected[2])
            assert bool(gate['actual_fill_tightened'])==(side*(expected[2]-F(str(prior['effective_stop'])))>0)
            assert int(gate['actual_added_quantity'])==int(state['held_quantity']-prior['held_quantity'])
            filled+=1
        else:
            assert np.all(np.isnan(raw_gate[16:])), ('未約定行の実fill線',row)
        if not np.isfinite(gate['old_stop_after_normal_update']):
            assert np.all(np.isnan(raw_gate[6:9])) and np.all(np.isnan(raw_gate[10:15]))
            continue
        q=int(state['held_quantity']); delta=min(q,int(state['maximum_quantity'])-q); total=q+delta
        assert delta>0
        quote=F(str(record['bid' if side==1 else 'ask'][row])); entry=F(str(record['ask' if side==1 else 'bid'][row]))
        cash=F(str(state['entry_cash'])); cost=int(state['entry_fees'])+fee(delta,symbol)+fee(total,symbol)
        cash_proposed=cash+delta*entry*value; old=F(str(gate['old_stop_after_normal_update']))
        risk=F(str(state['risk_budget']))
        expected=lines(side,total,cash_proposed,cost,risk,F(str(state['initial_line'])),F(str(state['price_peak'])),
            trail,old,bool(state['protection_active']),quote,int(state['initial_quantity']),width,value,tick,
            bool(config['trend_protection_mode']))
        net_old=side*(total*old*value-cash_proposed)-cost
        assert gate['planned_stop']==float(expected[2]) and gate['planned_net_at_old_stop']==float(net_old)
        cushion=side*(quote-expected[2]); allowed=cushion>=required
        budget_ok=net_old>=-risk; preserved=expected[2]==old
        assert bool(gate['cushion_allowed'])==allowed
        assert bool(gate['budget_at_old_allowed'])==budget_ok
        assert bool(gate['stop_preserved'])==preserved
        assert state['proposed_cash']==float(cash_proposed) and state['proposed_fees']==cost
        assert state['proposed_stop']==float(expected[2]) and state['proposed_cushion']==float(cushion)
        assert gate['old_stop_after_normal_update']==state['effective_stop']
        observed=raw_state[60:70]; anchor=raw_state[50:60]; last=int(state['last_fill_row'])
        pair=np.isfinite(observed).all() and observed[0]>=0 and observed[1]>=0 and observed[5]>=0 and observed[6]>=0 \
            and observed[3]>0 and observed[4]>observed[3] and observed[8]>0 and observed[9]>observed[8] \
            and observed[7]<=observed[2]+1e-8 and signal['entry_peer_bbo'][row,5]>0
        fresh=bool(pair and state['anchor_valid'] and observed[0]>anchor[0] and observed[1]>anchor[1]
            and observed[2]>record['time_s'][last] and observed[2]>anchor[2] and observed[5]>anchor[5]
            and observed[6]>anchor[6] and observed[7]>record['time_s'][last] and observed[7]>anchor[7])
        progress=bool(fresh and all(side*(observed[k]-anchor[k])>=t-t*1e-8
            for k,t in ((3,tick),(4,tick),(8,signal['peer_tick']),(9,signal['peer_tick']))))
        assert bool(state['pair_valid'])==bool(pair) and bool(state['fresh_sources'])==fresh
        assert bool(state['quotes_progress'])==progress
        current_net=side*(q*quote*value-cash)-int(state['total_fees'])
        proposed_net=side*(total*quote*value-cash_proposed)-cost
        restored=np.any((output['growth_events'][:,0]==row)&(output['growth_events'][:,1]==5))
        before_pending=row>0 and states[row-1,3]>0 and not gate['actual_added_quantity']
        current_allowed=bool(item['trend_lp_allowed'][side][row])
        expected_base=bool(not restored and row>last and not before_pending and signal['quality'][row]
            and not signal['reset'][row] and record['time_s'][row]<record['limit']-300.
            and current_allowed and pair and progress and current_net>=0 and proposed_net>=0)
        assert bool(gate['base_eligible'])==expected_base, ('base',row,gate,expected_base)
        expected_eligible=expected_base and allowed and (not preserve or budget_ok and preserved)
        assert bool(gate['eligible'])==bool(expected_eligible)
        assert bool(state['eligible'])==bool(expected_eligible)
        assert bool(state['net_allowed'])==(current_net>=0 and proposed_net>=0)
        if expected_eligible: assert state['pending_quantity']==delta
        details.append(dict(行=row,通常線=float(old),提案線=float(expected[2]),予算可否=bool(budget_ok),
            据置可否=bool(preserved),余裕可否=bool(allowed),基本資格=expected_base,追加可否=bool(expected_eligible)))
        judged+=1
    return {'19列判定行':judged,'実追加前後線':filled,'行診断':details}


def additions(output: dict) -> np.ndarray:
    """
    機能: 私有人工の実追加群だけを抽出する。
    引数: output(dict)。
    返り値: ndarray。予約は実約定へ含めない。
    """
    return output['growth_cohorts'][output['growth_cohorts'][:,23]==1]


def main() -> None:
    """
    機能: 局所人工と独立数理を検証し、新規の証跡だけ保存する。
    引数: なし。
    返り値: None。正式102損益・実原板・過去報告を開かない。
    """
    paths=[Path(__file__),BASE/'engine.py',BASE/'strategy.py',BASE/'catalog.py',BASE/'結果前の設計案.json',
        BASE/'実装前の仕様明確化.json',BASE/'結果前の数理明確化.json',
        ROOT/'work/wave_v101/review_pre/新しい101実装反証_局所状態と現金及び未来.py',
        ROOT/'work/wave_v101/strategy.py',ROOT/'work/wave_v101/engine.py',
        HERE/'初期幅余裕と旧停止線保全の独立仕様反証.json',
        HERE/'新主T0と保持した初版及び20条件の損益前独立再結合.json']
    before={p.relative_to(ROOT).as_posix():digest(p) for p in paths}
    strategy=module('102私有人工と19列の反証本体',BASE/'strategy.py')
    catalog=module('102私有人工の20条件',BASE/'catalog.py')
    old=module('101旧8だけの私有人工反証本体',ROOT/'work/wave_v101/strategy.py')
    cash=module('101独立現金検算の読取再使用102',ROOT/'work/wave_v101/review_pre/新しい101実装反証_局所状態と現金及び未来.py')
    configs={v['id']:v for v in catalog.catalog()}
    counts=dict(全20買売両商品=0,実fill19線=0,旧8局所null=0,
        T1通常更新後の比較=0,費用床だけで据置拒否=0,拒否後状態保持=0,
        予約後資格悪化でも実fill=0,不利実fillを巻き戻さない=0,人工prefix未来=0)
    counts['19列全行数理及び真偽']=0
    examples=[]

    # ----------------------------------------
    # 全20の私有人工。旧8だけは101の同条件と全共通金融及び状態列を一致させる。
    for config in configs.values():
        for symbol in catalog.SYMBOLS:
            for side in (-1,1):
                data=fixture(symbol,side); result=run(strategy,config,data)
                cash.verify_cash(result,data,config)
                checked=check19(config,data,result)
                counts['全20買売両商品']+=1
                counts['19列全行数理及び真偽']+=checked['19列判定行']
                counts['実fill19線']+=checked['実追加前後線']
                if not config['id'].startswith('B'):
                    previous=run(old,catalog.PREVIOUS[config['previous_growth_id']],data)
                    for name,value in previous.items():
                        if isinstance(value,np.ndarray): np.testing.assert_array_equal(result[name],value)
                        elif name.endswith('columns') or name.endswith('codes'): assert result[name]==value
                    assert result['entry_support_input_SHA256']==previous['entry_support_input_SHA256']
                    counts['旧8局所null']+=1
    assert counts['全20買売両商品']==80 and counts['旧8局所null']==32

    # ----------------------------------------
    # 当該行の通常追尾、拒否状態、active床の分離、成行判断後の資格変更を独立入力で確認。
    config=configs['B1_T1_Q1_X3']
    for symbol in catalog.SYMBOLS:
        for side in (-1,1):
            data=fixture(symbol,side); output=run(strategy,config,data); gate=output['growth_gate_state_trace']; state=output['growth_state_trace']
            added=additions(output); assert len(added)
            decision,fill=int(added[0,5]),int(added[0,8])
            rejected=np.flatnonzero((gate[:,13]==1)&(gate[:,10]==1)&(gate[:,12]==0)); assert len(rejected)
            first=int(rejected[0]); assert first<decision
            for index in (0,2,6,7,8,15,16,17,25,30,31):
                np.testing.assert_array_equal(state[first:decision+1,index],np.full(decision-first+1,state[first,index]))
            np.testing.assert_array_equal(state[first:decision+1,50:60],np.broadcast_to(state[first,50:60],(decision-first+1,10)))
            counts['拒否後状態保持']+=1
            rows=np.flatnonzero((gate[1:,14]==1)&(side*(gate[1:,6]-state[:-1,24])>0))+1
            assert len(rows) and np.all(gate[rows,6]==gate[rows,7]); counts['T1通常更新後の比較']+=1
            rows=np.flatnonzero((gate[:,13]==1)&(gate[:,11]==1)&(gate[:,12]==0)&(state[:,22]==1)
                &(side*(state[:,38]-gate[:,6])<=0)&(side*(state[:,39]-gate[:,6])>0))
            if len(rows):
                counts['費用床だけで据置拒否']+=1
                examples.append(dict(種類='予算だけ通るがactive床で据置拒否',商品=symbol,方向=side,行=int(rows[0]),
                    旧線=float(gate[rows[0],6]),提案予算線=float(state[rows[0],38]),提案費用床=float(state[rows[0],39])))
            for failure in ('peer','support','reset','quality','buffer'):
                altered=deepcopy(data); value=altered[next(iter(altered))]
                if failure=='peer': value['signal']['entry_peer_bbo'][fill,5]=0.
                elif failure=='support': value['trend_lp_allowed'][side][fill]=False
                elif failure=='reset': value['signal']['reset'][fill]=True
                elif failure=='quality': value['signal']['quality'][fill]=False
                else:
                    shift=-side*10.*gate[decision,4]
                    value['record']['bid'][fill]+=shift;value['record']['ask'][fill]+=shift
                    value['record']['price'][fill]=.5*(value['record']['bid'][fill]+value['record']['ask'][fill])
                changed=run(strategy,config,altered); actual=additions(changed)
                assert len(actual) and (int(actual[0,5]),int(actual[0,8]))==(decision,fill)
                assert actual[0,11]==value['record']['ask' if side==1 else 'bid'][fill]
                cash.verify_cash(changed,altered,config); check19(config,altered,changed)
                counts['予約後資格悪化でも実fill']+=1
            altered=deepcopy(data); value=altered[next(iter(altered))]
            value['record']['bid'][fill]+=side*20.*gate[decision,4]
            value['record']['ask'][fill]+=side*20.*gate[decision,4]
            value['record']['price'][fill]=.5*(value['record']['bid'][fill]+value['record']['ask'][fill])
            changed=run(strategy,config,altered); actual=additions(changed)
            assert len(actual) and (int(actual[0,5]),int(actual[0,8]))==(decision,fill)
            assert changed['growth_gate_state_trace'][fill,18]==1
            cash.verify_cash(changed,altered,config); check19(config,altered,changed)
            counts['不利実fillを巻き戻さない']+=1
            examples.append(dict(種類='判断据置でも次の不利実fillで線変更',商品=symbol,方向=side,
                判断行=decision,実約定行=fill,実前線=float(changed['growth_gate_state_trace'][fill,16]),
                実後線=float(changed['growth_gate_state_trace'][fill,17])))
    assert counts['費用床だけで据置拒否']>=2

    # ----------------------------------------
    # 19列も原行接頭と未来BBO/peer/LP改変に不変。閉鎖後cohortnetを判断へ戻さない。
    config=configs['B1_T0_Q1_X1']; data=fixture('TOPIX',1); whole=run(strategy,config,data); key=next(iter(data))
    for cut in (3,5,7,9,11,13):
        prefix=deepcopy(data)
        for name,array in prefix[key]['record'].items():
            if isinstance(array,np.ndarray): prefix[key]['record'][name]=array[:cut].copy()
        for name in ('mapped','event','quality','reset'): prefix[key]['signal'][name]=prefix[key]['signal'][name][:cut].copy()
        before_cut=run(strategy,config,prefix)
        poison=deepcopy(data); poison[key]['record']['bid'][cut:]+=1000.; poison[key]['record']['ask'][cut:]+=1000.
        poison[key]['signal']['entry_peer_bbo'][cut:,3:5]+=1000.;poison[key]['trend_lp_allowed'][1][cut:]=False
        changed=run(strategy,config,poison)
        for name in ('curve','target_trace','growth_state_trace','growth_gate_state_trace'):
            np.testing.assert_array_equal(before_cut[name],whole[name][:cut]);np.testing.assert_array_equal(changed[name][:cut],whole[name][:cut])
        for name in ('orders','growth_events'):
            expected=whole[name][whole[name][:,0]<cut]
            np.testing.assert_array_equal(before_cut[name],expected);np.testing.assert_array_equal(changed[name][changed[name][:,0]<cut],expected)
        counts['人工prefix未来']+=1
    ending={p.relative_to(ROOT).as_posix():digest(p) for p in paths};assert before==ending
    result=dict(全合格=True,種類='102本体の新金融前局所独立反証',主=catalog.PRIMARY,条件数=20,
        検査件数=counts,例=examples,開始と終端SHA一致=True,SHA256=ending,
        独立性='私有短列入力・全停止線と19列のFraction oracle。engine自己検査とfixture及び期待出力を使わない。'
                 '旧101の独立reviewの全cohort/親/実保有現金検算のみ再使用。',
        限界='人工のLP支持bool注入。実入力窓・真受信順・実全原板の因果性及び収益性はここでは認定しない。'
             'R0は価格線の理論net予算であり次成行実損失上限ではない。',
        正式新損益閲覧=0,正式新損益実行=0,実原板読取=0,現在API取得=0,実注文=0,過去成果変更=0)
    (HERE/'局所人工の新余裕と据置及び19列の独立反証.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,検査件数=counts),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
