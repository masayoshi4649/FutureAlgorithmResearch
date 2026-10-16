"""全32の実入力と金融接口だけを照合し、注文と損益は再生しない。"""

import runpy
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
RESEARCH = runpy.run_path(str(HERE/'research.py'))


def main() -> None:
    """
    機能: 64口座の正常列と19条件の接続契約を新金融再生前に確かめる。
    引数: なし。
    返り値: None。小さい接続証跡を保存し、executeは一度も呼ばない。
    """
    module, read, digest, save = (RESEARCH[name] for name in ('module', 'read', 'digest', 'save'))
    root = RESEARCH['ROOT']
    before = {str(path.relative_to(root)): digest(path) for path in
        [Path(__file__), HERE/'research.py', HERE/'base.py', HERE/'engine/finance_adapter.py', HERE/'engine/adapter.py']}
    material = module('103接続前の素材', HERE/'base.py').load()
    adapter = module('103接続前の旧設定', HERE/'engine/adapter.py')
    strategy = module('103接続前の読取準備', root/'work/wave_v102/strategy.py')
    prepared = strategy.prepare(material, adapter.reference_config())
    activity = module('103接続前の活動', HERE/'activity/data.py')
    finance = module('103接続前の金融接口', HERE/'engine/finance_adapter.py')
    cases = module('103接続前の条件', HERE/'catalog.py').catalog()
    checks = dict(正常五列口座数=0, 単一及び主の接続数=0, 実配分数量の接続数=0)
    for session in material['metadata']['sessions']:
        payload = activity.load_session(session)
        for symbol in ('TOPIX', 'NK225'):
            account, value = payload['accounts'][symbol], prepared[session, symbol]
            for config in cases:
                if config['kind'] == 'previous':
                    continue
                routes = list(zip(('C1', 'R1'), config['allocations'][symbol])) if config['kind'] == 'portfolio' else [(config['id'], 1)]
                for ident, quantity in routes:
                    signal, settings, decisions = finance.connect(account, ident, value['record'],
                        value['signal'], adapter.reference_config(), value['reference_open'], quantity)
                    assert signal['trend_width'] == value['signal']['trend_width']
                    assert settings['trend_hold_seconds'] == 1800. and settings['trend_growth_mode'] == 0
                    assert len(decisions) == np.count_nonzero(signal['event'])
                    checks['実配分数量の接続数' if config['kind'] == 'portfolio' else '単一及び主の接続数'] += 1
            checks['正常五列口座数'] += 1
        print(session+' 接続だけ合格・金融0', flush=True)
    assert checks == dict(正常五列口座数=64, 単一及び主の接続数=960, 実配分数量の接続数=384)
    assert before == {name: digest(root/name) for name in before}
    save(HERE/'金融前の実入力64口座の接続.json', dict(全合格=True, 検査=checks,
        source_SHA256=before, 活動SHA256=digest(HERE/'activity/全32の状態可用性と発火.json'),
        正式金融再生=0, API取得=0, 実注文=0))


if __name__ == '__main__':
    main()
