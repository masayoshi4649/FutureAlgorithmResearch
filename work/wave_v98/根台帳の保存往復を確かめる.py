"""34時計政策・入口・出口の診断を根の保存経路へ接続して検算する。"""

import hashlib
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalog
import research
import strategy


def fixture(symbol: str) -> dict:
    """
    機能: 順行、局所押し、回復、利益保護と場内返済が届く人工入力を作る。
    引数: symbol(str)はTOPIX又はNK225。
    返り値: dict。実入力と区別した原板・公表済み相手源・密な許可。
    """
    scale = 1. if symbol == 'TOPIX' else 20.
    peer_scale = 20. if symbol == 'TOPIX' else 1.
    n = 801
    times = 300. + 5. * np.arange(n)
    moves = np.zeros(n)
    moves[2:7] = np.arange(1, 6) * 2.
    moves[7:12] = np.arange(9., 4., -1.)
    moves[12:17] = np.arange(6., 11.)
    moves[17:30] = 48.
    moves[30:] = 20.
    bid = (3999.5 + moves) * scale
    record = dict(symbol=symbol, start=0., limit=float(times[-1]), tick=.5*scale,
                  time_s=times, seq=np.arange(n), price=bid+.25*scale,
                  bid=bid, ask=bid+.5*scale,
                  price_valid=np.ones(n, bool), quote_valid=np.ones(n, bool))
    event = np.zeros(n, np.int8); event[1] = 1; event[16] = 1
    peer_bid = (3999.5 + moves) * peer_scale
    peer = np.column_stack((np.arange(n), np.arange(n), times-1.,
                            peer_bid, peer_bid+.5*peer_scale, np.ones(n)))
    signal = dict(grid=times.copy(), mode=np.ones(n, np.int8), mapped=np.arange(n, dtype=np.int32),
                  quality=np.ones(n, bool), reset=np.zeros(n, bool), event=event,
                  trend_width=16.*scale, loss_observations=np.full((n, 22), np.nan),
                  execution_lp_index=np.arange(n), peer_tick=.5*peer_scale,
                  entry_peer_bbo=peer, entry_j2_long=np.ones(n, bool),
                  entry_j2_short=np.ones(n, bool), wait_opposite_long=np.zeros(n, bool),
                  wait_opposite_short=np.zeros(n, bool))
    return dict(record=record, signal=signal, reference_open=4000.*scale,
                trend_candidate_state={'candidates': np.array([[1., 1., 1., 1., 1.],
                                                               [16., 16., 1., 1., 1.]])},
                trend_lp_allowed={})


def restore(changes: np.ndarray, rows: int) -> np.ndarray:
    """
    機能: 変化行形式から全原行の状態を独立復元する。
    引数: changes(ndarray[float])は先頭行番号と状態、rows(int)は原行数。
    返り値: ndarray[float]。全原行へ展開した状態。
    """
    result = np.empty((rows, changes.shape[1]-1))
    for index, row in enumerate(changes):
        end = int(changes[index+1, 0]) if index+1 < len(changes) else rows
        result[int(row[0]):end] = row[1:]
    return result


def main() -> None:
    """
    機能: 全34人工68口座を根run_oneで保存し、政策・待機・親・全8期間を再読込する。
    引数: なし。
    返り値: None。正式損益を作らず、新work内の人工保存だけを行う。
    """
    session = '2099-01-01_Day'
    prepared = {(session, symbol): fixture(symbol) for symbol in catalog.SYMBOLS}
    serial = 1
    base = HERE / f'root_preflight/人工保存往復_{serial:05d}'
    while base.exists():
        serial += 1
        base = HERE / f'root_preflight/人工保存往復_{serial:05d}'
    count = 0
    for config in catalog.catalog():
        research.run_one(config, [session], base, prepared)
        saved_all = research.read(base / 'ledgers' / (config['id']+'.pkl'))
        rows = research.read(base / 'results' / (config['id']+'.json'))['rows']
        for symbol in catalog.SYMBOLS:
            key = session, symbol
            output = strategy.play(config, key, prepared)
            saved = saved_all[key]
            assert len(output['trades']) >= 1, config['id']
            for name in ('watch_state', 'trend_exit_state', 'entry_policy_state'):
                trace = restore(saved[name+'_changes'], len(output['curve']))
                np.testing.assert_array_equal(trace, output[name+'_trace'])
                assert hashlib.sha256(trace.tobytes()).hexdigest() == saved[name+'_SHA256']
            for name in ('orders', 'trades', 'entry_parent_diagnostics', 'entry_wait_events',
                         'trend_parent_diagnostics', 'entry_policy_events'):
                np.testing.assert_array_equal(saved[name], output[name])
            assert saved['entry_policy_state_columns'] == output['entry_policy_state_columns']
            assert saved['entry_policy_event_columns'] == output['entry_policy_event_columns']
            assert saved['entry_policy_event_codes'] == output['entry_policy_event_codes']
            for name in ('全31', '前16', '後15', '旧30', '後14', '追加1', 'デイ', 'ナイト'):
                values = research.accounting.aggregate(rows, symbol, [session])
                assert values['session_count'] == 1
                stable = research.stability(rows, config, prepared, [session])[symbol]
                assert stable['session_count'] == 1
                count += 1
    paths = [HERE / name for name in ('根台帳の保存往復を確かめる.py', 'engine.py', 'strategy.py',
                                      'catalog.py', 'accounting.py', 'research.py')]
    research.save(HERE / 'root_preflight/全34人工の根台帳と時計政策及び待機出口診断の保存往復.json', dict(
        全合格=True, 人工条件数=34, 人工口座数=68, 全8商品期間=count,
        保存先=str(base.relative_to(research.ROOT)), 新時計政策及び待機出口診断一致=True,
        期間の範囲='全8期間へ同じ明示人工1場を入力。実際の日夜分類や収益性能の証明ではない。',
        正式新損益実行=0, API取得=0, 実注文=0,
        SHA256={str(path.relative_to(research.ROOT)): research.data.digest(path) for path in paths}))
    print('根の全34人工68口座の保存往復と全8期間終端が一致しました。', flush=True)


if __name__ == '__main__':
    main()
