"""初回一呼値の値幅から往復料を引いた固定日次純目標を、二入口へ適用する。"""

import daily


TRIAL_ID='106_E01取引更新二入口の一呼値料金差引目標6対照'
QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}


def goals() -> dict:
    """
    機能: 呼値・初回枚数・倍率・注文別料金だけから、場全体の純目標定数を決める。
    引数: なし。特定場の極値や最終収支は参照しない。
    返り値: dict[str,float]はTOPIX2082円/NK225780円。各親一呼値利確とは同義でない。
    """
    values={s:daily.TICK[s]*QUANTITY[s]*daily.VALUE[s]-2*daily.fee(QUANTITY[s],s) for s in QUANTITY}
    assert values=={'TOPIX':2082.,'NK225':780.}
    return values


def configs() -> list[dict]:
    """
    機能: 元W60CONFIRM/VETO成行GUを固定した日次純目標と損失4/8/16の六政策を返す。
    引数: なし。
    返り値: list[dict]は結果前六設定。過去勝敗による目標変更や場停止後の再参加はしない。
    """
    return [dict(id=f'E01_NETTICK_W60_{mode}_D0_L{loss}',mode=mode,window_seconds=60,execution='D0',
        goal_yen=goals(),loss_ticks=loss,quantity=QUANTITY,cap=CAP,
        GU_id=f'E01_TRADE_W60_{mode}_D0_GU',
        baseline_ids={'P1L8':f'E01_TRADE_W60_{mode}_D0_P1L8','P1L4':f'E01_BUDGET_W60_{mode}_D0_P1_L4'})
        for mode in ('CONFIRM','VETO') for loss in (4,8,16)]


def apply(base: dict, quotes: dict, config: dict) -> dict:
    """
    機能: 固定円目標を初回呼値比へ変換し、旧exact日次firsthit/次気配UID別清算を使う。
    引数: base/quotes/config(dict)はGU実注文由来会計・当時気配・六設定。
    返り値: dictは純目標の新実口座。過去親損失や部分返済料が必要順行量を変える。
    """
    symbol=base['key'][1];unit=daily.TICK[symbol]*QUANTITY[symbol]*daily.VALUE[symbol]
    assert config['goal_yen']==goals() and config['loss_ticks'] in (4,8,16)
    goal=config['goal_yen'][symbol];ticks=goal/unit;assert ticks*unit==goal
    result=daily.apply_policy(base,quotes,dict(profit_ticks=ticks,loss_ticks=config['loss_ticks']))
    result['fixed_policy']=dict(goal_yen=goal,profit_ticks_equivalent=ticks,loss_ticks=config['loss_ticks'],
        goal_definition='初回一呼値値幅から初回往復料金を差し引いた固定額を、場全体の清算収支へ適用する。')
    return result
