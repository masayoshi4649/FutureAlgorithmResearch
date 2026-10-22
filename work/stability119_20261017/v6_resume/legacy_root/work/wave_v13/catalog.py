"""指定価格モデルで比較する入口・出口・有限複数玉の条件を定義する。"""

from __future__ import annotations

import data


def profiles() -> list[dict]:
    """機能: 既存24仮説と今回の新仮説を統合する。

    引数: なし。返り値: 信号の名称・思想・出典を含む一覧 (list[dict])。
    """
    import new_signals
    old = [dict(p, origin='既存') for p in data.signals_module().profiles()]
    new = [dict(p, origin='新規') for p in new_signals.profiles()]
    return old + new


def configs() -> list[dict]:
    """機能: 選択前に固定する全売買条件を返す。

    引数: なし。返り値: 重複しないIDと機械的な数値条件の一覧 (list[dict])。
    """
    entries = [dict(code='E0', label='次行価格', entry_mode='market', entry_atr=0.),
               dict(code='E1', label='0.25ATR追跡新規', entry_mode='trail', entry_atr=.25),
               dict(code='E2', label='0.50ATR追跡新規', entry_mode='trail', entry_atr=.5),
               dict(code='E3', label='0.25ATR逆指値新規', entry_mode='stop', entry_atr=.25)]
    exits = [dict(code='X0', label='損切1・利確2', initial_stop_atr=1., target_atr=2., trail_atr=None),
             dict(code='X1', label='損切1・追跡1', initial_stop_atr=1., trail_atr=1.),
             dict(code='X2', label='損切0.75・順行1から追跡2', initial_stop_atr=.75, trail_atr=2., trail_start_atr=1.),
             dict(code='X3', label='順行1で追跡0.5へ短縮', initial_stop_atr=1.5, trail_atr=1.5,
                  tighten_trigger_atr=1., tighten_width_atr=.5),
             dict(code='X4', label='順行1から利益の半分を保護', initial_stop_atr=1., trail_atr=2.,
                  protect_trigger_atr=1., protect_fraction=.5),
             dict(code='X5', label='板が反対なら追跡短縮', initial_stop_atr=1.5, trail_atr=2.,
                  weak_width_atr=.5, state_trigger_atr=.5)]
    extras = [dict(code='A0', label='小損切りと早い利益保護', entry_mode='market', entry_atr=0.,
                   initial_stop_atr=.75, trail_atr=.75, trail_start_atr=.5, breakeven_trigger_atr=1.),
              dict(code='A1', label='追跡新規と利益75%保護', entry_mode='trail', entry_atr=.25,
                   initial_stop_atr=1., trail_atr=1.5, protect_trigger_atr=1., protect_fraction=.75),
              dict(code='A2', label='浅い押し戻り指値', entry_mode='limit', entry_atr=.25,
                   initial_stop_atr=1., target_atr=1.5, trail_atr=None, max_age_min=5.),
              dict(code='A3', label='深い押し戻り指値', entry_mode='limit', entry_atr=.5,
                   initial_stop_atr=1.5, target_atr=2.5, trail_atr=None, max_age_min=10.),
              dict(code='A4', label='強い突破だけ逆指値', entry_mode='stop', entry_atr=.5,
                   initial_stop_atr=.75, trail_atr=1.5),
              dict(code='A5', label='長く停滞した建玉の出口短縮', entry_mode='trail', entry_atr=.25,
                   initial_stop_atr=.75, trail_atr=1., trail_start_atr=.5, time_tighten_min=30., time_width_atr=.25)]
    multiples = [dict(code='L0', label='３枚の段階利確と残りの追跡', max_legs=3, add_mode='simultaneous',
                      initial_stop_atr=1., trail_atr=1.5, trail_start_atr=1., leg_targets=[.75, 1.5, None]),
                 dict(code='L1', label='順行してから３枚まで増玉', max_legs=3, add_mode='pyramid', add_step_atr=.5,
                      initial_stop_atr=.75, trail_atr=1.5, trail_start_atr=.5),
                 dict(code='L2', label='３枚に限定した逆行追加', max_legs=3, add_mode='grid', add_step_atr=.5,
                      initial_stop_atr=2., target_atr=.75, trail_atr=None, holding_min=60.),
                 dict(code='L3', label='２枚で早期利確と継続保有', max_legs=2, add_mode='simultaneous',
                      initial_stop_atr=.75, trail_atr=1.5, trail_start_atr=.5, leg_targets=[.5, None])]
    rows = []
    for profile in profiles():
        family = profile['id']
        base = dict(family=family, group=profile['group'], origin=profile['origin'],
                    max_legs=1, cooldown_min=5., warmup_min=20., max_age_min=2., entry_deadline_min=30., trail_start_atr=0.)
        for sign in [1, -1]:
            signed = dict(base, signal_multiplier=sign)
            tag = '正方向' if sign == 1 else '反対方向'
            for minutes in [5., 15., 30., 60.]:
                rows.append(dict(signed, id=f'{family}_R{sign}_T{int(minutes):02}', philosophy='予測を固定時間で評価',
                                 label=f'{profile["label"]}・{tag}・{int(minutes)}分返済',
                                 entry_mode='market', entry_atr=0., initial_stop_atr=None,
                                 trail_atr=None, holding_min=minutes, us_pause=False))
            for entry in entries:
                for exit_rule in exits:
                    for pause in [False, True]:
                        cfg = dict(signed, id=f'{family}_R{sign}_{entry["code"]}_{exit_rule["code"]}_U{int(pause)}',
                                   philosophy='予測と単建玉管理', label=f'{profile["label"]}・{tag}／{entry["label"]}／{exit_rule["label"]}', us_pause=pause)
                        cfg.update({k:v for k,v in entry.items() if k not in ['code', 'label']})
                        cfg.update({k:v for k,v in exit_rule.items() if k not in ['code', 'label']})
                        rows.append(cfg)
            for strategy in extras + multiples:
                for pause in [False, True]:
                    cfg = dict(signed, id=f'{family}_R{sign}_{strategy["code"]}_U{int(pause)}',
                               philosophy='予測と複数建玉管理' if strategy['code'].startswith('L') else '新しい入口と利益保護',
                               label=f'{profile["label"]}・{tag}／{strategy["label"]}',
                               entry_mode='market', entry_atr=0., us_pause=pause)
                    cfg.update({k:v for k,v in strategy.items() if k not in ['code', 'label']})
                    rows.append(cfg)

    # ----------------------------------------
    # 価格方向を予測しない定刻信号は、固定乱数も含めて事後に選び直さない。
    for family, label in [('Q01', '定刻買い'), ('Q02', '定刻売り'), ('Q03', '交互方向'), ('Q04', '固定コイントス')]:
        for width in [.5, 1., 1.5]:
            for style in ['single', 'simultaneous', 'pyramid', 'grid', 'hedge', 'straddle']:
                cfg = dict(id=f'{family}_{style}_W{width:g}', family=family, group='注文主導', origin='注文方式',
                           philosophy='方向予測なしの注文', label=f'{label}／{style}／幅{width:g}ATR',
                           signal_multiplier=1, entry_mode='straddle' if style == 'straddle' else 'market', entry_atr=width,
                           initial_stop_atr=width, trail_atr=width*2, trail_start_atr=width,
                           cooldown_min=5., warmup_min=20., max_age_min=10., entry_deadline_min=30.,
                           max_legs=1 if style in ['single', 'straddle'] else 2 if style == 'hedge' else 3,
                           add_mode='none' if style in ['single', 'straddle'] else style, add_step_atr=width,
                           us_pause=False, holding_min=120.)
                if style == 'simultaneous':
                    cfg['leg_targets'] = [width, width*2, None]
                if style == 'grid':
                    cfg.update(initial_stop_atr=width*3, target_atr=width, trail_atr=None)
                rows.append(cfg)
    rows.extend([
        dict(id='旧主候補_P01', family='P01', group='平均回帰', origin='既存固定', philosophy='固定比較',
             label='前回の平均乖離反発・追跡新規・順行後追跡', max_legs=1, signal_multiplier=1,
             entry_mode='trail', entry_atr=.25, initial_stop_atr=.75, trail_atr=2., trail_start_atr=1.,
             cooldown_min=5., warmup_min=20., max_age_min=2., entry_deadline_min=30., us_pause=True),
        dict(id='旧T12', family='P23', group='旧方式比較', origin='既存固定', philosophy='固定比較',
             label='EMA収束と板反転・追跡新規0.25・追跡2', max_legs=1, signal_multiplier=1,
             entry_mode='trail', entry_atr=.25, initial_stop_atr=2., trail_atr=2.,
             cooldown_min=10., warmup_min=20., max_age_min=10., entry_deadline_min=30., us_pause=False, trail_start_atr=0.),
        dict(id='旧S17', family='P24', group='旧方式比較', origin='既存固定', philosophy='固定比較',
             label='両銘柄の板反転・順行後追跡', max_legs=1, signal_multiplier=1,
             entry_mode='trail', entry_atr=0., initial_stop_atr=.75, trail_atr=2., trail_start_atr=1.,
             cooldown_min=5., warmup_min=20., max_age_min=2., entry_deadline_min=30., us_pause=True)])
    assert len({r['id'] for r in rows}) == len(rows)
    return rows
