"""市場時計と因果特徴を、金融再生なしで独立照合する。"""

import ast
import copy
from datetime import datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time as clock
from zoneinfo import ZoneInfo
import numpy as np


HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import features131


CHECKS = []
JST = ZoneInfo("Asia/Tokyo")


def check(name, condition):
    """
    機能: 独立期待値との一致を検査して項目を残す。
    引数: name(str)は項目名、condition(bool)は検査結果。
    返り値: None。不一致ならAssertionError。
    """
    ok = bool(condition)
    CHECKS.append({"項目": name, "合格": ok})
    assert ok, name


def epoch(day, hour, minute, zone="Asia/Tokyo"):
    """
    機能: 暦と現地時計をUnix時刻へ変換する。
    引数: day(str)、hour/minute(int)、zone(str)は現地日付と時分・IANA地域。
    返り値: floatは秒時刻。
    """
    return datetime.combine(datetime.fromisoformat(day).date(), time(hour, minute), ZoneInfo(zone)).timestamp()


def clock_checks():
    """
    機能: 全13区分、休日、同一境界、欧米の夏時間が別週に変わる例を検証する。
    引数: なし。
    返り値: None。
    """
    check("区分数は13", len(features131.PHASES) == 13)
    for date in ("2026-09-24", "2026-10-20"):
        ticks = []
        expected = []
        for hour, minute, before, after in ((9, 0, 0, 1), (11, 30, 1, 2), (12, 30, 2, 3), (15, 25, 3, 4)):
            edge = epoch(date, hour, minute)
            ticks.extend([edge-.001, edge, edge, edge+.001])
            expected.extend([before, after, after, after])
        ready = {"session": date+"_Day", "time_s": np.array(ticks)}
        check(date+"日中各境界の前・等号・同時計・後", np.array_equal(features131.phases(ready), expected))
        altered = dict(ready, last=np.full(len(ticks), 999999.), final_direction=-1, net=-1e9)
        check(date+"日中は価格と場末分類に不変", np.array_equal(features131.phases(ready), features131.phases(altered)))
    for date in ("2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12"):
        times = np.array([epoch(date, 8, 45), epoch(date, 9, 0), epoch(date, 11, 30), epoch(date, 12, 30), epoch(date, 15, 35)])
        check(date+"現物休場でも先物日中の独立区分", np.all(features131.phases({"session": date+"_Day", "time_s": times}) == 5))
    for date, expected_open, expected_euro in (
        ("2026-09-21", "22:30", "00:30"),
        ("2026-10-12", "22:30", "00:30"),
        ("2026-10-23", "22:30", "00:30"),
        ("2026-10-26", "22:30", "01:30"),
        ("2026-11-02", "23:30", "01:30"),
    ):
        opening = epoch(date, 9, 30, "America/New_York")
        euro = epoch(date, 16, 30, "Europe/London")
        check(date+"米国開始の独立期待時刻", datetime.fromtimestamp(opening, JST).strftime("%H:%M") == expected_open)
        check(date+"欧州終了の独立期待時刻", datetime.fromtimestamp(euro, JST).strftime("%H:%M") == expected_euro)
        bounds = [opening-3600., opening, opening+1800., euro, opening+19800., opening+23400.]
        timestamps, expected = [], []
        for j, boundary in enumerate(bounds):
            timestamps.extend([boundary-.001, boundary, boundary, boundary+.001])
            expected.extend([6+j, 7+j, 7+j, 7+j])
        ready = {"session": date+"_Night", "time_s": np.array(timestamps), "us_open": opening}
        check(date+"夜間全境界の前・等号・同時計・後", np.array_equal(features131.phases(ready), expected))
        altered = dict(ready, final_direction=1, last=np.full(len(timestamps), 1e8))
        check(date+"夜間区分は場末方向と価格を参照しない", np.array_equal(features131.phases(ready), features131.phases(altered)))


def synthetic():
    """
    機能: 同時計原行、欠測、60秒境界を含む二商品人工資料を作る。
    引数: なし。
    返り値: dictは金融注文に使わない人工packet。
    """
    date = "2026-09-24"
    start = epoch(date, 8, 45)
    offsets = np.sort(np.r_[np.arange(0., 10801., 10.), 180., 180., 1800., 1800., 3780.])
    packet = {"inputs": {}, "quotes": {}}
    for symbol, base in (("TOPIX", 4000.), ("NK225", 65000.)):
        key = date+"_Day", symbol
        mid = base + np.sin(offsets/200.)*10 + offsets*.01
        ready = dict(session=key[0], symbol=symbol, start=start, limit=start+24500., tick=.5,
                     time_s=start+offsets, last=mid+99., atr=np.full(len(mid), 4.),
                     final_direction=999, final_close=999999.)
        quote = dict(bid=mid-.5, ask=mid+.5, quote_valid=np.ones(len(mid), dtype=bool))
        quote["quote_valid"][60] = False
        quote["ask"][80] = quote["bid"][80]
        packet["inputs"][key] = ready
        packet["quotes"][key] = quote
    return packet


def sliced(packet, cutoff):
    """
    機能: 両商品の未来原行を捨てる。元入力を変えない。
    引数: packet(dict)、cutoff(float)は入力と残す最終時刻。
    返り値: dictは接頭辞だけの資料。
    """
    result = copy.deepcopy(packet)
    for key, ready in packet["inputs"].items():
        mask = ready["time_s"] <= cutoff
        for name, values in ready.items():
            if isinstance(values, np.ndarray) and values.ndim and len(values) == len(mask):
                result["inputs"][key][name] = values[mask].copy()
        for name, values in packet["quotes"][key].items():
            result["quotes"][key][name] = values[mask].copy()
    return result


def check_features(packet, label, cuts):
    """
    機能: 未来切断・未来毒化・未使用終値変更・資料時刻と気配中値の整合を確かめる。
    引数: packet(dict)、label(str)、cuts(list[float])は素材・検査名・場開始からの切断秒。
    返り値: None。金融処理は呼ばない。
    """
    complete = features131.build(packet)
    for key, ready in complete[0].items():
        times = ready["time_s"]
        quote = packet["quotes"][key]
        good = quote["quote_valid"] & np.isfinite(quote["bid"]) & np.isfinite(quote["ask"])
        good &= (quote["ask"] > quote["bid"]) & (quote["bid"] > 0.)
        check(label+str(key)+"気配中値の選択", np.allclose(ready["last"][good], (quote["bid"][good]+quote["ask"][good])*.5, equal_nan=True))
        check(label+str(key)+"不適格気配は未知", np.isnan(ready["last"][~good]).all())
        check(label+str(key)+"ATRは過去準備値のまま", np.array_equal(ready["atr"], packet["inputs"][key]["atr"], equal_nan=True))
        market = complete[1][key]
        valid = np.isfinite(market[:,8])
        check(label+str(key)+"相手短期は厳密過去", np.all(market[valid,8] < times[valid]))
        valid = np.isfinite(market[:,9])
        check(label+str(key)+"30秒窓端も厳密過去", np.all(market[valid,9] < times[valid]-30.))
        history = complete[2][key]
        valid = np.isfinite(history[:,9])
        check(label+str(key)+"自己履歴は足終端60秒後", np.all(history[valid,9] <= times[valid]-60.))
        valid = np.isfinite(history[:,14])
        check(label+str(key)+"相手履歴は足終端120秒後", np.all(history[valid,14] <= times[valid]-120.))
    for seconds in cuts:
        cutoff = min(v["start"]+seconds for v in packet["inputs"].values())
        prefix = features131.build(sliced(packet, cutoff))
        toxic = copy.deepcopy(packet)
        for key, ready in toxic["inputs"].items():
            future = ready["time_s"] > cutoff
            ready["last"][future] = 987654.
            ready["atr"][future] = np.nan
            ready["final_direction"] = -999
            ready["final_close"] = -999999.
            q = toxic["quotes"][key]
            q["bid"][future] = 999999.
            q["ask"][future] = 999990.
            q["quote_valid"][future] = False
        poisoned = features131.build(toxic)
        for key in packet["inputs"]:
            count = len(prefix[0][key]["time_s"])
            for part in (1, 2, 3):
                check(label+str(key)+f"切断{seconds}部{part}", np.allclose(complete[part][key][:count], prefix[part][key], equal_nan=True))
                check(label+str(key)+f"毒化{seconds}部{part}", np.allclose(complete[part][key][:count], poisoned[part][key][:count], equal_nan=True))


def main():
    """
    機能: 独立監査と入力源の指紋を新規証跡へ保存する。
    引数: なし。
    返り値: None。
    """
    clock_checks()
    packet = synthetic()
    check_features(packet, "人工", [179.999, 1800., 3780.])
    full = features131.build(packet)
    for key, ready in packet["inputs"].items():
        cut = int(np.flatnonzero(ready["time_s"] == ready["start"]+1800.)[0])+1
        prefix = sliced(packet, ready["start"]+1800.)
        for column, values in prefix["inputs"][key].items():
            if isinstance(values, np.ndarray):
                prefix["inputs"][key][column] = values[:cut].copy()
        for column, values in prefix["quotes"][key].items():
            prefix["quotes"][key][column] = values[:cut].copy()
        partial = features131.build(prefix)
        for part in (1, 2, 3):
            check(str(key)+f"同時刻の後続自己原行を除去_部{part}", np.allclose(full[part][key][:cut], partial[part][key], equal_nan=True))
    # ----------------------------------------
    # 新規金融再生をせず、作者と違う日中・夜間の特徴だけを照合する。
    registry_path = ROOT/"work/daynight128_20261020/入力準備.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    used = []
    for ref in registry["packets"]:
        if ref["session"] not in ("2026-09-24_Day", "2026-10-14_Night"):
            continue
        path = ROOT/ref["path"]
        check(ref["session"]+"保存入力指紋", hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"])
        packet = pickle.loads(path.read_bytes())
        if ref["session"].endswith("_Night"):
            for key, ready in packet["inputs"].items():
                check(str(key)+"保存米開始時計", ready["us_open"] == epoch("2026-10-14",9,30,"America/New_York"))
        check_features(packet, ref["session"], [5400.])
        used.append(ref)
    paths = [HERE/"features131.py", HERE/"common131.py",
             ROOT/"work/visual_pdca129_20261020/features129.py",
             ROOT/"work/visual_pdca129_20261020/common129.py",
             ROOT/"work/daynight128_20261020/features128.py",
             ROOT/"work/daynight128_20261020/common128.py"]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value,str)]
        banned = ("final_direction", "final_close", "ニュース", "事前予定_方向数値なし", "全条件の会計", "全場比較")
        check(path.name+"結果とニュース方向への依存なし", not any(x in text for x in banned for text in literals))
    result = {
        "passed": True, "金融再生数": 0, "実測検査数": len(CHECKS),
        "checks": CHECKS, "入力": used,
        "sourceSHA": [{"path":p.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
        "監査コードSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "制限": "対象期間の休日4日を固定した比較。未知年の休日を自動取得する実装ではない。原時計と実受信順の一致は証明しない。寄付後30分・引け前1時間は研究上の区切り。",
    }
    target = Path(__file__).parent/f"13時間区分と未来切断の独立監査_{clock.time_ns()}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed":True,"checks":len(CHECKS),"proof":target.relative_to(ROOT).as_posix()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
