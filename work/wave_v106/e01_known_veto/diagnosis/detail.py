"""先に固定した変更場だけを一読し、実親消失と後参加を分ける。"""

from collections import Counter
import gc
import hashlib
import time

import numpy as np

import tools


def gate(value: dict) -> dict:
    """
    機能: 公開時に保存された W60 票の区分と二政策の採否を求める。
    引数: value(dict) は候補の当時代理票。
    返り値: dict は説明用の採否。金融本体や票を再運転しない。
    """
    if not value['known']:
        return dict(区分='未知', VETO=True, KNOWN_VETO=False, 原未知理由=int(value['reason']))
    if value['direction_votes'] < 2:
        return dict(区分='既知二票未満', VETO=True, KNOWN_VETO=False)
    balance = value['balance']; assert balance is not None and np.isfinite(balance)
    group = '強同向' if balance >= .25 else '強逆向' if balance <= -.25 else '中間'
    return dict(区分='既知二票以上・' + group, VETO=balance > -.25, KNOWN_VETO=balance > -.25)


def point(account: dict, cid: int) -> dict:
    """
    機能: 不変 paper の新規公開一件を、当時票と正常気配へ結ぶ。
    引数: account(dict) は保存入力、cid(int) は紙上親。
    返り値: dict は公開時観測。原 seq 以下の保存特徴だけを用いる。
    """
    paper = account['feed'][(account['feed'][:, 2] == cid) & (account['feed'][:, 7] == 1)]
    assert len(paper) == 1
    o = paper[0]; row = int(o[0]); feature = account['trade_features']['60'][row]
    result = dict(親=cid, 公開=tools.clock(account, row), 方向='買い' if o[3] > 0 else '売り',
        公開予定枚数=int(o[4]), 公開Last=float(o[5]), 公開ATR=float(o[9]), 票=feature, 採否区分=gate(feature))
    if 'candidate_raw_row' in feature:
        assert feature['candidate_raw_row'] == int(account['mapping'][row])
        assert feature['candidate_raw_seq'] == int(account['quotes']['seq'][row])
        assert feature['candidate_price_time_s'] == float(account['quotes']['time_s'][row])
        assert feature['last_vote_raw_row'] <= int(account['mapping'][row])
    return result


def state_at(ledger: dict, row: int, count: int) -> dict:
    """
    機能: 保存された GU 執行状態の一行だけを復元する。
    引数: ledger(dict)、row/count(int) は台帳・対象行・行数。
    返り値: dict は紙上状態と GU 執行状態。政策停止後の実建玉とは区別する。
    """
    v = ledger['execution_states']
    if isinstance(v, np.ndarray): assert len(v) == count; selected = v[row]
    else:
        assert v['length'] == count
        selected = v['values'][int(np.searchsorted(v['rows'], row, side='right') - 1)]
    names = ('紙上親', '紙上残量', 'GU実親', 'GU買い残量', 'GU売り残量', '新規待機', '永久取消', '新規済', '公開線', '返済予約数')
    return dict(zip(names, selected.tolist()))


def scalar_at(value: object, row: int, count: int) -> object:
    """
    機能: plateau 保存値の当該一行だけを返す。
    引数: value(object)、row/count(int) は保存配列と対象。
    返り値: object は保存された値。全行へ展開しない。
    """
    if isinstance(value, np.ndarray): assert len(value) == count; return value[row]
    assert value['length'] == count
    return value['values'][int(np.searchsorted(value['rows'], row, side='right') - 1)]


def presence(ledger: dict, account: dict, cid: int) -> dict:
    """
    機能: 同じ候補の実参加、公開 mask、場停止、GU busy を保存証跡から整理する。
    引数: ledger/account(dict)、cid(int) は対象台帳・入力・紙上親。
    返り値: dict は候補消失又は参加の説明。影 GU 注文を実政策の注文へ数えない。
    """
    obs = point(account, cid); row = obs['公開']['normal_row']; n = len(account['record']['price'])
    actual = ledger['orders'][(ledger['orders'][:, 2] == cid) & (ledger['orders'][:, 7] == 1)]
    shadow = ledger['shadow_GU_orders'][(ledger['shadow_GU_orders'][:, 2] == cid) & (ledger['shadow_GU_orders'][:, 7] == 1)]
    control = ledger.get('control', {}); stopped = bool(control.get('発動') and row > control['判断行'])
    mask = bool(scalar_at(ledger['gate_accepted'], row, n))
    proof = ledger['limit_events']; pub = proof[(proof[:, 2] == cid) & (proof[:, 1] == 1)]
    assert len(pub) == 1
    published = pub[0]
    if len(actual): cause = '実参加'
    elif stopped: cause = 'この候補より前に場口座が停止した'
    elif not mask: cause = '公開時の観測資格で見送り'
    elif published[14] and int(published[17]) == 94: cause = 'GU 執行本体で保有又は返済予約があり busy'
    elif published[14]: cause = '既知静観又は期限等で新規予約なし'
    else: cause = '公開予約後に未約定のまま終了。追加原因は推測しない'
    result = dict(原因=cause, 公開mask許可=mask, 公開mask理由=int(scalar_at(ledger['gate_reasons'], row, n)),
        公開前の場停止=stopped, 実新規注文数=len(actual), 影GUの新規注文数=len(shadow),
        GU公開時保有枚数=int(published[12]), GU公開時待機=bool(published[13]),
        GU公開時永久取消=bool(published[14]), GU公開理由=int(published[17]),
        GU公開証跡=published, GU執行状態=state_at(ledger, row, n),
        系譜の意味='影 GU は全 feed を継続する。P1L8 場停止後の影状態を実建玉と呼ばない。')
    if control.get('発動'):
        result['場停止'] = dict(**control, 判断気配=tools.clock(account, int(control['判断行'])),
            実返済気配=tools.clock(account, int(control['返済行'])))
    return result


def path(ledger: dict, account: dict, cid: int) -> dict:
    """
    機能: 対象実親の実注文だけから事後の料金後清算経路を再集計する。
    引数: ledger/account(dict)、cid(int) は保存された完結実親。
    返り値: dict は MFE/MAE と時刻。別出口で実現できた利益とは呼ばない。
    """
    q = account['quotes']; symbol = account['symbol']; orders = ledger['orders']; selected = np.flatnonzero(orders[:, 2] == cid)
    first, last = int(orders[selected[0], 0]), int(orders[selected[-1], 0]); n = last - first + 1
    cash_delta = np.zeros(n); paid = np.zeros(n); quantity_delta = np.zeros(n); reserved = np.zeros(n)
    states = {}; previous = 0; targets = ledger.get('exit_target_uids', np.full(len(orders), -1, np.int64))
    for oi in selected:
        o = orders[oi]; row, side, qty, new = map(int, (o[0], o[3], o[4], o[7])); i = row - first
        reserved[previous:i] = sum(tools.fee(v['remaining'], symbol) for v in states.values() if v['remaining'])
        cash_delta[i] -= side * qty * o[5]; paid[i] += tools.fee(qty, symbol); quantity_delta[i] += side * qty
        if new:
            states[int(ledger['order_uids'][oi])] = dict(remaining=qty, side=side)
        else:
            left = qty; target = int(targets[oi])
            for uid, v in states.items():
                if not v['remaining'] or v['side'] != -side or (target >= 0 and target != uid): continue
                take = min(left, v['remaining']); v['remaining'] -= take; left -= take
                if not left: break
            assert left == 0
        previous = i
    reserved[previous:] = sum(tools.fee(v['remaining'], symbol) for v in states.values() if v['remaining'])
    held = np.cumsum(quantity_delta)
    valid = q['quote_valid'] & np.isfinite(q['bid']) & np.isfinite(q['ask']) & (q['bid'] > 0) & (q['ask'] > q['bid'])
    prior = np.maximum.accumulate(np.where(valid, np.arange(len(valid)), -1)); assert np.all(prior[first:last+1] >= 0)
    b, a = q['bid'][prior[first:last+1]], q['ask'][prior[first:last+1]]
    clear = (np.cumsum(cash_delta) + np.maximum(held, 0) * b + np.minimum(held, 0) * a) * tools.VALUE[symbol] - np.cumsum(paid) - reserved
    assert held[-1] == 0 and np.isclose(clear[-1], tools.parents(ledger)[cid]['収支'], atol=1e-5, rtol=0.)
    hi, lo = int(np.argmax(clear)), int(np.argmin(clear))
    return dict(事後最大清算利益=float(clear[hi]), 事後最大清算損失=float(clear[lo]),
        最大利益気配=tools.clock(account, first + hi), 最大損失気配=tools.clock(account, first + lo),
        利益最大から最終返済までの差=float(clear[hi] - clear[-1]), 別出口の実現利益ではない=True)


def episode(ledger: dict, account: dict, cid: int) -> dict:
    """
    機能: 完結実親の公開・新規・返済判断・実気配と UID を時系列へ結ぶ。
    引数: ledger/account(dict)、cid(int) は対象実親。
    返り値: dict は価格代理時計・原 seq・実注文料金・事後経路の診断。
    """
    parent = tools.parents(ledger)[cid]; orders = ledger['orders']; chosen = np.flatnonzero(orders[:, 2] == cid)
    new = chosen[orders[chosen, 7] == 1]; assert len(new) == 1
    e = orders[new[0]]; q = account['quotes']; good = q['quote_valid'] & np.isfinite(q['bid']) & np.isfinite(q['ask']) & (q['bid'] > 0) & (q['ask'] > q['bid'])
    assert int(e[0]) == int(e[1]) + 1 + int(np.flatnonzero(good[int(e[1])+1:])[0])
    exits = []
    for oi in chosen[orders[chosen, 7] == 0]:
        o = orders[oi]; decision, fill = int(o[1]), int(o[0])
        assert fill == decision + 1 + int(np.flatnonzero(good[decision+1:])[0])
        exits.append(dict(判断=tools.clock(account, decision), 実返済=tools.clock(account, fill),
            売買='買い' if o[3] > 0 else '売り', 価格=float(o[5]), 枚数=int(o[4]), 理由=int(o[6]),
            注文料=tools.fee(int(o[4]), account['symbol']), 対象UID=int(ledger['exit_target_uids'][oi])))
    obs = point(account, cid); side = int(e[3]); tick = float(account['record']['tick'])
    return dict(**obs, 収支=parent['収支'], 粗損益=parent['粗損益'], 実費=parent['費用'],
        実UID=int(ledger['order_uids'][new[0]]), 実新規=tools.clock(account, int(e[0])),
        実新規価格=float(e[5]), 実新規枚数=int(e[4]), 新規注文料=tools.fee(int(e[4]), account['symbol']),
        公開Lastから新規の不利呼値=side * (float(e[5]) - obs['公開Last']) / tick,
        公開気配幅呼値=(obs['公開']['ask'] - obs['公開']['bid']) / tick,
        当時ATR呼値=obs['公開ATR'] / tick, 返済注文=exits, 事後経路=path(ledger, account, cid))


def scene(before: dict, after: dict, account: dict, expected: dict) -> dict:
    """
    機能: 固定した変更場の全実親を新旧対応し、五寄与と後参加の原因を保存する。
    引数: before/after/account/expected(dict) は新旧台帳・入力・小結果。
    返り値: dict は変更場全数の時刻つき説明。対象親を勝敗で減らさない。
    """
    d = tools.contribution(before, after)
    for k in tools.FIVE: assert np.isclose(d[k], expected['寄与5'][k], atol=1e-5, rtol=0.)
    a, b = tools.parents(before), tools.parents(after)
    ids = sorted(a.keys() | b.keys(), key=lambda cid: point(account, cid)['公開']['normal_row'])
    comparison = []
    for cid in ids:
        comparison.append(dict(親=cid, 変更='消えた旧親' if cid not in b else '新たな親' if cid not in a else '共通親',
            公開=point(account, cid), 旧参加又は消失理由=presence(before, account, cid),
            新参加又は消失理由=presence(after, account, cid),
            旧実親=episode(before, account, cid) if cid in a else None,
            新実親=episode(after, account, cid) if cid in b else None))
    paper = account['feed'][account['feed'][:, 7] == 1]
    differences = []
    for o in paper:
        cid = int(o[2]); row = int(o[0]); value = account['trade_features']['60'][row]; judged = gate(value)
        n = len(account['record']['price'])
        oldmask, newmask = bool(scalar_at(before['gate_accepted'], row, n)), bool(scalar_at(after['gate_accepted'], row, n))
        assert oldmask == judged['VETO'] and newmask == judged['KNOWN_VETO']
        if oldmask != newmask:
            differences.append(dict(**point(account, cid), 旧状況=presence(before, account, cid), 新状況=presence(after, account, cid),
                旧実親収支=a[cid]['収支'] if cid in a else None, 新実親収支=b[cid]['収支'] if cid in b else None))
    return dict(session=account['record'].get('session', before['key'][0]), symbol=account['symbol'],
        旧会計=before['summary'], 新会計=after['summary'], 五寄与=d, 全実親の対応=comparison,
        この場の公開mask変更全候補=differences,
        旧場停止=before.get('control'), 新場停止=after.get('control'),
        分母=dict(旧実親=len(a), 新実親=len(b), 公開候補=len(paper), 公開mask変更=len(differences)),
        影GU収支を政策利益へ混ぜない=True)


def run() -> None:
    """
    機能: 先に固定した四場・八台帳だけを一読し、P1L8 の損益相殺を説明する。
    引数: なし。大型入力・台帳の対象は読取前計画のまま。
    返り値: None。金融、原板、原 NPZ、API は呼ばない。
    """
    plan, plan_sha = tools.read(tools.HERE / 'P1L8変更場の読取前固定.json')
    evidence = {}; result = []; reads = Counter(); started = time.monotonic()
    source_sha = {p.relative_to(tools.ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in tools.HERE.glob('*.py')}
    for session in plan['sessions']:
        packet = tools.checked(plan['input_cache'][session], evidence); reads['選択input一読'] += 1
        assert packet['session'] == session
        for chosen in [x for x in plan['selected'] if x['session'] == session]:
            key = session + '|' + chosen['symbol']; account = packet['accounts'][chosen['symbol']]
            before = tools.checked(plan['old_ledgers'][key], evidence); reads['旧台帳一読'] += 1
            after = tools.checked(plan['new_ledgers'][key], evidence); reads['新台帳一読'] += 1
            assert before['key'] == after['key'] == (session, chosen['symbol'])
            assert before['summary'] == chosen['旧会計'] and after['summary'] == chosen['新会計']
            result.append(scene(before, after, account, chosen)); del before, after
        del packet; gc.collect(); print(session + ' 変更場の一読診断完了、金融0', flush=True)
    assert reads == Counter(選択input一読=4, 旧台帳一読=4, 新台帳一読=4)
    assert source_sha == {p.relative_to(tools.ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in tools.HERE.glob('*.py')}
    total = {symbol: {k: sum(s['五寄与'][k] for s in result if s['symbol'] == symbol) for k in tools.FIVE} for symbol in ('TOPIX', 'NK225')}
    proof = dict(全合格=True, 対象='P1L8 五寄与又は小会計の全変更場', 結果前の選抜=False,
        読取前計画SHA256=plan_sha, 結果小資料=plan['result_source'], 変更場数={'TOPIX':3, 'NK225':1},
        全変更場の五寄与=total, scenes=result, 読取件数=dict(reads), 一読したSHA256=evidence,
        診断source開始終端一致=True, 診断source_SHA256=source_sha, 金融再生=0, 原板読取=0, 原NPZ読取=0, API=0,
        解釈=['同じ旧親を消すだけではない。影 feed を維持して後続の新しい実参加と場停止も変わる。',
            '消えた旧親の負け額は部分寄与。新親の負けと消えた旧勝ちを差し引いて初めて改善額になる。',
            'この保存対照の共通親出口差は0円。入口採否と後参加・口座停止が主な変更である。'],
        限界=plan['限界'] + ['公開票は正出来高更新に伴う Last 対前 BBO の一更新一票。真の攻撃注文や数量の優勢ではない。',
            '事後最大清算利益は別出口の実利益ではない。UNKNOWN拒否だけで方向精度改善や全場安定を証明しない。'],
        経過秒=time.monotonic() - started)
    print(tools.write('P1L8全変更場の票と原seq及び実親入替の診断.json', proof), flush=True)


if __name__ == '__main__': run()
