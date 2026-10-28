"""完了許可後だけ保存された新入口を原板の単純走査で独立検算する。"""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
PHASES = ("Day", "preUS", "postUS")
DIRECTIONAL = ("ret5_pt", "ret15_pt", "ret60_pt", "ret120_pt", "ret300_pt", "ret5_lag5_pt", "accel5_15_pt_s", "ofi5", "ofi15", "depth_imb", "imb1", "microprice_offset_pt", "peer_ret15_bp", "peer_ret60_bp")
UNDIRECTED = ("spread", "range60_pt", "range60_previous_pt", "er60", "peer_age_s")


def read(path):
    """UTF-8の確定JSONを読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    """保存内容の指紋を返す。

    引数: path(Path)。返り値: str。
    """
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def same(actual, expected, context=""):
    """入れ子の公開集計を許容差内で照合する。

    引数: actual/expected(object)、context(str)。返り値: None。不一致は例外。
    """
    if isinstance(expected, dict):
        for key, value in expected.items():
            assert key in actual, (context, key, "欠測")
            same(actual[key], value, context+"/"+str(key))
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected), context
        for n, (a, b) in enumerate(zip(actual, expected)):
            same(a, b, context+f"/{n}")
    elif expected is None:
        assert actual is None, (context, actual, expected)
    elif isinstance(expected, (int, float, np.number)):
        assert math.isclose(float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-10), (context, actual, expected)
    else:
        assert actual == expected, (context, actual, expected)


def raw_market(scene, symbol="NK225"):
    """独立読取りで物理順を保った価格時計/BBO/数量列を作る。

    引数: scene(dict)、symbol(str)。返り値: ndarray の時刻/Last/Bid/Ask/買量/売量/物理行。
    """
    path = Path(scene["books"][symbol]); h = hashlib.sha256()
    before = path.stat(); rows = []; prior = scene["start"]
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            h.update(line)
            obj = json.loads(line)
            clock = obj.get("CurrentPriceTime")
            if not isinstance(clock, str):
                continue
            try:
                t = datetime.fromisoformat(clock).timestamp()
            except (ValueError, TypeError):
                continue
            if t < scene["start"] or t > scene["end"] or t >= scene["cutoff"] or t < prior:
                continue
            last = float(obj.get("CurrentPrice") or 0)
            if not math.isfinite(last) or last <= 0:
                continue
            prior = t
            buy, sell = obj.get("Buy1") or {}, obj.get("Sell1") or {}
            rows.append([t, last, float(buy.get("Price") or 0), float(sell.get("Price") or 0),
                         float(buy.get("Qty") or 0), float(sell.get("Qty") or 0), line_number])
    after = path.stat()
    expected = next(x["sha256"] for x in scene["fingerprints"] if Path(x["path"]) == path)
    assert h.hexdigest() == expected, str(path)
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), str(path)
    return np.asarray(rows, dtype=float)


def normal(raw):
    """正常なラージBBOを数量資格と独立に判定する。

    引数: raw(ndarray)。返り値: ndarray[bool]。
    """
    return np.isfinite(raw[:, 2]) & np.isfinite(raw[:, 3]) & (raw[:, 2] > 0) & (raw[:, 3] > raw[:, 2])


def first_hit(raw, entry, side, mode="primary"):
    """原行を先頭から単純走査し100/50の最初到達を求める。

    引数: raw(ndarray)、entry/side(int)、mode(str)。返り値: dict。
    """
    mask = normal(raw)
    end = len(raw)-1 if mode == "last" else int(np.flatnonzero(mask)[-1])
    base = raw[entry, 1] if mode == "last" else raw[entry, 3 if side == 1 else 2]
    up = down = -1
    for i in range(entry, end+1):
        if mode == "primary" and not mask[i]:
            continue
        px = raw[i, 1] if mode == "last" else raw[i, 2 if side == 1 else 3]
        distance = side*(px-base)
        if distance >= 100 and up < 0:
            up = i
        if distance <= -50 and down < 0:
            down = i
        if up >= 0 and down >= 0:
            break
    if up < 0 and down < 0:
        status, hit = 0, -1
    elif up >= 0 and (down < 0 or up < down):
        status, hit = 1, up
    else:
        status, hit = -1, down
    stop = hit if hit >= 0 else end
    return dict(status=status, up=up, down=down, hit=hit, hit_time=float(raw[stop, 0]),
                path_bad_bbo=int((~mask[entry:stop+1]).sum()),
                path_gap=int(np.any(np.diff(raw[entry:stop+1, 0]) > 15)),
                path_gap_gt60=int(np.any(np.diff(raw[entry:stop+1, 0]) > 60)),
                end=stop, base=float(base))


def model_probability(f, side, trained, family):
    """固定係数/木から別実装で学習スコアを再計算する。

    引数: f(dict)、side(int)、trained(dict)、family(str)。返り値: ndarray。
    """
    cols = [f[k]*side for k in DIRECTIONAL] + [f[k] for k in UNDIRECTED]
    cols += [side*(f["pos60"]-.5), side*(f["bid_refill15"]-f["ask_refill15"])]
    x = np.stack(cols, axis=1); missing = ~np.isfinite(x); pre = trained["preprocess"]
    imputed = np.where(missing, np.asarray(pre["median"]), x)
    z = np.clip((imputed-np.asarray(pre["mean"]))/np.asarray(pre["std"]), -8, 8)
    matrix = np.concatenate([z, missing.astype(float)], axis=1)
    model = trained[family]
    if family == "GL":
        coefficients = np.asarray(model["coefficient"])
        value = np.clip(matrix @ coefficients[1:] + coefficients[0], -35, 35)
        return 1/(1+np.exp(-value))
    result = np.empty(len(matrix))
    pending = [(model, np.arange(len(matrix)))]
    while pending:
        node, positions = pending.pop()
        if "column" not in node:
            result[positions] = node["probability"]
            continue
        left = matrix[positions, node["column"]] <= node["threshold"]
        pending.extend([(node["left"], positions[left]), (node["right"], positions[~left])])
    return result


def signals(f, candidate, side, model):
    """登録条件を別実装で判定し、未来ラベルは入力しない。

    引数: f/candidate/model(dict)、side(int)。返り値: ndarray[bool]。
    """
    good = np.isfinite(f["spread"]) & (f["spread"] > 0) & (f["spread"] <= 20)
    if candidate["kind"] == "learned":
        matrix = np.stack([f[k]*side for k in DIRECTIONAL]+[f[k] for k in UNDIRECTED]
                          +[side*(f["pos60"]-.5), side*(f["bid_refill15"]-f["ask_refill15"])], axis=1)
        good &= np.isfinite(f["ret15_pt"]) & np.isfinite(f["ret60_pt"]) & (np.isfinite(matrix).sum(axis=1) >= 12)
        return good & (model_probability(f, side, model, candidate["family"]) >= candidate["threshold"])
    level = candidate["level"]; family = candidate["family"]
    d5, d15, d60 = side*f["ret5_pt"], side*f["ret15_pt"], side*f["ret60_pt"]
    if family == "M":
        x = (d5 >= [10,20,30][level]) & (d15 >= [20,30,40][level]) & (f["er60"] >= [.20,.35,.50][level])
    elif family == "A":
        x = (d5 >= [10,20,30][level]) & (side*(f["vel5_pt_s"]-f["vel15_pt_s"]) >= [1,2,3][level]) & (d15 >= 0) & (d60 >= 0) & (side*f["ofi5"] >= 0)
    elif family == "P":
        x = (side*f["ret120_pt"] >= [40,60,80][level]) & (side*f["ret5_lag5_pt"] <= -[10,20,30][level]) & (d5 >= [10,20,30][level]) & (d15 <= 10)
    elif family == "R":
        x = (d60 <= -[40,60,80][level]) & (d15 >= 0) & (d5 >= [10,20,30][level]) & (side*f["ofi5"] >= 0)
    elif family == "B":
        position = f["pos60"] if side == 1 else 1-f["pos60"]
        x = (side*f["depth_imb"] >= [.20,.35,.50][level]) & (side*f["ofi15"] >= [.10,.20,.35][level]) & (d15 >= [0,10,20][level]) & (position >= .6)
    elif family == "S":
        refill = f["bid_refill15" if side == 1 else "ask_refill15"]
        x = (side*f["ofi15"] <= -[.10,.20,.35][level]) & (d15 >= -[10,10,20][level]) & (d5 >= [10,20,20][level]) & (refill >= [.20,.40,.60][level])
    elif family == "L":
        peer = side*f["peer_ret60_bp"]
        x = (peer >= [1,2,3][level]) & (d60/f["mid"]*10000 <= peer*.5) & (d60 >= -10) & (d5 >= [0,10,20][level]) & (f["peer_age_s"] <= [5,5,3][level])
    elif family == "C":
        breakout = f["mid"]-f["high60_prev"] if side == 1 else f["low60_prev"]-f["mid"]
        x = (f["range60_previous_pt"] <= [80,60,40][level]) & (f["range60_pt"] >= 1.2*f["range60_previous_pt"]) & (d15 >= [20,30,40][level]) & (breakout >= [0,10,10][level]) & (side*f["ofi5"] >= 0)
    else:
        raise AssertionError(family)
    return good & x


def summarize(events, names):
    """全信号分母と場単位区間を別コードで再集計する。

    引数: events(list)、names(list[str])。返り値: dict。
    """
    n = len(events); status = Counter(e["status"] for e in events)
    counts = np.array([sum(e["session"] == s for e in events) for s in names])
    wins = np.array([sum(e["session"] == s and e["status"] == 1 for e in events) for s in names])
    reverse = np.array([sum(e["session"] == s and e["opposite_status"] == 1 for e in events) for s in names])
    wilson = cluster = difference = None
    if n:
        z = 1.959963984540054; p = status[1]/n; den = 1+z*z/n
        center = (p+z*z/(2*n))/den
        half = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
        wilson = [center-half, center+half]
        rng = np.random.default_rng(610161)
        ix = rng.integers(0, len(names), size=(4000,len(names)))
        total = counts[ix].sum(axis=1); valid = total > 0
        if valid.any():
            cluster = np.quantile(wins[ix].sum(axis=1)[valid]/total[valid], [.025,.975]).tolist()
            difference = np.quantile((wins-reverse)[ix].sum(axis=1)[valid]/total[valid], [.025,.975]).tolist()
    return dict(events=n, successes=status[1], adverse_first=status[-1], unresolved=status[0], no_entry=status[-2],
        active_sessions=int((counts>0).sum()), total_sessions=len(names), long_events=sum(e["side"]==1 for e in events), short_events=sum(e["side"]==-1 for e in events),
        success_probability=status[1]/n if n else None, resolved_probability=status[1]/(status[1]+status[-1]) if status[1]+status[-1] else None,
        resolution_rate=(status[1]+status[-1])/n if n else None, wilson95=wilson, session_cluster95=cluster,
        opposite_success_probability=sum(e["opposite_status"]==1 for e in events)/n if n else None,
        paired_difference_cluster95=difference, last_success_probability=sum(e["last_status"]==1 for e in events)/n if n else None,
        max_session_share=float(counts.max()/n) if n else None,
        sessions=[dict(session=s,count=int(c),successes=int(w)) for s,c,w in zip(names,counts,wins)])


def exclusions(stats, stage):
    """固定の選択最低条件を独立判定する。

    引数: stats(dict)、stage(str)。返り値: list[str]。
    """
    need = [40,8,5,.3] if stage == "train" else [15,3,2,.5]
    tests = [stats["events"] < need[0], stats["active_sessions"] < need[1], min(stats["long_events"],stats["short_events"]) < need[2], stats["max_session_share"] is None or stats["max_session_share"] > need[3]]
    return [label for label, flag in zip(["件数不足","活動場数不足","片方向件数不足","一場集中"],tests) if flag]


def check_event_order(events, scenes, phase):
    """保存全候補の重複・未決中の再採用・区分誤帰属を検査する。

    引数: events(list)、scenes(dict)、phase(str)。返り値: None。
    """
    previous={}; unique=set()
    for event in events:
        name=event["session"]; scene=scenes[name]
        key=(name,event["decision_index"])
        assert key not in unique and event["side"] in (-1,1),key
        unique.add(key)
        actual_phase="Day" if scene["kind"]=="Day" else "preUS" if event["decision_time"]<scene["us_open"] else "postUS"
        assert event["phase"]==phase==actual_phase
        assert event["split"]==scene["split"]
        if name in previous:
            old=previous[name]
            assert old["resolution_index"]>=0,(name,"未決中に再採用")
            assert event["decision_index"]>old["resolution_index"],(name,"重複する予測")
            assert event["decision_time"]-old["decision_time"]>=60,(name,"60秒未満")
        previous[name]=event


def audit_scene(scene, selected, candidates, models, expected, feature_path):
    """選択候補の全時点条件・edge・先着を一場ずつ再構築する。

    引数: scene/selected/candidates/models/expected(dict)、feature_path(str)。返り値: dict は独立原行検算。
    """
    data_path = Path(feature_path)
    with np.load(data_path, allow_pickle=False) as z:
        feature = {k:z[k].copy() for k in z.files}
    metadata = json.loads(str(feature["metadata"]))
    assert metadata["session"] == scene["session"] and metadata["split"] == scene["split"]
    raw = raw_market(scene); valid = normal(raw); normal_rows = np.flatnonzero(valid)
    f = {str(name):feature["features"][:,n] for n,name in enumerate(feature["feature_names"])}
    observed = []; prior = None
    for i in normal_rows:
        if raw[i,0] != prior:
            observed.append(int(i)); prior=raw[i,0]
    assert observed == feature["decision_index"].tolist(), scene["session"]
    np.testing.assert_array_equal(feature["time"], raw[observed,0])
    np.testing.assert_array_equal(feature["physical_line"], raw[observed,6])
    phases = np.array(PHASES)[feature["phase"]]
    output = []; quote_checks = 0
    for phase, candidate_id in selected.items():
        candidate = candidates[candidate_id]
        if not np.any(phases == phase):
            continue
        ls = signals(f,candidate,1,models.get(phase)); ss = signals(f,candidate,-1,models.get(phase))
        prev = [False,False]; until=-1; last=-math.inf; permanently=False; rebuilt=[]
        for row,index in enumerate(observed):
            now = [bool(ls[row]) and phases[row]==phase, bool(ss[row]) and phases[row]==phase]
            edges = [now[s] and not prev[s] for s in (0,1)]; prev=now
            t=raw[index,0]
            if permanently or index <= until or t-last < 60 or now[0]==now[1]:
                continue
            side = 1 if now[0] else -1
            if not edges[0 if side==1 else 1]:
                continue
            after = normal_rows[normal_rows > index]
            if not len(after):
                event = dict(session=scene["session"],split=scene["split"],phase=phase,candidate=candidate_id,side=side,row=row,
                    decision_index=index,physical_line=int(raw[index,6]),decision_time=float(t),entry_index=-1,entry_time=None,entry_price=None,
                    status=-2,opposite_status=-2,last_status=-2,resolution_index=-1,resolution_time=float(raw[normal_rows[-1],0]))
                permanently=True
            else:
                entry=int(after[0]); a=first_hit(raw,entry,side); b=first_hit(raw,entry,-side); c=first_hit(raw,entry,side,"last")
                cross = scene["kind"]=="Night" and ((t<scene["us_open"]) != (raw[entry,0]<scene["us_open"]))
                event=dict(session=scene["session"],split=scene["split"],phase=phase,candidate=candidate_id,side=side,row=row,
                    decision_index=index,physical_line=int(raw[index,6]),decision_time=float(t),entry_index=entry,entry_time=float(raw[entry,0]),entry_price=a["base"],
                    status=a["status"],opposite_status=b["status"],last_status=c["status"],resolution_index=a["hit"],resolution_time=a["hit_time"],
                    entry_price_clock_gap_s=float(raw[entry,0]-t),entry_cross_phase=float(cross),entry_gap_gt60=float(raw[entry,0]-t>60),
                    path_bad_bbo=float(a["path_bad_bbo"]),path_gap=float(a["path_gap"]),primary_path_bad_bbo=float(a["path_bad_bbo"]),primary_path_gap=float(a["path_gap"]),
                    last_path_bad_bbo=float(c["path_bad_bbo"]),last_path_gap=float(c["path_gap"]))
                if a["hit"] < 0:
                    permanently=True
                else:
                    until=a["hit"]
            last=t; rebuilt.append(event)
            # ----------------------------------------
            # 採用された入口の自己差分は、生成器を使わず元価格端点からも照合する。
            mid=(raw[index,2]+raw[index,3])/2
            same(f["mid"][row],mid,scene["session"]+"/mid")
            for window in [5,15,30,60,120,300]:
                prior_rows=normal_rows[raw[normal_rows,0] <= t-window]
                known=len(prior_rows)>0 and t-window-raw[prior_rows[-1],0] <= 15
                value=f[f"ret{window}_pt"][row]
                if known:
                    ix=prior_rows[-1]; expected_change=mid-(raw[ix,2]+raw[ix,3])/2
                    same(value,expected_change,scene["session"]+f"/ret{window}")
                    same(f[f"vel{window}_pt_s"][row],expected_change/(t-raw[ix,0]),scene["session"]+f"/vel{window}")
                else:
                    assert np.isnan(value)
                quote_checks+=1
        saved=expected.get(phase,[])
        assert len(saved)==len(rebuilt),(scene["session"],phase,len(saved),len(rebuilt))
        for original,recalculated in zip(saved,rebuilt):
            same(original,recalculated,scene["session"]+"/"+phase)
        output += rebuilt
    return dict(session=scene["session"],split=scene["split"],passed=True,raw_rows=len(raw),normal_rows=len(normal_rows),
                events=len(output),feature_endpoint_checks=quote_checks,proof=output)


def main():
    """rootのtest正常完了許可を確認してから事後監査を一度だけ実行する。

    引数: CLI --completion(Path)、--workers(int)。返り値: None。
    """
    parser=argparse.ArgumentParser(); parser.add_argument("--completion",type=Path,required=True); parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args(); permit=read(args.completion)
    assert permit.get("completed") is True and permit.get("root_completed") is True
    assert type(permit.get("returncode")) is int and permit["returncode"]==0
    test_path=WORK/"results/locked_test161.json"; freeze_path=WORK/"results/selection_frozen161.json"
    assert sha(test_path)==permit["locked_test_sha256"] and sha(freeze_path)==permit["freeze_sha256"]
    target=HERE/"audit161.json"; assert not target.exists(), "確定監査を上書きしない"
    manifest=read(WORK/"inputs161.json"); scenes=manifest["sessions"]
    scene_by_id={s["session"]:s for s in scenes}
    train=read(WORK/"results/train_validation161.json"); test=read(test_path); frozen=read(freeze_path)
    candidates={c["id"]:c for c in read(WORK/"search/candidates161.json")}; assert len(candidates)==34
    for record in read(HERE/"preflight161.json")["sources"]:
        assert sha(ROOT/record["path"])==record["sha256"],record["path"]
    assert frozen["test_opened"] is False
    assert test["selected"]==frozen["selected"] and test["freeze_sha256"]==sha(freeze_path)
    assert all(x["split"] in {"train","validation"} for x in train["access"])
    assert all(x["split"]=="test" for x in test["access"])
    for record in train["access"]+test["access"]:
        assert sha(record["features"])==record["feature_sha256"] and sha(record["labels"])==record["label_sha256"]
    feature_paths={record["session"]:record["features"] for record in train["access"]+test["access"]}
    summary_checks=0; chosen={}
    for phase in PHASES:
        ranking=[]; kind="Day" if phase=="Day" else "Night"
        for key in candidates:
            recomputed={}
            for stage in ["train","validation"]:
                names=[s["session"] for s in scenes if s["kind"]==kind and s["split"]==stage]
                events=train["events"][stage][phase][key]
                check_event_order(events,scene_by_id,phase)
                stats=summarize(events,names); same(train["reports"][phase][key][stage],stats,phase+"/"+key+"/"+stage)
                fails=exclusions(stats,stage); assert fails==train["reports"][phase][key][stage+"_exclusions"]
                recomputed[stage]=(stats,fails); summary_checks+=1
            if not recomputed["train"][1] and not recomputed["validation"][1]:
                s=recomputed["validation"][0]
                ranking.append((min(s["wilson95"][0],s["session_cluster95"][0]),s["success_probability"],s["events"],key))
        if ranking:
            ranking.sort(key=lambda x:(-x[0],-x[1],-x[2],x[3])); chosen[phase]=ranking[0][3]
    assert chosen==frozen["selected"],(chosen,frozen["selected"])
    for phase,events in test["events"].items():
        check_event_order(events,scene_by_id,phase)
        kind="Day" if phase=="Day" else "Night"
        names=[s["session"] for s in scenes if s["kind"]==kind and s["split"]=="test"]
        same(test["reports"][phase],summarize(events,names),"test/"+phase); summary_checks+=1
    # ----------------------------------------
    # 最大3選択候補を全期間へ同じ独立式で適用。新しい候補の発見や選び直しはしない。
    rows=[]; workers=max(1,min(args.workers,4))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs={}
        for scene in scenes:
            expected={}
            for phase,key in chosen.items():
                all_events=test["events"][phase] if scene["split"]=="test" else train["events"][scene["split"]][phase][key]
                expected[phase]=[e for e in all_events if e["session"]==scene["session"]]
            jobs[pool.submit(audit_scene,scene,chosen,candidates,frozen["models"],expected,feature_paths[scene["session"]])]=scene["session"]
        for future in as_completed(jobs):
            result=future.result(); rows.append(result)
            destination=HERE/"結果照合"/(result["session"]+".json"); destination.parent.mkdir(exist_ok=True)
            destination.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
            print(json.dumps({k:result[k] for k in ["session","events","passed"]},ensure_ascii=False),flush=True)
    for record in read(HERE/"preflight161.json")["sources"]:
        assert sha(ROOT/record["path"])==record["sha256"],record["path"]
    assert sha(test_path)==permit["locked_test_sha256"] and sha(freeze_path)==permit["freeze_sha256"]
    report=dict(passed=True,created_at=datetime.now().astimezone().isoformat(),selected=chosen,sessions=len(rows),
        selected_events=sum(r["events"] for r in rows),summary_checks=summary_checks,
        raw_rows=sum(r["raw_rows"] for r in rows),feature_endpoint_checks=sum(r["feature_endpoint_checks"] for r in rows),
        new_candidate_evaluations=0,financial_replays=0,api_calls=0,
        scope="保存された選択候補を独立実装で照合。新条件採用や学習し直しなし。後半も既知開発資料。",
        proof_files=[dict(path=str((HERE/"結果照合"/(r["session"]+".json")).relative_to(ROOT)),sha256=sha(HERE/"結果照合"/(r["session"]+".json"))) for r in sorted(rows,key=lambda x:x["session"])],
        completion=dict(path=str(args.completion),sha256=sha(args.completion)),
        results=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in [test_path,freeze_path,WORK/"results/train_validation161.json"]])
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["passed","sessions","selected_events","summary_checks"]},ensure_ascii=False))


if __name__=="__main__":
    main()
