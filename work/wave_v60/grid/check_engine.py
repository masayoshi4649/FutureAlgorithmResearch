"""格子の上限・gap・両建て・待機指値・将来非参照を損益前に合成検査する。"""

import json
from pathlib import Path

import numpy as np

from accounting import check_accounting
from backtest import account_week, summarize
from engine import replay


HERE = Path(__file__).resolve().parent


def fixture(prices: list[float], direction_events: list[list[float]] | None = None,
            times: np.ndarray | None = None) -> dict:
    """機能: 末尾に清算判断行と次行を持つ単一週の合成原本を作る。

    引数: prices(list[float])、direction_events(list[list[float]]|None)、times(ndarray|None)。
    返り値: 再生器引数(dict)。売買成績を使った閾値調整はしない。
    """
    mid = np.asarray(prices, float)
    if times is None:
        times = np.r_[np.arange(len(mid) - 2, dtype=float), 1000., 1001.]
    events = np.asarray(direction_events if direction_events is not None else [[0., 0., 0., 1.]], float)
    return dict(times=times, seqs=np.arange(len(mid), dtype=np.int64), mid=mid,
                bid=mid - 1., ask=mid + 1., sessions=np.zeros(len(mid), np.int64),
                limits=np.array([1060.]), events=events, final_reason=1)


def run(data: dict, family: int = 0, mode: int = 0, carry: int = 1, finish: bool = True) -> tuple:
    """機能: 一方向10枚・5段・間隔10の共通設定で機構試験を実行する。

    引数: data(dict)、family/mode/carry(int)、finish(bool)。返り値: 再生結果(tuple)。
    """
    return replay(**data, family=family, steps=5, carry=carry, mode=mode, fraction=.001,
                  cap=10, value=1000., tick=1., fee_tenths=418, finish=finish)


def main() -> None:
    """機能: 既知の価格経路だけで、全familyと注文モデルの会計・数量・時系列を検証する。

    引数: なし。返り値: なし(None)。合格証跡をgrid内へ保存する。
    """
    checks = []
    base = [10000., 10000., 9990., 9989., 9988., 10001., 10002., 10000., 10000.]
    for family in range(5):
        for mode in range(3):
            for carry in range(2):
                result = run(fixture(base), family, mode, carry)
                orders, trades, equity, mid_equity, risks = result[:5]
                assert np.all(risks[:, :2] <= 10) and np.all(risks[:, :2] >= 0)
                assert not np.any(result[6][:, 1] > 0)
                assert np.all(orders[:, 2] > orders[:, 1])
                np.testing.assert_allclose(equity[-1], trades[:, 18].sum(), atol=1e-6)
                assert np.all(orders[:, 13] == np.floor(orders[:, 11] * 418 / 10))
                checks.append(dict(検査='売買方向別上限と手数料全会計', family=family, mode=mode, carry=carry))
    # ----------------------------------------
    # 複数段を一度に飛ぶ条件注文は、間の格子価格を捏造せず同じ次行価格で約定する。
    gap = fixture([10000., 10000., 9900., 9870., 9880., 9880., 9880.])
    result = run(gap)
    entries = result[0][result[0][:, 9] == 1]
    assert len(entries) == 5 and np.all(entries[:, 12] == 9871.) and entries[:, 11].sum() == 10
    assert np.all(entries[:, 2] == 3)
    checks.append(dict(検査='5段gapの同じ実値約定'))
    delayed = fixture([10000., 10000., 9900., 9870., 9880., 9880.],
                      times=np.array([0., 1., 2., 800., 1000., 1001.]))
    result = run(delayed)
    assert len(result[0]) == 0 and len(result[9]) == 5
    checks.append(dict(検査='新規約定が締切を超えた場合の取消'))
    crossed = fixture([10000., 10000., 9900., 9900., 9900., 9900., 9900., 9900.],
                      times=np.array([0., 1., 2., 3., 1000., 2000., 3000., 3001.]))
    crossed['sessions'][5:] = 1
    crossed['limits'] = np.array([1060., 3060.])
    try:
        run(crossed, carry=0)
    except ValueError as error:
        assert '場内型' in str(error)
    else:
        raise AssertionError('場内型の前場返済未完了を次場へ持ち越しました')
    carried = run(crossed, carry=1)
    assert np.any(carried[4][4, :2] > 0)
    checks.append(dict(検査='場内型の場跨ぎ返済禁止と週内型の持越し許可'))
    crossed['bid'][4] -= 100.
    carried = run(crossed, carry=1)
    stream = dict(symbol='TOPIX', week='2026-09-21', sessions=['2026-09-21_Day', '2026-09-21_Night'],
                  offsets=np.array([0, 5]), final_reason=1)
    accounts, _ = account_week(stream, carried)
    total = summarize(accounts)
    for field, raw in (('drawdown', carried[2]), ('mid_drawdown', carried[3])):
        path = np.r_[0., raw]
        np.testing.assert_allclose(total[field], np.max(np.maximum.accumulate(path) - path))
    np.testing.assert_allclose(sum(a['net'] for a in accounts), carried[2][-1])
    checks.append(dict(検査='持越しと場末spread変化を含む中値と清算気配のDD別集計'))
    loss_gap = fixture([10000., 10000., 9900., 9870., 9000., 8900., 10000., 10000., 10000.])
    result = run(loss_gap, family=1)
    forced = result[0][result[0][:, 15] == 4]
    assert len(forced) == 1 and forced[0, 12] == 8899. and forced[0, 11] == 10
    assert result[2][-1] < -600000.
    checks.append(dict(検査='週予算を跨ぐgapは観測実値で返済し超過を隠さない'))
    # ----------------------------------------
    # 通過確認付き指値は触値では成立せず、既に待機していた価格だけを用いる。
    passive = fixture([10000., 10000., 9989., 9988., 10000., 10001., 10002., 10002., 10002.])
    result = run(passive, mode=2)
    entries, exits = result[0][result[0][:, 9] == 1], result[0][result[0][:, 9] == 2]
    assert len(entries) == 1 and entries[0, 2] == 3 and entries[0, 12] == 9990.
    assert exits[0, 2] == 6 and exits[0, 12] == 10000. and exits[0, 15] == 10
    checks.append(dict(検査='待機指値の触値不成立と通過成立'))
    # ----------------------------------------
    # 方向unknownはカバー解除の根拠にせず、有効な中立公開で初めて解除する。
    covered = fixture([10000., 10000., 9980., 9980., 9980., 9980., 9980., 9980., 9980., 9980., 9980., 9980.],
                      [[0., 0., 0., 1.], [4., -40., -20., 1.], [6., 0., 0., 0.], [8., 0., 0., 1.]])
    result = run(covered, family=3)
    cover_open = result[0][result[0][:, 15] == 7]
    cover_close = result[0][result[0][:, 15] == 8]
    assert len(cover_open) == 1 and len(cover_close) == 1
    assert cover_open[0, 2] == 5 and cover_close[0, 1] == 8 and cover_close[0, 2] == 9
    assert np.max(result[4][:, 0]) <= 10 and np.max(result[4][:, 1]) <= 10
    checks.append(dict(検査='カバー数量とunknown方向の区別'))
    # ----------------------------------------
    # 途中で終わる再生は仮想清算しない。未来の切断・改変は過去の注文を変えない。
    data = fixture(base)
    for family in range(5):
        for mode in range(3):
            full = run(data, family, mode)[0]
            for cut in (4, 6):
                short = {k: (v[:cut] if k in ('times', 'seqs', 'mid', 'bid', 'ask', 'sessions') else v)
                         for k, v in data.items()}
                short['events'] = data['events'][data['events'][:, 0] < cut]
                short['final_reason'] = 0
                part = run(short, family, mode, finish=False)[0]
                np.testing.assert_array_equal(part, full[full[:, 2] < cut])
                changed = {k: v.copy() if isinstance(v, np.ndarray) else v for k, v in data.items()}
                for key in ('mid', 'bid', 'ask'):
                    changed[key][cut:] += 100.
                altered = run(changed, family, mode)[0]
                np.testing.assert_array_equal(altered[altered[:, 2] < cut], full[full[:, 2] < cut])
                checks.append(dict(検査='未来切断と未来改変', family=family, mode=mode, cut=cut))
    result = dict(合格=True, 件数=len(checks), 手数料会計=check_accounting(), 詳細=checks)
    (HERE / '合成検査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(合格=True, 件数=len(checks)), ensure_ascii=False))


if __name__ == '__main__':
    main()
