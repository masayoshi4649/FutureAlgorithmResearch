"""元E01を完全固定し、極値からの反転保険の十三条件を全保存場で比較する。"""

import argparse
import importlib.util
import json
import pickle
from pathlib import Path
import sys
import time

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v85'
FIXED = HERE / '事前固定.json'


def module(name, path):
    """
    機能: 作業固有名で既存又は新規モジュールを読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


old = module('wave85_research', OLD / 'research.py')
catalog = module('wave87_round8_catalog', HERE / 'catalog.py')
prepare = module('wave85_prepare', OLD / 'prepare.py')


def save(path, value):
    """
    機能: 新作業内へ有限値の日本語JSONを保存する。
    引数: path(Path)、value(dict又はlist)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def strategy_module():
    """
    機能: 新しい再参加・出口実装を読み込む。
    引数: なし。
    返り値: module。
    """
    return module('wave87_round8_strategy', HERE / 'strategy.py')


def freeze():
    """
    機能: 戦略と条件・参照入力を全場計算の前に固定する。
    引数: なし。
    返り値: dict。
    """
    strategy = strategy_module()
    strategy.prepare.load(verify=True)
    prior = old.read(OLD / 'results/事前固定.json')
    old.validate(prior)
    paths = {Path(m.__file__).resolve() for m in tuple(sys.modules.values())
             if getattr(m, '__file__', None) and Path(m.__file__).suffix == '.py'
             and Path(m.__file__).resolve().is_relative_to(ROOT / 'work')}
    paths.update(HERE.glob('*.py'))
    paths.update([HERE.parent / 'round6/事前固定.json', HERE.parent / 'round6/fee_account.py',
                  HERE.parent / 'round7/事前固定.json', HERE.parent / 'round7/strategy.py',
                  HERE.parent / 'round3/事前固定.json', HERE.parent / 'round3/prepared/short.pkl',
                  HERE.parent / 'round3/prepared/支持準備の照合.json',
                  HERE.parent / 'round3/prepared/終端元時計の照合.json',
                  HERE / 'prepared/支持参照固定.json'])
    paths.update(ROOT / 'work/wave_v86' / name for name in
                 ('事前固定.json', 'catalog.py', 'phase2/事前固定.json', 'phase2/catalog.py'))
    fixed = dict(catalog=catalog.catalog(), specification=catalog.specification(),
        models=['observed', 'specified'],
        **{k: prior[k] for k in ('全30', '前16', '後14', 'input_SHA256', 'input_proof_SHA256')},
        code_SHA256={str(p.relative_to(ROOT)): old.sha(p) for p in sorted(paths)},
        基準結果SHA256={str(p.relative_to(ROOT)): old.sha(p) for p in
            [OLD / m / 'results/E01_G_U.json' for m in ('observed', 'specified')]})
    assert len(fixed['catalog']) == 13
    if FIXED.exists():
        assert old.read(FIXED) == fixed, '固定内容が変化しています'
    else:
        save(FIXED, fixed)
    return fixed


def validate(fixed):
    """
    機能: 固定した実装・基準損益の変更を検知する。
    引数: fixed(dict)。
    返り値: None。
    """
    for field in ('code_SHA256', '基準結果SHA256'):
        for name, digest in fixed[field].items():
            assert old.sha(ROOT / name) == digest, name
    assert old.sha(OLD / 'prepared/入力準備の完了.json') == fixed['input_proof_SHA256']


def run_one(config, model, inputs, features, strategy, fixed):
    """
    機能: 六十口座を再生し、旧会計との照合後に疎な台帳と集計を保存する。
    引数: config/inputs/features/fixed(dict)、model(str)、strategy(module)。
    返り値: dict の結果。
    """
    path = HERE / model / 'results' / (config['id']+'.json')
    ledger_path = HERE / model / 'ledgers' / (config['id']+'.pkl')
    run = dict(model=model, delay=0., sessions=fixed['全30'], code_SHA256=fixed['code_SHA256'],
               input_SHA256=fixed['input_SHA256'])
    if path.exists():
        saved = old.read(path)
        assert saved['run'] == run and saved['config'] == config
        assert old.sha(ledger_path) == saved['ledger_SHA256']
        return saved
    with (OLD / model / 'ledgers/E01_G_U.pkl').open('rb') as stream:
        reference = pickle.load(stream)
    rows, ledgers, core_rows = [], {}, []
    started = time.monotonic()
    for key, ready in sorted(inputs.items()):
        result, settings = strategy.play(config, ready, features[key], observed=model == 'observed')
        row, ledger, equity = old.account(strategy.previous, ready, result, settings)
        core_row, core_ledger, core_equity = old.account(strategy.previous, ready, result['core_result'], settings)
        for name in ('orders', 'trades', 'cycles', 'fees', 'time_events'):
            np.testing.assert_array_equal(core_ledger[name], reference[key][name], err_msg=str((key, name)))
        assert core_ledger['net_trades'] == reference[key]['net_trades']
        assert core_ledger['curve_SHA256'] == reference[key]['curve_SHA256']
        assert core_ledger['raw_curve_SHA256'] == reference[key]['raw_curve_SHA256']
        sat_orders = result['satellite_orders']
        sat_trades = result['satellite_trades']
        sat_fee = float(np.floor(sat_orders[:,4]*strategy.previous.FEES[ready['symbol']]+1e-8).sum())
        sat_gross = float(sat_trades[:,10].sum()*strategy.previous.VALUES[ready['symbol']])
        assert abs(row['net']-core_row['net']-(sat_gross-sat_fee)) < 1e-7
        row.update(core_net=core_row['net'], satellite_gross=sat_gross, satellite_fees=sat_fee,
                   satellite_net=sat_gross-sat_fee, core_unchanged=True,
                   satellite_entries=int((sat_orders[:,7]==1).sum()))
        ledger.update(core_ledger=core_ledger, satellite_orders=sat_orders.copy(),
                      satellite_trades=sat_trades.copy(), satellite_stats=result['satellite_stats'].copy())
        assert not np.any(result['satellite_stats'][:2])
        if not config['relation']:
            for name in ('orders','trades','cycles','fees'):
                np.testing.assert_array_equal(ledger[name],core_ledger[name])
            assert ledger['curve_SHA256']==core_ledger['curve_SHA256']
        core_rows.append(core_row)
        del core_equity
        rows.append(row)
        ledgers[key] = ledger
        del result, equity
    periods = {period: {s: old.aggregate(strategy.previous, rows, s, fixed[period])
                       for s in ('TOPIX', 'NK225')} for period in ('前16', '後14', '全30')}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        pickle.dump(ledgers, stream, protocol=5)
    temporary.replace(ledger_path)
    output = dict(config=config, model=model, run=run, rows=rows, periods=periods,
                  基準台帳完全一致=not bool(config['relation']), 全条件コア完全一致=True,
                  コア行=core_rows, ledger_SHA256=old.sha(ledger_path),
                  elapsed_seconds=time.monotonic()-started)
    save(path, output)
    return output


def run(models, identifiers):
    """
    機能: 固定済み条件だけを全セッションで実行する。
    引数: models(list[str])、identifiers(list[str])。
    返り値: None。
    """
    fixed = old.read(FIXED)
    validate(fixed)
    strategy = strategy_module()
    inputs, signals, hashes = prepare.load_inputs(verify=True)
    assert hashes == fixed['input_SHA256']
    features = strategy.initialize(inputs, signals)
    configs = [c for c in fixed['catalog'] if not identifiers or c['id'] in identifiers]
    assert not identifiers or len(configs) == len(identifiers)
    for model in models:
        assert model in fixed['models']
        for config in configs:
            started = time.monotonic()
            run_one(config, model, inputs, features, strategy, fixed)
            print(f'{model} {config["id"]} 全30場完了 {time.monotonic()-started:.1f}秒', flush=True)
    validate(fixed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='元E01固定と反転保険の十三条件')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--models', default='observed,specified')
    parser.add_argument('--ids', default='')
    args = parser.parse_args()
    if args.freeze:
        freeze()
        print('元E01固定と反転保険の十三条件を固定しました', flush=True)
    if args.run:
        run(args.models.split(','), [s for s in args.ids.split(',') if s])
