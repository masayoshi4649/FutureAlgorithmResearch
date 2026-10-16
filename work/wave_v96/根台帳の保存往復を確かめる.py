"""新しい出口診断を根の正式台帳と同じ保存経路で検算する。"""

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


def fixture() -> dict:
    """
    機能: 順行後保護と反落返済を含む最小の人工入力を作る。
    引数: なし。
    返り値: dict。実データと区別した新規・返済の人工素材。
    """
    times = np.array([0., 300., 301., 302., 303., 304., 305., 306., 307., 4000., 4940., 5000.])
    bid = np.array([3999.5, 3999.5, 3999.5, 4008., 4010., 4009., 4008., 4004., 4000., 3990., 3990., 3990.])
    n = len(times)
    record = dict(symbol='TOPIX', start=0., limit=5000., tick=.5, time_s=times,
                  seq=np.arange(n), price=bid+.25, bid=bid, ask=bid+.5,
                  price_valid=np.ones(n, bool), quote_valid=np.ones(n, bool))
    event = np.zeros(n, np.int8)
    event[1] = 1
    signal = dict(grid=times.copy(), mode=np.ones(n, np.int8), mapped=np.arange(n),
                  quality=np.ones(n, bool), reset=np.zeros(n, bool), event=event,
                  trend_width=16., loss_observations=np.full((n, 22), np.nan),
                  execution_lp_index=np.arange(n))
    return dict(record=record, signal=signal, reference_open=4000.,
                trend_candidate_state={'candidates': np.array([[1., 1., 1., 1., 1.]])},
                trend_lp_allowed={})


def restore(changes: np.ndarray, rows: int) -> np.ndarray:
    """
    機能: 変化行形式から全原行の診断を独立復元する。
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
    機能: 18人工条件を根run_oneで保存し、新診断・親会計・指紋を検算する。
    引数: なし。
    返り値: None。正式損益を作らず、新work内の人工保存だけを行う。
    """
    key = ('2099-01-01_Day', 'TOPIX')
    own = fixture()
    other = fixture()
    other['record'] = dict(other['record'], symbol='NK225', tick=10.,
                           price=other['record']['price']*20.,
                           bid=other['record']['bid']*20., ask=other['record']['ask']*20.)
    other['signal'] = dict(other['signal'], trend_width=320.)
    other['reference_open'] = 80000.
    prepared = {key: own, (key[0], 'NK225'): other}
    serial = 1
    base = HERE / f'root_preflight/人工保存往復_{serial:05d}'
    while base.exists():
        serial += 1
        base = HERE / f'root_preflight/人工保存往復_{serial:05d}'
    for config in catalog.catalog():
        output = strategy.play(config, key, prepared)
        research.run_one(config, [key[0]], base, prepared)
        saved = research.read(base / 'ledgers' / (config['id']+'.pkl'))[key]
        trace = restore(saved['trend_exit_state_changes'], len(output['curve']))
        np.testing.assert_array_equal(trace, output['trend_exit_state_trace'])
        np.testing.assert_array_equal(saved['orders'], output['orders'])
        np.testing.assert_array_equal(saved['trades'], output['trades'])
        np.testing.assert_array_equal(saved['trend_parent_diagnostics'], output['trend_parent_diagnostics'])
        assert saved['trend_line_owners'] == output['trend_line_owners']
        assert hashlib.sha256(trace.tobytes()).hexdigest() == saved['trend_exit_state_SHA256']
        assert np.isclose(saved['trades'][:, 11].sum(), output['curve'][-1], atol=1e-5)
    paths = [HERE / name for name in ('根台帳の保存往復を確かめる.py', 'engine.py', 'strategy.py',
                                      'catalog.py', 'accounting.py', 'research.py')]
    research.save(HERE / 'root_preflight/全18人工の根台帳と新出口診断の保存往復.json', dict(
        全合格=True, 人工条件数=18, 人工口座数=36,
        保存先=str(base.relative_to(research.ROOT)), 新出口状態及び親診断一致=True,
        正式新損益実行=0, API取得=0, 実注文=0,
        SHA256={str(path.relative_to(research.ROOT)): research.data.digest(path) for path in paths}))
    print('根の全18人工台帳と新出口診断の保存往復が一致しました。', flush=True)


if __name__ == '__main__':
    main()
