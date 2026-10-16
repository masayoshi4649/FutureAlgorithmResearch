"""条件を変えず追加Dayを別に再生し、既知32の選択へ混ぜない。"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import base
import catalog
import research


HERE = Path(__file__).resolve().parent
SESSION = '2026-10-13_Day'
DIRECTORY = HERE/'holdout_finance'
ACTIVITY = HERE/'holdout_input/追加Dayの活動と19入口.json'


def save(path: Path, value: dict) -> None:
    """
    機能: 追加一場の新しい金融証跡を既知32と別に保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。過去の成果と同名資料は上書きしない。
    """
    assert path.resolve().is_relative_to(DIRECTORY.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def sources() -> dict:
    """
    機能: 不変121条件と新一場入力・活動・正式32完了を小さい証跡へ結ぶ。
    引数: なし。
    返り値: dict[str,str]は内容指紋。旧32巨大入力と原本の再hashはしない。
    """
    paths = [Path(__file__), HERE/'research.py', HERE/'catalog.py', HERE/'base.py',
        HERE/'金融事前固定.json', HERE/'金融全32の結果.json', ACTIVITY,
        HERE/'holdout_input/metadata.json', HERE/'holdout_input/追加入力sourceと人工確認の固定.json',
        HERE/'engine/追加Day入力sourceの独立レビュー.json']
    activity = base.read(ACTIVITY)
    paths += [base.ROOT/name for name in activity['source_SHA256']]
    fixed = base.read(HERE/'金融事前固定.json')
    paths += [base.ROOT/name for name in fixed['source_SHA256']]
    return {str(path.relative_to(base.ROOT)): base.digest(path) for path in paths}


def freeze() -> None:
    """
    機能: 追加一場の損益前に、旧32と同じ121条件・主・実枚数を固定する。
    引数: なし。
    返り値: None。旧32で見つかった比較候補も追加場に合わせて変更しない。
    """
    fixed = base.read(HERE/'金融事前固定.json')
    assert json.loads(json.dumps(catalog.catalog())) == fixed['catalog']
    activity = base.read(ACTIVITY)
    assert activity['全合格'] and activity['session'] == SESSION and activity['金融再生'] == 0
    save(DIRECTORY/'追加Day金融の事前固定.json', dict(全合格=True, session=SESSION,
        catalog=fixed['catalog'], primary=fixed['primary'], source_SHA256=sources(),
        既知32と同条件=True, 活動資格と採用基準の変更=0, 追加場での再選択=0,
        初回新金融=0, 原本再読=0, 現在API=0, 実注文=0))
    print('追加Dayも旧32と同じ121条件で金融前に固定しました。', flush=True)


def load() -> dict:
    """
    機能: 一回作成した新活動と完全prepareを同じbytesで読み出す。
    引数: なし。
    返り値: dictは活動・peer・prepared。旧64baseや原本を再読しない。
    """
    metadata = base.read(ACTIVITY)
    path = base.ROOT/metadata['path']
    assert path.resolve().is_relative_to((HERE/'holdout_input').resolve())
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == metadata['SHA256']
    value = pickle.loads(gzip.decompress(payload))
    assert value['schema_version'] == 1 and value['session'] == SESSION
    assert set(value['prepared']) == {(SESSION, symbol) for symbol in catalog.SYMBOLS}
    assert len(value['peer']['cases']) == 19
    base.immutable(value)
    return value


def store(path: Path, output: dict, entry_id: str | None, quantity: int, exit_id: str) -> str:
    """
    機能: 新入口は共通台帳へ保存し、追加旧G0には元の候補診断も保存する。
    引数: path(Path)、output(dict)、entry_id(str|None)、quantity(int)、exit_id(str)は保存内容。
    返り値: strは新台帳の指紋。旧G0の由来を新しい板入口の根拠に代用しない。
    """
    if exit_id != 'OLD_G0':
        return research.ledger(path, output, entry_id, quantity, exit_id)
    assert not path.exists() and path.resolve().is_relative_to(DIRECTORY.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    names = ('orders', 'order_columns', 'trades', 'trade_columns', 'events', 'event_columns',
        'stats', 'stat_columns', 'curve', 'source_curve', 'target_trace', 'trace_columns',
        'growth_cohorts', 'growth_cohort_columns', 'entry_parent_diagnostics', 'entry_parent_columns')
    saved = {name: output[name] for name in names}
    saved.update(raw_entry_diagnostics=[], entry_id=None, configured_quantity=quantity, exit_id=exit_id,
                 entry_basis='旧G0の元entry_parent_diagnosticsを保存。新104自己候補とは別。')
    with path.open('wb') as stream:
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0, compresslevel=3) as zipped:
            pickle.dump(saved, zipped, protocol=5)
    return base.digest(path)


def run() -> None:
    """
    機能: 新一場の全121と旧G0を同じ注文・費用規則で一回再生する。
    引数: なし。
    返り値: None。新しい順位は作らず、各条件の追加場会計を保存する。
    """
    fixed = base.read(DIRECTORY/'追加Day金融の事前固定.json')
    assert fixed['全合格'] and fixed['source_SHA256'] == sources()
    assert not list((DIRECTORY/'ledger').glob('*/*.pkl.gz')) and not (DIRECTORY/'追加Day全121の損益.json').exists()
    bundle = load()
    interface = base.module('104追加Day金融の共通接口', HERE/'engine/interface.py')
    accounting = base.module('104追加Day金融の不変会計', base.ROOT/'work/wave_v102/accounting.py')
    guard = base.module('104追加金融の旧module保存先ガード', HERE/'holdout_input/core.py')
    with guard.owned_cache():
        strategy = base.module('104追加Dayの不変G0執行', base.ROOT/'work/wave_v102/strategy.py')
    # ----------------------------------------
    # import終了後の設定復元だけでなく、生成済みdispatcher保存先も新所有域か確認する。
    for imported in list(sys.modules.values()):
        filename = getattr(imported, '__file__', None)
        if not filename or not str(filename).startswith(str(base.ROOT/'work')):
            continue
        for value in list(vars(imported).values()):
            if type(value).__name__ != 'CPUDispatcher':
                continue
            locator = getattr(getattr(getattr(value, '_cache', None), '_impl', None), '_locator', None)
            if locator is not None:
                assert Path(locator.get_cache_path()).resolve().is_relative_to(HERE.resolve()), filename
    adapter = interface.module('104の不変103配分snapshot', HERE/'engine/adapter.py')
    cases = {config['id']: dict(config=config, rows=[], ledgers={}) for config in fixed['catalog']}
    extras = {}
    for symbol in catalog.SYMBOLS:
        key, value = (SESSION, symbol), bundle['prepared'][SESSION, symbol]
        legs = {}
        for config in fixed['catalog']:
            ident = config['id']
            if config['kind'] == 'previous':
                output = strategy.play(adapter.reference_config(), key, bundle['prepared'])
                entry_id, exit_id, quantity = None, 'OLD_G0', 1
                output['raw_entry_diagnostics'] = []
            elif config['kind'] == 'portfolio':
                exit_id, allocation = config['exit_id'], tuple(config['allocations'][symbol])
                for component, quantity in zip(config['components'], allocation, strict=True):
                    cache_key = (component, exit_id, quantity)
                    if cache_key not in legs:
                        output = interface.play(value, bundle['peer']['cases'][component][symbol]['normal'], exit_id, quantity)
                        accounting.account(key, output)
                        path = DIRECTORY/'legs'/f'{component}_{exit_id}_Q{quantity}'/(SESSION+'_'+symbol+'.pkl.gz')
                        fingerprint = store(path, output, component, quantity, exit_id)
                        extras[symbol+'|'+component+'|'+exit_id+'|'+str(quantity)] = research.item(path, fingerprint)
                        legs[cache_key] = output
                output = interface.join({family: legs[component, exit_id, quantity]
                    for family, component, quantity in zip(('C', 'R'), config['components'], allocation, strict=True)}, allocation, symbol)
                entry_id, quantity = None, sum(allocation)
            else:
                entry_id, exit_id, quantity = config['entry_id'], config['exit_id'], config['quantity'][symbol]
                output = interface.play(value, bundle['peer']['cases'][entry_id][symbol]['normal'], exit_id, quantity)
            row = accounting.account(key, output)
            cases[ident]['rows'].append(row)
            path = DIRECTORY/'ledger'/ident/(SESSION+'_'+symbol+'.pkl.gz')
            fingerprint = store(path, output, entry_id, quantity, exit_id)
            cases[ident]['ledgers'][SESSION+'|'+symbol] = research.item(path, fingerprint)
            del output
        del legs
        print(symbol+' 追加Dayの全121条件を保存', flush=True)
    assert fixed['source_SHA256'] == sources()
    save(DIRECTORY/'追加Day全121の損益.json', dict(全合格=True, session=SESSION, cases=cases,
        extra_legs=extras, 掲載会計数=242, 追加実枚数腿数=24, 新実数量金融再生数=254,
        配分合算会計数=12, 新台帳数=266, source_SHA256=sources(), 開始終端source一致=True,
        固定121条件変更=0, 主=fixed['primary'], 原本再読=0, 旧64base再読=0, 現在API=0, 実注文=0,
        限界='今回追加の一場。旧32の選択へ混ぜず別確認とする。一場だけで将来安定を証明しない。'))
    print('追加Dayの固定121条件と旧対照を保存。独立監査へ渡します。', flush=True)


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 保存追加場の検証から外部通信を拒否する。
    引数: args(tuple)、kwargs(dict)は通信指定。
    返り値: None。常に例外を送出する。
    """
    raise RuntimeError('保存追加Dayだけを検証します')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--freeze', action='store_true')
    mode.add_argument('--run', action='store_true')
    options = parser.parse_args()
    socket.create_connection = deny
    socket.socket.connect = deny
    freeze() if options.freeze else run()
