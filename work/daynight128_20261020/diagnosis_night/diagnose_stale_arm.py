"""保存した夜間注文について、準備時の中期根拠が発注時にも残ったかを診断する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
from numba import njit

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
JST = timezone(timedelta(hours=9))
METHODS = (("N16", "round2", 1.e9), ("N27", "round3", 1.5), ("N24", "round3", 1.e9))


@njit(cache=False)
def trace(times, price, atr, history, market, bid, ask, qok, allowed, tick, expected, maximum):
    """
    機能: 保存注文で取引不能区間を固定し、入口準備だけを再構成する。
    引数: 原行列・履歴・allowed・expected(ndarray)、tick/maximum(float)。
    返り値: ndarrayは判断行・準備行・固定境界・固定幅。売買や資金を再計算しない。
    """
    out = np.zeros((len(expected), 4))
    count = 0
    arm, began = 0, -1
    level, width = 0., 0.
    for i in range(len(times)):
        if not allowed[i]:
            continue
        known = np.isfinite(price[i]) and np.isfinite(atr[i]) and atr[i] > 0.
        known = known and np.isfinite(history[i, :]).all() and market[i, 11] == 1.
        known = known and np.isfinite(market[i, 4:8]).all()
        if not known:
            continue
        good = qok[i] and np.isfinite(bid[i]) and np.isfinite(ask[i]) and 0. < bid[i] < ask[i]
        if not good:
            continue
        w = max(atr[i], 4. * tick)
        quote_ok = ask[i] - bid[i] <= .25 * w and max(ask[i] - price[i], price[i] - bid[i]) <= .5 * w
        if arm and times[i] - times[began] > 1800.:
            arm = 0
        if not arm and quote_ok:
            if history[i, 5] >= .35:
                if price[i] > history[i, 3] and history[i, 10] > 0. and history[i, 11] > 0.:
                    arm, level = 1, history[i, 3]
                elif price[i] < history[i, 4] and history[i, 10] < 0. and history[i, 11] < 0.:
                    arm, level = -1, history[i, 4]
            if arm:
                width, began = w, i
        elif arm:
            if arm * (price[i] - level) < -.25 * width:
                arm = 0
            else:
                support = arm * market[i, 4] > 0. and arm * market[i, 6] > 0.
                trigger = times[i] - times[began] >= 60. and support and arm * (price[i] - level) >= .25 * width
                trigger = trigger and arm * market[i, 5] > .05 and arm * market[i, 7] > .05
                quote = ask[i] if arm > 0 else bid[i]
                trigger = trigger and arm * (quote - level) <= maximum * width
                if trigger and quote_ok:
                    assert count < len(expected) and expected[count] == i
                    out[count] = np.array([i, began, level, width])
                    count += 1
                    arm = 0
    assert count == len(expected)
    return out


def read(path: Path, sources: list) -> bytes:
    """
    機能: 保存入力を読み、参照元の指紋を残す。
    引数: path(Path)、sources(list)は入力と記録先。
    返り値: bytesは元の内容。
    """
    raw = path.read_bytes()
    sources.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(raw).hexdigest()))
    return raw


def stamp(value: float) -> str:
    """
    機能: 保存時計の時刻を日本時刻へ変換する。
    引数: value(float)はＵｎｉｘ秒。
    返り値: strは日本時刻。受信時刻とは同一視しない。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def observed(row: int, side: int, history: np.ndarray, market: np.ndarray) -> dict:
    """
    機能: 当行で既知の中期・短期根拠を売買方向に揃えて取り出す。
    引数: row/side(int)、history/market(ndarray)は行・方向・既知入力。
    返り値: dictは実測値。価格差は商品単位、短期差は当時ＡＴＲ単位。
    """
    h, m = history[row], market[row]
    return dict(own5=float(side*h[6]), own20=float(side*h[7]),
                peer5=float(side*h[10]), peer20=float(side*h[11]),
                efficiency20=float(h[5]),
                own30_atr=float(side*m[4]), own120_atr=float(side*m[5]),
                peer30_atr=float(side*m[6]), peer120_atr=float(side*m[7]))


def aggregate(rows: list) -> dict:
    """
    機能: 保存親の条件別成績を再集計する。
    引数: rows(list[dict])は診断した保存親。
    返り値: dictは件数・正負・収支。別条件の金融結果ではない。
    """
    return dict(trades=len(rows), wins=sum(r["net"] > 0. for r in rows),
                losses=sum(r["net"] < 0. for r in rows),
                profit=sum(r["net"] for r in rows if r["net"] > 0.),
                loss=-sum(r["net"] for r in rows if r["net"] < 0.),
                net=sum(r["net"] for r in rows),
                sessions=len({r["session"] for r in rows}))


def main() -> None:
    """
    機能: Ｎ１６・Ｎ２７・Ｎ２４の準備根拠の失効と、同時に除去される勝ちを保存する。
    引数: なし。
    返り値: None。金融再生・元市場読取・ＡＰＩ接続は零。
    """
    target = HERE / "第三巡の準備根拠失効と除去勝ちの診断.json"
    assert not target.exists()
    sources, rows, session_rows = [], [], []
    manifest = json.loads(read(TASK / "入力準備.json", sources))
    results = {folder: json.loads(read(TASK / folder / "全条件の会計.json", sources))
               for folder in ("round2", "round3")}
    lookup = {}
    for method, folder, maximum in METHODS:
        for row in results[folder]["rows"]:
            if row["method"] == method:
                session_rows.append(row)
                lookup[method, row["session"], row["symbol"]] = row
    for ref in manifest["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Night"):
            continue
        packet = pickle.loads(read(ROOT / ref["path"], sources))
        with np.load(ROOT / ref["features"]["path"], allow_pickle=False) as histories:
            for symbol in ("TOPIX", "NK225"):
                ready = packet["inputs"][scene, symbol]
                market = packet["markets"][scene, symbol]
                quotes = packet["quotes"][scene, symbol]
                history = histories[symbol + "__history"]
                times, prices = ready["time_s"], ready["last"]
                for method, folder, maximum in METHODS:
                    path = TASK / folder / "measurement" / (symbol + "_" + scene + ".npz")
                    with np.load(path, allow_pickle=False) as saved:
                        orders, trades = saved[method + "__orders"], saved[method + "__trades"]
                    entries = orders[orders[:, 7] == 1.]
                    expected = entries[:, 1].astype(np.int64)
                    allowed = (times >= ready["us_open"] + 1320.) & (times < ready["limit"])
                    for order, trade in zip(entries, trades):
                        next_ready = np.searchsorted(times, times[int(trade[1])] + 300., side="left")
                        allowed[int(order[1])+1:next_ready] = False
                    states = trace(times, prices, ready["atr"], history, market,
                                   quotes["bid"], quotes["ask"], quotes["quote_valid"],
                                   allowed, ready["tick"], expected, maximum)
                    assert len(entries) == len(trades) == len(states)
                    assert np.isclose(trades[:, 8].sum(), lookup[method, scene, symbol]["net"])
                    for order, trade, state in zip(entries, trades, states):
                        decision, arm = int(state[0]), int(state[1])
                        e, x, side, qty = map(int, trade[:4])
                        boundary, width = map(float, state[2:])
                        assert order[0] == e and decision < e and np.isclose(trade[11], width)
                        before = observed(arm, side, history, market)
                        now = observed(decision, side, history, market)
                        conf2 = all(now[k] > 0. for k in ("own5", "own20", "peer5", "peer20"))
                        arm_conf2 = all(before[k] > 0. for k in ("own5", "own20", "peer5", "peer20"))
                        # ----------------------------------------
                        # 準備中の境界外滞在は、原行の値を次行まで保持した保存時計の時間加重。
                        dt = np.diff(times[arm:decision+1])
                        outside = side * (prices[arm:decision] - boundary) > 0.
                        duration = float(times[decision] - times[arm])
                        boundary_fraction = float(dt[outside].sum()/duration) if duration else 0.
                        current_boundary = history[decision, 3 if side > 0 else 4]
                        row = dict(method=method, session=scene, symbol=symbol,
                            arm_row=arm, decision_row=decision, entry_row=e, exit_row=x,
                            arm_time=stamp(times[arm]), decision_time=stamp(times[decision]),
                            entry_time=stamp(times[e]), exit_time=stamp(times[x]),
                            side=side, direction="買い" if side > 0 else "売り", quantity=qty,
                            entry_price=float(trade[4]), exit_price=float(trade[5]),
                            gross=float(trade[6]), fee=float(trade[7]), net=float(trade[8]),
                            mfe_points=float(trade[9]), mae_points=float(trade[10]), width=width,
                            mfe_r=float(trade[9]/width), reason=int(trade[12]),
                            fixed_boundary=boundary, arm_wait_seconds=duration,
                            arm=before, decision=now,
                            conf2_rejected=not conf2,
                            conf2_was_good_then_lost=arm_conf2 and not conf2,
                            peer_support_lost=now["peer5"] <= 0. or now["peer20"] <= 0.,
                            own_support_missing=now["own5"] <= 0. or now["own20"] <= 0.,
                            efficiency_lost=now["efficiency20"] < .35,
                            peer_twenty_lost=now["peer20"] <= 0.,
                            own_twenty_missing=now["own20"] <= 0.,
                            arm_outside_seconds_fraction=boundary_fraction,
                            arm_max_inside_r=float(max(0., -np.min(side*(prices[arm:decision+1]-boundary))/width)),
                            latest_twenty_boundary=float(current_boundary),
                            beyond_latest_twenty_boundary=bool(side*(prices[decision]-current_boundary) > 0.))
                        rows.append(row)
        print(scene, "準備状態照合済み", flush=True)
    summary, worst = [], []
    flags = ("conf2_rejected", "conf2_was_good_then_lost", "peer_support_lost",
             "own_support_missing", "efficiency_lost", "peer_twenty_lost",
             "own_twenty_missing")
    for method, folder, maximum in METHODS:
        for symbol in ("TOPIX", "NK225"):
            part = [r for r in rows if r["method"] == method and r["symbol"] == symbol]
            groups = {flag: dict(rejected=aggregate([r for r in part if r[flag]]),
                                kept=aggregate([r for r in part if not r[flag]]))
                      for flag in flags}
            summary.append(dict(method=method, symbol=symbol, all=aggregate(part), groups=groups))
            ranked = sorted([r for r in session_rows if r["method"] == method and r["symbol"] == symbol],
                            key=lambda r: r["net"])[:3]
            for session in ranked:
                chosen = [r for r in part if r["session"] == session["session"]]
                worst.append(dict(**session, trades=sorted(chosen, key=lambda r: r["net"])))
    result = dict(passed=True, rows=rows, summary=summary, worst_three=worst,
        reconstruction="保存新規判断行から返済後５分までを準備不可に固定。空き区間だけの準備状態を復元し、全発火行と初期幅を保存注文へ完全照合。",
        limits=["条件に合わない既存親を抜いた分類であり、見送った後に新しい入口を探索した成績ではない。",
                "今後の共通入口変更は、同一出口の単独対照として別途固定・登録して検証する必要がある。",
                "境界外の時間割合は保存価格時計での時点保持。実受信時計や約定量の定着率ではない。",
                "準備時の相手５分・２０分条件の再確認と、自己５分・２０分条件の追加を区別する。",
                "すべて既知開発データ。未見成功の証拠とはしない。"],
        sources=sources, financial_replays=0, original_market_reads=0, API=0,
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
