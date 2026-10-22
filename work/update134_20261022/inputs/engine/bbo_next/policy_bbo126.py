"""保存済み原E01の通知を、実玉を持つ次原行BBO運転へ接続する。"""

import numpy as np

import core126
from policy126 import normalized_summary as last_summary, policy_parameters


FIELDS = ('orders', 'trades', 'curve', 'stats', 'cycles', 'order_uids',
          'execution_events', 'execution_states', 'actual_parents')
EVENT_NAMES = {1: '原版新規通知', 2: '実新規約定', 3: '元返済の実約定',
               4: '実予算又は場末の全返済', 6: '原版通知の処理', 8: '新規待機中の影撤回',
               9: '実組予算又は利益床の返済予約', 10: '場損失による終了予約',
               11: '赤字実組後の同方向制限', 12: '両市場反対時の利益床昇格',
               13: '損失後の新アンカー固定', 14: '次行からの同方向制限解除'}


def make_feed(paper: dict) -> np.ndarray:
    """
    機能: 保存原版注文へ、元の組開始時に固定された初回ATRだけを付ける。
    引数: paper(dict)は手法無変更のLast原版orders/cycles保存値。
    返り値: ndarray[float64]は十列の通知。終了時刻・最終損益・最終極値は読まない。
    """
    orders = np.asarray(paper['orders'], dtype=float)
    cycles = np.asarray(paper['cycles'], dtype=float)
    assert orders.ndim == 2 and orders.shape[1] == 8
    assert cycles.ndim == 2 and cycles.shape[1] == 10
    # ----------------------------------------
    # 列五のaは元coreでentry plan[24]から組開始時に一度だけ設定される値。
    # 保存場所が組完成行でも、未来の価格から計算された閾値へ置換しない。
    initial_atr = {int(row[0]): float(row[5]) for row in cycles}
    assert len(initial_atr) == len(cycles)
    feed = np.zeros((len(orders), 10), dtype=float)
    feed[:, :8] = orders
    for index, order in enumerate(orders):
        row, source, cid = map(int, order[:3])
        assert 0 <= source < row
        assert order[6] != 32., '原版の実予算返済を紙上出口へ混入させません'
        if order[7] == 1.:
            assert int(order[2]) in initial_atr
            feed[index,9] = initial_atr[cid]
            assert np.isfinite(feed[index,9]) and feed[index,9] > 0.
    assert np.all(np.diff(feed[:,0]) >= 0.)
    return feed


def play(config: dict, ready: dict, quotes: dict, market: np.ndarray,
         paper: dict, *, use_python: bool = False) -> dict:
    """
    機能: 原版Last影を保存引用し、実BBOの建値・数量・予算で独立に全経路を運転する。
    引数: config/ready/quotes/paper(dict)、market(ndarray)、use_python(bool)は人工用選択。
    返り値: dictは実注文と実会計。ミニ／マイクロ実板の約定保証ではない。
    """
    np.testing.assert_array_equal(ready['seq'], quotes['seq'])
    np.testing.assert_array_equal(ready['time_s'], quotes['time_s'])
    feed = make_feed(paper)
    parameters = policy_parameters(config)
    quantity = {'TOPIX': 5, 'NK225': 10}[ready['symbol']]
    cap = {'TOPIX': 10, 'NK225': 20}[ready['symbol']]
    assert np.all(feed[feed[:,7] == 1.,4] == quantity)
    assert np.all(feed[:,0] < len(ready['time_s']))
    runner = getattr(core126.simulate, 'py_func', core126.simulate) if use_python else core126.simulate
    values = runner(ready['time_s'], ready['last'], quotes['bid'], quotes['ask'],
                    quotes['quote_valid'], feed, float(ready['limit']), cap, market, parameters)
    result = dict(zip(FIELDS, values))
    assert len(values) == len(FIELDS)
    result['paper_feed'] = feed
    return result


def normalized_summary(result: dict, ready: dict) -> dict:
    """
    機能: 実BBOの返済脚正負・親組・枚数・実行イベントを別々に集計する。
    引数: result/ready(dict)は実運転完成値と保存元入力。
    返り値: dictは手数料零の一場実会計。未返済を黒字へ補完しない。
    """
    view = dict(result, policy_events126=np.empty((0,14)))
    row = last_summary(view, ready)
    row['policy_event_counts'] = {name:int((result['execution_events'][:,1] == code).sum())
                                  for code,name in EVENT_NAMES.items()}
    row['model'] = '次正常原行BBO・原版Last影・実建値1ATR予算'
    row['paper_publications'] = int((result['paper_feed'][:,7] == 1.).sum())
    return row
