"""初回幅余裕と旧線据置を独立有理数で事前反証する。"""

from fractions import Fraction
from pathlib import Path

import common
import math_oracle as oracle


def finite(value: object) -> object:
    """
    機能: 有理数を分子・分母・表示値に分け、有限JSONへ保存できる形にする。
    引数: value(object)は有理数、cohort、辞書又は通常値。
    返り値: object。表示floatを数理の期待値へ戻さない。
    """
    if isinstance(value,Fraction):
        return dict(分子=value.numerator,分母=value.denominator,表示値=float(value))
    if isinstance(value,oracle.Cohort):
        return dict(実fill順=value.ordinal,数量=value.quantity,価格=finite(value.price),新規料金=value.entry_fee)
    if isinstance(value,dict):
        return {str(key):finite(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):
        return [finite(item) for item in value]
    return value


def gate(bid: object, old: object, peak: object, multiple: object = 1,
         preserve: bool = True, protected: bool = False, active: bool = False,
         side: int = 1) -> dict:
    """
    機能: 同じ初回一枚と実料金から、買売反射した追加一枚の数学門番を作る。
    引数: bid/old/peak/multiple(object)、preserve/protected/active(bool)、side(int)は±1。
    返り値: dict。初回S=4、倍率1000、呼値0.5の独立想定値。実商品条件を変更しない。
    """
    first=oracle.cohort(0,1,4000,41.8)
    if side == -1:
        ask=8000-oracle.rational(bid)
        bid=ask-oracle.rational(.5)
        old,peak=8000-oracle.rational(old),8000-oracle.rational(peak)
    else:
        ask=oracle.rational(bid)+oracle.rational(.5)
    return oracle.projected_add([first],1,bid,ask,side,4082,old,4000-side*4,
        peak,4,16,active,protected,1,1000,41.8,.5,'initial_width',multiple,preserve)


def main() -> None:
    """
    機能: 二軸の正負・等号・反射・悪い次fillを純数学で確認し有限監査計画を保存する。
    引数: なし。根本体や正式損益を呼ばない。
    返り値: None。合格証は期待値準備の範囲のみとし、旧固定を二重全ハッシュしない。
    """
    catalog=common.module('102独立数学条件',common.BASE/'catalog.py')
    configs=catalog.catalog()
    assert len(configs) == 20 and catalog.PRIMARY == 'B1_T0_Q1_X1'
    quantities=[]
    for config in configs:
        for symbol in common.SYMBOLS:
            initial=oracle.quantity_for(config,symbol)
            maximum=8 if symbol == 'TOPIX' else 16
            assert initial <= maximum
            if config['id'].startswith('B'):
                assert initial == 1 and config['trend_initial_quantity'] == 1
                assert config['trend_growth_cushion_initial_multiple'] in (.5,1.,2.)
            quantities.append(dict(条件=config['id'],商品=symbol,絶対初回=initial,実最大=maximum))
    # ----------------------------------------
    # 正利益だけでは予算又は起動済み費用床を保証しないことを別に反証する。
    cases=[]
    for side in (1,-1):
        fail=gate(4021,4005,4021,preserve=True,side=side)
        free=gate(4021,4005,4021,preserve=False,side=side)
        assert fail['net'] > 0 and fail['cushion_allowed'] and not fail['budget_at_old_allowed']
        assert not fail['stop_preserved'] and not fail['allowed'] and free['allowed']
        cases.append(dict(確認='現在利益は正でも旧線予算超過',方向=side,据置=fail,線更新可=free))
        fee=gate(4010,4005.5,4021.5,protected=True,active=True,side=side)
        assert fee['net'] > 0 and fee['budget_at_old_allowed'] and not fee['stop_preserved']
        assert fee['cushion_allowed'] and not fee['allowed']
        cases.append(dict(確認='予算合格でも起動済み費用床が寄る',方向=side,判定=fee))
        passed=gate(4031,4015,4031,preserve=True,side=side)
        assert passed['allowed'] and passed['stop_preserved'] and passed['budget_at_old_allowed']
        cases.append(dict(確認='通常追尾後の線を保ったまま追加可能',方向=side,判定=passed))
        protected=gate(4036,4020,4036,preserve=True,protected=True,active=True,side=side)
        assert protected['allowed'] and protected['active'] and protected['stop_preserved']
        cases.append(dict(確認='X3費用床を含む据置合格',方向=side,判定=protected))
        first=oracle.cohort(0,1,4000,41.8)
        addition=oracle.cohort(1,1,4050,41.8)
        price,old,peak=4015,4015,4031
        if side == -1:
            addition=oracle.cohort(1,1,8000-addition.price,41.8)
            price,old,peak=8000-price,8000-old,8000-peak
        actual=oracle.integrated_line([first,addition],side,4082,old,4000-side*4,peak,16,False,1000,41.8,.5)
        assert side*(actual['line']-oracle.rational(old)) > 0
        assert oracle.liquidation([first,addition],price,side,1000,41.8)['net'] < -4082
        cases.append(dict(確認='判断時据置合格でも悪い次実fillで線が寄る',方向=side,
            判断=passed,実fill後線=actual,巻戻し又は未来取消=False))
    boundaries=[]
    for multiple in (Fraction(1,2),Fraction(1),Fraction(2)):
        for delta in (Fraction(-1,1000000),Fraction(),Fraction(1,1000000)):
            quote=Fraction(4008)+4*multiple+delta
            for side in (1,-1):
                result=gate(quote,4008,4024,multiple,preserve=True,side=side)
                assert result['required_cushion'] == 4*multiple
                assert result['clearance'] == 4*multiple+delta
                assert result['cushion_allowed'] == (delta >= 0)
                assert result['allowed'] == (delta >= 0)
                boundaries.append(dict(B=multiple,差=delta,方向=side,判定=result))
    # ----------------------------------------
    # Sの最低2呼値では新0.5Sが旧1呼値と厳密に同じ。数学nullを公差で救済しない。
    nulls=[]
    for side in (1,-1):
        first=[oracle.cohort(0,1,4000,41.8)]
        bid,ask,old,peak=4002,4002.5,4001,4004
        if side == -1:
            bid,ask,old,peak=8000-ask,8000-bid,8000-old,8000-peak
        risk=oracle.fixed_risk(first[0],1,1000,41.8)
        before=oracle.projected_add(first,1,bid,ask,side,risk,old,4000-side,peak,1,4,False,False,1,1000,41.8,.5)
        after=oracle.projected_add(first,1,bid,ask,side,risk,old,4000-side,peak,1,4,False,False,1,1000,41.8,.5,'initial_width',.5,False)
        assert before == after
        nulls.append(dict(方向=side,旧呼値数=1,新S倍数=.5,完全同値=True))
    paths=[common.BASE/'catalog.py',common.BASE/'結果前の設計草案.json',
        common.BASE/'結果前の数理明確化.json',Path(__file__),common.HERE/'math_oracle.py',common.HERE/'common.py',
        common.ROOT/'work/wave_v101/事前固定.json',common.BASE/'正式新損益前の主変更理由.json',
        common.BASE/'初版catalog.py',common.BASE/'初版結果前の設計案.json']
    final=common.BASE/'結果前の設計案.json'
    if final.exists():
        paths.append(final)
    plan=dict(状態='本体完成前の独立期待値準備',所有='work/wave_v102/auditのみ',条件数=20,
        事前主=catalog.PRIMARY,全31既知=True,未見場数=0,
        必須=[
            '独立Fractionの初回幅余裕、通常追尾後旧線での予算、全統合線の厳密等号',
            '全20人工×両商品×買売、実追加到達と悪fill後の非巻戻しを分離',
            '旧8対照×31×2=496口座、旧70と旧全台帳及び共有prepare完全null',
            '実代表prefixと自己相手LP/BBO未來源及び同clock後続不変',
            '通常監査CLI人工40口座・全320商品期間・根保存再読込',
            '許可後全1240口座・320商品期間・全原板会計と意味別代表再生'],
        scope='旧70は保存全列、11保有数理は独立、別19門番は独立期待値へ接続する。補助flagsを真として正答生成しない。',
        正式新損益=0,API取得=0,実注文=0,SHA256=common.fingerprints(paths))
    common.save(common.HERE/'plan.json',plan)
    proof=dict(合格=True,範囲='純数理のみ、本体再生なし',絶対数量ケース=40,数量=quantities,
        買売反射の意味反例=finite(cases),厳密等号両側=finite(boundaries),最低幅null=nulls,
        新正式損益=0,API取得=0,実注文=0,SHA256=common.fingerprints(paths+[common.HERE/'plan.json']))
    destination=common.HERE/'初回幅余裕と統合停止線据置の独立純数理.json'
    common.save(destination,proof)
    print('純数理合格: 40数量/10意味反例/18等号両側/2数学null。本体実行0。',flush=True)


if __name__ == '__main__':
    main()
