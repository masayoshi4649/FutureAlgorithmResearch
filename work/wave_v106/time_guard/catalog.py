"""四つの不変B4入口へ開場静観3政策を適用する。"""

ENTRIES=('C_OWN','C_N30','U_P10','R_OWN')


def catalog() -> list[dict]:
    """
    機能: 日中/NYSE/両方の静観だけを変える12条件を固定する。
    引数: なし。
    返り値: list[dict]はTOP10/NK20実量の12条件。基準結果を再金融しない。
    """
    result=[]
    for entry in ENTRIES:
        for mode in ('J','U','JU'):
            result.append(dict(id=entry+'_B4_TIME_'+mode,entry_id=entry,base_id=entry+'_B4',
                quantity={'TOPIX':10,'NK225':20},quiet_mode=mode,support_ticks=4,profit_trail=False,
                r_profit=False,alpha=2.,beta=1.,reentry_band=False,session_brake=False,session_budget_multiple=1.,
                filter_mode='NONE',window=30,own_path='NORMAL',initial_stop_fraction=.001,
                cooldown_seconds=30.,start_offset=300.,cut_offset=300.,force_offset=60.,
                name='既知開場時刻の静観',explanation='日中08:45～09:15、NYSE開場前後15分、又は両方を静観する。保有は開始予定で返済し、未約定新規は取り消す。'))
    assert len(result)==12 and len({c['id'] for c in result})==12
    return result
