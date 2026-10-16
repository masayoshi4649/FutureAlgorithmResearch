"""公開価格FAKと二票/四票を、同一利益線の対照で分ける十八条件。"""

QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
BUDGET={'TOPIX':5000.,'NK225':2000.}
TRIAL_ID='104_E01公開気配FAK二許容と票強度四条件の十八対照'
GATES={'G25':(.25,2),'G50':(.5,2),'G75':(.75,2),'G50N4':(.5,4)}
OLD_IDS={('G25','P1'):'E01_ANCHOR_W60_CONFIRM_D0_P1_L2_A1',('G25','ATR25'):'E01_CROSS_A02',
    ('G50','P1'):'E01_CROSS_B01',('G50','ATR25'):'E01_CROSS_B02',
    ('G75','P1'):'E01_CROSS_B03',('G75','ATR25'):'E01_CROSS_B04'}


def entry_ids() -> tuple[str,...]:
    """
    機能: 公開時に計算する四方向票gateを列挙する。
    引数: なし。
    返り値: tuple[str,...] は同代理の釣合い閾値と最少票数の四route。
    """
    return tuple(GATES)


def case_id(gate: str, execution: str, target: str) -> str:
    """
    機能: 四gate・三執行・二利益線の条件を機械的IDへ結ぶ。
    引数: gate/execution/target(str) は結果前の部品名。
    返り値: str は新条件ID。旧保存対照のIDを新試行へ改名しない。
    """
    assert gate in GATES and execution in ('FAK0','FAK1','MARKET') and target in ('P1','ATR25')
    return 'E01_FAK_'+gate+'_'+execution+'_'+target


def configs() -> list[dict]:
    """
    機能: 十六FAKと四票市場二対照を固定し、旧市場六対照を新条件数から除く。
    引数: なし。
    返り値: list[dict] は十八新条件。利益線と固定hardBは受理qから決める。
    """
    result=[]
    for gate,(balance,min_votes) in GATES.items():
        executions=('FAK0','FAK1','MARKET') if gate=='G50N4' else ('FAK0','FAK1')
        for execution in executions:
            for target in ('P1','ATR25'):
                baseline=OLD_IDS['G50',target] if execution=='MARKET' else (case_id(gate,'MARKET',target) if gate=='G50N4' else OLD_IDS[gate,target])
                result.append(dict(id=case_id(gate,execution,target),entry_id=gate,execution_id=execution,target_id=target,
                    min_votes=min_votes,balance_threshold=balance,adverse_ticks=1 if execution=='FAK1' else 0,
                    exit_kind='fixed',target_basis='P1' if target=='P1' else 'ATR',target_multiple=.25,
                    hard_basis='BUDGET',floor_yen=0.,quantity=QUANTITY,cap=CAP,window_seconds=60,
                    risk_atr_multiple=1.,offset_atr=0.,quantity_selection_budget_yen=BUDGET,baseline_id=baseline,
                    anchor='最初受理q/ATR/spreadで場線を一回固定。FAK未約定取消でも保持。',
                    title=gate+' '+execution+' '+target))
    assert len(result)==18 and len({c['id'] for c in result})==18
    return result


def new_gu_routes() -> tuple[tuple[str,str],...]:
    """
    機能: 共有新GU九routeを、出口別会計十八から分ける。
    引数: なし。
    返り値: tuple[tuple[str,str],...] は八FAKと四票市場一route。
    """
    return tuple((g,e) for g in GATES for e in ('FAK0','FAK1'))+(('G50N4','MARKET'),)
