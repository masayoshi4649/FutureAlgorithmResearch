"""保存夜間親の順行接触と残存単価幅を分類する。注文は生成しない。"""

import hashlib
import json
from pathlib import Path
import pickle
from datetime import datetime, timedelta, timezone

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
OLD = ROOT/"work/daynight128_20261020"
JST = timezone(timedelta(hours=9))
READS = []


def read_json(path: Path) -> dict:
    """
    機能: JSONを読み、入力指紋を記録する。
    引数: path(Path)は保存位置。
    返り値: dictは保存済み内容。
    """
    raw = path.read_bytes()
    READS.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(raw).hexdigest()))
    return json.loads(raw)


def verified(ref: dict) -> Path:
    """
    機能: 既存指紋付き参照の一致を確認する。
    引数: ref(dict)はpathとsha256。
    返り値: Pathは照合した保存位置。
    """
    path = ROOT/ref["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"]
    READS.append(ref)
    return path


def clock(t: float) -> str:
    """
    機能: 保存価格時計を日本時間で表示する。
    引数: t(float)はUTC秒。
    返り値: strは日付と時分秒。
    """
    return datetime.fromtimestamp(float(t), JST).strftime("%Y-%m-%d %H:%M:%S")


def clean(value):
    """
    機能: 非有限値とNumPy型をJSON保存用に変換する。
    引数: value(object)は分類値。
    返り値: objectは通常型の値。
    """
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def quantiles(values: list) -> dict:
    """
    機能: 単価幅の主要範囲と端をまとめる。
    引数: values(list[float])は分類済みの幅。
    返り値: dictは最小・25%・中央値・75%・最大。
    """
    if not values:
        return {}
    points = np.quantile(values, [0., .25, .5, .75, 1.])
    return dict(zip(("minimum", "p25", "median", "p75", "maximum"), map(float, points)))


def classify(scene: str, symbol: str, method: str, packet: dict,
             orders: np.ndarray, trades: np.ndarray) -> list:
    """
    機能: 各保存親の0.5R/1R接触と、旧出口までの単価経路を分類する。
    引数: scene/symbol/method(str)、packet(dict)、orders/trades(ndarray)は保存資料。
    返り値: list[dict]は親・閾値別の接触/残存幅。追加注文・改修収支は生成しない。
    """
    ready = packet["inputs"][scene, symbol]
    q = packet["quotes"][scene, symbol]
    times = ready["time_s"]
    good = q["quote_valid"] & np.isfinite(q["bid"]) & np.isfinite(q["ask"])
    good &= (q["bid"] > 0.) & (q["ask"] > q["bid"])
    rows = []
    for cid, trade in enumerate(trades):
        own = orders[orders[:, 2] == cid]
        entries, exits = own[own[:, 7] == 1], own[own[:, 7] == 0]
        assert len(entries) == len(exits) == 1
        entering, exiting = entries[0], exits[0]
        first, last = int(trade[0]), int(trade[1])
        decision_end = int(exiting[1])
        side, qty, price, exit_price = int(trade[2]), int(trade[3]), trade[4], trade[5]
        width = trade[11]
        assert qty == (5 if symbol == "TOPIX" else 10) and width > 0.
        assert entering[0] == first and exiting[0] == last
        mark = q["bid"] if side > 0 else q["ask"]
        entry_quote = q["ask"] if side > 0 else q["bid"]
        eligible = np.flatnonzero(good[first:last+1])+first
        gains = side*(mark[eligible]-price)
        assert np.isclose(max(0., gains.max()), trade[9])
        assert np.isclose(min(0., gains.min()), trade[10])
        for threshold in (.5, 1.):
            base = dict(method=method, session=scene, symbol=symbol, parent=cid, threshold_R=threshold,
                side=side, quantity=qty, proposed_initial=2 if symbol == "TOPIX" else 4,
                proposed_additional=3 if symbol == "TOPIX" else 6,
                entry_time=clock(times[first]), exit_time=clock(times[last]),
                exit_decision_time=clock(times[decision_end]),
                original_entry_price=float(price), original_exit_price=float(exit_price),
                R_width=float(width), original_gross=float(trade[6]), original_fees=float(trade[7]),
                original_net=float(trade[8]), old_winner=bool(trade[8] > 0.),
                old_loser=bool(trade[8] < 0.), old_exit_reason=int(trade[12]),
                original_end_width=float(side*(exit_price-price)),
                original_end_R=float(side*(exit_price-price)/width),
                maximum_R=float(trade[9]/width), minimum_R=float(trade[10]/width),
                touched=False, usable_next_quote=False)
            contacts = eligible[(eligible > first) & (gains >= threshold*width)]
            if len(contacts):
                row = int(contacts[0])
                base.update(touched=True, contact_row=row, contact_time=clock(times[row]),
                    contact_before_old_exit_decision=bool(row < decision_end),
                    contact_gain_R=float(side*(mark[row]-price)/width),
                    contact_spread=float(q["ask"][row]-q["bid"][row]),
                    contact_spread_R=float((q["ask"][row]-q["bid"][row])/width),
                    seconds_from_entry=float(times[row]-times[first]),
                    remaining_seconds_to_old_exit=float(times[last]-times[row]),
                    remaining_from_contact_liquidation=float(side*(exit_price-mark[row])),
                    remaining_from_contact_R=float(side*(exit_price-mark[row])/width),
                    after_contact_minimum_from_contact=float(np.min(side*(mark[eligible[eligible >= row]]-mark[row]))),
                    after_contact_minimum_R=float(np.min(side*(mark[eligible[eligible >= row]]-mark[row]))/width))
                nexts = eligible[eligible > row]
                # 旧返済の判断後なら追加予約不可。同じ行の接触値では追加取得しない。
                if row < decision_end and len(nexts) and nexts[0] <= decision_end:
                    additional_row = int(nexts[0])
                    additional_price = entry_quote[additional_row]
                    remainder = eligible[eligible >= additional_row]
                    residual = side*(exit_price-additional_price)
                    after = side*(mark[remainder]-additional_price)
                    # 4割先行・6割追加を同じ旧出口へ置いた幾何的な損益符号のみ。
                    # 費用、状態変化、再判定を運転していないため、改修収支として集計しない。
                    fixed_exit_weighted_width = .4*side*(exit_price-price)+.6*residual
                    base.update(usable_next_quote=True, next_quote_row=additional_row,
                        next_quote_time=clock(times[additional_row]), next_entry_quote=float(additional_price),
                        next_quote_spread=float(q["ask"][additional_row]-q["bid"][additional_row]),
                        next_quote_spread_R=float((q["ask"][additional_row]-q["bid"][additional_row])/width),
                        next_entry_vs_contact_liquidation=float(side*(additional_price-mark[row])),
                        next_entry_vs_contact_R=float(side*(additional_price-mark[row])/width),
                        remaining_from_next_entry=float(residual), remaining_from_next_entry_R=float(residual/width),
                        after_next_minimum=float(min(0., after.min())),
                        after_next_minimum_R=float(min(0., after.min())/width),
                        after_next_maximum=float(max(0., after.max())),
                        after_next_maximum_R=float(max(0., after.max())/width),
                        additional_unit_positive=bool(residual > 0.),
                        additional_unit_negative=bool(residual < 0.),
                        fixed_exit_four_six_gross_positive=bool(fixed_exit_weighted_width > 0.),
                        fixed_exit_four_six_gross_negative=bool(fixed_exit_weighted_width < 0.))
            rows.append(base)
    return rows


def main() -> None:
    """
    機能: N36/NV02全保存親を分類し、勝敗反例と単価範囲を保存する。
    引数: なし。
    返り値: None。JSONのみ保存し、金融再生・注文生成をしない。
    """
    manifest = read_json(OLD/"入力準備.json")
    refs = {r["session"]: r for r in manifest["packets"]}
    sources = (("N36", OLD/"round5/全条件の会計.json"), ("NV02", TASK/"round1/全条件の会計.json"))
    rows, session_scope = [], {}
    for method, path in sources:
        measured = read_json(path)
        config = next(c for c in measured["configs"] if c["id"] == method)
        assert config["stop"] == 1.
        session_scope[method] = sorted({r["session"] for r in measured["rows"] if r["method"] == method})
        scene_loaded, packet = None, None
        for ref in measured["cache"]:
            scene, symbol = ref["session"], ref["symbol"]
            if not scene.endswith("_Night"):
                continue
            if scene != scene_loaded:
                packet = pickle.loads(verified(refs[scene]).read_bytes())
                scene_loaded = scene
            with np.load(verified(ref), allow_pickle=False) as stored:
                orders, trades = stored[method+"__orders"], stored[method+"__trades"]
            expected = next(r for r in measured["rows"] if
                            r["method"] == method and r["session"] == scene and r["symbol"] == symbol)
            assert np.isclose(trades[:, 8].sum(), expected["net"])
            rows.extend(classify(scene, symbol, method, packet, orders, trades))
    summaries = []
    for method, _ in sources:
        for symbol in ("TOPIX", "NK225"):
            for threshold in (.5, 1.):
                group = [r for r in rows if r["method"] == method and r["symbol"] == symbol and r["threshold_R"] == threshold]
                hit = [r for r in group if r["touched"]]
                usable = [r for r in group if r["usable_next_quote"]]
                hit_wins, hit_losses = [r for r in hit if r["old_winner"]], [r for r in hit if r["old_loser"]]
                harmed = [r for r in usable if r["old_winner"] and r["additional_unit_negative"]]
                flipped = [r for r in usable if r["old_winner"] and r["fixed_exit_four_six_gross_negative"]]
                summaries.append(dict(method=method, symbol=symbol, threshold_R=threshold, parents=len(group),
                    original_winners=sum(r["old_winner"] for r in group), original_losers=sum(r["old_loser"] for r in group),
                    touched_winners=len(hit_wins), touched_losers=len(hit_losses),
                    no_touch_winners=sum(r["old_winner"] and not r["touched"] for r in group),
                    no_touch_losers=sum(r["old_loser"] and not r["touched"] for r in group),
                    usable_contacts=len(usable), late_contacts=len(hit)-len(usable),
                    additional_positive=sum(r["additional_unit_positive"] for r in usable),
                    additional_negative=sum(r["additional_unit_negative"] for r in usable),
                    old_winner_additional_negative=len(harmed), old_winner_reference_gross_flip=len(flipped),
                    residual_width=quantiles([r["remaining_from_next_entry"] for r in usable]),
                    residual_R=quantiles([r["remaining_from_next_entry_R"] for r in usable]),
                    quote_spread_R=quantiles([r["next_quote_spread_R"] for r in usable]),
                    entry_cost_after_contact_R=quantiles([r["next_entry_vs_contact_R"] for r in usable]),
                    adverse_after_next_R=quantiles([r["after_next_minimum_R"] for r in usable]),
                    hit_loss_examples=sorted(hit_losses, key=lambda r: r["original_net"])[:3],
                    winner_additional_loss_examples=sorted(harmed, key=lambda r: r["remaining_from_next_entry_R"])[:3],
                    no_touch_win_examples=sorted([r for r in group if r["old_winner"] and not r["touched"]],
                                                key=lambda r: -r["original_net"])[:3]))
    output = dict(passed=True, summaries=summaries, rows=rows, session_scope=session_scope, reads=READS,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0, original_book_reads=0, API=0,
        scope="既存親の単価経路分類。正常BBOによる初回返済可能幅が0.5/1Rへ達した最初の行を確認。",
        limitation="旧入口・出口を固定した観測。新数量の注文・返済・手数料・状態を運転していない。参考符号は損益実績ではない。")
    target = HERE/"夜間の順行後追加に残る単価幅.json"
    target.write_text(json.dumps(clean(output), ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(path=str(target), parent_threshold_rows=len(rows),
        summaries=[{k: v for k, v in s.items() if not isinstance(v, (list, dict))} for s in summaries]), ensure_ascii=True))


if __name__ == "__main__":
    main()
