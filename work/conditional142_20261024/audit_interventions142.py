"""保存された注文と判定記録だけから、実介入・同値・追撃予算を確認する。"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ORDER_COLUMNS = ("約定行", "判断行", "親ID", "売買方向", "枚数", "価格", "理由", "新規返済", "玉ID", "手数料")
ECONOMIC_COLUMNS = [0, 1, 2, 3, 4, 5, 7, 8, 9]
TRACE_COLUMNS = ("判断行", "入口又は管理", "方向", "選択", "理由", "親ID", "現在利益R", "最大利益R", "同方向失敗数")


def read(path: Path) -> dict:
    """JSONを読み取る。

    引数: path(Path) は読み取り対象。
    返り値: dict は保存された資料。元資料は変更しない。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fingerprint(path: Path) -> str:
    """ファイル全体のSHA256を得る。

    引数: path(Path) は読み取り対象。
    返り値: str は内容指紋。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def array_hash(array: np.ndarray, columns: list[int] | None = None) -> str:
    """形状と列順を含めた注文列の指紋を作る。

    引数: array(ndarray) は保存配列、columns(list[int]|None) は採用列。
    返り値: str。理由を除く同値と、完全同値を別々に測る。
    """
    selected = array if columns is None else array[:, columns]
    selected = np.ascontiguousarray(selected, dtype="<f8")
    return hashlib.sha256(str(selected.shape).encode("ascii") + selected.tobytes()).hexdigest()


def load_templates() -> tuple[dict, str]:
    """固定設定の定義関数だけを読み取り、売買プログラムを実行せず設定値を得る。

    引数: なし。
    返り値: tuple[dict,str] は二商品の固定設定とその原コード指紋。
    """
    path = ROOT / "work/aggressive140_20261024/active140_v2.py"
    parsed = ast.parse(path.read_text(encoding="utf-8-sig"))
    function = next(node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == "configurations")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    configs = namespace["configurations"]()
    return {"NK225": configs[35], "TOPIX": configs[32]}, fingerprint(path)


def event_keys(orders: np.ndarray, reason: int) -> set[tuple[int, int]]:
    """複数玉の同時返済を一つの発注判断へまとめる。

    引数: orders(ndarray) は保存注文、reason(int) は理由コード。
    返り値: set[tuple[int,int]] は判断行・親IDの組。
    """
    return {(int(row[1]), int(row[2])) for row in orders if int(row[6]) == reason and row[7] == 0}


def counts(orders: np.ndarray, trace: np.ndarray, changes: dict) -> dict:
    """保存された準備・判定遷移・実発注を区別して集計する。

    引数: orders/trace(ndarray) は保存配列、changes(dict) は固定条件。
    返り値: dict は件数。判定記録数を全呼出回数とは呼ばない。
    """
    assert orders.ndim == 2 and orders.shape[1] == 10
    assert trace.ndim == 2 and trace.shape[1] == 9
    initial = orders[(orders[:, 7] == 1) & (orders[:, 8] == 0)]
    adds = orders[(orders[:, 7] == 1) & (orders[:, 8] > 0)]
    entry_trace = trace[trace[:, 1] == 1]
    management = trace[trace[:, 1] == 2]
    result = dict(入口準備記録=len(entry_trace), 通常反発準備=int(np.sum(entry_trace[:, 3] == 0)),
                  二段階準備=int(np.sum(entry_trace[:, 3] == 2)),
                  管理判定遷移=len(management), 維持判定遷移=int(np.sum(management[:, 3] == 0)),
                  半減判定遷移=int(np.sum(management[:, 3] == 1)), 全返済判定遷移=int(np.sum(management[:, 3] == 2)),
                  初回新規=len(initial), 追撃新規=len(adds), 追撃枚数=int(adds[:, 4].sum()),
                  通常反発の実新規=0, 二段階反発の実新規=0, 入口選択なしの実新規=0,
                  半減の実発注=0, 全返済の実発注=0,
                  入口理由=dict(sorted(Counter(str(int(row[4])) for row in entry_trace).items())),
                  管理理由=dict(sorted(Counter(str(int(row[4])) for row in management).items())))
    for row in initial:
        if changes.get("entry_policy", 0) and row[6] == 144:
            candidates = entry_trace[(entry_trace[:, 0] <= row[1]) & (entry_trace[:, 5] == row[2])]
            assert len(candidates), ("入口判定がありません", row.tolist())
            latest = candidates[-1]
            assert latest[2] == row[3], ("入口方向が一致しません", row.tolist(), latest.tolist())
            result["通常反発の実新規" if latest[3] == 0 else "二段階反発の実新規"] += 1
        else:
            result["入口選択なしの実新規"] += 1
    policy = changes.get("management_policy", 0)
    if policy:
        for action, reason, label in ((1, 1430 + policy, "半減の実発注"), (2, 1420 + policy, "全返済の実発注")):
            actual = event_keys(orders, reason)
            intended = {(int(row[0]), int(row[5])) for row in management if row[3] == action}
            assert actual == intended, ("管理判定と実発注が不一致", reason, actual ^ intended)
            result[label] = len(actual)
    return result


def main() -> None:
    """全保存資料を照合し、集計JSONと短い説明を保存する。

    引数: なし。
    返り値: None。売買再生・新しい発注・API取得は一切行わない。
    """
    source = read(HERE / "結果142.json")
    plan = read(HERE / "試行計画142.json")
    configs = {item["id"]: item for item in plan["configs"]["active"]}
    methods = sorted(configs)
    templates, template_sha = load_templates()
    financial = {(row["symbol"], row["session"], row["method"]): row for row in source["rows"]}
    cache = sorted(source["cache"], key=lambda row: (row["symbol"], row["session"]))
    assert len(cache) == 100 and len({(row["symbol"], row["session"]) for row in cache}) == 100
    records, provenance = [], []
    signatures = defaultdict(list)
    finance_signatures = defaultdict(list)
    pairs = {(symbol, left, right): Counter() for symbol in ("NK225", "TOPIX") for left, right in itertools.combinations(methods, 2)}
    aggregates = {}
    for reference in cache:
        symbol, session = reference["symbol"], reference["session"]
        path = ROOT / reference["path"]
        assert fingerprint(path) == reference["sha256"], path
        trace_path = HERE / "traces" / path.name
        provenance.append(dict(symbol=symbol, session=session, measurement=reference, trace_path=str(trace_path.relative_to(ROOT)), trace_sha256=fingerprint(trace_path)))
        with np.load(path) as book, np.load(trace_path) as traces:
            scene_signatures = {}
            for method in methods:
                active, combined, trace = book["A_" + method], book[method], traces[method]
                config = configs[method]["changes"]
                stat = counts(active, trace, config)
                selected = combined[combined[:, 2] >= 3_000_000].copy()
                if len(selected):
                    selected[:, 2] -= 3_000_000
                selected_parents = set(selected[:, 2].astype(int))
                selected_expected = active[np.isin(active[:, 2], list(selected_parents))]
                np.testing.assert_array_equal(selected, selected_expected)
                stat["口座採用の追加親"] = len(selected_parents)
                stat["口座採用の追撃"] = int(np.sum((selected[:, 7] == 1) & (selected[:, 8] > 0)))
                policy = config.get("management_policy", 0)
                stat["口座採用の半減"] = len(event_keys(selected, 1430 + policy)) if policy else 0
                stat["口座採用の全返済"] = len(event_keys(selected, 1420 + policy)) if policy else 0
                for key, array in (("A_" + method, active), (method, combined)):
                    expected = financial[symbol, session, key]["net"]
                    multiplier = 100.0 if symbol == "NK225" else 1000.0
                    actual = float(np.sum(-array[:, 3] * array[:, 4] * array[:, 5] * multiplier - array[:, 9]))
                    assert abs(actual - expected) < 0.001, (symbol, session, key, actual, expected)
                signature = {"追加全列": array_hash(active), "追加約定": array_hash(active, ECONOMIC_COLUMNS),
                             "合成全列": array_hash(combined), "合成約定": array_hash(combined, ECONOMIC_COLUMNS),
                             "判定全列": array_hash(trace), "判定理由除外": array_hash(trace, [0, 1, 2, 3, 5, 6, 7, 8])}
                scene_signatures[method] = signature
                for measure, value in signature.items():
                    signatures[symbol, method, measure].append((session, value))
                net = financial[symbol, session, method]["net"]
                finance_signatures[symbol, method].append((session, net))
                record = dict(symbol=symbol, session=session, method=method, changes=config, **stat, signatures=signature,
                              合成収支=net, 追加単独収支=financial[symbol, session, "A_" + method]["net"])
                records.append(record)
                total = aggregates.setdefault((symbol, method), dict(symbol=symbol, method=method, name=configs[method]["name"], changes=config, 場数=0))
                total["場数"] += 1
                for key, value in stat.items():
                    if isinstance(value, int):
                        total[key] = total.get(key, 0) + value
                    elif isinstance(value, dict):
                        accum = total.setdefault(key, {})
                        for reason, count in value.items():
                            accum[reason] = accum.get(reason, 0) + count
                total["追加実取引場数"] = total.get("追加実取引場数", 0) + int(stat["初回新規"] > 0)
                total["管理実介入場数"] = total.get("管理実介入場数", 0) + int(stat["半減の実発注"] + stat["全返済の実発注"] > 0)
                total["追撃実行場数"] = total.get("追撃実行場数", 0) + int(stat["追撃新規"] > 0)
            for left, right in itertools.combinations(methods, 2):
                counter = pairs[symbol, left, right]
                counter["対象場数"] += 1
                for measure in scene_signatures[left]:
                    counter[measure + "同値場数"] += int(scene_signatures[left][measure] == scene_signatures[right][measure])
                counter["場収支同値数"] += int(financial[symbol, session, left]["net"] == financial[symbol, session, right]["net"])

    # ----------------------------------------
    # 全50場の列が同じ条件をまとめ、比較条件数と独立した売買経路の数を区別する。
    groups = []
    for symbol in ("NK225", "TOPIX"):
        for period in ("全50場", "Day", "Night"):
            for measure in ("追加全列", "追加約定", "合成全列", "合成約定", "判定全列", "判定理由除外", "場収支"):
                buckets = defaultdict(list)
                for method in methods:
                    items = finance_signatures[symbol, method] if measure == "場収支" else signatures[symbol, method, measure]
                    signature = tuple(row for row in items if period == "全50場" or row[0].endswith("_" + period))
                    buckets[signature].append(method)
                groups.append(dict(symbol=symbol, period=period, measure=measure, 設定条件数=len(methods), 全期間の固有経路数=len(buckets), 同値組=[items for items in buckets.values() if len(items) > 1]))

    # ----------------------------------------
    # 初回予算を使い切る停止線の算術を確認する。反実仮想の売買再生は行わない。
    budget_checks = []
    for symbol, template in templates.items():
        assert template["activation"] > template["trail"] and template["stop"] > 0
        relevant = [row for row in aggregates.values() if row["symbol"] == symbol and row["changes"].get("add_policy") in (1, 2)]
        budget_checks.append(dict(symbol=symbol, template=template, add_policy対象条件=[row["method"] for row in relevant],
            保存追撃注文数=sum(row["追撃新規"] for row in relevant),
            保護前追撃の可否="構造上不可能", 保護前の実追撃数=0,
            根拠="保護前floor=-stop×R。半減後は追撃禁止。初回玉損失=q0×stop×R=actual_initial_risk=予算。新玉リスク>=tick>0なので合計が予算を超える。保護後floor>=（activation−trail）×R>0で両policyが許可する。",
            注意="保存注文には固定R/floorが無い。0件は実注文時点でfloorを再測定した値ではなく、実装の条件と予算式による到達不能の証明。取得済み追撃の件数は保存注文を直接計数。"))
    report = dict(新金融再生=0, API取得=0, 原資料変更=0, 原注文列=list(ORDER_COLUMNS), 判定列=list(TRACE_COLUMNS),
                  対象口座資料数=len(cache), 対象追加条件数=len(methods), 対象条件口座数=len(records),
                  注記=["入口記録は準備を開始した回数で、実新規回数ではない。", "管理記録は状態が変わった場合等だけを記録した遷移数で、毎行の判定呼出数ではない。", "追加担当単独と、先着採用後の口座を区別する。", "約定同値は理由列だけ除外し、行・価格・枚数・手数料・親・玉IDを全て保持する。", "同値はこの全50場の保存経路の観測。policy1/2の追撃だけは予算式で構造的同値を確認する。"],
                  固定計画SHA256=fingerprint(HERE / "試行計画142.json"), 固定設定原文SHA256=template_sha,
                  集計=list(aggregates.values()), 全期間同値=groups,
                  ペア比較=[dict(symbol=key[0], left=key[1], right=key[2], **value) for key, value in pairs.items()],
                  追撃予算検査=budget_checks, 場別=records, 資料指紋=provenance)
    (HERE / "実介入数と同値の独立集計142.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 実介入と同値の独立確認", "", "新たな売買再生はせず、第一巡の全100商品場に保存された14追加条件を確認した。", "", "## 実際に変えた判断", "", "|商品|条件|通常/二段階の準備記録|反転実新規の通常/二段階|管理の維持/半減/全返済記録|実半減/全返済|追撃|合成後採用親|", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in aggregates.values():
        lines.append(f'|{row["symbol"]}|{row["method"]}|{row["通常反発準備"]}/{row["二段階準備"]}|{row["通常反発の実新規"]}/{row["二段階反発の実新規"]}|{row["維持判定遷移"]}/{row["半減判定遷移"]}/{row["全返済判定遷移"]}|{row["半減の実発注"]}/{row["全返済の実発注"]}|{row["追撃新規"]}|{row["口座採用の追加親"]}|')
    lines.extend(["", "入口の準備記録は新規約定の回数ではない。管理記録も毎原行の呼出回数ではなく、選択が変わった場合等の記録数。表の管理・追撃は追加担当単独で、TOPIXは先着採用後に実口座へ残る数を別に確認する。全発注と判定記録の対応、全額会計、採用親の原注文一致を照合した。", "", "## 全期間で同じ売買になった条件", ""])
    for row in groups:
        if row["measure"] in ("合成約定", "場収支"):
            labels = ["・".join(items) for items in row["同値組"]]
            lines.append(f'- {row["symbol"]}・{row["period"]}の{row["measure"]}：14設定に対して{row["全期間の固有経路数"]}通り。同値組は' + ("、".join(labels) if labels else "なし") + "。")
    for symbol in ("NK225", "TOPIX"):
        comparison = pairs[symbol, "C09", "C12"]
        by_scene = defaultdict(dict)
        for row in records:
            if row["symbol"] == symbol and row["method"] in ("C09", "C12"):
                by_scene[row["session"]][row["method"]] = row
        differences = [(scene, pair["C09"]["合成収支"], pair["C12"]["合成収支"]) for scene, pair in by_scene.items()
                       if pair["C09"]["signatures"]["合成約定"] != pair["C12"]["signatures"]["合成約定"]]
        lines.append(f'- {symbol} C09/C12：全50場中{comparison["合成約定同値場数"]}場で約定同値、{comparison["場収支同値数"]}場で収支同値。約定差のある場と収支（C09/C12）は{differences}。')
    lines.extend(["", "約定同値は理由コードを除いた全注文列の一致であり、合計収支だけの一致とは別。全50場の経路が同じ条件を、複数の独立した成功例に数えない。", "", "## 追撃policy 1と2は予算式のため差が出ない", "", "利益保護前は、初回玉から元の損切り線までの損失だけで初回実損失予算を使い切る。新玉には最低1呼値の追加リスクがあるので、長短の方向が一致してpolicy 2が許可しても数量審査を通らない。半減後も追撃は禁止される。", "", "利益保護開始時は、日経1.25R−0.75R＝0.5R、TOPIX0.75R−0.5R＝0.25R以上へ停止線が上がる。そこではpolicy 1も2も許可する。この仕様では、保護前の実追撃は構造上0件であり、policy 2の緩和だけの有効性は測れていない。", "", "保存注文は固定R・停止線を持たないため、0件を各注文のfloorを再測定した統計とは呼ばない。式と実装からの到達不能確認と、実保存された追撃数を分けている。個別場数・実採用された半減/返済・全ペア一致数・指紋は[独立集計JSON](実介入数と同値の独立集計142.json)に保存。", "", "対象：[第一巡固定計画](試行計画142.json)、[保存注文](measurement/)、[判定記録](traces/)。以前の会計や金融コードは変更していない。"])
    (HERE / "実介入数と同値の独立確認142.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(dict(対象口座資料数=len(cache), 対象条件口座数=len(records), 全期間同値=groups, 追撃予算検査=budget_checks), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
