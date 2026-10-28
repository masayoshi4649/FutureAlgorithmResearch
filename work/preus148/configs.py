"""米国開始前に限定する、事前登録済みの対称売買条件。"""

from copy import deepcopy


BASE = {
    "id": "P01",
    "description": "5分・10分の方向一致で5枚、40pt順行後5枚追加",
    "fast_window": 5,
    "slow_window": 10,
    "minimum_fast_speed": 4.0,
    "minimum_slow_speed": 1.0,
    "minimum_acceleration": 0.0,
    "require_acceleration": False,
    "entry_confirm_seconds": 15.0,
    "hard_stop_points": 100.0,
    "refutation_seconds": 30.0,
    "activation_points": 100.0,
    "trail_points": 80.0,
    "cooldown_seconds": 60.0,
    "quantities": [5, 5],
    "add_gain_points": [40.0],
    "add_wait_seconds": 30.0,
    "max_per_side": 10,
    "cutoff_before_us_seconds": 900.0,
    "quote_unknown_seconds": 120.0,
    "confirmation_gap_seconds": 5.0,
    "fee_yen": 0.0,
}


def configurations():
    """
    機能: 一因子または同じ利確設計の強弱で構成した16条件を返す。
    引数: なし。
    返り値: list[dict]。各辞書は独立した、変更可能な設定値。
    """
    changes = [
        ("P01", BASE["description"], {}),
        ("P02", "方向一致に、同じ窓の傾きが順方向へ強まる条件を追加",
         {"require_acceleration": True, "minimum_acceleration": 1.0}),
        ("P03", "短い方向窓を3分に変更", {"fast_window": 3}),
        ("P04", "長い方向支持窓を20分に変更", {"slow_window": 20}),
        ("P05", "3分・5分の短い方向一致", {"fast_window": 3, "slow_window": 5}),
        ("P06", "入口の方向一致を30秒確認", {"entry_confirm_seconds": 30.0}),
        ("P07", "60pt順行で40ptトレール開始", {"activation_points": 60.0, "trail_points": 40.0}),
        ("P08", "160pt順行で120ptトレール開始", {"activation_points": 160.0, "trail_points": 120.0}),
        ("P09", "100pt順行後のトレール幅だけ40ptへ短縮", {"trail_points": 40.0}),
        ("P10", "初期損切り幅を140ptに変更", {"hard_stop_points": 140.0}),
        ("P11", "逆向きの方向一致を15秒で損切り判断", {"refutation_seconds": 15.0}),
        ("P12", "逆向きの方向一致を60秒待って損切り判断", {"refutation_seconds": 60.0}),
        ("P13", "全返済後の再開待ちを30秒へ短縮", {"cooldown_seconds": 30.0}),
        ("P14", "全返済後の再開待ちを120秒へ延長", {"cooldown_seconds": 120.0}),
        ("P15", "10枚を最初に一括投入", {"quantities": [10], "add_gain_points": []}),
        ("P16", "2枚から40ptで3枚、80ptで5枚を追撃", {"quantities": [2, 3, 5], "add_gain_points": [40.0, 80.0]}),
    ]
    result = []
    for method, description, delta in changes:
        config = deepcopy(BASE)
        config.update(delta)
        config.update(id=method, description=description)
        result.append(config)
    return result


CONFIGS = configurations()
