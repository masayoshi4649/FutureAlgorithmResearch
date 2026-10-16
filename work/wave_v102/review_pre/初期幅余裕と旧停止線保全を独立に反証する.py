"""102の追加判断をFractionと呼値格子の列挙で独立反証する。売買再生は行わない。"""

from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
F = Fraction


def digest(path: Path) -> str:
    """
    機能: 小さな仕様と数学コードの依存だけを指紋化する。
    引数: path (Path) は実在ファイル。
    返り値: str はSHA256。全参照原本の重複hashを行わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 数学例の注文ごとの料金を十進有理数から整数円に切り捨てる。
    引数: quantity (int)、symbol (str) はTOPIX又はNK225。
    返り値: int は一注文の手数料。新規複数注文の料金をまとめない。
    """
    assert quantity > 0 and symbol in ('TOPIX', 'NK225')
    return math.floor(quantity * (F('41.8') if symbol == 'TOPIX' else F(11)))


def terms(symbol: str) -> dict:
    """
    機能: 両商品の異なる呼値と倍率を持つ、保存始値率と整合する数学例を作る。
    引数: symbol (str) は商品。
    返り値: dict はFractionの建値・呼値・倍率・初期S・通常D・固定R0・費用。
    """
    base, tick, value = (F(4500), F(1, 2), F(1000)) if symbol == 'TOPIX' else (F(70000), F(10), F(10))
    width = max(2, math.ceil(base * F(1, 1000) / tick)) * tick
    trail = max(2, math.ceil(base * F(4, 1000) / tick)) * tick
    return dict(symbol=symbol, base=base, tick=tick, value=value, width=width, trail=trail,
                risk=width * value + 2 * fee(1, symbol), initial_fees=F(2 * fee(1, symbol)),
                proposed_fees=F(2 * fee(1, symbol) + fee(2, symbol)))


def net_at(price: Fraction, side: int, quantity: int, cash: Fraction, fees: Fraction,
           value: Fraction) -> Fraction:
    """
    機能: 指定価格で全保有玉を清算した数学上の現金netを求める。
    引数: price/cash/fees/value (Fraction)、side/quantity (int)。
    返り値: Fraction は費用後の全量損益。事後の戦略成績ではない。
    """
    return side * (quantity * price * value - cash) - fees


def scan_stop(data: dict, side: int, quantity: int, cash: Fraction, fees: Fraction,
              old: Fraction, peak: Fraction, active: bool) -> Fraction:
    """
    機能: 旧線・初期線・通常追尾・損失予算・費用床を満たす最小保護線を格子列挙する。
    引数: data (dict)、side/quantity (int)、cash/fees/old/peak (Fraction)、active (bool)。
    返り値: Fraction は合成した有効停止値。根の予算線やceil/floor合成関数へ委譲しない。
    """
    base, tick, width = data['base'], data['tick'], data['width']
    first_line = base - side * width
    trail_line = peak - side * data['trail']
    low, high = math.floor((base - 32 * width) / tick), math.ceil((base + 32 * width) / tick)
    indices = range(low, high + 1) if side == 1 else range(high, low - 1, -1)
    for index in indices:
        price = index * tick
        if any(side * (price - line) < 0 for line in (old, first_line, trail_line)):
            continue
        current = net_at(price, side, quantity, cash, fees, data['value'])
        if current < -data['risk']:
            continue
        # ----------------------------------------
        # 費用床の全価格保護丸め＋1tickは、格子上で全Q×倍率×1tick以上のnetという制約へ等価に変換する。
        if active and current < quantity * data['value'] * tick:
            continue
        return price
    raise AssertionError('数学例の有限格子内に保護線がありません')


def proposal(data: dict, side: int, old_offset: Fraction, quote_offset: Fraction,
             peak_offset: Fraction, active: bool) -> dict:
    """
    機能: 初回1枚へ1枚を提案する時のBとT1の可否を独立計算する。
    引数: data (dict)、side (int)、old_offset/quote_offset/peak_offset (Fraction)、active (bool)。
    返り値: dict は旧線net・合成線・清算余裕・各B・T1。
    支持・源更新・TTL等を仮定した数学部分であり、実新規を認定しない。
    """
    base, width = data['base'], data['width']
    old = base + side * old_offset
    quote = base + side * quote_offset
    peak = base + side * peak_offset
    addition = quote + side * data['tick']
    cash = (base + addition) * data['value']
    stop = scan_stop(data, side, 2, cash, data['proposed_fees'], old, peak, active)
    prior_net = net_at(old, side, 2, cash, data['proposed_fees'], data['value'])
    distance = side * (quote - stop)
    current_net = net_at(quote, side, 1, base * data['value'], data['initial_fees'], data['value'])
    proposed_net = net_at(quote, side, 2, cash, data['proposed_fees'], data['value'])
    assert current_net >= 0 and proposed_net >= 0
    assert side * (stop - old) >= 0
    allowed = prior_net >= -data['risk'] and stop == old
    return dict(old=old, quote=quote, addition=addition, peak=peak, cash=cash, stop=stop,
                current_net=current_net, proposed_net=proposed_net, old_line_net=prior_net,
                old_line_budget_allowed=prior_net >= -data['risk'], preserve_allowed=allowed,
                distance=distance, distance_initial_widths=distance / width,
                B={name: distance >= multiple * width for name, multiple in
                   (('B05', F(1, 2)), ('B1', F(1)), ('B2', F(2)))})


def reflect(value: Fraction, base: Fraction) -> Fraction:
    """
    機能: 買い例の価格を同じ建値中心で売りへ反射する。
    引数: value/base (Fraction) は価格と中心。
    返り値: Fraction は反射した価格。料金と金額損益は変えない。
    """
    return 2 * base - value


def cases() -> list[dict]:
    """
    機能: 予算・費用床・通常線更新・戻り後余裕・実fill悪化を両商品買売で反証する。
    引数: なし。
    返り値: list[dict] は20方向例の独立数理結果。
    """
    answer = []
    for symbol in ('TOPIX', 'NK225'):
        data = terms(symbol)
        width = data['width']
        definitions = (
            ('現在利益でも旧停止値で予算超過', -width, 3 * width, 3 * width, False),
            ('予算内でもactive費用床が旧線を越す', 4 * width, 8 * width, 8 * width, True),
            ('当該行の通常線更新後なら保全可能', 6 * width, 10 * width, 10 * width, True),
            ('保持したpeak後の回復でB1等号', 3 * width, 4 * width, 7 * width, True),
            ('判断合格後の次fill悪化では実線が寄る', 3 * width, 12 * width, 7 * width, True))
        for label, old_offset, quote_offset, peak_offset, active in definitions:
            paired = []
            for side in (1, -1):
                actual = proposal(data, side, old_offset, quote_offset, peak_offset, active)
                if label == definitions[0][0]:
                    assert not actual['old_line_budget_allowed'] and not actual['preserve_allowed']
                    assert actual['B']['B1'], 'Bだけ通過してもT1は別に拒否する'
                elif label == definitions[1][0]:
                    assert actual['old_line_budget_allowed'] and not actual['preserve_allowed']
                    without_floor = proposal(data, side, old_offset, quote_offset, peak_offset, False)
                    assert without_floor['preserve_allowed'], 'active床の無視が誤追加を生む'
                elif label == definitions[2][0]:
                    assert actual['preserve_allowed'] and all(actual['B'].values())
                    before = data['base'] - side * width
                    normal_line = scan_stop(data, side, 1, data['base'] * data['value'], data['initial_fees'],
                                            before, actual['quote'], True)
                    assert normal_line == actual['old']
                    assert side * (actual['stop'] - before) > 0, '前行線との誤比較なら正常追尾まで拒否する'
                elif label == definitions[3][0]:
                    assert actual['preserve_allowed'] and actual['distance'] == width
                    assert actual['B'] == {'B05': True, 'B1': True, 'B2': False}
                else:
                    legal_decision = proposal(data, side, 3 * width, 4 * width, 7 * width, True)
                    assert legal_decision['preserve_allowed'] and legal_decision['B']['B1']
                    assert not actual['preserve_allowed'] and side * (actual['stop'] - legal_decision['old']) > 0
                paired.append(actual)
                answer.append(dict(例=label, 商品=symbol, 方向=side, 初期S=width, 通常D=data['trail'],
                                   呼値=data['tick'], 初回R0=data['risk'], 提案全費用=data['proposed_fees'], **actual))
            assert paired[0]['distance'] == paired[1]['distance']
            assert paired[0]['old_line_net'] == paired[1]['old_line_net']
            assert paired[1]['stop'] == reflect(paired[0]['stop'], data['base'])
    return answer


def boundaries() -> dict:
    """
    機能: 非整数呼値の半Sと等号、最低Sの旧幅同値、費用がR0を超える境界を検査する。
    引数: なし。
    返り値: dict は小さな境界事実。既検証の費用問題を新発見とは呼ばない。
    """
    data = terms('TOPIX')
    assert data['width'] == F('4.5') and data['width'] / 2 == F('2.25')
    assert not F(2) >= data['width'] / 2 and F('2.5') >= data['width'] / 2
    exact = []
    for multiple in (F(1, 2), F(1), F(2)):
        threshold = multiple * data['width']
        for offset in (-F(1, 4), F(0), F(1, 4)):
            assert ((threshold + offset) >= threshold) == (offset >= 0)
            exact.append(dict(B=multiple, 距離=threshold + offset, 必要幅=threshold, 可否=offset >= 0))
    minimum = {symbol: dict(最低S=2 * terms(symbol)['tick'],
                            半Sが旧1tick=True, Sが旧2tick=True) for symbol in ('TOPIX', 'NK225')}
    for symbol in minimum:
        assert minimum[symbol]['最低S'] / 2 == terms(symbol)['tick']
    # ----------------------------------------
    # NK最低S20ならR0=222円、16枚の実累計料＋全量返済料352円。負の残予算をclampしてはいけない。
    small = terms('NK225')
    small['width'], small['trail'], small['risk'] = F(20), F(80), F(222)
    cash, fees = 16 * small['base'] * small['value'], F(352)
    old = small['base'] - small['width']
    line = scan_stop(small, 1, 16, cash, fees, old, small['base'], False)
    assert line > small['base']
    assert net_at(small['base'], 1, 16, cash, fees, small['value']) < -small['risk']
    return dict(数学等号及び両側=exact, 半Sの数学幅=data['width'] / 2,
                半S2_25に距離2は拒否=True, 距離2_5は受理=True,
                最低幅の旧幅同値=minimum,
                既検証費用継承=dict(R0=222, 全費用=352, 必要予算線=line,
                                    注記='線計算の数理だけ。全追加が支持資格を満たす実経路とは主張しない。'))


def late_participation() -> list[dict]:
    """
    機能: 初回Q1から新peakにQ1追加する単純経路のT1が遅くなる必要閾値を導く。
    引数: なし。
    返り値: list[dict] は両商品・買売・active有無の下限と呼値境界。
    正常追尾線が支配する単純経路内だけの数学で、実活動数又は支持の十分条件ではない。
    """
    answer = []
    for symbol in ('TOPIX', 'NK225'):
        data = terms(symbol)
        for active in (False, True):
            bound = 2 * data['trail'] - data['width'] + data['tick'] \
                + (data['proposed_fees'] - data['initial_fees']) / data['value']
            if active:
                bound = max(bound, 2 * data['trail'] + 3 * data['tick'] + data['proposed_fees'] / data['value'])
            on_grid = math.ceil(bound / data['tick']) * data['tick']
            for side in (1, -1):
                evaluated = []
                for distance in (on_grid - data['tick'], on_grid):
                    actual = proposal(data, side, distance - data['trail'], distance, distance, active)
                    assert actual['preserve_allowed'] == (distance == on_grid)
                    evaluated.append(dict(順行幅=distance, T1可否=actual['preserve_allowed']))
                answer.append(dict(商品=symbol, 方向=side, active費用床=active, 初期S=data['width'], 通常D=data['trail'],
                                   数学下限=bound, 呼値上の通過境界=on_grid, S比=on_grid / data['width'],
                                   前一呼値と境界=evaluated,
                                   限定='現在値が新peak、1tick spread、Q1からQ2、通常D線支配の場合。未知peer、L1、時限、源更新等は別に必要。'))
    return answer


def plain(value: object) -> object:
    """
    機能: Fractionを有限JSON数値へ変換する。
    引数: value (object) は有理数又は辞書・配列等。
    返り値: object はJSON互換値。範囲検査済みの数学例だけを対象とする。
    """
    if isinstance(value, F):
        return int(value) if value.denominator == 1 else float(value)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


# ----------------------------------------


def main() -> None:
    """
    機能: 結果前仕様と独立Fraction反証を小さな根拠へ固定する。
    引数: なし。
    返り値: None。新102エンジン、正式損益、APIを実行せず証跡だけを保存する。
    """
    paths = [Path(__file__), WORK / 'catalog.py', WORK / '結果前の設計草案.json',
             WORK / '結果前の設計案.json', WORK / '結果前の数理明確化.json', WORK / '実装前の仕様明確化.json',
             WORK / 'engine_preflight/math.py', WORK / 'engine_preflight/停止線据置と初期幅余裕の結果前数理.json']
    before = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    spec = importlib.util.spec_from_file_location('102定義だけの独立仕様読取', WORK / 'catalog.py')
    definition = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(definition)
    configs = definition.catalog()
    assert len(configs) == 20 and definition.PRIMARY == 'B1_T1_Q1_X1'
    new = [config for config in configs if config['id'].startswith('B')]
    controls = [config for config in configs if not config['id'].startswith('B')]
    assert len(new) == 12 and len(controls) == 8
    assert all(config['trend_initial_quantity'] == 1 and config['trend_growth_cushion_basis'] == 'initial_width'
               for config in new)
    assert {(config['trend_growth_cushion_initial_multiple'], config['trend_growth_preserve_stop'],
             bool(config['trend_hold_seconds'])) for config in new} == {
                 (multiple, preserve, deadline) for multiple in (.5, 1., 2.)
                 for preserve in (False, True) for deadline in (False, True)}
    expected = {config['id']: config for config in definition.previous.catalog()}
    for config in controls:
        value = dict(config)
        prior = value.pop('previous_growth_id')
        assert value == expected[prior]
    examples, limits, participation = cases(), boundaries(), late_participation()
    assert len(examples) == 20 and len(participation) == 8
    after = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    assert before == after
    coverage = [
        'T1のLは通常peak・追尾・既存active床更新後の現在線。前行との比較は別条件。',
        'BとT1の拒否だけでは保有/費用/R0/anchor/phase/初回期限を変えず、後の正常進行で再判定する。',
        'T1合格後の成行予約は次正常自己quoteで実約定し、後のB/T1/L1/peer悪化のみで取り消さない。既存返済/期限/場末取消を優先。',
        '実追加fill後は実E/Q/Fから全線を更新する。T1判断時据置と実fill後の据置保証は別。',
        '最低2tickのSと強いD追尾ではB同値又は同時成立がある。活動数縮小と確度改善を分ける。',
        '旧8経済nullは496口座。旧101全20/1240監査完了の根拠と今回持込対照の検査範囲を混同しない。',
        '人工bodyの共有input不変、未知peer基準だけ復帰、同fillrow禁止、予約競合、prefix/未来改変と局所gate19のscopeは実装後に検査する。']
    proof = dict(全合格=True, 結果前=True, 条件数=20, 新条件数=12, 旧対照数=8,
                 理論主=definition.PRIMARY, 独立格子及びFraction方向例数=len(examples), 数学例=examples,
                 初期幅境界=limits, 単純経路で追加が遅くなる必要閾値=participation,
                 仕様反証及び局所実装の必要境界=coverage,
                 結論='据置は全線の追加後制約が現在線以下の時だけ可能。金額R0内でも負けの反復は残り得る。T1は大きな先行利益を待つ選択になり、低活動又はG0同値を成功へ読み替えない。',
                 実装動作の認定=False, 金融成功の認定=False, 正式102新損益閲覧=0, 新102売買実行=0,
                 旧101及び過去成果変更=0, 現在API取得=0, 実注文=0, SHA256=after)
    target = HERE / '初期幅余裕と旧停止線保全の独立仕様反証.json'
    assert not target.exists()
    target.write_text(json.dumps(plain(proof), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 方向例数=20, 必要閾値数=8, SHA256=digest(target),
                         正式102新損益閲覧=0, 新102売買実行=0), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
