"""入口候補の人工経路、途中切断、未来改変、重複原本行を照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from core import candidate_signals, SIGNAL_META


HERE = Path(__file__).resolve().parent


def artificial(path: list[float] | np.ndarray, events: list[tuple] | None = None) -> tuple:
    """機能: 有効な人工気配と任意の表示補充完了を入口関数の引数にする。

    引数: path(list[float]|ndarray)、events(list[tuple]|None)。
    返り値: 入口用引数(tuple)。時刻は全行同秒、原本順は配列順である。
    """
    mid = np.asarray(path, dtype=float)
    size = len(mid)
    ev = events or []
    reset = np.zeros(size, dtype=np.bool_)
    reset[0] = True
    return (mid - .5, mid + .5, np.full(size, 100.), np.full(size, 100.),
            np.r_[0., np.diff(mid) * 100.], np.ones(size, dtype=np.bool_), reset,
            np.full(size, 300.), np.array([e[0] for e in ev], dtype=np.int64),
            np.array([e[1] for e in ev], dtype=np.int8), np.array([e[2] for e in ev], dtype=float),
            np.array([e[3] for e in ev], dtype=float), np.array([e[4] for e in ev], dtype=float), 1., 0.)


def shorter(arguments: tuple, end: int) -> tuple:
    """機能: 元行までに完了した補充だけを残して入力を途中で切る。

    引数: arguments(tuple)、end(int)。返り値: 短縮引数(tuple)。未来の補充は渡さない。
    """
    visible = arguments[8] < end
    return tuple(v[:end] if k < 8 else v[visible] if k < 13 else v
                 for k, v in enumerate(arguments))


def main() -> None:
    """機能: 全8系列の動作と過去不変性を人工経路だけで確認して保存する。

    引数: なし。返り値: なし(None)。損益ファイルは参照しない。
    """
    checks = []
    path = np.r_[np.full(3, 1000.), np.arange(1001., 1011.), np.arange(1009., 1004., -1.)]
    args = artificial(path)
    signals = candidate_signals(*args)
    assert signals[0].min() == signals[1].min() == -1
    checks.append('4/8呼値の上伸び後、2/4呼値の下戻りで反転候補')
    reflected = artificial(2000. - path)
    np.testing.assert_array_equal(candidate_signals(*reflected), -signals)
    checks.append('上下を鏡像にしたとき方向が正反対')
    for back in (2, 4):
        path = np.r_[np.full(3, 1000.), np.arange(1001., 1011.),
                     np.arange(1009., 1009. - back, -1.),
                     np.arange(1011. - back, 1011.)]
        resume = candidate_signals(*artificial(path))
        assert np.count_nonzero(resume[2 if back == 2 else 3] == 1) == 1
    jump_path = np.r_[np.full(3, 1000.), np.arange(1001., 1011.), 1008., 1011.]
    assert candidate_signals(*artificial(jump_path))[2, -1] == 1
    checks.append('2/4呼値の押し後の再開と極値を飛び越す再開')
    up = np.r_[np.full(3, 1000.), np.arange(1001., 1011.)]
    event_at = len(up) - 1
    path = np.r_[up, np.arange(1009., 1004., -1.)]
    ev = [(event_at, -1, 100., 100., 1010.5)]
    args = artificial(path, ev)
    signals = candidate_signals(*args)
    assert signals[4].min() == signals[5].min() == -1
    checks.append('売り側表示補充後の2/4呼値反落')
    reflected_events = [(event_at, 1, 100., 100., 2000. - 1010.5)]
    np.testing.assert_array_equal(candidate_signals(*artificial(2000. - path, reflected_events)), -signals)
    # 一呼値を超える前進を挟むと、止まったという仮説が失効する。
    advanced = np.r_[up, 1012., 1008., 1006.]
    assert np.count_nonzero(candidate_signals(*artificial(advanced, ev))[4:6]) == 0
    checks.append('補充後に元方向へ1呼値超え進んだ反転候補を破棄')
    long_up = np.r_[np.full(3, 1000.), np.arange(1001., 1021.)]
    event_at = len(long_up) - 1
    ev = [(event_at, -1, 100., 100., 1020.5)]
    breakout_path = np.r_[long_up, np.arange(1021., 1027.)]
    args_break = artificial(breakout_path, ev)
    assert np.count_nonzero(candidate_signals(*args_break)[6] == 1) == 1
    assert np.count_nonzero(candidate_signals(*args_break)[7] == 1) == 1
    wrong_ofi = list(args_break)
    wrong_ofi[4] = -np.abs(wrong_ofi[4])
    assert np.count_nonzero(candidate_signals(*wrong_ofi)[6:8]) == 0
    checks.append('補充価格突破、両気配前進、OFI符号支持の全条件')
    rng = np.random.default_rng(69)
    random_path = np.r_[np.full(3, 1000.), 1000. + np.cumsum(rng.choice([-1., 1.], size=2000))]
    ev = [(i, -1 if i % 2 else 1, 100., 100.,
           random_path[i] + (.5 if i % 2 else -.5)) for i in range(24, len(random_path), 17)]
    args = artificial(random_path, ev)
    full = candidate_signals(*args)
    prefix_checks = 0
    for end in (2, 9, 21, 80, 301, 777, 1801):
        np.testing.assert_array_equal(candidate_signals(*shorter(args, end)), full[:, :end])
        future = list(args)
        for k in (0, 1):
            future[k] = args[k].copy()
            future[k][end:] += 50.
        future[4] = args[4].copy()
        future[4][end:] *= -10.
        future[7] = args[7].copy()
        future[7][end:] += 1200.
        np.testing.assert_array_equal(candidate_signals(*future)[:, :end], full[:, :end])
        prefix_checks += 2
    checks.append('途中切断と未来の価格・OFI・時計の変更で過去信号が完全一致')
    duplicated = list(args)
    for k in range(8):
        duplicated[k] = np.repeat(args[k], 5)
    duplicated[4] = np.zeros(len(duplicated[0]))
    duplicated[4][::5] = args[4]
    duplicated[6] = np.zeros(len(duplicated[0]), dtype=np.bool_)
    duplicated[6][0] = True
    duplicated[8] = args[8] * 5
    repeated = candidate_signals(*duplicated)
    np.testing.assert_array_equal(repeated[:, ::5], full)
    assert np.count_nonzero(repeated[:, np.arange(repeated.shape[1]) % 5 != 0]) == 0
    checks.append('同じ中値の原本行を5倍に増やしてもティック数・全候補が同じ')
    fixed = artificial(np.full(100, 1000.))
    assert not candidate_signals(*fixed).any()
    checks.append('固定気配内の約定往復だけでは候補を発火しない')
    reset = list(artificial(np.r_[np.full(3, 1000.), np.arange(1001., 1011.), 1009., 1008.]))
    reset[6] = reset[6].copy()
    reset[6][-2] = True
    assert not candidate_signals(*reset)[0:2, -2:].any()
    checks.append('不連続を挟む古い伸びから反転候補を作らない')
    gap = list(artificial(np.r_[np.full(3, 1000.), np.arange(1001., 1011.), 1009., 1008.]))
    gap[7] = gap[7].copy()
    gap[7][-2:] += 121.
    assert not candidate_signals(*gap)[0:2, -2:].any()
    checks.append('120秒超の時計空白後は状態を初期化')
    record = dict(合格=True,人工経路の確認=checks,途中切断と未来改変の照合数=prefix_checks,
                  同秒原本順=True,ATR使用=False,EMA使用=False,損益参照=False,
                  core_SHA256=hashlib.sha256((HERE / 'core.py').read_bytes()).hexdigest(),
                  入口仕様=SIGNAL_META)
    (HERE / '入口人工経路の照合.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(合格=True,人工確認数=len(checks),prefix未来改変=prefix_checks), ensure_ascii=False))


if __name__ == '__main__':
    main()
