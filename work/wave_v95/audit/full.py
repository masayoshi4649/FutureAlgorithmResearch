"""38条件全31場の旧執行会計と新入口及び四源再参加を、同じ終端保存経路で監査する。"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import pickle

import numba
import numpy as np

import common
import protocol
import state_checks
import entry_checks
import price_checks
import check_loss
import check_signals


OLD_PATH = common.ROOT / 'work/wave_v94/audit/full.py'
OLD = common.module('旧94の独立会計関数のみ読取95', OLD_PATH)
WORKER_STATE = None


def read(path: Path) -> object:
    """
    機能: 明示した入力又は結果を読み、正式と人工の保存先を混同しない。
    引数: path(Path)。JSON又はpickle。
    返り値: object。保存内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def account(key: tuple[str, str], prepared: dict, config: dict, ledger: dict) -> tuple[dict, dict]:
    """
    機能: 不変の旧独立会計と新66列を接続し、新metadataの全指紋と疎展開を確認する。
    引数: key(tuple[str,str])、prepared/config/ledger(dict)。因果入力と保存台帳。
    返り値: tuple[dict,dict]。場会計と照合件数。
    旧94の会計/出口/全原行源時計/状態復元の数式を読取再利用し、旧mainは呼ばない。
    """
    record, signal = prepared['record'], prepared['signal']
    row, counts = OLD.account(key, record, signal, config, ledger)
    observed = dict(orders=np.asarray(ledger['orders'], float).reshape((-1, 17)),
                    events=np.asarray(ledger['events'], float).reshape((-1, 12)),
                    loss_reentry_events=np.asarray(ledger['loss_reentry_events'], float).reshape((-1, 66)))
    counts.update(check_loss.verify(record, signal, config, observed))
    common.exact(prepared['trend_candidate_state'], ledger['trend_candidate_state'])
    common.exact(prepared['trend_lp_allowed'], ledger['trend_lp_allowed'])
    restored_event = OLD.expand(np.asarray(ledger['trend_event_changes']), len(record['time_s']))[:, 0]
    common.exact(restored_event, signal['event'])
    assert OLD.array_sha(signal['event']) == ledger['trend_event_SHA256']
    assert OLD.array_sha(signal['loss_observations']) == ledger['loss_observations_SHA256']
    assert OLD.array_sha(signal['execution_lp_index']) == ledger['execution_lp_index_SHA256']
    counts['新入口イベントと四源指紋'] = 1
    return row, counts


def verify_config(config: dict, material: dict, prepared: dict, fixed: dict, base: Path,
                  artificial: bool, period_map: dict) -> dict:
    """
    機能: 一条件の全口座・全期間・安定性を、人工と正式共通の独立手順で検算する。
    引数: config/material/prepared/fixed/period_map(dict)、base(Path)、artificial(bool)。
    返り値: dict。条件別全会計、件数、入力結果指紋。
    """
    rows, ledgers, expected_parts, counts, fingerprints = [], {}, {}, {}, {}
    for part, period in (('front', '前16'), ('back', '後15')):
        result_path = base / part / 'results' / (config['id'] + '.json')
        ledger_path = base / part / 'ledgers' / (config['id'] + '.pkl')
        result, subset = read(result_path), read(ledger_path)
        assert result['config'] == config and common.sha(ledger_path) == result['ledger_SHA256']
        assert not set(ledgers) & set(subset)
        ledgers.update(subset)
        expected_parts[period] = result
        fingerprints.update(common.fingerprint([result_path, ledger_path]))
    assert set(ledgers) == set(material['prices'])
    for key in sorted(ledgers):
        if not artificial:
            check_signals.verify(material, key, config, prepared[key])
            price_checks.signal_check(material, key[0], key[1], config, prepared[key]['signal'])
        row, checked = account(key, prepared[key], config, ledgers[key])
        rows.append(row)
        for name, amount in checked.items():
            counts[name] = counts.get(name, 0) + amount
    for period, result in expected_parts.items():
        common.same([row for row in rows if row['session'] in fixed[period]], result['rows'])
    periods, stable = {}, {}
    for period, sessions in period_map.items():
        stable[period] = OLD.stability(rows, config, material['prices'], sessions)
        periods[period] = {}
        for symbol in common.SYMBOLS:
            periods[period][symbol] = OLD.aggregate(rows, symbol, sessions)
            if period in expected_parts:
                expected = expected_parts[period]
                common.same(periods[period][symbol], expected['periods'][period][symbol])
                common.same(stable[period][symbol], expected['stability'][symbol])
            counts['商品期間集計'] = counts.get('商品期間集計', 0) + 1
    counts['口座'] = len(ledgers)
    print(f"{config['id']}: {'人工' if artificial else '正式'}全口座会計/最初返済/旧22源/新66列/全8期間が一致", flush=True)
    return dict(id=config['id'], totals=dict(config=config, rows=rows, periods=periods, stability=stable),
                counts=counts, fingerprints=fingerprints)


def initialize_worker(base: str, artificial: bool, period_map: dict) -> None:
    """
    機能: 条件担当プロセスへ読取専用素材を一度だけ読み、同じ検算関数へ接続する。
    引数: base(str)、artificial(bool)、period_map(dict)。
    返り値: None。WORKER_STATEへ保存素材を保持。条件ごとに新しいPLは計算しない。
    """
    global WORKER_STATE
    folder = Path(base)
    fixed = read(folder / '事前固定.json')
    if artificial:
        fixture = read(folder / 'fixture.pkl')
        WORKER_STATE = dict(base=folder, artificial=True, fixed=fixed, material=fixture['material'],
                            prepared=fixture['prepared'], period_map=period_map)
    else:
        data = common.module('95並列正式監査の読取素材', common.WORK / 'data.py')
        strategy = common.module('95並列正式監査の因果準備', common.WORK / 'strategy.py')
        WORKER_STATE = dict(base=folder, artificial=False, fixed=fixed, material=data.load_inputs(),
                            strategy=strategy, period_map=period_map)
    numba.config.CACHE_DIR = str(common.HERE / 'jit')


def worker(config: dict) -> dict:
    """
    機能: 指定一条件を、逐次経路と同じverify_configで省略なく検算する。
    引数: config(dict)。固定条件。
    返り値: dict。全口座/期間/安定性/指紋の条件別証跡。
    """
    state = WORKER_STATE
    prepared = (state['prepared'][config['id']] if state['artificial'] else
                state['strategy'].prepare(state['material'], config))
    return verify_config(config, state['material'], prepared, state['fixed'], state['base'],
                         state['artificial'], state['period_map'])


def run(fixed: dict, material: dict | None, prepare: object, base: Path, artificial: bool,
        workers: int = 3) -> dict:
    """
    機能: 全条件の前後台帳から口座・期間・安定性を独立算定し、全後段と指紋を保存する。
    引数: fixed(dict)、material(dict|None)、prepare(Callable|None)、base(Path)、artificial(bool)、workers(int)。
    返り値: dict。検査件数と全会計及び指紋。人工も同じループ/後段/保存を通す。
    """
    conditions = fixed['条件']
    assert len(conditions) == 38
    if artificial:
        assert fixed['人工専用'] and base.resolve().is_relative_to(common.HERE.resolve())
    else:
        assert fixed['全31既知'] and len(fixed['全31']) == 31
        assert base == common.WORK
    for relative, digest in fixed['SHA256'].items():
        assert common.sha(common.ROOT / relative) == digest, relative
    selection = read(base / '前16参考代表.json')
    assert selection['固定SHA256'] == common.sha(base / '事前固定.json')
    assert selection['後15正式損益前選定']
    for relative, digest in selection['結果SHA256'].items():
        assert common.sha(common.ROOT / relative) == digest, relative
    period_map = {name: fixed[name] for name in ('全31', '前16', '後15', '旧30', '後14', '追加1')}
    period_map.update(デイ=[session for session in fixed['全31'] if session.endswith('_Day')],
                      ナイト=[session for session in fixed['全31'] if session.endswith('_Night')])
    counts, totals, fingerprints = {}, {}, {}
    assert 1 <= workers <= 3
    if workers == 1:
        calculated = {config['id']: verify_config(config, material, prepare(material, config), fixed,
                      base, artificial, period_map) for config in conditions}
    else:
        calculated = {}
        with ProcessPoolExecutor(max_workers=workers, initializer=initialize_worker,
                                 initargs=(str(base), artificial, period_map)) as executor:
            tasks = {executor.submit(worker, config): config['id'] for config in conditions}
            for task in as_completed(tasks):
                calculated[tasks[task]] = task.result()
    assert set(calculated) == {config['id'] for config in conditions}
    for config in conditions:
        value = calculated[config['id']]
        totals[config['id']] = value['totals']
        fingerprints.update(value['fingerprints'])
        for name, amount in value['counts'].items():
            counts[name] = counts.get(name, 0) + amount
    analysis_path = base / 'analysis/比較結果.json'
    analysis = read(analysis_path)
    assert set(analysis['results']) == set(totals)
    for ident, values in totals.items():
        common.same(values, analysis['results'][ident])
    fingerprints.update(common.fingerprint([Path(__file__), Path(common.__file__), Path(protocol.__file__),
                                            Path(state_checks.__file__), Path(entry_checks.__file__),
                                            Path(price_checks.__file__), Path(check_loss.__file__),
                                            Path(check_signals.__file__), OLD_PATH, base / '事前固定.json',
                                            base / '前16参考代表.json', analysis_path]))
    for relative, digest in fixed['SHA256'].items():
        assert common.sha(common.ROOT / relative) == digest, relative
    assert counts['口座'] == 38 * len(fixed['全31']) * 2
    assert counts['商品期間集計'] == 608
    if not artificial:
        assert counts['口座'] == 2356
    proof = dict(合格=True, 人工専用=artificial, 全期間既知=True, 検査件数=counts,
                 全会計=totals, SHA256=fingerprints, 旧数式の読取再利用=True,
                 旧fullmain呼出し=0, 末尾依存名の明示import及び終端保存=True,
                 条件worker数=workers, 同一検算関数で全38を実行=True, API取得=0, 実注文=0, 旧変更=0)
    name = ('人工専用_全38監査main終端保存と全源及び期間会計.json' if artificial else
            '全38全31の新入口と四源反転及び全原板会計と安定性の独立検算.json')
    common.save(name, proof)
    common.exact(read(common.HERE / name), common.clean(proof))
    return proof


def main() -> None:
    """
    機能: 正式監査又は隔離人工を通常CLIで起動し、終端保存/再読込まで通す。
    引数: CLIの--formal又は--artificial(Path)。人工fixture保存先。
    返り値: None。根の許可前に--formalを実行しない。
    """
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--formal', action='store_true')
    mode.add_argument('--artificial', type=Path)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    if args.artificial:
        base = args.artificial.resolve()
        assert base.is_relative_to(common.HERE.resolve())
        fixture = read(base / 'fixture.pkl')
        fixed = read(base / '事前固定.json')
        run(fixed, fixture['material'], lambda material, config: fixture['prepared'][config['id']], base, True, args.workers)
    else:
        data = common.module('95正式独立監査の保存素材', common.WORK / 'data.py')
        strategy = common.module('95正式独立監査の因果準備', common.WORK / 'strategy.py')
        run(read(common.WORK / '事前固定.json'), data.load_inputs() if args.workers == 1 else None,
            strategy.prepare, common.WORK, False, args.workers)


if __name__ == '__main__':
    main()
