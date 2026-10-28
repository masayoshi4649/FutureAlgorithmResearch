"""二巡の保存結果だけから、先着確率と全場の表を作る。再評価はしない。"""

from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PUBLIC = ROOT/"アルゴリズム調査/00161_日経100円先着の独立入口探索"
PHASE_NAMES = {"Day": "日中", "preUS": "夜間・米国前", "postUS": "夜間・米国後"}


def read(path: Path) -> dict:
    """UTF-8の保存結果を読む。

    引数: path(Path)。返り値: dict。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ratio(wins: int, count: int) -> str:
    """分子分母を併記した観測率を返す。

    引数: wins/count(int)。返り値: str。信号なしを成功としない。
    """
    return f"{wins}/{count}＝{wins/count:.1%}" if count else "0件・未測定"


def main() -> None:
    """合格済み保存結果を選択候補の表へまとめる。

    引数: なし。返り値: None。新たな条件採択をしない。
    """
    assert read(HERE/"audit/audit161.json")["passed"]
    assert read(HERE/"round2/audit/audit161r2.json")["passed"]
    manifest = read(HERE/"inputs161.json")
    summaries = []
    lines = ["# 選択された入口の全セッション先着率", "",
             "100円順行が50円逆行より先なら成功。未到達・次正常板なしも全信号分母に残す。枚数・金額損益の評価ではない。",
             "第一巡も過去研究で既知の資料。第二巡の後半は第一巡を見た後の追加開発であり、未見検証ではない。", ""]
    comparisons = ["# 全58条件の開発比較", "", "表は前30場の学習と次10場の選択の結果。後半は選択済み候補だけを採点した。", ""]
    for number, folder in ((1, HERE), (2, HERE/"round2")):
        train = read(folder/"results/train_validation161.json")
        test = read(folder/"results/locked_test161.json")
        freeze = read(folder/"results/selection_frozen161.json")
        for phase, selected in freeze["selected"].items():
            records = train["reports"][phase][selected]
            samples = {stage: train["events"][stage][phase][selected] for stage in ("train", "validation")}
            samples["test"] = test["events"][phase]
            total = [event for values in samples.values() for event in values]
            side = {direction: {"events": sum(e["side"] == direction for e in total),
                                "successes": sum(e["side"] == direction and e["status"] == 1 for e in total)} for direction in (1, -1)}
            summaries.append({"round": number, "phase": phase, "candidate": selected,
                              "train": records["train"], "validation": records["validation"],
                              "test": test["reports"][phase], "test_baselines": test["baselines"][phase],
                              "all": {"events": len(total), "successes": sum(e["status"] == 1 for e in total), "side": side}})
            lines += [f"## 第{number}巡・{PHASE_NAMES[phase]}・{selected}", "",
                      "|セッション|用途|成功|逆行先着|未到達|次板なし|全信号|成功率|", "|---|---|---:|---:|---:|---:|---:|---:|"]
            for scene in manifest["sessions"]:
                if scene["kind"] != ("Day" if phase == "Day" else "Night"):
                    continue
                rows = [e for e in samples[scene["split"]] if e["session"] == scene["session"]]
                count = Counter(e["status"] for e in rows)
                status = {"train": "学習", "validation": "選択", "test": "固定後確認" if number == 1 else "既知追加確認"}[scene["split"]]
                pct = f"{count[1]/len(rows):.1%}" if rows else "未測定"
                lines.append(f"|{scene['session']}|{status}|{count[1]}|{count[-1]}|{count[0]}|{count[-2]}|{len(rows)}|{pct}|")
            count = Counter(e["status"] for e in total)
            lines += [f"|合計|選択用を含む|{count[1]}|{count[-1]}|{count[0]}|{count[-2]}|{len(total)}|{count[1]/len(total):.1%}|", "",
                      "時間帯ごとに予測を独立管理するため、米国前後の予測期間は重なり得る。合算して単一戦略の売買成績とは扱わない。", ""]
        for phase, records in train["reports"].items():
            comparisons += [f"## 第{number}巡・{PHASE_NAMES[phase]}", "",
                            "|条件|学習|選択|選択への資格|採択|", "|---|---:|---:|---|---|"]
            for key, rec in records.items():
                reason = "; ".join(rec["train_exclusions"]+rec["validation_exclusions"]) or "適格"
                chosen = "採択" if freeze["selected"].get(phase) == key else ""
                comparisons.append(f"|{key}|{ratio(rec['train']['successes'],rec['train']['events'])}|{ratio(rec['validation']['successes'],rec['validation']['events'])}|{reason}|{chosen}|")
            comparisons.append("")
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC/"全セッションの先着率.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    (PUBLIC/"全候補の開発比較.md").write_text("\n".join(comparisons)+"\n", encoding="utf-8")
    (HERE/"報告用集計161.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print("二巡の選択条件と全場の先着率を保存しました。", flush=True)


if __name__ == "__main__":
    main()
