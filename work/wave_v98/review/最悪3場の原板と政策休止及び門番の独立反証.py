"""全31正式完了後に、待機が救った又は損なった経路を原本の同seqへ戻す。"""

from pathlib import Path

import numpy as np

import 共通独立読取 as R
import 元候補対応と独立会計分解 as P
import 全34政策の同旧候補建値差と固有経路の独立分解 as D


def j2_facts(key: tuple, grid: int, side: int, material: dict) -> dict:
    """
    機能: 旧J2の現在板・両価格方向・比率・十分な逆OFIを独立再計算する。
    引数: key(tuple[str,str])、grid/side(int)、material(dict)。
    返り値: dict。OFI不明は支持でなく逆向き拒否の証拠なしとして扱う。
    """
    if grid < 0:
        return dict(格子なし=True, J2許可=False, 理由=['未公開格子'])
    current_ok, price_ok, reverse = True, True, False
    values, signed, reasons = {}, [], []
    session = material['grids'][key[0]]
    for symbol in R.SYMBOLS:
        market = session['markets'][symbol]
        current, window, flow = market['current'], market['windows'][300], market['flow'][15]
        normal = bool(current['valid'][grid])
        observable = bool(window['source_valid'][grid] and np.isfinite(window['ret_bp'][grid]))
        ret = float(side * window['ret_bp'][grid])
        sufficient = bool(flow['source_valid'][grid] and flow['valid'][grid]
            and not flow['missing_ofi'][grid] and flow['nonzero_ofi_count'][grid] >= 3
            and np.isfinite(flow['ofi_ratio'][grid]))
        veto = sufficient and side * flow['ofi_ratio'][grid] <= -.1
        current_ok &= normal
        price_ok &= observable and ret > 0.
        reverse |= veto
        signed.append(ret)
        values[symbol] = dict(現在板資格=normal, 価格300秒観測可能=observable,
            方向付き300秒変位bp=ret, OFI十分=sufficient, 十分な逆OFI拒否=veto,
            OFI不明=bool(flow['missing_ofi'][grid]), OFI比=float(flow['ofi_ratio'][grid]))
        if not normal:
            reasons.append(symbol + ':現在板資格なし')
        if not observable:
            reasons.append(symbol + ':価格300秒不明')
        elif ret <= 0:
            reasons.append(symbol + ':判断方向へ進んでいない')
        if veto:
            reasons.append(symbol + ':十分な逆OFI')
    ratio = bool(np.minimum(*signed) >= .25 * np.maximum(*signed))
    if not ratio:
        reasons.append('両市場変位比が1対4未満')
    expected = current_ok and price_ok and ratio and not reverse
    observed = material['entries'][key[0]]['entries']['J2'][
        'long_allowed' if side == 1 else 'short_allowed'][grid]
    assert expected == bool(observed), (key, grid, side, expected, observed)
    return dict(格子=grid, 旧J2許可=expected, 両市場=values, 比率条件=ratio,
        拒否根拠=reasons, 独立照合=True,
        注意='未知OFIだけではJ2拒否にならない。正常LPで旧mid窓や執行資格を救済しない。')


def activity_summary(ledger: dict, record: dict) -> dict:
    """
    機能: 保存政策状態から休止の原行数と代理時計区間を実建玉数と別に集計する。
    引数: ledger/record(dict)。
    返り値: dict。40状態全行の独立再現や実受信停止の計測ではない。
    """
    state, names = ledger['entry_policy_state_changes'], ledger['entry_policy_state_columns']
    columns = {name: i + 1 for i, name in enumerate(names)}
    assert len(names) == 40 and state.shape[1] == 41
    rows = state[:, 0].astype(np.int64)
    lengths = np.diff(np.r_[rows, ledger['input_rows']])
    paused = state[:, columns['paused']] == 1
    episodes, start = [], None
    for position, value in enumerate(paused):
        if value and start is None:
            start = position
        elif not value and start is not None:
            a, b = int(rows[start]), int(rows[position])
            episodes.append(dict(元候補ID=int(state[start, columns['candidate_id']]),
                開始行=a, 終了行=b, 開始seq=int(record['seq'][a]), 終了seq=int(record['seq'][b]),
                開始代理時計=R.clock(record['time_s'][a]), 終了代理時計=R.clock(record['time_s'][b]),
                代理時計秒=float(record['time_s'][b] - record['time_s'][a]), 原行数=b-a))
            start = None
    assert start is None, '場末までの休止記録が閉じていない'
    return dict(待機及び消費=P.watch_counts(ledger), 政策観測=P.policy_counts(ledger),
        保存状態上の休止原行数=int(np.sum(lengths[paused])), 休止区間数=len(episodes),
        休止代理時計秒合計=sum(value['代理時計秒'] for value in episodes),
        休止代理時計秒中央値=float(np.median([v['代理時計秒'] for v in episodes])) if episodes else None,
        最大休止20区間=sorted(episodes, key=lambda v: -v['代理時計秒'])[:20],
        内部scope='保存政策状態の記述。全行独立再現ではない。代理clock秒は真受信の停止秒ではない。')


def policy_evidence(key: tuple, ledger: dict, candidate: int, material: dict, wanted: dict) -> list[dict]:
    """
    機能: 対象候補のgap・epoch・再準備・発注イベントの保存源を原本へ直接戻す。
    引数: key(tuple[str,str])、ledger/material/wanted(dict)、candidate(int)。
    返り値: list[dict]。保存旗の全行再現を経済照合から推定しない。
    """
    record = material['prices'][key]
    peer = 'NK225' if key[1] == 'TOPIX' else 'TOPIX'
    mapped = R.published_grid(record, material['grids'][key[0]]['grid'])
    out = []
    for row in ledger['entry_policy_events']:
        d = P.named(row, ledger['entry_policy_event_columns'])
        if int(d['candidate_id']) != candidate:
            continue
        position = int(d['row'])
        value = dict(保存診断=d, 事象=ledger['entry_policy_event_codes'][int(d['code'])],
            事象原板=R.point(key, position, material, mapped, wanted))
        if int(d['code']) == 1:
            assert position > 0 and record['time_s'][position] - record['time_s'][position - 1] > 10.
            value['自己隣接原本seq差'] = int(record['seq'][position] - record['seq'][position - 1])
            value['自己価格時計差秒'] = float(record['time_s'][position] - record['time_s'][position - 1])
        for prefix, source_key in (('own', key), ('peer', (key[0], peer))):
            index = d['observed_' + prefix + '_index']
            if not np.isfinite(index) or index < 0:
                continue
            source_record = material['prices'][source_key]
            index = int(index)
            assert int(source_record['seq'][index]) == int(d['observed_' + prefix + '_seq'])
            assert float(source_record['time_s'][index]) == d['observed_' + prefix + '_time']
            assert float(source_record['bid'][index]) == d['observed_' + prefix + '_bid']
            assert float(source_record['ask'][index]) == d['observed_' + prefix + '_ask']
            value[prefix + '保存源原板'] = R.raw_point(source_key, source_record, index, wanted)
        value['scope'] = '代表の観測源を直接照合。政策40状態及び10補助旗の全行再現ではない。'
        out.append(value)
    return out


def blocking_examples(ident: str, ledgers: dict, material: dict, wanted: dict) -> dict:
    """
    機能: 未成立候補の現在J2・価格幾何・両源更新の別門番を具体原板で区別する。
    引数: ident(str)、ledgers/material/wanted(dict)。
    返り値: dict。保存状態点の代表診断であり、未保存の成功確率を補わない。
    """
    out = {}
    for symbol in R.SYMBOLS:
        selected, counts = {}, {}
        for key, ledger in ledgers.items():
            if key[1] != symbol:
                continue
            names = ledger['watch_state_columns']
            columns = {name: i + 1 for i, name in enumerate(names)}
            for row in ledger['watch_state_changes']:
                if row[columns['active']] != 1:
                    continue
                failures = [name for name in ('j2_allowed', 'fresh_sources', 'quotes_progress', 'price_ready', 'pair_valid')
                    if row[columns[name]] == 0]
                for name in failures:
                    counts[name] = counts.get(name, 0) + 1
                    if len(selected.get(name, [])) < 2:
                        selected.setdefault(name, []).append((key, row, columns))
        groups = {}
        for name, values in selected.items():
            groups[name] = []
            for key, row, columns in values:
                ledger = ledgers[key]
                state = {label: float(row[position]) for label, position in columns.items()}
                position, side, grid = int(row[0]), int(state['side']), int(state['grid_index'])
                record = material['prices'][key]
                mapped = R.published_grid(record, material['grids'][key[0]]['grid'])
                quote = float(record['ask'][position] if side == 1 else record['bid'][position])
                kind = int(state['kind'])
                phase = int(state['phase'])
                from_original = side * (quote - state['candidate_quote'])
                from_extreme = side * (quote - state['opposite_extreme'])
                groups[name].append(dict(場=key[0], 保存watch状態=state,
                    判定原板=R.point(key, position, material, mapped, wanted),
                    旧J2の独立根拠=j2_facts(key, grid, side, material),
                    独立幾何=dict(kind=kind, phase=phase, 方向付き元候補から進行pt=from_original,
                        方向付き不利極値から回復pt=from_extreme, phase行=int(state['phase_row']),
                        初回押し未経験=kind >= 6 and phase != 2),
                    候補政策経過=policy_evidence(key, ledger, int(state['candidate_id']), material, wanted)))
        out[symbol] = dict(保存状態変化点での不合格件数=counts, 具体例=groups,
            scope='件数は疎状態の変化点だけ。全原行の独立門番再現・不成立確率・実受信速度ではない。')
    return out


# ----------------------------------------
# 経済で確定した悪化親を観測原板と別の保存状態診断へ戻す。


def parent(key: tuple, trade: np.ndarray, ledger: dict, material: dict, wanted: dict) -> dict:
    """
    機能: 元候補・待機位相・実発注・約定・返済と事後順逆行を原本seqに照合する。
    引数: key(tuple[str,str])、trade(ndarray)、ledger/material/wanted(dict)。
    返り値: dict。将来の最大順行を候補当時の成功確率として扱わない。
    """
    record = material['prices'][key]
    mapped = R.published_grid(record, material['grids'][key[0]]['grid'])
    rows = ledger['entry_parent_diagnostics']
    found = rows[rows[:, 0] == trade[0]]
    assert len(found) == 1
    entry_d = P.named(found[0], ledger['entry_parent_columns'])
    orders = ledger['orders'][ledger['orders'][:, 2] == trade[0]]
    assert len(orders) == 2 and orders[0, 7] == 1 and orders[1, 7] == 0
    entry, close = orders
    side, start, end = int(trade[4]), int(trade[2]), int(trade[3])
    valid = (record['quote_valid'] & np.isfinite(record['bid']) & np.isfinite(record['ask'])
        & (record['bid'] > 0) & (record['ask'] > record['bid']))
    available = np.flatnonzero(valid[start:end + 1]) + start
    assert len(available)
    quote = record['bid'] if side == 1 else record['ask']
    signed = side * (quote[available] - trade[6])
    best, worst = int(available[np.argmax(signed)]), int(available[np.argmin(signed)])
    answer = dict(親=int(trade[0]), 方向=side, 枚数=int(trade[5]),
        新規価格=float(trade[6]), 返済価格=float(trade[7]), 総額円=float(trade[10]),
        料金円=float(trade[8] + trade[9]), 純額円=float(trade[11]),
        返済理由=ledger['reasons'][int(trade[13])], 入口保存診断=entry_d,
        元候補原板=R.point(key, int(entry_d['candidate_row']), material, mapped, wanted),
        位相基準原板=R.point(key, int(entry_d['phase_row']), material, mapped, wanted),
        発注判断原板=R.point(key, int(entry[1]), material, mapped, wanted),
        実新規原板=R.point(key, start, material, mapped, wanted),
        返済判断原板=R.point(key, int(close[1]), material, mapped, wanted),
        実返済原板=R.point(key, end, material, mapped, wanted),
        候補から発注秒=entry_d['trigger_time'] - entry_d['candidate_time'],
        発注から約定秒=float(entry[11] - entry[10]),
        新規から実返済秒=float(close[11] - entry[11]),
        返済判断から約定秒=float(close[11] - close[10]),
        候補から発注の方向付き進行pt=side * (entry_d['trigger_quote'] - entry_d['candidate_quote']),
        候補から実新規の方向付き進行pt=side * (float(trade[6]) - entry_d['candidate_quote']),
        事後保有中の最良清算変位pt=float(signed.max()),
        事後保有中の最悪清算変位pt=float(signed.min()),
        事後最良清算原板=R.point(key, best, material, mapped, wanted),
        事後最悪清算原板=R.point(key, worst, material, mapped, wanted))
    phase_events = []
    for row in ledger['entry_wait_events']:
        value = P.named(row, ledger['entry_wait_event_columns'])
        if (np.isfinite(value['state_candidate_row']) and
            value['state_candidate_row'] == entry_d['candidate_row']
            and value['state_side'] == side and int(value['code']) in (1, 5, 6, 7, 8)):
            phase_events.append(value)
    answer['保存待機経過'] = phase_events
    previous = ledger['trades'][ledger['trades'][:, 3] < start]
    if len(previous):
        previous = previous[np.argmax(previous[:, 3])]
        answer['直前完了親'] = dict(親=int(previous[0]), 方向=int(previous[4]), 純額円=float(previous[11]),
            返済原板=R.point(key, int(previous[3]), material, mapped, wanted), 同方向=previous[4] == side)
    exit_rows = ledger['trend_parent_diagnostics']
    exit_found = exit_rows[exit_rows[:, 0] == trade[0]]
    assert len(exit_found) == 1
    exit_d = P.named(exit_found[0], ledger['trend_parent_columns'])
    assert exit_d['entry_row'] == start and exit_d['exit_row'] == end and exit_d['net'] == trade[11]
    answer['出口保存診断'] = exit_d
    answer['初期S'] = exit_d['initial_width']; answer['利益追尾D'] = exit_d['trail_width']
    answer['返済判断の観測原板'] = R.point(key, int(exit_d['decision_observation_row']), material, mapped, wanted)
    answer['停止線所有者'] = [name for bit, name in ledger['trend_line_owners'].items()
        if int(exit_d['effective_line_owner']) & int(bit)]
    columns = {name: i + 1 for i, name in enumerate(ledger['trend_exit_state_columns'])}
    state = ledger['trend_exit_state_changes']
    active = state[(state[:, columns['parent_id']] == trade[0]) & (state[:, columns['protection_active']] == 1)]
    if len(active):
        answer['最初の利益保護発火原板'] = R.point(key, int(active[0, 0]), material, mapped, wanted)
    answer['保存政策経過と源照合'] = policy_evidence(key, ledger, int(entry_d['candidate_id']), material, wanted)
    answer['発注時の旧J2判定根拠'] = j2_facts(key, int(entry_d['trigger_grid']), side, material)
    answer['注意'] = [
        '入口はP0旧候補と旧J2及び旧BBO。表示する独立LPは同時点診断であり入口に使った新価格ではない。',
        '候補後の順行は新規前の利益ではない。押し回復で旧即時の建値より高く買い又は安く売る場合もある。',
        '場末返済の予定時計とdecision_observation_rowの観測時計を別に表示する。',
        '板数量から参加者の焦り、約定と取消の内訳又は未来の方向を断定しない。']
    return answer


def worst(ident: str, result: dict, ledger: dict, material: dict, wanted: dict) -> dict:
    """
    機能: 主・事前参考・同出口即時の各商品最悪3場と最大3損失親を具体化する。
    引数: ident(str)、result/ledger/material/wanted(dict)。
    返り値: dict。損失が無い商品では赤字場を架空に作らない。
    """
    answer = {}
    for symbol in R.SYMBOLS:
        rows = sorted((r for r in result['rows'] if r['symbol'] == symbol and r['net'] < -1e-5),
            key=lambda r: (r['net'], r['session']))[:3]
        answer[symbol] = []
        for row in rows:
            key = row['session'], symbol
            losses = sorted((t for t in ledger[key]['trades'] if t[11] < -1e-5), key=lambda t: t[11])[:3]
            answer[symbol].append(dict(場=key[0], 利益円=row['profit'], 損失円=row['loss'], 収支円=row['net'],
                親数=row['campaigns'], 含み損及び料金込み最大下落円=row['equity_drawdown'],
                大損3親=[parent(key, t, ledger[key], material, wanted) for t in losses],
                待機及び消費=P.watch_counts(ledger[key]), 政策観測=P.policy_counts(ledger[key])))
    return answer


def trade_by_parent(ledger: dict, pid: int) -> np.ndarray:
    """
    機能: 保存親IDから一つの完結親を得る。
    引数: ledger(dict)、pid(int)。
    返り値: ndarray[float]。同じ原候補対応の資料を原板へ戻すために使う。
    """
    rows = ledger['trades'][ledger['trades'][:, 0] == pid]
    assert len(rows) == 1
    return rows[0]


def examples(ident: str, cause: dict, ledgers: dict, material: dict, wanted: dict, baseline: str | None = None) -> dict:
    """
    機能: 同出口即時との差から救済、勝ち刈り、見送り及び新固有負けの例を追跡する。
    引数: ident(str)、cause/ledgers/material/wanted(dict)、baseline(str|None)。
    返り値: dictは商品別の原因例。親除外を新戦略の成績と呼ばない。
    """
    immediate = baseline or 'A0_' + ident.split('_')[-1]
    if ident == immediate:
        return dict(比較なし='同出口即時自身')
    source = cause['比較'][immediate + '→' + ident]['期間別元候補対応']['全31']
    out = {}
    for symbol in R.SYMBOLS:
        values = source[symbol]
        out[symbol] = {}
        common = values['同候補一覧']
        selections = {
            '元負けの救済又は軽減': sorted((v for v in common if v['元']['純額円'] < 0 and v['純額差円'] > 0), key=lambda v: -v['純額差円'])[:2],
            '元勝ちの刈り又は減益': sorted((v for v in common if v['元']['純額円'] > 0 and v['純額差円'] < 0), key=lambda v: v['純額差円'])[:2],
            '同候補の最大悪化': sorted(common, key=lambda v: v['純額差円'])[:1]}
        for label, items in selections.items():
            out[symbol][label] = []
            for item in items:
                old, new = item['元'], item['新']
                key = old['場'], symbol
                out[symbol][label].append(dict(独立会計差=item,
                    元対照経路=parent(key, trade_by_parent(ledgers[immediate][key], old['親']), ledgers[immediate][key], material, wanted),
                    待機経路=parent(key, trade_by_parent(ledgers[ident][key], new['親']), ledgers[ident][key], material, wanted)))
        for label, rows, owner, opposite in (
            ('見送った元固有大勝ち', sorted(values['元固有一覧'], key=lambda v: -v['純額円'])[:1], immediate, ident),
            ('避けた元固有大負け', sorted(values['元固有一覧'], key=lambda v: v['純額円'])[:1], immediate, ident),
            ('新固有の大負け', sorted(values['新固有一覧'], key=lambda v: v['純額円'])[:1], ident, immediate)):
            rows = [r for r in rows if r['純額円'] > 0] if label == '見送った元固有大勝ち' else [r for r in rows if r['純額円'] < 0]
            out[symbol][label] = []
            for item in rows:
                key = item['場'], symbol
                evidence = P.exclusion_evidence(ledgers[opposite][key], item['元候補行'], item['方向'])
                mapped = R.published_grid(material['prices'][key], material['grids'][key[0]]['grid'])
                for value in evidence:
                    value['事象原板'] = R.point(key, value['行'], material, mapped, wanted)
                out[symbol][label].append(dict(独立会計差=item, 参加経路=parent(key,
                    trade_by_parent(ledgers[owner][key], item['親']), ledgers[owner][key], material, wanted),
                    他側の取消消費保存理由=evidence,
                    原因限定='同候補未参加を確認する記録であり、この親だけを未来に除外した新策略の損益ではない。'))
    return out


def dependence(results: dict, ledgers: dict, fixed: dict) -> dict:
    """
    機能: 全34で最大利益親・日除外と方向、日夜、前後及び活動不足を確認する。
    引数: results/ledgers/fixed(dict)。
    返り値: dict。全31事後の依存診断を売買条件又は主選択へ戻さない。
    """
    answer = {}
    for ident, result in results.items():
        answer[ident] = {}
        for symbol in R.SYMBOLS:
            trades = np.concatenate([ledgers[ident][s, symbol]['trades'] for s in fixed['全31']])
            index = int(np.argmax(trades[:, 11])) if len(trades) and trades[:, 11].max() > 1e-5 else None
            remaining = np.delete(trades, index, axis=0) if index is not None else trades
            removed = float(trades[index, 11]) if index is not None else 0.
            value = result['periods']['全31'][symbol]
            assert abs(R.totals(remaining)['net'] - value['net'] + removed) < 1e-4
            best_session = max((r for r in result['rows'] if r['symbol'] == symbol), key=lambda r: (r['net'], r['session']))
            no_session = np.concatenate([ledgers[ident][s, symbol]['trades'] for s in fixed['全31'] if s != best_session['session']])
            answer[ident][symbol] = dict(最大利益親除外=R.totals(remaining), 除外最大親純額円=removed,
                最大収支場=best_session['session'], 最大収支場除外=R.totals(no_session),
                最大利益日=value['best_day'], 最大利益日除外=value['without_best_day'], 買売別=value['directions'],
                前16=result['periods']['前16'][symbol], 後15=result['periods']['後15'][symbol],
                デイ=result['periods']['デイ'][symbol], ナイト=result['periods']['ナイト'][symbol],
                活動黒字場=value['positive_sessions'], 活動赤字場=value['losing_sessions'], 無取引場=value['no_trade_sessions'],
                全31安定性=result['stability']['全31'][symbol])
    return answer


def main() -> None:
    """
    機能: 主・前16参考・同出口即時の最悪原板と待機の救済/損害を独立保存する。
    引数: --根許可後(bool)はrootの全31正式完了通知後だけ必須。
    返り値: None。API、実注文、新戦略再生、主差替えを行わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    proof_path = R.HERE / '全34条件全31の独立親会計と安定性及びC0旧対照一致.json'
    cause_path = R.HERE / '全34待機の同候補建値差と勝ち刈り及び固有経路の独立分解.json'
    proof, cause = R.read(proof_path), R.read(cause_path)
    assert proof['全合格'] and cause['全合格'] and proof['口座'] == cause['口座'] == 2108
    assert proof['根集計SHA256'] == cause['根集計SHA256'] == R.digest(R.WORK / 'analysis/比較結果.json')
    material = R.material()
    focal = list(dict.fromkeys((fixed['主'], assembled['selected'])))
    immediate = ['A0_' + name.split('_')[-1] for name in focal]
    corresponding = ['C0_' + name.split('_', 1)[1] for name in focal if name.startswith('C')]
    roles = list(dict.fromkeys(focal + corresponding + immediate + ['A0_X3', 'C2_A7_X3', 'C3_A7_X3']))
    ledgers, policy_activity = {}, {}
    for config in fixed['条件']:
        ident = config['id']; values = R.load_ledgers(ident)
        policy_activity[ident] = {'|'.join(key): activity_summary(value, material['prices'][key]) for key, value in values.items()}
        ledgers[ident] = values if ident in roles else {key: {'trades': value['trades']} for key, value in values.items()}
    wanted = {}
    cases = {ident: worst(ident, assembled['results'][ident], ledgers[ident], material, wanted) for ident in roles}
    example = {ident: examples(ident, cause, ledgers, material, wanted) for ident in focal}
    policy_pairs = [('C0_A7_X3', 'C1_A7_X3'), ('C1_A7_X3', 'C2_A7_X3'), ('C1_A7_X3', 'C3_A7_X3')]
    policy_examples = {a+'→'+b: examples(b, cause, ledgers, material, wanted, a) for a,b in policy_pairs}
    blocks = {ident: blocking_examples(ident, ledgers[ident], material, wanted) for ident in roles if ident.startswith('C')}
    raw = R.attach_raw(wanted)
    transitions = {immediate + '→' + ident: D.daily_change(assembled['results'][immediate], assembled['results'][ident], fixed['全31'])
        for ident in focal for immediate in ['A0_' + ident.split('_')[-1]] if ident != immediate}
    R.save('主と参考及びC0即時の最悪3場原板と政策休止及び門番の独立反証.json', dict(
        全合格=True, 条件数=34, 口座=2108, 主=fixed['主'], 前16固定参考=assembled['selected'],
        最悪3場=cases, 同候補救済及び刈りと固有親の具体原板=example, 原本同seq照合=raw,
        全34政策の休止と活動=policy_activity, 別門番の具体根拠=blocks,
        政策一軸の具体原板=policy_examples,
        既存赤字救済と無取引及び新赤字の区別=transitions,
        全34最大勝ち依存及び方向時間活動=dependence(assembled['results'], ledgers, fixed),
        両商品金額80=proof['両商品金額80'], 主変更=False, 参考事後差替え=False,
        注意=['待機成立と残存利益余地は別。事後に戻る又は伸びる事実を新規時の既知情報にしない。',
            '待機の赤字額縮小は同候補改善/参加減少/旧勝ち逸失/新規連鎖を全会計で区別する。',
            '通常期限なしでも場内強制返済と次正常BBO実約定を保持する。',
            '政策40状態と補助10旗は保存内部診断。全行独立再現ではない。代理clockによる休止秒を実受信停止秒と呼ばない。'],
        根拠SHA256={str(p.relative_to(R.ROOT)): R.digest(p) for p in (proof_path, cause_path)},
        計算コードSHA256=R.digest(Path(__file__)), **R.provenance()))


if __name__ == '__main__':
    main()
