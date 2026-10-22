"""正式登録後に追加七場だけを旧E01で準備し、十四実口座と旧六十六保存会計を統合する。"""

import argparse
from collections import Counter
import gc
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time
import traceback

import numpy as np

import adapter_v6 as adapter
import legacy_runtime
import plan_v6 as plan
from source_v6 import HERE, ROOT, MIRROR, SESSIONS, SYMBOLS, read, save, digest


RESULT_NAME = '少額E01固定二設定の追加七場と全四十場.json'


def guard(found: list[dict], fixed: dict, proposal: dict, meta: dict, current: dict) -> None:
    """
    機能: 実登録の八部品・入力・条件・実行源を原本初読の前に完全照合する。
    引数: found(list[dict])、fixed/proposal/meta/current(dict)は実登録と固定資料。
    返り値: None。不一致の実行を拒否し、過去の金融会計を変更しない。
    """
    assert len(found) == 1 and found[0]['id'] == proposal['id'] == plan.TRIAL
    assert found[0]['spec'] == proposal['spec']
    assert current == fixed['source_SHA256'] == proposal['spec']['implementation']
    expected_manifest = dict(path=(HERE/'入力目録.json').relative_to(ROOT).as_posix(), sha256=digest(HERE/'入力目録.json'))
    assert proposal['spec']['data']['input_manifests'] == [expected_manifest]
    assert fixed['input_manifest'] == expected_manifest
    assert meta['inputs'] == fixed['inputs'] == found[0]['spec']['data']['inputs']
    assert meta['sessions'] == fixed['sessions'] == found[0]['spec']['data']['sessions']
    assert len(meta['sessions']) == len(set(meta['sessions'])) == 40
    assert meta['new_sessions'] == fixed['new_sessions'] == list(SESSIONS)
    assert set(meta['old_sessions']).isdisjoint(SESSIONS) and len(meta['old_sessions']) == 33
    assert fixed['actual_config'] == meta['actual_config'] == adapter.ACTUAL == proposal['spec']['entry']['actual_config']
    assert fixed['counters'] == meta['counters'] == found[0]['spec']['data']['counters']
    assert len(meta['inputs']) == 42 and len({v['path'] for v in meta['inputs']}) == 42
    expected = {(scene, symbol, kind) for scene in SESSIONS for symbol in SYMBOLS
                for kind in ('book', 'candle_1min', 'candle_5min')}
    assert {(v['session'], v['symbol'], v['kind']) for v in meta['inputs']} == expected
    for item in meta['inputs']:
        ext = '.jsonl' if item['kind'] == 'book' else '.csv'
        assert item['path'] == f"{item['kind']}/{item['symbol']}/{item['session']}{ext}"
        assert len(item['SHA256']) == 64 and item['bytes'] > 0
    assert meta['old_reference'] == fixed['old_reference'] == proposal['spec']['data']['old_reference']
    assert digest(ROOT/meta['old_reference']['path']) == meta['old_reference']['SHA256']
    for relative, expected_sha in meta['fixed_metadata'].items():
        assert digest(MIRROR/relative) == expected_sha


def packet(path: Path, value: dict) -> dict:
    """
    機能: 今回所有の入力又は新十四台帳だけをgzip/pickleで保存する。
    引数: path(Path)、value(dict)は出力位置とデータ。
    返り値: dictは位置・SHA・bytes。既存cacheを上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    payload = gzip.compress(pickle.dumps(value, protocol=5), compresslevel=4, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return dict(path=path.relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))


def source_scope_guard(fixed_sources: dict) -> None:
    """
    機能: 全repo数値moduleの所有位置とJIT locatorを実行時にも確認する。
    引数: fixed_sources(dict[str,str])は正式固定された全Python源。
    返り値: None。旧sourceの直接実行又は旧cache保存先を拒否する。
    """
    from numba.core.registry import CPUDispatcher
    for value in tuple(sys.modules.values()):
        filename = getattr(value, '__file__', None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path.suffix != '.py' or not path.is_relative_to(ROOT/'work'):
            continue
        assert path.is_relative_to(HERE), ('所有域外module', str(path))
        assert path.relative_to(ROOT).as_posix() in fixed_sources, ('未固定module', str(path))
        for function in vars(value).values():
            if isinstance(function, CPUDispatcher):
                cache = getattr(function, '_cache', None)
                impl = getattr(cache, '_impl', None)
                locator = getattr(impl, '_locator', None)
                if locator is not None:
                    assert Path(locator._cache_path).resolve().is_relative_to(HERE), str(locator._cache_path)


def normalize_orders(result: dict, account: dict) -> list[dict]:
    """
    機能: 実注文の原seq・価格時計・BBO・料金・UIDを小金融結果にも保存する。
    引数: result/account(dict)は完成実政策と同じ入力。
    返り値: list[dict]は各実注文の保存値。未来fillを補完しない。
    """
    rows = []
    for index, order in enumerate(result['orders']):
        row = int(order[0])
        rows.append(dict(index=index, order=order.tolist(), uid=int(result['order_uids'][index]),
            fee=int(result['order_fees'][index]), raw_seq=int(account['record']['seq'][row]),
            price_time_s=float(account['record']['time_s'][row]), bid=float(account['quotes']['bid'][row]),
            ask=float(account['quotes']['ask'][row]), quote_valid=bool(account['quotes']['quote_valid'][row])))
    return rows


def execute() -> None:
    """
    機能: 根の実登録後に既stageだけで高水位資格表示→旧E01生成→十四金融を行う。
    引数: なし。根担当の--root-runが必要。
    返り値: None。旧33口座の金融・旧比較の再金融は一切実行しない。
    """
    fixed = read(HERE/'固定計画.json')
    proposal = read(HERE/'試行計画.json')
    meta = read(HERE/'入力目録.json')
    checked = read(HERE/'正式照合の全出力.json')
    registered = read(HERE/'正式登録の全出力.json')
    assert checked['終了コード'] == registered['終了コード'] == 0
    assert json.loads(checked['stdout'])['proposal_complete'] is True
    enrolled = json.loads(registered['stdout'])
    before = plan.sources()
    guard([enrolled], fixed, proposal, meta, before)
    assert not (HERE/'measurement').exists() and not (HERE/'実行開始.json').exists()
    save(HERE/'実行開始.json', dict(開始=time.time(), source_SHA256=before, 原本初読前=True,
        新金融予定=14, 旧保存会計引用=66, 原本予定=0, 既stage使用予定=42, 再実行不可=True))
    counter = Counter()
    read_log, new_rows, details, caches, input_diagnostics = [], [], [], {}, {}
    try:
        read_log = adapter.stage_raw(meta)
        counter.update(既stagebook一読=14, 既stage1分CSV一読=14, 既stage5分CSV一読=14)
        save(HERE/'原本の一回複写履歴.json', dict(全合格=True, read_log=read_log, 原本追加走査=0,
            初回='119fで原本42をstage済み、新金融0で中断。hではその保存copyだけを使う。',
            備考='bookは原seq保持で不適格時計をNone表示。CSVは同bytes。raw44票は未加工のf stageから抽出。'))
        with legacy_runtime.isolated(discover=False):
            rt = legacy_runtime.runtime()
            modules = adapter.engine_modules()
            source_scope_guard(before)
            selected = adapter.selected_configs(modules)
            assert {s:c['id'] for s,c in selected.items()} == adapter.ACTUAL
            for scene in SESSIONS:
                folder = MIRROR/'work/v6_prepared'/scene
                folder.mkdir(parents=True, exist_ok=False)
                rt['extractor'].HERE = folder
                ready_inputs, depth_features = rt['extractor'].extract(scene)
                signals = rt['extractor'].signal_audit(ready_inputs, depth_features)
                assert read(folder/'信号監査.json')['全合格']
                features = legacy_runtime.inject(rt, ready_inputs, signals)
                assert set(features) == set(ready_inputs) == {(scene, s) for s in SYMBOLS}
                for symbol in SYMBOLS:
                    key = scene, symbol
                    with np.load(folder/'features'/f'約定系列_{symbol}_{scene}.npz', allow_pickle=False) as saved:
                        tape = {k:saved[k] for k in saved.files}
                    ready = ready_inputs[key]
                    quotes = adapter.quote_mapping(ready, tape)
                    account, diagnosis = adapter.make_account(rt, scene, symbol, ready, quotes, features[key])
                    source_scope_guard(before)
                    counter.update(新E01紙上口座=1)
                    input_meta = packet(folder/(symbol+'_00106入力.pkl.gz'), account)
                    raw = modules['interface'].execute(account, selected[symbol]['entry_id'], selected[symbol]['execution_id'])
                    context = modules['interface'].prepared(scene, account, raw['values'], finish=True)
                    result = modules['interface'].apply(context, selected[symbol], raw['gate'], fak_events=raw['fak_events'])
                    assert result['summary']['全会計合格']
                    assert not result['long_qty'][-1] and not result['short_qty'][-1]
                    row = adapter.account_row(scene, symbol, result)
                    assert np.isclose(row['profit']-row['loss'], row['net'], atol=1e-5, rtol=1e-12)
                    output_meta = packet(HERE/'measurement/ledger'/symbol/(scene+'.pkl.gz'), result)
                    new_rows.append(row)
                    details.append(adapter.primitive(dict(session=scene, symbol=symbol, actual_config=adapter.ACTUAL[symbol],
                        summary=result['summary'], goal_anchor=result['goal_anchor'], exit_boundary=result['exit_boundary'],
                        control=result['control'], parent=result['parent'], actual_legs=result['actual_legs'],
                        uid_accounts=result['uid_accounts'], orders=normalize_orders(result, account),
                        gate_diagnostics=raw['gate']['diagnostics'], fak_columns=result['fak_columns'],
                        fak_events=result['fak_events'], cache=output_meta)))
                    caches[scene+'|'+symbol] = dict(input=input_meta, ledger=output_meta)
                    input_diagnostics[scene+'|'+symbol] = adapter.primitive(diagnosis)
                    counter.update(新実GU=1, 新実政策会計=1)
                del ready_inputs, depth_features, signals, features
                gc.collect()
                print(scene+' 旧固定二設定の追加二会計完了', flush=True)
        old, old_ref = adapter.old_rows()
        assert old_ref == meta['old_reference']
        rows = old + new_rows
        assert len(rows) == len({(v['session'],v['symbol']) for v in rows}) == 80
        assert len(new_rows) == 14 and len(old) == 66
        assert counter == Counter(既stagebook一読=14,既stage1分CSV一読=14,既stage5分CSV一読=14,
                                  新E01紙上口座=14,新実GU=14,新実政策会計=14)
        after = plan.sources()
        assert before == after
        metrics = {}
        for symbol in SYMBOLS:
            own = [v for v in rows if v['symbol']==symbol]
            metrics[symbol] = {name:adapter.metrics([v for v in own if v['session'] in scenes])
                for name,scenes in (('全40',meta['sessions']),('旧33',meta['old_sessions']),('追加7',list(SESSIONS)))}
        output = dict(全合格=True, trial=plan.TRIAL, method=adapter.METHOD, actual_config=adapter.ACTUAL,
            sessions=meta['sessions'], old_sessions=meta['old_sessions'], new_sessions=list(SESSIONS),
            rows=rows, metrics=metrics, old_rows=old, old_reference=old_ref, new_accounts=details,
            cache=caches, input_diagnostics=input_diagnostics, read_log=read_log, input_clock_qualification={k:v['clock_qualification'] for k,v in input_diagnostics.items()}, stopped_trial=meta['stopped_trial'], clock_contract=meta['clock_contract'],期間差=meta['期間差'],
            counters=dict(counter), raw_reads=0, new_actual_accounts=14, reused_accounting=66,
            inherited_original_reads=42, old_financial_rerun=0, old_comparison_rerun=0,
            source_SHA256=before, source_end_SHA256=after, unclosed_new=0,
            留保=['旧保存66行を新たな金融標本へ数えない。旧33と追加7の入力資格は異なる。', '旧33の未保存親個別経路等は補完しない。',
                  '全40場は既知開発であり、旧目標解除が有効性の新証拠を作る訳ではない。',
                  'ラージ気配代理。小型の実板・受信順・待ち順位の物理約定証明はない。'])
        save(HERE/'measurement'/RESULT_NAME, adapter.primitive(output))
        print('追加14新会計＋旧66引用＝80会計完了、旧33再金融0。', flush=True)
    except BaseException:
        save(HERE/'実行False.json', dict(全合格=False, traceback=traceback.format_exc(), counters=dict(counter),
            read_log=read_log, 新会計完了数=len(new_rows), 再実行不可=True, 元sourceを変更しない=True))
        raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='根の正式登録後だけ追加十四口座を旧E01で運転する')
    parser.add_argument('--root-run',action='store_true')
    args=parser.parse_args()
    assert args.root_run
    execute()
