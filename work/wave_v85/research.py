"""原E01の16通りの改修と時間帯9対照を、全30場・二つの約定仮定で再生する。"""

from pathlib import Path
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import pickle
import sys
import time

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXED = HERE / 'results/事前固定.json'
SYMBOLS = ('TOPIX', 'NK225')
MODELS = ('specified', 'observed')
PRIMARY = ('E01', 'E01_G', 'E01_GPDC')
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')


def module(name, path):
    """
    機能: 同じファイルの再読込と旧モジュール名の衝突を防いで読み込む。
    引数: name (str)、path (Path)。
    返り値: module。
    """
    if name in sys.modules:
        value = sys.modules[name]
        assert Path(value.__file__).resolve() == path.resolve()
        return value
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def read(path):
    """
    機能: 通常又はgzip圧縮された保存JSONを読む。
    引数: path (Path)。
    返り値: dict 又は list の内容。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def sha(path):
    """
    機能: 参照ファイルを分割して指紋化する。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def save(path, value):
    """
    機能: 新作業だけへ有限JSONを一時保存後に確定する。
    引数: path (Path)、value (object)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def engines():
    """
    機能: 今回の戦略と条件を固有名で読み、Numba出力先を今回に限定する。
    引数: なし。
    返り値: tuple[module,module] の戦略・カタログ。
    """
    strategy = module('wave85_strategy', HERE / 'strategy.py')
    catalog = module('wave85_catalog', HERE / 'catalog.py')
    import numba
    numba.config.CACHE_DIR = str(HERE / 'cache')
    return strategy, catalog


def freeze():
    """
    機能: 売買再生前に比較対象・主3条件・入力・今回と旧実装の指紋を固定する。
    引数: なし。
    返り値: dict の固定仕様。既存固定内容と違う時は上書きしない。
    """
    strategy, catalog_module = engines()
    catalog = catalog_module.catalog()
    assert len(catalog) == len({c['id'] for c in catalog}) == 25
    assert set(PRIMARY) <= {c['id'] for c in catalog}
    assert {ident + suffix for ident in PRIMARY for suffix in ('_J', '_U', '_JU')} <= {c['id'] for c in catalog}
    proof = read(HERE / 'prepared/入力準備の完了.json')
    own_paths = [HERE / name for name in ('research.py', 'prepare.py', 'strategy.py', 'catalog.py', 'time_filter.py')]
    own_paths += [p for p in HERE.glob('*engine*.py') if p not in own_paths]
    imported = {Path(m.__file__).resolve() for m in tuple(sys.modules.values()) if getattr(m, '__file__', None)
                and Path(m.__file__).suffix == '.py' and Path(m.__file__).resolve().is_relative_to(ROOT / 'work')}
    imported = {p for p in imported if not p.is_relative_to(HERE)}
    dependencies = {str(p.relative_to(ROOT)): sha(p) for p in sorted(imported)}
    for p in (ROOT / 'work/wave_v27/hierarchy_design_fixed.json',):
        dependencies[str(p.relative_to(ROOT))] = sha(p)
    references = {str((ROOT / 'work/wave_v67' / model / (ident + '.json.gz')).relative_to(ROOT)):
                  sha(ROOT / 'work/wave_v67' / model / (ident + '.json.gz'))
                  for model in MODELS for ident in ('E01', 'R01')}
    value = dict(catalog=catalog, primary=list(PRIMARY), 全30=proof['全30'], 前16=proof['前16'], 後14=proof['後14'],
        models=list(MODELS), 選抜='主3条件を事前固定。元16条件と主3の時間帯9対照を両モデル・全30場で比較し、結果で主条件を差し替えない。',
        既知性='全30場は既知。前16と後14は時間順の耐性確認であり未見検証とは呼ばない。',
        会計=dict(主='初回から全返済までの親組における料金後金額利益割合。決済脚は別表示。',
                  金額利益割合='利益/(利益+損失)。無取引は利益扱いしない。',
                  料金={'TOPIX': 41.8, 'NK225': 11.}, 円倍率={'TOPIX': 1000., 'NK225': 10.},
                  初回枚数={'TOPIX': 5, 'NK225': 10}, 片方向上限={'TOPIX': 10, 'NK225': 20},
                  料金単位='新規と返済の注文ごとに合計を1円未満切捨て。元新規料金は部分返済数量へ按分。',
                  時価='全原板観測のCurrentPriceによる全建玉評価＋確定損益−その時点までの実注文料金。仮想将来返済料金を先取りしない。',
                  最大下落='場内は0を初期高値に含める。期間は各場の全原板時価を累積接続して最大下落を計算。',
                  場内='全返済・未決済0・注文から復元した保有枚数上限・最終時価会計一致を必須にする。',
                  利益日除外='最大収支1セッションを除外。昼夜を合算した暦日の除外とは区別する。'),
        約定=dict(specified='前行までの有効指定線を次の保存観測行以降で発動。通過済み市場条件は観測CurrentPrice。',
                  observed='同じ規則で発動し、その観測CurrentPriceで約定。建値・停止線・後続経路も全再計算。',
                  追加固定時間遅延=0., 気配置換='今回の2モデルに含めない。',
                  時計制約='CurrentPriceTimeと原板保存順。真の受信時計や同時計内の経過時間は不明。'),
        catalog_specification=catalog_module.specification() if hasattr(catalog_module, 'specification') else None,
        code_SHA256={str(p.relative_to(HERE)): sha(p) for p in sorted(set(own_paths))},
        legacy_code_SHA256=dependencies, input_SHA256=proof['使用入力SHA256'],
        input_proof_SHA256=sha(HERE / 'prepared/入力準備の完了.json'),
        reference_SHA256=references, API取得=0, 実注文=0)
    if FIXED.exists():
        assert read(FIXED) == value, '固定内容が変化しています'
    else:
        save(FIXED, value)
    return value


def validate(fixed):
    """
    機能: 凍結済みコードと台帳比較元が変更されていないことを再生前に確認する。
    引数: fixed (dict)。
    返り値: None。
    """
    for name, expected in fixed['code_SHA256'].items():
        assert sha(HERE / name) == expected, name
    for field in ('legacy_code_SHA256', 'reference_SHA256'):
        for name, expected in fixed[field].items():
            assert sha(ROOT / name) == expected, name
    assert sha(HERE / 'prepared/入力準備の完了.json') == fixed['input_proof_SHA256']


# ----------------------------------------
def add_ratios(value):
    """
    機能: 決済脚と親組の金額比率を同じ集計へ追加する。
    引数: value (dict) は基本会計。内容を更新する。
    返り値: dict の更新済み会計。
    """
    for prefix in ('', 'campaign_'):
        gain, loss = value[prefix + 'profit'], value[prefix + 'loss']
        value[prefix + 'profit_share'] = gain / (gain + loss) if gain + loss else None
        value[prefix + 'pf'] = gain / loss if loss else None
    value.update(cycle_profit=value['campaign_profit'], cycle_loss=value['campaign_loss'],
                 cycle_net=value['net'], cycles=value['campaigns'], cycle_wins=value['campaign_wins'],
                 cycle_losses=value['campaign_losses'], cycle_profit_share=value['campaign_profit_share'],
                 cycle_pf=value['campaign_pf'], cycle_payoff=value['campaign_payoff'],
                 cycle_avg_net=value['net'] / value['campaigns'] if value['campaigns'] else None,
                 cycle_win_rate=value['campaign_wins'] / value['campaigns'] if value['campaigns'] else None,
                 trades=value['wins'] + value['losses'] + value['flats'],
                 settled_lots=value['winning_lots'] + value['losing_lots'] + value['flat_lots'])
    return value


def account(previous, ready, result, settings):
    """
    機能: 元会計を再利用し、全原板時価・全注文在庫・部分返済と親組を補強する。
    引数: previous (module)、ready/result/settings (dict)。
    返り値: tuple[dict,dict,ndarray] の集計・台帳・料金後時価。
    """
    row, old_ledger, equity = previous.account(ready, result, settings)
    orders, trades, cycles = result['orders'], result['trades'], result['cycles']
    count = len(ready['last'])
    inventory, holdings = np.zeros(2, int), np.zeros(2, int)
    maximum_gross = maximum_net = 0
    cash_delta, qty_delta = np.zeros(count), np.zeros(count)
    values = previous.VALUES[ready['symbol']]
    for o in orders:
        fill, source, side, qty = int(o[0]), int(o[1]), int(o[3]), int(o[4])
        assert 0 <= source < fill < count and side in (-1, 1) and qty > 0
        assert qty == o[4]
        held_side = side if o[7] else -side
        index = 0 if held_side == 1 else 1
        inventory[index] += qty if o[7] else -qty
        assert (inventory >= 0).all()
        holdings = np.maximum(holdings, inventory)
        maximum_gross = max(maximum_gross, int(inventory.sum()))
        maximum_net = max(maximum_net, int(abs(inventory[0] - inventory[1])))
        cash_delta[fill] -= side * qty * o[5]
        qty_delta[fill] += side * qty
    assert not inventory.any()
    assert int(holdings[0]) == row['max_long'] and int(holdings[1]) == row['max_short']
    assert holdings.max(initial=0) <= settings['audit_cap']
    assert np.all(np.isfinite(equity)) and len(equity) == count
    fees = np.asarray(old_ledger['fees'], float)
    fee_delta = np.zeros(count)
    np.add.at(fee_delta, orders[:, 0].astype(int), fees)
    reconstructed = (np.cumsum(cash_delta) + np.cumsum(qty_delta) * ready['last']) * values - np.cumsum(fee_delta)
    np.testing.assert_allclose(reconstructed, equity, atol=1e-5, rtol=0)
    assert abs(float(equity[-1]) - row['net']) < 1e-5
    row.update(entry_orders=int(np.sum(orders[:, 7] == 1)), exit_orders=int(np.sum(orders[:, 7] == 0)),
        new_lots=int(orders[orders[:, 7] == 1, 4].sum()), exit_lots=int(orders[orders[:, 7] == 0, 4].sum()),
        max_gross=maximum_gross, max_net=maximum_net, equity_min=float(min(0., equity.min(initial=0))),
        equity_max=float(max(0., equity.max(initial=0))), residual_long=int(inventory[0]), residual_short=int(inventory[1]))
    assert row['new_lots'] == row['exit_lots']
    row['reason_counts'] = {str(int(reason)): int(np.sum(trades[:, 9] == reason)) for reason in np.unique(trades[:, 9])}
    row['guard_event_count'] = len(result.get('guard_events', []))
    time_events = result.get('time_events', np.empty((0, 7)))
    row.update(time_forced_exits=int(np.sum(time_events[:, 2] == 1)),
               time_rejected_preparations=int(np.sum(time_events[:, 2] == 2)),
               time_exit_lots=int(orders[(orders[:, 7] == 0) & (orders[:, 6] == 71), 4].sum()),
               time_window_count=len(result.get('time_windows', [])),
               time_first_observation_after_window=sum(w['窓終了後の初観測'] for w in result.get('time_windows', [])))
    add_ratios(row)
    ledger = dict(session=ready['session'], symbol=ready['symbol'], settings=settings, orders=orders.copy(),
        trades=trades.copy(), cycles=cycles.copy(), fees=fees, net_trades=old_ledger['trades'],
        stats=result['stats'].copy(), curve_SHA256=hashlib.sha256(np.asarray(equity).tobytes()).hexdigest(),
        raw_curve_SHA256=hashlib.sha256(np.asarray(result['curve']).tobytes()).hexdigest())
    for name, value in result.items():
        if isinstance(value, np.ndarray) and ('event' in name or name == 'entry_preparations'):
            ledger[name] = value.copy()
    if 'guard_columns' in result:
        ledger['guard_columns'] = result['guard_columns']
    ledger['time_windows'] = result.get('time_windows', [])
    return row, ledger, equity


def aggregate(previous, rows, symbol, names):
    """
    機能: 元集計へ時系列連結DD・取引休止・最良1場除外を追加する。
    引数: previous (module)、rows (list[dict])、symbol (str)、names (list[str])。
    返り値: dict の同商品だけの期間会計。
    """
    subset = sorted([r for r in rows if r['symbol'] == symbol and r['session'] in names], key=lambda r: r['session'])
    value = previous.aggregate(rows, symbol, names)
    cumulative = peak = drawdown = 0.
    for row in subset:
        drawdown = max(drawdown, row['max_drawdown'], peak - (cumulative + row['equity_min']))
        peak = max(peak, cumulative + row['equity_max'])
        cumulative += row['net']
    active = [r for r in subset if r['campaigns']]
    value.update(max_drawdown=float(drawdown), no_trade_sessions=sum(r['campaigns'] == 0 for r in subset),
                 flat_active_sessions=sum(r['campaigns'] > 0 and r['net'] == 0 for r in subset),
                 best_session=max((r['net'] for r in subset), default=0.),
                 worst_session=min((r['net'] for r in subset), default=0.))
    best = max(subset, key=lambda r: r['net']) if subset else None
    value['best_session_id'] = best['session'] if best else None
    value['best_session_removed'] = value['net'] - best['net'] if best else None
    for field in ('entry_orders', 'exit_orders', 'new_lots', 'exit_lots', 'guard_event_count',
                  'time_forced_exits', 'time_rejected_preparations', 'time_exit_lots',
                  'time_window_count', 'time_first_observation_after_window'):
        value[field] = sum(r[field] for r in subset)
    for field in ('max_long', 'max_short', 'max_gross', 'max_net'):
        value[field] = max((r[field] for r in subset), default=0)
    value['positive_active_share'] = value['positive_sessions'] / len(active) if active else None
    return add_ratios(value)


def compare_original(key, result, ledger, original, value):
    """
    機能: 基準E01と入口再確認Gについて旧28場の売買完全一致を要求する。
    引数: key (tuple)、result/ledger/original (dict)、value (float) は円倍率。
    返り値: None。旧台帳で省略された元脚番号と役割は増玉なしの注文列から復元する。
    """
    np.testing.assert_array_equal(result['orders'], np.asarray(original['orders']).reshape(result['orders'].shape), err_msg=str(key))
    np.testing.assert_array_equal(result['cycles'], np.asarray(original['cycles']).reshape(result['cycles'].shape), err_msg=str(key))
    assert ledger['net_trades'] == original['trades'], key
    entries = {(int(o[2]), int(o[0])): number for number, o in enumerate([o for o in original['orders'] if o[7] == 1])}
    restored = [[t['組'], entries[t['組'], t['新規行']], t['方向'], t['枚数'], t['建値'], t['返済値'],
                 t['新規行'], t['返済行'], 0., t['理由'], t['利益損失前'] / value] for t in original['trades']]
    np.testing.assert_array_equal(result['trades'], np.asarray(restored).reshape(result['trades'].shape), err_msg=str(key))


# ----------------------------------------
def run_condition(config, model, inputs, features, strategy, fixed):
    """
    機能: 1条件を全60口座へ逐次再生し、集計JSONと疎な台帳を別保存する。
    引数: config/inputs/features/fixed (dict)、model (str)、strategy (module)。
    返り値: dict の結果。条件変更や成績による再選定はしない。
    """
    target = HERE / model / 'results' / (config['id'] + '.json')
    ledger_path = HERE / model / 'ledgers' / (config['id'] + '.pkl')
    run = dict(model=model, delay=0., sessions=fixed['全30'], code_SHA256=fixed['code_SHA256'], input_SHA256=fixed['input_SHA256'])
    if target.exists():
        saved = read(target)
        assert saved['config'] == config and saved['run'] == run and ledger_path.exists()
        assert sha(ledger_path) == saved['ledger_SHA256']
        return saved
    old = {}
    if config['id'] in ('E01', 'E01_G'):
        old_id = 'E01' if config['id'] == 'E01' else 'R01'
        old = {(v['session'], v['symbol']): v for v in read(ROOT / 'work/wave_v67' / model / (old_id + '.json.gz'))['ledgers']}
        assert len(old) == 56
    rows, ledgers, checks = [], {}, []
    started = time.monotonic()
    for key, ready in sorted(inputs.items()):
        result, settings = strategy.play(config, ready, features[key], observed=model == 'observed')
        row, ledger, equity = account(strategy.previous, ready, result, settings)
        if key in old:
            compare_original(key, result, ledger, old[key], strategy.previous.VALUES[key[1]])
            checks.append(dict(session=key[0], symbol=key[1], 注文決済組完全一致=True))
        rows.append(row)
        ledgers[key] = ledger
        del result, equity
    periods = {name: {symbol: aggregate(strategy.previous, rows, symbol, fixed[name]) for symbol in SYMBOLS}
               for name in ('前16', '後14', '全30')}
    periods['対象'] = periods['全30']
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_suffix('.pkl.tmp')
    with temporary.open('wb') as stream:
        pickle.dump(ledgers, stream, protocol=5)
    temporary.replace(ledger_path)
    out = dict(config=config, model=model, run=run, rows=rows, periods=periods, 旧28場完全一致=checks,
               ledger_SHA256=sha(ledger_path), elapsed_seconds=time.monotonic() - started)
    save(target, out)
    return out


def run(models, identifiers):
    """
    機能: 根担当の開始指示後、凍結した条件だけを逐次計算する。
    引数: models (list[str])、identifiers (list[str]) は空なら全固定条件。
    返り値: None。入力検証は親で一度だけ行う。
    """
    assert FIXED.exists(), '事前固定が必要です'
    fixed = read(FIXED)
    validate(fixed)
    strategy, catalog_module = engines()
    assert catalog_module.catalog() == fixed['catalog']
    data = module('wave85_prepare', HERE / 'prepare.py')
    inputs, signals, hashes = data.load_inputs(verify=True)
    assert hashes == fixed['input_SHA256']
    features = strategy.initialize(inputs, signals)
    assert set(features) == set(inputs)
    configs = [c for c in fixed['catalog'] if not identifiers or c['id'] in identifiers]
    assert len(configs) == len(identifiers) if identifiers else len(configs) == 25
    for model in models:
        assert model in MODELS
        for number, config in enumerate(configs, start=1):
            run_condition(config, model, inputs, features, strategy, fixed)
            print(f'{model} {number}/{len(configs)} {config["id"]} 全30場完了', flush=True)
    validate(fixed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='原E01と改修・時間帯25条件の全30場比較')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--models', default='specified,observed')
    parser.add_argument('--ids', default='')
    args = parser.parse_args()
    if args.freeze:
        freeze()
        print('主3・部品16条件・時間帯9対照・二つの約定仮定を固定しました', flush=True)
    if args.run:
        run(args.models.split(','), [v for v in args.ids.split(',') if v])
