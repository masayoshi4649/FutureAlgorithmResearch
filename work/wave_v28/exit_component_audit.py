"""第四反復の退出と損失制限を、他条件固定の全対応組で分解する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import gzip
import hashlib
import itertools
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent
SYMBOLS = ("TOPIX", "NK225")
RULES = {
    "対象": "第四反復27,648条件の全対応組。固定信号96×固定管理288。最良例や合格例へ絞らない。",
    "退出": "同一信号と他管理値を固定。価格注文のみから、中期反転・中立10分・両方の3比較。差は追加側−価格注文のみ。",
    "損失制限": "同一信号と他管理値を固定。追加制限なしから、2連敗+3R・3連敗+5R・3Rのみの3比較。差は追加側−なし。",
    "件数": "各比較・各銘柄6,912対応組、合計82,944組。各固定組を等重み。",
    "指標": "同銘柄内の全期間収支差・含み損込み最大DD差の中央値、厳密改善率・同値率、収支増かつDD減率。0.01円以下の差は同値。",
    "台帳": "保存ledger_hashは両銘柄・全26入力の結合指紋。したがって両銘柄共通の全台帳同一率として表示。銘柄単独の台帳同一率と偽らない。銘柄別収支/DD同値率は別記する。",
    "層別": "全対応組に加えて主方向6種別と、EMA2速度を同思想にまとめた5思想別を集計。層別の良い箇所へ再選抜しない。",
    "記述件数": "v27固定主案H019__D273に対し、両銘柄とも収支75%以上・DD80%以下の条件数と既存探索score最高順位を数える。最低基準通過を併せた数も別記。その他の一次反証・乱数・指定波の合格を意味しない。",
    "禁止": "採用規則の変更・新候補の再選定・現在スナップショット・API取得・新売買再生。",
    "限界": "同じ既知期間と多数の関連条件による記述。改善率を未知の成功確率と呼ばない。退出追加の比較は、2入力の分離だけの純粋な効果ではない。",
}


def read(path: Path):
    """機能: 通常又は圧縮JSONをUTF-8で読み込む。

    引数: path (Path)。返り値: 内容 (dict|list)。
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def save(path: Path, value) -> None:
    """機能: 新しい作業領域へ診断資料を保存する。

    引数: path (Path)、value (dict|list)。返り値: なし (None)。
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def digest(path: Path) -> str:
    """機能: 比較規則と参照資料の指紋を得る。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> dict:
    """機能: 部品成績を読む前に全対応組と記述件数の定義を固定する。

    引数: なし。返り値: 固定仕様 (dict)。
    """
    path = HERE / "exit_component_fixed.json"
    current = dict(固定日時=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), 規則=RULES,
                   コードSHA256=digest(Path(__file__)), 探索仕様SHA256=digest(HERE / "探索条件の固定.json"))
    if path.exists():
        saved = read(path)
        assert {key: value for key, value in saved.items() if key != "固定日時"} == {key: value for key, value in current.items() if key != "固定日時"}
        return saved
    save(path, current)
    return current


def manager_pairs(management: list[dict]) -> list[dict]:
    """機能: 変更する部品以外の全パラメータが一致した管理条件だけを対応させる。

    引数: management (list[dict])。返り値: 432対応組 (list[dict])。
    """
    output = []
    for axis in ("退出", "損失制限"):
        grouped = defaultdict(dict)
        for manager in management:
            changes = manager["changes"]
            if axis == "退出":
                removed = {"signal_exit", "neutral_min"}
                option = (changes["signal_exit"], changes["neutral_min"], manager["context_source"])
                fixed = {key: value for key, value in changes.items() if key not in removed}
            else:
                removed = {"max_same_losses", "session_budget_r"}
                option = (changes["max_same_losses"], changes["session_budget_r"])
                fixed = dict({key: value for key, value in changes.items() if key not in removed}, context_source=manager["context_source"])
            group = json.dumps(fixed, sort_keys=True)
            assert option not in grouped[group], "同一部品の管理重複"
            grouped[group][option] = manager["id"]
        assert len(grouped) == 72 and all(len(group) == 4 for group in grouped.values())
        if axis == "退出":
            base = (0, 0., "entry")
            targets = [((1, 0., "main"), "価格注文のみ→中期反転"), ((0, 10., "main"), "価格注文のみ→中立10分"), ((1, 10., "main"), "価格注文のみ→中期反転又は中立")]
        else:
            base = (0, 0.)
            targets = [((2, 3.), "制限なし→2連敗と3R"), ((3, 5.), "制限なし→3連敗と5R"), ((0, 3.), "制限なし→3Rのみ")]
        for fixed, group in grouped.items():
            assert base in group
            for target, name in targets:
                output.append(dict(axis=axis, comparison=name, before=group[base], after=group[target], 固定管理値=json.loads(fixed)))
    assert len(output) == 432
    return output


def summarize(rows: list[dict]) -> dict:
    """機能: 利益増とDD減、同時改善、全台帳同一を区別して記述する。

    引数: rows (list[dict])。返り値: 対応差の分布 (dict)。
    """
    net = np.array([row["net_difference"] for row in rows])
    dd = np.array([row["dd_difference"] for row in rows])
    return dict(対応組数=len(rows), 収支差中央値円=float(np.median(net)), DD差中央値円=float(np.median(dd)),
                収支改善率=float(np.mean(net > .01)), DD改善率=float(np.mean(dd < -.01)),
                両改善率=float(np.mean((net > .01) & (dd < -.01))),
                収支同値率=float(np.mean(abs(net) <= .01)), DD同値率=float(np.mean(abs(dd) <= .01)),
                両銘柄全台帳同一率=float(np.mean([row["ledger_identical"] for row in rows])),
                収支差10_90百分位=np.percentile(net, [10, 90]).tolist(), DD差10_90百分位=np.percentile(dd, [10, 90]).tolist())


def group_summary(rows: list[dict], columns: tuple[str, ...]) -> list[dict]:
    """機能: 事前固定した比較名・銘柄・思想で全対応組を層別する。

    引数: rows (list[dict])、columns (tuple[str,...])。返り値: 層別集計 (list[dict])。
    """
    grouped = defaultdict(list)
    for row in rows:
        grouped[tuple(row[column] for column in columns)].append(row)
    return [dict(zip(columns, key), **summarize(group)) for key, group in sorted(grouped.items())]


def improvement_counts(candidates: list[dict], baseline: dict) -> dict:
    """機能: 既存固定順位を保って75%収益/80%DDの該当数だけを数える。

    引数: candidates (list[dict])、baseline (dict)。返り値: 記述件数と既存順位 (dict)。
    """
    from context_runner import score
    ordered = sorted(sorted(candidates, key=lambda row: row["id"]), key=score, reverse=True)
    assert [row["id"] for row in ordered] == [row["id"] for row in candidates], "保存順位が固定score順でない"
    matched, basic = [], []
    per_symbol = dict.fromkeys(SYMBOLS, 0)
    for rank, row in enumerate(ordered, 1):
        conditions = {symbol: (row["symbols"][symbol]["net_yen"] >= .75 * baseline["symbols"][symbol]["net_yen"] - 1e-8 and
                               row["symbols"][symbol]["drawdown_yen"] <= .8 * baseline["symbols"][symbol]["drawdown_yen"] + 1e-8) for symbol in SYMBOLS}
        for symbol, meets in conditions.items():
            per_symbol[symbol] += int(meets)
        if all(conditions.values()):
            item = dict(id=row["id"], 既存固定順位=rank)
            matched.append(item)
            if not row["failures"]:
                basic.append(item)
    return dict(比較基準=baseline["id"], 全条件数=len(ordered), 銘柄別該当数=per_symbol,
                両銘柄該当数=len(matched), うち探索最低基準も通過=len(basic),
                両銘柄該当の最高固定順位=matched[0] if matched else None,
                最低基準も通過の最高固定順位=basic[0] if basic else None,
                解釈="件数と元からある順位の記述のみ。一次反証/乱数/8波の通過を意味せず、研究候補の再選定には使わない。")


def evaluate() -> dict:
    """機能: 保存済み全期間集計から部品差を読み、全対応比較だけを保存する。

    引数: なし。返り値: 部品診断 (dict)。売買再生・現在データは使用しない。
    """
    protocol = freeze()
    paths = [HERE / "探索条件の固定.json", HERE / "全条件の期間集計.json.gz", HERE / "反証前の候補固定.json",
             HERE.parent / "wave_v27" / "反証前の候補固定.json"]
    fingerprints = {str(path): digest(path) for path in paths}
    fixed, candidates, completed, previous = [read(path) for path in paths]
    assert len(fixed["signals"]) == 96 and len(fixed["managers"]) == 288
    assert len(candidates) == fixed["全組合せ数"] == completed["全条件数"] == 27648
    lookup = {row["id"]: row for row in candidates}
    expected = {signal["id"] + "__" + manager["id"] for signal in fixed["signals"] for manager in fixed["managers"]}
    assert len(lookup) == len(candidates) and set(lookup) == expected
    pairs = manager_pairs(fixed["managers"])
    rows = []
    for spec, pair, symbol in itertools.product(fixed["signals"], pairs, SYMBOLS):
        before, after = (lookup[spec["id"] + "__" + pair[key]] for key in ("before", "after"))
        a, b = before["symbols"][symbol], after["symbols"][symbol]
        assert np.isfinite([a["net_yen"], b["net_yen"], a["drawdown_yen"], b["drawdown_yen"]]).all()
        kind = spec["params"]["main_kind"]
        rows.append(dict(signal_id=spec["id"], main_kind=kind, philosophy="EMA" if kind.startswith("ema") else kind,
                         symbol=symbol, axis=pair["axis"], comparison=pair["comparison"], before=before["id"], after=after["id"],
                         net_difference=b["net_yen"] - a["net_yen"], dd_difference=b["drawdown_yen"] - a["drawdown_yen"],
                         ledger_identical=before["ledger_hash"] == after["ledger_hash"]))
    assert len(rows) == 82944
    baseline = next(row for row in previous["上位30"] if row["id"] == "H019__D273")
    report = dict(事前固定=protocol, 全対応組数=len(rows), 全比較=group_summary(rows, ("comparison", "symbol")),
                  主方向別=group_summary(rows, ("comparison", "symbol", "main_kind")), 思想別=group_summary(rows, ("comparison", "symbol", "philosophy")),
                  収益維持とDD削減の記述件数=improvement_counts(candidates, baseline),
                  台帳率の限界=RULES["台帳"], 新売買再生=False, API取得数=0, 現在スナップショット使用=False,
                  候補再選定=False, 参照SHA256=fingerprints)
    assert fingerprints == {str(path): digest(path) for path in paths}
    save(HERE / "exit_component_pairs.json.gz", rows)
    save(HERE / "exit_component_audit.json", report)
    lines = ["# 退出と損失制限の全対応比較", "", "同じ信号・他の管理値を固定した全82,944対応組。差は追加側−基準側。収支差が正、DD差が負なら改善。", "",
             "| 比較 | 銘柄 | 組数 | 収支差中央値 | 改善率 | DD差中央値 | DD改善率 | 両改善率 | 両銘柄全台帳同一率 |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["全比較"]:
        lines.append(f"|{row['comparison']}|{row['symbol']}|{row['対応組数']:,}|{row['収支差中央値円']:+,.0f}円|{row['収支改善率']:.1%}|{row['DD差中央値円']:+,.0f}円|{row['DD改善率']:.1%}|{row['両改善率']:.1%}|{row['両銘柄全台帳同一率']:.1%}|")
    counts = report["収益維持とDD削減の記述件数"]
    lines += ["", "## 固定された改善目標の該当数", "",
              f"H019__D273に対し、両銘柄で収益75%以上・DD80%以下は **{counts['両銘柄該当数']:,}/27,648条件**。うち探索最低基準も通過するのは **{counts['うち探索最低基準も通過']:,}条件**。",
              "最高の既存固定順位：" + (str(counts["両銘柄該当の最高固定順位"]) if counts["両銘柄該当の最高固定順位"] else "該当なし") + "。",
              "この数は一次反証・乱数対照・指定8波の合格数ではなく、新しい候補選抜にも使わない。", "",
              "## 解釈", "", "- 同じ既知データを共有する関連条件の分布であり、改善率は未知の成功確率ではない。",
              "- 台帳指紋は両銘柄全26入力を合わせたもの。銘柄別の厳密な台帳同一率ではない。銘柄別の収支/DD同値率はJSONへ保存した。",
              "- 退出追加の対照には、退出条件を増やす効果も入る。二入力の分離だけの効果は、同じ退出設定でcontext=entryへ戻す一次反証の部品対照で確認する。",
              "- 主方向別・思想別の全対応分布と全差分をJSONに保存。現在データは未使用、売買再生・候補再選定・規則変更はしていない。"]
    (HERE / "exit_component_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    """機能: 規則を先に固定し、その後だけ全対応比較を実行する。

    引数: --prepare (bool)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    freeze()
    if args.prepare:
        fixed = read(HERE / "探索条件の固定.json")
        assert len(manager_pairs(fixed["managers"])) == 432
        print("部品432対応組と全82,944比較を結果前に固定。", flush=True)
        return
    result = evaluate()
    print(json.dumps(dict(全対応組数=result["全対応組数"], 記述件数=result["収益維持とDD削減の記述件数"]), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
