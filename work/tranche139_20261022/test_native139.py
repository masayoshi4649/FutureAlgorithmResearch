"""独立出口の走査短絡が注文を変えないことを人工経路だけで確認する。"""

from hashlib import sha256
import json
from pathlib import Path

import numpy as np

import engine139
import engine139_native


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sample(side=1, path='wave'):
    """
    機能: 追撃・利益返済・再追加・停止を含む人工価格と二行だけの親を作る。
    引数: side(int)は買い1又は売り-1、path(str)は波形識別子。
    返り値: tupleは両エンジンに同じ形式で渡す七つの入力。
    """
    times = np.arange(1001, dtype=float)
    if path == 'wave':
        move = np.interp(times, [0, 150, 220, 450, 520, 700, 800, 1000], [0, 75, 22.5, 140, 80, 190, -100, -110])
    elif path == 'trend':
        move = times * .2
    elif path == 'stop':
        move = -times * .5
    else:
        move = np.zeros(len(times))
    middle = 1000. + side * move
    bid, ask = middle - .5, middle + .5
    valid = np.ones(len(times), dtype=bool)
    valid[180:185] = False
    quotes = dict(bid=bid, ask=ask, quote_valid=valid)
    atr = np.full(len(times), 20.)
    market = np.ones((len(times), 12))
    market[:, 4:8] *= side
    market[:, 8] = times - .01
    phase = np.ones(len(times), dtype=np.int64)
    opened = ask[1] if side > 0 else bid[1]
    closed = bid[-1] if side > 0 else ask[-1]
    original = np.array([[1, 0, 1, side, 5, opened, 1, 1, 0, 1, 0, 1],
                         [1000, 999, 1, -side, 5, closed, 2, 0, 0, 1000, 999, 1]], dtype=float)
    return times, quotes, atr, market, phase, original


def main():
    """
    機能: 買売・追撃・再追加・部分保護・終端返済で旧核と注文の完全同値を確認する。
    引数: なし。
    返り値: None。SHA256付き人工確認JSONを保存する。
    """
    configs = [
        dict(id='終端のみ', initial=5, target=5, increments=[], steps=[]),
        dict(id='初回停止', initial=2, target=5, increments=[], steps=[], stop_width=1.),
        dict(id='三段追撃停止', initial=2, target=5, increments=[1, 1, 1], steps=[.25, .5, .75], stop_width=1.),
        dict(id='玉別追尾', initial=2, target=5, increments=[1, 1, 1], steps=[.25, .5, .75],
             stop_width=2., exit_activation=[0., .5, .5, .5], exit_width=[1., 1., .75, .5]),
        dict(id='再追加', initial=2, target=5, increments=[1, 1, 1], steps=[.25, .5, .75],
             stop_width=2., exit_activation=[0., .5, .5, .5], exit_width=[1., .5, .5, .5],
             recycle_rounds=2, cooldown=30., recycle_step=.25),
        dict(id='部分保護', initial=2, target=5, increments=[3], steps=[.25],
             stop_width=2., exit_activation=[0., .5], exit_width=[1., .5], profit_take=1),
        dict(id='初回追尾', initial=5, target=5, increments=[], steps=[],
             stop_width=2., exit_activation=1., exit_width=.5),
    ]
    checks = []
    recycling_seen = False
    partial_seen = False
    early_close_seen = False
    for side in (-1, 1):
        for path in ('wave', 'trend', 'stop', 'flat'):
            args = sample(side, path)
            for config in configs:
                old = engine139.replay(*args, config)
                new = engine139_native.replay(*args, config)
                assert np.array_equal(old, new), (side, path, config['id'])
                checks.append(dict(方向=side, 人工経路=path, 条件=config['id'], 注文数=len(new), 最終約定行=int(new[-1, 0])))
                recycling_seen |= bool(np.any(new[:, 6] == 1393.))
                partial_seen |= bool(np.any((new[:, 6] == 1391.) & (new[:, 4] == 1.)))
                early_close_seen |= bool(new[-1, 0] < 1000.)
    assert recycling_seen and partial_seen and early_close_seen

    # ----------------------------------------
    # 通常の途中返済通知を誤って渡した場合は、専用核への入力を拒否する。
    args = list(sample())
    base = args[-1]
    partial = base[-1].copy()
    partial[0] = 900
    partial[1] = 899
    partial[4] = 2
    tail = base[-1].copy()
    tail[4] = 3
    args[-1] = np.vstack([base[0], partial, tail])
    rejected = False
    try:
        engine139_native.replay(*args, configs[0])
    except AssertionError:
        rejected = True
    assert rejected
    sources = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
               for path in (HERE / 'engine139.py', HERE / 'engine139_native.py', Path(__file__).resolve())}
    result = dict(結果='全件合格', 注文同値条件数=len(checks), 条件=checks,
                  再追加実行確認=recycling_seen, 部分保護実行確認=partial_seen, 終端前全返済確認=early_close_seen,
                  通常部分返済入力拒否=rejected, 実装=sources, 金融再生=0, API=0, 実注文=0)
    (HERE / '独立出口短絡_人工確認.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(結果=result['結果'], 注文同値条件数=len(checks)), ensure_ascii=False))


if __name__ == '__main__':
    main()
