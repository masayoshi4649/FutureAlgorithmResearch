"""出口の反例を踏まえ、価格応答を追加する二つの入口比較を固定する。"""

from common130 import HERE, PREV, ROOT, read, save, reference


def main():
    """
    機能: 元の出口を保った入口活動条件を登録用資料へ保存する。
    引数: なし。第一巡比較と原板診断を読む。
    返り値: None。金融再生や現在データ取得はしない。
    """
    config = []
    old = read(HERE / "第一巡条件.json")
    for number, base in ((7, "NV01"), (8, "NV25")):
        row = dict(next(c for c in old if c["base"] == base),
                   id=f"W{number:02d}", name=f"{base}入口・逆向き約定代理にも価格が進む",
                   exit_style=0, activity_mode=1)
        config.append(row)
    save(HERE / "第二巡条件.json", config)
    reason = dict(
        question="両市場の向きに加え、逆向きの出来高代理があっても自市場の気配中値が進む状態に入口を限ると、夜間の不発を減らせるか。",
        change="第一巡の出口変更を使わずNV01/NV25の旧出口を維持。旧発注資格が成立した時に、正常接続の30秒窓で方向付き中値差>0・出来高正増分>0・方向付き売買代理差<0を要求。不適格と未知は準備を破棄し全段階をやり直す。",
        repeat_reason="単純な板厚、出来高符号だけの見送りは勝ち反例がある。第一巡6条件では起動前の床引上げ/部分返済が安定化せず、元の出口のまま価格応答という入口情報を追加する。",
        compares_to=["129_round1_チャートと板の失敗機構改善", "129_round7_チャートと板の失敗機構改善",
                     "130_round1_final_夜間損失のなぜ三段階と再改善"],
        diagnosis=reference(HERE / "entry_book/全原行活動と全親分類の照合.json"),
        observed="旧NV25の厳密正常窓でNK5/5親が利益だが、TOPIXは6親中4勝2敗。旧N36ではNK7親中4勝3敗。方式・商品を越えた普遍性を先取りしない。照合は既知の過去親だけの観察で、新経路の成績は未計算。",
        counterexample="10月1日TOPIXの旧NV25損失は今回の入口条件を満たす。真の約定主導側は記録されておらず、前行気配とCurrentPriceによる売買分類は代理であり、吸収や焦りの真値ではない。",
        extra_input_paths=[str((HERE / name).relative_to(ROOT).as_posix()) for name in
            ("原板活動の非金融準備.json", "第一巡比較.json", "entry_book/全入口の原板活動と固定価格表示数量.json")],
        quantity="TOPIXmini5枚/NKmicro10枚。追加・部分返済なし、場内全返済。",
        prior_scope="00129の両市場の価格確認、今回の全145旧親の板観察、入口.md参照。全過去試行の網羅的同等性を保証しない。",
        selection="赤字場・最悪場・上位3黒字除外・方向別・前後半・無取引を併記。21夜間全て既知の開発資料。")
    save(HERE / "第二巡の変更根拠.json", reason)


if __name__ == "__main__":
    main()
