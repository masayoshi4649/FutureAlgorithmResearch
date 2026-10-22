"""架空の共同価格時計だけで復帰二確認・極値撤回・二脚会計を反証する。"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import traceback

import numpy as np

import engine_v8 as E


HERE = Path(__file__).resolve().parent
COUNTS = Counter()


def check(value: bool, label: str) -> None:
    """
    機能: 独立した人工期待を項目別に記録する。
    引数: value(bool)は一致、label(str)は検査名。
    返り値: None。不一致なら停止する。
    """
    assert value, label
    COUNTS[label] += 1


def replay_case(path: list[tuple[float, float]], mode: int = 0, clocks: tuple = (120., 180., 240.),
                common: dict | None = None, top_end: float = math.inf, spread: dict | None = None,
                python: bool = False, cutoff: float = math.inf) -> tuple:
    """
    機能: モデルが既知の架空価格経路を共同clockで運転する。
    引数: path(list[tuple[float,float]])は時計と残差、mode(int)、clocks(tuple)、common/spread(dict|None)、
          top_end/cutoff(float)、python(bool)は反証の条件。
    返り値: tupleは新核心の保存配列。現実の金融又は原入力は使わない。
    """
    path = [(t, d) for t, d in path if t <= cutoff]
    t = np.array([v[0] for v in path])
    d = np.array([v[1] for v in path])
    scale = np.array([(common or {}).get(float(x), 1.) for x in t])
    prices = (60000. * np.exp(d) * scale, 4000. * scale)
    records = []
    for leg in range(2):
        use = t <= (top_end if leg else math.inf)
        tt, p = t[use], prices[leg][use]
        width = np.array([(spread or {}).get(float(x), (10., .5))[leg] for x in tt])
        records.append((np.arange(len(tt), dtype=np.int64), tt, p - width / 2., p + width / 2., p))
    cc = np.array([c for c in clocks if c <= cutoff])
    history = np.array([[1., 1., math.log(15.), .001] for _ in cc]).reshape(-1, 4)
    times = np.concatenate((records[0][1], records[1][1], cc))
    kinds = np.concatenate((np.zeros(len(records[0][1]), np.int8), np.ones(len(records[1][1]), np.int8), np.full(len(cc), 2, np.int8)))
    indexes = np.concatenate((np.arange(len(records[0][1])), np.arange(len(records[1][1])), np.arange(len(cc)))).astype(np.int64)
    rows = np.concatenate((records[0][0], records[1][0], np.zeros(len(cc), np.int64)))
    ix = np.lexsort((rows, kinds, times))
    fn = E.replay.py_func if python else E.replay
    return fn(times[ix], kinds[ix], indexes[ix], cc, history, *records[0], *records[1], 800., 900., mode)


def material() -> tuple:
    """
    機能: 本物のモデル推定を含め、八設定の接続に使う架空足と正常気配を作る。
    引数: なし。
    返り値: tuple[dict,dict,dict,dict]は二市場の足と気配。過去実績は参照しない。
    """
    n = 80
    origin = datetime(2034, 2, 8, 9, tzinfo=timezone(timedelta(hours=9))).timestamp()
    x = np.arange(n, dtype=float)
    clocks = origin + 60 * x
    top = 4000 * np.exp(.0001 * x + .0003 * np.sin(x / 7))
    nk = 15 * top * np.exp(.001 * np.sin(x / 2))
    bars, quotes = [], []
    for leg, prices in enumerate((nk, top)):
        bars.append(dict(t_s=clocks.copy(), close=prices.copy(), valid=np.ones(n, bool), pub_price_time_s=clocks + 60))
        tt, pp = [], []
        for i in range(n):
            for k, offset in enumerate((0., 1., 2., 3., 20., 21., 30.)):
                factor = (1.01, 1.009, 1.009, 1.0088, 1.002, 1.003, 1.)[k] if leg == 0 and i in (65, 72) else 1.
                tt.append(clocks[i] + 60 + offset)
                pp.append(prices[i] * factor)
        pp = np.asarray(pp)
        width = 10. if leg == 0 else .5
        quotes.append(dict(row=np.arange(len(pp), dtype=np.int64), time=np.asarray(tt), last=pp,
            bid=pp - width / 2, ask=pp + width / 2, bq=np.full(len(pp), 100.), aq=np.full(len(pp), 100.)))
    return *bars, *quotes


def main() -> None:
    """
    機能: 正負両方向・二退出・未来接頭・同clock・料金を人工だけで検査する。
    引数: なし。
    返り値: None。現源に結合した検査JSONを保存する。実測金融は行わない。
    """
    target = HERE / '相対復帰二確認と固定極値及び二脚の純人工.json'
    assert not target.exists()
    baseline = [(120., .003), (121., .0023), (122., .0022), (123., .0021), (124., .0001), (125., -.0001), (126., -.0001)]
    for sign in (-1, 1):
        path = [(t, sign * d) for t, d in baseline]
        for mode in (0, 1):
            r = replay_case(path, mode)
            py = replay_case(path, mode, python=True)
            for a, b in zip(r, py):
                check(np.array_equal(a, b, equal_nan=True), 'PythonとJITの全配列一致')
            orders, parents, _, _, prep = r[:5]
            check(len(parents) == 1 and parents[0, 1] == 1. and len(orders) == 4, '両方向と二出口に実新規返済')
            check(orders[0, 5] == 122. and np.all(orders[:2, 6] == 123.), '二確認後予約と厳密次clockfill')
            check(parents[0, 2] == -sign and parents[0, 38] == 120., '復帰方向と準備の結合')
            check(prep[0, 8] == 121. and prep[0, 9] == 122. and prep[0, 19] == 1., '異なる二価格clockの保存')
            nominal = prep[0, 15] * 10. * prep[0, 17]
            fee = 2 * (math.floor(prep[0, 15] * 11 + 1e-9) + math.floor(prep[0, 16] * 41.8 + 1e-9))
            check(math.isclose(prep[0, 12], abs(prep[0, 7] - prep[0, 11]) * nominal + fee, abs_tol=1e-6), '停止幅元本と往復明示料の正予算')
            for order in orders:
                check(order[9] == math.floor(order[4] * (11. if order[1] == 0 else 41.8) + 1e-9), '脚ごと注文ごとの円未満切捨て')
                check(order[6] > order[5], '新規返済の同clock約定禁止')
            check(abs(parents[0, 22:24].sum() - parents[0, 24:26].sum() - parents[0, 28]) < 1e-6, '料金を予算と二重課金しない')
    # ----------------------------------------
    # 確認途中の失敗と同clockの偽乖離を、成功例の反対条件から検査する。
    for reset in (.0028, .0035):
        path = [(120., .003), (121., .0023), (122., reset), (123., reset - .0007), (124., reset - .0008), (125., reset - .0009)]
        r = replay_case(path)
        check(r[4][0, 8] == 123. and r[4][0, 9] == 124., '閾値割れ又は新極値で二確認reset')
        check(r[0][0, 5] == 124., '古い一確認を持ち越して早く入らない')
    cancel = replay_case([(120., .003), (121., -.0001), (122., -.0001)])
    check(len(cancel[0]) == 0 and cancel[4][0, 19] == 2., 'center帰還なら未予約準備を取消')
    no_second = replay_case(baseline, cutoff=121.)
    check(len(no_second[0]) == 0 and no_second[-1][0] == 0, '一確認だけを取引成功にしない')
    common = replay_case([(120., .003), (121., .0023), (122., .0022), (123., .0021), (124., .0021)], common={124.: 1.1})
    check(len(common[0]) == 2 and common[1][0, 1] == 0. and common[1][0, 5] == 0., '同clock共通上昇の中間残差で偽stopしない')
    trail = replay_case([(120., .003), (121., .0023), (122., .0022), (123., .0021), (124., .0010), (125., .0016), (126., .0016)], 1)
    check(trail[1][0, 5] == 6. and trail[1][0, 4] == 125., '一σ改善後の半σ戻りで追尾')
    extreme = replay_case([(120., .003), (121., .0023), (122., .0022), (123., .0021), (124., .0031), (125., .0031)])
    check(extreme[1][0, 5] == 2., '準備極値への逆戻りで撤回')
    cashstop = replay_case([(120., .003), (121., .0023), (122., .0022), (123., .0021), (124., .0021), (125., .0021)], spread={124.: (200., 10.)})
    check(cashstop[1][0, 5] == 3., '残差とは別の清算資産安全止損')
    timeout = replay_case([(120., .003), (121., .0023), (122., .0022), (123., .0021), (182., .0021), (183., .0021)], top_end=122.)
    check(timeout[1][0, 29] == 1. and timeout[1][0, 5] == 4. and timeout[-1][2] == 1, '六十秒片脚失効と孤立返済')
    nofill = replay_case(baseline, top_end=122., cutoff=122.)
    check(len(nofill[0]) == 0 and len(nofill[1]) == 0 and nofill[-1][0] == 1, '未fill予約は完結親へ数えない')
    no_rearm = replay_case([(120., .003), (121., .0023), (122., .0022), (123., .0021), (124., .0031), (125., .0031), (180., .003)])
    check(len(no_rearm[4]) == 1, '決済後も中心復帰なしなら同波再準備しない')
    rearm = replay_case([(120., .003), (121., .0023), (122., .0022), (123., .0021), (124., .0031), (125., .0031),
        (190., -.0001), (240., .003), (241., .0023), (242., .0022), (243., .0021)])
    check(len(rearm[4]) == 2 and rearm[4][1, 1] == 240., '完結後中心帰還を観測して再arm')
    prefix = replay_case(baseline, cutoff=123.)
    for future in (.2, -.2):
        changed = replay_case(baseline[:4] + [(t, future) for t, _ in baseline[4:]])
        check(np.array_equal(prefix[0], changed[0][changed[0][:, 6] <= 123.], equal_nan=True), '未来suffixで過去注文を変えない')
        check(np.array_equal(prefix[2], changed[2][:len(prefix[2])], equal_nan=True), '未来suffixで過去公開資産を変えない')
        check(np.array_equal(prefix[4][:, :19], changed[4][:1, :19], equal_nan=True), '予約済準備のモデル極値二確認を未来で変えない')
        check(np.array_equal(changed[0][:2, 4], prefix[0][:2, 4]), '予約後の未来価格で枚数を選び直さない')
    # ----------------------------------------
    # 推定式と履歴資格を含む公開APIを全八仕様へ接続する。
    details = []
    data = material()
    for method in ('ratio_mr', 'ols_mr'):
        for lookback in (30, 60):
            for mode in (0, 1):
                answer = E.run_pair(*data, dict(method=method, lookback=lookback, exit_mode=mode,
                    entry_end=data[2]['time'][-1] - 20., close_time=data[2]['time'][-1] - 10.))
                check(len(answer['orders']) > 0 and len(answer['parents']) > 0, '全八モデル退出の実核心接続')
                check(answer['parents'].shape[1] == 46 and answer['preparations'].shape[1] == 21, '会計と準備系譜の列数')
                check(abs(sum(v['net'] for v in answer['leg_summary'].values()) - answer['summary']['net']) < 1e-5, '二脚の資産合計')
                check(abs(answer['orders'][:, 9].sum() - answer['summary']['fees']) < 1e-6, '全親全注文の実料金')
                details.append(dict(method=method, lookback=lookback, exit_mode=mode, summary=answer['summary']))
    proof = dict(passed=True, scope='完全人工だけ。既所有市場、実結果、登録、正式金融の読取又は実行0。',
        counts=dict(COUNTS), total_checks=sum(COUNTS.values()), source_SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE / 'engine_v8.py', Path(__file__))},
        details=details, market_reads=0, formal_financial_replay=0, API=0, registry_changes=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    print(json.dumps(dict(passed=True, checks=sum(COUNTS.values()), SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        path = HERE / '人工False.json'
        assert not path.exists()
        path.write_text(json.dumps(dict(passed=False, traceback=traceback.format_exc(), counts=dict(COUNTS),
            engine_SHA256=hashlib.sha256((HERE / 'engine_v8.py').read_bytes()).hexdigest(), market_reads=0, formal_financial_replay=0), ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        raise
