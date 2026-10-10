"""理想指定価格の再生を別の手計算と全脚会計で監査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import exact_engine as engine

OUT = Path(__file__).resolve().parent
SESSION = '2026-09-23_Day'
BASE = dict(entry_mode='market', entry_atr=0., initial_stop_atr=10., trail_atr=None,
            warmup_min=0., cooldown_min=0., max_age_min=60., entry_deadline_min=0.)


def prepared(prices: list[float] | np.ndarray, events: list[tuple[int, int]] | None = None,
             times: list[float] | np.ndarray | None = None, symbol: str = 'NK225') -> dict:
    """機能: 相場原本を参照しない独立した人工価格と信号を準備する。

    引数: prices (list|ndarray)、events (list[tuple]|None)、times (list|ndarray|None)、symbol (str)。
    返り値: dict: 現在価格と因果イベントの再生入力。
    """
    start = engine.bounds(SESSION)[0]
    time = np.asarray(times if times is not None else start+np.arange(len(prices))*60., dtype=float)
    seq = np.arange(len(prices), dtype=np.int64)*3+10
    tape = dict(seq=seq, time_s=time, last=np.asarray(prices, dtype=float), atr=np.full(len(prices), 100.))
    frame = pd.DataFrame([dict(family='監査', seq=int(seq[i]), side=side, source_last_seq=int(seq[i]-1),
                              time_s=float(time[i]), deadline_time_s=float(time[i]+3600))
                          for i, side in (events if events is not None else [(0, 1)])])
    return engine.prepare(tape, frame, SESSION, symbol)


def run_case(prices: list[float], overrides: dict | None = None,
             events: list[tuple[int, int]] | None = None, times: list[float] | None = None) -> tuple[dict, dict]:
    """機能: 人工ケースを既定の費用ゼロ条件で再生する。

    引数: prices (list[float])、overrides (dict|None)、events (list|None)、times (list|None)。
    返り値: tuple[dict, dict]: 準備入力と結果。
    """
    ready = prepared(prices, events=events, times=times)
    result = engine.simulate(ready, '監査', dict(BASE, **(overrides or {})), detail=True)
    return ready, result


def close_equal(actual: float | np.ndarray, expected: float | np.ndarray) -> None:
    """機能: 数値を小数誤差だけ許して照合する。

    引数: actual/expected (float|ndarray)。返り値: None。不一致時は例外。
    """
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-6, equal_nan=True)


def independent_accounting(ready: dict, result: dict) -> int:
    """機能: 出力脚を原本価格の全行へ並べ直し、含み損・DD・理想差を独立再計算する。

    引数: ready/result (dict): 再生入力と結果。
    返り値: int: 照合した集計項目数。
    """
    raw, summary = result['raw'], result['summary']
    prices = ready['last']
    multiple = engine.MULTIPLIERS[ready['symbol']]
    curve = np.zeros(len(prices))
    gross = np.zeros(len(prices))
    realized_curve = np.zeros(len(prices))
    ideal, observed, profits, losses = 0., 0., 0., 0.
    closed_count, win_count, loss_count, open_count = 0, 0, 0, 0
    entry_gap_count, exit_gap_count = 0, 0
    for row in raw:
        side, enter, finish = row[2], int(row[5]), int(row[6])
        entry, fill, closed = row[8], row[9], bool(row[14])
        points = side*(fill-entry)
        close_equal(points, row[15])
        assert enter > int(row[4]), '入口を指定した行で約定している'
        assert finish >= enter and row[20] == ready['seq'][enter] and row[21] == ready['seq'][finish]
        if closed:
            assert finish > enter
            curve[finish:] += points
            realized_curve[finish:] += points
            closed_count += 1
            win_count += int(points > 0)
            loss_count += int(points < 0)
            profits += max(points, 0)
            losses += min(points, 0)
            if int(row[13]) in [3, 4, 5, 6, 7, 8]:
                assert finish > row[17], '時間・信号返済が条件と同じ行で約定している'
                close_equal(fill, prices[finish])
            if int(row[13]) in [1, 2]:
                ideal += side*(fill-prices[finish])
                exit_gap_count += int(abs(fill-prices[finish]) > 1e-6)
        else:
            open_count += 1
        end = finish if closed else len(prices)
        curve[enter:end] += side*(prices[enter:end]-entry)
        gross[enter:end] += 1
        ideal += side*(prices[enter]-entry)
        entry_gap_count += int(abs(prices[enter]-entry) > 1e-6)
        observed += side*(prices[finish]-prices[enter])
        close_equal(row[12], max(0., np.nanmax(side*(prices[enter:finish+1]-entry))))
    valid = np.isfinite(prices) & (prices > 0)
    valid_curve = curve[valid]
    maximum = np.maximum.accumulate(np.r_[0., valid_curve])[1:]
    checks = dict(net_yen=valid_curve[-1]*multiple, closed_net_yen=realized_curve[valid][-1]*multiple,
                  profit_yen=profits*multiple, loss_yen=losses*multiple,
                  open_yen=(valid_curve[-1]-realized_curve[valid][-1])*multiple,
                  max_drawdown_yen=np.max(maximum-valid_curve)*multiple,
                  gross_peak=np.max(gross[valid]), entry_count=len(raw),
                  closed_count=closed_count, win_count=win_count, loss_count=loss_count,
                  open_count=open_count, ideal_fill_benefit_yen=ideal*multiple,
                  ideal_entry_gap_count=entry_gap_count, ideal_exit_gap_count=exit_gap_count,
                  fee_yen=0., spread_cost_yen=0.)
    for key, expected in checks.items():
        close_equal(summary[key], expected)
    close_equal(summary['net_yen'], (observed+ideal)*multiple)
    for eq in result['equity']:
        index = int(np.searchsorted(ready['seq'], eq[1]))
        close_equal(eq[2], curve[index]*multiple)
        close_equal(eq[4], gross[index])
        close_equal(eq[5], realized_curve[index]*multiple)
    return len(checks)+1


def hand_cases() -> list[dict]:
    """機能: あらかじめ計算した指定価格・複数玉・時間条件を検査する。

    引数: なし。返り値: list[dict]: 成功した人工例と期待収支。
    """
    cases = [
        ('上方向ギャップの指定新規と指定損切り', [1000, 1080, 980], dict(entry_mode='stop', entry_atr=.3, initial_stop_atr=.2), None, None, -20000., 80000.),
        ('下方向ギャップの指定新規と指定損切り', [1000, 920, 1020], dict(entry_mode='stop', entry_atr=.3, initial_stop_atr=.2), [(0, -1)], None, -20000., 80000.),
        ('指値を飛び越した場合の不利な指定約定も計上', [1000, 900, 1020], dict(entry_mode='limit', entry_atr=.3, target_atr=.5), None, None, 50000., -70000.),
        ('追跡安値更新後の反発新規と高値追跡返済', [1000, 960, 900, 920, 930, 990, 960], dict(entry_mode='trail', entry_atr=.3, initial_stop_atr=.3, trail_atr=.2, trail_start_atr=0), None, None, 40000., 10000.),
        ('反対信号による追跡短縮は次行から', [1000, 1000, 1100, 1060, 1050], dict(trail_atr=1., trail_start_atr=0., opposite_width_atr=.2), [(0, 1), (3, -1)], None, 80000., 30000.),
        ('新規時に利益幅を飛び越しても同行返済なし', [1000, 1200, 1150], dict(entry_mode='stop', entry_atr=0., target_atr=.5), None, None, 50000., 100000.),
        ('利益玉だけ返済した両建ての含み損を含む', [1000, 1000, 1100, 1120], dict(add_mode='hedge', max_legs=2, leg_targets=[.5, None]), None, None, -70000., -50000.),
        ('３枚を異なる指定幅で段階利確', [1000, 1000, 1060, 1130, 1080, 1250], dict(add_mode='simultaneous', max_legs=3, leg_targets=[.5, 1., 2.]), None, None, 350000., -90000.),
        ('同一ギャップで有限２段追加した含み損', [1000, 1000, 1120, 940], dict(add_mode='pyramid', max_legs=3, add_step_atr=.5), None, None, -330000., 90000.),
        ('固定グリッド３枚の全含み損', [1000, 1000, 870], dict(add_mode='grid', max_legs=3, add_step_atr=.5), None, None, -240000., -110000.),
        ('無効現在価格行は条件監視と約定から除外', [1000, np.nan, 1010, np.nan, 900], dict(initial_stop_atr=.2), None, None, -20000., 90000.),
    ]
    start, end = engine.bounds(SESSION)
    cases += [
        ('同一代理秒でも原本次行から約定', [1000, 1010, 1020], dict(entry_mode='stop', entry_atr=0.), None, [start]*3, 20000., 10000.),
        ('新規禁止境界で未約定注文を取消', [1000, 1030, 1100], dict(entry_mode='stop', entry_atr=.3, entry_deadline_min=30.), None, [end-1801, end-1800, end-1799], 0., 0.),
        ('強制返済条件の次行でセッション内返済', [1000, 1000, 1050, 1100], {}, None, [end-100, end-99, end, end+1], 100000., 0.),
        ('保有上限条件の次行で返済', [1000, 1000, 1040, 990], dict(holding_min=1.), None, [start, start+1, start+61, start+62], -10000., 0.),
        ('有効期限後の到達では入らない', [1000, 1050], dict(entry_mode='stop', entry_atr=.3, max_age_min=.01), None, [start, start+1], 0., 0.),
        ('暖機時間未満の通知を採用しない', [1000, 1010, 1020, 1030], dict(warmup_min=20.), [(0, 1), (2, 1)], [start+1100, start+1150, start+1200, start+1201], 0., 0.),
        ('合算損切り条件後の次行で全脚返済', [1000, 1000, 970, 950], dict(add_mode='simultaneous', max_legs=3, basket_stop_atr=.5), None, None, -150000., 0.),
        ('合算利確条件後の次行で全脚返済', [1000, 1000, 1040, 1060], dict(add_mode='simultaneous', max_legs=3, basket_target_atr=1.), None, None, 180000., 0.),
        ('反対通知による返済も次行約定', [1000, 1000, 1040, 1010], dict(reverse_exit=True), [(0, 1), (2, -1)], None, 10000., 0.),
    ]
    completed = []
    for label, prices, cfg, events, times, net, benefit in cases:
        ready, result = run_case(prices, cfg, events, times)
        close_equal(result['summary']['net_yen'], net)
        close_equal(result['summary']['ideal_fill_benefit_yen'], benefit)
        independent_accounting(ready, result)
        if label == '反対信号による追跡短縮は次行から':
            assert result['raw'][0, 6] == 4
        if label == '利益玉だけ返済した両建ての含み損を含む':
            close_equal(result['summary']['profit_yen'], 50000.)
            close_equal(result['summary']['open_yen'], -120000.)
        completed.append(dict(ケース=label, 期待収支円=net, 指定価格と到達観測価格との差円=benefit, 成功=True))
    return completed


def prefix_cases() -> dict:
    """機能: ランダム人工経路の未来を切り落とし、過去売買と全脚会計が変わらないと確認する。

    引数: なし。返り値: dict: 経路数・設定数・打切り比較数。
    """
    rng = np.random.default_rng(20260924)
    configurations = [
        dict(entry_mode='market', holding_min=3.), dict(entry_mode='stop', entry_atr=.3),
        dict(entry_mode='trail', entry_atr=.2, trail_atr=.4, trail_start_atr=.2),
        dict(entry_mode='limit', entry_atr=.3, target_atr=.4),
        dict(entry_mode='straddle', entry_atr=.5, trail_atr=.5, trail_start_atr=.3),
        dict(add_mode='hedge', max_legs=2, leg_targets=[.5, 1.]),
        dict(add_mode='simultaneous', max_legs=3, leg_targets=[.2, .4, None]),
        dict(add_mode='pyramid', max_legs=3, add_step_atr=.3, target_atr=1.),
        dict(add_mode='grid', max_legs=3, add_step_atr=.3, basket_stop_atr=.5),
        dict(reverse_exit=True, trail_atr=.7, trail_start_atr=.3),
        dict(opposite_width_atr=.1, trail_atr=1.2, trail_start_atr=.1),
        dict(breakeven_trigger_atr=.4, protect_trigger_atr=.7, protect_fraction=.6),
    ]
    comparisons, accountings, closed_checks = 0, 0, 0
    for path_number in range(30):
        prices = 5000+10*np.cumsum(rng.integers(-12, 13, size=64))
        events = [(i, int(rng.choice([-1, 1]))) for i in range(0, 64, 8)]
        ready = prepared(prices, events)
        for cfg in configurations:
            config = dict(BASE, initial_stop_atr=.8, **cfg)
            full = engine.simulate(ready, '監査', config, detail=True)
            accountings += independent_accounting(ready, full)
            for count in [7, 19, 37, 53]:
                prefix = prepared(prices[:count], [(i, side) for i, side in events if i < count])
                truncated = engine.simulate(prefix, '監査', config, detail=True)
                accountings += independent_accounting(prefix, truncated)
                old_closed = full['raw'][(full['raw'][:, 14] == 1) & (full['raw'][:, 6] < count)]
                new_closed = truncated['raw'][truncated['raw'][:, 14] == 1]
                close_equal(new_closed, old_closed)
                closed_checks += len(new_closed)
                for eq in truncated['equity']:
                    match = full['equity'][full['equity'][:, 1] == eq[1]]
                    if len(match):
                        close_equal(eq, match[0])
                comparisons += 1
    return dict(人工経路数=30, 注文設定数=len(configurations), 打切り比較数=comparisons,
                確定脚比較数=closed_checks, 独立会計項目比較数=accountings)


def main() -> None:
    """機能: 手計算と未来打切りの独立監査を実行し、日本語で記録する。

    引数: なし。返り値: None: 監査JSONを作業先へ保存する。
    """
    result = dict(成功=True, 原本相場読取=False, 最終保留読取=False, API取得回数=0,
                  エンジンSHA256=hashlib.sha256((OUT/'exact_engine.py').read_bytes()).hexdigest(),
                  手計算=hand_cases(), 打切り=prefix_cases())
    (OUT/'指定価格再生の独立監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(成功=True, 手計算ケース数=len(result['手計算']), **result['打切り']), ensure_ascii=False))


if __name__ == '__main__':
    main()
