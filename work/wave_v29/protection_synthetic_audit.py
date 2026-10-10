"""新しい残玉機構を合成経路だけで検査し、既存追跡への包含と旧互換を分ける。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import itertools
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
import engine_protection as current
import protection_design
sys.path.insert(0, str(HERE.parent / 'wave_v28'))
import engine_context as previous
sys.path.insert(0, str(HERE.parent / 'wave_v23'))
import managers


def digest(path: Path) -> str:
    """機能: 検査に用いたソースを識別する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(relative: list | np.ndarray, symbol: str = 'TOPIX', side: int = 1,
            tick: float = .5, requested_atr: float = 2., odd_even: bool = False,
            duplicate_time: bool = False) -> tuple:
    """機能: 最初の追跡注文から始まる呼値整合済み合成相場を作る。

    引数: relative (list|ndarray) は建値基準の初回ATR倍率、symbol (str)、side (int)、
    tick/requested_atr (float)、odd_even/duplicate_time (bool)。返り値: 原本形・入口・設定 (tuple)。
    """
    start = 10000.
    a = max(requested_atr, 2 * tick)
    anchor = previous.rounded(start + side * .25 * a, tick, side)
    tail = np.rint((anchor + side * a * np.asarray(relative)) / tick) * tick
    prices = np.r_[start, tail, tail[-1], tail[-1], tail[-1]]
    times = np.arange(len(prices), dtype=float) * 15.
    if duplicate_time:
        times[1:3] = times[0]
    ready = dict(last=prices, time_s=times, atr=np.full(len(prices), requested_atr), tick=tick,
                 start=0., limit=times[-2], us_open=np.inf, session='合成_Day')
    state = np.zeros(len(prices), dtype=np.int8)
    state[:2] = side
    config = managers.make_config(protection_design.catalog()[0], symbol, ready)
    config.update(warmup_min=0., entry_cutoff_min=0., cooldown_min=0.)
    if odd_even:
        config['initial_qty'] = 4 if symbol == 'TOPIX' else 9
    return ready, state, config


def account(result: dict, ready: dict, config: dict) -> None:
    """機能: 約定台帳から現金・在庫・時価を独立集計し、全返済と上限を検査する。

    引数: result/ready/config (dict)。返り値: なし (None)。
    """
    orders, trades, curve = result['orders'], result['trades'], result['curve']
    size = len(ready['last'])
    cash, inventory, realized = np.zeros(size), np.zeros(size), np.zeros(size)
    for row in orders:
        fill, source = int(row[0]), int(row[1])
        assert fill > source
        cash[fill] -= row[3] * row[4] * row[5]
        inventory[fill] += row[3] * row[4]
    for trade in trades:
        assert trade[6] < trade[7]
        np.testing.assert_allclose(trade[10], trade[2] * trade[3] * (trade[5] - trade[4]), atol=1e-7, rtol=0)
        realized[int(trade[7])] += trade[10]
    cash, inventory, realized = np.cumsum(cash), np.cumsum(inventory), np.cumsum(realized)
    equity = cash + inventory * ready['last']
    np.testing.assert_allclose(curve[:, 0], equity, atol=1e-6, rtol=0)
    np.testing.assert_allclose(curve[:, 1], realized, atol=1e-6, rtol=0)
    np.testing.assert_allclose(curve[:, 5], cash, atol=1e-6, rtol=0)
    np.testing.assert_allclose(curve[:, 6], inventory, atol=1e-6, rtol=0)
    assert inventory[-1] == 0 and result['stats'][9] == 0
    assert result['stats'][2] <= config['audit_cap'] and result['stats'][3] <= config['audit_cap']
    np.testing.assert_allclose(trades[:, 10].sum(), result['stats'][0], atol=1e-6, rtol=0)


def exact(first: dict, second: dict) -> None:
    """機能: 理由を含む全出力が完全一致することを確認する。

    引数: first/second (dict)。返り値: なし (None)。
    """
    assert set(first) == set(second)
    for key in first:
        np.testing.assert_array_equal(first[key], second[key], err_msg=key)


def economic(first: dict, second: dict) -> int:
    """機能: 理由コードだけを除き、価格・数量・時刻・全行時価の一致を確認する。

    引数: first/second (dict)。返り値: 理由が異なる返済件数 (int)。
    """
    reason_columns = {'trades': 9, 'orders': 6, 'cycles': 9}
    for key in first:
        if key in reason_columns:
            a = np.delete(first[key], reason_columns[key], axis=1)
            b = np.delete(second[key], reason_columns[key], axis=1)
            np.testing.assert_array_equal(a, b, err_msg='経済的相違:' + key)
        else:
            np.testing.assert_array_equal(first[key], second[key], err_msg='経済的相違:' + key)
    return int(np.count_nonzero(first['trades'][:, 9] != second['trades'][:, 9]))


def compatibility() -> dict:
    """機能: 旧20管理の既定・明示無効設定を、複数合成経路と二入力で厳密比較する。

    引数: なし。返り値: 理由を含む完全互換件数 (dict)。
    """
    assert current.PARAMS[:-2] == previous.PARAMS
    assert current.REASONS == previous.REASONS
    paths = ([0, .5, 1, 2, 3, 2, 0, -2], [0, -.2, -.8, -2, -3, -1, 2, 0],
             [3, -4, 4, -5, 5, -6, 0], [0, .5, 1.5, 2, 1.75, 3, 3.5, .5, -1])
    count = 0
    for symbol, path, old_spec in itertools.product(('TOPIX', 'NK225'), paths, managers.manager_catalog()):
        ready, _, _ = fixture(path, symbol)
        state = np.where(np.arange(len(ready['last'])) < len(ready['last']) // 2, 1, -1).astype(np.int8)
        config = managers.make_config(old_spec, symbol, ready)
        config.update(warmup_min=0., entry_cutoff_min=0., cooldown_min=0.)
        for context in (None, -state):
            legacy = previous.run(ready, state, config, True, context)
            for actual in (config, dict(config, residual_risk_cap=0, lock_activation_r=1.)):
                answer = current.run(ready, state, actual, True, context)
                exact(legacy, answer)
                account(answer, ready, actual)
                count += 1
    return {'理由を含む旧仕様完全一致件数': count, '旧PARAMSの順序維持': True, '旧理由コード維持': True}


def containment() -> dict:
    """機能: 固定split2/trail3で残玉制限の有無が金銭経路を変えるかを合成検査する。

    引数: なし。返り値: 全比較数・理由差・検査した境界 (dict)。
    """
    scenarios = [
        ('通常上昇後反落', [0, .5, 1, 1.5, 2, 2.5, 3, 2.5, 1.5, 0, -2], .5, 2., False, False),
        ('2ATR頂点の同値ストップ追跡', [0, .5, 1, 1.5, 2, 1.5, 0, -1, -2], .5, 2., False, False),
        ('部分利確後の価格飛び', [0, .5, 1.5, 2, 2.5, -6, -7], .5, 2., True, False),
        ('約定済条件と同時イベント', [3, -4, -6, 5, -8], .5, 2., False, False),
        ('呼値境界と奇偶反転', [0, 1.49, 1.51, 1.99, 2.01, 2.49, .99, -.99, -2], .5, 1.3, True, False),
        ('ATR最低二呼値', [0, 1, 1.5, 2, 3, .5, -3], 5., .1, False, False),
        ('同一時刻内の原本順', [0, 1.5, 2, 3, 3.5, -4, 2], .1, .7, True, True),
    ]
    count = differences = partial = 0
    sample_differences = []
    for spec, symbol, side, scenario in itertools.product(protection_design.catalog(), ('TOPIX', 'NK225'), (-1, 1), scenarios):
        name, path, tick, atr, odd_even, duplicates = scenario
        ready, state, config = fixture(path, symbol, side, tick, atr, odd_even, duplicates)
        config.update({key: value for key, value in spec['changes'].items() if key not in ('quantity_fraction',)})
        no_cap = current.run(ready, state, dict(config, residual_risk_cap=0), True)
        capped = current.run(ready, state, dict(config, residual_risk_cap=1), True)
        delta = economic(no_cap, capped)
        count += 1
        differences += delta
        partial += int(np.any(no_cap['trades'][:, 9] == 7))
        account(no_cap, ready, config)
        account(capped, ready, config)
        if delta and len(sample_differences) < 8:
            sample_differences.append({'管理': spec['id'], '相場': name, '銘柄': symbol, '売買方向': side,
                                      '旧理由': no_cap['trades'][:, 9].astype(int).tolist(),
                                      'cap理由': capped['trades'][:, 9].astype(int).tolist()})
    return {'比較数': count, '全て価格数量時刻曲線損益一致': True, '部分利確を実際に含む比較数': partial,
            '理由差の返済件数': differences, '理由差の例': sample_differences,
            '合成境界': [row[0] for row in scenarios], '固定管理条件数': len(protection_design.catalog()),
            '包含の説明': '2ATR部分利確時の3ATR追跡水準が初期1ATRストップ以上に厳しい。理由だけ変わる同値注文を新しい経済効果と数えない。'}


def feature_and_causality() -> dict:
    """機能: 包含しない合成設定でcapの実装効果、開始R、次行有効と不正併用拒否を確認する。

    引数: なし。返り値: 個別機能の検算結果 (dict)。
    固定探索を変える処理ではなく、機能が配線されていることを確認する合成診断だけである。
    """
    ready, state, config = fixture([0, .5, 1.5, 2, 2.5, 1, -.5, -1, -2, -3, -4])
    separate = dict(config, main_trail=np.inf)
    free = current.run(ready, state, dict(separate, residual_risk_cap=0), True)
    capped = current.run(ready, state, dict(separate, residual_risk_cap=1), True)
    assert capped['stats'][0] > free['stats'][0]
    account(free, ready, separate)
    account(capped, ready, separate)
    modes = []
    for activation in (1., 2., 3.):
        actual = dict(config, split_target=0., main_trail=np.inf, lock_fraction=.5, lock_activation_r=activation)
        result = current.run(ready, state, actual, True)
        account(result, ready, actual)
        modes.append(float(result['stats'][0]))
    assert modes[1] > modes[2], '2Rを通過し3Rに達しない経路で開始Rの違いがない'
    prefix_count = 0
    cfg = dict(config, residual_risk_cap=1, lock_fraction=.5, lock_activation_r=2.)
    full = current.run(ready, state, cfg, True)
    for stop in (3, 5, 7, 9):
        short = {key: value[:stop] if isinstance(value, np.ndarray) else value for key, value in ready.items()}
        answer = current.run(short, state[:stop], cfg, True)
        np.testing.assert_array_equal(answer['curve'], full['curve'][:stop])
        np.testing.assert_array_equal(answer['orders'], full['orders'][full['orders'][:, 0] < stop])
        np.testing.assert_array_equal(answer['trades'], full['trades'][full['trades'][:, 7] < stop])
        prefix_count += 1
    rejected = 0
    for changed in ({'residual_risk_cap': -1}, {'residual_risk_cap': 2}, {'residual_risk_cap': np.nan},
                    {'lock_activation_r': 0}, {'lock_activation_r': np.inf}, {'lock_activation_r': '2'},
                    {'residual_risk_cap': 1, 'add_mode': 1}, {'residual_risk_cap': 1, 'hedge_ratio': .5},
                    {'residual_risk_cap': 1, 'cover_add': 1}, {'residual_risk_cap': 1, 'reverse_mode': 1},
                    {'lock_activation_r': 2., 'add_mode': 1}, {'lock_activation_r': 2., 'hedge_ratio': .5}):
        try:
            current.run(ready, state, dict(config, **changed), True)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError('不正設定が受理された')
    return {'追跡を外した合成ではcap効果あり': True, '開始Rによる保護時点差あり': True,
            '開始1_2_3Rの合成収支': modes, '未来末尾削除の完全一致数': prefix_count,
            '不正併用と値の拒否数': rejected, '合成診断の追跡なし設定を探索カタログへ追加しない': True}


def main() -> None:
    """機能: 旧互換・包含・新機能の合成検算を実行して保存する。

    引数: なし。返り値: なし (None)。保存相場も現在相場も読み込まない。
    """
    before = {str(path): digest(path) for path in (HERE / 'engine_protection.py', HERE.parent / 'wave_v28' / 'engine_context.py')}
    result = {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '実相場データ未読': True, '現在データ未読': True,
              '互換': compatibility(), '包含': containment(), '個別機能': feature_and_causality(), 'コードSHA256': before}
    assert before == {path: digest(Path(path)) for path in before}
    (HERE / 'protection_synthetic_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('互換', '包含', '個別機能')}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
