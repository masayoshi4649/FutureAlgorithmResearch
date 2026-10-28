"""新しい入口のtrain/validation選択と、凍結後のtest採点を分離する。"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from rules161 import candidates, manual_signal, model_matrix, fit_preprocess, transform, fit_logit, fit_tree, predict

HERE = Path(__file__).resolve().parent
PHASES = ("Day", "preUS", "postUS")
SEED = 610161
COOLDOWN = 60


def read_json(path):
    """UTF-8の固定JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    """ファイル内容のSHA256を返す。

    引数: path(Path)。返り値: str。
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    """新しい証跡JSONを既存成果の上書きなしで保存する。

    引数: path(Path)、value(dict又はlist)。返り値: None。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2, allow_nan=False)
        out.write("\n")


def canonical_digest(value):
    """JSONの意味内容を安定した指紋に変換する。

    引数: value(dict又はlist)。返り値: str。
    """
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def require_registration(path, stage, spec_path, manifest_path, freeze_path=None):
    """対象段階と仕様指紋が登録受領に一致する場合だけ実測を許す。

    引数: path/spec_path/manifest_path(Path)、stage(str)、freeze_path(Path又はNone)。
    返り値: dict。不一致や未登録では金融資料を開く前に例外とする。
    """
    receipt = read_json(path)
    if receipt.get("registered") is not True or type(receipt.get("returncode")) is not int or receipt["returncode"] != 0:
        raise ValueError("登録成功が確認できません")
    if stage not in receipt.get("allowed_stages", []):
        raise ValueError("この段階の実測は未登録です")
    if receipt.get("spec_sha256") != digest(spec_path) or receipt.get("manifest_sha256") != digest(manifest_path):
        raise ValueError("登録仕様又は目録の指紋が異なります")
    for record in read_json(spec_path).get("implementation", []):
        target = Path(spec_path).resolve().parent / record["file"]
        if digest(target) != record["sha256"]:
            raise ValueError("登録実装が変更されています")
    if stage == "locked_test" and (freeze_path is None or receipt.get("freeze_sha256") != digest(freeze_path)):
        raise ValueError("test選択の凍結指紋が一致しません")
    return receipt


def load_scene(scene, data_root, allowed_splits, access_log):
    """許可されたsplitの特徴とラベルだけを読む。

    引数: scene(dict)、data_root(Path)、allowed_splits(set[str])、access_log(list)。
    返り値: dict。testを選択段階から読むことを禁止する。
    """
    if scene["split"] not in allowed_splits:
        raise ValueError(f"許可外の期間を読み込もうとしました: {scene['session']}")
    root = Path(data_root)
    feature_path = root / "features" / scene["split"] / f"{scene['session']}.npz"
    label_path = root / "labels" / scene["split"] / f"{scene['session']}.npz"
    with np.load(feature_path, allow_pickle=False) as packed:
        feature = {key: packed[key].copy() for key in packed.files}
    with np.load(label_path, allow_pickle=False) as packed:
        label = {key: packed[key].copy() for key in packed.files}
    names = [str(x) for x in feature["feature_names"]]
    values = feature["features"]
    if values.shape != (len(feature["time"]), len(names)):
        raise ValueError("特徴行列の形が不正です")
    for feature_key, label_key in (("decision_index", "decision_index"), ("time", "decision_time")):
        if label_key not in label or not np.array_equal(feature[feature_key], label[label_key]):
            raise ValueError("特徴とラベルの観測順が異なります")
    if feature["phase"].dtype.kind in "iu":
        if np.any((feature["phase"] < 0) | (feature["phase"] > 2)):
            raise ValueError("phase番号が不正です")
        feature["phase"] = np.asarray(PHASES)[feature["phase"]]
    if not set(feature["phase"].astype(str)).issubset(PHASES):
        raise ValueError("phase名が不正です")
    index = feature["decision_index"]
    if len(index) > 1 and (np.any(np.diff(index) <= 0) or np.any(np.diff(feature["time"]) <= 0)):
        raise ValueError("価格時計が変わる最初の観測に一意化されていません")
    access_log.append(dict(session=scene["session"], split=scene["split"],
                           features=str(feature_path), labels=str(label_path),
                           feature_sha256=digest(feature_path), label_sha256=digest(label_path)))
    return dict(scene=scene, feature=feature, f={name: values[:, i] for i, name in enumerate(names)}, label=label)


def model_eligible(features):
    """学習対照にも価格資格と最低限の既知特徴を要求する。

    引数: features(dict[str,ndarray])。返り値: ndarray[bool]。
    """
    matrix = model_matrix(features, 1)
    return ((features["spread"] > 0) & (features["spread"] <= 20)
            & np.isfinite(features["ret15_pt"]) & np.isfinite(features["ret60_pt"])
            & (np.isfinite(matrix).sum(axis=1) >= 12))


def anchor_mask(times, start, interval):
    """固定時間格子の各枠で最初の観測だけを選ぶ。

    引数: times(ndarray)、start(float)、interval(int秒)。返り値: ndarray[bool]。
    """
    slots = np.floor((times - start) / interval).astype(np.int64)
    return np.r_[True, np.diff(slots) != 0]


def label_event(data, row, side, candidate_id, phase):
    """選ばれた一観測の主方向と同時刻逆方向の既存ラベルを取り出す。

    引数: data(dict)、row(int)、side(int)、candidate_id/phase(str)。返り値: dict。
    金額・未来の手法選択は作らない。
    """
    column, opposite = (0, 1) if side == 1 else (1, 0)
    label, feature, scene = data["label"], data["feature"], data["scene"]
    result = dict(session=scene["session"], split=scene["split"], phase=phase, candidate=candidate_id,
                  side=side, row=row, decision_index=int(feature["decision_index"][row]),
                  physical_line=int(feature["physical_line"][row]), decision_time=float(feature["time"][row]),
                  entry_index=int(label["entry_index"][row]), entry_time=None,
                  entry_price=None, status=int(label["primary_status"][row, column]),
                  opposite_status=int(label["primary_status"][row, opposite]),
                  last_status=int(label["last_status"][row, column]),
                  resolution_index=int(label["primary_resolution_index"][row, column]),
                  resolution_time=None)
    for target, value in (("entry_time", label["entry_time"][row]), ("entry_price", label["entry_price"][row, column]),
                          ("resolution_time", label["primary_resolution_time"][row, column])):
        result[target] = float(value) if np.isfinite(value) else None
    for key in ("entry_price_clock_gap_s", "entry_cross_phase", "entry_gap_gt60", "path_gap", "path_bad_bbo", "primary_path_gap", "primary_path_bad_bbo", "last_path_gap", "last_path_bad_bbo"):
        if key in label:
            value = label[key][row]
            if np.ndim(value):
                value = value[column]
            result[key] = float(value) if np.isfinite(value) else None
    return result


def collect_events(data, long_signal, short_signal, candidate_id, phase, pulse=False):
    """条件エッジ・未決ロック・60秒間隔で予測を間引く。

    引数: data(dict)、long_signal/short_signal(ndarray[bool])、candidate_id/phase(str)、pulse(bool)。
    返り値: list[dict]。busy中もエッジ状態を更新し、未来の決着で過去の入口を作らない。
    """
    feature = data["feature"]
    times, indices = feature["time"], feature["decision_index"]
    phases = feature["phase"].astype(str)
    previous_long = previous_short = False
    busy_until = -1
    permanently_busy = False
    last_decision = -math.inf
    events = []
    for row, (at, index) in enumerate(zip(times, indices)):
        current_long = bool(long_signal[row]) and phases[row] == phase
        current_short = bool(short_signal[row]) and phases[row] == phase
        edge_long = current_long and (pulse or not previous_long)
        edge_short = current_short and (pulse or not previous_short)
        previous_long, previous_short = current_long, current_short
        if permanently_busy or index <= busy_until or at - last_decision < COOLDOWN:
            continue
        if current_long == current_short:
            continue
        if not (edge_long if current_long else edge_short):
            continue
        side = 1 if current_long else -1
        event = label_event(data, row, side, candidate_id, phase)
        events.append(event)
        last_decision = at
        resolution = event["resolution_index"]
        if resolution < 0:
            permanently_busy = True
        else:
            busy_until = resolution
            if resolution < event["entry_index"] or resolution < index:
                raise ValueError("決着が判断又は実新規より前です")
    return events


def evaluate_candidate(data, candidate, phase, models):
    """手動又は固定学習候補を同じ間引き規則で採点する。

    引数: data(dict)、candidate(dict)、phase(str)、models(dict)。返り値: list[dict]。
    """
    if not np.any(data["feature"]["phase"].astype(str) == phase):
        return []
    if candidate["kind"] == "manual":
        signals = [manual_signal(data["f"], candidate, side) for side in (1, -1)]
    else:
        trained = models.get(phase)
        if trained is None:
            return []
        valid = model_eligible(data["f"])
        cache = data.setdefault("_model_scores", {})
        scores = []
        for side in (1, -1):
            key = (phase, candidate["family"], side)
            if key not in cache:
                cache[key] = predict(transform(model_matrix(data["f"], side), trained["preprocess"]), trained[candidate["family"]])
            scores.append(cache[key])
        signals = [(score >= candidate["threshold"]) & valid for score in scores]
    return collect_events(data, *signals, candidate["id"], phase)


def evaluate_baselines(data, phase):
    """60秒固定格子の常時買い・常時売り・決定的コイントスを採点する。

    引数: data(dict)、phase(str)。返り値: dict[str,list]。
    各対照も一予測未決中は再参加せず、候補の反転採用には使わない。
    """
    feature, scene = data["feature"], data["scene"]
    if not np.any(feature["phase"].astype(str) == phase):
        return {}
    pulse = anchor_mask(feature["time"], scene["start"], 60)
    eligible = (data["f"]["spread"] > 0) & (data["f"]["spread"] <= 20)
    pulse &= eligible
    slots = np.floor((feature["time"] - scene["start"]) / 60).astype(np.int64)
    directions = np.array([int(hashlib.sha256(f"161:{scene['session']}:{slot}".encode()).hexdigest()[:8], 16) % 2 == 0 for slot in slots])
    zero = np.zeros(len(pulse), dtype=bool)
    return {"基準_常時買い": collect_events(data, pulse, zero, "基準_常時買い", phase, True),
            "基準_常時売り": collect_events(data, zero, pulse, "基準_常時売り", phase, True),
            "基準_固定コイントス": collect_events(data, pulse & directions, pulse & ~directions, "基準_固定コイントス", phase, True)}


def wilson(wins, count, z=1.959963984540054):
    """独立性を仮定した参考Wilson区間を算出する。

    引数: wins/count(int)、z(float)。返り値: list[float]又はNone。
    同波の独立性は保証せず、場単位区間を主に使う。
    """
    if count == 0:
        return None
    p = wins / count
    center = (p + z*z / (2*count)) / (1 + z*z/count)
    radius = z * math.sqrt(p*(1-p)/count + z*z/(4*count*count)) / (1 + z*z/count)
    return [center-radius, center+radius]


def summarize(events, session_names):
    """未決を除外しない成功率と場単位の不確実性を集計する。

    引数: events(list[dict])、session_names(list[str])。返り値: dict。
    全候補分母と解決例分母、初回玉勝率、金額利益率を混同しない。
    """
    n = len(events)
    status = Counter(e["status"] for e in events)
    names = list(session_names)
    counts = np.array([sum(e["session"] == name for e in events) for name in names])
    wins = np.array([sum(e["session"] == name and e["status"] == 1 for e in events) for name in names])
    matched = np.array([sum(e["session"] == name and e["opposite_status"] == 1 for e in events) for name in names])
    interval = difference_interval = None
    if n and names:
        rng = np.random.default_rng(SEED)
        draws = rng.integers(0, len(names), size=(4000, len(names)))
        denominator = counts[draws].sum(axis=1)
        valid = denominator > 0
        if valid.any():
            success = wins[draws].sum(axis=1)[valid] / denominator[valid]
            difference = (wins-matched)[draws].sum(axis=1)[valid] / denominator[valid]
            interval = np.quantile(success, [.025, .975]).tolist()
            difference_interval = np.quantile(difference, [.025, .975]).tolist()
    success_count = status[1]
    failure_count = status[-1]
    side_counts = {str(side): dict(events=sum(e["side"] == side for e in events),
                                   successes=sum(e["side"] == side and e["status"] == 1 for e in events),
                                   adverse_first=sum(e["side"] == side and e["status"] == -1 for e in events)) for side in (1, -1)}
    quality = {key: dict(recorded=sum(key in e for e in events),
                        positive=sum(e.get(key) is not None and e.get(key, 0) > 0 for e in events),
                        success_with_positive=sum(e.get(key) is not None and e.get(key, 0) > 0 and e["status"] == 1 for e in events))
               for key in ("entry_cross_phase", "path_gap", "path_bad_bbo", "primary_path_gap", "primary_path_bad_bbo")}
    return dict(events=n, successes=success_count, adverse_first=failure_count,
                unresolved=status[0], no_entry=status[-2], active_sessions=int((counts > 0).sum()),
                total_sessions=len(names), long_events=sum(e["side"] == 1 for e in events),
                short_events=sum(e["side"] == -1 for e in events),
                success_probability=success_count/n if n else None,
                resolved_probability=success_count/(success_count+failure_count) if success_count+failure_count else None,
                resolution_rate=(success_count+failure_count)/n if n else None,
                wilson95=wilson(success_count, n), session_cluster95=interval,
                opposite_success_probability=sum(e["opposite_status"] == 1 for e in events)/n if n else None,
                paired_difference_cluster95=difference_interval,
                last_success_probability=sum(e["last_status"] == 1 for e in events)/n if n else None,
                max_session_share=float(counts.max()/n) if n else None,
                by_side=side_counts, observation_quality=quality,
                sessions=[dict(session=name, count=int(count), successes=int(win)) for name, count, win in zip(names, counts, wins)])


def eligibility(summary, stage):
    """事前固定した最小件数・方向・場分布の条件を検査する。

    引数: summary(dict)、stage(str)。返り値: list[str]。空なら適格。
    """
    minimum, scenes, one_side, maximum_share = (40, 8, 5, .30) if stage == "train" else (15, 3, 2, .50)
    reasons = []
    for failed, name in ((summary["events"] < minimum, "件数不足"),
                         (summary["active_sessions"] < scenes, "活動場数不足"),
                         (min(summary["long_events"], summary["short_events"]) < one_side, "片方向件数不足"),
                         (summary["max_session_share"] is None or summary["max_session_share"] > maximum_share, "一場集中")):
        if failed:
            reasons.append(name)
    return reasons


def select_final(reports):
    """各phaseから適格な一候補だけをvalidation順位で選ぶ。

    引数: reports(dict[phase,dict])。返り値: dict。該当なしを無理に埋めない。
    """
    selected = {}
    for phase, records in reports.items():
        eligible = []
        for key, record in records.items():
            if record["train_exclusions"] or record["validation_exclusions"]:
                continue
            validation = record["validation"]
            lower = min(validation["wilson95"][0], validation["session_cluster95"][0])
            eligible.append((lower, validation["success_probability"], validation["events"], key))
        if eligible:
            # 同点は名称昇順とし、成績確認後の裁量選択をしません。
            eligible.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3]))
            selected[phase] = eligible[0][3]
    return selected


def validate_manifest(manifest):
    """53場の期間分割が日付固定と一致することを検査する。

    引数: manifest(dict)。返り値: list[dict]。
    """
    scenes = manifest["sessions"]
    if len(scenes) != 53 or len({s["session"] for s in scenes}) != 53:
        raise ValueError("53場の一意な入力が必要です")
    for scene in scenes:
        date = scene["session"][:10]
        expected = "train" if date <= "2026-10-09" else "validation" if date <= "2026-10-16" else "test"
        if scene["split"] != expected:
            raise ValueError("事前固定した期間分割と異なります")
    if Counter(s["split"] for s in scenes) != {"train": 30, "validation": 10, "test": 13}:
        raise ValueError("期間の場数が異なります")
    return scenes


def train_models(scenes, data_root, access_log):
    """train固定5分アンカーだけで二種類のモデルを学習する。

    引数: scenes(list[dict])、data_root(Path)、access_log(list)。返り値: dict。
    """
    buffers = {phase: [] for phase in PHASES}
    for scene in scenes:
        if scene["split"] != "train":
            continue
        data = load_scene(scene, data_root, {"train"}, access_log)
        feature = data["feature"]
        anchors = anchor_mask(feature["time"], scene["start"], 300) & model_eligible(data["f"])
        for phase in PHASES:
            mask = anchors & (feature["phase"].astype(str) == phase)
            for column, side in enumerate((1, -1)):
                if mask.any():
                    buffers[phase].append((model_matrix(data["f"], side)[mask], (data["label"]["primary_status"][mask, column] == 1).astype(float), scene["session"]))
    models = {}
    for phase, values in buffers.items():
        if not values:
            continue
        x, y = np.concatenate([v[0] for v in values]), np.concatenate([v[1] for v in values])
        scene_counts = Counter()
        for matrix, _, scene in values:
            scene_counts[scene] += len(matrix)
        weight = np.concatenate([np.full(len(matrix), 1 / scene_counts[scene]) for matrix, _, scene in values])
        preprocess = fit_preprocess(x)
        transformed = transform(x, preprocess)
        models[phase] = dict(preprocess=preprocess, GL=fit_logit(transformed, y, weight),
                             DT=fit_tree(transformed, y, weight), train_rows=len(y),
                             train_scenes=dict(scene_counts), train_successes=int(y.sum()))
    return models


def execute_train(args):
    """登録後にtrain/validationだけを測り候補とモデルを凍結する。

    引数: args(argparse.Namespace)。返り値: None。testファイルは開かない。
    """
    require_registration(args.receipt, "train_validation", args.spec, args.manifest)
    scenes = validate_manifest(read_json(args.manifest))
    out = Path(args.out)
    if (out / "selection_frozen161.json").exists():
        raise ValueError("既に選択済みです。上書きしません")
    access = []
    models = train_models(scenes, args.data, access)
    all_candidates = candidates()
    events = {stage: {phase: {c["id"]: [] for c in all_candidates} for phase in PHASES} for stage in ("train", "validation")}
    baselines = {stage: {phase: {} for phase in PHASES} for stage in events}
    for scene in scenes:
        stage = scene["split"]
        if stage not in events:
            continue
        data = load_scene(scene, args.data, {"train", "validation"}, access)
        for phase in PHASES:
            for candidate in all_candidates:
                events[stage][phase][candidate["id"]].extend(evaluate_candidate(data, candidate, phase, models))
            for key, rows in evaluate_baselines(data, phase).items():
                baselines[stage][phase].setdefault(key, []).extend(rows)
    reports = {phase: {} for phase in PHASES}
    baseline_reports = {phase: {} for phase in PHASES}
    for phase in PHASES:
        phase_kind = "Day" if phase == "Day" else "Night"
        names = {stage: [s["session"] for s in scenes if s["split"] == stage and s["kind"] == phase_kind] for stage in events}
        for candidate in all_candidates:
            key = candidate["id"]
            tr = summarize(events["train"][phase][key], names["train"])
            va = summarize(events["validation"][phase][key], names["validation"])
            reports[phase][key] = dict(train=tr, validation=va,
                                       train_exclusions=eligibility(tr, "train"), validation_exclusions=eligibility(va, "validation"))
        for stage in events:
            baseline_reports[phase][stage] = {key: summarize(rows, names[stage]) for key, rows in baselines[stage][phase].items()}
    selection = select_final(reports)
    frozen = dict(selected=selection, models=models, spec_sha256=digest(args.spec),
                  manifest_sha256=digest(args.manifest), candidates_sha256=canonical_digest(all_candidates),
                  selection_rule="各phaseで適格候補のvalidation保守下限最大。反対方向成績は順位に使わない。",
                  test_opened=False, metadata="全場は既知開発資料。train固定5分アンカーとval条件エッジの分布は異なる。")
    frozen["content_sha256"] = canonical_digest(frozen)
    write_json(out / "train_validation161.json", dict(reports=reports, baselines=baseline_reports, events=events, access=access))
    write_json(out / "selection_frozen161.json", frozen)


def execute_test(args):
    """候補凍結後に選択済み最大三条件だけを後半で一度採点する。

    引数: args(argparse.Namespace)。返り値: None。再選択は実装しない。
    """
    require_registration(args.receipt, "locked_test", args.spec, args.manifest, args.freeze)
    frozen = read_json(args.freeze)
    check = {key: value for key, value in frozen.items() if key != "content_sha256"}
    if canonical_digest(check) != frozen["content_sha256"]:
        raise ValueError("選択済み内容が変更されています")
    if frozen["spec_sha256"] != digest(args.spec) or frozen["manifest_sha256"] != digest(args.manifest):
        raise ValueError("選択後に仕様又は入力が変わっています")
    candidate_map = {c["id"]: c for c in candidates()}
    if frozen["candidates_sha256"] != canonical_digest(candidates()) or len(frozen["selected"]) > 3:
        raise ValueError("候補集合又は最終数が変わっています")
    out = Path(args.out) / "locked_test161.json"
    if out.exists():
        raise ValueError("testは既に採点済みです。再実行しません")
    scenes = validate_manifest(read_json(args.manifest))
    access, events = [], {phase: [] for phase in frozen["selected"]}
    baselines = {phase: {} for phase in events}
    for scene in scenes:
        if scene["split"] != "test" or not events:
            continue
        data = load_scene(scene, args.data, {"test"}, access)
        for phase, key in frozen["selected"].items():
            events[phase].extend(evaluate_candidate(data, candidate_map[key], phase, frozen["models"]))
            for name, rows in evaluate_baselines(data, phase).items():
                baselines[phase].setdefault(name, []).extend(rows)
    reports, baseline_reports = {}, {}
    for phase in events:
        kind = "Day" if phase == "Day" else "Night"
        names = [s["session"] for s in scenes if s["split"] == "test" and s["kind"] == kind]
        reports[phase] = summarize(events[phase], names)
        baseline_reports[phase] = {key: summarize(rows, names) for key, rows in baselines[phase].items()}
    write_json(out, dict(selected=frozen["selected"], freeze_sha256=digest(args.freeze), reports=reports,
                         baselines=baseline_reports, events=events, access=access,
                         warning="この後半も過去研究で既知。今回の条件選択には不使用。結果を見た修正は新探索であり再認証しない。"))


def main():
    """登録受領が必須の段階別コマンドを起動する。

    引数: コマンドライン引数。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("train_validation", "locked_test"))
    for name in ("receipt", "manifest", "spec", "data", "out"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--freeze")
    args = parser.parse_args()
    (execute_train if args.stage == "train_validation" else execute_test)(args)


if __name__ == "__main__":
    main()
