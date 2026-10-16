"""既知92の反例と次段16対照を、93の損益を使わず論理検査する。"""

import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DESIGN = ROOT / 'work/wave_v92/review/次段N3N4と独立配分の16対照設計.json'


def fingerprint(path: Path) -> str:
    """
    機能: 参照した既知設計又は理論コードの内容を識別する。
    引数: path (Path) は読取対象ファイル。
    返り値: str はSHA256の16進表記。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fee_width(quantity: int, per_side: float, multiplier: float) -> float:
    """
    機能: 新規と返済の注文単位floor手数料を一枚当たり価格幅へ換算する。
    引数: quantity (int) は予定枚数、per_side (float) は片道円料、multiplier (float) は一枚一価格点の円倍率。
    返り値: float は予定往復手数料の価格幅。
    """
    assert quantity > 0 and per_side >= 0 and multiplier > 0
    return 2 * math.floor(quantity * per_side + 1e-10) / (quantity * multiplier)


def required_win_rate(ratio: float) -> float:
    """
    機能: 実平均勝負金額比を仮定し、金額利益80%に必要な利益親率を計算する。
    引数: ratio (float) は費用後平均利益額を費用後平均損失額で割った値。
    返り値: float はPF4を満たす利益親率。
    """
    assert ratio > 0
    return 4 / (ratio + 4)


def mathematical_cases() -> list[dict]:
    """
    機能: 予定価格と実約定、幅停止と極値停止、損益割合の飛躍を人工数値で反証する。
    引数: なし。市場経路や新しい損益を入力しない。
    返り値: list[dict] は反例の数値と成立した恒等式。
    """
    top_full_fee = fee_width(10, 41.8, 1000)
    top_small_fee = fee_width(2, 41.8, 1000)
    nk_full_fee = fee_width(20, 11, 10)
    nk_small_fee = fee_width(4, 11, 10)
    assert top_full_fee == .0836 and top_small_fee == .083
    assert nk_full_fee == nk_small_fee == 2.2
    assert math.isclose(required_win_rate(2), 2 / 3)
    assert math.isclose(required_win_rate(.5), 8 / 9)
    # ----------------------------------------
    # 同じ発注判断を後の実価格で採否変更すると未来情報が混じる反例。
    anchor, width, extreme, bid, ask = 100., 4., 95., 95.5, 96.
    failure_line = extreme - .5
    planned_distance = ask - failure_line
    assert 0 < planned_distance <= .5 * width
    next_ask = 97.5
    assert next_ask - failure_line > .5 * width
    # ----------------------------------------
    # 予定rhoだけでは実PFや80%を証明しない。
    planned_g = anchor - ask - (ask - bid) - top_full_fee
    planned_r = min(planned_distance, width + ask - bid) + top_full_fee
    rho = planned_g / planned_r
    assert rho >= 2
    actual_average_ratio, actual_positive_rate = 2., .5
    actual_pf = actual_positive_rate * actual_average_ratio / (1 - actual_positive_rate)
    assert actual_pf == 2 and actual_pf / (1 + actual_pf) < .8
    # ----------------------------------------
    # 独立親のG/Lは相殺せず、源別割合を金額で加重する。
    gains, losses = (400., 30.), (100., 70.)
    source_shares = [g / (g + l) for g, l in zip(gains, losses)]
    aggregate = sum(gains) / (sum(gains) + sum(losses))
    weighted = sum((g + l) * s for g, l, s in zip(gains, losses, source_shares)) / (sum(gains) + sum(losses))
    assert math.isclose(aggregate, weighted)
    assert min(source_shares) <= aggregate <= max(source_shares)
    assert aggregate < source_shares[0]
    return [
        {'検査': '予定枚数ごとの注文単位floor料金', 'TOPIX10枚': top_full_fee,
         'TOPIX2枚': top_small_fee, 'NK20枚': nk_full_fee, 'NK4枚': nk_small_fee,
         '意味': 'TOPIXのS02予定入口はC11の単純0.2倍へ代用できない。日経のこの料金幅は枚数に依存しない。'},
        {'検査': '発注後の次気配飛び', '判断ask': ask, '判断時極値失敗線': failure_line,
         '予定停止距離': planned_distance, '最大予定距離': .5 * width,
         '次実ask': next_ask, '実停止距離': next_ask - failure_line,
         '意味': '判断時の上限合格は実約定後の損失上限を保証しない。後の実価格で予約を消さない。'},
        {'検査': '入口rhoと実金額利益割合の区別', '予定rho': rho,
         '仮定した実平均勝負比': actual_average_ratio, '仮定した実利益親率': actual_positive_rate,
         '実PF': actual_pf, '実金額利益割合': actual_pf / (1 + actual_pf),
         '意味': '予定rho>=2でも、実勝負比2と親率50%なら金額利益は66.7%で80%未達。'},
        {'検査': '小幅利確の必要利益親率', '平均勝負比2': required_win_rate(2),
         '平均勝負比0.5': required_win_rate(.5),
         '意味': '中心目標を近くして親勝率が増えても、実平均勝ち額が縮めばPF4へ必要な親率が上がる。'},
        {'検査': '親を相殺しない配分の割合上限', '源別割合': source_shares,
         '合計割合': aggregate, '加重平均': weighted,
         '意味': '独立固定枠の配分だけで最高源割合を超えない。日別平準化には別の価値があり、それを否定する式ではない。'},
    ]


def depth_selection_cases() -> dict:
    """
    機能: rho2ゲートが通常の一幅反発より深い逸脱を選ぶ作用を、新損益なしで反証する。
    引数: なし。固定した幅・呼値・spread・料金と人工価格だけを使用する。
    返り値: dict は導出式、代表一幅境界、深い逸脱正例及び正常呼値気配例。
    """
    rows = []
    for symbol, width, tick, spread, fee in [('TOPIX', 5., .5, .5, fee_width(10, 41.8, 1000)),
                                          ('NK225', 70., 10., 10., fee_width(20, 11, 10))]:
        v = .25
        distance = v * width + tick
        assert distance <= width + spread
        threshold = 3 * v + 2 * tick / width + spread / width + 3 * fee / width
        for u, kind in [(1., '理想化した通常一幅逸脱'), (2., '同じ回復量で深さ二幅')]:
            gain = (u - v) * width - spread - fee
            risk = distance + fee
            ratio = gain / risk
            accepted = gain > 0 and ratio >= 2
            assert accepted == (u >= threshold)
            assert accepted == (u == 2.)
            rows.append({'銘柄': symbol, '例': kind, 'W': width, '呼値': tick,
                         'spread': spread, '往復fee価格幅': fee,
                         'u': u, 'v': v, '予定極値停止距離': distance,
                         '中心までの予定利益代理': gain, '予定リスク代理': risk,
                         'rho': ratio, '必要最小u': threshold, 'ゲート合格': accepted,
                         '注': 'vは予定ask/bidと極値midの差の幅比。ここでは.25と理想化し、正常呼値への丸めと半spreadを加えない。'})
    # ----------------------------------------
    # ラージの呼値に合う実行可能な気配だけで、mid回復と入口askの違いを確認する。
    quotes = [('TOPIX', 4100., 4095.25, 4096.5, 4097., 5., .5, .5,
               fee_width(10, 41.8, 1000), False),
              ('TOPIX', 4100., 4090.25, 4091.5, 4092., 5., .5, .5,
               fee_width(10, 41.8, 1000), True),
              ('NK225', 68600., 68525., 68540., 68550., 70., 10., 10.,
               fee_width(20, 11, 10), False),
              ('NK225', 68600., 68455., 68470., 68480., 70., 10., 10.,
               fee_width(20, 11, 10), True)]
    valid_quote_rows = []
    for symbol, anchor, extreme, bid, ask, width, tick, spread, fee, expected in quotes:
        assert math.isclose(ask - bid, spread)
        assert math.isclose(bid / tick, round(bid / tick))
        assert math.isclose(ask / tick, round(ask / tick))
        mid = (bid + ask) / 2
        assert mid - extreme >= .25 * width
        failure = extreme - tick
        assert bid > failure
        v, u = (ask - extreme) / width, (anchor - extreme) / width
        distance = ask - failure
        assert distance <= width + spread
        gain, risk = anchor - ask - spread - fee, distance + fee
        ratio = gain / risk
        threshold = 3 * v + 2 * tick / width + spread / width + 3 * fee / width
        assert (ratio >= 2) == (u >= threshold) == expected
        valid_quote_rows.append({'銘柄': symbol, '例': '深い逸脱正例' if expected else '通常一幅境界付近',
                                 '準備中心A': anchor, '極値mid': extreme, '現在bid': bid, '現在ask': ask,
                                 '現在mid': mid, '実mid回復幅': mid - extreme,
                                 '入口askから極値midの幅': ask - extreme,
                                 'u': u, 'v': v, '極値失敗線E': failure,
                                 '予定停止距離D': distance, '予定中心利益代理': gain,
                                 '予定リスク代理': risk, 'rho': ratio, '必要最小u': threshold,
                                 'ゲート合格': expected})
    return {'対象': '主C11及びrho2列の構造。条件16及びrho2は変更しない。人工価格の式だけで新しい売買損益を計算しない。',
            '定義': {'u': 'd(A−x)/W。中心から観測極値までの深さの幅比。',
                     'v': 'd(q_entry−x)/W。予定新規買ask又は売bidから極値midまでの幅比。mid回復量とは異なる。',
                     'E': 'x−d×呼値。新規判断時までに観測したmid極値から一呼値先の失敗線。',
                     '適用領域': 'D=vW+呼値がW+現在spread以下で、予定ORリスクのminが極値側Dとなる場合。',
                     'g': '(u−v)W−spread−fee', 'r': 'vW+呼値+fee',
                     '導出': 'rho=g/r>=2 ⇔ u>=3v+2呼値/W+spread/W+3fee/W。'},
            '通常境界と深い正例': rows, '正常呼値に合うBBOの反例と正例': valid_quote_rows,
            '売り反射': '価格を任意基準Bに対し2B−価格へ写し、bidとaskを交換するとd=−1でu/v/g/r及び採否は同一。方向バイアスを式へ入れない。',
            '選択効果': [
                'TOPIXの理想化した一幅逸脱・v=.25でも必要u=1.10016、日経は1.272857以上なので通常u=1は拒否される。',
                '実際のmid回復.25Wから予定askまで半spreadが加わり、呼値に応じて回復量を超過するためvが増え、必要逸脱はさらに深くなる。',
                'ゲートは低リスクを見て高い勝率を証明するものではない。中心余地が大きい深い逸脱に選択が偏り、その深さは強い片道ドリフトを示している可能性もある。',
                '拒否機会を同エピソードで消費するので、拒否後に深く下がった同じ準備へ入り直すことはない。ここでいう深い逸脱選択は最初の双方回復判断の時点で既に深かった別の機会を指す。',
                '活動が少なくなるだけで金額80や無損失を作る可能性がある。活動場数・親数・消えた利益・新固有損失を全31既知場で別に算出する。',
                '現在spreadを利益側の安全余裕へもう一度引くのは事前設計の保守代理。将来spreadや次約定の悪化を保証する式ではない。',
            ],
            '追加条件': 0, '条件変更': 0, '主変更': 0, '新93損益閲覧': 0,
            '有用性認定': False}


def main() -> None:
    """
    機能: 新しい16条件の損益を閲覧せず、事前反証と実装に必要な人工ケースを保存する。
    引数: なし。既知92の事前設計だけを読み取る。
    返り値: None。新93のtheoryへ日本語JSONを保存する。
    """
    design = json.loads(DESIGN.read_text(encoding='utf-8'))
    ids = [v['ID'] for v in design['最小16対照案']]
    assert ids == [f'C{i:02}' for i in range(12)] + [f'S{i:02}' for i in range(4)]
    value = {
        '段階': '新93の完結損益閲覧0。既知92全31結果と次段設計に基づく損益前反証。条件の有用性認定ではない。',
        '既知設計': str(DESIGN.relative_to(ROOT)).replace('\\', '/'),
        '既知設計SHA256': fingerprint(DESIGN), '理論コードSHA256': fingerprint(Path(__file__)),
        '対象16条件': ids, '主': 'C11', '配分統合': 'S03',
        '主に据える論理': [
            '回復を待った後の入口には、観測中心までの利益余地が小さい一方、過去極値までの負け距離が大きいという不整合がある。現在BBOだけで採否を固定して検証する。',
            '反発仮説に対して3Wの目標が中心を大きく通り越す不整合を、当時既知の中心到達へ変更する。',
            '幅保険停止と極値失敗を論理和にし、極値失敗で実損失が確定した時は旧中心の新しい双方帰還まで反発だけを止める。',
            'この三要素は理論上の接続であり、勝ちを失う反例を持つ。C11を成績予測又は実行推奨へ扱わない。',
        ],
        '最小仕様の明確化': {
            'raw往復': '旧raw=2は両市場のvalid・low ER・inside・common==0。mode!=2をraw Falseへ代用しない。有限有効common!=0は正当なFalse。共同方向を外したlow ER単独へ原設計を変えない。',
            'raw三状態': '根の事前決定に従いN4専用knownはER/currentに加え両180範囲の源・位置有効及び有限正幅・有限low/highと、共同方向の30/300return源有効かつ有限を要求する。不明raw0はFalseへ数えない。旧C00/C01対照の入力は変更しない。',
            'raw履歴': 'raw_oldest_timeは両市場30/300窓と180範囲の実start源時計の最小。FalseもTrueもこれが実返済時計より後であることを要求する。Falseは両current源と時計が実返済時より新しく、TrueはFalse後の格子で両源がFalse源より新しく元のmode2確認完了を要求。返済前False、返済行False、確認済みmodeが残るだけ、欠測をFalseにすることは不可。単なるgrid−300で代用しない。',
            '双方帰還': '自己は実返済後の正常原板LastPrice/BBO、相手は同判断の正常最新mid格子かつ10秒以内。相手源は実返済時公開源より新しく、代理時計は実返済時計より後。初の中心取得と別時刻帰還の寄せ集めを不可とする。',
            '新準備の中心': '失敗中心は休止解除の履歴変数。解除当行に新規しない。別の後続有効mode2へ新しい準備中心を一度作り、その後新逸脱・新回復を要求する。',
            '停止証拠': '元LastPrice固定線と極値清算BBO線は異なる。ORの両条件を独立評価し、同時成立時も両証拠を保持。N4は極値証拠と実全返済net<0に基づき、表示理由が幅停止なら構造失敗が消える実装を不可とする。',
            '機会消費': '元の双方回復が初成立した行で入口ゲートを一度評価し、拒否後は同エピソードの安くなった後の行へ再採否しない。旧仮説の明確解除と新準備だけが解除する。既予約を未来実価格で取消しない。',
            '実枚数料金': 'C11フル枠とS02小枠は注文単位floor料金を各自使用する。S03の反発源は同枚数S02と経路一致し、追従源はS00と一致する。',
            '同時源': '8/16追従と2/4反発は別親・別状態・固定独立枠。相殺、枠貸出、片方の休止で他方の取消や方向変更をしない。',
        },
        '人工数値反証': mathematical_cases(),
        'rho2による逸脱深さの選択作用': depth_selection_cases(),
        '人工経路で必須の反例': [
            '同じ判断前まで一致し、次askだけ飛ぶ二経路で入口ゲートと予約行は不変。実取得・実損失だけが変わる。',
            '最初の双方回復でrho不足→後で安くなりrho合格しても新規なし。明確解除→後続mode2→新準備→新逸脱でのみ次機会を作る。',
            '買いでLastPrice固定停止だけ、bid極値停止だけ、両停止同時、利確と停止同時の四経路。売り反射でも同じ証拠。',
            '極値証拠で返済予約後、次気配で実net負ならN4開始。次気配が戻って実net正なら休止しない。幅停止だけのnet負も最初のN4対象にしない。',
            '返済前又は同返済行のraw Falseを無効化。返済後missing/ER不明/raw0をFalseに数えず、確認中mode0もFalseにしない。現在源だけ更新しても窓又は範囲の実start源が返済前なら無効。有限有効raw False→後の確認済みTrueで解除する。',
            '返済後の自己帯内と相手過去帯内を別時刻で保存してもBOTH解除なし。相手源番号だけ増え代理時計が返済以前なら解除なし。新源の第一center取得だけでも解除なし。',
            '休止解除行の逸脱では新規なし。後続mode2で作った新中心を使い、旧失敗中心へ相手だけ新しい中心を追加しない。',
            '中心目標のLastPrice到達後、次返済bidが下へ飛びnet負となる親を利益へ数えない。中心目標だから勝ちとする会計を拒否する。',
            '共同回復で反発と追従がともに買い→急反落し両源損切り。反対玉の含み損と両側料金を残したまま源別G/Lを検算する。',
            'S03をS00/S02と同枚数・同入力で走らせ、全予約と注文価格と全行清算時価まで源別一致を要求する。',
        ],
        '反証しても残る限界': [
            '予定rhoは未来到達確率でも実平均勝負比でもない。小さな戻りで入るほど底の偽物と気配往復の影響を受ける。',
            'OR停止は許容価格の実約定保証ではない。幅停止のLastPriceと極値停止のbid/askを同じmin価格へ統合して真の上限と宣伝しない。',
            '中心は真の均衡ではない。一方向に流れる相場では帰還しない。休止により損失とともに次の有利な反発も失う。',
            'C10の全窓更新には観測履歴上少なくとも300秒窓の始点更新が必要。その後も有効False→確認済みTrueが来なければ場末まで休む。固定待ち時間の性能保証ではなく、活動不足という実際の副作用として確認する。',
            '双方回復は独立した二つの確率証拠ではない。共通要因に反応する両市場の確認を合成して95%等にしない。',
            '異なる思想でも双方同方向の建玉となり同時損失を出せる。低相関だけで赤字場や最大下落の改善を予測しない。',
            '保存31は全て既知探索。前16と後15に分けることは新しい未知データの実証ではない。',
        ],
        '結果後に固定して分析する項目': [
            '各16条件×31場×2商品、親別G/L/net、両側料金、全行清算時価と方向最大予約/保有。',
            'C00→C01→C02、C01→C03/C04、C02→C05、C05→C06/C07、C02→C08/C09/C10、C06→C11の同一新規管理差と消えた旧利益/損失及び新固有親。',
            'C11/S03の最悪3場を商品別に原板時計へ戻し、判断時中心・極値・bid/ask・peer源・rho・停止証拠・再参加を具体時刻で説明する。',
            '最大利益日及び最大利益親の除外、前後区分、Long/Short源、無取引を勝ちへ含めない活動量。',
            'S03−S00の追加価値、S03−S01の同上限置換価値、S03源別S00/S02一致、両源赤字/追従赤字を救った場/追従黒字を壊した場。',
        ],
        '有用性認定': False, '金額80達成認定': False,
        '新93完結損益閲覧': 0, '新売買実行': 0, 'API取得': 0, '実注文': 0,
    }
    destination = HERE / '16対照の損益前反証と人工ケース.json'
    destination.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'保存先': str(destination), 'SHA256': fingerprint(destination),
                      '数値反例数': len(value['人工数値反証']), '経路反例数': len(value['人工経路で必須の反例']),
                      '新93完結損益閲覧': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
