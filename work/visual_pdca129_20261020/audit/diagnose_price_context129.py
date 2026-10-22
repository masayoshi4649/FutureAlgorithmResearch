"""保存注文の価格源差と一時間資料の欠測を独立に分解する。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import features129


def read(path):
    """
    機能: 保存資料を読む。
    引数: path(Path)は読取位置。
    返り値: dict又はlistは保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    """
    機能: 保存源の内容指紋を求める。
    引数: path(Path)は読取位置。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value):
    """
    機能: 価格時計を日本時刻に変換する。
    引数: value(float)はUnix秒。
    返り値: strは日付を含む時刻。
    """
    return datetime.fromtimestamp(float(value), timezone(timedelta(hours=9))).isoformat()


def safe(value):
    """
    機能: 非有限値を保存可能な不明値へ変換する。
    引数: value(float)は観測。
    返り値: float又はNone。
    """
    return float(value) if np.isfinite(value) else None


def minute_samples(ready):
    """
    機能: 公開前の一分端点を独立に抽出し、一時間の内部欠測を調べる。
    引数: ready(dict)は選択した観測価格の原行。
    返り値: tuple[ndarray,ndarray]は区切り時刻と新鮮な過去価格。
    """
    times, prices = ready["time_s"], ready["last"]
    good = np.isfinite(prices) & (prices > 0.)
    gt, gp = times[good], prices[good]
    boundary = np.arange(ready["start"]+60., times[-1]+.001, 60.)
    values = np.full(len(boundary), np.nan)
    for j, end in enumerate(boundary):
        ix = np.searchsorted(gt, end, side="left")-1
        if ix >= 0 and end-gt[ix] <= 90.:
            values[j] = gp[ix]
    return boundary, values


def aggregates(rows):
    """
    機能: 保存親の固定分類を集計する。
    引数: rows(list[dict])は保存親の診断。
    返り値: dictは親数、勝敗と合計。
    """
    return dict(親数=len(rows), 黒字=sum(x["net"] > 0 for x in rows),
                赤字=sum(x["net"] < 0 for x in rows), 収支=sum(x["net"] for x in rows))


def main():
    """
    機能: 同じ入口の出口差と異なる入口経路を分離し、欠測による除外を数える。
    引数: なし。
    返り値: None。保存資料のみ会計・特徴再計算し、新金融再生はしない。
    """
    target = HERE/"価格源変更と一時間欠測の保存親独立診断.json"
    assert not target.exists()
    manifest = read(ROOT/"work/daynight128_20261020/入力準備.json")
    refs, cases, differences, contrasts = [], [], [], []
    snapshots = {}
    for ref in manifest["packets"]:
        scene = ref["session"]
        if not scene.endswith("_Night"):
            continue
        assert sha(ROOT/ref["path"]) == ref["sha256"]
        packet = pickle.loads((ROOT/ref["path"]).read_bytes())
        refs.append(ref)
        for method, kind in (("NV01", "last"), ("NV02", "mid")):
            inputs = features129.prices_for(packet, kind)
            contexts = features129.long_history(inputs)
            for symbol in ("TOPIX", "NK225"):
                key = scene, symbol
                ready, quote = inputs[key], packet["quotes"][key]
                z = np.load(WORK/"round1/measurement"/f"{symbol}_{scene}.npz")
                trades, orders = z[method+"__trades"], z[method+"__orders"]
                boundary, closes = minute_samples(ready)
                source_last = packet["inputs"][key]["last"]
                for j, tr in enumerate(trades):
                    enter, leave = orders[2*j:2*j+2]
                    i = int(enter[1])
                    t = ready["time_s"][i]
                    ix = np.searchsorted(boundary+60., t, side="right")-1
                    segment = closes[ix-60:ix+1] if ix >= 60 else np.array([])
                    missing = np.flatnonzero(~np.isfinite(segment))
                    endpoint = len(segment) == 61 and np.isfinite(segment[[0, -1]]).all()
                    delta = segment[-1]-segment[0] if endpoint else np.nan
                    row = dict(method=method, symbol=symbol, session=scene, parent=j,
                               decision_row=i, entry_row=int(tr[0]), exit_row=int(tr[1]),
                               decision_time=stamp(t), entry_time=stamp(ready["time_s"][int(tr[0])]),
                               exit_time=stamp(ready["time_s"][int(tr[1])]), side=int(tr[2]),
                               entry=tr[4], exit=tr[5], net=tr[8], mfe=tr[9], mae=tr[10],
                               width=tr[11], exit_reason=int(tr[12]),
                               last=safe(source_last[i]), bid=safe(quote["bid"][i]), ask=safe(quote["ask"][i]),
                               self60=safe(contexts[key][i, 0]), peer60=safe(contexts[key][i, 3]),
                               context=[safe(x) for x in contexts[key][i]],
                               endpoints_known=bool(endpoint), endpoints_delta=safe(delta),
                               missing_minutes=[stamp(boundary[ix-60+int(x)]) for x in missing] if len(segment) else [],
                               window_start=stamp(boundary[ix-60]) if ix >= 60 else None,
                               window_end=stamp(boundary[ix]) if ix >= 0 else None)
                    cases.append(row)
                if scene in ("2026-10-16_Night", "2026-10-02_Night", "2026-10-01_Night"):
                    snapshots[method, symbol, scene] = dict(trades=trades, orders=orders)
        # ----------------------------------------
        # 同一原行の新規が共通なら出口差を独立分類し、経路全体の差と混同しない。
        for symbol in ("TOPIX", "NK225"):
            groups = {method: [x for x in cases if x["session"] == scene and x["symbol"] == symbol
                               and x["method"] == method] for method in ("NV01", "NV02")}
            maps = {method: {(x["entry_row"], x["side"]): x for x in group} for method, group in groups.items()}
            common = maps["NV01"].keys() & maps["NV02"].keys()
            old_only = [x for k, x in maps["NV01"].items() if k not in common]
            new_only = [x for k, x in maps["NV02"].items() if k not in common]
            shared_delta = sum(maps["NV02"][k]["net"]-maps["NV01"][k]["net"] for k in common)
            old_net, new_net = (sum(x["net"] for x in groups[m]) for m in ("NV01", "NV02"))
            assert np.isclose(new_net-old_net, shared_delta+sum(x["net"] for x in new_only)-sum(x["net"] for x in old_only))
            differences.append(dict(session=scene, symbol=symbol, old_net=old_net, new_net=new_net,
                                    delta=new_net-old_net, same_entry_count=len(common),
                                    same_entry_exit_delta=shared_delta,
                                    old_different=aggregates(old_only), new_different=aggregates(new_only)))
            for k in common:
                a, b = maps["NV01"][k], maps["NV02"][k]
                if a["exit_row"] != b["exit_row"]:
                    contrasts.append(dict(old=a, new=b, delta=b["net"]-a["net"]))
        # ----------------------------------------
        # 10月16日夜間の早い短期利確が、その後の下落参加を変えた実際の気配を確認。
        if scene == "2026-10-16_Night":
            key = scene, "TOPIX"
            ready, quote = packet["inputs"][key], packet["quotes"][key]
            old = snapshots["NV01", "TOPIX", scene]["trades"][1]
            new = snapshots["NV02", "TOPIX", scene]["trades"][1]
            good = quote["quote_valid"] & np.isfinite(quote["ask"]) & (quote["bid"] < quote["ask"])
            limits = {}
            for label, tr in (("old", old), ("new", new)):
                start, end = int(tr[0]), int(new[1])
                indices = np.arange(start, end+1)
                indices = indices[good[indices]]
                move = tr[2]*(quote["ask"][indices]-tr[4])
                peak = float(max(0., np.max(move)))
                floor = peak-.75*tr[11] if peak >= tr[11] else -tr[11]
                limits[label] = dict(entry=tr[4], width=tr[11], mfe_before_new_exit=peak,
                                     protection_activated=peak>=tr[11], floor_points=floor,
                                     movement_at_new_exit=tr[2]*(quote["ask"][int(new[1])]-tr[4]))
            new_exit_path = dict(session=scene, symbol="TOPIX", new_exit=stamp(ready["time_s"][int(new[1])]),
                                 ask=quote["ask"][int(new[1])], tracks=limits)
    # ----------------------------------------
    # 未知と逆方向を分ける。これは旧注文固定の分類であり新収支ではない。
    groups = []
    for method in ("NV01", "NV02"):
        for symbol in ("TOPIX", "NK225"):
            selected = [x for x in cases if x["method"] == method and x["symbol"] == symbol]
            unknown = [x for x in selected if x["self60"] is None]
            internal = [x for x in unknown if x["endpoints_known"] and x["missing_minutes"]]
            opposed = [x for x in selected if x["self60"] is not None and x["side"]*x["self60"] < 0.]
            groups.append(dict(method=method, symbol=symbol, all=aggregates(selected),
                               unknown=aggregates(unknown), internal_missing=aggregates(internal),
                               unknown_other=aggregates([x for x in unknown if x not in internal]),
                               opposed=aggregates(opposed)))
    oct1 = read(WORK/"round2/全条件の会計.json")
    z1 = np.load(WORK/"round1/measurement"/"NK225_2026-10-01_Night.npz")
    z2 = np.load(WORK/"round2/measurement"/"NK225_2026-10-01_Night.npz")
    a, b = z1["NV02__trades"], z2["NV07__trades"]
    assert np.array_equal(a[[0, 1, 2, 4]], b)
    assert np.array_equal(np.delete(z1["NV02__orders"], [6, 7], axis=0)[:, [0, 1, 3, 4, 5, 6, 7]],
                          z2["NV07__orders"][:, [0, 1, 3, 4, 5, 6, 7]])
    result = dict(passed=True, financial_replays=0, API=0, script_sha256=sha(Path(__file__)),
                  feature_sha256=sha(WORK/"features129.py"), input_refs=refs,
                  context_groups=groups, cases=cases, price_source_differences=differences,
                  same_entry_exit_changes=contrasts, early_trail_example=new_exit_path,
                  oct1_nk_context=dict(sole_removed_net=float(a[3, 8]), other_four_trades_identical=True,
                                      old_net=float(a[:, 8].sum()), new_net=float(b[:, 8].sum())),
                  limitation="全て既知資料の保存注文分類。除外群の損益を引くだけで新戦略収支とはしない。")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False,
                                default=lambda value: value.item()), encoding="utf-8")
    print(json.dumps(dict(groups=groups, same_entry_exit_changes=len(contrasts),
                          early_trail=new_exit_path), ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
