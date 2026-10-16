"""途中の広spreadが最良価格の無効であるかを、旧と初版の人工価格窓で反証する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v77/inputs/core.py'
INITIAL = ROOT / 'work/wave_v94/inputs/core.py'


def module(name: str, path: Path) -> object:
    """
    機能: 純入力部品をmainの実行なしに読む。
    引数: name (str)、path (Path)。
    返り値: object は読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def fixture(old: object) -> tuple:
    """
    機能: 最良価格と数量が正常で、途中だけ3呼値spreadとなる人工入力を作る。
    引数: old (object) は旧入力の定義。
    返り値: tuple はgrid、ready、book、snapshot。
    """
    times = np.repeat(np.arange(0., 501.), 2)
    n = len(times)
    base = 1000. + np.floor(np.arange(n) / 7) % 9
    bid, ask = base - .25, base + .25
    # 200秒の2raw行だけ価格差が3呼値。他は1呼値、最良Qtyは全て正。
    ask[400:402] = bid[400:402] + 1.5
    mid = (bid + ask) / 2
    reset = np.zeros(n, bool)
    reset[0] = True
    reason = reset.astype(np.uint8)
    ready = dict(time_s=times, seq=np.arange(n, dtype=np.int64), tick=.5, last=base.copy())
    book = dict(bid=bid, ask=ask, mid=mid, last=base.copy(), valid=np.ones(n, bool),
                reset=reset, reset_reason=reason, bid_qty=np.full(n, 100.), ask_qty=np.full(n, 100.),
                best_ofi=np.zeros(n))
    snapshot = {'valid': np.ones(n, bool)}
    snapshot.update({k: np.zeros(n) for k in old.LEGACY.SNAPSHOT_FIELDS})
    return np.array([400.]), ready, book, snapshot


def main() -> None:
    """
    機能: 根の修正前部品で端点と履歴資格の交絡を人工確認し、旧成果不変更で保存する。
    引数: なし。
    返り値: None。新input_theoryのJSONだけを保存し、新しい損益を計算しない。
    """
    old, initial = module('広spreadの旧77比較', OLD), module('広spreadの初版94比較', INITIAL)
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (OLD, INITIAL)}
    grid, ready, book, snapshot = fixture(old)
    a = old.market_features(grid, 1, ready, book, snapshot)
    b = initial.price_features(grid, 1, ready, book)
    old_window, new_window = a['windows'][300], b['windows'][300]
    assert old_window['source_valid'][0] and np.isfinite(old_window['efficiency'][0])
    assert not new_window['source_valid'][0] and np.isnan(new_window['efficiency'][0])
    assert a['current']['index'][0] == b['current']['index'][0]
    assert old_window['old'][0] == new_window['old'][0] and old_window['now'][0] == new_window['now'][0]
    assert not old_window['reset_or_invalid_cross'][0] and new_window['reset_or_invalid_cross'][0]
    for p in (OLD, INITIAL):
        assert hashlib.sha256(p.read_bytes()).hexdigest() == before[str(p.relative_to(ROOT))]
    value = {'人工反証合格': True, '対象': '修正前のinputs初版。修正版inputs_r1の性能又は合格を意味しない。',
             '人工観測': {'呼値': .5, '通常spread': .5, '途中200秒だけspread': 1.5,
                         '最良Price有限正非交差': True, '最良Qty有限正': True, '原seq連続': True,
                         '時計正常': True, '現在及び300秒前の端点spread正常': True},
             '旧300窓': {'源有効': bool(old_window['source_valid'][0]), 'ER': float(old_window['efficiency'][0]),
                         '不正横断': bool(old_window['reset_or_invalid_cross'][0])},
             '初版300窓': {'源有効': bool(new_window['source_valid'][0]), 'ER': None,
                           '不正横断': bool(new_window['reset_or_invalid_cross'][0])},
             '端点の同一性': True,
             '原因': '初版の価格validはspread2呼値上限を窓のbrokenへ伝播した。旧は2呼値を端点だけに適用し、途中の広spreadは最良価格/Qty不正と同一視していない。',
             '根の損益前決定': '新inputs_r1でpath_validを最良Price/Qty正常、endpoint_validをpath_validと旧spread2呼値上限に分け、旧の正常価格窓の意味を保持する。初版/preparedは残す。',
             '修正版に必須の検査': ['同じ人工経路で旧とr1のcurrent/old/now/source_valid/TV/ER/高安が一致。',
                                   '最良Price又はQtyが不正ならr1でも価格窓が不明。',
                                   '端点自身が3呼値なら旧とr1とも端点を採用しない。',
                                   '価格の有効化でQ/OFI/補充の不明を救済しない。'],
             '参照SHA256': before, '理論コードSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             '全62新生成': 0, '新売買計算': 0, '新損益計算': 0, '旧成果変更': 0, 'API取得': 0, '実注文': 0}
    path = HERE / '初版の広spread履歴伝播の交絡を示す人工反証.json'
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'保存先': str(path), 'SHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      '旧ER': value['旧300窓']['ER'], '初版ER': None, '新損益計算': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
