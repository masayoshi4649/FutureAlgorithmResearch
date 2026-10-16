"""三源の停止再開を、当時の仮想完了情報だけで全場検証する。"""

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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT/'work/wave_v88'
FIXED = HERE/'事前固定.json'
SOURCES = ('GU','M3','C03')


def module(name, path):
    """
    機能: 既存実装を固有名で読み、同名の研究モジュールの混入を防ぐ。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name,path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


accounting = module('wave89_previous_account',PREVIOUS/'accounting.py')
prepare = module('wave89_original_prepare',ROOT/'work/wave_v85/prepare.py')


def read(path):
    """
    機能: 日本語JSONを読み取る。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 原本と既存成果を変更せず内容指紋を計算する。
    引数: path(Path)。
    返り値: str。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda:stream.read(8*1024*1024),b''):
            value.update(part)
    return value.hexdigest()


def clean(value):
    """
    機能: NumPy数値をJSONへ保存できる同値の標準型へ変換する。
    引数: value(object)。
    返り値: object。
    """
    if isinstance(value,dict):
        return {key:clean(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):
        return [clean(item) for item in value]
    if isinstance(value,np.generic):
        return value.item()
    return value


def save(path, value):
    """
    機能: 今回の作業内へ有限値の日本語JSONを保存する。
    引数: path(Path)、value(dict又はlist)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    temporary.replace(path)


def inputs(verify=True):
    """
    機能: 完成済みの全30場入力と三源公開注文を変更せず参照する。
    引数: verify(bool)。
    返り値: tuple[dict,dict,dict]。
    """
    data, signals, hashes = prepare.load_inputs(verify=verify)
    path = PREVIOUS/'prepared/source_orders.pkl'
    previous = read(PREVIOUS/'事前固定.json')
    assert sha(path)==previous['code_SHA256'][str(path.relative_to(ROOT))]
    with path.open('rb') as stream:
        feeds = pickle.load(stream)
    assert set(feeds)==set(data) and len(data)==60
    assert sorted(p.stem for p in (ROOT/'book/NK225').glob('*.jsonl')) == previous['全30']
    assert sorted(p.stem for p in (ROOT/'book/TOPIX').glob('*.jsonl')) == previous['全30']
    assert hashes==previous['input_SHA256']
    return data,feeds,hashes


def references():
    """
    機能: 同配分の停止なし成果を会計比較専用に読み取る。
    引数: なし。
    返り値: dict。未来の親成績を売買判断へ渡さない。
    """
    out = {}
    for profile, config in catalog.PROFILES.items():
        identifier = config['reference_id']
        result = read(PREVIOUS/'results'/f'{identifier}.json')
        path = PREVIOUS/'ledgers'/f'{identifier}.pkl'
        assert sha(path)==result['ledger_SHA256']
        with path.open('rb') as stream:
            ledger = pickle.load(stream)
        out[profile] = result,ledger
    return out


def check_parent_subset(actual, baseline):
    """
    機能: 採用親の全実注文が停止なしと一致することを検算する。
    引数: actual/baseline(dict:会計台帳)。
    返り値: dict。金額差は別の事後診断で分解する。
    """
    parents = {(p['source'],p['cid']):p for p in actual['parents']}
    base = {(p['source'],p['cid']):p for p in baseline['parents']}
    assert set(parents)<=set(base)
    for key,parent in parents.items():
        for field in ('net','fees','gross','initial_qty','entry_row','exit_row'):
            assert abs(parent[field]-base[key][field])<1e-7
        s = SOURCES.index(key[0])
        a = actual['orders'][(actual['orders'][:,2]==s)&(actual['orders'][:,3]==key[1])]
        b = baseline['orders'][(baseline['orders'][:,2]==s)&(baseline['orders'][:,3]==key[1])]
        np.testing.assert_array_equal(a[:,:9],b[:,:9])
    return dict(採用親完全一致数=len(parents),元親数=len(base),元親にない新規=0)


def check_baseline():
    """
    機能: 新実装の停止なし三対照だけを旧全場成果と照合する。
    引数: なし。
    返り値: None。新しい停止条件の全場損益は計算しない。
    """
    data,feeds,hashes = inputs(verify=True)
    refs = references()
    strategy = module('wave89_source_strategy',HERE/'strategy.py')
    records = []
    for config in [c for c in catalog.catalog() if c['gate']['mode']=='all']:
        previous, baseline = refs[config['profile_id']]
        lookup = {(r['session'],r['symbol']):r for r in previous['rows']}
        for key in sorted(data):
            result = strategy.play(config,key,data[key],feeds)
            np.testing.assert_array_equal(result['orders'],baseline[key]['orders'])
            np.testing.assert_array_equal(result['target_trace'],baseline[key]['target_trace'])
            row,ledger,equity,parts = accounting.account(data[key],result)
            assert row=={name:value for name,value in lookup[key].items() if name!='config_id'}
            assert hashlib.sha256(equity.tobytes()).hexdigest()==baseline[key]['curve_SHA256']
            virtual = result['virtual_result']
            np.testing.assert_array_equal(virtual['orders'],baseline[key]['orders'])
            assert len(result['completion_records'])==row['campaigns']
            for completion in result['completion_records']:
                parent = next(p for p in ledger['parents'] if (p['source'],p['cid'])==(completion['source'],completion['cid']))
                assert completion['net']==parent['net'] and completion['fees']==parent['fees']
                assert completion['publish_row']>=parent['exit_row']
            records.append(dict(id=config['id'],session=key[0],symbol=key[1],全一致=True))
    save(HERE/'対照全180口座の完全一致.json',dict(全合格=True,口座数=len(records),各口座=records,入力SHA256=hashes,
        実装SHA256={str(p.relative_to(ROOT)):sha(p) for p in (HERE/'engine.py',HERE/'strategy.py',HERE/'catalog.py',HERE/'research.py')}))
    print('三停止なし対照、全180口座の注文・仮想親・全会計が旧結果と完全一致',flush=True)


def validate(fixed):
    """
    機能: 既存源と新規条件の固定内容指紋を確認する。
    引数: fixed(dict)。
    返り値: None。
    """
    assert fixed['catalog']==catalog.catalog() and fixed['specification']==catalog.specification()
    for name,digest in fixed['code_SHA256'].items():
        assert sha(ROOT/name)==digest,name


def freeze():
    """
    機能: 対照・独立人工・未来切断が済んだ81条件を損益前に固定する。
    引数: なし。
    返り値: None。
    """
    assert not FIXED.exists() and not (HERE/'results').exists()
    baseline = read(HERE/'対照全180口座の完全一致.json')
    audit = read(HERE/'audit/仮想完了ゲートの順序と全81条件の人工検査.json')
    prefixes = read(HERE/'audit/完了ゲート全81条件の実観測未来切断と将来成績毒入れ.json')
    assert baseline['全合格'] and audit['全合格'] and prefixes['全合格']
    previous = read(PREVIOUS/'事前固定.json')
    dependencies = dict(previous['code_SHA256'])
    for evidence in (baseline,audit,prefixes):
        for key,mapping in evidence.items():
            if 'SHA256' in key and isinstance(mapping,dict):
                for name,digest in mapping.items():
                    if isinstance(digest,str) and len(digest)==64 and (ROOT/name).is_file():
                        assert sha(ROOT/name)==digest,name
                        dependencies[name] = digest
    paths = list(HERE.glob('*.py'))+[HERE/'対照全180口座の完全一致.json']
    paths += list((HERE/'audit').glob('*.py'))+list((HERE/'audit').glob('*.json'))+list((HERE/'theory').glob('*.json'))
    dependencies.update({str(p.relative_to(ROOT)):sha(p) for p in paths})
    for config in catalog.PROFILES.values():
        for folder,suffix in (('results','.json'),('ledgers','.pkl')):
            path = PREVIOUS/folder/f'{config["reference_id"]}{suffix}'
            dependencies[str(path.relative_to(ROOT))] = sha(path)
    fixed = dict(catalog=catalog.catalog(),specification=catalog.specification(),code_SHA256=dependencies,
        input_SHA256=previous['input_SHA256'],全30=previous['全30'],前16=previous['前16'],後14=previous['後14'],全期間既知=True)
    validate(fixed)
    save(FIXED,fixed)
    print('仮想成績による参加停止再開の81条件を固定しました',flush=True)


def run(identifiers):
    """
    機能: 同時点までの独立仮想履歴を商品別に渡して、全保存場を再生する。
    引数: identifiers(list[str])。
    返り値: None。
    """
    fixed = read(FIXED)
    validate(fixed)
    data,feeds,hashes = inputs(verify=True)
    assert hashes==fixed['input_SHA256']
    refs = references()
    strategy = module('wave89_source_strategy',HERE/'strategy.py')
    configs = [c for c in fixed['catalog'] if not identifiers or c['id'] in identifiers]
    assert not identifiers or len(configs)==len(identifiers)
    for config in configs:
        started = time.monotonic()
        histories = {s:{name:[] for name in SOURCES} for s in ('TOPIX','NK225')}
        rows,ledgers = [],{}
        reference,base_ledgers = refs[config['profile_id']]
        for key in sorted(data):
            ready = data[key]
            result = strategy.play(config,key,ready,feeds,histories[key[1]])
            histories[key[1]] = result['history_out']
            np.testing.assert_array_equal(result['virtual_result']['orders'],base_ledgers[key]['orders'])
            np.testing.assert_array_equal(result['virtual_result']['target_trace'],base_ledgers[key]['target_trace'])
            row,ledger,equity,source_equity = accounting.account(ready,result)
            proof = check_parent_subset(ledger,base_ledgers[key])
            trace = [t for t in result['gate_trace'] if t['allocated_quantity']>0]
            row.update(config_id=config['id'],gate_eligible=len(trace),gate_allowed=int(sum(t['allowed'] for t in trace)),
                       gate_rejected=int(sum(not t['allowed'] for t in trace)),gate_warmup=int(sum(t['warmup'] for t in trace)),
                       virtual_campaigns=len(result['completion_records']))
            for item in trace:
                assert all(r['publish_time']<item['time'] for r in item['selected'])
            ledger.update(gate_trace=result['gate_trace'],completion_records=result['completion_records'],
                parent_subset_proof=proof,source_orders={s:feeds[key][s]['orders'] for s in SOURCES},
                curve_SHA256=hashlib.sha256(equity.tobytes()).hexdigest())
            rows.append(row);ledgers[key]=ledger
        periods = {}
        for period in ('前16','後14','全30','Day','Night'):
            periods[period] = {}
            for symbol in ('TOPIX','NK225'):
                selected = [r for r in rows if r['symbol']==symbol and (r['session'] in fixed[period] if period in fixed else r['session'].endswith(period))]
                stat = accounting.aggregate(selected,[(r['curve_min'],r['curve_max'],r['max_drawdown']) for r in selected])
                for name in ('gate_eligible','gate_allowed','gate_rejected','gate_warmup','virtual_campaigns'):
                    stat[name] = sum(r[name] for r in selected)
                periods[period][symbol] = stat
        path = HERE/'ledgers'/f'{config["id"]}.pkl'
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.with_suffix('.tmp').open('wb') as stream:
            pickle.dump(ledgers,stream,protocol=5)
        path.with_suffix('.tmp').replace(path)
        save(HERE/'results'/f'{config["id"]}.json',dict(config=config,rows=rows,periods=periods,ledger_SHA256=sha(path),elapsed_seconds=time.monotonic()-started))
        print(config['id']+' 全30場完了',flush=True)
    validate(fixed)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description='独立仮想成績による三源の参加停止再開')
    parser.add_argument('--check-baseline',action='store_true')
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--ids',default='')
    args = parser.parse_args()
    if args.check_baseline:
        check_baseline()
    if args.freeze:
        freeze()
    if args.run:
        run([identifier for identifier in args.ids.split(',') if identifier])
