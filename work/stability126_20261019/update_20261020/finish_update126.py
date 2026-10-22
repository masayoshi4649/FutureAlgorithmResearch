"""追加二場の公開確認後に案内・知見の追跡値と試行の完了記録を整える。"""

import copy
import json
from pathlib import Path
import re
import subprocess
import sys

from run_update126 import HERE, ROOT, RESULT_NAME, read, save, sha
from register_update126 import MANAGER, TRIAL


PUBLIC = ROOT / "アルゴリズム調査/00126_E01の損失抑制と方向偏りの再検証"


def update(path: Path, text: str, records: list) -> None:
    """
    機能: 更新前の案内を専用領域へ保存してから最新値へ差し替える。
    引数: path(Path)、text(str)、records(list)は対象、更新内容、証跡格納先。
    返り値: None。数値会計の旧保存資料には書き込まない。
    """
    relative = path.relative_to(ROOT)
    previous = HERE / "案内更新前" / relative
    assert not previous.exists()
    previous.parent.mkdir(parents=True, exist_ok=True)
    previous.write_bytes(path.read_bytes())
    path.write_text(text, encoding="utf-8")
    records.append(dict(path=relative.as_posix(), before_sha256=sha(previous), after_sha256=sha(path)))


def main() -> None:
    """
    機能: 確認済み四十三場の案内を公開し、新試行だけを完了状態へ更新する。
    引数: なし。
    返り値: None。旧四十一場の順位や金融結果を再選定・再生しない。
    """
    public = read(HERE / "公開更新の記録.json")
    view = read(HERE / "visual/全選択と全場会計の実描画確認.json")
    visual = read(HERE / "visual/目視確認.json")
    assert public["passed"] and view["passed"] and visual["passed"] and visual["root_viewed"]
    assert public["after_sha256"] == view["html_sha256"] == visual["html_sha256"]
    result = read(HERE / RESULT_NAME)
    cumulative = {(r["model"], r["method"], r["symbol"]): r for r in public["cumulative"]}
    selected = {symbol: cumulative["next_normal_bbo", "GU_Q", symbol] for symbol in ("TOPIX", "NK225")}
    description = ("旧41場の第一候補GU_Q・次善G_Qを固定し、10月19日ナイトと20日デイを追加して全43場へ更新。"
        f"GU_QはTOPIX累計{selected['TOPIX']['net']:+,.0f}円・赤字{selected['TOPIX']['red']}/43場、"
        f"日経累計{selected['NK225']['net']:+,.0f}円・赤字{selected['NK225']['red']}/43場。")
    edits = []
    for name in ("README.md", "アルゴリズム調査/README.md", "アルゴリズム調査/共通/知見台帳/README.md"):
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        match = re.search(r"<!--00126案内-->.*?<!--00126案内終了-->", text, re.S)
        assert match
        current = match.group()
        link = re.search(r"\[00126：.*?\]\((.*?)\)", current)
        assert link
        replacement = ("<!--00126案内-->\n最新：[00126：E01改修の全43場損益](" + link.group(1) + ")。" + description + "\n<!--00126案内終了-->")
        update(path, text[:match.start()] + replacement + text[match.end():], edits)
    index = ROOT / "アルゴリズム調査/index.html"
    text = index.read_text(encoding="utf-8")
    match = re.search(r"<!--00126開始-->.*?<!--00126終了-->", text, re.S)
    assert match
    block = re.sub(r"<p>.*?</p>", "<p>" + description + "</p>", match.group(), count=1, flags=re.S)
    block = block.replace("全41セッション", "全43セッション")
    update(index, text[:match.start()] + block + text[match.end():], edits)
    public_readme = ("# E01の損失抑制と方向偏りの再検証\n\n"
        "最初に見るファイルは [E01改修のセッション損益](E01改修のセッション損益.html) です。"
        "全43セッションの利益・損失・収支と累計を表示します。主表示5手法と参考Last3手法を切り替えられます。\n\n"
        + description + "\n\n"
        "TOPIXミニ初回5枚・片方向上限10枚、日経マイクロ初回10枚・上限20枚。追加と復元なし。"
        "手数料0円、全玉を場内返済。主表示はラージ板代理の次正常原行BBO約定です。\n\n"
        "GU_Qは両市場の方向を再確認し、米国寄付き前後15分と広い気配を避け、E01の途中判断・返済を使います。"
        "G_Qは米国寄付き前後の静観だけを外します。旧41場で選んだ数値条件を今回の追加成績で変更していません。\n\n"
        "読む順序は、[追加二場の作業記録](../../work/stability126_20261019/update_20261020/README.md)、"
        "[旧41場の相対評価訂正](../../work/stability126_20261019/relative126/相対評価と訂正記録.json)、"
        "[当初の作業記録](../../work/stability126_20261019/README.md)です。"
        "旧数値目標による合否と、今回求められたベスト・ベターの相対比較を区別します。\n")
    update(PUBLIC / "README.md", public_readme, edits)
    policy_path = ROOT / "アルゴリズム調査/調査方針.md"
    policy = policy_path.read_text(encoding="utf-8")
    marker = "\n<!--00126追加20261020-->\n"
    assert marker not in policy
    update(policy_path, policy + marker + description + " 新しい閾値探索と過去41場の再生は行わず、既存公開8選択の追加2場だけを検証する。手数料0・場内全返済・気配代理模型は従来どおり。\n<!--00126追加20261020終了-->\n", edits)
    ledger = ROOT / "アルゴリズム調査/共通/知見台帳/出口.md"
    text = ledger.read_text(encoding="utf-8")
    assert '<a id="00126_二場追加の固定追跡"></a>' not in text
    follow = ("\n\n<a id=\"00126_二場追加の固定追跡\"></a>\n\n"
        "## 同じ入口・途中判断・出口を固定した追加二場の追跡\n\n"
        "**出典：** [00126_E01の損失抑制と方向偏りの再検証](../../00126_E01の損失抑制と方向偏りの再検証/README.md)。\n\n"
        "**範囲：** 2026年10月19日ナイトと20日デイ。旧41場は保存引用し、新二場だけを公開済み条件で処理。"
        "主表示BBO5選択と参考Last3選択を混同せず、以下はGU_Q・G_Qの次正常原行BBO模型。手数料0。\n\n"
        "| 手法 | 追加セッション | TOPIX収支 | 日経収支 |\n| --- | --- | ---: | ---: |\n")
    for method in ("GU_Q", "G_Q"):
        for scene in result["sessions"]:
            values = {r["symbol"]: r["net"] for r in result["rows"] if r["method"] == method and r["session"] == scene and r["model"] == "next_normal_bbo"}
            follow += f"| {method} | {scene} | {values['TOPIX']:+,.0f}円 | {values['NK225']:+,.0f}円 |\n"
    follow += ("\n**使い方・限界：** 2場は追加時点で条件を固定した追跡結果であり、2場だけの勝敗を法則の確立や再選定へ使わない。"
        "今回の結果で過去41場の同一会計を書き換えない。\n\n"
        "**根拠：** [追加会計と固定条件](../../../work/stability126_20261019/update_20261020/追加二場の八公開選択会計.json)、"
        "[独立会計監査](../../../work/stability126_20261019/update_20261020/audit/追加二場三十二会計の全注文と全行清算の独立監査.json)。\n")
    update(ledger, text + follow, edits)
    (HERE / "README.md").write_text("# 2026年10月20日の追加二場更新\n\n" + description + "\n\n"
        "最初に見るファイルは [公開損益HTML](../../../アルゴリズム調査/00126_E01の損失抑制と方向偏りの再検証/E01改修のセッション損益.html)。"
        "次に [追加会計](追加二場の八公開選択会計.json)、[全注文と全行清算の独立監査](audit/追加二場三十二会計の全注文と全行清算の独立監査.json) を参照。\n\n"
        "既存41場は再生せず保存結果を引用。追加2場のLast3・BBO5だけを計算し、同じ商品場の完全同値条件は引用する。"
        "ローカルに無かった日経生板2本は、既存取得ツールの共有保存元にある終了済みファイルを10Mbpsで専用領域へ取得。"
        "研究原本のbook・candle_1min・candle_5minへ書込みなし。現在API・実注文なし。\n", encoding="utf-8")

    # ----------------------------------------
    # 完了状態の変更は今回追加試行だけへ限定する。
    trials_path = MANAGER.parent / "data/trials.json"
    registry = read(trials_path)
    before = copy.deepcopy(registry)
    row = next(r for r in registry["trials"] if r["id"] == TRIAL)
    row["status"] = "検証完了・条件固定で二場追加"
    row["result_summary"] = description
    for path in (HERE / RESULT_NAME, HERE / "全四十三場の公開会計.json",
                 HERE / "audit/追加二場三十二会計の全注文と全行清算の独立監査.json"):
        row.setdefault("evidence", []).append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha(path)))
    assert [r for r in registry["trials"] if r["id"] != TRIAL] == [r for r in before["trials"] if r["id"] != TRIAL]
    save(HERE / "登録後の完了前台帳.json", before)
    trials_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    for command, args in (("build", []), ("verify", ["--deep"])):
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(MANAGER), command, *args],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        save(HERE / ("完了後の" + command + ".json"), dict(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr))
        assert process.returncode == 0, process.stderr[-1200:]
    save(HERE / "二場追加の公開と案内及び台帳の完了.json", dict(passed=True, sessions=43, edits=edits,
        trial=TRIAL, other_trials_unchanged=True, report_sha256=public["after_sha256"],
        financial_replays_in_this_step=0, new_financial_accounts=result["new_financial_accounts"]))
    print("全43場の損益・案内・共通知見の追跡・試行台帳を更新完了", flush=True)


if __name__ == "__main__":
    main()
