"""入口と保有方向を分離したエンジンを、成績選別なしで独立監査する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "wave_v23"
PREVIOUS = HERE.parent / "wave_v27"
sys.path.insert(0, str(OLD))
import engine as LEGACY
import managers
sys.path.insert(0, str(PREVIOUS))
import hierarchy_signals
sys.path.insert(0, str(HERE))
import engine_context as ENGINE


def digest(path: Path) -> str:
    """機能: 参照コードと固定仕様の不変性を確認する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def structural_check() -> dict:
    """機能: 指定された4つの保有判定以外にsimulateの処理差がないか検証する。

    引数: なし。返り値: AST差分検査結果 (dict)。
    """
    old = ast.parse((OLD / "engine.py").read_text(encoding="utf-8"))
    new = ast.parse((HERE / "engine_context.py").read_text(encoding="utf-8"))
    old_functions = {node.name: node for node in old.body if isinstance(node, ast.FunctionDef)}
    new_functions = {node.name: node for node in new.body if isinstance(node, ast.FunctionDef)}
    own = deepcopy(new_functions["simulate"])
    own.args.args = [node for node in own.args.args if node.arg != "context"]
    changed = []
    for node in ast.walk(own):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "context":
            changed.append(node.lineno)
            node.value.id = "state"
    for function in (own, old_functions["simulate"]):
        if isinstance(function.body[0], ast.Expr) and isinstance(function.body[0].value, ast.Constant):
            function.body.pop(0)
    assert len(changed) == 4
    assert ast.dump(own, include_attributes=False) == ast.dump(old_functions["simulate"], include_attributes=False), "指定4判定以外のsimulate差分"
    for name in ("rounded", "inventory", "close_positions"):
        assert ast.dump(old_functions[name], include_attributes=False) == ast.dump(new_functions[name], include_attributes=False)
    assert ENGINE.PARAMS == LEGACY.PARAMS and ENGINE.REASONS == LEGACY.REASONS
    return dict(保有判定だけ4箇所変更=True, context参照行=changed, 注文会計補助関数は同一=True)


def ready(prices: list[float] | np.ndarray, seconds: np.ndarray | None = None) -> dict:
    """機能: 末尾に返済用行を持つ、価格統計を使わない合成入力を作る。

    引数: prices (list[float]|ndarray)、seconds (ndarray|None)。返り値: エンジン入力 (dict)。
    """
    prices = np.asarray(prices, dtype=float)
    times = np.arange(len(prices), dtype=float) if seconds is None else np.asarray(seconds, float)
    return dict(time_s=times, last=prices, atr=np.full(len(prices), 2.), seq=np.arange(len(prices)), tick=1.,
                start=0., limit=float(times[-2]), us_open=1e9, symbol="TOPIX", session="合成監査")


def config(**changes) -> dict:
    """機能: 他の退出が干渉しない合成用設定を、差分指定で作る。

    引数: changes (dict) は既存管理パラメータ。返り値: 合成用管理設定 (dict)。
    """
    value = dict(managers.BASE, initial_qty=1, audit_cap=10, point_value=1., warmup_min=0., entry_cutoff_min=0.,
                 entry_mode=2, cooldown_min=0., stop_atr=20., main_trail=100., activation_atr=100.,
                 timeout_min=1000., ttl_seconds=1000.)
    value.update(changes)
    return value


def accounting(data: dict, result: dict, cfg: dict, final_flat: bool = True) -> int:
    """機能: 注文から現金・両方向在庫・実現損益を独立に復元する。

    引数: data/result/cfg (dict)、final_flat (bool)。返り値: 照合した原本行数 (int)。
    """
    count = len(data["last"])
    cash_delta, long_delta, short_delta, realized_delta = (np.zeros(count) for _ in range(4))
    orders, trades, curve = result["orders"], result["trades"], result["curve"]
    assert np.all(orders[:, 0] > orders[:, 1])
    assert np.all(trades[:, 7] > trades[:, 6])
    for row, source, campaign, side, quantity, price, reason, is_open in orders:
        row = int(row)
        assert quantity > 0 and quantity == int(quantity)
        cash_delta[row] -= side * quantity * price
        if is_open:
            (long_delta if side > 0 else short_delta)[row] += quantity
        else:
            (short_delta if side > 0 else long_delta)[row] -= quantity
    for trade in trades:
        expected = trade[2] * trade[3] * (trade[5] - trade[4])
        np.testing.assert_allclose(expected, trade[10], atol=1e-7, rtol=0)
        realized_delta[int(trade[7])] += expected
    cash, longs, shorts, realized = (np.cumsum(values) for values in (cash_delta, long_delta, short_delta, realized_delta))
    assert np.min(longs) >= 0 and np.min(shorts) >= 0
    assert np.max(longs) <= cfg["audit_cap"] and np.max(shorts) <= cfg["audit_cap"]
    np.testing.assert_allclose(curve[:, 5], cash, atol=1e-6, rtol=0)
    np.testing.assert_allclose(curve[:, 2], longs, atol=0, rtol=0)
    np.testing.assert_allclose(curve[:, 3], shorts, atol=0, rtol=0)
    np.testing.assert_allclose(curve[:, 6], longs - shorts, atol=0, rtol=0)
    np.testing.assert_allclose(curve[:, 1], realized, atol=1e-6, rtol=0)
    np.testing.assert_allclose(curve[:, 0], cash + (longs - shorts) * data["last"], atol=1e-6, rtol=0)
    if final_flat:
        assert longs[-1] == shorts[-1] == result["stats"][9] == 0
        np.testing.assert_allclose([trades[:, 10].sum(), result["cycles"][:, 3].sum(), result["stats"][0]], realized[-1], atol=1e-6, rtol=0)
    return count


def equal(old: dict, new: dict) -> None:
    """機能: 旧互換対象の全台帳・全会計配列を完全照合する。

    引数: old/new (dict)。返り値: なし (None)。
    """
    for key in ("trades", "cycles", "curve", "orders", "stats"):
        np.testing.assert_array_equal(old[key], new[key], err_msg=key)


def logical_cases() -> tuple[dict, list[tuple]]:
    """機能: 2入力の役割・部分利確・予算停止を反例用の短い経路で検査する。

    引数: なし。返り値: 判定一覧と後続対称性検査用ケース (tuple[dict,list[tuple]])。
    """
    cases, checks = [], {}

    def run(name: str, data: dict, entry: np.ndarray, context: np.ndarray, cfg: dict) -> dict:
        """機能: 一つの合成を再生し会計検査を共通適用する。

        引数: name (str)、data/cfg (dict)、entry/context (ndarray)。返り値: 再生台帳 (dict)。
        """
        result = ENGINE.run(data, entry, cfg, detail=True, context=context)
        accounting(data, result, cfg)
        cases.append((name, deepcopy(data), entry.copy(), context.copy(), dict(cfg), result))
        return result

    flat = ready([100.] * 12)
    zeros, ones = np.zeros(12, np.int8), np.ones(12, np.int8)
    result = run("contextだけで新規しない", flat, zeros, ones, config())
    assert len(result["orders"]) == 0
    checks["contextだけで通常新規しない"] = True
    entry = ones.copy(); entry[2:] = 0
    result = run("入口消失でも主方向保持", flat, entry, ones, config(neutral_min=.05, signal_exit=1))
    assert set(result["trades"][:, 9]) == {9}
    checks["entry中立だけでは保有中立撤回しない"] = True
    context = ones.copy(); context[3:] = -1
    result = run("context反転で撤回", flat, ones, context, config(signal_exit=1, cooldown_min=10.))
    assert result["trades"][0, 7] == 4 and result["trades"][0, 9] == 13
    checks["context反転の次行で撤回"] = True
    entry = np.array([1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 0], dtype=np.int8)
    context = ones.copy(); context[3:] = 0
    result = run("中立時計はcontext", flat, entry, context, config(neutral_min=.05, cooldown_min=10.))
    assert result["trades"][0, 7] == 7 and result["trades"][0, 9] == 10
    checks["entry点滅はcontext中立時計を戻さない"] = True
    data = ready([100, 100, 103, 103, 103, 103, 103, 103])
    entry = np.ones(8, np.int8); context = entry.copy(); context[1:] = -1
    result = run("contextで未約定を取消しない", data, entry, context, config(entry_mode=0, entry_atr=1.))
    assert result["orders"][0, 0] == 2
    entry[1:] = 0; context[:] = 1
    result = run("entryで未約定取消", data, entry, context, config(entry_mode=0, entry_atr=1.))
    assert len(result["orders"]) == 0
    checks["未約定取消はentryのみ"] = True
    data = ready([100, 100, 97] + [97.] * 12)
    entry = np.ones(15, np.int8); context = entry.copy(); context[3:] = -1
    cfg = config(stop_atr=1., max_same_losses=1, rearm_atr=10., cooldown_min=8 / 60)
    result = run("contextで連敗解除しない", data, entry, context, cfg)
    assert np.count_nonzero(result["orders"][:, 6] == 20) == 1
    entry = entry.copy(); entry[4] = -1
    result = run("entry反対で連敗解除", data, entry, context, cfg)
    assert np.count_nonzero(result["orders"][:, 6] == 20) == 2
    checks["連敗解除はcontextでなくentry"] = True
    data = ready([100, 100, 102, 103, 101, 96, 95, 95, 95, 95, 95, 95])
    entry = np.ones(12, np.int8); context = entry.copy(); context[5] = -1
    result = run("奇数部分利確と組全体連敗", data, entry, context,
                 config(initial_qty=5, split_target=1., signal_exit=1, max_same_losses=1, rearm_atr=10.))
    split = result["trades"][result["trades"][:, 9] == 7]
    assert len(split) == 1 and split[0, 3] == 2
    assert np.count_nonzero(result["orders"][:, 6] == 20) == 1
    assert len(result["cycles"]) == 1 and result["cycles"][0, 3] < 0
    assert result["trades"][:, 3].sum() == 5 and np.all(result["trades"][:, 6] == 1)
    checks["部分利確の整数枚と元建値を保持し組全体で連敗"] = True
    data = ready([100, 100, 97, 95, 110, 120, 125, 120, 120, 120])
    entry = np.ones(10, np.int8); context = entry.copy()
    result = run("含み損予算は以後停止", data, entry, context, config(session_budget_yen=2.))
    assert result["trades"][0, 7] == 3 and result["trades"][0, 9] == 14
    assert np.count_nonzero(result["orders"][:, 6] == 20) == 1
    checks["含み損予算を割った次行返済かつ反発後も再開禁止"] = True
    for invalid in (np.ones(10), np.ones((10, 1), np.int8), np.ones(9, np.int8), np.full(10, 2, np.int8)):
        try:
            ENGINE.run(data, entry, config(), context=invalid)
        except ValueError:
            continue
        raise AssertionError("不正contextを受け入れた")
    checks["contextの型長さ値を拒否"] = True
    return checks, cases


def reflection(cases: list[tuple]) -> int:
    """機能: 上下反射後の理由・時刻・枚数・損益・会計を照合する。

    引数: cases (list[tuple])。返り値: 一致ケース数 (int)。
    """
    for name, data, entry, context, cfg, original in cases:
        mirrored = dict(data, last=200. - data["last"])
        changed = ENGINE.run(mirrored, -entry, cfg, detail=True, context=-context)
        accounting(mirrored, changed, cfg)
        expected = original["orders"].copy()
        expected[:, 3] *= -1; expected[:, 5] = 200. - expected[:, 5]
        np.testing.assert_allclose(expected, changed["orders"], atol=1e-8, rtol=0, err_msg=name)
        expected = original["trades"].copy()
        expected[:, 2] *= -1; expected[:, 4:6] = 200. - expected[:, 4:6]
        np.testing.assert_allclose(expected, changed["trades"], atol=1e-8, rtol=0, err_msg=name)
        expected = original["cycles"].copy(); expected[:, 8] *= -1
        np.testing.assert_allclose(expected, changed["cycles"], atol=1e-8, rtol=0, err_msg=name)
        np.testing.assert_allclose(original["curve"][:, [0, 1, 4]], changed["curve"][:, [0, 1, 4]], atol=1e-8, rtol=0)
    return len(cases)


def context_mapping(inputs: dict) -> tuple[dict, dict]:
    """機能: 96入口を24中期方向へ対応させ、主方向のみ入口と完全照合する。

    引数: inputs (dict)。返り値: 対応検査結果と代表context (tuple[dict,dict])。
    """
    specs = hierarchy_signals.catalog()
    grouped, hashes, checked = {}, {}, 0
    representative = None
    for spec in specs:
        params = spec["params"]
        key = (params["main_kind"], params["time_multiplier"], params["peer_confirm"])
        values = hierarchy_signals.main_directions(spec, inputs)
        if key in grouped:
            for data_key in inputs:
                np.testing.assert_array_equal(grouped[key][data_key], values[data_key])
                checked += 1
        else:
            grouped[key] = values
        if params["entry_kind"] == "direction":
            with np.load(PREVIOUS / "directions" / f"{spec['id']}.npz", allow_pickle=False) as archive:
                for data_key in inputs:
                    np.testing.assert_array_equal(archive["|".join(data_key)], values[data_key])
                    checked += 1
        fingerprint = hashlib.sha256()
        for data_key in sorted(inputs):
            fingerprint.update(values[data_key].tobytes())
        hashes[key] = fingerprint.hexdigest()
        if spec["id"] == "H004":
            representative = values
    assert len(grouped) == len(set(hashes.values())) == 24
    return dict(主方向系列数=24, 入口対応比較数=checked, 未来情報なしの既存主方向関数使用=True), representative


def compatible_and_causal(inputs: dict, context: dict, cases: list[tuple]) -> dict:
    """機能: 旧互換と2入力のprefix/未来改変不変を、成績表示せず検査する。

    引数: inputs/context (dict)、cases (list[tuple])。返り値: 比較件数と会計行数 (dict)。
    """
    count = prefix = future = rows = 0
    for name, data, entry, held, cfg, result in cases:
        old = LEGACY.run(data, entry, cfg, detail=True)
        equal(old, ENGINE.run(data, entry, cfg, detail=True))
        equal(old, ENGINE.run(data, entry, cfg, detail=True, context=entry))
        count += 2
    selected = [item for item in managers.manager_catalog() if item["id"] in ("G01", "G02", "G08", "G11", "G12", "G14", "G16", "G17")]
    with np.load(PREVIOUS / "directions" / "H004.npz", allow_pickle=False) as archive:
        for key, data in inputs.items():
            entry = archive["|".join(key)]
            for manager in selected:
                cfg = managers.make_config(manager, key[1], data)
                original = LEGACY.run(data, entry, cfg, detail=True)
                current = ENGINE.run(data, entry, cfg, detail=True, context=entry)
                equal(original, current)
                rows += accounting(data, current, cfg)
                count += 1
                if key[0] not in ("2026-09-22_Night", "2026-09-29_Day") or manager["id"] not in ("G01", "G08", "G12", "G14"):
                    continue
                full = ENGINE.run(data, entry, cfg, detail=True, context=context[key])
                rows += accounting(data, full, cfg)
                for fraction in (.31, .67):
                    length = int(len(entry) * fraction)
                    short = {name: value[:length].copy() if isinstance(value, np.ndarray) and value.ndim and len(value) == len(entry) else value for name, value in data.items()}
                    partial = ENGINE.run(short, entry[:length], cfg, detail=True, context=context[key][:length])
                    for name, column in (("orders", 0), ("trades", 7), ("cycles", 2)):
                        np.testing.assert_array_equal(full[name][full[name][:, column] < length], partial[name])
                    np.testing.assert_array_equal(full["curve"][:length], partial["curve"])
                    prefix += 1
                    changed = dict(data)
                    for name in ("last", "atr"):
                        changed[name] = data[name].copy(); changed[name][length:] = changed[name][length:] * 1.5 + 300
                    changed_entry, changed_context = entry.copy(), context[key].copy()
                    changed_entry[length:] *= -1; changed_context[length:] = 1 - abs(changed_context[length:])
                    altered = ENGINE.run(changed, changed_entry, cfg, detail=True, context=changed_context)
                    for name, column in (("orders", 0), ("trades", 7), ("cycles", 2)):
                        np.testing.assert_array_equal(full[name][full[name][:, column] < length], altered[name][altered[name][:, column] < length])
                    np.testing.assert_array_equal(full["curve"][:length], altered["curve"][:length])
                    future += 1
    return dict(旧互換比較数=count, prefix比較数=prefix, 未来値改変比較数=future, 注文からの会計照合行数=rows)


def main() -> None:
    """機能: 独立監査を実行し、成績ではなく合否と参照指紋だけ保存する。

    引数: なし。返り値: なし (None)。現在データと成績ランキングは使用しない。
    """
    paths = [Path(__file__), HERE / "context_audit_plan.md", HERE / "engine_context.py", OLD / "engine.py",
             OLD / "managers.py", PREVIOUS / "hierarchy_signals.py", PREVIOUS / "hierarchy_design_fixed.json"]
    hashes = {str(path): digest(path) for path in paths}
    structure = structural_check()
    logical, cases = logical_cases()
    reflected = reflection(cases)
    print("構造差分・2入力の役割・部分利確/停止・上下反射が一致", flush=True)
    inputs = pickle.loads((OLD / "inputs.pkl").read_bytes())
    mapping, context = context_mapping(inputs)
    comparison = compatible_and_causal(inputs, context, cases)
    assert hashes == {str(path): digest(path) for path in paths}, "監査中にコードが変更された"
    report = dict(全検査合格=True, 新損益の集計表示比較=False, API取得数=0, 現在スナップショット使用=False,
                  構造検査=structure, 合成論理=logical, 上下反射ケース数=reflected, 中期入力対応=mapping,
                  既存原本による監査=comparison, 参照コード不変=True, SHA256=hashes,
                  限界=["監査通過は収益性の保証ではない。", "context反転の補充新規は保有管理の例外。今回の管理候補では反転を使わない。",
                        "セッション損失予算は次行執行のため価格飛躍で超過し得る。", "CurrentPriceTimeは受信時刻ではない。"])
    (HERE / "context_engine_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 第4反復エンジンの独立監査", "", "入口と保有方向の2入力を、成績選別なしで検査した。", "",
             f"- 保有判定4箇所以外のsimulate処理は旧エンジンと同一。context=entryの旧互換{comparison['旧互換比較数']}比較が完全一致。",
             f"- prefix {comparison['prefix比較数']}比較、未来の2方向/価格/ATR改変{comparison['未来値改変比較数']}比較が一致。",
             f"- 注文から独立再構築した会計を{comparison['注文からの会計照合行数']:,}行で照合。上下反射{reflected}ケースが一致。",
             f"- 96入口は24中期方向へ対応し、{mapping['入口対応比較数']}配列比較が一致。",
             "- contextだけでは通常新規しない。entry中立でもcontextが維持されれば中立撤回しない。未約定取消と連敗解除はentryに従う。",
             "- 奇数枚の部分利確後も元建値と残枚数を保持し、組全体の損益で連敗を数える。含み損予算停止後は価格反発でも再開しない。", ""]
    lines += ["- " + item for item in report["限界"]]
    (HERE / "context_engine_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(comparison, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
