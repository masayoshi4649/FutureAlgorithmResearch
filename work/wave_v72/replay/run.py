"""凍結T1L1_R01の既存28場を再利用し、保存済み追加場だけを同じ仕様で再生する。"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import numba
from numba import njit


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v70'
EXTRA = ROOT / 'work/wave_v71/prepared'
ID = 'T1L1_R01'
SYMBOLS = ('TOPIX', 'NK225')
sys.dont_write_bytecode = True
numba.config.CACHE_DIR = str(HERE / 'numba_cache')


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存再生からのネットワーク接続を必ず拒否する。

    引数: args(tuple)、kwargs(dict)。
    返り値: なし(None)。接続要求時はRuntimeErrorを発生する。
    """
    raise RuntimeError('保存済み資料の再生では通信を禁止しています')


def load(path: Path) -> object:
    """機能: 読み取り専用の既存資料又は今回資料を読み込む。

    引数: path(Path)。
    返り値: JSON又はpickleに保存された値(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(name: str, value: object) -> Path:
    """機能: 今回のreplay領域へ新しい資料だけを保存する。

    引数: name(str)、value(object)。
    返り値: 保存先(Path)。既存資料は上書きしない。
    """
    path = (HERE / name).resolve()
    assert path.is_relative_to(HERE) and not path.exists(), ('保存先重複', path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.pkl':
        path.write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    return path


def digest(path: Path) -> str:
    """機能: 保存資料の内容指紋をストリーム読取で計算する。

    引数: path(Path)。
    返り値: SHA256の16進表記(str)。原本への書込みは行わない。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def import_file(name: str, path: Path) -> object:
    """機能: 凍結済み実装を変更せず読み込み、今回のキャッシュ先を維持する。

    引数: name(str)、path(Path)。
    返り値: 読み込んだモジュール(object)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    numba.config.CACHE_DIR = str(HERE / 'numba_cache')
    return module


def frozen_parent() -> object:
    """機能: 元の親予約関数だけを抽出し、凍結と同じ処理を今回領域で実行する。

    引数: なし。
    返り値: wave70のcandidates関数(object)。関数本文・判定順・定数は変更しない。
    モジュール上位の旧作業キャッシュ先指定を実行しないため、旧領域に書込まない。
    """
    path = OLD / 'inputs/schedule.py'
    tree = ast.parse(path.read_text(encoding='utf8'), filename=str(path))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'candidates']
    assert len(nodes) == 1
    namespace = dict(np=np, njit=njit)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['candidates']


def inventory() -> dict:
    """機能: 原板と二種類の足の保存範囲を銘柄別に列挙する。

    引数: なし。
    返り値: フォルダ別・銘柄別のセッション一覧(dict)。内容の再抽出は行わない。
    """
    return {folder: {symbol: sorted(p.stem for p in (ROOT / folder / symbol).glob('*' + suffix))
                    for symbol in SYMBOLS}
            for folder, suffix in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv'))}


def sliced(mapping: dict, count: int) -> dict:
    """機能: 原本行と同じ長さを持つ系列だけを途中で切断する。

    引数: mapping(dict)、count(int)。
    返り値: 時刻の開始・返済期限などの定数を保持した短縮辞書(dict)。
    """
    n = len(mapping['time_s'])
    return {name: value[:count] if isinstance(value, np.ndarray) and len(value) == n else value
            for name, value in mapping.items()}


def sparse(raw: tuple) -> np.ndarray:
    """機能: 元の親予約結果を共通の疎な五列入口配列へ変換する。

    引数: raw(tuple)。
    返り値: 約定行・判断行・予約行・方向・予約気配の配列(ndarray[float64,N,5])。
    """
    fills = np.flatnonzero(raw[0])
    return np.column_stack((fills, raw[2][fills], raw[3][fills], raw[0][fills], raw[1][fills]))


def causal_checks(key: tuple, ready: dict, feature: dict, event: np.ndarray, signal: np.ndarray,
                  schedule: np.ndarray, model: object, parent: object, study: object,
                  config: dict, full: tuple) -> dict:
    """機能: 追加場の入口・親予約・管理を途中切断と未来改変で照合する。

    引数: key(tuple)、ready/feature/config(dict)、event/signal/schedule(ndarray)、
    model/parent/study(object)、full(tuple)。
    返り値: 三切断点における一致記録(dict)。終端で架空清算する処理は追加しない。
    """
    n = len(ready['time_s'])
    rows = []
    args = model.arguments_from(feature, event, ready['tick'], ready['start'])
    for cut in sorted(set((n // 3, n // 2, 2 * n // 3))):
        e_short = event[event['i'] < cut]
        r_short, f_short = sliced(ready, cut), sliced(feature, cut)
        generated = model.candidate_signals(*model.arguments_from(f_short, e_short, ready['tick'], ready['start']))[1]
        np.testing.assert_array_equal(generated, signal[:cut])
        parent_short = parent(r_short['time_s'], f_short['bid'], f_short['ask'], generated,
                              f_short['reset'], ready['start'], ready['limit'])
        scheduled = sparse(parent_short)
        np.testing.assert_array_equal(scheduled, schedule[schedule[:, 0] < cut])
        short = study.engine.simulate(*study.arguments(config, key, {key:r_short}, {key:f_short},
                                       {key:np.vstack([generated] * 6)}, {key:[scheduled] * 6}))
        np.testing.assert_array_equal(short[0], full[0][full[0][:, 0] < cut])
        np.testing.assert_array_equal(short[1], full[1][full[1][:, 2] < cut])
        np.testing.assert_array_equal(short[2], full[2][:cut])
        # ----------------------------------------
        # 未来の価格・フロー・品質・補充価格を変え、過去の入口と管理判断が不変か検査する。
        changed = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in feature.items()}
        for field in ('bid', 'ask', 'mid', 'last', 'bid_far', 'ask_far'):
            changed[field][cut:] += 100. * ready['tick']
        changed['best_ofi'][cut:] *= -7.
        changed['reset'][cut:] = True
        changed_event = event.copy()
        changed_event['price'][changed_event['i'] >= cut] += 100. * ready['tick']
        changed_signal = model.candidate_signals(*model.arguments_from(changed, changed_event,
                                                  ready['tick'], ready['start']))[1]
        np.testing.assert_array_equal(changed_signal[:cut], signal[:cut])
        changed_raw = parent(ready['time_s'], changed['bid'], changed['ask'], changed_signal,
                             changed['reset'], ready['start'], ready['limit'])
        changed_schedule = sparse(changed_raw)
        np.testing.assert_array_equal(changed_schedule[changed_schedule[:, 0] < cut], scheduled)
        future = study.engine.simulate(*study.arguments(config, key, {key:ready}, {key:changed},
                                        {key:np.vstack([changed_signal] * 6)}, {key:[changed_schedule] * 6}))
        np.testing.assert_array_equal(future[0][future[0][:, 0] < cut], short[0])
        np.testing.assert_array_equal(future[1][future[1][:, 2] < cut], short[1])
        np.testing.assert_array_equal(future[2][:cut], short[2])
        rows.append(dict(切断行=cut, 入口一致=True, 共通枠一致=True, 注文一致=True,
                         決済一致=True, 時価一致=True, 未来変更一致=True))
    return dict(session=key[0], symbol=key[1], 原本行数=n, 検査=rows,
                親予約行判断行約定行分離=bool(np.all(schedule[:, 2] < schedule[:, 1])
                                           and np.all(schedule[:, 1] < schedule[:, 0])),
                代理時計='CurrentPriceTime。受信時刻の因果性ではなく保存行順の因果性を照合。')


def main() -> None:
    """機能: 既存結果を保全して、追加再生と全保存場の統合資料を作成する。

    引数: なし。
    返り値: なし(None)。API取得と実注文はともにゼロ。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    HERE.mkdir(parents=True, exist_ok=True)
    assert not (HERE / (ID + '_追加セッション.json')).exists(), '完了済み結果は上書きしない'
    fixed = load(OLD / '事前固定.json')
    old_result = load(OLD / 'results' / (ID + '.json'))
    config = next(c for c in fixed['条件'] if c['id'] == ID)
    assert config == old_result['config'] and config['source_index'] == 0 and not config['paired']
    source_hashes = {str((ROOT / name).relative_to(ROOT)): digest(ROOT / name) for name in fixed['SHA256']}
    assert source_hashes == fixed['SHA256'], '凍結実装又は既存入力が変更されています'
    paths = [EXTRA / name for name in ('extra_inputs.pkl', 'extra_features.pkl', 'extra_events.pkl', 'extra_base_signals.pkl')]
    paths += [ROOT / 'work/wave_v71/inputs/schedule.pkl', ROOT / 'work/wave_v69/signals/core.py',
              OLD / 'inputs/schedule.py', OLD / 'results' / (ID + '.json'), OLD / 'ledgers' / (ID + '.pkl')]
    hashes = {str(p.relative_to(ROOT)):digest(p) for p in paths}
    extra_audit = load(EXTRA / '追加デイの入力照合.json')
    for name, expected in extra_audit['SHA256'].items():
        assert digest(EXTRA / name) == expected, ('追加入力指紋不一致', name)
    assert digest(ROOT / 'work/wave_v69/signals/core.py') == load(ROOT / 'work/wave_v69/signals/入口仕様.json')['core_SHA256']
    inv = inventory()
    sessions = sorted(set(inv['book']['TOPIX']) | set(inv['book']['NK225']))
    known = fixed['全セッション']
    added = sorted(set(sessions) - set(known))
    ready, features, events, signals = (load(p) for p in paths[:4])
    new_keys = sorted(set(ready) - {(s, symbol) for s in known for symbol in SYMBOLS})
    supported = {(s, symbol) for s in known for symbol in SYMBOLS} | set(new_keys)
    unhandled = sorted((s, symbol) for symbol in SYMBOLS for s in inv['book'][symbol] if (s, symbol) not in supported)
    assert set(ready) == set(features) == set(events) == set(signals)
    assert {key[0] for key in new_keys} == set(added) and not unhandled
    assert all(inv[folder][symbol] == sessions for folder in inv for symbol in SYMBOLS)
    old_book_audit = load(ROOT / 'work/wave_v69/prepared/入力と特徴の照合.json')
    expected_raw = {(r['セッション'], r['銘柄']):r['原本SHA256'] for r in old_book_audit['口座別']}
    expected_raw.update({(Path(name).stem, Path(name).parent.name):sha for name, sha in extra_audit['原本SHA256'].items()})
    raw_records = []
    for session in sessions:
        for symbol in SYMBOLS:
            path = ROOT / 'book' / symbol / (session + '.jsonl')
            actual = digest(path)
            assert actual == expected_raw[(session, symbol)], ('原本が準備時から変化', session, symbol)
            raw_records.append(dict(session=session, symbol=symbol, 原本=str(path.relative_to(ROOT)),
                                    バイト数=path.stat().st_size, SHA256=actual, 準備時一致=True))
    save('保存範囲の照合.json', dict(保存範囲=inv, 全セッション=sessions, 場数=len(sessions), 口座数=2*len(sessions),
         既存再利用場=known, 追加再生場=added, 未対応=unhandled, 原本照合=raw_records, API取得=0, 実注文=0))
    freeze_path = save('再生前固定.json', dict(固定時刻=datetime.now(timezone.utc).isoformat(), config=config,
        初回と片方向上限=fixed['初回と片方向上限'], 円倍率=fixed['円倍率'], 片道料金=fixed['片道料金'],
        共通入口=fixed['共通入口'], 再生対象=added, 再利用=known,
        料金=fixed['料金'], 気配約定='原板の買いask・売りbid。条件成立の次の有効観測で約定。',
        方針='wave70 T1L1_R01のみを同じ設定で追加再生。入口・利益固定・保有時間・料金を変更しない。',
        既知性='既存28場は再利用。追加10/09Dayは他の調査で閲覧済みだが、この条件の選び直しには使わない。',
        API取得=0, 実注文=0, 凍結元SHA256=source_hashes, 参照SHA256=hashes,
        今回コードSHA256=digest(Path(__file__))))
    print('29場58口座の保存範囲と原本指紋一致。追加1場を固定仕様で再生します。', flush=True)
    # ----------------------------------------
    # 旧モジュールのキャッシュ先指定より先にエンジンを読み込み、書込先を今回領域へ限定する。
    import_file('engine', OLD / 'engine.py')
    import_file('net', OLD / 'net.py')
    study = import_file('replay_frozen_study70', OLD / 'study.py')
    assert config == next(c for c in study.catalog() if c['id'] == ID)
    model = import_file('replay_frozen_ticks69', ROOT / 'work/wave_v69/signals/core.py')
    parent = frozen_parent()
    saved_schedule = load(ROOT / 'work/wave_v71/inputs/schedule.pkl')
    rows, ledgers, audits, schedules = [], {}, [], {}
    for key in new_keys:
        r, f, e = ready[key], features[key], events[key]
        np.testing.assert_array_equal(r['time_s'], f['time_s'])
        np.testing.assert_array_equal(r['seq'], f['seq'])
        assert np.all(np.diff(r['seq']) > 0) and np.all(np.diff(r['time_s']) >= 0)
        generated = model.candidate_signals(*model.arguments_from(f, e, r['tick'], r['start']))[1]
        np.testing.assert_array_equal(generated, signals[key][0])
        raw = parent(r['time_s'], f['bid'], f['ask'], generated, f['reset'], r['start'], r['limit'])
        schedule = sparse(raw)
        np.testing.assert_array_equal(schedule, saved_schedule[key][0])
        schedules[key] = [schedule] * 6
        full = study.engine.simulate(*study.arguments(config, key, ready, features, signals, schedules))
        orders, trades, curve, counters = full
        row = study.account(key, ready, orders, trades, curve, counters)
        assert np.all(orders[orders[:, 7] == 1, 4] == fixed['初回と片方向上限'][key[1]])
        assert np.all(orders[:, 8] == 0), 'R01に保険玉を加えない'
        assert np.all(r['time_s'][orders[:, 0].astype(int)] < r['limit']), '全注文は場内期限前'
        rows.append(row)
        ledgers[key] = dict(orders=orders, trades=trades, counters=counters,
                            curve_hash=hashlib.sha256(curve.tobytes()).hexdigest(), paired_metadata=None)
        audits.append(causal_checks(key, r, f, e, generated, schedule, model, parent, study, config, full))
        print(key[0], key[1], '収支', row['net'], '円 /', row['campaigns'], '組', flush=True)
    new_ledger = save(ID + '_追加台帳.pkl', ledgers)
    inputs_paths = {name:str((EXTRA / name).relative_to(ROOT)) for name in
                   ('extra_inputs.pkl','extra_features.pkl','extra_events.pkl','extra_base_signals.pkl')}
    inputs_paths['共通予約照合先'] = 'work/wave_v71/inputs/schedule.pkl（T1L1_G0=0列）'
    inputs_paths['凍結元実装'] = 'work/wave_v70/engine.py'
    save(ID + '_追加セッション.json', dict(config=config, rows=rows, sessions=added,
         periods={'追加1':{s:study.aggregate(rows,s,added) for s in SYMBOLS}},
         inputs=inputs_paths, ledger_SHA256=digest(new_ledger), 再生前固定SHA256=digest(freeze_path),
         既存変更=False, API取得=0, 実注文=0))
    save('追加再生の因果検査.json', dict(全合格=True, 検査=audits,
         無条件入口='wave69 T1L1元関数の再計算とextra_base_signals0列が完全一致。',
         共通枠='wave70元candidates再計算とwave71 T1L1_G0予約列が完全一致。',
         場内返済=True, 最終保有ゼロ=True, API取得=0, 実注文=0))
    # ----------------------------------------
    # 既存56口座の行・台帳は計算し直さず、内容をそのまま今回の統合資料へ接続する。
    old_ledgers = load(OLD / 'ledgers' / (ID + '.pkl'))
    assert not set(old_ledgers) & set(ledgers)
    all_rows = sorted(old_result['rows'] + rows, key=lambda r:(r['session'], r['symbol']))
    all_ledgers = dict(old_ledgers, **{})
    all_ledgers.update(ledgers)
    assert set(all_ledgers) == supported and len(all_rows) == 2 * len(sessions)
    combined_ledger = save(ID + '_全台帳.pkl', all_ledgers)
    periods = {name:{s:study.aggregate(all_rows,s,scope) for s in SYMBOLS} for name, scope in
               [('前16',fixed['前16']),('後12',fixed['後12']),('全28',known),('追加1',added),('全29',sessions)]}
    for name in old_result['periods']:
        assert periods[name] == old_result['periods'][name], ('既存集計が変化', name)
    save(ID + '_全セッション.json', dict(config=config, rows=all_rows, sessions=sessions, periods=periods,
        inputs=inputs_paths, 既存結果='work/wave_v70/results/T1L1_R01.json',
        既存台帳='work/wave_v70/ledgers/T1L1_R01.pkl', 追加結果=ID + '_追加セッション.json',
        ledger_SHA256=digest(combined_ledger), API取得=0, 実注文=0))
    unchanged = all(digest(ROOT / name) == value for name, value in hashes.items())
    assert unchanged
    save('再生後の保全照合.json', dict(全合格=True, 元実装入力結果台帳の変更なし=unchanged,
         既存28場の集計完全一致=True, 追加1場のみ再生=True, 保存場の未対応=unhandled,
         全場数=len(sessions), 全口座数=len(all_rows), 今回成果={p.name:digest(p) for p in HERE.iterdir() if p.is_file()},
         API取得=0, 実注文=0))
    print('全29場の統合資料・追加台帳・因果検査を保存しました。', flush=True)


if __name__ == '__main__':
    main()
