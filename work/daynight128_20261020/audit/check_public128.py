"""公開結果と統合入口を、金融再生せずに独立照合する。"""

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys
import time
from types import ModuleType
from urllib.parse import unquote, urlsplit


HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
PUBLIC = ROOT / "アルゴリズム調査/00128_日中改修と夜間新造の反復検証"


def read(path):
    """
    機能: 保存済みのJSONだけを読み取る。
    引数: path(Path)は対象資料。
    返り値: dict又はlistは読み取った内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    """
    機能: 監査時点の資料指紋を記録する。
    引数: path(Path)は対象資料。
    返り値: dictは相対位置とSHA256。
    """
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def aggregates(rows):
    """
    機能: 生の場別会計から表示集計を独立して再計算する。
    引数: rows(list[dict])は単一手法・商品の保存会計。
    返り値: dictは場数、親別損益、場別統計。
    """
    net = [r["net"] for r in rows]
    wins = [v for v in net if v > 0]
    losses = [v for v in net if v < 0]
    return {
        "sessions": len(rows),
        "profit": sum(r["profit"] for r in rows),
        "loss": sum(r["loss"] for r in rows),
        "fees": sum(r["fees"] for r in rows),
        "net": sum(net),
        "black": len(wins),
        "red": len(losses),
        "flat": net.count(0),
        "active": sum(r["entries"] > 0 for r in rows),
        "median": statistics.median(net),
        "worst": min(net),
        "mean_black": statistics.mean(wins) if wins else 0,
        "mean_red": -statistics.mean(losses) if losses else 0,
        "without_top3": sum(net) - sum(sorted(wins, reverse=True)[:3]),
        "entries": sum(r["entries"] for r in rows),
    }


def rank(pair):
    """
    機能: 保存計画の優先順位を別実装で計算する。
    引数: pair(list[dict])は二商品の統計。
    返り値: tupleは両黒字、最低黒字率、最悪損失比、最低利益割合の順位。
    """
    return (
        int(all(g["net"] > 0 for g in pair)),
        min(g["black"] / g["sessions"] for g in pair),
        -max(-g["worst"] / g["mean_black"] if g["mean_black"] > 0 else 1e10 for g in pair),
        min(g["profit"] / (g["profit"] + g["loss"]) if g["profit"] + g["loss"] else 0 for g in pair),
    )


def route_only(selection):
    """
    機能: 数値核を代用品へ置換し昼夜振分けだけを検査する。
    引数: selection(dict)は公開された固定候補。
    返り値: intは合格した人工ケース数。金融再生は行わない。
    """
    calls = []
    dummy = ModuleType("adapter5")

    def play_day(*args):
        """
        機能: 日中核の代わりに引数だけを記録する。
        引数: args(tuple)は統合入口から渡された引数。
        返り値: dictは検査用の識別子。
        """
        calls.append(("Day", args))
        return {"仮結果": "Day"}

    def play_night(*args):
        """
        機能: 夜間核の代わりに引数だけを記録する。
        引数: args(tuple)は統合入口から渡された引数。
        返り値: dictは検査用の識別子。
        """
        calls.append(("Night", args))
        return {"仮結果": "Night"}

    def summarize(*args):
        """
        機能: 会計核の代わりに候補IDだけを返す。
        引数: args(tuple)は仮結果・入力識別子・条件。
        返り値: dictは検査用の候補ID。
        """
        calls.append(("会計", args))
        return {"仮会計": args[2]["id"]}

    dummy.play_day = play_day
    dummy.play_night = play_night
    dummy.summarize = summarize
    old = sys.modules.get("adapter5")
    sys.modules["adapter5"] = dummy
    sys.path.insert(0, str(HERE))
    module = ModuleType("公開入口の純人工")
    module.__file__ = str(HERE / "selected_algorithm.py")
    count = 0
    try:
        exec(compile((HERE / "selected_algorithm.py").read_text(encoding="utf-8"), module.__file__, "exec"), module.__dict__)
        for kind, expected in (("Day", "D17"), ("Night", "N27")):
            for date in ("2026-09-21", "2026-10-20", "2030-01-01"):
                session = date + "_" + kind
                config = module.session_config(session)
                assert config["id"] == expected and config["kind"] == kind
                for key, value in selection["methods"][kind].items():
                    assert config[key] == value
                config["id"] = "変更しても保存条件には伝播しない"
                assert module.session_config(session)["id"] == expected
                count += 1
                for symbol in ("TOPIX", "NK225"):
                    calls.clear()
                    ready = {"session": session, "symbol": symbol}
                    quote, market, history, feed = {}, object(), object(), object()
                    answer = module.simulate_session(ready, quote, market, history, feed)
                    assert [c[0] for c in calls] == [kind, "会計"]
                    assert answer == ({"仮結果": kind}, {"仮会計": expected})
                    args = calls[0][1]
                    assert args[1] is ready and args[2] is quote and args[3] is market and args[4] is history
                    assert len(args) == (6 if kind == "Day" else 5)
                    if kind == "Day":
                        assert args[5] is feed
                    count += 1
        calls.clear()
        try:
            module.simulate_session({"session": "2026-10-20_Day"}, {}, object(), object())
        except ValueError:
            assert not calls
            count += 1
        else:
            raise AssertionError("日中の通知欠測を拒否しなかった")
        for invalid in ("2026-10-20", "2026-10-20_day", "2026-10-20_Unknown"):
            try:
                module.session_config(invalid)
            except ValueError:
                count += 1
            else:
                raise AssertionError(invalid)
    finally:
        sys.path.pop(0)
        if old is None:
            del sys.modules["adapter5"]
        else:
            sys.modules["adapter5"] = old
    return count


def main():
    """
    機能: 公開データ・相対リンク・候補選定・純人工振分けをまとめて検査する。
    引数: なし。
    返り値: None。自分の監査領域へ時刻付き証跡だけを新規保存する。
    """
    public_html = PUBLIC / "日中改修と夜間新造の損益.html"
    content = public_html.read_text(encoding="utf-8")
    match = re.search(r'<script id="saved-data" type="application/json">([\s\S]*?)</script>', content)
    saved = json.loads(match.group(1).replace("<\\/", "</"))
    comparison = read(HERE / "round5/前後半と方向別の比較.json")
    selection = read(HERE / "採用候補と公開記録.json")
    assert saved["summary"] == comparison["summary"]
    assert saved["selected"] == comparison["selected"]
    assert saved["defaults"] == {"Day": "D17", "Night": "N27"}
    assert selection["front_fixed"] == comparison["selected"]
    assert {k: v["frozen_on_first_half"] for k, v in comparison["selected"].items()} == {"Day": "D18", "Night": "N20"}
    assert "採用保留" in selection["status"]["Night"]
    assert selection["methods"]["Night"]["id"] == "N27"
    assert "N36" in selection["topix_night_reference"]
    assert "採用保留" in content and "12赤字" in content and "未知データ" in content
    document_path = HERE / "文書公開と知見追記.json"
    visual_path = HERE / "visual_final/全選択と全場累計の実描画照合.json"
    document = read(document_path)
    visual = read(visual_path)
    assert document["passed"] and visual["passed"]
    assert all(v["passed"] for v in visual["results"])
    assert visual["html_sha256"] == digest(public_html)["sha256"]
    references = selection["sources"] + selection["reports"]
    references += [document["report"], document["readme"]] + document["knowledge"]
    for ref in references:
        assert digest(ROOT / ref["path"]) == ref

    # ----------------------------------------
    # 監査済み原会計と公開行の比較。
    raw = {}
    configs = {}
    for n in range(1, 6):
        audited = read(HERE / f"audit/round{n}_全注文と全行会計の独立照合.json")
        assert audited["passed"]
        data = read(HERE / f"round{n}/全条件の会計.json")
        for r in data["rows"]:
            key = r["method"], r["session"], r["symbol"]
            assert key not in raw
            raw[key] = r
        for config in data["configs"]:
            assert config["id"] not in configs
            configs[config["id"]] = config
    for row in read(HERE / "baseline/基準四十三場の親別手数料会計.json")["rows"]:
        r = dict(row, method="D00" if row["kind"] == "Day" else "N00", entries=row["parents"])
        raw[r["method"], r["session"], r["symbol"]] = r
    assert len(raw) == len(comparison["rows"]) == len(saved["rows"]) == 2478
    for row in saved["rows"]:
        reference = raw[row["method"], row["session"], row["symbol"]]
        for key in ("method", "session", "symbol", "kind", "profit", "loss", "net", "fees", "entries"):
            assert row[key] == reference[key], (key, row)
        assert row["profit"] - row["loss"] == row["net"]
    assert len(configs) == 56 and len(saved["methods"]) == 58
    for key, config in configs.items():
        for name, value in config.items():
            assert saved["methods"][key][name] == value

    # ----------------------------------------
    # 全場・前後半・上昇下落同値・週の集計を別実装で確認。
    groups = defaultdict(list)
    for row in comparison["rows"]:
        groups[row["method"], row["symbol"]].append(row)
    checks = 0
    for item in saved["summary"]:
        rows = groups[item["method"], item["symbol"]]
        subsets = [(item, rows)]
        for field, label in (("halves", "half_within_kind"), ("regimes", "regime"), ("weeks", "week_start")):
            for name, stats in item[field].items():
                subsets.append((stats, [r for r in rows if r[label] == name]))
        for stats, subset in subsets:
            for name, value in aggregates(subset).items():
                assert abs(stats[name] - value) < 1e-8, (item["method"], item["symbol"], name)
                checks += 1
    for kind, full_id, front_id in (("Day", "D17", "D18"), ("Night", "N27", "N20")):
        methods = [m for m, c in saved["methods"].items() if c["kind"] == kind]
        by_full, by_front = [], []
        for method in methods:
            pair = [s for s in saved["summary"] if s["method"] == method]
            by_full.append((rank(pair), method))
            by_front.append((rank([s["halves"]["前半"] for s in pair]), method))
        assert max(by_full)[1] == full_id
        assert max(by_front)[1] == front_id
    topix_nights = [s for s in saved["summary"] if s["kind"] == "Night" and s["symbol"] == "TOPIX"]
    best_black = max(s["black"] for s in topix_nights)
    assert best_black == 17
    assert next(s for s in topix_nights if s["method"] == "N36")["black"] == 17

    # ----------------------------------------
    # 今回公開範囲の相対リンクだけを確認。
    paths = [public_html, PUBLIC / "README.md", PUBLIC / "手法と検証仕様.md"]
    knowledge = ROOT / "アルゴリズム調査/共通/知見台帳"
    paths += [knowledge / f"{name}.md" for name in ("入口", "継続", "出口", "売買の工夫")]
    link_count = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if path.parent == knowledge:
            text = text[text.index('<a id="00128_'):]
        links = re.findall(r'href="([^"]+)"', text) if path.suffix == ".html" else re.findall(r'\]\(([^)]+)\)', text)
        for target in links:
            parts = urlsplit(target)
            if parts.scheme or not parts.path:
                continue
            resolved = (path.parent / unquote(parts.path)).resolve()
            assert resolved.exists(), (path, target)
            link_count += 1
    route_cases = route_only(selection)
    result = {
        "passed": True,
        "公開方法数": len(saved["methods"]),
        "公開商品場行数": len(saved["rows"]),
        "独立再集計値数": checks,
        "有効な相対リンク数": link_count,
        "公開記録の資料指紋照合数": len(references) + 1,
        "統合入口の純人工ケース数": route_cases,
        "全場選定": saved["defaults"],
        "前半選定": {"Day": "D18", "Night": "N20"},
        "数値核実行数": 0,
        "金融再生数": 0,
        "確認範囲": "主要説明の読解、監査済み会計との公開値一致、再集計、選定、相対リンク、代用核での昼夜振分け。ブラウザ描画は別担当の証跡。",
        "資料": [digest(p) for p in paths + [HERE / "selected_algorithm.py", HERE / "採用候補と公開記録.json", document_path, visual_path, Path(__file__) ]],
    }
    output = HERE / "audit" / f"公開資料と統合入口の独立レビュー_{time.time_ns()}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "資料"}, ensure_ascii=False))
    print(output.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
