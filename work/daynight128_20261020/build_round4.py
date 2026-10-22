"""支持の再確認だけを分離し、既存核で第四巡を用意する。"""

from common128 import HERE, read, save, reference


def main():
    """
    機能: 既存三出口を固定し、発注時中期確認だけを変える対照を保存する。
    引数: なし。
    返り値: None。金融実行・登録は別工程。
    """
    configs={c["id"]:c for filename in ("第二巡条件.json","第三巡条件.json") for c in read(HERE/filename)}
    chosen=[]
    for id, base in (("N31","N16"),("N32","N23"),("N33","N24")):
        chosen.append(dict(configs[base],id=id,name=f"夜間・{base}の出口を保ち発注時5分20分支持を再確認",
            entry_confirm=2,maximum_extension=1.e9))
    save(HERE/"第四巡条件.json",chosen)
    runner=(HERE/"run3.py").read_text(encoding="utf-8").replace('"run3.py"','"run4.py"').replace('default="round3"','default="round4"')
    (HERE/"run4.py").write_text(runner,encoding="utf-8")
    analyzer=(HERE/"analyze3.py").read_text(encoding="utf-8").replace('default="round3"','default="round4"')
    analyzer=analyzer.replace('read(HERE/"round2/全条件の会計.json")["rows"] + measured["rows"]',
        'read(HERE/"round2/全条件の会計.json")["rows"] + read(HERE/"round3/全条件の会計.json")["rows"] + measured["rows"]')
    (HERE/"analyze4.py").write_text(analyzer,encoding="utf-8")
    save(HERE/"第四巡の変更根拠.json",dict(
        based_on=reference(HERE/"round3/全条件の会計.json"),
        reason="第三巡の利益保護調整だけでは夜間NKの前半赤字と大勝ち依存が残る。mode2の準備時5/20分支持が発注まで存続しているかの確認を単因子で分離。",
        existing="N17/N18は確認2のほか出口mode1と追尾幅/開始を同時に変更。N16/23/24は出口mode2であり、この三つの入口だけの変更と完全一致しない。",
        kernel="night3.pyとadapter3.pyは変更しない。人工と源指紋で全中期列の再確認を追加点検。",
        preserves="日中の追加金融再生なし。夜間の帯形成・数量5/10・費用・初期stop・各基準の出口・場内返済は同一。",
        copies={n:reference(HERE/n) for n in ("run4.py","analyze4.py")} ))
    save(HERE/"round4/金融前の選定源固定.json",dict(passed=True,source=reference(HERE/"analyze4.py"),
        reason="累積比較の事前順位を継承。未知外部テストと呼ばない。"))


if __name__=="__main__":
    main()
