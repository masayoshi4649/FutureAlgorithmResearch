"""利益割合と追跡短縮を、結果前固定の全対応組で記述比較する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import gzip
import hashlib
import itertools
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

import protection_design

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
RULES = {
    '対象': '固定96入口×50管理の全4,800条件。最良・黒字・合格条件へ絞らず、同一入口のK000を基準にする。',
    '同入口差': '全4,800条件×両銘柄の差を保存。K000自身96条件は差ゼロであり、改善率の分母から明示的に除外する。各銘柄4,704比較。',
    '対応組': '同じ入口・他の全管理値を固定し、割合保護追加45、始動R増加45、保護割合増加45、追跡短縮追加40、短縮始動ATR増加20、短縮幅縮小20の215管理対応を作る。96入口×215×2銘柄=41,280比較。',
    '水準比較': '始動Rの1→2/1→3/2→3、保護割合の25→50/25→75/50→75を全て含む。追跡始動は2→3ATR、短縮幅は1.5→0.75ATR。無効状態の変数を水準比較へ混ぜない。',
    '差': '変更後−変更前。同銘柄内の収支差と含み損込みDD差を円で集計。収支差>0.01円、DD差<−0.01円を厳密改善とし、両方の改善も数える。0.01円以内は同値。',
    '重み': '各対応組を等重み。6軸の全体・具体的な水準比較・主方向6種類・EMA2速度をまとめた5思想で集計。多数の関連設定であり、改善率は未知の成功確率ではない。',
    '台帳': '保存ledger_hashは両銘柄・全26入力の結合指紋。両銘柄全台帳同一率としてのみ表示し、銘柄別の厳密な台帳率と呼ばない。銘柄別収支/DD同値は別に記す。',
    '両市場': '各対応組でTOPIX・NK225の両方が収支増かつDD減となる割合も別集計。金額を銘柄間で合算しない。',
    '記述目標': '全4,800条件について、同一入口K000比75%収支維持/80%DD以下、旧H019__D273比の同基準、両方同時達成を別計数。同入口K000は両銘柄黒字かつ正DDの入口だけを適格とし、不適格数を残す。',
    '最低基準': '上の記述件数と、保存された探索最低基準も通過する件数を分ける。一次反証・乱数・指定波合格数ではない。候補再選抜はしない。',
    '交互作用': '部分利確の時点・初期枚数は全件共通。割合と追跡を一方ずつ固定して比較し、組合せの最良例から各機構の優位を推定しない。出口変更で後続新規時刻も変わり、単一取引の純粋な出口効果とは限らない。',
    '禁止': '新売買再生・追加現在通信・既取得現在データ使用・閾値変更・候補の再選定を行わない。集計コードは新機構の結果を読む前に固定する。',
}


def read(path: Path):
    """機能: 通常又はgzipのJSONを読む。

    引数: path (Path)。返り値: 内容 (dict|list)。
    """
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        return json.load(stream)


def save(path: Path, value) -> None:
    """機能: 自作の診断だけをUTF-8で保存する。

    引数: path (Path)、value (dict|list)。返り値: なし (None)。
    """
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'wt', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def digest(path: Path) -> str:
    """機能: 参照資料と事前規則の指紋を求める。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manager_pairs(management: list[dict]) -> list[dict]:
    """機能: 他条件を厳密に一致させて215組の管理対応を作る。

    引数: management (list[dict])。返り値: 固定された対応組 (list[dict])。
    """
    assert len(management) == 50 and len({m['id'] for m in management}) == 50
    output = []
    definitions = [
        ('割合保護追加', ('lock_fraction', 'lock_activation_r'), 45),
        ('始動R増加', ('lock_activation_r',), 45),
        ('保護割合増加', ('lock_fraction',), 45),
        ('追跡短縮追加', ('tighten_atr', 'tight_width'), 40),
        ('短縮始動ATR増加', ('tighten_atr',), 20),
        ('短縮幅縮小', ('tight_width',), 20),
    ]
    for axis, fields, expected_count in definitions:
        groups = defaultdict(dict)
        for management_spec in management:
            changes = management_spec['changes']
            assert changes['residual_risk_cap'] == 0 and management_spec['context_source'] == 'entry'
            if axis in ('始動R増加', '保護割合増加') and changes['lock_fraction'] == 0:
                continue
            if axis in ('短縮始動ATR増加', '短縮幅縮小') and changes['tighten_atr'] == 0:
                continue
            option = tuple(changes[name] for name in fields)
            fixed = dict({name: value for name, value in changes.items() if name not in fields},
                         context_source=management_spec['context_source'])
            key = json.dumps(fixed, sort_keys=True)
            assert option not in groups[key], '固定機構・操作値が重複'
            groups[key][option] = management_spec['id']
        added = 0
        for fixed, options in sorted(groups.items()):
            if axis in ('割合保護追加', '追跡短縮追加'):
                baseline = (0., 1.)
                assert baseline in options
                pairs = [(baseline, option) for option in sorted(options) if option != baseline]
            else:
                pairs = list(itertools.combinations(sorted(options, reverse=axis == '短縮幅縮小'), 2))
            for before, after in pairs:
                before_values, after_values = dict(zip(fields, before)), dict(zip(fields, after))
                comparison = axis + '：' + ','.join(f'{name}={before_values[name]:g}→{after_values[name]:g}' for name in fields)
                output.append(dict(axis=axis, comparison=comparison, before=options[before], after=options[after],
                                   changed_fields=list(fields), before_values=before_values, after_values=after_values,
                                   固定管理値=json.loads(fixed)))
                added += 1
        assert added == expected_count, (axis, added)
    assert len(output) == 215
    assert len({(p['axis'], p['before'], p['after']) for p in output}) == 215
    return output


def summary(rows: list[dict]) -> dict:
    """機能: 対応差の中央値・改善率・同値率を集計する。

    引数: rows (list[dict])。返り値: 分布と件数 (dict)。
    """
    assert rows
    net, dd = (np.array([r[name] for r in rows]) for name in ('net_difference', 'dd_difference'))
    assert np.isfinite(net).all() and np.isfinite(dd).all()
    return dict(対応組数=len(rows), 収支差中央値円=float(np.median(net)), DD差中央値円=float(np.median(dd)),
                収支改善率=float(np.mean(net > .01)), DD改善率=float(np.mean(dd < -.01)),
                両改善率=float(np.mean((net > .01) & (dd < -.01))),
                収支同値率=float(np.mean(abs(net) <= .01)), DD同値率=float(np.mean(abs(dd) <= .01)),
                両銘柄全台帳同一率=float(np.mean([r['ledger_identical'] for r in rows])),
                収支差10_90百分位=np.percentile(net, [10, 90]).tolist(), DD差10_90百分位=np.percentile(dd, [10, 90]).tolist())


def group_summary(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    """機能: 固定された比較軸や思想で対応組を層別する。

    引数: rows (list[dict])、fields (tuple[str,...])。返り値: 層別集計 (list[dict])。
    """
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[field] for field in fields)].append(row)
    return [dict(zip(fields, key), **summary(group)) for key, group in sorted(groups.items())]


def validate_candidates(candidates: list[dict], fixed: dict) -> dict:
    """機能: 全組合せの欠落・重複・非有限値を拒否する。

    引数: candidates (list[dict])、fixed (dict)。返り値: ID辞書 (dict)。
    """
    expected = {s['id'] + '__' + m['id'] for s in fixed['signals'] for m in fixed['managers']}
    lookup = {c['id']: c for c in candidates}
    assert len(candidates) == len(lookup) == len(expected) == 4800
    assert set(lookup) == expected
    for identifier, row in lookup.items():
        assert identifier == row['signal_id'] + '__' + row['manager_id']
        assert set(row['symbols']) == set(SYMBOLS) and isinstance(row['failures'], list)
        assert len(row['ledger_hash']) == 64 and all(c in '0123456789abcdef' for c in row['ledger_hash'])
        for symbol in SYMBOLS:
            value = row['symbols'][symbol]
            assert np.isfinite([value['net_yen'], value['drawdown_yen']]).all()
            assert value['drawdown_yen'] >= 0
    return lookup


def improvement_counts(candidates: list[dict], baseline: dict, lookup: dict) -> dict:
    """機能: 同入口と旧主案の75/80基準を別々に数え、再選抜しない。

    引数: candidates (list[dict])、baseline/lookup (dict)。返り値: 記述件数 (dict)。
    """
    for symbol in SYMBOLS:
        assert baseline['symbols'][symbol]['net_yen'] > 0 and baseline['symbols'][symbol]['drawdown_yen'] > 0
    eligible = {c['signal_id'] for c in candidates
                if all(lookup[c['signal_id'] + '__K000']['symbols'][s]['net_yen'] > 0 and
                       lookup[c['signal_id'] + '__K000']['symbols'][s]['drawdown_yen'] > 0 for s in SYMBOLS)}
    counts = {name: dict(両銘柄該当数=0, うち探索最低基準も通過=0, 銘柄別該当数=dict.fromkeys(SYMBOLS, 0))
              for name in ('同入口のみ', '旧主案のみ', '両基準同時')}
    matches = []
    for row in candidates:
        paired = lookup[row['signal_id'] + '__K000']
        conditions = {'同入口のみ': {}, '旧主案のみ': {}, '両基準同時': {}}
        for symbol in SYMBOLS:
            value, old, own = row['symbols'][symbol], baseline['symbols'][symbol], paired['symbols'][symbol]
            conditions['同入口のみ'][symbol] = (row['signal_id'] in eligible and
                value['net_yen'] >= .75 * own['net_yen'] - 1e-8 and value['drawdown_yen'] <= .8 * own['drawdown_yen'] + 1e-8)
            conditions['旧主案のみ'][symbol] = (value['net_yen'] >= .75 * old['net_yen'] - 1e-8 and
                value['drawdown_yen'] <= .8 * old['drawdown_yen'] + 1e-8)
            conditions['両基準同時'][symbol] = conditions['同入口のみ'][symbol] and conditions['旧主案のみ'][symbol]
        for name, symbols in conditions.items():
            for symbol, condition in symbols.items():
                counts[name]['銘柄別該当数'][symbol] += int(condition)
            joint = all(symbols.values())
            counts[name]['両銘柄該当数'] += int(joint)
            counts[name]['うち探索最低基準も通過'] += int(joint and not row['failures'])
        if all(conditions['両基準同時'].values()):
            matches.append(row['id'])
    return dict(全条件数=len(candidates), 比較する旧主案=baseline['id'], 同入口基準が両銘柄黒字かつ正DDの入口数=len(eligible),
                同入口比較の適格条件数=len(eligible) * 50, 同入口比較の不適格条件数=(96 - len(eligible)) * 50,
                条件別=counts, 両基準同時の該当ID=sorted(matches),
                解釈='記述件数であり一次反証・乱数・指定波の合格数ではない。新候補選抜にも使わない。')


def rows_for_pairs(signals: list[dict], pairs: list[dict], lookup: dict) -> list[dict]:
    """機能: 機構ペアへ同じ信号・銘柄を対応させて差を作る。

    引数: signals/pairs (list[dict])、lookup (dict)。返り値: 全対応差 (list[dict])。
    """
    rows = []
    for signal, pair, symbol in itertools.product(signals, pairs, SYMBOLS):
        before, after = (lookup[signal['id'] + '__' + pair[field]] for field in ('before', 'after'))
        kind = signal['params']['main_kind']
        rows.append(dict(signal_id=signal['id'], main_kind=kind, philosophy='EMA' if kind.startswith('ema') else kind,
                         symbol=symbol, axis=pair['axis'], comparison=pair['comparison'], before=before['id'], after=after['id'],
                         net_difference=after['symbols'][symbol]['net_yen'] - before['symbols'][symbol]['net_yen'],
                         dd_difference=after['symbols'][symbol]['drawdown_yen'] - before['symbols'][symbol]['drawdown_yen'],
                         ledger_identical=before['ledger_hash'] == after['ledger_hash']))
    return rows


def both_markets(rows: list[dict]) -> list[dict]:
    """機能: 同じ対応組の両銘柄で収支増かつDD減が同時に起きた割合を数える。

    引数: rows (list[dict])。返り値: 軸別の両市場同時改善率 (list[dict])。
    """
    paired, groups = defaultdict(dict), defaultdict(list)
    for row in rows:
        key = (row['axis'], row['before'], row['after'])
        assert row['symbol'] not in paired[key]
        paired[key][row['symbol']] = row
    for key, values in paired.items():
        assert set(values) == set(SYMBOLS)
        good = all(r['net_difference'] > .01 and r['dd_difference'] < -.01 for r in values.values())
        groups[key[0]].append(good)
    return [dict(axis=axis, 銘柄対の組数=len(values), 両銘柄で収支増かつDD減率=float(np.mean(values)))
            for axis, values in sorted(groups.items())]


def freeze() -> dict:
    """機能: 新機構の結果を読む前に対応規則とコードを指紋固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    destination = HERE / 'protection_component_fixed.json'
    record = dict(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 規則=RULES,
                  コードSHA256=digest(Path(__file__)), 管理設計SHA256=digest(HERE / 'protection_design.py'),
                  探索仕様SHA256=digest(HERE / '探索条件の固定.json'))
    if destination.exists():
        previous = read(destination)
        assert {k: v for k, v in previous.items() if k != '固定日時'} == {k: v for k, v in record.items() if k != '固定日時'}
        return previous
    save(destination, record)
    return record


def selftest() -> dict:
    """機能: 合成候補だけで全組数・75/80境界・入力拒否を確かめる。

    引数: なし。返り値: 合成検査結果 (dict)。新成績ファイルは読まない。
    """
    management = protection_design.catalog()
    pairs = manager_pairs(management)
    signals = [dict(id=f'H{i:03d}', params=dict(main_kind='ema8_30')) for i in range(96)]
    fixed = dict(signals=signals, managers=management)
    candidates = [dict(id=s['id'] + '__' + m['id'], signal_id=s['id'], manager_id=m['id'], failures=[],
                       ledger_hash='0' * 64, symbols={symbol: dict(net_yen=100., drawdown_yen=100.) for symbol in SYMBOLS})
                  for s, m in itertools.product(signals, management)]
    lookup = validate_candidates(candidates, fixed)
    for symbol in SYMBOLS:
        lookup['H000__K001']['symbols'][symbol].update(net_yen=75., drawdown_yen=80.)
    baseline = dict(id='H019__D273', symbols={s: dict(net_yen=100., drawdown_yen=100.) for s in SYMBOLS})
    counts = improvement_counts(candidates, baseline, lookup)
    assert counts['条件別']['両基準同時']['両銘柄該当数'] == 1
    assert counts['両基準同時の該当ID'] == ['H000__K001']
    lookup['H001__K000']['symbols']['TOPIX']['net_yen'] = -1.
    lookup['H002__K000']['symbols']['NK225']['drawdown_yen'] = 0.
    counts = improvement_counts(candidates, baseline, lookup)
    assert counts['同入口基準が両銘柄黒字かつ正DDの入口数'] == 94
    assert counts['同入口比較の不適格条件数'] == 100
    rows = rows_for_pairs(signals, pairs, lookup)
    assert len(rows) == 41280
    assert sum(row['銘柄対の組数'] for row in both_markets(rows)) == 20640
    group_summary(rows, ('axis', 'symbol'))
    failures = 0
    for incorrect in (candidates[:-1], candidates + [candidates[0]]):
        try:
            validate_candidates(incorrect, fixed)
        except AssertionError:
            failures += 1
    original = candidates[0]['symbols']['TOPIX']['net_yen']
    candidates[0]['symbols']['TOPIX']['net_yen'] = float('nan')
    try:
        validate_candidates(candidates, fixed)
    except AssertionError:
        failures += 1
    candidates[0]['symbols']['TOPIX']['net_yen'] = original
    assert failures == 3
    result = dict(合成検査合格=True, 管理対応組数=len(pairs), 全対応差数=len(rows),
                  閾値境界一致=True, 負基準とゼロDD除外=True, 欠落重複NaN拒否数=failures, 実成績読取=False)
    save(HERE / 'protection_component_selftest.json', result)
    return result


def evaluate() -> dict:
    """機能: 全探索完了後の保存値だけで対応分布と二重目標該当数を記述する。

    引数: なし。返り値: 分解診断 (dict)。新売買再生や候補再選抜は行わない。
    """
    protocol = freeze()
    paths = [HERE / '探索条件の固定.json', HERE / '全条件の期間集計.json.gz',
             HERE / '反証前の候補固定.json', HERE.parent / 'wave_v27/反証前の候補固定.json']
    hashes = {str(p): digest(p) for p in paths}
    fixed, candidates, finished, previous = [read(p) for p in paths]
    assert len(fixed['signals']) == 96 and len(fixed['managers']) == 50
    assert fixed['全組合せ数'] == finished['全条件数'] == 4800
    lookup = validate_candidates(candidates, fixed)
    pairs = manager_pairs(fixed['managers'])
    rows = rows_for_pairs(fixed['signals'], pairs, lookup)
    assert len(rows) == 41280
    base_pairs = [dict(axis='同入口K000差', comparison='同入口K000との差', before='K000', after=m['id'])
                  for m in fixed['managers']]
    base_rows = rows_for_pairs(fixed['signals'], base_pairs, lookup)
    assert len(base_rows) == 9600
    changed_rows = [r for r in base_rows if r['before'] != r['after']]
    assert len(changed_rows) == 9408
    baseline = next(c for c in previous['上位30'] if c['id'] == 'H019__D273')
    report = dict(事前固定=protocol, 全条件数=4800, 全管理対応組数=len(pairs), 全対応差数=len(rows),
                  同一入口基準との差=group_summary(changed_rows, ('symbol',)),
                  同一入口基準との差の主方向別=group_summary(changed_rows, ('symbol', 'main_kind')),
                  全軸=group_summary(rows, ('axis', 'symbol')), 全比較=group_summary(rows, ('comparison', 'symbol')),
                  主方向別=group_summary(rows, ('axis', 'symbol', 'main_kind')),
                  思想別=group_summary(rows, ('axis', 'symbol', 'philosophy')),
                  両市場同時改善=both_markets(rows),
                  二重改善目標の記述件数=improvement_counts(candidates, baseline, lookup),
                  台帳率の限界=RULES['台帳'], 未知成功確率ではない=True,
                  新売買再生=False, 候補再選定=False, API取得数=0, 現在データ使用=False, 参照SHA256=hashes)
    assert hashes == {str(p): digest(p) for p in paths}
    save(HERE / 'protection_component_pairs.json.gz', dict(同入口全差分=base_rows, 機構全対応差分=rows))
    save(HERE / 'protection_component_audit.json', report)
    lines = ['# 利益保護と追跡短縮・全対応比較', '',
             '同じ入口・枚数・部分利確を保ち、全4,800条件を対応させた。各機構の比較は他の管理値も同一。差は変更後−変更前、収支が正・DDが負なら改善。', '',
             '|比較軸|銘柄|組数|収支差中央値|収支改善率|DD差中央値|DD改善率|両改善率|両銘柄全台帳同一率|',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in [dict(row, axis='同入口K000との差') for row in report['同一入口基準との差']] + report['全軸']:
        lines.append(f'|{row["axis"]}|{row["symbol"]}|{row["対応組数"]:,}|{row["収支差中央値円"]:+,.0f}|{row["収支改善率"]:.1%}|{row["DD差中央値円"]:+,.0f}|{row["DD改善率"]:.1%}|{row["両改善率"]:.1%}|{row["両銘柄全台帳同一率"]:.1%}|')
    counts = report['二重改善目標の記述件数']
    lines += ['', '## 収支75%維持・DD80%以下の記述件数', '',
              f'同入口K000が両銘柄黒字かつ正DDの入口は{counts["同入口基準が両銘柄黒字かつ正DDの入口数"]}/96。適格は{counts["同入口比較の適格条件数"]:,}条件。負の収支やDDゼロの基準へ75/80を機械的に適用しない。', '',
              '|基準|両銘柄で該当|うち探索最低基準も通過|', '|---|---:|---:|']
    for name, value in counts['条件別'].items():
        lines.append(f'|{name}|{value["両銘柄該当数"]:,}|{value["うち探索最低基準も通過"]:,}|')
    lines += ['', '## 読み方', '',
              '- 同一入口差の改善率からK000自身を除外した。全差分の保存にはK000も含めている。',
              '- 台帳指紋は両銘柄全26入力の結合。銘柄別の厳密な台帳同一率ではない。',
              '- 始動Rや割合の全水準間を比較し、部分的な最良例へ絞らない。主方向別と個別比較もJSONに保存した。',
              '- 出口が変わると次の新規時刻も変わるため、全口座差には再エントリー経路の違いも含む。',
              '- 多数の関連条件が同じ既知期間を使う。改善率は未知成功確率ではなく、上記件数は一次反証・乱数・8波の合格数でもない。候補再選抜・現在データ使用・売買再生はしていない。', '']
    (HERE / 'protection_component_audit.md').write_text('\n'.join(lines), encoding='utf-8')
    return report


def main() -> None:
    """機能: 結果前の合成検査・固定、又は完了後の集計を明示的に分ける。

    引数: --self-test/--prepare (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(selftest(), ensure_ascii=False), flush=True)
        return
    freeze()
    if args.prepare:
        assert len(manager_pairs(protection_design.catalog())) == 215
        print('215管理対応、41,280比較、同入口75/80と旧主案75/80の別計数を結果前に固定。', flush=True)
        return
    result = evaluate()
    print(json.dumps(dict(全対応差数=result['全対応差数'], 記述件数=result['二重改善目標の記述件数']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
