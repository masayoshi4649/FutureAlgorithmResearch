"""DV01が撤退した当時条件の持続を分類する。新しい注文・損益は生成しない。"""

from io import BytesIO
import json
from pathlib import Path
import pickle
import hashlib

import numpy as np

import render_day129 as source


def blocks(times: np.ndarray, mask: np.ndarray, left: int, right: int) -> list:
    """
    機能: 当行の成立だけを読み、解除・未知・15秒超の時計空白で連続を切る。
    引数: times(ndarray)、mask(ndarray)、left/right(int)は分類区間。
    返り値: list[dict]は区間内の連続成立区間と60/120秒の最初の観測行。
    """
    output = []
    start = -1
    first60 = -1
    first120 = -1
    for i in range(left, right+1):
        broken = not mask[i] or (i > left and times[i]-times[i-1] > 15.)
        if broken and start >= 0:
            output.append(dict(start=start, end=i-1, seconds=float(times[i-1]-times[start]),
                               first60=first60, first120=first120))
            start = -1
            first60 = -1
            first120 = -1
        if not mask[i]:
            continue
        if start < 0:
            start = i
        duration = times[i]-times[start]
        if duration >= 60. and first60 < 0:
            first60 = i
        if duration >= 120. and first120 < 0:
            first120 = i
    if start >= 0:
        output.append(dict(start=start, end=right, seconds=float(times[right]-times[start]),
                           first60=first60, first120=first120))
    return output


def main() -> None:
    """
    機能: DV01の全75撤退について、元D17勝敗と成立持続を対応する。
    引数: なし。
    返り値: None。条件分布JSONを保存する。約定・手法損益の再計算はしない。
    """
    baseline = source.read_json(source.OLD/"round3/全条件の会計.json")
    measured = source.read_json(source.HERE.parent/"day_round1/全条件の会計.json")
    diagnosis = source.read_json(source.HERE/"日中第一巡の影別増減と残存損失.json")
    manifest = source.read_json(source.OLD/"入力準備.json")
    refs = {r["session"]: r for r in manifest["packets"]}
    old_refs = {(r["session"], r["symbol"]): r for r in baseline["cache"]}
    rows = []
    for ref in measured["cache"]:
        scene, symbol = ref["session"], ref["symbol"]
        with np.load(BytesIO(source.read_fixed(ref)), allow_pickle=False) as stored:
            orders = stored["DV01__orders"]
            mapping = stored["DV01__parent_mapping"]
        failures = orders[(orders[:, 7] == 0.) & (orders[:, 6] == 75.)]
        if not len(failures):
            continue
        packet = pickle.loads(source.read_fixed(refs[scene]))
        ready, quote = packet["inputs"][scene, symbol], packet["quotes"][scene, symbol]
        times = ready["time_s"]
        market = packet["markets"][scene, symbol]
        with np.load(BytesIO(source.read_fixed(refs[scene]["features"])), allow_pickle=False) as stored:
            history = stored[symbol+"__history"]
        with np.load(BytesIO(source.read_fixed(old_refs[scene, symbol])), allow_pickle=False) as stored:
            base_orders = stored["D17__orders"]
            base_cycles = stored["D17__cycles"]
        account = next(r for r in diagnosis["rows"] if
                       r["session"] == scene and r["symbol"] == symbol and r["method"] == "DV01")
        for failure in failures:
            cid = int(failure[2])
            shadow = int(mapping[mapping[:, 0] == cid][0, 1])
            base = base_cycles[base_cycles[:, 0] == shadow][0]
            initial = base_orders[(base_orders[:, 2] == shadow) & (base_orders[:, 7] == 1)][0]
            first, decision, last, side = int(initial[0]), int(failure[1]), int(base[2]), int(initial[3])
            anchor = market[first]
            known = (market[:, 11] == 1.) & np.isfinite(market[:, :2]).all(axis=1)
            good = quote["quote_valid"] & np.isfinite(quote["bid"]) & np.isfinite(quote["ask"])
            good &= (quote["bid"] > 0.) & (quote["ask"] > quote["bid"])
            fresh = (np.arange(len(times)) > first) & (market[:, 8] > anchor[8])
            own = side*(market[:, 0]-anchor[0])/base[5]
            peer = side*(market[:, 1]-anchor[1])/anchor[3]
            mask = known & good & fresh & (own <= -.25) & (peer <= -.25)
            assert mask[decision]
            sequence = blocks(times, mask, decision, last)
            assert sequence and sequence[0]["start"] == decision
            parent = next(r for r in account["parents"] if r["shadow_parent"] == shadow)
            info = dict(session=scene, symbol=symbol, shadow_parent=shadow,
                side=side, entry=source.clock(times[first]), first_trigger=source.clock(times[decision]),
                old_exit=source.clock(times[last]), old_net=parent["old_net"],
                dv01_net=parent["new_net"], old_winner=parent["old_net"] > 0,
                first_episode_seconds=sequence[0]["seconds"],
                longest_episode_seconds=max(b["seconds"] for b in sequence),
                trigger_own20_signed=float(side*history[decision, 7]),
                trigger_peer20_signed=float(side*history[decision, 11]),
                trigger_own_vs_mean20=float(side*(market[decision, 0]-history[decision, 1])),
                trigger_mean5_vs20=float(side*(history[decision, 0]-history[decision, 1])),
                episodes=sequence)
            for threshold in (60, 120):
                indices = [b["first"+str(threshold)] for b in sequence if b["first"+str(threshold)] >= 0]
                info["ever"+str(threshold)] = bool(indices)
                info["first"+str(threshold)+"_time"] = source.clock(times[indices[0]]) if indices else None
            rows.append(info)
    summary = []
    for symbol in ("TOPIX", "NK225"):
        for winner in (True, False):
            subset = [r for r in rows if r["symbol"] == symbol and r["old_winner"] == winner]
            summary.append(dict(symbol=symbol, old_winner=winner, count=len(subset),
                first60=sum(r["first_episode_seconds"] >= 60. for r in subset),
                first120=sum(r["first_episode_seconds"] >= 120. for r in subset),
                ever60=sum(r["ever60"] for r in subset), ever120=sum(r["ever120"] for r in subset),
                original_net=sum(r["old_net"] for r in subset), dv01_net=sum(r["dv01_net"] for r in subset),
                first_seconds=[r["first_episode_seconds"] for r in subset]))
    output = dict(passed=True, summary=summary, rows=source.clean(rows), reads=source.READS,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0,
        scope="DV01の実75撤退を元D17保有終了まで分類。未知/条件解除/原価格時計gap>15秒でreset。",
        limitation="既存損切り優先や再参加後は模擬しない。60/120秒分類はその条件が現れるかであり、手法の損益ではない。")
    path = source.HERE/"両市場0.25逆行の持続分類.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(path=str(path), summary=summary, count=len(rows)), ensure_ascii=True))


if __name__ == "__main__":
    main()
