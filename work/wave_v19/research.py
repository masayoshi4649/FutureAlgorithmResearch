"""M3逆A00の変数を既知の一週間で比較し、両銘柄の安定性から選ぶ。"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.append(str(OUT.parent / 'wave_v17'))
import engine
import signal_variants

metric_spec = importlib.util.spec_from_file_location('previous_metrics', OUT.parent / 'wave_v17/research.py')
metrics = importlib.util.module_from_spec(metric_spec)
metric_spec.loader.exec_module(metrics)
metrics.MULT = {'TOPIX': 1000., 'NK225': 10.}
SYMBOLS = ['TOPIX', 'NK225']
SESSIONS = [f'2026-09-{day:02d}_{part}' for day in range(21, 26) for part in ['Day', 'Night']]
BASE = dict(initial_qty=1, entry_atr=.25, stop_atr=1., main_trail=2., add_mode=0,
            add_step=.5, add_qty=0, hedge_ratio=0., hedge_trigger=.75, cover_add=0,
            cover_step=.5, cover_trail=.5, reverse_mode=0, lock_fraction=0.,
            split_target=0., timeout_min=180., neutral_min=0., us_mode=0,
            activation_atr=1., tighten_atr=0., tight_width=1., breakeven_atr=0.,
            breakeven_floor=0., failure_min=0., failure_mfe=.5, failure_stop=.25,
            cooldown_min=5., ttl_seconds=120., entry_mode=0, signal_exit=0,
            after_open_factor=1., audit_cap=1)


def save(name: str, value: object) -> None:
    """機能: 数値型と欠損を整え、今回の作業領域へJSONを保存する。

    引数: name (str)、value (object)。返り値: なし (None)。
    """
    (OUT / name).write_text(json.dumps(metrics.clean(value), ensure_ascii=False, indent=2), encoding='utf-8')


def make_catalog() -> list[dict]:
    """機能: 損益を参照せず、単独変更と入口・出口との組合せを列挙する。

    引数: なし。返り値: 重複を除いた全設定 (list[dict])。
    """
    rows, seen = [], set()
    specs = signal_variants.variant_specs()

    def append(signal: str, family: str, description: str, changes: dict) -> None:
        """機能: 同じ信号・同じ執行設定の重複を除いて候補を追加する。

        引数: signal/family/description (str)、changes (dict)。返り値: なし (None)。
        """
        config = dict(BASE, **changes)
        signature = (signal, tuple(config[k] for k in engine.PARAMS))
        if signature in seen:
            return
        seen.add(signature)
        rows.append(dict(id=f'V{len(rows):04d}', signal_id=signal, family=family,
                         description=description, config=config,
                         changes={k: v for k, v in config.items() if v != BASE[k]}))

    append('S00', '基準', '元のM3_逆_A00。固定１枚、入口0.25ATR、損切り１ATR、追跡２ATR。', {})
    # ----------------------------------------
    # 基礎格子は変数の近傍比較にも使う。新規幅０は過去価格約定を避けるため含めない。
    for entry, stop, trail in itertools.product([.125, .25, .5, .75], [.5, .75, 1., 1.25, 1.5], [1., 1.5, 2., 2.5, 3.]):
        append('S00', '入口・損切り・追跡幅', '反転の確認幅と損切り・追跡幅の組合せ。',
               dict(entry_atr=entry, stop_atr=stop, main_trail=trail))
    for spec in specs:
        for entry, stop, trail in itertools.product([.25, .5], [.75, 1., 1.25], [1.5, 2., 2.5]):
            append(spec['id'], '方向判定', spec['description'],
                   dict(entry_atr=entry, stop_atr=stop, main_trail=trail))
    variants = []
    variants += [('追跡開始', f'{v}ATR進んでから追跡を開始。', dict(activation_atr=v)) for v in [.5, 1.5, 2.]]
    variants += [('利益後の幅短縮', f'{trigger}ATR進んだら追跡幅を{width}ATRへ短縮。', dict(tighten_atr=trigger, tight_width=width))
                 for trigger, width in [(2., .75), (2., 1.), (2., 1.5), (3., 1.), (3., 1.5)]]
    variants += [('建値保護', f'{trigger}ATR進んだら最低損益を{floor}ATRへ引き上げ。', dict(breakeven_atr=trigger, breakeven_floor=floor))
                 for trigger, floor in [(1., 0.), (1.5, 0.), (2., 0.), (2., .25)]]
    variants += [('初動不発の縮小', f'{minutes}分経過して最大順行が{mfe}ATR未満なら、損切りを{stop}ATRへ短縮。',
                  dict(failure_min=minutes, failure_mfe=mfe, failure_stop=stop))
                 for minutes, mfe, stop in [(20., .5, .25), (30., .5, .5), (45., .75, .5)]]
    variants += [('再入場の間隔', f'返済後{v}分待って再入場。', dict(cooldown_min=v)) for v in [0., 2., 10., 20.]]
    variants += [('新規注文の寿命', f'新規逆指値を{v}秒で取り消して再判定。', dict(ttl_seconds=v)) for v in [60., 300., 600.]]
    variants += [('追跡して新規', f'新規を追跡安値・高値からの反転で行い、{v}秒で再判定。', dict(entry_mode=1, ttl_seconds=v)) for v in [120., 300.]]
    variants += [('保有時間', f'保有上限を{v}分に変更。場末は必ず返済。', dict(timeout_min=v)) for v in [60., 90., 120., 240., 360.]]
    variants += [('時間帯', '夜間22:15〜23:00は新規を休止。', dict(us_mode=2)),
                 ('時間帯', '夜間22:15〜23:00は新規を休止し保有玉も返済。', dict(us_mode=1)),
                 ('時間帯', '夜間22:30以降は追跡幅を25％縮小。既存水準を緩めない。', dict(after_open_factor=.75)),
                 ('時間帯', '夜間22:30以降は新しく算出する追跡幅を25％拡大。既存水準を緩めない。', dict(after_open_factor=1.25))]
    variants += [('判断撤回', '保持中に取引方向の状態が反対へ切り替わったら次行で全返済。', dict(signal_exit=1))]
    variants += [('利益割合の保護', f'初期損失予算以上の含み益から、最高益の{v:.0%}を保護。', dict(lock_fraction=v)) for v in [.25, .5, .75]]
    for family, description, changes in variants:
        for entry, stop, trail in itertools.product([.25, .5], [.75, 1.], [1.5, 2., 2.5]):
            append('S00', family, description, dict(entry_atr=entry, stop_atr=stop, main_trail=trail, **changes))
    return rows


def aggregate(rows: list[dict], trades: list[np.ndarray]) -> dict:
    """機能: 週成績へ最大勝ち除外・時間別の安定性を追加する。

    引数: rows (list[dict])、trades (list[ndarray])。返り値: 拡張週集計 (dict)。
    """
    out = metrics.aggregate(rows)
    best = max(rows, key=lambda r: r['net_yen'])
    removed = [r for r in rows if r['session'] != best['session']]
    drop = metrics.aggregate(removed)
    values = np.concatenate([t[:, 10] for t in trades]) * metrics.MULT[out['symbol']]
    positive = sorted(values[values > 0], reverse=True)
    maximum = float(positive[0]) if positive else 0.
    longest, streak = 0, 0
    for value in values:
        streak = streak + 1 if value < 0 else 0
        longest = max(longest, streak)
    out.update(best_session=best['session'], drop_best_session_net=drop['net_yen'],
               drop_best_session_pf=drop['money_ratio'], best_trade_yen=maximum,
               drop_best_trade_net=out['net_yen']-maximum,
               drop_top3_trades_net=out['net_yen']-sum(positive[:3]),
               worst_trade_yen=float(values.min()) if len(values) else 0., longest_loss_streak=longest,
               first_half_net=sum(r['net_yen'] for r in rows[:5]),
               second_half_net=sum(r['net_yen'] for r in rows[5:]),
               day_net=sum(r['net_yen'] for r in rows if r['session'].endswith('Day')),
               night_net=sum(r['net_yen'] for r in rows if r['session'].endswith('Night')),
               recovery=out['net_yen']/out['drawdown_yen'] if out['drawdown_yen'] else None)
    return out


def qualify(week: dict) -> bool:
    """機能: あらかじめ固定した銘柄別の安定性条件を判定する。

    引数: week (dict)。返り値: 全条件を満たすか (bool)。
    """
    return bool(week['net_yen'] > 0 and (week['money_ratio'] or 0) > 1 and
                (week['unit_payoff'] or 0) > 1 and week['positive_sessions'] >= 6 and
                week['active_sessions'] >= 8 and week['cycles'] >= 30 and
                week['drop_best_session_net'] > 0 and week['drop_best_trade_net'] > 0 and
                week['first_half_net'] > 0 and week['second_half_net'] > 0 and
                week['day_net'] > 0 and week['night_net'] > 0)


def select(records: list[dict]) -> dict:
    """機能: 両銘柄の資格と近傍を用い、円額を混ぜずに共通候補を選ぶ。

    引数: records (list[dict])。返り値: 主候補・対照候補と選択根拠 (dict)。
    """
    keys = ['entry_atr', 'stop_atr', 'main_trail']
    lookup = {}
    for record in records:
        config = record['config']
        for varied in keys:
            group = (varied, record['signal_id'], tuple((k, config[k]) for k in engine.PARAMS if k != varied))
            lookup.setdefault(group, []).append(record)
    for record in records:
        neighbors = {}
        for varied in keys:
            config = record['config']
            group = (varied, record['signal_id'], tuple((k, config[k]) for k in engine.PARAMS if k != varied))
            ordered = sorted(lookup[group], key=lambda r: r['config'][varied])
            position = next(i for i, value in enumerate(ordered) if value['id'] == record['id'])
            for i in [position-1, position+1]:
                if 0 <= i < len(ordered):
                    neighbors[ordered[i]['id']] = ordered[i]
        positive = sum(all(r['weeks'][s]['net_yen'] > 0 and r['weeks'][s]['drop_best_session_net'] > 0 for s in SYMBOLS)
                       for r in neighbors.values())
        values = [min(r['weeks'][s]['drop_best_session_pf'] or 0 for s in SYMBOLS) for r in neighbors.values()]
        record['neighbor'] = dict(ids=list(neighbors), count=len(neighbors), positive_count=positive,
                                  positive_rate=positive/len(neighbors) if neighbors else 0.,
                                  median_drop_pf=float(np.median(values)) if values else 0.,
                                  worst_drop_pf=min(values) if values else 0.)
        record['common_eligible'] = all(qualify(record['weeks'][s]) for s in SYMBOLS)
        record['stable_eligible'] = (record['common_eligible'] and len(neighbors) >= 3 and
                                     record['neighbor']['positive_rate'] >= .75)
        record['score'] = min(record['weeks'][s]['drop_best_session_pf'] or 0 for s in SYMBOLS)
        record['change_count'] = len(record['changes']) + (record['signal_id'] != 'S00')
    ranked = sorted(records, key=lambda r: (-int(r['stable_eligible']), -r['neighbor']['median_drop_pf'],
                                           -r['score'], r['change_count'], r['id']))
    eligible = [r for r in ranked if r['stable_eligible']]
    selected = eligible[0]['id'] if eligible else 'V0000'
    # 単発の最高成績と、近傍込みの主候補は別々に記録する。
    peak = max(records, key=lambda r: r['score'])['id']
    by_symbol = {}
    for symbol in SYMBOLS:
        candidates = [r for r in records if qualify(r['weeks'][symbol])]
        by_symbol[symbol] = max(candidates, key=lambda r: r['weeks'][symbol]['drop_best_session_pf'])['id'] if candidates else 'V0000'
    return dict(primary=selected, baseline='V0000', single_point_best=peak, by_symbol=by_symbol,
                common_eligible_count=sum(r['common_eligible'] for r in records),
                stable_eligible_count=len(eligible), ranking=[r['id'] for r in ranked],
                displayed=list(dict.fromkeys(['V0000', selected, peak, *by_symbol.values(), *[r['id'] for r in eligible[:3]]])))


def main() -> None:
    """機能: 条件を先に固定し、基準一致確認後に全候補を原本順に再生する。

    引数: なし。返り値: なし (None)。現在APIは取得せず、元データを変更しない。
    """
    started = time.time()
    configs = make_catalog()
    paths = [OUT / name for name in ['research.py', 'engine.py', 'signal_variants.py']]
    paths += [OUT.parent / 'wave_v16' / f'入力_{stage}.pkl' for stage in ['development', 'holdout']]
    paths += [OUT.parent / 'wave_v17/主方向状態.pkl']
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    save('探索前の固定記録.json', dict(条件数=len(configs), 全データ既読=True, 現在API取得回数=0,
         入力期間='2026-09-21日中〜2026-09-25夜間', 初回枚数=1, 増玉=False, 同時保有=1,
         選択条件='両銘柄ともPF>1、１枚平均利益/損失>1、黒字6/10以上、稼働8/10以上、取引30以上。最大勝ちセッションおよび最大勝ち取引を各々除いて黒字。前半・後半・日中計・夜間計も黒字。',
         近傍='同じ信号・他設定を固定し、入口幅・損切り幅・追跡幅の直近上下を調べる。３近傍以上かつ75％以上で両銘柄の週収支・最大勝ちセッション除外収支が黒字。',
         順位='資格合格後、近傍の両銘柄弱い側の最大勝ちセッション除外PFの中央値、本人の同PF、変更項目の少なさ、ID。円額は銘柄間で合算しない。',
         最大勝ち定義='セッションは円の純収支最大。取引は固定１枚の新規〜全返済１組。別々に除外。除外後の注文再計算は行わない寄与度の診断。',
         約定='費用０・指定価格。次行から注文有効。保有上限はTOPIX10枚/NK20枚、探索は固定１枚で表示枚数を変更可能。',
         注意='同じ既知週での探索。新規の未使用データ評価とは区別。新規注文幅０は含めない。', ハッシュ=hashes))
    save('全条件一覧.json', configs)
    save('信号条件一覧.json', signal_variants.variant_specs())
    inputs = {}
    for stage in ['development', 'holdout']:
        inputs.update(pickle.loads((OUT.parent / 'wave_v16' / f'入力_{stage}.pkl').read_bytes()))
    states = pickle.loads((OUT.parent / 'wave_v17/主方向状態.pkl').read_bytes())
    original = pickle.loads((OUT.parent / 'wave_v18/allocation/固定型全配分の生台帳.pkl').read_bytes())
    old_spec = importlib.util.spec_from_file_location('old_scaled_engine', OUT.parent / 'wave_v18/audit_engine_scaled.py')
    old_engine = importlib.util.module_from_spec(old_spec)
    old_spec.loader.exec_module(old_engine)
    baseline_checks = []
    for session in SESSIONS:
        for symbol in SYMBOLS:
            key = (session, symbol)
            direction = np.ascontiguousarray(-states[key]['M3'], dtype=np.int8)
            new = engine.run(inputs[key], direction, BASE)
            old_key = (f'M3_逆_A00__{symbol}__I01_A00', session, symbol)
            reference = original[old_key]
            for field in ['trades', 'cycles', 'orders', 'stats']:
                np.testing.assert_allclose(new[field], reference[field], rtol=0, atol=1e-8)
            baseline_checks.append(dict(session=session, symbol=symbol, trades=len(new['trades']), 完全一致=True))
    save('基準再現監査.json', dict(合格=True, 区間数=len(baseline_checks), 検査=baseline_checks))
    print(f'基準20区間一致、{len(configs)}条件の比較を開始', flush=True)
    records, session_rows, blocks = [], [], {}
    by_signal = {}
    for config in configs:
        by_signal.setdefault(config['signal_id'], []).append(config)
    spec_by_id = {s['id']: s for s in signal_variants.variant_specs()}
    completed = 0
    for signal_id, group in by_signal.items():
        directions = signal_variants.build_one(spec_by_id[signal_id], inputs, states)
        for candidate in group:
            weeks, candidate_rows = {}, []
            for symbol in SYMBOLS:
                rows, trades = [], []
                for session in SESSIONS:
                    key = (session, symbol)
                    result = engine.run(inputs[key], directions[key], candidate['config'])
                    row = metrics.summarize(result, candidate, symbol, session)
                    rows.append(row)
                    trades.append(result['trades'])
                    blocks[(candidate['id'], session, symbol)] = dict(trades=result['trades'], cycles=result['cycles'],
                                                                     orders=result['orders'], stats=result['stats'])
                weeks[symbol] = aggregate(rows, trades)
                candidate_rows.extend(rows)
            records.append(dict(candidate, weeks=weeks))
            session_rows.extend(candidate_rows)
            completed += 1
            if completed % 25 == 0:
                print(f'{completed}/{len(configs)}条件、{time.time()-started:.1f}秒', flush=True)
    selection = select(records)
    save('週比較.json', records)
    save('セッション比較.json', session_rows)
    save('選択結果.json', selection)
    with (OUT / '全取引台帳.pkl').open('wb') as stream:
        pickle.dump(blocks, stream, pickle.HIGHEST_PROTOCOL)
    assert all(hashlib.sha256(Path(name).read_bytes()).hexdigest() == value for name, value in hashes.items())
    save('探索完了記録.json', dict(合格=True, 条件数=len(configs), セル数=len(session_rows),
         現在API取得回数=0, 原本不変=True, 全区間返済=True, 経過秒=time.time()-started, 選択=selection))
    print(json.dumps(dict(完了=True, 条件数=len(configs), 主候補=selection['primary'], 安定合格数=selection['stable_eligible_count'],
                         経過秒=time.time()-started), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
