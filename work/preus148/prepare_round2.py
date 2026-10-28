"""第一巡を保持したまま、欠測確認と押戻り入口だけを分離した第二巡を固定する。"""

from pathlib import Path
from copy import deepcopy
import json
from configs import BASE

HERE = Path(__file__).resolve().parent


def main():
    """追加8条件と独立エンジンを保存する。金融再生はしない。

    引数: なし。
    返り値: None。第一巡の凍結コードは変更しない。
    """
    changes = [
        ('Q01', '更新間隔120秒まで方向確認を維持', {}),
        ('Q02', '確認維持に加え、順方向への加速を要求', dict(require_acceleration=True, minimum_acceleration=1.)),
        ('Q03', '確認維持、3本と10本の方向一致', dict(fast_window=3)),
        ('Q04', '確認維持、5本と20本の方向一致', dict(slow_window=20)),
        ('Q05', '確認維持、速度を12pt毎分と3pt毎分へ引上げ', dict(minimum_fast_speed=12., minimum_slow_speed=3.)),
        ('Q06', '方向一致後40pt押し・30pt再反発で入る', dict(pullback_points=40., rebound_points=30.)),
        ('Q07', '押戻り再反発、初期損切140・利益開始160・追跡120pt', dict(pullback_points=40., rebound_points=30., hard_stop_points=140., activation_points=160., trail_points=120.)),
        ('Q08', '押戻り再反発の長期支持を20本へ延長', dict(pullback_points=40., rebound_points=30., slow_window=20)),
    ]
    configs = []
    for identifier, description, delta in changes:
        config = deepcopy(BASE)
        config.update(id=identifier, description=description, confirmation_gap_seconds=120.,
                      pullback_points=0., rebound_points=0., pullback_expiry_seconds=900.)
        config.update(delta)
        configs.append(config)
    (HERE / 'configs_round2.json').write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding='utf-8')
    source = (HERE / 'engine.py').read_text(encoding='utf-8')
    source = source.replace('"""確定済み価格の勢いで入り、赤字の反証と黒字の追跡を分離する研究エンジン。"""',
        '"""第二巡。第一巡を保持し、価格更新間隔と押戻り再反発の入口だけを比較する。"""')
    source = source.replace('config["confirmation_gap_seconds"],\n', 'config["confirmation_gap_seconds"],\n        config["pullback_points"], config["rebound_points"], config["pullback_expiry_seconds"],\n')
    source = source.replace('    last_liquidation = np.nan\n', '    last_liquidation = np.nan\n    arm_side = 0\n    arm_phase = 0\n    arm_best = 0.0\n    arm_extreme = 0.0\n    arm_since = 0.0\n')
    old = '        if side == 0 and entry_direction != 0 and confirm_since >= 0:\n            if now - confirm_since >= p[6] and now - last_exit_time >= p[11]:'
    new = '''        rebound_ready = p[15] <= 0.0
        if side == 0 and p[15] > 0.0:
            mid = (bid[i] + ask[i]) * 0.5
            if arm_side != 0 and (not known or slow * arm_side < 0.0 or now - arm_since >= p[17]):
                arm_side = 0
            if arm_side == 0 and entry_direction != 0 and confirm_since >= 0.0 and now - confirm_since >= p[6]:
                arm_side = entry_direction
                arm_best = mid
                arm_extreme = mid
                arm_phase = 0
                arm_since = now
            elif arm_side != 0:
                if arm_phase == 0:
                    if arm_side * (mid - arm_best) > 0.0:
                        arm_best = mid
                    if arm_side * (arm_best - mid) >= p[15]:
                        arm_phase = 1
                        arm_extreme = mid
                else:
                    if arm_side * (mid - arm_extreme) < 0.0:
                        arm_extreme = mid
                    rebound_ready = arm_side == entry_direction and arm_side * (mid - arm_extreme) >= p[16]
        if side == 0 and entry_direction != 0 and confirm_since >= 0:
            if rebound_ready and now - confirm_since >= p[6] and now - last_exit_time >= p[11]:
                arm_side = 0'''
    assert old in source
    source = source.replace(old, new)
    (HERE / 'engine_round2.py').write_text(source, encoding='utf-8')


if __name__ == '__main__':
    main()
