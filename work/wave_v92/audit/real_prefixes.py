"""新条件の全場損益を見る前に、実観測の短い接頭部で執行の因果性を検査する。"""

from pathlib import Path

import numpy as np

import common
import accounting as independent_accounting
from execution_checks import prefix, prefix_equal
import protocol


def main():
    """
    機能: 全条件の実観測接頭部を再生し、将来を切断・毒入れしても過去注文と極値が不変か確認する。
    引数: なし。
    返り値: None。場内の途中会計だけを検査し、採択用全場損益は計算又は閲覧しない。
    """
    import sys
    sys.path.insert(0, str(common.WORK))
    import data
    import strategy
    engine = strategy.ENGINE
    import catalog
    material = data.load_inputs()
    sessions = ('2026-09-24_Night', '2026-09-28_Day', '2026-10-06_Day', '2026-10-09_Night', '2026-10-12_Day')
    counts = dict(実観測接頭部=0, 独立注文会計=0, 未来切断=0, 未来価格毒入れ=0, 未来状態毒入れ=0)
    keys = [(session, symbol) for session in sessions for symbol in common.SYMBOLS]
    for config in catalog.catalog():
        prepared = strategy.prepare(material, config)
        for key in keys:
            value = prepared[key]
            record, signal = prefix(value['record'], value['signal'], min(30000, len(value['record']['time_s'])))
            n = len(record['time_s'])
            assert record['time_s'][-1] < record['limit'] - 300, 'prefix検査に完結場を使いません'
            full = engine.execute(record, signal, config, finish=False)
            partial = dict(full, finish=False)
            independent_accounting.restore(record, partial, config)
            protocol.verify(record, signal, config, full)
            protocol.arm_state(record, signal, config, full)
            if not config.get('persistent_arm'):
                protocol.activation(record, signal, config, full)
            counts['実観測接頭部'] += 1
            counts['独立注文会計'] += len(full['orders'])
            for stop in np.unique(np.rint(np.linspace(1, n - 1, 9)).astype(int)):
                cut_record, cut_signal = prefix(record, signal, stop)
                part = engine.execute(cut_record, cut_signal, config, finish=False)
                prefix_equal(full, part, stop)
                counts['未来切断'] += 1
                future_record = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in record.items()}
                for name in ('price', 'bid', 'ask'):
                    future_record[name][stop:] *= 7
                poisoned_price = engine.execute(future_record, signal, config, finish=False)
                prefix_equal(full, poisoned_price, stop)
                counts['未来価格毒入れ'] += 1
                future_signal = {name: value.copy() if isinstance(value, np.ndarray) else value for name, value in signal.items()}
                used = signal['mapped'][:stop]
                last_g = int(used.max(initial=-1))
                future_signal['mode'][last_g + 1:] = 0
                for name in ('arm_common', 'arm_trend300'):
                    future_signal[name][last_g + 1:] *= -1
                for name in ('current_valid', 'reverse_long', 'reverse_short'):
                    future_signal[name][last_g + 1:] = ~future_signal[name][last_g + 1:]
                future_signal['peer_mid'][last_g+1:] *= 7
                future_signal['peer_valid'][last_g+1:] = ~future_signal['peer_valid'][last_g+1:]
                future_signal['peer_source'][last_g+1:] += 10000
                future_signal['event'][stop:] *= -1
                future_signal['quality'][stop:] = ~future_signal['quality'][stop:]
                future_signal['reset'][stop:] = ~future_signal['reset'][stop:]
                poisoned_state = engine.execute(record, future_signal, config, finish=False)
                prefix_equal(full, poisoned_state, stop)
                counts['未来状態毒入れ'] += 1
        del prepared
        print(f'{config["id"]} 実10接頭部・未来切断・価格状態毒入れ合格', flush=True)
    paths = [Path(__file__), Path(common.__file__), Path(independent_accounting.__file__), Path(protocol.__file__),
             common.HERE / 'execution_checks.py', common.HERE/'entry_checks.py', common.WORK / 'data.py', *[common.WORK / name for name in ('catalog.py', 'strategy.py', 'engine.py')], *material['paths']]
    common.save('全条件の実観測接頭部と回復及び中心帰還の未来不変.json',
                dict(全合格=True, 全期間既知=True, 条件数=len(catalog.catalog()), 検査件数=counts,
                     完結実損益集計=0, 採択用実損益閲覧=0, 現在API取得=0, 実注文=0, 旧変更=0,
                     SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
