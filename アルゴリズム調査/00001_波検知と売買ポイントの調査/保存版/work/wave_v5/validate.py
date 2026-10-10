"""方向候補の再現・損益・切断因果性と、元データの非変更を独立に監査する。"""

from __future__ import annotations

import argparse
from dataclasses import fields
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from exits import BASE, ConfigV5, simulate_exit
from search import cell_metrics, evaluate, load_data_v5, ranking_metrics, save_json, schedule_for
from signals import build_features


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def sha256(path: Path) -> str:
    """機能: 元ファイルを読み取りだけでハッシュ化する。

    引数: path (Path)。返り値: SHA256文字列 (str)。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def config_from_row(row: dict) -> ConfigV5:
    """機能: 比較表から定義済み設定項目だけを復元する。

    引数: row (dict)。返り値: 比較条件 (ConfigV5)。
    """
    values = {}
    for field in fields(ConfigV5):
        value = row.get(field.name)
        if value is None or pd.isna(value):
            value = field.default
        values[field.name] = value.item() if isinstance(value, np.generic) else value
    return ConfigV5(**values)


def normalized(value: object) -> object:
    """機能: 再計算値と保存JSONの型をそろえる。

    引数: value (object)。返り値: JSON化後のオブジェクト (object)。
    """
    return json.loads(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False))


def close_equal(actual: object, expected: object, label: str) -> None:
    """機能: 構造を保ったまま、数値の丸め誤差だけ許して値の一致を調べる。

    引数: actual/expected (object)、label (str) は不一致箇所表示。
    返り値: なし (None)。不一致なら AssertionError。
    """
    if isinstance(actual, dict) and isinstance(expected, dict):
        if actual.keys() != expected.keys():
            raise AssertionError(f"{label}: 項目が不一致")
        for key in actual:
            close_equal(actual[key], expected[key], f"{label}/{key}")
    elif isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            raise AssertionError(f"{label}: 件数が不一致")
        for position, (left, right) in enumerate(zip(actual, expected)):
            close_equal(left, right, f"{label}/{position}")
    elif isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if not np.isclose(actual, expected, rtol=1e-10, atol=1e-9):
            raise AssertionError(f"{label}: {actual} != {expected}")
    elif actual != expected:
        raise AssertionError(f"{label}: {actual} != {expected}")


def audit_accounting(trades: list[dict], cells: list[dict], data: dict) -> dict:
    """機能: 価格差・往復費用・保有時間・実在足と銘柄別集計を別計算で点検する。

    引数: trades/cells (list[dict])、data (dict) は実在足とセッション境界。
    返り値: 確認件数・時刻返済件数・利確価格抑制件数 (dict)。
    """
    capped_gap, timed = 0, 0
    for trade in trades:
        key = trade["session"], trade["symbol"]
        item, side = data[key], trade["side"]
        one, tick = item["one"], item["tick"]
        entry, exit_time = pd.Timestamp(trade["entry_time"]), pd.Timestamp(trade["exit_time"])
        signal = pd.Timestamp(trade["signal_time"])
        assert trade["closed"] and entry in one.index and exit_time in one.index
        assert entry >= signal + pd.Timedelta(minutes=1)
        assert entry <= exit_time < item["limit"] + pd.Timedelta(minutes=5)
        assert (entry - item["z"].index[0]).total_seconds() / 60 < item["limit_min"] - 30
        assert one.loc[entry, "low"] <= trade["entry_price"] <= one.loc[entry, "high"]
        within = one.loc[exit_time, "low"] <= trade["exit_price"] <= one.loc[exit_time, "high"]
        if not within:
            assert trade.get("reason") == "固定指値利確"
            assert side * (one.loc[exit_time, "open"] - trade["exit_price"]) >= 0
            capped_gap += 1
        if trade["reason"] == "セッション内の時刻返済":
            assert exit_time >= item["limit"]
            timed += 1
        gross = side * (trade["exit_price"] - trade["entry_price"])
        assert abs(gross - trade["gross_points"]) < 1e-9
        assert abs(gross - 2 * tick - trade["net_points"]) < 1e-9
        assert abs(gross - 4 * tick - trade["stress_points"]) < 1e-9
        assert abs((exit_time - entry).total_seconds() / 60 - trade["duration_min"]) < 1e-9
    for cell in cells:
        subset = [trade for trade in trades if (trade["session"], trade["symbol"]) == (cell["session"], cell["symbol"])]
        net = [trade["net_points"] for trade in subset]
        profit, loss = sum(max(0, value) for value in net), -sum(min(0, value) for value in net)
        assert abs(profit - cell["profit"]) < 1e-9 and abs(loss - cell["loss"]) < 1e-9
        assert abs(profit - loss - cell["net"]) < 1e-9
        assert len(subset) == cell["count"] == cell["closed"]
        assert sum(value > 0 for value in net) == cell["wins"]
        assert sum(value < 0 for value in net) == cell["losses"]
        assert sum(trade["duration_min"] <= 15 for trade in subset) == cell["micro15_count"]
        assert abs(sum(trade["net_points"] for trade in subset if trade["duration_min"] <= 15) - cell["micro15_net"]) < 1e-9
        assert abs(sum(trade["gross_points"] for trade in subset) - cell["cost"] - cell["net"]) < 1e-9
    return dict(取引数=len(trades), セル数=len(cells), 時刻返済件数=timed, 有利ギャップの利確価格抑制件数=capped_gap)


def visible_execution(trades: list[dict], cutoff: pd.Timestamp | None = None) -> list[dict]:
    """機能: 未来の返済を隠し、切断時点の取引実態だけを比較対象にする。

    引数: trades (list[dict])、cutoff (Timestamp | None)。返り値: 比較用取引 (list[dict])。
    """
    fields = ("symbol", "session", "side", "signal_time", "entry_time", "entry_price", "atr", "exit_time",
              "exit_price", "closed", "duration_min", "gross_points", "net_points", "stress_points", "net_atr")
    result = []
    for original in trades:
        if cutoff is not None and pd.Timestamp(original["entry_time"]) > cutoff:
            continue
        trade = {key: original[key] for key in fields if key in original}
        if cutoff is not None and trade["closed"] and pd.Timestamp(trade["exit_time"]) > cutoff:
            trade.update(exit_time=None, exit_price=None, closed=False, duration_min=None, gross_points=None)
            for field in ("net_points", "stress_points", "net_atr"):
                trade.pop(field, None)
        result.append(trade)
    return result


def read_five(session: str, symbol: str) -> pd.DataFrame:
    """機能: 確定済み５分足を描画や結果に依存せず読み込む。

    引数: session/symbol (str)。返り値: 確定５分足 (DataFrame)。
    """
    frame = pd.read_csv(ROOT / "candle_5min" / symbol / f"{session}.csv")
    frame["time"] = pd.to_datetime(frame.time)
    return frame[frame.closed.astype(str).str.lower().eq("true")].set_index("time").sort_index()


def audit_prefix(data: dict, selected: list[dict]) -> dict:
    """機能: 共通確定時刻で特徴量から再構成し、全段階の過去不変を確認する。

    引数: data (dict)、selected (list[dict]) は監査候補。
    返り値: 特徴・信号・取引の照合回数 (dict)。
    """
    full_schedules = {item["cfg"].key: schedule_for(data, item["cfg"]) for item in selected}
    full_trades = {item["cfg"].key: {key: simulate_exit(value, full_schedules[item["cfg"].key][key], item["cfg"])
                   for key, value in data.items()} for item in selected}
    feature_checks, signal_checks, execution_checks = 0, 0, 0
    for session in sorted({key[0] for key in data}):
        index = data[(session, "NK225")]["z"].index
        fives = {symbol: read_five(session, symbol) for symbol in ("NK225", "TOPIX")}
        for position in sorted({16, 45, 90, int(len(index) * .4), int(len(index) * .75)}):
            cutoff = index[position]
            clipped = {}
            for symbol in ("NK225", "TOPIX"):
                key = session, symbol
                full = data[key]
                one = full["one"].loc[:cutoff]
                directory = OUT if session == "2026-09-23_Day" else OUT.parent / ("wave_v3_check" if session == "2026-09-22_Night" else "wave_v2")
                board = directory / f"板特徴_{symbol}_{session}.csv"
                z = build_features(one, fives[symbol], board, full["tick"], cutoff)
                pd.testing.assert_frame_equal(z, full["z"].loc[:cutoff], check_exact=False, atol=1e-10, rtol=1e-10)
                clipped[key] = BASE.prepare(one, z, symbol, session)
                feature_checks += 1
            for chosen in selected:
                cfg = chosen["cfg"]
                schedules = schedule_for(clipped, cfg)
                for key, value in clipped.items():
                    for part in (0, 1):
                        np.testing.assert_array_equal(schedules[key][part], full_schedules[cfg.key][key][part][:len(value["z"])])
                    signal_checks += 1
                    prefix = simulate_exit(value, schedules[key], cfg)
                    expected = visible_execution(full_trades[cfg.key][key], value["times"][-1])
                    close_equal(normalized(visible_execution(prefix)), normalized(expected), f"切断/{cfg.key}/{key}/{cutoff}")
                    execution_checks += 1
    return dict(特徴一致=feature_checks, 信号一致=signal_checks, 約定一致=execution_checks)


def run() -> None:
    """機能: 完了した探索から代表を独立再生し、監査結果を日本語で保存する。

    引数: なし。返り値: なし (None)。API取得・条件選び直し・元データ変更は行わない。
    """
    data_audit = json.loads((OUT / "データ監査.json").read_text(encoding="utf-8"))
    expected_hashes = data_audit["source_sha256"]
    assert len(expected_hashes) == 30
    source_checks = []
    for relative, expected in expected_hashes.items():
        actual = sha256(ROOT / relative)
        assert actual == expected, f"元データの内容変更: {relative}"
        source_checks.append(dict(ファイル=relative, SHA256=actual, 一致=True))
    table = pd.read_csv(OUT / "方向全条件比較.csv")
    main = json.loads((OUT / "方向主候補.json").read_text(encoding="utf-8"))
    assert ConfigV5(**main["config"]).key == table.iloc[0].config
    selections = [("主候補", table.iloc[0].to_dict())]
    for family in (9, 18):
        selections.append((f"系統{family}代表", table[table.family.eq(family)].iloc[0].to_dict()))
    for mode in ("fixed_bracket", "small_stop_trail"):
        selections.append((f"出口{mode}代表", table[table.exit_mode.eq(mode)].iloc[0].to_dict()))
    selected = []
    for role, row in selections:
        cfg = config_from_row(row)
        duplicate = next((item for item in selected if item["cfg"].key == cfg.key), None)
        if duplicate is not None:
            duplicate["roles"].append(role)
        else:
            selected.append(dict(cfg=cfg, row=row, roles=[role]))
    data, replay_checks = load_data_v5(), []
    for chosen in selected:
        cfg = chosen["cfg"]
        payload = json.loads((OUT / f"方向候補_{cfg.key}.json").read_text(encoding="utf-8"))
        trades, cells = evaluate(data, cfg)
        close_equal(normalized(trades), payload["trades"], f"保存取引/{cfg.key}")
        close_equal(normalized(cells), payload["cells"], f"保存集計/{cfg.key}")
        close_equal(normalized(ranking_metrics(cells)), payload["summary"], f"順位指標/{cfg.key}")
        counts = audit_accounting(trades, cells, data)
        replay_checks.append(dict(役割=chosen["roles"], 条件=cfg.key, 保存再現=True, **counts))
    prefix = audit_prefix(data, selected)
    boundary = 0
    for key, item in data.items():
        mixed = item["one"].copy()
        mixed.loc[item["limit"] + pd.Timedelta(minutes=5)] = mixed.iloc[-1]
        try:
            BASE.prepare(mixed, item["z"], key[1], key[0])
        except ValueError:
            boundary += 1
        else:
            raise AssertionError(f"別セッション価格の混入を拒否できません: {key}")
    tradeoff_checks = 0
    tradeoff_path = OUT / "入口と微細波明細.json"
    if tradeoff_path.exists():
        for case in json.loads(tradeoff_path.read_text(encoding="utf-8")):
            audit_accounting(case["trades"], case["cells"], data)
            tradeoff_checks += 1
    results = dict(時刻=pd.Timestamp.now(tz="Asia/Tokyo"), 成功=True, API取得=False,
                   対象条件数=len(table), 元データ一致数=len(source_checks), 元データ照合=source_checks,
                   候補再現=replay_checks, 段階切断一致=prefix, セッション外価格拒否数=boundary,
                   入口感度会計確認数=tradeoff_checks,
                   追加返済単体試験="test_exits.py 14試験成功。160切断条件、60条件の既存互換も確認済み。",
                   検証コードSHA256={name: sha256(OUT / name) for name in ("exits.py", "test_exits.py", "search.py", "data.py", "validate.py")})
    save_json(OUT / "独立監査.json", results)
    lines = ["# 独立監査", "", "監査対象は全て保存済みの既知データです。通信と条件の選び直しは行っていません。", "",
             f"- 元データ30ファイル（足20・生板10）のSHA256が、探索前データ監査と全件一致しました。",
             f"- 主候補、系統9・18、追加出口２方式の代表を再計算し、保存取引・セッション集計・順位指標が一致しました（重複除外{len(selected)}条件）。",
             f"- 共通確定時刻で特徴を作り直した切断再生は、特徴{prefix['特徴一致']}・信号{prefix['信号一致']}・約定{prefix['約定一致']}の全件で一致しました。",
             f"- 全取引が実在足で新規・返済され、セッション外価格混入の拒否{boundary}件に成功しました。",
             "- 利益合計−損失合計＝収支、価格差損益−往復費用＝収支、２・４ティック費用、保有時間、15分以内の件数と収支を別計算で照合しました。",
             f"- 入口・微細波の感度明細も{tradeoff_checks}条件で会計照合しました。",
             "- 追加返済の単体試験14件、160切断条件、60条件の既存追跡約定互換は事前に成功しています。", ""]
    (OUT / "独立監査.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({key: value for key, value in results.items() if key not in ("元データ照合", "検証コードSHA256")}, ensure_ascii=False, default=str))


def audit_trailing_update() -> None:
    """機能: 初期損切りを固定した追跡幅４条件だけを再照合し、既存監査へ追記する。

    引数: なし。返り値: なし (None)。全探索・全テストは再実行しない。
    """
    details_path = OUT / "入口と微細波明細.json"
    details = json.loads(details_path.read_text(encoding="utf-8"))
    base = next(case for case in details if case["name"] == "基準")
    cases = [case for case in details if case["name"].startswith("追跡幅_")]
    assert len(cases) == 4 and {case["config"]["trail"] for case in cases} == {1.5, 2.5, 4.0, 6.0}
    assert base["config"]["exit_mode"] == "nativebaseline"
    initial = min(2.5, base["config"]["trail"])
    data = load_data_v5()
    records = []
    for case in cases:
        cfg = ConfigV5(**case["config"])
        assert cfg.exit_mode == "small_stop_trail" and cfg.stop_loss == initial
        expected = dict(base["config"], exit_mode="small_stop_trail", stop_loss=initial, trail=cfg.trail)
        close_equal(case["config"], expected, f"追跡幅以外固定/{case['name']}")
        trades, cells = evaluate(data, cfg)
        close_equal(normalized(trades), case["trades"], f"追跡保存取引/{case['name']}")
        close_equal(normalized(cells), case["cells"], f"追跡保存集計/{case['name']}")
        counts = audit_accounting(trades, cells, data)
        for trade in trades:
            tick = data[(trade["session"], trade["symbol"])]["tick"]
            stop = BASE.rounded(trade["entry_price"] - trade["side"] * initial * trade["atr"], tick, trade["side"] == -1)
            assert abs(trade["initial_stop"] - stop) < 1e-9
        matched = None
        if cfg.trail == base["config"]["trail"]:
            close_equal(normalized(visible_execution(trades)), normalized(visible_execution(base["trades"])), "追跡4ATRと基準の約定・損益")
            close_equal(normalized(cells), base["cells"], "追跡4ATRと基準のセッション集計")
            matched = True
        records.append(dict(条件=case["name"], 初期損切りATR=initial, 保存再現=True,
                            基準との約定損益一致=matched, **counts))
    update = dict(時刻=pd.Timestamp.now(tz="Asia/Tokyo"), 成功=True, 対象４条件=records,
                  実施範囲="初期損切り2.5ATR固定の追跡幅1.5/2.5/4/6ATRだけ再検証。全探索・全テストは再実行しない。",
                  入口比較コードSHA256=sha256(OUT / "tradeoff.py"), 感度明細SHA256=sha256(details_path))
    record_path = OUT / "独立監査.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["追跡幅の追加監査"] = update
    record["検証コードSHA256"]["validate.py"] = sha256(OUT / "validate.py")
    save_json(record_path, record)
    report = OUT / "独立監査.md"
    text = report.read_text(encoding="utf-8")
    marker = "\n## 追跡幅の比較に対する追加監査\n"
    text = text.split(marker)[0]
    text += marker + "\n初期損切りを全て2.5ATRに固定し、追跡幅だけを1.5・2.5・4・6ATRへ変える４条件を再検証しました。４条件の保存取引・集計・費用計算が再現しました。追跡幅4ATRは、元の基準条件と新規・返済・損益および全セッション集計が一致しています。全探索・全テストの再実行はしていません。\n"
    report.write_text(text, encoding="utf-8")
    print(json.dumps(update, ensure_ascii=False, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="方向候補の独立監査")
    parser.add_argument("--trailing-update", action="store_true")
    arguments = parser.parse_args()
    audit_trailing_update() if arguments.trailing_update else run()
