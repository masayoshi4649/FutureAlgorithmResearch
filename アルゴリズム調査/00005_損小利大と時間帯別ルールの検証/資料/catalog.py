"""損小利大と時間帯対応を比べる有限の実験条件を、収支を見る前に定義する。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def entry_presets() -> dict[str, dict]:
    """機能: 入口の反発幅・転換の鮮度・返済後休止を比較する８条件を作る。

    引数: なし。返り値: 入口識別子と条件の対応 (dict[str, dict])。
    """
    values = [
        ('E00', '初動・鮮度２分', 0.0, 2.0, 5.0),
        ('E01', '0.1ATR反発・鮮度２分', 0.1, 2.0, 5.0),
        ('E02', '0.25ATR反発・鮮度２分', 0.25, 2.0, 5.0),
        ('E03', '0.5ATR反発・鮮度２分', 0.5, 2.0, 5.0),
        ('E04', '0.25ATR反発・鮮度30秒', 0.25, 0.5, 5.0),
        ('E05', '0.25ATR反発・鮮度10分', 0.25, 10.0, 5.0),
        ('E06', '0.25ATR反発・休止なし', 0.25, 2.0, 0.0),
        ('E07', '前回と同じ入口・休止10分', 0.25, 10.0, 10.0),
    ]
    return {key: dict(entry_name=name, entry_offset=offset, max_age_min=age,
                      cooldown_min=cooldown) for key, name, offset, age, cooldown in values}


def exit_presets() -> dict[str, dict]:
    """機能: 初期損切りと追跡、利益保護、停滞・反対転換による短縮を定義する。

    引数: なし。返り値: 出口識別子と条件の対応 (dict[str, dict])。
    """
    return {
        'X00': dict(exit_name='前回同様２ATR追跡', initial_stop_atr=2., trail_atr=2.),
        'X01': dict(exit_name='常時１ATR追跡', initial_stop_atr=1., trail_atr=1.),
        'X02': dict(exit_name='初期0.75ATR・伸びたら２ATR追跡', initial_stop_atr=.75,
                    trail_atr=2., trail_start_atr=1.),
        'X03': dict(exit_name='初期１ATR・1.5ATR追跡', initial_stop_atr=1.,
                    trail_atr=1.5, trail_start_atr=.5),
        'X04': dict(exit_name='１ATR順行後0.5ATRに短縮', initial_stop_atr=1.25,
                    trail_atr=2., tighten_trigger_atr=1., tighten_width_atr=.5),
        'X05': dict(exit_name='1.5ATR順行後１ATRに短縮', initial_stop_atr=1.25,
                    trail_atr=2., tighten_trigger_atr=1.5, tighten_width_atr=1.),
        'X06': dict(exit_name='0.5ATR順行後0.5ATRに短縮', initial_stop_atr=1.,
                    trail_atr=1.5, tighten_trigger_atr=.5, tighten_width_atr=.5),
        'X07': dict(exit_name='１ATR順行後に最大順行の半分を保護', initial_stop_atr=1.,
                    trail_atr=2., protect_trigger_atr=1., protect_fraction=.5),
        'X08': dict(exit_name='0.75ATR順行後に費用込み建値を保護', initial_stop_atr=1.,
                    trail_atr=2., breakeven_trigger_atr=.75),
        'X09': dict(exit_name='20分で0.5ATR伸びなければ追跡を短縮', initial_stop_atr=1.,
                    trail_atr=2., time_tighten_min=20., time_min_progress_atr=.5,
                    time_width_atr=.5),
        'X10': dict(exit_name='順行後の反対転換で0.5ATRに短縮', initial_stop_atr=1.25,
                    trail_atr=2., state_trigger_atr=.5, opposite_width_atr=.5),
        'X11': dict(exit_name='順行後の板反転で0.75ATRに短縮', initial_stop_atr=1.25,
                    trail_atr=2., state_trigger_atr=.5, weak_width_atr=.75),
    }


def time_presets() -> dict[str, dict]:
    """機能: 米国株通常市場の開始前15分から開始後30分までの５対応を定義する。

    引数: なし。返り値: 時間帯対応識別子と条件の対応 (dict[str, dict])。
    """
    return {
        'Z00': dict(time_name='時間帯による変更なし', us_mode='なし'),
        'Z01': dict(time_name='米国開始前後は新規を休止', us_mode='新規停止'),
        'Z02': dict(time_name='米国開始前に返済し開始後30分まで休止', us_mode='返済'),
        'Z03': dict(time_name='米国開始前後は１ATR追跡', us_mode='幅変更', us_width_atr=1.),
        'Z04': dict(time_name='米国開始前後はEMA方向の一致も必要', us_mode='順行確認'),
    }


def configs(profiles: dict[str, dict]) -> list[dict]:
    """機能: 信号20・入口８・出口12・時間帯５の全組合せを生成する。

    引数: profiles (dict[str, dict]) は信号名と群を持つ定義。
    返り値: 重複しない9,600条件 (list[dict])。
    """
    output = []
    for signal, profile in profiles.items():
        for entry, ep in entry_presets().items():
            for exit_id, xp in exit_presets().items():
                for time_id, zp in time_presets().items():
                    output.append(dict(id=f'{signal}_{entry}_{exit_id}_{time_id}', family=signal,
                                       signal=signal, group=profile.get('group', '転換'),
                                       signal_name=profile.get('name', signal), entry_id=entry,
                                       exit_id=exit_id, time_id=time_id, warmup_min=20.,
                                       us_before_min=15., us_after_min=30., **ep, **xp, **zp))
    return output


def entry_neighbors(config: dict) -> list[str]:
    """機能: 過去の入口設定近傍の成績を使うため、比較する条件IDを列挙する。

    引数: config (dict)。返り値: 同じ信号・出口・時間帯の近傍条件ID (list[str])。
    """
    mapping = {'E00': ['E00', 'E01'], 'E01': ['E00', 'E01', 'E02'],
               'E02': ['E01', 'E02', 'E03'], 'E03': ['E02', 'E03']}
    members = mapping.get(config['entry_id'], ['E02', config['entry_id']])
    return [f"{config['signal']}_{entry}_{config['exit_id']}_{config['time_id']}" for entry in members]


def us_open_time(session: str) -> float:
    """機能: 対象日のニューヨーク09:30を夏時間込みでUnix秒へ変換する。

    引数: session (str)。返り値: 米国通常市場開始のUnix秒 (float)。
    今回の対象日は米国営業日である。将来の祝日判断を行う関数ではない。
    """
    return datetime.fromisoformat(session[:10] + 'T09:30:00').replace(
        tzinfo=ZoneInfo('America/New_York')).timestamp()
