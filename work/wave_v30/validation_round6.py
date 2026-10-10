"""第６反復の敵対検査。入口と中期撤回を分離し、管理と損失制限も個別判定する。"""

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
SIGNAL_ROOT = HERE.parent / 'wave_v27'
import context_split_runner as runner
sys.path.insert(0, str(HERE.parent / 'wave_v28'))
import engine_context as engine
import managers
import research

SYMBOLS = ('TOPIX', 'NK225')
INPUTS, FEATURES, SPECS = {}, {}, {}
OBSERVED = SIGNALS = None
VALIDATION_SHA = ''

RULES = {
    '目的': '第６反復の12入口×7管理=84条件を既知13セッションだけで反証する。過去5反復と一回照合の失敗を知った後の機構診断であり未知検証ではない。現在データは読取・再試験・追加取得を一切行わない。',
    '二入力': '入口は既存peer=trueの同一配列。context_source=entryはcontext=NoneのB0、mainは両確認C、ownは自己のみS。基準と管理近傍は基準context。時計等の近傍は変更specから入口を生成し、Sだけ中期params.peer_confirm=False。短期確認で中期不変、Sの相手遅延変更でも中期不変を照合する。',
    '候補選別': {'対象': '全84条件。最低基準・台帳重複・思想・順位による絞込みをしない。',
                 '順位': '検査順はID昇順。全件の不通過も保存。良い近傍への差替えは禁止。'},
    '基準': {'両銘柄黒字': True, 'PF': 1.3, '平均1枚利益損失比': 1.2,
             '最小組数': 13, '最小稼働セッション': 7, '最小黒字セッション': 7,
             '最大2勝ちセッション除外黒字': True, '最大2勝ち組除外黒字': True,
             '日夜それぞれ黒字': True, '前週追加週それぞれ黒字': True},
    '厳格実行': {'入口と中期撤回の同時遅延秒': [1, 5, 15], '観測価格約定': True,
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
    '損失・撤回制限': {'パラメータ': ['session_budget_r', 'max_same_losses', 'neutral_min'],
                   '変形': 'session_budget_rとneutral_minは±20%。max_same_lossesは±1、下限1。元値0はいずれも構造不使用として分母から除外。',
                   '判定': '他カテゴリから独立してceil(有効数*0.75)通過、銘柄別中央値>=0.5基準・最悪>=-0.25基準。各変数も別表示。'},
    '構造不使用とデータ不変の区別': '構造不使用(applied=False)は除外。有効変形なのに方向列や売買が同一なら感度結果へ残し、同一比率を併記して実質的不安を表示。',
    '追加防御': {'最大2開始日除外': '両銘柄net>0', '最悪セッション損失': '<=同銘柄総利益の0.5倍'},
    '部品対照': ['入口と中期撤回を同時反転', '入口と中期撤回を常時買い', '入口と中期撤回を常時売り', '管理G08交換（context=Noneの旧管理）', '片方向同時保有1枚制限', '同じ退出規則でcontextをentryへ戻す', '損失制限だけ除去', '同一入口L000へ交換'],
    '乱数対照': {'対象': '一次反証の通過・不通過を問わず全84条件。順位や思想で絞らない。',
                 'seed': list(range(64)), '方式': ['30分公平コイントス', '元信号非ゼロ時刻限定の30分公平コイントス'],
                 '共通性': '同一セッション内の両銘柄は同じ時計区分の乱数方向を共有。候補間でも同じseedを使う。',
                 '保持': 'セッション・seed・30分間隔で乱数系列を固定。将来末尾の延長で過去列不変。',
                 '二入力': '入口と中期撤回を同じ30分乱数にする。発火限定は入口だけ元state非ゼロで絞り、中期撤回には絞る前の乱数を渡す。真の中期方向を残さない。',
                 '解釈': '全64seedと銘柄別分布を記録。正式な有意確率と呼ばない。発火限定はタイミング情報を残す。'},
    '指定波': '既定4波×2銘柄の8区間すべてで正方向ネット保有20分以上を研究候補選抜で要求する。一次反証合格だけで目的達成とはしない。',
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
    exploration = runner.read(HERE / '探索条件の固定.json')
    for relative, expected in exploration['SHA256'].items():
        assert runner.digest(HERE.parent / relative) == expected, f'探索固定後の実装変更: {relative}'
    files = [Path(__file__), HERE / '反証規則の固定.json', HERE / 'context_split_runner.py',
             HERE / 'context_split_design.py', HERE / '管理設計の固定.json', HERE.parent / 'wave_v28' / 'engine_context.py',
             HERE.parent / 'wave_v28' / 'engine_context_observed.py', HERE.parent / 'wave_v28' / '観測モデル派生の固定.json',
             HERE / '探索条件の固定.json',
             SIGNAL_ROOT / 'hierarchy_signals.py', SIGNAL_ROOT / 'hierarchy_design_fixed.json',
             PREVIOUS / 'discovery_signals.py', PREVIOUS / 'discovery_runner.py', PREVIOUS / 'd016_price_control.py',
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


def verify_observed_derivation() -> None:
    """機能: 観測価格モデルが凍結元から指定した２置換だけで作られたことを確認する。

    引数: なし。返り値: なし (None)。実相場データは読まない。
    """
    record = runner.read(HERE.parent / 'wave_v28' / '観測モデル派生の固定.json')
    origin_path, derived_path = HERE.parent / 'wave_v28' / 'engine_context.py', HERE.parent / 'wave_v28' / 'engine_context_observed.py'
    assert runner.digest(origin_path) == record['派生元SHA256']
    assert runner.digest(derived_path) == record['派生先SHA256']
    expected = origin_path.read_text(encoding='utf-8')
    for change in record['変更']:
        assert expected.count(change['元']) == change['箇所数'] == 1
        expected = expected.replace(change['元'], change['先'])
    assert expected == derived_path.read_text(encoding='utf-8'), '観測モデルに指定外の変更'


def initialize() -> None:
    """機能: ワーカーごとに凍結済み入力と通常importの観測エンジンをロードする。

    引数: なし。返り値: なし (None)。旧原本を書き換えない。
    """
    global INPUTS, FEATURES, SPECS, OBSERVED, SIGNALS, VALIDATION_SHA
    INPUTS = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    FEATURES = pickle.loads((OLD / 'features_depth.pkl').read_bytes())
    SPECS = runner.read(HERE / '探索条件の固定.json')
    VALIDATION_SHA = runner.digest(HERE / '反証実装の固定.json')
    import engine_context_observed
    import hierarchy_signals
    OBSERVED, SIGNALS = engine_context_observed, hierarchy_signals


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


def load_context(identifier: str, source: str = 'main') -> dict:
    """機能: 探索時に保存した中期撤回方向を読み込む。

    引数: identifier/source (str)。返り値: 区間別中期方向 (dict)。ownは自己のみ、他は両確認の参考列。
    """
    directory = 'contexts_own' if source == 'own' else 'contexts'
    with np.load(HERE / directory / f'{identifier}.npz') as archive:
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
    identity = f'v30|{seed}|{ready["session"]}|1800'.encode()
    generator = np.random.default_rng(int.from_bytes(hashlib.sha256(identity).digest()[:8], 'little'))
    blocks = np.maximum(0, np.floor((ready['time_s'] - ready['start']) / 1800).astype(np.int64))
    values = (generator.integers(0, 2, size=int(blocks[-1]) + 1, dtype=np.int64) * 2 - 1).astype(np.int8)
    output = values[blocks]
    output[ready['time_s'] < ready['start'] + 1200] = 0
    if gate is not None:
        output[gate == 0] = 0
    return output


def replay(name: str, direction: dict, management: dict, observed: bool = False,
           cap_one: bool = False, context: dict | None = None) -> dict:
    """機能: 同一口座の全玉を再生し、原本行順・会計・保有限度を検算する。

    引数: name (str)、direction/management (dict)、observed/cap_one (bool)、context (dict|None)。
    返り値: 全区間と期間集計 (dict)。main設定の中期列欠落は拒否する。
    """
    module = OBSERVED if observed else engine
    source = management.get('context_source', 'entry')
    assert source in ('entry', 'main', 'own'), '中期撤回の入力源が不正'
    assert set(direction) == set(INPUTS), '入口方向の区間不足又は余分な区間'
    if source != 'entry':
        assert context is not None and set(context) == set(INPUTS), '中期撤回方向の区間不足又は余分な区間'
    rows, ledger = [], hashlib.sha256()
    for key, ready in INPUTS.items():
        config = managers.make_config(management, key[1], ready)
        if cap_one:
            config.update(audit_cap=1, initial_qty=1, add_qty=min(config['add_qty'], 1), cover_add=min(config['cover_add'], 1))
        result = module.run(ready, direction[key], config, detail=False,
                            context=context[key] if source != 'entry' else None)
        row = research.summarize(result, config, key[1], key[0], name)
        row['two_largest_cycle_profits'] = sorted([float(v) * config['point_value'] for v in result['cycles'][:, 3] if v > 0], reverse=True)[:2]
        rows.append(row)
        ledger.update(str(key).encode())
        ledger.update(result['trades'].tobytes())
    return {'case': name, 'symbols': runner.diagnostics(rows), 'rows': rows,
            'ledger_hash': ledger.hexdigest(), 'context_source': source}


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
    """機能: 入口・管理幅・損失撤回制限の単独変形を損益に依存せず定義する。

    引数: management (dict)。返り値: 有効変形・構造不使用記録 (tuple[list[dict],list[dict]])。
    """
    config = dict(managers.BASE, **management['changes'])
    variants, skipped = [], []
    controls = ('session_budget_r', 'max_same_losses', 'neutral_min')
    for parameter in ['entry_atr', 'stop_atr', 'main_trail', 'lock_fraction', 'timeout_min', *controls]:
        if (parameter == 'entry_atr' and config['entry_mode'] == 2) or (parameter in ('lock_fraction', 'timeout_min', *controls) and config[parameter] <= 0):
            skipped.append({'parameter': parameter, 'reason': '設定上不使用', '条件数': 2})
            continue
        values = (-1, 1) if parameter == 'max_same_losses' else (.8, 1.2)
        for factor in values:
            changes = dict(management['changes'])
            changes[parameter] = max(1, int(config[parameter]) + factor) if parameter == 'max_same_losses' else config[parameter] * factor
            label = f'{parameter}{factor:+d}' if parameter == 'max_same_losses' else f'{parameter}×{factor}'
            category = 'entry' if parameter == 'entry_atr' else ('loss_controls' if parameter in controls else 'management')
            variants.append({'id': label, 'parameter': parameter, 'category': category,
                             'management': dict(management, changes=changes)})
    return variants, skipped


def select_candidates(candidates: list[dict]) -> list[dict]:
    """機能: 順位や最低基準で除かず、全候補をIDの安定順にする。

    引数: candidates (list[dict])。返り値: 全件の反証対象 (list[dict])。
    全84の完全性は固定カタログとの直積で入口側と選抜ガードが別途確認する。
    """
    assert len({value['id'] for value in candidates}) == len(candidates), '候補ID重複'
    return sorted(candidates, key=lambda value: value['id'])


def context_for_spec(specification: dict, inputs: dict, source: str) -> dict:
    """機能: 同じ入口仕様から両確認又は自己だけの中期方向を生成する。

    引数: specification/inputs (dict)、source (str)。返り値: 中期配列 (dict)。
    自己参照でも入口buildを変更せず、中期生成だけ相手確認を外す。
    """
    assert source in ('entry', 'main', 'own')
    main_spec = specification
    if source == 'own':
        main_spec = dict(specification, params=dict(specification['params'], peer_confirm=False))
    return SIGNALS.main_directions(main_spec, inputs)


def signal_variants(signal_spec: dict, state: dict, context: dict, source: str = 'main') -> tuple[list[dict], list[dict]]:
    """機能: 有効な時計・相手遅延・確認近傍を生成し、不使用とデータ不変を区別する。

    引数: signal_spec/state/context (dict)、source (str)。返り値: 生成済み変形・不使用記録 (tuple[list[dict],list[dict]])。
    """
    original_hash = direction_hash(state)
    original_context_hash = direction_hash(context)
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
        main = context_for_spec(specification, INPUTS, source)
        prefix = SIGNALS.build(specification, truncated, pair_features)
        main_prefix = context_for_spec(specification, truncated, source)
        for key in pair:
            np.testing.assert_array_equal(prefix[key], direction[key][:len(prefix[key])])
            np.testing.assert_array_equal(main_prefix[key], main[key][:len(main_prefix[key])])
        state_hash = direction_hash(direction)
        context_hash = direction_hash(main)
        if category == 'confirmation' or (source == 'own' and category == 'peer'):
            assert context_hash == original_context_hash, '短期確認又は自己contextの相手遅延だけの変更で中期が変化'
        changed = sum(int(np.count_nonzero(direction[key] != state[key])) for key in state)
        main_changed = sum(int(np.count_nonzero(main[key] != context[key])) for key in context)
        total = sum(len(value) for value in state.values())
        variants.append({'id': specification['id'], 'category': category, 'directions': direction, 'contexts': main,
                         'specification': specification, 'state_hash': state_hash,
                         'context_hash': context_hash,
                         '基準と方向完全一致': state_hash == original_hash,
                         '基準と中期方向完全一致': context_hash == original_context_hash,
                         '基準と両入力完全一致': state_hash == original_hash and context_hash == original_context_hash,
                         '基準から方向変更した行の割合': changed / total if total else 0.,
                         '基準から中期方向変更した行の割合': main_changed / total if total else 0.,
                         '未来末尾削除の方向一致区間数': len(pair),
                         '未来末尾削除の中期方向一致区間数': len(pair)})
    return variants, skipped


def audit(candidate: dict) -> dict:
    """機能: 一候補に実行・時計・確認・入口・管理・損失撤回制限の独立検査を行う。

    引数: candidate (dict)。返り値: 全条件とカテゴリ別の厳格判定 (dict)。
    """
    path = HERE / 'adversarial' / f'{candidate["id"]}.json.gz'
    if path.exists():
        saved = runner.read(path)
        assert saved['validation_sha'] == VALIDATION_SHA and saved['candidate'] == candidate
        return saved
    state = load_state(candidate['signal_id'])
    management = next(value for value in SPECS['managers'] if value['id'] == candidate['manager_id'])
    context = load_context(candidate['signal_id'], management['context_source'])
    signal_spec = next(value for value in SPECS['signals'] if value['id'] == candidate['signal_id'])
    base = replay('基準再現', state, management, context=context)
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
        delayed_context = {key: lagged(ready, context[key], seconds) for key, ready in INPUTS.items()}
        case = replay(f'両入力{seconds}秒遅延', directions, management, context=delayed_context)
        case.update(category='delay', seconds=seconds)
        delayed.append(case)
        cases.append(case)
    observed = replay('観測価格約定', state, management, observed=True, context=context)
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
    groups = {'entry': [], 'management': [], 'clock': [], 'confirmation': [], 'loss_controls': []}
    for variant in variants:
        case = replay(variant['id'], state, variant['management'], context=context)
        case.update(category=variant['category'], parameter=variant['parameter'],
                    基準と台帳完全一致=case['ledger_hash'] == base['ledger_hash'])
        cases.append(case)
        groups[variant['category']].append(case)
    variants, signal_unused = signal_variants(signal_spec, state, context, management['context_source'])
    for variant in variants:
        case = replay(variant['id'], variant['directions'], management, context=variant['contexts'])
        case.update(category=variant['category'], specification=variant['specification'],
                    state_hash=variant['state_hash'], 基準と方向完全一致=variant['基準と方向完全一致'],
                    context_hash=variant['context_hash'], 基準と中期方向完全一致=variant['基準と中期方向完全一致'],
                    基準と両入力完全一致=variant['基準と両入力完全一致'],
                    基準から方向変更した行の割合=variant['基準から方向変更した行の割合'],
                    基準から中期方向変更した行の割合=variant['基準から中期方向変更した行の割合'],
                    未来末尾削除の方向一致区間数=variant['未来末尾削除の方向一致区間数'],
                    未来末尾削除の中期方向一致区間数=variant['未来末尾削除の中期方向一致区間数'],
                    基準と台帳完全一致=case['ledger_hash'] == base['ledger_hash'])
        case['基準と実際の使用入力完全一致'] = (variant['基準と両入力完全一致']
            if management['context_source'] != 'entry' else variant['基準と方向完全一致'])
        cases.append(case)
        group = 'clock' if variant['category'] in ('clock', 'peer') else 'confirmation'
        groups[group].append(case)
    for name, values in groups.items():
        categories[name] = group_diagnostics(name, values, base, allow_empty=name in ('entry', 'confirmation', 'loss_controls'))
        flags.extend(f'{name}:{reason}' for reason in categories[name]['失敗理由'])
    subcategories = {}
    for parameter in ('stop_atr', 'main_trail', 'lock_fraction', 'timeout_min'):
        values = [case for case in groups['management'] if case['parameter'] == parameter]
        subcategories[parameter] = group_diagnostics(parameter, values, base, allow_empty=True)
    for parameter in ('session_budget_r', 'max_same_losses', 'neutral_min'):
        values = [case for case in groups['loss_controls'] if case['parameter'] == parameter]
        subcategories[parameter] = group_diagnostics(parameter, values, base, allow_empty=True)
    for name in ('clock', 'peer'):
        values = [case for case in groups['clock'] if case['category'] == name]
        subcategories[name] = group_diagnostics(name, values, base, allow_empty=True)

    # ----------------------------------------
    standard = next(value for value in managers.manager_catalog() if value['id'] == 'G08')
    cases += [replay('両入力を反転', {key: -value for key, value in state.items()}, management,
                     context={key: -value for key, value in context.items()}),
              replay('管理をG08へ交換', state, standard),
              replay('片方向1枚へ保有制限', state, management, cap_one=True, context=context),
              replay('同じ退出規則でcontextをentryへ戻す', state, dict(management, context_source='entry')),
              replay('損失制限だけ除去', state, dict(management, changes=dict(management['changes'],
                     max_same_losses=0, session_budget_r=0.)), context=context)]
    baseline_manager = next(value for value in SPECS['managers'] if value['id'] == 'L000')
    cases.append(replay('同一入口L000へ交換', state, baseline_manager))
    for side in (-1, 1):
        direction = {key: np.where(ready['time_s'] >= ready['start'] + 1200, side, 0).astype(np.int8) for key, ready in INPUTS.items()}
        cases.append(replay('常時買い' if side > 0 else '常時売り', direction, management, context=direction))
    signal_cases = groups['clock'] + groups['confirmation']
    invariant = sum(case['基準と実際の使用入力完全一致'] for case in signal_cases)
    warnings = []
    if signal_cases and invariant / len(signal_cases) >= .5:
        warnings.append('信号近傍の半数以上で実際に使用する入力が基準と完全一致。main/ownは入口・中期の両入力、entryは入口だけで数える。形式通過と異なる判断の検査数を分けて読む。')
    if unused or signal_unused:
        warnings.append('構造的不使用のパラメータは通過数へ含めていない。')
    result = {'candidate': candidate, 'cases': cases, 'basic_failures': basic_failures,
              'first_stage_failures': flags, 'カテゴリ判定': categories, '個別変数診断': subcategories,
              '管理の構造不使用': unused, '信号の構造不使用': signal_unused,
              '有効信号近傍数': len(signal_cases),
              '基準と方向完全一致の近傍数': sum(case['基準と方向完全一致'] for case in signal_cases),
              '基準と中期方向完全一致の近傍数': sum(case['基準と中期方向完全一致'] for case in signal_cases),
              '基準と両入力完全一致の近傍数': sum(case['基準と両入力完全一致'] for case in signal_cases),
              '基準と実際の使用入力完全一致の近傍数': invariant,
              '同一使用入力近傍比率': invariant / len(signal_cases) if signal_cases else None,
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
            directions, contexts = {}, {}
            for key, ready in INPUTS.items():
                gate = state[key] if gated else None
                directions[key] = random_direction(ready, seed, gate)
                contexts[key] = random_direction(ready, seed)
                if gate is None:
                    np.testing.assert_array_equal(directions[key], contexts[key])
                else:
                    np.testing.assert_array_equal(directions[key], np.where(gate != 0, contexts[key], 0))
                if seed in (0, 63):
                    cut = len(ready['time_s']) // 2
                    short = dict(ready, time_s=ready['time_s'][:cut])
                    np.testing.assert_array_equal(random_direction(short, seed, gate[:cut] if gate is not None else None), directions[key][:cut])
                    np.testing.assert_array_equal(random_direction(short, seed), contexts[key][:cut])
                    prefix_count += 1
            result = replay(f'{"発火時刻限定" if gated else "30分コイントス"}_{seed:02d}', directions, management, context=contexts)
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
              '中期撤回も同一30分乱数へ置換': True,
              '発火限定は入口だけに適用': True,
              '解釈': '正式な有意確率ではない。同じ既知価格経路の再生。発火限定は元のタイミングを残すが真の中期方向を残さない。'}
    runner.save(path, output)
    return output


def synthetic_audit() -> dict:
    """機能: 実相場損益を読まず、約定モデル差・乱数因果性・カテゴリ分離を確認する。

    引数: なし。返り値: 合成検算結果 (dict)。
    """
    import engine_context_observed as observed
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
    assert group_diagnostics('loss_controls', [], base, allow_empty=True)['構造的不使用']
    assert not group_diagnostics('loss_controls', [bad, bad, good, good], base)['通過']

    # ----------------------------------------
    empty_variants, unused = management_neighbors({'changes': {}})
    guards = {'session_budget_r', 'max_same_losses', 'neutral_min'}
    assert not [value for value in empty_variants if value['parameter'] in guards]
    assert guards <= {value['parameter'] for value in unused}
    variants, _ = management_neighbors({'changes': {'session_budget_r': 3., 'max_same_losses': 2, 'neutral_min': 10.}})
    assert len([value for value in variants if value['category'] == 'loss_controls']) == 6
    limits = [value['management']['changes']['max_same_losses'] for value in variants if value['parameter'] == 'max_same_losses']
    assert limits == [1, 3]
    variants, _ = management_neighbors({'changes': {'max_same_losses': 1}})
    assert [value['management']['changes']['max_same_losses'] for value in variants if value['parameter'] == 'max_same_losses'] == [1, 2]
    gate = np.where(np.arange(len(random_input['time_s'])) % 3 == 0, 1, 0).astype(np.int8)
    main_random = random_direction(random_input, 7)
    entry_random = random_direction(random_input, 7, gate)
    np.testing.assert_array_equal(entry_random, np.where(gate != 0, main_random, 0))
    assert np.any((gate == 0) & (main_random != 0)), '中期方向まで入口gateで消えていないこと'
    routing = synthetic_routing_audit(observed)
    source_audit = synthetic_context_source_audit()
    return {'逆指値新規の指定101対観測110を確認': True, '観測モデルと指定モデルの収支差': True,
            '全玉会計・次行・上限・返済': True, '乱数prefix8条件': True, '遅延0秒と1秒': True,
            '時計悪化を別カテゴリ好成績で救済しない': True, '利益あり損失0のPF扱い': True,
            '損失撤回制限の0不使用・6変形・連敗下限1': True, '損失撤回制限を別カテゴリで判定': True,
            '乱数中期方向は入口gateで絞らない': True, '二入力ルーティング': routing,
            '自己中期の仕様変換と全件選定': source_audit}


def synthetic_routing_audit(observed: object) -> dict:
    """機能: 合成入力で実際のreplayが二入力と従来入力を使い分けることを確認する。

    引数: observed (module) は観測価格エンジン。返り値: 機構検査の合否 (dict)。
    実データを読まず、検査後はワーカー変数を復元する。
    """
    global INPUTS, OBSERVED
    saved_inputs, saved_observed = INPUTS, OBSERVED
    try:
        synthetic = {'time_s': np.arange(30, dtype=float) * 60., 'last': np.full(30, 100.),
                     'atr': np.ones(30), 'tick': .1, 'start': 0., 'limit': 28. * 60.,
                     'us_open': np.inf, 'session': '合成_Day'}
        INPUTS = {(synthetic['session'], symbol): dict(synthetic) for symbol in SYMBOLS}
        OBSERVED = observed
        state = {key: np.ones(30, dtype=np.int8) for key in INPUTS}
        context = {key: np.where(np.arange(30) < 8, 1, -1).astype(np.int8) for key in INPUTS}
        changes = {'warmup_min': 0., 'entry_cutoff_min': 0., 'entry_mode': 2,
                   'stop_atr': 20., 'main_trail': 100., 'activation_atr': 1000.,
                   'signal_exit': 1, 'cooldown_min': 100., 'timeout_min': 360.}
        management = {'context_source': 'main', 'changes': changes}
        main = replay('合成の中期撤回', state, management, context=context)
        own = replay('合成の自己撤回', state, dict(management, context_source='own'), context=context)
        entry = replay('合成の入口撤回', state, dict(management, context_source='entry'), context=context)
        explicit_entry = replay('合成の入口と同じ中期', state, management, context=state)
        observed_main = replay('合成の観測約定と中期撤回', state, management, observed=True, context=context)
        assert main['ledger_hash'] != entry['ledger_hash']
        assert entry['ledger_hash'] == explicit_entry['ledger_hash']
        assert observed_main['ledger_hash'] == main['ledger_hash']
        assert own['ledger_hash'] == main['ledger_hash'], 'mainとownは与えた配列が同一なら同じ経路'
        try:
            replay('合成の自己中期欠落', state, dict(management, context_source='own'))
        except AssertionError:
            pass
        else:
            raise AssertionError('own設定で中期入力の欠落を受理した')
        try:
            replay('合成の中期欠落', state, management)
        except AssertionError:
            pass
        else:
            raise AssertionError('main設定で中期入力の欠落を受理した')
        return {'main設定で中期反転が台帳を変更': True, 'entry設定で別中期を無視し従来と一致': True,
                'ownも同じ入力ならmainと厳密一致': True, 'own設定の中期入力欠落を拒否': True,
                '観測価格モデルも二入力を維持': True, 'main設定の中期入力欠落を拒否': True}
    finally:
        INPUTS, OBSERVED = saved_inputs, saved_observed


def synthetic_context_source_audit() -> dict:
    """機能: 自己contextだけ相手確認を外し、低成績も全件残す経路を合成確認する。

    引数: なし。返り値: 合成監査 (dict)。実データや実成績は読まない。
    """
    from copy import deepcopy
    from types import SimpleNamespace
    global SIGNALS
    previous = SIGNALS
    calls = []

    def fake_main(specification: dict, inputs: dict) -> dict:
        """機能: 機械的な引数転送を記録する架空の中期生成器。

        引数: specification/inputs (dict)。返り値: 空配列の辞書 (dict)。
        """
        calls.append(deepcopy(specification))
        return {key: np.zeros(2, dtype=np.int8) for key in inputs}

    original = {'id': '合成', 'params': {'peer_confirm': True, 'peer_multiplier': .8,
                'clock_multiplier': 1.2, 'confirmation_multiplier': .8}}
    before = deepcopy(original)
    try:
        SIGNALS = SimpleNamespace(main_directions=fake_main)
        for source in ('entry', 'main', 'own'):
            context_for_spec(original, {('合成', 'TOPIX'): {}}, source)
        assert original == before and calls[0] == calls[1] == original
        assert calls[2]['params'] == dict(original['params'], peer_confirm=False)
        candidates = [{'id': f'合成{i:03d}', 'failures': ['不合格'] if i % 2 else [],
                       'ledger_hash': '全件同一', 'signal_family': '同じ思想'} for i in range(84)]
        assert select_candidates(candidates[::-1]) == candidates
        try:
            select_candidates(candidates + [candidates[0]])
        except AssertionError:
            pass
        else:
            raise AssertionError('重複候補を受理した')
        return {'入口仕様を変更せず自己中期だけpeerFalse': True,
                '時間・相手遅延・確認の倍率を保持': True,
                '84件全て最低基準と重複台帳に無関係に検査': True, 'ID重複を拒否': True}
    finally:
        SIGNALS = previous


def write_design() -> None:
    """機能: 最初に読む設計説明と実行手順を保存する。

    引数: なし。返り値: なし (None)。
    """
    text = """# 第6反復の反証設計

12入口×7管理の全84条件を、最低基準や順位で絞らず一次反証・64seed×2方式の乱数・指定8波へ進める。既知13セッションだけを使用し、現在保存物/APIは使用しない。

入口は相手確認ありの既存列。保有contextはB0=なし、C=相手一致の中期、S=自己の中期だけ。近傍で入口と中期の両方を再生成するが、Sは中期だけpeer_confirm=Falseにする。Sの相手遅延近傍は入口に作用し中期には作用しない。短期閾値だけの近傍でも中期は不変。基準と管理近傍は同じcontextを保つ。

遅延1/5/15秒と方向反転は両入力へ適用。常時買売・無予測対照は両入力を同じ定数又は同じ30分乱数へ置換し、真の中期方向を残さない。発火限定は入口だけを元非0時刻で絞る。B0はcontextを使用しない。

数値基準・カテゴリは反証規則の固定.jsonを参照。時計・相手遅延、短期閾値、入口幅、管理幅、中立時間を別々に判定する。構造不使用だけ分母から除き、値が偶然不変の近傍は件数を残して表示する。観測価格約定は費用0・指定約定と異なる補足耐性であり、費用を追加するものではない。

同じ入口L000への交換、同じ撤回規則でcontextを短期入口へ戻す等は機構対照。改善候補の選抜は旧主案と同入口L000の両方への75%収支・80%DDを別コードで要求する。良い日だけの切替や最良近傍への差替えはしない。

実行は validation_round6.py --rules-only、主探索固定後 --prepare、全主探索後 --workers 12、乱数は --workers 8 --random。主結果は一次反証の結果.json、無関係対照の要約.json、全明細はadversarial/とrandomized/。現在照合機能はない。
"""
    (HERE / 'validation_round6.md').write_text(text, encoding='utf-8')



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
    verify_observed_derivation()
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
    frozen = runner.read(HERE / '探索条件の固定.json')
    expected_ids = {signal['id'] + '__' + manager['id'] for signal in frozen['signals'] for manager in frozen['managers']}
    assert len(expected_ids) == 84 and {value['id'] for value in selected} == expected_ids, '全84条件の不足・余分'
    if args.random:
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
