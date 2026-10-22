"""最悪場の負け組を実時刻へ戻し、改修で減った損と失った利益を分ける。"""

from io import BytesIO
from datetime import datetime, timezone, timedelta
import hashlib
import pickle
import numpy as np
from common126 import ROOT, HERE, read, save, sha


def clock(value: float) -> str:
    """
    機能: 保存された秒時計を日本の日時へ変換する。
    引数: value(float)はエポック秒。
    返り値: strは日本時間。
    """
    return datetime.fromtimestamp(value, timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def group_details(orders: np.ndarray, cycles: np.ndarray, ready: dict, market: np.ndarray) -> list[dict]:
    """
    機能: 原版の各完結組を注文現金から再構成し、損失の前に得た含み益を測る。
    引数: orders/cycles/market(ndarray)は保存注文・組・因果特徴、ready(dict)は同じ入力。
    返り値: list[dict]は時刻・価格・最大利益・両市場逆行の診断。新たな売買判断はしない。
    """
    multiplier = 1000. if ready["symbol"] == "TOPIX" else 10.
    result = []
    for cycle in cycles:
        cid, start, end = map(int, cycle[:3])
        group = orders[orders[:, 2] == cid]
        entry = group[group[:, 7] == 1.]
        assert len(entry) == 1
        direction, quantity, entry_price = entry[0, 3:6]
        n = end-start+1
        delta_cash, delta_quantity = np.zeros(n), np.zeros(n)
        for order in group:
            i = int(order[0])-start
            assert 0 <= i < n
            delta_cash[i] -= order[3]*order[4]*order[5]
            delta_quantity[i] += order[3]*order[4]
        equity = (np.cumsum(delta_cash)+np.cumsum(delta_quantity)*ready["last"][start:end+1])*multiplier
        peak_index = int(np.argmax(equity))+start
        support = market[start:end+1]
        against = (support[:, 11] == 1.)
        against &= direction*support[:, 4] < -.05
        against &= direction*support[:, 5] < -.1
        against &= direction*support[:, 6] < -.05
        against &= direction*support[:, 7] < -.1
        first_opposition = int(np.flatnonzero(against)[0])+start if against.any() else None
        exits = group[group[:, 7] == 0.]
        item = dict(campaign=cid, direction="買い" if direction > 0. else "売り",
            entry_time=clock(float(ready["time_s"][start])), entry_row=start,
            entry_original_seq=int(ready["seq"][start]), entry_price=float(entry_price), quantity=int(quantity),
            fixed_atr=float(cycle[5]), final_time=clock(float(ready["time_s"][end])),
            net=float(cycle[3]*multiplier), maximum_known_profit=float(equity.max()),
            peak_time=clock(float(ready["time_s"][peak_index])),
            last_at_peak=float(ready["last"][peak_index]), final_reason=int(cycle[9]),
            first_two_market_opposition_time=None if first_opposition is None else clock(float(ready["time_s"][first_opposition])),
            pnl_at_first_opposition=None if first_opposition is None else float(equity[first_opposition-start]),
            exit_orders=[dict(time=clock(float(ready["time_s"][int(o[0])])), price=float(o[5]),
                quantity=int(o[4]), reason=int(o[6])) for o in exits])
        assert abs(item["net"]-float(equity[-1])) < 1e-5
        result.append(item)
    return sorted(result, key=lambda v: v["net"])


def execute() -> None:
    """
    機能: 各商品の原版最悪三場と選定改修の最悪三場を具体的に対照する。
    引数: なし。
    返り値: None。診断の再読は別記し、金融の追加再生には数えない。
    """
    data = read(HERE / "原版と十五改修の全四十一場会計.json")
    selected = read(HERE / "十六条件の方向別比較と固定優先順による選定.json")["selected"]
    manifest = read(HERE / "input_audit/attempt2/全四十一場の元入力と新市場特徴の非金融準備.json")
    packets = {r["session"]: r for r in manifest["packets"]}
    caches = {(r["session"], r["symbol"]): r for r in data["cache"]}
    lookup = {(r["method"], r["session"], r["symbol"]): r for r in data["rows"]}
    old = read(HERE / "baseline/原版旧三十場の費用なし保存引用.json")
    baseline_cache = np.load(ROOT / old["cache"]["path"], allow_pickle=False)
    baseline_keys = {(r["session"], r["symbol"]) for r in old["rows"]}
    keys = set()
    for symbol in ("TOPIX", "NK225"):
        for method in ("E01", selected):
            rows = sorted([r for r in data["rows"] if r["method"] == method and r["symbol"] == symbol], key=lambda r: r["net"])
            keys.update((r["session"], symbol) for r in rows[:3])
    packet_cache, read_log, details = {}, [], []
    for scene, symbol in sorted(keys):
        if scene not in packet_cache:
            ref = packets[scene]
            raw = (ROOT / ref["path"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == ref["sha256"]
            packet_cache[scene] = pickle.loads(raw)
            read_log.append(dict(path=ref["path"], sha256=ref["sha256"], purpose="損失具体箇所の診断", reads=1))
        packet = packet_cache[scene]
        ready, market = packet["inputs"][scene, symbol], packet["markets"][scene, symbol]
        ref = caches[scene, symbol]
        raw = (ROOT / ref["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == ref["sha256"]
        with np.load(BytesIO(raw), allow_pickle=False) as measurement:
            prefix = symbol+"_"+scene+"__" if (scene, symbol) in baseline_keys else "E01__"
            base = baseline_cache if (scene, symbol) in baseline_keys else measurement
            parent = group_details(base[prefix+"orders"], base[prefix+"cycles"], ready, market)
            revised = group_details(measurement[selected+"__orders"], measurement[selected+"__cycles"], ready, market)
            events = measurement[selected+"__policy_events126"]
            event_rows = [dict(time=clock(float(ready["time_s"][int(e[0])])), values=e.tolist()) for e in events]
        details.append(dict(session=scene, symbol=symbol, selected=selected,
            original=lookup["E01", scene, symbol], revised=lookup[selected, scene, symbol],
            delta=lookup[selected, scene, symbol]["net"]-lookup["E01", scene, symbol]["net"],
            original_groups=parent, revised_groups=revised, new_events=event_rows))
        read_log.append(dict(path=ref["path"], sha256=ref["sha256"], purpose="原版と改修の注文会計診断", reads=1))
    baseline_cache.close()
    save(HERE / "最悪三場の原版と改修を実時刻へ戻した診断.json", dict(passed=True,
        selected=selected, cases=details, diagnostic_read_log=read_log, new_financial_accounts=0,
        original_market_reads=0, API=0,
        caution="初回ATRの利益保全等は実装比較済みだが、失敗場だけへ後付け適用しない。二市場逆行時刻は価格特徴であり、約定主体の心理又は板の補充を直接観測した証拠とはしない。"))
    for d in details:
        print(d["session"], d["symbol"], d["original"]["net"], d["revised"]["net"], "差", d["delta"], flush=True)


if __name__ == "__main__":
    execute()
