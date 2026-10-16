"""限定小射影だけを独立Fraction算術と公開済み会計へ照合する。"""

import ast
from datetime import datetime
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import traceback


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = HERE.parents[1]
NAME = '根へ渡す九条件と六例の限定小結.json'
EXPECTED_SHA = '65942e400ee39afb70b826b4868ed2dd928759dd91ccbcd188d0836ab9a5cb7d'
PROOF = HERE / '九条件と六例及び初期支持線比較の独立限定診断監査.json'
MAIN = 'E01_CURRENT_VOL_PRICE_RESPONSE_WIDE_TRAIL'
SYMBOLS = ('TOPIX', 'NK225')
MONEY_KEYS = ('mid_direction_yen', 'crossing_disadvantage_yen', 'actual_fee_yen', 'actual_net_yen')
SUM_KEYS = ('parent_count', *MONEY_KEYS, 'wins', 'losses', 'mid_reverse_count', 'nonnegative_mid_but_net_loss',
            'once_positive_liquidation_count', 'never_positive_liquidation_count', 'support_updated_parents', 'peak_reached_wide_arm')
checks = 0


def check(value: bool, detail: object) -> None:
    """
    機能: 検査件数を数え、不整合ならその場で根拠とともに停止する。
    引数: value(bool)は検査結果、detail(object)は根拠。
    返り値: None。
    """
    global checks
    checks += 1
    assert value, detail


def same(actual: object, expected: object, detail: object) -> None:
    """
    機能: 零と未定義を区別して保存値を独立期待へ照合する。
    引数: actual/expected/detail(object)は実値、期待値、根拠。
    返り値: None。
    """
    if isinstance(actual, (int, float, Fraction)) and not isinstance(actual, bool) and isinstance(expected, (int, float, Fraction)) and not isinstance(expected, bool):
        check(math.isfinite(actual) and math.isfinite(expected) and math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-7), (detail, actual, expected))
    else:
        check(actual == expected and (actual is None) == (expected is None), (detail, actual, expected))


def amount(side: int, q: int, mult: int, entry: dict, exit_: dict, fee: int) -> dict:
    """
    機能: 買ask/売bidの実行価格と気配中値分解を別式で計算する。
    引数: side(int)、q(int)、mult(int)、entry/exit_(dict)は両端気配、fee(int)は全実料。
    返り値: dictはFractionによる中値方向、横断負担、粗損益、純損益。
    """
    eb, ea = Fraction(str(entry['bid'])), Fraction(str(entry['ask']))
    xb, xa = Fraction(str(exit_['bid'])), Fraction(str(exit_['ask']))
    assert 0 < eb <= ea and 0 < xb <= xa
    ep, xp = (ea, xb) if side == 1 else (eb, xa)
    mid_e, mid_x = (eb + ea) / 2, (xb + xa) / 2
    direct = side * (xp - ep) * q * mult
    direction = side * (mid_x - mid_e) * q * mult
    crossing = ((ea - eb) + (xa - xb)) / 2 * q * mult
    same(direct, direction - crossing, ('独立中値恒等式', side, q, mult))
    return dict(mid_direction_yen=direction, crossing_disadvantage_yen=crossing,
        actual_gross_yen=direct, actual_fee_yen=fee, actual_net_yen=direct - fee,
        entry_mid=mid_e, exit_mid=mid_x, entry_spread=ea - eb, exit_spread=xa - xb)


def round_fee(q: int, symbol: str) -> int:
    """
    機能: 注文ごとの税込料を整数切捨てして往復実料を独立計算する。
    引数: q(int)は単回枚数、symbol(str)は商品。
    返り値: intは新規と全量返済の二注文分の手数料。
    """
    rate = Fraction(209, 5) if symbol == 'TOPIX' else Fraction(11, 1)
    return 2 * (q * rate.numerator // rate.denominator)


def validate_group(group: dict, symbol: str, label: object) -> None:
    """
    機能: 全親又は限定群の分母、実料、損益恒等式と分類の足算を確認する。
    引数: group(dict)、symbol(str)、label(object)は限定集計と根拠。
    返り値: None。集計から未保存の個別親を復元しない。
    """
    count = group['parent_count']
    same(group['wins'] + group['losses'], count, (label, '勝負親数'))
    same(sum(group['exits'].values()), count, (label, '出口分母'))
    same(group['once_positive_liquidation_count'] + group['never_positive_liquidation_count'], count, (label, '途中黒字分母'))
    same(group['mid_reverse_count'] + group['nonnegative_mid_but_net_loss'], group['losses'], (label, '負け中値分類'))
    same(group['actual_fee_yen'], count * round_fee(10 if symbol == 'TOPIX' else 20, symbol), (label, '全量実料'))
    same(group['actual_net_yen'], group['mid_direction_yen'] - group['crossing_disadvantage_yen'] - group['actual_fee_yen'], (label, '金額恒等式'))
    check(group['crossing_disadvantage_yen'] >= 0 and group['actual_fee_yen'] >= 0, (label, '負担非負'))
    for key, value in group.items():
        if key.endswith('_count') or key in ('wins', 'losses', 'support_updated_parents', 'peak_reached_wide_arm'):
            check(int(value) == value and 0 <= value <= count, (label, key))


def combine(groups: list[dict], target: dict, label: object) -> None:
    """
    機能: 排他的部分群の保存数値を足し合わせ、母群との整合を確認する。
    引数: groups(list[dict])は部分群、target(dict)は母群、label(object)は根拠。
    返り値: None。
    """
    for key in SUM_KEYS:
        if key in target and all(key in group for group in groups):
            same(sum(group[key] for group in groups), target[key], (label, key))
    codes = set(target['exits']) | set().union(*(set(group['exits']) for group in groups))
    for code in codes:
        same(sum(group['exits'].get(code, 0) for group in groups), target['exits'].get(code, 0), (label, '出口', code))


def source_fingerprints() -> dict:
    """
    機能: 金融計算を呼ばず、完成経済17sourceの監査前後指紋を取得する。
    引数: なし。
    返り値: dict[str,str]はsource相対pathとSHA256。
    """
    paths = list((BASE / 'engine').glob('*.py')) + [BASE / 'root_review' / name for name in ('plan.py', 'finance.py', 'financial_metrics.py')]
    check(len(paths) == 17, '経済17源')
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def run() -> dict:
    """
    機能: 計画済みの限定JSON保全資料だけを実例と群の独立算術へ結ぶ。
    引数: なし。
    返り値: dictは合否、保存範囲と未測事項。元金融や大射影は開かない。
    """
    before = source_fingerprints()
    raw = (HERE / '同bytes保全' / NAME).read_bytes()
    same(hashlib.sha256(raw).hexdigest(), EXPECTED_SHA, '限定同bytes')
    value = json.loads(raw)
    check(value['全合格'], '限定診断の保存完了')
    public_path = BASE / 'technical_audit/report_audit/公開同bytes保全/現在の活動と再進行の公開会計.json'
    public = json.loads(public_path.read_bytes())
    same(value['出典結果SHA256'], public['金融出典']['SHA256'], '公開会計と診断の同一結果系譜')
    same(len(value['九条件']), 9, '九条件')
    group_count = 0
    for cid, symbols in value['九条件'].items():
        same(set(symbols), set(SYMBOLS), (cid, '両商品'))
        for symbol, groups in symbols.items():
            all_, neg = groups['all_parents'], groups['negative_parents']
            for name, group in groups.items():
                validate_group(group, symbol, (cid, symbol, name))
                group_count += 1
            same(neg['parent_count'], all_['losses'], (cid, symbol, '負群は実負親限定'))
            same(neg['wins'], 0, (cid, symbol, '負群勝ちなし'))
            same(all_['mid_reverse_count'], neg['mid_reverse_count'], (cid, symbol, '中値逆行親は負親'))
            same(all_['never_positive_liquidation_count'], neg['never_positive_liquidation_count'], (cid, symbol, '黒字なし親は負親'))
            same(all_['once_positive_liquidation_count'] - all_['wins'], neg['once_positive_liquidation_count'], (cid, symbol, '勝ちを除く途中黒字'))
            rows = [row for row in public['cases'][cid]['rows'] if row['symbol'] == symbol]
            same(sum(row['campaigns'] for row in rows), all_['parent_count'], (cid, symbol, '公開親分母'))
            same(sum(row['net'] for row in rows), all_['actual_net_yen'], (cid, symbol, '公開純損益'))
            same(-sum(row['loss'] for row in rows), neg['actual_net_yen'], (cid, symbol, '公開総損失'))
            same(sum(row['profit'] for row in rows), all_['actual_net_yen'] - neg['actual_net_yen'], (cid, symbol, '公開総利益'))
            same(sum(row['fees'] for row in rows), all_['actual_fee_yen'], (cid, symbol, '公開料'))
            for key in ('crossing_disadvantage_yen', 'actual_fee_yen'):
                check(all_[key] >= neg[key], (cid, symbol, '部分群負担', key))
            check(all_['mid_direction_yen'] < 0, (cid, symbol, '全九の中値合計も負'))
    # ----------------------------------------
    for symbol, groups in value['主反応WIDE'].items():
        for label, group in groups.items():
            validate_group(group, symbol, ('主WIDE', symbol, label))
            group_count += 1
        for short, original in (('全親', 'all_parents'), ('負親', 'negative_parents')):
            for key, saved in value['九条件'][MAIN][symbol][original].items():
                same(groups[short][key], saved, (symbol, '主同値', short, key))
        combine([groups['負親かつ一度も黒字なし'], groups['負親かつ途中黒字あり']], groups['負親'], (symbol, '負親黒字有無の二分'))
        same(groups['負親']['peak_reached_wide_arm'], 0, (symbol, '負親はWIDE起動未達'))
    support_summary = {}
    for symbol, groups in value['支持更新返済の初期線比較'].items():
        for label, group in groups.items():
            validate_group(group, symbol, ('支持当行', symbol, label))
            group_count += 1
            same(set(group['exits']) - {'143'}, set(), (symbol, label, '支持出口だけ'))
        all_main = value['主反応WIDE'][symbol]['全親']
        same(sum(group['parent_count'] for group in groups.values()), all_main['exits'].get('143', 0), (symbol, '全支持出口の二分'))
        unlost = groups['更新線を喪失・初期線は未喪失']
        same(unlost['parent_count'], 32 if symbol == 'TOPIX' else 54, (symbol, '当行初期線未喪失'))
        same(unlost['once_positive_liquidation_count'], unlost['parent_count'], (symbol, '群は全親途中黒字'))
        same(unlost['support_updated_parents'], unlost['parent_count'], (symbol, '更新群資格'))
        support_summary[symbol] = dict(群分母=unlost['parent_count'], 勝ち=unlost['wins'], 負け=unlost['losses'],
            中値=unlost['mid_direction_yen'], 横断=unlost['crossing_disadvantage_yen'], 料=unlost['actual_fee_yen'], net=unlost['actual_net_yen'],
            未確認='各32/54親の当行BBOと初期線の個別分類は限定射影に無い。sourceの式と群の足算のみ検査。OFF後の回復と損益は未測。')
    # ----------------------------------------
    classifier_path = BASE / 'diagnosis/support_reference.py'
    classifier_source = classifier_path.read_text(encoding='utf-8')
    tree = ast.parse(classifier_source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'classify')
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(classifier_path), 'exec'), namespace)
    classify = namespace['classify']
    support_pure = 0
    for side in (1, -1):
        for distance in (0, 1, 2, 3):
            initial, active = 100, 100 + side * distance
            for bid in range(94, 107):
                for spread in (0, 1, 2):
                    ask = bid + spread
                    active_lost = bid <= active and ask <= active if side == 1 else bid >= active and ask >= active
                    if not active_lost:
                        continue
                    p = dict(side=side, initial_support_line=initial,
                        exits=[dict(reason=143, 判断=dict(normal=True, bid=bid, ask=ask, support_line=active))])
                    lost = bid <= initial and ask <= initial if side == 1 else bid >= initial and ask >= initial
                    same(classify(p), '初期線も喪失' if lost else '更新線を喪失・初期線は未喪失', ('支持独立両BBO真偽表', side, distance, bid, ask))
                    support_pure += 1
    identity_pure = 0
    for side in (1, -1):
        for symbol, q, mult, tick in (('TOPIX', 10, 1000, .5), ('NK225', 20, 10, 10)):
            for se in (1, 2, 3):
                for sx in (1, 2, 3):
                    for move in (-3, 0, 3):
                        e = dict(bid=1000, ask=1000 + se * tick)
                        x = dict(bid=1000 + move * tick, ask=1000 + (move + sx) * tick)
                        amount(side, q, mult, e, x, round_fee(q, symbol))
                        identity_pure += 1
    # ----------------------------------------
    example_summary = []
    losing_peaks = []
    for symbol in SYMBOLS:
        losses, wins = value['赤字上位三場六親'][symbol], value['勝ち反証最大二親'][symbol]
        same(len(losses), 3, (symbol, '赤字三場の三親'))
        same(len(wins), 2, (symbol, '勝ち反証二親'))
        ordered_rows = sorted((row for row in public['cases'][MAIN]['rows'] if row['symbol'] == symbol and row['net'] < 0), key=lambda row: row['net'])[:3]
        same([parent['session'] for parent in losses], [row['session'] for row in ordered_rows], (symbol, '公開赤字上位三場'))
        for parent in losses + wins:
            side, q = parent['side'], parent['q']
            mult, tick = (1000, .5) if symbol == 'TOPIX' else (10, 10)
            same(parent['symbol'], symbol, (parent['session'], '商品'))
            same(q, 10 if symbol == 'TOPIX' else 20, (symbol, '上限全量'))
            pub, enter, exit_ = parent['publication'], parent['entry'], parent['exit_fill']
            same(enter['normal_row'], pub['normal_row'] + 1, (symbol, parent['session'], '新規次行'))
            check(enter['raw_seq'] > pub['raw_seq'], '同clockでも原seqは先行')
            check(enter['normal_row'] < exit_['normal_row'] and enter['raw_seq'] < exit_['raw_seq'], '返済は新規より後')
            check(datetime.fromisoformat(pub['JST_price_proxy']) <= datetime.fromisoformat(enter['JST_price_proxy']) <= datetime.fromisoformat(exit_['JST_price_proxy']), '価格時計順')
            for point in (pub, enter, exit_):
                check(point['bid'] > 0 and point['ask'] >= point['bid'], '両気配正常')
                if point['volume_known']:
                    n = point['volume_up'] + point['volume_down']
                    if n:
                        same(point['volume_signed_balance'], side * (point['volume_up'] - point['volume_down']) / n, ('代理票符号一回', symbol, point['raw_seq']))
                if point['peer_price_known']:
                    check(0 < point['peer_price_age_seconds'] <= 60, ('peer時計strict過去', symbol, point['raw_seq']))
            check(pub['volume_known'] and pub['volume_up'] + pub['volume_down'] >= 2, '出来高入口資格')
            check(pub['volume_signed_balance'] >= (.5 if symbol == 'TOPIX' else .25), '出来高閾値')
            for prefix in ('own', 'peer'):
                check(pub[prefix + '_price_known'] and pub[prefix + '_price_count'] >= 2 and pub[prefix + '_price_balance'] >= .25, '両市場入口資格')
            strong = all(pub[prefix + '_price_known'] and pub[prefix + '_price_count'] >= 2 and pub[prefix + '_price_balance'] >= .75 for prefix in ('own', 'peer'))
            same(parent['adverse_ticks'], int(strong), '当時票による固定FAK許容')
            ep = enter['ask'] if side == 1 else enter['bid']
            cap = pub['ask'] + int(strong) * tick if side == 1 else pub['bid'] - int(strong) * tick
            check(ep <= cap if side == 1 else ep >= cap, '保存新規は固定cap内')
            result = amount(side, q, mult, enter, exit_, round_fee(q, symbol))
            same(result['actual_net_yen'], parent['net'], '六例と勝ち四親のBBO純損益')
            same(exit_['parent_liquidation_yen'], parent['net'], '返済局所清算')
            same(enter['parent_liquidation_yen'], -(enter['ask'] - enter['bid']) * q * mult - round_fee(q, symbol), '新規直後横断＋料')
            same(parent['wide_arm'], Fraction(str(ep)) * q * mult * Fraction(125, 100000), '初fill名目WIDE線')
            same(parent['cash_stop'], Fraction(str(ep)) * q * mult * Fraction(75, 100000), '初fill名目現金停止線')
            if parent in losses:
                for key in MONEY_KEYS + ('actual_gross_yen', 'entry_mid', 'exit_mid', 'entry_spread', 'exit_spread'):
                    same(parent['amounts'][key], result[key], ('六例分解', symbol, parent['session'], key))
                same(parent['amounts']['direction_class'], '中値逆行', '六例は中値逆行')
                same(parent['amounts']['net_class'], '負け', '六例は負け親')
                same(parent['amounts']['friction_outweighed_nonnegative_mid'], False, '費用だけの負けではない')
                same(parent['support_updates'], 0, '六例更新0')
                same(parent['exit_reason'], '親純損失停止', '六例現金停止')
                check(parent['peak'] < parent['wide_arm'], '六例保護未起動')
                same(parent['best']['parent_liquidation_yen'], parent['peak'], '事後最良清算')
                source = parent['exit_source']
                same(exit_['normal_row'], source['normal_row'] + 1, '返済判断から次行')
                check(exit_['raw_seq'] > source['raw_seq'], '返済判断から原seq前進')
                check(source['parent_liquidation_yen'] <= -parent['cash_stop'], '判断時現金停止到達')
                for point_name in ('entry', 'best', 'worst_point', 'exit_source', 'exit_fill'):
                    point = parent[point_name]
                    liquidation = amount(side, q, mult, enter, point, round_fee(q, symbol))['actual_net_yen']
                    same(point['parent_liquidation_yen'], liquidation, ('保存点の独立清算', symbol, parent['session'], point_name))
                    same(point['support_line'], enter['support_line'], '更新0なので保存支持線固定')
                row = next(row for row in public['cases'][MAIN]['rows'] if row['symbol'] == symbol and row['session'] == parent['session'])
                same(parent['session_net'], row['net'], '場と親の損益を分離')
                losing_peaks.append(parent['peak'])
            else:
                check(parent['net'] > 0 and parent['peak'] >= parent['wide_arm'], '勝ち反証は実黒字かつ保護起動')
                same(parent['exit_reason'], '親純益保護', '勝ち反証保護退出')
            example_summary.append(dict(symbol=symbol, session=parent['session'], side=side, q=q,
                entry_price=ep, exit_price=exit_['bid'] if side == 1 else exit_['ask'],
                mid=float(result['mid_direction_yen']), crossing=float(result['crossing_disadvantage_yen']),
                fee=round_fee(q, symbol), net=parent['net'], peak=parent['peak'], winning=parent in wins))
    same(sum(peak > 0 for peak in losing_peaks), 3, '六例は途中黒字3')
    same(sum(peak <= 0 for peak in losing_peaks), 3, '六例は黒字なし3')
    # ----------------------------------------
    doc_sources = {}
    doc_rules = {
        'アルゴリズム調査/00113_現在の注文活動と再進行から波の中間に参加/損失の原因と未検証の改善.md':
            ['取引を減らして避けた損失と、判断精度が上がった効果を同一視しない', '入口の正答率ではない', '事後分類',
             '収支−136,752円／−167,760円', '支持線更新による退出を外した後の損益は未測定', '救済利益とは数えない', '数量版の成績は未測定'],
        'アルゴリズム調査/共通/知見台帳/入口.md': ['00113_反対活動後の再進行でも継続利益は未達', '独立の入口的中率ではない', '母集団・退出も異なる'],
        'アルゴリズム調査/共通/知見台帳/継続.md': ['00113_更新支持線による小往復の負担', 'TOP32親（12勝20負）・NK54親（11勝43負）', '更新OFFなら回復した利益ではない', '未検証'],
        'アルゴリズム調査/共通/知見台帳/出口.md': ['00113_小黒字と保護未起動及び入口失敗の区別', '57/94', '39/93', '事後MFEは取得可能な利確額ではなく'],
        'アルゴリズム調査/共通/知見台帳/売買の工夫.md': ['00113_方向変化と気配横断と実料の分解', '中値約定の再現ではない', '入口の正答率ではない', '追加2場は未測']}
    for relative, phrases in doc_rules.items():
        content = (ROOT / relative).read_bytes()
        text = content.decode('utf-8')
        for phrase in phrases:
            check(phrase in text, (relative, '留保', phrase))
        doc_sources[relative] = hashlib.sha256(content).hexdigest()
    same(before, source_fingerprints(), '経済17source監査前後不変更')
    return dict(全合格=True, 検査数=checks, 群検査=group_count, 独立恒等式人工=identity_pure, 初期線独立真偽表=support_pure,
        限定診断SHA256=EXPECTED_SHA, 限定診断実bytes=len(raw), 監査sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        金融結果への系譜=value['出典結果SHA256'], 支持比較=support_summary, 六負親と四勝親の独立分解=example_summary,
        経済17source_SHA256=before, 根原因MDと共通知見のsource_SHA256=doc_sources,
        限界=['全親/負親の保存合計と公開会計の整合を確認し、個々の全親を独立再集計していない。',
              '32/54群の当行BBOは未収録。sourceの両BBO述語と群の足算を検査し、各親の分類自体は未独立確認。',
              '六例の最大負親選択とbestの真の最大性は実台帳を読まず未独立確認。赤字上位三場との対応は公開会計で確認。',
              '価格時計/原seqは保存値の順序だけ。peer原seqを自己seqと大小比較せず、物理受信順を保証しない。',
              '中値損益は実約定の恒等分解で、中値約定・逆売買利益・改善手法の救済PLを意味しない。',
              '負親だけの86/96・169/187は入口正答率ではない。今後の勝率や未測追加二場の成果も示さない。'],
        読取=dict(限定診断原一読=1, 診断集計138KB=0, 大射影40MB=0, 原金融結果=0, 実台帳=0, 入力cache=0, 原板=0, API=0, 新金融=0),
        金融source変更=0, 共通変更=0, 公開変更=0)


def main() -> None:
    """
    機能: 限定監査を一回保存し、checker失敗ならFalseとsourceを保持する。
    引数: なし。
    返り値: None。
    """
    assert not PROOF.exists()
    try:
        result = run()
    except Exception as error:
        result = dict(全合格=False, 検査数=checks, 理由=str(error), traceback=traceback.format_exc(),
            原金融=0, 台帳=0, cache=0, API=0, 新金融=0)
        PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
    PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=checks, 証跡=str(PROOF), SHA256=hashlib.sha256(PROOF.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
