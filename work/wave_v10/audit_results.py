"""全数値売買を独立再集計し、未来の損益変更に対する選択の不変性を検査する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import research
import signals

OUT = Path(__file__).resolve().parent


def check_close(actual: object, expected: object, label: str) -> None:
    """機能: 保存時の浮動小数点丸めだけを許して、二つの数値列を照合する。

    引数: actual/expected (object) は数値または配列、label (str) は検査名。
    返り値: None。不一致時は AssertionError。
    """
    assert np.allclose(actual, expected, rtol=1e-10, atol=1e-7, equal_nan=True), label


def independent_drawdown(values: np.ndarray) -> float:
    """機能: 逐次加算と最高残高の保持だけで確定損益の最大下落を求める。

    引数: values (ndarray) は取引順の損益。
    返り値: float。最大下落。
    """
    balance, peak, worst = 0.0, 0.0, 0.0
    for value in values:
        balance += float(value)
        peak = max(peak, balance)
        worst = max(worst, peak - balance)
    return worst


def audit_saved_rows(frame: pd.DataFrame) -> dict:
    """機能: 全取引の実気配・約定順序・費用を確認し、全集計セルを独立再計算する。

    引数: frame (DataFrame) は全条件セッション集計。
    返り値: dict。検査件数と一致した項目。
    """
    schema = json.loads((OUT / "数値売買形式.json").read_text(encoding="utf-8"))
    rows = np.load(OUT / "全売買数値.npz", allow_pickle=False)["rows"]
    method = np.array(schema["条件順"])
    cell_map = schema["セル順"]
    config_i, cell_i = rows[:, 0].astype(int), rows[:, 1].astype(int)
    raw = rows[:, 2:]
    multipliers = np.array([1000. if cell["銘柄"] == "NK225" else 10000. for cell in cell_map])[cell_i]
    ticks = np.array([10. if cell["銘柄"] == "NK225" else .5 for cell in cell_map])[cell_i]
    points = raw[:, 1] * (raw[:, 8] - raw[:, 7]) - 2 * ticks
    check_close(raw[:, 14], points, "全取引の売買価格からの費用２呼値損益")
    check_close(raw[:, 15], points - 2 * ticks, "全取引の費用４呼値損益")
    assert np.isin(raw[:, 1], [-1, 1]).all()
    assert np.isin(raw[:, 13], [0, 1]).all()
    assert (raw[:, 6] > 0).all()
    assert (raw[:, 2] < raw[:, 3]).all() and (raw[:, 3] < raw[:, 4]).all()
    closed = raw[:, 13] == 1
    assert (raw[closed, 4] < raw[closed, 17]).all() and (raw[closed, 17] < raw[closed, 5]).all()

    # ----------------------------------------
    # 数値表の約定価格を、独立に読み込んだ原気配の該当行へ照合する。
    quote_records = []
    for index, cell in enumerate(cell_map):
        session, symbol = cell["セッション"], cell["銘柄"]
        tape = dict(np.load(signals.feature_root(session) / f"約定系列_{symbol}_{session}.npz", allow_pickle=False))
        mask = cell_i == index
        subset = raw[mask]
        entry_index, exit_index = subset[:, 4].astype(int), subset[:, 5].astype(int)
        side = subset[:, 1]
        entry_quote = np.where(side > 0, tape["ask"][entry_index], tape["bid"][entry_index])
        exit_quote = np.where(side > 0, tape["bid"][exit_index], tape["ask"][exit_index])
        check_close(subset[:, 7], entry_quote, f"{session} {symbol} 新規気配")
        check_close(subset[:, 8], exit_quote, f"{session} {symbol} 返済・時価気配")
        check_close(subset[:, 16], (tape["time_s"][exit_index] - tape["time_s"][entry_index]) / 60,
                    f"{session} {symbol} 保有分")
        if session != signals.SESSIONS[-1]:
            assert (subset[:, 13] == 1).all(), (session, symbol)
        quote_records.append(dict(セッション=session, 銘柄=symbol, 約定気配照合数=len(subset), 一致=True))

    values = pd.DataFrame({
        "方式": method[config_i],
        "セッション": [cell_map[index]["セッション"] for index in cell_i],
        "銘柄": [cell_map[index]["銘柄"] for index in cell_i],
        "取引数": closed.astype(int), "未返済数": (~closed).astype(int),
        "勝ち数": (closed & (points > 0)).astype(int), "負け数": (closed & (points < 0)).astype(int),
        "引分数": (closed & (points == 0)).astype(int),
        "利益円": np.where(closed & (points > 0), points * multipliers, 0.),
        "損失円": np.where(closed & (points < 0), -points * multipliers, 0.),
        "収支円": np.where(closed, points * multipliers, 0.),
        "費用倍収支円": np.where(closed, (points - 2 * ticks) * multipliers, 0.),
        "ATR収支": np.where(closed, points / raw[:, 6], 0.),
        "費用倍ATR収支": np.where(closed, (points - 2 * ticks) / raw[:, 6], 0.),
        "評価損益円": np.where(~closed, points * multipliers, 0.),
        "最大順行からの返却円": np.where(closed, np.maximum(0., raw[:, 11] - points - 2 * ticks) * multipliers, 0.),
    })
    keys = ["方式", "セッション", "銘柄"]
    grouped = values.groupby(keys, sort=False).sum()
    observed = frame.set_index(keys)
    expected = grouped.reindex(observed.index).fillna(0.)
    for column in expected:
        check_close(observed[column].to_numpy(), expected[column].to_numpy(), column)
    check_close(frame["利益円"] - frame["損失円"], frame["収支円"], "利益－損失＝収支")
    assert (frame["勝ち数"] + frame["負け数"] + frame["引分数"] == frame["取引数"]).all()
    check_close(frame["費用倍収支円"], frame["収支円"] - frame["取引数"] * frame["銘柄"].map({"NK225": 20000., "TOPIX": 10000.}),
                "費用倍の追加損失")

    # ----------------------------------------
    # 集計関数と別の逐次式で確定最大下落を再計算する。
    dd_rows = []
    for key, part in values[values["取引数"].eq(1)].groupby(keys, sort=False):
        dd_rows.append(dict(zip(keys, key), 確定最大下落ATR=independent_drawdown(part["費用倍ATR収支"].to_numpy()),
                            確定最大下落円=independent_drawdown(part["収支円"].to_numpy())))
    dd = pd.DataFrame(dd_rows).set_index(keys).reindex(observed.index).fillna(0.)
    for column in dd:
        check_close(observed[column].to_numpy(), dd[column].to_numpy(), column)
    return dict(全数値売買数=len(raw), 全集計セル数=len(frame), 原気配照合=quote_records,
                損益費用と勝敗未返済の再集計一致=True, 確定最大下落の独立逐次計算一致=True,
                限界="最大順行の値は保存記録を使い、返却額の会計計算を確認した。生板全列からの最大順行再計算はこの検査に含まない。")


def audit_selection(frame: pd.DataFrame) -> list[dict]:
    """機能: 未学習セッションの全数値を変えても、過去の採用と全順位が変わらないことを確認する。

    引数: frame (DataFrame) は全条件集計。
    返り値: list[dict]。学習２～５セッションでの不変性記録。
    """
    conditions = json.loads((OUT / "条件一覧.json").read_text(encoding="utf-8"))
    output = []
    for count in range(2, 6):
        train = signals.SESSIONS[:count]
        expected = research.choose(frame, conditions, train)
        changed = frame.copy()
        future = ~changed["セッション"].isin(train)
        changed.loc[future, "取引数"] = 999999
        changed.loc[future, "費用倍ATR収支"] = np.arange(int(future.sum()), dtype=float) * 1e12
        changed.loc[future, "確定最大下落ATR"] = 1e15
        observed = research.choose(changed, conditions, train)
        assert observed == expected, train
        selected = expected["採用"]
        if selected:
            assert all(value >= len(train) for value in selected["銘柄別取引数"].values())
        output.append(dict(学習=train, 採用=selected["方式"] if selected else None,
                           比較順位数=len(expected["全順位"]), 未来改変後の全順位一致=True,
                           近傍不足の基本得点への切替=expected["近傍不足の基本得点への切替"]))
    return output


def main() -> None:
    """機能: 全取引の会計と、全候補からの時系列選択を独立監査する。

    引数: なし。
    返り値: None。損益・選択の独立監査 JSON を保存する。
    """
    frame = pd.read_csv(OUT / "全条件セッション集計.csv")
    result = dict(全売買集計=audit_saved_rows(frame), 選択未来改変=audit_selection(frame))
    result["監査対象SHA256"] = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
                               for name in ["全条件セッション集計.csv", "全売買数値.npz", "engine.py", "research.py"]}
    (OUT / "全損益と選択の独立監査.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("全数値売買の原気配・損益再集計・確定下落・未来改変選択の監査が一致しました。", flush=True)


if __name__ == "__main__":
    main()
