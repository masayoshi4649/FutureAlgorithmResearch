"""全事前候補から過去の完了区間だけで選び、次区間の売買損益を連結する。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import math
import pickle

import numpy as np


WORK = Path(__file__).resolve().parent
OLD = WORK.parent / 'wave_v23'
PREVIOUS = WORK.parent / 'wave_v24'
JST = timezone(timedelta(hours=9))
SYMBOLS = ['TOPIX', 'NK225']
FALLBACK = 'F32__G08'
STRATEGY_ID = 'SQ00_過去入口を通る単純首位'
INITIAL = 6
FIELDS = [
    'gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units',
    'cycles', 'cycle_wins', 'cycle_losses', 'cycle_profit_yen', 'cycle_loss_yen', 'closed_units',
    'net_r', 'drawdown_yen', 'min_equity_yen', 'max_equity_yen', 'max_long', 'max_short',
    'longest_losing_streak', 'maximum_trade_profit', 'maximum_trade_loss', 'reversals',
    'top_cycle_1', 'top_cycle_2',
]
INDEX = {name: i for i, name in enumerate(FIELDS)}
SUM_FIELDS = FIELDS[:13]
INTEGER_FIELDS = {'profit_units', 'loss_units', 'zero_units', 'cycles', 'cycle_wins', 'cycle_losses',
                  'closed_units', 'max_long', 'max_short', 'longest_losing_streak', 'reversals'}


def read(path: Path) -> object:
    """機能: 通常または圧縮されたJSONを読む。

    引数: path (Path) 読取先。
    返り値: JSON内容 (object)。
    """
    if path.suffix == '.gz':
        return json.loads(gzip.decompress(path.read_bytes()).decode('utf-8'))
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: object) -> None:
    """機能: 非有限値を拒否して、今回の領域へJSONを保存する。

    引数: path (Path) 保存先、value (object) 内容。
    返り値: なし (None)。
    """
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(gzip.compress(encoded) if path.suffix == '.gz' else encoded)
    temporary.replace(path)


def digest(path: Path) -> str:
    """機能: 読み取り専用でファイルのSHA256を取得する。

    引数: path (Path) 対象。
    返り値: SHA256の文字列 (str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while part := stream.read(8 * 1024 * 1024):
            result.update(part)
    return result.hexdigest()


def now() -> str:
    """機能: 記録用の日本時間を作る。

    引数: なし。
    返り値: ISO時刻 (str)。
    """
    return datetime.now(JST).isoformat()


def parameter_count(value: object) -> int:
    """機能: 同点整理用に明示的な数値・真偽設定を数える。

    引数: value (object) パラメータ辞書等。
    返り値: 数値・真偽の葉の個数 (int)。統計的な自由度ではない。
    """
    if isinstance(value, dict):
        return sum(parameter_count(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(parameter_count(v) for v in value)
    return int(isinstance(value, (int, float, bool)))


def catalog_metadata(frozen: dict) -> tuple[list[dict], np.ndarray]:
    """機能: 成績を参照せず、全候補IDと同点用設定数を作る。

    引数: frozen (dict) 探索前カタログ。
    返り値: 候補メタデータ (list[dict])、設定数 (ndarray)。
    """
    items = []
    for signal in frozen['signals']:
        for manager in frozen['managers']:
            items.append({
                'id': signal['id'] + '__' + manager['id'],
                'signal_id': signal['id'], 'manager_id': manager['id'],
                'signal_family': signal.get('family', '既存学習'),
                'manager_family': manager['family'],
                '明示数値真偽設定数': parameter_count(signal.get('params', {}))
                                    + parameter_count(manager.get('changes', {})),
            })
    items.sort(key=lambda item: item['id'])
    assert len(items) == frozen['全組合せ数']
    assert len({item['id'] for item in items}) == len(items)
    assert FALLBACK in {item['id'] for item in items}
    return items, np.asarray([item['明示数値真偽設定数'] for item in items], dtype=np.int64)


def prepare() -> dict:
    """機能: 新探索成績を読まず、選択工程と既知入力の境界を凍結する。

    引数: なし。
    返り値: 凍結記録 (dict)。成績ファイルにはアクセスしない。
    """
    path = WORK / 'sequential_selection_fixed.json'
    frozen = read(WORK / '探索条件の固定.json')
    audit = read(WORK / 'data_audit.json')
    items, _ = catalog_metadata(frozen)
    sessions = audit['セッション一覧']
    assert audit['前回と全原本が一致'] and len(sessions) == 13
    assert sessions == sorted(sessions)
    dependencies = [Path(__file__), WORK / '探索条件の固定.json', WORK / 'validation_protocol.json',
                    WORK / 'data_audit.json', OLD / 'inputs.pkl', PREVIOUS / '枝除去と感度.json']
    hashes = {p.relative_to(WORK.parent).as_posix(): digest(p) for p in dependencies}
    if path.exists():
        result = read(path)
        assert result['SHA256'] == hashes, '固定後に依存コード・仕様・既知入力が変わりました'
        return result
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    timing = {}
    for session in sessions:
        starts = [float(inputs[(session, symbol)]['time_s'][0]) for symbol in SYMBOLS]
        ends = [float(inputs[(session, symbol)]['time_s'][-1]) for symbol in SYMBOLS]
        timing[session] = {'最初の観測秒': min(starts), '最後の観測秒': max(ends)}
    for previous, following in zip(sessions, sessions[1:]):
        assert timing[previous]['最後の観測秒'] < timing[following]['最初の観測秒']
    result = {
        '固定時刻': now(), '新探索成績を未読で作成': True,
        '対象候補数': len(items), '対象候補IDのSHA256': hashlib.sha256(
            '\n'.join(item['id'] for item in items).encode()).hexdigest(),
        '選択工程ID': STRATEGY_ID, '選択工程数': 1,
        '基準': 'validation_protocol.json の時間順選択工程と同じ入口・順位を使用する。',
        '学習': '最初6セッションから完了セッションだけを追加する拡張窓。',
        '評価': '次の1セッションを7回。最初6区間の損益は評価収支へ含めない。',
        '過去入口': {
            '活動と黒字区間': '各ceil(過去区間数/2)以上', '売買組数': '過去区間数以上',
            'PF': 1.30, '1枚平均勝ち負け比': 1.20, '収支': '>0',
            '最大2勝ち売買組除外': '>0', '最大2黒字区間除外': '>0',
            '存在する日中夜間と開始週': '各合計>0',
        },
        '順位': ['最弱銘柄の最大2勝ち組除外後収支÷利益額を降順',
                 '最弱銘柄の最大2黒字区間除外後収支÷利益額を降順',
                 '最弱銘柄のPFを上限5で降順', '最弱銘柄の1枚平均勝ち負け比を上限5で降順',
                 '明示された数値・真偽パラメータ葉数を昇順', '候補IDを昇順'],
        '設定数の留保': '順位の最後に使う簡易複雑度。統計的自由度や実際に使われる全設定数の厳密推定ではない。',
        '該当なし': FALLBACK, '同じ採用IDを両銘柄へ適用': True,
        '未来成績参照禁止': '選択関数の入口でデータ配列を過去cut区間へ切り、残りと現在評価区間は参照しない。',
        '未来改変監査': '各7foldで全候補の未来を削除／別値へ改変して、全候補の検査値・採否・全順位が不変か確認。',
        '成績保存粒度': '各foldの全候補数・合格数・不合格理由件数・全順位ハッシュ・上位10・採用の全過去検査・次区間2銘柄。',
        'セッション一覧': sessions, '観測境界': timing,
        '一次探索との違い': '一次探索の上位に絞らず全カタログを判定。一次探索の順位式とは別に事前固定した時間順工程。',
        '既知性': '13セッションは全て過去研究で既読。F32 fallbackも既知全期間を見て選ばれた基準。事後の時間順再現であり未見OOSではない。',
        '数量': '保存された各管理の実枚数を維持。共通初期リスク総額への変更は未実装。',
        'API取得数': 0, '旧コード原本変更': False, 'SHA256': hashes,
    }
    save(path, result)
    return result


def safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """機能: 分母が正の場合だけ比率を計算する。

    引数: numerator/denominator (ndarray) 同形配列。
    返り値: 分母不足をNaNとする配列 (ndarray)。
    """
    return np.divide(numerator, denominator, out=np.full_like(numerator, np.nan), where=denominator > 1e-8)


def choose_before(cube: np.ndarray, sessions: list[str], cut: int,
                  complexities: np.ndarray, ids: list[str]) -> dict:
    """機能: 完了したcut区間のみで全候補を検査し、共通採用IDを選ぶ。

    引数: cube (ndarray) 候補×区間×銘柄×項目、sessions (list[str]) 区間名、
        cut (int) 完了区間数、complexities (ndarray) 設定数、ids (list[str]) 昇順候補ID。
    返り値: 全候補の過去検査値・採否・順位・採用位置 (dict)。未来側の値は使用しない。
    """
    assert 1 <= cut <= cube.shape[1] and len(ids) == cube.shape[0]
    past = cube[:, :cut, :, :]
    prior_sessions = sessions[:cut]
    total = past.sum(axis=1)
    gross_profit = total[:, :, INDEX['gross_profit_yen']]
    gross_loss = total[:, :, INDEX['gross_loss_yen']]
    net = total[:, :, INDEX['net_yen']]
    pf = safe_ratio(gross_profit, gross_loss)
    mean_win = safe_ratio(gross_profit, total[:, :, INDEX['profit_units']])
    mean_loss = safe_ratio(gross_loss, total[:, :, INDEX['loss_units']])
    payoff = safe_ratio(mean_win, mean_loss)
    session_net = past[:, :, :, INDEX['net_yen']]
    active = (past[:, :, :, INDEX['cycles']] > 0).sum(axis=1)
    winning = (session_net > 0).sum(axis=1)
    session_best = np.sort(np.maximum(session_net, 0.), axis=1)[:, -2:, :].sum(axis=1)
    cycle_values = past[:, :, :, [INDEX['top_cycle_1'], INDEX['top_cycle_2']]]
    cycle_values = cycle_values.transpose(0, 2, 1, 3).reshape(len(ids), len(SYMBOLS), cut * 2)
    cycle_best = np.sort(cycle_values, axis=-1)[:, :, -2:].sum(axis=-1)
    after_sessions = net - session_best
    after_cycles = net - cycle_best
    metrics = {'gross_profit_yen': gross_profit, 'gross_loss_yen': gross_loss, 'net_yen': net,
               'profit_units': total[:, :, INDEX['profit_units']], 'loss_units': total[:, :, INDEX['loss_units']],
               'zero_units': total[:, :, INDEX['zero_units']], 'cycles': total[:, :, INDEX['cycles']],
               'active_sessions': active, 'win_sessions': winning, 'money_ratio': pf,
               'average_unit_payoff': payoff, 'two_sessions_removed_net': after_sessions,
               'two_cycles_removed_net': after_cycles}
    checks = {
        '収支が正': net > 0, 'PF1.30以上': pf >= 1.30, '1枚平均比1.20以上': payoff >= 1.20,
        '売買組数が過去区間数以上': metrics['cycles'] >= cut,
        '活動が過去区間の半数以上': active >= math.ceil(cut / 2),
        '黒字が過去区間の半数以上': winning >= math.ceil(cut / 2),
        '最大2勝ち組除外後黒字': after_cycles > 0,
        '最大2黒字区間除外後黒字': after_sessions > 0,
    }
    groups = {'日中': [i for i, s in enumerate(prior_sessions) if s.endswith('_Day')],
              '夜間': [i for i, s in enumerate(prior_sessions) if s.endswith('_Night')]}
    for index, session in enumerate(prior_sessions):
        iso = date.fromisoformat(session[:10]).isocalendar()
        groups.setdefault(f'{iso.year}年第{iso.week}週', []).append(index)
    for name, indices in groups.items():
        if indices:
            value = session_net[:, indices, :].sum(axis=1)
            metrics[name + '収支'] = value
            checks[name + '合計黒字'] = value > 0
    passed = np.ones(len(ids), dtype=bool)
    for values in checks.values():
        passed &= values.all(axis=1)
    score = np.column_stack((
        np.nanmin(np.nan_to_num(safe_ratio(after_cycles, gross_profit), nan=-np.inf), axis=1),
        np.nanmin(np.nan_to_num(safe_ratio(after_sessions, gross_profit), nan=-np.inf), axis=1),
        np.nanmin(np.nan_to_num(np.minimum(pf, 5.), nan=-np.inf), axis=1),
        np.nanmin(np.nan_to_num(np.minimum(payoff, 5.), nan=-np.inf), axis=1),
    ))
    # ----------------------------------------
    # 最後の同点は事前のID昇順で決め、並列計算の完了順に依存しない。
    order = np.lexsort((np.arange(len(ids)), complexities, -score[:, 3], -score[:, 2],
                        -score[:, 1], -score[:, 0], ~passed))
    eligible = order[passed[order]]
    chosen = int(eligible[0]) if len(eligible) else ids.index(FALLBACK)
    return {'metrics': metrics, 'checks': checks, 'passed': passed, 'order': order,
            'eligible': eligible, 'selected_index': chosen, 'score': score}


def compare_choices(first: dict, second: dict) -> None:
    """機能: 選択だけでなく全候補の過去検査と全順位が一致するか確認する。

    引数: first/second (dict) choose_beforeの結果。
    返り値: なし (None)。不一致ではAssertionError。
    """
    assert first['selected_index'] == second['selected_index']
    for name in ['passed', 'order', 'score']:
        np.testing.assert_array_equal(first[name], second[name])
    assert first['metrics'].keys() == second['metrics'].keys()
    for name in first['metrics']:
        np.testing.assert_array_equal(first['metrics'][name], second['metrics'][name])
    for name in first['checks']:
        np.testing.assert_array_equal(first['checks'][name], second['checks'][name])


def finite(value: float) -> float | None:
    """機能: 比率の欠損をJSONのnullへ変換する。

    引数: value (float) 数値。
    返り値: 有限数またはNone (float|None)。
    """
    return float(value) if np.isfinite(value) else None


def candidate_diagnostic(result: dict, index: int, metadata: list[dict]) -> dict:
    """機能: ある候補の過去検査を両銘柄分保存できる形へ整える。

    引数: result (dict) 選択結果、index (int) 候補位置、metadata (list[dict]) 仕様。
    返り値: 候補ID、検査値、判定、順位用数値 (dict)。
    """
    symbols = {}
    for j, symbol in enumerate(SYMBOLS):
        symbols[symbol] = {
            '過去成績': {name: finite(value[index, j]) for name, value in result['metrics'].items()},
            '検査': {name: bool(value[index, j]) for name, value in result['checks'].items()},
        }
    return {**metadata[index], '過去入口合格': bool(result['passed'][index]),
            '順位用指標': [finite(v) for v in result['score'][index]], 'symbols': symbols}


def row_array(row: dict) -> np.ndarray:
    """機能: 保存済みの１セッション集計を固定順の配列へ変換する。

    引数: row (dict) 金額・枚数集計。
    返り値: 有限数の一次元配列 (ndarray)。
    """
    wins = list(row['two_largest_cycle_profits'])
    assert len(wins) <= 2 and all(value > 0 for value in wins)
    wins += [0.] * (2 - len(wins))
    values = dict(row, top_cycle_1=wins[0], top_cycle_2=wins[1])
    result = np.asarray([values[key] for key in FIELDS], dtype=np.float64)
    assert np.isfinite(result).all()
    assert abs(row['gross_profit_yen'] - row['gross_loss_yen'] - row['net_yen']) < .01
    assert row['profit_units'] + row['loss_units'] + row['zero_units'] == row['closed_units']
    return result


def array_row(cube: np.ndarray, index: int, session_index: int, symbol_index: int,
              ids: list[str], sessions: list[str]) -> dict:
    """機能: 採用された次区間の値だけを報告用辞書へ戻す。

    引数: cube (ndarray)、index/session_index/symbol_index (int)、ids/sessions (list[str])。
    返り値: 元の採用IDと銘柄・区間を持つ集計 (dict)。
    """
    values = cube[index, session_index, symbol_index]
    result = {name: int(values[i]) if name in INTEGER_FIELDS else float(values[i])
              for i, name in enumerate(FIELDS) if not name.startswith('top_cycle_')}
    result.update(id=ids[index], symbol=SYMBOLS[symbol_index], session=sessions[session_index],
                  two_largest_cycle_profits=[float(value) for value in values[-2:] if value > 0])
    return result


def load_library(frozen: dict, metadata: list[dict], sessions: list[str]) -> tuple[np.ndarray, list[dict]]:
    """機能: 探索完了後に全候補の全26区間を読み、欠損や重複を拒否する。

    引数: frozen (dict) 事前カタログ、metadata (list[dict]) 全仕様、sessions (list[str]) 区間。
    返り値: 全候補データ配列と読取ハッシュ記録 (tuple[ndarray,list[dict]])。
    """
    ids = [item['id'] for item in metadata]
    positions = {identifier: i for i, identifier in enumerate(ids)}
    session_positions = {session: i for i, session in enumerate(sessions)}
    cube = np.full((len(ids), len(sessions), len(SYMBOLS), len(FIELDS)), np.nan)
    seen = set()
    manifests = []
    expected_managers = {item['id'] for item in frozen['managers']}
    for signal in frozen['signals']:
        path = WORK / 'sessions' / (signal['id'] + '.json.gz')
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        items = json.loads(gzip.decompress(content).decode('utf-8'))
        assert len(items) == len(expected_managers)
        assert {item['id'].split('__', 1)[1] for item in items} == expected_managers
        for item in items:
            identifier = item['id']
            assert identifier.startswith(signal['id'] + '__') and identifier not in seen
            seen.add(identifier)
            assert len(item['rows']) == len(sessions) * len(SYMBOLS)
            seen_rows = set()
            for row in item['rows']:
                key = row['session'], row['symbol']
                assert row['id'] == identifier and key not in seen_rows
                seen_rows.add(key)
                cube[positions[identifier], session_positions[key[0]], SYMBOLS.index(key[1])] = row_array(row)
        manifests.append({'相対パス': path.relative_to(WORK).as_posix(), 'SHA256': hashlib.sha256(content).hexdigest(),
                          '候補数': len(items), 'バイト数': len(content)})
    assert seen == set(ids) and np.isfinite(cube).all()
    return cube, manifests


def aggregate(rows: list[dict]) -> dict:
    """機能: 選ばれた期間だけの全玉損益、枚数、時価下落を合算する。

    引数: rows (list[dict]) 同一銘柄の完了区間集計。
    返り値: 合計・比率・最大勝ち除外・活動等 (dict)。
    """
    result = {key: sum(row[key] for row in rows) for key in SUM_FIELDS}
    gp, gl = result['gross_profit_yen'], result['gross_loss_yen']
    pu, lu = result['profit_units'], result['loss_units']
    result['money_ratio'] = gp / gl if gl > 1e-8 else None
    result['average_unit_payoff'] = (gp / pu) / (gl / lu) if pu and lu and gl > 1e-8 else None
    result['cycle_ratio'] = result['cycle_profit_yen'] / result['cycle_loss_yen'] if result['cycle_loss_yen'] > 1e-8 else None
    cash = high = dd = 0.
    for row in sorted(rows, key=lambda item: item['session']):
        dd = max(dd, row['drawdown_yen'], high - (cash + row['min_equity_yen']))
        high = max(high, cash + row['max_equity_yen'])
        cash += row['net_yen']
    cycles_known = all('two_largest_cycle_profits' in row for row in rows)
    wins = sorted((v for row in rows for v in row.get('two_largest_cycle_profits', [])), reverse=True)
    best_sessions = sorted((max(0., row['net_yen']) for row in rows), reverse=True)
    result.update(
        drawdown_yen=dd, win_sessions=sum(row['net_yen'] > 0 for row in rows),
        active_sessions=sum(row['cycles'] > 0 for row in rows), session_count=len(rows),
        best_cycle_removed_net=result['net_yen'] - sum(wins[:1]) if cycles_known else None,
        two_cycles_removed_net=result['net_yen'] - sum(wins[:2]) if cycles_known else None,
        best_session_removed_net=result['net_yen'] - sum(best_sessions[:1]),
        two_sessions_removed_net=result['net_yen'] - sum(best_sessions[:2]),
        unit_balance=pu-lu, worst_session=min((row['net_yen'] for row in rows), default=0),
        max_long=max((row['max_long'] for row in rows), default=0),
        max_short=max((row['max_short'] for row in rows), default=0),
        longest_session_losing_streak=max((row['longest_losing_streak'] for row in rows), default=0),
    )
    return result


def report_series(rows: list[dict]) -> dict:
    """機能: 同じ次７区間について全期間・週・日夜・セッション別の報告を作る。

    引数: rows (list[dict]) 二銘柄の区間集計。
    返り値: 集計と全明細 (dict)。
    """
    periods, weeks, day_night = {}, {}, {}
    for symbol in SYMBOLS:
        own = [row for row in rows if row['symbol'] == symbol]
        periods[symbol] = aggregate(own)
        groups = defaultdict(list)
        for row in own:
            iso = date.fromisoformat(row['session'][:10]).isocalendar()
            groups[f'{iso.year}年第{iso.week}週'].append(row)
        weeks[symbol] = {key: aggregate(value) for key, value in groups.items()}
        day_night[symbol] = {part: aggregate([row for row in own if row['session'].endswith(suffix)])
                             for part, suffix in [('日中', '_Day'), ('夜間', '_Night')]}
    return {'全評価期間': periods, '週別': weeks, '日中夜間': day_night, 'セッション別': rows}


def self_test() -> dict:
    """機能: 合成集計で同点、活動、除外、週境界と未来改変不変を検査する。

    引数: なし。
    返り値: 検査内容 (dict)。実探索の損益は読まない。
    """
    sessions = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day', '2026-09-22_Night',
                '2026-09-23_Day', '2026-09-23_Night', '2026-09-24_Day', '2026-09-24_Night',
                '2026-09-25_Day', '2026-09-25_Night', '2026-09-28_Day', '2026-09-28_Night', '2026-09-29_Day']
    ids = ['A00', 'A01', FALLBACK]
    complexity = np.ones(3, dtype=np.int64)
    cube = np.zeros((3, 13, 2, len(FIELDS)))
    for name, value in [('gross_profit_yen', 200.), ('gross_loss_yen', 100.), ('net_yen', 100.),
                        ('profit_units', 1), ('loss_units', 1), ('cycles', 2),
                        ('top_cycle_1', 200.)]:
        cube[:, :, :, INDEX[name]] = value
    baseline = choose_before(cube, sessions, 6, complexity, ids)
    assert ids[baseline['selected_index']] == 'A00'
    assert baseline['passed'].all()
    assert baseline['metrics']['two_cycles_removed_net'][0, 0] == 200.
    assert '2026年第40週収支' not in baseline['metrics']
    cube[1, 10:, :, INDEX['gross_profit_yen']] = 1e12
    cube[1, 10:, :, INDEX['net_yen']] = 1e12
    compare_choices(baseline, choose_before(cube, sessions, 6, complexity, ids))
    compare_choices(baseline, choose_before(cube[:, :6], sessions[:6], 6, complexity, ids))
    inactive = cube.copy()
    inactive[:, :6, :, INDEX['cycles']] = 0
    result = choose_before(inactive, sessions, 6, complexity, ids)
    assert not result['passed'].any() and ids[result['selected_index']] == FALLBACK
    loss = cube.copy()
    loss[:, :6, :, INDEX['gross_loss_yen']] = 250.
    result = choose_before(loss, sessions, 6, complexity, ids)
    assert not result['passed'].any()
    return {'合成検査合格': True, '検査': ['同点ID昇順', '最大2組除外の算式', '未知週を入口へ含めない',
            '未来成績改変不変', '未来成績削除不変', '不稼働候補の排除と固定fallback', 'PF不合格'],
            '実探索の成績を使用': False}


def run() -> dict:
    """機能: 凍結後かつ探索完了後に全候補から７回選択し、反証監査と結果を保存する。

    引数: なし。
    返り値: 時間順選択結果 (dict)。新たな売買パラメータ調整は行わない。
    """
    assert (WORK / 'sequential_selection_fixed.json').exists(), '先に--prepareで仕様を凍結してください'
    fixed = prepare()
    completion_path = WORK / '反証前の候補固定.json'
    assert completion_path.exists(), '全探索の完了記録がまだありません'
    completion = read(completion_path)
    assert completion['全条件数'] == fixed['対象候補数']
    frozen = read(WORK / '探索条件の固定.json')
    metadata, complexity = catalog_metadata(frozen)
    ids = [item['id'] for item in metadata]
    sessions = fixed['セッション一覧']
    cube, manifests = load_library(frozen, metadata, sessions)
    save(WORK / 'sequential_selection_inputs.json', {'読取時刻': now(), '全候補数': len(ids),
         '新探索成績の読取は選択仕様凍結後': True, 'ファイル': manifests,
         '完了記録SHA256': digest(completion_path), '評価に使った全行数': len(ids) * len(sessions) * len(SYMBOLS)})
    folds, chosen_rows, fallback_rows, audit = [], [], [], []
    for cut in range(INITIAL, len(sessions)):
        result = choose_before(cube, sessions, cut, complexity, ids)
        # ----------------------------------------
        # 評価する現在区間を含め、それ以降の全候補値の改変・削除で選択が不変か検算する。
        truncated = choose_before(cube[:, :cut], sessions[:cut], cut, complexity, ids)
        compare_choices(result, truncated)
        changed = cube.copy()
        changed[:, cut:, :, :] = 987654321.
        changed[:, cut:, :, INDEX['net_yen']] = -123456789.
        altered = choose_before(changed, sessions, cut, complexity, ids)
        compare_choices(result, altered)
        del changed, truncated, altered
        selected = result['selected_index']
        next_rows = [array_row(cube, selected, cut, j, ids, sessions) for j in range(len(SYMBOLS))]
        for row in next_rows:
            row['選択工程ID'] = STRATEGY_ID
        chosen_rows.extend(next_rows)
        fallback_rows.extend(array_row(cube, ids.index(FALLBACK), cut, j, ids, sessions) for j in range(len(SYMBOLS)))
        order_hash = hashlib.sha256('\n'.join(ids[int(i)] for i in result['order']).encode()).hexdigest()
        selection_time = fixed['観測境界'][sessions[cut]]['最初の観測秒']
        latest_history = fixed['観測境界'][sessions[cut-1]]['最後の観測秒']
        assert latest_history < selection_time
        reasons = {symbol: {name: int((~values[:, j]).sum()) for name, values in result['checks'].items()}
                   for j, symbol in enumerate(SYMBOLS)}
        folds.append({
            'fold': cut - INITIAL + 1, '過去セッション数': cut, '過去セッション': sessions[:cut],
            '評価セッション': sessions[cut],
            '判断時刻': datetime.fromtimestamp(selection_time, JST).isoformat(),
            '過去入力の最終時刻': datetime.fromtimestamp(latest_history, JST).isoformat(),
            '評価した候補数': len(ids), '過去入口合格数': int(result['passed'].sum()),
            '理由別不合格候補数_重複あり': reasons, '全順位SHA256': order_hash,
            '採用ID': ids[selected], 'fallback': not bool(result['passed'].any()),
            'fallback理由': '全カタログに過去入口を満たす候補なし' if not result['passed'].any() else None,
            '採用候補の過去検査': candidate_diagnostic(result, selected, metadata),
            '過去入口合格の上位10': [candidate_diagnostic(result, int(index), metadata) for index in result['eligible'][:10]],
            '次セッション結果': next_rows,
        })
        audit.append({'fold': cut - INITIAL + 1, '全候補数': len(ids), '未来削除で全検査全順位採用不変': True,
                      '未来損益枚数全値改変で全検査全順位採用不変': True,
                      '過去完了時刻が判断時刻より前': True, '同じIDを両銘柄へ採用': True})
        print(f"時間順選択 {cut - INITIAL + 1}/7 完了", flush=True)
    old = next(item for item in read(PREVIOUS / '枝除去と感度.json') if item['id'] == '基準_X05')
    x05_rows = [row for row in old['rows'] if row['session'] in sessions[INITIAL:]]
    assert len(chosen_rows) == len(fallback_rows) == len(x05_rows) == 14
    series = report_series(chosen_rows)
    checks = {}
    for symbol, summary in series['全評価期間'].items():
        checks[symbol] = {
            '次7区間収支が正': summary['net_yen'] > 0,
            '次7区間PF1.10以上': (summary['money_ratio'] or 0) >= 1.10,
            '次7区間平均勝ち負け比1.10以上': (summary['average_unit_payoff'] or 0) >= 1.10,
            '活動4区間以上': summary['active_sessions'] >= 4,
            '最大1勝ち組除外後0以上': summary['best_cycle_removed_net'] >= 0,
            '最大1黒字区間除外後0以上': summary['best_session_removed_net'] >= 0,
        }
    output = {
        '作成時刻': now(), '仕様凍結SHA256': digest(WORK / 'sequential_selection_fixed.json'),
        '全カタログ候補数': len(ids), '各foldで全候補を評価': True,
        '上位候補へ絞り込んでいない': True, '選択工程ID': STRATEGY_ID,
        '最初6区間は評価損益から除外': True, '評価セッション': sessions[INITIAL:],
        '採用回数': dict(Counter(item['採用ID'] for item in folds)),
        'fallback回数': sum(item['fallback'] for item in folds),
        'folds': folds, '選択工程結果': series,
        '同じ7区間の固定基準': {FALLBACK: report_series(fallback_rows), 'X05_G08': report_series(x05_rows)},
        '工程の数値判定': checks,
        '工程の数値判定合格': all(all(values.values()) for values in checks.values()),
        '判定の留保': '数値判定はこの工程の研究候補の一条件。別途の遅延・近傍・会計等を未実行なら全反証合格ではない。',
        '既知性': fixed['既知性'], '数量': fixed['数量'],
        '連敗の意味': '報告値はセッション内最長。日をまたいだ売買組の連敗はこの集計から復元していない。',
        '固定X05の最大勝ち組除外': '過去の軽量集計に2位までの組利益がないため本出力ではnull。',
        'API取得数': 0, '旧コード原本変更': False,
    }
    save(WORK / 'sequential_selection_audit.json', {'時刻': now(), '合成検査': self_test(),
         '実データ監査': audit, '合計比較数': len(audit) * 2,
         '比較範囲': '各比較で全36668候補の全過去検査、採否、全順位、採用を照合。',
         '全合格': True, '未来区間の注文成績を選択に使っていない': True})
    save(WORK / 'sequential_selection_result.json', output)
    return output


def main() -> None:
    """機能: 成績未読の凍結・合成検査と、探索完了後の評価を明確に分ける。

    引数: コマンドラインのprepare/self-test/run (bool)。
    返り値: なし (None)。指定がない場合は合成検査だけを行う。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.run:
        result = run()
        print(json.dumps({'評価区間数': len(result['評価セッション']), '全候補数': result['全カタログ候補数'],
                          '出力': 'sequential_selection_result.json'}, ensure_ascii=False))
    else:
        test = self_test()
        save(WORK / 'sequential_selection_self_test.json', test)
        if args.prepare:
            frozen = prepare()
            print(json.dumps({'固定時刻': frozen['固定時刻'], '候補数': frozen['対象候補数'],
                              '実探索成績を未読': True, '合成検査合格': test['合成検査合格']}, ensure_ascii=False))
        else:
            print(json.dumps(test, ensure_ascii=False))


if __name__ == '__main__':
    main()
