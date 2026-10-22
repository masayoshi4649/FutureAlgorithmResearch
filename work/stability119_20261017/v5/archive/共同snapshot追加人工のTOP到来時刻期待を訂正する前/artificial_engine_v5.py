"""NT四仮説の非同時約定・独立料金会計・固定モデルと接頭を人工だけで確認する。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'numba_artificial')
import engine_v5 as engine

CHECKS = []


def check(value: bool, label: str) -> None:
    """
    機能: 意味の異なる人工期待と照合し証跡へ記録する。
    引数: value(bool)は検査式、label(str)は検査の名称。
    返り値: None。不一致なら成功証跡を作らず停止する。
    """
    assert value, label
    CHECKS.append(label)


def fixture(sign: int = 1, method: str = 'ratio_mr', lookback: int = 30, kind: str = 'center') -> tuple:
    """
    機能: 実市場を参照せず連続足と二脚の異なる時計を生成する。
    引数: sign(int)は初期残差符号、method(str)/lookback(int)は仮説、kind(str)は経路。
    返り値: tupleは二市場足・気配・設定。全量と手数料の期待を後から独立計算できる。
    """
    base = 1800000000. - (1800000000. % 60.)
    i = np.arange(85, dtype=float)
    t = base + (i + 1) * 60.
    x = .003 * np.sin(i / 7.)
    top = dict(t_s=t, valid=np.ones(len(i), bool), close=4000. * np.exp(x), pub_price_time_s=t + 1.)
    nk = dict(t_s=t, valid=np.ones(len(i), bool), close=60000. * np.exp(1.1 * x + .001 * np.sin(i * 2.1)), pub_price_time_s=t + 1.)
    now = base + 65. * 60.
    pn = 60000. * math.exp(sign * .02)
    tn = now + np.asarray([0., 0., 1., 2., 10., 11., 12., 60., 61., 62., 91., 92., 121.])
    tt = now + np.asarray([0., 1.5, 2., 10., 11., 12., 60., 61., 62., 91., 92., 121.])
    lastn, lastt = np.full(len(tn), pn), np.full(len(tt), 4000.)
    if kind == 'center':
        lastn[tn >= now + 10.] = 55000. if sign == 1 else 65000.
    elif kind == 'outer':
        lastn[tn >= now + 10.] = pn * math.exp(sign * .02)
    elif kind == 'timeout':
        tt = now + np.asarray([0., 61., 62., 91., 92., 121.])
        lastt = np.full(len(tt), 4000.)
    elif kind == 'no_fill':
        tn = now + np.asarray([0., 60., 61., 91., 92.])
        tt = now + np.asarray([0., 60., 61., 91., 92.])
        lastn, lastt = np.full(len(tn), pn), np.full(len(tt), 4000.)
    elif kind == 'stale':
        tt = now + np.asarray([-6., 61., 62., 91., 92.])
        lastt = np.full(len(tt), 4000.)
    quotes = []
    for clocks, last, spread in ((tn, lastn, 10.), (tt, lastt, .5)):
        quotes.append(dict(row=np.arange(len(clocks), dtype=np.int64), time=clocks,
            last=last, bid=last-spread/2., ask=last+spread/2., bq=np.full(len(clocks), 100.), aq=np.full(len(clocks), 100.)))
    if kind == 'cash':
        if sign == 1:
            quotes[0]['bid'][2] = pn / 2.
        else:
            quotes[0]['ask'][2] = pn * 2.
    if kind == 'cost':
        quotes[0]['bid'][:] = pn / 2.
        quotes[0]['ask'][:] = pn * 2.
    config = dict(method=method, lookback=lookback, entry_end=now+30., close_time=now+90.)
    return nk, top, quotes[0], quotes[1], config


def accounting(answer: dict) -> None:
    """
    機能: 実注文からDecimal料金と独立脚別損益を再構成する。
    引数: answer(dict)は人工運転の返却値。
    返り値: None。親・脚・場の合算と未清算の別扱いを照合する。
    """
    orders = answer['orders']
    columns = {name: i for i, name in enumerate(engine.ORDER_COLUMNS)}
    totals = [dict(gross=0., fees=0., cash=0.) for _ in range(2)]
    entries = {}
    for row in orders:
        leg, kind, parent, side, q = (int(row[columns[k]]) for k in ('leg', 'kind', 'parent', 'side', 'quantity'))
        fee = float((Decimal(str(11. if leg == 0 else 41.8)) * Decimal(q)).to_integral_value(rounding=ROUND_FLOOR))
        check(row[columns['fee']] == fee, '各注文一回の円未満切捨て')
        check(row[columns['fill_time']] > row[columns['decision_time']], '両脚とも厳密な後価格秒で約定')
        totals[leg]['fees'] += fee
        totals[leg]['cash'] -= fee
        if kind == 1:
            entries[parent, leg] = side, q, row[columns['price']]
        else:
            d, size, entry = entries[parent, leg]
            check(q == size and side == -d, '返済注文方向と全枚数')
            gross = d * (row[columns['price']] - entry) * q * (10. if leg == 0 else 1000.)
            totals[leg]['gross'] += gross
            totals[leg]['cash'] += gross
    for leg, symbol in enumerate(('NK225', 'TOPIX')):
        view = answer['leg_summary'][symbol]
        for key, expected in (('gross', totals[leg]['gross']), ('fees', totals[leg]['fees']), ('realized', totals[leg]['cash'])):
            check(math.isclose(view[key], expected, rel_tol=0., abs_tol=1e-6), '独立累積脚/' + symbol + '/' + key)
    check(math.isclose(answer['summary']['fees'], sum(t['fees'] for t in totals), abs_tol=1e-6), '全親の累積料')
    check(math.isclose(answer['summary']['realized'], sum(t['cash'] for t in totals), abs_tol=1e-6), '全脚の累積cash')
    if answer['summary']['unclosed'] == 0:
        check(math.isclose(answer['summary']['net'], sum(t['cash'] for t in totals), abs_tol=1e-6), '全玉返済後net')
    for row in answer['parents']:
        check(abs(row[26]+row[27]-row[28]) < 1e-6, '親の脚別netと組net')
    for key in ('orders', 'parents', 'curve', 'models'):
        columns = answer[key[:-1]+'_columns'] if key in ('orders', 'parents', 'models') else answer['curve_columns']
        check(answer[key].shape[1] == len(columns), '公開列のshape/' + key)


def common_clock_case(rate: float = .1) -> tuple:
    """
    機能: 同時計の共通変動が一時的な残差へ化けない人工を構成する。
    引数: rate(float)は両市場へ同率に加える変動率。
    返り値: tupleはreplayの引数。真の比率復帰は七十秒後にだけ発生する。
    """
    now = 1800000000.
    nt = now + np.asarray([0., 1., 3., 70., 71., 72., 121.])
    tt = now + np.asarray([0., 2., 3., 70., 71., 72., 121.])
    pn = np.full(len(nt), 100000.)
    pt = np.full(len(tt), 1000.)
    pn[nt >= now+3.] = 100000.*(1.+rate)
    pt[tt >= now+3.] = 1000.*(1.+rate)
    pn[nt >= now+70.] = 108800. if rate == .1 else 99.*1000.*(1.+rate)-100.
    nr, tr = np.arange(len(nt), dtype=np.int64), np.arange(len(tt), dtype=np.int64)
    clocks = now + np.asarray([0., 60., 120.])
    history = np.tile(np.asarray([1., 1., math.log(99.), .001]), (len(clocks), 1))
    times = np.concatenate((nt, tt, clocks))
    kinds = np.concatenate((np.zeros(len(nt), np.int8), np.ones(len(tt), np.int8), np.full(len(clocks), 2, np.int8)))
    indexes = np.concatenate((nr, tr, np.arange(len(clocks)))).astype(np.int64)
    raw = np.concatenate((nr, tr, np.zeros(len(clocks), np.int64)))
    order = np.lexsort((raw, kinds, times))
    return (times[order], kinds[order], indexes[order], clocks, history,
        nr, nt, pn-1., pn+1., pn, tr, tt, pt-.01, pt+.01, pt, now+30., now+120.)


def main() -> None:
    """
    機能: 四モデルの接続と重要境界及び未来接頭を合成素材だけで検査する。
    引数: なし。ファイルから市場値・既結果を読み込まない。
    返り値: None。成功又はFalseを私有JSONへ保存する。
    """
    economic = HERE / 'engine_v5.py'
    initial_sha = hashlib.sha256(economic.read_bytes()).hexdigest()
    try:
        for method in ('ratio_mr', 'ols_mr'):
            for lookback in (30, 60):
                for sign in (1, -1):
                    data = fixture(sign, method, lookback)
                    answer = engine.run_pair(*data)
                    check(answer['summary']['parents'] >= 1 and answer['summary']['unclosed'] == 0, '四モデルと両残差方向の実完結')
                    check(int(answer['orders'][0, 3]) == -sign, '高い脚を売り低い脚を買う')
                    check(int(answer['parents'][0, 5]) == 1, '固定モデル中心返済')
                    accounting(answer)
        for kind, reason in (('outer', 2), ('cash', 3), ('timeout', 4)):
            answer = engine.run_pair(*fixture(kind=kind))
            check(int(answer['parents'][0, 5]) == reason, '独立退出理由/' + kind)
            if kind in ('cash', 'timeout'):
                check(answer['parents'][0, 29] == 1., '両脚成立前も取消と返済/' + kind)
            accounting(answer)
        answer = engine.run_pair(*fixture(kind='no_fill'))
        check(answer['summary']['attempts'] == 1 and answer['summary']['canceled'] == 2
              and answer['summary']['parents'] == 0 and len(answer['orders']) == 0, 'ちょうど六十秒は失効先・遅延fillなし')
        for kind in ('stale', 'cost'):
            answer = engine.run_pair(*fixture(kind=kind))
            check(answer['summary']['attempts'] == 0, '公開時だけの審査/' + kind)
        data = list(fixture())
        data[4] = dict(data[4], close_time=data[2]['time'][0]+10., entry_end=data[2]['time'][0]+5.)
        answer = engine.run_pair(*data)
        check(int(answer['parents'][0, 5]) == 5, '中心同時でも既知場末が先')
        accounting(answer)

        # ----------------------------------------
        # 未来の板・価格・モデル足を変えても確定した以前の実注文は変わらない。
        data = fixture()
        full = engine.run_pair(*data)
        now = data[2]['time'][0]
        for offset in (0., 1., 1.5, 2., 10., 11., 12., 60.):
            cut = now + offset
            short = tuple(data[:2]) + tuple({k: v[q['time'] <= cut].copy() for k, v in q.items()} for q in data[2:4]) + (data[4],)
            partial = engine.run_pair(*short)
            expected = full['orders'][full['orders'][:, 6] <= cut]
            check(np.array_equal(partial['orders'], expected, equal_nan=True), '確定時計接頭/' + str(offset))
            if 0. < offset < 10.:
                check(partial['summary']['unclosed'] > 0, 'EOF保有を過去quoteへ清算しない/' + str(offset))
        nk, top, nq, tq, config = fixture()
        clocks = np.asarray([nq['time'][0]])
        baseline = engine.model_history(nk, top, clocks, 'ols_mr', 30)
        future = dict(nk, close=nk['close'].copy())
        future['close'][nk['t_s'] > clocks[0]-60.] *= 100.
        check(np.array_equal(baseline, engine.model_history(future, top, clocks, 'ols_mr', 30), equal_nan=True), 'tより一分前を越す未来足排除')
        delayed = dict(top, pub_price_time_s=top['pub_price_time_s'].copy())
        delayed['pub_price_time_s'][np.flatnonzero(top['t_s'] == clocks[0]-60.)[0]] = clocks[0]+.001
        check(engine.model_history(nk, delayed, clocks, 'ols_mr', 30)[0, 0] == 0., '未公表足を後からknownにしない')
        empty = dict(top, valid=top['valid'].copy())
        empty['valid'][np.flatnonzero(top['t_s'] == clocks[0]-600.)[0]] = False
        check(engine.model_history(nk, empty, clocks, 'ratio_mr', 30)[0, 0] == 0., '一致連続足の欠測は未知')
        qn, qt, error = engine.choose_quantities(65000., 4000., 1.)
        options = [(abs(n*10.*65000.-t*1000.*4000.)/((n*10.*65000.+t*1000.*4000.)/2.), n*10.*65000.+t*1000.*4000., n, t)
                   for n in range(1, 21) for t in range(1, 11)]
        options = [item for item in options if item[0] <= .05+1e-12]
        best = min(options)
        check((qn, qt) == (best[2], best[3]) and abs(error-best[0]) < 1e-12, '200整数組の独立全探索')
        nk, top, nq, tq, config = fixture()
        config = dict(config, entry_end=now+90., close_time=now+150.)
        nq = {key: value.copy() for key, value in nq.items()}
        nq['last'][nq['time'] >= now+91.] = 65000.
        nq['bid'], nq['ask'] = nq['last']-5., nq['last']+5.
        multiple = engine.run_pair(nk, top, nq, tq, config)
        check(multiple['summary']['parents'] >= 2, '中心再武装後の複数親')
        accounting(multiple)
        reference = engine.run_pair(*fixture())
        original = engine.replay
        engine.replay = original.py_func
        try:
            python = engine.run_pair(*fixture())
        finally:
            engine.replay = original
        for key in ('orders', 'parents', 'curve', 'models', 'positions'):
            check(np.allclose(reference[key], python[key], rtol=0., atol=1e-7, equal_nan=True), 'Python/JIT/' + key)
        for key in reference['summary']:
            check(abs(reference['summary'][key]-python['summary'][key]) < 1e-7, 'Python/JIT集計/' + key)
        for rate in (.1, -.1):
            raw = engine.replay(*common_clock_case(rate))
            orders, parents, _, _, _, _, _, _, counts = raw
            check(np.array_equal(orders[:, 6], 1800000000.+np.asarray([1., 2., 71., 72.])), '同時計共通変動では不要返済しない/' + str(rate))
            check(int(parents[0, 5]) == 1 and abs(counts[6]-144.) < 1e-6, '共同snapshotだけの残差と最大下落/' + str(rate))
            check(abs(parents[0, 36]+144.) < 1e-6, '親最大逆行へ同clock中間損失を混ぜない/' + str(rate))
            if rate == .1:
                check(abs(parents[0, 28]-11856.) < 1e-6, '同clock監査素材の独立純益11856円')
                check(abs(parents[0, 30]-2.) < 1e-6, '実際の単脚時計差だけを積算')
            py = engine.replay.py_func(*common_clock_case(rate))
            check(all(np.allclose(a, b, rtol=0., atol=1e-7, equal_nan=True) for a, b in zip(raw, py)), '共同snapshotのPythonJIT/' + str(rate))
        check(hashlib.sha256(economic.read_bytes()).hexdigest() == initial_sha, '人工中の核心源不変')
        proof = dict(全合格=True, 確認数=len(CHECKS), 確認=CHECKS,
            source_SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (economic, Path(__file__))},
            原市場読取=0, 保存cache読取=0, 既金融読取=0, 金融再生=0, API=0,
            留保='人工は実効性標本ではない。Lastは共通受信順を証明せず、EOF時価は実返済でない。')
    except BaseException as error:
        proof = dict(全合格=False, 成功確認数=len(CHECKS), error=repr(error),
            source_SHA256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (economic, Path(__file__))},
            原市場読取=0, 金融再生=0)
        (HERE / 'NT二脚の純人工初回False.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')
        raise
    output = HERE / 'NT二脚の個別約定と固定モデル及び接頭の純人工_v3.json'
    assert not output.exists()
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')
    print(json.dumps(dict(全合格=True, 確認数=len(CHECKS), SHA256=hashlib.sha256(output.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
