"""D016__D065を変更せず、独立会計、利益集中、基準差と相手情報の寄与を監査する。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import gzip
import hashlib
import json
import pickle
import sys

import numpy as np


WORK = Path(__file__).resolve().parent
OLD = WORK.parent / 'wave_v23'
PREVIOUS = WORK.parent / 'wave_v24'
sys.path.insert(0, str(OLD))
import engine
import managers
from audit_core import check_accounting

SYMBOLS = ['TOPIX', 'NK225']
IDENTIFIER = 'D016__D065'
SEED = 20260930
REPEATS = 5000
JST = timezone(timedelta(hours=9))


def read(path: Path) -> object:
    """機能: 保存済みの通常JSONまたは圧縮JSONを読む。

    引数: path (Path) 対象。
    返り値: JSON内容 (object)。
    """
    content = path.read_bytes()
    if path.suffix == '.gz':
        content = gzip.decompress(content)
    return json.loads(content.decode('utf-8'))


def digest(path: Path) -> str:
    """機能: 読み取り専用で依存ファイルのSHA256を取得する。

    引数: path (Path) 対象。
    返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while part := stream.read(8 * 1024 * 1024):
            value.update(part)
    return value.hexdigest()


def divide(a: float, b: float) -> float | None:
    """機能: 分母が正の場合だけ比率を計算する。

    引数: a/b (float) 分子と分母。
    返り値: 比率またはNone (float|None)。
    """
    return float(a / b) if b > 1e-8 else None


def totals(rows: list[dict]) -> dict:
    """機能: 決済枚数と金額を、銘柄を混ぜずに合算する。

    引数: rows (list[dict]) セッションまたは売買方向の集計。
    返り値: 金額、枚数、PF、１枚平均勝ち負け比 (dict)。
    """
    keys = ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'cycles']
    result = {key: sum(row[key] for row in rows) for key in keys}
    result['money_ratio'] = divide(result['gross_profit_yen'], result['gross_loss_yen'])
    mean_win = divide(result['gross_profit_yen'], result['profit_units'])
    mean_loss = divide(result['gross_loss_yen'], result['loss_units'])
    result['average_unit_payoff'] = divide(mean_win, mean_loss) if mean_win is not None and mean_loss else None
    result['unit_balance'] = result['profit_units'] - result['loss_units']
    return result


def trade_totals(trades: list[dict]) -> dict:
    """機能: 全返済明細から、利益玉と損失玉を独立に集計する。

    引数: trades (list[dict]) 組番号・枚数・損益を持つ明細。
    返り値: 金額、枚数、売買組数 (dict)。
    """
    result = {
        'gross_profit_yen': sum(max(0., row['損益円']) for row in trades),
        'gross_loss_yen': -sum(min(0., row['損益円']) for row in trades),
        'net_yen': sum(row['損益円'] for row in trades),
        'profit_units': sum(row['枚数'] for row in trades if row['損益円'] > 1e-6),
        'loss_units': sum(row['枚数'] for row in trades if row['損益円'] < -1e-6),
        'zero_units': sum(row['枚数'] for row in trades if abs(row['損益円']) <= 1e-6),
        'cycles': len({(row['セッション'], row['組番号']) for row in trades}),
    }
    return totals([result])


def replay(signal_id: str, spec: dict, inputs: dict, expected_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """機能: 保存方向と凍結管理を再生し、全行現金・在庫と原集計を独立照合する。

    引数: signal_id (str)、spec (dict) 管理、inputs (dict) 原本処理済入力、expected_rows (list[dict]) 元集計。
    返り値: 売買明細、全26区間の会計監査 (tuple[list[dict],list[dict]])。
    """
    expected = {(row['session'], row['symbol']): row for row in expected_rows}
    trades, audits = [], []
    with np.load(WORK / 'directions' / (signal_id + '.npz')) as archive:
        assert {tuple(name.split('|')) for name in archive.files} == set(inputs)
        for key, ready in inputs.items():
            direction = archive['|'.join(key)]
            config = managers.make_config(spec, key[1], ready)
            result = engine.run(ready, direction, config, detail=True)
            check = check_accounting(ready, result, config)
            assert check['最大買い枚数'] <= 1 and check['最大売り枚数'] <= 1
            if signal_id == 'D016':
                orders = result['orders']
                opening = orders[:, 7] == 1
                np.testing.assert_allclose(orders[opening, 5], ready['last'][orders[opening, 0].astype(int)], rtol=0, atol=1e-8)
            own = []
            for trade in result['trades']:
                side, qty, entry, exit_price = int(trade[2]), int(trade[3]), float(trade[4]), float(trade[5])
                entry_row, exit_row = int(trade[6]), int(trade[7])
                value = side * qty * (exit_price - entry) * config['point_value']
                assert abs(value - trade[10] * config['point_value']) < 1e-6
                own.append({'セッション': key[0], '銘柄': key[1], '組番号': int(trade[0]),
                            '方向': 'ロング' if side > 0 else 'ショート', '枚数': qty,
                            '建値': entry, '返済値': exit_price, '損益円': float(value),
                            '新規行': entry_row, '返済行': exit_row,
                            '新規時刻': datetime.fromtimestamp(float(ready['time_s'][entry_row]), JST).isoformat(),
                            '返済時刻': datetime.fromtimestamp(float(ready['time_s'][exit_row]), JST).isoformat(),
                            '保有分': float((ready['time_s'][exit_row] - ready['time_s'][entry_row]) / 60),
                            '返済理由番号': int(trade[9])})
            actual = trade_totals(own)
            for field in ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'cycles']:
                assert abs(actual[field] - expected[key][field]) < .01, (signal_id, key, field)
            trades.extend(own)
            audits.append({'信号': signal_id, 'セッション': key[0], '銘柄': key[1], **check,
                           '元集計の金額枚数一致': True, '円倍率': config['point_value']})
    return trades, audits


def partition(rows: list[dict], key_function) -> dict:
    """機能: 開始日・日中夜間・週などに分類し、同じ銘柄だけで集計する。

    引数: rows (list[dict]) 区間集計、key_function (callable) 分類キー。
    返り値: 銘柄→分類→金額枚数集計 (dict)。
    """
    output = {}
    for symbol in SYMBOLS:
        groups = defaultdict(list)
        for row in rows:
            if row['symbol'] == symbol:
                groups[key_function(row)].append(row)
        output[symbol] = {key: totals(value) for key, value in sorted(groups.items())}
    return output


def week_key(row: dict) -> str:
    """機能: 夜間もセッション開始日のISO週へ所属させる。

    引数: row (dict) 区間集計。
    返り値: ISO週の表示 (str)。
    """
    iso = date.fromisoformat(row['session'][:10]).isocalendar()
    return f'{iso.year}年第{iso.week}週'


def exclusions(rows: list[dict], trades: list[dict]) -> dict:
    """機能: 最大１・２勝ちの売買組、セッション、開始日をそれぞれ除外する。

    引数: rows (list[dict]) 区間集計、trades (list[dict]) 全返済明細。
    返り値: 除外対象・残収支・残PF (dict)。
    """
    output = {}
    for symbol in SYMBOLS:
        own = [row for row in rows if row['symbol'] == symbol]
        groups = {
            'セッション': {row['session']: totals([row]) for row in own},
            '開始日': partition(own, lambda row: row['session'][:10])[symbol],
        }
        grouped_trades = defaultdict(list)
        for trade in trades:
            if trade['銘柄'] == symbol:
                grouped_trades[f"{trade['セッション']}#{trade['組番号']}"] .append(trade)
        groups['売買組'] = {key: trade_totals(value) for key, value in grouped_trades.items()}
        total = totals(own)
        result = {}
        for kind, values in groups.items():
            wins = sorted(((key, value) for key, value in values.items() if value['net_yen'] > 0),
                          key=lambda item: (-item[1]['net_yen'], item[0]))
            for n in [1, 2]:
                dropped = wins[:n]
                residual = {field: total[field] - sum(value[field] for _, value in dropped)
                            for field in ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'cycles']}
                result[f'最大{n}{kind}除外'] = {
                    '除外': [{'対象': key, '損益円': value['net_yen']} for key, value in dropped],
                    '残成績': totals([residual]),
                    '除外純益の全純益比': divide(sum(value['net_yen'] for _, value in dropped), total['net_yen']),
                }
        output[symbol] = result
    return output


def interval(values: np.ndarray) -> dict:
    """機能: 再抽出値の中央95%区間と欠損件数を記録する。

    引数: values (ndarray) 再抽出値。
    返り値: 下側2.5%、中央値、上側97.5%等 (dict)。
    """
    valid = values[np.isfinite(values)]
    lower, middle, upper = np.quantile(valid, [.025, .5, .975]) if len(valid) else (None, None, None)
    return {'下側2_5': float(lower) if lower is not None else None,
            '中央': float(middle) if middle is not None else None,
            '上側97_5': float(upper) if upper is not None else None,
            '標本数': len(values), '有限標本数': len(valid), '非定義数': len(values) - len(valid)}


def bootstrap(series: dict[str, list[dict]]) -> dict:
    """機能: 全銘柄・全比較へ共通の開始日ブロックを使って差を再抽出する。

    引数: series (dict[str,list[dict]]) 基準候補と比較集計。
    返り値: 5000回の差区間、同日除外、相関を含む診断 (dict)。
    """
    days = sorted({row['session'][:10] for row in series[IDENTIFIER]})
    assert len(days) == 7
    generator = np.random.default_rng(SEED)
    sampled = generator.integers(0, len(days), size=(REPEATS, len(days)))
    counts = np.asarray([(sampled == i).sum(axis=1) for i in range(len(days))]).T
    matrices = {}
    for name, rows in series.items():
        data = np.zeros((len(days), len(SYMBOLS), 3))
        for row in rows:
            data[days.index(row['session'][:10]), SYMBOLS.index(row['symbol'])] += [row['net_yen'], row['gross_profit_yen'], row['gross_loss_yen']]
        matrices[name] = data
    resampled = {name: np.einsum('bd,dsf->bsf', counts, data) for name, data in matrices.items()}
    result = {'seed': SEED, '反復数': REPEATS, '開始日': days, '共通抽出添字SHA256': hashlib.sha256(sampled.tobytes()).hexdigest(),
              '単位': '開始日。両銘柄と全比較対象へ同じ抽出添字。', '比較': {}, '基準候補の収支区間': {}}
    own = matrices[IDENTIFIER]
    bs = resampled[IDENTIFIER]
    for j, symbol in enumerate(SYMBOLS):
        result['基準候補の収支区間'][symbol] = interval(bs[:, j, 0])
    for name, other in matrices.items():
        if name == IDENTIFIER:
            continue
        other_bs = resampled[name]
        comparison = {}
        for j, symbol in enumerate(SYMBOLS):
            net_diff = bs[:, j, 0] - other_bs[:, j, 0]
            first_pf = np.divide(bs[:, j, 1], bs[:, j, 2], out=np.full(REPEATS, np.nan), where=bs[:, j, 2] > 1e-8)
            other_pf = np.divide(other_bs[:, j, 1], other_bs[:, j, 2], out=np.full(REPEATS, np.nan), where=other_bs[:, j, 2] > 1e-8)
            first = own[:, j].sum(axis=0)
            second = other[:, j].sum(axis=0)
            comparison[symbol] = {
                '実測収支差円': float(first[0] - second[0]),
                '実測PF差': divide(first[1], first[2]) - divide(second[1], second[2]),
                '収支差の中央95%区間': interval(net_diff), 'PF差の中央95%区間': interval(first_pf - other_pf),
                '一開始日除外後の収支差円': {day: float((own[:, j, 0] - other[:, j, 0]).sum() - (own[k, j, 0] - other[k, j, 0])) for k, day in enumerate(days)},
            }
        comparison['両銘柄で同時に差が正の再標本割合'] = float(np.mean(((bs[:, :, 0] - other_bs[:, :, 0]) > 0).all(axis=1)))
        comparison['日次差の二銘柄相関'] = float(np.corrcoef((own[:, :, 0] - other[:, :, 0]).T)[0, 1])
        result['比較'][name] = comparison
    result['制限'] = [
        '候補は36,668条件と後続反証を見て選んでおり、探索バイアス未補正。正式有意確率ではない。',
        '７開始日だけで独立性は保証されない。夜間は翌暦日へ続き、9/29は昼のみ。',
        '標本割合を将来利益の確率や優越確率と解釈しない。差の区間が０を含まなくても真未見の優位性とは主張しない。',
    ]
    return result


def yen(value: float) -> str:
    """機能: 符号付き金額を短い表へ整える。

    引数: value (float) 円額。
    返り値: 表示文字列 (str)。
    """
    return f'{value:+,.0f}'


def markdown(output: dict) -> str:
    """機能: 検証値から短い日本語の結論表を作る。

    引数: output (dict) 全監査値。
    返り値: Markdown本文 (str)。
    """
    lines = ['# D016__D065の独立反証', '',
             '**台帳・全行現金の独立検算で黒字を再現した。最大２勝ちを除いても両銘柄で黒字が残る。ただし、両市場情報が両銘柄に必要とは言えない。**', '',
             '全13セッション・７開始日は既知。各１枚、費用０、指定価格約定。条件の改訂・最適化・現在API取得は行っていない。', '',
             '| 同じ13区間 | TOPIX収支 / PF | NK収支 / PF |', '|---|---:|---:|']
    for name in [IDENTIFIER, 'F32_G08', 'X05_G08', 'D016_SELF_PEER']:
        a, b = (output['全期間比較'][name][symbol] for symbol in SYMBOLS)
        lines.append(f"| {name} | {yen(a['net_yen'])}円 / {a['money_ratio']:.3f} | {yen(b['net_yen'])}円 / {b['money_ratio']:.3f} |")
    lines += ['', '自己系列版は、相手の特徴を同じ60秒遅延の自銘柄特徴で置き換えた対照。確認条件をなくしたものではない。相手を全て０にして売買も０になる対照は、相手情報の有用性を証明しない。', '',
              '| 基準候補の集中度 | TOPIX | NK |', '|---|---:|---:|']
    for label, key in [('最大２勝ち組除外', '最大2売買組除外'), ('最大２黒字セッション除外', '最大2セッション除外'), ('最大２黒字開始日除外', '最大2開始日除外')]:
        a, b = (output['最大勝ち除外'][IDENTIFIER][symbol][key]['残成績']['net_yen'] for symbol in SYMBOLS)
        lines.append(f'| {label} | {yen(a)}円 | {yen(b)}円 |')
    for label, field in [('日中', '日中'), ('夜間', '夜間')]:
        a, b = (output['日中夜間'][IDENTIFIER][symbol][field]['net_yen'] for symbol in SYMBOLS)
        lines.append(f'| {label}収支 | {yen(a)}円 | {yen(b)}円 |')
    for week in ['2026年第39週', '2026年第40週']:
        a, b = (output['週別'][IDENTIFIER][symbol][week]['net_yen'] for symbol in SYMBOLS)
        lines.append(f'| {week} | {yen(a)}円 | {yen(b)}円 |')
    lines += ['', '| 勝ち方向の分解 | TOPIX | NK |', '|---|---:|---:|']
    for side in ['ロング', 'ショート']:
        a, b = (output['ロングショート'][IDENTIFIER][symbol][side]['net_yen'] for symbol in SYMBOLS)
        lines.append(f'| {side}収支 | {yen(a)}円 | {yen(b)}円 |')
    lines += ['', '| D016基準 − 比較対象：同日bootstrap差区間 | TOPIX（円） | NK（円） |', '|---|---:|---:|']
    for reference, values in output['対応開始日bootstrap']['比較'].items():
        cells = []
        for symbol in SYMBOLS:
            point = values[symbol]['実測収支差円']
            span = values[symbol]['収支差の中央95%区間']
            cells.append(f"{yen(point)}［{yen(span['下側2_5'])}〜{yen(span['上側97_5'])}］")
        lines.append(f'| {reference} | {cells[0]} | {cells[1]} |')
    lines += ['', '７開始日を両銘柄・全比較対象へ共通に5,000回再抽出した記述的診断。探索後バイアスは補正しておらず、独立性も保証されない。正式な有意確率でも未知相場の証明でもない。', '',
              '**黒字全体と、既存手法への上積みは区別する。** F32に対するTOPIXの上積み＋31,500円は9/29を除くと−8,500円、NKの上積み＋5,300円は9/24を除くと−2,100円へ反転する。最大２勝ちを除いても基準候補自体は黒字だが、F32を上回った部分の分散はまだ弱い。', '',
              'TOPIXでは他市場参照を自己系列へ換えると収支が大きく悪化し、この期間では相手情報を使う選別の寄与と整合する。NKは自己系列版の収支・PFが上回るため、「両市場の確認がNKにも必要」とは言えない。変更によって注文時刻・保有・再注文も変わるため、差額を情報単独の機械的な利益へ分解することもできない。', '',
              'NKの後半３区間の利益が小さい点も残る。前半と後半で寄与が入れ替わっており、同じ１週間内の複数パターンに耐えた事実と、今後も同じ頻度・利益を維持するかは別である。', '',
              '詳細・全セッションの金額と枚数・全返済明細・一日除外・PF差区間は `d016_statistical_audit.json`。再生コードは `d016_statistical_audit.py`。']
    return '\n'.join(lines) + '\n'


def main() -> None:
    """機能: 凍結済み候補を再生し、既存対照との独立監査だけを保存する。

    引数: なし。
    返り値: なし (None)。書込はこの作業の監査JSONとMarkdownだけ。
    """
    dependencies = [Path(__file__), WORK / '探索条件の固定.json', WORK / 'adversarial' / (IDENTIFIER + '.json.gz'),
                    WORK / 'directions/D016.npz', WORK / 'directions/F32.npz', OLD / 'engine.py', OLD / 'managers.py',
                    OLD / 'audit_core.py', OLD / 'inputs.pkl', PREVIOUS / '枝除去と感度.json', PREVIOUS / 'branch_attribution.json']
    before = {p.relative_to(WORK.parent).as_posix(): digest(p) for p in dependencies}
    candidate = read(WORK / 'adversarial' / (IDENTIFIER + '.json.gz'))
    variants = {item['case']: item for item in candidate['cases']}
    catalog = read(WORK / '探索条件の固定.json')
    spec = next(item for item in catalog['managers'] if item['id'] == 'D065')
    standard = next(item for item in catalog['managers'] if item['id'] == 'G08')
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    own_trades, own_checks = replay('D016', spec, inputs, variants['基準再現']['rows'])
    f32_trades, f32_checks = replay('F32', standard, inputs, variants['固定F32_G08']['rows'])
    print('固定候補とF32の52区間・全行会計の再生照合が完了', flush=True)
    old_x05 = next(item for item in read(PREVIOUS / '枝除去と感度.json') if item['id'] == '基準_X05')
    old_trades = read(PREVIOUS / 'branch_attribution.json')['全取引']
    x05_trades = [dict(row, 方向='ロング' if row['方向'] == '買い' else 'ショート') for row in old_trades]
    series = {IDENTIFIER: variants['基準再現']['rows'], 'F32_G08': variants['固定F32_G08']['rows'],
              'X05_G08': old_x05['rows'], 'D016_SELF_PEER': variants['D016_SELF_PEER']['rows']}
    trade_sets = {IDENTIFIER: own_trades, 'F32_G08': f32_trades, 'X05_G08': x05_trades}
    for name, trades in trade_sets.items():
        for symbol in SYMBOLS:
            actual = trade_totals([row for row in trades if row['銘柄'] == symbol])
            expected = totals([row for row in series[name] if row['symbol'] == symbol])
            for field in ['gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'cycles']:
                assert abs(actual[field] - expected[field]) < .01, (name, symbol, field)
    longshort = {name: {symbol: {side: trade_totals([row for row in trades if row['銘柄'] == symbol and row['方向'] == side])
                                            for side in ['ロング', 'ショート']} for symbol in SYMBOLS}
                 for name, trades in trade_sets.items()}
    removed = {name: exclusions(series[name], trades) for name, trades in trade_sets.items()}
    for symbol in SYMBOLS:
        original = candidate['candidate']['symbols'][symbol]
        for kind, field in [('売買組', 'two_cycles_removed_net'), ('セッション', 'two_sessions_removed_net'), ('開始日', 'two_start_days_removed_net')]:
            assert removed[IDENTIFIER][symbol]['最大2' + kind + '除外']['残成績']['net_yen'] == original[field]
    after = {p.relative_to(WORK.parent).as_posix(): digest(p) for p in dependencies}
    assert before == after
    output = {
        '記録時刻': datetime.now(JST).isoformat(), '対象': IDENTIFIER, '条件の変更と最適化': False,
        '前提': '13セッション・７開始日、各１枚、費用０・指定価格約定。NKは1pt=10円、TOPIXミニは1pt=1000円。',
        '期間の既知性': '候補は36,668条件と反証結果の後に選ばれた。全13区間既知で未見OOSではない。',
        '依存SHA256': before, '旧ファイル変更なし': before == after, 'API取得数': 0,
        '会計監査': {'全合格': True, '再生区間数': len(own_checks) + len(f32_checks),
                    '全行検算数': sum(row['全行検算'] for row in own_checks + f32_checks),
                    'D016新規は次観測の実価格': True, '銘柄ごと最大１枚': True,
                    'D016': own_checks, 'F32': f32_checks, 'X05': '保存済み93取引から金額・枚数・組数を独立合算して元の全26区間と照合。'},
        '全期間比較': {name: {symbol: totals([row for row in rows if row['symbol'] == symbol]) for symbol in SYMBOLS} for name, rows in series.items()},
        'セッション別': {name: partition(rows, lambda row: row['session']) for name, rows in series.items()},
        '開始日別': {name: partition(rows, lambda row: row['session'][:10]) for name, rows in series.items()},
        '日中夜間': {name: partition(rows, lambda row: '日中' if row['session'].endswith('_Day') else '夜間') for name, rows in series.items()},
        '週別': {name: partition(rows, week_key) for name, rows in series.items()},
        'ロングショート': longshort, '最大勝ち除外': removed,
        '対応開始日bootstrap': bootstrap(series),
        '全返済明細': trade_sets,
        '相手情報の解釈': {
            '自己系列対照': '相手特徴だけを同じ60秒遅延の自銘柄特徴へ置換。ゲート削除ではない。',
            'TOPIX': '自己系列版は−42000円、基準+134500円。既知期間では他市場情報による取引選別の寄与と整合。普遍的必要性までは示さない。',
            'NK225': '自己系列版は+24300円・PF2.642、基準+22400円・PF2.445。両市場が必要とは言えず、他市場情報の追加価値もこの対照では確認できない。',
            '中立化対照': '相手を全て０にするとAND条件のため信号と売買が０。設計上の必須入力であることを示すだけで、情報の予測価値の証明ではない。',
            '寄与差額の制限': '相手変更によって入口時刻、保有期間、返済、再注文まで変わる。取引を同一に保った情報の独立効果ではない。',
        },
        '一次反証の範囲': '保存済み22条件での結果。今回の監査で近傍条件を変更・追加して最良候補へ置換していない。',
    }
    (WORK / 'd016_statistical_audit.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (WORK / 'd016_statistical_audit.md').write_text(markdown(output), encoding='utf-8')
    print(json.dumps({'全行会計': output['会計監査']['全行検算数'], '基準合計': output['全期間比較'][IDENTIFIER],
                      '開始日bootstrap': output['対応開始日bootstrap']['比較']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
