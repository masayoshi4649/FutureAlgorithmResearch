"""対象外の時間帯を指定しても売買を変えないことを全30場で照合する。"""

import hashlib
import json
import pickle
import numpy as np

from original import read, HERE, WORK


def check(left, right):
    """
    機能: 固定価格経路と疎イベント・時価指紋を全項目で比較する。
    引数: left/right (dict) の口座台帳。
    返り値: int の項目数。
    """
    assert left.keys() == right.keys()
    count = 0
    for key in left:
        a, b = left[key], right[key]
        if isinstance(a, np.ndarray):
            np.testing.assert_array_equal(a, b, err_msg=key)
        else:
            assert a == b, key
        count += 1
    return count


def main():
    """
    機能: DayのU無影響・NightのJ無影響とJUの合成を確認する。
    引数: なし。
    返り値: None。
    """
    fixed = read(WORK / "results/事前固定.json")
    records = []
    fields = 0
    for model in ("specified", "observed"):
        for base in fixed["primary"]:
            ledgers = {}
            for mode in ("", "J", "U", "JU"):
                ident = base + ("_" + mode if mode else "")
                path = WORK / model / "ledgers" / (ident + ".pkl")
                expected = read(WORK / model / "results" / (ident + ".json"))["ledger_SHA256"]
                assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
                with path.open("rb") as stream:
                    ledgers[mode] = pickle.load(stream)
            for key in sorted(ledgers[""]):
                day = key[0].endswith("_Day")
                pairs = (("U", ""), ("JU", "J")) if day else (("J", ""), ("JU", "U"))
                for a, b in pairs:
                    fields += check(ledgers[a][key], ledgers[b][key])
                    records.append(dict(モデル=model, 主手法=base, セッション=key[0], 銘柄=key[1],
                        左=a or "無指定", 右=b or "無指定", 完全一致=True))
    result = dict(全合格=True, 口座対照数=len(records), 台帳項目一致数=fields, 検査=records,
        コードSHA256=hashlib.sha256(__import__("pathlib").Path(__file__).read_bytes()).hexdigest(),
        注記="本30場では日本寄付きと米国寄付きは別セッションに含まれる。対象外の時間窓による経路変更を検出する検査。")
    (HERE / "時間帯指定の対象外不変とJU合成一致.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(全合格=True, 口座対照数=len(records), 台帳項目一致数=fields), ensure_ascii=False))


if __name__ == "__main__":
    main()
