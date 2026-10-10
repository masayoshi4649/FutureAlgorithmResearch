"""出来高代理の追加価値を、共通価格準備と固定注文管理で比較する設計。"""

from __future__ import annotations

from copy import deepcopy


PARAMETERS = dict(
    warmup_seconds=1200., freshness_seconds=60., minimum_events=5,
    progress_atr=.25, progress_ticks=2., stall_fraction=.25,
    stall_atr=.10, stall_ticks=1., confirmation_atr=.25, confirmation_ticks=2.,
    setup_lifetime_min=300., setup_lifetime_windows=2., signal_lifetime_seconds=120.,
    peer_delay_seconds=60., peer_recent_atr=.10, peer_recent_ticks=1.,
)
PRIMARY_SIGNAL = 'Q034'


def catalog() -> list[dict]:
    """機能: 価格準備2窓・情報5種・反応3枝・他市場3扱いの90条件を返す。

    引数: なし。返り値: 一意な固定設計 (list[dict])。損益は参照しない。
    """
    output = []
    for window in (120., 600.):
        for proxy, threshold in (('price', 0.), ('all_volume', 2.), ('all_volume', 5.),
                                 ('stable_volume', 2.), ('stable_volume', 5.)):
            for branch in ('reversal', 'breakout', 'automatic'):
                for peer_mode in ('none', 'veto', 'confirm'):
                    label = f'Q{len(output):03d}'
                    params = dict(PARAMETERS, window_seconds=window, proxy=proxy,
                        volume_threshold=threshold, branch=branch, peer_mode=peer_mode)
                    output.append(dict(id=label, params=params, primary=label == PRIMARY_SIGNAL))
    assert len(output) == 90
    main = next(r for r in output if r['id'] == PRIMARY_SIGNAL)
    assert main['params']['proxy'] == 'stable_volume' and main['params']['window_seconds'] == 120.
    assert main['params']['volume_threshold'] == 2. and main['params']['branch'] == 'automatic'
    assert main['params']['peer_mode'] == 'veto'
    return deepcopy(output)


def variants() -> list[dict]:
    """機能: 窓だけの感度と観測価格約定を別診断として返す。

    引数: なし。返り値: 4変形の一覧 (list[dict])。
    """
    return [dict(id='V000', clock_scale=1., observed_fill=False),
        dict(id='C080', clock_scale=.8, observed_fill=False),
        dict(id='C120', clock_scale=1.2, observed_fill=False),
        dict(id='O000', clock_scale=1., observed_fill=True)]


def conditions() -> list[dict]:
    """機能: 90信号と旧H019比較の主91・診断273を一意に列挙する。

    引数: なし。返り値: 全364条件 (list[dict])。主仮説を結果後に差し替えない。
    """
    output = []
    for signal in catalog() + [dict(id='H019', primary=False, baseline=True)]:
        for variant in variants():
            output.append(dict(id=signal['id'] + '__' + variant['id'], signal_id=signal['id'],
                signal=signal, variant_id=variant['id'], clock_scale=variant['clock_scale'],
                observed_fill=variant['observed_fill'], primary=variant['id'] == 'V000'))
    assert len(output) == len({r['id'] for r in output}) == 364
    return output


def supplementary_conditions() -> list[dict]:
    """機能: 主Q034の64方向乱数と全方向反転を別計数で固定する。

    引数: なし。返り値: 補助65条件 (list[dict])。最良の乱数は選択しない。
    """
    source = next(r for r in conditions() if r['id'] == PRIMARY_SIGNAL + '__V000')
    rows = [dict(source, id=PRIMARY_SIGNAL + f'__R{seed:03d}', primary=False,
        random_seed=seed, supplementary=True) for seed in range(64)]
    rows.append(dict(source, id=PRIMARY_SIGNAL + '__REV', primary=False,
        reverse_direction=True, supplementary=True))
    return rows
