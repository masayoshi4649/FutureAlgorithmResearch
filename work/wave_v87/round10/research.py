"""仮想判断を固定し、次の有効観測で実行する三方式を全保存場で比較する。"""

import argparse
import hashlib
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
prepare = module('wave85_prepare', OLD / 'prepare.py')


def save(path, value):
    """
    機能: 今回の作業内へ有限値の日本語JSONを保存する。
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
    機能: 仮想源と実行層を接続した今回の戦略を読み込む。
    引数: なし。
    返り値: module。
    """
    return module('wave87_round10_strategy', HERE / 'strategy.py')


def reference_folder(identifier):
    """
    機能: 仮想源に対応する既存の凍結台帳の所在を返す。
    引数: identifier(str)。
    返り値: Path。
    """
    if identifier == 'E01_G_U':
        return OLD
    if identifier.startswith('C_'):
        return HERE.parent / 'round7'
    if identifier.startswith('I_'):
        return HERE.parent / 'round8'
    raise ValueError(identifier)


def freeze():
    """
    機能: 因果・会計検査後、全場損益を見る前に十三条件と全参照指紋を固定する。
    引数: なし。
    返り値: dict。
    """
    strategy = strategy_module()
    catalog = module('wave87_round10_catalog', HERE / 'catalog.py')
    strategy.prior.prepare.load(verify=True)
    prior = old.read(OLD / 'results/事前固定.json')
    old.validate(prior)
    paths = {Path(m.__file__).resolve() for m in tuple(sys.modules.values())
             if getattr(m, '__file__', None) and Path(m.__file__).suffix == '.py'
             and Path(m.__file__).resolve().is_relative_to(ROOT / 'work')}
    paths.update(HERE.glob('*.py'))
    paths.update([HERE.parent / 'round6/事前固定.json', HERE.parent / 'round6/fee_account.py',
                  HERE.parent / 'round7/事前固定.json', HERE.parent / 'round7/strategy.py',
                  HERE.parent / 'round8/事前固定.json', HERE.parent / 'round8/strategy.py',
                  HERE.parent / 'round8/prepare.py', HERE.parent / 'round8/engine.py',
                  HERE.parent / 'round3/事前固定.json', HERE.parent / 'round3/prepared/short.pkl',
                  HERE.parent / 'round3/prepared/支持準備の照合.json',
                  HERE.parent / 'round3/prepared/終端元時計の照合.json',
                  HERE.parent / 'round8/prepared/支持参照固定.json'])
    paths.update(ROOT / 'work/wave_v86' / name for name in
                 ('事前固定.json', 'catalog.py', 'phase2/事前固定.json', 'phase2/catalog.py'))
    proofs = [HERE / '四つの仮想規則と元GU対照の全会計完全一致.json',
              HERE / 'audit/差引実行のUID会計と次観測境界の人工検査.json',
              HERE / 'audit/差引実行の旧仮想不変とUID会計と未来切断.json',
              HERE / 'audit/差引実行の保険相殺と元玉終了の分岐切断.json']
    for path in proofs:
        assert old.read(path)['全合格'], path.name
    paths.update(proofs)
    paths.update(HERE / 'audit' / name for name in ('checks.py', 'prefixes.py', 'focused.py'))
    references = []
    for identifier in ('E01_G_U', 'C_H05_S25', 'C_H05_S50', 'I_P00_R50_C1'):
        folder = reference_folder(identifier) / 'observed'
        references.extend([folder / 'results' / (identifier+'.json'), folder / 'ledgers' / (identifier+'.pkl')])
    fixed = dict(catalog=catalog.catalog(), specification=catalog.specification(), models=['observed'],
        **{k: prior[k] for k in ('全30', '前16', '後14', 'input_SHA256', 'input_proof_SHA256')},
        code_SHA256={str(p.relative_to(ROOT)): old.sha(p) for p in sorted(paths)},
        基準結果SHA256={str(p.relative_to(ROOT)): old.sha(p) for p in references})
    assert len(fixed['catalog']) == 13
    if FIXED.exists():
        assert old.read(FIXED) == fixed, '固定内容が変化しています'
    else:
        save(FIXED, fixed)
    return fixed


def validate(fixed):
    """
    機能: 固定した実装・仮想売買源・入力準備の変更を検知する。
    引数: fixed(dict)。
    返り値: None。
    """
    for field in ('code_SHA256', '基準結果SHA256'):
        for name, digest in fixed[field].items():
            assert old.sha(ROOT / name) == digest, name
    assert old.sha(OLD / 'prepared/入力準備の完了.json') == fixed['input_proof_SHA256']


def equal_reference(ledger, reference, key):
    """
    機能: 今回の仮想源が既存の凍結判断・会計・時価と同一か確認する。
    引数: ledger/reference(dict)、key(tuple[str,str])。
    返り値: None。
    """
    for name in ('orders', 'trades', 'cycles', 'fees', 'time_events'):
        np.testing.assert_array_equal(ledger[name], reference[name], err_msg=str((key, name)))
    assert ledger['net_trades'] == reference['net_trades'], key
    assert ledger['curve_SHA256'] == reference['curve_SHA256'], key
    assert ledger['raw_curve_SHA256'] == reference['raw_curve_SHA256'], key


def array_sha(value):
    """
    機能: 密な実建玉の時価又は差引数量を保存せず内容指紋にする。
    引数: value(ndarray)。
    返り値: str。
    """
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def run_one(config, model, inputs, features, strategy, fixed):
    """
    機能: 六十口座の仮想判断を照合し、実注文の全会計と疎な台帳を保存する。
    引数: config/inputs/features/fixed(dict)、model(str)、strategy(module)。
    返り値: dict。
    """
    path = HERE / model / 'results' / (config['id']+'.json')
    ledger_path = HERE / model / 'ledgers' / (config['id']+'.pkl')
    run = dict(model=model, delay=0., sessions=fixed['全30'], code_SHA256=fixed['code_SHA256'],
               input_SHA256=fixed['input_SHA256'], 発注='仮想判断を受領後の次有効観測。無遅延対照を別掲。')
    if path.exists():
        saved = old.read(path)
        assert saved['run'] == run and saved['config'] == config
        assert old.sha(ledger_path) == saved['ledger_SHA256']
        return saved
    source_id = config['source_id']
    with (reference_folder(source_id) / model / 'ledgers' / (source_id+'.pkl')).open('rb') as stream:
        reference = pickle.load(stream)
    with (OLD / model / 'ledgers/E01_G_U.pkl').open('rb') as stream:
        core_reference = pickle.load(stream)
    rows, ledgers, virtual_rows = [], {}, []
    started = time.monotonic()
    for key, ready in sorted(inputs.items()):
        result, settings = strategy.play(config, ready, features[key], observed=True)
        row, ledger, equity = old.account(strategy.previous, ready, result, settings)
        virtual_row, virtual_ledger, virtual_equity = old.account(strategy.previous, ready, result['virtual_result'], settings)
        core_row, core_ledger, core_equity = old.account(strategy.previous, ready, result['core_result'], settings)
        equal_reference(virtual_ledger, reference[key], key)
        equal_reference(core_ledger, core_reference[key], key)
        row.update(virtual_net=virtual_row['net'], virtual_fees=virtual_row['fees'], core_net=core_row['net'],
                   execution_net_change=row['net']-virtual_row['net'],
                   execution_fee_change=row['fees']-virtual_row['fees'], virtual_unchanged=True)
        if config['execution_mode'] != 'IDEAL':
            scheduled = result['orders'][(result['orders'][:, 7] == 0) & (result['orders'][:, 6] == 92)]
            row['time_forced_exits'] = len(np.unique(scheduled[:, 0]))
            row['time_exit_lots'] = int(scheduled[:, 4].sum())
        ledger.update(virtual_ledger=virtual_ledger, core_ledger=core_ledger,
                      gross_equity_SHA256=array_sha(result['curve'][:, 0]))
        for name in ('order_uids', 'execution_events', 'virtual_feed'):
            if name in result:
                ledger[name] = result[name].copy()
        if len(result.get('execution_states', [])):
            states = result['execution_states']
            changed = np.r_[True, np.any(states[1:] != states[:-1], axis=1)]
            ledger['execution_state_changes'] = np.column_stack((np.flatnonzero(changed), states[changed]))
            ledger['execution_states_SHA256'] = array_sha(states)
            ledger['net_inventory_SHA256'] = array_sha(result['curve'][:, 6])
        virtual_rows.append(virtual_row)
        rows.append(row)
        ledgers[key] = ledger
        del result, equity, virtual_equity, core_equity
    periods = {period: {s: old.aggregate(strategy.previous, rows, s, fixed[period])
                       for s in ('TOPIX', 'NK225')} for period in ('前16', '後14', '全30')}
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        pickle.dump(ledgers, stream, protocol=5)
    temporary.replace(ledger_path)
    output = dict(config=config, model=model, run=run, rows=rows, periods=periods,
                  全条件仮想源完全一致=True, 仮想源行=virtual_rows, ledger_SHA256=old.sha(ledger_path),
                  elapsed_seconds=time.monotonic()-started)
    save(path, output)
    return output


def run(models, identifiers):
    """
    機能: 事前固定した観測約定の条件だけを全保存セッションで実行する。
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
    parser = argparse.ArgumentParser(description='仮想判断を固定した実行層の十三条件')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--models', default='observed')
    parser.add_argument('--ids', default='')
    args = parser.parse_args()
    if args.freeze:
        freeze()
        print('仮想判断を固定した実行層の十三条件を固定しました', flush=True)
    if args.run:
        run(args.models.split(','), [s for s in args.ids.split(',') if s])
