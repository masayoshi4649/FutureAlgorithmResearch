"""異なる入口の固定配分と、小利益で場を終える39対照。"""

from copy import deepcopy

BASES = ('P_OWN_B4','P_N30_B4','R_OWN_B4')


def catalog() -> list[dict]:
    """
    機能: 3無目標基準と36目標政策を事前固定する。
    引数: なし。
    返り値: list[dict]は39条件。実損益を見て配分・閾値を選び直さない。
    """
    answer=[]
    for base in BASES:
        entry=base[:-3]
        components=['R_OWN'] if entry=='R_OWN' else ['C_OWN' if entry=='P_OWN' else 'C_N30','R_OWN']
        alloc={'TOPIX':[10],'NK225':[20]} if entry=='R_OWN' else (
            {'TOPIX':[5,5],'NK225':[10,10]} if entry=='P_OWN' else {'TOPIX':[8,2],'NK225':[16,4]})
        setting=dict(id=base,base_id=base,entry_id=entry,components=components,allocations=alloc,
            quantity={'TOPIX':10,'NK225':20},support_ticks=4,profit_trail=False,r_profit=False,
            alpha=2.,beta=1.,reentry_band=False,session_brake=False,session_budget_multiple=1.,
            filter_mode='NONE',window=30,own_path='NORMAL',initial_stop_fraction=.001,
            cooldown_seconds=30.,start_offset=300.,cut_offset=300.,force_offset=60.,
            goal_ticks=None,loss_ticks=None,name='固定配分の無目標基準',
            explanation='Cの進行入口とRの進行失敗入口を固定配分し、それぞれ元B4で返済する。単独Rも対照にする。')
        answer.append(setting)
        for goal in (1,2,4):
            for loss in (4,8,16,None):
                answer.append(dict(deepcopy(setting),id=base+'_DAY_P'+str(goal)+'_L'+('FREE' if loss is None else str(loss)),
                    goal_ticks=goal,loss_ticks=loss,name='小利益又は損失枠で場内終了',
                    explanation='全腿の手数料後清算時価が場目標か損失枠へ最初に達したら、次正常気配で全親を返済してその場を終了する。'))
    assert len(answer)==39 and len({v['id'] for v in answer})==39
    return answer
