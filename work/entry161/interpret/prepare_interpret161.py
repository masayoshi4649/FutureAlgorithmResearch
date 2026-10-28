"""凍結済みtrain/validationの結果だけを読み、候補選択と失敗理由を整理する。testは扱わない。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


PHASES = {"Day": "日中", "preUS": "米国開始前", "postUS": "米国開始以後"}
FAMILIES = {"M": "即時の勢い", "A": "加速", "P": "押し戻し後の再開", "R": "失速後の反転",
            "B": "板圧力と価格受容", "S": "補充と吸収の代理", "L": "二市場の先行一致", "C": "圧縮後の放出",
            "GL": "L2ロジット", "DT": "深さ2分類木"}
MODEL_NAMES = ["方向付き5秒値幅", "方向付き15秒値幅", "方向付き60秒値幅", "方向付き120秒値幅", "方向付き300秒値幅",
               "方向付き5〜10秒前値幅", "方向付き5秒対15秒の加速", "方向付きOFI5", "方向付きOFI15",
               "方向付き距離加重板偏り", "方向付き最良数量偏り", "方向付きマイクロ価格差", "方向付きTOPIX15秒変化",
               "方向付きTOPIX60秒変化", "気配差", "60秒値幅帯", "直前60秒値幅帯", "60秒価格効率", "相手板の古さ",
               "方向付き高安内位置", "方向側と反対側の補充差"]
RULE_EXPLANATIONS = {
    "M": "直近5秒・15秒の進行が同方向で、60秒の往復が多すぎない時に入る。",
    "A": "直近5秒の速度が15秒平均より強まり、価格と板増減も同じ方向を向いた時に入る。",
    "P": "2分の方向に一度押した後、直近5秒が元の方向へ戻った時に入る。",
    "R": "1分の下落・上昇の後、15秒と5秒が逆方向へ転じた時に入る。",
    "B": "方向側の板数量と増減が優位で、価格も逆行せず高安帯の方向側にいる時に入る。",
    "S": "逆向きの板増減でも価格が崩れず、方向側の数量が補充されて反発した時に入る。真の吸収を直接識別したものではない。",
    "L": "TOPIXが先に動き、遅れていた日経も同じ方向へ動き始めた時に入る。",
    "C": "狭い値幅帯から高値・安値を抜け、短期の値幅と板増減が同方向へ広がった時に入る。",
    "GL": "過去期間だけで学習した価格・板・二市場の合成スコアが固定閾値を超えた方向へ入る。",
    "DT": "過去期間だけで学習した最大二段の条件分岐で、固定閾値を超える葉に入った方向へ入る。",
}


def read_json(path):
    """開発結果又は選択凍結だけを読む。

    引数: path(Path)。返り値: dict。test名の入力を拒否する。
    """
    path = Path(path)
    if "test" in path.name.lower() or path.name not in ("train_validation161.json", "selection_frozen161.json"):
        raise ValueError("この解釈器は指定した開発結果と選択凍結だけを扱います")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def pct(value):
    """率を百分率表示する。

    引数: value(float又はNone)。返り値: str。
    """
    return "未測定" if value is None else f"{value*100:.1f}%"


def fraction(row):
    """成功の分子と全採用分母をまとめる。

    引数: row(dict)。返り値: str。
    """
    return f"{row['successes']}/{row['events']}（{pct(row['success_probability'])}）"


def family_of(candidate):
    """IDから固定familyを取り出す。

    引数: candidate(str)。返り値: str。
    """
    return candidate[:-2]


def rank(record):
    """選択器と同じ開発順位を保存結果だけから再構成する。

    引数: record(dict)。返り値: tuple。
    """
    row = record["validation"]
    if row["events"] == 0:
        return (-1, -1, 0)
    return (min(row["wilson95"][0], row["session_cluster95"][0]), row["success_probability"], row["events"])


def describe_model(phase, candidate, frozen):
    """選択された単純学習器の固定係数又は分岐を説明用に出す。

    引数: phase/candidate(str)、frozen(dict)。返り値: dict。
    係数を因果的な効き目や校正済み確率へ読み替えない。
    """
    family = family_of(candidate)
    if family not in ("GL", "DT"):
        return {}
    trained = frozen["models"][phase]
    names = MODEL_NAMES + [f"欠測指示：{name}" for name in MODEL_NAMES]
    model = trained[family]
    threshold = (.4, .5, .6, .7, .8)[int(candidate[-2:])-1]
    if family == "GL":
        weights = list(zip(names, model["coefficient"][1:]))
        weights.sort(key=lambda x: (-abs(x[1]), x[0]))
        return dict(type=family, threshold=threshold, intercept=model["coefficient"][0],
                    top_coefficients=[dict(feature=name, coefficient=value) for name, value in weights[:8]],
                    interpretation="連続列はtrain標準化後、欠測指示は0/1。相関した特徴を含み、因果効果ではない。")
    nodes = []
    pending = [("根", model)]
    while pending:
        path, node = pending.pop(0)
        record = dict(path=path, train_probability=node["probability"], train_count=node["count"])
        if "column" in node:
            column = node["column"]
            boundary = node["threshold"]
            record.update(feature=names[column], standardized_threshold=boundary)
            if column < len(MODEL_NAMES):
                record["raw_threshold_after_imputation"] = boundary * trained["preprocess"]["std"][column] + trained["preprocess"]["mean"][column]
            pending.extend(((path+"/以下", node["left"]), (path+"/超", node["right"])))
        nodes.append(record)
    return dict(type=family, threshold=threshold, nodes=nodes,
                interpretation="葉の率は学習アンカー内の値であり、独立した後半の入口成功率ではない。")


def analyze(report, frozen):
    """全34候補を保ちつつ、familyと選択理由を重複集計せず整理する。

    引数: report/frozen(dict)。返り値: dict。
    """
    result = dict(selected=frozen["selected"], phases={}, new_financial_measurements=0,
                  source_stage="train/validationのみ。test未閲覧。", pooled_candidate_sample_size=None)
    for phase, records in report["reports"].items():
        excluded = Counter()
        eligible = []
        for candidate, record in records.items():
            for reason in record["train_exclusions"]:
                excluded["train:"+reason] += 1
            for reason in record["validation_exclusions"]:
                excluded["validation:"+reason] += 1
            if not record["train_exclusions"] and not record["validation_exclusions"]:
                eligible.append(candidate)
        families = {}
        for family in FAMILIES:
            names = [key for key in records if family_of(key) == family]
            permitted = [key for key in names if key in eligible]
            if permitted:
                representative = sorted(permitted, key=lambda key: (*(-v for v in rank(records[key])), key))[0]
                rule = "適格候補内の登録済み順位"
            else:
                representative = sorted(names, key=lambda key: (-records[key]["validation"]["events"], key))[0] if names else None
                rule = "適格なし。最多件数の代表を表示し、率で救済選択しない"
            families[family] = dict(name=FAMILIES[family], conditions=len(names), eligible=len(permitted),
                                    representative=representative, representative_rule=rule,
                                    record=records.get(representative))
        selection = frozen["selected"].get(phase)
        if selection is not None:
            assert selection in eligible
        result["phases"][phase] = dict(eligible=len(eligible), exclusions=dict(excluded),
                                      selected=selection, families=families, all_candidates=records,
                                      baselines=report["baselines"].get(phase, {}),
                                      plain_rule=RULE_EXPLANATIONS[family_of(selection)] if selection else "適格候補なし。",
                                      learned_description=describe_model(phase, selection, frozen) if selection else {})
    return result


def markdown(result):
    """長い全条件表をJSONへ分け、開発判断の要点だけをMarkdownへ整える。

    引数: result(dict)。返り値: str。
    """
    lines = ["# 新入口34条件の開発結果", "", "これはtrain/validationの探索結果であり、後半の検証成績ではない。同じ場・同じ波・複数候補の事象を独立標本へ合算していない。", ""]
    for phase, data in result["phases"].items():
        selected = data["selected"]
        lines += [f"## {PHASES[phase]}", "", f"適格条件は34条件中{data['eligible']}。選択は**{selected or 'なし'}**。", "", data["plain_rule"], ""]
        if selected:
            record = data["all_candidates"][selected]
            train, validation = record["train"], record["validation"]
            lines += [f"成功／全採用事象はtrain **{fraction(train)}**、validation **{fraction(validation)}**。validationは{validation['active_sessions']}/{validation['total_sessions']}場で活動、買い{validation['long_events']}件・売り{validation['short_events']}件。", "",
                      f"validationの内訳：100円順行が先{validation['successes']}、50円逆行が先{validation['adverse_first']}、未到達{validation['unresolved']}、未約定{validation['no_entry']}。", "",
                      f"同時刻逆方向の成功率は{pct(validation['opposite_success_probability'])}、Last補助は{pct(validation['last_success_probability'])}。いずれも主結果と違う採点であり、よい方へ変更しない。", ""]
            interval = validation.get("session_cluster95")
            if interval:
                lines += [f"場単位の参考95%区間は{pct(interval[0])}〜{pct(interval[1])}。34条件から選んだ同じ開発期間なので、未見での成功保証や多重探索調整済み有意性ではない。", ""]
            external = data["baselines"].get("validation", {}).get("基準_固定コイントス")
            if external:
                lines += [f"60秒固定格子のコイントス対照は{fraction(external)}。入口時刻が異なるので、この差だけを方向判断の因果効果にしない。", ""]
            learned = data["learned_description"]
            if learned.get("type") == "GL":
                details = "、".join(f"{x['feature']} {x['coefficient']:+.3f}" for x in learned["top_coefficients"][:5])
                lines += [f"学習スコア閾値は{learned['threshold']:.2f}。絶対値の大きい係数は {details}。係数はtrain標準化尺度で、因果効果・確率校正ではない。", ""]
            elif learned.get("type") == "DT":
                branches = [x for x in learned["nodes"] if "feature" in x]
                details = "、".join(f"{x['path']}：{x['feature']}≦{x.get('raw_threshold_after_imputation', x['standardized_threshold']):.3f}" for x in branches)
                lines += [f"学習スコア閾値は{learned['threshold']:.2f}。分岐は {details or '分岐なし'}。葉の率は学習内の値であり、今回の採用事象の率とは別。", ""]
        else:
            reasons = "、".join(f"{reason}={count}条件" for reason, count in sorted(data["exclusions"].items()))
            lines += [f"除外理由は {reasons}。同じ候補に複数理由が付くため件数を合計しない。", ""]
        lines += ["|原理|適格／条件数|代表|validation成功／全件|代表の適格性|", "|---|---:|---|---:|---|"]
        for family in FAMILIES:
            row = data["families"][family]
            record = row["record"]
            qualifications = [] if record is None else record["train_exclusions"] + record["validation_exclusions"]
            note = "適格" if row["eligible"] else "／".join(sorted(set(qualifications))) or "事象なし"
            lines.append(f"|{row['name']}|{row['eligible']}/{row['conditions']}|{row['representative'] or 'なし'}|{fraction(record['validation']) if record else '未測定'}|{note}|")
        lines += ["", "適格なしの系列は最多件数の条件を代表表示した。最も高い成功率だけを拾った表ではない。", ""]
    lines += ["## 限界", "", "- 初回成功の多い候補でも、入口条件自体は過去資料から選択されている。後半の一回評価が必要。",
              "- 負けの少なさは100円／50円の先着で測った。利益延長・部分返済・数量・資金管理を含む運用損益ではない。",
              "- 米国前の予測が米国後まで続くことがある。phase別の結果を単一の非重複戦略の成功率へ合算しない。",
              "- 原板欠測中にも50円逆行がなかったという連続市場の証明はできない。観測品質の旗は成功・失敗の両方に保持する。", ""]
    return "\n".join(lines)


def main():
    """完成通知後に開発結果だけを読み、説明と全条件JSONを保存する。

    引数: CLI(report/freeze/out)。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report, frozen = read_json(args.report), read_json(args.freeze)
    if any(row["split"] == "test" for row in report.get("access", [])):
        raise ValueError("開発結果にtest読取が含まれています")
    result = analyze(report, frozen)
    result["input_sha256"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.report, args.freeze)}
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "全34候補の開発集計161.json").open("x", encoding="utf-8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")
    with (args.out / "開発解釈161.md").open("x", encoding="utf-8") as out:
        out.write(markdown(result))


if __name__ == "__main__":
    main()
