"""旧保存スナップショットだけで現在照合経路を監査する。通信を強制遮断する。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import ast
import hashlib
import inspect
import json
from pathlib import Path
import pickle
import shutil
import socket
import sys
from types import ModuleType
import urllib.request

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD_LIVE = ROOT / 'work/wave_v23/live'
sys.path.insert(0, str(HERE))
import current_validation as current
import select_current as selection
import engine
import managers


def digest(path: Path) -> str:
    """機能: 読取専用でファイルの内容指紋を求める。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(root: Path) -> dict:
    """機能: 旧保存領域の全ファイルを監査用に指紋化する。

    引数: root (Path)。返り値: 相対パスと指紋 (dict)。
    """
    return {path.relative_to(root).as_posix(): digest(path) for path in root.rglob('*') if path.is_file()}


@contextmanager
def blocked_network(counter: list):
    """機能: 誤って通信経路を呼んだ場合も接続前に例外で止める。

    引数: counter (list) は拒否した呼出記録。返り値: コンテキスト管理器。
    """
    original_connect = socket.socket.connect
    original_connection = socket.create_connection
    original_open = urllib.request.OpenerDirector.open
    def denied(*args, **kwargs):
        """機能: 外部通信を拒否して試行を記録する。

        引数: args/kwargs (tuple/dict)。返り値: なし。必ず例外を送出する。
        """
        counter.append('通信経路が呼ばれたため遮断')
        raise AssertionError('offline検査では通信禁止')
    socket.socket.connect = denied
    socket.create_connection = denied
    urllib.request.OpenerDirector.open = denied
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_connection
        urllib.request.OpenerDirector.open = original_open


def technical_items() -> list[dict]:
    """機能: 成績を選ばず中期6主方向と3短期入口、旧比較実装を覆う。

    引数: なし。返り値: 技術検査専用の12条件 (list[dict])。
    """
    old = current.runner.read(current.PREVIOUS / '探索条件の固定.json')
    g = next(row for row in old['managers'] if row['id'] == 'G08')
    market = next(row for row in old['managers'] if row['id'] == 'G18')
    d = next(row for row in old['managers'] if row['id'] == 'D065')
    f = next(row for row in old['signals'] if row['id'] == 'F32')
    absorption = next(row for row in old['signals'] if row['id'] == 'D016')
    hierarchy = {value['id']: value for value in current.hierarchy_signals.catalog()}
    result = [{'id': '技術' + identifier, 'name': hierarchy[identifier]['name'],
               'signal': dict(hierarchy[identifier], 実装元='中期階層'), 'manager': market}
              for identifier in ('H000', 'H016', 'H032', 'H048', 'H064', 'H080', 'H035', 'H037', 'H039')]
    result += [{'id': '技術F32', 'name': '旧板経路', 'signal': dict(f, 実装元='既存板'), 'manager': g},
               {'id': '技術D016', 'name': '新板経路', 'signal': dict(absorption, 実装元='新規板'), 'manager': d},
               {'id': '技術P02', 'name': '価格経路', 'signal': dict(absorption, 実装元='価格P02'), 'manager': d}]
    return result


def fixture(items: list[dict], destination: Path) -> None:
    """機能: 旧17:25スナップショットを今回専用offline領域へ複写する。

    引数: items (list[dict])、destination (Path)。返り値: なし (None)。旧原本を変更しない。
    """
    destination.mkdir(parents=True, exist_ok=False)
    for directory in ('book', 'candle_1min', 'candle_5min', '応答原本'):
        shutil.copytree(OLD_LIVE / directory, destination / directory)
    shutil.copy2(OLD_LIVE / 'status.json', destination / 'status.json')
    converted = current.runner.read(OLD_LIVE / '足変換記録.json')
    for row in converted:
        relative = (ROOT / row['path']).relative_to(OLD_LIVE)
        row['path'] = (destination / relative).relative_to(ROOT).as_posix()
    current.runner.save(destination / '足変換記録.json', converted)
    record = current.runner.read(OLD_LIVE / '取得記録.json')
    for request in record['requests']:
        source = ROOT / request['path']
        relative = source.relative_to(OLD_LIVE)
        target = destination / relative
        assert digest(target) == request['sha256']
        request['path'] = target.relative_to(ROOT).as_posix()
    sources = [Path(current.__file__), Path(selection.__file__), current.HERE / 'hierarchy_signals.py',
               current.HERE / 'hierarchy_design_fixed.json',
               current.PREVIOUS / 'discovery_signals.py', current.PREVIOUS / 'd016_price_control.py']
    frozen = {'凍結時刻': datetime.now(current.JST).isoformat(), '主候補': None, '最終候補': items,
              'ファイルSHA256': {path.relative_to(ROOT).as_posix(): digest(path) for path in sources},
              '条件の再選択なし': True, '位置付け': '技術監査用に旧保存データを複写。新しい現在価格は取得していない。'}
    current.runner.save(destination / '現在照合の凍結記録.json', frozen)
    record['凍結記録SHA256'] = digest(destination / '現在照合の凍結記録.json')
    current.runner.save(destination / '取得記録.json', record)


def project_modules(starting: list[ModuleType]) -> list[str]:
    """機能: 動的別名も辿り、実際に読み込まれたプロジェクト内依存を列挙する。

    引数: starting (list[ModuleType])。返り値: ルート相対Pythonソース (list[str])。
    """
    stack, visited, paths = list(starting), set(), set()
    while stack:
        module = stack.pop()
        if id(module) in visited:
            continue
        visited.add(id(module))
        filename = getattr(module, '__file__', None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if not path.is_relative_to(ROOT) or path.suffix != '.py':
            continue
        paths.add(path.relative_to(ROOT).as_posix())
        stack.extend(value for value in vars(module).values() if isinstance(value, ModuleType))
    return sorted(paths)


def dependency_coverage(loaded: list[str]) -> dict:
    """機能: 通信関数のうち依存パス列挙だけを実行し、実ロードとの網羅性を検査する。

    引数: loaded (list[str])。返り値: 未収録の依存一覧 (dict)。取得・保存・通信部分は実行しない。
    """
    function = ast.parse(inspect.getsource(current.fetch_once)).body[0]
    nodes, started = [], False
    for node in function.body:
        names = [target.id for target in node.targets if isinstance(target, ast.Name)] if isinstance(node, ast.Assign) else []
        if not started and 'paths' in names:
            started = True
        if started and 'fixed' in names:
            break
        if started:
            nodes.append(node)
    assert nodes
    scope = dict(vars(current))
    expression = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(expression, '<依存パス列挙のみ>', 'exec'), scope)
    frozen = {path.resolve().relative_to(ROOT).as_posix() for path in scope['paths']}
    missing = sorted(set(loaded) - frozen)
    assert not missing, missing
    return {'実ロード数': len(loaded), '固定対象数': len(frozen), '未収録': missing}


def suffix_synthetic() -> dict:
    """機能: 境界前の建玉を保持したまま、17:25以後の時価差を独立に検算する。

    引数: なし。返り値: 架空末尾返済なしの境界会計監査 (dict)。
    """
    boundary = datetime.fromisoformat('2026-09-29T17:25:00+09:00').timestamp()
    stamps = boundary + np.array([-120., -60., -1., 0., 60., 120.])
    ready = {'time_s': stamps, 'last': np.array([100., 100., 110., 115., 113., 120.]),
             'atr': np.full(6, 20.), 'tick': .5, 'start': boundary - 1800., 'limit': boundary + 12 * 3600.,
             'us_open': boundary + 6 * 3600., 'symbol': 'TOPIX'}
    config = managers.make_config({'changes': {'entry_mode': 2}}, 'TOPIX', ready)
    result = engine.run(ready, np.ones(6, dtype=np.int8), config, True)
    partial = current.legacy.partial_accounting(ready, result, config)
    assert len(result['trades']) == 0 and partial['保有買い枚数'] == 1
    last_before = np.flatnonzero(stamps < boundary)[-1]
    start = result['curve'][last_before, 0]
    difference = (result['curve'][-1, 0] - start) * config['point_value']
    assert start == 10. and difference == 10000.
    assert partial['実現収支円'] == 0 and partial['含み損益円'] == 20000.
    return {'境界前時価損益円': start * config['point_value'], '境界以降差額円': difference,
            '未返済買い枚数': partial['保有買い枚数'], '実現収支円': partial['実現収支円'],
            '末尾含み損益円': partial['含み損益円'], '架空返済なし': True}


def no_primary_check(destination: Path, items: list[dict]) -> dict:
    """機能: 主候補未選定なら通信より前に取得を拒否することを隔離検査する。

    引数: destination (Path)、items (list[dict])。返り値: 拒否結果 (dict)。探索成果を読まない。
    """
    actual_read, actual_live = current.runner.read, current.LIVE
    def substituted(path: Path) -> object:
        """機能: 読取を主候補なしの模擬記録へ一時差替えする。

        引数: path (Path)。返り値: 模擬記録または元のファイル (object)。
        """
        if path == current.HERE / '現在照合候補の固定.json':
            return {'候補': items, '候補再選択禁止': True, '主候補': None}
        return actual_read(path)
    current.runner.read = substituted
    current.LIVE = destination / '主候補なし拒否検査'
    try:
        current.fetch_once(None)
        raise RuntimeError('主候補なしで取得を進めた')
    except AssertionError as error:
        assert '主候補がない' in str(error)
        return {'主候補なしを通信前に拒否': True, '理由': str(error)}
    finally:
        current.runner.read, current.LIVE = actual_read, actual_live


def saved_tampering_check(destination: Path, helper) -> dict:
    """機能: 複写領域だけを一時改変し、保存物の不一致を再生前に拒否するか調べる。

    引数: destination (Path)、helper (module)。返り値: 拒否した改変 (dict)。
    """
    probes = [destination / '現在照合の凍結記録.json', destination / 'book/TOPIX/2026-09-29_Night.jsonl',
              destination / 'candle_1min/TOPIX/2026-09-29_Night.csv']
    results = {}
    for path in probes:
        saved = path.read_bytes()
        rejected = False
        try:
            path.write_bytes(saved + b'\n')
            if path.suffix == '.csv':
                current.evaluate_saved(helper)
            else:
                current.verify_saved()
        except AssertionError:
            rejected = True
        finally:
            path.write_bytes(saved)
        results[path.relative_to(destination).as_posix()] = rejected
        assert rejected
    path = destination / '取得記録.json'
    saved = path.read_bytes()
    try:
        record = json.loads(saved)
        record['requests'][0]['path'] = (OLD_LIVE / 'status.json').relative_to(ROOT).as_posix()
        current.runner.save(path, record)
        try:
            current.verify_saved()
            raise RuntimeError('別保存領域への参照を受け入れた')
        except AssertionError:
            results['同じ内容でも旧保存領域を直接参照したら拒否'] = True
    finally:
        path.write_bytes(saved)
    current.verify_saved()
    return results


def main() -> None:
    """機能: 旧入力のみで四信号経路・保存再計算・途中会計・参照根を検査する。

    引数: なし。返り値: なし (None)。新規live領域と実通信には触れない。
    """
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    destination = HERE / 'current_offline_fixture' / stamp
    before = tree_hash(OLD_LIVE)
    attempts, candle_reads, hierarchy_reads = [], [], []
    original_read_csv = pd.read_csv
    root = current.LIVE
    source_sha = digest(Path(current.__file__))
    def audited_csv(path, *args, **kwargs):
        """機能: 足ファイル参照が今回の複写根だけに向くことを確認する。

        引数: path (Path|str)、args/kwargs (tuple/dict)。返り値: DataFrame。
        """
        target = Path(path).resolve()
        if 'candle_1min' in target.parts or 'candle_5min' in target.parts:
            candle_reads.append(target.relative_to(ROOT).as_posix())
            assert target.is_relative_to(destination.resolve()), f'足の根が違う: {target}'
            caller = inspect.currentframe().f_back
            if caller.f_globals.get('__name__') == current.hierarchy_signals.LEGACY.__name__:
                hierarchy_reads.append(target.relative_to(ROOT).as_posix())
        return original_read_csv(path, *args, **kwargs)
    with blocked_network(attempts):
        items = technical_items()
        fixture(items, destination)
        current.LIVE = destination
        current.SignalDispatcher.ROOT = destination
        pd.read_csv = audited_csv
        helper = current.legacy.load_module(ROOT / 'work/wave_v7/fetch_once.py', 'v27_offline_helper')
        helper.LIVE, helper.FROZEN = destination, destination / '現在照合の凍結記録.json'
        first = current.evaluate_saved(helper)
        first_replay = pickle.loads((destination / 'replay.pkl').read_bytes())
        first_inputs = pickle.loads((destination / 'inputs.pkl').read_bytes())
        second = current.evaluate_saved(helper)
        second_replay = pickle.loads((destination / 'replay.pkl').read_bytes())
        assert first['結果'] == second['結果']
        assert first['前回未読部分の増減'] == second['前回未読部分の増減']
        assert all(value['17時25分以降増減円'] == 0 for value in first['前回未読部分の増減'])
        for key in first_replay:
            for array in ('trades', 'orders', 'curve', 'cycles', 'stats'):
                np.testing.assert_array_equal(first_replay[key][array], second_replay[key][array])
        old_inputs = pickle.loads((OLD_LIVE / 'inputs.pkl').read_bytes())
        for key in first_inputs:
            for column in ('seq', 'time_s', 'last', 'atr'):
                np.testing.assert_array_equal(first_inputs[key][column], old_inputs[key][column])
        modules = project_modules([current, helper] + [value for key, value in sys.modules.items() if key.startswith('v23_current') and isinstance(value, ModuleType)])
        synthetic = suffix_synthetic()
        tamper_checks = saved_tampering_check(destination, helper)
        selection_check = no_primary_check(destination, items)
        assert len(set(hierarchy_reads)) == 2
        assert current.hierarchy_signals.ROOT == destination.resolve()
        assert current.hierarchy_signals.LEGACY.ROOT == destination.resolve()
        pd.read_csv = original_read_csv
        current.LIVE = root
    after = tree_hash(OLD_LIVE)
    assert before == after and not attempts
    result = {'対象': '旧2026-09-29_Nightの17:25までの保存物のみ。現在セッション再取得ではない。',
              '検査開始ソースSHA256': source_sha, '検査終了ソースSHA256': digest(Path(current.__file__)),
              '外部通信試行': attempts, '旧保存領域の全ファイル不変': True, '新規live取得なし': True,
              '複写先': destination.relative_to(ROOT).as_posix(), '検査条件数': len(items),
              '全銘柄条件数': len(items) * 2, '保存再実行完全一致': True,
              '再抽出のseq時刻価格ATRが旧入力と完全一致': True, '17時25分までの入力で以後差額0': True,
              '足読取は複写領域のみ': sorted(set(candle_reads)), '途中玉の合成会計': synthetic,
              '中期階層からの直接1分足参照': sorted(set(hierarchy_reads)),
              '保存物改変の拒否': tamper_checks,
              '主候補未選定時の取得拒否': selection_check, '実ロード依存': modules,
              '実ロード依存の凍結対象網羅': dependency_coverage(modules),
              '階層信号ROOT': str(current.hierarchy_signals.ROOT),
              '階層信号LEGACY_ROOT': str(current.hierarchy_signals.LEGACY.ROOT),
              '階層根の同期': True,
              '限界': '25分間の旧スナップショットでは長期EMA等の必要足数が足りず中立になる。成績評価ではなく経路・会計・根の技術監査。'}
    current.runner.save(HERE / 'current_offline_check.json', result)
    report = '''# 第３反復の現在照合・完全オフライン監査

重大な実装不一致は検出しなかった。旧2026-09-29ナイトの17:25までのスナップショットを別フォルダへ複写し、通信を強制遮断して実行した。新規の現在セッションデータを取得していない。

- 中期6主方向と短期入口3方式、固定比較3方式の計12条件×2銘柄を、同一プロセスで二度再抽出・再生した。seq・時刻・価格・ATR、注文・返済台帳・資産曲線が一致した。
- 中期階層のROOTとLEGACY.ROOTは複写先へ同期した。階層信号からの1分足読取りは両銘柄とも複写先だけを参照した。
- 凍結記録・原本板・変換足の改変、および旧保存フォルダへの参照変更を拒否した。旧保存物は全ファイルSHA不変。
- 旧スナップショットは17:25より前で終わるため、17:25以降の時価増減は全条件0。別の合成検算では、境界前に建てた1枚を保持したまま実現0円・末尾含み2万円・境界後増減1万円となり、末尾に架空の返済を追加しなかった。
- 主候補なしの模擬記録では、通信前に取得を拒否した。実際の探索成績や候補選択資料は本監査で参照していない。

25分の入力では長期EMA等の必要足数が不足する。これは収益性や指定波の適合検査ではなく、保存データに対する参照経路と会計の検査である。詳細な件数・ハッシュ・参照ファイルは current_offline_check.json を参照。
'''
    (HERE / 'current_offline_check.md').write_text(report, encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key not in ('実ロード依存', '足読取は複写領域のみ')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
