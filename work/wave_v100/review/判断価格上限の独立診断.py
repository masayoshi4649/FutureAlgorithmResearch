"""売買を再生せず、完了入口の数学上限と保存拒否状態を別々に検算する。"""

import numpy as np

import 共通独立読取 as R
import 元候補対応と独立会計分解 as P


def parent_check(ledger: dict, config: dict, record: dict) -> dict:
    """
    機能: 上限21列を旧入口45列と実判断/約定BBOから独立に再計算する。
    引数: ledger/config/record(dict)。
    返り値: dict。実判断の資格と次行のfill超過を分ける。最初成立全行を再生しない。
    """
    assert R.AUTHORIZED
    assert len(ledger['entry_cap_parent_columns']) == 21
    parents, caps = ledger['entry_parent_diagnostics'], ledger['entry_cap_parent_diagnostics']
    assert len(parents) == len(caps)
    multiple = config['entry_price_cap_multiple']
    enabled = multiple is not None
    rows = []
    for parent, saved in zip(parents, caps):
        d = P.named(parent, ledger['entry_parent_columns'])
        side, width = int(d['side']), d['width']
        candidate, trigger, fill = d['candidate_quote'], d['trigger_quote'], d['fill_price']
        expected_quote = record['ask'] if side == 1 else record['bid']
        assert candidate == expected_quote[int(d['candidate_row'])]
        assert trigger == expected_quote[int(d['trigger_row'])]
        threshold = multiple * width if enabled else np.nan
        decision_adverse = side * (trigger - candidate)
        assert np.isfinite(decision_adverse)
        decision_inside = not enabled or decision_adverse <= threshold
        assert decision_inside, '判断上限外の親を実参加したことにしていません'
        if np.isfinite(fill):
            assert fill == expected_quote[int(d['fill_row'])]
            fill_adverse = side * (fill - candidate)
        else:
            assert d['market_outcome'] == 2
            fill_adverse = np.nan
        excess = max(0., fill_adverse - threshold) if enabled and np.isfinite(fill_adverse) else np.nan
        expected = np.asarray([d['parent_id'], d['candidate_id'], d['candidate_time'], side,
            d['quantity'], candidate, width, enabled, multiple if enabled else np.nan, threshold,
            d['trigger_row'], d['trigger_time'], trigger, decision_adverse, decision_inside,
            d['fill_row'], d['fill_time'], fill, fill_adverse, excess, d['market_outcome']], float)
        np.testing.assert_array_equal(saved, expected)
        rows.append(dict(親=int(d['parent_id']), 候補=int(d['candidate_id']), 方向=side,
            判断不利幅=decision_adverse, cap幅=None if not enabled else threshold,
            約定不利幅=fill_adverse, 約定上限超過=excess, outcome=int(d['market_outcome'])))
    return dict(全親21列一致=True, 入口診断親=len(rows), 成行予約後取消=sum(r['outcome'] == 2 for r in rows),
        完了親=len(ledger['trades']), cap有効=enabled,
        約定上限超過親=sum(np.isfinite(r['約定上限超過']) and r['約定上限超過'] > 0 for r in rows),
        買売別超過親={str(side): sum(r['方向'] == side and np.isfinite(r['約定上限超過'])
            and r['約定上限超過'] > 0 for r in rows) for side in (-1, 1)},
        各親=rows, scope='旧入口保存45列・実BBOから21列を独立検算。最初の潜在触発全行監査は別担当。')


def state_counts(ledger: dict) -> dict:
    """
    機能: 疎なcap20状態の継続行数と候補数を実親会計と区別して計数する。
    引数: ledger(dict)。
    返り値: dict。保存20列の記述であり最初触発の独立再生成とは呼ばない。
    """
    changes = ledger['entry_cap_state_changes']
    columns = ledger['entry_cap_state_columns']
    assert changes.shape[1] == 21 and len(columns) == 20
    starts = changes[:, 0].astype(np.int64)
    assert starts[0] == 0 and np.all(np.diff(starts) > 0)
    assert starts[-1] == int(ledger['input_rows']) - 1
    lengths = np.diff(np.r_[starts, int(ledger['input_rows'])])
    result = {}
    for name in ('old_trigger', 'selected_trigger', 'cap_blocked'):
        mask = changes[:, columns.index(name) + 1] == 1.
        result[name] = dict(原行数=int(lengths[mask].sum()),
            候補数=len(set(changes[mask, columns.index('candidate_id') + 1].astype(int))))
    result['scope'] = '保存cap状態の継続数。実建玉と拒否候補及び無取引を混ぜない。'
    return result


def blocked_samples(ledger: dict, candidate_id: int, maximum: int = 3) -> list[dict]:
    """
    機能: 指定元候補の上限拒否を保存状態から代表行だけ抽出する。
    引数: ledger(dict)、candidate_id/maximum(int)。
    返り値: list[dict]。最初と最後及び最大不利幅の代表で、全潜在判断の監査とは別。
    """
    columns = ledger['entry_cap_state_columns']
    changes = ledger['entry_cap_state_changes']
    mask = (changes[:, columns.index('candidate_id') + 1] == candidate_id)
    mask &= changes[:, columns.index('cap_blocked') + 1] == 1.
    selected = changes[mask]
    if not len(selected):
        return []
    positions = list(dict.fromkeys((0, len(selected) - 1,
        int(np.argmax(selected[:, columns.index('adverse_width') + 1])))))[:maximum]
    return [dict(行=int(selected[i, 0]), 保存20列=P.named(selected[i, 1:], columns)) for i in positions]


def cap_exclusion(ledger: dict, candidate_id: int) -> dict:
    """
    機能: 不参加候補のcap拒否と後続の旧取消/消費を分けるため保存拒否点を添える。
    引数: ledger(dict)、candidate_id(int)。
    返り値: dict。最後の値下がりだけから未保存理由を創作しない。
    """
    samples = blocked_samples(ledger, candidate_id)
    return dict(上限拒否の保存代表=samples, 少なくとも一度cap拒否=bool(samples),
        scope='cap拒否はwatch取消そのものではない。旧取消・他親保有・経路差も別に調べる。')
