"""旧日中94親の片市場だけの進行失敗を保存経路で分類する。新退出は作らない。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def read(path):
    """
    機能: 既存の小JSONを読む。
    引数: path(Path)は保存資料。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def clock(value):
    """
    機能: 保存価格時計を時分秒へ変換する。
    引数: value(float)はエポック秒。
    返り値: strは日本時間。
    """
    return datetime.fromtimestamp(value, ZoneInfo("Asia/Tokyo")).strftime("%H:%M:%S")


def finite(value):
    """
    機能: 欠測をJSONのnullへ保存する。
    引数: value(float)は測定値。
    返り値: float又はNone。
    """
    return float(value) if np.isfinite(value) else None


def main():
    """
    機能: 自己逆行と相手順行の同時発生を、旧実保有中だけで全親分類する。
    引数: なし。
    返り値: None。閾値は既存の0.25初期幅、持続も既存の60秒・120秒を用いる。
    """
    account = read(WORK/"round2/全条件の会計.json")
    manifest = read(ROOT/"work/daynight128_20261020/入力準備.json")
    results, refs = [], []
    for ref in manifest["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Day"):
            continue
        path = ROOT/ref["path"]
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == ref["sha256"]
        packet = pickle.loads(content)
        refs.append(dict(path=ref["path"], sha256=ref["sha256"]))
        feature_path = ROOT/ref["features"]["path"]
        assert hashlib.sha256(feature_path.read_bytes()).hexdigest() == ref["features"]["sha256"]
        with np.load(feature_path, allow_pickle=False) as features:
            for symbol in ("TOPIX", "NK225"):
                key = scene, symbol
                ready, quotes, market = packet["inputs"][key], packet["quotes"][key], packet["markets"][key]
                history, feed = features[symbol+"__history"], features[symbol+"__feed"]
                archive_ref = next(r for r in account["cache"] if r["session"] == scene and r["symbol"] == symbol)
                archive_path = ROOT/archive_ref["path"]
                assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == archive_ref["sha256"]
                with np.load(archive_path, allow_pickle=False) as archive:
                    orders, parents = archive["S03__core_orders"], archive["S03__core_trades"]
                for parent in parents:
                    cid, begin, last, side = map(int, parent[:4])
                    owned = orders[orders[:, 2] == cid]
                    entry = owned[owned[:, 7] == 1][0]
                    close = owned[owned[:, 7] == 0]
                    source = int(entry[1])
                    notice = feed[(feed[:, 0] == source) & (feed[:, 7] == 1)]
                    assert len(notice) == 1
                    own_width = notice[0, 9]
                    boundary = int(close[-1, 1])
                    anchor = market[begin]
                    allowed = anchor[11] == 1. and np.isfinite(anchor[:4]).all() and anchor[3] > 0
                    elapsed, latest = -np.inf, -np.inf
                    events = {}
                    # ----------------------------------------
                    # 元の全返済判断より後は新たな途中判断の候補に含めない。
                    if allowed:
                        for i in range(begin+1, boundary):
                            known = market[i, 11] == 1. and np.isfinite(market[i, :2]).all()
                            good = quotes["quote_valid"][i] and np.isfinite(quotes["bid"][i]) and np.isfinite(quotes["ask"][i])
                            good = good and 0 < quotes["bid"][i] < quotes["ask"][i]
                            known = known and market[i, 8] > anchor[8]
                            own_progress = side*(market[i, 0]-anchor[0])/own_width
                            peer_progress = side*(market[i, 1]-anchor[1])/anchor[3]
                            condition = known and good and own_progress <= -.25 and peer_progress >= .25
                            if not condition or (i > begin+1 and ready["time_s"][i]-ready["time_s"][i-1] > 15):
                                elapsed = -np.inf
                            if condition:
                                if not np.isfinite(elapsed):
                                    elapsed = ready["time_s"][i]
                                duration = ready["time_s"][i]-elapsed
                                latest = max(latest, duration)
                                for seconds in (0, 60, 120):
                                    name = str(seconds)
                                    if name not in events and duration >= seconds:
                                        events[name] = dict(row=i, time=clock(ready["time_s"][i]),
                                            own=finite(market[i, 0]), peer=finite(market[i, 1]),
                                            own_progress=finite(own_progress), peer_progress=finite(peer_progress),
                                            bid=finite(quotes["bid"][i]), ask=finite(quotes["ask"][i]),
                                            own20=finite(history[i, 7]), peer20=finite(history[i, 11]))
                    results.append(dict(session=scene, symbol=symbol, parent=cid, side=side,
                        entry_time=clock(ready["time_s"][begin]), entry=float(entry[5]),
                        exit_time=clock(ready["time_s"][last]), exit=float(parent[6]),
                        net=float(parent[9]), initial_atr=float(own_width), anchor_known=bool(allowed),
                        entry_own20=finite(history[source, 7]), entry_peer20=finite(history[source, 11]),
                        events=events, longest_seconds=0. if not np.isfinite(latest) else float(latest)))
        print(scene, len(results), "旧保存親", flush=True)
    summaries = []
    for symbol in ("TOPIX", "NK225"):
        all_items = [r for r in results if r["symbol"] == symbol]
        for seconds in (0, 60, 120):
            chosen = [r for r in all_items if str(seconds) in r["events"]]
            summaries.append(dict(symbol=symbol, seconds=seconds, total=len(all_items), matches=len(chosen),
                wins=sum(r["net"] > 0 for r in chosen), losses=sum(r["net"] < 0 for r in chosen),
                old_final_net=sum(r["net"] for r in chosen),
                examples=sorted(chosen, key=lambda r: abs(r["net"]), reverse=True)[:6]))
    target = HERE/"旧日中の自己失敗と相手進行の全94親分類.json"
    assert not target.exists()
    output = dict(passed=True, financial_replays=0, order_generation=0, parents=results,
        summary=summaries, packet_references=refs,
        condition="実約定時の各Lastを起点に自己が−0.25初期ATR以下、相手が＋0.25相手初期ATR以上。元最終返済判断前だけ。",
        caution="保存親の最終損益による事後分類。新条件での退出損益ではない。新しい出口・後続参加は未実行。")
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
