"""条件固定の追加一場を、旧待機入口と新板入口を分離して検算する。"""

import argparse
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys
import traceback

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WAVE = HERE.parents[1]
ROOT = WAVE.parents[1]
SESSION = '2026-10-13_Day'
CURRENT = {}
sys.path.insert(0, str(WAVE))


def module(name: str, path: Path) -> object:
    """
    機能: 完了済み監査の算数と入力資格部品を、CLIを呼ばず読取接続する。
    引数: name(str)、path(Path)は固有名と小source位置。
    返り値: object。金融再生、原本、NPZ、APIは実行しない。
    """
    import importlib.util
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
    return sys.modules[name]


FULL = module('104追加監査で再利用する全数監査', HERE/'全121条件の会計と安定性を独立監査する.py')
COMMON, LEDGER, COUNTS = FULL.COMMON, FULL.LEDGER, FULL.COUNTS
equal, charge, totals, read, sha = COMMON.equal, COMMON.charge, COMMON.totals, FULL.read, FULL.sha


def own_sources() -> dict:
    """
    機能: 新監査と変更しない既検算部品の指紋を小sourceだけから取得する。
    引数: なし。
    返り値: dict[str,str]は独立監査source SHA256。巨大cacheや原本はhashしない。
    """
    paths = [Path(__file__), HERE/'全121条件の会計と安定性を独立監査する.py',
        HERE/'入力と集計の独立部品.py', HERE/'台帳と停止線の独立部品.py',
        ROOT/'work/wave_v103/review/finance_audit/全19条件の注文現金と時価及び安定性を独立監査する.py']
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def save(path: Path, value: dict) -> None:
    """
    機能: 所有域の新しい証跡だけを日本語UTF-8で保存する。
    引数: path(Path)、value(dict)は保存位置と内容。
    返り値: None。既合格及び失敗資料を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def legacy_context(context: dict) -> dict:
    """
    機能: 新104候補とは別に、完全旧prepareの元信号とLP現在支持を索引化する。
    引数: context(dict)は同bundleの物理recordと完全preparedを持つ口座。
    返り値: dictは旧G0検算の当時信号と現在格子。新qualifiedへ入口を置換しない。
    """
    prepared, record = context['prepared'], context['record']
    signal = prepared['signal']
    mapped = signal['mapped']
    latest = np.maximum.accumulate(np.where(mapped >= 0, mapped, -1))
    pulse = signal['event']
    assert len(mapped) == len(pulse) == len(record['seq'])
    assert set(prepared['trend_lp_allowed']) == {1, -1}
    return dict(signal=signal, latest=latest, counter=np.cumsum(pulse != 0),
        support=prepared['trend_lp_allowed'], width=COMMON.width(prepared['reference_open'], record['tick']))


def observation(context: dict, old: dict, row: int) -> tuple[np.ndarray, bool]:
    """
    機能: 旧自己normal行と既に格子公開された相手BBOだけを当時観測へ写す。
    引数: context/old(dict)、row(int)は口座と当時行。
    返り値: tuple[ndarray,bool]は10観測列と旧ペア資格。価格時計は受信時刻ではない。
    """
    record, signal = context['record'], old['signal']
    grid = int(old['latest'][row])
    value = np.full(10, np.nan)
    value[:5] = row, record['seq'][row], record['time_s'][row], record['bid'][row], record['ask'][row]
    if grid >= 0:
        value[5:] = signal['entry_peer_bbo'][grid, :5]
    fresh = grid >= 0 and record['time_s'][row]-signal['grid'][grid] <= 10.+1e-8
    good = bool(context['qok'][row] and fresh and signal['entry_peer_bbo'][grid, 5] == 1.
        and np.isfinite(value).all() and value[5] >= 0 and value[6] >= 0
        and value[8] > 0 and value[9] > value[8] and value[7] <= value[2]+1e-8)
    return value, good


def legacy_watch(ledger: dict, context: dict, old: dict) -> tuple[np.ndarray, dict]:
    """
    機能: 元候補の待機・取消・市場予約の疎イベントから占有数量を独立に復元する。
    引数: ledger/context/old(dict)は旧G0台帳、物理口座及び旧信号。
    返り値: tuple[ndarray,dict]は未発注方向別待機量と市場予約parent別の元待機。
    """
    record, signal, n = context['record'], old['signal'], len(context['record']['seq'])
    columns = ledger['entry_wait_event_columns']
    index = {name: i for i, name in enumerate(columns)}
    assert len(columns) == 57 and ledger['entry_wait_events'].shape[1] == 57
    delta, active, reserved, seen = np.zeros((n, 2), np.int64), None, {}, set()
    rows = ledger['entry_wait_events']
    assert np.all(np.diff(rows[:, 0]) >= 0)
    own_tick, peer_tick = record['tick'], signal['peer_tick']
    for event in rows:
        row, code = int(event[0]), int(event[1])
        assert 0 <= row < n
        watch = event[7:39]
        obs, pair = observation(context, old, row)
        np.testing.assert_allclose(event[39:49], obs, atol=1e-5, rtol=0, equal_nan=True)
        equal(event[index['pair_valid']], pair, '旧元ペア資格')
        if code == 1:
            assert active is None
            candidate, side = int(watch[4]), int(watch[2])
            assert candidate == row and side == int(signal['event'][row]) != 0
            assert signal['quality'][row] and not signal['reset'][row] and context['qok'][row]
            assert record['start']+300 <= record['time_s'][row] < record['limit']-300
            equal(watch[3], old['counter'][row], '旧元候補番号')
            equal(watch[5], record['seq'][row], '旧候補rawseq')
            equal(watch[6], record['time_s'][row], '旧候補代理時計')
            equal(watch[7], record['ask' if side == 1 else 'bid'][row], '旧元候補新規quote')
            equal(watch[8], record['time_s'][row]+300., '旧候補期限')
            equal(watch[9], old['width'], '旧幅')
            np.testing.assert_array_equal(watch[10:13], 0.)
            equal(watch[31], 1, '固定待機方式')
            active = dict(side=side, candidate=row, ident=int(watch[3]))
            delta[row, 0 if side == 1 else 1] += 1
            seen.add(int(watch[3]))
        elif code in (3, 8):
            assert active is not None and int(watch[3]) == active['ident']
            side = active['side']
            delta[row, 0 if side == 1 else 1] -= 1
            if code == 8:
                parent = int(event[3])
                assert parent > 0 and parent not in reserved and row > active['candidate']
                assert context['qok'][row] and signal['quality'][row] and not signal['reset'][row] and pair
                grid = int(old['latest'][row])
                assert grid >= 0 and old['support'][side][grid]
                assert record['time_s'][row] < record['limit']-300 and record['time_s'][row] < watch[8]
                assert watch[27] == 1 and np.isfinite(watch[17:27]).all()
                assert obs[0] > watch[17] and obs[1] > watch[18] and obs[2] > watch[16] and obs[2] > watch[19]
                assert obs[5] > watch[22] and obs[6] > watch[23] and obs[7] > watch[16] and obs[7] > watch[24]
                for current, anchor, tick in ((3, 20, own_tick), (4, 21, own_tick), (8, 25, peer_tick), (9, 26, peer_tick)):
                    assert side*(obs[current]-watch[anchor]) >= tick-tick*1e-8
                quote = record['ask' if side == 1 else 'bid'][row]
                assert side*(quote-watch[7]) <= old['width']
                for flag in ('j2_allowed', 'fresh_sources', 'quotes_progress', 'price_ready', 'pair_valid'):
                    equal(event[index[flag]], True, ('旧発注根拠', flag))
                reserved[parent] = (row, watch.copy(), event.copy())
            else:
                reason = int(event[2])
                grid = int(old['latest'][row])
                fresh = grid >= 0 and record['time_s'][row]-signal['grid'][grid] <= 10.+1e-8
                opposite = fresh and signal['wait_opposite_long' if side == 1 else 'wait_opposite_short'][grid]
                expected = 1 if record['time_s'][row] >= record['limit']-300 else 2 if record['time_s'][row] >= watch[8] else \
                    4 if signal['reset'][row] else 5 if not context['qok'][row] else 6 if opposite else 0
                assert reason == expected != 0
            active = None
        elif code == 7:
            assert active is not None and pair and watch[28] == 1 and watch[27] == 1
            np.testing.assert_allclose(watch[17:27], obs, atol=1e-5, rtol=0)
        elif code == 2:
            assert int(event[5]) == old['counter'][row] and signal['event'][row] != 0
        elif code in (4, 5, 6):
            assert active is not None
            assert code == 4, '固定A1には押し回復の位相はありません'
        elif code == 9:
            assert record['time_s'][row] >= record['limit']-300
        else:
            raise AssertionError(('未知旧待機event', code))
        COUNTS['旧候補待機疎イベント'] += 1
    pending = np.cumsum(delta, axis=0)
    assert active is None and not pending[-1].any() and np.all(pending >= 0) and np.all(pending.sum(axis=1) <= 1)
    state = ledger['watch_state_trace']
    wc = {name: i for i, name in enumerate(ledger['watch_state_columns'])}
    np.testing.assert_array_equal(state[:, wc['active']] != 0, pending.sum(axis=1) != 0)
    for side, column in ((1, 0), (-1, 1)):
        np.testing.assert_array_equal((state[:, wc['active']] != 0)&(state[:, wc['side']] == side), pending[:, column] != 0)
    COUNTS['旧候補待機全normal行'] += n
    return pending, reserved


def legacy_stop(ledger: dict, context: dict, old: dict, entry: dict, order: np.ndarray) -> None:
    """
    機能: 元G0の前行までのpeak、固定S/D、30分期限、既知forceの最初成立を検算する。
    引数: ledger/context/old/entry(dict)、order(ndarray)は元入力と返済注文。
    返り値: None。新支持停止線は課さず、fill同行に通常停止を許さない。
    """
    record, side, start = context['record'], entry['side'], entry['row']
    n, decision, reason = len(record['seq']), int(order[1]), int(order[8])
    reservation = ledger['events'][(ledger['events'][:, 1] == entry['parent_id'])&(ledger['events'][:, 3] == 2)]
    assert len(reservation) == 1
    stop_end = int(reservation[0, 0])-1 if reason == 4 else decision
    indexes = np.arange(start+1, stop_end+1)
    price, wide = side*entry['price'], float(old['signal']['trend_width'])
    quote = side*record['bid' if side == 1 else 'ask'][indexes]
    valid = context['qok'][indexes]
    peak = np.maximum.accumulate(np.r_[price, np.where(valid, quote, -np.inf)])[:-1]
    stop = np.maximum(price-old['width'], peak-wide)
    timeout = record['time_s'][indexes] >= record['time_s'][start]+1800.
    hit = valid & (quote-stop <= record['tick']*1e-8)
    prior_force = record['time_s'][indexes] >= record['limit']-60
    triggers = timeout | hit | prior_force
    if reason == 4:
        assert not triggers.any()
    else:
        assert triggers.any() and indexes[np.flatnonzero(triggers)[0]] == decision
        position = int(np.flatnonzero(triggers)[0])
        assert not prior_force[position]
        expected = 3 if timeout[position] else 1 if abs(peak[position]-price) < record['tick']*1e-8 else 2
        equal(reason, expected, '旧優先停止理由')
    COUNTS['旧G0固定出口当時判断行'] += len(indexes)


def legacy_audit(ledger: dict, context: dict) -> dict:
    """
    機能: 追加旧G0を、元待機入口と注文現金から独立に全親/玉/全行時価へ復元する。
    引数: ledger/context(dict)は旧台帳と同bundleの完全prepared。
    返り値: dictは相殺前G/L、net、枚数、源、方向、保有最大及び経路。
    """
    symbol, record = context['symbol'], context['record']
    n, multiplier = len(record['seq']), 1000 if symbol == 'TOPIX' else 10
    old = legacy_context(context)
    wait, reserved = legacy_watch(ledger, context, old)
    orders, trades, cohorts = ledger['orders'], ledger['trades'], ledger['growth_cohorts']
    assert ledger['entry_id'] is None and ledger['exit_id'] == 'OLD_G0' and ledger['configured_quantity'] == 1
    assert ledger['raw_entry_diagnostics'] == []
    assert orders.shape[1] == 17 and trades.shape[1] == 16 and np.isfinite(orders).all() and np.isfinite(trades).all()
    assert np.all(np.diff(orders[:, 0]) >= 0)
    dc = {name: i for i, name in enumerate(ledger['entry_parent_columns'])}
    diagnostics = {int(row[dc['parent_id']]): row for row in ledger['entry_parent_diagnostics']}
    assert len(dc) == 45 and len(diagnostics) == len(ledger['entry_parent_diagnostics'])
    gc = {name: i for i, name in enumerate(ledger['growth_cohort_columns'])}
    cash_delta, position_delta = np.zeros((n, 2)), np.zeros((n, 2), np.int64)
    live, parents, uids = {}, [], set()
    for order in orders:
        row, decision, parent, src, side, quantity, new, reason = [int(order[i]) for i in (0, 1, 2, 3, 4, 5, 7, 8)]
        uid, price, fee = int(order[16]), float(order[6]), float(order[9])
        assert 0 <= decision <= row < n and src == 0 and side in (-1, 1) and quantity == 1 and uid not in uids
        uids.add(uid)
        assert context['qok'][row] and order[14] == 0
        equal(price, record['ask' if side == 1 else 'bid'][row], '旧当時物理BBO')
        equal(fee, charge(quantity, symbol), '旧Decimal注文料金')
        equal(order[11], record['time_s'][row], '旧物理fill代理時計')
        if new:
            assert new == 1 and parent not in live and parent in diagnostics and parent in reserved
            assert row == LEDGER.next_quote(context, decision) and decision < row
            assert record['time_s'][row] < record['limit']-300
            trigger, watch, event = reserved[parent]
            assert trigger == decision
            diag = diagnostics[parent]
            expected_prefix = np.array([parent, watch[3], watch[4], watch[5], watch[6], watch[7], watch[31], watch[2], 1,
                watch[9], watch[10], watch[11], watch[12], watch[15], watch[16], watch[13], watch[14], *watch[17:27],
                watch[28], decision, record['seq'][decision], record['time_s'][decision], record['ask' if side == 1 else 'bid'][decision],
                old['latest'][decision], 1, 1, 1, 1])
            np.testing.assert_allclose(diag[:37], expected_prefix, atol=1e-5, rtol=0, equal_nan=True)
            np.testing.assert_allclose(diag[37:42], [row, record['seq'][row], record['time_s'][row], price, 1], atol=1e-5, rtol=0)
            equal(diag[44], True, '旧発注ペアvalid')
            assert int(diag[dc['side']]) == side
            equal(order[10], record['time_s'][decision], '旧新規判断時計')
            live[parent] = dict(parent_id=parent, source=src, side=side, quantity=quantity, price=price, fee=fee,
                row=row, decision=decision, uid=uid)
            COUNTS['旧G0実新規の元候補lineage'] += 1
        else:
            assert new == 0 and parent in live
            entry = live.pop(parent)
            assert side == -entry['side']
            if reason == 4:
                equal(order[10], record['limit']-60, '旧force時計')
                good = context['good'][record['time_s'][context['good']] >= record['limit']-60]
                assert len(good) and row == good[0]
            else:
                assert decision < row and row == LEDGER.next_quote(context, decision)
                equal(order[10], record['time_s'][decision], '旧返済判断時計')
            gross = float(Decimal(entry['side']*quantity*multiplier)*(Decimal(str(price))-Decimal(str(entry['price']))))
            net = gross-entry['fee']-fee
            result = dict(entry, gross=gross, fees=entry['fee']+fee, net=net, entry_row=entry['row'], exit_row=row)
            matched = trades[(trades[:, 0] == parent)&(trades[:, 1] == src)]
            assert len(matched) == 1
            for column, wanted in {2: entry['row'], 3: row, 4: entry['side'], 5: quantity, 6: entry['price'], 7: price,
                8: entry['fee'], 9: fee, 10: gross, 11: net, 13: reason, 15: entry['decision']}.items():
                equal(matched[0, column], wanted, ('旧親', column))
            selected = cohorts[cohorts[:, gc['parent_id']] == parent]
            assert len(selected) == 1
            for field, wanted in dict(source=src, side=entry['side'], quantity=quantity, entry_row=entry['row'], exit_row=row,
                entry_price=entry['price'], exit_price=price, entry_fee=entry['fee'], exit_fee_share=fee, gross=gross,
                net=net, order_uid=entry['uid'], decision_row=entry['decision']).items():
                equal(selected[0, gc[field]], wanted, ('旧玉', field))
            diag = diagnostics[parent]
            equal(diag[dc['exit_row']], row, '旧親診断実返済')
            equal(diag[dc['net']], net, '旧親診断現金')
            legacy_stop(ledger, context, old, entry, order)
            parents.append(result)
        cash_delta[row, src] -= side*quantity*price*multiplier+fee
        position_delta[row, src] += side*quantity
        COUNTS['全物理注文'] += 1
    assert not live and len(parents) == len(trades) == len(cohorts)
    for parent, diag in diagnostics.items():
        outcome = int(diag[dc['market_outcome']])
        assert outcome in (1, 2) and parent in reserved
        if outcome == 2:
            assert not np.any(orders[:, 2] == parent)
            assert np.any((ledger['events'][:, 1] == parent)&(ledger['events'][:, 3] == 6))
    assert len(diagnostics) == len(reserved)
    position, cash = np.cumsum(position_delta, axis=0), np.cumsum(cash_delta, axis=0)
    last = np.maximum(context['last'], 0)
    bid, ask = record['bid'][last], record['ask'][last]
    liquidation = np.where(position >= 0, bid[:, None], ask[:, None])
    absolute = np.abs(position)
    remaining_fee = absolute*209//5 if symbol == 'TOPIX' else absolute*11
    sources = cash+position*liquidation*multiplier-remaining_fee
    curve = sources.sum(axis=1)
    np.testing.assert_allclose(ledger['source_curve'], sources, atol=1e-4, rtol=0)
    np.testing.assert_allclose(ledger['curve'], curve, atol=1e-4, rtol=0)
    pending, exiting = LEDGER.reservations(ledger['events'], n)
    pending += wait
    long, short = np.maximum(position, 0).sum(axis=1), np.maximum(-position, 0).sum(axis=1)
    trace = np.column_stack((long, short, long+pending[:, 0], short+pending[:, 1], pending.sum(axis=1), exiting))
    np.testing.assert_array_equal(ledger['target_trace'], trace)
    assert not trace[-1].any() and np.all(trace >= 0) and np.all(trace[:, :4] <= 1)
    result = dict(totals(parents), **LEDGER.path_totals(curve), cohorts=LEDGER.cohort_totals(parents),
        order_count=len(orders), entry_order_count=len(parents), adding_order_count=0)
    result['sources'] = {name: dict(totals([p for p in parents if p['source'] == src]), **LEDGER.path_totals(sources[:, src]))
        for src, name in enumerate(('J2', 'O06'))}
    result['directions'] = {name: totals([p for p in parents if p['side'] == side]) for side, name in ((1, '買い'), (-1, '売り'))}
    result['cohort_directions'] = {name: LEDGER.cohort_totals([p for p in parents if p['side'] == side]) for side, name in ((1, '買い'), (-1, '売り'))}
    result['maximums'] = {name: int(trace[:, i].max(initial=0)) for i, name in enumerate(ledger['trace_columns'])}
    np.testing.assert_array_equal(ledger['stats'][:4], trace[:, :4].max(axis=0, initial=0))
    np.testing.assert_array_equal(ledger['stats'][4:8], trace[-1, [0, 1, 4, 5]])
    equal(ledger['stats'][15], curve[-1], '旧末尾全現金')
    result['event_counts'] = {str(int(code)): int(np.sum(ledger['events'][:, 3] == code)) for code in np.unique(ledger['events'][:, 3])}
    COUNTS['全新台帳'] += 1
    COUNTS['旧G0新台帳独立監査'] += 1
    COUNTS['全時価_源_予約trace行'] += n
    return result


def plan() -> None:
    """
    機能: 金融結果と入力pickleを読む前に追加一場の読取及び会計監査契約を固定する。
    引数: なし。
    返り値: None。新金融値・新packet・旧32cacheは読まず計画だけを保存する。
    """
    save(HERE/'追加Day全121独立監査の計画.json', dict(全合格=True, session=SESSION,
        scope='旧32と条件固定の追加一場、掲載242口座及び実量腿24、全266台帳の一回独立監査。',
        予定読取=dict(追加活動JSON=1, 追加活動pickle=1, 新台帳=266, 旧64base=0, 旧32cache=0, 原本=0, NPZ=0),
        予定検査=['全121config固定一致', '同bundleの全19入口と元状態/資格/strictpast一般支持',
            '全物理次quoteとDecimal注文料floor', '親/玉の相殺前G/L及びnetと全行清算時価',
            '源別curveと全予約/待機6列・caps・末尾flat', 'B/T最初停止と当時support/lineage',
            '実量腿24と配分12のnamespace完全連結', '旧G0は完全旧preparedの元候補と待機及び旧S/D/30分を分離'],
        追加場での再選択=0, 再ランキング=0, 新金融結果読取=0, 新金融再生=0,
        SHA256=own_sources(), 正式監査本実行=0, 原本読取=0, NPZ読取=0, API取得=0, goal操作=0))
    print('追加Day独立監査の計画保存。新金融と入力packetは未読。', flush=True)


def run() -> None:
    """
    機能: 根の追加金融終端通知後だけ、同packet一回から全266保存台帳を検算する。
    引数: なし。CLIの明示完了フラグをmainが要求する。
    返り値: None。固定条件の監査証跡だけを保存し、追加場で再選択しない。
    """
    destination = HERE/'追加Day全121と旧入口及び全266台帳の独立金融監査.json'
    assert not destination.exists()
    plan_value = read(HERE/'追加Day全121独立監査の計画_人工後最終接続.json')
    assert plan_value['全合格'] and plan_value['SHA256'] == own_sources()
    before = own_sources()
    folder = WAVE/'holdout_finance'
    fixed, final = read(folder/'追加Day金融の事前固定.json'), read(folder/'追加Day全121の損益.json')
    old_fixed = read(WAVE/'金融事前固定.json')
    assert fixed['全合格'] and final['全合格'] and fixed['session'] == final['session'] == SESSION
    assert fixed['source_SHA256'] == final['source_SHA256'] and final['開始終端source一致']
    assert len(fixed['catalog']) == 121 and FULL.canonical(fixed['catalog']) == FULL.canonical(old_fixed['catalog'])
    assert fixed['primary'] == final['主'] == old_fixed['primary']
    assert final['固定121条件変更'] == fixed['追加場での再選択'] == fixed['活動資格と採用基準の変更'] == 0
    for name, wanted in fixed['source_SHA256'].items():
        assert sha(ROOT/name) == wanted, name
    metadata_path = WAVE/'holdout_input/追加Dayの活動と19入口.json'
    metadata = read(metadata_path)
    COUNTS['追加活動JSON読取'] += 1
    path = ROOT/metadata['path']
    assert path.resolve().is_relative_to((WAVE/'holdout_input').resolve())
    payload = path.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == metadata['SHA256']
    bundle = pickle.loads(gzip.decompress(payload))
    del payload
    COUNTS['追加活動pickle読取'] += 1
    assert bundle['schema_version'] == 1 and bundle['session'] == SESSION
    assert set(bundle['prepared']) == {(SESSION, symbol) for symbol in ('TOPIX', 'NK225')}
    entries = [dict(id=cfg['entry_id'], family=cfg['family'], gate=cfg['gate']) for cfg in fixed['catalog']
        if cfg['kind'] == 'single' and cfg['exit_id'] == 'O']
    assert len(entries) == len(bundle['peer']['cases']) == 19
    contexts = COMMON.check_prepared(bundle['peer'], bundle['activity'], bundle['prepared'], entries, SESSION)
    assert len(final['cases']) == 121 and set(final['cases']) == {cfg['id'] for cfg in fixed['catalog']}
    hashes, computed = {}, {}
    for symbol in ('TOPIX', 'NK225'):
        context, legs = contexts[symbol], {}
        for key, item in final['extra_legs'].items():
            market, component, exit_id, qty = key.split('|')
            if market != symbol:
                continue
            CURRENT.update(銘柄=symbol, 条件=key)
            ledger = FULL.load_ledger(item, folder/'legs', hashes)
            cfg = dict(id=component+'_'+exit_id+'_Q'+qty, kind='single', entry_id=component, exit_id=exit_id, quantity={symbol: int(qty)})
            assert ledger['entry_id'] == component and ledger['configured_quantity'] == int(qty) and ledger['exit_id'] == exit_id
            _, connection = LEDGER.audit(ledger, context, cfg)
            legs[component, exit_id, int(qty)] = connection
            COUNTS['追加実量腿'] += 1
        assert len(legs) == 12
        for config in fixed['catalog']:
            ident = config['id']
            CURRENT.update(銘柄=symbol, 条件=ident)
            document = final['cases'][ident]
            assert FULL.canonical(document['config']) == FULL.canonical(config)
            rows = [row for row in document['rows'] if row['session'] == SESSION and row['symbol'] == symbol]
            assert len(rows) == 1 and len(document['rows']) == 2
            ledger = FULL.load_ledger(document['ledgers'][SESSION+'|'+symbol], folder/'ledger', hashes)
            if config['kind'] == 'previous':
                independent = legacy_audit(ledger, context)
            else:
                assert ledger['exit_id'] == config['exit_id']
                quantity = sum(config['allocations'][symbol]) if config['kind'] == 'portfolio' else config['quantity'][symbol]
                assert ledger['configured_quantity'] == quantity
                if config['kind'] == 'portfolio':
                    components, allocation = config['components'], config['allocations'][symbol]
                    FULL.join_check(ledger, legs[components[0], config['exit_id'], allocation[0]], legs[components[1], config['exit_id'], allocation[1]])
                    assert ledger['entry_id'] is None
                else:
                    assert ledger['entry_id'] == config['entry_id']
                independent, _ = LEDGER.audit(ledger, context, config)
            FULL.compare_row(rows[0], independent, (ident, symbol))
            independent.update(session=SESSION, symbol=symbol)
            computed.setdefault(ident, {})[symbol] = independent
            COUNTS['追加Day全掲載口座'] += 1
        print(symbol+' 追加Day全121と12実量腿を独立検算', flush=True)
        del legs
    assert len(hashes) == COUNTS['全新台帳'] == final['新台帳数'] == 266
    assert COUNTS['追加Day全掲載口座'] == final['掲載会計数'] == 242
    assert COUNTS['追加実量腿'] == final['追加実枚数腿数'] == 24
    assert COUNTS['実量腿と配分完全連結'] == final['配分合算会計数'] == 12
    assert COUNTS['旧G0新台帳独立監査'] == 2 and final['新実数量金融再生数'] == 254
    for name, wanted in fixed['source_SHA256'].items():
        assert sha(ROOT/name) == wanted, name
    assert before == own_sources()
    save(destination, dict(全合格=True, session=SESSION, scope=plan_value['scope'], 検査件数=dict(COUNTS),
        SHA256=dict(before, **{str(path.relative_to(ROOT)): sha(path) for path in (metadata_path,
            folder/'追加Day金融の事前固定.json', folder/'追加Day全121の損益.json')}),
        入力packetSHA256=metadata['SHA256'], 全266台帳SHA256=hashes, 全121独立追加場会計=computed,
        事前固定sourceSHA256=fixed['source_SHA256'], 旧G0='同完全preparedの旧P0候補→C1/L1待機→実注文。新104qualifiedを適用しない。',
        再選択=0, 再ランキング=0, 金融再実行=0, counterfactual生成=0, 旧64base読取=0,
        旧32cache読取=0, 原本読取=0, NPZ読取=0, API取得=0, 実注文=0, goal操作=0,
        限界='追加一場だけ。旧32と条件固定した別確認であり、将来安定の証明や新候補選択ではない。価格時計は受信時刻ではない。'))
    print(json.dumps(dict(全合格=True, 検査件数=dict(COUNTS), SHA256=sha(destination)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument('--plan', action='store_true')
        mode.add_argument('--root-additional-results-complete', action='store_true')
        options = parser.parse_args()
        plan() if options.plan else run()
    except Exception as error:
        number = 1
        while (HERE/f'追加Day独立監査False_{number:05d}.json').exists():
            number += 1
        save(HERE/f'追加Day独立監査False_{number:05d}.json', dict(全合格=False, 対象=CURRENT, 例外=str(error),
            traceback=traceback.format_exc(), 完了検査件数=dict(COUNTS), sourceSHA256=sha(Path(__file__)),
            金融再生=0, 原本読取=0, NPZ読取=0, API取得=0, goal操作=0))
        raise
