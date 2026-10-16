"""価格境界反発単独と機械AUTO選択を、結果前の24条件へ固定する。"""


TRIAL_ID='106_純価格レンジ境界反発と二市場AUTO24対照'


def catalog() -> list[dict]:
    """
    機能: 2選択×2ER×3固定停止margin×2新規執行を事前固定する。
    引数: なし。
    返り値: list[dict]は24条件。最大損益を見て変数を選ばない。
    """
    result=[dict(id=f'{mode}_ER{int(er*100)}_M{margin}_{entry}',mode=mode,range_er=er,
        margin_ticks=margin,range_entry=entry,trend_bp=2.,boundary_fraction=.25,
        minimum_span_ticks=4.,minimum_stop_ticks=2.,minimum_payoff=1.25,
        quantity={'TOPIX':5,'NK225':10},caps={'TOPIX':10,'NK225':20},
        cooldown_seconds=30.,start_offset=300.,cut_offset=300.,force_offset=60.,quiet_mode='J',
        support_ticks=4,initial_stop_fraction=.001,trend_width_fraction=.004,
        profit_trail=False,r_profit=False,reentry_band=False,session_brake=False)
        for mode in ('R_ONLY','AUTO') for er in (.2,.4) for margin in (1,2,4) for entry in ('MARKET','LIMIT')]
    assert len(result)==24 and len({c['id'] for c in result})==24
    return result

