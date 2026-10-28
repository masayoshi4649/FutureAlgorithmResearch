"""公開説明の値とリンクを保存会計へ照合し、診断を新しい金融再生と区別して閉じる。"""
from pathlib import Path
from datetime import datetime
import re
from urllib.parse import unquote

from register163 import ROOT, HERE, read, sha, record, save, verify_receipt

PUBLIC = ROOT/"アルゴリズム調査/00163_元手法への局所減枚と復元"
BOOK = PUBLIC/"元手法の局所減枚と復元の全セッション損益.xlsx"


def amount(value: str) -> int:
    """公開表の整数金額を符号付き整数へ戻す。

    引数: value(str)。返り値: int。
    """
    return int(value.replace(",", "").replace("−", "-").replace("+", ""))


def event_tuple(event: dict) -> tuple:
    """具体例の約定時刻・方向・数量・価格・収支を比較用にまとめる。

    引数: event(dict)。返り値: tuple。
    """
    return (event["fill_time"][11:19], event["side"], event["qty_micro"], event["price"], event["net"])


def check_links(path: Path, content: str) -> list[dict]:
    """今回の公開部分の相対リンクと明示アンカーの実在を確認する。

    引数: path(Path)、content(str)。返り値: list[dict]。
    """
    references = re.findall(r"\]\(([^)]+)\)", content)+re.findall(r'href="([^"]+)"', content)
    checked = []
    for reference in references:
        reference = unquote(reference.strip().strip("<>"))
        assert not reference.startswith(("http:", "https:")), "今回はローカルリンクだけを確認"
        filename, _, anchor = reference.partition("#")
        target = (path.parent/filename).resolve() if filename else path
        assert target.is_relative_to(ROOT) and target.is_file(), (path, reference)
        if anchor:
            assert f'id="{anchor}"' in target.read_text(encoding="utf-8-sig"), reference
        checked.append(dict(source=path.relative_to(ROOT).as_posix(), reference=reference, target=target.relative_to(ROOT).as_posix()))
    return checked


def main() -> None:
    """表・比較値・具体売買・最新知見の引用を照合して根拠を固定する。

    引数: なし。返り値: None。原板再生、金融、順位選択、台帳更新はしない。
    """
    verify_receipt()
    summary = read(HERE/"diagnosis/比較集計163.json")
    groups = summary["groups"]
    parents = read(HERE/"diagnosis/全親差分163.json")
    examples = read(HERE/"diagnosis/具体親診断163.json")
    raw = read(HERE/"diagnosis/原板例照合163.json")
    audit = read(HERE/"audit/audit163.json")
    checked = read(HERE/"report/検算163.json")
    complete = read(HERE/"再生全完了163.json")
    assert audit["passed"] is True and checked["passed"] is True
    assert complete["completed"] is True and complete["sessions"] == 53 and complete["cases"] == 530
    assert checked["workbook_sha256"] == sha(BOOK)
    readme = (PUBLIC/"README.md").read_text(encoding="utf-8-sig")
    details = (PUBLIC/"検証記録.md").read_text(encoding="utf-8-sig")
    numeric_checks = []
    for line in readme.splitlines():
        if not re.match(r"\|(B00|D80|R80|C50)\|", line):
            continue
        cells = line.strip("|").split("|")
        group = groups[cells[0]+"_全場_全場"]
        assert amount(cells[2]) == group["net"]
        assert cells[3] == f'{group["negative_sessions"]}/53'
        assert amount(cells[4]) == group["worst_equity"]
        numeric_checks.append(dict(table="README", id=cells[0], net=group["net"], red=group["negative_sessions"], worst=group["worst_equity"]))
    assert len(numeric_checks) == 4
    for line in details.splitlines():
        if not re.match(r"\|(昼27場|夜26場)\|", line):
            continue
        cells = line.strip("|").split("|")
        kind = "Day" if cells[0] == "昼27場" else "Night"
        group = groups[cells[1]+"_"+kind+"_全場"]
        assert [amount(v) for v in cells[2:]] == [group["profit"], group["loss"], group["net"], group["negative_sessions"]]
        numeric_checks.append(dict(table="昼夜", id=cells[1], kind=kind, values=group))
    assert len(numeric_checks) == 10
    base, d80, r80 = [groups[key+"_全場_全場"] for key in ("B00", "D80", "R80")]
    assert groups["F00_全場_全場"] == d80
    assert summary["selected"] == {"Day":"D80", "Night":"D80"}
    assert d80["net"]-base["net"] == -775500
    assert (base["profit"], base["loss"], d80["profit"], d80["loss"]) == (7227000,3946000,6462500,3957000)
    assert (round(-base["mean_red"]), round(-d80["mean_red"])) == (45059,47906)
    assert (base["minimum_session"],d80["minimum_session"]) == (-115000,-109000)
    assert [groups[key+"_全場_全場"]["excluding_top3"] for key in ("B00","D80","R80")] == [2239000,1733000,2149500]
    assert (groups["B00_全場_後13"]["net"],groups["D80_全場_後13"]["net"]) == (1053000,447000)
    assert groups["B00_全場_後13"]["negative_sessions"] == groups["D80_全場_後13"]["negative_sessions"] == 5
    changed = [row for row in parents if row["id"] == "D80" and row["reduced"]]
    assert len(changed) == 99
    assert [sum(row["baseline"] > 0 for row in changed), sum(row["baseline"] < 0 for row in changed), sum(row["baseline"] == 0 for row in changed)] == [31,67,1]
    assert [sum(row["delta"] > 0 for row in changed), sum(row["delta"] < 0 for row in changed), sum(row["delta"] == 0 for row in changed)] == [64,33,2]
    assert sum(row["delta"] for row in parents if row["id"] == "D80" and row["baseline"] < 0 and row["delta"] > 0) == 371000
    assert -sum(row["delta"] for row in parents if row["id"] == "D80" and row["baseline"] > 0 and row["delta"] < 0) == 1131500
    restored = [row for row in parents if row["id"] == "R80"]
    assert (len(restored),sum(row["reduced"] for row in restored),sum(row["restored"] for row in restored)) == (304,65,46)
    assert [groups["R80_"+kind+"_全場"]["net"]-groups["G80_"+kind+"_全場"]["net"] for kind in ("全場","Day","Night")] == [483000,486000,-3000]
    assert r80["net"]-base["net"] == -124500 and r80["maximum_dd"] == base["maximum_dd"] == 294000
    assert all(groups[identity+"_全場_全場"]["no_entries"] == 0 for identity in ("B00","C50","D40","D80","G40","G80","R40","R80","E40","E80"))
    assert max((groups[identity+"_全場_全場"]["net"],identity) for identity in ("D40","D80","G40","G80","R40","R80","E40","E80"))[1] == "R80"
    # ----------------------------------------
    # 本文で示す三局面を約定行の完全な順序で照合する。
    loss = examples["D80_Day_改善"][0]
    assert loss["session"] == "2026-10-15_Day" and (loss["baseline"],loss["net"]) == (-66000,-42000)
    assert [event_tuple(event) for event in loss["baseline_events"]] == [("09:35:35","買い",20,65780,0),("09:48:54","売り",20,65450,-66000)]
    assert [event_tuple(event) for event in loss["revised_events"]] == [("09:35:35","買い",20,65780,0),("09:36:49","売り",10,65690,-9000),("09:48:54","売り",10,65450,-33000)]
    winner = examples["D80_Day_悪化"][0]
    assert winner["session"] == "2026-10-22_Day" and (winner["baseline"],winner["net"]) == (361000,158000)
    assert [event_tuple(event) for event in winner["baseline_events"]] == [("10:04:55","売り",50,64390,0),("11:22:16","買い",20,64090,60000),("13:59:29","買い",20,63510,176000),("15:35:00","買い",10,63140,125000)]
    assert event_tuple(winner["revised_events"][1]) == ("10:16:39","買い",25,64480,-22500)
    restored_winner = examples["R80_Day_悪化"][0]
    assert restored_winner["net"] == 343500
    assert [event_tuple(event) for event in restored_winner["revised_events"][1:3]] == [("10:17:13","買い",25,64490,-25000),("10:17:30","売り",25,64420,0)]
    assert next(row["net"] for row in parents if row["id"]=="G80" and row["session"]==winner["session"] and row["parent"]==winner["parent"]) == 155500
    repeat = examples["R80_Night_悪化"][0]
    assert repeat["session"] == "2026-10-21_Night" and (repeat["baseline"],repeat["net"]) == (-40000,-55000)
    assert [event_tuple(event) for event in repeat["revised_events"]] == [("23:38:06","買い",50,64930,0),("23:38:40","売り",25,64840,-22500),("23:41:56","買い",25,64900,0),("23:56:18","売り",50,64850,-32500)]
    assert len(parents) == 2432 and (len(raw["examples"]),len(raw["raw"]),raw["checked_rows"]) == (12,8,72)
    assert [audit["totals"][key] for key in ("cases","events","lots","normal_marks","policy_decisions")] == [530,10263,4286,78793530,1128]
    # ----------------------------------------
    # 過去研究の全リンクを再点検せず、今回追加した公開箇所を固定する。
    links = check_links(PUBLIC/"README.md",readme)+check_links(PUBLIC/"検証記録.md",details)
    additions = [ROOT/"アルゴリズム調査/README.md",ROOT/"アルゴリズム調査/index.html",ROOT/"アルゴリズム調査/共通/知見台帳/README.md",ROOT/"アルゴリズム調査/共通/知見台帳/出口.md",ROOT/"アルゴリズム調査/共通/知見台帳/売買の工夫.md"]
    for path in additions:
        text = path.read_text(encoding="utf-8-sig")
        selected_text = "\n".join(line for line in text.splitlines() if "00163" in line)
        links += check_links(path, selected_text)
    public_files = [PUBLIC/"README.md",PUBLIC/"検証記録.md",BOOK,*additions]
    save(HERE/"公開照合163.json",dict(passed=True,financial_replays=0,workbook_sha256=sha(BOOK),
        numeric_tables=numeric_checks,document_assertions="主要累計・昼夜内訳・比率以外の比較額・後13・大勝ち除外・親件数・三局面の全約定を保存会計へ照合",
        links=links,link_count=len(links),sources=[record(path) for path in public_files],
        implementation=record(Path(__file__)),created_at=datetime.now().astimezone().isoformat()))
    verify_receipt()
    files = [*public_files,Path(__file__),HERE/"公開照合163.json",HERE/"diagnose163.py",HERE/"extract_examples163.py",HERE/"publish163.py",
        HERE/"再生全完了163.json",HERE/"report_data163.json",HERE/"audit/audit163.json",HERE/"audit/selection_audit163.json",HERE/"report/検算163.json",
        HERE/"results/train_validation/再生完了163_train_validation.json",HERE/"results/locked_test/再生完了163_locked_test.json",
        HERE/"diagnosis/比較集計163.json",HERE/"diagnosis/全親差分163.json",HERE/"diagnosis/具体親診断163.json",HERE/"diagnosis/原板例照合163.json"]
    save(HERE/"diagnosis/診断完了163.json",dict(completed=True,sources_unchanged=True,new_financial_replay=False,source_changes=False,
        scope="登録済み金融源は不変。診断は全53場530条件場の保存会計、全2432改修親、72判断/約定原行の照合のみ。診断コード新設を金融源変更と呼ばない。",
        files=[record(path) for path in sorted(set(files))],created_at=datetime.now().astimezone().isoformat()))
    print(f"公開数値・具体三局面・{len(links)}リンクPASS。診断成果を指紋固定。")


if __name__ == "__main__":
    main()
