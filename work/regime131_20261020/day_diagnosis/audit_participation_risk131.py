"""発注時の値幅だけで追加枚数を変える核と接続を独立人工で検査する。"""

import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time
from zoneinfo import ZoneInfo
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import participation_risk131 as core
import participation_exit131 as previous
import run_risk131 as runner
import register_risk131 as register
import audit_engine131 as helper
import audit_participation131 as addon_helper
import audit_portfolio131 as portfolio


def arguments(data, budget=8., style=0, trail_start=1.25, trail_width=.75, starts=None):
    """
    機能: 人工素材を新18引数へ対応する。
    引数: data(dict)、budget/trail_start/trail_width(float)、style(int)、starts(ndarray又はNone)。
    返り値: dictは新核の引数。
    """
    values = addon_helper.arguments(data, starts, style)
    values.update(trail_start=trail_start, trail_width=trail_width, budget_ticks=budget)
    return values


def run(data, budget=8., style=0, trail_start=1.25, trail_width=.75, starts=None, jit=False):
    """
    機能: 保存市場を使わず、新しい数量核を人工資料へ実行する。
    引数: data(dict)、各設定(float/int)、starts(ndarray又はNone)、jit(bool)。
    返り値: tuple[ndarray,...]は人工注文・親・時価。
    """
    call = core.simulate if jit else core.simulate.py_func
    return call(**arguments(data, budget, style, trail_start, trail_width, starts))


def independent_cash(data, result, label):
    """
    機能: 注文を別の現金会計へ積み、数量と端数料金を検査する。
    引数: data(dict)、result(tuple)、label(str)は人工資料と名称。
    返り値: None。
    """
    orders, trades, curve = result
    ledger = portfolio.expected_ledger(orders[:, :8], data["bid"], data["ask"],
        data["multiplier"], data["fee_per_contract"])
    expected_fees = orders[:, 4].astype(np.int64)*round(data["fee_per_contract"]*10)//10
    helper.equal(label+"注文料金", orders[:, 8], expected_fees)
    helper.equal(label+"全時価", curve[:, 0], ledger["liquidation_equity"])
    helper.equal(label+"全数量", curve[:, 1], ledger["long_quantity"]-ledger["short_quantity"])
    helper.equal(label+"全実現", curve[:, 2], ledger["realized_cash"])
    helper.equal(label+"全返済", orders[orders[:, 7] == 1, 4].sum(), orders[orders[:, 7] == 0, 4].sum())
    helper.equal(label+"親総額", trades[:, 9].sum(), ledger["liquidation_equity"][-1])
    helper.check(label+"整数上限", np.all(orders[:, 4] == orders[:, 4].astype(int)) and
        np.all(orders[:, 4] >= 1) and np.all(orders[:, 4] <= data["quantity"]))
    good = np.flatnonzero(data["qok"] & np.isfinite(data["bid"]) & np.isfinite(data["ask"]) &
        (data["bid"] > 0) & (data["ask"] > data["bid"]))
    for order in orders:
        source, row, side = int(order[1]), int(order[0]), int(order[3])
        expected = good[np.searchsorted(good, source+1)]
        helper.equal(label+"次正常原行"+str(source), row, expected)
        helper.equal(label+"気配"+str(source), order[5], data["ask"][row] if side > 0 else data["bid"][row])


def core_audit():
    """
    機能: 整数境界・単位・鏡像・未来・固定幅・不明・最低1枚を人工で確認する。
    引数: なし。
    返り値: None。
    """
    for quantity, tick, fee, mult in ((5, .5, 41.8, 1000.), (10, 10., 11., 10.)):
        for budget in (8., 12., 16., 24.):
            numerator = quantity*budget*tick
            widths = [8.*tick, numerator/2., numerator/2.-1e-6, numerator/2.+1e-6,
                numerator, numerator+1e-6, 2.*numerator]
            for requested_width in widths:
                for style, start, trail in ((0, 1.25, .75), (1, .75, .5)):
                    data = helper.tape()
                    data.update(quantity=quantity, tick=tick, fee_per_contract=fee, multiplier=mult)
                    data["atr"][:] = requested_width
                    data["h"][:, 3] = 101.
                    data["h"][:, 4] = 99.
                    width = max(requested_width, 8.*tick)
                    expected_qty = max(1, min(quantity, int(np.floor(numerator/width))))
                    result = run(data, budget, style, start, trail)
                    label = f"枚数{quantity}予算{budget}幅{requested_width}方式{style}"
                    helper.equal(label+"期待枚数", result[0][:, 4], np.full(len(result[0]), expected_qty))
                    helper.equal(label+"初期幅", result[1][:, 10], np.array([width]))
                    args = arguments(data, budget, style, start, trail)
                    del args["budget_ticks"]
                    old = previous.simulate.py_func(**args)
                    helper.equal(label+"方向時計価格出口不変", result[0][:, [0,1,2,3,5,6,7,9,10,11]],
                        old[0][:, [0,1,2,3,5,6,7,9,10,11]])
                    helper.equal(label+"幅と経路不変", result[1][:, 10:17], old[1][:, 10:17])
                    helper.equal(label+"粗益の正比例", result[1][:, 7], old[1][:, 7]*expected_qty/quantity)
                    independent_cash(data, result, label)
                    if numerator/width < 1:
                        helper.check(label+"最低1枚で予算超過を隠さない",
                            expected_qty == 1 and expected_qty*width > numerator)
                    if expected_qty == quantity:
                        for i in range(3):
                            helper.equal(label+"基準枚数旧互換"+str(i), result[i], old[i])
    # ----------------------------------------
    # 今回の範囲で1・2・3・4・5枚の料金を独立な整数十分円計算へ照合する。
    for desired in range(1, 6):
        data = helper.tape()
        data.update(quantity=5, tick=.5, fee_per_contract=41.8, multiplier=1000.)
        data["atr"][:] = 20./(desired+.1)
        data["h"][:, 3:5] = [101., 99.]
        result = run(data)
        helper.equal("TOPIX料金数量"+str(desired), result[0][:, 4], [desired, desired])
        helper.equal("TOPIX端数料金"+str(desired), result[0][:, 8], [desired*418//10]*2)
    data = helper.tape()
    data["atr"][:] = 10.
    data["h"][:, 3:5] = [101., 99.]
    data.update(quantity=5, tick=.5, fee_per_contract=41.8, multiplier=1000.)
    baseline = run(data)
    poisoned = copy.deepcopy(data)
    poisoned["atr"][46:] = 10000.
    poisoned["h"][46:] = np.nan
    starts = np.zeros(len(data["times"]), np.int64); starts[47] = 1
    result = run(poisoned, starts=starts)
    for i in range(3):
        helper.equal("未来ATR履歴旧核で数量を変えない"+str(i), result[i], baseline[i])
    delayed = copy.deepcopy(data)
    delayed["qok"][46:51] = False
    delayed["atr"][46:] = 10000.
    result = run(delayed)
    helper.equal("約定待ち中も数量固定", result[0][0, [0,1,4]], [51,45,2])
    helper.equal("約定待ち中も初期幅固定", result[1][0, 10], 10.)
    # 損切り・利益追尾でも旧版と約定時計が同じ。新設定を保有後に選び直さない。
    for style, start, trail in ((0, 1.25, .75), (1, .75, .5)):
        for kind in ("損切り", "追尾"):
            current = copy.deepcopy(data)
            if kind == "損切り":
                current["bid"][100:] = 89.; current["ask"][100:] = 89.5
            else:
                current["bid"][100:] = 116.; current["ask"][100:] = 116.5
                current["bid"][101:] = 105.; current["ask"][101:] = 105.5
            result = run(current, style=style, trail_start=start, trail_width=trail)
            args = arguments(current, style=style, trail_start=start, trail_width=trail)
            del args["budget_ticks"]
            old = previous.simulate.py_func(**args)
            label = kind+str(style)
            helper.equal(label+"旧出口時計", result[0][:, [0,1,3,5,6]], old[0][:, [0,1,3,5,6]])
            independent_cash(current, result, label)
            mirrored = run(helper.mirror(current), style=style, trail_start=start, trail_width=trail)
            helper.equal(label+"鏡像時計数量", result[0][:, [0,1,2,4,6,7,8]], mirrored[0][:, [0,1,2,4,6,7,8]])
            helper.equal(label+"鏡像方向", result[0][:, 3], -mirrored[0][:, 3])
            helper.equal(label+"鏡像価格", result[0][:, 5], 200.-mirrored[0][:, 5])
            helper.equal(label+"鏡像損益", result[1][:, 7:13], mirrored[1][:, 7:13])
            compiled = run(current, style=style, trail_start=start, trail_width=trail, jit=True)
            for i in range(3):
                helper.equal(label+"JIT一致"+str(i), result[i], compiled[i])
    # 価格単位を100倍、円倍率を100分の1としても同じ円会計になる。
    unit = copy.deepcopy(data)
    unit["bid"] *= 100.; unit["ask"] *= 100.; unit["atr"] *= 100.
    unit["h"][:, [0,1,2,3,4,6,7,8,10,11,13]] *= 100.
    unit["tick"] *= 100.; unit["multiplier"] /= 100.
    result = run(unit)
    helper.equal("単位変更数量時計", baseline[0][:, [0,1,3,4,6,7,8]], result[0][:, [0,1,3,4,6,7,8]])
    helper.equal("単位変更円会計", baseline[2], result[2])
    unknown = copy.deepcopy(data); unknown["h"][:] = np.nan
    helper.check("全未知なら架空参加しない", len(run(unknown)[0]) == 0)
    cancelled = copy.deepcopy(data); cancelled["qok"][46:1200] = False
    helper.check("終端未約定取消", len(run(cancelled)[0]) == 0)
    poisoned = copy.deepcopy(data); poisoned["bid"][101:] -= 20.; poisoned["ask"][101:] -= 20.
    result = run(poisoned)
    helper.equal("未来注文接頭不変", baseline[0][baseline[0][:,0] <= 100], result[0][result[0][:,0] <= 100])
    helper.equal("未来曲線接頭不変", baseline[2][:101], result[2][:101])


def connection_audit():
    """
    機能: 実mainを架空資料へ差替え、18引数と六成分再利用キーを確認する。
    引数: なし。
    返り値: None。登録・実金融は行わない。
    """
    target = HERE/"可変枚数接続人工"; target.mkdir(exist_ok=True)
    scene = "2099-01-05_Day"
    inputs, quotes, histories, phases = {}, {}, {}, {}
    for symbol in ("TOPIX", "NK225"):
        data = helper.tape()
        key = scene, symbol
        inputs[key] = dict(time_s=data["times"], atr=data["atr"], start=0., limit=data["end"],
            tick=.5 if symbol == "TOPIX" else 10., session=scene, symbol=symbol)
        quotes[key] = dict(bid=data["bid"], ask=data["ask"], quote_valid=data["qok"])
        histories[key] = data["h"]; phases[key] = data["phase"]
    packet = dict(inputs=inputs, quotes=quotes)
    path = target/"人工入力.pkl"; path.write_bytes(pickle.dumps(packet))
    ref = dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), session=scene)
    configs = []
    for variant in (0, 1):
        for budget in (8., 12., 16., 24.):
            configs.append(dict(id=f"人工{variant}{budget}", name="人工", core_variant=variant,
                schedule=0, style=0, trail_start=1.25, trail_width=.75, budget_ticks=budget))
    for changed in (dict(schedule=1), dict(style=1), dict(trail_start=.75), dict(trail_width=.5)):
        value = dict(configs[0]); value.update(changed); value["id"] = "別条件"+str(len(configs))
        configs.append(value)
    fixed = dict(sources={}, artificial=[], input_references=[], configs=configs)
    expected_configs = []
    seen = set()
    for c in configs:
        signature = tuple(c[n] for n in ("schedule", "style", "trail_start", "trail_width", "budget_ticks"))
        if signature not in seen:
            expected_configs.append(c); seen.add(signature)
    calls, saves, arrays = [], [], []
    originals = {n: getattr(runner, n) for n in ("HERE", "read", "reference", "save", "sources")}
    oldbuild = runner.features131.build
    oldload = runner.baseline131.load_core
    oldsimulate = core.simulate
    oldnp = np.savez_compressed
    oldargv = sys.argv.copy()

    def fake_read(location):
        """
        機能: 人工計画と人工素材参照だけを返す。
        引数: location(Path)は読取先。
        返り値: dictは人工資料。
        """
        if Path(location).name == "固定計画.json": return fixed
        if Path(location).name == "登録.json": return dict(returncode=0)
        if Path(location).name == "入力準備.json": return dict(packets=[ref])
        raise AssertionError(str(location))

    def fake_reference(location):
        """
        機能: 人工入力と出力だけに参照を与える。
        引数: location(Path)は対象。
        返り値: dictは人工参照。
        """
        if Path(location) == path: return {k: ref[k] for k in ("path", "sha256")}
        return dict(path=Path(location).relative_to(ROOT).as_posix(), sha256="人工")

    def fake_load(scene, symbol, variant):
        """
        機能: 保存市場資料の代わりに零旧口座を返す。
        引数: scene/symbol(str)、variant(int)は要求。
        返り値: dictは零注文資料。
        """
        return dict(orders=np.zeros((0,8)), multiplier=1000. if symbol == "TOPIX" else 10.,
            fee=41.8 if symbol == "TOPIX" else 11., method="人工旧",
            source=dict(path="人工旧源", sha256="人工"), measurement=dict(path="人工旧会計", sha256="人工"))

    def fake_core(*args):
        """
        機能: 18引数と予定設定を独立期待へ照合する。
        引数: args(tuple)は新接続の引数。
        返り値: tupleは零追加口座。
        """
        symbol = "TOPIX" if len(calls) < len(expected_configs) else "NK225"
        c = expected_configs[len(calls) % len(expected_configs)]
        key = scene, symbol
        rd, q = inputs[key], quotes[key]
        expected = [rd["time_s"],q["bid"],q["ask"],q["quote_valid"],rd["atr"],histories[key],phases[key],
            np.zeros(len(rd["time_s"]),np.int64),runner.activation(rd,c["schedule"]),rd["limit"],rd["tick"],
            5 if symbol == "TOPIX" else 10,1000. if symbol == "TOPIX" else 10.,
            41.8 if symbol == "TOPIX" else 11.,c["style"],c["trail_start"],c["trail_width"],c["budget_ticks"]]
        helper.equal("新接続引数数"+str(len(calls)),len(args),18)
        for i, value in enumerate(expected):
            helper.equal("新接続"+str(len(calls))+"/"+str(i),args[i],value)
        calls.append((symbol,c["id"]))
        return np.zeros((0,12)),np.zeros((0,17)),np.zeros((len(rd["time_s"]),5))

    try:
        runner.HERE=target;runner.read=fake_read;runner.reference=fake_reference;runner.sources=lambda:{}
        runner.save=lambda p,v:saves.append((p,v))
        runner.features131.build=lambda p:(inputs,{},histories,phases)
        runner.baseline131.load_core=fake_load;core.simulate=fake_core
        np.savez_compressed=lambda p,**v:arrays.append((p,v))
        sys.argv=["run_risk131.py","--round","人工実行"]
        runner.main()
        final=saves[-1][1]
        helper.equal("全キー区別16実行",len(calls),16)
        helper.equal("全24商品設定",len(final["rows"]),24)
        helper.equal("同義8商品設定だけ再利用",final["reused_config_rows"],8)
        helper.equal("旧核再生零",final["core_replays"],0)
        helper.check("全数値配列保存",len(arrays)==2 and all(len(v)==len(configs)*10 for _,v in arrays))
    finally:
        for name,value in originals.items():setattr(runner,name,value)
        runner.features131.build=oldbuild;runner.baseline131.load_core=oldload
        core.simulate=oldsimulate;np.savez_compressed=oldnp;sys.argv=oldargv


def registration_audit():
    """
    機能: 登録prepareの副作用を人工資料へ閉じ、固定書と提案の可変数量表示を検査する。
    引数: なし。
    返り値: None。正式登録の呼出しは行わない。
    """
    target=HERE/"可変枚数登録人工"
    target.mkdir(exist_ok=True)
    configs=[dict(id="人工"+str(i)) for i in range(8)]
    reason=dict(compares_to=["人工先行"],quantity="旧5/10枚・追加1〜5/1〜10枚",
        question="人工",change="人工数量だけ",repeat_reason="人工")
    fakepaths={key:target/(key+".json") for key in ("条件","理由","証拠")}
    for p in fakepaths.values():p.write_text("{}\n",encoding="utf-8")
    values={str(fakepaths["条件"]):configs,str(fakepaths["理由"]):reason,str(fakepaths["証拠"]):dict(passed=True)}
    source=WORK/"participation_risk131.py"
    source_ref=dict(path=source.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    captures=[]
    originals={n:getattr(register,n) for n in ("HERE","read","reference","save","comparison_ids","resolve_input")}
    oldsources=runner.sources

    def fake_read(path):
        """
        機能: 人工固定書と場参照のみを渡す。
        引数: path(Path)は対象。
        返り値: objectは人工資料。
        """
        if str(path) in values:return values[str(path)]
        if Path(path).name=="入力準備.json":return dict(packets=[dict(session="人工Day")])
        raise AssertionError(str(path))

    def fake_reference(path):
        """
        機能: 核指紋は実源、それ以外は人工参照を返す。
        引数: path(Path)は対象。
        返り値: dictは参照。
        """
        if Path(path)==source:return source_ref
        return dict(path=Path(path).relative_to(ROOT).as_posix(),sha256="人工")

    try:
        register.HERE=target;register.read=fake_read;register.reference=fake_reference
        register.save=lambda p,v:captures.append((Path(p).name,v))
        register.comparison_ids=lambda r:["人工先行"]
        register.resolve_input=lambda p,prefer_here=True:fakepaths[p]
        runner.sources=lambda:{source_ref["path"]:source_ref["sha256"]}
        args=argparse.Namespace(round="人工巡",configs="条件",reason="理由",proof=["証拠"],
            input=[],runner="run_risk131")
        register.prepare(args)
        fixed=next(v for n,v in captures if n=="固定計画.json")
        proposal=next(v for n,v in captures if n=="試行計画.json")
        helper.check("登録理由の可変枚数を保持",fixed["quantity"]==reason["quantity"])
        for value in (fixed["allocation"],proposal["spec"]["allocation"]):
            helper.check("登録TOP可変表示",value["独立初回追加"]["TOPIXmini"]=="1〜5枚")
            helper.check("登録NK可変表示",value["独立初回追加"]["NKmicro"]=="1〜10枚")
            helper.check("登録数量式あり","発注時R" in value["独立初回追加"]["数量"])
            helper.check("登録旧数量保持",value["旧核"]==dict(TOPIXmini=5,NKmicro=10))
    finally:
        for name,value in originals.items():setattr(register,name,value)
        runner.sources=oldsources


def main():
    """
    機能: 核・会計・接続・登録表示を独立確認し、指紋付き証拠を保存する。
    引数: なし。
    返り値: None。金融0・実資料読込0・正式登録0。
    """
    helper.CHECKS.clear()
    core_audit()
    oldrunner=portfolio.runner
    try:
        portfolio.runner=runner
        portfolio.clock_audit()
        portfolio.account_audit()
    finally:
        portfolio.runner=oldrunner
    connection_audit()
    registration_audit()
    files=[WORK/n for n in ("participation_risk131.py","participation_exit131.py",
        "run_risk131.py","register_risk131.py","baseline131.py","features131.py","common131.py")]
    files += [HERE/n for n in ("audit_engine131.py","audit_participation131.py","audit_portfolio131.py")]
    proof=dict(passed=True,checks=len(helper.CHECKS),labels=helper.CHECKS,
        sources={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0,market_data_reads=0,registrations=0,
        caveat="今回の登録理由は可変枚数を明示。registerのquantity未指定時の既定文は固定枚数の旧文で、汎用転用時には理由を明示する必要がある。",
        quantity="方向・時刻・価格幅は第三巡と同じ。注文枚数と円会計だけ変更。最低1枚は予定予算を超え得る。",
        scope="人工検査。実場の黒字数・赤字平均と中央値の改善は金融後に独立評価。")
    path=HERE/f"追加枚数リスク調整の独立人工_{time.time_ns()}.json"
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(path.as_posix(),len(helper.CHECKS),"合格",flush=True)


if __name__=="__main__":
    main()
