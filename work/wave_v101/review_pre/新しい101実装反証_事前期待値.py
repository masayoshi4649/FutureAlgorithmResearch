"""既存の純数理証跡を変更せず、101実装に必要な状態反証の期待値を固定する。"""

from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]


def digest(path: Path) -> str:
    """
    機能: 既存純数理及び固定20条件を内容指紋へ結び付ける。
    引数: path(Path)。
    返り値: strはSHA256。既存ファイルを変更しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(value: object) -> Fraction:
    """
    機能: 明示した人工金額を十進有理数へ変換する。
    引数: value(object)はFraction又は数値。
    返り値: Fraction。市場価格又は新正式損益を参照しない。
    """
    return value if isinstance(value, Fraction) else Fraction(str(value))


def cash(cohorts: list[tuple[int, float]], quote: float, side: int,
         multiplier: float, unit: float) -> tuple[Fraction, int, int]:
    """
    機能: 実fillだけの集合から現在清算netと実累計新規/全量返済費用を独立算出する。
    引数: cohorts(list[tuple[int,float]])、quote/multiplier/unit(float)、side(int:1/-1)。
    返り値: tuple[Fraction,int,int]はnet、累計新規費用、全量返済費用。
    """
    quantity = sum(item[0] for item in cohorts)
    entry_cost = sum(math.floor(q * number(unit)) for q, price in cohorts)
    exit_cost = math.floor(quantity * number(unit))
    gross = sum(side * q * (number(quote) - number(price)) * number(multiplier)
                for q, price in cohorts)
    return gross - entry_cost - exit_cost, entry_cost, exit_cost


def enumerate_stop(cohorts: list[tuple[int, float]], risk: int, side: int,
                   multiplier: float, unit: float, tick: float) -> Fraction:
    """
    機能: 有効呼値を列挙し全玉netが−R0以上となる最も緩い停止価格を別式で求める。
    引数: cohorts(list)、risk/side(int)、multiplier/unit/tick(float)。
    返り値: Fraction。買ceil/売floorの公式へ直接委譲しない少数人工oracle。
    """
    prices = [number(price) for q, price in cohorts]
    low = math.floor((min(prices) - 30) / number(tick))
    high = math.ceil((max(prices) + 30) / number(tick))
    allowed = [index * number(tick) for index in range(low, high + 1)
        if cash(cohorts, index * number(tick), side, multiplier, unit)[0] >= -risk]
    assert allowed
    return min(allowed) if side == 1 else max(allowed)


def main() -> None:
    """
    機能: 新実装の私有人工に必要な優先順と数値期待値を保存する。
    引数: なし。正式101金融素材及びシミュレータを一切開かない。
    返り値: None。新しい101実装反証で始まる自担当JSONだけを作成する。
    """
    plan = BASE / '結果前の設計案.json'
    pure = HERE / '20条件の予算固定増玉と費用及び予約競合の損益前独立反証.json'
    pure_code = HERE / '予算と費用の純数理を反証する.py'
    assert digest(plan) == '5db0b6b44360855ede7d439b740845d68bd4d47ba970914b0fae83dfb65de6cc'
    assert digest(pure) == '5368660920eaf0e7bf74c64a983d5eae955e1015ff39055f4bb091dee0ac4ab6'
    assert digest(pure_code) == '9f3ddfd7d08a64d01553dc184ebf1ab7dfd6d2d3a74148a84394c420060be260'
    spec = importlib.util.spec_from_file_location('101実装反証の固定定義だけ', BASE / 'catalog.py')
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    configs = catalog.catalog()
    assert len(configs) == 20 and catalog.PRIMARY == 'G1_Q1_X1'
    assert all(config['trend_initial_quantity'] in (None, 1, 2, 4) for config in configs)
    cases = []

    # ----------------------------------------
    # 理論線では予算を守れても悪い実約定で損失保証にはならないことを別oracleで確認する。
    for side in (-1, 1):
        center = 8000.
        reflect = lambda price: price if side == 1 else center - price
        cohorts = [(1, reflect(4000.)), (1, reflect(4001.5))]
        liquidation = reflect(4001.)
        risk = 4000 + 82
        net, opening_cost, closing_cost = cash(cohorts, liquidation, side, 1000., 41.8)
        assert net == 335 and opening_cost == 82 and closing_cost == 83
        stop = enumerate_stop(cohorts, risk, side, 1000., 41.8, .5)
        assert stop == reflect(3999.)
        actual = [(1, reflect(4000.)), (1, reflect(4011.5))]
        actual_net = cash(actual, liquidation, side, 1000., 41.8)[0]
        actual_stop = enumerate_stop(actual, risk, side, 1000., 41.8, .5)
        assert actual_net == -9665 and actual_stop == reflect(4004.)
        assert side * (liquidation - actual_stop) < 0
        cases.append(dict(種類='合法判断から不利追加fill後の同row全玉stop', 方向=side,
            初回R0=risk, 判断想定net=float(net), 判断予算線=float(stop),
            実fill後net=float(actual_net), 実fill後予算線=float(actual_stop),
            即時返済判断=True, 実返済は次正常行=True, 追加未約定へ巻き戻し禁止=True))

    # ----------------------------------------
    # 固定小数量だけで下方偏差は改善するが黒字頻度の根拠にはならない。
    scale_case = {}
    for q in (1, 8):
        values = [float(cash([(q, 4000.)], close, 1, 1000., 41.8)[0]) for close in (3996., 4009.)]
        scale_case[str(q)] = dict(各場純額=values, 黒字場=1, 赤字場=1, 活動場=2,
            共通4万円単位下方偏差=math.sqrt(sum(min(value / 40000., 0.) ** 2 for value in values) / 2))
    assert scale_case['1']['共通4万円単位下方偏差'] < scale_case['8']['共通4万円単位下方偏差']
    assert scale_case['1']['黒字場'] == scale_case['8']['黒字場']

    # ----------------------------------------
    # 実装後に量だけ増えた仮の観測を、実際の保有金額又は既知の利益へすり替えない。
    expectations = [
        dict(ID='E01', 検査='数量と旧全量null', 正例='Q1/Q2/Q4は両商品で絶対枚数。Noneだけ8/16。',
            負例='NKへ初回1を2倍換算、又は未fill追加をheldへ算入すると失敗。'),
        dict(ID='E02', 検査='実保有と追加仮状態を隔離', 正例='追加判断行のE/Q/F/stopは実fill済みcohortだけ。想定線はgate診断のみ。',
            負例='pending価格又は予定Qを保有stop/時価/cohort費用へ先取りすると失敗。'),
        dict(ID='E03', 検査='全玉net及び全線cushion統合', 正例='買いは売bid、売りは買askへ全玉を清算し費用非負と統合stop余裕を同時確認。',
            負例='既存玉のみ黒字、予算線のみ余裕、又は将来有効の費用床除外で誤追加。'),
        dict(ID='E04', 検査='固定R0と非緩和', 正例='R0と初回期限を固定し、各実fill後も全玉有効線はside向きへ後退しない。',
            負例='R0をQ倍へ増額、費用がR0超のときclamp0、weighted entry更新で旧stopを後退。'),
        dict(ID='E05', 検査='X3の実grossとactive', 正例='現在清算quoteの実E/Qからq0×2Sの閾値、active一度成立なら保持。',
            負例='新追加へ過去peakを掛けた偽gross、仮約定で起動、又は追加後gross減少でactive解除。'),
        dict(ID='E06', 検査='未知peer基準復帰', 正例='実fillでpeer未知ならanchor無効、後続正常pair初回は基準のみ、後続更新/進行が必要。',
            負例='判断行の旧peerへ無言で復帰、未来peerをfillへ遡及、復帰baseline同行に追加。'),
        dict(ID='E07', 検査='同行再追加と源更新', 正例='初回又は追加fill同行は再追加不可。各自index/seq/clock及び共通phaseの旧C1を保持。',
            負例='同clockseqだけ新clockの証拠にする、自己だけ更新、又は同fillrowに倍増予約を連発。'),
        dict(ID='E08', 検査='追加pendingと返済/cut/期限',
            正例='追加の新判断はentry_cut300前、追加pendingはforce60又はX1初回期限又はprior返済pendingで先に取消。初回marketpendingは旧entry_cut300を保持。',
            負例='新判断停止と既予約取消の時刻混同、古い返済数量へ追加を混ぜる、30分期限延長、又はforce後追加fill。'),
        dict(ID='E09', 検査='追加fill時の新stop及び資格悪化', 正例='旧nextnormal自己qokで実fillを先記録し、新current stopはその後全量返済判断。',
            負例='悪いfillや予約後のL1/peer/reset悪化を理由に実予約を未約定へ巻戻す。'),
        dict(ID='E10', 検査='cohort/親/費用の整数照合', 正例='全量返済費用の最大剰余法。同率は実fill作成順。親とcohortの合計及びGP/GLを両方評価。',
            負例='全新規費用を一注文へ置換、剰余を損益で配分、又は親黒字で追加cohort赤字を隠す。'),
        dict(ID='E11', 検査='prefixと自己/peer未来', 正例='実追加前/後/返済pendingのprefix、未来price/LP支持/peer変更で過去の経済と状態不変。',
            負例='将来のfill、終端返済価格、未公表peer又は事後MFEを追加判断へ使用。'),
    ]
    references = [BASE / 'catalog.py', plan, pure, pure_code, ROOT / 'work/wave_v100/事前固定.json', Path(__file__)]
    result = dict(全合格=True, 種類='101実装前の状態反証期待値', 実装認定=False, 条件数=20,
        主=catalog.PRIMARY, 旧全量対照=catalog.CONTROL, 同初回固定対照=catalog.SMALL_CONTROL,
        既存pure及びコード編集=0, 非保証の買売正負=cases, 小数量だけの見掛け安定反例=scale_case,
        必要な本体境界=expectations,
        採用評価の反証='G0小QのRMS低下は資金配分の縮小であって入口の確度改善ではない。'
              'G1/G2を同QのG0と比較し、赤字額・黒字頻度・活動・最大利益日除外・親/cohort金額比を'
              '全体で確認する。参照順位で小Qが上でも黒字頻度を改善しないことを隠さず、採用達成としない。',
        時間及び因果の範囲='CurrentPriceTime由来の代理公表順内。真受信時計と両市場共通受信順は未観測。',
        未検査=['実本体の局所状態・旧124正式経済null・人工全20保存・実接頭未来は本体到着後。',
            '収益性・毎場安定・未見データ・実ミニ/マイクロ気配・実注文は未認定。'],
        SHA256={path.relative_to(ROOT).as_posix(): digest(path) for path in references},
        正式101損益閲覧=0, 正式101売買実行=0, API取得=0, 実注文=0)
    target = HERE / '新しい101実装反証_事前期待値.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('101の既存純数理を保持し、本体検査の11境界と数量縮小反例を固定。新PL0。', flush=True)


if __name__ == '__main__':
    main()
