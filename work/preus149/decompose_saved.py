"""保存約定を変えず、中値変化と気配差へ分解する診断。新規売買を生成しない。"""

import json
import pickle
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / 'work/preus148'
JST = timezone(timedelta(hours=9))


def clock(seconds):
    """UNIX秒を日本時間文字列へ変換する。

    引数: seconds(float)は保存された価格時計。
    返り値: strは時差付き時刻。
    """
    return datetime.fromtimestamp(float(seconds), JST).isoformat()


def diagnose(scene, method, orders, data):
    """完結した保存親ごとに実収支と同一時刻の中値・気配差を照合する。

    引数: scene(str)、method(str)、orders(ndarray[N,10])、data(dict)は既存保存入力。
    返り値: list[dict]は親単位の会計分解。中値結果は架空売買の利益と解釈しない。
    """
    times = data['ready']['time_s']
    bid, ask = data['quotes']['bid'], data['quotes']['ask']
    mid = (bid + ask) / 2
    output = []
    for parent in dict.fromkeys(orders[:, 2]):
        rows = orders[orders[:, 2] == parent]
        indices, decisions = rows[:, 0].astype(int), rows[:, 1].astype(int)
        sides, quantities, prices = rows[:, 3], rows[:, 4], rows[:, 5]
        assert np.sum(sides * quantities) == 0
        assert np.all(indices > decisions)
        np.testing.assert_array_equal(prices, np.where(sides > 0, ask[indices], bid[indices]))
        cash = float(-np.sum(sides * quantities * prices) * 100)
        mid_cash = float(-np.sum(sides * quantities * mid[indices]) * 100)
        spread = float(np.sum(quantities * (ask[indices] - bid[indices]) / 2) * 100)
        assert abs(cash - (mid_cash - spread)) < 1e-6
        first = indices[0]
        hour = datetime.fromtimestamp(float(times[first]), JST).hour
        band = '17〜19時' if hour < 19 else '19〜21時' if hour < 21 else '21時以後'
        output.append(dict(session=scene, method=method, parent=int(parent), entry=clock(times[first]),
                           exit=clock(times[indices[-1]]), band=band, direction='買い' if sides[0] > 0 else '売り',
                           quantity=int(np.sum(quantities[rows[:, 7] == 1])), net=cash,
                           midpoint_change=mid_cash, spread_paid=spread,
                           initial_spread=float(ask[first]-bid[first]),
                           decision_to_fill_midpoint=float(-np.sum(sides*quantities*(mid[indices]-mid[decisions]))*100)))
    return output


def summarize(rows):
    """保存親の分解を集計し、夜数と親数を区別する。

    引数: rows(list[dict])は同じ対象群の保存親。
    返り値: dictは実収支・分解値・親の分子分母。
    """
    return dict(parents=len(rows), sessions_with_trade=len(set(r['session'] for r in rows)),
                net=sum(r['net'] for r in rows), midpoint_change=sum(r['midpoint_change'] for r in rows),
                spread_paid=sum(r['spread_paid'] for r in rows),
                positive_midpoint=sum(r['midpoint_change'] > 0 for r in rows),
                positive_net=sum(r['net'] > 0 for r in rows),
                positive_midpoint_but_nonpositive_net=sum(r['midpoint_change'] > 0 and r['net'] <= 0 for r in rows))


def main():
    """25夜の既存約定だけを読み、診断結果を新作業へ保存する。

    引数: なし。
    返り値: None。過去会計・入力・売買条件を変更しない。
    """
    rows = []
    for source in sorted((OLD / 'inputs').glob('*_Night.pkl')):
        if source.stem == '2026-10-26_Night':
            continue
        with source.open('rb') as stream:
            packet = pickle.load(stream)
        scene = source.stem
        rows += diagnose(scene, 'D07', packet['pre'], packet['data'])
        for folder, methods in ((OLD / 'orders', ('P01', 'P06')), (OLD / 'round2/orders', ('Q01', 'Q06'))):
            with np.load(folder / (scene + '.npz')) as saved:
                for method in methods:
                    rows += diagnose(scene, method, saved[method], packet['data'])
    # ----------------------------------------
    # 保存経路の帰属だけを出力し、新しい戦略損益は作らない。
    summaries = {method: summarize([r for r in rows if r['method'] == method]) for method in ('D07','P01','P06','Q01','Q06')}
    by_band = {method: {band:summarize([r for r in rows if r['method']==method and r['band']==band])
                        for band in ('17〜19時','19〜21時','21時以後')} for method in summaries}
    result = dict(definition='同一保存約定経路の中値変化−売買時の半気配差総和＝次正常気配での実収支。中値約定の実行可能性は主張しない。',
                  new_replays=0, sessions=25, summary=summaries, by_band=by_band, parents=rows)
    destination = HERE / '保存約定の中値と気配差分解.json'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
