"""公開時点の気配予算と、同一商品場だけの通知・方策同値判定。"""

import hashlib
from pathlib import Path
import sys

import numpy as np

TASK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK / 'engine'))
sys.path.insert(0, str(TASK / 'engine/bbo_next'))
from policy_bbo126 import make_feed


def finite_or_none(value: float) -> object:
    """
    機能: 診断用の未知数値を零にせず明示的な欠測へ変換する。
    引数: value(float)は公開済み価格又は比率。
    返り値: float又はNone。注文や数値核の資料を補完しない。
    """
    return float(value) if np.isfinite(value) else None


def filter_paper(paper: dict, ready: dict, quotes: dict,
                 enabled: bool = True) -> tuple[dict, list[dict]]:
    """
    機能: 新規通知公開行の気配だけで親の参加を固定し、同じ親の後続通知へ引き継ぐ。
    引数: paper/ready/quotes(dict)は保存原版・価格・気配、enabled(bool)は入口予算の有効化。
    返り値: tuple[dict,list[dict]]は通知部分集合と各親の因果判定証跡。
    """
    np.testing.assert_array_equal(ready['seq'], quotes['seq'])
    np.testing.assert_array_equal(ready['time_s'], quotes['time_s'])
    feed = make_feed(paper)
    accepted, keep, traces = {}, [], []
    for position, order in enumerate(feed):
        row, source, cid = map(int, order[:3])
        assert 0 <= source < row < len(ready['last'])
        if order[7] == 1.:
            assert cid not in accepted, '一親につき初回新規通知は一回'
            side, atr = float(order[3]), float(order[9])
            last = float(ready['last'][row])
            bid, ask = float(quotes['bid'][row]), float(quotes['ask'][row])
            normal = bool(quotes['quote_valid'][row]) and np.isfinite(bid) and np.isfinite(ask) and 0. < bid < ask
            known = normal and np.isfinite(last) and last > 0. and np.isfinite(atr) and atr > 0.
            spread = ask-bid if normal else np.nan
            adverse = (ask-last if side == 1. else last-bid) if known else np.nan
            permit = (not enabled) or bool(known and spread <= .5*atr and adverse <= .5*atr)
            accepted[cid] = permit
            reason = '条件無効' if not enabled else '許可' if permit else '気配又は価格が未知' if not known else '気配幅超過' if spread > .5*atr else 'Lastから不利幅超過'
            traces.append(dict(parent=cid, publication_row=row, preparation_row=source,
                publication_seq=int(ready['seq'][row]), publication_time=float(ready['time_s'][row]),
                side=int(side), initial_atr=atr, normal_quote=bool(normal), enabled=enabled,
                last=finite_or_none(last), bid=finite_or_none(bid), ask=finite_or_none(ask),
                spread=finite_or_none(spread), adverse=finite_or_none(adverse),
                spread_atr=finite_or_none(spread/atr), adverse_atr=finite_or_none(adverse/atr),
                accepted=bool(permit), reason=reason))
        else:
            assert cid in accepted, '入口採否なしの返済通知を補完しない'
        if accepted[cid]:
            keep.append(position)
    filtered = dict(paper)
    filtered['orders'] = np.asarray(paper['orders'])[keep].copy()
    assert filtered['orders'].shape == (len(keep), 8)
    return filtered, traces


def economic_key(feed: np.ndarray, parameters: np.ndarray) -> str:
    """
    機能: 初回ATR込み数値通知と四個の数値方策が完全同一かを指紋化する。
    引数: feed(ndarray[N,10])、parameters(ndarray[4])は数値核への通知と方策。
    返り値: strはSHA256。最終損益・終了時刻・未来極値・手法名を読まない。
    """
    feed = np.ascontiguousarray(feed, dtype=np.float64)
    parameters = np.ascontiguousarray(parameters, dtype=np.float64)
    assert feed.ndim == 2 and feed.shape[1] == 10 and parameters.shape == (4,)
    assert np.isfinite(feed).all() and np.isfinite(parameters).all()
    digest = hashlib.sha256()
    for array in (feed, parameters):
        digest.update(str(array.shape).encode('ascii'))
        digest.update(array.dtype.str.encode('ascii'))
        digest.update(array.tobytes(order='C'))
    return digest.hexdigest()
