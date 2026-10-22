"""一回追加の保存注文を当時の二市場方向と入口位置へ対応する。新金融は行わない。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import features131


def read(path):
    """
    機能: 保存済み日本語JSONを読み取る。
    引数: path(Path)は固定資料。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path):
    """
    機能: 読み取った保存資料の参照を記録する。
    引数: path(Path)は資料。
    返り値: dictは相対位置と指紋。
    """
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def number(value):
    """
    機能: 欠測をゼロへ補完せずJSON用へ移す。
    引数: value(float)は観測値。
    返り値: float又はNone。
    """
    return float(value) if np.isfinite(value) else None


def clock(value):
    """
    機能: 原資料時計を日本の時分秒へ表示する。
    引数: value(float)はエポック秒。
    返り値: strは日本時間。
    """
    return datetime.fromtimestamp(value, ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")


def describe(ready, quotes, history, market, row):
    """
    機能: 指定した判断行までに得られる価格位置・二市場方向を保存する。
    引数: ready/quotes(dict)、history/market(ndarray)、row(int)は保存資料と判断行。
    返り値: dictは当時の観測であり、将来ラベルを含まない。
    """
    h = history[row]
    bid, ask = quotes["bid"][row], quotes["ask"][row]
    mid = (bid+ask)*.5
    span = h[3]-h[4]
    return dict(row=row, time=clock(ready["time_s"][row]), bid=number(bid), ask=number(ask),
        mid=number(mid), atr=number(ready["atr"][row]),
        own5=number(h[6]), own20=number(h[7]), peer5=number(h[10]), peer20=number(h[11]),
        own_open=number(h[8]), own_from_open=number(mid-h[8]), peer_from_open=number(h[13]),
        high20=number(h[3]), low20=number(h[4]), mean5=number(h[0]), mean20=number(h[1]),
        position_in_known_band=number((mid-h[4])/span if span > 0 else np.nan),
        efficiency20=number(h[5]), peer_efficiency20=number(h[12]),
        own30_atr=number(market[row, 4]), peer30_atr=number(market[row, 6]),
        own120_atr=number(market[row, 5]), peer120_atr=number(market[row, 7]),
        current_market_known=bool(market[row, 11] == 1.),
        own_history_time=clock(h[9]) if np.isfinite(h[9]) else None,
        peer_history_time=clock(h[14]) if np.isfinite(h[14]) else None)


def main():
    """
    機能: 第二巡日中の中盤・後半・始値方式を保存取引だけから診断する。
    引数: なし。
    返り値: None。注文生成や金融再生は零。
    """
    account_path = WORK/"round2/全条件の会計.json"
    account = read(account_path)
    wanted = [r for r in account["rows"] if r["kind"] == "Day" and r["method"] in ("S02", "S03", "S07")
        and r["components"]["追加"]["entries"] > 0]
    manifest_path = ROOT/"work/daynight128_20261020/入力準備.json"
    manifest = read(manifest_path)
    provenance = [reference(account_path), reference(manifest_path)]
    cases = []
    for scene in sorted(set(r["session"] for r in wanted)):
        packet_ref = next(r for r in manifest["packets"] if r["session"] == scene)
        path = ROOT/packet_ref["path"]
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == packet_ref["sha256"]
        packet = pickle.loads(raw)
        del raw
        inputs, markets, histories, phases = features131.build(packet)
        provenance.append(dict(path=packet_ref["path"], sha256=packet_ref["sha256"]))
        for symbol in ("TOPIX", "NK225"):
            selected = [r for r in wanted if r["session"] == scene and r["symbol"] == symbol]
            if not selected:
                continue
            archive_ref = next(r for r in account["cache"] if r["session"] == scene and r["symbol"] == symbol)
            archive_path = ROOT/archive_ref["path"]
            provenance.append(reference(archive_path))
            assert provenance[-1]["sha256"] == archive_ref["sha256"]
            key = scene, symbol
            ready, q, history, market = inputs[key], packet["quotes"][key], histories[key], markets[key]
            with np.load(archive_path, allow_pickle=False) as archive:
                for row in selected:
                    method = row["method"]
                    orders = archive[method+"__extra_orders"]
                    trades = archive[method+"__extra_trades"]
                    core_orders = archive[method+"__core_orders"]
                    opened = orders[orders[:, 7] == 1]
                    closed = orders[orders[:, 7] == 0]
                    assert len(opened) == len(closed) == len(trades) == 1
                    entry, exit_order, trade = opened[0], closed[0], trades[0]
                    source, exit_source = int(entry[1]), int(exit_order[1])
                    before = describe(ready, q, history, market, source)
                    side = int(entry[3])
                    own20, peer20 = history[source, 7], history[source, 11]
                    own5, peer5 = history[source, 6], history[source, 10]
                    op, pp = before["own_from_open"], before["peer_from_open"]
                    core_entry = core_orders[core_orders[:, 7] == 1]
                    same20 = side*own20 > 0 and side*peer20 > 0
                    same5 = side*own5 > 0 and side*peer5 > 0
                    sameopen = side*op > 0 and side*pp > 0
                    cases.append(dict(method=method, session=scene, symbol=symbol,
                        side=side, quantity=int(entry[4]), entry_time=clock(ready["time_s"][int(entry[0])]),
                        entry_price=float(entry[5]), exit_time=clock(ready["time_s"][int(exit_order[0])]),
                        exit_price=float(exit_order[5]), exit_reason=int(exit_order[6]),
                        net=float(trade[9]), risk=float(trade[10]), mfe=float(trade[11]), mae=float(trade[12]),
                        before=before, at_exit_decision=describe(ready, q, history, market, exit_source),
                        signed_own20=number(side*own20), signed_peer20=number(side*peer20),
                        both20_support=bool(same20), both5_support=bool(same5), both_open_support=bool(sameopen),
                        core_entries_full_session=len(core_entry),
                        core_entries_at_decision=int((core_entry[:, 0] <= source).sum()),
                        later_core_entries=[dict(time=clock(ready["time_s"][int(o[0])]),
                            side=int(o[3]), price=float(o[5])) for o in core_entry if o[0] > source]))
        print(scene, len(cases), "保存親診断", flush=True)
    aggregate = []
    for method in ("S02", "S03", "S07"):
        for symbol in ("TOPIX", "NK225"):
            data = [x for x in cases if x["method"] == method and x["symbol"] == symbol]
            groups = {}
            for label, predicate in (("両20分支持", lambda x: x["both20_support"]),
                                     ("20分不一致または中立", lambda x: not x["both20_support"]),
                                     ("両5分支持", lambda x: x["both5_support"]),
                                     ("両始値支持", lambda x: x["both_open_support"])):
                matched = [x for x in data if predicate(x)]
                groups[label] = dict(parents=len(matched), wins=sum(x["net"] > 0 for x in matched),
                    losses=sum(x["net"] < 0 for x in matched), net=sum(x["net"] for x in matched))
            aggregate.append(dict(method=method, symbol=symbol, parents=len(data),
                net=sum(x["net"] for x in data), groups=groups))
    output = dict(passed=True, financial_replays=0, order_generation=0, cases=cases, aggregate=aggregate,
        provenance=provenance, feature_source=reference(WORK/"features131.py"),
        note="当時値へ既存注文を対応した非金融再分類。MFE/MAE・出口・収支は事後ラベル。条件除外後の新運転成績ではない。")
    target = HERE/"第二巡日中の追加入口と当時の二市場方向.json"
    assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    for item in cases:
        b = item["before"]
        print(item["method"], item["session"], item["symbol"], "買" if item["side"] > 0 else "売",
            item["entry_time"][11:19], item["entry_price"], "→", item["exit_time"][11:19],
            item["exit_price"], item["net"], "20分", b["own20"], b["peer20"],
            "5分", b["own5"], b["peer5"], "始値差", b["own_from_open"], b["peer_from_open"],
            "帯位置", b["position_in_known_band"], "R", item["risk"], "MFE", item["mfe"])


if __name__ == "__main__":
    main()
