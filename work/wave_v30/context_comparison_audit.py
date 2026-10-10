"""全対応比較の時計・最初の共通分岐・注文会計を合成相場で確認する。"""

from __future__ import annotations

from copy import deepcopy
import socket
import urllib.request

import numpy as np

import context_comparison as target


def fixture() -> tuple[dict, dict, np.ndarray]:
    """機能: 未来や成績に依存しない一定価格の合成入力を作る。

    引数: なし。返り値: 入力・管理設定・入口方向 (tuple[dict,dict,ndarray])。
    """
    count = 30
    ready = {'time_s': np.arange(count, dtype=float) * 60., 'seq': np.arange(count),
             'last': np.full(count, 100.), 'atr': np.ones(count), 'tick': .1,
             'start': -1200., 'limit': (count - 2) * 60., 'us_open': np.inf}
    cfg = target.runner.managers.make_config({'changes': {'entry_mode': 2}}, 'TOPIX', ready)
    cfg.update(warmup_min=0., entry_cutoff_min=0., cooldown_min=0., stop_atr=20., main_trail=np.inf)
    entry = np.zeros(count, dtype=np.int8)
    entry[0] = 1
    return ready, cfg, entry


def main() -> None:
    """機能: 無通信で独立会計と中立原因交代を検算し記録する。

    引数: なし。返り値: なし (None)。実セッション損益は使わない。
    """
    socket.socket.connect = target.episode.reject_network
    socket.create_connection = target.episode.reject_network
    urllib.request.OpenerDirector.open = target.episode.reject_network
    records = []
    ready, cfg, entry = fixture()
    c = np.ones_like(entry)
    c[2:] = 0
    s = np.ones_like(entry)
    s[2:7] = 0
    neutral_cfg = dict(cfg, neutral_min=10.)
    left = target.runner.engine.run(ready, entry, neutral_cfg, True, c)
    right = target.runner.engine.run(ready, entry, neutral_cfg, True, s)
    for result in (left, right):
        target.accounting(ready, result, neutral_cfg)
    causes = target.causes(ready, c, s)
    runs = target.neutral_runs(ready, c, causes, left)
    decision = [d for run in runs for d in run['中立返済判断']][0]
    assert decision['判断行'] == 12 and decision['約定行'] == 13 and decision['時計秒'] == 600.
    pieces = decision['判断までの原因区間']
    assert [(p['原因'], p['秒']) for p in pieces] == [('自己中立', 300.), ('相手不一致又は相手方向なし', 300.)]
    diff = target.first_divergence(ready, c, s, left, right)
    assert diff['最初の分岐行'] == 13 and diff['同じ分岐行のC注文']['理由'] == 10
    assert diff['同じ分岐行のS注文'] is None
    assert diff['分岐直前のC中立時計']['時計秒'] == 600. and not diff['分岐直前のS中立時計']['作動中']
    records.append({'検査': '自己中立から相手不一致へ原因が変わっても600秒時計は継続する', '一致': True})
    records.append({'検査': '最初のC返済だけを共通状態と対応し、後のS場末返済は対応させない', '一致': True})

    # ----------------------------------------
    c = np.ones_like(entry)
    c[8:] = 0
    s = np.ones_like(entry)
    s[8:] = -1
    exit_cfg = dict(cfg, signal_exit=1)
    left = target.runner.engine.run(ready, entry, exit_cfg, True, c)
    right = target.runner.engine.run(ready, entry, exit_cfg, True, s)
    diff = target.first_divergence(ready, c, s, left, right)
    assert diff['最初の分岐行'] == 9 and diff['同じ分岐行のS注文']['理由'] == 13
    assert diff['同じ分岐行のS注文']['判断行'] == 8 and diff['同じ分岐行のC注文'] is None
    assert diff['直前共通状態']['買い枚数'] == 1
    records.append({'検査': '自己反転のS返済は次原本行。C中立は反転返済しない', '一致': True})
    same = target.runner.engine.run(ready, entry, exit_cfg, True, c)
    assert target.first_divergence(ready, c, c, left, same)['注文台帳同一']
    records.append({'検査': '同じ管理方向なら注文と金銭経路も一致する', '一致': True})

    # ----------------------------------------
    duplicate = deepcopy(ready)
    duplicate['time_s'][4] = duplicate['time_s'][3]
    result = target.runner.engine.run(duplicate, entry, exit_cfg, True, s)
    target.accounting(duplicate, result, exit_cfg)
    stats = target.activity(duplicate, result)
    assert stats['保有分'] == (duplicate['time_s'][9] - duplicate['time_s'][1]) / 60
    assert stats['買い枚数分'] == stats['保有分']
    records.append({'検査': '同値時刻を0秒とし、時間積分と原本行の約定順を分離する', '一致': True})
    tampered = deepcopy(result)
    tampered['curve'][3, 5] += 1
    try:
        target.accounting(duplicate, tampered, exit_cfg)
    except AssertionError:
        records.append({'検査': '内部現金を改変すると注文からの再構成が不一致を検出する', '一致': True})
    else:
        raise AssertionError('会計改変を見逃した')
    for answer in (left, right, same):
        target.accounting(ready, answer, exit_cfg)
    records.append({'検査': '全玉返済・上下限・前行発注・取引損益と注文現金を独立照合', '一致': True})
    path = target.HERE / 'context_comparison_audit.json'
    target.runner.save(path, {'対象': '合成入力のみ', 'API取得': 0, '検査': records,
                              '実装SHA256': target.runner.digest(target.HERE / 'context_comparison.py')})
    print('原因比較の合成監査:', len(records), '件一致', flush=True)


if __name__ == '__main__':
    main()
