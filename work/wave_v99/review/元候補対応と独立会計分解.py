"""売買を再実行せず、元候補と実新規を別の鍵として会計差を検算する。"""

import numpy as np

import 共通独立読取 as R


def candidate_at(ledger: dict, row: int) -> tuple[int, int]:
    """
    機能: 保存された元eventの疎状態から、原候補の累積IDと方向を独立復元する。
    引数: ledger(dict)、row(int)は元候補原行。
    返り値: tuple[int,int]は候補IDと方向。同方向の連続pulseも原行ごとに数える。
    """
    changes = ledger['trend_event_changes']
    starts = changes[:, 0].astype(np.int64)
    assert len(starts) and starts[0] == 0 and np.all(np.diff(starts) > 0)
    assert 0 <= row < int(ledger['input_rows'])
    position = int(np.searchsorted(starts, row, side='right') - 1)
    lengths = np.diff(np.r_[starts, int(ledger['input_rows'])])
    values = changes[:, 1].astype(np.int64)
    assert np.isin(values, (-1, 0, 1)).all()
    prior = int(np.sum(lengths[:position] * (values[:position] != 0)))
    side = int(values[position])
    assert side != 0, '候補でない原行を新規起点にしない'
    return prior + row - int(starts[position]) + 1, side


def named(row: np.ndarray, columns: list[str]) -> dict:
    """
    機能: 保存診断の一行を列名付きの辞書へ変換する。
    引数: row(ndarray[float])、columns(list[str])。
    返り値: dict[str,float]。未定義値を他の正常源で補完しない。
    """
    assert len(row) == len(columns)
    return {name: float(value) for name, value in zip(columns, row)}


def origin_map(ledger: dict, record: dict | None = None) -> dict:
    """
    機能: 完了親を旧event由来の候補ID・方向に一対一対応させる。
    引数: ledger(dict)、record(dict|None)は原本に由来する自己観測。
    返り値: dict[tuple,dict]。元原行/seqも照合し発注行の変化と混同しない。
    """
    rows = ledger['entry_parent_diagnostics']
    columns = ledger['entry_parent_columns']
    assert len(columns) == 45 and rows.ndim == 2 and rows.shape[1] == 45
    diagnostics = {}
    for row in rows:
        value = named(row, columns)
        pid = int(value['parent_id'])
        assert pid not in diagnostics
        diagnostics[pid] = value
    answer = {}
    for trade in ledger['trades']:
        assert int(trade[1]) == 0, '今回の34条件は旧J8源のみ'
        d = diagnostics[int(trade[0])]
        assert d['market_outcome'] == 1 and d['net'] == trade[11]
        assert d['fill_row'] == trade[2] and d['exit_row'] == trade[3]
        assert d['side'] == trade[4] and d['quantity'] == trade[5]
        assert d['fill_price'] == trade[6] and d['trigger_row'] == trade[15]
        assert d['candidate_row'] <= d['trigger_row'] < d['fill_row'] <= d['exit_row']
        assert d['candidate_time'] <= d['trigger_time'] <= d['fill_time']
        assert d['width'] > 0 and np.isfinite(d['width'])
        if record is not None:
            for label in ('candidate', 'trigger', 'fill'):
                row = int(d[label + '_row'])
                assert int(record['seq'][row]) == int(d[label + '_seq'])
                assert float(record['time_s'][row]) == d[label + '_time']
            expected = record['ask'] if trade[4] == 1 else record['bid']
            assert d['candidate_quote'] == expected[int(d['candidate_row'])]
            assert d['trigger_quote'] == expected[int(d['trigger_row'])]
            assert d['fill_price'] == expected[int(d['fill_row'])]
        old_candidate_id, old_candidate_side = candidate_at(ledger, int(d['candidate_row']))
        assert old_candidate_id == int(d['candidate_id']) and old_candidate_side == int(trade[4])
        key = (int(trade[1]), old_candidate_id, old_candidate_side)
        assert key not in answer, '同候補から二重の完了親を作っていない'
        answer[key] = dict(trade=trade, entry=d)
    completed = [value for value in diagnostics.values() if value['market_outcome'] == 1]
    assert len(completed) == len(answer)
    assert all(value['market_outcome'] in (1, 2) for value in diagnostics.values())
    return answer


def scalar_parent(session: str, value: dict) -> dict:
    """
    機能: 原候補から発注・新規・返済までを独立分解用に記録する。
    引数: session(str)、value(dict)は完了親と入口診断。
    返り値: dict。時刻は保存された公表時計であり真受信時刻ではない。
    """
    t, d = value['trade'], value['entry']
    return dict(場=session, 親=int(t[0]), 源=int(t[1]), 方向=int(t[4]), 枚数=int(t[5]),
        元候補ID=int(d['candidate_id']),
        元候補行=int(d['candidate_row']), 元候補seq=int(d['candidate_seq']),
        元候補時計=R.clock(d['candidate_time']), 元候補quote=d['candidate_quote'],
        発注行=int(t[15]), 発注時計=R.clock(d['trigger_time']), 発注quote=d['trigger_quote'],
        実新規行=int(t[2]), 実新規時計=R.clock(d['fill_time']), 実新規価格=float(t[6]),
        返済行=int(t[3]), 返済価格=float(t[7]), 純額円=float(t[11]),
        料金円=float(t[8] + t[9]), 待機秒=d['trigger_time'] - d['candidate_time'],
        待機機構=int(d['kind']), 入口W=d['width'], phase行=int(d['phase_row']),
        有利peak=d['favorable_peak'], 不利extreme=d['opposite_extreme'],
        未知基準代替=bool(d['fallback_used']))


def sign(value: float) -> str:
    """
    機能: 手数料後の親を利益・損失・同額へ分類する。
    引数: value(float)は純額。
    返り値: str。無取引を利益へ分類する処理は含まない。
    """
    return '利益' if value > 1e-5 else '損失' if value < -1e-5 else '同額'


def decompose(old: dict, new: dict, symbol: str, sessions: list[str], details: bool = False) -> dict:
    """
    機能: 元候補共通親の取得・返済・料金差と固有親に全収支差を恒等分解する。
    引数: old/new(dict)は口座別origin_map、symbol(str)、sessions(list[str])、details(bool)。
    返り値: dict。取得と返済の実経路差は別の反実策略の因果効果ではない。
    """
    multiplier = 1000. if symbol == 'TOPIX' else 10.
    shared, old_only, new_only = [], [], []
    cohorts = {}
    strict_delta = strict_count = 0
    for session in sessions:
        a, b = old[session, symbol], new[session, symbol]
        for origin in sorted(a.keys() & b.keys()):
            x, y = a[origin], b[origin]
            ta, tb = x['trade'], y['trade']
            assert ta[4] == tb[4] and ta[5] == tb[5]
            for name in ('candidate_id', 'candidate_row', 'candidate_seq', 'candidate_time', 'candidate_quote'):
                assert x['entry'][name] == y['entry'][name], ('同じ旧候補IDの原点が異なる', name)
            side, quantity = int(ta[4]), int(ta[5])
            entry_change = side * (float(ta[6]) - float(tb[6])) * quantity * multiplier
            exit_change = side * (float(tb[7]) - float(ta[7])) * quantity * multiplier
            fee_change = float(ta[8] + ta[9] - tb[8] - tb[9])
            net_change = float(tb[11] - ta[11])
            assert abs(entry_change + exit_change + fee_change - net_change) < 1e-4
            strict = np.array_equal(ta[[2, 4, 5, 6, 8, 15]], tb[[2, 4, 5, 6, 8, 15]])
            if strict:
                strict_count += 1
                strict_delta += net_change
            tag = sign(float(ta[11])) + '→' + sign(float(tb[11]))
            group = cohorts.setdefault(tag, dict(親=0, 元収支円=0., 新収支円=0., 差円=0.))
            group['親'] += 1
            group['元収支円'] += float(ta[11]); group['新収支円'] += float(tb[11])
            group['差円'] += net_change
            shared.append(dict(元=scalar_parent(session, x), 新=scalar_parent(session, y),
                建値差円=entry_change, 返済差円=exit_change, 料金差円=fee_change,
                純額差円=net_change, 厳密同一実新規=strict, 符号変化=tag))
        old_only += [scalar_parent(session, a[k]) for k in sorted(a.keys() - b.keys())]
        new_only += [scalar_parent(session, b[k]) for k in sorted(b.keys() - a.keys())]
    old_net = sum(float(v['trade'][11]) for s in sessions for v in old[s, symbol].values())
    new_net = sum(float(v['trade'][11]) for s in sessions for v in new[s, symbol].values())
    common_delta = sum(v['純額差円'] for v in shared)
    missing = sum(v['純額円'] for v in old_only)
    extra = sum(v['純額円'] for v in new_only)
    assert abs(new_net - old_net - common_delta + missing - extra) < 1e-4
    out = dict(元収支円=old_net, 新収支円=new_net, 全経路差円=new_net - old_net,
        同候補親=len(shared), 建値改善円=sum(v['建値差円'] for v in shared),
        返済差円=sum(v['返済差円'] for v in shared), 料金差円=sum(v['料金差円'] for v in shared),
        同候補収支差円=common_delta, 厳密同一実新規親=strict_count, 厳密同一実新規管理差円=strict_delta,
        元勝ちの同候補差円=sum(v['純額差円'] for v in shared if v['元']['純額円'] > 1e-5),
        元負けの同候補差円=sum(v['純額差円'] for v in shared if v['元']['純額円'] < -1e-5),
        有利建値親=sum(v['建値差円'] > 1e-5 for v in shared),
        不利建値親=sum(v['建値差円'] < -1e-5 for v in shared),
        同値建値親=sum(abs(v['建値差円']) <= 1e-5 for v in shared),
        平均待機秒=float(np.mean([v['新']['待機秒'] for v in shared])) if shared else None,
        同候補符号変化=cohorts, 元固有親=len(old_only), 新固有親=len(new_only),
        逃した元固有利益円=sum(max(v['純額円'], 0.) for v in old_only),
        避けた元固有損失円=-sum(min(v['純額円'], 0.) for v in old_only),
        新固有利益円=sum(max(v['純額円'], 0.) for v in new_only),
        新固有損失円=-sum(min(v['純額円'], 0.) for v in new_only),
        元固有収支円=missing, 新固有収支円=extra, 恒等検算=True)
    if details:
        out.update(同候補一覧=shared, 元固有一覧=old_only, 新固有一覧=new_only,
            改善上位例=sorted(shared, key=lambda v: -v['純額差円'])[:3],
            悪化上位例=sorted(shared, key=lambda v: v['純額差円'])[:3])
    return out


def watch_counts(ledger: dict) -> dict:
    """
    機能: 保存待機イベントの成立・消費・取消を、約定親と区別して計数する。
    引数: ledger(dict)。
    返り値: dict。候補を見送っただけの損失除外を新策略利益へ計上しない。
    """
    events = ledger['entry_wait_events']
    columns = ledger['entry_wait_event_columns']
    assert events.shape[1] == len(columns) == 57
    code, reason = columns.index('code'), columns.index('reason')
    codes = {name: int(np.sum(events[:, code] == int(number)))
        for number, name in ledger['entry_wait_event_codes'].items()}
    cancellations = {name: int(np.sum((events[:, code] == 3) & (events[:, reason] == int(number))))
        for number, name in ledger['entry_wait_reasons'].items()}
    consumption = {name: int(np.sum((events[:, code] == 2) & (events[:, reason] == int(number))))
        for number, name in ledger['entry_wait_reasons'].items()}
    return dict(イベント=codes, 取消理由=cancellations, 候補消費理由=consumption,
        完了親=len(ledger['trades']), 市場予約後取消親=sum(
            value['market_outcome'] == 2 for value in [named(row, ledger['entry_parent_columns'])
                for row in ledger['entry_parent_diagnostics']]))


def exclusion_evidence(ledger: dict, candidate_row: int, side: int) -> list[dict]:
    """
    機能: 元固有又は新固有候補が相手側で消費・取消された保存理由を検索する。
    引数: ledger(dict)、candidate_row/side(int)。
    返り値: list[dict]。理由が無い場合は後付けで失効理由を創作しない。
    """
    answer = []
    for row in ledger['entry_wait_events']:
        d = named(row, ledger['entry_wait_event_columns'])
        own_candidate = int(d['row']) == candidate_row and d['arriving_side'] == side
        state_candidate = (np.isfinite(d['state_candidate_row']) and
            int(d['state_candidate_row']) == candidate_row and d['state_side'] == side)
        if int(d['code']) in (2, 3, 9) and (own_candidate or state_candidate):
            answer.append(dict(行=int(d['row']), コード=int(d['code']),
                事象=ledger['entry_wait_event_codes'][int(d['code'])],
                理由=ledger['entry_wait_reasons'][int(d['reason'])], 保存列=d))
    return answer


def policy_counts(ledger: dict) -> dict:
    """
    機能: 40状態/50イベントの観測gapとepoch診断を、取消と実約定から分離する。
    引数: ledger(dict)。
    返り値: dict。イベント時刻から実受信時計を捏造しない。
    """
    events = ledger['entry_policy_events']
    columns = ledger['entry_policy_event_columns']
    assert len(columns) == events.shape[1] == 50
    code = columns.index('code')
    return {name: int(np.sum(events[:, code] == int(number)))
        for number, name in ledger['entry_policy_event_codes'].items()}
