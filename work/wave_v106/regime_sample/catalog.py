"""共通レジーム分類の単独と自動選択を26実条件に固定する。"""


def setting(mode: str, bp: int, er: float, exit_id: str) -> dict:
    """
    機能: 同時配分せず、一口座の新規選択条件を作る。
    引数: mode/exit_id(str)、bp(int)、er(float)は使用源と固定水準。
    返り値: dictは標準TOP10/NK20のB4又はCだけR21条件。
    """
    ident=mode+'_B'+str(bp)+'_ER'+str(int(er*100)).zfill(2)+'_'+exit_id
    return dict(id=ident,entry_id='REGIME_'+mode,mode=mode,trend_bp=bp,range_er=er,C_exit=exit_id,
        quantity={'TOPIX':10,'NK225':20},support_ticks=4,profit_trail=False,r_profit=exit_id=='R21',
        alpha=2.,beta=1.,reentry_band=False,session_brake=False,session_budget_multiple=1.,
        filter_mode='NONE',window=300,own_path='SIX_PUBLIC',initial_stop_fraction=.001,
        cooldown_seconds=30.,start_offset=300.,cut_offset=300.,force_offset=60.,quiet_mode='J',
        name='両市場の進行と往復でC/Rを選択',
        explanation='双方往復なら余地のあるR、そうでなければ双方同方向進行と一致するCを選ぶ。保有中の出口は新規時に固定する。')


def catalog() -> list[dict]:
    """
    機能: 36表示組合せのうち、R_ONLYの同一経済10条件を除く。
    引数: なし。
    返り値: list[dict]は実26条件。同じR_ONLYの損益を再生成しない。
    """
    result=[setting(mode,bp,er,exit_id) for mode in ('C_ONLY','AUTO')
        for bp in (2,3,5) for er in (.2,.4) for exit_id in ('B4','R21')]
    result += [setting('R_ONLY',2,er,'B4') for er in (.2,.4)]
    assert len(result)==26 and len({c['id'] for c in result})==26
    return result


def aliases() -> list[dict]:
    """
    機能: R_ONLYで未使用のC閾値とC出口の表示条件を、既実条件へ対応する。
    引数: なし。
    返り値: list[dict]は10alias。経済コピーは新検証と数えない。
    """
    result=[]
    for bp in (2,3,5):
        for er in (.2,.4):
            for ex in ('B4','R21'):
                item=setting('R_ONLY',bp,er,ex);source=setting('R_ONLY',2,er,'B4')['id']
                if item['id']!=source:result.append(dict(id=item['id'],reuse_id=source,新金融再生=0,
                    reason='R_ONLYはRANGEとR余地だけを使用し、Cのbp/出口は経済条件に使用しない'))
    assert len(result)==10
    return result
