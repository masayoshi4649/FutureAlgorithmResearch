"""10月22日core親0のS01/R01保存損益差を、価格経路とBBO負担へ恒等分解する。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import importlib.util
import json


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
JST = timezone(timedelta(hours=9))
POINT = 100


def clock(value: float) -> str:
    """UNIX秒を日本時間へ変換する。

    引数: value(float)はUNIX秒。返り値: strは秒までの日本時間。
    """
    return datetime.fromtimestamp(value, JST).strftime("%H:%M:%S")


def load_parent(path: Path) -> tuple[dict, dict]:
    """独立会計の対象親だけを読み、参照指紋を残す。

    引数: path(Path)は監査会計JSON。返り値: tupleはcore親0と出典。
    """
    data = path.read_bytes()
    parsed = json.loads(data)
    parent = next(p for p in parsed["parents"] if p["owner"] == "core" and p["campaign"] == 0)
    assert parent["remaining"] == 0
    return parent, {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def accounting(parent: dict, raw) -> dict:
    """保存実約定のキャッシュフローを中値と執行差へ分解する。

    引数: parent(dict)は完結親、raw(ndarray)は同一原行採番。
    返り値: dictは実収支・中値収支・BBO執行差と全移動明細。
    """
    actual = mid_profit = 0.0
    moves = []
    quantity = 0
    for event in parent["movements"]:
        index = event["index"]
        bid, ask = float(raw[index, 2]), float(raw[index, 3])
        assert 0 < bid < ask
        mid = (bid + ask) / 2
        change = event["quantity"] * (1 if event["action"] == "new" else -1)
        fill_side = parent["side"] if change > 0 else -parent["side"]
        expected = ask if fill_side == 1 else bid
        assert expected == event["price"]
        cash = -parent["side"] * change * event["price"] * POINT
        mid_cash = -parent["side"] * change * mid * POINT
        actual += cash
        mid_profit += mid_cash
        quantity += change
        assert quantity >= 0
        moves.append({**event, "clock":clock(raw[index, 0]), "time":float(raw[index, 0]),
                      "mid":mid, "bid":bid, "ask":ask, "change":change,
                      "after_quantity":quantity, "actual_cashflow":cash,
                      "mid_cashflow":mid_cash, "execution_difference":cash-mid_cash})
    assert quantity == 0
    assert abs(actual-parent["net"]) < 1e-6
    return {"actual_net":actual,"mid_net":mid_profit,"execution_difference":actual-mid_profit,
            "new_events":sum(m["action"] == "new" for m in moves),
            "new_quantity":sum(m["quantity"] for m in moves if m["action"] == "new"),"moves":moves}


def main() -> None:
    """原板と保存約定だけで35.5万円差の経路恒等式を検算し保存する。

    引数: なし。返り値: None。注文判断や新しい取引経路を生成しない。
    """
    spec = importlib.util.spec_from_file_location("analyze156", BASE/"analyze156.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((BASE/"inputs156.json").read_text(encoding="utf-8"))
    scene = next(s for s in manifest["sessions"] if s["session"] == "2026-10-22_Day")
    raw, raw_audit = module.raw_quotes(scene)
    source_paths = {"S01":BASE/"audit/cases/2026-10-22_Day/S01.json",
                    "R01":BASE/"round2/audit/cases/2026-10-22_Day/R01.json"}
    parents, sources, accounts = {}, {}, {}
    for method, path in source_paths.items():
        parents[method], sources[method] = load_parent(path)
        accounts[method] = accounting(parents[method], raw)
    assert parents["S01"]["side"] == parents["R01"]["side"] == -1
    side = -1
    changes = {name:defaultdict(int) for name in accounts}
    indices = set()
    for method, account in accounts.items():
        for move in account["moves"]:
            changes[method][move["index"]] += move["change"]
            indices.add(move["index"])
    indices = sorted(indices)
    quantities = {"S01":0,"R01":0}
    sums = defaultdict(float)
    intervals = []
    path_mid = {"S01":0.0,"R01":0.0}
    for index, finish in zip(indices[:-1],indices[1:]):
        for method in quantities:
            quantities[method] += changes[method][index]
        q_s, q_r = quantities["S01"], quantities["R01"]
        mid0, mid1 = float(raw[index,2:4].mean()), float(raw[finish,2:4].mean())
        move = side * (mid1-mid0)
        pnl_s, pnl_r = q_s * move * POINT, q_r * move * POINT
        path_mid["S01"] += pnl_s
        path_mid["R01"] += pnl_r
        category = ("R無保有_S保有" if q_s > 0 and q_r == 0 else
                    "双方保有_数量差" if q_s > 0 and q_r > 0 else
                    "Rのみ保有" if q_r > 0 else "双方無保有")
        delta = pnl_r-pnl_s
        sums[category] += delta
        intervals.append({"start_index":index,"end_index":finish,"start":clock(raw[index,0]),"end":clock(raw[finish,0]),
                          "start_time":float(raw[index,0]),"end_time":float(raw[finish,0]),"mid_start":mid0,"mid_end":mid1,
                          "short_directional_change":move,"s01_quantity":q_s,"r01_quantity":q_r,
                          "s01_mid_pnl":pnl_s,"r01_mid_pnl":pnl_r,"r01_minus_s01":delta,"category":category})
    for method in quantities:
        quantities[method] += changes[method][indices[-1]]
        assert quantities[method] == 0
        assert abs(path_mid[method]-accounts[method]["mid_net"]) < 1e-6
    spread_delta = accounts["R01"]["execution_difference"]-accounts["S01"]["execution_difference"]
    actual_delta = accounts["R01"]["actual_net"]-accounts["S01"]["actual_net"]
    reconstructed = sum(sums.values())+spread_delta
    assert abs(reconstructed-actual_delta) < 1e-6
    assert actual_delta == -355000
    out = {"spec":{"session":"2026-10-22_Day","owner":"core","campaign":0,"side":-1,"point_yen":100,
                    "partition":"全約定原行添字の和集合。各添字の全約定後枚数で次約定添字までの中値変化を評価",
                    "range":"両親の初回の早い方から最終返済の遅い方まで。片側の完済後は0枚",
                    "identity":"R実損益−S実損益＝R無保有時の差＋双方保有時の数量差＋Rのみ保有時の差＋BBO執行差の差",
                    "new_trading_replay":False,"causal_attribution":"保存経路の会計恒等式。別の入口なら得た利益という因果反実仮想ではない"},
           "sources":sources,"raw":raw_audit,"accounts":accounts,"mid_path_checks":path_mid,
           "delta_components":dict(sums),"execution_delta":spread_delta,"actual_delta":actual_delta,
           "reconstructed_delta":reconstructed,"intervals":intervals,
           "largest_negative_intervals":sorted(intervals,key=lambda x:x["r01_minus_s01"])[:8]}
    target = HERE/"10月22日core損益差の恒等分解156.json"
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    s,r = accounts["S01"],accounts["R01"]
    lines = ["# 10月22日 core親0の35.5万円差", "", "**同じ最初の売りから、S01は+361,000円、R01は+6,000円。差は−355,000円。** 保存約定と同じラージ気配だけを読み、次の恒等式で全額一致した。", "",
             "| 項目 | S01 | R01 | R01−S01 |", "|---|---:|---:|---:|",
             f'| 中値で数えた経路損益 | {s["mid_net"]:,.0f}円 | {r["mid_net"]:,.0f}円 | {r["mid_net"]-s["mid_net"]:+,.0f}円 |',
             f'| 実気配での執行差 | {s["execution_difference"]:,.0f}円 | {r["execution_difference"]:,.0f}円 | {spread_delta:+,.0f}円 |',
             f'| 保存約定の収支 | {s["actual_net"]:,.0f}円 | {r["actual_net"]:,.0f}円 | {actual_delta:+,.0f}円 |',
             "", "中値損益差の内訳（すべてR01−S01）：", "", "| 原板経路の区分 | 損益差 |", "|---|---:|"]
    for key in ("R無保有_S保有","双方保有_数量差","Rのみ保有","双方無保有"):
        lines.append(f'| {key} | {sums[key]:+,.0f}円 |')
    lines += ["",f'S01の新規は{s["new_events"]}回・延べ{s["new_quantity"]}枚、R01は{r["new_events"]}回・延べ{r["new_quantity"]}枚。手数料は0だが、売りはbid・買い返済はaskになるため回転による気配差負担は残る。',"","| 差が大きかった区間 | S01枚数 | R01枚数 | 売り方向の中値進行 | 損益差 |","|---|---:|---:|---:|---:|"]
    for interval in out["largest_negative_intervals"][:4]:
        lines.append(f'| {interval["start"]}～{interval["end"]} | {interval["s01_quantity"]} | {interval["r01_quantity"]} | {interval["short_directional_change"]:+g}pt | {interval["r01_minus_s01"]:+,.0f}円 |')
    lines += ["", "約定時刻が同秒でも原行添字を優先した。同じ添字の部分返済は合算し、約定**後**の保有枚数で次の約定までを評価。両者の最終返済が違うため、遅い方まで揃えて完済側を0枚とした。", "", "これは保存経路の会計分解であり、『待たずに再参加すれば必ずこの差を取り戻せた』という反実仮想ではない。新しい取引や注文判断は生成していない。", "", "[全区間・全約定・原板指紋](10月22日core損益差の恒等分解156.json)"]
    (HERE/"10月22日core損益差の恒等分解156.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"accounts":{k:{x:v[x] for x in ("actual_net","mid_net","execution_difference","new_events","new_quantity")} for k,v in accounts.items()},
                      "components":dict(sums),"spread_delta":spread_delta,"delta":actual_delta,"intervals":len(intervals)},ensure_ascii=True))


if __name__=="__main__":
    main()
