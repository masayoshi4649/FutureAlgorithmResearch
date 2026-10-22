"""監査済みの比較を案内と法則別知見へ接続し、今回の試行だけを閉じる。"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import re
import subprocess
import sys
from common126 import ROOT, HERE, PUBLIC, read, save, sha

NAME = PUBLIC.name
TITLE = "E01改修のセッション損益.html"
TABLE = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data"


def table_line(values: list[object]) -> str:
    """
    機能: 算術済みの値をＭａｒｋｄｏｗｎ表の一行へ変換する。
    引数: values(list[object])は数値又は表示文字列。
    返り値: strは表一行。
    """
    return "| "+" | ".join(f"{v:,.0f}" if isinstance(v, (int, float)) else str(v) for v in values)+" |"


def draft_for_common(path: object) -> str:
    """
    機能: 完成済み初段の法則草案を共通正本の相対リンクへ移す。
    引数: path(Path)は今回所有草案。
    返り値: strは出典と実測を残した追記本文。後段未測定という時点注記は後続参照へ更新。
    """
    text = path.read_text(encoding="utf-8")
    text = text[text.index('<a id="'):]
    text = text.replace("](../../../アルゴリズム調査/", "](../../")
    text = re.sub(r"\]\(\.\./(?!\.\./)([^)]+)\)",
        lambda m: "](../../../work/stability126_20261019/"+m[1]+")", text)
    text = text.replace("Ｇ・ＧＵの次気配模型と最終低リスク利益床・Ｑ条件は、この草案の完成根拠では**未測定**。",
        "後続のＧ・ＧＵ気配接続と低Ｒ・Ｑの結果は、本調査の追加項目を参照。")
    text = text.replace("Ｇ／ＧＵの気配接続と最終低リスク利益床・Ｑ条件は本草案では**未測定**。",
        "後続の低Ｒ・Ｑ対照は本調査の追加項目を参照。")
    text = text.replace("最終低リスク利益床・Ｑ条件はこの草案では**未測定**。",
        "低Ｒ・Ｑの後続実測は本調査の追加項目を参照。")
    text = text.replace("**次の未測定：** 最終低リスク利益床・Ｑ条件、Ｇ／ＧＵを次気配へ接続した追加政策は、本草案の完成証拠では**未測定**。今回のＡ・Ｌの失敗からそれらの成績を推測して埋めない。",
        "**後続確認：** 低Ｒ・ＱとＧ／ＧＵ気配接続は後段で別固定して測定した。ここに記したＡ・Ｌの数値へ混ぜず、追加項目を参照する。")
    source = f"**出典：** [{NAME}](../../{NAME}/README.md)。"
    parts = re.split(r'(?=<a id="00126_)', text)
    for i, part in enumerate(parts):
        if '<a id="' in part and "**出典：**" not in part:
            parts[i] = re.sub(r"(\n## [^\n]+\n)", r"\1\n"+source+"\n", part, count=1)
    return "".join(parts)


def execute(final_audit: object) -> None:
    """
    機能: 全最終会計と実描画の成功を要求し、今回の法則・案内・試行状態を保存する。
    引数: final_audit(Path)は追加気配会計の独立監査。
    返り値: None。市場再生・外部接続・実注文を一切行わない。
    """
    combined = read(HERE / "最終統合の価格モデル別比較と公開会計.json")
    assert combined["passed"]
    result_paths = [HERE / "原版と十五改修の全四十一場会計.json",
        HERE / "engine/bbo_next/全十六条件の次原行BBO会計.json",
        HERE / "rearm126/ＧとＧＵの全四十一場会計.json",
        HERE / "gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json"]
    results = [read(p) for p in result_paths]
    for data in results:
        assert data["passed"]
        for relative, digest in data["sources"].items():
            assert sha(ROOT / relative) == digest, relative
    audits = [HERE / "audit_result126/全千三百十二会計と全行時価及び累計の独立監査.json",
        HERE / "audit_bbo_result126/全千三百十二BBO会計と全行清算の独立監査.json",
        HERE / "rearm126/ＧＧＵ全百六十四会計と全行時価及び紙上通知の独立監査.json", final_audit]
    assert all(read(p).get("passed", False) for p in audits)
    visual = read(HERE / "visual_final/全選択と全場会計の実描画確認.json")
    viewed = read(HERE / "visual_final/目視確認.json")
    assert visual["passed"] and viewed["passed"] and viewed["root_viewed"]
    assert visual["html_sha256"] == sha(PUBLIC / TITLE)
    actual = next(m for m in combined["models"] if m["id"] == "next_normal_bbo")
    selected = actual["ranking"][0]
    best = selected["id"]
    final_passed = any(m["minimum_passed"] and m["worst_compensated_by_typical"]
        and m["previous_price_target_passed"] for m in actual["ranking"])
    names = {m["id"]: m["name"] for m in actual["methods"]}
    summary = "条件を満たす手法は未発見。" if not final_passed else "既知範囲で条件を満たす候補あり。"
    summary += f"比較代表は{best}（{names[best]}）。"
    for symbol, p in selected["products"].items():
        summary += f'{symbol}累計{p["net"]:+,.0f}円・赤字{p["red"]}/41場。'
    PUBLIC.joinpath("README.md").write_text(f'''# E01の損失抑制と方向偏りの再検証

最初に見るファイルは [E01改修のセッション損益]({TITLE}) です。選択した手法の全41セッションの利益・損失・収支と、その場までの累計だけを表示します。元E01、G、GUとの比較と、参考の観測Last模型を切り替えられます。

{summary}

TOPIXミニ初回5枚・片方向上限10枚、日経マイクロ初回10枚・上限20枚。追加と復元なし。手数料0円、全玉を場内返済。主表示はラージ売買気配代理の次正常原行約定です。参考Lastの利益を実気配の成績へ移しません。全41場は既知開発で、未知場の安定性保証ではありません。

詳しい条件・工程は [作業記録](../../work/stability126_20261019/README.md)、損失の具体箇所は [原版の実時刻診断](../../work/stability126_20261019/diagnosis_notes/原版と利益保全P03の最悪三場を確認した結論.md) と [気配負担と利益返し](../../work/stability126_20261019/diagnosis_notes/bbo/気配負担と利益返しを分けた結論.md)、最終判断は [敵対的レビュー](../../work/stability126_20261019/diagnosis_notes/最終の敵対的レビュー.md) の順で参照してください。
''', encoding="utf-8")
    counts = dict(new_financial_accounts=sum(d["new_financial_accounts"] for d in results),
        final_displayed_accounts=results[-1]["displayed_accounts"],
        final_unique_new=results[-1]["new_financial_accounts"],
        final_old_reused=results[-1]["reused_previous_accounts"],
        final_stage_aliases=results[-1]["reused_within_stage_accounts"],
        observed_displayed_accounts=1476, bbo_displayed_accounts=5658)
    HERE.joinpath("README.md").write_text(f'''# 原版E01からの損失改善

公開入口は [E01改修のセッション損益](../../アルゴリズム調査/{NAME}/{TITLE})。

{summary}

1. 原版と15改修：二市場逆行時の利益床、実赤字後の新アンカー、場全体の損失予算。旧30原版60会計は引用、新1252会計。
2. 同16条件の実建値・次正常BBO：新1312会計。買ask／売bid、手数料0、実建値1ATR予算と実際の清算時価を逐次再判定。
3. 既知G/GU：旧120を引用し追加11場44会計だけ新測定。初期方向の厳格再確認と米国寄付き前後15分の静観を原式で延長。
4. G/GU・早期床・公開気配予算Q：53条件4346表示。新規金融{counts["final_unique_new"]}、旧結果引用{counts["final_old_reused"]}、同段内同値引用{counts["final_stage_aliases"]}。同一商品場の全入力・数値核・終了・上限、初回ATR込みfeedと方策bytesを拘束し、同じ計算を繰り返して証拠に数えない。

Qは発注するという紙上通知公開行で正常気配を要求し、幅とLastからの不利差が各初回ATRの半分以下なら参加する。将来fill行の気配を見て過去注文を取り消さない。低Rは元P01の開始だけ0.25／0.5／0.75Rに変更し、両市場反対時の50%床と元影を維持する。新規と同じ波へ高速再参加する変更は入れていない。

利益／損失は返済脚の正負、parent列は完結組の正負。価格幅率はnet/(上限枚数×円倍率×場初Last)で別商品ごとに計算。上下ラベルは場初末の事後採点だけで取引へ用いない。

各金融前に源・入力・人工を固定し試行登録した。独立会計は注文現金・FIFO・全行在庫と清算時価・全返済・累計を再構成。G/GUの会計監査は実装作者による算術監査であり、別担当の非空旧新同値・公開時計・引用照合を併用する。

旧入力を再利用し、追加G素材で不足した歴史1分CSV6個だけを旧SHAへ拘束して読み取り専用複写。生板原本追加読取0、現在API0、実注文0、App変更0。ラージBBO代理の全量模型で、実ミニ・マイクロの待ち順位と真の受信時計は未観測。全41場は既知開発、未見の有効性確認ではない。

初回Last登録の形式拒否は registration_attempt1/ に源と出力を保存し、金融0のまま確定書式へ修正した。数値実装の人工・入力準備時の停止は各監査領域に残し、損失や無取引へ変換していない。
''', encoding="utf-8")
    # ----------------------------------------
    # 正本には法則と実測だけを追記し、本文の二重管理を避ける。
    knowledge = ROOT / "アルゴリズム調査/共通/知見台帳"
    appended = []
    for stage in ("入口", "継続", "出口", "売買の工夫"):
        path = knowledge / (stage+".md")
        current = path.read_text(encoding="utf-8")
        assert '<a id="00126_' not in current
        addition = draft_for_common(HERE / "knowledge_drafts" / (stage+".md"))
        path.write_text(current+"\n\n"+addition, encoding="utf-8")
        appended.append(path.relative_to(ROOT).as_posix())
    source = f"**出典：** [{NAME}](../../{NAME}/README.md)。"
    all_actual = {m["id"]: m for m in actual["ranking"]}
    lines = ["<a id=\"00126_公開気配予算の全経路対照\"></a>", "", "## 気配予算による見送りは、避けた損失と失った利益を同じ全運転で数える", "", source, "",
        "**当時条件：** Qは新規通知公開行の正常bid/askとLastを使い、気配幅及び判断Lastからの不利差が初回固定ATRの半分以下なら参加。元準備行へ遡らず、後続fill行の気配を見て取消しない。拒否後も元影の時系列は維持する。", "",
        "**実測・分母：** 下表は各41場・二商品。手数料0、買ask／売bid、全玉場内返済。Qだけを加えた対照。利益と損失は返済脚。", "",
        "| 入口 | 商品 | Q前収支 | Q後収支 | Q後赤字場 | Q後未参加場 |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for label, before, after in (("原E01", "E01", "E01_Q"), ("G", "G_E01", "G_Q"), ("GU", "GU_E01", "GU_Q")):
        for symbol in ("TOPIX", "NK225"):
            a, b = all_actual[before]["products"][symbol], all_actual[after]["products"][symbol]
            lines.append(table_line([label, symbol, a["net"], b["net"], b["red"], b["no_entry"]]))
    lines += ["", "**限界：** 幅の大きい既知二例を避けたことだけを新手法の収益にしない。未参加を勝ちへ数えない。ラージ代理と既知41場の結果であり、将来の確率保証ではない。", "",
        "**根拠：** [最終全会計と採否記録](../../../work/stability126_20261019/gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json)、[最終の反証レビュー](../../../work/stability126_20261019/diagnosis_notes/最終の敵対的レビュー.md)。"]
    with (knowledge / "入口.md").open("a", encoding="utf-8") as stream:
        stream.write("\n\n"+"\n".join(lines)+"\n")
    lines = ["<a id=\"00126_一R未満の条件付き利益保護\"></a>", "", "## 一リスク未満の利益保全は、入口を固定した単因子で比較する", "", source, "",
        "**当時条件：** 元の二市場反対時だけ半益床を上げる規則を保ち、開始を0.25／0.5／0.75Rへ下げた。Rは初回枚数×初回固定ATR×倍率。新設床による返済も次正常原行で、床の価格で必ず返せるとはしない。通常影は続き、早い再参加は追加しない。", "",
        "**実測・分母：** 各41場・両商品、Qなし同入口に対する収支変化。負けた場だけへ当てた結果ではない。", "",
        "| 入口 | 床開始R | TOPIX収支変化 | 日経収支変化 |", "| --- | ---: | ---: | ---: |"]
    for label, prefix, parent in (("原E01", "E01_", "E01"), ("G", "G_", "G_E01"), ("GU", "GU_", "GU_E01")):
        for code, level in (("P025", "0.25"), ("P050", "0.5"), ("P075", "0.75")):
            deltas = [all_actual[prefix+code]["products"][s]["net"]-all_actual[parent]["products"][s]["net"] for s in ("TOPIX", "NK225")]
            lines.append(table_line([label, level]+deltas))
    lines += ["", "**最終選定：** "+summary, "", "**限界：** 未順行の負け、気配横断、床予約から約定までの価格飛びは別に残る。途中利益への到達率と取引勝率を混同しない。最終比較の表示数には同値引用があり、独立市場標本ではない。", "",
        "**根拠：** [価格模型別の最終評価](../../../work/stability126_20261019/最終統合の価格モデル別比較と公開会計.json)、[低RとQの独立人工](../../../work/stability126_20261019/input_audit/gated_artificial126/公開気配と低利益床及び商品場内同値引用の最終独立監査.json)。"]
    with (knowledge / "出口.md").open("a", encoding="utf-8") as stream:
        stream.write("\n\n"+"\n".join(lines)+"\n")
    # ----------------------------------------
    # 新しい入口を案内へ加え、他試行を変えずに今回四試行だけ終了する。
    for path, prefix in ((ROOT / "README.md", "アルゴリズム調査/"), (ROOT / "アルゴリズム調査/README.md", ""), (knowledge / "README.md", "../../")):
        text = path.read_text(encoding="utf-8")
        assert "<!--00126案内-->" not in text
        pos = text.index("\n")+1
        note = f"\n<!--00126案内-->\n最新：[00126：E01改修の全41場損益]({prefix}{NAME}/{TITLE})。原版・入口再確認・早期利益保護・気配予算を比較。{summary}\n<!--00126案内終了-->\n"
        path.write_text(text[:pos]+note+text[pos:], encoding="utf-8")
    index = ROOT / "アルゴリズム調査/index.html"
    text = index.read_text(encoding="utf-8")
    assert "<!--00126開始-->" not in text
    card = f'''<!--00126開始--><article class="task latest"><div class="number">作業00126・E01の損失と方向偏り</div><h2>E01改修の各場損益と累計</h2><p>{summary}</p><a class="button" href="{NAME}/{TITLE}">全41セッションの利益・損失・収支</a> <a href="{NAME}/README.md">読む順序</a></article><!--00126終了-->\n'''
    assert "<!--00125開始-->" in text
    index.write_text(text.replace("<!--00125開始-->", card+"<!--00125開始-->", 1), encoding="utf-8")
    policy = ROOT / "アルゴリズム調査/調査方針.md"
    text = policy.read_text(encoding="utf-8")
    marker = "<!--00126最終比較-->"
    assert marker not in text
    policy.write_text(text+f"\n\n{marker}\n00126は原版16対照、同BBO16、既知G/GU延長、Q・低R53追加までを固定して測定。表示数と同値引用を区別し、実金融は{counts['new_financial_accounts']}口座。全41場は既知開発で、方向区分は採点のみ。{summary}\n", encoding="utf-8")
    before = read(TABLE / "trials.json")
    identifiers = ["126_原版E01の二市場利益保護と損失後再参加及び場損失の十六対照",
        "126_BBO_原版影と実建値予算を分けた次正常原行十六対照",
        "126G_既知EMA入口再確認と米国開始静観の追加十一場", "126_GGU低R利益床と公開気配予算の五十三対照"]
    untouched = deepcopy([r for r in before["trials"] if r["id"] not in identifiers])
    snapshot = TABLE / "history/00126_終了前の試行台帳.json"
    assert not snapshot.exists()
    snapshot.write_bytes((TABLE / "trials.json").read_bytes())
    for number, identifier in enumerate(identifiers):
        row = next(r for r in before["trials"] if r["id"] == identifier)
        row.update(status="検証完了・既知範囲の候補" if final_passed else "検証完了・目標未達",
            readme=PUBLIC.joinpath("README.md").relative_to(ROOT).as_posix(), report=PUBLIC.joinpath(TITLE).relative_to(ROOT).as_posix(),
            financial_accounts=results[number]["new_financial_accounts"], displayed_accounts=len(results[number]["rows"]),
            result_summary=summary)
        row["evidence"] += [dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p))
            for p in (result_paths[number], audits[number], HERE / "最終統合の価格モデル別比較と公開会計.json", HERE / "visual_final/全選択と全場会計の実描画確認.json")]
    assert untouched == [r for r in before["trials"] if r["id"] not in identifiers]
    before["updated_at"] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    (TABLE / "trials.json").write_text(json.dumps(before, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    assert untouched == [r for r in read(TABLE / "trials.json")["trials"] if r["id"] not in identifiers]
    outputs = []
    for command, extra in (("build", []), ("verify", ["--deep"])):
        proc = subprocess.run([sys.executable, "-B", "-X", "utf8", str(TABLE.parent / "manage.py"), command]+extra,
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        outputs.append(dict(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr))
        print(command, proc.returncode, flush=True)
        assert proc.returncode == 0, proc.stderr[-1200:]
    save(HERE / "案内と法則別知見及び四試行の終了.json", dict(passed=True, counts=counts,
        goal_met=final_passed, summary=summary, selected=best, html_sha256=sha(PUBLIC / TITLE),
        old_trials_unchanged=True, common_updated=appended, original_csv_reads=6, original_book_reads=0,
        financial_replays=0, current_API=0, real_orders=0, outputs=outputs))
    print(summary, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--final-audit", required=True)
    execute(__import__("pathlib").Path(parser.parse_args().final_audit).resolve())
