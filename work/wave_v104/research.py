"""同じ板の入口で支持境界と利益追尾を比べ、最大収益より毎場の損失を評価する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import gzip
import json
from pathlib import Path
import pickle
import socket

import numpy as np

import base
import catalog
import prepared_data


HERE = Path(__file__).resolve().parent
SYMBOLS = catalog.SYMBOLS


def save(path: Path, value: dict) -> None:
    """
    機能: 今回の新しい金融証跡だけを保存する。
    引数: path(Path)、value(dict)は保存位置と標準JSON内容。
    返り値: None。過去の成果と同名の証跡は上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def sources() -> dict:
    """
    機能: 金融実装、入口準備、独立人工、安定性基準を小さい直接証跡で結ぶ。
    引数: なし。
    返り値: dict[str,str]は内容指紋。巨大原本と旧全台帳は再走査しない。
    """
    names = ('research.py', 'base.py', 'catalog.py', 'prepared_data.py', '数値設計案.json',
        '安定性の採用基準補足.json', '入口準備前の固定.json', '入口準備の全32結果.json',
        'engine/core.py', 'engine/interface.py', 'engine/adapter.py', 'engine/old_finance_snapshot.py',
        'engine/19入口normalとO及び支持出口の結合人工.json',
        'engine/支持境界と利益保険及び予約順序の人工検査_結合接口.json',
        'engine/広追尾と長い保有及び未来不変の追加人工_結合接口.json',
        'review/正式準備と最終sourceの独立確認.json',
        'evaluation/assessment.py', 'evaluation/安定性採用判定の人工検査.json')
    paths = [HERE/name for name in names]
    dependencies = base.read(HERE/'入口準備の全32結果.json')['source_SHA256']
    paths += [base.ROOT/name for name in dependencies]
    paths += [base.ROOT/'work/wave_v102'/name for name in ('engine.py', 'strategy.py', 'accounting.py')]
    paths += [HERE/'engine'/'旧自己入口同出口の全32経済null.json']
    paths += sorted((HERE/'review').glob('*独立人工.json'))
    paths += [base.PREVIOUS/'金融全32の結果.json', base.PREVIOUS/'finance/results/OLD_G0.json',
              base.PREVIOUS/'research.py']
    return {str(path.relative_to(base.ROOT)): base.digest(path) for path in paths}


def freeze() -> None:
    """
    機能: 121条件と日々の損失を優先する採用規則を、新104損益前に固定する。
    引数: なし。
    返り値: None。入口の活動と旧同値検算を金融成果と混同しない。
    """
    assert not (HERE/'金融事前固定.json').exists() and not list((HERE/'finance').glob('**/*.json'))
    prepared = base.read(HERE/'入口準備の全32結果.json')
    assert prepared['全合格'] and prepared['新金融再生'] == 0 and prepared['対象場数'] == 32
    for name, wanted in prepared['source_SHA256'].items():
        assert base.digest(base.ROOT/name) == wanted, name
    null = base.read(HERE/'engine/旧自己入口同出口の全32経済null.json')
    assert null['全合格'] and null['口座数'] == 128
    assessment = base.read(HERE/'evaluation/安定性採用判定の人工検査.json')
    assert assessment['全合格'] and assessment['正式金融読取'] == 0
    review = base.read(HERE/'review/正式準備と最終sourceの独立確認.json')
    assert review['全合格']
    save(HERE/'金融事前固定.json', dict(全合格=True, sessions=prepared['sessions'], catalog=catalog.catalog(),
        primary=catalog.PRIMARY, assessment=base.read(HERE/'安定性の採用基準補足.json'),
        source_SHA256=sources(), 全32既知=True, 未知確認場数=0,
        正式新104金融再生=0, 旧同出口経済null口座数=128, 原本再抽出=0, 現在API=0, 実注文=0))
    print('121条件と日々の安定性を金融前に固定しました。', flush=True)


def ledger(path: Path, output: dict, entry_id: str | None, quantity: int, exit_id: str) -> str:
    """
    機能: 独立検算できる物理注文、全行時価、支持判断と当時根拠を保存する。
    引数: path(Path)、output(dict)、entry_id(str|None)、quantity(int)、exit_id(str)は保存内容。
    返り値: strは新しい圧縮台帳の指紋。名目幅を損失の上限と呼ばない。
    """
    assert not path.exists() and path.resolve().is_relative_to(HERE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    names = ('orders', 'order_columns', 'trades', 'trade_columns', 'events', 'event_columns',
        'stats', 'stat_columns', 'curve', 'source_curve', 'target_trace', 'trace_columns',
        'growth_cohorts', 'growth_cohort_columns', 'raw_entry_diagnostics')
    answer = {name: output[name] for name in names}
    for name in ('judgments', 'judgment_columns', 'candidate_diagnostics', 'candidate_columns',
                 'stale_equity', 'initial_width', 'wide_width', 'economics', 'risk_definition'):
        if name in output:
            answer[name] = output[name]
    answer.update(entry_id=entry_id, configured_quantity=quantity, exit_id=exit_id)
    with path.open('wb') as stream:
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0, compresslevel=3) as zipped:
            pickle.dump(answer, zipped, protocol=5)
    return base.digest(path)


def item(path: Path, fingerprint: str) -> dict:
    """
    機能: 台帳の位置と指紋を会計に結ぶ。
    引数: path(Path)、fingerprint(str)は今回の保存証跡。
    返り値: dictは位置とSHA256。
    """
    return dict(path=str(path.relative_to(base.ROOT)), SHA256=fingerprint)


def one_session(session: str, prepared: dict, cases: list[dict], old_rows: dict) -> dict:
    """
    機能: 全19入口を一場一回読み、6出口と実枚数による二腿配分を再生する。
    引数: session(str)、prepared/cases/old_rows(dict/list/dict)は固定した素材。
    返り値: dictは121会計と台帳指紋。追加枚数腿を配分間で再利用する。
    """
    packet = prepared_data.load_session(session)
    interface = base.module('104正式金融の共通接口', HERE/'engine/interface.py')
    accounting = base.module('104正式金融の不変会計', base.ROOT/'work/wave_v102/accounting.py')
    result = {config['id']: dict(rows=[], ledgers={}) for config in cases}
    extras = {}
    for symbol in SYMBOLS:
        key, value = (session, symbol), prepared[session, symbol]
        legs = {}
        for config in cases:
            ident = config['id']
            if config['kind'] == 'previous':
                result[ident]['rows'].append(deepcopy(old_rows[key]))
                continue
            exit_id = config['exit_id']
            if config['kind'] == 'portfolio':
                allocations = tuple(config['allocations'][symbol])
                for component, quantity in zip(config['components'], allocations, strict=True):
                    cache_key = (component, exit_id, quantity)
                    if cache_key not in legs:
                        output = interface.play(value, packet['cases'][component][symbol]['normal'], exit_id, quantity)
                        accounting.account(key, output)
                        path = HERE/'finance/legs'/f'{component}_{exit_id}_Q{quantity}'/(session+'_'+symbol+'.pkl.gz')
                        fingerprint = ledger(path, output, component, quantity, exit_id)
                        extras[symbol+'|'+component+'|'+exit_id+'|'+str(quantity)] = item(path, fingerprint)
                        legs[cache_key] = output
                output = interface.join({family: legs[component, exit_id, quantity]
                    for family, component, quantity in zip(('C', 'R'), config['components'], allocations, strict=True)},
                    allocations, symbol)
                entry_id, quantity = None, sum(allocations)
            else:
                entry_id, quantity = config['entry_id'], config['quantity'][symbol]
                output = interface.play(value, packet['cases'][entry_id][symbol]['normal'], exit_id, quantity)
            row = accounting.account(key, output)
            result[ident]['rows'].append(row)
            path = HERE/'finance/ledger'/ident/(session+'_'+symbol+'.pkl.gz')
            fingerprint = ledger(path, output, entry_id, quantity, exit_id)
            result[ident]['ledgers'][session+'|'+symbol] = item(path, fingerprint)
            del output
        del legs
    save(HERE/'finance/session'/(session+'.json'), dict(cases=result, extra_legs=extras))
    print(session+' 全121条件・追加24腿の会計を保存', flush=True)
    return dict(cases=result, extra_legs=extras)


def run(workers: int) -> None:
    """
    機能: 結果前に固定した121条件を全32で一度再生し、安定性判定へ接続する。
    引数: workers(int)は同時場数1又は2。
    返り値: None。無取引、少数例、最大勝ち依存、各商品別の悪化を保持する。
    """
    assert workers in (1, 2) and not (HERE/'金融全32の結果.json').exists()
    assert not list((HERE/'finance').glob('**/*.json'))
    fixed = base.read(HERE/'金融事前固定.json')
    assert fixed['全合格'] and fixed['source_SHA256'] == sources()
    cases, sessions = fixed['catalog'], fixed['sessions']
    old_rows = {(row['session'], row['symbol']): row
                for row in base.read(base.PREVIOUS/'finance/results/OLD_G0.json')['rows']}
    assert len(old_rows) == 64
    prepared = base.load_prepared()
    records = {key: value['reference_open'] for key, value in prepared.items()}
    # ----------------------------------------
    # 共有する部品の初回importを単一スレッドで済ませる。
    interface = base.module('104正式金融の共通接口', HERE/'engine/interface.py')
    interface.module('104最小執行の根条件', HERE/'catalog.py')
    interface.module('104の支持境界と利益追尾執行', HERE/'engine/core.py')
    old = interface.module('104専用の不変103金融snapshot', HERE/'engine/old_finance_snapshot.py')
    interface.module('104の不変103配分snapshot', HERE/'engine/adapter.py')
    old.adapter.module('103新入口の読取102固定出口', old.adapter.PREVIOUS/'engine.py')
    accounting = base.module('104正式金融の不変会計', base.ROOT/'work/wave_v102/accounting.py')
    previous = base.module('104の不変103安定性計測', base.PREVIOUS/'research.py')
    assessment = base.module('104正式金融の事前安定性判定', HERE/'evaluation/assessment.py')
    collected = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        jobs = {executor.submit(one_session, session, prepared, cases, old_rows): session for session in sessions}
        for job in as_completed(jobs):
            collected[jobs[job]] = job.result()
    assert len(collected) == 32 and fixed['source_SHA256'] == sources()
    outputs, summaries = {}, {}
    for config in cases:
        ident = config['id']
        rows = [row for session in sessions for row in collected[session]['cases'][ident]['rows']]
        ledgers = {key: value for session in sessions for key, value in collected[session]['cases'][ident]['ledgers'].items()}
        periods = {label: {symbol: accounting.aggregate(rows, symbol, selected) for symbol in SYMBOLS}
            for label, selected in (('前16', sessions[:16]), ('後16', sessions[16:]), ('全32', sessions))}
        output = dict(config=config, rows=rows, periods=periods, ledgers=ledgers,
            stability={label: previous.stability(rows, config, records, selected)
                for label, selected in (('前16', sessions[:16]), ('後16', sessions[16:]), ('全32', sessions))})
        path = HERE/'finance/results'/(ident+'.json')
        save(path, output)
        outputs[ident] = item(path, base.digest(path))
        summaries[ident] = output
    evaluation = assessment.assess(summaries)
    save(HERE/'安定性の全121判定.json', evaluation)
    extras = {session: collected[session]['extra_legs'] for session in sessions}
    save(HERE/'金融全32の結果.json', dict(全合格=True, sessions=sessions, 条件数=121, 掲載口座数=7744,
        既存対照参照口座数=64, 新単一口座数=7296, 実数量の追加腿再生口座数=768,
        配分合算掲載口座数=384, 新実数量再生合計=8064, results=outputs, extra_legs=extras,
        開始終端source一致=True, source_SHA256=sources(), 事前固定SHA256=base.digest(HERE/'金融事前固定.json'),
        安定性判定SHA256=base.digest(HERE/'安定性の全121判定.json'), 原本再抽出=0, 現在API=0, 実注文=0,
        全32既知=True, 未知確認場数=0, 主=catalog.PRIMARY, 独立金融監査='別に検査。完了するまで採用とは説明しない。'))
    print('全32の121条件を保存。独立金融監査へ渡します。', flush=True)


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 保存32場の研究から外部通信を拒否する。
    引数: args(tuple)、kwargs(dict)は通信引数。
    返り値: None。常に例外を送出する。
    """
    raise RuntimeError('保存データだけで検証します')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--freeze', action='store_true')
    choice.add_argument('--run', action='store_true')
    parser.add_argument('--workers', type=int, default=2)
    options = parser.parse_args()
    socket.create_connection = deny
    socket.socket.connect = deny
    freeze() if options.freeze else run(options.workers)
