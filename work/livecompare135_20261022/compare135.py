"""提示約定の算術と、保存済み二回目の通常影が返済幅へ届いたかを確認する。"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = ROOT / "work/update134_20261022"
SCENE = "2026-10-22_Day"
JST = timezone(timedelta(hours=9))


def read(path: Path) -> dict:
    """
    機能: 保存済みJSONを読む。
    引数: path(Path)はファイル位置。
    返り値: dictはJSONの内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path: Path) -> dict:
    """
    機能: 比較元・入力・コードの内容指紋を計算する。
    引数: path(Path)は既存ファイル。
    返り値: dictは位置とSHA256。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=digest)


def stamp(value: float) -> str:
    """
    機能: 保存価格時計を日本時刻で表示する。
    引数: value(float)はUNIX秒。
    返り値: strは日本時刻ISO文字列。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def main() -> None:
    """
    機能: ユーザー提示価格の独立算術と、既存約定後の価格幅を計測する。
    引数: なし。
    返り値: None。売買器を実行せず、新規の注文経路・損益は生成しない。
    """
    audit_path = PRIOR / "audit/独立注文会計と約定明細.json"
    audit = read(audit_path)
    supplied = [("新規売", "4054.55", 5), ("返済買", "4060.45", 5),
                ("新規売", "4051.3", 5), ("返済買", "4041.7", 2), ("返済買", "4030.7", 3)]
    assert len(supplied) == len(audit["orders"]) == 5
    price = None
    remaining = 0
    records = []
    for (action, raw_price, quantity), old in zip(supplied, audit["orders"]):
        current = Decimal(raw_price)
        opening = action == "新規売"
        assert old["opening"] == opening and old["quantity"] == quantity
        assert old["side"] == (-1 if opening else 1)
        if opening:
            assert remaining == 0
            price, remaining = current, quantity
            gross = Decimal(0)
        else:
            assert remaining >= quantity
            gross = (price-current)*quantity*1000
            remaining -= quantity
        fee = (Decimal("27.5")*quantity).to_integral_value(rounding=ROUND_FLOOR)
        records.append(dict(action=action, price=raw_price, quantity=quantity,
            gross=int(gross), assumed_jnet_fee=int(fee), research_time=old["time"],
            research_price=old["price"], actual_time="ユーザー提示なし"))
    assert remaining == 0
    gross = sum(row["gross"] for row in records)
    fees = sum(row["assumed_jnet_fee"] for row in records)
    assert gross == 51500 and fees == 548 and gross-fees == 50952

    # ----------------------------------------
    # 保存済み入力と注文明細を読む。入口・出口のシミュレータは呼び出さない。
    manifest = read(PRIOR / "inputs/input_manifest.json")
    packet_ref = next(item for item in manifest["packets"] if item["session"] == SCENE)
    packet_path = ROOT / packet_ref["path"]
    assert reference(packet_path)["sha256"] == packet_ref["sha256"]
    packet = pickle.loads(packet_path.read_bytes())
    key = SCENE, "TOPIX"
    ready = packet["inputs"][key]
    cache_path = PRIOR / "results/measurement/TOPIX_2026-10-22_Day.npz"
    assert reference(cache_path)["sha256"] == audit["cache"]["sha256"]
    with np.load(cache_path, allow_pickle=False) as archive:
        paper = archive["paper_orders"]
        cycles = archive["paper_cycles"]
        accepted = archive["accepted_feed"]
    np.testing.assert_array_equal(paper, accepted[:, :8])
    assert len(cycles) == 2 and len(paper) == 5
    cycle = cycles[1]
    start = int(cycle[1])
    assert cycle[8] == -1
    times, prices = ready["time_s"], ready["last"]
    cutoff = ready["limit"]
    stop = int(np.searchsorted(times, cutoff, side="left"))
    indexes = np.arange(start, stop)
    values = prices[indexes]
    low = np.minimum.accumulate(values)
    initial_atr, tick = float(cycle[5]), float(ready["tick"])
    anchor = float(values[0])
    width = 3*initial_atr
    raw_line = low+width
    rounded_line = np.ceil((raw_line-1e-8)/tick)*tick
    previous_line = np.r_[np.nan, rounded_line[:-1]]
    armed_previous = np.r_[False, anchor-low[:-1] >= 1.5*initial_atr]
    trigger = armed_previous & (values >= previous_line-1e-8)
    assert not np.any(trigger), "通常影の返済幅へ到達した行があるため、未終了と推論できない"
    initial_stop = float(np.ceil((anchor+initial_atr-1e-8)/tick)*tick)
    assert values.max() < initial_stop
    assert cutoff < times[start]+360*60
    rebound = values-low
    peak = int(np.argmax(rebound))
    hourly = []
    direction = np.asarray(packet["features"][key]["columns"][0])
    gate = packet["gates"][key]
    for hour in (12, 13, 14, 15):
        begin = datetime(2026, 10, 22, hour, tzinfo=JST).timestamp()
        finish = min(begin+3600, cutoff-300)
        mask = (times >= begin) & (times < finish)
        permitted = mask & gate & (direction != 0)
        hourly.append(dict(hour=hour, observed_rows=int(mask.sum()),
            short_direction_and_gate_rows=int(np.sum(permitted & (direction == -1))),
            long_direction_and_gate_rows=int(np.sum(permitted & (direction == 1))),
            qualification="入口の方向資格のみ。全てが新規発注可能な状態ではない。"))
    sources = [ROOT / "App/SessionTrader/internal/e01/engine.go",
        ROOT / "App/SessionTrader/internal/strategy/cores.go",
        ROOT / "work/stability126_20261019/engine/legacy_root/work/wave_v67/replay.py",
        ROOT / "work/stability126_20261019/engine/legacy_root/work/wave_v67/engine_shadow.py",
        ROOT / "work/stability126_20261019/engine/legacy_root/work/wave_v85/strategy.py"]
    output = dict(passed=True, supplied_orders=records, reported_net=50952,
        arithmetic=dict(gross=gross, assumed_jnet_fees=fees, net=gross-fees,
            research_gross=audit["account"]["gross"], research_fees=audit["account"]["fees"],
            research_net=audit["account"]["net"],
            price_difference=gross-audit["account"]["gross"],
            fee_difference=audit["account"]["fees"]-fees,
            total_difference=gross-fees-audit["account"]["net"],
            caveat="手数料548円は提示収支とJ-NET27.5円の一致。約定の経路・実課金を記録で確認したわけではない。"),
        saved_research_orders=audit["orders"],
        diagnosis=dict(second_entry=stamp(times[start]), actual_exit_in_research=stamp(times[int(cycle[2])]),
            horizon_exclusive=stamp(cutoff), entry_price=anchor, initial_atr=initial_atr,
            normal_trail_width_pt=width, exit_trail_after_3atr_pt=initial_atr*.75,
            maximum_rebound_pt=float(rebound[peak]), maximum_rebound_at=stamp(times[indexes[peak]]),
            normal_trail_at_maximum_rebound=float(rounded_line[peak]), price_at_maximum_rebound=float(values[peak]),
            normal_trail_crossed=False, maximum_price_after_entry=float(values.max()), initial_normal_stop=initial_stop,
            timed_exit_at=stamp(times[start]+360*60), hourly_direction_qualification=hourly,
            inference="通常影は初期3ATR幅のままで、返済幅・初期損切り・最大保有時間のどれにも場内返済前に到達しない。出口側だけ先に終わり、通常影が新規準備を抑止する構造と整合。",
            limits="既存二回目建玉と保存価格経路によるコード上の診断。実行PCの当時の通常影状態・受信履歴・設定は未取得。実売買時刻も未提示。"),
        evidence=[reference(audit_path), reference(packet_path), reference(cache_path), reference(Path(__file__))]+[reference(path) for path in sources],
        financial_replays=0, new_orders=0, API=0, algorithm_changed=False)
    with (HERE / "提示約定と午後待機の照合.json").open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(arithmetic=output["arithmetic"], diagnosis=output["diagnosis"]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
