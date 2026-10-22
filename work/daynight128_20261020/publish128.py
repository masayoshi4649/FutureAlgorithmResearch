"""昼夜独立の固定会計を、短い説明と全セッション表へ公開する。"""

import html
import json
from common128 import HERE, ROOT, PUBLIC, read, reference, save


def describe(config):
    """
    機能: 実際の保存条件から入口・途中・出口を短く説明する。
    引数: config(dict)は固定条件。
    返り値: strは表示説明。条件を追加したり売買を再計算しない。
    """
    if config["id"] in ("D00", "N00"):
        return "従来のGU_Q。二市場の方向を確認し、追跡新規・途中の部分返済・段階トレーリングを使う比較元。"
    if config["kind"] == "Day":
        entry = {
            0:"従来の二市場E01の入口を使う",
            1:"発注判断時に両市場が120秒で逆行していれば見送る",
            2:"発注判断時に両市場の30秒の進行が揃った場合だけ入る",
            3:"9:15以降、両市場の120秒逆行を見送る",
            4:"当場始値からの方向が両市場で揃う場合だけ入る",
            5:"発注判断時にどちらかの市場が30秒で明確に逆行していれば見送る。横ばいは許す",
        }[config["entry_filter"]]
        parts=[entry+"。"]
        if config["exit_rule"] in (1,3):
            floor=config.get("risk_floor",.5)
            parts.append(f"日中の値幅が縮めば損切りも縮める（初期幅の{floor:g}倍まで、再拡大しない）。")
        if config["exit_rule"] in (2,3):
            rule="自己と相手の20分方向がともに逆行" if "protect_start" in config else "自己価格が20分平均を割り、相手の5分方向も逆行"
            start=config.get("protect_start",.5)
            parts.append(f"{start:g}R以上順行後に{rule}したら、最高利益の半分を守る返済を加える。")
        parts.append("通常の部分返済と追尾を継承。早期返済しても元のE01が終了するまでは再参加を待つ。")
        return "".join(parts)
    modes={
        1:"20分の価格帯を外れた後、帯内へ戻る失敗を確認して反対方向へ入る",
        2:"20分帯を抜け、固定線を大きく割らず60秒経過し、発注時も線外0.25R以上で二市場が支持する方向へ入る",
        3:"両市場の方向が揃った後、押し・戻りと再進行を待って入る",
        4:"米国開始前は帯抜け失敗、開始後は帯外への定着を使う",
        5:"米国開始前は帯抜け失敗、開始後は押し・戻りを使う",
        6:"方向効率が低ければ帯抜け失敗、高ければ帯外定着、中間は待つ",
    }
    phase="米国開始後22分までは待ち、" if config["phase"]==1 else "米国開始15分前までに限り、" if config["phase"]==2 else ""
    parts=[phase+modes[config["mode"]]+"。"]
    if config.get("entry_confirm",0):
        parts.append("発注時には両市場の120秒支持も必要。")
    if config.get("entry_confirm",0)==2:
        parts.append("5分・20分方向も揃う場合に限定。")
    if config.get("entry_confirm",0)==3:
        parts.append("相手市場の5分・20分支持だけを発注時に再確認。")
    parts.append(f"初期損切り{config['stop']:g}R、{config['trail_start']:g}R順行から{config['trail_width']:g}Rの幅で追尾する。")
    if config.get("exit_mode",0)==2:
        parts.append("突破線の内側へ戻り相手の20分方向も逆行したら撤退。")
    elif config.get("exit_mode",0)==0:
        parts.append("両市場の120秒逆行でも撤退。")
    if config.get("rearm",0):
        parts.append("損失後の同方向は前建値から0.5R進むまで待つ。")
    if config.get("maximum_extension",1.e9)<1.e9:
        parts.append(f"新規気配が固定突破線から{config['maximum_extension']:g}Rを超えて離れていたら見送る。")
    return "".join(parts)


def main():
    """
    機能: 全注文監査済みの会計だけを公開し、入力結果と公開源の指紋を保存する。
    引数: なし。
    返り値: None。金融再生なし、既存研究の会計を変更しない。
    """
    comparison=read(HERE/"round5/前後半と方向別の比較.json")
    proofs=[read(HERE/f"audit/round{n}_全注文と全行会計の独立照合.json") for n in (1,2,3,4,5)]
    assert all(p["passed"] for p in proofs)
    all_configs=[]
    for n in (1,2,3,4,5):
        all_configs += read(HERE/f"round{n}/全条件の会計.json")["configs"]
    methods={}
    for c in [dict(id="D00",kind="Day",name="従来のGU_Q"),dict(id="N00",kind="Night",name="従来のGU_Q")]+all_configs:
        quantity="TOPIXミニ5枚／日経マイクロ10枚で新規。追加なし。"
        if c.get("weak_fraction",1.) < 1.:
            top,nk=int(5*c["weak_fraction"]),int(10*c["weak_fraction"])
            quantity=f"強い支持ではTOPIXミニ5枚／日経マイクロ10枚。弱い支持では{top}枚／{nk}枚。追加なし。"
        methods[c["id"]]=dict(c,description=describe(c),quantity=quantity)
    defaults={kind:v["full_development_reference"] for kind,v in comparison["selected"].items()}
    keep=("method","session","symbol","kind","profit","loss","net","fees","entries","regime")
    data=dict(rows=[{key:r[key] for key in keep} for r in comparison["rows"]],
        summary=comparison["summary"],methods=methods,defaults=defaults,selected=comparison["selected"])
    lead=f"日中は{defaults['Day']}が両銘柄で有力。夜間はTOPIXのN36が改善しましたが、日経は安定性不足です。五巡・{len(all_configs)}条件を検証しました。"
    conclusion=f"日中D17は両銘柄とも赤字6場まで減少。夜間N36はTOPIXで17黒字・3赤字・1無取引、日経では8黒字・12赤字・1無取引でした。夜間の両銘柄共通の比較上位は{defaults['Night']}ですが、安定性不足のため採用保留。全体の完成には未達です。"
    template=(HERE/"report128.html").read_text(encoding="utf-8")
    rendered=template.replace("__LEAD__",html.escape(lead)).replace("__CONCLUSION__",html.escape(conclusion))
    rendered=rendered.replace("__DATA__",json.dumps(data,ensure_ascii=False,allow_nan=False).replace("</","<\\/"))
    target=PUBLIC/"日中改修と夜間新造の損益.html"
    target.write_text(rendered,encoding="utf-8")
    selection=dict(passed=True,basis="五巡の既知全場比較。事後候補選定であり未知テストではない。",
        methods={kind:methods[id] for kind,id in defaults.items()},front_fixed=comparison["selected"],
        status={"Day":"日中の第一候補。既知全場選定で将来の安定性は未確立",
                "Night":"比較用上位の再現に限る。両銘柄での安定性不足により採用保留"},
        topix_night_reference="N36。日経へ同じ条件を適用して安定するとは判断しない。",
        sources=[reference(HERE/f"round{n}/全条件の会計.json") for n in (1,2,3,4,5)],
        reports=[reference(target)],live_application_changed=False)
    save(HERE/"採用候補と公開記録.json",selection)
    print(json.dumps(dict(defaults=defaults,conditions=len(all_configs),accounts=sum(p["accounts"] for p in proofs),
        report=str(target)),ensure_ascii=False))


if __name__=="__main__":
    main()
