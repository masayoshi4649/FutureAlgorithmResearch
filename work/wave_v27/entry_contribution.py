"""入口と相手確認の追加効果を、対応する全条件の差として調べる。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "wave_v23"
ENTRY = ("direction", "short_price", "ofi_price", "pullback_resume")
NAMES = dict(direction="主方向のみ", short_price="短期価格の順行", ofi_price="短期価格＋OFI一致", pullback_resume="押し戻り後の再開")
SYMBOLS = ("TOPIX", "NK225")
WAVES = (
    dict(id="W01", session="2026-09-21_Day", start="2026-09-21T10:45:00+09:00", end="2026-09-21T15:35:00+09:00", side=1),
    dict(id="W02", session="2026-09-22_Day", start="2026-09-22T09:20:00+09:00", end="2026-09-22T11:45:00+09:00", side=-1),
    dict(id="W03", session="2026-09-23_Day", start="2026-09-23T09:05:00+09:00", end="2026-09-23T11:15:00+09:00", side=-1),
    dict(id="W04", session="2026-09-22_Night", start="2026-09-23T00:40:00+09:00", end="2026-09-23T03:20:00+09:00", side=1),
)
RULES = {
    "目的": "中期方向を固定した対応比較で、短期入口と相手市場確認が収支・下落・頻度・指定波に加えた変化を全件集計する。最良条件だけは拾わない。",
    "全条件": "6主方向×2時間倍率×4入口×2相手確認×206管理器。欠測条件があれば計算を停止し、全探索完了後に読む。",
    "入口比較": "主方向・時間倍率・相手確認・管理器を固定し、direction/short_price/ofi_price/pullback_resumeの順で全6組を比較。差は後者−前者。銘柄ごと各比較4,944組。",
    "相手比較": "主方向・時間倍率・入口・管理器を固定し、相手確認あり−なし。銘柄ごと9,888組。",
    "比重": "全対応組を等重みで集計。同一台帳も除外せず一致率を併記。条件間の従属性が強いため改善割合を独立試行の有意確率にしない。",
    "収支": "全13セッションのnet_yenを合算。両銘柄の円額を合算しない。差の中央値・10/90百分位、厳密改善/悪化/同値割合を示す。",
    "最大DD": "既存research.aggregateと同じ、場内時価下落とセッション間累積損益を接続した最大DD。差が負なら改善。",
    "頻度": "cyclesは売買組数、closed_unitsは返済枚数の延べ数として別記。枚数と約定件数を混同しない。取引減少だけを改善とは定義しない。",
    "同値許容": "円額差の絶対値0.01以下を同値、売買組数と枚数は完全一致。",
    "複合評価": "収支増かつDD減、収支非減かつDD減、収支減かつDD減を分ける。全期黒字化/赤字化・稼働セッション減少も表示する。利益増だけで価値を断定しない。",
    "層別": "主方向6思想ごと、および注文管理familyごとにも同じ全対応比較を載せる。層別結果から候補を再選択しない。",
    "波の全信号比較": "固定4波を全96方向で比較。正方向/逆方向の信号時間と正方向20分目安の差を示す。信号時間は保有時間ではない。管理206倍で重複加重しない。",
    "波の保有補足": "任意の--first-stageで一次反証の合格全候補を受け取り、その主方向・時間倍率・管理器を固定した全8入口/相手確認対照を追加再生。合格候補のみの選別された補足であり全探索の保有分布と区別。合格なしなら未実施と明示。",
    "波の単位": "CurrentPriceTimeの各行から次行まで、同値行は0秒。直前の信号または約定後在庫を積分。正方向ネット保有合計20分を説明目安とし統計有意と呼ばない。境界評価は過去lastのasofのみ。",
    "波区間": list(WAVES),
    "解釈の注意": "short_price/pullback_resumeも板から観測したmid価格を使うが数量は使わない。ofi_price対short_priceがOFI条件の追加比較。相手確認は相手の中期価格方向であり相手OFIではない。最終入口方向は退出にも渡るため入口限定の因果効果ではない。",
    "禁止": "現在API取得、固定信号/管理/エンジン/原本の変更、結果に合わせた比較条件の選別・閾値変更。",
}


def read(path: Path):
    """機能: UTF-8の通常または圧縮JSONを読む。

    引数: path (Path)。返り値: JSONの内容 (dict|list)。
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def save(path: Path, value) -> None:
    """機能: 作業領域へUTF-8の診断結果を保存する。

    引数: path (Path)、value (dict|list)。返り値: なし (None)。
    """
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def digest(path: Path) -> str:
    """機能: 固定資料の内容指紋を得る。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> dict:
    """機能: 損益を読む前に、対応組・指標・波補足範囲を固定する。

    引数: なし。返り値: 固定済み仕様 (dict)。
    """
    path = HERE / "entry_contribution_fixed.json"
    if path.exists():
        value = read(path)
        assert value["規則"] == RULES, "固定後の比較条件変更は禁止"
        return value
    value = dict(固定日時=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), 新結果未読=True, 規則=RULES,
                 探索仕様SHA256=digest(HERE / "探索条件の固定.json"))
    save(path, value)
    return value


def aggregate(rows: list[dict]) -> dict:
    """機能: 同銘柄の13セッションを既存管理器と同じ会計で接続する。

    引数: rows (list[dict])。返り値: 全期間指標 (dict)。
    """
    output = {key: float(sum(row[key] for row in rows)) for key in
              ("net_yen", "gross_profit_yen", "gross_loss_yen", "cycles", "closed_units")}
    cash = high = drawdown = 0.
    for row in sorted(rows, key=lambda value: value["session"]):
        drawdown = max(drawdown, row["drawdown_yen"], high - (cash + row["min_equity_yen"]))
        high = max(high, cash + row["max_equity_yen"])
        cash += row["net_yen"]
    output.update(drawdown_yen=float(drawdown), active_sessions=sum(row["cycles"] > 0 for row in rows),
                  win_sessions=sum(row["net_yen"] > 0 for row in rows))
    return output


def matched_signals(specs: list[dict]) -> list[dict]:
    """機能: 同じ主方向と時間倍率の入口全6組、および相手確認全組を列挙する。

    引数: specs (list[dict])。返り値: 対応する信号IDと固定属性 (list[dict])。
    """
    lookup = {(s["params"]["main_kind"], s["params"]["time_multiplier"], s["params"]["entry_kind"], s["params"]["peer_confirm"]): s["id"] for s in specs}
    main_kinds = list(dict.fromkeys(s["params"]["main_kind"] for s in specs))
    output = []
    for kind, scale in itertools.product(main_kinds, (1, 2)):
        for peer, (before, after) in itertools.product((False, True), itertools.combinations(ENTRY, 2)):
            output.append(dict(comparison=f"{before}→{after}", category="入口", main_kind=kind, time_multiplier=scale,
                               fixed_peer=peer, fixed_entry=None,
                               before=lookup[kind, scale, before, peer], after=lookup[kind, scale, after, peer]))
        for entry in ENTRY:
            output.append(dict(comparison="相手確認なし→あり", category="相手確認", main_kind=kind, time_multiplier=scale,
                               fixed_peer=None, fixed_entry=entry,
                               before=lookup[kind, scale, entry, False], after=lookup[kind, scale, entry, True]))
    assert len(output) == 192
    return output


def load_periods(specs: list[dict], management: list[dict]) -> tuple[dict, dict]:
    """機能: 全再生完了を確認して全セッション結果を銘柄別に集約する。

    引数: specs/management (list[dict])。返り値: 期間指標と全台帳指紋 (tuple[dict,dict])。
    """
    if not (HERE / "全条件の期間集計.json.gz").exists() or not (HERE / "反証前の候補固定.json").exists():
        raise RuntimeError("全探索が完了する前には結果を読みません")
    periods, ledgers = {}, {}
    manager_ids = {item["id"] for item in management}
    for spec in specs:
        result = read(HERE / "sessions" / f"{spec['id']}.json.gz")
        assert len(result) == len(management)
        assert {item["id"].split("__")[1] for item in result} == manager_ids
        for item in result:
            signal_id, manager_id = item["id"].split("__")
            assert signal_id == spec["id"]
            for symbol in SYMBOLS:
                rows = [row for row in item["rows"] if row["symbol"] == symbol]
                assert len(rows) == 13 and len({row["session"] for row in rows}) == 13
                periods[signal_id, manager_id, symbol] = aggregate(rows)
        summaries = read(HERE / "summaries" / f"{spec['id']}.json")["candidates"]
        for item in summaries:
            ledgers[item["id"]] = item["ledger_hash"]
            for symbol in SYMBOLS:
                own = periods[spec["id"], item["manager_id"], symbol]
                for key, value in own.items():
                    assert abs(value - item["symbols"][symbol][key]) < .01, f"集計不一致 {item['id']} {symbol} {key}"
    return periods, ledgers


def build_pairs(matches: list[dict], periods: dict, management: list[dict], ledgers: dict) -> list[dict]:
    """機能: 管理器を一つも選別せず、対応する2条件の指標差を計算する。

    引数: matches (list[dict])、periods/ledgers (dict)、management (list[dict])。
    返り値: 全対応組の銘柄別差分 (list[dict])。
    """
    output = []
    for match, manager, symbol in itertools.product(matches, management, SYMBOLS):
        before = periods[match["before"], manager["id"], symbol]
        after = periods[match["after"], manager["id"], symbol]
        row = dict(match, symbol=symbol, manager_id=manager["id"], manager_family=manager["family"],
                   before_net=before["net_yen"], after_net=after["net_yen"],
                   before_dd=before["drawdown_yen"], after_dd=after["drawdown_yen"],
                   before_cycles=before["cycles"], after_cycles=after["cycles"],
                   both_market_ledger_identical=ledgers[match["before"] + "__" + manager["id"]] == ledgers[match["after"] + "__" + manager["id"]])
        row.update({"delta_" + key: after[key] - before[key] for key in before})
        output.append(row)
    assert len(output) == 79104
    return output


def distribution(values: list[float], lower_better: bool = False, tolerance: float = .01) -> dict:
    """機能: 対応差を中央値と分位点、厳密改善・悪化・同値に分ける。

    引数: values (list[float])、lower_better (bool)、tolerance (float)。返り値: 分布指標 (dict)。
    """
    array = np.asarray(values, float)
    signed = -array if lower_better else array
    return dict(中央値=float(np.median(array)), 下位10百分位=float(np.quantile(array, .1)), 上位90百分位=float(np.quantile(array, .9)),
                改善割合=float(np.mean(signed > tolerance)), 悪化割合=float(np.mean(signed < -tolerance)), 同値割合=float(np.mean(abs(signed) <= tolerance)))


def count_distribution(values: list[float]) -> dict:
    """機能: 頻度の増減を改善と呼ばず、そのまま分布として記録する。

    引数: values (list[float])。返り値: 中央値と増加/減少/同値割合 (dict)。
    """
    result = distribution(values, tolerance=0)
    result["増加割合"] = result.pop("改善割合")
    result["減少割合"] = result.pop("悪化割合")
    return result


def summarize_pairs(rows: list[dict]) -> dict:
    """機能: 一つの対応比較について利益と下落と頻度を同時に要約する。

    引数: rows (list[dict])。返り値: 選別なしの集計結果 (dict)。
    """
    net = np.array([row["delta_net_yen"] for row in rows])
    dd = np.array([row["delta_drawdown_yen"] for row in rows])
    return dict(対応組数=len(rows),
                収支差円=distribution(net.tolist()), 最大DD差円=distribution(dd.tolist(), lower_better=True),
                売買組数差=count_distribution([row["delta_cycles"] for row in rows]),
                延べ返済枚数差=count_distribution([row["delta_closed_units"] for row in rows]),
                稼働セッション差=count_distribution([row["delta_active_sessions"] for row in rows]),
                総利益差円=distribution([row["delta_gross_profit_yen"] for row in rows]),
                総損失差円=distribution([row["delta_gross_loss_yen"] for row in rows], lower_better=True),
                収支増かつDD減割合=float(np.mean((net > .01) & (dd < -.01))),
                収支非減かつDD減割合=float(np.mean((net >= -.01) & (dd < -.01))),
                収支減かつDD減割合=float(np.mean((net < -.01) & (dd < -.01))),
                黒字へ改善割合=float(np.mean([row["before_net"] <= .01 and row["after_net"] > .01 for row in rows])),
                黒字を失う割合=float(np.mean([row["before_net"] > .01 and row["after_net"] <= .01 for row in rows])),
                両市場全台帳同一割合=float(np.mean([row["both_market_ledger_identical"] for row in rows])),
                比較前収支中央値=float(np.median([row["before_net"] for row in rows])),
                比較後収支中央値=float(np.median([row["after_net"] for row in rows])))


def grouped_pairs(rows: list[dict], attributes: tuple[str, ...]) -> list[dict]:
    """機能: 事前固定した属性だけで対応組を層別する。

    引数: rows (list[dict])、attributes (tuple[str,...])。返り値: 層別集計 (list[dict])。
    """
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in attributes)].append(row)
    return [dict(zip(attributes, key), **summarize_pairs(values)) for key, values in sorted(groups.items(), key=lambda item: str(item[0]))]


def integral(times: np.ndarray, values: np.ndarray, wave: dict) -> float:
    """機能: 各原本行の状態を次時点まで積分し、同値時刻を0秒として扱う。

    引数: times/values (ndarray)、wave (dict)。返り値: 区間内の状態値×分 (float)。
    """
    start, end = (datetime.fromisoformat(wave[key]).timestamp() for key in ("start", "end"))
    duration = np.maximum(0., np.minimum(times[1:], end) - np.maximum(times[:-1], start))
    return float(np.sum(duration * values[:-1]) / 60)


def signal_waves(specs: list[dict], inputs: dict, matches: list[dict]) -> dict:
    """機能: 管理器による重複加重なしで全96信号の指定波時間を比較する。

    引数: specs/matches (list[dict])、inputs (dict)。返り値: 波別値と対応差集計 (dict)。
    """
    rows, totals = [], {}
    for spec in specs:
        with np.load(HERE / "directions" / f"{spec['id']}.npz", allow_pickle=False) as archive:
            for symbol in SYMBOLS:
                forward = reverse = hits = 0
                for wave in WAVES:
                    ready = inputs[wave["session"], symbol]
                    state = archive[f"{wave['session']}|{symbol}"] * wave["side"]
                    correct = integral(ready["time_s"], state > 0, wave)
                    wrong = integral(ready["time_s"], state < 0, wave)
                    hit = correct >= 20 - 1e-9
                    rows.append(dict(signal_id=spec["id"], symbol=symbol, wave=wave["id"], 正方向信号分=correct, 逆方向信号分=wrong, 正方向20分目安=hit))
                    forward += correct
                    reverse += wrong
                    hits += int(hit)
                totals[spec["id"], symbol] = dict(forward=forward, reverse=reverse, hits=hits)
    changes = []
    for match, symbol in itertools.product(matches, SYMBOLS):
        before, after = (totals[match[key], symbol] for key in ("before", "after"))
        changes.append(dict(match, symbol=symbol, **{"delta_" + key: after[key] - before[key] for key in before}))
    grouped = defaultdict(list)
    for row in changes:
        grouped[row["comparison"], row["symbol"]].append(row)
    summary = [dict(comparison=key[0], symbol=key[1], 対応信号組数=len(values),
                    正方向信号分差=distribution([row["delta_forward"] for row in values]),
                    逆方向信号分差=distribution([row["delta_reverse"] for row in values], lower_better=True),
                    四波の20分目安達成数差=distribution([row["delta_hits"] for row in values], tolerance=0))
               for key, values in sorted(grouped.items())]
    return dict(保有時間ではない=True, 波別=rows, 対応差=changes, 全対応集計=summary)


def holding_waves(path: Path | None, specs: list[dict], management: list[dict], inputs: dict, matches: list[dict]) -> dict:
    """機能: 一次反証合格全候補に対応する8変種だけを保有波診断へ再生する。

    引数: path (Path|None)、specs/management/matches (list[dict])、inputs (dict)。
    返り値: 選別された補足の範囲・波別値・対応差 (dict)。
    """
    if path is None:
        return dict(実施=False, 理由="一次反証合格の固定資料が未指定。全信号の波診断とは区別し、実保有は未計測。")
    tested = read(path)
    passed = [item["candidate"] for item in tested if not item["first_stage_failures"]]
    lookup = {spec["id"]: spec for spec in specs}
    management_lookup = {item["id"]: item for item in management}
    groups = sorted({(lookup[item["signal_id"]]["params"]["main_kind"], lookup[item["signal_id"]]["params"]["time_multiplier"], item["manager_id"]) for item in passed})
    fixed = dict(一次反証SHA256=digest(path), 合格候補=[item["id"] for item in passed], 対照群=[list(group) for group in groups],
                 選び方="全合格候補に対応する主方向/時間倍率/管理器を固定し、入口4種×相手確認2種の全8変種。波の結果で絞らない。")
    destination = HERE / "entry_contribution_wave_selection.json"
    if destination.exists():
        assert read(destination) == fixed, "波保有対照の固定後変更は禁止"
    else:
        save(destination, fixed)
    if not groups:
        return dict(実施=False, 理由="一次反証合格候補なし", 固定範囲=fixed)
    sys.path.insert(0, str(HERE))
    import hierarchy_runner as runner
    rows, values = [], {}
    for kind, scale, manager_id in groups:
        group_specs = [spec for spec in specs if spec["params"]["main_kind"] == kind and spec["params"]["time_multiplier"] == scale]
        assert len(group_specs) == 8
        for spec in group_specs:
            with np.load(HERE / "directions" / f"{spec['id']}.npz", allow_pickle=False) as archive:
                for wave, symbol in itertools.product(WAVES, SYMBOLS):
                    ready = inputs[wave["session"], symbol]
                    state = archive[f"{wave['session']}|{symbol}"]
                    config = runner.managers.make_config(management_lookup[manager_id], symbol, ready)
                    result = runner.engine.run(ready, state, config, detail=True)
                    curve = result["curve"]
                    own = curve[:, 6] * wave["side"]
                    forward, reverse = integral(ready["time_s"], own > 0, wave), integral(ready["time_s"], own < 0, wave)
                    boundaries = []
                    for boundary in ("start", "end"):
                        timestamp = datetime.fromisoformat(wave[boundary]).timestamp()
                        index = np.searchsorted(ready["time_s"], timestamp, side="right") - 1
                        boundaries.append(float((curve[index, 5] + curve[index, 6] * ready["last"][index]) * config["point_value"]))
                    row = dict(signal_id=spec["id"], manager_id=manager_id, symbol=symbol, wave=wave["id"],
                               正方向ネット保有分=forward, 逆方向ネット保有分=reverse, 正方向20分目安=forward >= 20 - 1e-9,
                               時価損益差円=boundaries[1] - boundaries[0])
                    rows.append(row)
                    values[spec["id"], manager_id, symbol, wave["id"]] = row
    changes = []
    for kind, scale, manager_id in groups:
        for match in matches:
            if match["main_kind"] != kind or match["time_multiplier"] != scale:
                continue
            for wave, symbol in itertools.product(WAVES, SYMBOLS):
                before, after = (values[match[key], manager_id, symbol, wave["id"]] for key in ("before", "after"))
                changes.append(dict(match, manager_id=manager_id, symbol=symbol, wave=wave["id"],
                                    正方向ネット保有分差=after["正方向ネット保有分"] - before["正方向ネット保有分"],
                                    逆方向ネット保有分差=after["逆方向ネット保有分"] - before["逆方向ネット保有分"],
                                    捕捉増減=int(after["正方向20分目安"]) - int(before["正方向20分目安"]),
                                    時価損益差円差=after["時価損益差円"] - before["時価損益差円"]))
    grouped = defaultdict(list)
    for row in changes:
        grouped[row["comparison"], row["symbol"]].append(row)
    summary = [dict(comparison=key[0], symbol=key[1], 対応波区間数=len(group),
                    正方向保有分差=distribution([row["正方向ネット保有分差"] for row in group]),
                    逆方向保有分差=distribution([row["逆方向ネット保有分差"] for row in group], lower_better=True),
                    捕捉改善割合=float(np.mean([row["捕捉増減"] > 0 for row in group])),
                    捕捉喪失割合=float(np.mean([row["捕捉増減"] < 0 for row in group])))
               for key, group in sorted(grouped.items())]
    return dict(実施=True, 選別された補足で全探索ではない=True, 固定範囲=fixed, 波別=rows, 対応差=changes, 全対応集計=summary)


def tick_threshold_diagnostic(inputs: dict | None = None) -> dict:
    """機能: 固定短期価格閾値の呼値未満割合を、損益とは独立に測る。

    引数: inputs (dict|None) は既存入力。返り値: 原本行と解放板時点の呼値比 (dict)。
    """
    rules = dict(目的="閾値近傍で方向不変でも、呼値量子化による不変性を安定領域と誤解しないための共通入力診断。成績・選別には使わない。",
                 対象="全26入力、開始20分以後でATRが有限かつ正の原本行、ならびに同条件の解放板イベント。",
                 閾値ATR倍=[.05, .10], 感度倍率=[.8, 1., 1.2],
                 比較="指定幅/各銘柄のtick。1呼値未満と半呼値未満を別記。厳密な小なりで等号は含めない。",
                 重み="原本行頻度と次行までの経過秒重みを区別。解放イベント頻度は別に測る。中期方向や実際の取引成立で絞らない。",
                 限界="short_priceは板midの差。midは半呼値刻みもあり、閾値が1呼値未満でも不使用とは限らない。短期閾値が同じ区間にとどまることと方向の不変性は同義ではない。")
    path = HERE / "entry_threshold_ticks_fixed.json"
    if path.exists():
        assert read(path)["規則"] == rules
    else:
        save(path, dict(固定日時=datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(), 結果生成前=True, 規則=rules))
    if inputs is None:
        inputs = pickle.loads((OLD / "inputs.pkl").read_bytes())
    features = pickle.loads((OLD / "features_depth.pkl").read_bytes())
    output, pooled = [], defaultdict(list)
    for key, ready in inputs.items():
        times, atr = ready["time_s"], ready["atr"]
        valid = (times >= ready["start"] + 1200) & np.isfinite(atr) & (atr > 0)
        duration = np.r_[np.diff(times), 0.]
        frame = features[key]
        indices = np.searchsorted(ready["seq"], frame.seq.to_numpy(), side="right") - 1
        available = (indices >= 0) & (frame.seq.to_numpy() <= ready["seq"][-1]) & (frame.time_s.to_numpy() <= times[-1])
        indices = indices[available]
        indices = indices[valid[indices]]
        for base, multiplier in itertools.product((.05, .10), (.8, 1., 1.2)):
            ratios = atr / ready["tick"] * base * multiplier
            for unit, values, weights in (("原本行", ratios[valid], np.ones(np.count_nonzero(valid))),
                                          ("経過秒", ratios[valid], duration[valid]),
                                          ("解放板イベント", ratios[indices], np.ones(len(indices)))):
                total = float(weights.sum())
                row = dict(session=key[0], symbol=key[1], base=base, multiplier=multiplier, unit=unit,
                           件数または秒=total, 呼値比中央値=float(np.median(values)),
                           半呼値未満分子=float(np.sum(weights * (values < .5))),
                           一呼値未満分子=float(np.sum(weights * (values < 1.))))
                row.update(半呼値未満割合=row["半呼値未満分子"] / total if total else None,
                           一呼値未満割合=row["一呼値未満分子"] / total if total else None)
                output.append(row)
                pooled[key[1], base, multiplier, unit].append(row)
    summary = []
    for (symbol, base, multiplier, unit), rows in sorted(pooled.items()):
        total = sum(row["件数または秒"] for row in rows)
        summary.append(dict(symbol=symbol, base=base, multiplier=multiplier, unit=unit, 件数または秒=total,
                            半呼値未満割合=sum(row["半呼値未満分子"] for row in rows) / total if total else None,
                            一呼値未満割合=sum(row["一呼値未満分子"] for row in rows) / total if total else None))
    report = dict(規則SHA256=digest(path), 全期間=summary, セッション別=output, 損益使用=False)
    save(HERE / "entry_threshold_ticks.json", report)
    return report


def check_wave_overlap(holding: dict) -> dict:
    """機能: 別の波レポートと重なる実保有時間・境界損益を照合する。

    引数: holding (dict)。返り値: 照合件数と参照資料指紋 (dict)。
    """
    path = HERE / "episode_audit.json"
    if not holding["実施"] or not path.exists():
        return dict(実施=False, 理由="別実装の波診断または保有補足が未完成")
    reference = read(path)
    lookup = {(row["method"], row["symbol"], row["wave"]): row for row in reference["結果"]}
    count = 0
    for row in holding["波別"]:
        key = (row["signal_id"] + "__" + row["manager_id"], row["symbol"], row["wave"])
        if key not in lookup:
            continue
        other = lookup[key]
        for field in ("正方向ネット保有分", "逆方向ネット保有分", "時価損益差円"):
            assert abs(row[field] - other[field]) < 1e-6, f"別実装波診断の不一致 {key} {field}"
        assert row["正方向20分目安"] == other["正方向ネット20分目安達成"]
        count += 1
    assert count == len(holding["固定範囲"]["合格候補"]) * 8
    return dict(実施=True, 全一致=True, 照合波区間数=count, 比較指標=["正方向ネット保有分", "逆方向ネット保有分", "時価損益差円", "20分目安"],
                別実装SHA256=digest(path))


def write_markdown(report: dict) -> None:
    """機能: 全対応比較の結果を短い日本語表と注意点にまとめる。

    引数: report (dict)。返り値: なし (None)。
    """
    lines = ["# 短期入口と相手市場確認の追加効果", "", "同じ主方向・時間倍率・注文管理を対応させた全条件の比較。差は右側の方法−左側の方法。銘柄の円額は合算していない。", "",
             "収支改善は差が正、DD改善は差が負。売買組数が減ること自体は改善と呼ばない。", "",
             "| 比較 | 銘柄 | 対応組数 | 収支差中央値 | 収支改善率 | DD差中央値 | DD改善率 | 売買組数差中央値 | 収支増＋DD減 |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["全対応集計"]:
        label = row["comparison"]
        for key, value in NAMES.items():
            label = label.replace(key, value)
        lines.append(f"|{label}|{row['symbol']}|{row['対応組数']:,}|{row['収支差円']['中央値']:+,.0f}円|{row['収支差円']['改善割合']:.1%}|{row['最大DD差円']['中央値']:+,.0f}円|{row['最大DD差円']['改善割合']:.1%}|{row['売買組数差']['中央値']:+.1f}|{row['収支増かつDD減割合']:.1%}|")
    lines += ["", "## 指定波との交換条件", "", "以下は全96条件の信号時間。実際の建玉を持った時間とは異なる。管理器206個による重複加重はしていない。", "",
              "| 比較 | 銘柄 | 正方向信号の合計時間差中央値 | 逆方向信号の合計時間差中央値 | 4波の20分目安達成数差中央値 |", "|---|---|---:|---:|---:|"]
    for row in report["全信号の波"]["全対応集計"]:
        label = row["comparison"]
        for key, value in NAMES.items():
            label = label.replace(key, value)
        lines.append(f"|{label}|{row['symbol']}|{row['正方向信号分差']['中央値']:+.1f}分|{row['逆方向信号分差']['中央値']:+.1f}分|{row['四波の20分目安達成数差']['中央値']:+.1f}|")
    holding = report["保有波の補足"]
    if holding["実施"]:
        lines += ["", "実保有の波診断は、一次反証合格候補に対応する8変種だけの補足。全探索より選別された範囲である。", "",
                  "| 比較 | 銘柄 | 波区間数 | 正方向保有分差中央値 | 捕捉改善率 | 捕捉喪失率 |", "|---|---|---:|---:|---:|---:|"]
        for row in holding["全対応集計"]:
            label = row["comparison"]
            for key, value in NAMES.items():
                label = label.replace(key, value)
            lines.append(f"|{label}|{row['symbol']}|{row['対応波区間数']}|{row['正方向保有分差']['中央値']:+.1f}分|{row['捕捉改善割合']:.1%}|{row['捕捉喪失割合']:.1%}|")
    else:
        lines += ["", "実保有の補足：" + holding["理由"]]
    lines += ["", "## 呼値と短期閾値", "",
              "全26入力を確認。以下は解放板イベントでの割合。midには半呼値刻みもあるため、1呼値未満だから即座に無意味とはならない。", "",
              "| 銘柄 | ATR倍 | 半呼値未満 | 1呼値未満 |", "|---|---:|---:|---:|"]
    for row in report["短期閾値と呼値"]["全期間"]:
        if row["unit"] == "解放板イベント" and row["multiplier"] == 1.:
            lines.append(f"|{row['symbol']}|{row['base']:.2f}|{row['半呼値未満割合']:.1%}|{row['一呼値未満割合']:.1%}|")
    lines += ["", "閾値を±20%変えても方向が同じ場合、価格刻みの間にとどまった可能性がある。それだけで広い安定領域とは判断しない。", "", "## 読み方", "",
              "- OFIそのものの追加比較は『短期価格→短期価格＋OFI一致』。押し戻りや短期価格だけは数量を使わず、相手確認は相手の中期価格方向を使う。",
              "- 短期条件は正方向の信号を減らす一方、誤方向の信号も減らし得る。機会の削減と損失抑制を区別する。",
              "- 最終入口方向は既存管理器の退出にも影響する。この比較を新規発注だけの効果とは言わない。",
              "- 全対応組は同じデータを共有しており独立標本ではない。改善割合はこの条件集合内の分布で、未知期間の成功確率ではない。",
              "- 主方向別・管理思想別の層別、全対応差、波別値はJSONに保存。最良例への絞込み・再最適化・現在API取得はしていない。"]
    (HERE / "entry_contribution.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute(fixed: dict, first_stage: Path | None) -> None:
    """機能: 凍結済み比較規則に従い既存結果と波の対応診断を出力する。

    引数: fixed (dict)、first_stage (Path|None)。返り値: なし (None)。
    """
    design = read(HERE / "探索条件の固定.json")
    assert digest(HERE / "探索条件の固定.json") == fixed["探索仕様SHA256"]
    specs, management = design["signals"], design["managers"]
    assert len(specs) == 96 and len(management) == 206
    matches = matched_signals(specs)
    periods, ledgers = load_periods(specs, management)
    pairs = build_pairs(matches, periods, management, ledgers)
    save(HERE / "entry_contribution_pairs.json.gz", pairs)
    inputs = pickle.loads((OLD / "inputs.pkl").read_bytes())
    report = dict(規則SHA256=digest(HERE / "entry_contribution_fixed.json"), API取得数=0,
                  全対応組数=len(pairs), 全期間指標数=len(periods),
                  全対応集計=grouped_pairs(pairs, ("comparison", "symbol")),
                  主方向別=grouped_pairs(pairs, ("comparison", "symbol", "main_kind")),
                  管理思想別=grouped_pairs(pairs, ("comparison", "symbol", "manager_family")),
                  相手確認の入口別=grouped_pairs([row for row in pairs if row["category"] == "相手確認"], ("comparison", "symbol", "fixed_entry")),
                  全信号の波=signal_waves(specs, inputs, matches),
                  保有波の補足=holding_waves(first_stage, specs, management, inputs, matches),
                  短期閾値と呼値=tick_threshold_diagnostic(inputs))
    report["波診断別実装との照合"] = check_wave_overlap(report["保有波の補足"])
    save(HERE / "entry_contribution.json", report)
    write_markdown(report)
    print(f"入口と相手確認の全{len(pairs):,}対応組を保存しました。", flush=True)


def main() -> None:
    """機能: 比較規則を先に保存し、その後に全対応組の分解を実行する。

    引数: --prepare (bool)、--first-stage (Path|None)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--first-stage", type=Path)
    parser.add_argument("--thresholds-only", action="store_true")
    args = parser.parse_args()
    fixed = freeze()
    if args.prepare:
        print("入口・相手確認の全対応比較を、結果閲覧前に固定しました。", flush=True)
        return
    if args.thresholds_only:
        tick_threshold_diagnostic()
        print("損益を読まず呼値閾値の共通入力診断を保存しました。", flush=True)
        return
    execute(fixed, args.first_stage)


if __name__ == "__main__":
    main()
