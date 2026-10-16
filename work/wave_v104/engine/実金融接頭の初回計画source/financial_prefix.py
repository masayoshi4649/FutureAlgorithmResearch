"""正式B/Tの先頭六親を、未来の場末清算をしない原行接頭だけで確認する。"""

import argparse
from copy import deepcopy
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
CASES = ('C_OWN_B2', 'C_OWN_T2', 'U_P10_T2')
SYMBOLS = ('TOPIX', 'NK225')
FUTURES = ('将来気配価格', '将来価格時計', '将来入口資格とreset',
           '将来eventと当時台帳', '将来supportと当時台帳', '将来全部組合せ')
PLAN = HERE / '実金融の先頭6親と接頭不変_計画.json'
ARTIFICIAL = HERE / '実金融接頭helperの人工検査.json'
SELECTION = HERE / '実金融の先頭6親_固定対象.json'
STARTED = HERE / '実金融の先頭6親と接頭不変_開始.json'
OUTPUT = HERE / '実金融の先頭6親と接頭不変.json'
SPARSE = dict(orders=0, trades=3, growth_cohorts=14, events=0,
              judgments=0, candidate_diagnostics=0)
DENSE = ('curve', 'source_curve', 'target_trace', 'stale_equity')
COLUMNS = ('order_columns', 'trade_columns', 'growth_cohort_columns', 'event_columns',
           'trace_columns', 'judgment_columns', 'candidate_columns')


def module(name: str, path: Path) -> object:
    """
    機能: 読取部品を固定したcanonical名で一度だけ接続する。
    引数: name(str)は識別名、path(Path)はソース位置。
    返り値: objectは読取部品。旧領域へキャッシュを書き込まない。
    """
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
    return sys.modules[name]


def read(path: Path) -> dict:
    """
    機能: 日本語UTF-8の直接資料を読む。
    引数: path(Path)はJSON位置。
    返り値: dictは資料内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 現sourceと直接使用証跡のSHA256を読む。
    引数: path(Path)は今回の直接資料。
    返り値: strは内容指紋。巨大原本の継承指紋を二重走査しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 新しい検査証跡だけを104engineへ保存する。
    引数: path(Path)、value(dict)は保存位置と内容。
    返り値: None。既存のFalse及びgreenを上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def immutable(value: object) -> None:
    """
    機能: 部分素材も正式再生と同じ読取専用配列資格へ固定する。
    引数: value(object)は辞書・列・配列。
    返り値: None。JIT型及び保存済み素材の不変性を保つ。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            immutable(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            immutable(child)


def equal(first: object, second: object, context: str) -> None:
    """
    機能: 入れ子の当時lineageも許容誤差なしで比較する。
    引数: first/second(object)は比較値、context(str)は検査位置。
    返り値: None。浮動小数のNaN同位置以外を救済しない。
    """
    if isinstance(first, np.ndarray) or isinstance(second, np.ndarray):
        assert isinstance(first, np.ndarray) and isinstance(second, np.ndarray), context
        assert first.dtype == second.dtype and first.shape == second.shape, context
        np.testing.assert_array_equal(first, second, err_msg=context)
    elif isinstance(first, dict) or isinstance(second, dict):
        assert isinstance(first, dict) and isinstance(second, dict) and first.keys() == second.keys(), context
        for name in first:
            equal(first[name], second[name], context + '/' + str(name))
    elif isinstance(first, (list, tuple)) or isinstance(second, (list, tuple)):
        assert isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)), context
        assert len(first) == len(second), context
        for row, (left, right) in enumerate(zip(first, second, strict=True)):
            equal(left, right, context + '/' + str(row))
    elif isinstance(first, (float, np.floating)) and isinstance(second, (float, np.floating)):
        assert first == second or (np.isnan(first) and np.isnan(second)), context
    else:
        assert first == second, context


def prefix(prepared: dict, case: dict, length: int) -> tuple[dict, dict]:
    """
    機能: 正常原行、旧共通信号、原行map及び当時台帳を同じ長さで切る。
    引数: prepared/case(dict)、length(int)は正常行接頭の長さ。
    返り値: tuple[dict,dict]は読取専用の接頭。既知start/limitは変更せず端点清算しない。
    """
    n = len(prepared['record']['time_s'])
    assert 0 < length <= n
    record = {name: np.ascontiguousarray(value[:length])
        if isinstance(value, np.ndarray) and value.ndim and len(value) == n else value
        for name, value in prepared['record'].items()}
    old = prepared['signal']
    grid_length = len(old['grid'])
    grid_cut = int(np.searchsorted(old['grid'], record['time_s'][-1], side='right'))
    signal = {}
    for name, value in old.items():
        if isinstance(value, np.ndarray) and value.ndim:
            if len(value) == n:
                value = np.ascontiguousarray(value[:length])
            elif len(value) == grid_length:
                value = np.ascontiguousarray(value[:grid_cut])
        signal[name] = value
    material = dict(prepared, record=record, signal=signal)
    small = {name: np.ascontiguousarray(value[:length])
        if isinstance(value, np.ndarray) and value.ndim and len(value) == n else value
        for name, value in case.items() if name not in ('decisions', 'legacy_account')}
    small['decisions'] = [row for row in case['decisions'] if int(row['row']) < length]
    immutable(material)
    immutable(small)
    return material, small


def expected(full: dict, length: int) -> dict:
    """
    機能: 正式台帳から当該接頭に既に実現した物理出力を選ぶ。
    引数: full(dict)は保存された正式出力、length(int)は正常原行の接頭長。
    返り値: dictは比較対象。full最終statsは未来全場値なので接頭比較に用いない。
    """
    answer = {name: full[name][full[name][:, row_column] < length] for name, row_column in SPARSE.items()}
    answer.update({name: full[name][:length] for name in DENSE})
    answer.update({name: full[name] for name in COLUMNS})
    answer['raw_entry_diagnostics'] = [row for row in full['raw_entry_diagnostics'] if int(row['fill_row']) < length]
    return answer


def compare(output: dict, wanted: dict) -> dict:
    """
    機能: 注文・親・玉・全時価・枠・判断及びlineageの接頭同値を確認する。
    引数: output/wanted(dict)は接頭再生と正式接頭。
    返り値: dict[str,int]は各出力の検査要素数。正式未来の損益を再計算しない。
    """
    for name in tuple(SPARSE) + DENSE + COLUMNS + ('raw_entry_diagnostics',):
        equal(output[name], wanted[name], name)
    return {name: int(output[name].size) for name in tuple(SPARSE) + DENSE}


def change_future(prepared: dict, case: dict, length: int, kind: str) -> tuple[dict, dict, dict]:
    """
    機能: 切断より後の気配・時計・入口情報だけを六種類の反例へ変更する。
    引数: prepared/case(dict)は完全素材、length(int)は接頭長、kind(str)は固定改変種別。
    返り値: tuple[dict,dict,dict]は改変素材と件数。将来部分の金融を再生しない。
    """
    assert kind in FUTURES
    n = len(prepared['record']['time_s'])
    assert length < n, '切断後の未来原行が存在しません'
    record = dict(prepared['record'])
    changed = {name: value for name, value in case.items() if name != 'legacy_account'}
    details = dict(未来正常行数=n-length, 価格列=0, 入口列=0, future_decisions=0)
    selected = FUTURES[:-1] if kind == FUTURES[-1] else (kind,)
    if FUTURES[0] in selected:
        for name in ('bid', 'ask', 'price'):
            if name in record:
                value = record[name].copy()
                value[length:] += float(record['tick']) * 101
                record[name] = value
                details['価格列'] += 1
    if FUTURES[1] in selected:
        value = record['time_s'].copy()
        value[length:] = np.nan
        record['time_s'] = value
        details['価格列'] += 1
    if FUTURES[2] in selected:
        for name in ('entry_quality', 'entry_reset'):
            value = changed[name].copy()
            value[length:] = ~value[length:]
            changed[name] = value
            details['入口列'] += 1
    if FUTURES[3] in selected:
        event = changed['event'].copy()
        support = changed['support_price'].copy()
        event[length:] = 0
        at = min(n-1, length+1)
        side = -int(case['event'][np.flatnonzero(case['event'])[0]]) if case['event'].any() else -1
        event[at], support[at] = side, float(prepared['record']['bid'][at])
        changed['event'], changed['support_price'] = event, support
        changed['decisions'] = [row for row in case['decisions'] if int(row['row']) < length]
        changed['decisions'].append(dict(row=at, normal_row=at,
            raw_row=int(case['execution_to_raw_index'][at]), raw_seq=int(prepared['record']['seq'][at]),
            side=side, support_price=float(support[at]),
            self_lineages=[dict(family='未来反例だけ', anchor_raw_seq=int(prepared['record']['seq'][at]))]))
        details['入口列'] += 2
        details['future_decisions'] = 1
    if FUTURES[4] in selected:
        support = changed['support_price'].copy()
        support[length:] = float(prepared['record']['bid'][length]) + float(record['tick']) * 203
        changed['support_price'] = support
        changed['decisions'] = [dict(row, support_price=float(support[int(row['row'])]))
            if int(row['row']) >= length else row for row in changed['decisions']]
        details['入口列'] += 1
    material = dict(prepared, record=record)
    immutable(material)
    immutable(changed)
    return material, changed, details


def artificial() -> None:
    """
    機能: 人工買売及び予約・保有・返済接頭でhelperの切断と未来分離を検査する。
    引数: なし。
    返り値: None。正式104金融結果、原本、NPZ及び活動cacheを読まない。
    """
    assert not ARTIFICIAL.exists()
    interface = module('104正式金融の共通接口', HERE/'interface.py')
    assert 'interface' not in sys.modules or Path(sys.modules['interface'].__file__).resolve() == (HERE/'interface.py').resolve()
    sys.modules['interface'] = interface
    fixtures = module('104金融接頭helperの人工factory', HERE/'artificial.py')
    paths = [Path(__file__), HERE/'interface.py', HERE/'core.py', HERE/'artificial.py', WAVE/'catalog.py']
    start = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    counts = dict(買売完結例=0, 予約保有返済接頭=0, 接頭未来改変=0, 比較器差異拒否=0,
                  原行map切断=0, JIT読取専用資格=0)
    for symbol in SYMBOLS:
        for side in (1, -1):
            for exit_id, entry_id in (('B2', 'C_OWN'), ('T2', 'C_OWN'), ('T2', 'U_P10')):
                material, case = fixtures.fixture(symbol, side, entry_id)
                case['execution_to_raw_index'] = np.arange(len(case['event']), dtype=np.int64)*2+7
                fixtures.refresh(case, material['record'])
                tick = float(material['record']['tick'])
                if exit_id == 'B2':
                    fixtures.quote_from(material, 340, float(case['support_price'][330])-side*2*tick, side)
                else:
                    entry = float(material['record']['ask'][331] if side == 1 else material['record']['bid'][331])
                    fixtures.quote_from(material, 340, entry+side*3*tick, side)
                    fixtures.quote_from(material, 344, entry+side*tick, side)
                immutable(material)
                immutable(case)
                full = interface.play(material, case, exit_id)
                assert len(full['trades']) == 1
                counts['買売完結例'] += 1
                after_exit = int(full['trades'][0, 3])+1
                raw_cut = int(case['execution_to_raw_index'][after_exit-1])+1
                normal_cut = int(np.searchsorted(case['execution_to_raw_index'], raw_cut, side='left'))
                assert normal_cut == after_exit
                counts['原行map切断'] += 1
                for length in (331, 335, after_exit):
                    small, reduced = prefix(material, case, length)
                    assert not small['record']['bid'].flags.writeable and small['record']['bid'].flags.c_contiguous
                    assert not reduced['event'].flags.writeable and reduced['event'].flags.c_contiguous
                    counts['JIT読取専用資格'] += 1
                    answer = interface.play(small, reduced, exit_id, finish=False)
                    wanted = expected(full, length)
                    compare(answer, wanted)
                    if length == 331:
                        assert not len(answer['orders']) and answer['target_trace'][-1,4] == 1
                    elif length == 335:
                        assert len(answer['orders']) == 1 and not len(answer['trades'])
                    else:
                        assert len(answer['orders']) == 2 and len(answer['trades']) == 1 and not answer['target_trace'][-1].any()
                    counts['予約保有返済接頭'] += 1
                for kind in FUTURES:
                    modified, change, details = change_future(material, case, after_exit, kind)
                    # ----------------------------------------
                    # 完全配列を接続だけ確認し、未知未来の金融は再生せず同じ原行接頭を渡す。
                    interface.connect(modified, change, exit_id)
                    small, reduced = prefix(modified, change, after_exit)
                    answer = interface.play(small, reduced, exit_id, finish=False)
                    compare(answer, expected(full, after_exit))
                    assert details['未来正常行数'] > 0
                    counts['接頭未来改変'] += 1
                changed_wanted = expected(full, after_exit)
                changed_wanted['curve'] = changed_wanted['curve'].copy()
                changed_wanted['curve'][330] += 1
                try:
                    compare(answer, changed_wanted)
                except AssertionError:
                    counts['比較器差異拒否'] += 1
                else:
                    raise AssertionError('接頭曲線の差異を見逃しました')
    end = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    assert start == end
    save(ARTIFICIAL, dict(全合格=True, 人工専用=True, 検査件数=counts,
        開始終端source一致=True, source_SHA256=start,
        正式金融結果読取=0, 正式接頭再生=0, 原本及びNPZ読取=0, 活動cache読取=0,
        将来counterfactual金融再生=0, 現在API=0, 実注文=0,
        限界='未来改変は完全配列の接口検証後に同prefixへ切断。未来部分の損益全体は再生せず、'
             '正式全入力と実接頭の一致検査を実行前人工で確認した。'))
    print('接頭helper人工の予約・保有・返済及び未来六改変が一致しました。', flush=True)


def register() -> None:
    """
    機能: 勝敗によらない六親の選び方と改変範囲を金融結果前に登録する。
    引数: なし。
    返り値: None。正式金融結果を読まず固定旧32順だけを使う。
    """
    assert not PLAN.exists() and read(ARTIFICIAL)['全合格']
    metadata = read(WAVE/'入口準備の全32結果.json')
    assert metadata['全合格'] and len(metadata['sessions']) == 32
    save(PLAN, dict(全合格=True, 条件=list(CASES), 商品=list(SYMBOLS), 必要親数=6,
        sessions=metadata['sessions'],
        選定='各条件商品で固定旧32順の最初の完結親。sessionはcampaigns>0で指定し、'
             '親はentry_decision_row/entry_row/parent_idの順で最初。利益・損失・最大順行で選ばない。',
        cut='exit正常行をexecution_to_raw_indexへ戻した原行index+1。正常prefixはmap<raw_cutだけ。',
        再生='finish=Falseで同normal原行接頭のみ。旧known start/limit、保存始値、旧Dは交換しない。',
        exact比較=list(SPARSE)+list(DENSE)+list(COLUMNS)+['raw_entry_diagnostics及びepisodeの自己相手lineage'],
        比較しない値='fullの最終statsは場全体の値。接頭経済/判断と混同しない。',
        未来改変=list(FUTURES),
        未来改変範囲='完全入力の未来だけを変更し接口接続を検証。同prefixを再生し、未来の金融全体は再生しない。',
        開始条件='根121正式金融終了通知と別途許可後の一回。timeoutによる再開始禁止。',
        helperSHA256=digest(Path(__file__)), 人工SHA256=digest(ARTIFICIAL),
        金融結果前登録=True, 正式104金融結果読取=0, 正式接頭再生=0,
        新121全面再生=0, 将来counterfactual金融再生=0, 原本及びNPZ読取=0, 現在API=0, 実注文=0))
    print('固定三条件・二商品・先頭六親の接頭計画を保存しました。', flush=True)


def dependencies() -> list[Path]:
    """
    機能: 実接頭へ直接使うsourceと正式完了証跡を列挙する。
    引数: なし。
    返り値: list[Path]は小さい直接依存。正式台帳は同bytes読取時に別照合する。
    """
    paths = [Path(__file__), HERE/'interface.py', HERE/'core.py', HERE/'adapter.py', HERE/'old_finance_snapshot.py',
        WAVE/'base.py', WAVE/'catalog.py', WAVE/'prepared_data.py', WAVE/'research.py',
        WAVE/'金融事前固定.json', WAVE/'金融全32の結果.json', WAVE/'入口準備の全32結果.json', PLAN, ARTIFICIAL]
    paths += [ROOT/'work/wave_v102'/name for name in ('engine.py', 'strategy.py')]
    paths += [ROOT/name for name in read(WAVE/'入口準備の全32結果.json')['source_SHA256']]
    return sorted(set(paths), key=lambda path: path.as_posix())


def run() -> None:
    """
    機能: 根許可後の正式先頭六親を一回だけ接頭再生し、保存出力へexact照合する。
    引数: なし。
    返り値: None。False時は元sourceと対象・完了件数を保持し、自動再試行しない。
    """
    assert not OUTPUT.exists() and not STARTED.exists() and not SELECTION.exists()
    plan = read(PLAN)
    assert plan['helperSHA256'] == digest(Path(__file__)) and plan['人工SHA256'] == digest(ARTIFICIAL)
    terminal = read(WAVE/'金融全32の結果.json')
    assert terminal['全合格'] and terminal['条件数'] == 121 and terminal['sessions'] == plan['sessions']
    assert terminal['原本再抽出'] == terminal['現在API'] == terminal['実注文'] == 0
    paths = dependencies()
    start = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    save(STARTED, dict(開始UTC=datetime.now(timezone.utc).isoformat(), source_SHA256=start,
        根許可='正式121完了後の固定先頭六親接頭だけ', 正式全面再生=0,
        将来counterfactual金融再生=0, API=0, 実注文=0))
    selected, direct_hashes, loaded = [], {}, {}
    finished = []
    context = dict(case=None, symbol=None, session=None)
    try:
        # ----------------------------------------
        # 先頭場は会計の完結親数だけで決め、勝敗を見る選び直しを行わない。
        for ident in CASES:
            item = terminal['results'][ident]
            result_path = ROOT/item['path']
            assert result_path.resolve().is_relative_to((WAVE/'finance/results').resolve())
            assert digest(result_path) == item['SHA256']
            direct_hashes[result_path.relative_to(ROOT).as_posix()] = item['SHA256']
            result = read(result_path)
            assert result['config']['kind'] == 'single' and result['config']['quantity'] == {'TOPIX':1,'NK225':1}
            for symbol in SYMBOLS:
                available = {row['session'] for row in result['rows'] if row['symbol'] == symbol and row['campaigns'] > 0}
                session = next((value for value in plan['sessions'] if value in available), None)
                assert session is not None, ident+'/'+symbol+'に完結親がありません'
                context = dict(case=ident, symbol=symbol, session=session)
                ledger_item = result['ledgers'][session+'|'+symbol]
                path = ROOT/ledger_item['path']
                assert path.resolve().is_relative_to((WAVE/'finance/ledger'/ident).resolve())
                saved = path.read_bytes()
                fingerprint = hashlib.sha256(saved).hexdigest()
                assert fingerprint == ledger_item['SHA256']
                full = pickle.loads(gzip.decompress(saved))
                assert full['configured_quantity'] == 1
                assert full['entry_id'] == result['config']['entry_id'] and full['exit_id'] == result['config']['exit_id']
                assert len(full['trades'])
                first = min(full['trades'], key=lambda row:(int(row[15]),int(row[2]),int(row[0])))
                selected.append(dict(case=ident, symbol=symbol, session=session,
                    entry_id=full['entry_id'], exit_id=full['exit_id'], parent_id=int(first[0]),
                    entry_decision_normal_row=int(first[15]), entry_normal_row=int(first[2]),
                    exit_normal_row=int(first[3]), cut_normal_length=int(first[3])+1,
                    ledger=ledger_item))
                direct_hashes[path.relative_to(ROOT).as_posix()] = fingerprint
                loaded[ident,symbol] = full
                del saved
        assert len(selected) == 6
        save(SELECTION, dict(全合格=True, 親数=6, 選定=plan['選定'], 対象=selected,
            計画SHA256=digest(PLAN), 正式結果SHA256=digest(WAVE/'金融全32の結果.json'),
            直接資料SHA256=direct_hashes, 金融結果参照あり=True, 勝敗による対象変更=0))
        # ----------------------------------------
        # 共通旧素材は一回、新normal入口cacheは必要な各場を一回だけ読む。
        base = module('104金融接頭の根base', WAVE/'base.py')
        assert 'base' not in sys.modules or Path(sys.modules['base'].__file__).resolve() == (WAVE/'base.py').resolve()
        sys.modules['base'] = base
        data = module('104金融接頭の完了入口cache', WAVE/'prepared_data.py')
        interface = base.module('104正式金融の共通接口', HERE/'interface.py')
        prepared = base.load_prepared()
        packets = {session:data.load_session(session) for session in dict.fromkeys(row['session'] for row in selected)}
        for target in selected:
            ident, symbol, session = target['case'], target['symbol'], target['session']
            context = dict(case=ident,symbol=symbol,session=session)
            material = prepared[session,symbol]
            case = packets[session]['cases'][target['entry_id']][symbol]['normal']
            mapping = case['execution_to_raw_index']
            assert np.all(np.diff(mapping) > 0)
            length = target['cut_normal_length']
            raw_cut = int(mapping[target['exit_normal_row']])+1
            assert int(np.searchsorted(mapping,raw_cut,side='left')) == length
            assert np.all(mapping[:length] < raw_cut) and np.all(mapping[length:] >= raw_cut)
            small, reduced = prefix(material,case,length)
            answer = interface.play(small,reduced,target['exit_id'],finish=False)
            wanted = expected(loaded[ident,symbol],length)
            sizes = compare(answer,wanted)
            assert np.any(answer['trades'][:,0] == target['parent_id'])
            assert not answer['target_trace'][-1].any(), 'exit直後の接頭に未返済予約が残っています'
            assert len(answer['curve']) == length and length < len(material['record']['time_s'])
            mutations = []
            for kind in FUTURES:
                changed, change, details = change_future(material,case,length,kind)
                interface.connect(changed,change,target['exit_id'])
                part, reduced = prefix(changed,change,length)
                alternative = interface.play(part,reduced,target['exit_id'],finish=False)
                compare(alternative,wanted)
                mutations.append(dict(種類=kind, 全接頭一致=True, **details))
                del alternative, part, reduced, changed, change
            finished.append(dict(**target, cut_raw_index=raw_cut,
                exit_raw_seq=int(material['record']['seq'][target['exit_normal_row']]),
                正式接頭全一致=True, future_timer清算なし=True, finish=False,
                検査要素数=sizes, 未来改変=mutations))
            print(ident+'/'+symbol+'/'+session+' 先頭親と六未来改変が接頭一致',flush=True)
            del answer, small, wanted, loaded[ident,symbol]
        end = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
        assert start == end
        for name, wanted_sha in direct_hashes.items():
            assert digest(ROOT/name) == wanted_sha
        save(OUTPUT, dict(全合格=True, 対象親数=6, 検査件数=dict(正式接頭=6,未来改変接頭=36),
            対象=finished, 金融結果参照あり=True, 開始終端source一致=True,
            source_SHA256=start, 終端source_SHA256=end, 直接資料SHA256=direct_hashes,
            固定対象SHA256=digest(SELECTION), 正式新金融全面再生=0,
            旧共通base準備=1, 入口cache一場読取=len(packets),
            将来counterfactual金融再生=0, 原本及びNPZ読取=0, 現在API=0, 実注文=0,
            限界='先頭六完結親の出口直後接頭。全121の独立会計は別監査。'
                 '未来変更の金融全場は再生せず、modified full接口から同prefixを切って検査。'
                 '保有端点と未約定端点の未来清算なしはhelper人工と独立人工で別に検査。'))
        print('固定先頭六親と三十六未来改変の接頭が全て一致しました。',flush=True)
    except BaseException as error:
        folder=HERE/('実金融接頭False_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        folder.mkdir()
        for path in (Path(__file__),HERE/'interface.py',HERE/'core.py'):
            shutil.copy2(path,folder/path.name)
        save(folder/'失敗.json',dict(全合格=False,完了対象親数=len(finished),現在=context,
            exception_type=type(error).__name__,message=str(error),source_SHA256=start,
            固定対象=selected,完了=finished,自動再試行=0,新全面金融再生=0,API=0,実注文=0))
        raise


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 保存資料の接頭検査から外部通信を拒否する。
    引数: args(tuple)、kwargs(dict)は通信引数。
    返り値: None。常に例外を送出する。
    """
    raise RuntimeError('保存資料の金融接頭だけを検査します')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    choice=parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--artificial',action='store_true')
    choice.add_argument('--register',action='store_true')
    choice.add_argument('--root-formal121-completed',action='store_true')
    option=parser.parse_args()
    socket.create_connection=deny
    socket.socket.connect=deny
    if option.artificial:
        artificial()
    elif option.register:
        register()
    else:
        run()
