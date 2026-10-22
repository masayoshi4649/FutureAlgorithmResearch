"""夜間の準備根拠だけを再確認する第五巡を用意する。"""

from common128 import HERE, read, save, reference
from build_round2 import replace_once


def main():
    """
    機能: 自己中期一致を足さず、相手の支持の失効だけを発注時に除く比較を保存する。
    引数: なし。
    返り値: None。既測核と会計は不変、金融再生なし。
    """
    text=(HERE/"night3.py").read_text(encoding="utf-8")
    text=replace_once(text,"                        slot = 0 if arm > 0 else 1\n",
        "                        elif entry_confirm == 3.:\n"
        "                            trigger = trigger and arm*history[i,10] > 0. and arm*history[i,11] > 0.\n"
        "                        slot = 0 if arm > 0 else 1\n")
    (HERE/"night5.py").write_text(text,encoding="utf-8")
    text=(HERE/"adapter3.py").read_text(encoding="utf-8").replace("import night3","import night5").replace("night3.simulate","night5.simulate")
    (HERE/"adapter5.py").write_text(text,encoding="utf-8")
    text=(HERE/"run4.py").read_text(encoding="utf-8").replace("from adapter3 import","from adapter5 import")
    text=text.replace('"adapter3.py"','"adapter5.py"').replace('"night3.py"','"night5.py"').replace('"run4.py"','"run5.py"')
    text=text.replace('default="round4"','default="round5"')
    (HERE/"run5.py").write_text(text,encoding="utf-8")
    text=(HERE/"analyze4.py").read_text(encoding="utf-8").replace('default="round4"','default="round5"')
    text=text.replace('read(HERE/"round3/全条件の会計.json")["rows"] + measured["rows"]',
        'read(HERE/"round3/全条件の会計.json")["rows"] + read(HERE/"round4/全条件の会計.json")["rows"] + measured["rows"]')
    (HERE/"analyze5.py").write_text(text,encoding="utf-8")
    existing={c["id"]:c for name in ("第二巡条件.json","第三巡条件.json") for c in read(HERE/name)}
    configs=[dict(existing[base],id=id,name=f"夜間・{base}の出口を保ち相手5分20分支持だけ再確認",
        entry_confirm=3,maximum_extension=1.e9) for id,base in (("N34","N16"),("N35","N23"),("N36","N24"))]
    save(HERE/"第五巡条件.json",configs)
    save(HERE/"第五巡の変更根拠.json",dict(
        based_on=reference(HERE/"round4/全条件の会計.json"),
        diagnostics=reference(HERE/"diagnosis_night/第三巡の準備根拠失効と除去勝ちの診断.json"),
        reason="第四巡の自己相手5/20分確認はTOPIXを改善する一方、NK三対照をいずれも赤字にした。NK自己中期支持不足の旧群は+42020円なので自己支持を新要件にしない。",
        evidence="N16の準備時相手支持失効群はTOPIX5/48組−24590円、NK13/58組−21860円。N24も相手失効群は6組−30008円、14組−32080円。ただし最悪場の主因ではなく、既存親分類と新運転を区別する。",
        mechanism="準備時に必要とした相手5/20分支持を発注時にも要求。both30/120、固定帯、各初期停止/追尾、枚数、料金は各基準と同一。自己中期一致は要求しない。",
        sources={n:reference(HERE/n) for n in ("night5.py","adapter5.py","run5.py","analyze5.py")}))
    save(HERE/"round5/金融前の選定源固定.json",dict(passed=True,source=reference(HERE/"analyze5.py"),
        reason="累積比較順位を継承。未知資料ではない。"))


if __name__=="__main__":
    main()
