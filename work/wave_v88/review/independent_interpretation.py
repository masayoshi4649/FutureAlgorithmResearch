"""凍結実注文から会計・下落・相関を独立復元し、配分の解釈を検査する。"""

from pathlib import Path
import hashlib
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
NAMES = ('GU', 'M3', 'C03')


def read(path):
    """
    機能: 日本語JSONを読取専用で読む。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 検査対象の保存内容を指紋化する。
    引数: path(Path)。
    返り値: str。
    """
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def equal(a, b):
    """
    機能: 独立集計の値と公表値を許容誤差内で照合する。
    引数: a/b(float又はNone)。
    返り値: None。不一致なら例外。
    """
    if a is None or b is None:
        assert a is None and b is None
    else:
        np.testing.assert_allclose(a, b, rtol=0, atol=1e-5)


def independent_account(ready, ledger, curves):
    """
    機能: 保存実注文だけから親別損益と必要なら全原板清算時価を復元する。
    引数: ready/ledger(dict)、curves(bool)。
    返り値: tuple[dict,dict,ndarray又はNone,ndarray又はNone]。
    """
    symbol = ready['symbol']
    multiplier = 1000 if symbol == 'TOPIX' else 10
    fee_cents = 4180 if symbol == 'TOPIX' else 1100
    orders = ledger['orders']
    fees = [int(o[5])*fee_cents//100 for o in orders]
    np.testing.assert_array_equal(fees, ledger['fees'])
    parents, entries = {}, {}
    for order, fee in zip(orders, fees):
        row, decision, source, cid, side, quantity, price, reason, new, uid = order
        row, source, cid, quantity, uid = map(int, (row, source, cid, quantity, uid))
        assert price == ready['last'][row]
        assert decision < row or reason == 99
        parent = parents.setdefault((source, cid), dict(net=0., gross=0., fees=0, quantity=0))
        parent['fees'] += fee
        if new:
            assert uid not in entries
            entries[uid] = dict(side=side, price=price, remaining=quantity)
            parent['quantity'] = quantity
        else:
            entry = entries[uid]
            assert entry['side'] == -side and entry['remaining'] >= quantity
            entry['remaining'] -= quantity
            parent['gross'] += entry['side']*(price-entry['price'])*quantity*multiplier
    assert all(p['remaining'] == 0 for p in entries.values())
    saved = {(NAMES.index(p['source']), p['cid']): p for p in ledger['parents']}
    assert saved.keys() == parents.keys()
    for key, parent in parents.items():
        parent['net'] = parent['gross']-parent['fees']
        for field in ('net', 'gross', 'fees'):
            equal(parent[field], saved[key][field])
    positive = sum(p['net'] for p in parents.values() if p['net'] > 0)
    negative = -sum(p['net'] for p in parents.values() if p['net'] < 0)
    summary = dict(profit=positive, loss=negative, net=positive-negative,
                   fees=sum(fees), campaigns=len(parents),
                   profit_share=positive/(positive+negative) if positive+negative else None)
    if not curves:
        return summary, parents, None, None
    cash = np.zeros((len(ready['last']), 3))
    delta = np.zeros_like(cash)
    for order, fee in zip(orders, fees):
        row, source = int(order[0]), int(order[2])
        signed = order[4]*order[5]
        cash[row, source] += -signed*order[6]*multiplier-fee
        delta[row, source] += signed
    positions = np.cumsum(delta, axis=0)
    liquidation_fee = (np.abs(positions).astype(np.int64)*fee_cents)//100
    curve = np.cumsum(cash, axis=0)+positions*ready['last'][:, None]*multiplier-liquidation_fee
    assert (positions[-1] == 0).all()
    equal(curve[-1].sum(), summary['net'])
    return summary, parents, curve, positions


def drawdown(curve):
    """
    機能: 開始資産0を含む全観測の最大下落を求める。
    引数: curve(ndarray)。
    返り値: float。
    """
    values = np.r_[0., curve]
    return float(np.max(np.maximum.accumulate(values)-values))


def joined(curves, sessions, symbol, source=None):
    """
    機能: 場内全時価を開始資産へ接続して期間下落を独立計算する。
    引数: curves(dict)、sessions(list[str])、symbol(str)、source(int又はNone)。
    返り値: tuple[float,float,int]。最終収支・最大下落・黒字場数。
    """
    parts, offset, positive = [], 0., 0
    for session in sessions:
        value = curves[(session, symbol)]
        value = value[:, source] if source is not None else value.sum(axis=1)
        parts.append(value+offset)
        offset += value[-1]
        positive += int(value[-1] > 0)
    return float(offset), drawdown(np.concatenate(parts)), positive


def corr(a, b):
    """
    機能: 有効な対だけの標本相関を直接求める。
    引数: a/b(list又はndarray)。
    返り値: float又はNone。
    """
    a, b = np.asarray(a, float), np.asarray(b, float)
    valid = np.isfinite(a) & np.isfinite(b)
    a, b = a[valid], b[valid]
    if len(a) < 2 or np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def main():
    """
    機能: 新しい売買を作らず、固定台帳と結論の独立検査を保存する。
    引数: なし。
    返り値: None。出力はreview配下に限定。
    """
    fixed = read(WORK/'事前固定.json')
    analysis = read(WORK/'analysis/比較結果.json')
    fingerprints = {name: sha(ROOT/name) for name in fixed['code_SHA256']}
    assert fingerprints == fixed['code_SHA256']
    # ----------------------------------------
    # 売買・集計モジュールを呼ばず、固定入力の価格系列だけを読む。
    material = read(ROOT/'work/wave_v85/prepared/入力準備の完了.json')
    inputs = {}
    for pair in material['入力対応']:
        path = ROOT/pair['inputs']
        assert sha(path) == fixed['input_SHA256'][pair['inputs']]
        with path.open('rb') as stream:
            inputs.update(pickle.load(stream))
    assert len(inputs) == 60
    results, period_checks, allocations = {}, [], []
    parent_count = account_count = 0
    samples = {}
    curve_ids = ('A0622', 'A0820', 'A1000', 'A00100', 'A00010')
    for config in fixed['catalog']:
        identifier = config['id']
        result = read(WORK/'results'/f'{identifier}.json')
        assert sha(WORK/'ledgers'/f'{identifier}.pkl') == result['ledger_SHA256']
        assert sha(WORK/'results'/f'{identifier}.json') == analysis['結果SHA256'][identifier]
        with (WORK/'ledgers'/f'{identifier}.pkl').open('rb') as stream:
            ledgers = pickle.load(stream)
        curves, accounts, parent_sets = {}, {}, {}
        for key in sorted(inputs):
            ready = inputs[key]
            summary, parents, curve, positions = independent_account(ready, ledgers[key], identifier in curve_ids)
            expected = next(r for r in result['rows'] if (r['session'], r['symbol']) == key)
            for field, value in summary.items():
                equal(value, expected[field])
            account_count += 1
            parent_count += len(parents)
            accounts[key], parent_sets[key] = summary, parents
            if curve is not None:
                curves[key] = curve
                equal(drawdown(curve.sum(axis=1)), expected['max_drawdown'])
                grid = np.arange(ready['start']+60., ready['limit'], 60.)
                index = np.searchsorted(ready['time_s'], grid, side='right')-1
                valid = (index >= 0) & (grid-ready['time_s'][np.maximum(index, 0)] <= 180.)
                equity = curve.sum(axis=1)
                values = np.where(valid, equity[np.maximum(index, 0)], np.nan)
                saved = ledgers[key]['samples']
                np.testing.assert_array_equal(saved['rows'], index)
                np.testing.assert_allclose(saved['values'], values, rtol=0, atol=1e-5, equal_nan=True)
                samples[(identifier, key)] = dict(values=values, valid=valid, position=positions[np.maximum(index, 0)])
        for period in ('前16', '後14', '全30'):
            for symbol in ('TOPIX', 'NK225'):
                chosen = [accounts[(session, symbol)] for session in fixed[period]]
                own = {k:sum(row[k] for row in chosen) for k in ('net', 'profit', 'loss', 'fees', 'campaigns')}
                own['profit_share'] = own['profit']/(own['profit']+own['loss']) if own['profit']+own['loss'] else None
                expected = result['periods'][period][symbol]
                for field, value in own.items():
                    equal(value, expected[field])
                source_ratios = []
                for source, name in enumerate(NAMES):
                    ps = [p for session in fixed[period] for (s, _), p in parent_sets[(session, symbol)].items() if s == source]
                    profit = sum(p['net'] for p in ps if p['net'] > 0)
                    loss = -sum(p['net'] for p in ps if p['net'] < 0)
                    ratio = profit/(profit+loss) if profit+loss else None
                    source_expected = analysis['source_contributions'][identifier][period][symbol][name]
                    for field, value in dict(net=profit-loss, profit=profit, loss=loss, campaigns=len(ps), profit_share=ratio).items():
                        equal(value, source_expected[field])
                    if ratio is not None:
                        source_ratios.append(ratio)
                assert own['profit_share'] <= max(source_ratios)+1e-12
                if curves:
                    net, maximum, positive = joined(curves, fixed[period], symbol)
                    equal(net, expected['net']); equal(maximum, expected['max_drawdown'])
                    assert positive == expected['positive_sessions']
                    if identifier in ('A0622', 'A0820'):
                        gu_net, gu_dd, gu_positive = joined(curves, fixed[period], symbol, 0)
                        reference = analysis['risk_attribution'][identifier][period][symbol]['allocated_gu_only']
                        equal(gu_net, reference['net']); equal(gu_dd, reference['max_drawdown'])
                        assert gu_positive == reference['positive_sessions']
                        if period == '全30':
                            allocations.append(dict(id=identifier, symbol=symbol, GU同枚数収支=gu_net,
                                合成収支=net, GU同枚数最大下落=gu_dd, 合成最大下落=maximum,
                                下落増分=maximum-gu_dd, 収支下落比変化=[gu_net/gu_dd, net/maximum],
                                黒字場変化=[gu_positive, positive]))
                period_checks.append(dict(id=identifier, period=period, symbol=symbol, 利益割合=own['profit_share']))
        results[identifier] = result
    # ----------------------------------------
    # 前16だけの選定と、全期間を見た後の参考を分離する。
    eligible = []
    for identifier, result in results.items():
        stats = result['periods']['前16']
        if identifier == 'GU_HALF' or not all(stats[s]['net'] > 0 and stats[s]['campaigns'] >= 20 and stats[s]['max_drawdown'] > 0 for s in ('TOPIX', 'NK225')):
            continue
        score = min(stats[s]['net']/stats[s]['max_drawdown'] for s in ('TOPIX', 'NK225'))
        tie = min(stats[s]['worst_session']/stats[s]['max_drawdown'] for s in ('TOPIX', 'NK225'))
        eligible.append((-score, -tie, identifier))
    selected = min(eligible)[2] if eligible else None
    assert selected == analysis['selected'] == 'A0622'
    assert all(results[c]['periods']['全30'][s]['profit_share'] < .8 for c in results for s in ('TOPIX', 'NK225'))
    # ----------------------------------------
    # 単独源の全原板から作った同じ1分格子で相関・重複を再計算する。
    single = dict(GU='A1000', M3='A00100', C03='A00010')
    correlations = []
    for symbol in ('TOPIX', 'NK225'):
        for source_a, source_b in (('GU', 'M3'), ('GU', 'C03'), ('M3', 'C03')):
            changes_a, changes_b, days_a, days_b, signs_a, signs_b = [], [], [], [], [], []
            for session in fixed['全30']:
                key = session, symbol
                a, b = samples[(single[source_a], key)], samples[(single[source_b], key)]
                valid = a['valid'] & b['valid']
                consecutive = valid[:-1] & valid[1:]
                changes_a.extend(np.diff(a['values'])[consecutive]); changes_b.extend(np.diff(b['values'])[consecutive])
                signs_a.extend(np.sign(a['position'][valid, NAMES.index(source_a)]))
                signs_b.extend(np.sign(b['position'][valid, NAMES.index(source_b)]))
                for source, out in ((source_a, days_a), (source_b, days_b)):
                    out.append(next(r['net'] for r in results[single[source]]['rows'] if (r['session'], r['symbol']) == key))
            a, b = np.asarray(signs_a), np.asarray(signs_b)
            both, either = (a != 0) & (b != 0), (a != 0) | (b != 0)
            own = dict(session_correlation=corr(days_a, days_b), minute_correlation=corr(changes_a, changes_b),
                minute_return_count=len(changes_a), mutual_active_fraction=float(both.sum()/either.sum()),
                same_active_fraction=float(((a == b) & both).sum()/both.sum()), opposite_active_fraction=float(((a == -b) & both).sum()/both.sum()))
            expected = next(p for p in analysis['diversity'][symbol]['pairs'] if p['sources'] == [source_a, source_b])
            for field, value in own.items():
                equal(value, expected[field])
            correlations.append(dict(商品=symbol, 源=[source_a, source_b], **own))
    # ----------------------------------------
    # 参照先の結論と数値を検査し、因果を過剰に解釈しない。
    ratios = {}
    for symbol in ('TOPIX', 'NK225'):
        a, b = results['A0820']['periods']['全30'][symbol], results['A1000']['periods']['全30'][symbol]
        ratios[symbol] = dict(満額GUに対する収支維持率=a['net']/b['net'], 満額GUに対する下落削減率=1-a['max_drawdown']/b['max_drawdown'])
    assert results['A0622']['periods']['後14']['NK225']['net'] == -27344
    nk_parts = analysis['source_contributions']['A0622']['後14']['NK225']
    assert nk_parts['GU']['net'] == 55728 and nk_parts['M3']['net'] == -11624 and nk_parts['C03']['net'] == -71448
    generated = read(WORK/'report/生成結果.json')
    htmlpath = ROOT/generated['HTML']
    assert sha(htmlpath) == generated['HTML_SHA256']
    text = htmlpath.read_text(encoding='utf-8')
    for line in analysis['conclusion']:
        assert line in text
    assert {name:sha(ROOT/name) for name in fixed['code_SHA256']} == fingerprints
    proof = dict(全合格=True, 独立注文会計口座数=account_count, 独立親組数=parent_count,
        利益損失期間照合数=len(period_checks), 全原板下落再計算条件=list(curve_ids),
        前16の独立選定=selected, 両商品全22利益八割未達=True,
        同GU枚数対照=allocations, 満額GUとの比較=ratios, 相関と保有重複=correlations,
        公開結論三文=analysis['conclusion'], 公開HTML_SHA256=generated['HTML_SHA256'],
        解釈=['A0820の満額GU比の最大下落減を、同じGU枚数に他手法を追加した直接のリスク減とは呼ばない。同枚数対照では両商品とも最大下落が増えた。',
              '同枚数GU対照から収支/最大下落が改善したことは効率指標の改善であり、絶対損失の削減又は全日安定ではない。',
              '主A0622の日経後14の赤字ではC03の損失が最大の負寄与。低相関は正の収益性や安定黒字を保証しない。',
              'A0820は全30閲覧後の参考。事前主案と前16選定はいずれもA0622であり、入替えたとは説明しない。'],
        禁止事項遵守='新しい条件・売買・配分を追加せず、固定注文を読み取る別会計だけを実行。凍結コード不変更。',
        証跡=dict(固定指紋一致数=len(fingerprints), 集計SHA256=sha(WORK/'analysis/比較結果.json'), 自コードSHA256=sha(Path(__file__))))
    (HERE/'配分効果と結論の独立再検算.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 口座数=account_count, 親数=parent_count, 選定=selected), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
