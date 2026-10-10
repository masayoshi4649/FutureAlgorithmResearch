"""第３反復の敵対検査。時計・確認・注文管理を混ぜずに個別判定する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import argparse
import hashlib
import math
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v23'
PREVIOUS = HERE.parent / 'wave_v25'
import hierarchy_runner as runner
import engine
import managers
import research

SYMBOLS = ('TOPIX', 'NK225')
INPUTS, FEATURES, SPECS = {}, {}, {}
OBSERVED = SIGNALS = None
VALIDATION_SHA = ''

RULES = {
    '目的': '第３反復の全探索後に、一律の独立感度検査を行う。全期間既知であり未知検証ではない。',
    '候補選別': {'台帳一意上位': 30, '思想ごとの首位': 'signal_family', '上限': 75,
                 '順位': 'v25と同じscore、同順位はID昇順。台帳一意上位と思想代表の和集合。75を超えれば同順位で切る。',
                 '不通過候補の追加・良い近傍への差替え': False},
    '基準': {'両銘柄黒字': True, 'PF': 1.3, '平均1枚利益損失比': 1.2,
             '最小組数': 13, '最小稼働セッション': 7, '最小黒字セッション': 7,
             '最大2勝ちセッション除外黒字': True, '最大2勝ち組除外黒字': True,
             '日夜それぞれ黒字': True, '前週追加週それぞれ黒字': True},
    '厳格実行': {'方向遅延秒': [1, 5, 15], '観測価格約定': True,
                 '全条件両銘柄収支': '>0', '全条件PF': 1.2,
                 '遅延3条件の各銘柄収支中央値': '>=基準収支の0.5倍',
                 '補足': '観測価格約定は費用追加と別の補足モデル。指定価格・費用0の基準を否定する根拠としない。厳格耐性の資格は別に判定する。'},
    '時計': {'集計時計倍率': [.8, 1.2], '相手遅延倍率': [.8, 1.2],
             '有効4条件の通過数': 3, '構造的不使用を除く一般式': 'ceil(有効条件数*0.75)',
             '各条件': '両銘柄net>0かつPF>=1.2',
             '各銘柄中央値': '>=基準収支の0.5倍', '各銘柄最悪': '>=-基準収支の0.25倍',
             '個別表示': '時計窓と相手遅延の2小区分についても全結果・中央値・最悪値を表示する。'},
    '短期確認の閾値': {'倍率': [.8, 1.2], '判定': '時計とは別カテゴリでceil(有効数*0.75)通過、銘柄別中央値>=0.5基準・最悪>=-0.25基準。2条件なら両方通過。',
                 '短期確認を使わない主方向のみ': '構造的不使用として2条件を分母から除外し、未使用と明記。'},
    '入口幅': {'パラメータ': 'entry_atr', '倍率': [.8, 1.2],
               '判定': '他カテゴリと別に2条件とも両黒字PF>=1.2、銘柄別中央値>=0.5基準・最悪>=-0.25基準。',
               '成行新規': 'entry_mode=2は不使用のため件数に含めない。'},
    '管理幅': {'パラメータ': ['stop_atr', 'main_trail', 'lock_fraction', 'timeout_min'], '倍率': [.8, 1.2],
               '判定': '注文管理カテゴリ単独でceil(有効数*0.75)通過、銘柄別中央値>=0.5基準・最悪>=-0.25基準。各変数2件の数値と合否も分けて表示。',
               '不使用': '元値0のlockとtimeoutは構造的不使用。無効なentry幅を管理幅へ混ぜない。'},
    '構造不使用とデータ不変の区別': '構造不使用(applied=False)は除外。有効変形なのに方向列や売買が同一なら感度結果へ残し、同一比率を併記して実質的不安を表示。',
    '追加防御': {'最大2開始日除外': '両銘柄net>0', '最悪セッション損失': '<=同銘柄総利益の0.5倍'},
    '部品対照': ['方向反転', '常時買い', '常時売り', '管理G08交換', '片方向同時保有1枚制限'],
    '乱数対照': {'対象': '厳格検査通過からscore上位、(signal_family,manager_family)の異なる最大10条件。',
                 'seed': list(range(64)), '方式': ['30分公平コイントス', '元信号非ゼロ時刻限定の30分公平コイントス'],
                 '共通性': '同一セッション内の両銘柄は同じ時計区分の乱数方向を共有。候補間でも同じseedを使う。',
                 '保持': 'セッション・seed・30分間隔で乱数系列を固定。将来末尾の延長で過去列不変。',
                 '解釈': '全64seedと銘柄別分布を記録。正式な有意確率と呼ばない。発火限定はタイミング情報を残す。'},
    '費用と数量': '費用0、指定価格約定を基準。TOPIXミニ片方向10枚・NK225マイクロ20枚以内。全玉損益・含み損込み下落、場内返済。銘柄間円額を合算しない。',
    '監査': '基準台帳完全一致、全条件の会計・次行・上限・場内返済。合成で観測価格モデルが実際に異なることと乱数prefixを確認。信号近傍は信号担当の因果監査に加えて末尾切断方向も比較。',
}


def freeze_rules() -> dict:
    """機能: 実データ損益を読む前に判定数値とカテゴリを固定する。

    引数: なし。返り値: 保存済み固定規則 (dict)。既存規則は変更しない。
    """
    path = HERE / '反証規則の固定.json'
    if path.exists():
        value = runner.read(path)
        assert value['規則'] == RULES, '固定した反証閾値の変更は禁止'
        return value
    value = {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), '損益結果未読': True, '規則': RULES}
    runner.save(path, value)
    return value


def freeze_implementation() -> dict:
    """機能: 実行直前に判定・信号・注文エンジン・入力の実装指紋を固定する。

    引数: なし。返り値: 実装指紋 (dict)。候補損益は参照しない。
    """
    freeze_rules()
    files = [Path(__file__), HERE / '反証規則の固定.json', HERE / 'hierarchy_runner.py',
             HERE / 'hierarchy_signals.py', HERE / 'hierarchy_design_fixed.json', HERE / 'engine_observed_v27.py', HERE / '探索条件の固定.json',
             PREVIOUS / 'discovery_signals.py', PREVIOUS / 'd016_price_control.py',
             OLD / 'engine.py', OLD / 'managers.py', OLD / 'research.py', OLD / 'signals.py',
             OLD / 'inputs.pkl', OLD / 'features_depth.pkl']
    hashes = {str(path.relative_to(HERE.parent)): runner.digest(path) for path in files}
    path = HERE / '反証実装の固定.json'
    if path.exists():
        value = runner.read(path)
        assert value['SHA256'] == hashes, '固定後の実装変更を検出したため再利用を拒否'
        return value
    value = {'日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 'SHA256': hashes}
    runner.save(path, value)
    return value


def initialize() -> None:
    """機能: ワーカーごとに凍結済み入力と通常importの観測エンジンをロードする。

    引数: なし。返り値: なし (None)。旧原本を書き換えない。
    """
    global INPUTS, FEATURES, SPECS, OBSERVED, SIGNALS, VALIDATION_SHA
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FEATURES = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    SPECS = runner.read(HERE / '探索条件の固定.json')
    VALIDATION_SHA = runner.digest(HERE / '反証実装の固定.json')
    import engine_observed_v27
    import hierarchy_signals
    OBSERVED, SIGNALS = engine_observed_v27, hierarchy_signals


def direction_hash(direction: dict) -> str:
    """機能: 方向列の一意性をキー順に依存せず記録する。

    引数: direction (dict)。返り値: SHA256 (str)。
    """
    digest = hashlib.sha256()
    for key in sorted(direction):
        digest.update(str(key).encode())
        digest.update(np.asarray(direction[key], dtype=np.int8).tobytes())
    return digest.hexdigest()


def load_state(identifier: str) -> dict:
    """機能: 探索時に保存した方向を読み込む。

    引数: identifier (str)。返り値: 区間別方向 (dict)。
    """
    with np.load(HERE / 'directions' / f'{identifier}.npz') as archive:
        return {tuple(key.split('|')): archive[key] for key in archive.files}


def lagged(ready: dict, state: np.ndarray, seconds: float) -> np.ndarray:
    """機能: 指定秒以前に存在した方向だけを使用する。

    引数: ready (dict)、state (ndarray)、seconds (float)。返り値: 遅延方向 (ndarray[int8])。
    """
    if seconds < 0:
        raise ValueError('負の遅延は禁止')
    if seconds == 0:
        return state.copy()
    positions = np.searchsorted(ready['time_s'], ready['time_s'] - seconds, side='right') - 1
    output = np.zeros(len(positions), dtype=np.int8)
    valid = positions >= 0
    output[valid] = state[positions[valid]]
    return output


def random_direction(ready: dict, seed: int, gate: np.ndarray | None = None) -> np.ndarray:
    """機能: 両銘柄で共通の30分乱数方向を未来に依存せず生成する。

    引数: ready (dict)、seed (int)、gate (ndarray|None)。返り値: 方向 (ndarray[int8])。
    """
    if not len(ready['time_s']):
        return np.zeros(0, dtype=np.int8)
    identity = f'v27|{seed}|{ready["session"]}|1800'.encode()
    generator = np.random.default_rng(int.from_bytes(hashlib.sha256(identity).digest()[:8], 'little'))
    blocks = np.maximum(0, np.floor((ready['time_s'] - ready['start']) / 1800).astype(np.int64))
    values = (generator.integers(0, 2, size=int(blocks[-1]) + 1, dtype=np.int64) * 2 - 1).astype(np.int8)
    output = values[blocks]
    output[ready['time_s'] < ready['start'] + 1200] = 0
    if gate is not None:
        output[gate == 0] = 0
    return output


def replay(name: str, direction: dict, management: dict, observed: bool = False, cap_one: bool = False) -> dict:
    """機能: 同一口座の全玉を再生し、原本行順・会計・保有限度を検算する。

    引数: name (str)、direction/management (dict)、observed/cap_one (bool)。返り値: 全区間と期間集計 (dict)。
    """
    module = OBSERVED if observed else engine
    rows, ledger = [], hashlib.sha256()
    for key, ready in INPUTS.items():
        config = managers.make_config(management, key[1], ready)
        if cap_one:
            config.update(audit_cap=1, initial_qty=1, add_qty=min(config['add_qty'], 1), cover_add=min(config['cover_add'], 1))
        result = module.run(ready, direction[key], config, detail=False)
        row = research.summarize(result, config, key[1], key[0], name)
        row['two_largest_cycle_profits'] = sorted([float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
        rows.append(row)
        ledger.update(str(key).encode())
        ledger.update(result['trades'].tobytes())
    return {'case': name, 'symbols': runner.diagnostics(rows), 'rows': rows, 'ledger_hash': ledger.hexdigest()}


def effective_pf(summary: dict) -> float:
    """機能: 正の利益だけで損失0のPFを判定時に正の無限大として扱う。

    引数: summary (dict)。返り値: 判定用PF (float)。JSONへ無限値を書き込まない。
    """
    if summary['gross_loss_yen'] <= 1e-8:
        return math.inf if summary['gross_profit_yen'] > 1e-8 else 0.
    return summary['gross_profit_yen'] / summary['gross_loss_yen']


def acceptable(result: dict) -> bool:
    """機能: 感度条件ごとに両銘柄黒字とPF1.2以上を判定する。

    引数: result (dict)。返り値: 合否 (bool)。
    """
    return all(result['symbols'][symbol]['net_yen'] > 0 and effective_pf(result['symbols'][symbol]) >= 1.2 for symbol in SYMBOLS)


def group_diagnostics(name: str, cases: list[dict], base: dict, allow_empty: bool = False) -> dict:
    """機能: 一つの感度カテゴリだけで通過数・中央値・最悪損失を判定する。

    引数: name (str)、cases (list[dict])、base (dict)、allow_empty (bool)。返り値: カテゴリ診断 (dict)。
    """
    count, passed = len(cases), sum(acceptable(case) for case in cases)
    required = math.ceil(count * .75)
    reasons = []
    if not count and not allow_empty:
        reasons.append('有効な感度条件が存在しない')
    if passed < required:
        reasons.append(f'両銘柄の黒字/PF1.2通過が{passed}/{count}で必要{required}未達')
    symbols = {}
    for symbol in SYMBOLS:
        values = [case['symbols'][symbol]['net_yen'] for case in cases]
        if not values:
            symbols[symbol] = {'中央値': None, '最悪': None, '基準': base['symbols'][symbol]['net_yen']}
            continue
        median, worst, reference = float(np.median(values)), float(min(values)), base['symbols'][symbol]['net_yen']
        symbols[symbol] = {'中央値': median, '最悪': worst, '基準': reference,
                           '中央値の基準比': median / reference if reference else None,
                           '最悪の基準比': worst / reference if reference else None}
        if median < .5 * reference:
            reasons.append(f'{symbol}:カテゴリ中央値が基準収支の半分未満')
        if worst < -.25 * reference:
            reasons.append(f'{symbol}:カテゴリ最悪が基準収支の-25%未満')
    return {'カテゴリ': name, '有効条件数': count, '必要通過数': required, '通過数': passed,
            '構造的不使用': count == 0 and allow_empty, 'symbols': symbols,
            '失敗理由': reasons, '通過': not reasons, '条件ID': [case['case'] for case in cases]}


def management_neighbors(management: dict) -> tuple[list[dict], list[dict]]:
    """機能: 入口幅と管理四変数の単独±20%を損益に依存せず定義する。

    引数: management (dict)。返り値: 有効変形・構造不使用記録 (tuple[list[dict],list[dict]])。
    """
    config = dict(managers.BASE, **management['changes'])
    variants, skipped = [], []
    for parameter in ['entry_atr', 'stop_atr', 'main_trail', 'lock_fraction', 'timeout_min']:
        if (parameter == 'entry_atr' and config['entry_mode'] == 2) or (parameter in ('lock_fraction', 'timeout_min') and config[parameter] <= 0):
            skipped.append({'parameter': parameter, 'reason': '設定上不使用', '条件数': 2})
            continue
        for factor in (.8, 1.2):
            changes = dict(management['changes'])
            changes[parameter] = config[parameter] * factor
            variants.append({'id': f'{parameter}×{factor}', 'parameter': parameter,
                             'category': 'entry' if parameter == 'entry_atr' else 'management',
                             'management': dict(management, changes=changes)})
    return variants, skipped


def select_candidates(candidates: list[dict]) -> list[dict]:
    """機能: 上位30一意台帳と各思想首位を、固定順位で最大75件にする。

    引数: candidates (list[dict])。返り値: 反証対象 (list[dict])。
    """
    ordered = sorted(sorted(candidates, key=lambda value: value['id']), key=runner.score, reverse=True)
    seen, top, families = set(), [], {}
    for candidate in ordered:
        if candidate['ledger_hash'] not in seen:
            seen.add(candidate['ledger_hash'])
            if len(top) < 30:
                top.append(candidate)
        families.setdefault(candidate['signal_family'], candidate)
    selected = {value['id']: value for value in top + list(families.values())}
    return sorted(sorted(selected.values(), key=lambda value: value['id']), key=runner.score, reverse=True)[:75]


def signal_variants(signal_spec: dict, state: dict) -> tuple[list[dict], list[dict]]:
    """機能: 有効な時計・相手遅延・確認近傍を生成し、不使用とデータ不変を区別する。

    引数: signal_spec/state (dict)。返り値: 生成済み変形・不使用記録 (tuple[list[dict],list[dict]])。
    """
    original_hash = direction_hash(state)
    variants, skipped = [], []
    last_session = sorted({key[0] for key in INPUTS})[-1]
    pair = {key: ready for key, ready in INPUTS.items() if key[0] == last_session}
    cutoff = min(ready['start'] + .55 * (ready['time_s'][-1] - ready['start']) for ready in pair.values())
    truncated = {}
    for key, ready in pair.items():
        mask = ready['time_s'] <= cutoff
        truncated[key] = {name: value[mask] if isinstance(value, np.ndarray) and value.ndim > 0 and len(value) == len(mask) else value
                          for name, value in ready.items()}
    pair_features = {key: FEATURES[key] for key in pair}
    for specification in SIGNALS.neighbor_specs(signal_spec):
        category = specification['diagnostic_category']
        if not specification['applied']:
            skipped.append({'id': specification['id'], 'category': category, 'reason': specification['skip_reason']})
            continue
        direction = SIGNALS.build(specification, INPUTS, FEATURES)
        prefix = SIGNALS.build(specification, truncated, pair_features)
        for key in pair:
            np.testing.assert_array_equal(prefix[key], direction[key][:len(prefix[key])])
        state_hash = direction_hash(direction)
        changed = sum(int(np.count_nonzero(direction[key] != state[key])) for key in state)
        total = sum(len(value) for value in state.values())
        variants.append({'id': specification['id'], 'category': category, 'directions': direction,
                         'specification': specification, 'state_hash': state_hash,
                         '基準と方向完全一致': state_hash == original_hash,
                         '基準から方向変更した行の割合': changed / total if total else 0.,
                         '未来末尾削除の方向一致区間数': len(pair)})
    return variants, skipped


def audit(candidate: dict) -> dict:
    """機能: 一候補に実行・時計・確認・入口・管理の独立した敵対検査を行う。

    引数: candidate (dict)。返り値: 全条件とカテゴリ別の厳格判定 (dict)。
    """
    path = HERE / 'adversarial' / f'{candidate["id"]}.json.gz'
    if path.exists():
        saved = runner.read(path)
        assert saved['validation_sha'] == VALIDATION_SHA and saved['candidate'] == candidate
        return saved
    state = load_state(candidate['signal_id'])
    management = next(value for value in SPECS['managers'] if value['id'] == candidate['manager_id'])
    signal_spec = next(value for value in SPECS['signals'] if value['id'] == candidate['signal_id'])
    base = replay('基準再現', state, management)
    assert base['ledger_hash'] == candidate['ledger_hash'], '探索台帳の完全再現に失敗'
    for symbol in SYMBOLS:
        assert base['symbols'][symbol] == candidate['symbols'][symbol], '探索集計の完全再現に失敗'
    cases, categories, flags = [base], {}, []
    basic_failures = runner.failures(base['symbols'])
    if basic_failures:
        flags.append('発見の最低条件未達')
    delayed = []
    for seconds in (1, 5, 15):
        directions = {key: lagged(ready, state[key], seconds) for key, ready in INPUTS.items()}
        case = replay(f'方向{seconds}秒遅延', directions, management)
        case.update(category='delay', seconds=seconds)
        delayed.append(case)
        cases.append(case)
    observed = replay('観測価格約定', state, management, observed=True)
    observed['category'] = 'observed'
    cases.append(observed)
    if not all(acceptable(value) for value in delayed + [observed]):
        flags.append('遅延または観測約定で両銘柄黒字PF1.2を維持できない')
    for symbol in SYMBOLS:
        reference = base['symbols'][symbol]
        if np.median([value['symbols'][symbol]['net_yen'] for value in delayed]) < .5 * reference['net_yen']:
            flags.append(f'{symbol}:遅延3条件の収支中央値が基準の半分未満')
        if reference['two_start_days_removed_net'] <= 0:
            flags.append(f'{symbol}:最大2開始日除外で非黒字')
        if -reference['worst_session'] > .5 * reference['gross_profit_yen']:
            flags.append(f'{symbol}:最悪セッション損失が総利益の半分超')

    # ----------------------------------------
    variants, unused = management_neighbors(management)
    groups = {'entry': [], 'management': [], 'clock': [], 'confirmation': []}
    for variant in variants:
        case = replay(variant['id'], state, variant['management'])
        case.update(category=variant['category'], parameter=variant['parameter'],
                    基準と台帳完全一致=case['ledger_hash'] == base['ledger_hash'])
        cases.append(case)
        groups[variant['category']].append(case)
    variants, signal_unused = signal_variants(signal_spec, state)
    for variant in variants:
        case = replay(variant['id'], variant['directions'], management)
        case.update(category=variant['category'], specification=variant['specification'],
                    state_hash=variant['state_hash'], 基準と方向完全一致=variant['基準と方向完全一致'],
                    基準から方向変更した行の割合=variant['基準から方向変更した行の割合'],
                    未来末尾削除の方向一致区間数=variant['未来末尾削除の方向一致区間数'],
                    基準と台帳完全一致=case['ledger_hash'] == base['ledger_hash'])
        cases.append(case)
        group = 'clock' if variant['category'] in ('clock', 'peer') else 'confirmation'
        groups[group].append(case)
    for name, values in groups.items():
        categories[name] = group_diagnostics(name, values, base, allow_empty=name in ('entry', 'confirmation'))
        flags.extend(f'{name}:{reason}' for reason in categories[name]['失敗理由'])
    subcategories = {}
    for parameter in ('stop_atr', 'main_trail', 'lock_fraction', 'timeout_min'):
        values = [case for case in groups['management'] if case['parameter'] == parameter]
        subcategories[parameter] = group_diagnostics(parameter, values, base, allow_empty=True)
    for name in ('clock', 'peer'):
        values = [case for case in groups['clock'] if case['category'] == name]
        subcategories[name] = group_diagnostics(name, values, base, allow_empty=True)

    # ----------------------------------------
    standard = next(value for value in managers.manager_catalog() if value['id'] == 'G08')
    cases += [replay('方向だけ反転', {key: -value for key, value in state.items()}, management),
              replay('管理をG08へ交換', state, standard), replay('片方向1枚へ保有制限', state, management, cap_one=True)]
    for side in (-1, 1):
        direction = {key: np.where(ready['time_s'] >= ready['start'] + 1200, side, 0).astype(np.int8) for key, ready in INPUTS.items()}
        cases.append(replay('常時買い' if side > 0 else '常時売り', direction, management))
    signal_cases = groups['clock'] + groups['confirmation']
    invariant = sum(case['基準と方向完全一致'] for case in signal_cases)
    warnings = []
    if signal_cases and invariant / len(signal_cases) >= .5:
        warnings.append('信号近傍の半数以上が基準方向と完全一致。形式通過と、実際に異なる判断を試せた数を分けて読む。')
    if unused or signal_unused:
        warnings.append('構造的不使用のパラメータは通過数へ含めていない。')
    result = {'candidate': candidate, 'cases': cases, 'basic_failures': basic_failures,
              'first_stage_failures': flags, 'カテゴリ判定': categories, '個別変数診断': subcategories,
              '管理の構造不使用': unused, '信号の構造不使用': signal_unused,
              '有効信号近傍数': len(signal_cases), '基準と方向完全一致の近傍数': invariant,
              '同一方向近傍比率': invariant / len(signal_cases) if signal_cases else None,
              '実質的注意': warnings, 'validation_sha': VALIDATION_SHA,
              '解釈': '変更した近傍は反証用であり、良い変形を採用し直さない。観測価格約定は主条件と区別した追加耐性検査。'}
    runner.save(path, result)
    return result


def randomized(candidate: dict) -> dict:
    """機能: 固定64seed×2方式の対照を同じ数量管理で再生する。

    引数: candidate (dict)。返り値: 全試行・各銘柄分布 (dict)。正式な有意確率は計算しない。
    """
    path = HERE / 'randomized' / f'{candidate["id"]}.json.gz'
    if path.exists():
        saved = runner.read(path)
        assert saved['validation_sha'] == VALIDATION_SHA and saved['candidate'] == candidate
        return saved
    state = load_state(candidate['signal_id'])
    management = next(value for value in SPECS['managers'] if value['id'] == candidate['manager_id'])
    results, prefix_count = [], 0
    for gated in (False, True):
        for seed in range(64):
            directions = {}
            for key, ready in INPUTS.items():
                gate = state[key] if gated else None
                directions[key] = random_direction(ready, seed, gate)
                if seed in (0, 63):
                    cut = len(ready['time_s']) // 2
                    short = dict(ready, time_s=ready['time_s'][:cut])
                    np.testing.assert_array_equal(random_direction(short, seed, gate[:cut] if gate is not None else None), directions[key][:cut])
                    prefix_count += 1
            result = replay(f'{"発火時刻限定" if gated else "30分コイントス"}_{seed:02d}', directions, management)
            result.update(seed=seed, gated=gated)
            results.append(result)
    summary = []
    for gated in (False, True):
        subset = [value for value in results if value['gated'] == gated]
        row = {'発火時刻限定': gated, '試行数': 64, 'symbols': {}}
        for symbol in SYMBOLS:
            values = np.array([value['symbols'][symbol]['net_yen'] for value in subset])
            row['symbols'][symbol] = {'収支平均円': float(values.mean()), '収支標準偏差円': float(values.std(ddof=1)),
                                     '収支0_5_50_95_100百分位': np.percentile(values, [0, 5, 50, 95, 100]).tolist(),
                                     '黒字seed数': int(np.sum(values > 0)),
                                     '候補以上の収支seed数': int(np.sum(values >= candidate['symbols'][symbol]['net_yen'])),
                                     '候補以上のPF_seed数': sum(effective_pf(value['symbols'][symbol]) >= effective_pf(candidate['symbols'][symbol]) for value in subset)}
        row['両銘柄黒字seed数'] = sum(all(value['symbols'][symbol]['net_yen'] > 0 for symbol in SYMBOLS) for value in subset)
        row['両銘柄で候補以上の収支seed数'] = sum(all(value['symbols'][symbol]['net_yen'] >= candidate['symbols'][symbol]['net_yen'] for symbol in SYMBOLS) for value in subset)
        summary.append(row)
    output = {'candidate': candidate, 'summary': summary, 'prefix一致数': prefix_count,
              'results': results, 'validation_sha': VALIDATION_SHA,
              '解釈': '正式な有意確率ではない。同じ既知価格経路の再生。発火限定は元のタイミングを残す。'}
    runner.save(path, output)
    return output


def synthetic_audit() -> dict:
    """機能: 実相場損益を読まず、約定モデル差・乱数因果性・カテゴリ分離を確認する。

    引数: なし。返り値: 合成検算結果 (dict)。
    """
    import engine_observed_v27 as observed
    ready = {'time_s': np.arange(6, dtype=float), 'last': np.array([100., 110., 111., 90., 90., 90.]),
             'atr': np.full(6, 4.), 'tick': 1., 'start': 0., 'limit': 4., 'us_open': np.inf, 'session': '合成'}
    cfg = managers.make_config({'changes': {'warmup_min': 0., 'entry_cutoff_min': 0.}}, 'TOPIX', ready)
    state = np.ones(6, dtype=np.int8)
    standard, alternate = engine.run(ready, state, cfg, True), observed.run(ready, state, cfg, True)
    assert standard['orders'][0, 5] == 101. and alternate['orders'][0, 5] == 110.
    assert standard['stats'][0] != alternate['stats'][0]
    for value in (standard, alternate):
        research.summarize(value, cfg, 'TOPIX', '合成', '合成')
    random_input = dict(ready, time_s=np.arange(10000, dtype=float))
    for seed in (0, 63):
        full = random_direction(random_input, seed)
        for cut in (0, 1201, 1801, 7001):
            prefix = dict(random_input, time_s=random_input['time_s'][:cut])
            np.testing.assert_array_equal(random_direction(prefix, seed), full[:cut])
    np.testing.assert_array_equal(lagged(ready, state, 0), state)
    np.testing.assert_array_equal(lagged(ready, state, 1), np.array([0, 1, 1, 1, 1, 1], dtype=np.int8))
    minimal = {'net_yen': 100., 'gross_profit_yen': 200., 'gross_loss_yen': 100.}
    base = {'symbols': {symbol: dict(minimal) for symbol in SYMBOLS}}
    bad = {'case': '時計不合格', 'symbols': {symbol: dict(minimal, net_yen=-30.) for symbol in SYMBOLS}}
    good = dict(base, case='良い別カテゴリ')
    assert not group_diagnostics('clock', [bad, bad, good, good], base)['通過']
    assert group_diagnostics('management', [good] * 8, base)['通過']
    assert acceptable({'symbols': {symbol: dict(minimal, gross_loss_yen=0.) for symbol in SYMBOLS}})
    return {'逆指値新規の指定101対観測110を確認': True, '観測モデルと指定モデルの収支差': True,
            '全玉会計・次行・上限・返済': True, '乱数prefix8条件': True, '遅延0秒と1秒': True,
            '時計悪化を別カテゴリ好成績で救済しない': True, '利益あり損失0のPF扱い': True}


def write_design() -> None:
    """機能: 最初に読む設計説明と実行手順を保存する。

    引数: なし。返り値: なし (None)。
    """
    text = '''# 第３反復の敵対検査

最初に `反証規則の固定.json` を読む。新しい成績を見る前に数値基準を固定する。`反証実装の固定.json` は実行開始前にコードと入力の指紋を確定する。

時計窓・相手遅延の4条件、短期確認の閾値の2条件、入口幅の2条件、管理stop/trail/lock/timeoutの8条件を混ぜず判定する。時計4条件なら3条件以上が両銘柄黒字かつPF1.2以上。各カテゴリは各銘柄の中央値が元収支の半分以上、最悪値が元収支のマイナス25%以上を要求する。遅延1/5/15秒と観測価格約定は全条件で両銘柄黒字・PF1.2以上を要求する。

構造上使用しない値（成行入口幅、0の利益保護/時間上限、短期確認を使わない主方向のみ、単独F32の相手遅延）は分母から除外する。有効な変形でも今回の方向列が偶然同じなら、その件数・比率と台帳一致を表示する。時計小区分や個別管理変数の結果も分けて残し、平均値の裏で壊れる条件を隠さない。

探索上位30の異なる台帳と各信号思想の首位を最大75件まで検査し、合格から異なる信号思想・管理思想の組を最大10件、固定64seed×2の無予測対照へ進める。乱数の都合の良いseedを採らず正式な有意確率を主張しない。これらは全て既知期間に対する反証であり、未知期間の検証とは呼ばない。

費用0・指定価格約定を主条件として維持する。観測価格約定は費用とは別の補足耐性検査である。全玉合算、片方向保有限度、次観測以降の執行、場内返済を各再生で検算する。

実行順序:

1. `python work/wave_v27/validation_round3.py --rules-only`：結果を読まず数値規則だけ固定。
2. 信号コードと探索仕様が完成後、`python work/wave_v27/validation_round3.py --prepare`：実装指紋固定と合成検算。
3. 全探索終了後、`python work/wave_v27/validation_round3.py --workers 10`：固定候補へ一次反証。
4. `python work/wave_v27/validation_round3.py --workers 4 --random`：通過した思想へ64seed×2対照。

主結果は `一次反証の結果.json`、詳細は `adversarial/`、乱数要約は `無関係対照の要約.json`、全seedは `randomized/`。同じ反証実装指紋の結果だけを再開利用できる。
'''
    (HERE / 'validation_round3.md').write_text(text, encoding='utf-8')


def main() -> None:
    """機能: 結果前固定、合成検算、一律反証、無予測対照を段階実行する。

    引数: --workers (int)、--rules-only/--prepare/--random (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=10)
    parser.add_argument('--rules-only', action='store_true')
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--random', action='store_true')
    args = parser.parse_args()
    freeze_rules()
    write_design()
    if args.rules_only:
        print('反証規則を固定。新探索の損益は未読。', flush=True)
        return
    freeze_implementation()
    runner.save(HERE / '反証合成検算.json', synthetic_audit())
    if args.prepare:
        print('実装指紋と合成検算完了。新探索の損益は未読。', flush=True)
        return
    for name in ('adversarial', 'randomized'):
        (HERE / name).mkdir(exist_ok=True)
    all_candidates = runner.read(HERE / '全条件の期間集計.json.gz')
    selected = select_candidates(all_candidates)
    parent_ids = {value['id'] for value in runner.read(HERE / '反証前の候補固定.json')['反証候補']}
    assert {value['id'] for value in selected} == parent_ids, '主探索と敵対検査の候補選定が不一致'
    runner.save(HERE / '反証対象の確認.json', {'候補': selected, '件数': len(selected)})
    if args.random:
        first = runner.read(HERE / '一次反証の結果.json')
        passed = [value['candidate'] for value in first if not value['first_stage_failures']]
        selected, families = [], set()
        for candidate in sorted(sorted(passed, key=lambda value: value['id']), key=runner.score, reverse=True):
            family = (candidate['signal_family'], candidate['manager_family'])
            if family not in families:
                families.add(family)
                selected.append(candidate)
            if len(selected) == 10:
                break
        runner.save(HERE / '無関係対照前の候補固定.json', selected)
    operation, outputs = (randomized if args.random else audit), []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize) as pool:
        futures = {pool.submit(operation, candidate): candidate['id'] for candidate in selected}
        for future in as_completed(futures):
            result = future.result()
            outputs.append({key: value for key, value in result.items() if key not in ('results', 'cases')})
            print(f'{len(outputs)}/{len(selected)} {futures[future]} 完了', flush=True)
    outputs.sort(key=lambda value: value['candidate']['id'])
    runner.save(HERE / ('無関係対照の要約.json' if args.random else '一次反証の結果.json'), outputs)


if __name__ == '__main__':
    main()
