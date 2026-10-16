"""段階通過前に観測できた移動の失敗を忘れる境界を、人工原行だけで反証する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 小source又は証跡の内容指紋を取る。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。原本及び金融資料は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str, path: Path) -> object:
    """
    機能: 入口sourceと人工生成部品を固有名で読む。
    引数: name(str)、path(Path)は名前とsource。
    返り値: objectはモジュール。正式再生を呼び出さない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


# ----------------------------------------

def examples(factory: object, family: str, broken: bool) -> tuple[list[dict], int, int]:
    """
    機能: C準備行又はR回復行で移動が同時成立し、その直後に維持又は破れる人工を作る。
    引数: factory(Callable)、family(str:C/R)、broken(bool)は生成関数、入口及び価格破れ。
    返り値: tuple[list[dict],int,int]は人工、同時成立行、次境界行。
    """
    base = [factory(), factory()]
    if family == 'C':
        rows = base + [factory(101, 102, bidq=5, last=101, volume=30)]
        rows += [factory(askq=4)] if broken else [factory(101, 102, bidq=5)]
        if broken:
            rows.append(factory(101, 102, bidq=5))
        rows.append(factory(101, 102, bidq=5, volume=30))
        return rows, 2, 3
    rows = base + [factory(askq=4, volume=30),
                   factory(99, 100, askq=5, last=99, amods={101: 8})]
    rows += [factory(askq=8)] if broken else [factory(99, 100, askq=5, last=99, amods={101: 8})]
    if broken:
        rows.append(factory(99, 100, askq=5, last=99, amods={101: 8}))
    rows.append(factory(99, 100, askq=5, last=99, volume=30, amods={101: 8}))
    return rows, 3, 4


def price_moved(raw: dict, row: int, family: str, intent: int, tick: float) -> bool:
    """
    機能: 基準raw行1に対する移動の現在観測を独立な価格式で判定する。
    引数: raw(dict)、row/intent(int)、family(str)、tick(float)は人工と想定方向。
    返り値: boolは当該行での移動。段階通過や未来価格を参照しない。
    """
    b0, a0, b, a = raw['bid'][1], raw['ask'][1], raw['bid'][row], raw['ask'][row]
    if family == 'C':
        return bool(b >= a0 and a >= a0 + tick) if intent == 1 else bool(a <= b0 and b <= b0 - tick)
    return bool(b <= b0 - tick and a <= a0 - tick) if intent == 1 else bool(b >= b0 + tick and a >= a0 + tick)


# ----------------------------------------

def main() -> None:
    """
    機能: 同時成立行の観測欠落と旧活動の再利用を両商品・売買反射・全14入口で検証する。
    引数: なし。
    返り値: None。新review反例を保存する。新条件の金融又はsource修正は行わない。
    """
    destination = HERE / 'C準備とR回復行の先行移動を忘れる独立人工反例.json'
    assert not destination.exists(), '完成反例は上書きしません'
    review = load('先行移動人工の既存部品', HERE / '定着反転と二市場判断を独立人工で比較する.py')
    engine_path = HERE.parent / 'engine' / 'states.py'
    states = load('先行移動反証だけの対象入口', engine_path)
    catalog = load('先行移動反証だけの条件', HERE.parent / 'catalog.py')
    before = digest(engine_path)
    for name in ('fixed_quantity', 'seed', 'log_event'):
        setattr(states, name, getattr(states, name).py_func)
    cases = []
    for family in ('C', 'R'):
        for broken in (False, True):
            rows, observed, boundary = examples(review.market_row, family, broken)
            for symbol, tick in (('TOPIX', .5), ('NK225', 10.)):
                for reflection in (False, True):
                    raw = review.raw_fixture(rows, tick, reflection)
                    intent = -1 if reflection else 1
                    output_direction = intent if family == 'C' else -intent
                    column = 0 if output_direction == 1 else 1
                    assert price_moved(raw, observed, family, intent, tick)
                    assert price_moved(raw, boundary, family, intent, tick) == (not broken)
                    for config in catalog.catalog():
                        if config.get('kind') != 'single' or config.get('family') != family:
                            continue
                        actual = states.run(raw, dict(tick=tick), config, python=True)
                        events = actual['events']
                        intended = events[events[:, 1] == intent]
                        same_row_observation = intended[(intended[:, 0] == observed) & (intended[:, 3] == 9)]
                        boundary_resets = intended[(intended[:, 0] == boundary) & (intended[:, 3] == 8)]
                        assert len(same_row_observation) == 0
                        assert int(actual['anchor_raw_seq'][boundary, column]) == 1
                        assert bool(actual['ready'][-1, column])
                        if broken:
                            assert len(boundary_resets) == 0
                        cases.append(dict(入口=config['id'], 商品=symbol, 売買反射=reflection,
                            想定方向=intent, 実参加方向=output_direction, 移動後価格破れ=broken,
                            同時成立行=observed, 次境界行=boundary,
                            現source同時移動観測なし=True,
                            次行の基準seq=int(actual['anchor_raw_seq'][boundary, column]),
                            次行で旧基準破棄なし=len(boundary_resets) == 0,
                            最終ready=actual['ready'][:, column].tolist(),
                            最終基準seq=int(actual['anchor_raw_seq'][-1, column]),
                            段階=actual['phases'][:, column].tolist(),
                            元想定の段階ログ=intended[:, :12].tolist(),
                            新案で必要な基準seq=boundary if broken else 1))
    assert digest(engine_path) == before
    result = dict(全合格=False, 反例再現=True,
        scope='現sourceの段階境界を人工反証。金融損益の良化や新仕様の本体合格を意味しない。',
        検査ケース数=len(cases), 価格破れで旧活動再使用件数=sum(case['移動後価格破れ'] for case in cases),
        価格維持対照件数=sum(not case['移動後価格破れ'] for case in cases), 検査=cases,
        独立解釈='段階を同原行で二つ通過しない規則は保てる。C準備成立又はR回復成立の現在行で既に移動した事実は別に記録し、後で破れた場合はその失敗を知った現在行で基準を破棄する。',
        修正価値='あり。活動が失敗した波の証拠を後の別波へ再利用する状態上の矛盾を防ぐ。利益改善は未検証。',
        範囲限定='C活動準備に未到達の行又はR回復に未到達の行から移動監視を前倒しする案は今回未承認。閾値も変更しない。',
        必要実装='観測行ではcode9/first_price_moveだけを記録し、moved_row/postV開始は従来どおり次別行。直後破れはreason4で破棄。数量不足も同じ観測追跡。',
        SHA256={str(path.relative_to(ROOT)): digest(path) for path in (
            Path(__file__), engine_path, HERE.parent / 'catalog.py',
            HERE / '定着反転と二市場判断を独立人工で比較する.py', HERE.parent / '数値設計補足01.json')},
        金融再生=0, 正式原本読取=0, 新仕様本体実行=0, source変更=0, JIT実行=0,
        現在API取得=0, 実注文=0)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=False, 反例再現=True, 検査ケース数=len(cases),
        価格破れで旧活動再使用件数=result['価格破れで旧活動再使用件数'],
        価格維持対照件数=result['価格維持対照件数'], SHA256=digest(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
