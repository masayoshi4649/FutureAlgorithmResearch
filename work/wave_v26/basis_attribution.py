"""一次反証通過の17候補が、発注時にどの基礎方向を採用したかを測る。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import episode_audit as episode


def selected_basis(values: np.ndarray, mode: str) -> list[str]:
    """機能: 事前固定された合成式の主採用先を、その時点の4方向から説明する。

    引数: values (ndarray[int8]) はF32/D016/D056/P02の順、mode (str) は合成規則。
    返り値: 入口方向の主な採用元一覧 (list[str])。反対抑止に使う基礎は別集計。
    """
    names = ("F32", "D016", "D056", "P02")
    if mode in names:
        return [mode]
    if mode in ("D016_first", "D056_first"):
        index = 1 if mode == "D016_first" else 2
        return [names[index]] if values[index] != 0 else ["F32"]
    if mode == "price_and_flow":
        if values[3] != 0:
            agreement = [names[index] for index in (1, 2) if values[index] == values[3]]
            if agreement:
                return ["P02"] + agreement
        return ["F32"]
    if mode == "two_agree":
        active = values[values != 0]
        if len(active) >= 2 and np.all(active == active[0]):
            return [names[index] for index in range(4) if values[index] == active[0]]
        return []
    raise ValueError("未定義の合成方式です")


def tally(records: list[dict]) -> dict:
    """機能: 主玉新規の決定元における非中立・同方向・主採用先を数える。

    引数: records (list[dict]) は約定した新規注文の起源記録。
    返り値: 初回主玉の採用件数と、追加等を含む新規件数 (dict)。
    """
    initial = [row for row in records if row["理由番号"] == 20]
    names = ("F32", "D016", "D056", "P02")
    return dict(全新規件数=len(records), 初回主玉新規件数=len(initial),
                非中立基礎件数={name: sum(row["基礎方向"][name] != 0 for row in initial) for name in names},
                新規と同方向の基礎件数={name: sum(row["基礎方向"][name] == row["direction"] for row in initial) for name in names},
                主採用元件数={name: sum(name in row["主採用元"] for row in initial) for name in names},
                F32以外の主採用がある新規件数=sum(any(name != "F32" for name in row["主採用元"]) for row in initial),
                F32だけ非中立の新規件数=sum(row["基礎方向"]["F32"] != 0 and all(row["基礎方向"][name] == 0 for name in names[1:]) for row in initial))


def main() -> None:
    """機能: 全17候補を全26入力で再生し、初回新規の基礎採用とF32単独一致を保存する。

    引数: なし。返り値: なし (None)。売買条件は変更せず、診断を採用順位へ使わない。
    """
    source = HERE / "一次反証の結果.json"
    methods = [item for item in episode.methods(None, source) if item["signal"]["実装元"] == "多窓"]
    identifiers = sorted(item["id"] for item in methods)
    rules = dict(対象=identifiers, 一次反証SHA256=episode.digest(source),
                 主集計="ordersの新規かつ理由20（初回主玉）を対象とし、orders[:,1]の発注元行を使う。約定行の基礎へ付け替えない。追加・カバー等も全起源記録へ残す。",
                 基礎="窓と相手遅延の投票後、合成前の4基礎方向。各基礎の保持と撤回は含む。合成後の確認秒は元の最終信号から照合する。",
                 採用="単独ならその基礎、優先方式なら非中立の優先元またはF32、価格合意ならP02と同方向の板基礎、2基礎方式なら同方向の全基礎。反対抑止への利用は主採用と分ける。",
                 比較="同じ窓集合・合意率・確認秒でF32だけを使う方向を作り、全26入力の方向の完全一致/変更行数を測る。売買再生による部品除去の損益ではない。",
                 禁止="新規探索、パラメータ変更、候補の再選択、現在API取得。採用件数だけから損益への因果寄与を断定しない。")
    fixed_path = HERE / "basis_attribution_fixed.json"
    if fixed_path.exists():
        if json.loads(fixed_path.read_text(encoding="utf-8"))["規則"] != rules:
            raise ValueError("固定した基礎採用の診断対象と一致しません")
    else:
        fixed_path.write_text(json.dumps(dict(固定日時=datetime.now(episode.JST).isoformat(), 規則=rules), ensure_ascii=False, indent=2), encoding="utf-8")
    inputs = pickle.loads((episode.OLD / "inputs.pkl").read_bytes())
    features = pickle.loads((episode.OLD / "features_depth.pkl").read_bytes())
    signals = episode.load_module(HERE / "ensemble_signals.py", "basis_private_signals")
    loader = episode.load_module(episode.V25 / "d016_signal_audit.py", "basis_private_engine_loader")
    engine, managers = loader.load_engine()
    paths = [HERE / "ensemble_signals.py", episode.OLD / "engine.py"]
    before = {str(path): episode.digest(path) for path in paths}
    names = signals.BASE_NAMES
    primary = {"E037__D055": 0, "E015__D025": 1}
    methods.sort(key=lambda item: (primary.get(item["id"], 2), item["id"]))
    reports = []
    for method in methods:
        params = method["signal"]["params"]
        state = episode.directions(method, inputs, features, signals)
        basis = signals._basis(inputs, features, params)
        records, comparison = [], {}
        for key, ready in sorted(inputs.items()):
            own = basis[key]
            f32 = signals.COMPONENTS._asof(own["seq"], own["values"][0], ready["seq"]).astype(np.int8)
            f32[ready["time_s"] < ready["start"] + 1200] = 0
            f32[~np.isfinite(ready["atr"]) | (ready["atr"] <= 0)] = 0
            f32 = signals._confirm(f32, ready["time_s"], params["confirmation_seconds"])
            comparison["|".join(key)] = dict(原本行数=len(f32), F32単独と異なる行数=int(np.count_nonzero(f32 != state[key])),
                                            F32単独が非中立だが元は中立=int(np.count_nonzero((f32 != 0) & (state[key] == 0))),
                                            F32単独が中立だが元は非中立=int(np.count_nonzero((f32 == 0) & (state[key] != 0))))
            config = managers.make_config(method["manager"], key[1], ready)
            result = engine.run(ready, state[key], config)
            for order in result["orders"]:
                if order[7] != 1:
                    continue
                origin, fill, side = int(order[1]), int(order[0]), int(order[3])
                index = int(np.searchsorted(own["seq"], ready["seq"][origin], side="right") - 1)
                assert index >= 0 and origin < fill
                values = own["values"][:, index]
                selected = selected_basis(values, params["mode"])
                if int(order[6]) == 20:
                    assert state[key][origin] == side
                    assert selected and all(values[names.index(name)] == side for name in selected)
                records.append(dict(session=key[0], symbol=key[1], 発注元時刻=episode.stamp(ready["time_s"][origin]),
                                    発注元行=origin, 発注元seq=int(ready["seq"][origin]), 約定時刻=episode.stamp(ready["time_s"][fill]),
                                    約定行=fill, 約定seq=int(ready["seq"][fill]), direction=side, 枚数=int(order[4]),
                                    理由番号=int(order[6]), 発注元最終信号=int(state[key][origin]),
                                    基礎方向={name: int(values[i]) for i, name in enumerate(names)}, 主採用元=selected))
        total = tally(records)
        changed = sum(item["F32単独と異なる行数"] for item in comparison.values())
        result = dict(id=method["id"], mode=params["mode"], 全体=total,
                      銘柄別={symbol: tally([row for row in records if row["symbol"] == symbol]) for symbol in ("TOPIX", "NK225")},
                      全期間F32単独と方向一致=changed == 0, 全期間F32単独との差分行数=changed,
                      区間別F32比較=comparison, 全新規の発注起源=records)
        reports.append(result)
        print(json.dumps(dict(id=method["id"], 初回新規=total["初回主玉新規件数"], 主採用=total["主採用元件数"], F32単独方向完全一致=changed == 0), ensure_ascii=False), flush=True)
    assert before == {str(path): episode.digest(path) for path in paths}
    output = dict(固定仕様=rules, 結果=reports, 全初回新規で最終信号と採用基礎が一致=True,
                  凍結コード不変=True, 凍結コードSHA256=before, API取得数=0,
                  注意="発注元の採用件数は、退出・保有管理まで含めた損益への因果寄与を示さない。主採用がF32でも他基礎が反対時に抑止する場合は、信号全体がF32単独と同じとは限らない。")
    (HERE / "basis_attribution.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 合成方式は何を採用したか", "", "初回主玉の新規注文を決めた原本行で集計した。約定時の基礎方向へ付け替えていない。主採用と、反対方向の抑止に使うことを分ける。", "",
             "|候補|初回新規|F32採用|D016採用|D056採用|P02採用|F32単独と全方向一致|", "|---|---:|---:|---:|---:|---:|---|"]
    for row in reports:
        data = row["全体"]
        counts = data["主採用元件数"]
        lines.append(f"|{row['id']}|{data['初回主玉新規件数']}|{counts['F32']}|{counts['D016']}|{counts['D056']}|{counts['P02']}|{'一致' if row['全期間F32単独と方向一致'] else '相違あり'}|")
    lines += ["", "価格P02と板基礎の同意を採る場合は両方へ1件ずつ数えるため、採用件数の合計は初回新規件数を超え得る。JSONには各基礎が非中立だった件数、銘柄別件数、全新規の発注起源も残した。", "",
              output["注意"], "", "比較用F32単独は、各候補と同じ時間窓集合・同意率・連続確認幅を使う。旧F32_G08と同一という意味ではない。"]
    (HERE / "basis_attribution.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
