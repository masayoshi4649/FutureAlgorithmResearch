"""固定旧32場の自己入口と旧O出口を、完了103の注文及び会計へ同値検算する。"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import shutil
import socket
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WAVE = HERE.parent
ROOT = HERE.parents[2]
OUTPUT = HERE / '旧自己入口同出口の全32経済null.json'
STARTED = HERE / '旧自己入口同出口の全32経済null_開始.json'
PLAN = HERE / '旧自己入口同出口の全32経済null_計画.json'
ARTIFICIAL = HERE / '旧自己入口経済null比較器の人工検査.json'
ARRAYS = ('orders', 'trades', 'events', 'stats', 'curve', 'source_curve',
          'target_trace', 'growth_cohorts')
COLUMNS = ('order_columns', 'trade_columns', 'event_columns', 'stat_columns',
           'trace_columns', 'growth_cohort_columns')
SYMBOLS = ('TOPIX', 'NK225')
FAMILIES = ('C', 'R')


def load_module(name: str, path: Path) -> object:
    """
    機能: 読取部品を一つの固有名で接続する。
    引数: name(str)は識別名、path(Path)はソース位置。
    返り値: objectは接続した部品。旧ソースを変更しない。
    """
    if name not in sys.modules:
        specification = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(specification)
        sys.modules[name] = value
        specification.loader.exec_module(value)
    return sys.modules[name]


def digest(path: Path) -> str:
    """
    機能: 今回直接使用する小資料の内容指紋を読む。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。旧巨大原本の継承指紋を再走査しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    """
    機能: 日本語UTF-8の直接証跡を読む。
    引数: path(Path)はJSON位置。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 今回の証跡を既存資料へ上書きせず保存する。
    引数: path(Path)、value(dict)は新しい保存先と内容。
    返り値: None。保存範囲は104のengineだけに限定する。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8')


def compare(output: dict, previous: dict, row: dict, previous_row: dict) -> dict:
    """
    機能: 物理注文、全行時価、六列枠及び会計を許容誤差なしで比較する。
    引数: output/previous(dict)は新旧執行、row/previous_row(dict)は各口座会計。
    返り値: dictは比較対象ごとの要素数。追加された支持メタデータは経済比較へ混ぜない。
    """
    for name in ARRAYS:
        left, right = output[name], previous[name]
        assert isinstance(left, np.ndarray) and isinstance(right, np.ndarray), name
        assert left.dtype == right.dtype and left.shape == right.shape, name
        np.testing.assert_array_equal(left, right, err_msg=name)
    for name in COLUMNS:
        assert list(output[name]) == list(previous[name]), name
    assert row == previous_row, '口座会計'
    return {name: int(output[name].size) for name in ARRAYS}


def source_paths() -> list[Path]:
    """
    機能: 同値判定と直接入力の開始終端指紋に必要な資料を列挙する。
    引数: なし。
    返り値: list[Path]は現104及び読取103/102の小さい直接資料。
    """
    names = ('old_null.py', 'interface.py', 'core.py', 'adapter.py', 'old_finance_snapshot.py')
    paths = [HERE / name for name in names]
    paths += [WAVE / name for name in ('base.py', 'catalog.py', 'prepared_data.py',
        '入口準備前の固定.json', '入口準備の全32結果.json')]
    paths += [ROOT / 'work/wave_v103' / name for name in ('base.py', 'research.py',
        '金融全32の結果.json', '今回の入口反復と次の検証方針.json',
        'finance/results/C_OWN.json', 'finance/results/R_OWN.json')]
    paths += [ROOT / 'work/wave_v102' / name for name in ('engine.py', 'strategy.py', 'accounting.py')]
    dependencies = read(WAVE / '入口準備の全32結果.json')['source_SHA256']
    paths += [ROOT / name for name in dependencies]
    paths += [PLAN, ARTIFICIAL]
    return sorted(set(paths), key=lambda path: path.as_posix())


def fingerprints(paths: list[Path]) -> dict:
    """
    機能: 実際に使用する直接資料の現時点指紋を保存する。
    引数: paths(list[Path])は対象資料。
    返り値: dict[str,str]はプロジェクト相対位置とSHA256。
    """
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}


def artificial() -> None:
    """
    機能: 比較器が金額・方向・時価・枠・会計の違いを確実に拒否するか人工確認する。
    引数: なし。
    返り値: None。正式入力及び金融本体を読まず比較器だけを検査する。
    """
    assert not ARTIFICIAL.exists()
    original = {name: np.array([[1.0, np.nan], [2.0, 3.0]]) for name in ARRAYS}
    original.update({name: ['人工A', '人工B'] for name in COLUMNS})
    original['fixed_support_context'] = np.array([100.0, 101.0])
    row = dict(session='人工場', symbol='TOPIX', net=12.0, fees=82.0,
               cohorts=dict(lots=1, profit=12.0))
    assert compare(original, original, row, row)
    trials = 0
    for name in ARRAYS:
        for kind in ('値', '形状', '型'):
            changed = dict(original)
            changed[name] = original[name].copy()
            if kind == '値':
                changed[name][0, 0] += 1.0
            elif kind == '形状':
                changed[name] = changed[name][:1]
            else:
                changed[name] = changed[name].astype(np.float32)
            try:
                compare(changed, original, row, row)
            except AssertionError:
                trials += 1
            else:
                raise AssertionError(name + kind + 'の違いを見逃しました')
    for name in COLUMNS:
        changed = dict(original, **{name: ['人工A', '変更']})
        try:
            compare(changed, original, row, row)
        except AssertionError:
            trials += 1
        else:
            raise AssertionError(name + 'の列変更を見逃しました')
    try:
        compare(original, original, dict(row, fees=83.0), row)
    except AssertionError:
        trials += 1
    else:
        raise AssertionError('会計の違いを見逃しました')
    changed_metadata = dict(original, fixed_support_context=np.array([999.0, 999.0]))
    compare(changed_metadata, original, row, row)
    save(ARTIFICIAL, dict(全合格=True, 検査件数=dict(同値=2, 差異拒否=trials),
        source_SHA256=digest(Path(__file__)), 正式金融再生=0, 正式入力読取=0,
        説明='経済配列の型・形状・値及び口座会計をexact比較。支持メタデータ追加は経済同値とは分離。'))
    print('比較器の人工一致と差異拒否を保存しました。', flush=True)


def register() -> None:
    """
    機能: 根が指定した旧32及び128口座の同値範囲を再生前に登録する。
    引数: なし。
    返り値: None。正式入力は読まず完了103の固定場名だけを参照する。
    """
    assert not PLAN.exists() and read(ARTIFICIAL)['全合格']
    terminal = read(ROOT / 'work/wave_v103/金融全32の結果.json')
    sessions = terminal['sessions']
    assert terminal['全合格'] and len(sessions) == len(set(sessions)) == 32
    save(PLAN, dict(全合格=True, sessions=sessions, 商品=list(SYMBOLS), family=list(FAMILIES),
        旧条件=['C_OWN', 'R_OWN'], 新条件=['C_OWN_O', 'R_OWN_O'], 口座数=128,
        枚数=1, 出口='O：103不変のS/D/30分出口及び注文別料金',
        exact比較=list(ARRAYS) + list(COLUMNS) + ['口座会計'],
        追加支持及び入口metadata='経済nullと分離。原支持価格、自己相手lineageは新しい説明欄。',
        実行方針='根の入口準備32完了通知と一回128許可後にのみ実行。正常cache一場一読取、base一回。',
        旧32固定=True, 追加場読取=0, 新B及びT金融再生=0, 原本及びNPZ読取=0,
        現在API=0, 実注文=0, 原本継承指紋の再走査=0,
        旧結果SHA256=digest(ROOT / 'work/wave_v103/金融全32の結果.json'),
        比較器sourceSHA256=digest(Path(__file__)), 人工SHA256=digest(ARTIFICIAL)))
    print('旧32の128口座経済null計画を保存しました。', flush=True)


def run() -> None:
    """
    機能: 根が許可した128口座だけを一度旧Oで再生して完了103経済へ照合する。
    引数: なし。
    返り値: None。不一致時はFalseと実行sourceを保持し、自動再試行しない。
    """
    assert not OUTPUT.exists() and not STARTED.exists()
    plan = read(PLAN)
    metadata = read(WAVE / '入口準備の全32結果.json')
    assert metadata['全合格'] and metadata['対象場数'] == 32 and metadata['入口数'] == 19
    assert metadata['新金融再生'] == metadata['現在API'] == metadata['実注文'] == 0
    assert metadata['sessions'] == plan['sessions'] and plan['口座数'] == 128
    assert digest(Path(__file__)) == plan['比較器sourceSHA256']
    assert digest(ARTIFICIAL) == plan['人工SHA256']
    paths = source_paths()
    start = fingerprints(paths)
    save(STARTED, dict(開始UTC=datetime.now(timezone.utc).isoformat(), source_SHA256=start,
        対象場数=32, 口座数=128, 根許可='入口準備33712終端0後の旧128同出口のみ一回',
        新B及びT金融再生=0, API=0, 実注文=0))
    checked, ledger_hashes = [], {}
    completed = 0
    context = dict(session=None, symbol=None, family=None)
    try:
        # ----------------------------------------
        # rootのbase名を明示接続し、一度準備した旧正常素材を全128で再利用する。
        base = load_module('104旧nullの根base', WAVE / 'base.py')
        assert 'base' not in sys.modules or Path(sys.modules['base'].__file__).resolve() == (WAVE/'base.py').resolve()
        sys.modules['base'] = base
        prepared_data = load_module('104旧nullの入口cache', WAVE / 'prepared_data.py')
        interface = base.module('104旧nullの不変接口', HERE / 'interface.py')
        accounting = base.module('104旧nullの不変会計', ROOT / 'work/wave_v102/accounting.py')
        prepared = base.load_prepared()
        assert len(prepared) == 64
        terminal = read(ROOT / 'work/wave_v103/金融全32の結果.json')
        assert terminal['sessions'] == plan['sessions']
        references = {}
        for family in FAMILIES:
            item = terminal['results'][family + '_OWN']
            assert digest(ROOT / item['path']) == item['SHA256']
            value = read(ROOT / item['path'])
            assert len(value['rows']) == len(value['ledgers']) == 64
            assert value['config']['quantity'] == {'TOPIX': 1, 'NK225': 1}
            references[family] = dict(value=value,
                rows={(row['session'], row['symbol']): row for row in value['rows']})
        # ----------------------------------------
        # 新normalcacheと旧台帳をそれぞれ一度の同bytes照合で読み、支持出口は実行しない。
        for session in plan['sessions']:
            packet = prepared_data.load_session(session)
            for symbol in SYMBOLS:
                key = (session, symbol)
                for family in FAMILIES:
                    context = dict(session=session, symbol=symbol, family=family)
                    entry_id = family + '_OWN'
                    item = references[family]['value']['ledgers'][session + '|' + symbol]
                    path = ROOT / item['path']
                    assert path.resolve().is_relative_to((ROOT/'work/wave_v103/finance/ledger'/entry_id).resolve())
                    saved = path.read_bytes()
                    actual_sha = hashlib.sha256(saved).hexdigest()
                    assert actual_sha == item['SHA256'], str(path)
                    previous = pickle.loads(gzip.decompress(saved))
                    assert previous['configured_quantity'] == 1
                    output = interface.play(prepared[key], packet['cases'][entry_id][symbol]['normal'], 'O', 1)
                    row = accounting.account(key, output)
                    sizes = compare(output, previous, row, references[family]['rows'][key])
                    checked.append(dict(session=session, symbol=symbol, family=family,
                        新条件=entry_id+'_O', 旧条件=entry_id, 全比較一致=True,
                        要素数=sizes, 注文=len(output['orders']), 親=len(output['trades']),
                        玉群=len(output['growth_cohorts'])))
                    ledger_hashes[path.relative_to(ROOT).as_posix()] = actual_sha
                    completed += 1
                    del output, previous, saved
            del packet
            print(session + ' 4口座の注文・時価・会計が一致', flush=True)
        assert completed == 128
        end = fingerprints(paths)
        assert start == end
        save(OUTPUT, dict(全合格=True, 口座数=completed, 対象場数=32,
            sessions=plan['sessions'], 新条件=['C_OWN_O', 'R_OWN_O'], 旧条件=['C_OWN', 'R_OWN'],
            exact比較=list(ARRAYS) + list(COLUMNS) + ['口座会計'], 各口座=checked,
            開始終端source一致=True, source_SHA256=start, 終端source_SHA256=end,
            旧台帳SHA256=ledger_hashes, 入口cache一場読取=32, 旧共通base準備=1,
            旧O同値再生口座数=128, 新B及びT金融再生=0, 新121金融再生=0,
            追加場読取=0, 原本及びNPZ再読取=0, 原本継承指紋の再走査=0, 現在API=0, 実注文=0,
            支持metadataの扱い='支持価格、自己相手lineage、entry_case_id追加は経済比較対象から分離。'
                'O/B/T入口event/quality/resetの結合は別の結合人工で検査済み。',
            範囲='旧103自己入口と同O出口の実経済null。新支持出口の性能及び未知場を検証した証跡ではない。'))
        print('固定旧32の128口座経済nullが全て一致しました。', flush=True)
    except BaseException as error:
        folder = HERE / ('旧nullFalse_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        folder.mkdir()
        for path in (Path(__file__), HERE/'interface.py', HERE/'core.py'):
            shutil.copy2(path, folder / path.name)
        save(folder / '失敗.json', dict(全合格=False, 完了一致口座数=completed, 現在=context,
            exception_type=type(error).__name__, message=str(error), source_SHA256=start,
            計画SHA256=digest(PLAN), 開始SHA256=digest(STARTED), 各口座=checked,
            自動再試行=0, 新B及びT金融再生=0, 現在API=0, 実注文=0))
        raise


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 保存32場の経済nullから外部通信を拒否する。
    引数: args(tuple)、kwargs(dict)は通信引数。
    返り値: None。常に例外を送出する。
    """
    raise RuntimeError('保存資料だけで旧経済nullを検査します')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--artificial', action='store_true')
    choice.add_argument('--register', action='store_true')
    choice.add_argument('--root-preparation32-completed', action='store_true')
    options = parser.parse_args()
    socket.create_connection = deny
    socket.socket.connect = deny
    if options.artificial:
        artificial()
    elif options.register:
        register()
    else:
        run()
