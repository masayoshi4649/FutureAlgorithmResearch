"""101の結果前数式と処理順を独立期待値に固定し、旧金融資料の不変を確認する。"""

from fractions import Fraction
from pathlib import Path

import common
import math_oracle as oracle


def finite(value: object) -> object:
    """
    機能: 有理数の厳密値と表示値をJSONへ保存できる形にする。
    引数: value(object)は有理数、辞書又は通常値。
    返り値: object。有理数は分子/分母/表示値。計算は表示floatへ戻さない。
    """
    if isinstance(value, Fraction):
        return dict(分子=value.numerator, 分母=value.denominator, 表示値=float(value))
    if isinstance(value, dict):
        return {str(key): finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(item) for item in value]
    if isinstance(value, oracle.Cohort):
        return dict(実fill順=value.ordinal, 数量=value.quantity, 価格=finite(value.price), 新規料金=value.entry_fee)
    return value


def main() -> None:
    """
    機能: 最小限の数学反例と数量・競合期待値を保存し、後の売買監査計画を明示する。
    引数: なし。
    返り値: None。売買本体・原板再生・正式101損益を呼び出さない。
    """
    old_count = common.old_immutable()
    work, here = common.BASE, common.HERE
    review_path = work/'review_pre/20条件の予算固定増玉と費用及び予約競合の損益前独立反証.json'
    assert common.sha(review_path) == '5368660920eaf0e7bf74c64a983d5eae955e1015ff39055f4bb091dee0ac4ab6'
    design_path = work/'結果前の設計案.json'
    design = common.read(design_path)
    assert design['予定条件数'] == 20 and design['理論主'] == 'G1_Q1_X1'
    catalog = common.module('101監査の条件読取', work/'catalog.py')
    configs = catalog.catalog()
    assert len(configs) == 20
    quantity_cases = []
    for config in configs:
        for symbol, maximum, user_maximum in [('TOPIX',8,10),('NK225',16,20)]:
            initial = oracle.quantity_for(config, symbol)
            assert initial == config['trend_initial_quantity'] if config['trend_initial_quantity'] is not None else initial == maximum
            sequence = [initial]
            if config['trend_growth_mode']:
                while sequence[-1] < maximum:
                    delta = oracle.next_quantity(sequence[-1], maximum)
                    assert delta == sequence[-1]
                    assert oracle.next_quantity(sequence[-1], maximum, delta) == 0
                    sequence.append(sequence[-1]+delta)
            assert sequence[-1] <= maximum <= user_maximum
            quantity_cases.append(dict(条件=config['id'], 商品=symbol, 初回数量=initial,
                                       数学倍増列=sequence, 予約込み上限=maximum))
    # ----------------------------------------
    # 数学期待値は売買出力から引用せず、実注文料金と清算側を使って算出する。
    c = oracle.cohort
    single = [c(0,1,4000,41.8)]
    risk = oracle.fixed_risk(single[0],4,1000,41.8)
    assert risk == 4082
    current = single+[c(1,1,4010.5,41.8)]
    assert oracle.totals(current,1000,41.8)['weighted_entry'] == Fraction(16021,4)
    correct = oracle.budget_line(current,risk,1,1000,41.8,.5)
    assert correct == oracle.rational(4003.5)
    assert oracle.liquidation(current,correct,1,1000,41.8)['net'] == -3665 >= -risk
    assert oracle.liquidation(current,4003,1,1000,41.8)['net'] == -4665 < -risk
    assert oracle.fee_line(current,1,1000,41.8,.5) == 4006
    reflected = [c(item.ordinal,item.quantity,8000-item.price,41.8) for item in current]
    assert oracle.budget_line(reflected,risk,-1,1000,41.8,.5) == 8000-correct
    assert oracle.fee_line(reflected,-1,1000,41.8,.5) == 3994
    assert oracle.liquidation(reflected,8000-correct,-1,1000,41.8)['net'] == -3665
    examples = [dict(確認='固定R0・加重価格・保護方向丸め・買売反射', R0=risk,
                     加重価格=oracle.totals(current,1000,41.8)['weighted_entry'],
                     正しい買い線=correct, 誤floor時net=-4665, 買い費用床=4006, 売り費用床=3994)]
    fake = [c(0,1,4000,41.8),c(1,1,4001,41.8)]
    assert oracle.liquidation(fake,4000.5,1,1000,41.8)['net'] == -165
    assert oracle.liquidation(fake,4001,1,1000,41.8)['net'] == 835
    examples.append(dict(確認='追加想定全玉を買askで評価する誤り', 正しい売bid評価=-165, 誤買ask評価=835))
    grown = current+[c(2,2,4010.5,41.8)]
    active_gate = oracle.projected_add(grown,4,4010,4010.5,1,risk,4006,3996,
                                      4010,4,40,True,True,1,1000,41.8,.5)
    assert active_gate['net'] == 5834 and active_gate['parts']['固定予算'] == 4009
    assert active_gate['line'] == 4010 and active_gate['clearance'] == 0 and not active_gate['allowed']
    assert active_gate['active'] and active_gate['gross'] == 6500 < 8000
    examples.append(dict(確認='X3保護active継続と統合線の追加阻止', 門番=active_gate))
    reflected_grown = [c(item.ordinal,item.quantity,8000-item.price,41.8) for item in grown]
    short_gate = oracle.projected_add(reflected_grown,4,3989.5,3990,-1,risk,3994,4004,
                                     3990,4,40,True,True,1,1000,41.8,.5)
    assert short_gate['net'] == active_gate['net'] and short_gate['line'] == 8000-active_gate['line']
    assert short_gate['clearance'] == active_gate['clearance'] and short_gate['allowed'] is False
    # ----------------------------------------
    # 合成零費用は等号だけを分離する数学fixtureであり、実料金を変更する条件ではない。
    zero = [c(0,1,4000,0)]
    equal = oracle.projected_add(zero,1,4000.5,4001,1,4000,4000,3996,
                                4000,4,40,False,False,1,1000,0,.5)
    more = oracle.projected_add(zero,1,4000.5,4001,1,4000,4000,3996,
                               4000,4,40,False,False,2,1000,0,.5)
    assert equal['net'] == 0 and equal['clearance'] == oracle.rational(.5)
    assert equal['allowed'] and not more['allowed']
    examples.append(dict(確認='net非負と1呼値余裕の等号・2呼値不合格',
                         範囲='零費用の合成数学例。実101手数料の変更ではない。', net=0, 余裕=equal['clearance'],
                         G1合格=True,G2合格=False))
    completed = oracle.completed_cohorts([c(0,1,4000,41.8),c(1,1,4001.5,41.8)],4001,1,1000,41.8)
    assert completed['close_fees'] == {0:42,1:41} and completed['nets'] == {0:917,1:-582}
    assert completed['parent_net'] == 335 and completed['gross_profit'] == 917 and completed['gross_loss'] == 582
    reverse_items = [c(1,1,4001.5,41.8),c(0,1,4000,41.8)]
    assert oracle.allocate_close(reverse_items,83) == {0:42,1:41}
    examples.append(dict(確認='作成ordinalで料金同率割当・配列並び及び親相殺と分離', 会計=completed))
    fill_orders = [c(i,q,4000,41.8) for i,q in enumerate((1,1,2,4))]
    assert oracle.totals(fill_orders,1000,41.8)['entry_fee'] == 332
    assert oracle.order_fee(8,41.8) == 334
    examples.append(dict(確認='累計新規料金は実注文別切捨', 実332円=332, 誤まとめ334円=334))
    fee_loss = oracle.liquidation(single,4000,1,1000,41.8)
    assert fee_loss['gross'] == 0 and fee_loss['net'] == -82
    examples.append(dict(確認='価格損益ゼロでも料金後は負', gross=0,net=-82))
    late = [c(0,1,4000,41.8),c(1,1,4011.5,41.8)]
    assert oracle.liquidation(late,4001,1,1000,41.8)['net'] == -9665
    assert oracle.budget_line(late,risk,1,1000,41.8,.5) == 4004
    examples.append(dict(確認='悪い次正常fillを取り消さずR0超過を記録', 実fill後net=-9665,
                         R0=risk, 超過=5583, 実fill後停止線=4004))
    low = [c(i,q,p,11) for i,(q,p) in enumerate(((1,9900),(1,9940),(2,9960),(4,10000),(8,10030)))]
    small_risk = oracle.fixed_risk(low[0],20,10,11)
    assert small_risk == 222 and oracle.totals(low,10,11)['F'] == 352
    assert oracle.budget_line(low,small_risk,1,10,11,10) == 10010
    assert oracle.liquidation(low,10000,1,10,11)['net'] == -352
    examples.append(dict(確認='R0−Fを0clampしない', R0=222,F=352,正しい線=10010,誤clamp線net=-352))
    nulls = []
    for symbol,q,p,s,v,t,u in [('TOPIX',8,4000.5,4,1000,.5,41.8),('NK225',16,70000,70,10,10,11)]:
        for side in (-1,1):
            base = [c(0,q,p,u)]
            line = oracle.budget_line(base,oracle.fixed_risk(base[0],s,v,u),side,v,u,t)
            old_fee_width = oracle.tick_round(Fraction(2*oracle.order_fee(q,u),q*v),t,1)+oracle.rational(t)
            assert line == oracle.rational(p)-side*s
            assert oracle.fee_line(base,side,v,u,t) == oracle.rational(p)+side*old_fee_width
            nulls.append(dict(商品=symbol,数量=q,方向=side,初期線=line,費用床=oracle.fee_line(base,side,v,u,t)))
    races = [
        (dict(prior_exit=True,static_cut=False,deadline=False,quote_normal=True,first_stop_now=True),
         ['未fill追加取消','旧実数量の返済実fill']),
        (dict(prior_exit=False,static_cut=True,deadline=False,quote_normal=True,first_stop_now=True),
         ['未fill追加取消','旧実数量の返済判断']),
        (dict(prior_exit=False,static_cut=False,deadline=True,quote_normal=True,first_stop_now=False),
         ['未fill追加取消','旧実数量の返済判断']),
        (dict(prior_exit=False,static_cut=False,deadline=False,quote_normal=True,first_stop_now=True),
         ['追加実fill','実価格と実料金で停止線更新','全実数量の返済判断']),
        (dict(prior_exit=False,static_cut=False,deadline=False,quote_normal=False,first_stop_now=True),
         ['追加pending維持']),
    ]
    race_results = []
    for flags, operations in races:
        assert oracle.pending_order(**flags) == operations
        race_results.append(dict(条件=flags, 操作順=operations))
    # ----------------------------------------
    # ここまで純数理。エンジンはまだ呼ばず、必要な実装検算を有限に予約する。
    bindings = [work/'catalog.py',design_path,review_path,
                common.ROOT/'work/wave_v100/事前固定.json',Path(__file__),here/'common.py',here/'math_oracle.py']
    clarification = work/'実装前の仕様明確化.json'
    if clarification.exists():
        bindings.append(clarification)
    plan = dict(状態='独立数学の期待値準備。新売買実装を呼ぶ前。',所有='work/wave_v101/auditのみ',
        事前主='G1_Q1_X1', 条件数=20, 全31は既知=True,
        旧100不変照合=old_count,
        許可=['純数理','人工20条件','旧QFULL2×31×2=124口座のnull再生'],
        現段階実行=['数学のみ。旧原板や新正式損益は読んでいない。'],
        正式101損益実行=0, API取得=0, 実注文=0,
        予定検査=[
            dict(段階='本体完成後の人工',範囲='20条件×両商品、買売反射は意味のある代表経路に限定',
                 根拠='実注文から料金/cohort/初回固定R0/統合停止線/初回期限/実fill競合を期待値化。latent traceを正答としない。'),
            dict(段階='旧全量null',範囲='QFULL2×31×2=124口座',
                 根拠='100保存台帳の全注文・親・全原板曲線及び旧状態。同source/fees数量、初回/返済順を守る。'),
            dict(段階='実代表接頭',範囲='固定数量/主増玉/X3増玉を意味別に選ぶ少数接頭',
                 根拠='最初入口/追加判断/停止順、自己・相手・同時計後続の未来変形。未完親を勝ち又は消失にしない。'),
            dict(段階='通常人工CLI',範囲='人工20×両商品40口座と全8期間の具体集計・安定性・保存終端',
                 根拠='監査通常mainを保存再読込まで実行。根の実ledger/run_one保存終端も別に束ねる。架空31場へ水増ししない。'),
            dict(段階='固定後・根許可後',範囲='全20×31×2=1240口座、20×8×2=320商品期間',
                 根拠='全注文料金・親とcohort・全原板清算時価・絶対数量と上限を独立再算定。')],
        失敗の扱い='初回不合格を原因と指紋付きで保持。期待値又は許可範囲を結果へ合わせて拡げない。',
        未保証='数学準備は本体一致・全日安定収益・真受信同期・実ミニ/マイクロ執行の証明ではない。',
        SHA256=common.fingerprints(bindings))
    common.save(here/'plan.json',plan)
    proof = dict(合格=True, 範囲='独立有理数の期待値のみ。売買本体を呼んでいない。',
                 条件数=20, 絶対数量ケース=len(quantity_cases), 数量=quantity_cases,
                 数学反例=finite(examples), 旧全量数学null=finite(nulls), pending競合=race_results,
                 初期線の解釈='初回実fill価格−side*Sへ固定。価格peak・初回時刻・Sを追加でリセットしない。',
                 旧100不変照合=old_count, 正式101損益実行=0, API取得=0, 実注文=0,
                 売買実装認定=False, SHA256=common.fingerprints(bindings+[here/'plan.json']))
    output = here/'独立数理期待値と数量及び予約順の事前確認.json'
    common.save(output,proof)
    print('独立数理合格。20条件40数量、数学反例'+str(len(examples))+'、null4、競合5、旧1159不変。',flush=True)
    print('証跡SHA256='+common.sha(output),flush=True)


if __name__ == '__main__':
    main()
