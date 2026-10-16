"""既知全場で、固定配分の補完性・親別損益・負け場を比較する。"""

from datetime import datetime
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK))
import research
import selection


def clean(value):
    """
    機能: 診断計算のNumPy数値を同じ値のJSON標準数値へ変換する。
    引数: value(object)。
    返り値: object。売買台帳と数値は変更しない。
    """
    if isinstance(value,dict):
        return {key:clean(item) for key,item in value.items()}
    if isinstance(value,list):
        return [clean(item) for item in value]
    if isinstance(value,np.generic):
        return value.item()
    return value


def correlation(x, y):
    """
    機能: 共通で有効な系列だけを相関に使い、定数なら未定義とする。
    引数: x/y(ndarray)。
    返り値: float又はNone。
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x)<2 or np.std(x)==0 or np.std(y)==0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def read_ledger(identifier, result):
    """
    機能: 会計台帳の内容指紋を確認して読む。
    引数: identifier(str)、result(dict)。
    返り値: dict。
    """
    path = WORK/'ledgers'/f'{identifier}.pkl'
    assert research.sha(path) == result['ledger_SHA256']
    with path.open('rb') as stream:
        return pickle.load(stream)


def source_parts(ledgers, fixed):
    """
    機能: 手法間で親をまとめず、各源の利益・損失を期間別に残す。
    引数: ledgers(dict)、fixed(dict)。
    返り値: dict。
    """
    result = {}
    for period in ('前16','後14','全30'):
        result[period] = {}
        for symbol in ('TOPIX','NK225'):
            result[period][symbol] = {}
            for source in research.SOURCES:
                parents = [p for key, ledger in ledgers.items() if key[1]==symbol and key[0] in fixed[period]
                           for p in ledger['parents'] if p['source']==source]
                profit = sum(p['net'] for p in parents if p['net']>0)
                loss = -sum(p['net'] for p in parents if p['net']<0)
                result[period][symbol][source] = dict(net=profit-loss, profit=profit, loss=loss,
                    campaigns=len(parents), profit_share=profit/(profit+loss) if profit+loss else None)
    return result


def diversity(data, results):
    """
    機能: 同じ入力時計による時価増分と保有方向から、三源の補完性を測る。
    引数: data(dict)、results(dict)。
    返り値: dict。全30の事後診断であり売買や参考配分の選定には使わない。
    """
    singles = dict(GU='A1000', M3='A00100', C03='A00010')
    ledgers = {s:read_ledger(identifier, results[identifier]) for s, identifier in singles.items()}
    out = {}
    for symbol in ('TOPIX','NK225'):
        pair_rows = []
        for a, b in (('GU','M3'),('GU','C03'),('M3','C03')):
            changes_a, changes_b, signs_a, signs_b = [], [], [], []
            days_a, days_b = [], []
            for key in sorted(k for k in data if k[1]==symbol):
                la, lb = ledgers[a][key], ledgers[b][key]
                sa, sb = la['samples'], lb['samples']
                np.testing.assert_array_equal(sa['times'], sb['times'])
                np.testing.assert_array_equal(sa['rows'], sb['rows'])
                valid = sa['valid'] & sb['valid']
                consecutive = valid[1:] & valid[:-1]
                changes_a.extend(np.diff(sa['values'])[consecutive])
                changes_b.extend(np.diff(sb['values'])[consecutive])
                positions = []
                for source, ledger in ((a,la),(b,lb)):
                    state = ledger['cash_position_changes']
                    index = np.searchsorted(state[:,0], sa['rows'], side='right')-1
                    assert np.all(index[valid]>=0)
                    positions.append(np.sign(state[np.maximum(index,0), 4+research.SOURCES.index(source)]).astype(int)[valid])
                signs_a.extend(positions[0]);signs_b.extend(positions[1])
                days_a.append(next(r['net'] for r in results[singles[a]]['rows'] if (r['session'],r['symbol'])==key))
                days_b.append(next(r['net'] for r in results[singles[b]]['rows'] if (r['session'],r['symbol'])==key))
            pa, pb = np.asarray(signs_a), np.asarray(signs_b)
            both = (pa!=0)&(pb!=0)
            either = (pa!=0)|(pb!=0)
            pair_rows.append(dict(sources=[a,b], session_correlation=correlation(days_a,days_b),
                minute_correlation=correlation(changes_a,changes_b), minute_return_count=len(changes_a),
                mutual_active_fraction=float(both.sum()/either.sum()) if either.any() else None,
                same_active_fraction=float(((pa==pb)&both).sum()/both.sum()) if both.any() else None,
                opposite_active_fraction=float(((pa==-pb)&both).sum()/both.sum()) if both.any() else None))
        out[symbol] = dict(pairs=pair_rows, 分母='共通1分格子。相互保有割合は両方保有/どちらか保有。同方向・逆方向割合は両方保有の時だけ。価格が180秒より古い格子は除外。')
    return out


def diagnose(identifier, result, ledgers, data):
    """
    機能: 赤字上位3場を商品別に取り出し、源別収支と負け親の実時刻を示す。
    引数: identifier(str)、result/ledgers/data(dict)。
    返り値: dict。未来の反転は入口条件に使わない。
    """
    out = {}
    for symbol in ('TOPIX','NK225'):
        worst = sorted([r for r in result['rows'] if r['symbol']==symbol and r['net']<0], key=lambda r:r['net'])[:3]
        items = []
        for row in worst:
            key = row['session'], symbol
            ledger, ready = ledgers[key], data[key]
            parents = sorted([p for p in ledger['parents'] if p['net']<0], key=lambda p:p['net'])[:3]
            details = []
            for p in parents:
                stamp = lambda index:datetime.fromtimestamp(float(ready['time_s'][index]), ZoneInfo('Asia/Tokyo')).isoformat()
                entries = [o for o in ledger['orders'] if int(o[2])==research.SOURCES.index(p['source']) and int(o[3])==p['cid'] and o[8]==1]
                assert len(entries)==1
                legs = [leg for leg in ledger['legs'] if leg['source']==p['source'] and leg['cid']==p['cid']]
                details.append(dict(source=p['source'], cid=p['cid'], net=p['net'], quantity=p['initial_qty'], side=int(entries[0][4]),
                    entry_time=stamp(p['entry_row']), entry_price=float(entries[0][6]), final_exit_time=stamp(p['exit_row']),
                    exits=[dict(time=stamp(leg['exit_row']),price=leg['exit_price'],quantity=leg['quantity'],reason=leg['reason'],net=leg['net']) for leg in legs]))
            items.append(dict(session=row['session'], net=row['net'], sources=row['source_totals'], largest_losing_parents=details))
        out[symbol] = items
    return out


def risk_attribution(identifier, result, ledgers, data, fixed):
    """
    機能: 配分済みGUと同じ枚数の単独運転を復元し、単なる枚数削減と補完を分ける。
    引数: identifier(str)、result/ledgers/data/fixed(dict)。
    返り値: dict。保存実注文からの事後分解であり、新たな選定条件ではない。
    """
    components = []
    for key, ledger in ledgers.items():
        ready = data[key]
        state = ledger['cash_position_changes']
        indices = np.searchsorted(state[:,0], np.arange(len(ready['last'])), side='right')-1
        assert (indices>=0).all()
        cash, position = state[indices,1], state[indices,4]
        curve = cash+position*ready['last']*research.accounting.MULTIPLIERS[key[1]]-np.floor(abs(position)*research.accounting.FEES[key[1]]+1e-8)
        parents = [p for p in ledger['parents'] if p['source']=='GU']
        profit = sum(p['net'] for p in parents if p['net']>0)
        loss = -sum(p['net'] for p in parents if p['net']<0)
        orders = ledger['orders'][ledger['orders'][:,2]==0]
        row = dict(session=key[0],symbol=key[1],net=profit-loss,profit=profit,loss=loss,
            gross=sum(p['gross'] for p in parents),fees=sum(p['fees'] for p in parents), campaigns=len(parents),
            wins=int(sum(p['net']>0 for p in parents)), losses=int(sum(p['net']<0 for p in parents)),
            new_lots=int(orders[orders[:,8]==1,5].sum()),closed_lots=int(orders[orders[:,8]==0,5].sum()),
            max_long=int(np.maximum(position,0).max(initial=0)),max_short=int(np.maximum(-position,0).max(initial=0)),
            curve_min=float(curve.min(initial=0)),curve_max=float(curve.max(initial=0)),
            max_drawdown=float((np.maximum.accumulate(np.maximum(curve,0))-curve).max(initial=0)))
        np.testing.assert_allclose(curve[-1],row['net'],rtol=0,atol=1e-5)
        components.append(row)
    output = {}
    for period in ('前16','後14','全30'):
        output[period] = {}
        for symbol in ('TOPIX','NK225'):
            rows = sorted([r for r in components if r['symbol']==symbol and r['session'] in fixed[period]],key=lambda r:r['session'])
            gu = research.accounting.aggregate(rows,[(r['curve_min'],r['curve_max'],r['max_drawdown']) for r in rows])
            portfolio = result['periods'][period][symbol]
            output[period][symbol] = dict(allocated_gu_only=gu,portfolio=portfolio,
                net_change=portfolio['net']-gu['net'],drawdown_change=portfolio['max_drawdown']-gu['max_drawdown'],
                positive_sessions_change=portfolio['positive_sessions']-gu['positive_sessions'])
    return output


def main():
    """
    機能: 固定全22条件を読み、前半選定・全期間診断・目標達成を検算する。
    引数: なし。
    返り値: None。短い結論と再集計証拠JSONを保存する。
    """
    fixed = research.read(research.FIXED)
    research.validate(fixed)
    results = {c['id']:research.read(WORK/'results'/f'{c["id"]}.json') for c in fixed['catalog']}
    selected, proof = selection.select(results)
    data, feeds, hashes = research.inputs(verify=True)
    assert hashes == fixed['input_SHA256']
    parts, source_shares_check = {}, []
    for identifier, result in results.items():
        ledger = read_ledger(identifier, result)
        parts[identifier] = source_parts(ledger, fixed)
        for symbol in ('TOPIX','NK225'):
            for period in ('前16','後14','全30'):
                p = parts[identifier][period][symbol]
                stat = result['periods'][period][symbol]
                for key in ('net','profit','loss','campaigns'):
                    assert abs(sum(v[key] for v in p.values())-stat[key]) < 1e-5
                nonempty = [v['profit_share'] for v in p.values() if v['profit_share'] is not None]
                assert not nonempty or stat['profit_share'] <= max(nonempty)+1e-12
                source_shares_check.append(dict(id=identifier,symbol=symbol,period=period,合格=True))
    diagnoses = {identifier:diagnose(identifier,results[identifier],read_ledger(identifier,results[identifier]),data)
                 for identifier in dict.fromkeys([research.catalog.PRIMARY, selected]) if identifier is not None}
    risks = {identifier:risk_attribution(identifier,results[identifier],read_ledger(identifier,results[identifier]),data,fixed)
             for identifier in dict.fromkeys([research.catalog.PRIMARY, selected, 'A0820']) if identifier is not None}
    both80 = [identifier for identifier,r in results.items() if all(r['periods']['全30'][s]['profit_share'] is not None and r['periods']['全30'][s]['profit_share']>=.8 for s in ('TOPIX','NK225'))]
    stable = [identifier for identifier,r in results.items() if all(r['periods']['全30'][s]['net']>0 and r['periods']['前16'][s]['net']>0 and r['periods']['後14'][s]['net']>0 for s in ('TOPIX','NK225'))]
    conclusion = [
        '全30場での参考候補は追従8＋中期逆張り2（日経16＋4）。追従だけ10/20枚に比べ収支を約97%残し、最大下落はTOPIX9.4%・日経6.0%小さくなりました。これは全期間閲覧後の比較で、事前主案とは区別します。',
        '同じ8/16枚の追従だけに逆張りを追加すると、収支と最大下落はともに増加。黒字場はTOPIX21→18・日経18→19でした。枚数削減の効果と補完効果を分けると、全日安定を達成したとはいえません。',
        '事前主案の追従6・逆張り2・短期反転2は日経の後14場が−27,344円。短期反転C03が足を引っ張り、22条件すべて両銘柄の利益80%には未達です。']
    output = dict(全合格=True, primary=research.catalog.PRIMARY, selected=selected, selection_proof=proof,
        conditions=22, results=results, diversity=diversity(data,results), diagnosis=diagnoses, source_contributions=parts,
        risk_attribution=risks,
        both80=both80, both_positive_periods=stable, source_share_upper_bound_proof=source_shares_check,
        conclusion=conclusion, 入力SHA256=hashes, 既知全30=True,
        結果SHA256={identifier:research.sha(WORK/'results'/f'{identifier}.json') for identifier in results})
    research.save(HERE/'比較結果.json',clean(output))
    print(json.dumps(dict(主=output['primary'],前半選定=selected,金額八割=both80,期間両黒字=stable),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
