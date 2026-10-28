"""確定した夜間診断から、採用候補の改善と残課題を短く保存する。"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import diagnose_night164r2 as d


def main() -> None:
    """保存診断だけを集計し、例を説明用途として固定する。

    引数: なし。返り値: None。金融再生・候補選択・原結果変更はしない。
    """
    final,_=d.completed_inputs(d.STUDY/"再生全完了164r2.json")
    path=d.HERE/"results/夜間の具体診断164r2.json";v=d.base.read(path)
    assert v["completed"] is True and v["financial_replays"]==0
    ids=["NK225_P164_00","NK225_P164_06","NK225_P164_07","NK225_U164_00","NK225_U164_05","NK225_U164_06","NK225_U164_07"]
    lots={(x["method"],x["session"],x["source_id"]):x for x in v["lots"]}
    key="NK225_P164_00→NK225_P164_06";comp=v["comparisons"][key]
    examples=[]
    for label,chosen in (("追撃損の改善最大",max(comp["rows"],key=lambda x:x["delta"])),("元勝ちの悪化最大",min(comp["rows"],key=lambda x:x["delta"]))):
        examples.append(dict(label=label,difference=chosen,lots=[lots[(ident,chosen["session"],chosen["source_id"])] for ident in key.split("→")]))
    worst=min((x for x in v["cases"] if x["id"]=="NK225_P164_06"),key=lambda x:x["risk"]["Minimum"])
    held=[x for x in v["lots"] if x["method"]==worst["id"] and x["session"]==worst["session"] and x["ID"] in worst["risk"]["MinimumAt"]["Lots"]]
    examples.append(dict(label="選択案にも残る初回逆行",case=worst,lots=held))
    delay={}
    for ident,part in v["delays"].items():
        counts=Counter()
        for row in v["cases"]:
            if row["id"]==ident:counts.update(row["counts"])
        deferred={(x["session"],x["SourceID"]):x for x in part["deferred"]}
        waits=[]
        for release in part["released"]:
            start=deferred[(release["session"],release["SourceID"])]
            assert release["Accepted"]<=release["Desired"]<=start["Desired"]
            waits.append(dict(session=release["session"],source_id=release["SourceID"],desired_at_start=start["Desired"],accepted=release["Accepted"],decision_wait_seconds=release["Time"]-start["Time"],start=start,release=release))
        assert all(0<=x["decision_wait_seconds"]<=30 for x in waits)
        delay[ident]=dict(initial_parents=counts["元初回親数"],unknown_original_entries=counts["初回短期未知で元通知維持"],deferred=len(part["deferred"]),released=len(waits),cancelled=len(part["cancelled"]),skipped_additions=len(part["skipped_additions"]),waiting_seconds=d.base.distribution([x["decision_wait_seconds"] for x in waits]),quantity_never_increased=True,waits=waits)
    facts=dict(completed=True,financial_replays=0,sources_changed=False,selected=final["selected"],input=dict(path=str(path),sha256=d.base.sha(path)),
        methods={ident:v["methods"][ident] for ident in ids},p06_difference=comp,delay=delay,examples=examples,
        metadata_correction=dict(initial_diagnostic_exit_code=1,cause="10/27Nightのpreviously_usedが第一巡未記載から第二巡trueへ変更。価格・時刻・原資料指紋・Source全通知は一致。",accepted_exclusion=["previously_used"],financial_source_or_results_changes=0,successful_diagnostic_exit_code=0),
        source_parity_sessions=sum(x["source_all_equal"] for x in v["evidence"]),
        definitions=dict(zero_favorable="各候補の実保有中だけの最高順行。早期退出すると後の順行を含まなくなるため、同入口でも件数が変わる。",reaction="CurrentPriceTime代理の秒数と原行差。受信から注文までの実遅延ではない。",examples="全結果を読んだ後の説明用。選択変更には使わない。"))
    out=d.HERE/"results/第二巡の原因と対応範囲164r2.json"
    with out.open("x",encoding="utf-8") as stream:json.dump(facts,stream,ensure_ascii=False,allow_nan=False,indent=2)
    text="""# 第二巡：夜間の改善と残課題

米国前は前40場で固定した **NK225_P164_06**、米国後は元D07の **NK225_U164_00** が比較候補となった。全27夜の追加開発の結果であり、Appや運用設定は変更していない。元Sourceの全通知・約定は第一巡と27夜すべて一致し、04〜06の実入口価格・時刻・数量も00と一致した。

|論点|測れた改善と限界|
|---|---|
|少量の利益返し・残り1枚|米国後U05で、黒字部分返済後の残玉が正益から最終赤字になる玉は6→0。ただし残玉収支は52.8万→50.6万円、全体も110万→107.8万円へ減少。米国前P06の小量初回9玉は元から正益後赤字0で、収支だけ3.8万→0.7万円へ減った。|
|増量直後の損失|P06のSource追撃7玉は−3.9万→0円。うち未順行で60秒以内に50円逆行した2玉を−5.7万→−1万円に抑えた。一方で、回復して勝っていた追撃を損切りした例もある。初回の大口はこの限定停止の対象外。|
|勢い減衰後の入口|07は初回失速時だけ待機。米国前33親中7待機・6解除・1取消（同親追加1件も拒否）、米国後107親中41待機・37解除・4取消。初回未知は前18/後13親で元通り受付。待機解除量は全件当初以下。06比で前−0.6万、後+1.8万円にとどまり、07は選択されなかった。|
|利益追尾の開始・分内反応|全玉+10円起動の04は、米国後の正益→赤字玉を49→1へ減らしたが収支110万→−20.8万円。最初の正益から床判断の中央値は価格時計0秒・7原行で、細かい板変化に反応する機能は動いた。反応を早めるだけでは収益性を解決できていない。通信・発注遅延は未測定。|

P06の元P05との差 **+8,000円** は、元の負け2玉を47,000円縮めた効果と、元の勝ち9玉を39,000円削った差。全玉の正益→赤字件数は1→2であり、利益返し全般を解消した結果ではない。米国前は27夜中9夜が無取引で、場内最悪時価も−12万円のまま。米国後の選択は元D07なので、そこでの不満を新手法で解決したとは言えない。

具体例は次の3場に絞った（数量はmicro、10枚でmini1枚相当）。

1. **10/23・追撃損を抑えた例**：19:16:32、episodeの同親追撃で買10枚・62,450円。元P05は一度も正益にならず、22:15:02に62,130円で−32,000円。P06は19:17:10に62,400円で−5,000円、差+27,000円。判断原行37893→次正常37894で返済した。元入口をよくしたのではなく、逆行した追撃の損失を限定した。
2. **10/1・回復する勝ちを消した例**：18:53:50、episode追撃の売10枚・68,460円。元P05は19:00:25に68,430円で+3,000円。P06は途中で30円順行した後、18:57:59に68,510円で−5,000円（原行35027→35028）。差−8,000円。この玉は初回小量用トレールの対象ではなく、追加玉50円停止の対象だった。
3. **10/27・初回大口の課題が残る例**：18:21:01、core買50枚・63,760円。P06も元P05も19:20:54のBid63,520円で含み−120,000円（原行35969）。最終19:44:43には63,790円で+15,000円へ回復したが、途中の危険は消えていない。利益後の保護だけで初期逆行を解消したと扱わない。

第一巡の新入口01〜03は、未順行の初回玉と細かい往復の気配差が損失の中心だった。今回は元入口・量へ戻して04〜06で出口を比較したため、入口の失敗と保護の効き方を分離できた。ただし浅い全玉保護は再び大きな勝ちを削った。限定保護は機能として一部効いており、全夜の完成手法とは別に評価する必要がある。

各玉・配賦の全件、資格後だけの順行、判断/約定の原板物理行、07の待機前後数量は[夜間の具体診断164r2.json](夜間の具体診断164r2.json)と[短い根拠JSON](第二巡の原因と対応範囲164r2.json)に保存した。診断器は10/27の事後利用ラベル`previously_used`だけの差で一度停止し、そのラベルを金融同値照合から外して再実行した。価格・時刻・原板・元Source・金融実装・金融結果の変更はない。
"""
    with (d.HERE/"results/第二巡の原因と対応範囲164r2.md").open("x",encoding="utf-8") as stream:stream.write(text)
    evidence=dict(passed=True,financial_replays=0,source_result_changes=0,night_sessions=27,cases_compared=270,new_cases=216,reused_baseline_cases=54,source_parity_sessions=27,
        actual_lots=len(v["lots"]),actual_exit_pieces=sum(len(x["exits"]) for x in v["lots"]),
        tests=6,metadata_correction=facts["metadata_correction"],
        sources=[dict(path=str(p),sha256=d.base.sha(p)) for p in [Path(__file__),d.HERE/"diagnose_night164r2.py",d.HERE/"test_diagnose_night164r2.py",BASE_PATH()]],
        outputs=[dict(path=str(p),sha256=d.base.sha(p)) for p in sorted((d.HERE/"results").glob("*.json"))]+[dict(path=str(p),sha256=d.base.sha(p)) for p in sorted((d.HERE/"results").glob("*.md"))])
    with (d.HERE/"夜間診断の完了証跡164r2.json").open("x",encoding="utf-8") as stream:json.dump(evidence,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:evidence[k] for k in ["passed","night_sessions","cases_compared","actual_lots","actual_exit_pieces"]},ensure_ascii=False))


def BASE_PATH() -> Path:
    """再利用した第一巡の読取・会計関数の位置を返す。

    引数: なし。返り値: Path。
    """
    return d.BASE_STUDY/"night_design/diagnose_night164.py"


if __name__=="__main__":main()
