"""第一巡の夜間二候補を保存注文から具体診断する。新しい売買は再生しない。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
JST = timezone(timedelta(hours=9))
METHODS = ("N07", "N05")
REASONS = {32: "初期又は負値の停止線", 70: "正値の追尾線", 71: "帯中心",
           72: "両市場二分逆行", 93: "場末", 94: "米開始静観"}


def read(path: Path, sources: list) -> bytes:
    """
    機能: 保存資料を読み、出典指紋を記録する。
    引数: path(Path)は保存資料、sources(list)は記録先。
    返り値: bytesは保存内容。
    """
    raw = path.read_bytes()
    sources.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(raw).hexdigest()))
    return raw


def stamp(value: float) -> str:
    """
    機能: 保存価格時計を日本時刻で表記する。
    引数: value(float)はＵｎｉｘ秒。
    返り値: strは日本時刻。受信時計とは同一視しない。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def safe(value):
    """
    機能: 未知の数値を欠測として残す。
    引数: value(float)は数値又は非有限値。
    返り値: float|Noneは実測値又は欠測。
    """
    return float(value) if np.isfinite(value) else None


def aggregate(rows: list) -> dict:
    """
    機能: 保存取引を失敗機構別に要約する。
    引数: rows(list[dict])は診断対象の完結取引。
    返り値: dictは件数・収支・正負・矛盾信号等。
    """
    losses = [r for r in rows if r["net"] < 0]
    known_reverse = [r for r in rows if r["entry_known_two_minute_reverse"]]
    instant = [r for r in rows if r["exit_row"] == r["entry_row"]+1]
    reasons = defaultdict(list)
    modes = defaultdict(list)
    for row in rows:
        reasons[row["reason"]].append(row)
        modes[row["mode"]].append(row)
    return dict(trades=len(rows), net=sum(r["net"] for r in rows),
        fees=sum(r["fee"] for r in rows), gross=sum(r["gross"] for r in rows),
        last_direction=sum(r["last_direction"] for r in rows),
        entry_quote_difference=sum(r["entry_quote_difference"] for r in rows),
        exit_quote_difference=sum(r["exit_quote_difference"] for r in rows),
        wins=sum(r["net"]>0 for r in rows), losses=len(losses),
        loss_never_positive=sum(r["mfe_points"]<=0 for r in losses),
        loss_below_activation=sum(r["mfe_points"]<1.5*r["width"] for r in losses),
        loss_mfe_ge_width=sum(r["mfe_points"]>=r["width"] for r in losses),
        known_reverse_at_entry=dict(trades=len(known_reverse), net=sum(r["net"] for r in known_reverse)),
        exit_on_next_row=dict(trades=len(instant),net=sum(r["net"] for r in instant)),
        exit_reasons=[dict(reason=k,trades=len(v),net=sum(r["net"] for r in v)) for k,v in sorted(reasons.items())],
        entry_modes=[dict(mode=k,trades=len(v),net=sum(r["net"] for r in v)) for k,v in sorted(modes.items())])


def main() -> None:
    """
    機能: Ｎ０７とＮ０５の全夜間と各最悪三場について、保存時刻と気配費用を整理する。
    引数: なし。
    返り値: None。新金融再生・原市場読取・ＡＰＩ接続は零。
    """
    target = HERE / "第一巡N07とN05の具体診断.json"
    assert not target.exists()
    sources = []
    results = json.loads(read(TASK / "round1/全条件の会計.json", sources))
    inputs = json.loads(read(TASK / "入力準備.json", sources))
    references = {p["session"]:p for p in inputs["packets"]}
    rows = [r for r in results["rows"] if r["method"] in METHODS]
    expected = {(r["method"],r["session"],r["symbol"]):r for r in rows}
    caches = {(r["session"],r["symbol"]):r for r in results["cache"] if r["session"].endswith("_Night")}
    trade_rows = []
    session_rows = []
    for scene in sorted({scene for scene,symbol in caches}):
        item = references[scene]
        packet = pickle.loads(read(ROOT/item["path"],sources))
        histories = np.load(ROOT/item["features"]["path"],allow_pickle=False)
        sources.append(item["features"])
        for symbol in ("TOPIX","NK225"):
            key = scene,symbol
            ready,quotes,market = packet["inputs"][key],packet["quotes"][key],packet["markets"][key]
            history = histories[symbol+"__history"]
            times,last = ready["time_s"],ready["last"]
            mult = 1000 if symbol=="TOPIX" else 10
            item = caches[key]
            raw = read(ROOT/item["path"],sources)
            assert hashlib.sha256(raw).hexdigest()==item["sha256"]
            with np.load(ROOT/item["path"],allow_pickle=False) as archive:
                for method in METHODS:
                    orders,trades = archive[method+"__orders"],archive[method+"__trades"]
                    new = orders[orders[:,7]==1]
                    assert len(new)==len(trades)
                    selected = []
                    for cid,trade in enumerate(trades):
                        e,x,side,qty = map(int,trade[:4])
                        order = new[cid]
                        assert order[0]==e and order[2]==cid
                        decision = int(order[1])
                        assert decision<e
                        h,m = history[decision],market[decision]
                        gross,fee,net,mfe,mae,width,reason,mode = map(float,trade[6:])
                        last_component = side*(last[x]-last[e])*qty*mult
                        entry_difference = side*(trade[4]-last[e])*qty*mult
                        exit_difference = side*(last[x]-trade[5])*qty*mult
                        assert np.isclose(last_component-entry_difference-exit_difference,gross)
                        at_entry_reverse = bool(m[11]==1 and side*m[5]<-.25 and side*m[7]<-.25)
                        row = dict(method=method,session=scene,symbol=symbol,cid=cid,
                            entry_time=stamp(times[e]),exit_time=stamp(times[x]),decision_time=stamp(times[decision]),
                            entry_row=e,exit_row=x,decision_row=decision,side=side,quantity=qty,
                            direction="買い" if side>0 else "売り",entry_price=float(trade[4]),exit_price=float(trade[5]),
                            gross=gross,fee=fee,net=net,mfe_points=mfe,mae_points=mae,width=width,
                            mfe_yen=mfe*qty*mult,mae_yen=mae*qty*mult,
                            reason=REASONS.get(int(reason),str(int(reason))),mode=int(mode),
                            holding_seconds=float(times[x]-times[e]),last_direction=float(last_component),
                            entry_quote_difference=float(entry_difference),exit_quote_difference=float(exit_difference),
                            entry_known_two_minute_reverse=at_entry_reverse,
                            decision=dict(last=float(last[decision]),bid=float(quotes["bid"][decision]),ask=float(quotes["ask"][decision]),
                                atr=safe(ready["atr"][decision]),width_vs_current_atr=safe(width/ready["atr"][decision]),
                                mean20=safe(h[1]),mean20_distance_width=safe(side*(last[decision]-h[1])/width),
                                own5=safe(side*h[6]),own20=safe(side*h[7]),efficiency20=safe(h[5]),
                                peer5=safe(side*h[10]),peer20=safe(side*h[11]),peer_efficiency20=safe(h[12]),
                                own30=safe(side*m[4]),own120=safe(side*m[5]),
                                peer30=safe(side*m[6]),peer120=safe(side*m[7])),
                            fill=dict(last=float(last[e]),bid=float(quotes["bid"][e]),ask=float(quotes["ask"][e])),
                            exit=dict(last=float(last[x]),bid=float(quotes["bid"][x]),ask=float(quotes["ask"][x])))
                        trade_rows.append(row)
                        selected.append(row)
                    summary = aggregate(selected)
                    assert np.isclose(summary["net"],expected[method,scene,symbol]["net"])
                    summary.update(method=method,session=scene,symbol=symbol,
                        same_direction_after_loss=sum(a["net"]<0 and a["side"]==b["side"] for a,b in zip(selected,selected[1:])),
                        same_direction_consecutive_losses=sum(a["net"]<0 and b["net"]<0 and a["side"]==b["side"] for a,b in zip(selected,selected[1:])),
                        direction_changes=sum(a["side"]!=b["side"] for a,b in zip(selected,selected[1:])))
                    session_rows.append(summary)
        histories.close()
        print(scene,flush=True)
    summary = [dict(method=method,symbol=symbol,**aggregate([r for r in trade_rows if r["method"]==method and r["symbol"]==symbol]))
               for method in METHODS for symbol in ("TOPIX","NK225")]
    worst = [r for method in METHODS for symbol in ("TOPIX","NK225")
             for r in sorted([r for r in session_rows if r["method"]==method and r["symbol"]==symbol],key=lambda r:r["net"])[:3]]
    result = dict(passed=True,summary=summary,worst_three=worst,session_rows=session_rows,trades=trade_rows,
        sources=sources,financial_replays=0,original_market_reads=0,API=0,
        limits=["保存価格時計であり、実受信時計は未取得。",
                "最大順行は保有中の実清算側気配による順行幅。都合よく最大点で売買した成績へ変更しない。",
                "今回の診断は既知データを見た後の開発分析。対策の効果は別の事前固定比較が必要。"],
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
