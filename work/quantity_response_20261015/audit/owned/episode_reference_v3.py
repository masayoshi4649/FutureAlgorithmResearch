"""同じ両気配の公表活動と数量比を、完成sourceに依存せず純人工で定義する。"""

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Observation:
    """独立人工用の当時行。価格資格はfield契約を別検査するため明示flagとする。"""

    bid: float = 100
    ask: float = 101
    bid_q: float = 10
    ask_q: float = 10
    delta: float = 0
    last: float = 101
    price_known: bool = True
    volume_known: bool = True
    fresh_price: bool = False


def positive_finite(value: float) -> bool:
    """
    機能: 必要数量が既知の正有限値かを判定する。
    引数: value(float)は表示数量。
    返り値: boolは正有限値だけTrue。
    """
    return value is not None and math.isfinite(value) and value > 0


def events(rows: list[Observation]) -> list[dict]:
    """
    機能: 初行量を除外し、同BBOepisodeのT0/T1を各一回だけ純参照で作る。
    引数: rows(list[Observation])は純人工の保存行。
    返り値: list[dict]は公開行・初期Qty・当行比と当時累計だけの観測。
    """
    output = []
    current = None
    for index, row in enumerate(rows):
        usable = row.price_known and positive_finite(row.bid_q) and positive_finite(row.ask_q)
        usable = usable and row.volume_known and math.isfinite(row.delta) and row.delta >= 0
        if not usable:
            current = None
            continue
        bbo = row.bid, row.ask
        if current is None or bbo != current['bbo']:
            current = dict(start=index, bbo=bbo, q0=(row.bid_q, row.ask_q), direction=None,
                           total=Fraction(0), published=[False, False])
            continue
        current['total'] += Fraction(str(row.delta))
        if current['direction'] is None and row.delta > 0:
            if math.isfinite(row.last) and row.last > 0:
                current['direction'] = 1 if row.last >= row.ask else -1 if row.last <= row.bid else 0
            else:
                current['direction'] = 0
        side = current['direction']
        if side not in (-1, 1):
            continue
        q0 = current['q0'][1 if side == 1 else 0]
        qstar = row.ask_q if side == 1 else row.bid_q
        for type_ in (0, 1):
            if current['published'][type_]:
                continue
            if type_ == 1 and current['total'] < Fraction(str(q0)):
                continue
            current['published'][type_] = True
            output.append(dict(start=current['start'], publication=index, type=type_, side=side,
                q0=q0, qstar=qstar, activity=float(current['total']), ratio=qstar / q0,
                group='維持/回復' if qstar >= q0 else '減少', bid=row.bid, ask=row.ask,
                fresh_price=row.fresh_price))
    return output


def mirror(rows: list[Observation], axis: float = 1000) -> list[Observation]:
    """
    機能: 価格と両数量を鏡映し、最初の方向代理を反転する。
    引数: rows(list[Observation])は純人工、axis(float)は鏡映軸。
    返り値: list[Observation]は買売対称の列。
    """
    return [replace(row, bid=2 * axis - row.ask, ask=2 * axis - row.bid,
        bid_q=row.ask_q, ask_q=row.bid_q, last=2 * axis - row.last if math.isfinite(row.last) and row.last > 0 else row.last) for row in rows]


def fixtures() -> dict:
    """
    機能: 根が固定した初行除外・d0固定・未知終了の手書き期待を用意する。
    引数: なし。
    返り値: dictは素材列と期待する公開行/type/方向/群。
    """
    base = Observation(delta=50)
    return {
        '初行量を加算しない': ([base, Observation(delta=9)], [(1, 0, 1, '維持/回復')]),
        '累計等値で到達し方向は初回固定': ([base, Observation(delta=4), Observation(delta=6, last=100, ask_q=8)], [(1, 0, 1, '維持/回復'), (2, 1, 1, '減少')]),
        '一回正増で両type到達': ([base, Observation(delta=10)], [(1, 0, 1, '維持/回復'), (1, 1, 1, '維持/回復')]),
        '微量未達': ([base, Observation(delta=9.999)], [(1, 0, 1, '維持/回復')]),
        '気配内側の初回方向不明を固定': ([base, Observation(delta=5, last=100.5), Observation(delta=50)], []),
        'Last零の初回方向不明を固定': ([base, Observation(delta=5, last=0), Observation(delta=50)], []),
        'Last負値の初回方向不明を固定': ([base, Observation(delta=5, last=-1), Observation(delta=50)], []),
        'Last欠測の初回方向不明を固定': ([base, Observation(delta=5, last=float('nan')), Observation(delta=50)], []),
        'ゼロ差とQtyだけの減少回復は方向なし': ([base, Observation(ask_q=5), Observation(ask_q=20)], []),
        '方向未定中のゼロ差は消費しない': ([base, Observation(), Observation(delta=10)], [(2, 0, 1, '維持/回復'), (2, 1, 1, '維持/回復')]),
        '閾値後の回復で当時群を変えない': ([base, Observation(delta=10, ask_q=5), Observation(delta=100, ask_q=20)], [(1, 0, 1, '減少'), (1, 1, 1, '減少')]),
        '途中減少後回復も当行維持群': ([base, Observation(delta=4, ask_q=5), Observation(delta=6, ask_q=10)], [(1, 0, 1, '減少'), (2, 1, 1, '維持/回復')]),
        'V未知は古い累計を切る': ([base, Observation(delta=4), Observation(delta=20, volume_known=False), Observation(delta=20), Observation(delta=10)], [(1, 0, 1, '維持/回復'), (4, 0, 1, '維持/回復'), (4, 1, 1, '維持/回復')]),
        '片側Qty未知も古い累計を切る': ([base, Observation(delta=4), Observation(delta=6, bid_q=float('nan')), Observation(delta=20), Observation(delta=10)], [(1, 0, 1, '維持/回復'), (4, 0, 1, '維持/回復'), (4, 1, 1, '維持/回復')]),
        '初行片側Qty欠測は採用しない': ([replace(base, ask_q=float('nan')), Observation(delta=10), Observation(delta=10)], [(2, 0, 1, '維持/回復'), (2, 1, 1, '維持/回復')]),
        '価格変更行は旧閾値へ加算しない': ([base, Observation(delta=4), Observation(bid=101, ask=102, delta=6, last=102), Observation(bid=101, ask=102, delta=10, last=102)], [(1, 0, 1, '維持/回復'), (3, 0, 1, '維持/回復'), (3, 1, 1, '維持/回復')]),
        '価格不明後の初行量も除外': ([base, Observation(delta=4), Observation(delta=10, price_known=False), Observation(delta=20), Observation(delta=10)], [(1, 0, 1, '維持/回復'), (4, 0, 1, '維持/回復'), (4, 1, 1, '維持/回復')]),
    }


def main() -> None:
    """
    機能: 手書き期待・買売鏡映・全接頭から当時公開の不変を検査する。
    引数: なし。
    返り値: None。完成sourceへの接続や実データの有効性とは別に保存する。
    """
    path = HERE / '同BBO初行除外と方向固定及び未知終了の独立純期待_v3.json'
    assert not path.exists()
    checks = 0
    summaries = {}
    for name, (rows, expected) in fixtures().items():
        output = events(rows)
        assert [(event['publication'], event['type'], event['side'], event['group']) for event in output] == expected, name
        checks += 1
        reflected = events(mirror(rows))
        assert len(reflected) == len(output)
        checks += 1
        for original, other in zip(output, reflected):
            for key in ('start', 'publication', 'type', 'q0', 'qstar', 'activity', 'ratio', 'group', 'fresh_price'):
                assert original[key] == other[key], (name, key)
                checks += 1
            assert original['side'] == -other['side']
            checks += 1
        for stop in range(1, len(rows) + 1):
            assert events(rows[:stop]) == [event for event in output if event['publication'] < stop], (name, stop)
            checks += 1
        keys = [(event['start'], event['type']) for event in output]
        assert len(keys) == len(set(keys))
        checks += 1
        summaries[name] = dict(events=output, rows=len(rows))
    result = dict(全合格=True, 検査数=checks, 期待数=len(summaries), 人工=summaries,
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        鏡映訂正='Last<=0は欠測資格を保って鏡映しない。v2純checkerFalse/sourceを保全し、engine源は変更しない。',
        追補='Last正有限のfield契約を明示。旧純参照354確認/sourceはLast正値field資格の追補前へ同bytes保全。根の閾値と売買定義は変更しない。',
        仕様段階='根裁定後の独立純期待。実44列の価格/出来高資格はsource完成後に別の独立対照を行う。',
        元データ=0, NPZ=0, cache=0, 原金融=0, API=0, 新金融=0, 新engine_source接続=False)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=checks, SHA256=hashlib.sha256(path.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
