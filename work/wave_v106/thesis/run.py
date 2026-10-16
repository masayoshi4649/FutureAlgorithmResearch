"""登録された12途中条件を全33場66商品期間で再運転する専用runner。"""

import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import traceback

import numpy as np

import data
import interface


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TRIAL_ID = '106_支持破れと相手逆進行の途中返済12対照'


def read(path: Path) -> dict:
    """
    機能: 小さな固定・登録・会計JSONを読む。
    引数: path(Path)は既存JSON。
    返り値: dictは保存値。原本やAPIは読まない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path: Path, value: dict) -> None:
    """
    機能: 新thesis金融領域に、既存資料を上書きせず結果を保存する。
    引数: path(Path)、value(dict)は新保存位置と結果。
    返り値: None。失敗時にも新しいFalse証跡を保持する。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                    encoding='utf-8', newline='\n')


def load_module(name: str, path: Path) -> object:
    """
    機能: 所有runnerへ不変の小会計関数を固有名で接続する。
    引数: name(str)、path(Path)はmodule識別子とsource。
    返り値: objectは読取り会計部品。旧engine/JITを実行しない。
    """
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def run(registry: Path) -> None:
    """
    機能: 登録・指紋を確認してから12×33×2の同原行経済再生を行う。
    引数: registry(Path)は根担当が登録を完了した試行正本。
    返り値: None。新金融は明示flagと登録済IDを両方要求する。
    """
    final = HERE/'finance/results.json'
    assert not final.exists() and not (HERE/'finance/失敗.json').exists()
    plan = read(HERE/'試行計画.json')
    assert plan['id'] == TRIAL_ID
    registered = read(registry)['trials']
    assert any(value['id'] == TRIAL_ID for value in registered), '試行の登録通知前です'
    for name, wanted in plan['spec']['implementation'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == wanted, name
    manifest = plan['spec']['data']['input_manifests'][0]
    assert hashlib.sha256((ROOT/manifest['path']).read_bytes()).hexdigest() == manifest['sha256']
    sessions = plan['spec']['data']['sessions']
    configs = read(HERE/'条件12.json')
    assert len(configs) == 12 and len(sessions) == 33
    original = read(ROOT/'work/wave_v106/finance/results.json')
    # ----------------------------------------
    # 根の不変会計を読む。共通moduleは同106の読取部品で、書込はこのrunnerが行う。
    common = load_module('common', ROOT/'work/wave_v106/common.py')
    accounting = load_module('106途中返済の独立会計', ROOT/'work/wave_v106/accounting.py')
    evaluation = load_module('106途中返済の安定性評価', ROOT/'work/wave_v106/evaluation.py')
    cases = {value['id']: dict(rows=[], ledgers={}) for value in configs}
    result = dict(全合格=False, sessions=sessions, configs=configs, cases=cases,
        trial_id=TRIAL_ID, account_count=0, unknown_sessions=0, current_API_reads=0,
        actual_orders=0, source_start=plan['spec']['implementation'], input_packet_reads=0)
    maps = {value['id']:{symbol:{} for symbol in ('TOPIX','NK225')} for value in configs}
    try:
        for session in sessions:
            packet = data.load_session(session)
            result['input_packet_reads'] += 1
            for config in configs:
                ident = config['id']
                for symbol in ('TOPIX','NK225'):
                    prepared = packet['prepared'][symbol]
                    record = prepared['record']
                    output = interface.play_session(packet, config, symbol)
                    row = accounting.inspect((session,symbol), record, output)
                    row['budget_unit'] = (output['initial_width'] * config['quantity'][symbol]
                                          * output['economics']['multiplier'])
                    cases[ident]['rows'].append(row)
                    maps[ident][symbol][session] = accounting.trade_map(output,record)
                    path = HERE/'finance/ledgers'/ident/(session+'_'+symbol+'.pkl.gz')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    assert not path.exists()
                    curve = output['curve']
                    changes = np.flatnonzero(np.r_[True,np.diff(curve)!=0])
                    ledger = {key:output[key] for key in ('orders','trades','growth_cohorts',
                        'growth_cohort_columns','thesis_judgments','thesis_columns',
                        'thesis_integer_keys','thesis_integer_columns','judgments','judgment_columns')}
                    ledger.update(row_count=len(curve), equity_change_rows=changes,
                                  equity_change_values=curve[changes])
                    saved = gzip.compress(pickle.dumps(ledger,protocol=5),compresslevel=2,mtime=0)
                    path.write_bytes(saved)
                    cases[ident]['ledgers'].setdefault(session,{})[symbol] = dict(
                        path=str(path.relative_to(ROOT)).replace('\\','/'),
                        SHA256=hashlib.sha256(saved).hexdigest())
                    result['account_count'] += 1
            del packet
            print(session+'：12途中返済条件の両商品再運転・会計を確認',flush=True)
        for ident, value in cases.items():
            value['summary'] = {symbol:evaluation.summarize(value['rows'],symbol,sessions)
                                for symbol in ('TOPIX','NK225')}
        combined = dict(cases)
        for base in ('C_OWN_B4','C_N30_B4','U_P10_B4'):
            combined[base] = original['cases'][base]
        result['evaluation'] = evaluation.assess(combined,sessions,'C_N30_B4')
        result['diagnosis'] = {}
        baseline_maps = {}
        for config in configs:
            ident, base = config['id'],config['base_id']
            result['diagnosis'][ident] = {}
            for symbol in ('TOPIX','NK225'):
                summed = dict.fromkeys(('収支変化','避けた基準損失','失った基準利益',
                    '共通入口の出口変化','新たな入口の収支'),0.)
                for session in sessions:
                    map_key = (base,symbol,session)
                    if map_key not in baseline_maps:
                        item = original['cases'][base]['ledgers'][session][symbol]
                        path = ROOT/item['path']
                        saved = path.read_bytes()
                        assert hashlib.sha256(saved).hexdigest() == item['SHA256']
                        legacy = pickle.loads(gzip.decompress(saved))
                        old_map = {}
                        for trade in legacy['trades']:
                            # 正式106のsave_ledgerが保存したtrade_detailsからseqを得る。
                            decision = int(trade[15])
                            diag = next(v for v in legacy['trade_details']
                                        if int(v['decision_row']) == decision)
                            key = str(int(diag['decision_seq']))+'|'+str(int(trade[4]))
                            assert key not in old_map
                            old_map[key] = dict(net=float(trade[11]), entry_row=int(trade[2]),
                                quantity=int(trade[5]),entry_price=float(trade[6]))
                        baseline_maps[map_key] = old_map
                    old_map = baseline_maps[map_key]
                    difference = accounting.contribution(old_map,maps[ident][symbol][session])
                    for key in summed:
                        summed[key] += difference[key]
                result['diagnosis'][ident][symbol] = summed
        for name, wanted in plan['spec']['implementation'].items():
            assert common.digest(ROOT/name) == wanted, name
        assert result['account_count'] == 12*33*2 and result['input_packet_reads'] == 33
        result.update(全合格=True, 開始終端source一致=True)
    except Exception as error:
        write(HERE/'finance/失敗.json',dict(result,失敗=str(error),traceback=traceback.format_exc()))
        raise
    write(final,result)
    print('12×66の途中返済結果完了',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='登録後の12途中条件だけを再運転する。')
    parser.add_argument('--root-thesis-trial-registered',action='store_true')
    parser.add_argument('--registry',type=Path,
        default=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    args = parser.parse_args()
    assert args.root_thesis_trial_registered, '重複試行登録と根の明示指示が必要です'
    run(args.registry)
