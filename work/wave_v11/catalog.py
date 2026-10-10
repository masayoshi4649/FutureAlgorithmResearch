"""文献由来の予測仮説と注文条件を組み合わせる、探索前に固定する条件表。"""

from __future__ import annotations

import numpy as np

import signals

PHILOSOPHIES = ['予測主導', '予測と注文の組合せ', '注文主導']


def configs() -> list[dict]:
    """機能: 予測主導・組合せ・注文主導の全条件を作成する。

    引数: なし。返り値: 一意の識別子を持つ設定一覧 (list[dict])。
    """
    result = []
    entries = [dict(id='E0', label='検知後成行', entry_mode=1., entry_offset=0.),
               dict(id='E1', label='0.25ATR追跡新規', entry_mode=0., entry_offset=.25),
               dict(id='E2', label='0.50ATR追跡新規', entry_mode=0., entry_offset=.5),
               dict(id='E3', label='0.25ATR固定逆指値', entry_mode=2., entry_offset=.25)]
    exits = [dict(id='X0', label='損切1ATR・利確2ATR', initial_stop_atr=1., trail_atr=None,
                  trail_start_atr=None, target_atr=2.),
             dict(id='X1', label='初期1ATR・追跡1ATR', initial_stop_atr=1., trail_atr=1.),
             dict(id='X2', label='初期0.75ATR・順行1ATRから追跡2ATR', initial_stop_atr=.75,
                  trail_atr=2., trail_start_atr=1.),
             dict(id='X3', label='初期1.5ATR・順行1ATRで追跡0.5ATR', initial_stop_atr=1.5,
                  trail_atr=1.5, tighten_trigger_atr=1., tighten_width_atr=.5),
             dict(id='X4', label='初期1ATR・順行1ATRから最大順行の半分保護', initial_stop_atr=1.,
                  trail_atr=2., protect_trigger_atr=1., protect_fraction=.5),
             dict(id='X5', label='初期1.5ATR・板反対で追跡0.5ATR', initial_stop_atr=1.5,
                  trail_atr=2., weak_width_atr=.5, state_trigger_atr=.5)]
    for profile in signals.profiles():
        family = profile.get('family', profile['id'])
        base = dict(family=family, signal=profile['id'], group=profile['group'], engine='single',
                    max_positions=1, cooldown_min=5., warmup_min=20., max_age_min=2.)
        for horizon in [5, 15, 30, 60]:
            result.append(dict(base, id=f"P_{profile['id']}_{horizon:02d}", philosophy=PHILOSOPHIES[0],
                               label=f"{profile.get('label',profile['id'])}・{horizon}分後返済",
                               entry_mode=1., entry_offset=0., holding_min=float(horizon),
                               initial_stop_atr=None, trail_atr=None, trail_start_atr=None,
                               entry_id='成行', exit_id=f'{horizon}分固定', us_mode='なし'))
        for entry in entries:
            for exit_rule in exits:
                for pause in [False, True]:
                    cfg = dict(base, id=f"H_{profile['id']}_{entry['id']}_{exit_rule['id']}_Z{int(pause)}",
                               philosophy=PHILOSOPHIES[1], label=f"{profile.get('label',profile['id'])}／{entry['label']}／{exit_rule['label']}",
                               entry_id=entry['id'], exit_id=exit_rule['id'],
                               us_mode='新規停止' if pause else 'なし')
                    cfg.update({k:v for k,v in entry.items() if k not in ('id','label')})
                    cfg.update({k:v for k,v in exit_rule.items() if k not in ('id','label')})
                    result.append(cfg)
    import orders
    result.extend([
        dict(id='B_旧T12', family='P23', signal='P23', group='旧方式比較', engine='single',
             philosophy=PHILOSOPHIES[1], label='前回のEMA収束＋板反転・追跡新規0.25ATR・返済2ATR',
             max_positions=1, entry_mode=0., entry_offset=.25, max_age_min=10., cooldown_min=10.,
             warmup_min=20., initial_stop_atr=2., trail_atr=2., us_mode='なし', entry_id='前回固定', exit_id='前回固定'),
        dict(id='B_旧S17', family='P24', signal='P24', group='旧方式比較', engine='single',
             philosophy=PHILOSOPHIES[1], label='前回の両銘柄板反転・順行待ち・初期0.75ATR・追跡2ATR',
             max_positions=1, entry_mode=0., entry_offset=0., max_age_min=2., cooldown_min=5.,
             warmup_min=20., initial_stop_atr=.75, trail_atr=2., trail_start_atr=1.,
             us_mode='新規停止', entry_id='前回固定', exit_id='前回固定')])
    for profile in signals.profiles():
        for original in orders.catalog():
            if original['family'] not in ('O07','O08'):
                continue
            cfg = dict(original, id=f"M_{profile['id']}_{original['id']}",
                       philosophy=PHILOSOPHIES[1], engine='orders',
                       signal_family=profile.get('family',profile['id']), signal=profile['id'],
                       group=profile['group'], label=f"{profile['label']}／{original['label']}")
            cfg['exact_rules'] = orders.explain(cfg)
            result.append(cfg)
    for original in orders.catalog():
        cfg = dict(original, philosophy=PHILOSOPHIES[2], engine='orders')
        cfg.setdefault('signal', cfg['family'])
        cfg.setdefault('label', cfg['id'])
        result.append(cfg)
    if len({c['id'] for c in result}) != len(result):
        raise ValueError('条件IDが重複しています。')
    return result
