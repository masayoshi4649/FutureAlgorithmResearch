"""第三巡の出口二変数だけを、独立人工の期待行・会計・旧互換で確認する。"""

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
os.environ["NUMBA_CACHE_DIR"] = str(HERE / "jit_exit131")
import participation131 as old
import participation_exit131 as new
import run_exit131 as runner
import numba

numba.config.CACHE_DIR = str(HERE / "jit_exit131")
CHECKS = []
SETTINGS = ((.75, .5), (1., .5), (1., .75), (1.25, .75))


def check(label, truth):
    """
    機能: 独立期待との一致を数え、不一致で直ちに停止する。
    引数: label(str)、truth(bool)は検査名と真偽。
    返り値: None。
    """
    assert bool(truth), label
    CHECKS.append(label)


def equal(label, left, right):
    """
    機能: 人工結果の形と数値を厳密な小誤差以内で照合する。
    引数: label(str)、left/right(ndarray)は検査名と比較値。
    返り値: None。
    """
    check(label, np.shape(left) == np.shape(right) and
          np.allclose(left, right, rtol=0., atol=1e-8, equal_nan=True))


def fixture(quantity=5, style=0):
    """
    機能: 市場資料を一切読まず、判断1・新規約定2・初期幅8の24原行を作る。
    引数: quantity(int)、style(int)は枚数と方向方式。
    返り値: dict[str,object]は旧核15引数。
    """
    n = 24
    times = np.arange(n, dtype=float) * 10.
    times[-2:] = (1500., 1501.)
    h = np.zeros((n, 14))
    h[:, 3] = 104.; h[:, 4] = 96.
    h[:, 6] = 2.; h[:, 7] = 4.; h[:, 8] = 90.
    h[:, 10] = 20.; h[:, 11] = 40.; h[:, 13] = 8.
    return dict(times=times, bid=np.full(n, 100.), ask=np.full(n, 100.5),
                qok=np.ones(n, bool), atr=np.full(n, 8.), history=h,
                phase=np.zeros(n, np.int64), core_starts=np.zeros(n, np.int64),
                activation=10., end=1500., tick=.5, quantity=quantity,
                multiplier=1000. if quantity == 5 else 10.,
                fee_per_contract=41.8 if quantity == 5 else 11., style=style)


def mark(args, row, gain):
    """
    機能: 買い建値100.5からの清算幅を、指定行以後の人工気配へ設定する。
    引数: args(dict)、row(int)、gain(float)は人工資料・開始行・順行幅。
    返り値: None。引数の気配だけを変更する。
    """
    args["bid"][row:] = 100.5 + gain
    args["ask"][row:] = 101. + gain


def mirror(args):
    """
    機能: 中心1000で気配と方向差を反転し、上下対称の人工資料を作る。
    引数: args(dict)は旧核引数。
    返り値: dictは価格反転後の引数。
    """
    result = copy.deepcopy(args)
    result["bid"] = 1000. - args["ask"]
    result["ask"] = 1000. - args["bid"]
    h = result["history"]
    h[:, 3] = 1000. - args["history"][:, 4]
    h[:, 4] = 1000. - args["history"][:, 3]
    h[:, 8] = 1000. - args["history"][:, 8]
    h[:, [6, 7, 10, 11, 13]] *= -1.
    return result


def simulate(args, setting=(1.5, 1.), compiled=False):
    """
    機能: 純人工引数を新核へ渡す。
    引数: args(dict)、setting(tuple[float,float])、compiled(bool)は素材・出口・JIT指定。
    返り値: tuple[ndarray,...]は保存注文・親・全行曲線。
    """
    function = new.simulate if compiled else new.simulate.py_func
    return function(**args, trail_start=setting[0], trail_width=setting[1])


def accounting(args, result, label):
    """
    機能: 注文から別の現金台帳を作り、全行の評価額・在庫・費用・親収支を検算する。
    引数: args(dict)、result(tuple)、label(str)は人工資料・結果・検査名。
    返り値: None。売買判断の再実装はしない。
    """
    orders, trades, curve = result
    cash = 0.; realized = 0.; position = 0; peak = 0.; dd = 0.
    entry_price = None; side = 0; fees = 0.
    mb = ma = np.nan
    for i in range(len(args["times"])):
        good = (args["qok"][i] and np.isfinite(args["bid"][i]) and
                np.isfinite(args["ask"][i]) and args["ask"][i] > args["bid"][i] > 0.)
        if good:
            mb, ma = args["bid"][i], args["ask"][i]
        for order in orders[orders[:, 0] == i]:
            row, source = int(order[0]), int(order[1])
            next_good = next(j for j in range(source + 1, len(args["times"]))
                             if args["qok"][j] and np.isfinite(args["bid"][j]) and
                             np.isfinite(args["ask"][j]) and args["ask"][j] > args["bid"][j] > 0.)
            check(label + "/次正常原行", row == next_good)
            p = ma if order[3] > 0 else mb
            check(label + "/反対気配", order[5] == p)
            fee = int(order[4] * args["fee_per_contract"])
            check(label + "/注文費用", order[8] == fee)
            cash -= order[3] * order[4] * p * args["multiplier"] + fee
            position += int(order[3] * order[4]); fees += fee
            if order[7]:
                entry_price = p; side = order[3]; realized -= fee
            else:
                realized += side * (p - entry_price) * order[4] * args["multiplier"] - fee
        liquidation = cash
        if position:
            liquidation += position * (mb if position > 0 else ma) * args["multiplier"]
            liquidation -= int(abs(position) * args["fee_per_contract"])
        peak = max(peak, liquidation); dd = max(dd, peak - liquidation)
        equal(label + "/全行" + str(i), curve[i, :4], [liquidation, position, realized, dd])
    check(label + "/終端在庫", position == 0)
    equal(label + "/親全費用", trades[:, 8].sum(), fees)
    equal(label + "/親全収支", trades[:, 9].sum(), realized)


def symmetry(args, result, setting, label):
    """
    機能: 上下反転後の売買行・価格・円損益・全行曲線を照合する。
    引数: args(dict)、result(tuple)、setting(tuple)、label(str)は人工素材と期待。
    返り値: None。
    """
    other = simulate(mirror(args), setting)
    equal(label + "/鏡像行", result[0][:, [0, 1, 2, 4, 6, 7, 8, 9, 10, 11]],
          other[0][:, [0, 1, 2, 4, 6, 7, 8, 9, 10, 11]])
    equal(label + "/鏡像方向", result[0][:, 3], -other[0][:, 3])
    equal(label + "/鏡像価格", result[0][:, 5], 1000. - other[0][:, 5])
    equal(label + "/鏡像親", result[1][:, 7:13], other[1][:, 7:13])
    equal(label + "/鏡像曲線", result[2][:, [0, 2, 3, 4]], other[2][:, [0, 2, 3, 4]])


def source_connection():
    """
    機能: 旧源との差を限定し、実mainの17引数と二出口変数入り再利用キーを検査する。
    引数: なし。
    返り値: None。main自体や金融ループは実行しない。
    """
    before = (WORK / "participation131.py").read_text(encoding="utf-8")
    after = (WORK / "participation_exit131.py").read_text(encoding="utf-8")
    after = after.replace("fee_per_contract, style, trail_start, trail_width):",
                          "fee_per_contract, style):")
    after = after.replace("            trail_start/trail_width(float)は初期Rに対する利益保護開始・追尾幅。\n", "")
    after = after.replace("          trail_start/trail_width(float)は初期Rに対する利益保護開始・追尾幅。\n", "")
    after = after.replace("mfe >= trail_start*risk", "mfe >= 1.5*risk")
    after = after.replace("mfe-trail_width*risk", "mfe-risk")
    check("核は出口二式と引数だけの変更", before == after)
    before = (WORK / "run_portfolio131.py").read_text(encoding="utf-8")
    after = (WORK / "run_exit131.py").read_text(encoding="utf-8")
    normalized = after.replace("participation_exit131", "participation131").replace(
        "run_exit131.py", "run_portfolio131.py").replace(
        ', config["trail_start"], config["trail_width"]', "")
    check("runnerは源参照と引数と再利用キーだけの変更", before == normalized)
    tree = ast.parse(after)
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and
                isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and
                n.func.value.id == "participation_exit131" and n.func.attr == "simulate")
    cache = next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and
                 any(isinstance(t, ast.Name) and t.id == "extra_key" for t in n.targets))
    check("mainの引数数", len(call.args) == 17)
    for qty in (5, 10):
        for setting in SETTINGS:
            a = fixture(qty)
            config = dict(core_variant=0, schedule=2, style=1, trail_start=setting[0],
                          trail_width=setting[1])
            env = dict(ready=dict(time_s=a["times"], atr=a["atr"], limit=a["end"],
                                 tick=a["tick"]), q=dict(bid=a["bid"], ask=a["ask"],
                                 quote_valid=a["qok"]), history={"x": a["history"]},
                       phases={"x": a["phase"]}, starts=a["core_starts"], key="x",
                       config=config, top=qty == 5, activation=lambda ready, schedule: 700.,
                       core_key=0)
            values = [eval(compile(ast.Expression(node), "<人工接続>", "eval"), env)
                      for node in call.args]
            check("main末尾設定" + str((qty, setting)),
                  values[-3:] == [1, setting[0], setting[1]])
            check("main数量費用" + str((qty, setting)),
                  values[11:14] == [qty, 1000. if qty == 5 else 10.,
                                    41.8 if qty == 5 else 11.])
            key = eval(compile(ast.Expression(cache), "<人工再利用>", "eval"), env)
            check("設定別再利用キー" + str((qty, setting)), key == (0, 2, 1, *setting))
    configs = json.loads((WORK / "第三巡条件.json").read_text(encoding="utf-8"))
    check("八条件一意", len(configs) == len({c["id"] for c in configs}) == 8)
    for c in configs:
        check(c["id"] + "入口固定",
              c["core_variant"] == 0 and (c["schedule"], c["style"]) in ((2, 0), (1, 1)))
        check(c["id"] + "出口固定", (c["trail_start"], c["trail_width"]) in SETTINGS)


def main():
    """
    機能: 第三巡出口核を人工のみで監査し、実測件数と源指紋を保存する。
    引数: なし。
    返り値: None。市場資料の読取と金融再生を行わない。
    """
    source_connection()
    for qty in (5, 10):
        for style in (0, 1):
            for setting in SETTINGS:
                label = str((qty, style, setting))
                a = fixture(qty, style)
                entry = 100.5; risk = 8.
                floor = (setting[0] - setting[1]) * risk
                mark(a, 3, setting[0] * risk - .25)
                mark(a, 4, 0.)
                mark(a, 5, setting[0] * risk)
                mark(a, 6, floor + .25)
                mark(a, 7, floor)
                mark(a, 8, floor - 2.)
                a["qok"][8] = False
                a["ask"][9] = a["bid"][9]
                a["atr"][2:] = 1000.
                a["history"][7:] = np.nan
                a["core_starts"][8] = 1
                result = simulate(a, setting)
                equal(label + "/判断と次行", result[0][:, :2], [[2, 1], [10, 7]])
                equal(label + "/数量", result[0][:, 4], [qty, qty])
                check(label + "/利益保護理由", result[0][1, 6] == 70)
                equal(label + "/固定R", result[1][:, 10], [8.])
                equal(label + "/不利でも次正常約定", result[0][1, 5], entry + floor - 2.)
                accounting(a, result, label)
                symmetry(a, result, setting, label)
                jit = simulate(a, setting, True)
                for i in range(3):
                    equal(label + "/JIT" + str(i), result[i], jit[i])
                # ----------------------------------------
                # 起動直前の山から戻っても保護は未起動。初期1Rの等号で停止する。
                b = fixture(qty, style)
                mark(b, 3, setting[0] * risk - .25)
                mark(b, 4, -risk + .25)
                mark(b, 5, -risk)
                mark(b, 6, -risk - 5.)
                stop = simulate(b, setting)
                equal(label + "/起動前の初期停止", stop[0][:, :2], [[2, 1], [6, 5]])
                check(label + "/初期停止理由", stop[0][1, 6] == 32)
                accounting(b, stop, label + "/初期停止")
                symmetry(b, stop, setting, label + "/初期停止")
                # 全設定で同じ新規が行われ、出口だけが変わる。
                for alt in SETTINGS:
                    equal(label + "/入口不変" + str(alt), result[0][:1], simulate(a, alt)[0][:1])
                # 未来の旧核新規・相場・履歴の変更は過去へ伝播しない。
                base = fixture(qty, style); first = simulate(base, setting)
                changed = copy.deepcopy(base)
                mark(changed, 12, -20.); changed["history"][12:] = np.nan
                changed["core_starts"][12:] = 1
                second = simulate(changed, setting)
                equal(label + "/未来曲線", first[2][:12], second[2][:12])
                equal(label + "/未来注文", first[0][first[0][:, 0] < 12],
                      second[0][second[0][:, 0] < 12])
    # ----------------------------------------
    # 旧設定は上昇下落・欠測気配・遅れ・上下・両方向方式に対し全配列同値。
    rng = np.random.default_rng(131003)
    for scenario in range(32):
        a = fixture(5 if scenario % 2 == 0 else 10, scenario % 2)
        prices = 100. + np.cumsum(rng.choice([-5., -2., -.5, .5, 2., 5.], 24))
        a["bid"][3:] = prices[3:]; a["ask"][3:] = prices[3:] + .5
        a["qok"][3:20] = rng.random(17) > .2
        a["qok"][-2:] = True
        if scenario % 3 == 0:
            a["core_starts"][scenario % 7] = 1
        if scenario % 4 == 0:
            a["history"][7:13] = np.nan
        if scenario % 5 == 0:
            a["times"][4:8] = a["times"][3]
        for reflect in (False, True):
            material = mirror(a) if reflect else a
            expected = old.simulate.py_func(**material)
            actual = simulate(material)
            for i in range(3):
                equal("旧設定完全互換" + str((scenario, reflect, i)), expected[i], actual[i])
    a = fixture(); a["times"][2:4] = 20.
    base = simulate(a, SETTINGS[0])
    b = copy.deepcopy(a); mark(b, 3, -20.)
    other = simulate(b, SETTINGS[0])
    equal("同秒の後続原行を先読みしない", base[2][:3], other[2][:3])
    # 旧核が判断行までに参加済みなら、追加しない。後発は発注を取り消さない。
    for row in (0, 1, 2, 3):
        a = fixture(); a["core_starts"][row] = 1
        o = simulate(a, SETTINGS[0])[0]
        check("旧新規接頭だけを参照" + str(row), len(o) == (0 if row <= 1 else 2))
    sources = runner.sources()
    for name in ("第三巡条件.json", "第三巡の変更理由.json", "register_portfolio131.py"):
        p = WORK / name
        sources[p.relative_to(ROOT).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    reuse = [
        WORK / "audit/旧核円会計接続の作者人工と107商品場_1792502540335407400.json",
        WORK / "night_diagnosis/旧核円会計接続の独立人工_1792503010127276500.json",
        WORK / "day_diagnosis/旧核一回追加接続の独立人工_1792503298188210300.json",
    ]
    proofs = []
    for p in reuse:
        data = json.loads(p.read_text(encoding="utf-8"))
        check("不変接続の既存証跡" + p.name, data["passed"])
        proofs.append(dict(path=p.relative_to(ROOT).as_posix(),
                           sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    target = HERE / f"一回追加の出口変更の独立人工_{time.time_ns()}.json"
    proof = dict(passed=True, financial_replays=0, market_data_reads=0,
                 check_count=len(CHECKS), checks=CHECKS, sources=sources, reused_proofs=proofs,
                 audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 scope="旧設定同値・4出口の閾値境界・初期幅・入口固定・未来・上下・次原行・費用・JIT・実main引数",
                 limitation="新金融成績は検証していない。旧核会計と合算接続は源不変を照合し既存証跡を再利用。")
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.relative_to(ROOT), len(CHECKS), "合格", flush=True)


if __name__ == "__main__":
    main()
