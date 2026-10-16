"""43完結親の銘柄差を、出口十対照と入口六対照へ結果前に分ける。"""

QUANTITY={'TOPIX':5,'NK225':10}
CAP={'TOPIX':10,'NK225':20}
VALUE={'TOPIX':1000.,'NK225':10.}
FEE_RATIO={'TOPIX':(209,5),'NK225':(11,1)}
BUDGET={'TOPIX':5000.,'NK225':2000.}
TRIAL_ID='104_E01同入口の出口尺度十対照と票強度及び価格応答六対照'
BASELINE_ID='E01_ANCHOR_W60_CONFIRM_D0_P1_L2_A1'
BASE_ENTRY='CONFIRM25'


def configs() -> list[dict]:
    """
    機能: 原因に対応する十六対照を、同一商品共通係数のまま列挙する。
    引数: なし。
    返り値: list[dict] は正式結果前条件。旧基準は十六新条件へ含めない。
    """
    rules=[
        ('A01',BASE_ENTRY,'fixed',dict(target_basis='ATR',target_multiple=.125), '公開ATRの八分の一で純利確'),
        ('A02',BASE_ENTRY,'fixed',dict(target_basis='ATR',target_multiple=.25), '公開ATRの四分の一で純利確'),
        ('A03',BASE_ENTRY,'fixed',dict(target_basis='ATR',target_multiple=.5), '公開ATRの二分の一で純利確'),
        ('A04',BASE_ENTRY,'fixed',dict(target_basis='TICK_NET'), '観測ラージ一呼値の粗利益から往復料を引く'),
        ('A05',BASE_ENTRY,'fixed',dict(target_basis='P1',hard_basis='ATR_COST',hard_multiple=.25), '旧比例利確とATR四分の一及び公開費用の停止線'),
        ('A06',BASE_ENTRY,'fixed',dict(target_basis='P1',hard_basis='ATR_COST',hard_multiple=.5), '旧比例利確とATR二分の一及び公開費用の停止線'),
        ('A07',BASE_ENTRY,'fixed',dict(target_basis='ATR',target_multiple=.25,hard_basis='ATR_COST',hard_multiple=.5), 'ATR四分の一利確と費用込みATR二分の一停止'),
        ('A08',BASE_ENTRY,'protect',dict(arm_basis='ATR',arm_multiple=.125,draw_multiple=.25), '八分の一ATRで保全開始し四分の一ATRの戻しを許容'),
        ('A09',BASE_ENTRY,'protect',dict(arm_basis='ATR',arm_multiple=.25,draw_multiple=.5), '四分の一ATRで保全開始し二分の一ATRの戻しを許容'),
        ('A10',BASE_ENTRY,'protect',dict(arm_basis='P1',draw_multiple=.25), '旧比例利幅で保全開始し四分の一ATRの戻しを許容'),
        ('B01','CONFIRM50','fixed',dict(target_basis='P1'), '方向票釣合い半分以上と旧比例利確'),
        ('B02','CONFIRM50','fixed',dict(target_basis='ATR',target_multiple=.25), '方向票釣合い半分以上と四分の一ATR利確'),
        ('B03','CONFIRM75','fixed',dict(target_basis='P1'), '方向票釣合い四分の三以上と旧比例利確'),
        ('B04','CONFIRM75','fixed',dict(target_basis='ATR',target_multiple=.25), '方向票釣合い四分の三以上と四分の一ATR利確'),
        ('C01','SELF10','fixed',dict(target_basis='P1'), '旧方向票確認に自己両気配の十秒順行を加える'),
        ('C02','PEER10','fixed',dict(target_basis='P1'), '旧方向票確認に相手両気配の十秒順行を加える')]
    return [dict(id='E01_CROSS_'+code,entry_id=entry,exit_kind=kind,title=title,
        **dict(dict(hard_basis='BUDGET'),**rule),floor_yen=0.,quantity=QUANTITY,cap=CAP,
        window_seconds=60,execution='D0',offset_atr=0.,risk_atr_multiple=1.,
        quantity_selection_budget_yen=BUDGET,baseline_id=BASELINE_ID,
        anchor='最初の受理新規q・公開ATR・公開spreadから一回固定。未約定取消でも保持。')
        for code,entry,kind,rule,title in rules]


def entry_ids() -> tuple[str,...]:
    """
    機能: 出口差だけの共有GUと、新規全feed再生が必要な四入口を分ける。
    引数: なし。
    返り値: tuple[str,...] は五入口。CONFIRM25だけ旧GUを再利用する。
    """
    return ('CONFIRM25','CONFIRM50','CONFIRM75','SELF10','PEER10')
