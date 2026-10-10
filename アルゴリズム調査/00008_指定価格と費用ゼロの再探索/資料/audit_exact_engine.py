"""指定価格約定の手計算例と、未来原本を打ち切ったときの不変性を検査する。"""

from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

import exact_engine as engine

OUT = Path(__file__).resolve().parent


def fixture(prices: list[float], event_rows: list[int] | None = None,
            sides: list[int] | None = None, clock: list[float] | None = None) -> dict:
    """機能: 人が追跡できる人工原本を作成する。

    引数: prices (list[float])、event_rows/sides (list[int]|None)、clock (list[float]|None)。
    返り値: 準備済み入力 (dict)。
    """
    times = np.array(clock if clock is not None else np.arange(len(prices)), dtype=float)
    rows = event_rows if event_rows is not None else [0]
    directions = sides if sides is not None else [1] * len(rows)
    tape = dict(seq=np.arange(1, len(prices) + 1), time_s=times,
                last=np.array(prices, dtype=float), atr=np.full(len(prices), 20.))
    events = pd.DataFrame([dict(family='試験', seq=i + 1, side=side, source_last_seq=i,
                               time_s=times[i], deadline_time_s=np.inf)
                           for i, side in zip(rows, directions)])
    ready = engine.prepare(tape, events, '2026-09-21_Day', 'NK225')
    ready.update(start=0., limit=100000., us_open=np.inf)
    return ready


def run_case(name: str, prices: list[float], cfg: dict, expected: dict,
             event_rows: list[int] | None = None, sides: list[int] | None = None,
             clock: list[float] | None = None, overrides: dict | None = None) -> tuple[dict, dict]:
    """機能: 手計算の利益・損失・枚数等と再生結果を照合する。

    引数: name (str)、prices (list[float])、cfg/expected (dict)、任意の原本設定。
    返り値: 検査記録と準備済み入力 (tuple[dict, dict])。
    """
    ready = fixture(prices, event_rows, sides, clock)
    if overrides:
        ready.update(overrides)
    config = dict(entry_mode='market', initial_stop_atr=10., trail_atr=None, target_atr=None,
                  warmup_min=0., cooldown_min=0., entry_deadline_min=0., max_age_min=10.)
    config.update(cfg)
    result = engine.simulate(ready, '試験', config, detail=True)
    for key, value in expected.items():
        np.testing.assert_allclose(result['summary'][key], value, err_msg=name + ':' + key)
    for row in result['raw']:
        assert row[5] > row[4], name + ':設定行への遡及新規'
        if row[14]:
            assert row[6] > row[5], name + ':新規と同じ行への遡及返済'
    if len(result['equity']):
        np.testing.assert_allclose(result['summary']['net_yen'], result['equity'][-1, 2])
    return dict(名称=name, 期待値=expected, 合格=True), dict(ready=ready, config=config, full=result)


def prefix_checks(cases: list[dict]) -> int:
    """機能: 各原本の未来を削除し、それ以前の返済と評価曲線が不変か確かめる。

    引数: cases (list[dict])。返り値: 確認した打切り数 (int)。
    """
    count = 0
    for case in cases:
        ready, config, full = case['ready'], case['config'], case['full']
        for length in range(2, len(ready['seq'])):
            prefix = dict(ready)
            for key in ('time_s', 'seq', 'last', 'atr', 'board_side', 'trend_side'):
                prefix[key] = ready[key][:length].copy()
            prefix['families'] = {}
            for family, event in ready['families'].items():
                mask = event['indices'] < length
                prefix['families'][family] = {key: value[mask].copy() for key, value in event.items()
                                               if isinstance(value, np.ndarray)}
            part = engine.simulate(prefix, '試験', config, detail=True)
            expected = full['raw'][(full['raw'][:, 14] == 1) & (full['raw'][:, 6] < length)]
            actual = part['raw'][part['raw'][:, 14] == 1]
            np.testing.assert_allclose(actual, expected, equal_nan=True)
            for row in part['equity']:
                same = full['equity'][full['equity'][:, 1] == row[1]]
                if len(same):
                    np.testing.assert_allclose(row, same[0])
            count += 1
    return count


def main() -> None:
    """機能: 手計算例を実行して機械可読の監査記録を保存する。

    引数: なし。返り値: なし (None)。
    """
    checks, cases = [], []
    definitions = [
        ('市場相当は次行の現在価格', [100, 130, 140], {},
         dict(net_yen=10000, entry_count=1, open_count=1)),
        ('逆指値の上方ギャップと下方損切り', [100, 140, 90],
         dict(entry_mode='stop', entry_atr=1., initial_stop_atr=1.),
         dict(net_yen=-20000, closed_count=1, ideal_fill_gap_count=2, ideal_fill_benefit_yen=30000)),
        ('指値条件は下方到達後の事前指定価格', [100, 90, 70, 100],
         dict(entry_mode='limit', entry_atr=1., target_atr=1.),
         dict(net_yen=20000, closed_count=1, ideal_entry_gap_count=1)),
        ('追跡入口は更新後の次行で成立', [100, 80, 70, 90, 110],
         dict(entry_mode='trail', entry_atr=.5, target_atr=1.),
         dict(net_yen=20000, closed_count=1)),
        ('追跡出口は前行の極値だけを使う', [100, 100, 150, 100],
         dict(initial_stop_atr=2., trail_atr=1., trail_start_atr=0.),
         dict(net_yen=30000, closed_count=1)),
        ('順行後に幅を短縮', [100, 100, 140, 110],
         dict(trail_atr=2., trail_start_atr=1., tighten_trigger_atr=2., tighten_width_atr=.5),
         dict(net_yen=30000, closed_count=1)),
        ('損益ゼロ位置で保護', [100, 100, 120, 90],
         dict(breakeven_trigger_atr=1.), dict(net_yen=0, closed_count=1)),
        ('順行利益の半分を保護', [100, 100, 140, 110],
         dict(protect_trigger_atr=1., protect_fraction=.5), dict(net_yen=20000, closed_count=1)),
        ('三枚の段階利確と残脚評価', [100, 100, 120, 140, 150],
         dict(add_mode='simultaneous', max_legs=3, leg_targets=[1., 2., None]),
         dict(net_yen=110000, profit_yen=60000, open_yen=50000, closed_count=2, open_count=1, gross_peak=3)),
        ('有限三段の逆行追加', [100, 100, 80, 60, 120],
         dict(add_mode='grid', max_legs=3, add_step_atr=1., target_atr=1.),
         dict(net_yen=60000, closed_count=3, gross_peak=3, max_drawdown_yen=60000)),
        ('有限三段の順行追加', [100, 100, 120, 140, 100],
         dict(add_mode='pyramid', max_legs=3, add_step_atr=1., initial_stop_atr=2.),
         dict(net_yen=-60000, closed_net_yen=-40000, open_yen=-20000, gross_peak=3)),
        ('両建ての利益脚決済後も含み損評価', [100, 100, 120],
         dict(add_mode='hedge', max_legs=2, initial_stop_atr=3., target_atr=1.),
         dict(net_yen=0, closed_net_yen=20000, open_yen=-20000, closed_count=1, open_count=1)),
        ('両建て残脚の反転利確', [100, 100, 120, 80],
         dict(add_mode='hedge', max_legs=2, initial_stop_atr=3., target_atr=1.),
         dict(net_yen=40000, closed_count=2)),
        ('上下逆指値は下方到達で売り', [100, 70, 50],
         dict(entry_mode='straddle', entry_atr=1., target_atr=1.),
         dict(net_yen=20000, closed_count=1)),
        ('時刻による返済は次行の現在価格', [100, 100, 120, 150],
         dict(holding_min=1 / 60, initial_stop_atr=None),
         dict(net_yen=50000, closed_count=1)),
        ('方向反転設定', [100, 100, 70],
         dict(signal_multiplier=-1, target_atr=1.), dict(net_yen=20000, closed_count=1)),
        ('同じ時刻でも原本の次行を使う', [100, 110, 130], {},
         dict(net_yen=20000, open_count=1), None, None, [0, 0, 0]),
        ('無効価格を補完せずスキップ', [100, np.nan, 130, 140], {},
         dict(net_yen=10000, open_count=1)),
        ('入口期限を過ぎれば約定しない', [100, 100, 150],
         dict(entry_mode='stop', entry_atr=1., max_age_min=1 / 60),
         dict(net_yen=0, entry_count=0, expired_entries=1)),
        ('セッション返済条件の次行で返す', [100, 100, 120, 130, 140], {},
         dict(net_yen=30000, closed_count=1, open_count=0), None, None, None, dict(limit=2.)),
        ('反対信号は次行で返す', [100, 100, 120, 130], dict(reverse_exit=True),
         dict(net_yen=30000, closed_count=1), [0, 2], [1, -1]),
        ('米国開始の休止帯は新規を作らない', [100, 100, 120], dict(us_pause=True),
         dict(net_yen=0, entry_count=0), None, None, None, dict(us_open=1.)),
        ('米国開始の返済は次行', [100, 100, 120, 130], dict(us_exit=True, us_before_min=0.),
         dict(net_yen=30000, closed_count=1), None, None, None, dict(us_open=2.)),
        ('板反対による幅短縮は順行条件を必要とする', [100, 100, 120, 100],
         dict(trail_atr=2., trail_start_atr=.5, weak_width_atr=.5, state_trigger_atr=.5),
         dict(net_yen=10000, closed_count=1), None, None, None, dict(board_side=np.array([0, 0, -1, -1]))),
        ('合算損失上限は含み損を含み次行返済', [100, 100, 80, 60],
         dict(add_mode='simultaneous', max_legs=3, basket_stop_atr=2.),
         dict(net_yen=-120000, closed_count=3)),
    ]
    for definition in definitions:
        check, case = run_case(*definition)
        checks.append(check)
        cases.append(case)
    prefix_count = prefix_checks(cases)
    # ----------------------------------------
    # 異なる価格経路でも原本順・損益加算・詳細省略による集計不変を点検する。
    rng = np.random.default_rng(20260924)
    random_count = 0
    for mode in engine.ENTRY_MODES:
        for addition in engine.ADD_MODES:
            prices = (1000 + np.cumsum(rng.choice([-20., -10., 0., 10., 20.], 120))).tolist()
            cap = 1 if addition == 'none' else 2 if addition == 'hedge' else 3
            ready = fixture(prices, list(range(0, 100, 10)), [1, -1] * 5)
            cfg = dict(entry_mode=mode, add_mode=addition, max_legs=cap, warmup_min=0.,
                       cooldown_min=0., entry_deadline_min=0., holding_min=.25,
                       initial_stop_atr=1., target_atr=2., trail_atr=1., trail_start_atr=1.)
            full = engine.simulate(ready, '試験', cfg, detail=True)
            brief = engine.simulate(ready, '試験', cfg, detail=False)
            assert full['summary'] == brief['summary']
            np.testing.assert_allclose(full['raw'], brief['raw'], equal_nan=True)
            np.testing.assert_allclose(full['raw'][:, 15].sum() * 1000, full['summary']['net_yen'])
            assert full['summary']['gross_peak'] <= cap
            cases.append(dict(ready=ready, config=cfg, full=full))
            random_count += 1
    prefix_count += prefix_checks(cases[len(definitions):])
    report = dict(監査対象='費用ゼロ・指定価格約定の逐次再生器',
                  ソースSHA256=hashlib.sha256((OUT / 'exact_engine.py').read_bytes()).hexdigest(),
                  手計算例=checks, ランダム経路条件数=random_count, 未来打切り検査数=prefix_count,
                  注記='人工経路の手計算と未来打切り。実際の約定可能性を証明する検査ではない。', 合格=True)
    (OUT / '指定価格再生の手計算と未来打切り監査.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(手計算=len(checks), ランダム条件=random_count, 未来打切り=prefix_count, 合格=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
