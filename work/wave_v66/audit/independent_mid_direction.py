"""検知中値からの最大順行と対称先着を、未来経路の直接切片で独立検算する。"""

from hashlib import sha256
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
QUOTES = WORK.parent / "wave_v60" / "quotes.pkl"
SOURCE = WORK / "判断中値の方向診断.json"
MAIN = (
    "ACCEL_H03_V020", "STRAIGHT_H05_V020", "BREAK_H03_V020",
    "RAW_ACCEL_S060_V050", "RAW_STRAIGHT_S060_V050",
)
FRACTIONS = (0.0003, 0.0005, 0.001, 0.002)


def digest(path: Path) -> str:
    """機能: 検算対象の変更を検知するため、ファイル内容の識別値を返す。

    引数: path(Path)は読み取る入力ファイル。
    返り値: SHA256識別値(str)。
    """
    return sha256(path.read_bytes()).hexdigest()


def calculate(mid: np.ndarray, index: int, side: int) -> dict:
    """機能: 翌原板行以後の価格切片を直接採点し、元実装の累積極値を使わない。

    引数: mid(np.ndarray)は同一セッション中値、index(int)は検知行、
          side(int)は買い１・売り負１。
    返り値: 最大順行、順行比率、４対称幅の到達と先着判定(dict)。
    先着判定は切片上で最初に閾値へ達する箇所をnp.flatnonzeroで探す。
    """
    anchor = float(mid[index])
    gain = side * (mid[index + 1:] - anchor)
    assert len(gain) > 0
    mfe = max(0.0, float(np.max(gain)))
    absolute = np.abs(gain)
    labels = {}
    for fraction in FRACTIONS:
        width = anchor * fraction
        positions = np.flatnonzero(absolute >= width - 1.0e-9)
        if len(positions):
            offset = int(positions[0])
            first = 1 if gain[offset] >= width - 1.0e-9 else -1
            first_i = index + 1 + offset
        else:
            first, first_i = 0, -1
        labels[f"{fraction * 100:.2f}"] = {
            "target": bool(mfe >= width - 1.0e-9),
            "first": first,
            "first_i": first_i,
        }
    return {
        "decision_mid": anchor, "mfe": mfe, "mfe_fraction": mfe / anchor,
        "labels": labels,
    }


def summarize(rows: list[dict], symbol: str) -> dict:
    """機能: 独立採点済みの入口だけから銘柄別集計を再計算する。

    引数: rows(list[dict])は独立採点済み入口、symbol(str)は対象銘柄。
    返り値: 件数、最大順行の中央値、４幅の到達・先着件数と率(dict)。
    """
    selected = [row for row in rows if row["symbol"] == symbol]
    n = len(selected)
    labels = {}
    for fraction in FRACTIONS:
        key = f"{fraction * 100:.2f}"
        values = [row["labels"][key] for row in selected]
        targets = sum(value["target"] for value in values)
        first = sum(value["first"] == 1 for value in values)
        labels[key] = {
            "targets": targets,
            "target_rate": targets / n if n else None,
            "first": first,
            "first_rate": first / n if n else None,
            "opposite": sum(value["first"] == -1 for value in values),
            "unresolved": sum(value["first"] == 0 for value in values),
        }
    return {
        "n": n,
        "mfe_median": float(np.median([row["mfe"] for row in selected])) if n else None,
        "mfe_fraction_median": float(np.median([row["mfe_fraction"] for row in selected])) if n else None,
        "labels": labels,
    }


def main() -> None:
    """機能: 主５入口の全件と残り67入口の代表４件ずつを独立照合して保存する。

    引数: なし。
    返り値: なし(None)。元採点・入口・出口・選択結果を変更しない。
    """
    before = {str(path): digest(path) for path in (Path(__file__), SOURCE, QUOTES)}
    packet = json.loads(SOURCE.read_text(encoding="utf-8"))
    quotes = pickle.loads(QUOTES.read_bytes())
    assert len(packet["methods"]) == 72
    assert len({method["config"]["id"] for method in packet["methods"]}) == 72
    reports, cache = [], {}
    cases = 0
    for method in packet["methods"]:
        identity = method["config"]["id"]
        main_method = identity in MAIN
        old_rows = method["rows"]
        chosen = old_rows if main_method else [
            old_rows[int(position)]
            for position in np.unique(np.linspace(0, len(old_rows) - 1, min(4, len(old_rows)), dtype=int))
        ]
        checked_rows = []
        for row in chosen:
            key = (row["session"], row["symbol"])
            index, side = row["i"], row["side"]
            cache_key = (*key, index, side)
            if cache_key not in cache:
                cache[cache_key] = calculate(quotes[key]["mid"], index, side)
            actual = cache[cache_key]
            assert int(quotes[key]["seq"][index]) == row["seq"]
            for name in ("decision_mid", "mfe", "mfe_fraction"):
                np.testing.assert_allclose(actual[name], row[name], rtol=0, atol=1.0e-12)
            assert actual["labels"] == row["labels"], (identity, key, index)
            checked_rows.append({"symbol": row["symbol"], **actual})
            cases += 1
        report = {"手法": identity, "全候補照合": main_method, "全候補数": len(old_rows), "照合候補数": len(chosen)}
        if main_method:
            report["独立集計"] = {}
            for symbol in ("TOPIX", "NK225"):
                independent = summarize(checked_rows, symbol)
                old = method["summary"][symbol]
                assert independent["n"] == old["n"]
                for name in ("mfe_median", "mfe_fraction_median"):
                    if independent[name] is None:
                        assert old[name] is None
                    else:
                        np.testing.assert_allclose(independent[name], old[name], rtol=0, atol=1.0e-12)
                for label, values in independent["labels"].items():
                    assert values == old["labels"][label], (identity, symbol, label)
                report["独立集計"][symbol] = independent
        reports.append(report)
    assert all(digest(Path(path)) == value for path, value in before.items())
    result = {
        "全合格": True,
        "原実装から独立した方法": "原板中値の翌行以後を直接切り出し、変位のnp.maxと閾値のnp.flatnonzeroで採点。累積極値配列・元touch関数は使わない。",
        "主案全候補照合数": sum(report["照合候補数"] for report in reports if report["全候補照合"]),
        "その他代表候補照合数": sum(report["照合候補数"] for report in reports if not report["全候補照合"]),
        "合計照合候補数": cases,
        "独立経路数": len(cache),
        "照合した割合": [fraction * 100 for fraction in FRACTIONS],
        "不一致数": 0,
        "SHA256": before,
        "手法別照合": reports,
    }
    (HERE / "判断中値の独立診断.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in result.items() if key not in ("SHA256", "手法別照合")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
