"""新金融の保存結果を元影ごとに照合し、初回変化と再参加損益を分ける。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = HERE.parents[2]
OLD = ROOT / "work/daynight128_20261020"
JST = timezone(timedelta(hours=9))
READS = []


def read_json(path: Path) -> dict:
    """
    機能: 保存JSONを読み、指紋を診断証跡へ記録する。
    引数: path(Path)は参照位置。
    返り値: dictは保存内容。
    """
    data = path.read_bytes()
    READS.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(data).hexdigest()))
    return json.loads(data)


def verified(ref: dict) -> Path:
    """
    機能: 保存結果の指紋が元参照と一致することを確認する。
    引数: ref(dict)はpathとsha256。
    返り値: Pathは確認した絶対位置。
    """
    path = ROOT / ref["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"]
    READS.append(ref)
    return path


def clock(value: float) -> str:
    """
    機能: 元データ時計を日本時間へ変換する。
    引数: value(float)はUTC秒。
    返り値: strは時分秒。
    """
    return datetime.fromtimestamp(float(value), JST).strftime("%H:%M:%S")


def campaigns(data: dict, times: np.ndarray, symbol: str, new: bool) -> list:
    """
    機能: 保存注文・完成親を元影と参加回数に対応させる。
    引数: data(dict)は保存配列、times(ndarray)、symbol(str)、new(bool)は新核か。
    返り値: list[dict]は手数料後会計と各脚の時刻。
    """
    mult, rate = (1000., 418) if symbol == "TOPIX" else (10., 110)
    mapping = {int(m[0]): m for m in data["parent_mapping"]} if new else {}
    assert data["stats"][9] == 0.
    results = []
    for cycle in data["cycles"]:
        cid = int(cycle[0])
        orders = data["orders"][data["orders"][:, 2] == cid]
        entry = orders[orders[:, 7] == 1]
        assert len(entry) == 1
        assert orders[orders[:, 7] == 0, 4].sum() == entry[0, 4]
        fees = int((orders[:, 4].astype(np.int64) * rate // 10).sum())
        gross = float(cycle[3] * mult)
        independent = float(-np.sum(orders[:, 3] * orders[:, 4] * orders[:, 5]) * mult)
        assert np.isclose(gross, independent)
        link = mapping[cid] if new else [cid, cid, 0, entry[0, 1]]
        results.append(dict(real_parent=cid, shadow_parent=int(link[1]), attempt=int(link[2]),
            side=int(entry[0, 3]), quantity=int(entry[0, 4]), entry_price=float(entry[0, 5]),
            source_time=clock(times[int(entry[0, 1])]), entry_time=clock(times[int(entry[0, 0])]),
            exit_time=clock(times[int(cycle[2])]), gross=gross, fees=fees, net=gross-fees,
            last_reason=int(cycle[9]),
            exits=[dict(source=clock(times[int(o[1])]), time=clock(times[int(o[0])]),
                        quantity=int(o[4]), price=float(o[5]), reason=int(o[6]))
                   for o in orders if o[7] == 0.]))
    return results


def main() -> None:
    """
    機能: 基準D17と新4条件を保存親で完全照合する。
    引数: なし。
    返り値: None。金融再生をせず診断JSONを出力する。
    """
    baseline = read_json(OLD / "round3/全条件の会計.json")
    measured = read_json(TASK / "day_round2/全条件の会計.json")
    manifest = read_json(OLD / "入力準備.json")
    refs = {r["session"]: r for r in manifest["packets"]}
    old_refs = {(r["session"], r["symbol"]): r for r in baseline["cache"]}
    detail, current_scene, packet = [], None, None
    for ref in measured["cache"]:
        scene, symbol = ref["session"], ref["symbol"]
        if scene != current_scene:
            packet = pickle.loads(verified(refs[scene]).read_bytes())
            current_scene = scene
        times = packet["inputs"][scene, symbol]["time_s"]
        with np.load(verified(old_refs[scene, symbol]), allow_pickle=False) as stored:
            old = campaigns({f: stored["D17__" + f] for f in ("orders", "cycles", "stats")}, times, symbol, False)
        old_by_shadow = {r["shadow_parent"]: r for r in old}
        with np.load(verified(ref), allow_pickle=False) as stored:
            for config in measured["configs"]:
                method = config["id"]
                new = campaigns({f: stored[method + "__" + f] for f in
                                 ("orders", "cycles", "stats", "parent_mapping")}, times, symbol, True)
                new_by_shadow = defaultdict(list)
                for row in new:
                    new_by_shadow[row["shadow_parent"]].append(row)
                parents = []
                for shadow in sorted(set(old_by_shadow) | set(new_by_shadow)):
                    previous = old_by_shadow.get(shadow)
                    first = [r for r in new_by_shadow[shadow] if r["attempt"] == 0]
                    retry = [r for r in new_by_shadow[shadow] if r["attempt"] == 1]
                    assert len(first) <= 1 and len(retry) <= 1
                    before = previous["net"] if previous else 0.
                    initial = sum(r["net"] for r in first)
                    again = sum(r["net"] for r in retry)
                    parents.append(dict(shadow_parent=shadow, old=previous,
                        initial=first, retry=retry, old_net=before, initial_net=initial,
                        retry_net=again, new_net=initial+again, difference=initial+again-before))
                old_net, new_net = sum(r["net"] for r in old), sum(r["net"] for r in new)
                expected_old = next(r for r in baseline["rows"] if
                    r["session"] == scene and r["symbol"] == symbol and r["method"] == "D17")
                expected_new = next(r for r in measured["rows"] if
                    r["session"] == scene and r["symbol"] == symbol and r["method"] == method)
                assert np.isclose(old_net, expected_old["net"]) and np.isclose(new_net, expected_new["net"])
                assert np.isclose(sum(r["difference"] for r in parents), new_net-old_net)
                detail.append(dict(session=scene, symbol=symbol, method=method,
                    old_net=old_net, new_net=new_net, difference=new_net-old_net,
                    initial_change=sum(r["initial_net"]-r["old_net"] for r in parents),
                    retry_net=sum(r["retry_net"] for r in parents), parents=parents))
    # ----------------------------------------
    # 負け削減と消した勝ちを別に選び、最悪場だけで結論しない。
    summaries = []
    for config in measured["configs"]:
        for symbol in ("TOPIX", "NK225"):
            subset = [r for r in detail if r["method"] == config["id"] and r["symbol"] == symbol]
            lost_winners = []
            for row in subset:
                for parent in row["parents"]:
                    if parent["old_net"] > 0 and parent["difference"] < 0:
                        lost_winners.append(dict(session=row["session"], **parent))
            summaries.append(dict(method=config["id"], symbol=symbol,
                old_net=sum(r["old_net"] for r in subset), new_net=sum(r["new_net"] for r in subset),
                initial_change=sum(r["initial_change"] for r in subset),
                retry_net=sum(r["retry_net"] for r in subset),
                retry_count=sum(len(p["retry"]) for r in subset for p in r["parents"]),
                worst_three=sorted(subset, key=lambda r: r["new_net"])[:3],
                lost_winners_three=sorted(lost_winners, key=lambda r: r["difference"])[:3]))
    output = dict(passed=True, summaries=summaries, rows=detail, reads=READS,
                  financial_replays=0, API=0,
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  note="保存された全注文と親会計の照合。各差は初回変化＋再参加収支で一致。")
    path = HERE / "日中第二巡の影別増減と残存損失.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(path=str(path), passed=True, rows=len(detail),
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()), ensure_ascii=True))


if __name__ == "__main__":
    main()
