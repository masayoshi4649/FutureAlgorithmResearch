"""主条件の仮想約定が同じ行の気配範囲外で有利になった注文を直接照合する。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
JST = timezone(timedelta(hours=9))


def stamp(value: float) -> str:
    """機能: 原本の約定時計を日本時間の文字列へ変換する。

    引数: value(float)。返り値: 日本時間の日時(str)。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def inspect_order(order: list, frame: dict) -> dict:
    """機能: 一注文の約定行を最良気配と照合し、有利な範囲外と更新順の事実を記録する。

    引数: order(list)、frame(dict)。返り値: 注文別の直接観測(dict)。
    一般的な約定可能性を証明せず、保存行の値だけを比較する。
    """
    i = int(np.searchsorted(frame['seq'], int(order[3])))
    d = int(np.searchsorted(frame['seq'], int(order[2])))
    assert frame['seq'][i] == order[3] and frame['seq'][d] == order[2]
    assert i == d + 1, (i, d)
    assert frame['last'][i] == order[7] and frame['time_s'][i] == order[1]
    last, bid, ask = float(frame['last'][i]), float(frame['bid'][i]), float(frame['ask'][i])
    buy = order[5] > 0
    favorable = last < bid if buy else last > ask
    unfavorable = last > ask if buy else last < bid
    last_unchanged = bool(i > 0 and frame['last'][i] == frame['last'][i - 1])
    quote_changed = bool(i > 0 and (frame['bid'][i] != frame['bid'][i - 1]
                                  or frame['ask'][i] != frame['ask'][i - 1]))
    return dict(
        区分='新規' if order[4] == 1 else '返済', 売買方向='買い' if buy else '売り', 枚数=int(order[6]),
        判断時刻=stamp(order[0]), 判断原本行=int(order[2]),
        約定時計=stamp(order[1]), 約定原本行=int(order[3]),
        last=last, bid=bid, ask=ask, mid=float(frame['mid'][i]),
        同行気配範囲外で有利=bool(favorable), 同行気配範囲外で不利=bool(unfavorable),
        直前有効行とlast不変=last_unchanged, 直前有効行から気配変化=quote_changed,
        last不変かつ気配変化=last_unchanged and quote_changed,
        原本行が隣接=bool(i > 0 and frame['seq'][i] == frame['seq'][i - 1] + 1),
        直前有効原本行=int(frame['seq'][i - 1]) if i > 0 else None,
        直前の約定時計=stamp(frame['time_s'][i - 1]) if i > 0 else None,
        直前last=float(frame['last'][i - 1]) if i > 0 else None,
        直前bid=float(frame['bid'][i - 1]) if i > 0 else None,
        直前ask=float(frame['ask'][i - 1]) if i > 0 else None,
    )


def summarize(orders: list[dict]) -> dict:
    """機能: 気配範囲外での有利さと、最終価格不変・気配変化の件数をまとめる。

    引数: orders(list[dict])。返り値: 注文数を分母とする集計(dict)。
    """
    size = len(orders)
    favorable = sum(order['同行気配範囲外で有利'] for order in orders)
    stationary = sum(order['last不変かつ気配変化'] for order in orders)
    return dict(
        総注文数=size, 気配範囲外で有利な約定件数=favorable,
        気配範囲外で有利な約定割合=favorable / size if size else None,
        気配範囲外で不利な約定件数=sum(order['同行気配範囲外で不利'] for order in orders),
        last不変かつ気配変化件数=stationary,
        last不変かつ気配変化割合=stationary / size if size else None,
        有利範囲外かつlast不変気配変化件数=sum(order['同行気配範囲外で有利'] and order['last不変かつ気配変化'] for order in orders),
        有利範囲外かつ直前rawと隣接件数=sum(order['同行気配範囲外で有利'] and order['原本行が隣接'] for order in orders),
    )


def select_examples(groups: list[dict]) -> list[dict]:
    """機能: 有利な範囲外約定の最初の入口例・出口例を優先し、時系列で最大3組示す。

    引数: groups(list[dict]) は既にセッション・原本行順。返り値: 最大3往復組(list[dict])。
    損益、価格差、勝敗の大きさは選択に使わない。
    """
    selected = []
    used = set()
    for label in ('入口', '出口'):
        for group in groups:
            identifier = group['セッション'], group['組']
            if group[label]['同行気配範囲外で有利'] and identifier not in used:
                selected.append(group)
                used.add(identifier)
                break
    for group in groups:
        identifier = group['セッション'], group['組']
        if len(selected) >= 3:
            break
        if identifier not in used and (group['入口']['同行気配範囲外で有利'] or group['出口']['同行気配範囲外で有利']):
            selected.append(group)
            used.add(identifier)
    return selected


def main() -> None:
    """機能: 固定された主条件3つの注文証拠を作り、既存診断JSONへ追加する。

    引数: なし。返り値: なし(None)。売買コード・条件・台帳は変更しない。
    """
    path = BASE / '売買結果.json'
    source = json.loads(path.read_text(encoding='utf8'))
    frames = pickle.loads((BASE / 'features.pkl').read_bytes())
    main_ids = set(source['meta']['main_ids'])
    methods = []
    for method in source['methods']:
        if method['id'] not in main_ids:
            continue
        symbols = {}
        for symbol in ('TOPIX', 'NK225'):
            groups = []
            for account in sorted(method['accounts'], key=lambda row: row['session']):
                if account['symbol'] != symbol:
                    continue
                frame = frames[account['session'], symbol]
                orders = {(int(order[10]), int(order[4])): order for order in account['orders']}
                for trade in account['trades']:
                    cid = int(trade[9])
                    groups.append(dict(セッション=account['session'], 組=cid,
                                       入口=inspect_order(orders[cid, 1], frame),
                                       出口=inspect_order(orders[cid, 2], frame)))
            entry, exit_orders = [row['入口'] for row in groups], [row['出口'] for row in groups]
            assert len(groups) == method['summary'][symbol]['cycles']
            symbols[symbol] = dict(全注文=summarize(entry + exit_orders), 新規=summarize(entry),
                                    返済=summarize(exit_orders), 代表往復=select_examples(groups))
        methods.append(dict(手法ID=method['id'], 銘柄別=symbols))
    assert len(methods) == 3
    result = dict(
        目的='同じCurrentPriceTimeだったという間接情報だけでなく、仮想約定lastと同行bid/askの直接比較を示す。',
        有利範囲外の定義='買いはlast<bid、売りはlast>ask。同じ約定行の最良気配範囲外で有利な価格を仮想約定に使った注文。',
        更新差の定義='約定行と直前有効原本行でlastが同じ、かつbidまたはaskが変わった注文。判断行がその直前有効行であることも全件照合。',
        代表例の選定='各主条件×銘柄で最初の有利範囲外の新規例と返済例を優先し、残りは最初の未選択例。損益額や価格差で選んでいない。',
        限界='これは保存スナップショット上で価格が整合していない直接証拠。正確な配信順序、実際の受信遅延、特別な約定条件まで識別せず、全てを古いlastと断定しない。',
        含意='最終価格で必ず仮想約定する前提が、同行の表示気配では提供されていない有利な価格を使う注文を含む。実注文でも同じ利益を得られる根拠にはならない。',
        原本順次行照合=True, 条件変更=False, 入力結果SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
        手法別=methods,
    )
    (HERE / '気配範囲外約定の証拠.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    prior_path = HERE / '主条件の返済理由と価格差.json'
    prior = json.loads(prior_path.read_text(encoding='utf8'))
    prior['気配範囲外の直接証拠'] = result
    prior_path.write_text(json.dumps(prior, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps([{ '手法': method['手法ID'], '銘柄': symbol,
                       '全注文': values['全注文'], '新規有利件数': values['新規']['気配範囲外で有利な約定件数'],
                       '返済有利件数': values['返済']['気配範囲外で有利な約定件数'] }
                      for method in methods for symbol, values in method['銘柄別'].items()], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
