"""保存注文の会計・変更箇所・利益追尾の発火を独立に検算する。"""

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
import pickle
import statistics
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path):
    """
    機能: 保存済みの監査素材を読む。
    引数: path(Path)はJSONファイルの位置。
    返り値: dict又はlistは復号した内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    """
    機能: 保存素材の内容指紋を求める。
    引数: path(Path)は監査対象のファイル。
    返り値: strはSHA256。
    """
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def equal(left, right):
    """
    機能: 浮動小数の丸めだけを許して二値を比較する。
    引数: left/right(float)は照合対象。
    返り値: None。不一致は例外にする。
    """
    assert abs(left-right) < 1e-7, (left, right)


def ledger(orders, times, bid, ask, normal):
    """
    機能: 保存注文の現金差額とFIFO損益を別々に積算する。
    引数: orders/times/bid/ask/normal(ndarray)は保存注文と原行気配。
    返り値: dictは場・親・脚の会計と保有枚数検査。
    """
    inventory = defaultdict(deque)
    parents = defaultdict(lambda: dict(gross=0., fees=0, cash=0., legs={}))
    held = {1: 0, -1: 0}
    entries = quantity = maximum = next_normal = 0
    assert np.all(np.diff(orders[:, 0]) >= 0)
    for order in orders:
        row, decision, pid, side, amount = map(int, order[:5])
        price = float(order[5])
        reason, new, leg, fee = map(int, order[6:10])
        assert 0 <= decision < row < len(times)
        assert side in (-1, 1) and amount > 0 and new in (0, 1)
        assert fee == amount*385//10
        assert normal[np.searchsorted(normal, row)] == row
        equal(price, ask[row] if side == 1 else bid[row])
        if reason == 1381:
            assert not new and leg == 1
            assert normal[np.searchsorted(normal, decision, side='right')] == row
            next_normal += 1
        parent = parents[pid]
        component = parent['legs'].setdefault(leg, dict(gross=0., fees=0, cash=0., entries=0, quantity=0))
        cash = -side*amount*price*100.
        for account in (parent, component):
            account['cash'] += cash
            account['fees'] += fee
        parent.setdefault('entry', row)
        parent.setdefault('side', side)
        parent['exit'] = row
        key = pid, leg
        if new:
            assert not inventory[key], ('同一脚の未返済中の再新規', key)
            inventory[key].append([amount, price, side])
            held[side] += amount
            entries += 1
            quantity += amount
            component['entries'] += 1
            component['quantity'] += amount
        else:
            remaining = amount
            while remaining:
                assert inventory[key], ('建玉なしの返済', key, row)
                lot = inventory[key][0]
                assert lot[2] == -side
                used = min(remaining, lot[0])
                gain = lot[2]*(price-lot[1])*used*100.
                parent['gross'] += gain
                component['gross'] += gain
                remaining -= used
                lot[0] -= used
                if not lot[0]:
                    inventory[key].popleft()
            held[-side] -= amount
        assert 0 <= held[1] <= 10 and 0 <= held[-1] <= 10
        maximum = max(maximum, held[1], held[-1])
    assert held == {1: 0, -1: 0} and all(not v for v in inventory.values())
    for parent in parents.values():
        equal(parent['gross'], parent['cash'])
        parent['net'] = parent['gross']-parent['fees']
        for component in parent['legs'].values():
            equal(component['gross'], component['cash'])
            component['net'] = component['gross']-component['fees']
    profits = sum(p['net'] for p in parents.values() if p['net'] > 0)
    losses = -sum(p['net'] for p in parents.values() if p['net'] < 0)
    return dict(profit=profits, loss=losses, net=profits-losses,
                gross=sum(p['gross'] for p in parents.values()),
                fees=sum(p['fees'] for p in parents.values()), parents=dict(parents),
                entries=entries, quantity=quantity, max_per_side=maximum,
                next_normal_checks=next_normal)


def compare_accounts(saved, observed):
    """
    機能: 独立会計を保存済み場・親・脚会計へ照合する。
    引数: saved/observed(dict)は本計算と監査計算の結果。
    返り値: intは一致した数値項目数。
    """
    count = 0
    for name in ('profit', 'loss', 'net', 'gross', 'fees', 'entries', 'quantity', 'max_per_side'):
        equal(saved[name], observed[name])
        count += 1
    parents = {int(p['id']): p for p in saved['parents']}
    assert parents.keys() == observed['parents'].keys()
    for pid, parent in observed['parents'].items():
        counterpart = parents[pid]
        for name in ('gross', 'fees', 'net', 'entry', 'exit', 'side'):
            equal(parent[name], counterpart[name])
            count += 1
        assert set(parent['legs']) == set(map(int, counterpart['legs']))
        for leg, component in parent['legs'].items():
            for name in ('gross', 'fees', 'net', 'entries', 'quantity'):
                equal(component[name], counterpart['legs'][str(leg)][name])
                count += 1
    return count


def audit_trigger(original, altered, bid, ask, atr, normal, config):
    """
    機能: 保存された独自返済の最初の発火を、累積最大と元親優先から独立照合する。
    引数: original/altered/bid/ask/atr/normal(ndarray)、config(dict)は親の素材と固定条件。
    返り値: dictは発火数、取消候補数、判断時点の追尾根拠。
    """
    entries = original[(original[:, 8] == 1) & (original[:, 7] == 1)]
    stops = altered[altered[:, 6] == 1381]
    if not len(entries):
        assert not len(stops) and np.array_equal(original, altered)
        return dict(checked=0, triggered=0, cancelled=0, evidence=[])
    assert len(entries) == 1 and len(stops) <= 1
    entry = entries[0]
    side = int(entry[3])
    risk = max(20., float(atr[int(original[0, 1])]))
    assert np.isfinite(risk) and risk > 0
    end = int(original[(original[:, 8] == 1) & (original[:, 7] == 0)][-1, 0])
    # ----------------------------------------
    # 追撃自身が建った行以後だけで最高順行を作る。元親の最後の全返済行は除く。
    sample = normal[(normal >= int(entry[0])) & (normal < end)]
    mark = bid[sample] if side > 0 else ask[sample]
    move = side*(mark-entry[5])
    peaks = np.maximum.accumulate(move)
    active = peaks >= config['activation']*risk
    distances = np.full(len(sample), config['width']*risk)
    if config['tighten_at'] > 0:
        distances[peaks >= config['tighten_at']*risk] = config['tight_width']*risk
    floors = np.maximum.accumulate(np.where(active, peaks-distances, -np.inf))
    hits = np.flatnonzero(active & (move <= floors))
    original_close_rows = set(map(int, original[original[:, 7] == 0, 0]))
    expected = None
    cancelled = 0
    for ix in hits:
        decision = int(sample[ix])
        fill = int(normal[np.searchsorted(normal, decision, side='right')])
        if fill in original_close_rows:
            cancelled += 1
            continue
        assert fill < end
        expected = dict(decision=decision, fill=fill, risk=risk, peak=float(peaks[ix]),
                        floor=float(floors[ix]), move=float(move[ix]),
                        activation=float(config['activation']*risk),
                        entry=int(entry[0]), entry_price=float(entry[5]), side=side)
        break
    if expected is None:
        assert not len(stops), ('想定外の利益追尾', original[0, 2], config['id'])
    else:
        assert len(stops) == 1, ('利益追尾の欠落', original[0, 2], config['id'], expected)
        stop = stops[0]
        assert int(stop[0]) == expected['fill'] and int(stop[1]) == expected['decision']
        assert int(stop[3]) == -side
        assert not np.any((original[:, 0] == stop[0]) & (original[:, 7] == 0))
        assert expected['peak'] >= expected['activation']
        assert expected['move'] <= expected['floor']
        expected.update(quantity=int(stop[4]), fill_price=float(stop[5]),
                        realized_move=float(side*(stop[5]-entry[5])))
    # ----------------------------------------
    # 独自保護後も元親通知を保存割合で適用し、残りの数量が適切かを検算する。
    virtual = actual = int(entry[4])
    old_closes = original[(original[:, 8] == 1) & (original[:, 7] == 0)]
    new_closes = altered[(altered[:, 8] == 1) & (altered[:, 7] == 0) & (altered[:, 6] != 1381)]
    stop_used = False
    expected_old_count = 0
    for old in old_closes:
        if len(stops) and not stop_used and stops[0, 0] < old[0]:
            take = actual if config['protect'] == 0 else min(actual, config['protect'])
            assert int(stops[0, 4]) == take
            actual -= take
            stop_used = True
        before = virtual
        virtual -= int(old[4])
        remain = int(np.floor(actual*virtual/before+.5)) if virtual else 0
        take = actual-remain
        actual = remain
        found = new_closes[new_closes[:, 0] == old[0]]
        if take:
            assert len(found) == 1
            expected_order = old.copy()
            expected_order[4] = take
            expected_order[9] = take*385//10
            assert np.array_equal(found[0], expected_order)
            expected_old_count += 1
        else:
            assert not len(found)
    assert actual == virtual == 0 and expected_old_count == len(new_closes)
    assert stop_used == bool(len(stops))
    return dict(checked=1, triggered=int(expected is not None), cancelled=cancelled,
                evidence=[expected] if expected is not None else [])


def summarize(rows):
    """
    機能: 保存会計から赤字場と大勝ち依存を集計する。
    引数: rows(list[dict])は同じ手法の場会計。
    返り値: dictは収支・勝敗・平均損失等の比較尺度。
    """
    values = [r['net'] for r in rows]
    wins = [v for v in values if v > 0]
    losses = [-v for v in values if v < 0]
    return dict(sessions=len(rows), net=sum(values), black=len(wins), red=len(losses),
                no_trade=sum(r['entries'] == 0 for r in rows),
                mean_loss=statistics.mean(losses) if losses else 0.,
                median_loss=statistics.median(losses) if losses else 0.,
                worst_loss=max(losses, default=0.),
                without_top3=sum(values)-sum(sorted(wins, reverse=True)[:3]))


def main():
    """
    機能: 金融再生をせず、全条件の保存結果を入力指紋・会計・発火根拠で監査する。
    引数: なし。
    返り値: None。独立監査JSONと短いMarkdownを保存する。
    """
    result = read(HERE/'結果.json')
    plan = read(HERE/'試行計画.json')
    assert digest(ROOT/result['plan']['path']) == result['plan']['sha256']
    for source in plan['sources']:
        assert digest(ROOT/source['path']) == source['sha256']
    rows = {(r['session'], r['method']): r for r in result['rows']}
    assert len(rows) == len(result['rows']) == len(plan['inputs'])*len(plan['configs'])
    caches = {r['session']: r for r in result['cache']}
    baselines = {r['session']: r for r in plan['baselines']}
    totals = defaultdict(int)
    checked = []
    evidence = []
    for item in plan['inputs']:
        scene = item['session']
        newfile, oldfile = caches[scene], baselines[scene]
        for spec in (item['input'], newfile, oldfile):
            assert digest(ROOT/spec['path']) == spec['sha256']
        packet = pickle.loads((ROOT/item['input']['path']).read_bytes())
        key = scene, 'NK225'
        ready, quotes = packet['inputs'][key], packet['quotes'][key]
        times, atr = ready['time_s'], ready['atr']
        bid, ask = quotes['bid'], quotes['ask']
        good = quotes['quote_valid'] & np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
        normal = np.flatnonzero(good)
        with np.load(ROOT/newfile['path'], allow_pickle=False) as saved, np.load(ROOT/oldfile['path'], allow_pickle=False) as original:
            assert set(saved.files) == {c['id'] for c in plan['configs']}
            for config in plan['configs']:
                method = config['id']
                orders, baseline = saved[method], original[config['base']]
                assert np.array_equal(orders[orders[:, 7] == 1], baseline[baseline[:, 7] == 1])
                assert np.array_equal(orders[orders[:, 8] != 1], baseline[baseline[:, 8] != 1])
                totals['入口完全一致'] += int(np.sum(orders[:, 7] == 1))
                totals['初回補完完全一致'] += int(np.sum(orders[:, 8] != 1))
                observed = ledger(orders, times, bid, ask, normal)
                totals['会計項目'] += compare_accounts(rows[(scene, method)], observed)
                totals['注文'] += len(orders)
                totals['次正常行'] += observed['next_normal_checks']
                assert set(orders[:, 2]) == set(baseline[:, 2])
                for parent in np.unique(baseline[:, 2]):
                    origin = baseline[baseline[:, 2] == parent]
                    changed = orders[orders[:, 2] == parent]
                    check = audit_trigger(origin, changed, bid, ask, atr, normal, config)
                    totals['追撃親の発火有無'] += check['checked']
                    totals['独自利益追尾'] += check['triggered']
                    totals['元親優先で取消候補'] += check['cancelled']
                    evidence.extend(dict(session=scene, method=method, parent=int(parent), **e) for e in check['evidence'])
                checked.append(dict(session=scene, method=method, orders=len(orders), net=observed['net']))
        print(scene, '独立保存監査完了', flush=True)
    summaries = {c['id']: summarize([r for (s, m), r in rows.items() if m == c['id']]) for c in plan['configs']}
    output = dict(passed=True, accounts=len(checked), checks=dict(totals),
                  source_result_sha256=digest(HERE/'結果.json'), source_plan_sha256=digest(HERE/'試行計画.json'),
                  auditor_sha256=digest(Path(__file__)), summaries=summaries, checked=checked,
                  trigger_evidence=evidence, financial_replays=0, api=0, real_orders=0,
                  note='保存注文の独立FIFO・現金会計と、追撃以後の累積最大に基づく発火監査。新しい有効性標本ではない。実mini気配・Go実装との同値は未検証。')
    (HERE/'audit_financial138.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# 玉別利益追尾の独立保存監査', '',
             f'保存{len(checked)}場会計・{totals["注文"]:,}注文を照合し、全て一致。金融再生0、API0、実注文0。', '',
             f'全入口・初回玉・補完担当の注文は00137のWparent/CWparentと完全一致。{totals["追撃親の発火有無"]:,}件の追撃親について、追撃建値からの順行・起動・追尾下限を独立計算し、{totals["独自利益追尾"]:,}件の独自返済と返済なしの両方を確認した。', '',
             '独自返済は判断後の最初の正常原行。各注文の1円未満切捨て費用、部分返済後の数量、方向別上限10枚、場末残玉0を確認した。', '',
             f'元親返済との競合時は独自予約を取り消す規則で照合したが、今回の実データで取消候補は{totals["元親優先で取消候補"]}件。この競合枝そのものは実標本による検証ではない。', '',
             '| 条件 | 全場収支 | 黒字／赤字 | 平均赤字 | 最大赤字 | 上位3黒字を除く |',
             '|---|---:|---:|---:|---:|---:|']
    for method, summary in summaries.items():
        lines.append(f'| {method} | {summary["net"]:+,.0f}円 | {summary["black"]}／{summary["red"]} | {summary["mean_loss"]:,.0f}円 | {summary["worst_loss"]:,.0f}円 | {summary["without_top3"]:+,.0f}円 |')
    lines += ['', '同じ既知45場を使う保存結果の監査であり、新しい標本による優位の検証ではない。元の仮想通知は固定で、追尾返済後の再追加はない。実miniの気配、実受信時計、Go本体の数量状態は未検証。']
    (HERE/'audit_financial138.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, accounts=len(checked), checks=dict(totals)), ensure_ascii=False))


if __name__ == '__main__':
    main()
