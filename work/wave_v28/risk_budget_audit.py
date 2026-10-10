"""損失予算が厳密上限かを、保存データを読まず合成価格だけで反証する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "wave_v23"
sys.path.insert(0, str(OLD))
import managers
sys.path.insert(0, str(HERE))
import engine_context

ASSETS = {"TOPIX": dict(cap=10, quantity=5, tick=.5, point_value=1000.),
          "NK225": dict(cap=20, quantity=10, tick=5., point_value=10.)}


def digest(path: Path) -> str:
    """機能: 監査したエンジンの不変性を確認する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> dict:
    """機能: 合成反例の経路・検査範囲を再生前に固定する。

    引数: なし。返り値: 固定仕様 (dict)。
    """
    rules = dict(入力="合成だけ。保存済み相場・現在スナップショット・新成績は読まない。",
                 基本="呼値単位の価格1000、ATR4呼値、初期枚数TOPIX5/NK10、上限10/20。指定価格約定・費用0。",
                 ケース=["小刻みな下落で既設ストップ", "大幅ギャップで既設ストップ", "新規直後の方向撤回とギャップ", "呼値丸めで1R超過", "予算到達から次行まで小刻み", "予算到達から次行までギャップ", "部分利確後の価格逆指値", "部分利確後の方向撤回とギャップ"],
                 ギャップ系列=[10, 100, 1000, 10000, 100000],
                 判定="上限以内の数値保証を反証する。予算超過例を見つけても管理幅を最適化しない。",
                 不変="エンジン・管理設計・原本を変更せず、通常importを使う。")
    path = HERE / "risk_budget_audit_fixed.json"
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["規則"] == rules
        return saved
    value = dict(固定日時=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), 規則=rules)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return value


def make_case(symbol: str, prices: list[float], entry: list[int], context: list[int], changes: dict | None = None) -> tuple[dict, np.ndarray, np.ndarray, dict]:
    """機能: 呼値単位の合成価格と2方向列を、銘柄の倍率へ変換する。

    引数: symbol (str)、prices (list[float])、entry/context (list[int])、changes (dict|None)。
    返り値: 入力・入口・保有方向・設定 (tuple[dict,ndarray,ndarray,dict])。
    """
    asset = ASSETS[symbol]
    count = len(prices)
    assert len(entry) == len(context) == count
    data = dict(time_s=np.arange(count, dtype=float), seq=np.arange(count), last=np.asarray(prices, float) * asset["tick"],
                atr=np.full(count, 4 * asset["tick"]), tick=asset["tick"], start=0., limit=float(count - 2), us_open=1e9,
                session="合成監査", symbol=symbol)
    cfg = dict(managers.BASE, audit_cap=asset["cap"], point_value=asset["point_value"], initial_qty=asset["quantity"],
               entry_mode=2, entry_cutoff_min=0., warmup_min=0., cooldown_min=0., ttl_seconds=1000., stop_atr=1.,
               main_trail=1000., activation_atr=1000., timeout_min=1000.)
    cfg.update(changes or {})
    return data, np.asarray(entry, np.int8), np.asarray(context, np.int8), cfg


def execute_case(name: str, symbol: str, prices: list[float], entry: list[int], context: list[int], changes: dict | None = None) -> dict:
    """機能: 合成だけを再生して予算・超過額・決定行/約定行を記録する。

    引数: name/symbol (str)、prices (list[float])、entry/context (list[int])、changes (dict|None)。
    返り値: 合成反例の台帳と予算比 (dict)。実相場の収支比較は行わない。
    """
    data, state, held, cfg = make_case(symbol, prices, entry, context, changes)
    result = engine_context.run(data, state, cfg, detail=True, context=held)
    trades, orders, curve = result["trades"], result["orders"], result["curve"]
    multiplier = cfg["point_value"]
    risk = cfg["initial_qty"] * cfg["stop_atr"] * data["atr"][0] * multiplier
    budget = cfg["session_budget_r"] * risk if cfg["session_budget_r"] else None
    loss = float(-trades[:, 10].sum() * multiplier)
    assert result["stats"][9] == 0
    assert np.max(curve[:, 2]) <= cfg["audit_cap"] and np.max(curve[:, 3]) <= cfg["audit_cap"]
    assert np.all(orders[:, 0] > orders[:, 1])
    np.testing.assert_allclose(curve[:, 0], curve[:, 5] + curve[:, 6] * data["last"], atol=1e-6, rtol=0)
    np.testing.assert_allclose(trades[:, 10].sum(), result["stats"][0], atol=1e-6, rtol=0)
    records = [dict(約定行=int(row[0]), 決定元行=int(row[1]), 方向=int(row[3]), 枚数=int(row[4]), 指定又は約定価格=float(row[5]),
                    観測価格=float(data["last"][int(row[0])]), 理由番号=int(row[6]), 理由=engine_context.REASONS.get(int(row[6]), "通常新規"), 新規=bool(row[7])) for row in orders]
    trigger = None
    if budget is not None:
        reached = np.flatnonzero(curve[:, 0] * multiplier <= -budget + 1e-8)
        if len(reached):
            row = int(reached[0])
            trigger = dict(最初の予算到達行=row, その行の損失円=float(-curve[row, 0] * multiplier),
                           その行のネット枚数=float(curve[row, 6]), その行の価格=float(data["last"][row]))
    return dict(ケース=name, symbol=symbol, 合成価格は呼値単位=prices, entry=entry, context=context,
                初期枚数=cfg["initial_qty"], 片方向枚数上限=cfg["audit_cap"], 最大買い枚数=float(result["stats"][2]), 最大売り枚数=float(result["stats"][3]),
                初期1R円=risk, セッション予算円=budget, 最終損失円=loss, 初期1Rに対する最終損失比=loss / risk,
                予算超過円=max(0., loss - budget) if budget is not None else None,
                セッション予算に対する最終損失比=loss / budget if budget else None,
                予算到達=trigger, 約定=records, 最終残枚数=float(result["stats"][9]))


def base_cases(symbol: str) -> list[dict]:
    """機能: 通常ストップと市場返済の違いを同じ固定経路で検査する。

    引数: symbol (str)。返り値: 8種の合成結果 (list[dict])。
    """
    output = []
    prices = [1000, 1000, 999, 998, 997, 996, 996, 996]
    output.append(execute_case("小刻み・既設ストップ", symbol, prices, [1] + [0] * 7, [1] * 8))
    prices = [1000, 1000, 500, 500, 500]
    output.append(execute_case("大幅ギャップ・既設ストップ", symbol, prices, [1, 0, 0, 0, 0], [1] * 5))
    output.append(execute_case("新規直後の撤回・大幅ギャップ", symbol, prices, [1, 0, 0, 0, 0], [1, -1, -1, -1, -1], {"signal_exit": 1}))
    prices = [1000, 1000, 999, 998, 998, 998]
    data, state, held, cfg = make_case(symbol, prices, [1] + [0] * 5, [1] * 6, {"stop_atr": .375})
    # 4呼値×0.375=1.5呼値。丸めだけを孤立させる固定反例。
    output.append(execute_case("呼値丸め・理論1R超過", symbol, prices, state.tolist(), held.tolist(), {"stop_atr": .375}))
    # 実現2.5R損失の後、残り0.5Rの予算を次の玉が越える。最後だけ価格差を変える。
    for finish, label in ((986, "予算到達後・小刻みな次行"), (900, "予算到達後・大幅ギャップ")):
        prices = [1000, 1000, 996, 996, 992, 992, 990, 990, 987, finish, finish, finish]
        context = [1] * 12; context[5] = -1
        output.append(execute_case(label, symbol, prices, [1] * 8 + [0] * 4, context, {"signal_exit": 1, "session_budget_r": 3.}))
    prices = [1000, 1000, 1004, 1004, 990, 980, 980, 980]
    output.append(execute_case("部分利確後・価格逆指値", symbol, prices, [1] + [0] * 7, [1] * 8, {"split_target": 1.}))
    prices = [1000, 1000, 1004, 500, 500, 500]
    output.append(execute_case("部分利確後・撤回とギャップ", symbol, prices, [1] + [0] * 5, [1, 1, -1, -1, -1, -1], {"split_target": 1., "signal_exit": 1}))
    assert abs(output[0]["初期1Rに対する最終損失比"] - 1.) < 1e-8
    assert abs(output[1]["初期1Rに対する最終損失比"] - 1.) < 1e-8
    assert output[2]["初期1Rに対する最終損失比"] > 100
    assert abs(output[3]["初期1Rに対する最終損失比"] - 4 / 3) < 1e-8
    assert output[4]["予算超過円"] > 0 and output[5]["予算超過円"] > output[4]["予算超過円"]
    assert any(row["理由番号"] == 14 for row in output[4]["約定"])
    assert any(row["理由番号"] == 14 for row in output[5]["約定"])
    assert output[7]["初期1Rに対する最終損失比"] > 50
    return output


def unbounded_short_cases(symbol: str) -> list[dict]:
    """機能: 売り保有の次行市場返済に有限なR上限がないことを拡大反例で示す。

    引数: symbol (str)。返り値: 同じ枚数・ATR・予算でギャップだけ増やした結果 (list[dict])。
    """
    output = []
    for gap in (10, 100, 1000, 10000, 100000):
        prices = [1000, 1000, 1000 + gap, 1000 + gap, 1000 + gap]
        row = execute_case(f"売り新規直後の撤回・逆行{gap}呼値", symbol, prices, [-1, 0, 0, 0, 0], [-1, 1, 1, 1, 1], {"signal_exit": 1, "session_budget_r": 3.})
        assert abs(row["初期1Rに対する最終損失比"] - gap / 4) < 1e-8
        output.append(row)
    return output


def main() -> None:
    """機能: 合成反例のみから厳密上限の有無を検査し正確な説明文を保存する。

    引数: なし。返り値: なし (None)。実相場・新探索ランキングを参照しない。
    """
    freeze()
    paths = [HERE / "engine_context.py", OLD / "engine.py", OLD / "managers.py"]
    hashes = {str(path): digest(path) for path in paths}
    cases = [row for symbol in ASSETS for row in base_cases(symbol)]
    gaps = [row for symbol in ASSETS for row in unbounded_short_cases(symbol)]
    assert hashes == {str(path): digest(path) for path in paths}
    wording = {
        "stop_atr": "初期ATRと枚数から売買組全体の損切り基準を計算する。通常の価格逆指値は指定価格で約定する仮定だが、呼値丸めや優先される次行成行返済により、最終損失がこの基準を超える場合がある。",
        "session_budget_r": "セッションの実現損益と含み損益の合計が、初回注文準備時に固定した予定損失の指定倍数へ達したら、新規を停止し、保有があれば次の原本行で全返済する。損失額そのものをその金額以内に保証する仕組みではない。",
        "枚数上限": "買い・売りそれぞれの保有枚数上限は厳守する。枚数を制限しても、次の観測までの価格変化が無制限なら円損失に同じ厳密上限は付かない。",
        "部分利確": "部分利確後も元の売買組予算を使う。利確済み利益と残玉を合算するため、残玉1枚あたりの許容逆行幅は広がり得る。"
    }
    report = dict(全て合成=True, 相場データ読取数=0, API取得数=0, 新成績ランキング読取=False,
                  判定="stop_atr/session_budget_rは損切り水準または停止返済の始動基準であり、あらゆる観測経路に対する最終損失額の保証ではない。",
                  全ケース数=len(cases) + len(gaps), 固定反例=cases, ギャップ拡大反例=gaps,
                  正確な説明文=wording,
                  構造理由=["通常の価格逆指値は飛び越しても指定価格で返済する仮定。ギャップだから必ずストップ損失が拡大する、とも言えない。",
                            "前行で予約した市場返済は、その行の既設価格ストップを照合する前に処理される。方向撤回/時間/場末/予算返済では次行価格を使う。",
                            "1原本行につき1種類の管理イベントを処理する。全返済イベントでは複数の建玉約定を同じ行で記録し得るため、厳密には1約定だけではない。",
                            "注文水準を新たに作った時点ですでに通過している場合は、過去の指定価格へ遡らず次行の観測価格で返済する。",
                            "買いの損切り価格は下側、売りは上側の呼値へ丸める。通常価格ストップだけでも理論予算に最大で残ネット枚数×1呼値未満の超過があり得る。",
                            "予算到達を観測した行の損失が予算額を超える場合があり、次行返済までにさらに逆行し得る。"],
                  理論限界=["予算到達後の返済価格差による追加損失は、概ね -ネット保有枚数×(次行価格-到達行価格)×円倍率。観測価格差の上限を仮定しなければ有限のR上限は導けない。",
                            "空売り後の上方向ギャップを任意に増やせば、同じ枚数・ATR・3R設定のまま損失/Rを任意に増やせる。コードは値幅制限・清算制度の価格上限をモデル化していない。",
                            "正価格を仮定する買いでは建値からゼロまでという単一玉の数学的制約はあるが、設定したstop_atrや3R以内という保証ではない。"],
                  原コード不変=True, SHA256=hashes)
    (HERE / "risk_budget_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 損失予算は金額上限の保証か", "", "**保証ではない。stop_atrは損切り基準、session_budget_rは新規停止と返済を始動する基準。枚数上限10/20とは性質が異なる。**", "",
             "保存データ・現在データ・新しい成績を読まず、26個の合成反例で確認した。円額は銘柄ごとに異なるため、以下は各ケースの初期予定損失1Rに対する倍率で示す。", "",
             "| 合成経路 | TOPIX・損失/R | NK225・損失/R |", "|---|---:|---:|"]
    names = list(dict.fromkeys(row["ケース"] for row in cases))
    for name in names:
        rows = {row["symbol"]: row for row in cases if row["ケース"] == name}
        lines.append(f"|{name}|{rows['TOPIX']['初期1Rに対する最終損失比']:.3f}|{rows['NK225']['初期1Rに対する最終損失比']:.3f}|")
    lines += ["", "予算到達後の2ケースはセッション予算3R。小刻みな経路でも3Rを超え、次行のギャップでさらに拡大した。", "",
              "通常の既設逆指値は、指定価格約定という仮定により大幅ギャップでも1Rで閉じる。一方、先に予約された方向撤回・予算などの市場返済は価格ストップより先に処理され、次行価格で閉じる。この違いを無視して『常に超過する』『常に守られる』のどちらとも説明できない。", "",
              "売りの新規直後に撤回を決定し、次行が逆行する例では、10/100/1,000/10,000/100,000呼値のギャップに対し、損失は2.5/25/250/2,500/25,000R。枚数とATRと3R予算を変えずに拡大できた。観測価格差の上限がモデルにないため、有限の円損失上限も保証できない。", "",
              "## 報告に使う文言", ""]
    lines += [f"- **{key}**：{value}" for key, value in wording.items()]
    lines += ["", "1原本行に1種類の管理イベントを処理する仕様であり、全返済では複数建玉を同時に返せる。新しく作った条件が既に通過済みなら、過去価格へ遡らず次行へ送る。これらは因果性を守る一方、金額上限を保証するものではない。",
              "", "実行コードと原本は変更していない。これは執行モデルの限界の監査であり、実相場の収益性評価ではない。"]
    (HERE / "risk_budget_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(dict(合成ケース数=report["全ケース数"], 判定=report["判定"], 原コード不変=True), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
