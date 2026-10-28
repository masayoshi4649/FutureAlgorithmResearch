"""保存済みD07の会計・米国開始境界と夜間入力範囲だけを点検する。売買再生はしない。"""

import json
import pickle
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "audit"
JST = timezone(timedelta(hours=9))


def clock(value):
    """時刻を日本時間の文字列にする。

    引数: value(float)はUNIX秒。
    返り値: strは日本時間のISO表記。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def audit_session(path):
    """既存注文を集計して境界に残る建玉と未約定通知を確認する。

    引数: path(Path)は既存の夜間指標キャッシュ。
    返り値: dictは会計・境界保有・既存入力の検査結果。金融判断は生成しない。
    """
    with path.open("rb") as stream:
        packet, data, raw, baseline, label = pickle.load(stream)
    ready = data["ready"]
    times = ready["time_s"]
    scene = path.stem
    order_path = ROOT / "work/research145_roles/orders" / f"{scene}.npz"
    with np.load(order_path) as source:
        orders = source["D07"].copy()
    start = float(ready["us_open"]) - 900
    resume = float(ready["us_open"]) + 900
    parents = {}
    tickets = {}
    boundary_before = None
    boundary_resume = None
    late_pending = []
    maximum = {1: 0, -1: 0}
    first_after = None
    for row in orders:
        fill_i, decision_i, pid, side, qty, price, reason, is_new, ticket, fee = row
        fill_i, decision_i, pid, side, qty, ticket = map(int, (fill_i, decision_i, pid, side, qty, ticket))
        at = float(times[fill_i])
        decided = float(times[decision_i])
        assert fill_i > decision_i
        if boundary_before is None and at >= start:
            boundary_before = {"buy": sum(v[1] for v in tickets.values() if v[0] == 1), "sell": sum(v[1] for v in tickets.values() if v[0] == -1)}
        if boundary_resume is None and at >= resume:
            boundary_resume = {"buy": sum(v[1] for v in tickets.values() if v[0] == 1), "sell": sum(v[1] for v in tickets.values() if v[0] == -1)}
        if decided < resume <= at:
            late_pending.append({"parent": pid, "decision": clock(decided), "fill": clock(at), "new": bool(is_new), "qty": qty})
        parent = parents.setdefault(pid, {"id": pid, "first_new": None, "last_close": None, "cash": 0., "before_cut": False, "after_resume": False, "last_reason": None, "new_quantity": 0, "closed_quantity": 0})
        parent["cash"] += -side * qty * float(price) * 100 - float(fee)
        key = (pid, ticket)
        if is_new:
            assert key not in tickets
            tickets[key] = [side, qty]
            parent["new_quantity"] += qty
            parent["first_new"] = at if parent["first_new"] is None else min(at, parent["first_new"])
            parent["before_cut"] |= at < start
            parent["after_resume"] |= at >= resume
            if at >= resume and first_after is None:
                first_after = clock(at)
        else:
            assert key in tickets and tickets[key][0] == -side
            tickets[key][1] -= qty
            assert tickets[key][1] >= 0
            if tickets[key][1] == 0:
                tickets.pop(key)
            parent["closed_quantity"] += qty
            parent["last_close"] = at
            parent["last_reason"] = int(reason)
        for direction in (1, -1):
            maximum[direction] = max(maximum[direction], sum(v[1] for v in tickets.values() if v[0] == direction))
    assert not tickets
    boundary_before = boundary_before or {"buy": 0, "sell": 0}
    boundary_resume = boundary_resume or {"buy": 0, "sell": 0}
    crossing = []
    for parent in parents.values():
        assert parent["new_quantity"] == parent["closed_quantity"]
        assert parent["last_close"] is not None
        if parent["before_cut"] and parent["last_close"] >= start:
            crossing.append({"id": parent["id"], "entry": clock(parent["first_new"]), "close": clock(parent["last_close"]), "quiet_start_delay_seconds": parent["last_close"] - start, "last_reason": parent["last_reason"], "cash": parent["cash"], "remains_at_resume": parent["last_close"] >= resume})
    net = float(sum(p["cash"] for p in parents.values()))
    result = json.loads((ROOT / "work/research145_roles/results" / f"{scene}.json").read_text(encoding="utf-8"))
    expected = next(r for r in result["rows"] if r["method"] == "D07")["net"]
    assert abs(expected - net) < 1e-6
    early = [p for p in parents.values() if p["before_cut"]]
    late = [p for p in parents.values() if p["after_resume"]]
    other = [p for p in parents.values() if not p["before_cut"] and not p["after_resume"]]
    assert not any(p["before_cut"] and p["after_resume"] for p in parents.values())
    return {
        "session": scene, "reference": str(order_path.relative_to(ROOT)), "rows": len(times), "orders": len(orders),
        "quiet_start": clock(start), "resume": clock(resume), "net": net,
        "pre_parent_net": sum(p["cash"] for p in early), "post_parent_net": sum(p["cash"] for p in late),
        "other_parent_net": sum(p["cash"] for p in other), "pre_parent_count": len(early), "post_parent_count": len(late),
        "before_quiet_position": boundary_before, "before_resume_position": boundary_resume,
        "quiet_crossing_parents": crossing, "pending_orders_crossing_resume": late_pending,
        "maximum_buy": maximum[1], "maximum_sell": maximum[-1], "first_new_after_resume": first_after,
        "saved_account_exact": abs(expected - net) < 1e-6,
        "cache_schema": {"tuple": ["packet", "data", "raw_sources", "baseline", "label"], "ready_keys": list(ready), "quote_keys": list(data["quotes"]), "features_shape": list(data["features"].shape)},
    }


def main():
    """保存注文監査と新規夜間入力の有無をJSON・Markdownへ保存する。

    引数: なし。
    返り値: None。出力先は専用監査フォルダのみ。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    paths = sorted((ROOT / "work/research145_engine/cache").glob("*_Night.pkl"))
    rows = [audit_session(path) for path in paths]
    known = {path.stem for path in paths}
    scope = {}
    for symbol in ("NK225", "TOPIX"):
        raw_path = ROOT.parent / "JP_OSE_Data/future" / symbol
        names = {path.name for path in raw_path.iterdir() if path.is_dir() and path.name.endswith("_Night")}
        scope[symbol] = {"raw_nights": len(names), "known_nights": len(known), "raw_extra_nights": sorted(names - known), "cache_only_nights": sorted(known - names)}
    output = {
        "created_at": datetime.now(JST).isoformat(), "purpose": "保存D07の既存注文を読む会計監査。金融再生・新判断・API取得・実注文は0件。",
        "market_replays": 0, "new_financial_decisions": 0, "API_calls": 0,
        "point_value": 100, "max_per_side": 10, "fees": 0,
        "order_columns": ["fill_row", "decision_row", "parent_id", "side", "quantity", "fill_price", "reason", "new_flag", "ticket_id", "fee"],
        "input_scope": scope, "partial_current_session": {"session": "2026-10-26_Night", "source": "work/current_idle_20261026/三波確認/data", "cutoff": "2026-10-26T21:13:52+09:00", "complete_night_comparison": False},
        "nights": rows,
        "summary": {"night_count": len(rows), "all_saved_accounts_exact": all(r["saved_account_exact"] for r in rows), "nights_with_quiet_crossing_parents": sum(bool(r["quiet_crossing_parents"]) for r in rows), "positions_at_resume": sum(sum(r["before_resume_position"].values()) for r in rows), "pending_orders_crossing_resume": sum(len(r["pending_orders_crossing_resume"]) for r in rows), "other_parent_net": sum(r["other_parent_net"] for r in rows), "net": sum(r["net"] for r in rows), "pre_parent_net": sum(r["pre_parent_net"] for r in rows), "post_parent_net": sum(r["post_parent_net"] for r in rows)},
    }
    (OUT / "D07保存会計と切替境界.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# D07保存会計と米国開始境界の監査", "", "新しい売買判断・バックテストは実施していない。保存済み25夜の注文を読み、約定・親単位の会計・時間境界だけを点検した。", "", "|場|US15分前直前の買/売|US15分後直前の買/売|前段から静観へまたぐ親|前段収支|後段収支|全体収支|", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        before, after = row["before_quiet_position"], row["before_resume_position"]
        lines.append(f"|{row['session']}|{before['buy']}/{before['sell']}|{after['buy']}/{after['sell']}|{len(row['quiet_crossing_parents'])}|{row['pre_parent_net']:,.0f}|{row['post_parent_net']:,.0f}|{row['net']:,.0f}|")
    lines.extend(["", "前段・後段は新規親の所属で区分する。US15分前の返済条件成立後、次の有効行で約定するため境界を超える。10月2日は22:15:01、10月20日は22:15:40に最後の1枚を返済した。いずれも理由94の静観退出で、22:45の後段開始まで残っていない。", "", "保存注文上、判断が22:45より前・約定が22:45以後となる予約も全25場でゼロ。ただし、保存された完了注文に存在しない未成立・取消済み予約まで実測した意味ではない。今後の実装は実注文の取消完了も確認して切り替える。", "", "## 継続した仮想D07を利用する合成条件", "", "- 開場からD07を仮想運転し、仮想注文の約定・親・損失回数・再入場待機をすべて元どおり進める。米国15分前までは、その通知を実玉へ採用しない。", "- 米国15分前まで新手法だけが実玉を持ち、静観期間の最初の有効行で全返済する。未約定も含めゼロを確認するまで後段を開始しない。", "- 米国15分後以降は継続した仮想D07の新規通知から実玉へ採用する。前段新手法の損益や連敗をD07の仮想内部状態へ注入しない。", "- D07の利益予算は仮想会計を根拠とする信号用の状態であり、前段新手法の実利益や口座に存在する予算と表示しない。実リスク上限は別に設ける。", "- 保存注文を後段再利用できるのは、仮想D07がそのまま継続し、切替時に仮想・実玉・保留注文がすべてゼロで、同じ気配約定・入力・枚数である場合に限る。途中からD07を新規起動、allow=falseで影以外の状態停止、前段損益を注入する仕様には再利用できない。", "- 全D07を別の仮想ポートフォリオとして動かす必要がある。既存実装のSourceだけを進めて実約定の台帳を停止する運転とは異なる。ResearchActive145.filled145は仮想完結損益から連敗数・再入場時刻・直近返済方向を更新し、nativeResearchは採用時に実玉と親利益予算を初期化するためである。", "- 前後段の実玉の重複がなく、それぞれ上限10枚なら総保有も上限10枚以内。仮想D07の玉を実上限へ重複加算しない。新しい全場損失上限や実損益による停止を加えれば後段は変わり、保存注文の同一性は失われる。", "", "この分離仕様は因果的に実装可能だが、既存Webアプリが既にこの二重運転を実装している意味ではない。研究用の新しい合成仕様である。", "", "## 入力範囲", "", json.dumps(scope, ensure_ascii=False, indent=2), "", "上記は夜間フォルダ名と既存キャッシュの集合比較である。同名原資料の内容指紋は00145の保存照合が根拠であり、今回28GBを再ハッシュした意味ではない。", "", "2026-10-26ナイトの21:13:52までの保存スナップショットは未完了場として別評価する。新規のAPI取得はしない。"])
    (OUT / "D07切替境界の監査.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(json.dumps(scope, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
