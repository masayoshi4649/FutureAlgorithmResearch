"""過去往復と現在の短い進行を区別する18条件を結果前に固定する。"""


TRIAL_ID='106_直近位相によるR入口と方向別待機取消18対照'


def catalog() -> list[dict]:
    """
    機能: 3方向審査×3停止余裕×2新規方法を、保存AUTO6対照に対応させる。
    引数: なし。
    返り値: list[dict]は18条件。C進行・旧費用・出口・数量は変えない。
    """
    result=[]
    for policy in ('OWN_VETO','BOTH_VETO','ALIGNED'):
        for margin in (1,2,4):
            for entry in ('MARKET','LIMIT'):
                base=f'AUTO_ER40_M{margin}_{entry}'
                result.append(dict(id=f'{base}_{policy}',base_id=base,local_policy=policy,
                    mode='AUTO',range_er=.4,margin_ticks=margin,range_entry=entry,trend_bp=2.,
                    boundary_fraction=.25,minimum_span_ticks=4.,minimum_stop_ticks=2.,minimum_payoff=1.25,
                    quantity={'TOPIX':5,'NK225':10},caps={'TOPIX':10,'NK225':20},
                    cooldown_seconds=30.,start_offset=300.,cut_offset=300.,force_offset=60.,quiet_mode='J',
                    support_ticks=4,initial_stop_fraction=.001,trend_width_fraction=.004,
                    profit_trail=False,r_profit=False,reentry_band=False,session_brake=False,
                    local_er_minimum=.6,local_net_minimum_ticks=2.))
    assert len(result)==18 and len({x['id'] for x in result})==18
    return result
