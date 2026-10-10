"""残ったD016について、未検査だった時計と利益保護条件を一律に揺らす。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

import adversarial_round as audit
import discovery_runner as runner
import discovery_signals as signals

HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 条件を先に固定して14近傍を再生し、元候補の変更はしない。

    引数: なし。返り値: なし (None)。旧ソース・原本は変更しない。
    """
    fixed = runner.read(HERE / '探索条件の固定.json')
    signal = next(s for s in fixed['signals'] if s['id'] == 'D016')
    manager = next(s for s in fixed['managers'] if s['id'] == 'D065')
    variants = []
    for name in ['seconds', 'peer_delay_seconds', 'signal_ttl_seconds']:
        for factor in [.8, 1.2]:
            variants.append({'領域': '信号', '変数': name, '倍率': factor, '値': round(signal['params'][name] * factor)})
    for name in ['lock_fraction', 'activation_atr', 'timeout_min', 'cooldown_min']:
        for factor in [.8, 1.2]:
            original = manager['changes'].get(name, audit.managers.BASE[name])
            variants.append({'領域': '管理', '変数': name, '倍率': factor, '値': original * factor})
    plan = {'候補': 'D016__D065', '日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
            '根拠': '一次反証後、未検査の有効な時計・利益保護条件を追加で反証。新採用仕様を選ぶ探索ではない。',
            '全条件': variants, '条件数': len(variants), 'コードSHA256': runner.digest(Path(__file__)),
            '合格基準': '各銘柄で75%以上の条件が黒字かつPF1.20以上、収支中央値が元の50%以上、最悪条件が元利益の-25%以上。',
            '一時変更': '信号の公開カタログを同一プロセス内で一時置換し、finallyで復元。ファイルは変更しない。'}
    frozen_path = HERE / 'D016追加感度の固定.json'
    if frozen_path.exists():
        existing = runner.read(frozen_path)
        assert existing['全条件'] == variants
        plan = existing
    else:
        runner.save(frozen_path, plan)
    audit.initialize()
    base_state = audit.load_state('D016')
    base = audit.replay('基準再現', base_state, manager)
    outputs = []
    for variant in variants:
        name = f"{variant['変数']}×{variant['倍率']}"
        if variant['領域'] == '管理':
            altered = deepcopy(manager)
            altered['changes'][variant['変数']] = variant['値']
            result = audit.replay(name, base_state, altered)
        else:
            altered = deepcopy(signal)
            altered['params'][variant['変数']] = variant['値']
            original_catalog = signals.catalog
            catalog = original_catalog()
            try:
                signals.catalog = lambda: [altered if s['id'] == signal['id'] else s for s in catalog]
                signals.clear_cache()
                direction = signals.build(altered, audit.INPUTS, audit.FEATURES)
            finally:
                signals.catalog = original_catalog
                signals.clear_cache()
            result = audit.replay(name, direction, manager)
        outputs.append(dict(variant=variant, **result))
        print(name, {s: r['net_yen'] for s, r in result['symbols'].items()}, flush=True)
    checks = {}
    for symbol in ['TOPIX', 'NK225']:
        net = np.array([r['symbols'][symbol]['net_yen'] for r in outputs])
        passed = sum(r['symbols'][symbol]['net_yen'] > 0 and (r['symbols'][symbol]['money_ratio'] or 0) >= 1.2 for r in outputs)
        baseline = base['symbols'][symbol]['net_yen']
        checks[symbol] = {'通過条件数': passed, '条件数': len(outputs), '収支中央値': float(np.median(net)), '最悪収支': float(net.min()),
                          '合格': bool(passed >= np.ceil(.75 * len(outputs)) and np.median(net) >= .5 * baseline and net.min() >= -.25 * baseline)}
    runner.save(HERE / 'D016追加感度の結果.json', {'計画': plan, '基準': base, '結果': outputs, '判定': checks, '変更後条件の採用': False,
                '実行時コードSHA256': runner.digest(Path(__file__)), '実装修正': 'JSONへ保存する合否のNumPy論理値をPython boolへ変換。条件・売買・数値判定は不変。'})
    print(checks, flush=True)


if __name__ == '__main__':
    main()
