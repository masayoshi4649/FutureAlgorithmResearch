"""市場を使わない手計算二台帳で、保存監査器の長短・通常・代理を確認する。"""

import ast
import hashlib
import json
from pathlib import Path

import numpy as np

import audit_result125 as A


def arrays(columns: list[str], rows: list[dict]) -> np.ndarray:
    """
    機能: 人工台帳の明示値を固定列順に並べる。
    引数: columns (list[str]) 列名、rows (list[dict]) 明示した人工行。
    返り値: ndarray 人工二次元表。
    """
    return np.asarray([[row[key] for key in columns] for row in rows], dtype=float).reshape((-1, len(columns)))


def order(q: dict, uid: int, kind: int, side: int, quantity: int, decision: int, fill: int,
          cost: int, cash: float, position: int, average: float, reason: int, realized: float = 0.) -> dict:
    """
    機能: 判断・約定の行を指定した人工注文を一つ作る。
    引数: q (dict) 人工観測、各整数・価格値は手計算した注文内容。
    返り値: dict 固定二十列の人工注文。
    """
    return dict(order_uid=uid, group_id=1, kind=kind, side=side, quantity=quantity,
        decision_row=q["row"][decision], fill_row=q["row"][fill], decision_time=q["time"][decision],
        fill_time=q["time"][fill], price=q["ask" if side == 1 else "bid"][fill], fee=cost, reason=reason,
        decision_last=q["last"][decision], decision_bid=q["bid"][decision], decision_ask=q["ask"][decision],
        trigger_price=q["last"][decision], realized_net=realized, position_after=position,
        average_entry_after=average, cash_after=cash)


def main() -> None:
    """
    機能: 長い一群の追加通常返済と、短い一群の終端代理を手計算で検査する。
    引数: なし。
    返り値: None。金融エンジンと市場・完成結果・保存cacheは読まない。
    """
    raw = (A.OWNER / "engine125.py").read_text(encoding="utf-8")
    declarations = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("ORDER_COLUMNS", "TRADE_COLUMNS"):
            declarations[node.targets[0].id] = list(ast.literal_eval(node.value))
    columns = {"orders": declarations["ORDER_COLUMNS"], "trades": declarations["TRADE_COLUMNS"]}
    certificates = []
    for proxy in (False, True):
        prices = np.arange(100., 106.) if not proxy else np.arange(100., 94., -1.)
        q = dict(row=np.arange(10, 16, dtype=np.int64), time=np.asarray([0., 1., 61., 62., 122., 123. if not proxy else 2400.]), last=prices, bid=prices - .5, ask=prices + .5)
        if not proxy:
            orders = [order(q, 1, 1, 1, 5, 0, 1, 209, -209, 5, 101.5, 1),
                order(q, 2, 1, 1, 5, 2, 3, 209, -418, 10, 102.5, 20),
                order(q, 3, 2, -1, 10, 4, 5, 418, 19164, 0, 0, 13, 19164)]
            trade = dict(group_id=1, side=1, quantity=10, entry_notional=1025, average_entry=102.5, first_entry_row=11,
                first_entry_time=1, exit_decision_row=14, exit_row=15, exit_time=123, exit_price=104.5, gross=20000,
                entry_fees=418, exit_fee=418, net=19164, mfe=19164, mae=-5418, entry_reason=1, exit_reason=13,
                initial_w=4, initial_stop=97.5, entry_orders=2, proxy_flag=0, reference_row=15, planned_exit_time=122)
            curve = np.asarray([[10, 0, 0, 0, 0, 0, 0, 0], [12, 61, -418, -209, 0, 5, 0, 418],
                [14, 122, 9164, -418, 0, 10, 0, 0], [15, 123, 19164, 19164, 19164, 0, 0, 0]], float)
            net, fees, quantity, entries, add = 19164, 836, 10, 2, 1
            maximum_long, maximum_short, end = 10, 0, 18000
            rate_notional = 1025000
        else:
            orders = [order(q, 1, 1, -1, 5, 0, 1, 209, -209, -5, 98.5, 2)]
            trade = dict(group_id=1, side=-1, quantity=5, entry_notional=492.5, average_entry=98.5, first_entry_row=11,
                first_entry_time=1, exit_decision_row=-1, exit_row=-1, exit_time=2400, exit_price=95.5, gross=15000,
                entry_fees=209, exit_fee=209, net=14582, mfe=14582, mae=-5418, entry_reason=2, exit_reason=16,
                initial_w=4, initial_stop=102.5, entry_orders=1, proxy_flag=1, reference_row=15, planned_exit_time=2700)
            curve = np.asarray([[10, 0, 0, 0, 0, 0, 0, 0], [12, 61, -418, -209, 0, 0, 5, 418],
                [14, 122, 9582, -209, 0, 0, 5, 0], [15, 2400, 14582, -209, 0, 0, 5, 0], [15, 2400, 14582, -209, 0, 0, 5, 0]], float)
            net, fees, quantity, entries, add = 14582, 418, 5, 1, 0
            maximum_long, maximum_short, end = 0, 5, 2700
            rate_notional = 492500
        summary = dict(net=net, cash=net, profit=net, loss=0, fees_paid=fees, closed_groups=1, wins=1, losses=0,
            unclosed_quantity=0, unclosed=0, position=0, max_long=maximum_long, max_short=maximum_short,
            max_drawdown=5418, min_equity=-5418, entry_orders=entries, entry_quantity=quantity, clock_rejected=0,
            forced_groups=0, normal_groups=1, add_orders=add, groups_started=1, first_entry_time=1,
            last_time=q["time"][-1], last_equity=net, normal_closed_groups=0 if proxy else 1,
            proxy_closed_groups=int(proxy), proxy_quantity=5 if proxy else 0,
            proxy_reference_row=15 if proxy else -1, proxy_reference_time=2400 if proxy else -1,
            normal_unclosed_before_proxy=5 if proxy else 0)
        given = dict(symbol="TOPIX", session="人工", method="人工", session_end=end, summary=summary,
            net=net, profit=net, loss=0, fees=fees, entry_quantity=quantity, entry_orders=entries, groups=1,
            wins=1, losses=0, proxy_groups=int(proxy), normal_groups=0 if proxy else 1,
            max_long=maximum_long, max_short=maximum_short, forced_groups=0, forced_net=0, signal_groups=1,
            signal_net=net, rate_components=dict(reference_price=100, capacity_notional=1000000, actual_entry_notional=rate_notional))
        certificates.append(A.reconstruct(q, arrays(columns["orders"], orders), arrays(columns["trades"], [trade]), curve,
            given, dict(add_enabled=not proxy, stop_w=1), columns))
    result = dict(passed=True, cases=certificates, checks=A.CHECKS,
        audit_source_sha256=hashlib.sha256(Path(A.__file__).read_bytes()).hexdigest(),
        artificial_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        金融再生=0, 原市場=0, 保存結果読取=0, 保存入力読取=0,
        項目="手計算の買い半量追加・通常全返済と、売り半量・EOF代理。費用後全tick資産、MFE/MAE、保存間引きとproxy前後の差を確認。")
    print(json.dumps(A.save("長短と通常代理の手計算による監査器人工.json", result), ensure_ascii=False))


if __name__ == "__main__":
    main()
