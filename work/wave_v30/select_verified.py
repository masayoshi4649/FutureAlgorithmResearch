"""凍結済みの選抜条件を変えず、反証資料の完全性を検算してから選抜する。"""

from __future__ import annotations

from datetime import datetime
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import numpy as np

import context_split_runner as runner
import research_selection as selector
import validation_round6 as validator
import hierarchy_signals as SIGNALS

HERE = Path(__file__).resolve().parent
SYMBOLS = ('TOPIX', 'NK225')
RULES = {
    '目的': '資料の不足・重複・不一致・非有限数を拒否して、凍結済みresearch_selection.selectを呼ぶ。',
    '変更なし': '旧主案と同じ入口L000の両方に対する75%収支/80%DD、L000両銘柄黒字かつ正のDD、一次反証・8波・64seed×2・順位・最大2案・EMA同思想化を変更しない。',
    '一次': '全探索の固定カタログ12×7と全84候補を照合する。最低基準・順位で絞らず全候補の一次要約・実体・内容・実装SHAを一致させ、全変形の存在と集計及び判定を再計算する。',
    '同入口比較': '同じsignal_idのL000が全探索表に一意に存在し、一次反証の同一入口L000対照と期間集計・台帳指紋が一致することを確認する。基準の赤字やDD0は資料不正ではなく元選抜規則による不採用とする。',
    '乱数': '一次通過・不通過を問わず全84のID安定順を再計算。各候補は2方式×seed0..63の128件が一意に揃うことを要求し、全要約値を実体から再計算する。',
    '波': '全84候補と固定比較について4波×2銘柄の一意8行を要求。区間・方向・保有20分判定と方法別要約、一次追加元と仕様指紋を照合する。',
    '空資料': '一次通過0でも全84の乱数と波を必須とし、予定・実体の空や不足を拒否する。',
    '再利用': '選抜済み記録を再利用する場合はガード監査記録と全入力SHAの一致を要求する。',
    '禁止': '現在データ読取り・再生・API取得、候補改善の最適化、凍結済みコードの変更。',
}


def digest(path: Path) -> str:
    """機能: 保存資料の内容指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return runner.digest(path)


def finite(value: object, name: str = '資料') -> None:
    """機能: 入れ子JSONにNaN・無限大が含まれないことを確認する。

    引数: value (object)、name (str)。返り値: なし (None)。
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(name + 'に非有限数')
    if isinstance(value, dict):
        for key, item in value.items():
            finite(item, name + '/' + str(key))
    elif isinstance(value, list):
        for item in value:
            finite(item, name)


def unique(rows: list, key: str, name: str) -> dict:
    """機能: ID重複を拒否して辞書へ変換する。

    引数: rows (list)、key/name (str)。返り値: ID別資料 (dict)。
    """
    assert isinstance(rows, list), name + 'は配列である必要がある'
    mapped = {row[key]: row for row in rows}
    assert len(mapped) == len(rows), name + 'のID重複'
    return mapped


def counts(value: object, maximum: int, name: str) -> None:
    """機能: 件数が真偽値でない整数で、定義された範囲内かを確認する。

    引数: value (object)、maximum (int)、name (str)。返り値: なし (None)。
    """
    assert type(value) is int and 0 <= value <= maximum, name + 'の件数が不正'


def verify_case(case: dict, expected_keys: set) -> None:
    """機能: 一再生の26区間が一意に揃い、金額・数量・期間集計が明細と合うか確認する。

    引数: case (dict)、expected_keys (set[tuple])。返り値: なし (None)。
    """
    rows = case['rows']
    assert len(rows) == len(expected_keys)
    assert {(row['session'], row['symbol']) for row in rows} == expected_keys
    for row in rows:
        assert set(case['symbols']) == set(SYMBOLS)
        for field in ('gross_profit_yen', 'gross_loss_yen', 'drawdown_yen'):
            assert row[field] >= 0, field + 'が負'
        assert math.isclose(row['net_yen'], row['gross_profit_yen'] - row['gross_loss_yen'], rel_tol=0., abs_tol=1e-6)
        for field in ('profit_units', 'loss_units', 'zero_units', 'closed_units'):
            counts(row[field], 10**9, field)
        assert row['closed_units'] == row['profit_units'] + row['loss_units'] + row['zero_units']
    assert runner.diagnostics(rows) == case['symbols'], '区間明細と期間集計の不一致'


def random_summary(results: list, candidate: dict) -> list:
    """機能: 128試行の全要約値を元の反証コードと同じ定義で再計算する。

    引数: results (list)、candidate (dict)。返り値: 2方式の要約 (list)。
    """
    assert len(results) == 128
    for case in results:
        assert type(case['gated']) is bool
        counts(case['seed'], 63, 'seed')
    assert {(case['gated'], case['seed']) for case in results} == {(gate, seed) for gate in (False, True) for seed in range(64)}, '乱数seed/方式の重複又は欠落'
    output = []
    for gate in (False, True):
        subset = [case for case in results if case['gated'] == gate]
        row = {'発火時刻限定': gate, '試行数': 64, 'symbols': {}}
        for symbol in SYMBOLS:
            values = np.array([case['symbols'][symbol]['net_yen'] for case in subset])
            row['symbols'][symbol] = {
                '収支平均円': float(values.mean()), '収支標準偏差円': float(values.std(ddof=1)),
                '収支0_5_50_95_100百分位': np.percentile(values, [0, 5, 50, 95, 100]).tolist(),
                '黒字seed数': int(np.sum(values > 0)),
                '候補以上の収支seed数': int(np.sum(values >= candidate['symbols'][symbol]['net_yen'])),
                '候補以上のPF_seed数': sum(validator.effective_pf(case['symbols'][symbol]) >= validator.effective_pf(candidate['symbols'][symbol]) for case in subset),
            }
        row['両銘柄黒字seed数'] = sum(all(case['symbols'][symbol]['net_yen'] > 0 for symbol in SYMBOLS) for case in subset)
        row['両銘柄で候補以上の収支seed数'] = sum(all(case['symbols'][symbol]['net_yen'] >= candidate['symbols'][symbol]['net_yen'] for symbol in SYMBOLS) for case in subset)
        output.append(row)
    return output


def verify_first(full: dict, summary: dict, candidate: dict, specs: dict, expected_keys: set,
                 validation_sha: str, candidate_map: dict) -> None:
    """機能: 一次反証の全変形・明細・カテゴリ合否が凍結条件どおりであることを照合する。

    引数: full/summary/candidate/specs/candidate_map (dict)、expected_keys (set)、validation_sha (str)。
    返り値: なし (None)。同じ入口L000の基準も全探索と照合する。
    """
    assert full['candidate'] == summary['candidate'] == candidate
    assert full['validation_sha'] == summary['validation_sha'] == validation_sha
    assert {key: value for key, value in full.items() if key not in ('results', 'cases')} == summary
    cases = unique(full['cases'], 'case', '一次変形')
    manager = next(row for row in specs['managers'] if row['id'] == candidate['manager_id'])
    signal = next(row for row in specs['signals'] if row['id'] == candidate['signal_id'])
    management_variants, _ = validator.management_neighbors(manager)
    signal_variants = [row for row in SIGNALS.neighbor_specs(signal) if row['applied']]
    expected = {'基準再現', '両入力1秒遅延', '両入力5秒遅延', '両入力15秒遅延', '観測価格約定',
                '両入力を反転', '管理をG08へ交換', '片方向1枚へ保有制限',
                '同じ退出規則でcontextをentryへ戻す', '損失制限だけ除去', '常時買い', '常時売り',
                '同一入口L000へ交換'}
    expected.update(row['id'] for row in management_variants + signal_variants)
    assert set(cases) == expected, '一次変形の不足又は余分な変形'
    for case in cases.values():
        verify_case(case, expected_keys)
    base = cases['基準再現']
    assert base['symbols'] == candidate['symbols'] and base['ledger_hash'] == candidate['ledger_hash']
    paired = candidate_map[candidate['signal_id'] + '__L000']
    paired_case = cases['同一入口L000へ交換']
    assert paired_case['symbols'] == paired['symbols'] and paired_case['ledger_hash'] == paired['ledger_hash'], '同入口L000の実体と全探索が不一致'
    basic = runner.failures(base['symbols'])
    assert full['basic_failures'] == basic
    flags = ['発見の最低条件未達'] if basic else []
    delays = [cases[f'両入力{seconds}秒遅延'] for seconds in (1, 5, 15)]
    if not all(validator.acceptable(row) for row in delays + [cases['観測価格約定']]):
        flags.append('遅延または観測約定で両銘柄黒字PF1.2を維持できない')
    for symbol in SYMBOLS:
        reference = base['symbols'][symbol]
        if np.median([case['symbols'][symbol]['net_yen'] for case in delays]) < .5 * reference['net_yen']:
            flags.append(f'{symbol}:遅延3条件の収支中央値が基準の半分未満')
        if reference['two_start_days_removed_net'] <= 0:
            flags.append(f'{symbol}:最大2開始日除外で非黒字')
        if -reference['worst_session'] > .5 * reference['gross_profit_yen']:
            flags.append(f'{symbol}:最悪セッション損失が総利益の半分超')
    grouped = {'entry': [], 'management': [], 'clock': [], 'confirmation': [], 'loss_controls': []}
    for variant in management_variants + signal_variants:
        category = variant.get('category', variant.get('diagnostic_category'))
        group = 'clock' if category == 'peer' else category
        assert cases[variant['id']]['category'] == category
        grouped[group].append(cases[variant['id']])
    assert set(full['カテゴリ判定']) == set(grouped)
    for name, group in grouped.items():
        repeated = validator.group_diagnostics(name, group, base, allow_empty=name in ('entry', 'confirmation', 'loss_controls'))
        assert repeated == full['カテゴリ判定'][name], name + 'のカテゴリ判定が不一致'
        flags.extend(f'{name}:{reason}' for reason in repeated['失敗理由'])
    assert flags == full['first_stage_failures'], '一次反証の合否と明細が不一致'


def verify_waves(bundle: dict, passed: set) -> int:
    """機能: 波8明細の区間・重複・保有時間・要約と固定元を照合する。

    引数: bundle (dict)、passed (set[str])は全診断ID。返り値: 照合した波明細数 (int)。
    """
    report, fixed = bundle['episodes'], bundle['episode_fixed']
    assert report['固定仕様'] == fixed
    assert report['一次反証固定SHA256'] == bundle['first_sha']
    extension = bundle['episode_extension']['規則']
    assert extension['一次反証SHA256'] == bundle['first_sha']
    assert extension['元の波診断固定SHA256'] == bundle['episode_fixed_sha']
    assert extension['追加対象'] == sorted(passed)
    expected_methods = passed | set(fixed['規則']['固定比較'])
    methods = unique(report['手法'], 'id', '波手法')
    summaries = unique(report['方法別要約'], 'method', '波要約')
    assert set(methods) == set(summaries) == expected_methods
    waves = unique(fixed['規則']['対象'], 'id', '固定波')
    assert set(waves) == {'W01', 'W02', 'W03', 'W04'} and set(fixed['規則']['銘柄']) == set(SYMBOLS)
    expected_pairs = {(wave, symbol) for wave in waves for symbol in SYMBOLS}
    assert len(report['結果']) == 8 * len(expected_methods)
    assert {row['method'] for row in report['結果']} == expected_methods
    signals = {row['id']: row for row in bundle['specs']['signals']}
    managers = {row['id']: row for row in bundle['specs']['managers']}
    for identifier in expected_methods:
        if identifier in passed:
            candidate = bundle['candidate_map'][identifier]
            assert methods[identifier]['signal'] == dict(signals[candidate['signal_id']], 実装元='二入力階層')
            assert methods[identifier]['manager'] == managers[candidate['manager_id']]
        rows = [row for row in report['結果'] if row['method'] == identifier]
        assert len(rows) == 8 and {(row['wave'], row['symbol']) for row in rows} == expected_pairs, '波明細の重複又は欠落'
        for row in rows:
            definition = waves[row['wave']]
            assert (row['session'], row['開始'], row['終了'], row['波方向']) == (definition['session'], definition['start'], definition['end'], definition['side'])
            minutes = (datetime.fromisoformat(definition['end']) - datetime.fromisoformat(definition['start'])).total_seconds() / 60
            assert math.isclose(row['区間分'], minutes, abs_tol=1e-9)
            forward = row['正方向ネット保有分']
            assert 0 <= forward <= minutes + 1e-8
            assert type(row['正方向ネット20分目安達成']) is bool
            assert row['正方向ネット20分目安達成'] == (forward >= 20 - 1e-9)
        summary = summaries[identifier]
        assert summary['対象区間数'] == 8
        assert summary['目安達成区間数'] == sum(row['正方向ネット20分目安達成'] for row in rows)
        zero = [{'wave': row['wave'], 'symbol': row['symbol']} for row in rows if row['正方向ネット保有分'] == 0]
        assert summary['正方向保有0区間'] == zero
    return len(report['結果'])


def verify_bundle(bundle: dict) -> dict:
    """機能: 全資料を独立照合し、凍結済み選抜へ渡せる完全な集合だけを受理する。

    引数: bundle (dict)。返り値: 集合と再計算の監査結果 (dict)。採用条件を追加しない。
    """
    finite(bundle)
    baseline = bundle['baseline']
    assert baseline['id'] == 'H019__D273' and set(baseline['symbols']) == set(SYMBOLS)
    for row in baseline['symbols'].values():
        assert row['net_yen'] > 0 and row['drawdown_yen'] > 0, '固定比較の金額基準が不正'
    specs, candidates = bundle['specs'], bundle['candidates']
    signals = unique(specs['signals'], 'id', '信号仕様')
    managers = unique(specs['managers'], 'id', '管理仕様')
    assert 'L000' in managers, '同入口比較の管理L000がない'
    candidate_map = unique(candidates, 'id', '全探索候補')
    assert len(candidates) == specs['全組合せ数'] == len(signals) * len(managers)
    assert set(candidate_map) == {signal + '__' + manager for signal in signals for manager in managers}
    for candidate in candidates:
        assert candidate['id'] == candidate['signal_id'] + '__' + candidate['manager_id']
        assert candidate['signal_family'] == signals[candidate['signal_id']]['family']
        assert candidate['manager_family'] == managers[candidate['manager_id']]['family']
        assert set(candidate['symbols']) == set(SYMBOLS)
        assert candidate['failures'] == runner.failures(candidate['symbols'])
        for row in candidate['symbols'].values():
            assert row['drawdown_yen'] >= 0 and row['gross_profit_yen'] >= 0 and row['gross_loss_yen'] >= 0
    planned = unique(bundle['planned'], 'id', '一次予定')
    expected = {row['id']: row for row in validator.select_candidates(candidates)}
    assert planned == expected and planned, '一次反証の予定が固定順位又は全探索と不一致'
    first = {}
    for row in bundle['first']:
        identifier = row['candidate']['id']
        assert identifier not in first, '一次要約の候補重複'
        first[identifier] = row
    assert set(first) == set(planned) == set(bundle['adversarial']), '一次反証が未完了又は余分な候補'
    for identifier, summary in first.items():
        verify_first(bundle['adversarial'][identifier], summary, planned[identifier], specs,
                     bundle['expected_keys'], bundle['validation_sha'], candidate_map)
    passed = {identifier for identifier, row in first.items() if not row['first_stage_failures']}
    selected = validator.select_candidates(candidates)
    targets = unique(bundle['random_targets'], 'id', '乱数予定')
    assert bundle['random_targets'] == selected, '乱数予定が全条件ID順と不一致'
    random = {}
    for row in bundle['random']:
        identifier = row['candidate']['id']
        assert identifier not in random, '乱数要約の候補重複'
        random[identifier] = row
    assert set(targets) == set(random) == set(bundle['random_full']), '乱数結果の不足又は余分な候補'
    for identifier, summary in random.items():
        candidate, full = targets[identifier], bundle['random_full'][identifier]
        assert summary['candidate'] == full['candidate'] == first[identifier]['candidate'] == candidate
        assert summary['validation_sha'] == full['validation_sha'] == bundle['validation_sha']
        assert {key: value for key, value in full.items() if key not in ('results', 'cases')} == summary
        assert full['中期撤回も同一30分乱数へ置換'] is True and full['発火限定は入口だけに適用'] is True
        for case in full['results']:
            verify_case(case, bundle['expected_keys'])
        assert len(full['summary']) == 2
        for mode in full['summary']:
            assert type(mode['発火時刻限定']) is bool and type(mode['試行数']) is int and mode['試行数'] == 64
            counts(mode['両銘柄黒字seed数'], 64, '両銘柄黒字seed数')
            counts(mode['両銘柄で候補以上の収支seed数'], 64, '両銘柄の候補以上seed数')
            for symbol in SYMBOLS:
                for field in ('黒字seed数', '候補以上の収支seed数', '候補以上のPF_seed数'):
                    counts(mode['symbols'][symbol][field], 64, field)
        repeated = random_summary(full['results'], candidate)
        assert full['summary'] == summary['summary'] == repeated, '乱数明細と要約が不一致'
    bundle['candidate_map'] = candidate_map
    wave_count = verify_waves(bundle, set(candidate_map))
    return {'完全性検査通過': True, '全探索候補数': len(candidates), '一次反証候補数': len(first),
            '一次通過数': len(passed), '乱数候補数': len(random), '乱数実体数': len(random) * 128,
            '波明細数': wave_count, '採用閾値・順位・候補数変更なし': True, '現在データ使用': False}


def freeze_guard() -> dict:
    """機能: 新しい損益を読まず、資料検証の範囲とコード指紋を固定する。

    引数: なし。返り値: 固定記録 (dict)。既存選抜コードは変更しない。
    """
    selector.plan()
    paths = [Path(__file__), HERE / 'research_selection.py', HERE / '研究候補選抜の事前規則.json',
             HERE / 'validation_round6.py', HERE / '反証実装の固定.json', HERE / 'episode_audit.py', HERE / 'episode_audit_fixed.json']
    hashes = {path.name: digest(path) for path in paths}
    destination = HERE / '選抜整合ガードの固定.json'
    if destination.exists():
        record = runner.read(destination)
        assert record['規則'] == RULES and record['SHA256'] == hashes
        return record
    record = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '新損益未読': True, '規則': RULES, 'SHA256': hashes}
    runner.save(destination, record)
    return record


def load_bundle() -> tuple[dict, dict]:
    """機能: 選抜直前に完成資料を読み、各原本のSHAと実装の来歴を確認する。

    引数: なし。返り値: 検算用資料・入力SHA (tuple[dict,dict])。現在データを参照しない。
    """
    hashes = {}

    def tracked(path: Path) -> object:
        """機能: 同一バイト列からJSON解析と指紋採取を行う。

        引数: path (Path)。返り値: 通常又は圧縮JSONの内容 (object)。
        """
        raw = path.read_bytes()
        hashes[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
        return json.loads((gzip.decompress(raw) if path.suffix == '.gz' else raw).decode('utf-8'))

    implementation = tracked(HERE / '反証実装の固定.json')
    for relative, expected in implementation['SHA256'].items():
        assert digest(HERE.parent / relative) == expected, '反証実装の変更: ' + relative
    specs = tracked(HERE / '探索条件の固定.json')
    for relative, expected in specs['SHA256'].items():
        assert digest(HERE.parent / relative) == expected, '探索実装の変更: ' + relative
    first = tracked(HERE / '一次反証の結果.json')
    planned = tracked(HERE / '反証前の候補固定.json')['反証候補']
    random = tracked(HERE / '無関係対照の要約.json')
    random_targets = tracked(HERE / '無関係対照前の候補固定.json')
    episode_fixed = tracked(HERE / 'episode_audit_fixed.json')
    assert digest(HERE / 'episode_audit.py') == episode_fixed['計測コードSHA256']
    for relative, expected in episode_fixed['参照固定SHA256'].items():
        assert digest(HERE.parent / relative) == expected
    episodes = tracked(HERE / 'episode_audit.json')
    for path, expected in episodes['参照コードSHA256'].items():
        assert digest(Path(path)) == expected
    assert episodes['API取得数'] == 0 and episodes['参照コード不変'] is True and episodes['ルール変更'] is False
    assert specs['全組合せ数'] == 84 and len(specs['signals']) == 12 and len(specs['managers']) == 7
    expected_keys = set(pickle.loads((HERE.parent / 'wave_v23' / 'inputs.pkl').read_bytes()))
    assert len(expected_keys) == 26 and len({key[0] for key in expected_keys}) == 13
    bundle = dict(specs=specs, candidates=tracked(HERE / '全条件の期間集計.json.gz'), planned=planned,
                  first=first, random=random, random_targets=random_targets,
                  adversarial={row['id']: tracked(HERE / 'adversarial' / (row['id'] + '.json.gz')) for row in planned},
                  random_full={row['id']: tracked(HERE / 'randomized' / (row['id'] + '.json.gz')) for row in random_targets},
                  episodes=episodes, episode_fixed=episode_fixed,
                  episode_extension=tracked(HERE / 'episode_audit_first_stage_fixed.json'),
                  expected_keys=expected_keys, validation_sha=digest(HERE / '反証実装の固定.json'),
                  first_sha=digest(HERE / '一次反証の結果.json'), episode_fixed_sha=digest(HERE / 'episode_audit_fixed.json'))
    previous = tracked(HERE.parent / 'wave_v27' / '反証前の候補固定.json')
    old_candidates = unique(previous['上位30'], 'id', '固定比較を含む旧順位')
    bundle['baseline'] = old_candidates['H019__D273']
    return bundle, hashes


def select_verified() -> dict:
    """機能: 完全性検査後だけ元の選抜関数を呼び、入力指紋と監査記録を保存する。

    引数: なし。返り値: 元の研究候補選抜結果 (dict)。再生や価格取得は行わない。
    """
    freeze_guard()
    bundle, hashes = load_bundle()
    audit = verify_bundle(bundle)
    output = HERE / '研究候補の固定.json'
    audit_path = HERE / '選抜整合の監査.json'
    if output.exists():
        assert audit_path.exists(), '検証ガードの来歴がない既存選抜は再利用しない'
        previous = runner.read(audit_path)
        assert previous['入力SHA256'] == hashes and previous['選抜JSON_SHA256'] == digest(output)
        assert previous['ガード固定SHA256'] == digest(HERE / '選抜整合ガードの固定.json')
    for path, expected in hashes.items():
        assert digest(Path(path)) == expected, '検算中に資料が変更された'
    result = selector.select()
    for path, expected in hashes.items():
        assert digest(Path(path)) == expected, '選抜中に資料が変更された'
    audit.update(検査日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 入力SHA256=hashes,
                 ガード固定SHA256=digest(HERE / '選抜整合ガードの固定.json'), 選抜JSON_SHA256=digest(output))
    runner.save(audit_path, audit)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        freeze_guard()
        print('選抜整合ガードを固定。新探索損益・現在データは未読。', flush=True)
    else:
        selected = select_verified()
        print('検証済み研究主候補: ' + str(selected['主候補']), flush=True)
