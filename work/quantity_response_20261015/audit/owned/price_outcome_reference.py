"""公開後の両気配先着だけを計算する独立純参照。入口量の定義は実装しない。"""

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Quote:
    """純人工用の保存順と気配。二つの時計は物理受信時刻と呼ばない。"""

    seq: int
    bid: float
    ask: float
    known: bool = True
    session: str = '合成'
    price_clock: float = 100.0
    volume_clock: float = 100.0


def first_hit(rows: list[Quote], publication: int, side: int, tick: float) -> dict:
    """
    機能: 公開行の各BBOを起点に、後の保存行だけで両気配±1Tの初先着を調べる。
    引数: rows(list[Quote])は純人工気配、publication(int)は公開行、side(int)は方向、tick(float)は呼値。
    返り値: dictは順行・逆行・不明・未到達と判定行。出来高時計を未来資格には使わない。
    """
    assert side in (-1, 1) and 0 <= publication < len(rows) and math.isfinite(tick) and tick > 0
    reference = rows[publication]
    assert reference.known and 0 < reference.bid <= reference.ask
    step = Fraction(str(tick))
    rb, ra = Fraction(str(reference.bid)), Fraction(str(reference.ask))
    seq = reference.seq
    for row in range(publication + 1, len(rows)):
        current = rows[row]
        if current.session != reference.session:
            return dict(結果='未到達', 行=None, 終点='場末')
        if not current.known or not all(math.isfinite(value) for value in (current.bid, current.ask)) or not 0 < current.bid <= current.ask or current.seq <= seq:
            return dict(結果='不明', 行=row, 終点='価格又は保存順の資格なし')
        seq = current.seq
        b, a = Fraction(str(current.bid)), Fraction(str(current.ask))
        favorable = side * (b - rb) >= step and side * (a - ra) >= step
        adverse = side * (b - rb) <= -step and side * (a - ra) <= -step
        assert not (favorable and adverse)
        if favorable or adverse:
            return dict(結果='順行' if favorable else '逆行', 行=row, 終点='両気配初先着')
    return dict(結果='未到達', 行=None, 終点='観測終端')


def mirror(rows: list[Quote], axis: float = 1000) -> list[Quote]:
    """
    機能: 買いと売りを入れ替えるため両気配を価格軸の左右へ鏡映する。
    引数: rows(list[Quote])は純人工気配、axis(float)は十分高い鏡映軸。
    返り値: list[Quote]はbid/askの大小を保った鏡映列。
    """
    return [replace(row, bid=2 * axis - row.ask, ask=2 * axis - row.bid) for row in rows]


def main() -> None:
    """
    機能: 買売対称・suffix・同clock・場末・未知をデータなしで固定する。
    引数: なし。
    返り値: None。入口episode・数量群・成績の合格とは主張しない。
    """
    target = HERE / '公開後両気配先着だけの独立純期待.json'
    assert not target.exists()
    base = Quote(10, 100, 101)
    fixtures = {
        '公開行だけでは結果なし': ([base], '未到達', None),
        '順行ちょうど一呼値': ([base, Quote(11, 101, 102)], '順行', 1),
        '逆行ちょうど一呼値': ([base, Quote(11, 99, 100)], '逆行', 1),
        '片側だけでは未到達': ([base, Quote(11, 101, 101)], '未到達', None),
        '片側後に両側': ([base, Quote(11, 101, 101), Quote(12, 101, 102)], '順行', 2),
        '拡幅だけは未到達': ([base, Quote(11, 99, 102)], '未到達', None),
        '拡幅後の逆行': ([base, Quote(11, 99, 102), Quote(12, 98, 100)], '逆行', 2),
        '未知の前に順行': ([base, Quote(11, 101, 102), Quote(12, 99, 100, known=False)], '順行', 1),
        '未知の後の順行は使わない': ([base, Quote(11, 100, 101, known=False), Quote(12, 101, 102)], '不明', 1),
        'crossed気配': ([base, Quote(11, 103, 102)], '不明', 1),
        '非有限気配': ([base, Quote(11, float('nan'), 102)], '不明', 1),
        '保存順の重複': ([base, Quote(10, 101, 102)], '不明', 1),
        '同価格時計でも後の原行': ([base, Quote(11, 101, 102, price_clock=100)], '順行', 1),
        '出来高時計が後でも未来と呼ばない': ([replace(base, volume_clock=105), Quote(11, 101, 102, volume_clock=106)], '順行', 1),
        '場またぎは使わない': ([base, Quote(11, 101, 102, session='次場')], '未到達', None),
        '順行先着後に大逆行': ([base, Quote(11, 101, 102), Quote(12, 50, 51)], '順行', 1),
        '逆行先着後に大順行': ([base, Quote(11, 99, 100), Quote(12, 150, 151)], '逆行', 1),
    }
    checks = 0
    for name, (rows, outcome, row) in fixtures.items():
        for side, values in ((1, rows), (-1, mirror(rows))):
            result = first_hit(values, 0, side, 1)
            assert (result['結果'], result['行']) == (outcome, row), (name, side, result)
            checks += 1
            if result['行'] is not None:
                for stop in range(result['行'] + 1, len(values) + 1):
                    assert first_hit(values[:stop], 0, side, 1) == result
                    checks += 1
    result = dict(全合格=True, 検査数=checks, 純期待数=len(fixtures), 仕様='公開後の両BBO先着だけ。価格・保存順の既知flagを前提にし、時計逆行の資格規則は未固定。',
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        未確定=['episode初行ΔVの採否', '方向不明の最初の正増差の後に再認定を許すか',
                '未知を跨ぐ累計活動の完全量又は下限という定義', '量・数量・価格の各資格と時計逆行時の扱い'],
        scope='純価格先着の期待だけ。新engine source接続前で、episode入口・数量群・確率・金融の合格ではない。',
        NPZ=0, cache=0, 原板=0, 元金融=0, API=0, 新金融=0)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=checks, SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
