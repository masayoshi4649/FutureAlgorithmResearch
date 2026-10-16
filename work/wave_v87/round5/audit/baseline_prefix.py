"""既存.05対照だけを原本途中で切り、売買・影・強度証跡の過去不変を確かめる。"""

import hashlib
import json
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[2]
sys.path.insert(0, str(WORK))
import strategy
import catalog


def clip(value, count, length):
    """
    機能: 原本と同じ行数の特徴だけを同じ過去地点で切断する。
    引数: value (object)、count/length (int) は切断地点と原行数。
    返り値: object の過去資料の独立コピー。
    """
    if isinstance(value, dict):
        return {name: clip(item, count, length) for name, item in value.items()}
    if isinstance(value, tuple):
        return tuple(clip(item, count, length) for item in value)
    if isinstance(value, list):
        return [clip(item, count, length) for item in value]
    if isinstance(value, np.ndarray):
        return value[:count].copy() if value.ndim and len(value) == length else value.copy()
    return value


def compare(full, part, count):
    """
    機能: 完了済みイベントと逐次配列を独立した列定義で切り揃えて照合する。
    引数: full/part (dict)、count (int)。
    返り値: int の一致した配列数。
    """
    events = dict(orders=0, trades=7, cycles=2, prepare_events=1, entry_preparations=1,
                  slot_events=0, adjustment_events=0, budget_events=0, branch_events=0,
                  risk_events=0, guard_events=0, block_events=0, time_events=0,
                  dynamic_events=0, reentry_events=1, profit_reentry_events=0,
                  support_events=0, normal_support_events=0, support_strength_events=0)
    curves = ('curve', 'atr_curve', 'control_curve', 'slot_curve', 'branch_curve',
              'guard_curve', 'plans', 'execution_plans', 'support_curve', 'normal_support_curve')
    checked = 0
    for name, column in events.items():
        if name not in full:
            continue
        a, b = full[name], part[name]
        np.testing.assert_array_equal(a[a[:, column] < count], b[b[:, column] < count], err_msg=name)
        checked += 1
    for name in curves:
        if name in full:
            np.testing.assert_array_equal(full[name][:count], part[name][:count], err_msg=name)
            checked += 1
    for name in ('shadow', 'normal_shadow'):
        if name in full:
            checked += compare(full[name], part[name], count)
    if 'gate_evidence' in full:
        for name, value in full['gate_evidence'].items():
            if isinstance(value, np.ndarray):
                np.testing.assert_array_equal(value[:count], part['gate_evidence'][name][:count])
                checked += 1
    return checked


def main():
    """
    機能: 日夜両商品・既存四条件・二約定で、注文前後と期間途中の未来を切断する。
    引数: なし。
    返り値: None。新強度.25/.5の損益を実行せず、監査証拠JSONを保存する。
    """
    inputs, signals, hashes = strategy.prepare.old.load_inputs(verify=True)
    sessions = ('2026-09-25_Day', '2026-09-22_Night')
    inputs = {key:value for key,value in inputs.items() if key[0] in sessions}
    signals = {name:{key:value for key,value in values.items() if key in inputs}
               for name,values in signals.items()}
    features = strategy.initialize(inputs, signals)
    configs = [config for config in catalog.catalog() if config['threshold_atr'] == .05]
    rows = []
    for key, ready in sorted(inputs.items()):
        n = len(ready['last'])
        for observed in (True, False):
            for config in configs:
                full, _ = strategy.play(config, ready, features[key], observed)
                cuts = {int(n*.37), int(n*.78)}
                entries = full['orders'][full['orders'][:, 7] == 1]
                if len(entries):
                    row = int(entries[0, 0])
                    cuts.update((max(2, row), min(n-1, row+1)))
                checked = 0
                for count in sorted(cuts):
                    part, _ = strategy.play(config, clip(ready, count, n), clip(features[key], count, n), observed)
                    checked += compare(full, part, count)
                rows.append(dict(セッション=key[0], 銘柄=key[1], ID=config['id'], 観測約定=observed,
                                 切断数=len(cuts), 過去配列一致数=checked, 合格=True))
        print(key[0], key[1], '既存四条件の売買未来切断一致', flush=True)
    output = dict(全合格=True, 条件口座数=len(rows), 切断数=sum(r['切断数'] for r in rows),
                  過去配列一致数=sum(r['過去配列一致数'] for r in rows), 新強度実データ売買=False,
                  入力SHA256=hashes, 検査=rows,
                  実装SHA256={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in (WORK/'catalog.py', WORK/'strategy.py', HERE/'baseline_prefix.py')},
                  限界='新閾値の実取引因果照合は親による固定後に行う。本検査は旧.05閾値の完全一致対照だけを再生した。')
    (HERE/'既存005四対照の実原本売買未来切断.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
