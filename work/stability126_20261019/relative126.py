"""保存済み会計から相対的な第一候補と次善を示し、過去目標による合否表示を訂正する。"""

import copy
import json
import re
from pathlib import Path

from common126 import HERE, PUBLIC, ROOT, read, save, sha


def execute() -> None:
    """
    機能: 新たな売買再生をせず、完成会計を照合して案内と表示の評価方法を訂正する。
    引数: なし。
    返り値: None。訂正前の資料、出典指紋、相対評価、表示更新の記録を保存する。
    """
    output = HERE / "relative126"
    assert not output.exists()
    output.mkdir()
    integrated_path = HERE / "最終統合の価格モデル別比較と公開会計.json"
    integrated = read(integrated_path)
    bbo = next(m for m in integrated["models"] if m["id"] == "next_normal_bbo")
    source_hashes = {r["path"]: r["sha256"] for m in integrated["models"] for r in m["sources"]}
    source_hashes[integrated_path.relative_to(ROOT).as_posix()] = sha(integrated_path)
    assert all(sha(ROOT / name) == digest for name, digest in source_hashes.items())
    originals = [row for reference in bbo["sources"] for row in read(ROOT / reference["path"])["rows"]]
    metrics = {}
    for method in ("GU_Q", "G_Q"):
        products = {}
        saved = next(r for r in bbo["ranking"] if r["id"] == method)
        for symbol in ("TOPIX", "NK225"):
            rows = [r for r in originals if r["method"] == method and r["symbol"] == symbol]
            assert len(rows) == 41 and len({r["session"] for r in rows}) == 41
            positive = [r["net"] for r in rows if r["net"] > 0]
            negative = [-r["net"] for r in rows if r["net"] < 0]
            value = dict(profit=sum(r["profit"] for r in rows), loss=sum(r["loss"] for r in rows),
                         net=sum(r["net"] for r in rows), red=len(negative), black=len(positive),
                         worst=min(r["net"] for r in rows),
                         average_positive=sum(positive) / len(positive),
                         average_negative=sum(negative) / len(negative),
                         regimes=saved["products"][symbol]["regimes"],
                         strong_regimes=saved["products"][symbol]["strong_regimes"])
            value["average_win_loss_ratio"] = value["average_positive"] / value["average_negative"]
            for field in ("profit", "loss", "net", "red", "black", "worst"):
                assert value[field] == saved["products"][symbol][field]
            products[symbol] = value
        metrics[method] = products

    # ----------------------------------------
    # 表示する選択肢を追加し、既存会計の数値をそのまま保存する。
    report = PUBLIC / "E01改修のセッション損益.html"
    text = report.read_text(encoding="utf-8")
    match = re.search(r'(<script id="accounts" type="application/json">)(.*?)(</script>)', text, re.S)
    assert match is not None
    payload = json.loads(match.group(2))
    before_payload = copy.deepcopy(payload)
    for model in payload["models"]:
        for method in model["methods"]:
            method["name"] = method["name"].replace("（条件未達の比較代表）", "")
    view = next(m for m in payload["models"] if m["id"] == "next_normal_bbo")
    next(m for m in view["methods"] if m["id"] == "GU_Q")["name"] = "総合第一候補：入口再確認・米国寄付き回避・気配予算"
    assert not any(m["id"] == "G_Q" for m in view["methods"])
    view["methods"].insert(1, dict(id="G_Q", name="次善：入口再確認・気配予算"))
    fields = ("method", "session", "symbol", "profit", "loss", "net")
    addition = [{k: r[k] for k in fields} for r in originals if r["method"] == "G_Q"]
    assert len(addition) == 82
    view["rows"].extend(addition)
    for previous in before_payload["models"]:
        current = next(m for m in payload["models"] if m["id"] == previous["id"])
        assert current["rows"][:len(previous["rows"])] == previous["rows"]
    payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    updated_report = text[:match.start(2)] + payload_text + text[match.end(2):]

    # ----------------------------------------
    # 最新のユーザー指定を方針へ記録し、今回分の案内だけを修正する。
    old_summary = "条件を満たす手法は未発見。比較代表はGU_Q（入口再確認と米国寄付き回避・気配予算）。TOPIX累計+267,500円・赤字18/41場。NK225累計+91,000円・赤字17/41場。"
    summary = "相対比較の第一候補はGU_Q、次善はG_Q。GU_QはTOPIX累計+267,500円・赤字18/41場、日経累計+91,000円・赤字17/41場。G_Qは平均黒字場と平均赤字場の金額バランスを改善する一方、赤字場がTOPIX21場・日経18場へ増える。"
    changes = {report: updated_report}
    for name in ("README.md", "アルゴリズム調査/README.md", "アルゴリズム調査/index.html",
                 "アルゴリズム調査/共通/知見台帳/README.md", "アルゴリズム調査/共通/知見台帳/出口.md",
                 "アルゴリズム調査/00126_E01の損失抑制と方向偏りの再検証/README.md",
                 "アルゴリズム調査/調査方針.md"):
        path = ROOT / name
        original = path.read_text(encoding="utf-8")
        assert original.count(old_summary) == 1, name
        changes[path] = original.replace(old_summary, summary)
    policy_path = ROOT / "アルゴリズム調査/調査方針.md"
    old_criterion = "手数料0、各場参加、平均価格0.5%の直近目標は取り消されていないため内部で評価する。"
    assert old_criterion in changes[policy_path]
    changes[policy_path] = changes[policy_path].replace(old_criterion,
        "今回の評価について、ユーザーは具体的な数値基準を指定せず、ベストとベターの相対比較を求めると明確化した。過去の平均価格0.5%・利益割合65%・赤字20%・平均収支額などを合否条件として持ち込まない。負け場の少なさ、負けの金額、平均的な勝ち負けの幅、方向別成績を併せて順位とトレードオフを示す。手数料0の比較とし、過去目標で計算した保存済み判定は歴史的記録として区別する。")
    agents_path = ROOT / "AGENTS.md"
    original = agents_path.read_text(encoding="utf-8")
    old_latest = "- ユーザーは各セッション各銘柄で最低1回の実新規と、平均で価格自体の0.5%幅（TOPIX4,000なら20pt）を目標に確定した。"
    assert old_latest in original
    changes[agents_path] = original.replace(old_latest,
        "- 最新のユーザー訂正では、今回の評価は具体的な数値目標による合否ではなく、負け場の少なさ・負けの小ささ・上昇下落への偏りからベストとベターを選ぶ相対比較とする。以前の各場参加・平均価格0.5%等の数値目標を今回の必須条件へ持ち込まない。")
    readme_path = PUBLIC / "README.md"
    changes[readme_path] = changes[readme_path].replace("元E01、G、GUとの比較", "第一候補GU_Q・次善G_Qと、元E01、G、GUとの比較")
    details = "\n\n今回の選定は数値目標の合否ではなく相対比較です。GU_Qは両市場の方向を再確認し、米国寄付き前後15分と広い気配を避け、E01の途中判断・返済を使います。G_Qは米国寄付き前後の静観だけを外します。平均黒字場／平均赤字場の金額比は、GU_QがTOPIX1.04倍・日経0.87倍、G_Qが1.27倍・0.94倍。方向別ではTOPIXの上昇場への弱さが両方に残るため、上下への安定を完成したとは説明しません。\n\n今回の訂正と保存会計の照合は [相対評価の記録](../../work/stability126_20261019/relative126/相対評価と訂正記録.json) を参照してください。以下の旧作業記録・敵対的レビューには、当時持ち込んだ数値目標による判定が残っています。今回の第一候補選定とは区別します。\n"
    marker = "\n詳しい条件・工程は"
    assert marker in changes[readme_path]
    changes[readme_path] = changes[readme_path].replace(marker, details + marker)

    # ----------------------------------------
    # 更新前の表示と文章を保存し、会計源を変更していないことを確認する。
    edits = []
    for path, content in changes.items():
        relative = path.relative_to(ROOT)
        backup = output / "修正前" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(path.read_bytes())
        before_sha = sha(path)
        path.write_text(content, encoding="utf-8")
        edits.append(dict(path=relative.as_posix(), before_sha256=before_sha,
                          after_sha256=sha(path), backup=backup.relative_to(ROOT).as_posix()))
    assert all(sha(ROOT / name) == digest for name, digest in source_hashes.items())
    save(output / "相対評価と訂正記録.json", dict(
        passed=True, financial_replays=0, original_market_reads=0,
        criterion="今回は過去の数値目標を合否に用いず、負け場・損益幅・方向偏りの相対比較とする。",
        first="GU_Q", second="G_Q", metrics=metrics, unchanged_sources=source_hashes,
        old_display_rows_unchanged=True, added_saved_rows=len(addition), edits=edits,
        limitation="全41場は既知開発。上昇場の弱さが残り、将来の安定を保証した選定ではない。"))
    visual_source = (HERE / "visual126.py").read_text(encoding="utf-8")
    assert visual_source.count('HERE / "visual_final"') == 1
    (HERE / "visual_relative126.py").write_text(
        visual_source.replace('HERE / "visual_final"', 'HERE / "relative_visual"'), encoding="utf-8")
    print(json.dumps(dict(passed=True, financial_replays=0, report_sha256=sha(report),
                          methods=[m["id"] for m in view["methods"]]), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    execute()
