"""原本を途中で切った特徴と足だけで売買を再生し、過去の確定取引を照合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import model
import raw_features


OUT = Path(__file__).resolve().parent


def selected_configs() -> list[dict]:
    """価格対照・板・混合、両入口と両出口を含む代表12条件を抽出する。

    引数: なし。
    返り値: list[dict]。損益を見ずに系統番号で選んだ監査対象。
    """
    result = []
    for config in model.configs():
        if config["family"] == "P00":
            result.append(config)
        elif config["family"] in ("B05", "B12") and config["window"] == 300 and config["exit"] == "板反転併用":
            result.append(config)
        elif config["family"] in ("H01", "H02") and config["exit"] == "利益保護":
            result.append(config)
    assert len(result) == 12
    return result


def verify(path: Path, symbol: str, session: str) -> list[dict]:
    """二つの生行打切り点で方向・ATR・確定取引の不変性を確認する。

    引数: path（Path）原本。symbol（str）銘柄。session（str）セッション。
    返り値: list[dict]。各打切り点・監査条件の結果。
    """
    stem = f"{symbol}_{session}"
    with np.load(OUT / "features" / f"{stem}.npz") as data:
        full = pd.DataFrame({key: data[key] for key in raw_features.COLUMNS})
    with np.load(OUT / "features" / f"約定系列_{stem}.npz") as data:
        tape = {key: data[key] for key in data.files if key != "tick"}
    audit = json.loads((OUT / "features" / f"{stem}_audit.json").read_text(encoding="utf-8"))
    full_atr, full_price = model.price_features(session, symbol, full.time_s.to_numpy(float))
    full_directions, full_pressure = model.directions(full, full_price)
    configurations = selected_configs()
    full_trades = {
        config["id"]: model.simulate(tape, full, full_directions[(config["family"], config["window"])], full_atr, full_pressure, config, session, symbol)
        for config in configurations
    }
    records = []
    for fraction in (0.33337, 0.66671):
        cut = max(1, int(audit["読取行数"] * fraction))
        prefix_quotes = []
        prefix, _ = raw_features.extract_features(path, symbol, session, max_rows=cut, quotes=prefix_quotes)
        prefix_tape = {key: np.asarray([row[key] for row in prefix_quotes]) for key in tape}
        cutoff = float(prefix_tape["time_s"][-1])
        prefix_atr, prefix_price = model.price_features(session, symbol, prefix.time_s.to_numpy(float), cutoff=cutoff)
        expected = full.loc[full.seq < cut].reset_index(drop=True)
        pd.testing.assert_frame_equal(prefix, expected, check_exact=True)
        np.testing.assert_array_equal(prefix_atr, full_atr[:len(prefix)])
        np.testing.assert_array_equal(prefix_price, full_price[:len(prefix)])
        directions, pressure = model.directions(prefix, prefix_price)
        for key in directions:
            np.testing.assert_array_equal(directions[key], full_directions[key][:len(prefix)])
        np.testing.assert_array_equal(pressure, full_pressure[:len(prefix)])
        for config in configurations:
            trades = model.simulate(prefix_tape, prefix, directions[(config["family"], config["window"])], prefix_atr, pressure, config, session, symbol)
            closed = [row for row in trades if row["closed"]]
            expected_trades = [row for row in full_trades[config["id"]] if row["closed"] and row["exit_seq"] < cut]
            assert closed == expected_trades, f"確定取引不一致: {symbol} {session} {config['id']} seq {cut}"
            records.append({
                "銘柄": symbol, "セッション": session, "生行打切り数": cut,
                "足の利用可能時刻上限": cutoff, "条件": config["id"],
                "特徴行数": len(prefix), "気配行数": len(prefix_quotes),
                "確定取引照合数": len(closed), "取引属性照合数": sum(len(row) for row in closed),
                "ATR一致": True, "全27方向条件一致": True, "確定取引一致": True,
            })
    return records


def main() -> None:
    """12ファイル・各二点・12売買条件を実行し、独立検査記録を保存する。

    引数: なし。
    返り値: None。原本・既存モデルは変更せず監査JSONを書き出す。
    """
    files = [Path(model.__file__), Path(raw_features.__file__)]
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    records = []
    for path, symbol, session in raw_features.sources():
        records.extend(verify(path, symbol, session))
        print(f"売買の途中打切り一致: {symbol} {session}", flush=True)
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    result = {
        "使用コードSHA256": before,
        "監査中コード変更なし": before == after,
        "監査条件数": len(selected_configs()),
        "照合セル数": len(records),
        "確定取引照合延べ数": sum(row["確定取引照合数"] for row in records),
        "取引属性照合延べ数": sum(row["取引属性照合数"] for row in records),
        "結果": records,
        "限界": "同じ取引が複数条件・打切り点で再登場するため照合件数は独立取引数ではない。受信時刻がない点と実約定の不確実性は、この未来非依存テストでは解消できない。",
    }
    (OUT / "売買未来非依存監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert before == after, "監査中にモデルが変更されたため最終コードでの再実行が必要"
    print("ATR・方向・確定売買の独立監査に合格しました。", flush=True)


if __name__ == "__main__":
    main()
