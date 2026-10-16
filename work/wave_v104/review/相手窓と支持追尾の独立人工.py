"""正式素材を読まず、相手窓と停止線の数値定義を独立に反証する。"""

from decimal import Decimal, ROUND_FLOOR
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
POLICY = dict(max_public_gap_seconds=15., baseline_extra_age_seconds=15.,
              spread_max_ticks=2., spread_increment_ticks=1.)


def load(name: str, path: Path) -> object:
    """
    機能: 新104の相手窓部品を読取専用で接続する。
    引数: name(str)は独立名、path(Path)は小さいソース。
    返り値: objectはモジュール。原本、保存cache、金融をロードしない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def sha(path: Path) -> str:
    """
    機能: この人工が読んだ小さい直接ソースの指紋を作る。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。巨大台帳や原本は対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------


def publications(raw: dict) -> list[int]:
    """
    機能: 時計の最高値を越えた最初原行を独立した逐次リストで選ぶ。
    引数: raw(dict)は人工原行。
    返り値: list[int]は新最大最初の原行。無効な先頭も後半へ交換しない。
    """
    rows, high = [], float('-inf')
    for row, value in enumerate(raw['price_time_s']):
        if np.isfinite(value) and value > high:
            rows.append(row)
            high = value
    return rows


def window_oracle(raw: dict, tick: float, public: list[int], window: int, threshold: int) -> list[dict]:
    """
    機能: prefixや探索関数を使わず、各原行を歩いて相手窓の資格を判定する。
    引数: raw(dict)、tick(float)、public(list[int])、window/threshold(int)。
    返り値: list[dict]は基準原行・不明理由・方向。未来原行は参照しない。
    """
    values = []
    for kindex, current in enumerate(public):
        clock = raw['price_time_s'][current]
        past = [index for index in range(kindex) if raw['price_time_s'][public[index]] <= clock-window]
        index = past[-1] if past else -1
        reason = 0
        if index < 0:
            reason |= 1
        if not (raw['qualified'][current] and raw['bbo_valid'][current]):
            reason |= 2
        a = public[index] if index >= 0 else -1
        db, da, ambiguous = np.nan, np.nan, False
        if a >= 0:
            if not (raw['qualified'][a] and raw['bbo_valid'][a]):
                reason |= 4
            if clock-raw['price_time_s'][a] > window+15:
                reason |= 8
            for r in range(a, current+1):
                bad = not raw['bbo_valid'][r] or not np.isfinite(raw['price_time_s'][r]) or raw['price_reset_reason'][r] != 0
                if r > 0:
                    bad |= raw['raw_seq'][r] != raw['raw_seq'][r-1]+1
                    bad |= raw['price_time_s'][r] < raw['price_time_s'][r-1]
                if bad:
                    reason |= 16
            for p in range(index+1, kindex+1):
                if raw['price_time_s'][public[p]]-raw['price_time_s'][public[p-1]] > 15:
                    reason |= 32
            db = (raw['bid'][current]-raw['bid'][a])/tick
            da = (raw['ask'][current]-raw['ask'][a])/tick
            spread_a = (raw['ask'][a]-raw['bid'][a])/tick
            spread_k = (raw['ask'][current]-raw['bid'][current])/tick
            ambiguous = (db > 0 and da < 0) or (db < 0 and da > 0) or spread_k > max(2, spread_a+1)
        state = 3
        if reason == 0:
            if ambiguous:
                state = 2
            elif db >= threshold and da >= threshold:
                state = 1
            elif db <= -threshold and da <= -threshold:
                state = -1
            else:
                state = 0
        values.append(dict(reference_row=a, reason=reason, direction=state))
    return values


def fixture(tick: float, offset: float) -> dict:
    """
    機能: 同一時計を含む小さい正常人工原行を作る。
    引数: tick/offset(float)は商品呼値と基準価格。
    返り値: dictは15人工原行。現市場データは使わない。
    """
    time = np.array([0., 3., 6., 10., 10., 11., 15., 20., 21., 22., 30., 40., 41., 55., 56.])
    bid = offset+tick*np.array([0, 1, 2, 3, 4, 4, 5, 6, 6, 7, 8, 9, 10, 11, 12])
    return dict(raw_seq=np.arange(100, 100+len(time), dtype=np.int64), price_time_s=time,
        bid=bid, ask=bid+tick, bbo_valid=np.ones(len(time), bool), qualified=np.ones(len(time), bool),
        price_reset_reason=np.zeros(len(time), np.uint16))


def variants(tick: float, offset: float) -> list[tuple[str, dict]]:
    """
    機能: 欠測・時計・同時計・量だけの不明を混ぜた独立反例を作る。
    引数: tick/offset(float)は人工商品の経済値。
    返り値: list[tuple[str,dict]]は固定12反例。結果から条件を探さない。
    """
    result = []
    for name in ('正常', '同時計の隠れ不正', '時計逆転', '時計欠測', 'seq断裂', '価格reset',
                 '量だけの中間資格欠測', '無効最初と正常同時計後半', '公表間隔超過', '片気配だけ進行',
                 '逆符号でspread正常', '同方向だがspread拡大'):
        raw = fixture(tick, offset)
        if name == '同時計の隠れ不正':
            raw['bbo_valid'][4] = False
            raw['bid'][4] = np.nan
        elif name == '時計逆転':
            raw['price_time_s'][4] = 9.
        elif name == '時計欠測':
            raw['price_time_s'][4] = np.nan
        elif name == 'seq断裂':
            raw['raw_seq'][4:] += 1
        elif name == '価格reset':
            raw['price_reset_reason'][4] = 8
        elif name == '量だけの中間資格欠測':
            raw['qualified'][4] = False
        elif name == '無効最初と正常同時計後半':
            raw['qualified'][3] = False
            raw['bbo_valid'][3] = False
        elif name == '公表間隔超過':
            raw['price_time_s'][11:] += 10.
        elif name == '片気配だけ進行':
            raw['bid'][:] = offset
            raw['ask'][:] = offset+tick
            raw['ask'][7:] += tick
        elif name == '逆符号でspread正常':
            raw['bid'][:] = offset
            raw['ask'][:] = offset+5*tick
            raw['bid'][7:] += tick
            raw['ask'][7:] -= tick
        elif name == '同方向だがspread拡大':
            raw['bid'][:] = offset
            raw['ask'][:] = offset+tick
            raw['bid'][7:] += tick
            raw['ask'][7:] += 4*tick
        result.append((name, raw))
    return result


# ----------------------------------------


def stop_math() -> dict:
    """
    機能: 支持線・初期保険・費用床を有理数で検算し、約定悪化と区別する。
    引数: なし。
    返り値: dictは両商品・全許可枚数・買売・5幅の境界数と損失反例。
    """
    checks, examples = 0, []
    for symbol, tick, multiplier, rate, cap, base in (
            ('TOPIX', Fraction(1, 2), 1000, Decimal('41.8'), 10, Fraction(4000)),
            ('NK225', Fraction(10), 10, Decimal('11'), 20, Fraction(60000))):
        initial = Fraction(base, 1000)
        for q in range(1, cap+1):
            fee = int((rate*q).to_integral_value(rounding=ROUND_FLOOR))
            need = Fraction(2*fee, q*multiplier)
            fee_ticks = -(-need//tick)
            width = fee_ticks*tick
            assert width >= need and width-tick < need
            for side in (1, -1):
                for k in (1, 2, 4):
                    for distance in (-5*tick, 0*tick, 3*tick, 100*tick):
                        entry = base+side*distance
                        support_line = base-side*k*tick
                        insurance = entry-side*initial
                        stop = max(support_line, insurance) if side == 1 else min(support_line, insurance)
                        signed = side*(entry-stop)
                        assert signed == min(initial, distance+k*tick)
                        assert signed <= initial
                        checks += 1
                for k in (2, 4):
                    entry = base
                    best = entry+side*(width+k*tick)
                    floor = entry+side*width
                    trail = best-side*k*tick
                    assert floor == trail and side*(best-floor) == k*tick
                    assert side*(floor-entry)*q*multiplier-2*fee >= 0
                    one_bad = floor-side*(width+tick)
                    net = side*(one_bad-entry)*q*multiplier-2*fee
                    assert net < 0
                    checks += 1
                    if q == 1 and side == 1 and k == 2:
                        examples.append(dict(商品=symbol, 枚数=q, 利益発動価格=float(best), 費用床=float(floor),
                            次quoteの返済価格=float(one_bad), 手数料後収支=float(net), 説明='費用床で予約しても次正常quoteでは赤字になる。'))
    return dict(独立有理数検査数=checks, 費用床の非保証反例=examples,
        解釈='signed停止線距離は負にもなる。S以内なのは初期停止線までの名目距離で、次quoteまでの実損失上限ではない。')


def main() -> None:
    """
    機能: 24人工系列の全窓・反転・strictpastと固定停止線数理を独立検査する。
    引数: なし。
    返り値: None。reviewへ小JSONを保存する。正式金融、原本、cache、APIは使わない。
    """
    sources = [ROOT/'peer/core.py', ROOT/'peer/prices.py', ROOT/'catalog.py', ROOT/'数値設計案.json', Path(__file__)]
    before = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    core, prices = load('104独立相手原行', ROOT/'peer/core.py'), load('104独立相手窓', ROOT/'peer/prices.py')
    window_checks, publication_checks, selection_checks, reflection_checks = 0, 0, 0, 0
    cases = []
    for symbol, tick, offset in (('TOPIX', .5, 4000.), ('NK225', 10., 60000.)):
        for name, raw in variants(tick, offset):
            rows = publications(raw)
            actual_public = core.publications(raw)
            np.testing.assert_array_equal(actual_public['rows'], rows)
            publication_checks += 1
            actual = prices.build(raw, dict(tick=tick), actual_public, POLICY)
            for window in (3, 10, 30):
                for threshold in ((1, 2) if window == 10 else (1,)):
                    expected = window_oracle(raw, tick, rows, window, threshold)
                    value = actual['windows'][str(window)]
                    np.testing.assert_array_equal(value['reference_raw_row'], [x['reference_row'] for x in expected])
                    np.testing.assert_array_equal(value['unknown_reason'], [x['reason'] for x in expected])
                    np.testing.assert_array_equal(value['direction_t'+str(threshold)], [x['direction'] for x in expected])
                    window_checks += len(rows)
            # 同値時計は使わず、先頭不正を後半へ交換しない。
            own_times = np.r_[raw['price_time_s'], [-1., 10., 10.001, 71., 71.001, np.nan]]
            own = dict(price_time_s=own_times)
            selected = core.peer_rows(own, raw, actual_public)
            for i, stamp in enumerate(own_times):
                past = [r for r in rows if np.isfinite(stamp) and raw['price_time_s'][r] < stamp]
                reference = past[-1] if past else -1
                age = stamp-raw['price_time_s'][reference] if reference >= 0 else np.nan
                assert selected['rows'][i] == reference
                assert selected['fresh'][i] == (reference >= 0 and 0 < age <= 15)
                selection_checks += 1
            reflected = dict(raw, bid=2*offset-raw['ask'], ask=2*offset-raw['bid'])
            reverse = prices.build(reflected, dict(tick=tick), actual_public, POLICY)
            for window in (3, 10, 30):
                for threshold in ((1, 2) if window == 10 else (1,)):
                    original = actual['windows'][str(window)]['direction_t'+str(threshold)]
                    mirrored = reverse['windows'][str(window)]['direction_t'+str(threshold)]
                    expectation = np.where(np.abs(original) == 1, -original, original)
                    np.testing.assert_array_equal(mirrored, expectation)
                    reflection_checks += len(rows)
            cases.append(dict(商品=symbol, 人工条件=name, 原行数=len(raw['raw_seq']), 公表原行数=len(rows)))
    mathematics = stop_math()
    after = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    assert before == after, '人工の途中に検査対象sourceが変わりました。'
    proof = dict(全合格=True, scope='結果前の相手価格窓と固定停止線の独立人工。entry/state/金融本体全体の合格は意味しない。',
        検査件数=dict(人工系列=len(cases), 公表系列=publication_checks, 窓の独立原行値=window_checks,
            strictpast値=selection_checks, 買売反転値=reflection_checks, 停止線独立有理数=mathematics['独立有理数検査数']),
        SHA256=before, 人工条件=cases, 数理=mathematics,
        限界=['約定と取消の真の内訳、受信順、潜在注文は原入力から同定できない。',
            '窓Wの基準年齢はWからW+15秒、現在相手ageは最大15秒。厳密直近W秒の測定ではない。',
            '数量の中間欠測を価格反対としない。既知中立と不明は分離する。',
            '停止線を正しく守っても、次quoteの約定悪化、spreadと手数料は利益を消す。'],
        実行=dict(正式104金融=0, 原本読取=0, 旧巨大台帳読取=0, 保存活動cache読取=0, API=0, 実注文=0))
    target = HERE/'相手窓と支持追尾の独立人工.json'
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=proof['検査件数'], 証跡=str(target), SHA256=sha(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()
