"""追跡新規に使った極値による失敗線と固定0.25ATR線の重複を調べる。"""

import json
import pickle
from pathlib import Path

import numpy as np

from risk_structure import ROOT, HERE, read, sha, quantiles


def main():
    """
    機能: 既存入口818組の準備から約定前までの極値を再構成する。
    引数: なし。
    返り値: None。反証点の距離比較を保存し、新しい損益は計算しない。
    """
    proof = read(ROOT / 'work/wave_v85/prepared/入力準備の完了.json')
    inputs = {}
    for pair in proof['入力対応']:
        path = ROOT / pair['inputs']
        assert sha(path) == proof['使用入力SHA256'][pair['inputs']]
        with path.open('rb') as stream:
            inputs.update(pickle.load(stream))
    path = ROOT / 'work/wave_v86/phase2/observed/ledgers/T2_P1.pkl'
    expected = read(path.parent.parent / 'results/T2_P1.json')['ledger_SHA256']
    assert sha(path) == expected
    with path.open('rb') as stream:
        ledgers = pickle.load(stream)
    details = []
    for key, account in sorted(ledgers.items()):
        data = inputs[key]
        tick = float(data['tick'])
        preparations = {int(r[0]): r for r in account['entry_preparations']}
        cycles = {int(r[0]): r for r in account['cycles']}
        for order in account['orders']:
            if order[7] != 1:
                continue
            entry, source, cid, direction = map(int, order[:4])
            prep = int(preparations[cid][3])
            assert prep <= source < entry
            prices = np.asarray(data['last'][prep:entry], float)
            prices = prices[np.isfinite(prices) & (prices > 0)]
            extreme = float(prices.min() if direction > 0 else prices.max())
            atr = float(cycles[cid][5])
            raw_trigger = extreme + direction*.25*atr
            trigger = float((np.ceil(raw_trigger/tick-1e-9) if direction > 0 else
                             np.floor(raw_trigger/tick+1e-9))*tick)
            fill = float(order[5])
            jump = direction*(fill-trigger)
            assert jump >= -1e-7, (key, cid, trigger, fill)
            raw_stop = fill-direction*.25*atr
            stop25 = float((np.floor(raw_stop/tick+1e-9) if direction > 0 else
                            np.ceil(raw_stop/tick-1e-9))*tick)
            invalidation = extreme-direction*tick
            # ----------------------------------------
            # 次の売買損益を試すのではなく、同じ入口の二つの既知価格線を比べる。
            details.append(dict(セッション=key[0], 銘柄=key[1], 組=cid, 準備行=prep,
                                注文元行=source, 新規行=entry, 方向=direction, 建値=fill,
                                固定ATR=atr, 追跡極値=extreme, 元注文線=trigger,
                                注文線から観測約定の飛び呼値=jump/tick,
                                極値線距離ATR=direction*(fill-extreme)/atr,
                                極値1呼値外距離ATR=direction*(fill-invalidation)/atr,
                                固定025丸め線距離ATR=direction*(fill-stop25)/atr,
                                極値1呼値外と固定025線の差呼値=direction*(stop25-invalidation)/tick,
                                極値そのものと固定025線が同じ=abs(stop25-extreme) < 1e-7))
    summaries = []
    for symbol in ('TOPIX', 'NK225'):
        rows = [r for r in details if r['銘柄'] == symbol]
        summaries.append(dict(銘柄=symbol, 組数=len(rows),
                              極値線と固定025線一致組=sum(r['極値そのものと固定025線が同じ'] for r in rows),
                              観測約定が元注文線から飛んだ組=sum(r['注文線から観測約定の飛び呼値'] > 1e-7 for r in rows),
                              飛び呼値分布=quantiles([r['注文線から観測約定の飛び呼値'] for r in rows]),
                              反証線距離ATR分布=quantiles([r['極値1呼値外距離ATR'] for r in rows]),
                              極値1呼値外と固定025線の差呼値分布=quantiles([r['極値1呼値外と固定025線の差呼値'] for r in rows])))
    output = dict(全入口対応一致=True, 新戦略損益再生=False, 元台帳SHA256=expected,
                  集計=summaries, 明細=details,
                  解釈='新規が追跡極値から0.25ATR反発である以上、同じ極値の失敗線は固定0.25ATR線と強く重複する。1呼値余裕と注文線通過時の観測飛びだけで距離が変わる。',
                  未検証='反証点が遠い時の入口見送り・反証点損切りの売買全再生は行っていない。')
    (HERE / '新規追跡極値と固定停止の重複診断.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(summaries, ensure_ascii=False))


if __name__ == '__main__':
    main()
