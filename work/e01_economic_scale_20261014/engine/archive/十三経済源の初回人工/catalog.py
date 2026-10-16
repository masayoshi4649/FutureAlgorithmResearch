"""保有容量と一取引利益の経済規模を、結果前の十四条件へ分ける。"""

CAP={'TOPIX':10,'NK225':20}
HALF={'TOPIX':5,'NK225':10}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
GATES={'G25':(.25,2),'G50':(.5,2)}
SELECTED={'TOPIX':['G50',.75],'NK225':['G25',1.]}
TRIAL_ID='107_E01保有容量三種類と実親出口四種類及び追加機会十四対照'


def configs() -> list[dict]:
    """
    機能: 三数量×四出口と共通入口の全量二出口を固定する。
    引数: なし。
    返り値: list[dict] は十四経済条件。値幅目標を平均全親利益の実績へ代用しない。
    """
    result=[]
    for route,quantities,exits in (('SELECTED',('HALF','FULL','RISK'),('GU','TARGET','TRAIL','PARTIAL')),
                                   ('COMMON25',('FULL',),('TARGET','TRAIL'))):
        for quantity in quantities:
            for exit_id in exits:
                result.append(dict(id='E01_SCALE_'+route+'_'+quantity+'_'+exit_id,entry_route=route,quantity_mode=quantity,
                    exit_id=exit_id,quantity=HALF if quantity=='HALF' else CAP,cap=CAP,window_seconds=60,
                    entry_parameters=SELECTED if route=='SELECTED' else {s:['G25',.75] for s in CAP},
                    quantity_budget_fraction=.00125,parent_stop_fraction=.00125,parent_target_fraction=.005,
                    arm_fraction=.00375,draw_fraction=.00125,floor_fraction=.0025,partial_fraction=.25,
                    partial_arm_fraction=.0025,session_stop_fraction=.0025,risk_atr_multiple=1.,
                    target_parent_mean_net_yen={'TOPIX':100000,'NK225':None},session_profit_stop_yen=None,
                    title=route+' '+quantity+' '+exit_id))
    assert len(result)==14 and len({c['id'] for c in result})==14
    return result
