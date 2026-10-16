"""板の定着・進行失敗の19条件を同じ出口で比較し、毎場の損失を評価する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pickle
import socket
import sys

import numba
import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
os.environ['NUMBA_CACHE_DIR'] = str(HERE/'engine/jit')
numba.config.CACHE_DIR = str(HERE/'engine/jit')


def module(name: str, path: Path) -> object:
    """
    機能: 確定済みの資料を固有名で接続する。
    引数: name(str)、path(Path)はモジュール名と読取位置。
    返り値: objectは接続部品。旧領域へ新しいキャッシュを書かない。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    answer = importlib.util.module_from_spec(spec)
    sys.modules[name] = answer
    spec.loader.exec_module(answer)
    os.environ['NUMBA_CACHE_DIR'] = str(HERE/'engine/jit')
    numba.config.CACHE_DIR = str(HERE/'engine/jit')
    return answer


def digest(path: Path) -> str:
    """
    機能: 直接依存又は新出力の内容を固定する。
    引数: path(Path)は小さい資料又は今回の台帳。
    返り値: strはSHA256。生原本を追加走査しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    """
    機能: UTF-8の固定定義又は会計を読む。
    引数: path(Path)はJSON資料。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def clean(value: object) -> object:
    """
    機能: NumPyの計測値を有限JSONへ変換する。
    引数: value(object)は計測値。
    返り値: objectは標準の辞書・列・数値。
    """
    if isinstance(value, dict):
        return {str(key): clean(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(child) for child in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def save(path: Path, value: dict) -> None:
    """
    機能: 今回の領域へ新しい証跡だけを保存する。
    引数: path(Path)、value(dict)は位置と保存内容。
    返り値: None。既存成果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def old_paths() -> list[Path]:
    """
    機能: 既検算済みG0の全32会計だけを参照する。
    引数: なし。
    返り値: list[Path]は前16・後15・追加1の三資料。
    """
    return [ROOT/'work/wave_v102'/part/'results/G0_Q1_X1.json'
            for part in ('front', 'back', 'holdout_results')]


def sources() -> dict:
    """
    機能: 新金融処理の直接実装と完了した入力・状態証跡を結ぶ。
    引数: なし。
    返り値: dict[str,str]は内容指紋。原本確認は入力v2の証跡へ委譲する。
    """
    names = ['research.py', 'base.py', 'catalog.py', '金融結果前の安定性評価.json',
        '数値設計草案.json', 'activity/全32の状態可用性と発火.json', 'activity/data.py',
        'engine/adapter.py', 'engine/finance_adapter.py', 'engine/states.py',
        'engine/活動normal投影と旧固定出口の金融接口人工検査_呼出統一.json',
        '金融前の実入力64口座の接続.json',
        'review/補足07独立入口と現source及びv2由来の金融前判定.json']
    paths = [HERE/name for name in names]
    paths += [HERE/f'数値設計補足{index:02d}.json' for index in range(1, 8)]
    paths += [ROOT/'work/wave_v102'/name for name in ('engine.py', 'strategy.py', 'accounting.py', 'catalog.py')]
    paths += old_paths()
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def freeze() -> None:
    """
    機能: 正式な新金融再生前に19条件と毎場安定性の評価を固定する。
    引数: なし。
    返り値: None。活動不足を既知の失敗として保持し、主を差し替えない。
    """
    assert not (HERE/'金融事前固定.json').exists()
    assert not list((HERE/'finance').glob('**/*.json'))
    activity = read(HERE/'activity/全32の状態可用性と発火.json')
    assert activity['全合格'] and activity['対象場数'] == 32 and activity['正式金融再生'] == 0
    cases = module('103金融の確定条件', HERE/'catalog.py').catalog()
    assert clean(cases) == activity['catalog'] and len(cases) == 19
    artificial = read(HERE/'engine/活動normal投影と旧固定出口の金融接口人工検査_呼出統一.json')
    assert artificial['全合格'] and artificial['全32金融再生'] == 0
    for relative, wanted in artificial['SHA256'].items():
        assert digest(ROOT/relative) == wanted, relative
    connected = read(HERE/'金融前の実入力64口座の接続.json')
    assert connected['全合格'] and connected['正式金融再生'] == 0
    assert connected['検査'] == dict(正常五列口座数=64, 単一及び主の接続数=960, 実配分数量の接続数=384)
    save(HERE/'金融事前固定.json', dict(全合格=True, sessions=activity['sessions'],
        catalog=cases, primary='U_C1R1', assessment=read(HERE/'金融結果前の安定性評価.json'),
        全32既知=True, 未知確認セッション数=0, source_SHA256=sources(),
        原本再抽出=0, API取得=0, 実注文=0, 正式新金融再生=0,
        接続証跡との根source差='接続検査後、並列起動前の部品事前読込を追加。connect/入口/出口/会計/数量契約の変更なし。',
        主の活動不足='U_C1R1は両商品7場11発火、受付内は全て売り。日々の安定条件に既に不足。結果で主を変更しない。'))
    print('19条件の金融事前固定を保存。無活動は成功に含めません。', flush=True)


def ledger(path: Path, output: dict, pulse_id: str | None, quantity: int) -> str:
    """
    機能: 物理注文・親・建玉・全行時価と実保有だけを独立検算用に保存する。
    引数: path(Path)、output(dict)、pulse_id(str|None)、quantity(int)は保存内容。
    返り値: strは圧縮台帳の指紋。出口の大きな内部診断は再保存しない。
    """
    assert not path.exists() and path.resolve().is_relative_to(HERE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    names = ('orders', 'order_columns', 'trades', 'trade_columns', 'events', 'event_columns',
        'stats', 'stat_columns', 'curve', 'source_curve', 'target_trace', 'trace_columns',
        'growth_cohorts', 'growth_cohort_columns', 'raw_entry_diagnostics')
    answer = {name: output[name] for name in names}
    answer.update(pulse_id=pulse_id, configured_quantity=quantity)
    with path.open('wb') as stream:
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0, compresslevel=3) as zipped:
            pickle.dump(answer, zipped, protocol=5)
    return digest(path)


def stability(rows: list[dict], config: dict, records: dict, sessions: list[str]) -> dict:
    """
    機能: 無取引を勝ちにせず、設定枚数による比較単位で毎場の損失を計測する。
    引数: rows(list[dict])、config/records(dict)、sessions(list[str])は会計と開始価格。
    返り値: dictは商品別の活動率・赤字頻度・下方偏差・最大赤字。
    """
    answer = {}
    for symbol in SYMBOLS:
        selected = [row for row in rows if row['symbol'] == symbol and row['session'] in sessions]
        active = [row for row in selected if row['campaigns'] > 0]
        red = [row for row in active if row['net'] < -1e-5]
        quantity = sum(config['allocations'][symbol]) if config['kind'] == 'portfolio' else config['quantity'][symbol]
        multiplier = 1000. if symbol == 'TOPIX' else 10.
        units = {row['session']: records[row['session'], symbol] * quantity * multiplier * .001 for row in selected}
        normalized = np.array([row['net']/units[row['session']] for row in active], float)
        best = max(selected, key=lambda row: row['net'], default=None)
        answer[symbol] = dict(session_count=len(selected), active_sessions=len(active),
            no_trade_sessions=len(selected)-len(active), positive_sessions=sum(row['net'] > 1e-5 for row in active),
            losing_sessions=len(red), flat_active_sessions=sum(abs(row['net']) <= 1e-5 for row in active),
            losing_active_rate=len(red)/len(active) if active else None,
            downside_rms_units=float(np.sqrt(np.mean(np.minimum(normalized, 0.)**2))) if active else None,
            worst_session_loss_yen=max((-row['net'] for row in red), default=0.),
            worst_session_loss_units=max((-row['net']/units[row['session']] for row in red), default=0.),
            mean_losing_session_yen=float(np.mean([-row['net'] for row in red])) if red else None,
            configured_quantity=quantity,
            activity_adequate=len(active) >= 16 and sum(row['campaigns'] for row in active) >= 20,
            best_session=best['session'] if best else None,
            without_best_session_net=sum(row['net'] for row in selected if best is None or row['session'] != best['session']))
    return answer


def one_session(session: str, prepared: dict, cases: list[dict], old_rows: dict) -> dict:
    """
    機能: 一場の同一活動cacheから全条件を再生し、枚数別の腿を再利用する。
    引数: session(str)、prepared(dict)、cases(list[dict])、old_rows(dict)は確定素材。
    返り値: dictは会計行と新台帳指紋。参照G0の注文を再実行しない。
    """
    activity = module('103金融の活動cache', HERE/'activity/data.py').load_session(session)
    finance = module('103金融の接続', HERE/'engine/finance_adapter.py')
    adapter = module('103金融の旧接続', HERE/'engine/adapter.py')
    accounting = module('103金融の会計', ROOT/'work/wave_v102/accounting.py')
    answer = {config['id']: dict(rows=[], ledgers={}) for config in cases}
    for symbol in SYMBOLS:
        key = (session, symbol)
        account, value = activity['accounts'][symbol], prepared[key]
        legs = {}
        for config in cases:
            ident = config['id']
            if config['kind'] == 'previous':
                answer[ident]['rows'].append(deepcopy(old_rows[key]))
                continue
            if config['kind'] == 'portfolio':
                allocation = tuple(config['allocations'][symbol])
                for component, quantity in zip(('C1', 'R1'), allocation, strict=True):
                    if (component, quantity) not in legs:
                        legs[component, quantity] = finance.play(value, account, component, quantity)
                output = adapter.join_portfolio_outputs(
                    {family: legs[family+'1', amount] for family, amount in zip(('C', 'R'), allocation)}, allocation, symbol)
                pulse_id, quantity = None, sum(allocation)
            else:
                quantity = config['quantity'][symbol]
                output = finance.play(value, account, ident, quantity)
                pulse_id = ident
            row = accounting.account(key, output)
            answer[ident]['rows'].append(row)
            path = HERE/'finance/ledger'/ident/(session+'_'+symbol+'.pkl.gz')
            fingerprint = ledger(path, output, pulse_id, quantity)
            answer[ident]['ledgers'][session+'|'+symbol] = dict(path=str(path.relative_to(ROOT)), SHA256=fingerprint)
            if config['kind'] != 'portfolio':
                del output
        del legs
    save(HERE/'finance/session'/(session+'.json'), answer)
    print(session+' 全19条件の費用後会計を保存', flush=True)
    return answer


def run(workers: int) -> None:
    """
    機能: 固定した全32金融再生を一度だけ実施する。
    引数: workers(int)は同時場数1又は2。
    返り値: None。台帳・全場会計・安定性を残し、目標未達を隠さない。
    """
    assert workers in (1, 2) and not (HERE/'金融全32の結果.json').exists()
    assert not list((HERE/'finance').glob('**/*.json'))
    fixed = read(HERE/'金融事前固定.json')
    assert fixed['全合格'] and fixed['source_SHA256'] == sources()
    cases, sessions = fixed['catalog'], fixed['sessions']
    old_rows = {}
    for path in old_paths():
        for row in read(path)['rows']:
            key = (row['session'], row['symbol'])
            assert key not in old_rows
            old_rows[key] = row
    assert len(old_rows) == 64
    material = module('103金融の開始素材', HERE/'base.py').load()
    assert material['metadata']['sessions'] == sessions
    adapter = module('103金融の旧接続', HERE/'engine/adapter.py')
    strategy = module('103金融の読取準備', ROOT/'work/wave_v102/strategy.py')
    prepared = strategy.prepare(material, adapter.reference_config())
    module('103金融の開始素材', HERE/'base.py').immutable(prepared)
    records = {key: value['reference_open'] for key, value in prepared.items()}
    # ----------------------------------------
    # 部品の初回接続を一スレッドで済ませ、未初期化objectの共有を避ける。
    module('103金融の活動cache', HERE/'activity/data.py')
    finance = module('103金融の接続', HERE/'engine/finance_adapter.py')
    module('103金融の会計', ROOT/'work/wave_v102/accounting.py')
    finance.adapter.module('103新入口の読取102固定出口', ROOT/'work/wave_v102/engine.py')
    collected = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        jobs = {executor.submit(one_session, session, prepared, cases, old_rows): session for session in sessions}
        for job in as_completed(jobs):
            collected[jobs[job]] = job.result()
    assert len(collected) == 32 and fixed['source_SHA256'] == sources()
    accounting = module('103金融の会計', ROOT/'work/wave_v102/accounting.py')
    outputs = {}
    for config in cases:
        ident = config['id']
        rows = [row for session in sessions for row in collected[session][ident]['rows']]
        ledgers = {key: item for session in sessions for key, item in collected[session][ident]['ledgers'].items()}
        periods = {label: {symbol: accounting.aggregate(rows, symbol, selected) for symbol in SYMBOLS}
                   for label, selected in (('前16', sessions[:16]), ('後16', sessions[16:]), ('全32', sessions))}
        output = dict(config=config, rows=rows, periods=periods,
            stability={label: stability(rows, config, records, selected)
                for label, selected in (('前16', sessions[:16]), ('後16', sessions[16:]), ('全32', sessions))},
            ledgers=ledgers)
        save(HERE/'finance/results'/(ident+'.json'), output)
        outputs[ident] = dict(path=str((HERE/'finance/results'/(ident+'.json')).relative_to(ROOT)),
            SHA256=digest(HERE/'finance/results'/(ident+'.json')))
    save(HERE/'金融全32の結果.json', dict(全合格=True, sessions=sessions, 条件数=19, 掲載口座数=1216,
        既存対照参照口座数=64, 新単一及びunion口座数=960, 実数量の配分腿再生口座数=384,
        配分合算掲載口座数=192, 新実数量再生合計=1344, results=outputs,
        開始終端source一致=True, source_SHA256=sources(),
        事前固定SHA256=digest(HERE/'金融事前固定.json'), 原本再抽出=0, API取得=0, 実注文=0,
        全32既知=True, 未知確認セッション数=0, 主='U_C1R1', 達成の判定='別の独立監査と安定性集計で行う'))
    print('全32の19条件を保存。主の活動不足もそのまま掲載します。', flush=True)


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 保存板の研究から外部通信を拒否する。
    引数: args(tuple)、kwargs(dict)は通信引数。
    返り値: None。必ず例外を送出する。
    """
    raise RuntimeError('保存済み32セッションだけを使用します')


def main() -> None:
    """
    機能: 結果前固定とレビュー後再生を分けて実行する。
    引数: CLI --freeze(bool)又は--run(bool)、--workers(int)。
    返り値: None。固定前に新金融再生を開始しない。
    """
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--freeze', action='store_true')
    choice.add_argument('--run', action='store_true')
    parser.add_argument('--workers', type=int, default=2)
    arguments = parser.parse_args()
    socket.create_connection = deny
    socket.socket.connect = deny
    freeze() if arguments.freeze else run(arguments.workers)


if __name__ == '__main__':
    main()
