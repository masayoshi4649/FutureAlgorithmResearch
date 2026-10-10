"""公表HTMLの埋込会計・売買時刻・五分足と説明を固定台帳へ独立照合する。"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re

import numpy as np

from audit_all import read, digest
from independent_account import near, save


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
OUT = ROOT/"アルゴリズム調査/00066_ティック入口とIFDトレール"
MAIN = OUT/"ティック入口とIFDトレールの損益.html"
ALL = OUT/"全192条件の比較.html"


def embedded(path: Path) -> tuple[dict, str]:
    """機能: HTMLのJSONデータを直接取り出し、表示用変換前の保存値を読む。

    引数: path(Path)。返り値: 埋込辞書とHTMLソース(tuple[dict,str])。
    """
    source = path.read_text(encoding="utf-8")
    matches = re.findall(r'<script\b[^>]*type="application/json"[^>]*>(.*?)</script>', source, flags=re.S)
    assert len(matches) == 1
    return json.loads(matches[0]), source


def check_method(method: dict, original: dict, inputs: dict, sessions: list[str]) -> dict:
    """機能: 公表四手法と事後例の全場・全期間・週・全売買を固定保存値へ照合する。

    引数: method/original/inputs(dict)、sessions(list[str])。返り値: 検査件数(dict)。
    """
    assert method["config"] == original["config"]
    assert method["rows"] == original["rows"]
    assert method["periods"] == original["periods"]
    assert method["id"] == original["config"]["id"]
    ledger = read(WORK/"ledgers"/(method["id"]+".pkl"))
    assert set(method["orders"]) == {"|".join(key) for key in ledger}
    total_orders = 0
    for key, account in ledger.items():
        values = method["orders"]["|".join(key)]
        expected = account["orders"]
        assert len(values) == len(expected)
        if values:
            np.testing.assert_array_equal(np.asarray(values)[:, :8], expected)
            np.testing.assert_array_equal(np.asarray(values)[:, 8], inputs[key]["time_s"][expected[:, 0].astype(int)])
        total_orders += len(values)
    for symbol in ("TOPIX", "NK225"):
        groups = {}
        for session in sessions:
            day = date.fromisoformat(session[:10])
            monday = day-timedelta(days=day.weekday())
            groups.setdefault(monday, []).append(session)
        weeks = method["weeks"][symbol]
        assert len(weeks) == len(groups)
        for week, (monday, names) in zip(weeks, sorted(groups.items())):
            assert week["label"] == f"{monday:%m/%d}週（{len(names)}場）"
            rows = [row for row in method["rows"] if row["session"] in names and row["symbol"] == symbol]
            for name in ("gross", "fees", "net", "profit", "loss", "wins", "losses", "flats", "trades",
                "winning_lots", "losing_lots", "flat_lots", "net_ticks", "ideal_net"):
                near(sum(row[name] for row in rows), week[name], "公表週合計:"+name)
            assert sum(row["trades"] > 0 for row in rows) == week["active_sessions"]
            assert sum(row["net"] > 0 for row in rows) == week["positive_sessions"]
        near(sum(week["net"] for week in weeks), method["periods"]["全28"][symbol]["net"], "週合計と全28")
    return dict(ID=method["id"], 場会計数=len(method["rows"]), 注文数=total_orders, 週商品数=sum(len(x) for x in method["weeks"].values()), 合格=True)


def check_candles(bars: dict, sessions: list[str]) -> int:
    """機能: 描画用五分足を読み取り専用の元CSVの全OHLC・時刻へ照合する。

    引数: bars(dict)、sessions(list[str])。返り値: 照合した足数(int)。
    """
    assert len(bars) == 56
    count = 0
    for session in sessions:
        for symbol in ("TOPIX", "NK225"):
            path = ROOT/"candle_5min"/symbol/(session+".csv")
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = [[datetime.fromisoformat(row["time"]).timestamp(), float(row["open"]), float(row["high"]),
                    float(row["low"]), float(row["close"])] for row in csv.DictReader(stream)]
            assert rows == bars[session+"|"+symbol]
            count += len(rows)
    return count


def main() -> None:
    """機能: 公表二HTMLの全埋込数値と親子条件・事後選択の説明を点検する。

    引数: なし。返り値: なし(None)。
    """
    main_data, main_source = embedded(MAIN)
    all_data, all_source = embedded(ALL)
    fixed = read(WORK/"事前固定.json")
    selection = read(WORK/"機構別の前半選定.json")
    inputs = read(WORK/"prepared/inputs.pkl")
    originals = {config["id"]:read(WORK/"results"/(config["id"]+".json")) for config in fixed["条件"]}
    assert main_data["sessions"] == all_data["sessions"] == fixed["全セッション"]
    assert [method["id"] for method in main_data["methods"]] == [s["id"] for s in selection["選定"]]
    assert len(main_data["methods"]) == 4
    assert all_data["selectedIds"] == [s["id"] for s in selection["選定"]]
    assert len(all_data["methods"]) == 192
    assert {method["config"]["id"] for method in all_data["methods"]} == set(originals)
    assert all(method == originals[method["config"]["id"]] for method in all_data["methods"])
    checks = [check_method(method, originals[method["id"]], inputs, fixed["全セッション"]) for method in main_data["methods"]]
    exploratory = main_data["exploratory"]
    assert exploratory["id"] not in all_data["selectedIds"]
    checks.append(check_method(exploratory, originals[exploratory["id"]], inputs, fixed["全セッション"]))
    assert all(exploratory["periods"]["全28"][symbol]["net"] > 0 for symbol in ("TOPIX", "NK225"))
    assert all(exploratory["periods"]["全28"][symbol]["payoff"] < 1 for symbol in ("TOPIX", "NK225"))
    assert all(exploratory["periods"]["全28"][symbol]["without_best_session"] < 0 for symbol in ("TOPIX", "NK225"))
    assert all(method["periods"]["全28"][symbol]["net"] < 0 for method in main_data["methods"] for symbol in ("TOPIX", "NK225"))
    candles = check_candles(main_data["bars"], fixed["全セッション"])
    assert main_data["conditionsUrl"] == ALL.name and all_data["mainUrl"] == MAIN.name
    notes = "\n".join(main_data["notes"])
    assert "親予約時点" in notes and "実約定価格で再設定しません" in notes
    assert "中値へ置換" in notes and "実際に約定できる成績でもありません" in notes
    assert "参照ラージ" in notes and "原本行順" in notes
    assert "2呼値の順行を新規逆指値で待つ" not in main_source
    assert "事後" in main_source and "前半だけで選んだ" in main_source
    assert main_data["live"]["evaluated"] is False and main_data["live"]["現在板取得回数"] == 0
    save(HERE/"報告説明の点検.json", dict(合格=True, 主4手法と事後例の場会計数=sum(check["場会計数"] for check in checks),
        公表注文数=sum(check["注文数"] for check in checks), 全条件数=len(all_data["methods"]), 五分足数=candles,
        手法=checks, 説明点検=["親逆指値は候補時気配のstop", "2呼値追従は親trailだけ", "子は親予約時の絶対価格",
            "子監視は新規約定後の次行", "主4と事後黒字例を区別", "事後例は損小利大未達・最大勝ち場依存",
            "中値感度は固定注文の非実行可能な参考", "参照ラージ気配", "現在場未検証"],
        主HTML_SHA256=digest(MAIN), 全条件HTML_SHA256=digest(ALL), 報告生成SHA256=digest(WORK/"report.py"),
        監査SHA256=digest(Path(__file__))))
    print("公表HTML会計・全売買・五分足と説明の点検合格", flush=True)


if __name__ == "__main__":
    main()
