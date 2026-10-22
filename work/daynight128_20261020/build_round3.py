"""第二巡の保護起動前の利益返しと、静止した相手の誤拒否を修正する。"""

from common128 import HERE, read, save, reference
from build_round2 import replace_once


def main():
    """
    機能: 第三巡を別名源で作り、既存の測定源を保持する。
    引数: なし。
    返り値: None。金融再生・登録なし。
    """
    text=(HERE/"night2.py").read_text(encoding="utf-8")
    text=replace_once(text,"    entry_confirm, exit_mode, rearm = parameters[10:13]",
        "    entry_confirm, exit_mode, rearm = parameters[10:13]\n    maximum_extension = parameters[13]")
    text=replace_once(text,"                    if arm and trigger and quote_ok:\n",
        "                    if arm and trigger and arm_mode == 2:\n"
        "                        quoted_entry = ask[i] if arm > 0 else bid[i]\n"
        "                        trigger = arm*(quoted_entry-arm_level) <= maximum_extension*arm_width\n"
        "                    if arm and trigger and quote_ok:\n")
    (HERE/"night3.py").write_text(text,encoding="utf-8")
    text=(HERE/"adapter2.py").read_text(encoding="utf-8")
    text=text.replace("import night2","import night3").replace("night2.simulate","night3.simulate")
    text=replace_once(text,"            accepted[parent] = ok\n",
        "            elif kind == 5:\n"
        "                ok = market[row,11] == 1. and np.isfinite(market[row,4]) and np.isfinite(market[row,6])\n"
        "                ok = ok and side*market[row,4] >= -.05 and side*market[row,6] >= -.05\n"
        "            accepted[parent] = ok\n")
    insert='''
def resize_feed(feed, market, weak_fraction):
    """
    機能: 発注判断時の短期支持が弱い親の数量を落とし、紙上部分返済も同じ比率へ対応する。
    引数: feed/market(ndarray)、weak_fraction(float)は採用通知・当時の二市場・弱い時の比率。
    返り値: ndarrayは整数枚数通知。部分返済の累計を最寄り整数へ丸め、最終全量を保存する。
    """
    result, state = [], {}
    for order in feed:
        row,parent,side = int(order[0]),int(order[2]),int(order[3])
        if order[7] == 1.:
            strong = market[row,11] == 1. and np.isfinite(market[row,4]) and np.isfinite(market[row,6])
            strong = strong and side*market[row,4] > .05 and side*market[row,6] > .05
            original = int(order[4])
            desired = original if strong else max(1,int(round(original*weak_fraction)))
            state[parent] = [original,desired,0,0]
            take = desired
        else:
            current=state[parent]
            current[2] += int(order[4])
            target = int(np.floor(current[2]*current[1]/current[0]+.5))
            take = target-current[3]
            current[3] = target
        if take:
            changed=order.copy()
            changed[4]=take
            result.append(changed)
    return np.asarray(result).reshape((-1,10))


'''
    text=replace_once(text,"def play_day(config, ready, quotes, market, history, feed):",insert+
        "def play_day(config, ready, quotes, market, history, feed):")
    text=replace_once(text,'    accepted = day_filter(feed, ready, market, history, config["entry_filter"])\n',
        '    accepted = day_filter(feed, ready, market, history, config["entry_filter"])\n'
        '    accepted = resize_feed(accepted,market,config["weak_fraction"])\n')
    text=text.replace('"entry_confirm","exit_mode","rearm")','"entry_confirm","exit_mode","rearm","maximum_extension")')
    text=text.replace('max_quantity=5 if top else 10)', 'max_quantity=int(qty[entry].max()) if entry.any() else 0)')
    (HERE/"adapter3.py").write_text(text,encoding="utf-8")
    text=(HERE/"run2.py").read_text(encoding="utf-8")
    text=text.replace("from adapter2 import","from adapter3 import").replace("summarize, day_filter","summarize, day_filter, resize_feed")
    text=text.replace('"adapter2.py"','"adapter3.py"').replace('"night2.py"','"night3.py"').replace('"run2.py"','"run3.py"')
    text=text.replace('default="round2"','default="round3"')
    text=replace_once(text,'                        selected = day_filter(feed,ready,market,history,config["entry_filter"])\n',
        '                        selected = day_filter(feed,ready,market,history,config["entry_filter"])\n'
        '                        selected = resize_feed(selected,market,config["weak_fraction"])\n')
    (HERE/"run3.py").write_text(text,encoding="utf-8")
    second={c["id"]:c for c in read(HERE/"第二巡条件.json")}
    configs=[]
    for i,name,entry,fraction in [
        ("D16","明確な短期支持が揃う時だけ",2,1.),
        ("D17","相手の静止は許し明確な逆行だけ見送る",5,1.),
        ("D18","短期支持が弱い時は四割の枚数",0,.4),
        ("D19","明確逆行を見送り弱い支持は四割の枚数",5,.4),
        ("D20","明確逆行を見送り弱い支持は六割の枚数",5,.6)]:
        configs.append(dict(second["D11"],id=i,name="日中・"+name,entry_filter=entry,weak_fraction=fraction))
    definitions=[
        ("N23","一R順行から同幅で追尾",1.,1.,1.e9),
        ("N24","一R順行から四分の三幅で追尾",1.,.75,1.e9),
        ("N25","一・二五R順行から同幅で追尾",1.25,1.,1.e9),
        ("N26","突破線から四分の三幅以内で新規",1.5,1.,.75),
        ("N27","突破線から一・五幅以内で新規",1.5,1.,1.5),
        ("N28","追い過ぎを一幅以内にし一Rから追尾",1.,1.,1.),
        ("N29","追い過ぎを一幅以内にし四分の三幅追尾",1.,.75,1.),
        ("N30","追い過ぎを四分の三幅以内にし一Rから追尾",1.,1.,.75),
    ]
    for i,name,activation,trail,extension in definitions:
        configs.append(dict(second["N16"],id=i,name="夜間・"+name,trail_start=activation,
            trail_width=trail,maximum_extension=extension))
    save(HERE/"第三巡条件.json",configs)
    save(HERE/"第三巡の変更根拠.json",dict(
        based_on=reference(HERE/"round2/全条件の会計.json"),
        day="D02の支持なし群も合計黒字で、相手静止と逆行の混同がある。明確逆行だけ拒否、又は弱支持を数量縮小する単独対照。",
        night="N16損失組は全て1.5R追尾起動前。一R順行後赤字はTOP5組・NK6組。保護開始1/1.25Rを主比較。固定突破線から1R超の既存群はTOP4組+53328円・NK7組+18460円で、追い過ぎが主因という仮説は不支持。距離制限は悪化を含めて確認する反証用対照。",
        diagnostics=[reference(HERE/"diagnosis_day/第二巡D11で中立と逆行を分けた保存親分類.json"),
            reference(HERE/"diagnosis_night/第二巡N16の固定突破線と新規距離.json"),
            reference(HERE/"diagnosis_night/第二巡再参加で失った勝ちと保護前の接触事実.json")],
        quantities="日中D18-20の弱支持は5/10枚に.4又は.6を掛ける。紙上部分返済の累計枚数を最寄り整数へ対応、元影の待機を保持。",
        copies={n:reference(HERE/n) for n in ("night3.py","adapter3.py","run3.py")}))


if __name__=="__main__":
    main()
