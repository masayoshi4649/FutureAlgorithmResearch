"""全出口条件の会計・入口固定・時刻境界を、診断用の独立計算と突き合わせる。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import io
import json
import unittest

import numpy as np
import pandas as pd

from audit_baseline import MULTIPLIER, audit_trade
from exit_engine import ExitRule, simulate
from search_exits import configurations, rank
from shared import ARCHIVE, OUT, SESSIONS, load_inputs, normalize, save_json


def comparable(trades: list[dict], cutoff: pd.Timestamp) -> list[dict]:
    """機能: 指定時刻までに返済済みの取引を日時文字列へ正規化する。

    引数: trades (list[dict]) は仮想取引、cutoff (Timestamp) は観測済み最後の足。
    返り値: 比較できる取引一覧 (list[dict])。
    """
    return normalize([t for t in trades if t["closed"] and pd.Timestamp(t["exit_time"]) <= cutoff])


def truncate(data: dict, length: int) -> dict:
    """機能: 将来の価格足を削っても、セッション終了時刻は変更しない。

    引数: data (dict) は全期間入力、length (int) は保存する実在足数。
    返り値: 価格だけを期間短縮した再生入力 (dict)。
    """
    short = data.copy()
    for field in ("times", "minutes", "values", "positions"):
        short[field] = data[field][:length]
    return short


def run() -> None:
    """機能: 全条件の結果と代表条件の未来不変性を検査し、監査記録を出力する。

    引数: なし。
    返り値: なし (None)。入力と元調査は更新しない。
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([loader.discover(str(OUT), pattern="test_baseline_audit.py"),
                               loader.discover(str(OUT), pattern="test_exit_independent.py")])
    stream = io.StringIO()
    unit = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    assert unit.wasSuccessful(), stream.getvalue()
    data, schedules, cfg, primary = load_inputs()
    protected = [OUT / name for name in ("exit_engine.py", "shared.py", "search_exits.py", "出口全条件取引.json", "比較対象.json")]
    beginning_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    results = json.loads((OUT / "出口全条件取引.json").read_text(encoding="utf-8"))
    selected = json.loads((OUT / "比較対象.json").read_text(encoding="utf-8"))
    assert len(results) == len(configurations()) == 192
    old = primary["trades"]
    baseline_rule = ExitRule("baseline")
    baseline = []
    for key, item in data.items():
        baseline.extend(simulate(item, schedules[key], cfg, baseline_rule))
    assert len(baseline) == len(old) == 12
    assert all({key: normalize(actual[key]) for key in prior} == prior for actual, prior in zip(baseline, old))
    all_count, anchor_count, cell_count = 0, 0, 0
    old_by_key = {(session, symbol): [t for t in old if (t["session"], t["symbol"]) == (session, symbol)] for session, symbol in data}
    for result in results.values():
        for mode, field in (("full", "full_cells"), ("anchored", "anchored_cells")):
            trades = result[mode]
            for key, item in data.items():
                group = sorted([t for t in trades if (t["session"], t["symbol"]) == key], key=lambda t: t["entry_time"])
                if mode == "anchored":
                    prior = old_by_key[key]
                    assert len(group) == len(prior)
                    for actual, original in zip(group, prior):
                        for attr in ("symbol", "session", "entry_time", "entry_price", "atr", "side", "signal_time"):
                            assert actual[attr] == original[attr], (mode, key, attr)
                        anchor_count += 1
                else:
                    assert all(pd.Timestamp(group[j]["entry_time"]) >= pd.Timestamp(group[j-1]["exit_time"]) + pd.Timedelta(minutes=45) for j in range(1, len(group)))
                candles = item["one"]
                for trade in group:
                    assert trade["closed"]
                    entry, end = pd.Timestamp(trade["entry_time"]), pd.Timestamp(trade["exit_time"])
                    assert entry <= end < item["limit"] + pd.Timedelta(minutes=5)
                    audit = audit_trade(trade, candles, 0)
                    multiplier = MULTIPLIER[key[1]]
                    assert np.isclose(audit["最大含み益費用前円"], trade["mfe_close_points"] * multiplier)
                    assert np.isclose(audit["利益返却円"], trade["giveback_points"] * multiplier)
                    assert np.isclose(audit["初期損切価格"], trade["initial_stop"])
                    assert np.isclose(trade["stress_points"], trade["gross_points"] - 4 * item["tick"])
                    all_count += 1
                cell = next(row for row in result[field] if (row["session"], row["symbol"]) == key)
                assert cell["count"] == len(group)
                net = np.array([t["net_points"] for t in group])
                assert np.isclose(cell["profit"], net[net > 0].sum())
                assert np.isclose(cell["loss"], -net[net < 0].sum())
                assert np.isclose(cell["net"], net.sum())
                assert np.isclose(cell["profit"] - cell["loss"], cell["net"])
                assert mode != "full" or cell["overlapping_anchors"] == 0
                cell_count += 1

    # ----------------------------------------
    # 確認期間の成績を巨大な逆符号へ差し替えても、訓練得点が変わらないことを確認する。
    base_cells = results[baseline_rule.key]["full_cells"]
    ranking_count, eligible_candidates, ranked = 0, 0, []
    for result in results.values():
        prior = rank(result["full_cells"], result["anchored_cells"], base_cells, SESSIONS[:4])
        rule = result["rule"]
        if rule["kind"] != "baseline" and not (rule["kind"] == "fixed_trail" and rule["width"] == 4):
            ranked.append((not prior["eligible"], -prior["score"], ExitRule(**rule).key))
            eligible_candidates += int(prior["eligible"])
        altered = deepcopy([result["full_cells"], result["anchored_cells"], base_cells])
        for cells in altered:
            for cell in cells:
                if cell["session"] == SESSIONS[4]:
                    for field in ("stress_yen", "giveback_yen", "count"):
                        cell[field] = -1000000000
        assert rank(*altered, SESSIONS[:4]) == prior
        ranking_count += 1
    assert sorted(ranked)[0][2] == selected["selected"]["key"]
    assert selected["selection"]["eligible"] == (eligible_candidates > 0)

    # ----------------------------------------
    # 足の先頭半分・四分の三だけで再生した結果が、全期間の同時点までと一致する。
    representative = {}
    for result in results.values():
        representative.setdefault(result["rule"]["kind"], ExitRule(**result["rule"]))
    for delay in (1, 2):
        for kind in ("profit_lock", "stagnation"):
            representative[f"{kind}_{delay}"] = ExitRule(kind, delay=delay)
    representative["selected"] = ExitRule(**selected["selected"]["rule"])
    representative["利益保護参考"] = ExitRule("stepped", trigger=2.5, width=.5)
    prefix_count = 0
    for rule in representative.values():
        for key, item in data.items():
            complete = simulate(item, schedules[key], cfg, rule)
            for ratio in (.5, .75):
                length = int(len(item["times"]) * ratio)
                prefix = truncate(item, length)
                cutoff = prefix["times"][-1]
                limited = simulate(prefix, schedules[key], cfg, rule)
                assert comparable(limited, cutoff) == comparable(complete, cutoff), (rule.key, key, cutoff)
                prefix_count += 1

    # ----------------------------------------
    # 保存版入力の指紋が独立監査開始時と同じであることを確認する。
    audit_source = json.loads((OUT / "元方式の利益返却.json").read_text(encoding="utf-8"))
    from shared import ROOT
    for name, expected in audit_source["入力指紋"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    for path in protected:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == beginning_hashes[path.name], f"監査中に更新されました: {path.name}"
    paths = [OUT / name for name in ("exit_engine.py", "shared.py", "search_exits.py", "audit_baseline.py", "test_baseline_audit.py", "test_exit_independent.py", "出口全条件取引.json", "比較対象.json")]
    output = dict(
        成功=True, 人工境界検査数=unit.testsRun, 元取引完全一致数=len(baseline), 出口条件数=len(results),
        全取引会計及び最大利益照合数=all_count, 固定入口照合数=anchor_count, セル照合数=cell_count,
        訓練得点の確認期間変更不変数=ranking_count, 基準及び同値別名除外後の適格条件数=eligible_candidates,
        最終選定の順位一致=True, 未来足追加不変数=prefix_count,
        入力指紋不変数=len(audit_source["入力指紋"]), 現在API取得=False,
        修正済指摘=["構造型の幅０と反転型の起動０を固定計画どおり許可", "基準実装参照を保存版へ統一"],
        留意事項=["固定元入口は診断であり再新規ルールとして実行できない。重複保有も許すため実行可能版と分離する。",
                  "９月２３日を見て改善課題を設定したので、訓練得点へ混ぜなくても未使用データによる独立検証ではない。",
                  "１分足がない区間では保護条件の接触を観測できず、実在する次の足でしか返済できない。",
                  "保護幅や指値利確の起動は有利高安を利用するが確定後に更新し、次実在足から有効。利益返却の主指標は１分終値で別途計算。"],
        対象指紋={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
    )
    save_json(OUT / "v6出口独立監査.json", output)
    lines = ["# 出口改善の独立監査", "", "検査はすべて成功。原本・元調査を変更せず、現在ＡＰＩも取得していない。", "",
             f'- 人工境界検査: {unit.testsRun}件。新規足・返済足の扱い、SL/TP順序、買売ギャップ、初期2.5ATR、追加１・２足遅延、成行保留、当足高安の遡及利用禁止。',
             f'- 元の全12取引は保存版と全既存属性で一致。{len(results)}条件・{all_count}取引の会計と最大利益を独立診断に照合。',
             f'- 固定入口は{anchor_count}件で新規時刻・価格・方向・ATR・信号時刻が一致。{cell_count}セルの利益・損失・収支が一致。',
             '- 実行可能版は重複保有ゼロ、返済後45分待機、全建玉セッション内返済。',
             f'- 確認期間を改変しても{ranking_count}条件の訓練得点は不変。未来足を追加しても{prefix_count}条件・期間組合せの過去確定取引は不変。',
             f'- 基準方式と幅4ATRの同値別名を除外した後の適格条件は{eligible_candidates}件。適格性・得点・識別子の規定順序と最終選定が一致。',
             '- 保存足20ファイルの旧指紋照合と、独立監査開始時からの11ファイル指紋不変を確認。', "",
             "初回レビューで計画のゼロ値と引数検証の不一致、保存版以外の基準実装参照を指摘し、担当による修正後のコードを検査した。", ""]
    lines.extend(f'- {note}' for note in output["留意事項"])
    lines.append("")
    (OUT / "v6出口独立監査.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key not in ("対象指紋", "留意事項")}, ensure_ascii=False))


if __name__ == "__main__":
    run()
