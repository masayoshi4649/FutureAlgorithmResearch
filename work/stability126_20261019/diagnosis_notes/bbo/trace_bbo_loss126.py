"""完成ＢＢＯ会計の最悪場と価格モデル悪化場だけを、保存実注文から診断する。"""

from datetime import datetime,timezone,timedelta
import hashlib
import io
import json
import math
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
ROOT = TASK.parents[1]
JST = timezone(timedelta(hours=9))
METHODS = ('E01','P02')
SYMBOLS = ('TOPIX','NK225')


def digest(path: Path) -> str:
    """
    機能: 明示保存資料の指紋を取得する。
    引数: path(Path)は今回の源又は完成小資料。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 金融を再生せず完成JSONだけを読む。
    引数: path(Path)は固定資料又は完成会計。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def primitive(value: object) -> object:
    """
    機能: 診断配列を有限JSONへ変換し、未知をNoneで残す。
    引数: value(object)は診断の値。
    返り値: objectはJSON互換値。未知を零損益へ補完しない。
    """
    if isinstance(value,dict): return {str(k):primitive(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [primitive(v) for v in value]
    if isinstance(value,np.ndarray): return primitive(value.tolist())
    if isinstance(value,np.generic): return primitive(value.item())
    if isinstance(value,float) and not math.isfinite(value): return None
    return value


def save(path: Path, value: dict) -> None:
    """
    機能: 診断専用の未使用先だけへ保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。登録済み源と完成会計を変更しない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(),str(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(primitive(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def clock(value: float) -> str:
    """
    機能: 代理価格時計を日本日時へ表示変換する。
    引数: value(float)は保存epoch秒。
    返り値: strは日時。実受信秒や通信遅延を意味しない。
    """
    return datetime.fromtimestamp(value,JST).isoformat(timespec='seconds')


def payload(ref: dict, log: list, purpose: str) -> bytes:
    """
    機能: 目的を限定した所有入力を一回読み、同bytesを検証する。
    引数: ref(dict)、log(list)、purpose(str)は保存参照と診断読取記録。
    返り値: bytesは所有保存値。市場原本や現在APIを読まない。
    """
    path = (ROOT/ref['path']).resolve()
    assert path.is_relative_to(ROOT/'work')
    value = path.read_bytes()
    assert hashlib.sha256(value).hexdigest() == ref['sha256'],ref['path']
    log.append(dict(path=ref['path'],sha256=ref['sha256'],reads=1,purpose=purpose))
    return value


def quote_snapshot(ready: dict, quotes: dict, row: int) -> dict:
    """
    機能: 指定原行の気配を資格付きで取得する。
    引数: ready/quotes(dict)、row(int)は同seq対応の保存資料。
    返り値: dictは当行Last/BBOと資格。未来の正常行で置き換えない。
    """
    bid,ask = float(quotes['bid'][row]),float(quotes['ask'][row])
    valid = bool(quotes['quote_valid'][row] and np.isfinite(bid) and np.isfinite(ask) and 0 < bid < ask)
    return dict(row=row,seq=int(ready['seq'][row]),time=clock(float(ready['time_s'][row])),
        price_time_s=float(ready['time_s'][row]),last=float(ready['last'][row]),
        bid=bid,ask=ask,quote_valid=valid,
        spread=ask-bid if valid else None,
        last_outside_bbo=bool(ready['last'][row] < bid or ready['last'][row] > ask) if valid else None)


def peer_snapshot(packet: dict, symbol: str, at: float) -> dict:
    """
    機能: 自己時計より厳密な過去の相手原行を取得する。
    引数: packet(dict)、symbol(str)、at(float)は当場保存値と自己価格時計。
    返り値: dictは相手資料。未知と十五秒超を有効な反対票に置き換えない。
    """
    other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    key = packet['session'],other
    ready,quotes = packet['inputs'][key],packet['quotes'][key]
    index = int(np.searchsorted(ready['time_s'],at,side='left')-1)
    if index < 0: return dict(symbol=other,known=False,reason='厳密過去の相手行なし')
    snap = quote_snapshot(ready,quotes,index)
    age = at-float(ready['time_s'][index])
    assert age > 0.
    snap.update(symbol=other,known=bool(snap['quote_valid'] and age <= 15.),
                age_proxy_seconds=age,public_atr=float(ready['atr'][index]))
    return snap


def first_match(mask: np.ndarray, start: int, ready: dict) -> dict | None:
    """
    機能: 保有区間内で初めて成立した保存条件の原行を得る。
    引数: mask(ndarray[bool])、start(int)、ready(dict)は診断条件と元資料。
    返り値: dict又はNoneは最初の行と価格時計。
    """
    where = np.flatnonzero(mask)
    if not len(where): return None
    row = int(where[0])+start
    return dict(row=row,seq=int(ready['seq'][row]),time=clock(float(ready['time_s'][row])))


def group_details(packet: dict, symbol: str, result: dict, last_result: dict) -> list[dict]:
    """
    機能: 実注文からＢＢＯ清算経路と新規負担、実予算停止を独立に復元する。
    引数: packet/result/last_result(dict)、symbol(str)は完成保存資料。
    返り値: list[dict]は各実組の因果入力と事後診断。新しい売買政策は計算しない。
    """
    key = packet['session'],symbol
    ready,quotes,market = packet['inputs'][key],packet['quotes'][key],packet['markets'][key]
    np.testing.assert_array_equal(ready['seq'],quotes['seq'])
    np.testing.assert_array_equal(ready['time_s'],quotes['time_s'])
    mult = 1000. if symbol == 'TOPIX' else 10.
    orders,cycles,events = result['orders'],result['cycles'],result['execution_events']
    last_orders,last_cycles = last_result['orders'],last_result['cycles']
    old = {int(c[0]):c for c in last_cycles}
    price = np.asarray(ready['last'])
    changed = np.r_[True,np.diff(price) != 0.]
    last_change = np.maximum.accumulate(np.where(changed,np.arange(len(price)),0))
    groups = []
    for cycle in cycles:
        cid,start,end = map(int,cycle[:3])
        owned = orders[orders[:,2] == cid]
        entry = owned[owned[:,7] == 1.]
        assert len(entry) == 1
        e = entry[0]
        entry_row,source = int(e[0]),int(e[1])
        assert entry_row == start and source < entry_row
        direction,quantity = int(e[3]),int(e[4])
        atr = float(cycle[5]); risk = quantity*atr*mult
        source_quote = quote_snapshot(ready,quotes,source)
        entry_quote = quote_snapshot(ready,quotes,entry_row)
        assert entry_quote['quote_valid']
        actual_entry = float(e[5])
        assert actual_entry == (entry_quote['ask'] if direction > 0 else entry_quote['bid'])
        adverse = direction*(actual_entry-source_quote['last'])
        same_side_source = (source_quote['ask'] if direction > 0 else source_quote['bid']) if source_quote['quote_valid'] else None
        delta_cash,delta_qty = np.zeros(end-start+1),np.zeros(end-start+1)
        for order in owned:
            j = int(order[0])-start
            assert 0 <= j < len(delta_cash)
            delta_cash[j] -= order[3]*order[4]*order[5]
            delta_qty[j] += order[3]*order[4]
        cash,qty = np.cumsum(delta_cash),np.cumsum(delta_qty)
        raw_bid,raw_ask = quotes['bid'][start:end+1],quotes['ask'][start:end+1]
        quote_valid = quotes['quote_valid'][start:end+1].copy()
        quote_valid &= np.isfinite(raw_bid) & np.isfinite(raw_ask) & (raw_bid > 0.) & (raw_ask > raw_bid)
        known = quote_valid | (qty == 0.)
        liquidation = np.full(len(qty),np.nan)
        liquidation[known] = cash[known]+np.where(qty[known] > 0.,qty[known]*raw_bid[known],qty[known]*raw_ask[known])
        equity = liquidation*mult
        assert known[-1] and np.isclose(equity[-1],cycle[3]*mult,atol=1e-5)
        peak_local = int(np.nanargmax(equity)); minimum_local = int(np.nanargmin(equity))
        peak_row,minimum_row = peak_local+start,minimum_local+start
        own_feature = market[start:end+1]
        against = own_feature[:,11] == 1.
        against &= np.arange(start,end+1) > start
        against &= own_feature[:,8] > ready['time_s'][start]
        for col,width in ((4,.05),(5,.1),(6,.05),(7,.1)):
            against &= direction*own_feature[:,col] < -width
        first_opposition = first_match(against,start,ready)
        if first_opposition:
            index = first_opposition['row']-start
            first_opposition['liquidation_pnl'] = float(equity[index]) if known[index] else None
        active_events = events[events[:,2] == cid]
        budget = active_events[(active_events[:,1] == 9.) & (active_events[:,13] == 32.)]
        floor = active_events[active_events[:,1] == 12.]
        forced = owned[(owned[:,7] == 0.) & (owned[:,6] == 32.)]
        budget_info = []
        for event in budget:
            row = int(event[0])
            budget_info.append(dict(row=row,time=clock(float(ready['time_s'][row])),
                rows_after_entry=row-start,proxy_seconds_after_entry=float(ready['time_s'][row]-ready['time_s'][start]),
                queued_on_entry=row == start,liquidation_pnl=float(event[5]*mult),risk=float(event[6]*mult)))
        peer_source = peer_snapshot(packet,symbol,float(ready['time_s'][source]))
        peer_entry = peer_snapshot(packet,symbol,float(ready['time_s'][start]))
        peer_response = None
        if peer_source.get('known') and peer_entry.get('known'):
            peer_response = dict(direction_bid_change=direction*(peer_entry['bid']-peer_source['bid']),
                                 direction_ask_change=direction*(peer_entry['ask']-peer_source['ask']))
        own_response = None
        if source_quote['quote_valid']:
            own_response = dict(direction_bid_change=direction*(entry_quote['bid']-source_quote['bid']),
                                direction_ask_change=direction*(entry_quote['ask']-source_quote['ask']))
        result_item = dict(campaign=cid,direction='買い' if direction > 0 else '売り',quantity=quantity,
            entry_row=start,source_row=source,source_time=source_quote['time'],entry_time=entry_quote['time'],
            source_seq=source_quote['seq'],entry_seq=entry_quote['seq'],source_last=source_quote['last'],entry_price=actual_entry,
            row_delay=start-source,original_seq_gap=entry_quote['seq']-source_quote['seq'],
            proxy_clock_delay_seconds=float(ready['time_s'][start]-ready['time_s'][source]),
            fixed_atr=atr,initial_risk_yen=risk,entry_spread=entry_quote['spread'],spread_atr=entry_quote['spread']/atr,
            source_spread=source_quote['spread'],adverse_from_signal_last=adverse,adverse_from_signal_last_atr=adverse/atr,
            adverse_from_signal_same_side_bbo=None if same_side_source is None else direction*(actual_entry-same_side_source),
            source_last_outside_bbo=source_quote['last_outside_bbo'],entry_last_outside_bbo=entry_quote['last_outside_bbo'],
            unchanged_last_rows=source-int(last_change[source])+1,
            unchanged_last_proxy_seconds=float(ready['time_s'][source]-ready['time_s'][last_change[source]]),
            source_quote=source_quote,entry_quote=entry_quote,peer_at_source=peer_source,peer_at_entry=peer_entry,
            self_quote_response=own_response,peer_quote_response=peer_response,
            source_market=market[source].tolist(),entry_market=market[start].tolist(),
            net=float(cycle[3]*mult),final_time=clock(float(ready['time_s'][end])),final_reason=int(cycle[9]),
            maximum_observed_liquidation_pnl=float(equity[peak_local]),peak_time=clock(float(ready['time_s'][peak_row])),
            peak_row=peak_row,minimum_observed_liquidation_pnl=float(equity[minimum_local]),
            minimum_time=clock(float(ready['time_s'][minimum_row])),positive_observed=bool(np.any(equity[known] > 0.)),
            unknown_quote_rows_while_held=int((~quote_valid & (qty != 0.)).sum()),
            observed_rows_while_held=int((quote_valid & (qty != 0.)).sum()),
            first_two_market_opposition=first_opposition,
            budget32=budget_info,budget32_queued_on_entry=any(item['queued_on_entry'] for item in budget_info),
            exit32_count=len(forced),floor_events=[dict(time=clock(float(ready['time_s'][int(v[0])])),values=v.tolist()) for v in floor],
            exits=[dict(row=int(o[0]),source_row=int(o[1]),time=clock(float(ready['time_s'][int(o[0])])),
                source_time=clock(float(ready['time_s'][int(o[1])])),price=float(o[5]),quantity=int(o[4]),reason=int(o[6]),
                row_delay=int(o[0]-o[1]),proxy_clock_delay_seconds=float(ready['time_s'][int(o[0])]-ready['time_s'][int(o[1])]))
                for o in owned if o[7] == 0.])
        if cid in old:
            prior = old[cid]
            prior_orders = last_orders[last_orders[:,2] == cid]
            old_entry = prior_orders[prior_orders[:,7] == 1.]
            assert len(old_entry) == 1
            assert int(old_entry[0,3]) == direction and int(old_entry[0,4]) == quantity
            entry_component = -direction*quantity*(actual_entry-old_entry[0,5])*mult
            delta = cycle[3]*mult-prior[3]*mult
            result_item['Last_comparison'] = dict(entry_time=clock(float(ready['time_s'][int(old_entry[0,0])])),
                entry_price=float(old_entry[0,5]),net=float(prior[3]*mult),delta=float(delta),
                entry_price_component=float(entry_component),exit_path_and_price_component=float(delta-entry_component),
                entry_judgment_same_row=int(old_entry[0,0]) == source,
                exits=[dict(time=clock(float(ready['time_s'][int(o[0])])),price=float(o[5]),quantity=int(o[4]),reason=int(o[6]))
                       for o in prior_orders if o[7] == 0.])
        else:
            result_item['Last_comparison'] = None
        groups.append(result_item)
    return sorted(groups,key=lambda item:item['net'])


def cohort_summary(groups: list[dict]) -> dict:
    """
    機能: 指定した損失診断群の当時観測特徴と最終会計を記述する。
    引数: groups(list[dict])は同商品同手法の選択済み診断組。
    返り値: dictは記述集計。見送り後の別売買や改善収支は計算しない。
    """
    def stats(items: list[dict]) -> dict:
        """
        機能: 明示した診断群の件数と保存収支を集計する。
        引数: items(list[dict])は明示部分群。
        返り値: dictは同群の記述値。
        """
        return dict(count=len(items),net=sum(g['net'] for g in items),
            losing=sum(g['net'] < 0. for g in items),winning=sum(g['net'] > 0. for g in items),
            never_positive=sum(not g['positive_observed'] for g in items),
            immediate_budget=sum(g['budget32_queued_on_entry'] for g in items))
    return dict(all=stats(groups),
        spread_at_least_one_atr=stats([g for g in groups if g['spread_atr'] >= 1.]),
        signal_last_outside_bbo=stats([g for g in groups if g['source_last_outside_bbo'] is True]),
        signal_last_inside_bbo=stats([g for g in groups if g['source_last_outside_bbo'] is False]),
        adverse_at_least_half_atr=stats([g for g in groups if g['adverse_from_signal_last_atr'] >= .5]),
        immediate_budget=stats([g for g in groups if g['budget32_queued_on_entry']]),
        loss_with_low_entry_burden=stats([g for g in groups if g['net'] < 0. and g['spread_atr'] < .5 and g['adverse_from_signal_last_atr'] < .5]))


def main() -> None:
    """
    機能: 金融を再実行せず、最悪場とLast価格モデルから悪化した場を一読診断する。
    引数: なし。
    返り値: None。固定した診断対象・全組・読取記録を専用JSONへ保存する。
    """
    paths = dict(bbo=TASK/'engine/bbo_next/全十六条件の次原行BBO会計.json',
        last=TASK/'原版と十五改修の全四十一場会計.json',
        prepared=TASK/'input_audit/attempt2/全四十一場の元入力と新市場特徴の非金融準備.json',
        baseline=TASK/'baseline/原版旧三十場の費用なし保存引用.json')
    data = {name:read(path) for name,path in paths.items()}
    refs = {name:dict(path=path.relative_to(ROOT).as_posix(),sha256=digest(path)) for name,path in paths.items()}
    last_lookup = {(r['method'],r['session'],r['symbol']):r for r in data['last']['rows']}
    bbo_lookup = {(r['method'],r['session'],r['symbol']):r for r in data['bbo']['rows']}
    selections,targets = [],set()
    for method in METHODS:
        for symbol in SYMBOLS:
            rows = [r for r in data['bbo']['rows'] if r['method'] == method and r['symbol'] == symbol]
            worst = sorted(rows,key=lambda r:(r['net'],r['session']))[:3]
            adverse = sorted(rows,key=lambda r:(r['net']-last_lookup[method,r['session'],symbol]['net'],r['session']))[:3]
            for kind,chosen in (('ＢＢＯ最悪三場',worst),('同手法Lastからの悪化三場',adverse)):
                for rank,row in enumerate(chosen,1):
                    targets.add((row['session'],symbol))
                    selections.append(dict(method=method,symbol=symbol,session=row['session'],kind=kind,rank=rank,
                        bbo=row['net'],last=last_lookup[method,row['session'],symbol]['net'],
                        delta=row['net']-last_lookup[method,row['session'],symbol]['net']))
    before = digest(Path(__file__))
    plan = dict(passed=True,metadata=refs,source_sha256=before,selections=selections,
        targets=[dict(session=s,symbol=y) for s,y in sorted(targets)],
        scope='原E01/P02各商品で最悪三場＋同手法Last→BBO悪化三場、重複を統合。選択場だけの原因診断。',
        financial_replays=0,original_market_reads=0,API=0)
    save(HERE/'最悪場と価格モデル悪化場の固定診断計画.json',plan)
    log,diagnosed = [],[]
    bbo_caches = {(r['session'],r['symbol']):r for r in data['bbo']['cache']}
    last_caches = {(r['session'],r['symbol']):r for r in data['last']['cache']}
    packet_refs = {r['session']:r for r in data['prepared']['packets']}
    old_keys = {(r['session'],r['symbol']) for r in data['baseline']['rows']}
    with np.load(io.BytesIO(payload(data['baseline']['cache'],log,'旧三十場原版注文の診断一読')),allow_pickle=False) as old_arrays:
        for scene in sorted({s for s,_ in targets}):
            packet = pickle.loads(payload(packet_refs[scene],log,'保存入力と両市場気配の損失診断'))
            assert packet['session'] == scene
            for symbol in SYMBOLS:
                key = scene,symbol
                if key not in targets: continue
                bbo_raw = payload(bbo_caches[key],log,'ＢＢＯ実注文と実予算の診断')
                last_raw = payload(last_caches[key],log,'同手法Last注文との記述比較')
                with np.load(io.BytesIO(bbo_raw),allow_pickle=False) as current, np.load(io.BytesIO(last_raw),allow_pickle=False) as prior:
                    for method in METHODS:
                        actual = {name:current[method+'__'+name] for name in ('orders','cycles','execution_events')}
                        if method == 'E01' and key in old_keys:
                            prefix = symbol+'_'+scene+'__'
                            virtual = {name:old_arrays[prefix+name] for name in ('orders','cycles')}
                        else:
                            virtual = {name:prior[method+'__'+name] for name in ('orders','cycles')}
                        groups = group_details(packet,symbol,actual,virtual)
                        assert np.isclose(sum(g['net'] for g in groups),bbo_lookup[method,scene,symbol]['net'],atol=1e-5)
                        diagnosed.append(dict(session=scene,symbol=symbol,method=method,
                            selection=[s for s in selections if (s['session'],s['symbol'],s['method']) == (scene,symbol,method)],
                            bbo_row=bbo_lookup[method,scene,symbol],last_row=last_lookup[method,scene,symbol],
                            groups=groups,summary=cohort_summary(groups)))
                del bbo_raw,last_raw
            del packet
    for name,path in paths.items(): assert digest(path) == refs[name]['sha256']
    assert digest(Path(__file__)) == before
    cohorts = {}
    for method in METHODS:
        for symbol in SYMBOLS:
            groups = [g for c in diagnosed if c['method'] == method and c['symbol'] == symbol for g in c['groups']]
            cohorts[method+'_'+symbol] = cohort_summary(groups)
    save(HERE/'最悪場とLast悪化場の実建値BBO診断.json',dict(passed=True,plan=plan,
        cases=diagnosed,cohorts=cohorts,diagnostic_read_log=log,
        proxy_clock_caution='CurrentPriceTimeの代理時計。０秒差は実遅延０ではない。相手は同時計を除外し十五秒以内だけ有効。',
        accounting_caution='清算MFEは当行正常BBOだけ。未知気配行を零や将来正常値で補完しない。比較群の削除後PLを改善成績として示さない。',
        financial_replays=0,original_market_reads=0,API=0,real_orders=0))
    print(json.dumps(dict(passed=True,product_scenes=len(targets),cases=len(diagnosed),reads=len(log),
        financial_replays=0,original_market_reads=0),ensure_ascii=False))


if __name__ == '__main__': main()
