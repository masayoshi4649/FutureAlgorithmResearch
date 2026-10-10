"""NTペアの因果的な整数枚売買と、端数方向リスクの分解を行う。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
SESSIONS = ['2026-09-21_Day', '2026-09-21_Night', '2026-09-22_Day',
            '2026-09-22_Night', '2026-09-23_Day', '2026-09-23_Night',
            '2026-09-24_Day', '2026-09-24_Night']
SYMBOLS = ['NK225', 'TOPIX']
FAMILY_NAMES = {'ratio_mr': 'NT比の平均回帰', 'ratio_mom': 'NT比の持続', 'residual_mr': '回帰残差の平均回帰'}
SIZE_NAMES = ['ラージNK１枚にTOPIXを四捨五入', 'ラージ等金額の整数組合せ',
              'ラージ過去βの整数組合せ', 'mini相当NK10枚にTOPIXを四捨五入',
              'mini相当等金額の整数組合せ', '連続枚数の等金額診断']


def build_catalog() -> list[dict]:
    """機能: 成績を参照せず、６信号と６枚数方式の36条件を作る。

    引数: なし。返り値: 固定条件の一覧 (list[dict])。
    """
    result = []
    for family, levels in [('ratio_mr', [1.5, 2.0]), ('ratio_mom', [1.0, 1.5]), ('residual_mr', [1.5, 2.0])]:
        for threshold in levels:
            for mode, label in enumerate(SIZE_NAMES):
                result.append(dict(id=f'NT_{family}_Z{threshold:g}_S{mode}', family=family,
                    name=FAMILY_NAMES[family], threshold=threshold, sizing=mode, sizing_name=label,
                    lookback=60, momentum_minutes=15, delay_seconds=60, max_age_seconds=180,
                    risk_horizon_minutes=10, stop_r=1., target_r=2.5, trail_start_r=1.5,
                    trail_width_r=1., holding_minutes=120, cooldown_minutes=5,
                    gross_standard_limit=20, beta_min=.5, beta_max=2.,
                    executable_integer=mode != 5, mini_price_proxy=mode in (3, 4)))
    return result


def freeze_catalog() -> dict:
    """機能: 損益計算前の条件・約定・同期・丸め規則を新作業内へ保存する。

    引数: なし。返り値: 凍結記録 (dict)。既存ファイルがあれば同一内容だけ許す。
    """
    catalog = build_catalog()
    payload = json.dumps(catalog, ensure_ascii=False, indent=2)
    target = WORK/'NT_固定条件.json'
    if target.exists() and target.read_text(encoding='utf-8') != payload:
        raise ValueError('保存済みNT条件と異なるため上書きしません。')
    target.write_text(payload, encoding='utf-8')
    record = dict(固定時刻=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 条件数=len(catalog),
        条件SHA256=hashlib.sha256(payload.encode('utf-8')).hexdigest(), 損益を参照していない=True,
        注文規則='毎分時計で判断し、各脚をその時計より後の最初の有効な原本CurrentPriceで個別に約定。費用０。合算条件は個別価格を指定しないため、条件判断値で架空の同時約定を作らない。',
        同期規則='各銘柄の同一代理時刻ブロックは次の異なる時刻で封印。封印時刻から60秒後に公開。各分時計で両銘柄を後方asofし、価格の元時刻から180秒以内だけ利用。',
        決済規則='固定した１Rで損切り、2.5R利確、1.5R以上の最大利益から1Rの追跡返済、120分上限。平均回帰はzのゼロ交差でも返済。日15:35・夜05:50に返済指示し、その後の各脚最初の行で返済。新規は返済予定30分前で停止。',
        丸め規則='固定枚数は正数をfloor(x+0.5)で四捨五入。組合せは正整数の全組を標準合計20枚以内で列挙し、目標βからの相対想定元本差を最小化。同値なら合計枚数、NK枚数の小さい順。',
        同時刻順序='原本各銘柄内の行順を保持。異銘柄で同時刻はNK225→TOPIXの決定的順序を使用。真の受信順は不明であり、この順序で全行評価DDを測る。時計イベントは同時刻原本より後。新規・返済は厳密に後の時刻だけ。',
        診断区分='mini相当はJPX倍率100/1000をラージ原本価格へ適用した感度分析。実mini板での検証ではない。連続枚数は整数制約を外した診断で売買可能条件ではない。',
        枚数固定='数量と目標βは注文判断時の解放済み価格で固定し、保有中に変更しない。',
        期間='７完全セッションと既知の9/24ナイト23:19未満。すべて再探索資料で未見検証とは呼ばない。',
        参考資料=[{'名称':'JPX日経225先物', 'url':'https://www.jpx.co.jp/derivatives/products/domestic/225futures/'},
                 {'名称':'JPX TOPIX先物', 'url':'https://www.jpx.co.jp/derivatives/products/domestic/topix-futures/'},
                 {'名称':'JPX日経225mini', 'url':'https://www.jpx.co.jp/derivatives/products/domestic/225mini/'},
                 {'名称':'JPXミニTOPIX先物', 'url':'https://www.jpx.co.jp/derivatives/products/domestic/mini-topix-futures/'}])
    path = WORK/'NT_事前設計.json'
    if not path.exists():
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return json.loads(path.read_text(encoding='utf-8'))


def bounds(session: str) -> tuple[float, float]:
    """機能: セッション開始と返済指示時刻を返す。

    引数: session (str)。返り値: 開始秒と返済指示秒 (tuple[float, float])。
    """
    base = datetime.fromisoformat(session[:10]).replace(tzinfo=ZoneInfo('Asia/Tokyo'))
    night = session.endswith('Night')
    start = base + (timedelta(hours=17) if night else timedelta(hours=8, minutes=45))
    end = base + (timedelta(days=1, hours=5, minutes=50) if night else timedelta(hours=15, minutes=35))
    return start.timestamp(), end.timestamp()


def sealed(tape: dict, clocks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """機能: 同一時刻の末尾が確定した後さらに60秒待って過去価格を公開する。

    引数: tape (dict)、clocks (ndarray)。返り値: 後方参照価格と元時刻 (tuple[ndarray, ndarray])。
    """
    times = tape['time_s']
    last = np.flatnonzero(np.diff(times) > 0)
    release = times[last+1]+60.
    idx = np.searchsorted(release, clocks, side='right')-1
    valid = idx >= 0
    positions = last[np.maximum(idx, 0)]
    valid &= clocks-times[positions] <= 180.
    price = np.where(valid, tape['last'][positions], np.nan)
    source = np.where(valid, times[positions], np.nan)
    return price, source


def prepare_session(session: str, feature_root: Path | None = None,
                    tapes: list[dict] | None = None) -> dict:
    """機能: 保存済み真の約定系列から遅延付き毎分信号と全行順序を構成する。

    引数: session (str)、feature_root (Path|None)、tapes (list[dict]|None)。
    返り値: 再生入力 (dict)。ファイルを変更せず、通信しない。
    """
    if feature_root is None:
        feature_root = ROOT/('work/wave_v13/live/features' if session == '2026-09-24_Night' else 'work/wave_v13/features')
    if tapes is None:
        tapes = [dict(np.load(feature_root/f'約定系列_{symbol}_{session}.npz', allow_pickle=False)) for symbol in SYMBOLS]
    clean = []
    for tape in tapes:
        valid = np.isfinite(tape['time_s']) & np.isfinite(tape['last']) & (tape['last'] > 0)
        row = {k: np.asarray(tape[k])[valid] for k in ['seq', 'time_s', 'last']}
        if np.any(np.diff(row['time_s']) < 0) or np.any(np.diff(row['seq']) <= 0):
            raise ValueError('約定系列の原本順が不正です。')
        clean.append(row)
    start, limit = bounds(session)
    last_clock = np.floor(min(t['time_s'][-1] for t in clean)/60)*60
    clocks = np.arange(start, min(last_clock, limit)+1, 60.)
    values = [sealed(t, clocks) for t in clean]
    prices = np.column_stack([v[0] for v in values])
    sources = np.column_stack([v[1] for v in values])
    logs = np.log(prices)
    ratio = logs[:, 0]-logs[:, 1]
    delta = np.vstack([np.full(2, np.nan), np.diff(logs, axis=0)])
    features = np.full((len(clocks), 8), np.nan)
    for i in range(61, len(clocks)):
        past = logs[i-60:i]
        returns = delta[i-59:i+1]
        past = past[np.isfinite(past).all(axis=1)]
        returns = returns[np.isfinite(returns).all(axis=1)]
        if len(past) < 40 or len(returns) < 30 or not np.isfinite(logs[i]).all():
            continue
        ratios = past[:, 0]-past[:, 1]
        sd = float(np.std(ratios, ddof=1))
        z = (ratio[i]-np.mean(ratios))/sd if sd > 1e-9 else 0.
        ratio_returns = returns[:, 0]-returns[:, 1]
        vol = float(np.std(ratio_returns, ddof=1))
        momentum = (ratio[i]-ratio[i-15])/(vol*np.sqrt(15)) if vol > 1e-9 else 0.
        var = float(np.var(returns[:, 1], ddof=1))
        beta = float(np.clip(np.cov(returns.T)[0, 1]/var, .5, 2.)) if var > 1e-14 else 1.
        centered = past-past.mean(axis=0)
        den = float(centered[:, 1]@centered[:, 1])
        level_beta = float(centered[:, 1]@centered[:, 0]/den) if den > 1e-12 else 1.
        residual = centered[:, 0]-level_beta*centered[:, 1]
        residual_sd = float(np.std(residual, ddof=1))
        residual_now = logs[i, 0]-past[:, 0].mean()-level_beta*(logs[i, 1]-past[:, 1].mean())
        rz = residual_now/residual_sd if residual_sd > 1e-9 else 0.
        covariance = np.cov(returns.T)
        features[i] = [z, momentum, rz, beta, covariance[0, 0], covariance[1, 1], covariance[0, 1], level_beta]
    event_times = np.concatenate([clean[0]['time_s'], clean[1]['time_s'], clocks])
    event_types = np.concatenate([np.zeros(len(clean[0]['seq']), dtype=np.int64),
                                 np.ones(len(clean[1]['seq']), dtype=np.int64), np.full(len(clocks), 2, dtype=np.int64)])
    event_rows = np.concatenate([np.arange(len(t['seq'])) for t in clean]+[np.arange(len(clocks))])
    order = np.argsort(event_times, kind='stable')
    return dict(session=session, start=start, limit=limit, tapes=clean, clocks=clocks,
                prices=prices, sources=sources, features=features,
                event_times=event_times[order], event_types=event_types[order], event_rows=event_rows[order])


@njit(cache=True)
def quantities(mode, pn, pt, beta):
    """機能: 過去価格と過去βだけから整数枚または診断用連続枚数を決める。

    引数: mode (int)、pn/pt/beta (float)。返り値: 数量２個・倍率２個・目標β (tuple)。
    """
    mn, mt = (100., 1000.) if mode == 3 or mode == 4 else (1000., 10000.)
    wanted = beta if mode == 2 else 1.
    if mode == 0 or mode == 3 or mode == 5:
        qn = 10. if mode == 3 else 1.
        qt = qn*mn*pn/(mt*pt)
        if mode != 5:
            qt = max(1., np.floor(qt+.5))
        return qn, qt, mn, mt, wanted
    cap = 200 if mode == 4 else 20
    best = 1e9
    best_n, best_t, best_total = 1, 1, cap+1
    for qn in range(1, cap):
        ideal = wanted*qn*mn*pn/(mt*pt)
        for qt in (int(np.floor(ideal)), int(np.ceil(ideal))):
            if qt < 1 or qn+qt > cap:
                continue
            a, b = wanted*qn*mn*pn, qt*mt*pt
            error = abs(a-b)/(a+b)
            if error < best-1e-14 or (abs(error-best) <= 1e-14 and (qn+qt < best_total or (qn+qt == best_total and qn < best_n))):
                best, best_n, best_t, best_total = error, qn, qt, qn+qt
    return float(best_n), float(best_t), mn, mt, wanted


# ----------------------------------------
# 生価格の全行を評価し、注文後の個別約定時刻を保持する。
@njit(cache=True)
def replay(event_times, event_types, event_rows, tn, tt, pn, pt, seqn, seqt,
           clocks, prices, features, family, threshold, mode, start, limit):
    """機能: 一度に１組だけ保有し、合算損益条件を将来の２脚約定へ変換する。

    引数: 原本/毎分/特徴配列 (ndarray)、family/mode (int)、閾値/境界 (float)。
    返り値: サイクル・全行資産評価・集計 (tuple[ndarray, ndarray, ndarray])。
    """
    cycles = np.full((len(clocks)+2, 29), np.nan)
    curve = np.zeros((len(event_times), 8))
    active, closing, pending = False, False, False
    current = np.full(2, np.nan)
    ep, xp, et, xt = np.full(2, np.nan), np.full(2, np.nan), np.full(2, np.nan), np.full(2, np.nan)
    es, xs, eqty = np.full(2, -1, dtype=np.int64), np.full(2, -1, dtype=np.int64), np.zeros(2)
    q = np.ones(2)
    multipliers = np.array([1000., 10000.])
    order_time, exit_order_time, cooldown_until = -1., -1., start
    side, reason, n, nc = 0, 0, 0, 0
    risk, peak_profit, realized, peak_equity, maxdd, grosspeak = 1., 0., 0., 0., 0., 0.
    target_beta, decision_n, decision_t = 1., 0., 0.
    for k in range(len(event_times)):
        now, kind, row = event_times[k], event_types[k], event_rows[k]
        if kind < 2:
            price = pn[row] if kind == 0 else pt[row]
            sequence = seqn[row] if kind == 0 else seqt[row]
            current[kind] = price
            if pending and now > order_time and not np.isfinite(ep[kind]):
                ep[kind], et[kind], es[kind] = price, now, sequence
                eqty[kind] = q[kind]
                active = True
                if np.isfinite(ep).all():
                    pending = False
            if closing and now > exit_order_time and np.isfinite(ep[kind]) and not np.isfinite(xp[kind]):
                xp[kind], xt[kind], xs[kind] = price, now, sequence
                sign = side if kind == 0 else -side
                realized += sign*q[kind]*multipliers[kind]*(price-ep[kind])
                eqty[kind] = 0.
            if closing and np.isfinite(xp).all():
                cycles[n, :27] = np.array([side, order_time, exit_order_time, risk, q[0], q[1], multipliers[0], multipliers[1],
                    ep[0], ep[1], xp[0], xp[1], et[0], et[1], xt[0], xt[1], es[0], es[1], xs[0], xs[1],
                    reason, 1., target_beta, decision_n, decision_t, peak_profit, 0.])
                cycles[n, 27:29] = 1., 1.
                n += 1
                active, closing, pending = False, False, False
                cooldown_until = now+300.
                ep[:], xp[:], et[:], xt[:] = np.nan, np.nan, np.nan, np.nan
                es[:], xs[:], eqty[:] = -1, -1, 0.
        else:
            # ----------------------------------------
            # 時計時点では解放済みの双方だけを参照する。
            if active and not closing and not pending:
                mark = prices[row]
                profit = side*(q[0]*multipliers[0]*(mark[0]-ep[0])-q[1]*multipliers[1]*(mark[1]-ep[1]))
                if now >= limit:
                    reason = 5
                elif now-order_time >= 7200.:
                    reason = 4
                elif np.isfinite(profit):
                    peak_profit = max(peak_profit, profit)
                    z = features[row, family]
                    if profit <= -risk:
                        reason = 1
                    elif profit >= 2.5*risk:
                        reason = 2
                    elif peak_profit >= 1.5*risk and profit <= peak_profit-risk:
                        reason = 3
                    elif family != 1 and np.isfinite(z) and side*z >= 0:
                        reason = 6
                    else:
                        reason = 0
                else:
                    reason = 0
                if reason:
                    closing, exit_order_time = True, now
            if not active and not pending and now >= cooldown_until and now < limit-1800.:
                z = features[row, family]
                if not np.isfinite(z) or abs(z) < threshold:
                    continue
                side = (1 if z > 0 else -1)*(1 if family == 1 else -1)
                decision_n, decision_t = prices[row, 0], prices[row, 1]
                qn, qt, mn, mt, target_beta = quantities(mode, decision_n, decision_t, features[row, 3])
                q[:] = qn, qt
                multipliers[:] = mn, mt
                h = qt*mt*decision_t/(qn*mn*decision_n)
                variance = max(0., features[row, 4]+h*h*features[row, 5]-2*h*features[row, 6])
                risk = max(qn*mn*decision_n*np.sqrt(10*variance), 2*np.sqrt((qn*mn*10.)**2+(qt*mt*.5)**2))
                if not np.isfinite(risk) or risk <= 0:
                    continue
                pending, order_time, peak_profit = True, now, 0.
        open_pnl, gross, count = 0., 0., 0.
        for j in range(2):
            if eqty[j] > 0 and np.isfinite(current[j]):
                sign = side if j == 0 else -side
                open_pnl += sign*eqty[j]*multipliers[j]*(current[j]-ep[j])
                gross += eqty[j]*multipliers[j]/(1000. if j == 0 else 10000.)
                count += 1
        equity = realized+open_pnl
        peak_equity = max(peak_equity, equity)
        maxdd = max(maxdd, peak_equity-equity)
        grosspeak = max(grosspeak, gross)
        curve[nc] = np.array([now, realized, open_pnl, equity, peak_equity-equity, gross, kind, row])
        nc += 1
    if active:
        finished = np.isfinite(xp)
        for j in range(2):
            if not np.isfinite(ep[j]):
                q[j] = 0.
                ep[j] = decision_n if j == 0 else decision_t
                et[j], es[j] = order_time, -1
            if not np.isfinite(xp[j]):
                xp[j] = current[j]
                xt[j] = tn[-1] if j == 0 else tt[-1]
                xs[j] = seqn[-1] if j == 0 else seqt[-1]
        cycles[n, :27] = np.array([side, order_time, exit_order_time, risk, q[0], q[1], multipliers[0], multipliers[1],
            ep[0], ep[1], xp[0], xp[1], et[0], et[1], xt[0], xt[1], es[0], es[1], xs[0], xs[1],
            0., 0., target_beta, decision_n, decision_t, peak_profit, float(np.count_nonzero(eqty > 0))])
        cycles[n, 27:29] = finished.astype(np.float64)
        n += 1
    return cycles[:n], curve[:nc], np.array([realized, open_pnl, realized+open_pnl, maxdd, grosspeak])


def decomposition(side: int, qn: float, qt: float, mn: float, mt: float,
                  en: float, et: float, xn: float, xt: float, beta: float = 1.) -> dict:
    """機能: ２脚合計を相対価格変化と共通方向端数へ恒等分解する。

    引数: side (int)、数量・倍率・新規価格・評価価格・beta (float)。
    返り値: 円額と分解項目 (dict)。新規価格で固定した想定元本を用いる。
    """
    a, b = qn*mn*en, qt*mt*et
    rn, rt = (xn-en)/en, (xt-et)/et
    relative = side*(a+b)/2*(rn-rt)
    common = side*(a-b)*(rn+rt)/2
    beta_relative = side*a*(rn-beta*rt)
    beta_rounding = side*(beta*a-b)*rt
    return dict(net_yen=side*(qn*mn*(xn-en)-qt*mt*(xt-et)), relative_yen=relative,
                common_residual_yen=common, beta_relative_yen=beta_relative,
                beta_rounding_yen=beta_rounding, entry_notional_nk=a, entry_notional_topix=b,
                relative_mismatch=abs(a-b)/(a+b), beta_mismatch=abs(beta*a-b)/(beta*a+b))


def run(prepared: dict, config: dict, detail: bool = True) -> dict:
    """機能: 固定した１条件のペア損益・各脚・全玉DDと厳密分解を返す。

    引数: prepared/config (dict)、detail (bool)。返り値: summary/cycles/legs/curve (dict)。
    """
    p = prepared
    nk, top = p['tapes']
    family = ['ratio_mr', 'ratio_mom', 'residual_mr'].index(config['family'])
    raw, curve, metrics = replay(p['event_times'], p['event_types'], p['event_rows'],
        nk['time_s'], top['time_s'], nk['last'], top['last'], nk['seq'], top['seq'],
        p['clocks'], p['prices'], p['features'], family, config['threshold'], config['sizing'], p['start'], p['limit'])
    cycles, legs = [], []
    reasons = {0:'打切り時評価', 1:'合算１R損切り', 2:'合算2.5R利確', 3:'合算１R追跡', 4:'120分上限', 5:'セッション内返済', 6:'残差のゼロ交差'}
    for i, r in enumerate(raw):
        side, order, exit_order, risk, qn, qt, mn, mt, en, et, xn, xt, tne, tte, tnx, ttx, sne, ste, snx, stx, reason, complete, beta, dn, dt, peak, open_count, closed_n, closed_t = r
        if not np.isfinite([en, et]).all():
            raise ValueError('片脚だけの新規でデータが終了しました。独立会計を追加する必要があります。')
        dec = decomposition(int(side), qn, qt, mn, mt, en, et, xn, xt, beta)
        closed_net, open_net = 0., 0.
        for j, symbol in enumerate(SYMBOLS):
            q, mult, entry, out, te, tx, se, sx = (qn, mn, en, xn, tne, tnx, sne, snx) if j == 0 else (qt, mt, et, xt, tte, ttx, ste, stx)
            if q == 0:
                continue
            leg_side = int(side) if j == 0 else -int(side)
            closed = bool(closed_n if j == 0 else closed_t)
            pnl = leg_side*q*mult*(out-entry)
            closed_net += pnl if closed else 0.
            open_net += 0. if closed else pnl
            legs.append(dict(method=config['id'], session=p['session'], symbol=symbol, cycle_id=i, side=leg_side,
                quantity=q, multiplier=mult, entry_price=entry, exit_price=out, entry_time=te, exit_time=tx,
                entry_seq=int(se), exit_seq=int(sx), complete=closed, net_yen=pnl, risk_yen=risk,
                entry_order=order, exit_order=exit_order, reason=reasons[int(reason)]))
        leg_count = int(qn > 0)+int(qt > 0)
        item = dict(method=config['id'], symbol='NT', session=p['session'], cycle_id=i,
            complete=bool(complete), legs=leg_count, closed_legs=leg_count-int(open_count), open_legs=int(open_count),
            risk_yen=risk, net_points=dec['net_yen'], closed_points=closed_net, open_points=open_net,
            closed_yen=closed_net, open_yen=open_net,
            net_atr=dec['net_yen']/risk, closed_atr=closed_net/risk, open_atr=open_net/risk,
            net_r=dec['net_yen']/risk, closed_r=closed_net/risk, open_r=open_net/risk,
            cap=20, gross_standard=qn*mn/1000+qt*mt/10000, entry_order=order, exit_order=exit_order,
            entry_time_s=min(tne, tte), exit_time_s=max(tnx, ttx),
            holding_minutes=(max(tnx, ttx)-min(tne, tte))/60, reason=reasons[int(reason)],
            nk_quantity=qn, topix_quantity=qt, nk_multiplier=mn, topix_multiplier=mt,
            target_beta=beta, decision_nk=dn, decision_topix=dt, **dec)
        cycles.append(item)
    complete = [c for c in cycles if c['complete']]
    wins = [c['net_yen'] for c in complete if c['net_yen'] > 0]
    losses = [c['net_yen'] for c in complete if c['net_yen'] < 0]
    all_r = [c['net_r'] for c in complete]
    win_r, loss_r = [r for r in all_r if r > 0], [r for r in all_r if r < 0]
    summary = dict(method=config['id'], symbol='NT', session=p['session'], family=config['family'],
        sizing=config['sizing_name'], integer=config['executable_integer'], mini_proxy=config['mini_price_proxy'],
        profit_yen=sum(wins), loss_yen=sum(losses), closed_net_yen=float(metrics[0]), open_yen=float(metrics[1]),
        net_yen=float(metrics[2]), max_drawdown_yen=float(metrics[3]), gross_peak=float(metrics[4]),
        complete_cycles=len(complete), open_cycles=len(cycles)-len(complete), win_cycles=len(wins),
        win_rate=len(wins)/len(complete) if complete else None,
        pf=sum(wins)/-sum(losses) if losses else None,
        average_win_yen=float(np.mean(wins)) if wins else None, average_loss_yen=float(np.mean(losses)) if losses else None,
        payoff=float(np.mean(wins)/-np.mean(losses)) if wins and losses else None,
        mean_r=float(np.mean(all_r)) if all_r else None, sum_r=sum(all_r),
        pf_r=sum(win_r)/-sum(loss_r) if loss_r else None,
        payoff_r=float(np.mean(win_r)/-np.mean(loss_r)) if win_r and loss_r else None,
        relative_yen=sum(c['relative_yen'] for c in cycles), common_residual_yen=sum(c['common_residual_yen'] for c in cycles),
        beta_relative_yen=sum(c['beta_relative_yen'] for c in cycles), beta_rounding_yen=sum(c['beta_rounding_yen'] for c in cycles),
        average_mismatch=float(np.mean([c['relative_mismatch'] for c in cycles])) if cycles else None,
        points_unit='ペアのpointsは２脚合計円額。ATR列は予定１R換算。単独銘柄ポイントとは比較しない。')
    # ----------------------------------------
    # DDは全行で算出し、表示用曲線だけ各分末尾と約定前後へ間引く。
    if detail and len(curve):
        keep = np.r_[np.floor(curve[:-1, 0]/60) != np.floor(curve[1:, 0]/60), True]
        for leg in legs:
            for time in (leg['entry_time'], leg['exit_time']):
                loc = np.searchsorted(curve[:, 0], time)
                keep[max(0, loc-1):min(len(keep), loc+3)] = True
        display = curve[keep].tolist()
    else:
        display = []
    return dict(summary=summary, cycles=cycles, legs=legs, curve=display,
                full_curve=curve if detail else None)


def integrated_catalog() -> list[dict]:
    """機能: 固定条件を変更せず、親の比率選択器で必要な分類情報だけを足す。

    引数: なし。返り値: 分類を追加した36条件 (list[dict])。
    """
    return [dict(c, philosophy='NTペアと整数枚ヘッジ', group='２銘柄相対価格', origin='新規',
                 label=c['name']+'／'+c['sizing_name'], max_legs=20, engine='pair',
                 diagnostic_only=c['sizing'] in (3, 4, 5)) for c in build_catalog()]


def split_at_boundary(result: dict, prepared: dict, boundary: float) -> dict:
    """機能: 既知区間から持ち越した含みを境界直前の価格で差し引く。

    引数: result/prepared (dict)、boundary (float): 新しい評価区間の開始Unix秒。
    返り値: 境界以後の増分サイクル・脚・全評価曲線 (dict)。売買判断は再生し直さない。
    """
    marks = {}
    for symbol, tape in zip(SYMBOLS, prepared['tapes']):
        i = np.searchsorted(tape['time_s'], boundary, side='left')-1
        if i < 0:
            raise ValueError('境界前の評価価格がありません。')
        marks[symbol] = float(tape['last'][i])
    legs = []
    for original in result['legs']:
        if original['exit_time'] < boundary:
            continue
        leg = dict(original)
        leg['carried'] = original['entry_time'] < boundary
        leg['original_entry_price'] = original['entry_price']
        leg['original_entry_time'] = original['entry_time']
        if leg['carried']:
            leg['entry_price'] = marks[leg['symbol']]
            leg['entry_time'] = boundary
        leg['net_yen'] = leg['side']*leg['quantity']*leg['multiplier']*(leg['exit_price']-leg['entry_price'])
        legs.append(leg)
    cycles = []
    for original in result['cycles']:
        part = [leg for leg in legs if leg['cycle_id'] == original['cycle_id']]
        if not part:
            continue
        row = dict(original)
        row.update(legs=len(part), closed_legs=sum(x['complete'] for x in part), open_legs=sum(not x['complete'] for x in part),
                   complete=bool(all(x['complete'] for x in part)), boundary=boundary,
                   carried=any(x['carried'] for x in part), entry_time_s=min(x['entry_time'] for x in part),
                   exit_time_s=max(x['exit_time'] for x in part))
        for kind in ('net', 'closed', 'open'):
            pnl = sum(x['net_yen'] for x in part if kind == 'net' or (kind == 'closed' and x['complete']) or (kind == 'open' and not x['complete']))
            row[kind+'_yen'], row[kind+'_points'] = pnl, pnl
            row[kind+'_r'], row[kind+'_atr'] = pnl/row['risk_yen'], pnl/row['risk_yen']
        by_symbol = {x['symbol']:x for x in part}
        fallback = dict(quantity=0., multiplier=1000., entry_price=marks['NK225'], exit_price=marks['NK225'])
        nk = by_symbol.get('NK225', fallback)
        fallback = dict(quantity=0., multiplier=10000., entry_price=marks['TOPIX'], exit_price=marks['TOPIX'])
        top = by_symbol.get('TOPIX', fallback)
        side = by_symbol['NK225']['side'] if 'NK225' in by_symbol else -by_symbol['TOPIX']['side']
        row.update(decomposition(side, nk['quantity'], top['quantity'], nk['multiplier'], top['multiplier'],
                                  nk['entry_price'], top['entry_price'], nk['exit_price'], top['exit_price'], row['target_beta']))
        cycles.append(row)
    full = result.get('full_curve')
    baseline = float(full[full[:, 0] < boundary][-1, 3]) if full is not None and np.any(full[:, 0] < boundary) else 0.
    after = full[full[:, 0] >= boundary].copy() if full is not None else np.empty((0, 8))
    equity = np.column_stack([after[:, 0], after[:, 3]-baseline])
    peak = np.maximum.accumulate(np.r_[0., equity[:, 1]])[1:]
    dd = float(np.max(peak-equity[:, 1])) if len(equity) else 0.
    final = float(equity[-1, 1]) if len(equity) else 0.
    np.testing.assert_allclose(sum(c['net_yen'] for c in cycles), final, atol=1e-5)
    return dict(cycles=cycles, legs=legs, curve=equity, baseline_equity_yen=baseline,
                net_yen=final, max_drawdown_yen=dd, boundary_prices=marks,
                explanation='境界前の含み損益を差し引いた増分。持越し組は新規売買と区別する。')


def json_write(name: str, value: object) -> None:
    """機能: NumPy型を標準型へ変換してUTF-8のJSONを保存する。

    引数: name (str)、value (object)。返り値: なし (None)。
    """
    text = json.dumps(value, ensure_ascii=False, indent=2, default=lambda x: x.item() if isinstance(x, np.generic) else x.tolist(), allow_nan=False)
    (WORK/name).write_text(text, encoding='utf-8')


def main() -> None:
    """機能: 条件事前保存と、許可済み保存期間の再生を別々に実行する。

    引数: コマンドライン (argparse)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser(description='NTペアの固定条件と保存済み原本の再生')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.freeze:
        print(json.dumps(freeze_catalog(), ensure_ascii=False))
    if args.run:
        if not (WORK/'NT_事前設計.json').exists():
            raise ValueError('先に--freezeが必要です。')
        configs = json.loads((WORK/'NT_固定条件.json').read_text(encoding='utf-8'))
        summaries, cycles, legs, curves = [], [], [], {}
        for session in SESSIONS:
            prepared = prepare_session(session)
            for cfg in configs:
                result = run(prepared, cfg)
                summaries.append(result['summary'])
                cycles.extend(result['cycles'])
                legs.extend(result['legs'])
                curves[cfg['id']+'|'+session] = result['curve']
            print(json.dumps(dict(完了=session, 条件数=len(configs)), ensure_ascii=False), flush=True)
        pd.DataFrame(summaries).to_csv(WORK/'NT_セッション集計.csv', index=False, encoding='utf-8-sig')
        json_write('NT_サイクル.json', cycles)
        json_write('NT_全脚.json', legs)
        json_write('NT_資産曲線.json', curves)


if __name__ == '__main__':
    main()
