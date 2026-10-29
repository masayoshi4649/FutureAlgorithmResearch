"""今回の固定候補の損益を、索引と各候補の小さなMarkdownへ出力します。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


OWN_DIR = Path(__file__).resolve().parent
ROOT = OWN_DIR.parent.parent
STUDY = ROOT / "アルゴリズム調査" / "00170_複数時間足のテクニカルと指標出口"
SYMBOLS = ("NK225", "TOPIX")
SYMBOL_LABELS = {"NK225": "日経", "TOPIX": "TOPIX"}
KIND_LABELS = {"Day": "日中", "Night": "夜間"}
MONEY_FIELDS = ("gross_profit_yen", "gross_loss_yen", "realized_yen", "unrealized_yen", "final_equity_yen")


def number(value: object, label: str) -> float | None:
    """
    機能: 欠測と有限の数値を区別します。
    引数: value は object 型の入力、label は str 型の項目名です。
    返り値: float 型の数値、または欠測を表す None です。
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"数値が不正です。{label}")
    return float(value)


def near(actual: float, expected: float, label: str) -> None:
    """
    機能: 原入力の会計値を照合します。
    引数: actual と expected は float 型の実値と期待値、label は str 型の照合名です。
    返り値: None。不一致の場合は例外を送出します。
    """
    if abs(actual - expected) > 0.00001:
        raise ValueError(f"会計が一致しません。{label}: {actual} / {expected}")


def key(record: dict) -> tuple[str, str]:
    """
    機能: 場を一意に特定します。
    引数: record は dict 型の銘柄と場名を含む入力です。
    返り値: tuple[str, str] 型の銘柄と場名です。
    """
    return record["symbol"], record["session"]


def kind_of(session: str) -> str:
    """
    機能: 場名の末尾から昼夜を判定します。
    引数: session は str 型の場名です。
    返り値: str 型の Day または Night です。
    """
    for kind in KIND_LABELS:
        if session.endswith(f"_{kind}"):
            return kind
    raise ValueError(f"昼夜を判定できません。{session}")


def total(rows: list[dict], field: str) -> float | None:
    """
    機能: 欠測を健全なゼロへ置き換えずに集計します。
    引数: rows は list[dict] 型の対象場、field は str 型の集計項目です。
    返り値: float 型の合計、または1件以上の欠測がある場合は None です。
    """
    values = [row.get(field) for row in rows]
    return None if any(value is None for value in values) else sum(values)


def display(value: float | None) -> str:
    """
    機能: 金額のゼロと欠測を区別して日本語表へ表示します。
    引数: value は float 型の金額、または欠測を表す None です。
    返り値: str 型の桁区切り付きの金額または「欠測」です。
    """
    if value is None:
        return "欠測"
    if abs(value) < 0.000001:
        return "0"
    if abs(value - round(value)) < 0.000001:
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def prepare(source: dict, selection: dict) -> tuple[list[str], dict, dict]:
    """
    機能: 固定候補、場、分割、会計の重複や不整合を検査します。
    引数: source は dict 型の集計JSON、selection は dict 型の検討・確認の分割JSONです。
    返り値: tuple 型の候補ID一覧、候補銘柄別の場一覧、場の監査辞書です。
    """
    if not all(isinstance(source.get(name), list) for name in ("results", "configs", "audits")):
        raise ValueError("集計JSONに results/configs/audits がありません。")
    ids = sorted(config["id"] for config in source["configs"])
    if len(ids) != 72 or len(set(ids)) != 72:
        raise ValueError("重複のない72候補が必要です。")
    audits = {key(row): row for row in source["audits"]}
    splits = {key(row): row for row in selection["splits"]}
    if len(audits) != len(source["audits"]) or len(splits) != len(selection["splits"]):
        raise ValueError("場の監査または検討・確認の分割が重複しています。")
    groups = {(candidate, symbol): [] for candidate in ids for symbol in SYMBOLS}
    seen = set()
    for original in source["results"]:
        row = dict(original)
        candidate = row.get("config_id", row["method_id"])
        group_key = candidate, row["symbol"]
        unique = candidate, *key(row)
        if group_key not in groups or unique in seen:
            raise ValueError(f"候補または銘柄が不明、もしくは結果が重複しています。{unique}")
        seen.add(unique)
        audit, split = audits.get(key(row)), splits.get(key(row))
        if audit is None or split is None:
            raise ValueError(f"場の監査または検討・確認の分割がありません。{unique}")
        if not isinstance(row.get("complete"), bool):
            raise ValueError(f"場完了の状態がありません。{unique}")
        if audit["complete"] != row["complete"] or split["complete"] != row["complete"]:
            raise ValueError(f"場完了の状態が一致しません。{unique}")
        if split["phase"] not in ("検討", "確認"):
            raise ValueError(f"検討・確認の区分が不明です。{unique}")
        for field in (*MONEY_FIELDS, "entry_count"):
            row[field] = number(row.get(field), f"{unique}/{field}")
        for field in ("gross_profit_yen", "gross_loss_yen", "entry_count"):
            if row[field] is not None and row[field] < 0:
                raise ValueError(f"正数で保持する項目が負数です。{unique}/{field}")
        if all(row[field] is not None for field in ("gross_profit_yen", "gross_loss_yen", "realized_yen")):
            near(row["gross_profit_yen"] - row["gross_loss_yen"], row["realized_yen"], f"{unique}/利益−損失")
        if all(row[field] is not None for field in ("realized_yen", "unrealized_yen", "final_equity_yen")):
            near(row["realized_yen"] + row["unrealized_yen"], row["final_equity_yen"], f"{unique}/時価収支")
        position = row.get("final_position", {})
        position_qty = number(position.get("Qty", position.get("qty")), f"{unique}/残玉枚数")
        if row["complete"]:
            if position_qty is None:
                raise ValueError(f"完全場の残玉枚数がありません。{unique}")
            near(position_qty, 0, f"{unique}/完全場の残玉枚数")
            if row["unrealized_yen"] is not None:
                near(row["unrealized_yen"], 0, f"{unique}/完全場の含み")
        row.update(config_id=candidate, kind=kind_of(row["session"]), phase=split["phase"] if row["complete"] else "未完", direction=split["direction"])
        groups[group_key].append(row)
    for (candidate, symbol), rows in groups.items():
        expected = sum(audit["symbol"] == symbol for audit in source["audits"])
        if not expected or len(rows) != expected:
            raise ValueError(f"全場の結果が不足しています。{candidate}/{symbol}: {len(rows)}/{expected}")
        rows.sort(key=lambda row: (audits[key(row)].get("start_ns", 0), row["session"]))
    return ids, groups, audits


def detail_filename(candidate: str, symbol: str) -> str:
    """
    機能: 固定候補と銘柄から詳細Markdown名を作成します。
    引数: candidate と symbol は str 型の固定候補IDと銘柄です。
    返り値: str 型の詳細ファイル名です。
    """
    return f"{SYMBOL_LABELS[symbol]}_{candidate}.md"


def detail_text(candidate: str, symbol: str, rows: list[dict]) -> str:
    """
    機能: 一つの候補と銘柄の全場会計を記載します。
    引数: candidate と symbol は str 型、rows は list[dict] 型の時系列場別結果です。
    返り値: str 型のMarkdownです。
    """
    complete = [row for row in rows if row["complete"]]
    lines = [f"# {SYMBOL_LABELS[symbol]} {candidate}", "", f"実手法ID：`{rows[0]['method_id']}`。金額は円。", "", "[全候補の比較へ](../全候補と損益.md)", "", "| 場（区分） | 利益 | 損失 | 収支 | 未完の含み | 未完の時価収支 |", "|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        floating = "—" if row["complete"] else display(row["unrealized_yen"])
        equity = "—" if row["complete"] else display(row["final_equity_yen"])
        lines.append(f"| {row['session']}（{row['phase']}） | {display(row['gross_profit_yen'])} | {display(row['gross_loss_yen'])} | {display(row['realized_yen'])} | {floating} | {equity} |")
    lines.extend([f"| 完全場累計（{len(complete)}場） | {display(total(complete, 'gross_profit_yen'))} | {display(total(complete, 'gross_loss_yen'))} | {display(total(complete, 'realized_yen'))} | — | — |", "", "0は実際のゼロ、欠測は値なし。—は完了した場では対象外。未完の含み・時価収支は完全場累計へ加算しない。", ""])
    return "\n".join(lines)


def index_text(ids: list[str], groups: dict, selection: dict) -> str:
    """
    機能: 昼夜別の検討・確認比較と全詳細への索引を作成します。
    引数: ids は list[str] 型の候補ID、groups は dict 型の全場、selection は dict 型の選定結果です。
    返り値: str 型のMarkdownです。
    """
    chosen = {(row["symbol"], row["kind"]): row for row in selection.get("selected", [])}
    lines = ["# 全候補と損益", "", "72候補を各銘柄の時系列前34場で検討し、後23場で確認した。以下の収支と新規回数は完全な場だけを集計する。金額は円。", "", "日経225mini・TOPIXminiとも片方向10枚、主比較の手数料は0円。気配差と判断後の約定を含む。利益・損失は新規から全返済までの会計で、損失は正数で表示する。未完の時価収支を完全場の累計へ加えない。", "", "| 候補・明細 | 銘柄 | 昼夜 | 扱い | 検討収支（場数） | 確認収支（場数） | 完全場合計 | 未完時価（場数） | 新規回数 |", "|---|---|---|---|---:|---:|---:|---:|---:|"]
    for candidate in ids:
        for symbol in SYMBOLS:
            for kind, kind_label in KIND_LABELS.items():
                rows = [row for row in groups[(candidate, symbol)] if row["kind"] == kind]
                full = [row for row in rows if row["complete"]]
                unfinished = [row for row in rows if not row["complete"]]
                training = [row for row in full if row["phase"] == "検討"]
                confirmation = [row for row in full if row["phase"] == "確認"]
                choice = chosen.get((symbol, kind), {})
                status = "検討選定" if choice.get("method_id") == candidate else "選定の対照" if choice.get("control_id") == candidate else "比較対象"
                link = f"[{candidate}](損益/{detail_filename(candidate, symbol)})"
                lines.append(f"| {link} | {SYMBOL_LABELS[symbol]} | {kind_label} | {status} | {display(total(training, 'realized_yen'))}（{len(training)}） | {display(total(confirmation, 'realized_yen'))}（{len(confirmation)}） | {display(total(full, 'realized_yen'))} | {display(total(unfinished, 'final_equity_yen'))}（{len(unfinished)}） | {display(total(full, 'entry_count'))} |")
    lines.extend(["", "0は実際のゼロ、欠測は値なし。場数0の0円は成立した取引を意味しない。選定は検討区間だけで行い、確認区間の成績で候補を選び直さない。", "", "Iは指標出口と利益追尾・保険損切り、Tは同入口で指標通常出口を外した対照、FはIに早期利益床を加えた候補。保険損切りは約定建値比0.30%、利益追尾は順行0.10%で開始し0.05%戻り、Fの利益床は順行0.04%到達後の利益0.01%。床の利益は約定保証ではない。", "", "入力は今回作成した `work/research170/summary.json` と `work/research170/rootselection.json`。原板は前者の監査一覧のpath・sha256・行数で特定できる。分足の確定時刻・約定と原行の照合はSessionViewer用資料を参照する。", "", "指標の一次資料：[移動平均](https://info.monex.co.jp/technical-analysis/indicators/001.html)、[MACD](https://info.monex.co.jp/technical-analysis/indicators/002.html)、[ボリンジャーバンド](https://info.monex.co.jp/technical-analysis/indicators/003.html)、[RSI](https://info.monex.co.jp/technical-analysis/indicators/005.html)、[DMI](https://info.monex.co.jp/technical-analysis/indicators/015.html)。", ""])
    return "\n".join(lines)


def save_verified(destination: Path, text: str) -> None:
    """
    機能: UTF-8で保存し、再読取した本文が一致することを確認します。
    引数: destination は Path 型の保存先、text は str 型の本文です。
    返り値: None。不一致の場合は例外を送出します。
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(destination)
    if destination.read_text(encoding="utf-8") != text:
        raise ValueError(f"保存後の本文が一致しません。{destination}")


def main() -> None:
    """
    機能: 今回の実計算結果から索引1個と詳細144個を作成します。
    引数: なし。コマンドラインから入力JSONと出力先を受け取ります。
    返り値: None。架空の金融入力や別形式の損益表は作成しません。
    """
    parser = argparse.ArgumentParser(description="全候補と各候補の損益Markdownを作成します。")
    parser.add_argument("--input", type=Path, default=OWN_DIR / "summary.json")
    parser.add_argument("--selection", type=Path, default=OWN_DIR / "rootselection.json")
    parser.add_argument("--output", type=Path, default=STUDY)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    ids, groups, _ = prepare(source, selection)

    # ----------------------------------------
    # 検証済みの元入力からだけ詳細と概要を保存します。
    outputs = []
    for candidate in ids:
        for symbol in SYMBOLS:
            destination = args.output / "損益" / detail_filename(candidate, symbol)
            save_verified(destination, detail_text(candidate, symbol, groups[(candidate, symbol)]))
            outputs.append(destination)
    index = args.output / "全候補と損益.md"
    save_verified(index, index_text(ids, groups, selection))
    if len(outputs) != 144 or len(set(outputs)) != 144:
        raise ValueError("詳細資料が144ファイルになっていません。")
    for destination in outputs:
        body = destination.read_text(encoding="utf-8")
        candidate = destination.stem.split("_", 1)[1]
        symbol = "NK225" if destination.stem.startswith("日経_") else "TOPIX"
        expected_rows = len(groups[(candidate, symbol)])
        if sum(line.startswith("| 20") for line in body.splitlines()) != expected_rows:
            raise ValueError(f"全セッションの行数が一致しません。{destination}")
    print(json.dumps({"概要": str(index), "詳細ファイル数": len(outputs), "元入力結果数": len(source["results"]), "元入力会計照合": "一致", "保存後再読取": "一致", "全場行数": "一致"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
