"""正式原本を読まず、入力時計の局所資格と方向代理の一意性を独立に検算する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUT = HERE.parent / 'input'
JST = timezone(timedelta(hours=9))
START = datetime(2000, 1, 3, 17, tzinfo=JST).timestamp()
END = START + 1000


def digest(path: Path) -> str:
    """
    機能: 読み取りだけで小さいsource又は仕様の内容指紋を得る。
    引数: path(Path)は対象ファイル。
    返り値: strはSHA256。正式原本及び金融資料は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------

def stamp(offset: float) -> str:
    """
    機能: 人工の時計値をtimezone付き文字列にする。
    引数: offset(float)は人工開始後の秒数。
    返り値: strは原行へ置く日時。
    """
    return datetime.fromtimestamp(START + offset, JST).isoformat()


def fixture(price_clocks: list[float], volume_clocks: list[float]) -> list[tuple[int, dict]]:
    """
    機能: 二つの時計を独立に指定した正常十段の人工原行を作る。
    引数: price_clocks/volume_clocks(list[float])は各時計の秒数。
    返り値: list[tuple[int,dict]]は同じ長さの人工原行。
    """
    assert len(price_clocks) == len(volume_clocks)
    values = []
    for index, (pt, vt) in enumerate(zip(price_clocks, volume_clocks)):
        raw = dict(Symbol='独立人工', SymbolName='正式原本ではない', Exchange=2,
                   CurrentPrice=101, CurrentPriceTime=stamp(pt),
                   TradingVolume=100 + 10 * index, TradingVolumeTime=stamp(vt))
        for depth in range(1, 11):
            raw[f'Buy{depth}'] = dict(Price=101 - depth, Qty=10)
            raw[f'Sell{depth}'] = dict(Price=100 + depth, Qty=10)
        values.append((index, raw))
    return values


# ----------------------------------------

def oracle_usable(pt: list[float], vt: list[float], volumes: list[float]) -> list[bool]:
    """
    機能: sourceのreset計算を使わず、両行自身の時計逆行を含むusable資格を作る。
    引数: pt/vt/volumes(list[float])は人工の観測時計と累計。
    返り値: list[bool]は隣接区間の期待資格。全て場内正常の人工だけを対象とする。
    """
    price_row_ok, volume_row_ok = [], []
    price_high = volume_high = float('-inf')
    for p, v in zip(pt, vt):
        price_row_ok.append(p >= price_high)
        volume_row_ok.append(v >= volume_high)
        price_high, volume_high = max(price_high, p), max(volume_high, v)
    result = [False]
    for index in range(1, len(pt)):
        result.append(bool(price_row_ok[index - 1] and price_row_ok[index]
                           and volume_row_ok[index - 1] and volume_row_ok[index]
                           and volumes[index] >= volumes[index - 1]
                           and vt[index - 1] <= pt[index - 1] and vt[index] <= pt[index]))
    return result


def direction(last: float, bid: float, ask: float, usable: bool,
              volume_delta: float, equal_clock: bool, continuous: bool) -> int:
    """
    機能: 補足03の最終価格方向代理を独立な真偽計算にする。
    引数: last/bid/ask/volume_delta(float)、usable/equal_clock/continuous(bool)は局所観測。
    返り値: intは買い代理1、売り代理-1、不明0。真の方向別約定量を意味しない。
    """
    if not (usable and volume_delta > 0 and equal_clock and continuous and 0 < bid < ask):
        return 0
    return 1 if last >= ask else -1 if last <= bid else 0


# ----------------------------------------

def main() -> None:
    """
    機能: source資格と独立期待値を人工だけで比較し、方向代理が同時に両向きにならないか調べる。
    引数: なし。
    返り値: None。新規review JSONを保存し、既存入力・金融・生原本を変更しない。
    """
    destination = HERE / '入力時計と方向代理の独立人工反証.json'
    assert not destination.exists(), '完了資料は上書きしません'
    spec = importlib.util.spec_from_file_location('独立103入力core', INPUT / 'core.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = []
    for name, pt, vt in (
            ('正常な隣接区間', [0, 10, 20, 30], [0, 10, 20, 30]),
            ('価格のみ逆行し出来高時計は同じ', [0, 10, 5, 20], [0, 0, 0, 0]),
            ('出来高時計のみ逆行', [0, 10, 20, 30], [0, 10, 5, 30]),
            ('一つ前の価格逆行を旧人工の不一致時計で覆う', [0, 10, 5, 30], [0, 10, 20, 30]),
            ('逆行後も最大時計へ届かない', [0, 20, 10, 15, 20, 30], [0, 0, 0, 0, 0, 0])):
        rows = fixture(pt, vt)
        values, _ = module.extract_rows(rows, START, END)
        expected = oracle_usable(pt, vt, [row['TradingVolume'] for _, row in rows])
        actual = values['volume_delta_usable'].tolist()
        cases.append(dict(検査名=name, 価格時計=pt, 出来高時計=vt, 期待=expected, 実装=actual,
                          一致=expected == actual,
                          価格断裂=values['price_reset_reason'].tolist()))
    proxy_tests = []
    for last in (99, 100, 100.5, 101, 102):
        sign = direction(last, 100, 101, True, 10, True, True)
        buy, sell = last >= 101, last <= 100
        proxy_tests.append(dict(最終価格=last, 符号=sign, 一意=not (buy and sell)))
    for label, args in (
            ('不一致時計', (101, 100, 101, True, 10, False, True)),
            ('usable不明', (101, 100, 101, False, 10, True, True)),
            ('断裂', (101, 100, 101, True, 10, True, False)),
            ('正差なし', (101, 100, 101, True, 0, True, True)),
            ('交差quote', (101, 101, 100, True, 10, True, True))):
        sign = direction(*args)
        proxy_tests.append(dict(検査名=label, 符号=sign, 一意=sign == 0))
    registration = json.loads((INPUT / '原本抽出前の32場登録.json').read_text(encoding='utf-8'))
    source_match = all(digest(ROOT / name) == wanted
                       for name, wanted in registration['直接コードSHA256'].items())
    accounts = registration['accounts']
    registration_scope = (len(registration['sessions']) == 32 and len(accounts) == 64
                          and set(accounts) == {session + '|' + symbol
                                                for session in registration['sessions']
                                                for symbol in ('TOPIX', 'NK225')})
    schema = json.loads((INPUT / '入力schema.json').read_text(encoding='utf-8'))
    schema_equal = schema == module.schema()
    result = dict(全合格=all(case['一致'] for case in cases) and source_match and registration_scope
                        and schema_equal and all(case['一意'] for case in proxy_tests),
                  scope='人工の入力clock資格、草案方向代理及び登録sourceの読み取り検査。実状態機械合格ではない。',
                  時計検査=cases, 方向代理検査=proxy_tests,
                  登録32場64口座整合=registration_scope, 登録source指紋一致=source_match,
                  schema生成内容一致=schema_equal,
                  不一致数=sum(not case['一致'] for case in cases),
                  SHA256={str(path.relative_to(ROOT)): digest(path) for path in (
                      Path(__file__), INPUT / 'core.py', INPUT / '入力schema.json',
                      INPUT / 'artificial.py', INPUT / 'prepare.py',
                      INPUT / '原本抽出前の32場登録.json', HERE.parent / '数値設計補足03.json')},
                  正式原本読取=0, 正式入力再抽出=0, 金融再生=0, 現在API取得=0, 実注文=0,
                  限界='代理符号の人工は独立計算のみ。まだ未実装の入口sourceに対する合格ではない。')
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=result['全合格'], 不一致数=result['不一致数'],
                          結果=str(destination.relative_to(ROOT)), SHA256=digest(destination)), ensure_ascii=False))


if __name__ == '__main__':
    main()
