"""三戦略の公開注文を共通実行・会計に通して固定配分を比較する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np

import catalog
import execution
import accounting

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXED = HERE / '事前固定.json'
SOURCES = catalog.SOURCES


def read(path):
    """
    機能: UTF-8の日本語JSONを読む。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 既存資料と入力を変更せず内容指紋を計算する。
    引数: path(Path)。
    返り値: str。
    """
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(8*1024*1024), b''):
            hasher.update(part)
    return hasher.hexdigest()


def save(path, value):
    """
    機能: 作業内の日本語JSONを一時ファイルから保存する。
    引数: path(Path)、value(dict又はlist)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    temporary.replace(path)


def module(name, path):
    """
    機能: 既存の準備器を衝突しない固有名で読み込む。
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


def inputs(verify=True):
    """
    機能: 共通85入力と三源の公開注文キャッシュを接続する。
    引数: verify(bool)。
    返り値: tuple[dict,dict,dict]。原本素材・源注文・指紋。
    """
    prepare = module('wave88_original_prepare', ROOT/'work/wave_v85/prepare.py')
    data, signals, hashes = prepare.load_inputs(verify=verify)
    path = HERE/'prepared/source_orders.pkl'
    with path.open('rb') as stream:
        feeds = pickle.load(stream)
    assert set(feeds) == set(data) and len(data) == 60
    for key in data:
        assert set(feeds[key]) == set(SOURCES)
        for name in SOURCES:
            orders = feeds[key][name]['orders']
            assert isinstance(orders, np.ndarray) and orders.shape[1] == 8
            assert not len(orders) or orders[:, 0].max() < len(data[key]['last'])
    return data, feeds, hashes


def freeze():
    """
    機能: 三源準備と人工監査の完了後、売買・配分・選定を固定する。
    引数: なし。
    返り値: None。固定前に新配分の損益は計算しない。
    """
    assert not FIXED.exists(), '固定済み条件は上書きしません'
    assert not (HERE/'results').exists(), '損益の閲覧後に事前固定しません'
    prepared = read(HERE/'prepared/準備完了.json')
    checks = read(HERE/'audit/三源配分の逐次執行と独立会計の人工検査.json')
    assert prepared['全合格'] and checks['全合格']
    causal = read(HERE/'source_audit/三源の追加品質と原本から配分までの未来切断.json')
    gap = read(HERE/'audit/M3観測建値と価格飛越しの人工検査.json')
    assert causal['全合格'] and gap['全合格']
    dependencies = {}
    for evidence in (prepared, checks, causal, gap):
        for key, mapping in evidence.items():
            if 'SHA256' in key and isinstance(mapping, dict):
                for name, digest in mapping.items():
                    if isinstance(digest, str) and len(digest)==64 and (ROOT/name).is_file():
                        assert sha(ROOT/name)==digest, name
                        dependencies[name] = digest
    assert sha(HERE/'prepared/source_orders.pkl') == prepared['源注文SHA256']
    data, feeds, hashes = inputs(verify=True)
    paths = list(HERE.glob('*.py'))
    paths += [HERE/'prepared/source_orders.pkl', HERE/'prepared/準備完了.json',
              HERE/'audit/execution_checks.py', HERE/'audit/三源配分の逐次執行と独立会計の人工検査.json']
    paths += list((HERE/'prepared').glob('*.json'))
    paths += list(HERE.glob('生成仕様.json'))
    paths += list((HERE/'theory').glob('*.json'))
    paths += list((HERE/'audit').glob('*.py'))
    paths += list((HERE/'audit').glob('*.json'))
    paths += list((HERE/'source_audit').glob('*.py'))
    paths += list((HERE/'source_audit').glob('*.json'))
    code = dependencies | {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths)) if path.is_file()}
    sessions = sorted({key[0] for key in data})
    save(FIXED, dict(catalog=catalog.catalog(), specification=catalog.specification(),
        code_SHA256=code, input_SHA256=hashes, 全30=sessions, 前16=sessions[:16], 後14=sessions[16:],
        準備証拠=prepared, 人工検査=checks, 全期間既知=True))
    print('三源・22条件の配分と共通実行・会計を固定しました', flush=True)


def validate(fixed):
    """
    機能: 固定した条件と全実装・入力の指紋を照合する。
    引数: fixed(dict)。
    返り値: None。
    """
    assert catalog.catalog() == fixed['catalog']
    assert catalog.specification() == fixed['specification']
    for name, digest in fixed['code_SHA256'].items():
        assert sha(ROOT/name) == digest, name


def samples(ready, equity):
    """
    機能: 同じ原本時計の1分格子へ、当時までの清算時価を対応させる。
    引数: ready(dict)、equity(ndarray)。
    返り値: dict。欠測は無理にゼロにせず有効性を保存する。
    """
    grid = np.arange(ready['start']+60., ready['limit'], 60.)
    indices = np.searchsorted(ready['time_s'], grid, side='right')-1
    safe = np.maximum(indices, 0)
    valid = (indices >= 0) & (grid-ready['time_s'][safe] <= 180.)
    values = np.where(valid, equity[safe], np.nan)
    return dict(times=grid, rows=indices, valid=valid, values=values)


def run(identifiers):
    """
    機能: 固定済み全30場に配分を適用し、源別親損益と全体時価を保存する。
    引数: identifiers(list[str])。空なら全条件。
    返り値: None。
    """
    fixed = read(FIXED)
    validate(fixed)
    data, feeds, hashes = inputs(verify=True)
    assert hashes == fixed['input_SHA256']
    configs = [c for c in fixed['catalog'] if not identifiers or c['id'] in identifiers]
    assert not identifiers or len(configs) == len(identifiers)
    for config in configs:
        started = time.monotonic()
        rows, ledgers = [], {}
        for key in sorted(data):
            ready = data[key]
            source_orders = {name:feeds[key][name]['orders'] for name in SOURCES}
            result = execution.execute(ready, source_orders, config['budgets'])
            row, ledger, equity, source_equity = accounting.account(ready, result)
            row['config_id'] = config['id']
            ledger.update(source_orders=source_orders, samples=samples(ready, equity),
                          curve_SHA256=hashlib.sha256(equity.tobytes()).hexdigest(),
                          source_curve_SHA256=hashlib.sha256(source_equity.tobytes()).hexdigest())
            rows.append(row)
            ledgers[key] = ledger
        periods = {}
        for period in ('前16','後14','全30'):
            periods[period] = {}
            for symbol in ('TOPIX','NK225'):
                selected = [row for row in rows if row['symbol']==symbol and row['session'] in fixed[period]]
                periods[period][symbol] = accounting.aggregate(selected, [(r['curve_min'],r['curve_max'],r['max_drawdown']) for r in selected])
        for suffix in ('Day','Night'):
            periods[suffix] = {}
            for symbol in ('TOPIX','NK225'):
                selected = [r for r in rows if r['symbol']==symbol and r['session'].endswith(suffix)]
                periods[suffix][symbol] = accounting.aggregate(selected, [(r['curve_min'],r['curve_max'],r['max_drawdown']) for r in selected])
        path = HERE/'ledgers'/f'{config["id"]}.pkl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix('.tmp').open('wb') as stream:
            pickle.dump(ledgers, stream, protocol=5)
        path.with_suffix('.tmp').replace(path)
        save(HERE/'results'/f'{config["id"]}.json', dict(config=config, rows=rows, periods=periods,
            ledger_SHA256=sha(path), elapsed_seconds=time.monotonic()-started))
        print(config['id']+' 全30場完了', flush=True)
    validate(fixed)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='異なる三戦略の固定配分と同時運転')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--ids', default='')
    args = parser.parse_args()
    if args.freeze:
        freeze()
    if args.run:
        run([item for item in args.ids.split(',') if item])
