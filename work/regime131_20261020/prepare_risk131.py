"""一回追加の初期幅に応じた整数枚数を、将来損益なしで決める比較を用意する。"""

from common131 import HERE, read, save
from prepare_exit131 import new_source


def main():
    """
    機能: 第三巡の二入口・出口を固定し、発注時リスクによる四配分を保存する。
    引数: なし。
    返り値: None。旧源を上書きせず、損失親だけの再計算もしない。
    """
    kernel = (HERE/"participation_exit131.py").read_text(encoding="utf-8")
    kernel = kernel.replace("style, trail_start, trail_width):",
                            "style, trail_start, trail_width, budget_ticks):")
    kernel = kernel.replace("n = len(times)", "base_quantity = quantity\n    n = len(times)")
    kernel = kernel.replace(
        "if side and ask[i]-bid[i] <= .5*r:\n                    pending = 1",
        "if side and ask[i]-bid[i] <= .5*r:\n"
        "                    quantity = max(1, min(base_quantity, int(base_quantity*budget_ticks*tick/r)))\n"
        "                    pending = 1")
    kernel = kernel.replace("trail_start/trail_width(float)は初期Rに対する利益保護開始・追尾幅。",
        "trail_start/trail_width(float)は初期Rに対する利益保護開始・追尾幅。\n"
        "          budget_ticks(float)は基準枚数に許す一枚当たりのラージ呼値幅。\n"
        "          最低一枚では予算超過があり得る。約定飛びもあるため損失額を保証しない。")
    assert "int(base_quantity*budget_ticks*tick/r)" in kernel
    new_source("participation_risk131.py", kernel)
    runner = (HERE/"run_exit131.py").read_text(encoding="utf-8")
    runner = runner.replace("participation_exit131", "participation_risk131").replace("run_exit131.py", "run_risk131.py")
    runner = runner.replace('config["trail_width"])', 'config["trail_width"], config["budget_ticks"])')
    assert runner.count('config["budget_ticks"]') == 2
    new_source("run_risk131.py", runner)
    registration = (HERE/"register_portfolio131.py").read_text(encoding="utf-8")
    registration = registration.replace('default="run_portfolio131"', 'default="run_risk131"')
    registration = registration.replace(
        '"独立初回追加": {"TOPIXmini": 5, "NKmicro": 10, "各場の最大親数": 1}',
        '"独立初回追加": {"TOPIXmini": "1〜5枚", "NKmicro": "1〜10枚", "各場の最大親数": 1,\n'
        '        "数量": "発注時Rの逆比例。基準枚数×予算呼値×tick/Rを切捨て、最低1枚・最高基準枚数"}')
    registration = registration.replace("第二巡は金融前に指定した8条件を固定する", "第四巡は金融前に指定した8条件を固定する")
    new_source("register_risk131.py", registration)
    configs = []
    for schedule, style, start, width, base in ((2,0,1.25,.75,"T04"), (1,1,.75,.5,"T05")):
        for budget in (8.,12.,16.,24.):
            configs.append(dict(id=f"U{len(configs)+1:02d}",
                name=f"{base}入口出口・初期リスク{budget:g}呼値配分",
                core_variant=0, schedule=schedule, style=style, trail_start=start,
                trail_width=width, budget_ticks=budget))
    save(HERE/"第四巡条件.json", configs)
    reason = read(HERE/"第三巡の変更理由.json")
    reason.update(
        question="追加一回の初期幅が大きいとき、整数枚数を下げて大敗と大勝ち依存を減らせるか。",
        compares_to=["131_round3_旧核維持と独立初回参加"],
        change="旧核と追加の判断・約定時刻・方向・初期R・退出条件はT04/T05と同じ。追加の数量だけを発注時Rの逆比例へ変更。",
        repeat_reason="第三巡T05の日経夜間は黒字15/21でも最大赤字28220円、平均黒字約10575円。幅が広い場も固定10枚なのが大きい損失額の直接原因。追加単独の上位3除外は−21740円。",
        quantity="旧核TOPIXミニ5枚・NKマイクロ10枚を維持。追加q=max(1,min(基準枚数,floor(基準枚数×固定予算呼値×tick/R)))。片方向上限10/20枚。基準5/10枚、予算幅8/12/16/24呼値。",
        entry="第三巡T04/S03の後半二市場方向、又はT05/S07の中盤始値方向。追加は予定時刻まで旧核が未参加の場合の最大一回。数量はその発注判断時の初期Rのみで決め、将来の損益で変えない。",
        exit="T04は1.25Rから0.75R追尾、T05は0.75Rから0.5R追尾。どちらも初期1R損切り。旧核と全返済時刻は変更しない。",
        logic=[
            "同じ枚数でも初期幅が三倍なら予定損失も三倍になる。方向の確度と値動き幅を区別し、幅の増加をそのまま円リスク増加にしない。",
            "初期Rの逆比例で整数枚数を決める。最低一枚は参加維持のため、予算超過や小数量参加を別に開示する。",
            "ラージ呼値に基づく8/12/16/24幅は商品内の尺度。TOPIXと日経の円利益額は単純比較しない。",
            "予算は約定損失の上限保証ではない。飛び・気配・手数料を含めて同じ次正常行会計で評価する。",
            "荒い場の大きな利益も小さくなる。負けだけを減額せず、全場・全追加親で比較する。",
        ])
    reason["extra_input_paths"] += [
        "work/regime131_20261020/round3/全条件の会計.json",
        "work/regime131_20261020/round3/旧核と追加の寄与.json",
        "work/regime131_20261020/night_diagnosis/第三巡夜間の初期幅と固定枚数の損失集中.md",
    ]
    save(HERE/"第四巡の変更理由.json", reason)


if __name__ == "__main__":
    main()
