"""方向鮮度の診断指標を、損益結果を読まず合成入力で検査する。"""

from __future__ import annotations

import numpy as np

import episode_audit as target


def fixture() -> tuple[dict, dict]:
    """機能: 保有・無建玉を分けやすい一定価格の合成場を作る。

    引数: なし。返り値: 入力と固定設定 (tuple[dict,dict])。
    """
    n = 20
    ready = {'time_s': np.arange(n, dtype=float) * 60, 'seq': np.arange(n),
             'last': np.full(n, 100.), 'atr': np.ones(n), 'tick': .1, 'start': 0., 'limit': 1080., 'us_open': np.inf}
    config = target.runner.managers.make_config({'changes': {'entry_mode': 2}}, 'TOPIX', ready)
    config.update(warmup_min=0., cooldown_min=0., entry_cutoff_min=0., stop_atr=100., main_trail=np.inf, timeout_min=3.)
    return ready, config


def main() -> None:
    """機能: 時間積分・無取引・同値時刻・場末次行・開始待ちを検査する。

    引数: なし。返り値: なし (None)。相場の成績を参照しない。
    """
    target.deny_network()
    checks = []
    ready, config = fixture()
    entry = np.zeros(20, dtype=np.int8)
    entry[0], entry[9] = 1, -1
    result = target.runner.engine.run(ready, entry, config, True)
    target.account(ready, result, config)
    value = target.participation(ready, result, entry, entry, entry)
    for name, expected in [('買い枚数分', 4), ('売り枚数分', 4), ('保有分', 8), ('無建玉分', 10),
                           ('初回新規待ち分', 1), ('返済後再開待ち分', 5), ('最終返済後待ち分', 4)]:
        assert value[name] == expected, (name, value[name], expected)
    for name, expected in target.runner.participation(result, ready).items():
        assert value[name] == expected
    checks.append('独立curve積分が手計算の買売枚数分と3種類の無建玉時間、および取引台帳と一致')
    zeros = np.zeros_like(entry)
    flat = target.runner.engine.run(ready, zeros, config, True)
    inactive = target.participation(ready, flat, zeros, zeros, zeros)
    assert inactive['初回新規待ち分'] == 18 and inactive['無建玉分'] == 18 and inactive['first_entry_min'] is None
    checks.append('無取引は全観測時間を初回待ちとして計上し、存在しない新規時刻を0としない')
    duplicate = dict(ready, time_s=ready['time_s'].copy())
    duplicate['time_s'][3] = duplicate['time_s'][2]
    answer = target.runner.engine.run(duplicate, entry, config, True)
    target.account(duplicate, answer, config)
    value = target.participation(duplicate, answer, entry, entry, entry)
    for name, expected in target.runner.participation(answer, duplicate).items():
        assert value[name] == expected
    checks.append('同時刻の状態変更の時間寄与は0、原本順約定と台帳寿命の積分が一致')
    single = np.zeros_like(entry)
    single[0] = 1
    held = target.runner.engine.run(ready, single, dict(config, timeout_min=360.), True)
    target.account(ready, held, config)
    value = target.participation(ready, held, single, single, single)
    assert value['買い枚数分'] == 17 and value['long_unit_minutes'] == 18
    assert value['場末後等の区間外買い枚数分'] == 1
    checks.append('場末判断から次行返済までの1分を全台帳へ含め、場内clipとの差を別計上')
    times = np.array([0., 60., 60., 120., 180.])
    state = np.array([0., 1., 3., 0., 0.])
    assert target.metrics.integrate(times, state, 30., 150.) == 3.
    checks.append('波境界の部分区間と同値時刻を原本行の直前状態から積分')
    source = np.array([0, 1, 0, -1, 0], dtype=np.int8)
    main = np.array([1, 1, -1, -1, 1], dtype=np.int8)
    variant = {'delay_seconds': 60., 'mode': 'lag'}
    delayed = target.runner.lag_design.transform(times, source, main, main, variant)
    waited = target.runner.lag_design.transform(times, source, main, main, dict(variant, mode='start_only'))
    gate = int(np.flatnonzero(delayed[0] != 0)[0])
    assert gate == 4 and waited[0][gate] == 0 and waited[1][gate] == 1
    checks.append('開始待ちの解放行で現在entryが0でもcontextは解放。V/Wの初回非0一致を誤要求しない')
    fixed = target.runner.read(target.HERE / '探索条件の固定.json')
    template = target.runner.research.summarize(flat, config, 'TOPIX', '2026-09-21_Day', '合成')
    sessions = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day', '2026-09-22_Night',
                '2026-09-23_Day', '2026-09-23_Night', '2026-09-24_Day', '2026-09-24_Night',
                '2026-09-25_Day', '2026-09-25_Night', '2026-09-28_Day', '2026-09-28_Night', '2026-09-29_Day']
    values = []
    for signal in fixed['signals']:
        methods = [row for row in target.catalog(fixed) if row['signal']['id'] == signal['id']]
        members = [{'id': method['id'], 'session': session, 'symbol': symbol, **inactive,
                    '損益': dict(template, id=method['id'], session=session, symbol=symbol)}
                   for method in methods for session in sessions for symbol in ('TOPIX', 'NK225')]
        values.append({'signal': signal, '手法': methods, '参加': members})
    aggregate = target.aggregate_participation(values)
    assert len(aggregate['全期間']) == 840 and len(aggregate['週別']) == 1680 and len(aggregate['等重み集計']) == 84
    assert all(row['無建玉分'] == 234 for row in aggregate['全期間'])
    assert all(row['収支差円'] == 0 and row['買い枚数分差'] == 0 for row in aggregate['対照差'])
    checks.append('合成420条件を全26区間/週/期間へ集計し、全1,008対照差と84等重み群が正しい')
    target.runner.save(target.HERE / 'episode_participation_audit.json',
                       {'合成検査全合格': True, '検査': checks, 'API取得数': 0, '損益結果未使用': True,
                        '計測コードSHA256': target.runner.digest(target.HERE / 'episode_audit.py')})
    print('波・参加の合成検査:', len(checks), '件一致', flush=True)


if __name__ == '__main__':
    main()
