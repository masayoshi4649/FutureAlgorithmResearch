"""順行入口とドテンを共通会計で比較し、前半だけで代表を固定する。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
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
PRIOR = HERE.parent / 'wave_v83'
FIXED = HERE / 'results/事前固定.json'
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')


def load_module(name, path):
    """
    機能: 指定した既存又は今回のPythonを固有名で読み、同名衝突を防ぐ。
    引数: name (str)、path (Path)。
    返り値: module。既に同じ絶対パスで読み込んだ時は再利用する。
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


data = load_module('wave83_price_input_readonly', PRIOR / 'data.py')
previous_data = sys.modules.get('data')
try:
    sys.modules['data'] = data
    legacy = load_module('wave83_accounting_readonly', PRIOR / 'research.py')
finally:
    if previous_data is None:
        sys.modules.pop('data', None)
    else:
        sys.modules['data'] = previous_data

SYMBOLS = legacy.SYMBOLS
CONTRACTS = legacy.CONTRACTS
ORDER_COLUMNS = legacy.ORDER_COLUMNS
TRADE_COLUMNS = legacy.TRADE_COLUMNS
CYCLE_COLUMNS = legacy.CYCLE_COLUMNS
STAT_COLUMNS = legacy.STAT_COLUMNS
EVENT_COLUMNS = legacy.EVENT_COLUMNS
account = legacy.account
aggregate = legacy.aggregate
score = legacy.score
choose = legacy.choose


def read(path):
    """
    機能: 保存済み日本語JSONを復元する。
    引数: path (Path)。
    返り値: dict 又は list の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save_json(path, value):
    """
    機能: 今回領域だけに有限数値のJSONを一時保存後に確定する。
    引数: path (Path)、value (object)。
    返り値: None。旧研究ファイルへは書き込まない。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


# ----------------------------------------
def specification():
    """
    機能: 旧会計と同じ採点基準に今回の比較・固定条件を追加する。
    引数: なし。
    返り値: dict の事前仕様。新しい損益は参照しない。
    """
    value = legacy.specification()
    for key in ('感度', '乱数'):
        value.pop(key)
    value.update(
        会計再利用='wave_v83/research.py の account/aggregate/score/choose を変更せず使用。決済脚・親組の利益損失と全玉時価DDを保存する。',
        主執行='固定の追加発注遅延は0。現在値で条件を判断し、有効な同観測の売買気配で約定。無効気配又は場末の予定時計と観測の差を0秒の約定と誤認しない。観測内の新規・返済順序はcatalogの固定仕様に従う。',
        家族代表='6家族ごとに主の利益割合基準で1条件を前16だけから固定。',
        同幅比較='幅8呼値・variant1の6家族を損益を見る前から説明用に固定し、全30場で比較する。成績が良いから選んだ代表とは区別する。',
        比較組='同幅比較で家族0対1は入口方向だけの逆張り対順行。家族2対3/4/5は返済後の待機・即ドテン・反対方向へ一段確認・利益時だけ即ドテンの比較。具体的売買状態遷移を再生し、元損益の符号反転では計算しない。',
        最終='主3・家族6・事前指定の同幅6条件の一意unionだけ全30を再生する。後14の成績で代表を選び直さない。',
        論理対照='同じ固定unionをbid=ask=CurrentPrice、quote_valid=price_validへ変換した仮想市場で再生する。実手数料は維持。注文状態も変わるので通常損益への費用足し戻し又は利益上界とは呼ばない。',
        不要な追加探索='乱数種比較・0/1/5秒の固定遅延比較・全条件の後半探索は行わない。',
        入力検証='wave_v83の価格入力を読取専用で再利用。親プロセスで入力の指紋を1回検証し、同じ配列をスレッドで共有する。原本データ・旧研究ファイルは変更しない。')
    return value


def freeze():
    """
    機能: 根担当の開始指示後にエンジン・条件・既存会計・入力を事前固定する。
    引数: なし。
    返り値: dict の固定記録。既存の異なる固定値は上書きしない。
    """
    catalog_module = load_module('wave84_catalog', HERE / 'catalog.py')
    catalog = catalog_module.catalog()
    assert len(catalog) == len({c['id'] for c in catalog}) == 108
    assert {(c['family'], c['width_ticks'], c['variant']) for c in catalog} == {
        (f, w, v) for f in range(6) for w in (2, 4, 8, 16, 32, 64) for v in range(3)}
    source = read(data.PREPARED / '価格入力の仕様.json')
    value = dict(catalog=catalog, 全30=source['全30'], 前16=source['前16'], 後14=source['後14'],
                 specification=specification(), catalog_specification=catalog_module.specification(),
                 code_SHA256={name: data.digest(HERE / name) for name in ('engine.py', 'catalog.py', 'research.py')},
                 legacy_code_SHA256={name: data.digest(PRIOR / name) for name in ('data.py', 'research.py', 'engine.py')},
                 input_SHA256=read(data.PREPARED / '価格入力の照合.json')['出力SHA256'],
                 input_path=str(data.PREPARED / 'inputs.pkl'),
                 入力仕様SHA256=data.digest(data.PREPARED / '価格入力の仕様.json'))
    if FIXED.exists():
        assert read(FIXED) == value, '事前固定内容が変化しています'
    else:
        save_json(FIXED, value)
    return value


def validate_fixed(fixed):
    """
    機能: 今回と再利用元のコードが事前固定されたものと一致するか確認する。
    引数: fixed (dict)。
    返り値: None。不一致なら売買再生を開始しない。
    """
    for name, expected in fixed['code_SHA256'].items():
        assert data.digest(HERE / name) == expected, (name, '今回コードが事前固定から変化')
    for name, expected in fixed['legacy_code_SHA256'].items():
        assert data.digest(PRIOR / name) == expected, (name, '再利用コードが事前固定から変化')
    assert read(data.PREPARED / '価格入力の照合.json')['出力SHA256'] == fixed['input_SHA256']
    assert data.digest(data.PREPARED / '価格入力の仕様.json') == fixed['入力仕様SHA256']


# ----------------------------------------
def run_condition(config, inputs, sessions, fixed, base, model='quotes'):
    """
    機能: 指定1条件の売買を再生し、既存会計で照合して結果と台帳を保存する。
    引数: config/inputs/fixed (dict)、sessions (list[str])、base (Path)、model (str)。
    返り値: dict の条件会計。通常気配又は現在値必約定の対照を扱う。
    """
    assert model in ('quotes', 'ideal_fee')
    run = dict(delay=0., seed=0, slip_ticks=0., sessions=sessions, model=model,
               input_SHA256=fixed['input_SHA256'], code_SHA256=fixed['code_SHA256'],
               legacy_code_SHA256=fixed['legacy_code_SHA256'])
    target = base / 'results' / (config['id'] + '.json')
    ledger_path = base / 'ledgers' / (config['id'] + '.pkl')
    if target.exists():
        result = read(target)
        assert result['config'] == config and result['run'] == run and ledger_path.exists()
        return result
    engine = load_module('wave84_engine', HERE / 'engine.py')
    rows, ledgers = [], {}
    started = time.monotonic()
    for session in sessions:
        for symbol in SYMBOLS:
            key = (session, symbol)
            original = inputs[key]
            record = original if model == 'quotes' else dict(original, bid=original['price'],
                ask=original['price'], quote_valid=original['price_valid'])
            terms = CONTRACTS[symbol]
            output = engine.run(data.as_tuple(record), config['family'], config['width_ticks'], config['variant'],
                                terms['cap'], terms['pointvalue'], terms['fee'], 0., 0, 0.)
            assert len(output) == 5 and output[4].ndim == 2 and output[4].shape[1] == len(EVENT_COLUMNS)
            summary, cycles = account(key, record, output, run)
            rows.append(summary)
            ledgers[key] = dict(orders=output[0], trades=output[1], cycles=cycles, stats=output[3],
                                curve_hash=hashlib.sha256(np.asarray(output[2]).tobytes()).hexdigest())
            if model == 'ideal_fee' or 'final' in base.parts:
                ledgers[key]['events'] = output[4]
    periods = {name: {s: aggregate(rows, s, selected) for s in SYMBOLS} for name, selected in [
        ('前16', [s for s in sessions if s in fixed['前16']]),
        ('後14', [s for s in sessions if s in fixed['後14']]), ('対象', sessions)]}
    result = dict(config=config, run=run, rows=rows, periods=periods, elapsed_seconds=time.monotonic() - started)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_suffix('.pkl.tmp')
    with temporary.open('wb') as stream:
        pickle.dump(ledgers, stream, protocol=5)
    temporary.replace(ledger_path)
    save_json(target, result)
    return result


def batch(configs, inputs, sessions, fixed, base, workers, model='quotes'):
    """
    機能: 共有する読取専用入力を使い、固定条件を少数スレッドで実行する。
    引数: configs (list[dict])、inputs/fixed (dict)、sessions (list[str])、base (Path)、workers (int)、model (str)。
    返り値: None。進捗のみ出力し、損益を見て候補を差し替えない。
    """
    if not configs:
        return
    run_condition(configs[0], inputs, sessions, fixed, base, model)
    print(f'{base.relative_to(HERE)} 1/{len(configs)} 完了', flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = [pool.submit(run_condition, c, inputs, sessions, fixed, base, model) for c in configs[1:]]
        for number, future in enumerate(as_completed(pending), start=2):
            future.result()
            print(f'{base.relative_to(HERE)} {number}/{len(configs)} 完了', flush=True)


# ----------------------------------------
def select(fixed):
    """
    機能: 前半だけから主3観点・家族6を選び、事前指定の同幅6を合流する。
    引数: fixed (dict)。
    返り値: dict の固定代表。後半や論理対照の結果は読まない。
    """
    results = [read(HERE / 'train/results' / (c['id'] + '.json')) for c in fixed['catalog']]
    assert all(r['run']['sessions'] == fixed['前16'] and r['run']['delay'] == 0 and
               r['run']['seed'] == 0 and r['run']['slip_ticks'] == 0 and r['run']['model'] == 'quotes' for r in results)
    primary = [choose(results, kind) for kind in ('利益割合', '場の安定', '親組効率')]
    families = [choose([r for r in results if r['config']['family'] == f], '利益割合') for f in range(6)]
    common = []
    for family in range(6):
        source = next(r for r in results if r['config']['family'] == family and
                      r['config']['width_ticks'] == 8 and r['config']['variant'] == 1)
        record = choose([source], '利益割合')
        record.update(criterion='幅8・出口1幅の事前固定比較', selected_by_performance=False,
                      status='損益で選ばない同幅の説明用比較')
        common.append(record)
    common_ids = {r['family']: r['id'] for r in common}
    pairs = [dict(label='入口方向だけの逆張り対順行', left_id=common_ids[0], right_id=common_ids[1],
                  difference='待機基準から1幅動いた後に取る方向のみを比較。損切り1幅・利確3幅、成行相当約定を共通にする。', selected_by_performance=False)]
    for family, label in [(3, '待機対即ドテン'), (4, '待機対反対方向の一段確認'), (5, '待機対利益時だけ即ドテン')]:
        pairs.append(dict(label=label, left_id=common_ids[2], right_id=common_ids[family],
                          difference='初回の順行入口と追跡幅をそろえ、追跡返済後の新規の扱いを比較する。' +
                          ('一段確認は返済観測の現在値を基準とし、反転側へ1幅進むと建て、元方向へ1幅戻ると通常待機に解除する。' if family == 4 else ''),
                          selected_by_performance=False))
    selected = sorted({r['id'] for r in primary + families + common})
    value = dict(primary=primary, families=families, common_width=common, pairs=pairs, selected=selected,
                 primary_unique=len({r['id'] for r in primary}), selected_unique=len(selected),
                 selected_for_performance=sorted({r['id'] for r in primary + families}),
                 rule=fixed['specification'], 前16=fixed['前16'], 後14を参照した選び直し=False,
                 元結果SHA256={r['config']['id']: data.digest(HERE / 'train/results' / (r['config']['id'] + '.json')) for r in results})
    target = HERE / '前半選定.json'
    if target.exists():
        assert read(target) == value, '前半固定代表が変化しています'
    else:
        save_json(target, value)
    return value


def save_ideal_specification(selection, fixed):
    """
    機能: 同じ代表の仮想執行対照であることを再生前に保存する。
    引数: selection/fixed (dict)。
    返り値: None。論理対照から代表を選び直さない。
    """
    value = dict(対象=selection['selected'], 代表の選び直し=False,
                 仮定='bid=ask=CurrentPrice、quote_valid=price_valid。実手数料あり。実売買での全量約定を証明せず、元の損益への費用足し戻しでもない。',
                 全30=fixed['全30'], 元入力SHA256=fixed['input_SHA256'],
                 code_SHA256=fixed['code_SHA256'], legacy_code_SHA256=fixed['legacy_code_SHA256'])
    path = HERE / 'ideal_fee/固定条件.json'
    if path.exists():
        assert read(path) == value
    else:
        save_json(path, value)


# ----------------------------------------
def main():
    """
    機能: 根担当の指示した段階だけを固定・実行し、全後半探索を避ける。
    引数: CLIの--freeze、--phase、--workers、--select-only。
    返り値: None。引数なしでは売買再生を開始しない。
    """
    parser = argparse.ArgumentParser(description='順行・逆張り・ドテンの固定比較と会計')
    parser.add_argument('--phase', choices=('train', 'final', 'ideal_fee'))
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--select-only', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        freeze()
        if not args.phase and not args.select_only:
            print('会計・選抜・旧会計・入力と今回コードを事前固定しました')
            return
    if not args.phase and not args.select_only:
        parser.error('--freeze 又は --phase 又は --select-only を指定してください')
    fixed = read(FIXED)
    validate_fixed(fixed)
    if args.select_only:
        select(fixed)
        return
    assert 1 <= args.workers <= 16
    inputs = data.load_data(verify=True)
    if args.phase == 'train':
        batch(fixed['catalog'], inputs, fixed['前16'], fixed, HERE / 'train', args.workers)
        select(fixed)
    else:
        selection = read(HERE / '前半選定.json')
        configs = [c for c in fixed['catalog'] if c['id'] in selection['selected']]
        if args.phase == 'final':
            batch(configs, inputs, fixed['全30'], fixed, HERE / 'final/delay0', args.workers)
        else:
            save_ideal_specification(selection, fixed)
            batch(configs, inputs, fixed['全30'], fixed, HERE / 'ideal_fee', args.workers, 'ideal_fee')


if __name__ == '__main__':
    main()
