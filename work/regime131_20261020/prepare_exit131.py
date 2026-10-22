"""第二巡の一回追加について、入口を固定して利益保護だけを変える新源を準備する。"""

from common131 import HERE, read, save


def new_source(name, text):
    """
    機能: 既存源を上書きせず、第三巡専用の実装を保存する。
    引数: name(str)は新しい名前、text(str)はUTF-8の源。
    返り値: None。同名があれば停止する。
    """
    path = HERE/name
    assert not path.exists()
    path.write_text(text, encoding="utf-8")


def main():
    """
    機能: 核とrunnerの差分を出口二変数に限定し、事前の八条件を保存する。
    引数: なし。
    返り値: None。金融を実行しない。第二巡の既存ファイルを変更しない。
    """
    kernel = (HERE/"participation131.py").read_text(encoding="utf-8")
    kernel = kernel.replace("fee_per_contract, style):", "fee_per_contract, style, trail_start, trail_width):")
    kernel = kernel.replace("mfe >= 1.5*risk", "mfe >= trail_start*risk")
    kernel = kernel.replace("mfe-risk)", "mfe-trail_width*risk)")
    kernel = kernel.replace("quantity(int)、multiplier/fee_per_contract(float)、style(int)は会計と方向方式。",
        "quantity(int)、multiplier/fee_per_contract(float)、style(int)は会計と方向方式。\n"
        "          trail_start/trail_width(float)は初期Rに対する利益保護開始・追尾幅。")
    assert "1.5*risk" not in kernel and "mfe-risk)" not in kernel
    new_source("participation_exit131.py", kernel)
    runner = (HERE/"run_portfolio131.py").read_text(encoding="utf-8")
    runner = runner.replace("participation131", "participation_exit131").replace("run_portfolio131.py", "run_exit131.py")
    runner = runner.replace('config["style"])', 'config["style"], config["trail_start"], config["trail_width"])')
    assert runner.count('config["trail_start"]') == 2
    new_source("run_exit131.py", runner)
    configs = []
    for schedule, style, base in ((2, 0, "S03"), (1, 1, "S07")):
        for start, width in ((.75, .5), (1., .5), (1., .75), (1.25, .75)):
            configs.append(dict(id=f"T{len(configs)+1:02d}",
                name=f"{base}入口・{start:g}Rから{width:g}R追尾",
                core_variant=0, schedule=schedule, style=style,
                trail_start=start, trail_width=width))
    save(HERE/"第三巡条件.json", configs)
    reason = read(HERE/"第二巡の変更理由.json")
    reason.update(
        question="同じ一回参加の入口で、利益保護の開始を早めれば順行後の負け戻りを抑えられるか。",
        compares_to=["131_round2_旧核維持と独立初回参加"],
        change="旧核・初回期限・方向・初期1R損切り・枚数を維持。追加担当の利益保護を1.5R起動/1R幅から、事前固定した四種類へ変更。",
        repeat_reason="第二巡は全場参加したが、日経夜間の追加が1.5R未到達の順行を失う例を確認。通常入口の頻度を増やさず、この出口だけの差を全場再生する。",
        exit="追加は1R初期損切りを維持。保護開始/追尾幅は(.75,.5),(1,.5),(1,.75),(1.25,.75)R。S03又はS07入口と組み合わせ八条件。旧核の出口は変更しない。",
        logic=[
            "米国寄付後に一度進んでも、その後の往復で順行を返すことがある。1.5R到達まで無保護にする必要性を検査する。",
            "時間で利益を決めず、実際の順行幅が事前設定を満たした時だけ追尾を開始する。",
            "開始を早めると大きい勝ちの途中の押しでも降りる。その損失も全場の新しい出口で測り、保存負けだけを差引しない。",
            "一親の出口を変更しても旧核の参加や初回追加の再参加は変えない。後続追加は元々禁止している。",
            "第二巡のMFEは原因調査専用。どの場を修正するか、当該親の最大値を入力することはない。",
        ])
    reason["extra_input_paths"] += [
        "work/regime131_20261020/round2/全条件の会計.json",
        "work/regime131_20261020/round2/旧核と追加の寄与.json",
        "work/regime131_20261020/night_diagnosis/第二巡夜間の利益保護待ちと反例.md",
    ]
    save(HERE/"第三巡の変更理由.json", reason)


if __name__ == "__main__":
    main()
