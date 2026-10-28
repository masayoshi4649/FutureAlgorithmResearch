"""確定した二段階の売買記録を、全玉会計の比較と資料用データへ集計する。"""

from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def read(path: Path) -> dict:
    """UTF-8の保存記録を読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path: Path) -> dict:
    """入力結果の内容指紋を計算する。

    引数: path(Path)。返り値: dictはパスとSHA256。
    """
    path = path.resolve()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream,"sha256").hexdigest()
    return {"path":path.relative_to(ROOT).as_posix(),"sha256":digest}


def clock(at: float) -> str:
    """数値時計を日本時間の日時へ変換する。

    引数: at(float)。返り値: str。
    """
    return datetime.fromtimestamp(at,JST).isoformat()


def session_row(scene: dict, case: dict) -> dict:
    """売買記録を一場一行へ集計し、主とカバーの会計を照合する。

    引数: scene/case(dict)。返り値: dict。
    """
    value = case["summary"]
    roles = value["roles"]
    profit = sum(v["profit"] for v in roles.values())
    loss = sum(v["loss"] for v in roles.values())
    assert profit-loss == value["realized"]
    assert sum(v["net"] for v in roles.values()) == value["realized"]
    assert all(v["remaining_quantity"] == 0 for v in roles.values())
    assert value["final_mark"]["equity"] == value["realized"]
    caps = value["maximum_quantities"]
    assert max(caps["occupied_buy"],caps["occupied_sell"]) <= 10 and caps["gross_held"] <= 20
    new = {e["order"]["id"]:e for e in case["events"] if e["order"]["action"] == "new"}
    closes = [e for e in case["events"] if e["order"]["action"] == "close"]
    quantity = Counter()
    decomposition = Counter()
    refs = {r["index"]:r for r in case["reference"]}
    for event in closes:
        order = event["order"]
        entry = new[order["target"]]
        category = "win" if event["gross"] > 0 else "loss" if event["gross"] < 0 else "flat"
        quantity[category] += order["quantity"]
        start = refs[entry["fill_index"]]
        end = refs[event.get("quote_index") if event.get("proxy") else event["fill_index"]]
        side = entry["order"]["side"]
        mid_pl = side*((end["bid"]+end["ask"]-start["bid"]-start["ask"])/2)*order["quantity"]*100
        spread = event["gross"]-mid_pl
        assert spread <= 0
        decomposition[order["role"]+"_mid_net"] += mid_pl
        decomposition[order["role"]+"_spread_net"] += spread
    phase_net = {phase:sum(p["net"] for p in value["parents"] if p["phase"] == phase) for phase in ("Day","preUS","postUS")}
    cover_lots = [lot for lot in case["lots"] if lot["role"] == "cover"]
    row = {"session":scene["session"],"kind":scene["kind"],"split":scene["split"],
           "profit":profit,"loss":loss,"net":value["realized"],
           "main_profit":roles["main"]["profit"],"main_loss":roles["main"]["loss"],"main_net":roles["main"]["net"],
           "cover_profit":roles["cover"]["profit"],"cover_loss":roles["cover"]["loss"],"cover_net":roles["cover"]["net"],
           "minimum_equity":value["minimum_equity"],"maximum_drawdown":value["maximum_drawdown"],
           "minimum_at":clock(value["minimum_at"]["time"]),"drawdown_at":clock(value["drawdown_to"]["time"]),
           "main_entries":value["main_entries"],"cover_entries":value["cover_entries"],
           "main_quantity":roles["main"]["initial_quantity"],"cover_quantity":roles["cover"]["initial_quantity"],
           "winning_quantity":quantity["win"],"losing_quantity":quantity["loss"],"flat_quantity":quantity["flat"],
           "maximum_buy":caps["occupied_buy"],"maximum_sell":caps["occupied_sell"],"maximum_gross":caps["gross_held"],
           "capacity_rejections":value["rejections"].get("capacity",0),"interval_rejections":value["rejections"].get("interval",0),
           "cover_capacity_rows":value["cover_capacity_evaluated_rows"],"cover_capacity_slot_rows":value["cover_capacity_slot_rows"],
           "close_reasons":value["close_reasons"],"proxy_fills":value["proxy_fills"],"end_quote_age":value["ending"]["age"],
           "cover_never_profitable":sum(lot["best"] <= 0 for lot in cover_lots),
           "cover_profitable_then_loss":sum(lot["best"] > 0 and lot["realized"] < 0 for lot in cover_lots),
           "phase_net":phase_net,**decomposition}
    for role in ("main","cover"):
        row.setdefault(role+"_mid_net",0)
        row.setdefault(role+"_spread_net",0)
        assert row[role+"_mid_net"]+row[role+"_spread_net"] == row[role+"_net"]
    return row


def summarize(rows: list[dict]) -> dict:
    """黒字頻度、損失の深さ、全玉収支を同じ場集合で集計する。

    引数: rows(list[dict])。返り値: dict。
    """
    sums = ("profit","loss","net","main_profit","main_loss","main_net","cover_profit","cover_loss","cover_net",
            "main_entries","cover_entries","main_quantity","cover_quantity","winning_quantity","losing_quantity","flat_quantity",
            "capacity_rejections","interval_rejections","cover_capacity_rows","cover_capacity_slot_rows","proxy_fills","cover_never_profitable","cover_profitable_then_loss",
            "main_mid_net","main_spread_net","cover_mid_net","cover_spread_net")
    value = {key:sum(row[key] for row in rows) for key in sums}
    nets = [row["net"] for row in rows]
    wins,losses = [n for n in nets if n > 0],[-n for n in nets if n < 0]
    value.update(sessions=len(rows),winning_sessions=len(wins),losing_sessions=len(losses),
                 flat_sessions=sum(n == 0 for n in nets),no_trade_sessions=sum(row["main_entries"] == 0 for row in rows),
                 mean_net=statistics.mean(nets),median_net=statistics.median(nets),q25_net=float(np.quantile(nets,.25)),
                 mean_winning_session=statistics.mean(wins) if wins else 0,
                 mean_losing_session=statistics.mean(losses) if losses else 0,
                 median_losing_session=statistics.median(losses) if losses else 0,
                 worst_session=min(nets),minimum_equity=min(row["minimum_equity"] for row in rows),
                 maximum_drawdown=max(row["maximum_drawdown"] for row in rows),
                 excluding_largest_win=sum(nets)-(max(wins) if wins else 0),
                 excluding_three_largest_wins=sum(nets)-sum(sorted(wins,reverse=True)[:3]),
                 profit_factor=value["profit"]/value["loss"] if value["loss"] else None)
    return value


def main() -> None:
    """両段階の終了証跡を確認して全26案・53場を一度集計する。

    引数: なし。返り値: None。入口選択・売買の再実行は行わない。
    """
    frozen_path = HERE/"results/selection_frozen162.json"
    frozen = read(frozen_path)
    records,inputs = [],[fingerprint(frozen_path)]
    for stage,expected in (("train_validation",40),("locked_test",13)):
        folder = HERE/"results"/stage
        proof_path = folder/("再生完了162_"+stage+".json")
        proof = read(proof_path)
        assert proof["completed"] and proof["returncode"] == 0 and proof["sessions"] == expected
        inputs.append(fingerprint(proof_path))
        for entry in proof["results"]:
            path = Path(entry["path"])
            info = fingerprint(path)
            assert info["sha256"] == entry["sha256"]
            inputs.append(info)
            records.append(read(path))
    records.sort(key=lambda item:item["session"])
    assert len(records) == 53 and len({r["session"] for r in records}) == 53
    methods = []
    for number,definition in enumerate(records[0]["cases"]):
        ident = definition["id"]
        assert all(scene["cases"][number]["id"] == ident for scene in records)
        rows = [session_row(scene,scene["cases"][number]) for scene in records]
        cumulative = 0
        for row in rows:
            cumulative += row["net"]
            row["cumulative"] = cumulative
        periods = {"all":summarize(rows)}
        for kind in ("Day","Night"):
            periods[kind] = summarize([r for r in rows if r["kind"] == kind])
        for split in ("train","validation","test"):
            periods[split] = summarize([r for r in rows if r["split"] == split])
        methods.append({"id":ident,"description":definition["configuration"]["definition"]["description"],
                        "configuration":definition["configuration"]["definition"],"selected":ident in frozen["selected"],
                        "rows":rows,"summary":periods})
    base = next(m for m in methods if m["id"] == "N00")
    for method in methods:
        deltas = []
        for row,b in zip(method["rows"],base["rows"]):
            assert row["session"] == b["session"]
            deltas.append({"session":row["session"],"net_delta":row["net"]-b["net"],
                           "main_net_delta":row["main_net"]-b["main_net"],"cover_net":row["cover_net"],
                           "equity_delta":row["minimum_equity"]-b["minimum_equity"],
                           "drawdown_delta":row["maximum_drawdown"]-b["maximum_drawdown"]})
        method["compared_to_N00"] = {"improved":sum(d["net_delta"] > 0 for d in deltas),
                                       "worsened":sum(d["net_delta"] < 0 for d in deltas),
                                       "unchanged":sum(d["net_delta"] == 0 for d in deltas),"rows":deltas}
    output = {"product":"NK225mini","side_cap":10,"maximum_gross":20,"fee":0,"multiplier":100,
              "selected":frozen["selected"],"known_development":True,"methods":methods,"sources":inputs}
    destination = HERE/"report_data162.json"
    with destination.open("x",encoding="utf-8") as stream:
        json.dump(output,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps({"methods":len(methods),"sessions":53,"selected":frozen["selected"],"output":str(destination)},ensure_ascii=False))


if __name__ == "__main__":
    main()
