"""同親の複数実新規と一括返済を、全注文及び原板から独立会計に戻す。"""

from fractions import Fraction
import numpy as np

import compare_utils as checks
import math_oracle as oracle


def expand(changes: np.ndarray, rows: int) -> np.ndarray:
    """
    機能: 保存疎形式の変化行を原行数へ独立展開する。
    引数: changes(ndarray[float])は行番号と状態、rows(int)は原行数。
    返り値: ndarray[float]。全行状態。初行又は変化順の異常で停止する。
    """
    changes = np.asarray(changes,float)
    indexes = changes[:,0].astype(int)
    assert len(indexes) > 0 and indexes[0] == 0 and (np.diff(indexes) > 0).all()
    assert ((indexes >= 0) & (indexes < rows)).all()
    return changes[np.searchsorted(indexes,np.arange(rows),side='right')-1,1:]


def curves(record: dict, orders: np.ndarray) -> tuple:
    """
    機能: 全実注文の売買現金を原行へ伝播し、同源の実Qで全行清算時価を算定する。
    引数: record(dict)は原板、orders(ndarray[float])は旧17列の全実注文。
    返り値: tuple。全行curve・源別curve・源別実保有数・源別現金。
    予約玉及び仮の追加価格は現金へ入れず、残玉返済料金は全量一注文で計算する。
    """
    n = len(record['time_s'])
    multiplier,fee_unit = (1000.,41.8) if record['symbol'] == 'TOPIX' else (10.,11.)
    cash,positions = np.zeros((n,2)),np.zeros((n,2))
    for source in range(2):
        rows,balances,quantities = [-1],[0.],[0.]
        balance,quantity = 0.,0.
        for order in orders[orders[:,3] == source]:
            row = int(order[0])
            balance -= order[4]*order[5]*order[6]*multiplier+order[9]
            quantity += order[4]*order[5]
            if rows[-1] == row:
                balances[-1],quantities[-1] = balance,quantity
            else:
                rows.append(row)
                balances.append(balance)
                quantities.append(quantity)
        offsets = np.searchsorted(rows,np.arange(n),side='right')-1
        cash[:,source] = np.asarray(balances)[offsets]
        positions[:,source] = np.asarray(quantities)[offsets]
    qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    qok &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    observed = np.maximum.accumulate(np.where(qok,np.arange(n),-1))
    equity = cash.copy()
    for source in range(2):
        holding = positions[:,source] != 0
        assert (observed[holding] >= 0).all()
        known = observed[holding]
        quantity = positions[holding,source]
        liquidation = np.where(quantity > 0,record['bid'][known],record['ask'][known])
        equity[holding,source] += quantity*liquidation*multiplier-np.floor(np.abs(quantity)*fee_unit+1e-8)
    return equity.sum(axis=1),equity,positions,cash


def next_normal(record: dict, order: np.ndarray) -> int:
    """
    機能: 公開済み判断行の後の最初正常気配を、場末代理判断と区別して求める。
    引数: record(dict)、order(ndarray[float])は旧17列注文。
    返り値: int。最初の実fill可能行。価格時計等号を真受信時刻と誤認しない。
    """
    decision,reason = int(order[1]),int(order[8])
    times = record['time_s']
    begin = decision+1
    if reason == 4 and order[10] == record['limit']-60.:
        begin = max(begin,int(np.searchsorted(times,order[10],side='left')))
    qok = record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
    qok &= (record['bid'] > 0) & (record['ask'] > record['bid'])
    rows = np.flatnonzero(qok[begin:])
    assert len(rows), '判断後の正常気配がない実fill'
    return begin+int(rows[0])


def cohort_rows(output: dict) -> tuple[np.ndarray, dict[str,int]]:
    """
    機能: 新cohortを列名で解釈し、契約欠落を検出する。
    引数: output(dict)は本体又は保存台帳。
    返り値: tuple[ndarray,dict]。列定義の順序を暗黙推測しない。
    """
    columns = output['growth_cohort_columns']
    assert len(set(columns)) == len(columns)
    index = {name:i for i,name in enumerate(columns)}
    required = {'parent_id','cohort_id','source','side','quantity','entry_row','entry_price',
                'entry_fee','exit_row','exit_price','exit_fee_share','gross','net'}
    assert required <= set(index), required-set(index)
    return np.asarray(output['growth_cohorts'],float).reshape(-1,len(columns)),index


def verify_account(record: dict, config: dict, output: dict, complete: bool = True) -> dict:
    """
    機能: 実注文から各cohort・親・料金・加重価格・次BBO・全原板現金を独立再算定する。
    引数: record/config/output(dict)、complete(bool)は場終端か未完接頭か。
    返り値: dict。独立親/curve/cohort損益と検査件数。latent診断を正答生成には使わない。
    """
    symbol = record['symbol']
    multiplier,fee_unit,maximum,user_cap = (1000,41.8,8,10) if symbol == 'TOPIX' else (10,11,16,20)
    initial_quantity = oracle.quantity_for(config,symbol)
    orders = np.asarray(output['orders'],float).reshape(-1,17)
    actual_trades = np.asarray(output['trades'],float).reshape(-1,16)
    actual_cohorts,index = cohort_rows(output)
    assert np.isfinite(orders).all() and np.isfinite(actual_trades).all()
    assert (np.diff(orders[:,0]) >= 0).all()
    opened,rebuilt,closed,nets = {},[],set(),{}
    for order in orders:
        row,decision,parent,source,side,qty = map(int,order[:6])
        new,reason = int(order[7]),int(order[8])
        assert 0 <= decision < row < len(record['time_s']) and source == 0 and side in (-1,1)
        assert qty > 0 and order[5] == qty and order[9] == oracle.order_fee(qty,fee_unit)
        assert order[11] == record['time_s'][row] and order[14] == 0
        assert order[6] == (record['ask'][row] if side == 1 else record['bid'][row])
        assert row == next_normal(record,order), (config['id'],parent,row,'次正常気配以外で実fill')
        if reason == 4 and order[10] == record['limit']-60.:
            assert record['time_s'][decision] < order[10] <= order[11]
        else:
            assert order[10] == record['time_s'][decision]
        selected = actual_cohorts[(actual_cohorts[:,index['parent_id']] == parent)
                                  & (actual_cohorts[:,index['entry_row']] == row)]
        if new:
            assert len(selected) == 1 and parent not in closed and order[15] == side
            observed = selected[0]
            item = oracle.Cohort(int(observed[index['cohort_id']]),qty,oracle.rational(order[6]),int(order[9]))
            checks.exact(observed[[index[name] for name in ('source','side','quantity','entry_price','entry_fee')]],
                         [source,side,qty,order[6],order[9]],'cohort実新規対応')
            if parent not in opened:
                assert qty == initial_quantity and reason != 16
                opened[parent] = dict(entries=[order],cohorts=[item],side=side)
            else:
                campaign = opened[parent]
                assert config['trend_growth_mode'] in (1,2) and reason == 16 and side == campaign['side']
                assert item.ordinal > campaign['cohorts'][-1].ordinal
                holding = sum(c.quantity for c in campaign['cohorts'])
                assert qty == oracle.next_quantity(holding,maximum)
                campaign['entries'].append(order)
                campaign['cohorts'].append(item)
            assert sum(c.quantity for c in opened[parent]['cohorts']) <= maximum <= user_cap
        else:
            assert parent in opened and reason in (1,2,3,4)
            campaign = opened.pop(parent)
            entries,items = campaign['entries'],campaign['cohorts']
            first = entries[0]
            assert qty == sum(c.quantity for c in items) and side == -campaign['side']
            assert order[15] == first[4] and order[13] == first[13]
            facts = oracle.completed_cohorts(items,order[6],int(first[4]),multiplier,fee_unit)
            accounting = oracle.totals(items,multiplier,fee_unit)
            gross = facts['parent_net']+accounting['F']
            rebuilt.append([parent,source,first[0],row,first[4],qty,float(accounting['weighted_entry']),order[6],
                            accounting['entry_fee'],order[9],float(gross),float(facts['parent_net']),
                            first[8],reason,first[13],first[1]])
            for item in items:
                observed = actual_cohorts[(actual_cohorts[:,index['parent_id']] == parent)
                                          & (actual_cohorts[:,index['cohort_id']] == item.ordinal)]
                assert len(observed) == 1
                observed = observed[0]
                checks.exact(observed[[index[name] for name in ('exit_row','exit_price','exit_fee_share')]],
                             [row,order[6],facts['close_fees'][item.ordinal]],'cohort実返済と固定最大剰余')
                own_gross = campaign['side']*item.quantity*(oracle.rational(order[6])-item.price)*multiplier
                checks.money(observed[index['gross']],float(own_gross),'cohort価格損益')
                checks.money(observed[index['net']],float(facts['nets'][item.ordinal]),'cohort純損益')
                nets[parent,item.ordinal] = facts['nets'][item.ordinal]
            closed.add(parent)
    rebuilt = np.asarray(rebuilt,float).reshape(-1,16)
    # ----------------------------------------
    # 本案は呼値価格と2の冪の数量なので加重価格も厳密比較し、金額の演算順だけ公差を使う。
    strict = [0,1,2,3,4,5,6,7,8,9,12,13,14,15]
    checks.exact(actual_trades[:,strict],rebuilt[:,strict],'親の実源・数量・料金・返済')
    checks.money(actual_trades[:,[10,11]],rebuilt[:,[10,11]],'全玉親損益')
    expected_curve,source_curve,positions,cash = curves(record,orders)
    checks.money(output['curve'],expected_curve,'全原板清算時価')
    checks.money(output['source_curve'],source_curve,'全原板源別時価')
    trace = np.asarray(output['target_trace'],float)
    checks.exact(trace[:,0],np.maximum(positions,0).sum(axis=1),'実買い枚数')
    checks.exact(trace[:,1],np.maximum(-positions,0).sum(axis=1),'実売り枚数')
    assert (trace >= 0).all() and trace[:,2:4].max(initial=0) <= maximum
    assert trace[:,:4].max(initial=0) <= user_cap
    if complete:
        assert not opened and len(orders) == len(actual_cohorts)+len(rebuilt)
        assert not trace[-1].any() and not positions[-1].any()
        assert len(nets) == len(actual_cohorts)
        checks.money(expected_curve[-1],rebuilt[:,11].sum(),'全玉終端と親net')
    return dict(trades=rebuilt,curve=expected_curve,source_curve=source_curve,positions=positions,cash=cash,
                cohort_net=nets,counts=dict(注文=len(orders),決済親=len(rebuilt),cohort=len(actual_cohorts),
                                            全原板会計=len(record['time_s'])),未完親=len(opened))
