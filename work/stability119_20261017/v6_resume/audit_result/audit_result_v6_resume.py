"""hの新14保存注文と旧66引用を独立会計し、原市場と旧33を再運転しない。"""

import argparse
from decimal import Decimal, ROUND_FLOOR
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
V6 = HERE.parent
BASE = V6.parent
ROOT = BASE.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / 'audit_result119'))
import saved_accounting as audit

READS = dict(結果=0, 新入力=0, 新台帳=0, 旧保存会計=0, 原市場=0, 旧入力cache=0, 金融再実行=0)
ACTUAL = {'TOPIX': 'E01_ADAPT_G50_ADAPT75_P1', 'NK225': 'E01_ADAPT_G25_ADAPT100_P1'}
MULTIPLIERS = {'TOPIX': 1000., 'NK225': 10.}
FEES = {'TOPIX': '41.8', 'NK225': '11'}
CAPS = {'TOPIX': 10, 'NK225': 20}


# ----------------------------------------


def fee(quantity: int, symbol: str) -> int:
    """
    機能: 一つの注文又はUID残数量に対する料金を独立に切り捨てる。
    引数: quantity(int)、symbol(str) は実枚数と商品。
    返り値: int は円単位の料金。異なるUIDの返済予定料は合算切捨てしない。
    """
    return int((Decimal(int(quantity)) * Decimal(FEES[symbol])).to_integral_value(rounding=ROUND_FLOOR))


def write(path: Path, value: dict) -> dict:
    """
    機能: 所有領域に新しい有限JSONを保存する。
    引数: path(Path)、value(dict) は保存位置と資料。
    返り値: dict は位置・SHA・bytes。過去の成功/Falseを上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return dict(path=path.relative_to(ROOT).as_posix(), SHA256=audit.sha(payload), bytes=len(payload))


def compare(actual: object, expected: object, label: str) -> None:
    """
    機能: 日本語台帳のdict/list/数値を独立値と再帰照合する。
    引数: actual/expected(object)、label(str) は対象と説明。
    返り値: None。未保存値を零で補わない。
    """
    if isinstance(expected, dict):
        for key, value in expected.items():
            audit.check(key in actual, label + ':' + key)
            compare(actual[key], value, label + ':' + key)
    elif isinstance(expected, list):
        audit.check(len(actual) == len(expected), label + ':件数')
        for a, e in zip(actual, expected):
            compare(a, e, label)
    elif isinstance(expected, (str, bool)) or expected is None:
        audit.check(actual == expected, label)
    else:
        audit.near(actual, expected, label)


def own_packet(info: dict, destination: Path) -> dict:
    """
    機能: 根指定の完成cacheを一読保全し、同bytes検査後に展開する。
    引数: info(dict)、destination(Path) は位置・指紋と新保全先。
    返り値: dict は保存入力又は台帳。原市場や旧cacheを読まない。
    """
    path = ROOT / info['path']
    audit.check(path.resolve().is_relative_to(V6), '新cacheはv6所有域だけ')
    before = path.stat()
    payload = path.read_bytes()
    after = path.stat()
    audit.check((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), 'cache読取前後不変')
    audit.check(len(payload) == info['bytes'] and audit.sha(payload) == info['SHA256'], 'cache同bytes')
    assert not destination.exists()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return pickle.loads(gzip.decompress(payload))


def reconstruct(account: dict, ledger: dict) -> dict:
    """
    機能: 保存された実注文だけからUID/FIFO、親、全行時価と料金を独立復元する。
    引数: account(dict) は新入力、ledger(dict) は同じ新台帳。
    返り値: dict は独立場集計。入口/出口規則の金融再実行は行わない。
    """
    symbol, record, quotes = account['symbol'], account['record'], account['quotes']
    orders, uids, targets = ledger['orders'], ledger['order_uids'], ledger['exit_target_uids']
    n, multiplier = len(record['price']), MULTIPLIERS[symbol]
    audit.check(n > 0 and orders.shape == (len(uids), 8) and targets.shape == uids.shape, '実注文8列とUID/返済先shape')
    audit.near(record['seq'], quotes['seq'], '入力と気配は同原seq')
    audit.near(record['time_s'], quotes['time_s'], '入力と気配は同価格時計')
    audit.check(np.all(np.diff(record['seq']) > 0) and np.all(np.diff(record['time_s']) >= 0), '原seq単調と価格時計非減少')
    valid = quotes['quote_valid'] & np.isfinite(quotes['bid']) & np.isfinite(quotes['ask']) & (quotes['bid'] > 0) & (quotes['ask'] > quotes['bid'])
    audit.check(np.isfinite(orders).all() and np.all(np.diff(orders[:, 0]) >= 0), '有限で原行順の実注文')
    cash_delta, paid_delta = np.zeros(n), np.zeros(n)
    long_delta, short_delta, long_basis_delta, short_basis_delta = (np.zeros(n) for _ in range(4))
    reserved = np.zeros(n)
    states, parents, legs = {}, {}, []
    order_fees = []
    cursor, previous, reserve = 0, 0, 0
    while cursor < len(orders):
        row = int(orders[cursor, 0])
        audit.check(previous <= row < n, '注文原行範囲')
        reserved[previous:row] = reserve
        while cursor < len(orders) and int(orders[cursor, 0]) == row:
            order = orders[cursor]
            source, cid, side, quantity, new = map(int, (order[1], order[2], order[3], order[4], order[7]))
            uid, target = int(uids[cursor]), int(targets[cursor])
            audit.near(order[[0, 1, 2, 3, 4, 6, 7]], np.rint(order[[0, 1, 2, 3, 4, 6, 7]]), '注文離散欄は整数')
            audit.check(0 <= source < row and side in (-1, 1) and new in (0, 1) and 0 < quantity <= CAPS[symbol], '前原行判断・売買・実数量上限')
            audit.check(valid[row], '実注文は当時正常気配')
            audit.near(order[5], quotes['ask' if side == 1 else 'bid'][row], '実価格は買ask/売bid')
            audit.check(record['time_s'][source] <= record['time_s'][row], '同clock原行順を守る')
            cost = fee(quantity, symbol)
            paid_delta[row] += cost
            cash_delta[row] -= cost
            order_fees.append(cost)
            if cid not in parents:
                audit.check(new == 1, '親は実新規から生成')
                parents[cid] = dict(親=cid, 新規行=row, 最終返済行=row, 方向=side, 枚数=0, 費用=0, 粗損益=0.)
            parents[cid]['費用'] += cost
            if new:
                audit.check(uid >= 0 and uid not in states and target == -1, '実新規UIDの一意性')
                states[uid] = dict(cid=cid, side=side, quantity=quantity, remaining=quantity, row=row, price=order[5], fee=cost)
                parents[cid]['枚数'] += quantity
                if side == 1:
                    long_delta[row] += quantity
                    long_basis_delta[row] += quantity * order[5]
                else:
                    short_delta[row] += quantity
                    short_basis_delta[row] += quantity * order[5]
            else:
                audit.check(uid == -1, '返済注文自身に新UIDを付けない')
                remaining = quantity
                for current, state in states.items():
                    if (target >= 0 and current != target) or state['cid'] != cid or state['side'] != -side or not state['remaining']:
                        continue
                    q = min(remaining, state['remaining'])
                    gross = state['side'] * (order[5] - state['price']) * q * multiplier
                    infee, outfee = state['fee'] * q / state['quantity'], cost * q / quantity
                    legs.append(dict(uid=current, 親=cid, 方向=state['side'], 枚数=q, 新規行=state['row'], 返済行=row,
                        新規価格=state['price'], 返済価格=order[5], 粗損益=gross, 新規料金配分=infee, 返済料金配分=outfee,
                        収支=gross - infee - outfee, 返済注文=cursor, 理由=int(order[6])))
                    state['remaining'] -= q
                    remaining -= q
                    cash_delta[row] += gross
                    parents[cid]['粗損益'] += gross
                    if state['side'] == 1:
                        long_delta[row] -= q
                        long_basis_delta[row] -= q * state['price']
                    else:
                        short_delta[row] -= q
                        short_basis_delta[row] -= q * state['price']
                    if remaining == 0:
                        break
                audit.check(remaining == 0, '返済超過なし・UID指定又はFIFO')
                parents[cid]['最終返済行'] = row
            cursor += 1
        reserve = sum(fee(state['remaining'], symbol) for state in states.values() if state['remaining'])
        previous = row
    reserved[previous:] = reserve
    long_qty, short_qty = np.cumsum(long_delta), np.cumsum(short_delta)
    audit.check(np.all((long_qty >= 0) & (long_qty <= CAPS[symbol])) and np.all((short_qty >= 0) & (short_qty <= CAPS[symbol])), '全原行の片方向保有上限')
    q = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
    audit.check(not np.any((q < 0) & ((long_qty > 0) | (short_qty > 0))), '正常気配前の未知建玉時価を作らない')
    bid, ask = np.where(q >= 0, quotes['bid'][np.maximum(q, 0)], 0.), np.where(q >= 0, quotes['ask'][np.maximum(q, 0)], 0.)
    cash = np.cumsum(cash_delta)
    unrealized = ((long_qty * bid - np.cumsum(long_basis_delta)) + (np.cumsum(short_basis_delta) - short_qty * ask)) * multiplier
    equity, paid = cash + unrealized, np.cumsum(paid_delta)
    for field, values in dict(equity_yen=equity, liquidation_yen=equity-reserved, reserved_exit_fees=reserved,
                              long_qty=long_qty, short_qty=short_qty, cumulative_fees=paid).items():
        audit.near(ledger[field], values, '全原行の独立会計:' + field)
    audit.near(ledger['order_fees'], order_fees, '全注文の支払料金')
    audit.check(long_qty[-1] == short_qty[-1] == reserved[-1] == 0 and all(state['remaining'] == 0 for state in states.values()), '新14は実終端全玉返済')
    parent_rows = list(parents.values())
    for parent in parent_rows:
        parent['収支'] = parent['粗損益'] - parent['費用']
    compare(ledger['parent'], parent_rows, '親全会計')
    compare(ledger['actual_legs'], legs, 'UID別の全返済玉と費用按分')
    uid_rows = []
    for uid, state in states.items():
        own = [leg for leg in legs if leg['uid'] == uid]
        uid_rows.append(dict(uid=uid, 親=state['cid'], 方向=state['side'], 枚数=state['quantity'], 残枚数=state['remaining'],
            新規行=state['row'], 新規価格=state['price'], 収支=sum(leg['収支'] for leg in own), 実玉数=len(own)))
    compare(ledger['uid_accounts'], uid_rows, '全UID残数量と決済会計')
    nets = np.asarray([parent['収支'] for parent in parent_rows])
    gain, loss = float(sum(np.maximum(nets, 0.))), float(sum(np.maximum(-nets, 0.)))
    summary = dict(利益=gain, 損失=loss, 収支=float(sum(nets)), 親数=len(nets), 勝ち親=int(sum(nets > 0)),
        負け親=int(sum(nets < 0)), 零親=int(sum(nets == 0)), 費用=int(sum(order_fees)),
        新規枚数=sum(state['quantity'] for state in states.values()), 勝ち枚数=sum(leg['枚数'] for leg in legs if leg['収支'] > 0),
        負け枚数=sum(leg['枚数'] for leg in legs if leg['収支'] < 0), 零枚数=sum(leg['枚数'] for leg in legs if leg['収支'] == 0),
        最大買枚数=int(max(long_qty)), 最大売枚数=int(max(short_qty)),
        最大DD=float(max(np.maximum.accumulate(np.maximum(equity, 0.)) - equity)), 最悪時価=float(min(0., min(equity))),
        注文件数=len(orders), 全会計合格=True)
    compare(ledger['summary'], summary, '新口座場会計')
    audit.near(summary['収支'], cash[-1], '全実現現金と全親net')
    return summary


def metrics(rows: list[dict]) -> dict:
    """
    機能: 旧保存引用と新会計を分母どおりに独立集計する。
    引数: rows(list[dict]) は同商品同期間の場会計。
    返り値: dict は利益・損失・黒赤場・中央値等。無取引は勝ちにしない。
    """
    net = [r['net'] for r in rows]
    positive, negative = [v for v in net if v > 0], [v for v in net if v < 0]
    gain, loss = sum(r['profit'] for r in rows), sum(r['loss'] for r in rows)
    active = sum(r['campaigns'] > 0 for r in rows)
    return dict(net=sum(net), profit=gain, loss=loss, fees=sum(r['fees'] for r in rows), parents=sum(r['campaigns'] for r in rows),
        sessions=len(rows), positive=len(positive), negative=len(negative), active=active, no_trade=len(rows)-active,
        median=float(np.median(net)), mean_session_net=sum(net)/len(net), profit_share=gain/(gain+loss) if gain+loss else None,
        mean_positive_session_net=sum(positive)/len(positive) if positive else None, worst_session_loss=max([-v for v in negative], default=0),
        黒字率=len(positive)/len(rows), 未取引は勝ちでない=True, 旧十万円床を判定に使用しない=True)


# ----------------------------------------


def main(expected_sha: str) -> None:
    """
    機能: 完成SHA後に結果/新28cache/旧66引用を一読保全して全80行を独立照合する。
    引数: expected_sha(str) は根が完成後に通知した結果指紋。
    返り値: None。原市場と旧33入力/金融を再生しない。
    """
    audit.check(len(expected_sha) == 64, '完成後の根SHA必須')
    owned = HERE / 'owned'
    owned.mkdir(exist_ok=False)
    payload = (V6 / 'measurement/少額E01固定二設定の追加七場と全四十場.json').read_bytes()
    READS['結果'] += 1
    audit.check(audit.sha(payload) == expected_sha, '完成結果同bytes')
    (owned / '完成結果.json').write_bytes(payload)
    result = json.loads(payload.decode('utf-8'))
    fixed = json.loads((V6 / '固定計画.json').read_text(encoding='utf-8'))
    manifest_bytes = (ROOT / fixed['input_manifest']['path']).read_bytes()
    audit.check(audit.sha(manifest_bytes) == fixed['input_manifest']['sha256'], '事前入力目録一致')
    manifest = json.loads(manifest_bytes.decode('utf-8'))
    audit.check(result['全合格'] is True and result['source_SHA256'] == result['source_end_SHA256'] == fixed['source_SHA256'], '固定122源開始終端一致')
    for path, sha in fixed['source_SHA256'].items():
        audit.check(audit.sha((ROOT / path).read_bytes()) == sha, '経済源不変')
    audit.check(result['actual_config'] == ACTUAL and result['old_financial_rerun'] == result['old_comparison_rerun'] == 0, '旧二設定と再金融なし')
    audit.check(result['sessions'] == manifest['sessions'] and len(result['rows']) == 80 and len(result['old_rows']) == 66
                and len(result['new_accounts']) == len(result['cache']) == 14, '旧66引用と新14の80会計')
    expected_count = dict(既stagebook一読=14, 既stage1分CSV一読=14, 既stage5分CSV一読=14, 新E01紙上口座=14, 新実GU=14, 新実政策会計=14)
    audit.check(result['counters'] == expected_count and len(result['read_log']) == 42, '今回目的だけの実行/入力数')
    audit.check(result['raw_reads']==0 and result['new_actual_accounts']==14 and result['reused_accounting']==66 and result['inherited_original_reads']==42, 'h原新読0・新14・旧66・f既読42を分離')
    audit.check(result['new_sessions']==manifest['new_sessions'] and len(result['new_sessions'])==7, '追加七場固定')
    expected_new={(scene,symbol) for scene in result['new_sessions'] for symbol in ACTUAL}
    audit.check(len({(d['session'],d['symbol']) for d in result['new_accounts']})==14 and {(d['session'],d['symbol']) for d in result['new_accounts']}==expected_new, '新14識別の欠落重複なし')
    audit.check(set(result['cache'])=={scene+'|'+symbol for scene,symbol in expected_new}, '新28cacheの識別集合')
    compare(result['old_rows'], result['rows'][:66], '旧66保存行の二表示一致')
    compare(result['stopped_trial'],manifest['stopped_trial'],'f停止履歴の完全一致')
    audit.check(result['stopped_trial']['original_reads']==42 and result['stopped_trial']['new_financial']==0, 'f金融0中断の保持')
    manifests={item['path']:item for item in manifest['inputs']}
    audit.check(len({item['path'] for item in result['read_log']})==42 and {item['path'] for item in result['read_log']}==set(manifests), '42stageの識別集合')
    for item in result['read_log']:
        for key,value in manifests[item['path']].items():compare(item[key],value,'固定stage由来:'+key)
        audit.check(item['original_reads']==0 and item['staged_copy_reads']==1, '原本追加読0・既stage各一読')
        if item['kind']=='book':
            audit.check(item['clock_qualification']['original_SHA256']==item['SHA256'] and item['clock_qualification']['原価格時計変更'] is False and item['clock_qualification']['日付推定'] is False, 'book表示の元指紋と日付非推定')
        else:
            audit.check(item['csv_clock_guard']['strictly_increasing'] is True and item['csv_clock_guard']['原時刻修正'] is False, 'CSV時計の拒否検査由来')
    audit.check(result['old_reference'] == manifest['old_reference'], '旧引用参照位置とSHA固定')
    reference = ROOT / result['old_reference']['path']
    audit.check(reference.resolve().is_relative_to(BASE), '旧会計は根の同bytes所有参照だけ')
    old_bytes = reference.read_bytes()
    READS['旧保存会計'] += 1
    audit.check(audit.sha(old_bytes) == result['old_reference']['SHA256'], '旧保存会計同bytes')
    (owned / '旧保存会計.json').write_bytes(old_bytes)
    old = json.loads(old_bytes.decode('utf-8-sig'))
    lookup = {(r['session'], r['symbol']): r for r in result['rows']}
    audit.check(len(lookup) == 80 and {(s, k) for s in result['sessions'] for k in ACTUAL} == set(lookup), '80行の欠落重複なし')
    for symbol, config in ACTUAL.items():
        prior = [r for r in old['cases'][config]['rows'] if r['symbol'] == symbol]
        audit.check(len(prior) == 33, '商品別の旧33保存行だけ')
        for given in prior:
            current = lookup[given['session'], symbol]
            overwritten={'method','actual_config','origin','unclosed','verified_flat','verified_flat_basis','保存範囲'}
            compare(current,{k:v for k,v in given.items() if k not in overwritten}, '旧保存行の経済値を無変更引用')
            audit.check(current['method']=='E01_006_FIXED' and current['actual_config']==config and current['origin']=='旧33保存会計の引用', '旧引用の表示metadata')
            audit.check(current['unclosed'] is None and current['verified_flat'] is True and bool(current['verified_flat_basis']), '旧終端枚数はnull保持・flat検査へ委譲')
    certificates = []
    for detail in result['new_accounts']:
        scene, symbol = detail['session'], detail['symbol']
        info = result['cache'][scene + '|' + symbol]
        account = own_packet(info['input'], owned / 'input' / symbol / (scene + '.pkl.gz'))
        READS['新入力'] += 1
        ledger = own_packet(info['ledger'], owned / 'ledger' / symbol / (scene + '.pkl.gz'))
        READS['新台帳'] += 1
        audit.check(account['symbol'] == symbol and ledger['key'] == (scene, symbol), '新cache識別一致')
        summary = reconstruct(account, ledger)
        compare(detail['summary'], summary, 'JSONと新台帳の会計')
        compare(detail['parent'], ledger['parent'], 'JSONと新台帳の全親')
        compare(detail['actual_legs'], ledger['actual_legs'], 'JSONと新台帳の全決済玉')
        compare(detail['uid_accounts'], ledger['uid_accounts'], 'JSONと新台帳の全UID')
        current = lookup[scene, symbol]
        compare(current, dict(profit=summary['利益'], loss=summary['損失'], net=summary['収支'], campaigns=summary['親数'],
            winning_campaigns=summary['勝ち親'], losing_campaigns=summary['負け親'], winning_lots=summary['勝ち枚数'],
            losing_lots=summary['負け枚数'], fees=summary['費用'], unclosed=0), '新場行と実注文会計')
        audit.check(len(detail['orders']) == len(ledger['orders']), 'JSON全注文数')
        for i, given in enumerate(detail['orders']):
            order = ledger['orders'][i]
            row = int(order[0])
            compare(given, dict(index=i, order=order.tolist(), uid=int(ledger['order_uids'][i]), fee=int(ledger['order_fees'][i]),
                raw_seq=int(account['record']['seq'][row]), price_time_s=float(account['record']['time_s'][row]),
                bid=float(account['quotes']['bid'][row]), ask=float(account['quotes']['ask'][row]), quote_valid=True), 'JSONと全実注文原seq/BBO/費用')
        certificates.append(dict(session=scene, symbol=symbol, 実終端flat=True, 全注文会計一致=True))
        print(json.dumps(dict(新口座=len(certificates), session=scene, symbol=symbol, 検査数=audit.CHECKS), ensure_ascii=False), flush=True)
    for symbol in ACTUAL:
        for name, scenes in (('全40', result['sessions']), ('旧33', result['old_sessions']), ('追加7', result['new_sessions'])):
            compare(result['metrics'][symbol][name], metrics([lookup[scene, symbol] for scene in scenes]), '商品別期間集計')
    audit.check(READS == dict(結果=1, 新入力=14, 新台帳=14, 旧保存会計=1, 原市場=0, 旧入力cache=0, 金融再実行=0), '許可範囲一読だけ')
    write(HERE / 'h旧六十六引用と新十四口座の全注文親UID及び全行時価の独立監査.json', dict(全合格=True,
        検査数=audit.CHECKS, counts=READS, 結果SHA256=expected_sha, source_SHA256=fixed['source_SHA256'],
        監査源SHA256=audit.sha(Path(__file__).read_bytes()), 新実終端flat=14, 旧終端flat保証委譲=66,
        旧終端枚数はnull保持=True, 全80場行会計=True, 場別確認=certificates,
        限界='同じ保存会計の整合確認。原市場追加読取/旧33再金融/有効性標本追加0。旧33終端はcad15の既検証完了源へ委譲する。'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args()
    try:
        main(args.expected_sha)
    except BaseException as exc:
        write(HERE / 'False.json', dict(全合格=False, counts=READS, 検査数=audit.CHECKS, 型=type(exc).__name__, 例外=str(exc)))
        raise
