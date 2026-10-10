"""公開資料の会計・対照・少数黒字の重複を独立監査資料へ照合する。"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re

import numpy as np

from audit_all import read, digest, material, ROOT, WORK, HERE
from combine import aggregate
from independent_account import near, save


OUT = ROOT / "アルゴリズム調査/00068_入口確認とトレーリング幅拡大"
MAIN = OUT / "入口確認と幅拡大の説明と損益.html"
ALL = OUT / "全432条件の比較.html"
SYMBOLS = ("TOPIX", "NK225")
PERIODS = ("前16", "後12", "全28", "追加1", "全29")


def payload(path: Path) -> tuple[str, dict]:
    """機能: 公開固定JSONを読取専用で取り出す。

    引数: path(Path)。返り値: HTML文字列と埋込み辞書(tuple[str,dict])。
    """
    text = path.read_text(encoding="utf-8")
    parts = re.findall(r'<script id="report-data" type="application/json">(.*?)</script>', text, re.S)
    assert len(parts) == 1
    return text, json.loads(parts[0])


def match(method: dict, packet: dict, proof: dict) -> None:
    """機能: 公開58口座と五期間を保存台帳および独立再会計へ照合する。

    引数: method/packet/proof(dict)。返り値: なし(None)。
    """
    identifier = method.get("id", method["config"]["id"])
    for field in ("config", "rows", "periods", "ledger_SHA256"):
        assert method[field] == packet[field], (identifier, field)
    assert len(method["rows"]) == 58
    assert method["config"] == proof["設定"]
    assert set(method["periods"]) == set(PERIODS)
    for period in PERIODS:
        for symbol in SYMBOLS:
            for field, value in proof["期間"][period][symbol].items():
                reported = method["periods"][period][symbol][field]
                if value is None:
                    assert reported is None
                else:
                    near(reported, value, f"公開独立期間/{identifier}/{period}/{symbol}/{field}")


def comparison_configs(fixed: dict) -> dict:
    """機能: 432条件の入口、幅だけの変更、保険対照の対応を検査する。

    引数: fixed(dict)。返り値: 合格した比較の件数と定義(dict)。
    """
    configs = {c["id"]: c for c in fixed["条件"]}
    sources = sorted({c["source"] for c in configs.values()})
    widths = [(8, 4, 8, 4), (16, 4, 8, 4), (8, 8, 8, 4),
              (16, 8, 8, 4), (24, 12, 8, 4), (16, 8, 16, 8)]
    parameters = ("kind", "stop", "activation", "trail", "hold_seconds", "grid", "step_fraction",
                  "cover_activation", "cover_trail", "basket_stop", "basket_activation", "basket_trail",
                  "flip_fraction", "partial_level", "partial_fraction", "tighten_minutes", "ratchet_step",
                  "ratchet_keep", "grid_mode", "source", "source_index", "gate_level", "entry_index")
    groups = 0
    for source in sources:
        for gate in range(4):
            base = configs[f"{source}_G{gate}_W0_H"]
            for width, expected in enumerate(widths):
                prefix = f"{source}_G{gate}_W{width}"
                h, n, d = (configs[prefix + "_" + m] for m in ("H", "N", "D"))
                assert tuple(h[f] for f in ("trail", "cover_trail", "activation", "cover_activation")) == expected
                for field in parameters:
                    if field not in ("trail", "cover_trail", "activation", "cover_activation"):
                        assert h[field] == base[field], (prefix, "幅以外の変更", field)
                    assert h[field] == n[field], (prefix, "縮小復帰対応", field)
                    assert (d[field] == 0 if field == "kind" else d[field] == h[field]), (prefix, "無保険対応", field)
                assert not h["paired"] and n["paired"] and not d["paired"]
                assert n["paired_manager"] == h["id"]
                assert h["entry_index"] == h["source_index"] * 4 + gate
                groups += 1
    return dict(合格=True, 幅と三管理の対応群=groups, 同一入口系列=24,
                W1="元玉幅だけ2倍", W2="保険幅だけ2倍", W3="両幅2倍", W4="両幅3倍",
                W5="両幅2倍に加え追跡開始も2倍。幅単独とは扱わない")


def duplicate_paths(ready: dict, lookup: dict) -> dict:
    """機能: 少数黒字T3のG0/G1を全58口座の約定と時価で比較する。

    引数: ready/lookup(dict)。返り値: 黒字条件、同一経路、件数の監査(dict)。
    """
    signals = read(WORK / "inputs/signals.pkl")
    schedules = read(WORK / "inputs/schedule.pkl")
    candidate_differences = []
    for key in ready:
        differences = np.flatnonzero(signals[key][8] != signals[key][9])
        if len(differences):
            candidate_differences.append(dict(場=key[0], 銘柄=key[1], 相違原本行=differences.tolist()))
        np.testing.assert_array_equal(schedules[key][8], schedules[key][9])
    comparisons = 0
    for width in range(6):
        for method in ("H", "N", "D"):
            left_id, right_id = (f"T3L1_G{g}_W{width}_{method}" for g in (0, 1))
            left, right = (read(WORK / "ledgers" / (identifier + ".pkl")) for identifier in (left_id, right_id))
            assert lookup[left_id]["rows"] == lookup[right_id]["rows"]
            assert lookup[left_id]["periods"] == lookup[right_id]["periods"]
            for key in ready:
                # ----------------------------------------
                # 理由文字番号は会計に影響しないが、判断行、約定行、枚数、価格、役割は全て比較する。
                columns = [0, 1, 2, 3, 4, 5, 7, 8]
                np.testing.assert_array_equal(left[key]["orders"][:, columns], right[key]["orders"][:, columns])
                np.testing.assert_array_equal(left[key]["trades"], right[key]["trades"])
                assert left[key]["curve_hash"] == right[key]["curve_hash"]
                comparisons += 1
    blacks = {period: sorted(identifier for identifier, packet in lookup.items()
                            if all(packet["periods"][period][s]["net"] > 0 for s in SYMBOLS))
              for period in ("全28", "全29")}
    r = lookup["T3L1_G1_W4_D"]
    top, nk = (r["periods"]["全28"][s] for s in SYMBOLS)
    assert top["net"] == 184068 and nk["net"] == 113840
    assert round(top["campaign_payoff"], 2) == 1.68 and round(nk["campaign_payoff"], 2) == 1.23
    assert r["periods"]["前16"]["NK225"]["campaigns"] == 6
    assert r["periods"]["前16"]["NK225"]["active_sessions"] == 5
    assert r["periods"]["前16"]["NK225"]["net"] < 0 and top["without_best_session"] < 0
    assert r["periods"]["追加1"]["TOPIX"]["net"] == 14164
    assert r["periods"]["追加1"]["NK225"]["campaigns"] == 0
    return dict(合格=True, T3のG0とG1の初回入口列一致口座=58, 予約されなかった候補信号の相違=candidate_differences,
                幅管理別売買時価一致口座=comparisons,
                黒字条件=blacks, 参考="T3L1_G1_W4_D", 参考五期間=r["periods"],
                結論="G0/G1重複は独立成功例ではない。参考は最低入口数未達、NK前半赤字、TOP最大黒字場除外で赤字")


def main() -> None:
    """機能: 公開三代表、全432、五分足、幅対照、参考例を最終照合する。

    引数: なし。返り値: なし(None)。監査領域だけにJSONを保存する。
    """
    main_text, D = payload(MAIN)
    all_text, A = payload(ALL)
    fixed, selected = (read(WORK / f) for f in ("事前固定.json", "前半選定.json"))
    proof = read(HERE / "全条件の独立監査.json")
    assert proof["合格"] and proof["口座数"] == 25056
    independent = {r["ID"]: r for r in proof["条件"]}
    lookup = {p.stem: read(p) for p in sorted((WORK / "results").glob("*.json"))}
    ready, _ = material()
    sessions = fixed["全セッション"] + fixed["追加追試"]
    assert D["sessions"] == A["sessions"] == sessions and len(sessions) == 29
    assert [m["id"] for m in D["methods"]] == [r["id"] for r in selected["代表"]] == A["selectedIds"]
    assert len(D["methods"]) == 3 and len(A["methods"]) == 432
    assert {m["id"] for m in A["methods"]} == set(lookup) == set(independent)
    for method in A["methods"]:
        match(method, lookup[method["id"]], independent[method["id"]])
    comparisons = comparison_configs(fixed)
    save(HERE / "入口と幅の比較対応監査.json", comparisons)
    duplicates = duplicate_paths(ready, lookup)
    save(HERE / "少数黒字経路の重複監査.json", duplicates)
    diagnostic = read(WORK / "analysis/入口方向の独立診断.json")["集計"]
    dates = {}
    for session in sessions:
        day = date.fromisoformat(session[:10])
        dates.setdefault(day - timedelta(days=day.weekday()), []).append(session)
    assert len(dates) == 3
    order_count = 0
    for method in D["methods"]:
        identifier, c = method["id"], method["config"]
        match(method, lookup[identifier], independent[identifier])
        assert method["eligible"] is False and selected["採用条件充足"] is False
        prefix = identifier.rsplit("_", 1)[0]
        for field, expected_id in (("baseline", selected["基準"]), ("control", prefix + "_D"), ("netControl", prefix + "_N")):
            assert method[field] == lookup[expected_id]
            match(method[field], lookup[expected_id], independent[expected_id])
        assert [w["config"]["id"] for w in method["widthComparisons"]] == [f"{c['source']}_G{c['gate_level']}_W{w}_H" for w in range(6)]
        for comparison in method["widthComparisons"]:
            cid = comparison["config"]["id"]
            assert comparison == lookup[cid]
            match(comparison, lookup[cid], independent[cid])
        assert method["entryDiagnostic"] == diagnostic[f"{c['source']}_G{c['gate_level']}"]
        assert method["baseEntryDiagnostic"] == diagnostic[c["source"] + "_G0"]
        ledger = read(WORK / "ledgers" / (identifier + ".pkl"))
        assert set(method["orders"]) == {"|".join(k) for k in ready}
        for key, account in ledger.items():
            expected = [list(o) + [float(ready[key]["time_s"][int(o[0])])] for o in account["orders"]]
            assert method["orders"]["|".join(key)] == expected
            order_count += len(expected)
        for symbol in SYMBOLS:
            assert len(method["weeks"][symbol]) == len(dates)
            for week, (monday, keys) in zip(method["weeks"][symbol], sorted(dates.items())):
                assert week["label"] == f"{monday:%m/%d}週（{len(keys)}場）"
                # ----------------------------------------
                # 期間会計の独立集計器を、公開場別行の同じ週集合へ適用する。
                a = aggregate(method["rows"], keys, symbol, ready)
                for field, value in a.items():
                    if value is None:
                        assert week[field] is None
                    else:
                        near(week[field], value, "公開週/" + field)
            for field in ("profit", "loss", "net", "fees", "campaign_profit", "campaign_loss", "campaigns", "winning_lots", "losing_lots"):
                near(sum(week[field] for week in method["weeks"][symbol]), method["periods"]["全29"][symbol][field], "全29週合計")
    bar_count = 0
    assert set(D["bars"]) == {f"{session}|{symbol}" for session in sessions for symbol in SYMBOLS}
    for session in sessions:
        for symbol in SYMBOLS:
            path = ROOT / "candle_5min" / symbol / (session + ".csv")
            with path.open(encoding="utf-8-sig", newline="") as stream:
                expected = [[datetime.fromisoformat(r["time"]).timestamp(), *[float(r[k]) for k in ("open", "high", "low", "close")]] for r in csv.DictReader(stream)]
            assert D["bars"][f"{session}|{symbol}"] == expected
            bar_count += len(expected)
    reference = D["reference"]
    assert reference["id"] == "T3L1_G1_W4_D"
    assert reference["periods"] == lookup[reference["id"]]["periods"]
    for token in ("184,068", "113,840", "1.68", "1.23", "前半6組", "最低数未達", "前半赤字", "最大黒字場", "G1とG0", "追加デイ", "14,164", "NK無取引", "参考例"):
        assert token in reference["description"], ("少数黒字説明", token)
    notes = "\n".join(D["notes"] + D["sourceNotes"])
    for token in ("主選定除外", "同期は証明不能", "G別は入口が変わる", "入口部品", "旧アルゴリズム全体ではない", "W5は幅だけの変更ではない", "場では選び直さない", "全28は既知", "全29は単なる保存合計", "通信", "次の有効原本行", "1円未満", "全両方向"):
        assert token in notes, ("検証範囲説明", token)
    for token in ("管理終了までの組", "途中で0枚になっても同じ組", "決済勝率ではありません", "未到達は勝ちに含めません", "入口部品の変更前・保険の対照との比較"):
        assert token in main_text, ("公開成績説明", token)
    assert "採用条件未達" in D["conclusion"] and "主選定から除外" in all_text
    assert "color-scheme:dark" in main_text and "color-scheme:dark" in all_text
    published = read(WORK / "公開会計.json")
    assert published["主HTML_SHA256"] == digest(MAIN) and published["全条件HTML_SHA256"] == digest(ALL)
    save(HERE / "公開説明と会計の最終監査.json", dict(合格=True, 主要条件=432, 場数=29, 原本口座数=58,
        三代表=[m["id"] for m in D["methods"]], 全条件会計と独立再会計一致口座=25056,
        全条件五期間一致集計=4320, 三代表原本注文と約定時計一致注文=order_count,
        三代表三週合計一致=True, 入口確認別六幅と無保険縮小対照一致=True,
        五分足原本一致グラフ数=58, 五分足原本一致本数=bar_count,
        三代表未採用明記=True, 途中0枚は組終了ではない明記=True, 旧E01全体再現ではない明記=True,
        G3同期限界と主選定除外明記=True, 入口先着採点は決済勝率ではない明記=True,
        T3G0G1同一経路口座=duplicates["幅管理別売買時価一致口座"],
        少数黒字の最低数未達と集中依存明記=True, 追加デイと既知28分離=True,
        主HTML_SHA256=digest(MAIN), 全条件HTML_SHA256=digest(ALL),
        変更対象="監査領域だけ。HTML、凍結入力、モデル、旧成果、原本は変更しない"))
    print(f"公開3代表/全432・25056口座・4320期間・58図・{order_count}注文・幅対照・少数黒字重複: 合格", flush=True)


if __name__ == "__main__":
    main()
