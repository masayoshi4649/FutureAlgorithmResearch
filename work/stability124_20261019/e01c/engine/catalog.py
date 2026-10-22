"""公開票の強さで不利許容0/1観測呼値を一回固定する八対照。"""

QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
BUDGET={'TOPIX':5000.,'NK225':2000.}
TRIAL_ID='106_E01公開支持強度による一回FAK許容切替八対照'
GATES={'G25':(.25,2),'G50':(.5,2)}
STRONG={'ADAPT75':.75,'ADAPT100':1.}


def entry_ids() -> tuple[str,...]:
    """
    機能: 当時の既知二票以上を要求する二つの入口を返す。
    引数: なし。
    返り値: tuple[str,...] は元と同じ釣合い.25/.5の入口名。
    """
    return tuple(GATES)


def reference_id(gate: str, execution: str, target: str) -> str:
    """
    機能: 比較元00105の固定許容条件IDをそのまま参照する。
    引数: gate/execution/target(str) は二入口・固定0/1・二利益線。
    返り値: str は旧保存ID。保存経済を新しい有効性の標本へ数えない。
    """
    assert gate in GATES and execution in ('FAK0','FAK1') and target in ('P1','ATR25')
    return 'E01_FAK_'+gate+'_'+execution+'_'+target


def case_id(gate: str, execution: str, target: str) -> str:
    """
    機能: 新適応許容と利益線を条件名へ結ぶ。
    引数: gate/execution/target(str) は入口・強支持閾値・固定利益線。
    返り値: str は八新条件の機械ID。
    """
    assert gate in GATES and execution in STRONG and target in ('P1','ATR25')
    return 'E01_ADAPT_'+gate+'_'+execution+'_'+target


def configs() -> list[dict]:
    """
    機能: 公開時の強支持だけ許容1、それ以外0の八条件を結果前に列挙する。
    引数: なし。
    返り値: list[dict] は二入口×二強支持閾値×二純利益線。
    """
    result=[]
    for gate,(balance,votes) in GATES.items():
        for execution,strong in STRONG.items():
            for target in ('P1','ATR25'):
                result.append(dict(id=case_id(gate,execution,target),entry_id=gate,execution_id=execution,target_id=target,
                    min_votes=votes,balance_threshold=balance,strong_balance_threshold=strong,
                    weak_adverse_ticks=0,strong_adverse_ticks=1,allowance_selection='新規公開当行のみ。実試行行で再選択しない。',
                    exit_kind='fixed',target_basis='P1' if target=='P1' else 'ATR',target_multiple=.25,
                    hard_basis='BUDGET',floor_yen=0.,quantity=QUANTITY,cap=CAP,window_seconds=60,
                    risk_atr_multiple=1.,offset_atr=0.,quantity_selection_budget_yen=BUDGET,
                    baseline_id=reference_id(gate,'FAK0',target),comparison_ids=[reference_id(gate,e,target) for e in ('FAK0','FAK1')],
                    anchor='最初受理q/ATR/spreadで場線を一回固定。FAK未約定取消でも保持。',
                    title=gate+' 強支持'+str(strong)+' '+target))
    assert len(result)==8 and len({c['id'] for c in result})==8
    return result


def new_gu_routes() -> tuple[tuple[str,str],...]:
    """
    機能: 新GU四routeを出口別八会計から分ける。
    引数: なし。
    返り値: tuple[tuple[str,str],...] は二入口と二公開閾値。
    """
    return tuple((gate,execution) for gate in GATES for execution in STRONG)
