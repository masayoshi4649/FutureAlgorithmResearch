"""入口前に観測済みの往復と停止余裕だけで、新規候補を採否する。"""

import math

import numpy as np


REASONS = {1: '特徴不足又は不明', 2: '自己の有効観測が不足', 4: '自己の片道進行が不足',
           8: '相手の有効観測が不足', 16: '相手の片道進行が不足', 32: '最近の逆行に対して停止余裕が不足'}


def apply(prepared: dict, case: dict, features: dict, config: dict) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """
    機能: 当時の価格経路から候補を見送り、採否根拠を保存する。
    引数: prepared/case/features/config(dict)は不変実行入力・候補・過去特徴・固定条件。
    返り値: tupleは採否bool配列、理由bit配列、候補ごとの数値診断。将来の損益を参照しない。
    """
    record, mode = prepared['record'], config['filter_mode']
    assert mode in ('NONE', 'E', 'EP', 'N', 'EN')
    assert config['own_path'] in ('PUBLIC', 'NORMAL')
    n, tick = len(record['seq']), float(record['tick'])
    allowed, reasons = np.ones(n, np.bool_), np.zeros(n, np.int32)
    initial_width = max(2, math.ceil(prepared['reference_open']*config['initial_stop_fraction']/tick-1e-10))*tick
    diagnostics = []
    for decision in case['decisions']:
        row, side = int(decision['row']), int(decision['side'])
        assert side == int(case['event'][row]) and int(record['seq'][row]) == int(decision['raw_seq'])
        entry_quote = float(record['ask'][row] if side == 1 else record['bid'][row])
        liquidation = float(record['bid'][row] if side == 1 else record['ask'][row])
        support = float(case['support_price'][row])
        support_line, independent = support-side*config['support_ticks']*tick, entry_quote-side*initial_width
        stop = max(support_line, independent) if side == 1 else min(support_line, independent)
        clearance = side*(liquidation-stop)/tick
        feature = features.get(row)
        reason, own, peer = 0, None, None
        if mode != 'NONE':
            if feature is None:
                reason |= 1
            else:
                own_source = 'own' if config['own_path'] == 'PUBLIC' else 'own_normal'
                own = feature[own_source].get(str(config['window']))
                peer = feature['peer'].get(str(config['window']))
                if own is None or not own['known']:
                    reason |= 1
                elif own['count'] < 3:
                    reason |= 2
                else:
                    if 'E' in mode:
                        efficiency = own['efficiency']
                        if efficiency is not None and not math.isfinite(efficiency):
                            reason |= 1
                        elif efficiency is None or efficiency <= .5:
                            reason |= 4
                    if 'N' in mode:
                        adverse = own['max_adverse_ticks']
                        if adverse is None or not math.isfinite(adverse) or not math.isfinite(clearance):
                            reason |= 1
                        elif not clearance > adverse+1e-9:
                            reason |= 32
                if 'P' in mode:
                    if peer is None or not peer['known']:
                        reason |= 1
                    elif peer['count'] < 3:
                        reason |= 8
                    else:
                        efficiency = peer['efficiency']
                        if efficiency is not None and not math.isfinite(efficiency):
                            reason |= 1
                        elif efficiency is None or efficiency <= .5:
                            reason |= 16
        allowed[row], reasons[row] = reason == 0, reason
        diagnostics.append(dict(row=row, raw_seq=int(record['seq'][row]), side=side,
            time_s=float(record['time_s'][row]), mode=mode, window=config['window'], own_path=config['own_path'],
            entry_quote=entry_quote, liquidation_quote=liquidation, support=support,
            expected_stop=stop, clearance_ticks=clearance, accepted=reason == 0, reason=reason,
            own=own, peer=peer))
    assert len(diagnostics) == int(np.count_nonzero(case['event']))
    return allowed, reasons, diagnostics
