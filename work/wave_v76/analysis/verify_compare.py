"""未来損益を使わない状態ラベルと、反転・全決済の分割会計を人工台帳で検査する。"""

from pathlib import Path
import json
import numpy as np

import compare_management as diagnosis


def verify() -> dict:
    """機能: 片市場支持消失、反転取引、気配差、管理対照の一意性を独立値で確認する。

    引数: なし。返り値: 検査証拠(dict)。実データや新しい損益は読まない。
    """
    session, symbol = '人工_Day', 'TOPIX'
    times = np.arange(0., 180., 10.)
    grid = np.arange(10., 155., 5.)
    size = len(grid)
    raw = dict(time_s=times)
    ready = {(session, s): raw for s in diagnosis.SYMBOLS}
    book = {(session, symbol): dict(bid=np.full(len(times), 99.), ask=np.full(len(times), 100.))}
    own_weak, peer_weak = np.ones(size, dtype=np.int8), np.ones(size, dtype=np.int8)
    loss_g = int(np.flatnonzero(grid == 40.)[0])
    own_weak[loss_g] = 0
    top = np.maximum(0, ((grid - 15.) // 10).astype(int))
    nk = np.maximum(0, ((grid - 10.) // 10).astype(int))
    state = dict(grid=grid, valid=np.ones(size, bool), own_weak=own_weak, peer_weak=peer_weak,
                 own_strong=own_weak.copy(), peer_strong=peer_weak.copy(), source_top=top, source_nk=nk)
    states = {'F15': {session: state}}
    market = {}
    for s in diagnosis.SYMBOLS:
        market[s] = dict(windows={15: dict(source_valid=np.ones(size, bool), missing_ofi=np.zeros(size, bool),
            nonzero_ofi_count=np.full(size, 2 if s == 'TOPIX' else 5),
            zero_ofi_denominator=np.zeros(size, bool), actual_seconds=np.full(size, 15.))})
    grids = {session: dict(markets=market)}
    orders = np.asarray([[2, 1, 0, 1, 10, 100, 10, 1], [5, 4, 0, -1, 10, 99, 7, 0],
                         [8, 7, 1, -1, 10, 99, 12, 1], [11, 10, 1, 1, 10, 100, 6, 0]], float)
    trades = np.asarray([[0, 2, 5, 1, 10, 100, 99, 418, 418, -10000, -10836],
                         [1, 8, 11, -1, 10, 99, 100, 418, 418, -10000, -10836]], float)
    ledger = {(session, symbol): dict(orders=orders, trades=trades, stats=np.asarray([0, 0, 0, 0, 0, 0, 0, 1, 1]))}
    config = dict(signal_id='F15', legacy_entry=False, entry_source='F15', entry_confirm=0,
                  manage_mode=3, manage_confirm=15, width_fraction=.004, hold_seconds=1800.)
    rows, latency = diagnosis.trade_details(config, ledger, ready, book, states, grids)
    assert rows[0]['支持消失箇所'] == 'TOPIXのみ'
    assert rows[0]['判断時点の少数零OFI'] == 'TOPIXのみ'
    assert rows[1]['支持消失箇所'] == '両市場'
    summary = dict(net=-21672., profit=0., loss=21672., trades=2, fees=1672, spread_drag=20000.)
    split = diagnosis.details_period(rows, [session], symbol, summary, ledger, latency)
    assert split['反転新規']['収支'] == -10836.
    assert split['通常新規']['収支'] == -10836.
    assert split['支持消失返済の箇所別']['TOPIXのみ']['収支'] == -10836.
    assert split['反転取消数'] == 1
    assert split['判断から約定秒']['返済']['中央値'] == 10.
    # ----------------------------------------
    # 返済後の損益を変えても、判断時点の支持消失ラベルは同一でなければならない。
    different = trades.copy()
    different[:, 10] = [999999., -999999.]
    changed = {(session, symbol): dict(ledger[(session, symbol)], trades=different)}
    other_rows, _ = diagnosis.trade_details(config, changed, ready, book, states, grids)
    for original, other in zip(rows, other_rows, strict=True):
        assert original['支持消失箇所'] == other['支持消失箇所']
        assert original['判断証拠'] == other['判断証拠']
    # ----------------------------------------
    # M0は確認秒を使わず、旧入口M0は管理証拠に依存しない一条件を採る。
    baseline = dict(config, legacy_entry=True, entry_source='legacy_J1', signal_id='F15', manage_mode=0, manage_confirm=0)
    current = dict(config, legacy_entry=True, entry_source='legacy_J1', signal_id='FD30')
    archive = {'保険のみ': dict(config=baseline), '支持管理': dict(config=current)}
    assert diagnosis.counterpart(archive, current, manage_mode=0, manage_confirm=0) == '保険のみ'
    assert diagnosis.decision_grid(times, grid, np.searchsorted(times, grid, side='left'), 4) == loss_g
    return dict(人工検査合格=True, 実損益閲覧=False, API取得数=0, 実注文数=0,
                片市場停止分類=True, 反転会計照合=True, 気配差照合=True,
                未来損益変更で判断ラベル不変=True, 旧入口M0対照の一意性=True)


if __name__ == '__main__':
    proof = verify()
    target = Path(__file__).resolve().parent / '分析器の人工台帳検査.json'
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(proof, ensure_ascii=False))
