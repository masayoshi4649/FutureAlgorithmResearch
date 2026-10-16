"""広い気配差の経路資格と端点資格を、損益前に独立比較する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v77/inputs/core.py'
REVISED = ROOT / 'work/wave_v94/inputs_r1/core.py'


def module(name: str, path: Path) -> object:
    """
    機能: 売買を呼ばずに純入力部品を読む。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def equal(left: np.ndarray, right: np.ndarray, label: str) -> None:
    """
    機能: 数値と不明値を区別して共通配列を比較する。
    引数: left/right(ndarray)、label(str)。
    返り値: None。不一致なら例外で停止する。
    """
    if np.issubdtype(left.dtype, np.floating) or np.issubdtype(right.dtype, np.floating):
        np.testing.assert_allclose(left, right, rtol=0, atol=1e-9, equal_nan=True, err_msg=label)
    else:
        np.testing.assert_array_equal(left, right, err_msg=label)


def fixture(old: object) -> tuple:
    """
    機能: 同時計に二行ある正常最良気配の人工経路を作る。
    引数: old(object)は旧入力モジュール。
    返り値: tupleはgrid、ready、book、snapshot。
    """
    times = np.repeat(np.arange(0., 721.), 2)
    size = len(times)
    price = 1000. + np.floor(np.arange(size) / 7) % 9
    reset = np.zeros(size, bool)
    reset[0] = True
    ready = dict(time_s=times, seq=np.arange(size, dtype=np.int64), tick=.5, last=price.copy())
    book = dict(bid=price-.25, ask=price+.25, mid=price.copy(), last=price.copy(),
                bid_qty=np.full(size, 100.), ask_qty=np.full(size, 100.), valid=np.ones(size, bool),
                reset=reset, reset_reason=reset.astype(np.uint8), best_ofi=np.zeros(size))
    snapshot = {'valid': np.ones(size, bool)}
    snapshot.update({field: np.zeros(size) for field in old.LEGACY.SNAPSHOT_FIELDS})
    return np.arange(302., 719., 5.), ready, book, snapshot


def compare_price(new: dict, old: dict) -> int:
    """
    機能: 同じ経路資格を持つ旧及び修正版の共通価格列を全比較する。
    引数: new/old(dict)。
    返り値: intは比較した配列数。
    """
    count = 0
    for kind in ('current', 'windows', 'ranges'):
        groups = [(new[kind], old[kind])] if kind == 'current' else [
            (new[kind][seconds], old[kind][seconds]) for seconds in new[kind]]
        for first, second in groups:
            for field in sorted(first.keys() & second.keys()):
                equal(first[field], second[field], kind+'.'+field)
                count += 1
    return count


def main() -> None:
    """
    機能: 修正版の広spread・不正最良・深板・出来高の境界を検査する。
    引数: なし。
    返り値: None。新しい理論JSONだけ保存し、実場の売買や損益は計算しない。
    """
    old, revised = module('修正版独立の旧77', OLD), module('修正版独立の新94r1', REVISED)
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (OLD, REVISED)}
    cases = []
    total_columns = 0
    for kind in ('正常', '途中だけ広spread', '現在端点だけ広spread', '過去端点だけ広spread',
                 '最良数量ゼロ', '最良数量不明', '最良価格交差', '最良価格不明',
                 '深板だけ不正と次行の旧bit1', '出来高だけreset', '原行欠番'):
        grid, ready, book, snapshot = fixture(old)
        grid = np.array([400.]) if kind != '正常' else grid
        if kind in ('途中だけ広spread', '現在端点だけ広spread', '過去端点だけ広spread'):
            location = {'途中だけ広spread': 400, '現在端点だけ広spread': 796, '過去端点だけ広spread': 196}[kind]
            book['ask'][location:location+2] = book['bid'][location:location+2] + 1.5
            book['mid'] = (book['bid']+book['ask'])/2
        elif kind in ('最良数量ゼロ', '最良数量不明', '最良価格交差', '最良価格不明'):
            book['valid'][400:402] = False
            book['reset'][400:403] = True
            book['reset_reason'][400:402] = 4
            book['reset_reason'][402] = 1
            if kind == '最良数量ゼロ':
                book['bid_qty'][400:402] = 0.
            elif kind == '最良数量不明':
                book['ask_qty'][400:402] = np.nan
            elif kind == '最良価格交差':
                book['ask'][400:402] = book['bid'][400:402]
            else:
                book['bid'][400:402] = np.nan
            book['mid'] = (book['bid']+book['ask'])/2
        elif kind == '深板だけ不正と次行の旧bit1':
            book['valid'][400:402] = False
            book['reset'][400:403] = True
            book['reset_reason'][400:402] = 4
            book['reset_reason'][402] = 1
        elif kind == '出来高だけreset':
            book['reset'][400] = True
            book['reset_reason'][400] = 16
        elif kind == '原行欠番':
            ready['seq'][400:] += 1
            book['reset'][400] = True
            book['reset_reason'][400] = 2
        before = pickle.dumps((grid, ready, book, snapshot), protocol=5)
        original = old.market_features(grid, 1, ready, book, snapshot)
        output = revised.price_features(grid, 1, ready, book)
        qualified = output['windows'][300]['source_valid']
        if kind in ('正常', '途中だけ広spread', '現在端点だけ広spread', '過去端点だけ広spread', '原行欠番'):
            total_columns += compare_price(output, original)
        if kind == '途中だけ広spread':
            assert qualified[0] and output['price_quality']['path_valid'][400]
            assert not output['price_quality']['endpoint_valid'][400]
            assert not output['windows'][300]['reset_or_invalid_cross'][0]
        elif kind in ('現在端点だけ広spread', '過去端点だけ広spread'):
            assert not qualified[0]
            assert not output['windows'][300]['reset_or_invalid_cross'][0]
            assert not output['current']['valid'][0] if kind == '現在端点だけ広spread' else output['windows'][300]['old'][0] == -1
        elif kind.startswith('最良') or kind == '原行欠番':
            assert not qualified[0] and output['windows'][300]['reset_or_invalid_cross'][0]
        elif kind in ('深板だけ不正と次行の旧bit1', '出来高だけreset'):
            assert qualified[0] and not original['windows'][300]['source_valid'][0]
            assert not output['price_quality']['reset'][400:403].any()
        joined = revised.market_features(grid, 1, ready, book, snapshot)
        legacy_board = revised.LEGACY.market_features(grid, 1, ready, book, snapshot, windows=(15,30))
        for field, value in legacy_board['current'].items():
            equal(joined['q_current'][field], value, '旧Q不変.'+field)
        for seconds, flow in legacy_board['windows'].items():
            for field, value in flow.items():
                equal(joined['flow'][seconds][field], value, '旧OFI不変.'+field)
        assert before == pickle.dumps((grid, ready, book, snapshot), protocol=5)
        cases.append({'条件': kind, '300秒源有効': qualified.tolist(), '不正横断': output['windows'][300]['reset_or_invalid_cross'].tolist(),
                      '旧Q及びOFIの全列一致': True, '入力バイト不変': True})
    for path in (OLD, REVISED):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == hashes[str(path.relative_to(ROOT))]
    value = {'人工全合格': True, '対象': '入力資格だけ。損益や取引性能の証明ではない。',
             '検査': cases, '旧との共通価格全列比較数': total_columns,
             '意味': ['途中だけの広spreadは価格値の欠測と同一視しない。端点は旧同様2呼値まで。',
                      '最良Price又はQty不正と原行欠番は価格窓を切断する。',
                      '深板だけの不正及び出来高resetは価格だけから分離し、旧Q及びOFIの資格を変更しない。',
                      '旧bit1は初回以外にも深板不正後に発生するため価格resetへ丸ごと転用しない。'],
             '参照SHA256': hashes, '理論コードSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             '全62生成を実行': 0, '新条件売買実行': 0, '新損益計算': 0, 'API取得': 0, '実注文': 0}
    path = HERE / '修正版の広spread端点と価格経路及び旧板資格の独立人工.json'
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'保存先': str(path), 'SHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      '人工条件数': len(cases), '共通価格列比較数': total_columns, '新損益計算': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
