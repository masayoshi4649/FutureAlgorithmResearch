"""損失機構と勝ちの反例を踏まえ、出口だけを変える六条件を固定する。"""

from common130 import HERE, PREV, read, save, reference


def main():
    """
    機能: 保存診断を根拠として六つの比較条件と変更理由を保存する。
    引数: なし。
    返り値: None。新しい金融結果を見る前の条件だけを作る。
    """
    old = next(c for c in read(PREV / "第一巡条件.json") if c["id"] == "NV01")
    retest = next(c for c in read(PREV / "第七巡条件.json") if c["id"] == "NV25")
    configs = []
    labels = {1: "起動前から損失床を引き上げる", 2: "順行後の戻りで半分だけ確定",
              3: "損失床の引上げと半分確定を併用"}
    for index, base in enumerate((old, retest)):
        for style in (1, 2, 3):
            configs.append(dict(base, id=f"W{index*3+style:02d}",
                name=f"{base['id']}入口・{labels[style]}",
                base=base["id"], retest_mode=base.get("retest_mode", 0), exit_style=style))
    save(HERE / "第一巡条件.json", configs)
    save(HERE / "第一巡の変更根拠.json", dict(
        question="順行後も1R全量を失える出口設計を改めると、夜間の赤字頻度と深さを改善できるか。",
        change="入口・幅尺度・初回数量を維持。①起動前の床を最高順行−初期停止幅へ単調引上げ、"
               "②0.5R順行後0.25R戻りで初回数量の切捨て半分だけ返済し残りは旧出口、③両方。",
        repeat_reason="00129は入口の待機/破棄と追加数量。今回は旧入口を固定した起動前の損失床と"
                      "部分返済を実装する。00128の開始1.5R→1R/幅1R→.75R変更とは異なる。",
        compares_to=["129_round1_チャートと板の失敗機構改善",
                     "129_round7_チャートと板の失敗機構改善"],
        observed="NV01/NV25の旧親では連続床の候補接触が敗戦だけでなく勝ちにも存在。"
                 "半分返済はNV25日経の6敗中1敗に対して12勝全てへ接触するため、安定化を先取りしない。",
        counterexample="NV25 TOPIX10/16の大きな売り利益を連続床が先に切り得る。"
                       "9/23日経は停止後−1.5Rが+1R回復より先。一律の損切り拡大は今回行わない。",
        diagnosis=reference(HERE / "exit_diagnosis/夜間全親の保護未達と停止後の先着分類.json"),
        quantity="TOPIXmini5枚／NKmicro10枚。初回のみ、追加なし。部分は2+3枚／5+5枚。"
                 "同じ親の部分利益と残玉損を全費用後に合算。場内全返済。",
        prior_scope="00128の開始幅・追尾幅、00129の入口と数量、共通知見の早期利確/勝ち喪失を参照。"
                    "未整理の全旧試行を完全に照合済みとはしない。",
        selection="赤字場数・最悪場/平均黒字・上位3黒字除外・無取引・上昇下落同値・前後半を併記。"
                  "全場既知の参考比較。利益合計だけで上位を選ばない。",
    ))
    print("六条件と反例を固定。金融再生なし。", flush=True)


if __name__ == "__main__":
    main()
