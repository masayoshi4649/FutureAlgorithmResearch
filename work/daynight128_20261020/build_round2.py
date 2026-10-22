"""第一巡の失敗箇所から変更部品を分離して第二巡の実装を作る。"""

from common128 import HERE, read, save, reference


def replace_once(text, before, after):
    """
    機能: 既知の一箇所だけを明示的に置換する。
    引数: text/before/after(str)は源と変更前後。
    返り値: strは差分を加えた新源。
    """
    assert text.count(before)==1, before
    return text.replace(before,after)


def main():
    """
    機能: 旧源を保持し、二分の入口出口矛盾と二十分の途中判断だけを修正する。
    引数: なし。
    返り値: None。登録・金融再生は行わない。
    """
    text=(HERE/"day_core128.py").read_text(encoding="utf-8")
    text=text.replace("if exit_rule == 1:", "if exit_rule in (1, 3):")
    text=text.replace("max(.5, min(1., current_atr[i] / atr))", "max(policy[4], min(1., current_atr[i] / atr))")
    text=text.replace("if exit_rule == 2 and guard_peak >= .5 * risk:",
                      "if exit_rule in (2, 3) and guard_peak >= policy[5] * risk:")
    text=replace_once(text,
        "                failed = failed and side * (prices[i] - history[i, 1]) < 0. and side * history[i, 10] < 0.",
        "                failed = failed and np.isfinite(history[i,7]) and np.isfinite(history[i,11])\n"
        "                failed = failed and side * history[i,7] < 0. and side * history[i,11] < 0.")
    text=text.replace("elif exit_rule == 2 and np.isfinite(guard_floor)", "elif exit_rule in (2, 3) and np.isfinite(guard_floor)")
    (HERE/"day_core2.py").write_text(text,encoding="utf-8")
    # ----------------------------------------
    # 夜間は新規判定と退出判定の期間を揃える対照、短期退出を外す対照を別々にする。
    text=(HERE/"night128.py").read_text(encoding="utf-8")
    text=replace_once(text,
        "    mode, stop, activation, trail, phase, cooldown, bounce, buffer, efficiency, distance = parameters",
        "    mode, stop, activation, trail, phase, cooldown, bounce, buffer, efficiency, distance = parameters[:10]\n"
        "    entry_confirm, exit_mode, rearm = parameters[10:13]")
    text=replace_once(text,"    entry_mode = 0\n",
        "    entry_mode = 0\n    entry_boundary = 0.\n    pending_boundary = 0.\n"
        "    failed_price = np.full(2, np.nan)\n    failed_width = np.zeros(2)\n")
    text=replace_once(text,"                entry_mode = pending_mode\n",
        "                entry_mode = pending_mode\n                entry_boundary = pending_boundary\n")
    text=replace_once(text,"                tc += 1\n                position = 0",
        "                tc += 1\n"
        "                if gross-2*one_fee < 0. and rearm > 0.:\n"
        "                    slot = 0 if position > 0 else 1\n"
        "                    failed_price[slot] = entry\n"
        "                    failed_width[slot] = width\n"
        "                position = 0")
    text=replace_once(text,
        "                if position*market[i,5] < -.25 and position*market[i,7] < -.25 and movement < .5*width:\n                    reason = 72",
        "                opposite = position*market[i,5] < -.25 and position*market[i,7] < -.25\n"
        "                if exit_mode == 0. and opposite and movement < .5*width:\n"
        "                    reason = 72\n"
        "                elif exit_mode == 2. and np.isfinite(history[i,11]):\n"
        "                    if position*(prices[i]-entry_boundary) < -.25*width and position*history[i,11] < 0.:\n"
        "                        reason = 72")
    text=replace_once(text,"                    if arm and trigger and quote_ok:\n",
        "                    if arm and trigger:\n"
        "                        if entry_confirm >= 1.:\n"
        "                            trigger = arm*market[i,5] > .05 and arm*market[i,7] > .05\n"
        "                        if entry_confirm == 2.:\n"
        "                            trigger = trigger and arm*history[i,6] > 0. and arm*history[i,7] > 0.\n"
        "                            trigger = trigger and arm*history[i,10] > 0. and arm*history[i,11] > 0.\n"
        "                        slot = 0 if arm > 0 else 1\n"
        "                        if np.isfinite(failed_price[slot]):\n"
        "                            renewed = arm*(prices[i]-failed_price[slot]) >= .5*failed_width[slot]\n"
        "                            renewed = renewed and arm*market[i,5] > .05 and arm*market[i,7] > .05\n"
        "                            if renewed:\n"
        "                                failed_price[slot] = np.nan\n"
        "                            else:\n"
        "                                trigger = False\n"
        "                    if arm and trigger and quote_ok:\n")
    text=replace_once(text,"                        pending_mode = arm_mode\n",
        "                        pending_mode = arm_mode\n                        pending_boundary = arm_level\n")
    (HERE/"night2.py").write_text(text,encoding="utf-8")
    # ----------------------------------------
    # 新数値源の接続名を分離し、第一巡登録源を変更しない。
    text=(HERE/"adapter128.py").read_text(encoding="utf-8")
    text=text.replace("day_core128","day_core2").replace("night128","night2")
    text=text.replace("np.array([0.,.5,0.,0.])",
        'np.array([0.,.5,0.,0.,config["risk_floor"],config["protect_start"]])')
    text=text.replace('"cooldown","entry_bounce","opening_buffer","minimum_efficiency","band_distance")',
        '"cooldown","entry_bounce","opening_buffer","minimum_efficiency","band_distance",\n'
        '        "entry_confirm","exit_mode","rearm")')
    (HERE/"adapter2.py").write_text(text,encoding="utf-8")
    text=(HERE/"run128.py").read_text(encoding="utf-8")
    text=text.replace("from adapter128 import","from adapter2 import")
    text=text.replace('"adapter128.py"','"adapter2.py"').replace('"day_core128.py"','"day_core2.py"')
    text=text.replace('"night128.py"','"night2.py"').replace('"run128.py"','"run2.py"')
    text=text.replace('default="round1"','default="round2"')
    # 新日中条件の同値キーには尺度下限と床起動幅も含める。
    text=text.replace('selected.tobytes()+str(config["exit_rule"]).encode()',
        'selected.tobytes()+str((config["exit_rule"],config["risk_floor"],config["protect_start"])).encode()')
    (HERE/"run2.py").write_text(text,encoding="utf-8")
    configs=[]
    for i,lo,pro,ex in (("D10",.25,.5,1),("D11",.75,.5,1),
        ("D12",.5,.25,3),("D13",.5,.5,3),("D14",.5,.75,3),("D15",.5,.5,2)):
        configs.append(dict(id=i,name="日中・尺度縮小と両市場二十分の失敗確認 "+i,
            kind="Day",engine="day",entry_filter=0,exit_rule=ex,risk_floor=lo,protect_start=pro))
    original={c["id"]:c for c in read(HERE/"round1/固定計画.json")["configs"]}
    definitions=[
        ("N13","二分逆行の退出を外す",0,1,0,1.5,1.),
        ("N14","入口も二分支持を必要とする",1,0,0,1.5,1.),
        ("N15","二分支持を待ち短期退出を外す",1,1,0,1.5,1.),
        ("N16","固定突破線と中期逆行で退出",1,2,0,1.5,1.),
        ("N17","方向を再確認し早めに利益追尾",2,1,0,.75,.5),
        ("N18","方向を再確認し広く利益追尾",2,1,0,2.,1.5),
        ("N19","失敗した同方向は前建値更新まで待つ",1,1,1,1.5,1.),
        ("N20","中期失敗退出と再参加制限",1,2,1,1.5,1.),
        ("N21","短期退出を外し早めに利益追尾",0,1,0,.75,.5),
        ("N22","短期退出を外し広く利益追尾",0,1,0,2.,1.5),
    ]
    for i,name,confirm,exit_mode,rearm,activation,trail in definitions:
        c=dict(original["N10"],id=i,name="夜間・"+name,entry_confirm=confirm,
            exit_mode=exit_mode,rearm=rearm,trail_start=activation,trail_width=trail)
        configs.append(c)
    save(HERE/"第二巡条件.json",configs)
    save(HERE/"第二巡の変更根拠.json",dict(
        based_on=reference(HERE/"round1/全条件の会計.json"),
        day="D06で失った上位勝ち6親は相手20分が順行。中期の押しと失敗を区別。D05の損切り幅下限も単因子比較。",
        night="N05の入口30秒支持と出口120秒反対の矛盾、N07の主損失72退出を分離。N10のUS後帯外進行に限定して入口再確認と退出除外を別々に比較。",
        selection="第一巡の候補選定は上書きせず、第二巡は既知失敗を用いた再開発。後半は未知テストではない。",
        copies={n:reference(HERE/n) for n in ("day_core2.py","night2.py","adapter2.py","run2.py")}))


if __name__=="__main__":
    main()
