"""101の数量・予算線・費用床・親相殺を純数理だけで反証する。売買再生を呼ばない。"""

from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.dont_write_bytecode = True


def number(value: object) -> Fraction:
    """
    機能: 人工価格・費用を十進表記から厳密な有理数にする。
    引数: value(object)は数値又はFraction。
    返り値: Fraction。浮動丸めで上限を救済しない。
    """
    return value if isinstance(value, Fraction) else Fraction(str(value))


def fee(quantity: int, unit: object) -> int:
    """
    機能: 注文ごとの片道手数料を1円未満切捨てで計算する。
    引数: quantity(int)、unit(object)は1枚片道単価。
    返り値: int。cohortをまとめて新規料金を捏造しない。
    """
    assert isinstance(quantity, int) and quantity > 0
    value = quantity * number(unit)
    return value.numerator // value.denominator


def rounded(value: Fraction, tick: object, side: int) -> Fraction:
    """
    機能: 停止価格を損失予算を広げない方向へ呼値丸めする。
    引数: value(Fraction)、tick(object)、side(int)は買い+1/売り−1。
    返り値: Fraction。買いはceil、売りはfloor。
    """
    units = value / number(tick)
    count = -((-units.numerator) // units.denominator) if side == 1 else units.numerator // units.denominator
    return count * number(tick)


def accounting(cohorts: list[tuple[int, object]], unit: object, multiplier: object) -> tuple:
    """
    機能: 実fill済みcohortから枚数・価格金額・累計新規料金・全量返済料金を得る。
    引数: cohorts(list[tuple[int,object]])、unit/multiplier(object)。
    返り値: tuple[int,Fraction,int]。Q,E,F。未保有玉と予約価格は入力に混ぜない。
    """
    quantity = sum(q for q, _ in cohorts)
    exposure = sum((q * number(price) * number(multiplier) for q, price in cohorts), Fraction())
    costs = sum(fee(q, unit) for q, _ in cohorts) + fee(quantity, unit)
    return quantity, exposure, costs


def net(cohorts: list[tuple[int, object]], liquidation: object, side: int,
        unit: object, multiplier: object) -> Fraction:
    """
    機能: 現在の清算quoteで全実保有玉を返す損益を注文別料金込みで計算する。
    引数: cohorts(list)、liquidation/unit/multiplier(object)、side(int)。
    返り値: Fraction。買いは売bid、売りは買askを与えること。
    """
    quantity, exposure, costs = accounting(cohorts, unit, multiplier)
    return side * (quantity * number(liquidation) * number(multiplier) - exposure) - costs


def budget_line(cohorts: list[tuple[int, object]], risk: object, side: int,
                unit: object, multiplier: object, tick: object) -> tuple[Fraction, Fraction]:
    """
    機能: 固定R0で全玉netが−R0以上となる理論停止価格を求める。
    引数: cohorts(list)、risk/unit/multiplier/tick(object)、side(int)。
    返り値: tuple[Fraction,Fraction]。未丸め価格と有利方向丸め価格。
    """
    quantity, exposure, costs = accounting(cohorts, unit, multiplier)
    raw = (exposure + side * (costs - number(risk))) / (quantity * number(multiplier))
    return raw, rounded(raw, tick, side)


def protection_line(cohorts: list[tuple[int, object]], side: int,
                    unit: object, multiplier: object, tick: object) -> Fraction:
    """
    機能: weighted entryと実累計費用から価格全体を丸め、旧1呼値bufferを足す。
    引数: cohorts(list)、unit/multiplier/tick(object)、side(int)。
    返り値: Fraction。非呼値weighted entryへ丸め済み幅だけを加えない。
    """
    quantity, exposure, costs = accounting(cohorts, unit, multiplier)
    breakeven = (exposure + side * costs) / (quantity * number(multiplier))
    return rounded(breakeven, tick, side) + side * number(tick)


def allocate(total: int, quantities: list[int]) -> list[int]:
    """
    機能: 全量返済一注文の実料金を最大剰余法・古いcohort優先で配分する。
    引数: total(int)、quantities(list[int])は実保有数量。
    返り値: list[int]。合計はtotal。PnLを見て剰余の割当を選ばない。
    """
    quantity = sum(quantities)
    shares = [total * q // quantity for q in quantities]
    ranking = sorted(range(len(quantities)), key=lambda i: (-(total * quantities[i] % quantity), i))
    for index in ranking[:total - sum(shares)]:
        shares[index] += 1
    assert sum(shares) == total
    return shares


def digest(path: Path) -> str:
    """
    機能: 参照仕様と旧固定資料の現在指紋を読む。
    引数: path(Path)。
    返り値: str。既存資料を変更しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 20条件と少数の純数理反例を確認し、解消済み仕様と実装未検証を分けて保存する。
    引数: なし。
    返り値: None。実原板・正式損益・シミュレータ・APIを読取実行しない。
    """
    spec = importlib.util.spec_from_file_location('101の数量宣言だけ読取', WORK / 'catalog.py')
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    conditions = catalog.catalog()
    assert len(conditions) == 20 and catalog.PRIMARY == 'G1_Q1_X1'
    assert sum(c['trend_initial_quantity'] is None for c in conditions) == 2
    assert all(c['trend_initial_quantity'] in (1, 2, 4, None) for c in conditions)
    counts = {(q, g, x) for q in (1, 2, 4) for g in (0, 1, 2) for x in (1, 3)}
    assert {(c['trend_initial_quantity'], c['trend_growth_mode'], int(c['id'][-1]))
            for c in conditions if c['trend_initial_quantity'] is not None} == counts
    changed = {'id', 'previous_price_cap_id', 'trend_initial_quantity',
               'trend_growth_mode', 'trend_growth_cushion_ticks', 'trend_growth_risk_budget'}
    for condition in conditions:
        previous = catalog.PREVIOUS[condition['previous_price_cap_id']]
        assert {key: value for key, value in condition.items() if key not in changed} == {
            key: value for key, value in previous.items() if key not in changed}
    design_path = WORK / '結果前の設計案.json'
    design = json.loads(design_path.read_text(encoding='utf-8'))
    assert design['予定条件数'] == 20 and design['理論主'] == catalog.PRIMARY
    assert all(design[key] == 0 for key in ('売買実装', '正式新条件売買実行', '現在API取得', '実注文'))
    requirements = {
        '統合有効線の余裕': ('費用と余裕の門番', ['非緩和旧有効線', '当該想定で起動するX3費用床', '1呼値', '2呼値']),
        '価格全体の保護方向丸め': ('X3の実利益保護', ['価格全体', 'ロングceil/ショートfloor', '1呼値buffer']),
        '初回期限と保護active維持': ('予約と返済の競合', ['初回実fill+1800', '追加で延長しない']),
        '実fill後の返済順': ('同行の初停止と追加', ['pending追加', '実fillを優先', '実追加を保存後に全玉停止']),
        '不明peerの基準専用復帰': ('追加基準の不明源', ['追加基準を無効', '基準だけを設定', 'その行の追加判断はしない', '実fill同行でも再追加判断をしない']),
        '費用超過時も予算式を保持': ('費用が初回予算を超す場合', ['負でも0へ置換せず', '同じ行で返済判断', '次normalquote']),
        '整数最大剰余の固定同率順': ('会計の不正を防ぐ', ['floor', '小数剰余の大きい順', '実fill作成順の早いcohort', '後の損益でtieを変更しない']),
    }
    design_checks = []
    for name, (key, phrases) in requirements.items():
        assert all(phrase in design[key] for phrase in phrases), (name, key)
        design_checks.append(dict(確認=name, 仕様欄=key, 文言一致=True))
    assert '一度activeなら' in design['X3の実利益保護'] and '解除しない' in design['X3の実利益保護']
    cases = []
    # ----------------------------------------
    # 注文料金と現在清算価格の門番は、単なる含み益や買ask評価と異なる。
    example = [(1, 4000), (1, 4001)]
    true = net(example, 4000.5, 1, 41.8, 1000)
    fake = net(example, 4001, 1, 41.8, 1000)
    assert true == -165 and fake == 835
    assert net([(q, 8000-number(p)) for q, p in example], 3999.5, -1, 41.8, 1000) == true
    cases.append(dict(反証='買askで全玉を評価すると誤追加', 真の売bid清算net=float(true), 偽の買ask評価net=float(fake)))
    current = [(1, 4000), (1, 4010.5)]
    risk = 4 * 1000 + 2 * fee(1, 41.8)
    raw, line = budget_line(current, risk, 1, 41.8, 1000, .5)
    wrong = rounded(raw, .5, -1)
    assert net(current, line, 1, 41.8, 1000) == -3665
    assert net(current, wrong, 1, 41.8, 1000) == -4665 < -risk
    reflected = [(q, 8000-number(p)) for q, p in current]
    raw_s, line_s = budget_line(reflected, risk, -1, 41.8, 1000, .5)
    assert line_s == 8000-line
    assert net(reflected, line_s, -1, 41.8, 1000) == net(current, line, 1, 41.8, 1000)
    cases.append(dict(反証='予算線の不利丸めでR0超過', R0=risk, 買い未丸め線=float(raw), 正しい線=float(line),
        正しい線net=-3665, 誤floor線=float(wrong), 誤線net=-4665, 超過=583, 売り反射線=float(line_s)))
    quantity, exposure, costs = accounting(current, 41.8, 1000)
    weighted = exposure/(quantity*1000)
    offset = rounded(Fraction(costs, quantity*1000), .5, 1)+number(.5)
    wrong_floor = weighted+offset
    right_floor = protection_line(current, 1, 41.8, 1000, .5)
    assert wrong_floor == number(4006.25) and wrong_floor/number(.5) != int(wrong_floor/number(.5))
    assert right_floor == 4006
    assert protection_line(reflected, -1, 41.8, 1000, .5) == 8000-right_floor
    cases.append(dict(反証='費用幅だけ丸めてweighted entryへ加えると非呼値', weighted_entry=float(weighted),
        非呼値床=float(wrong_floor), 価格全体丸めとbuffer=float(right_floor)))
    # ----------------------------------------
    # 予算線だけの余裕では、X3の有効費用床を踏む追加を阻止できない。
    grown = [(1, 4000), (1, 4010.5), (2, 4010.5), (4, 4010.5)]
    _, budget = budget_line(grown, risk, 1, 41.8, 1000, .5)
    floor = protection_line(grown, 1, 41.8, 1000, .5)
    assert net(grown, 4010, 1, 41.8, 1000) == 5834
    assert budget == 4009 and floor == 4010
    assert 4010-budget >= number(.5) and 4010-floor < number(.5)
    gross = sum(q*(number(4010)-number(p))*1000 for q,p in grown)
    assert gross == 6500 < 2*4*1000
    cases.append(dict(反証='R0線だけなら通るがX3統合線では追加不可', 追加後全玉net=5834,
        予算線=float(budget), X3床=float(floor), 清算quote=4010, G1必要余裕=.5,
        予算線余裕=1, 有効線余裕=0, 追加後gross=6500, 以前に成立した保護閾値=8000,
        必要='予算線だけを門番にしない。保護activeを増玉後grossで解除しない。'))
    actual_gross = sum(q*(number(4010)-number(p))*1000 for q,p in current)
    fake_gross = 2*(4010-4000)*1000
    assert actual_gross == 9500 and fake_gross == 20000
    cases.append(dict(反証='未保有の追加玉へ過去peakを掛けた偽利益', 実2cohort現在gross=9500,
        偽の2枚過去peak利益=20000, 偽増額=10500))
    # ----------------------------------------
    # 全量一注文の料金とcohortの利益損失は、親内相殺後の表示と一致しない。
    costs_close = fee(2, 41.8)
    split = allocate(costs_close, [1,1])
    assert costs_close == 83 and split == [42,41]
    cohort_nets = [1000-fee(1,41.8)-split[0], -500-fee(1,41.8)-split[1]]
    assert cohort_nets == [917,-582] and sum(cohort_nets) == 335
    cases.append(dict(反証='親黒字だけなら100%だがcohortでは約61%', cohort_net=cohort_nets,
        返済料金配分=split, 親net=335, 親利益割合=1., cohort利益割合=917/1499,
        各cohort別切捨の誤料金=82, 全量注文料金=83))
    order_costs = [fee(q,41.8) for q in (1,1,2,4)]
    assert order_costs == [41,41,83,167] and sum(order_costs) == 332 < fee(8,41.8)
    cases.append(dict(反証='累計新規費用を最終Qの一注文へ置換できない', 実注文別新規料金=order_costs,
        実累計=332, 誤った全8枚新規一注文料金=334, 差=2))
    # ----------------------------------------
    # 同じ追加判断から悪い次気配に全量約定しても、予約を未来から取り消せない。
    before = net([(1,4000),(1,4001.5)],4001,1,41.8,1000)
    after = net([(1,4000),(1,4011.5)],4001,1,41.8,1000)
    _, late_line = budget_line([(1,4000),(1,4011.5)],risk,1,41.8,1000,.5)
    assert before == 335 and after == -9665 and late_line == 4004
    cases.append(dict(反証='判断は合法でも次正常wide quote約定でR0超過', 判断ask=4001.5, 判断bid=4001,
        判断後全玉net=335, 次正常ask=4011.5, 次正常bid=4001, 実fill後net=-9665,
        R0=risk, 超過=5583, 実fill後予算線=4004,
        必要='悪い追加fillも記録。新線が現在bid以上なら追加fill同行で返済判断、実返済は次正常quote。'))
    low_price_growth = [(1,9900),(1,9940),(2,9960),(4,10000),(8,10030)]
    small_risk = 1*20*10 + 2*fee(1,11)
    q,e,f = accounting(low_price_growth,11,10)
    _, proper = budget_line(low_price_growth,small_risk,1,11,10,10)
    assert q == 16 and e/(q*10) == 10000 and f == 352 and small_risk == 222 and proper == 10010
    assert net(low_price_growth,10000,1,11,10) == -352 < -small_risk
    legal_numeric_gates = []
    for size, liquidation in ((2,9930), (3,9950), (4,9990), (5,10020)):
        prefix = low_price_growth[:size]
        _, prospective_line = budget_line(prefix, small_risk, 1, 11, 10, 10)
        prospective_net = net(prefix, liquidation, 1, 11, 10)
        assert prospective_net >= 0 and number(liquidation)-prospective_line >= 10
        legal_numeric_gates.append(dict(追加後数量=sum(q for q,_ in prefix),
            現在清算quote=liquidation, 想定全玉net=float(prospective_net),
            予算線=float(prospective_line), 数学余裕=float(number(liquidation)-prospective_line)))
    cases.append(dict(反証='R0−Fを0へclampすると費用だけで予算超過', 初回R0=222, 全玉F=352,
        weighted_entry=10000, 誤clamp線=10000, 誤線net=-352, 正しい線=10010,
        正しい線net=float(net(low_price_growth,10010,1,11,10)), 超過=130,
        数学門番=legal_numeric_gates,
        範囲='X1・初回1・G1の1→2→4→8→16。費用後net非負と予算線1tick余裕だけを検査。源・支持・旧Dとの統合を含む売買経路はまだ再生していない。'))
    nulls=[]
    for symbol,q,p,s,v,t,u in [('TOPIX',8,4000.5,4,1000,.5,41.8),('NK225',16,70000,70,10,10,11)]:
        for side in (-1,1):
            r=q*s*v+2*fee(q,u)
            _,line0=budget_line([(q,p)],r,side,u,v,t)
            floor0=protection_line([(q,p)],side,u,v,t)
            old_width=rounded(Fraction(2*fee(q,u),q*v),t,1)+number(t)
            assert line0==number(p)-side*s and floor0==number(p)+side*old_width
            nulls.append(dict(商品=symbol, 数量=q, 方向=side, 初期線=float(line0), 費用床=float(floor0)))
    findings = [
        dict(ID='F01', 状態='数量宣言の整合確認済み・実装未検証', 内容='絶対数量1/2/4は商品別倍率変換を通さない。旧trend_budget8をNK側で2倍にする既存helperへQ1を流すと1が2になる。NoneのQFULLだけ8/16へ分岐。'),
        dict(ID='F02', 状態='数式整合と仕様明記確認済み', 内容='全玉net>=0は追加予定数量の想定買ask/売bidと清算売bid/買ask、各新規注文料金と新Q返済一注文料金で判定。既存玉の黒字だけでは不足。'),
        dict(ID='F03', 状態='仕様への統合で解消・実装未検証', 内容='余裕は追加後の有効停止線max/min（予算線・旧非緩和線・D・有効又は想定で起動する費用床）で測ることが明記された。'),
        dict(ID='F04', 状態='仕様への統合で解消・実装未検証', 内容='予算線はロングceil/ショートfloor。費用床は価格全体を同方向に丸めて1tick buffer。R0−Fが負でも0へclampしないことが明記された。'),
        dict(ID='F05', 状態='仕様への統合で解消・実装未検証', 内容='X1期限は初回実fill+1800から不変。X3のactiveは増玉後grossが閾値未満でも解除しないことが明記された。'),
        dict(ID='F06', 状態='仕様への統合で解消・実装未検証', 内容='prior返済pendingと既知cut/期限は未fill追加を取消す。いずれもなければ次normalで追加実fillを先に記録し、その後全玉停止を判断する。'),
        dict(ID='F07', 状態='仕様への統合で解消・実装未検証', 内容='既存停止が現在行で初成立する場合も、prior返済pending及びstatic cut/期限なしなら予約済み追加を先に実fillし、その後返済判断する。悪いfillを巻き戻さない。'),
        dict(ID='F08', 状態='仕様への統合で解消・実装未検証', 内容='実fill時peer未知なら追加基準を無効にし、後続初回正常pairを基準だけにする。同行追加を禁止し、C1の両source/時計更新を保持することが明記された。'),
        dict(ID='F09', 状態='仕様への統合で解消・会計実装未検証', 内容='全量一注文の返済料金を整数最大剰余で配分。同率は実fill作成順の早いcohortを優先し、後の損益で順序を変えない。実注文費用と親/cohort別GP/GLが明記された。'),
        dict(ID='F10', 状態='数学null確認済み・経済null未実行', 内容='G0_QFULL124口座は旧X1/X3を全経済で照合する必要がある。単独同Qの予算初期線と費用床は旧式と数学的同値。stop→peak更新順、initial-fill row、pending、実返済起点cooldownの一致は未検証。')
    ]
    paths=[WORK/'catalog.py',design_path,WORK/'初版の結果前設計案.json',
           WORK/'有限案だけを検算する.py',WORK/'有限案の純条件確認.json',
           HERE/'初版の20条件純数理レビュー.json',ROOT/'work/wave_v100/事前固定.json',Path(__file__)]
    proof=dict(純数理全合格=True, 仕様確定合格=True, 売買実装認定=False,
        判定='20条件と数式は整合し、今回指摘した未固定点は更新仕様で解消。これを収益性又は売買実装の合格とはしない。',
        条件数=20, 主=catalog.PRIMARY, 数量宣言='両商品で絶対1/2/4。Noneの旧全量だけ8/16。',
        数学的反証例=cases, 単独QFULL数学null=nulls, 指摘=findings, 更新設計の文言照合=design_checks,
        今回の未固定指摘=[],
        実装後に必要な未検証=['全20条件の人工売買と保存終端及び全8期間会計',
            '両商品の絶対数量・予約込み上限・実費用・親とcohort会計',
            '実fillと返済・期限・気配不正の競合及びR0超過',
            '実公表済み両源の追加基準・未知復帰・同clock後続と未来不変',
            '旧全量124口座の全注文・全曲線及び経済null',
            '事前固定後だけ行う全31の収益性・安定性検算'],
        初版の仕様確定不合格='初版の20条件純数理レビュー.jsonにFalseのまま保持。今回Trueは仕様の曖昧点解消だけで、未実装を合格へ置換していない。',
        コード反証の範囲='原板/日時/正式損益を一切読まず、Fractionで有限の価格・費用例を算定。シミュレータ一致や収益性は未検証。',
        損失予算の範囲='R0は理論停止線での全玉net予算。成行の実損失、受信順、委託証拠金や運用資金上限を保証しない。',
        旧100変更=0, 売買本体実装=0, 正式101損益実行=0, API取得=0, 実注文=0,
        SHA256={str(p.relative_to(ROOT)):digest(p) for p in paths})
    output=HERE/'20条件の予算固定増玉と費用及び予約競合の損益前独立反証.json'
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    assert json.loads(output.read_text(encoding='utf-8'))==proof
    print(json.dumps(dict(純数理全合格=True,仕様確定合格=True,売買実装認定=False,
        条件数=20,反証例=len(cases),数学null=len(nulls),指摘数=len(findings),
        仕様明確化=len(design_checks),証跡SHA256=digest(output)),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
