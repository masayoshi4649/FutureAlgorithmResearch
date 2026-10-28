"""確定利益で残す一枚の退出・後続候補への切替を、当時の通知と気配だけで管理する。"""

import numpy as np
from numba import njit


TRACE_COLUMNS = ["原行", "親ID", "種類", "方向", "枚数", "理由", "他玉利益見込", "実現利益", "残玉予算", "固定R", "残玉進捗", "残玉最高進捗", "未約定件数"]
REASONS = {14501: "反対候補で残玉返済", 14502: "新候補で残玉返済", 14503: "既得含み益の保護床", 14504: "残玉追尾幅の上限", 14520: "残玉返済後に方向を確認して再参加", 14521: "待機中に元候補が終了", 14522: "再参加時の短期方向不成立"}


def configurations():
    """比較する十二条件を事前固定する。

    引数: なし。
    返り値: list[dict]はR00～R11。費用0、同一枠、同じ元候補に対する比較。
    """
    base = dict(id="R00", name="元H04の一枚保持", enabled=True, trail_r=3., profit_fraction=1.,
                lock_fraction=0., cap_ticks=0., replace_mode=0, reentry_wait=0.,
                reentry_momentum=True, partial_mode=0, partial_return_fraction=0., partial_reasons=[7,30,1435],
                eligible_reasons=[2, 70, 1437], quiet_seconds=900., fee10=0,
                rule="新候補は残玉保有中に見送る。残玉化時に固定したRで追尾する。")
    result = [base, dict(base, id="R01", name="残玉なしで全返済", enabled=False),
              dict(base, id="R02", name="他玉利益の25%だけ残玉予算", profit_fraction=.25),
              dict(base, id="R03", name="残玉を1Rで追尾", trail_r=1.),
              dict(base, id="R04", name="残玉化時の含み益50%を床にする", lock_fraction=.5),
              dict(base, id="R05", name="残玉追尾を最大16呼値にする", cap_ticks=16.)]
    for number, wait in enumerate((0., 60., 300., 900.), 6):
        result.append(dict(base, id=f"R{number:02d}", name=f"反対候補へ切替・返済後{int(wait)}秒から再評価",
            replace_mode=1, reentry_wait=wait,
            rule="反対方向の新候補が実際に通知されたら残玉返済を判断。返済約定後の指定秒数から、元候補の残存・自己30秒順行・自己120秒非逆行・正常気配・静観外を確認して新規判断。満たすまで待ち、候補終了なら取消。実新規は判断後の次正常気配。"))
    result.append(dict(result[6], id="R10", name="同方向も含む新候補へ切替", replace_mode=2,
        rule=result[6]["rule"].replace("反対方向の新候補", "方向を問わない新候補")))
    result.append(dict(result[7], id="R11", name="反対60秒・既得益50%床・16呼値追尾上限", lock_fraction=.5, cap_ticks=16.))
    for number, mode, fraction, name in ((1,1,.5,"部分利確後ピークの50%戻りで残全返済"),
                                         (2,1,.3,"部分利確後ピークの30%戻りで残全返済"),
                                         (3,2,0.,"部分利確後の最高値から1Rで残全返済"),
                                         (4,3,0.,"部分利確価格の支持破綻と120秒逆行15秒で残全返済")):
        result.append(dict(base, id=f"P{number:02d}", name=name, partial_mode=mode, partial_return_fraction=fraction,
            rule="元の理由7/30/1435による部分返済の実約定が黒字で残玉があるとき開始。最初の部分返済直後の残玉平均建値と返済価格を固定し、それ以降のピークだけ追う。元予約完了後に残玉全返済を新規判断、次正常気配で約定。強制返済した親の以降追加は拒否し、新しい親には参加できる。未発動なら元H04を維持。"))
    for config in result:
        config['scope'] = "基本担当のみ。追加A3・別入口CS04は固定" if config['id'].startswith('P') else "基本CG・別入口CSの双方。同一条件。追加A3は固定"
    return result


@njit(cache=True)
def kernel(times, bid, ask, valid, atr, features, tick, end, us_open, rows, ep, et, pv, tp, tv,
           reasons, trail_r, fraction, quiet_seconds, lock_fraction, cap_ticks, replace_mode, wait_seconds, momentum, fee10,
           partial_mode, partial_fraction, partial_reasons):
    """通知・予約・実保有を分離し、残玉の返済後にだけ後続候補へ新たに参加する。

    引数: 時系列・価格・候補対応(ndarray)、幅・時刻(float)、切替・費用(int)、勢い条件(bool)。
    返り値: tuple[ndarray,ndarray]は十列約定と十三列診断。価格の鏡像で売買は対称。
    """
    n, count, npart, nticket = len(times), len(rows), len(pv), len(tv)
    out = np.empty((count * 4 + npart * 4 + 64, 11))
    log = np.empty((count * 5 + npart * 12 + 64, 13))
    queue = np.zeros((count * 4 + npart * 4 + 64, 8))
    # 予約列は判断行・親添字・玉添字・枚数・新規・理由・並び順・残玉返済の区別。
    nq = fq = no = nl = 0
    status = np.zeros(npart, np.int64)
    virtual = np.zeros(npart, np.int64)
    vt = np.zeros(nticket, np.int64)
    actual = np.zeros(nticket, np.int64)
    entry = np.zeros(nticket)
    first_fill = np.full(nticket, n + 1, np.int64)
    cash = np.zeros(npart)
    fixed_r = np.zeros(npart)
    sides = np.zeros(npart, np.int64)
    partial_started = np.zeros(npart,np.bool_)
    partial_anchor = np.zeros(npart)
    partial_level = np.zeros(npart)
    partial_best = np.zeros(npart)
    partial_since = np.full(npart,-np.inf)
    partial_forced = np.zeros(npart,np.int64)
    decision_order = np.argsort(rows[:, 1], kind="mergesort")
    owner = retained = waiting = -1
    di = total = pending = stage = force_reason = 0
    budget = estimate = best = protected = 0.
    wait_ready = np.inf
    synthetic_pending = False
    fee_one = fee10 // 10
    for i in range(n):
        now = times[i]
        terminal = now >= end
        quiet = np.isfinite(us_open) and us_open - quiet_seconds <= now < us_open + quiet_seconds
        # ----------------------------------------
        # 一度発注した予約は現在の方向・時刻で消さず、次の正常な自己原行で約定する。
        while fq < nq and queue[fq, 0] < i and valid[i]:
            decision, p, u, q, new, reason, ordering, residual_close = queue[fq]
            p, u, q, new = int(p), int(u), int(q), int(new)
            assert p == owner and q > 0
            side = sides[p] if new else -sides[p]
            price = ask[i] if side > 0 else bid[i]
            fee = q * fee10 // 10
            if new:
                before = actual[u]
                entry[u] = (entry[u] * before + price * q) / (before + q)
                actual[u] += q
                first_fill[u] = min(first_fill[u], i)
                total += q
                cash[p] -= fee
            else:
                assert actual[u] >= q
                closed_gain = sides[p] * (price - entry[u]) * q * 100. - fee
                cash[p] += closed_gain
                actual[u] -= q
                total -= q
                if (partial_mode > 0 and not partial_started[p] and total > 0 and closed_gain > 0.
                        and not residual_close and np.any(partial_reasons == int(reason))):
                    average = 0.
                    for v in range(nticket):
                        if tp[v] == p:
                            average += entry[v]*actual[v]
                    partial_anchor[p] = average/total
                    partial_level[p] = price
                    partial_best[p] = max(0., sides[p]*(price-partial_anchor[p]))
                    partial_started[p] = True
            out[no] = np.array([i, decision, pv[p], side, q, price, reason, new, tv[u], fee, ordering])
            no += 1
            pending -= 1
            if residual_close == 1:
                assert total == 0
                retained, stage, force_reason = -1, 0, 0
                synthetic_pending = False
                if waiting >= 0:
                    wait_ready = now + wait_seconds
            fq += 1
        if owner >= 0 and total == 0 and pending == 0 and stage == 0:
            owner = -1
        if stage > 0:
            if terminal:
                force_reason = 93
            elif quiet and force_reason == 0:
                force_reason = 94
        stop = di
        while stop < count and int(rows[decision_order[stop], 1]) == i:
            stop += 1
        withheld_event = -1
        # ----------------------------------------
        # 元の利益追尾が全返済を通知したときだけ、他玉利益で最古の一枚を残せるか確認する。
        if owner >= 0 and status[owner] == 1 and partial_forced[owner] == 0 and stage == 0 and pending == 0 and total > 0 and valid[i] and not terminal and not quiet and stop > di:
            new_quantity = close_quantity = 0
            eligible = True
            for pos in range(di, stop):
                k = decision_order[pos]
                if ep[k] == owner:
                    if rows[k, 7] > 0.:
                        new_quantity += int(rows[k, 4])
                    else:
                        close_quantity += int(rows[k, 4])
                        eligible = eligible and np.any(reasons == int(rows[k, 6]))
            if eligible and new_quantity == 0 and close_quantity > 0 and close_quantity == virtual[owner]:
                side = sides[owner]
                price = bid[i] if side > 0 else ask[i]
                candidate, age = -1, n + 2
                for u in range(nticket):
                    if tp[u] == owner and actual[u] > 0 and side * (price-entry[u]) * 100. > fee_one and first_fill[u] < age:
                        candidate, age = u, first_fill[u]
                if candidate >= 0:
                    estimate = cash[owner]
                    trial_event = -1
                    for pos in range(di, stop):
                        k = decision_order[pos]
                        if ep[k] != owner or rows[k, 7] > 0.:
                            continue
                        q, u = int(rows[k, 4]), et[k]
                        if u == candidate and trial_event < 0:
                            q -= 1
                            trial_event = k
                        estimate += side * (price-entry[u]) * q * 100. - q * fee10 // 10
                    if estimate > 0. and trial_event >= 0:
                        withheld_event, retained, stage, force_reason = trial_event, candidate, 1, 0
                        log[nl] = np.array([i, pv[owner], 2, side, 1, 0, estimate, cash[owner], 0., fixed_r[owner], side*(price-entry[retained]), 0., pending])
                        nl += 1
        # ----------------------------------------
        # 元候補の現在数量は全通知で進める。遅延参加は未来の源約定価格・未来収支を読まない。
        while di < stop:
            k = decision_order[di]
            p, u, q = ep[k], et[k], int(rows[k, 4])
            assert int(rows[k, 1]) == i and int(rows[k, 0]) > i
            if rows[k, 7] > 0.:
                virtual[p] += q
                vt[u] += q
                if status[p] == 0:
                    sides[p] = int(rows[k, 3])
                    fixed_r[p] = max(atr[i], 8.*tick) if np.isfinite(atr[i]) and atr[i] > 0. else 8.*tick
                    admitted = owner < 0 and waiting < 0
                    switched = (owner >= 0 and stage == 2 and pending == 0 and not synthetic_pending
                        and waiting < 0 and replace_mode > 0 and valid[i] and not terminal and not quiet
                        and (replace_mode == 2 or sides[p] != sides[owner]))
                    status[p] = 1 if admitted else (2 if switched else -1)
                    if admitted:
                        owner = p
                    if switched:
                        waiting = p
                        wait_ready = np.inf
                        force_reason = 14501 if sides[p] != sides[owner] else 14502
                    log[nl] = np.array([i, pv[p], 1, sides[p], q if admitted else 0, 0 if admitted else (force_reason if switched else 14384), 0., 0., 0., fixed_r[p], 0., 0., pending])
                    nl += 1
            else:
                virtual[p] -= q
                vt[u] -= q
                assert virtual[p] >= 0 and vt[u] >= 0
            use = q if status[p] == 1 else 0
            if k == withheld_event:
                use -= 1
            assert use >= 0
            if use:
                assert p == owner
                queue[nq] = np.array([i, p, u, use, rows[k, 7], rows[k, 6], k, 0])
                nq += 1
                pending += 1
            di += 1
        # ----------------------------------------
        # 利益予算と既得益床は他玉の返済確認後だけ確定する。残玉の過去ピークを遡及利用しない。
        if stage == 1 and pending == 0:
            assert owner >= 0 and total == 1 and actual[retained] == 1
            side = sides[owner]
            if cash[owner] <= 0.:
                force_reason = 14382 if force_reason == 0 else force_reason
            budget = max(0., cash[owner]) * fraction
            price = bid[i] if side > 0 else ask[i]
            best = side * (price-entry[retained])
            protected = max(0., best) * lock_fraction if lock_fraction > 0. else -np.inf
            stage = 2
            log[nl] = np.array([i, pv[owner], 3, side, 1, force_reason, estimate, cash[owner], budget, fixed_r[owner], best, best, pending])
            nl += 1
        if stage == 2 and not synthetic_pending:
            side = sides[owner]
            reason, gain = force_reason, np.nan
            if valid[i]:
                price = bid[i] if side > 0 else ask[i]
                gain = side * (price-entry[retained])
                best = max(best, gain)
                budget_floor = (fee_one-budget)/100.
                width = trail_r*fixed_r[owner]
                capped = cap_ticks > 0. and width > cap_ticks*tick
                if capped:
                    width = cap_ticks*tick
                trail_floor = best-width
                floor = max(budget_floor, trail_floor, protected)
                if reason == 0 and gain <= floor:
                    reason = 14503 if protected >= max(budget_floor,trail_floor) else (14381 if budget_floor >= trail_floor else (14504 if capped else 14380))
            if reason:
                queue[nq] = np.array([i, owner, retained, 1, 0, reason, 1.e12+no, 1])
                nq += 1
                pending += 1
                synthetic_pending = True
                log[nl] = np.array([i, pv[owner], 4, side, 1, reason, estimate, cash[owner], budget, fixed_r[owner], gain, best, pending-1])
                nl += 1
        # ----------------------------------------
        # 黒字の部分返済を実確認した後だけ、残る複数玉の利益返しを管理する。
        if owner >= 0 and stage == 0 and total > 0 and (status[owner] == 1 or partial_forced[owner] > 0) and partial_started[owner] and partial_mode > 0:
            p, side = owner, sides[owner]
            if valid[i]:
                mark = bid[i] if side > 0 else ask[i]
                gain = side*(mark-partial_anchor[p])
                partial_best[p] = max(partial_best[p], gain)
                if partial_mode == 1 and partial_best[p] > 0. and gain <= partial_best[p]*(1.-partial_fraction):
                    partial_forced[p] = 14530 + partial_mode
                elif partial_mode == 2 and partial_best[p] > 0. and gain <= partial_best[p]-fixed_r[p]:
                    partial_forced[p] = 14530 + partial_mode
                elif partial_mode == 3:
                    if i > 0 and now-times[i-1] > 15.:
                        partial_since[p] = -np.inf
                    bad = partial_best[p] > 0. and side*(mark-partial_level[p]) < -.1*fixed_r[p] and np.isfinite(features[i,13]) and side*features[i,13] < 0.
                    if bad:
                        if not np.isfinite(partial_since[p]):
                            partial_since[p] = now
                        if now-partial_since[p] >= 15.:
                            partial_forced[p] = 14533
                    else:
                        partial_since[p] = -np.inf
            else:
                partial_since[p] = -np.inf
            if partial_forced[p] > 0:
                status[p] = -1
            if partial_forced[p] > 0 and pending == 0:
                for u in range(nticket):
                    if tp[u] == p and actual[u] > 0:
                        queue[nq] = np.array([i,p,u,actual[u],0,partial_forced[p],1.e12+no+nq,2])
                        nq += 1
                        pending += 1
                log[nl] = np.array([i,pv[p],7,side,total,partial_forced[p],0.,cash[p],0.,fixed_r[p],0.,partial_best[p],pending])
                nl += 1
        # ----------------------------------------
        # 返済確認後に待機秒数を数え、まだ生きる候補を現在の勢いで再評価する。
        if waiting >= 0:
            p = waiting
            if virtual[p] == 0 or terminal or quiet:
                status[p] = -1
                waiting = -1
                log[nl] = np.array([i, pv[p], 5, sides[p], 0, 14521, 0., 0., 0., fixed_r[p], 0., 0., pending])
                nl += 1
            elif owner < 0 and pending == 0 and now >= wait_ready and valid[i]:
                side = sides[p]
                approved = not momentum or (np.isfinite(features[i,12]) and np.isfinite(features[i,13]) and side*features[i,12] > 0. and side*features[i,13] >= 0.)
                if approved:
                    owner, status[p], waiting = p, 1, -1
                    for u in range(nticket):
                        if tp[u] == p and vt[u] > 0:
                            queue[nq] = np.array([i, p, u, vt[u], 1, 14520, 1.e12+no+nq, 0])
                            nq += 1
                            pending += 1
                    log[nl] = np.array([i, pv[p], 6, side, virtual[p], 14520, 0., 0., 0., fixed_r[p], 0., 0., pending])
                    nl += 1
        assert total >= 0 and pending >= 0
    if n and times[-1] >= end and pending == 0:
        assert total == 0
    return out[:no], log[:nl]


def replay(data, baseline, config):
    """固定候補を通知の到着順に適用し、実際の保有数量と返済価格を再計算する。

    引数: data(dict)は原行・気配・公開特徴、baseline(ndarray[N,10])は費用0の源通知、config(dict)は条件。
    返り値: tuple[ndarray,ndarray]は十列実約定と診断。原の未来約定値は新規判断へ渡さない。
    """
    baseline = np.asarray(baseline,dtype=float).reshape(-1,10)
    times = np.asarray(data['ready']['time_s'],dtype=float)
    assert np.all(np.diff(times)>=0.) and np.all(baseline[:,0]>baseline[:,1])
    assert np.all(baseline[:,9] == 0.), "主比較の源は手数料0にする"
    if not len(baseline) or not config['enabled']:
        return baseline[baseline[:,0]<len(times)].copy(),np.empty((0,len(TRACE_COLUMNS)))
    ready,quotes=data['ready'],data['quotes']
    assert ready['symbol']=='NK225'
    bid,ask=np.asarray(quotes['bid']),np.asarray(quotes['ask'])
    good=np.asarray(quotes['quote_valid'],bool)&np.isfinite(bid)&np.isfinite(ask)&(bid>0.)&(ask>bid)
    parents=list(dict.fromkeys(baseline[:,2]))
    pmap={p:i for i,p in enumerate(parents)}
    tickets=list(dict.fromkeys((r[2],r[8]) for r in baseline))
    tmap={k:i for i,k in enumerate(tickets)}
    ep=np.array([pmap[r[2]] for r in baseline],np.int64)
    et=np.array([tmap[r[2],r[8]] for r in baseline],np.int64)
    tp=np.array([pmap[p] for p,u in tickets],np.int64)
    tv=np.array([u for p,u in tickets],float)
    out,trace=kernel(times,bid,ask,good,np.asarray(ready['atr']),np.asarray(data['features']),float(ready['tick']),
        float(ready['limit']),float(ready.get('us_open',np.nan)),baseline,ep,et,np.array(parents,float),tp,tv,
        np.array(config['eligible_reasons'],np.int64),float(config['trail_r']),float(config['profit_fraction']),
        float(config['quiet_seconds']),float(config['lock_fraction']),float(config['cap_ticks']),int(config['replace_mode']),
        float(config['reentry_wait']),bool(config['reentry_momentum']),int(config['fee10']),int(config['partial_mode']),
        float(config['partial_return_fraction']),np.array(config['partial_reasons'],np.int64))
    return (out[np.lexsort((out[:,10],out[:,0])),:10] if len(out) else out[:,:10]),trace

