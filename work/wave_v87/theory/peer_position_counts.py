"""旧GUの注文だけから保有を復元し、相手状態を過去時点で参照できる機会を数える。"""

from collections import Counter
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'work/wave_v87/round7/observed'


def digest(path):
    """
    機能: 読み取り対象のSHA256を計算する。
    引数: path(Path)は既存ファイル。
    返り値: strのSHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(4 * 1024 * 1024):
            h.update(data)
    return h.hexdigest()


def fee(quantity, symbol):
    """
    機能: 1注文の約定枚数に原GUの片道料金を適用する。
    引数: quantity(int)、symbol(str)。
    返り値: intの円未満切捨て料金。
    """
    unit = Decimal('41.8') if symbol == 'TOPIX' else Decimal('11')
    return int((quantity * unit).to_integral_value(rounding=ROUND_FLOOR))


def build_book(ledger, ready, symbol, cut=None):
    """
    機能: 新規・返済を保存順で適用し、各注文行の保有と既知停止イベントを復元する。
    引数: ledger/ready(dict)、symbol(str)、cut(int又はNone)は原本の途中切断位置。
    返り値: dictの状態、入口、停止イベント。cycles/trades/net_tradesは参照しない。
    """
    n = len(ready['time_s']) if cut is None else cut
    times = ready['time_s'][:n]
    prices = ready['last'][:n]
    assert np.all(np.diff(times) >= 0)
    orders = ledger['orders'][ledger['orders'][:, 0] < n]
    preparations = {int(x[0]): x for x in ledger['prepare_events'] if int(x[1]) < n}
    links = {int(x[0]): x for x in ledger['entry_preparations'] if int(x[1]) < n}
    value = 1000 if symbol == 'TOPIX' else 10
    snapshots, entries, stops = [], [], []
    cid, side, quantity, entry_row, entry_price, atr = -1, 0, 0, -1, 0.0, 0.0
    cash, paid = 0.0, 0
    pointer = 0
    while pointer < len(orders):
        row = int(orders[pointer, 0])
        while pointer < len(orders) and int(orders[pointer, 0]) == row:
            order = orders[pointer]
            pointer += 1
            source, current_cid, direction, qty, price, reason, new = order[1:]
            source, current_cid, direction, qty, reason, new = map(int, (source, current_cid, direction, qty, reason, new))
            assert 0 <= source < row < n
            assert abs(float(price) - float(prices[row])) < 1e-7
            if new:
                assert quantity == 0
                link = links[current_cid]
                prep = preparations[int(link[2])]
                assert int(link[1]) == row and int(link[3]) == int(prep[1])
                assert int(prep[1]) <= source < row and int(prep[2]) == direction
                cid, side, quantity = current_cid, direction, qty
                entry_row, entry_price, atr = row, float(price), float(prep[4])
                assert atr > 0
                cash, paid = 0.0, 0
                entries.append({'組': cid, '行': row, '根拠行': source, '時刻': float(times[row]),
                                '方向': side, '枚数': qty, '価格': entry_price, '固定ATR': atr,
                                'ATR準備行': int(prep[1])})
            else:
                assert current_cid == cid and direction == -side and 0 < qty <= quantity
                quantity -= qty
            cash -= direction * qty * float(price) * value
            paid += fee(qty, symbol)
            if not new and quantity == 0:
                net = cash - paid
                if reason in (1, 32) and net < 0:
                    stops.append({'組': cid, '行': row, '根拠行': source, '時刻': float(times[row]),
                                  '方向': side, '理由': reason, '既払料': paid,
                                  '当時までの全返済収支': net, '新規行': entry_row})
        snapshots.append({'行': row, '組': cid, '方向': side if quantity else 0,
                          '枚数': quantity, '新規行': entry_row, '建値': entry_price,
                          '固定ATR': atr, '現金': cash, '既払料': paid})
    good = np.isfinite(prices) & (prices > 0)
    good_rows = np.flatnonzero(good)
    return {'states': snapshots, 'rows': np.asarray([x['行'] for x in snapshots], dtype=np.int64),
            'entries': entries, 'stops': stops, 'orders': orders, 'times': times, 'prices': prices,
            'good_rows': good_rows, 'value': value, 'symbol': symbol}


def state_at(book, row):
    """
    機能: 当該行までに適用した注文だけから口座状態を得る。
    引数: book(dict)、row(int)。
    返り値: dictの保有状態。まだ注文がない場合はゼロ保有。
    """
    index = int(np.searchsorted(book['rows'], row, side='right')) - 1
    if index < 0:
        return {'行': -1, '組': -1, '方向': 0, '枚数': 0, '新規行': -1,
                '建値': 0.0, '固定ATR': 0.0, '現金': 0.0, '既払料': 0}
    return book['states'][index]


def peer_at(book, stamp):
    """
    機能: 自己時刻より厳密に過去の相手価格と、その時点までの口座状態を参照する。
    引数: book(dict)は相手口座、stamp(float)は自己代理時計。
    返り値: tuple(dict又はNone,int)。同時計の後続行は使用しない。
    """
    before = int(np.searchsorted(book['times'], stamp, side='left')) - 1
    if before < 0:
        return None, -1
    valid_i = int(np.searchsorted(book['good_rows'], before, side='right')) - 1
    if valid_i < 0:
        return None, -1
    row = int(book['good_rows'][valid_i])
    assert book['times'][row] < stamp
    # 状態も評価価格も同じ最後の有効相手原本行までに限定する。
    return state_at(book, row), row


def entry_checks(own, peer, session, decision=False):
    """
    機能: 旧自己新規の各行で、相手の保有・現在の順行・清算収支を確認する。
    引数: own/peer(dict)、session(str)、decision(bool)は発注根拠行の参考集計指定。
    返り値: list[dict]。自己の将来勝敗は含めない。
    """
    output = []
    for entry in own['entries']:
        row = entry['根拠行'] if decision else entry['行']
        stamp = float(own['times'][row])
        state, ref = peer_at(peer, stamp)
        equal = [o for o in peer['orders'] if peer['times'][int(o[0])] == stamp]
        label = '不明' if state is None else ('flat' if not state['枚数'] else (
            '同方向' if state['方向'] == entry['方向'] else '反対'))
        item = {'セッション': session, '商品': own['symbol'], '自己組': entry['組'],
                '自己新規行': entry['行'], '自己判断行': row, '自己時計': stamp,
                '自己方向': entry['方向'], '相手分類': label, '相手参照行': ref,
                '除外した相手同時計注文数': len(equal),
                '除外注文': [{'行': int(o[0]), '組': int(o[2]), '新規': int(o[7]), '理由': int(o[6])} for o in equal]}
        if ref >= 0:
            item.update(相手時計=float(peer['times'][ref]),
                        相手観測の古さ=float(stamp - peer['times'][ref]),
                        相手組=state['組'], 相手保有枚数=state['枚数'])
            assert peer['times'][ref] < stamp
            if state['枚数']:
                current = float(peer['prices'][ref])
                mtm = state['現金'] + state['方向'] * state['枚数'] * current * peer['value']
                mtm -= state['既払料'] + fee(state['枚数'], peer['symbol'])
                progress = state['方向'] * (current - state['建値']) / state['固定ATR']
                item.update(相手清算収支=mtm, 相手現在順行ATR=progress,
                            相手料金込非負=mtm >= 0, 相手現在順行025以上=progress >= .25 - 1e-12,
                            相手固定ATR=state['固定ATR'], 相手建値=state['建値'],
                            相手評価現在値=current, 相手新規行=state['新規行'])
        output.append(item)
    return output


def stop_checks(own, peer, session):
    """
    機能: 相手の確定した負け停止が初めて厳密過去になる自己行で、自己保有を確認する。
    引数: own/peer(dict)、session(str)。
    返り値: list[dict]。自己の未来終了行・最終収支は使用しない。
    """
    output = []
    for stop in peer['stops']:
        stamp = stop['時刻']
        left = int(np.searchsorted(own['times'], stamp, side='left'))
        after = int(np.searchsorted(own['times'], stamp, side='right'))
        valid_i = int(np.searchsorted(own['good_rows'], after, side='left'))
        row = int(own['good_rows'][valid_i]) if valid_i < len(own['good_rows']) else -1
        item = {'セッション': session, '商品': own['symbol'], '相手停止': stop,
                '同時計のため未公開の自己原本行数': after - left,
                '最初の公開自己行': row, '機会': False}
        if row < 0:
            item['分類'] = '後続有効自己観測なし'
        else:
            state = state_at(own, row)
            assert stamp < own['times'][row]
            item.update(自己公開時計=float(own['times'][row]), 自己組=state['組'],
                        自己方向=state['方向'], 自己保有枚数=state['枚数'], 自己新規行=state['新規行'],
                        公開までの代理秒数=float(own['times'][row] - stamp))
            if not state['枚数']:
                item['分類'] = '自己flat'
                current_orders = own['orders'][own['orders'][:, 0] == row]
                item['公開と同じ自己行で返済あり'] = bool(np.any(current_orders[:, 7] == 0))
            elif state['方向'] != stop['方向']:
                item['分類'] = '自己が反対方向を保有'
            elif state['新規行'] == row:
                item['分類'] = '同方向だが自己新規と同じ公開行'
            else:
                assert state['新規行'] < row
                item['分類'] = '自己新規後に同方向保有中へ到着'
                item['機会'] = True
                entry_time = float(own['times'][state['新規行']])
                item['相手停止と自己新規が同時計'] = stamp == entry_time
                item['相手停止の時計も自己新規より後'] = stamp > entry_time
                # 既に公開されていた古い停止を新しい自己組へ再利用しない。
                assert stamp >= entry_time
        output.append(item)
    return output


def summarize_entries(rows):
    """
    機能: 入口時点の相手状態と同方向時の二つの条件を集計する。
    引数: rows(list[dict])は入口の参照証跡。
    返り値: dictの件数。金額成績や自己の勝敗は集計しない。
    """
    same = [r for r in rows if r['相手分類'] == '同方向']
    cross = Counter(('料金非負' if r['相手料金込非負'] else '料金負') + '・' +
                    ('現在025以上' if r['相手現在順行025以上'] else '現在025未満') for r in same)
    ages = [r['相手観測の古さ'] for r in rows if r['相手参照行'] >= 0]
    return {'自己新規数': len(rows), '相手状態': dict(Counter(r['相手分類'] for r in rows)),
            '同方向保有中で料金込清算収支非負': sum(r['相手料金込非負'] for r in same),
            '同方向保有中で現在順行025ATR以上': sum(r['相手現在順行025以上'] for r in same),
            '同方向保有中で両方を満たす': sum(r['相手料金込非負'] and r['相手現在順行025以上'] for r in same),
            '同方向中の二条件内訳': dict(cross),
            '相手評価価格の代理時計上の古さ秒': {
                '中央値': float(np.median(ages)) if ages else None,
                '95百分位': float(np.quantile(ages, .95)) if ages else None,
                '最大': max(ages) if ages else None},
            '同時計相手注文を除外した自己新規数': sum(r['除外した相手同時計注文数'] > 0 for r in rows),
            '除外した相手同時計注文の延べ数': sum(r['除外した相手同時計注文数'] for r in rows)}


def summarize_stops(rows):
    """
    機能: 停止通知の到着時点に縮小判断を追加できる機会を集計する。
    引数: rows(list[dict])は停止通知の参照証跡。
    返り値: dictのイベント数と重複除外親組数。
    """
    opportunities = [r for r in rows if r['機会']]
    return {'相手の確定した全返済負け停止数': len(rows),
            '公開時点の分類': dict(Counter(r['分類'] for r in rows)),
            '新規後同方向保有中に初めて届いたイベント数': len(opportunities),
            '該当する自己親組数': len({(r['セッション'], r['自己組']) for r in opportunities}),
            '相手停止の時計も自己新規より後': sum(r['相手停止の時計も自己新規より後'] for r in opportunities),
            '相手停止と自己新規が同時計だった件数': sum(r['相手停止と自己新規が同時計'] for r in opportunities),
            '同時計自己行を除外してから公開したイベント数': sum(r['同時計のため未公開の自己原本行数'] > 0 for r in rows),
            '同時計のため未公開にした自己行延べ数': sum(r['同時計のため未公開の自己原本行数'] for r in rows)}


def main():
    """
    機能: 凍結GUと価格入力を接続し、60口座の件数・時計・未来切断を検査して保存する。
    引数: なし。
    返り値: None。新しい条件での売買再生・損益集計・条件選定は行わない。
    """
    ledger_path = BASE / 'ledgers/C_GU.pkl'
    ledgers = pickle.loads(ledger_path.read_bytes())
    saved = json.loads((BASE / 'results/C_GU.json').read_text(encoding='utf-8-sig'))
    assert digest(ledger_path) == saved['ledger_SHA256']
    manifest_path = ROOT / 'work/wave_v85/prepared/入力準備の完了.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    ready = {}
    fingerprints = {str(ledger_path.relative_to(ROOT)): digest(ledger_path),
                    str(manifest_path.relative_to(ROOT)): digest(manifest_path)}
    for record in manifest['入力対応']:
        relative = record['inputs']
        path = ROOT / relative
        actual = digest(path)
        assert actual == manifest['使用入力SHA256'][relative]
        part = pickle.loads(path.read_bytes())
        assert not set(part) & set(ready)
        ready.update(part)
        fingerprints[relative] = actual
    assert set(ready) == set(ledgers) and len(ready) == 60
    books = {key: build_book(ledgers[key], ready[key], key[1]) for key in sorted(ready)}
    all_entries, decisions, all_stops = [], [], []
    cut_count = direct_count = 0
    for key, own in books.items():
        session, symbol = key
        peer_key = (session, 'NK225' if symbol == 'TOPIX' else 'TOPIX')
        peer = books[peer_key]
        entries = entry_checks(own, peer, session)
        all_entries.extend(entries)
        decisions.extend(entry_checks(own, peer, session, decision=True))
        stops = stop_checks(own, peer, session)
        all_stops.extend(stops)
        # ----------------------------------------
        # 状態配列を使わない注文数量の直接合計でも、全入口の相手保有を照合する。
        peer_order_times = peer['times'][peer['orders'][:, 0].astype(np.int64)]
        for record in entries:
            prefix_orders = peer['orders'][peer_order_times < record['自己時計']]
            signed = int(sum(x[3] * x[4] for x in prefix_orders))
            expected = 'flat' if signed == 0 else ('同方向' if np.sign(signed) == record['自己方向'] else '反対')
            if record['相手参照行'] >= 0:
                assert expected == record['相手分類']
                assert abs(signed) == record['相手保有枚数']
            if signed and record['相手参照行'] >= 0:
                current_cid = int(prefix_orders[-1, 2])
                current_orders = prefix_orders[prefix_orders[:, 2] == current_cid]
                direct_cash = -sum(x[3] * x[4] * x[5] * peer['value'] for x in current_orders)
                direct_fee = sum(fee(int(x[4]), peer['symbol']) for x in current_orders)
                direct_mtm = direct_cash + signed * record['相手評価現在値'] * peer['value']
                direct_mtm -= direct_fee + fee(abs(signed), peer['symbol'])
                assert abs(direct_mtm - record['相手清算収支']) < 1e-6
            direct_count += 1
        # ----------------------------------------
        # 共通時計より先の注文・準備・価格を切り、過去の参照結果が変わらないことを確認。
        for fraction in [.25, .5, .75]:
            cut_time = own['times'][int(len(own['times']) * fraction)]
            own_cut = int(np.searchsorted(own['times'], cut_time, side='left'))
            peer_cut = int(np.searchsorted(peer['times'], cut_time, side='left'))
            if not own_cut or not peer_cut:
                continue
            left = build_book(ledgers[key], ready[key], symbol, own_cut)
            right = build_book(ledgers[peer_key], ready[peer_key], peer_key[1], peer_cut)
            expected_entry = [r for r in entries if r['自己時計'] < cut_time]
            assert entry_checks(left, right, session) == expected_entry
            expected_stop = [r for r in stops if r['最初の公開自己行'] >= 0 and r['自己公開時計'] < cut_time]
            actual_stop = [r for r in stop_checks(left, right, session) if r['最初の公開自己行'] >= 0]
            assert actual_stop == expected_stop
            cut_count += 1
    summaries = []
    for symbol in ['TOPIX', 'NK225']:
        summaries.append({'商品': symbol,
            '自己新規約定行': summarize_entries([r for r in all_entries if r['商品'] == symbol]),
            '参考_同じ注文の発注根拠行': summarize_entries([r for r in decisions if r['商品'] == symbol]),
            '相手負け停止の公開': summarize_stops([r for r in all_stops if r['商品'] == symbol])})
    violations = sum(r['相手時計'] >= r['自己時計'] for r in all_entries + decisions if r['相手参照行'] >= 0)
    violations += sum(r['相手停止']['時刻'] >= r['自己公開時計'] for r in all_stops if r['最初の公開自己行'] >= 0)
    assert violations == 0 and len(all_entries) == 278
    detail = {'新規約定行': all_entries, '発注根拠行': decisions, '停止公開': all_stops}
    detail_path = HERE / '相手GUの保有と停止公開の全件証跡.json'
    detail_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    result = {
        '対象': '凍結C_GUの既知全30セッション、両商品。旧自己注文を一切変更せず、当時利用できる相手状態の件数だけを確認。',
        '判定': ('相手負け停止を自己保有中に先に知れる機会は実数で確認できる。新情報ゼロを理由に途中判断の仮説を棄却する状況ではない。ただし予測優位・損益改善は未検証。'
                 if any(r['相手負け停止の公開']['新規後同方向保有中に初めて届いたイベント数'] for r in summaries)
                 else '相手負け停止を自己保有中に先に知れる機会はゼロ。この固定源を用いた途中縮小案には実効がない。'),
        '時点': '主は自己の新規約定当行。参考のorders列1は条件線などの根拠行であり、条件成立・発注判断の瞬間とは限らない。この参考件数を発注判断時のgate件数に置換しない。',
        '相手参照': '相手代理時計<自己代理時計の最後の有効価格行までの注文を適用。同時計イベントを全て除外。共通の受信時計ではないため、実通信順序の保証はしない。新しい鮮度秒数の閾値は設けていない。',
        '清算評価': '相手の当該親組の注文現金＋残枚数×方向×過去現在値×倍率−既払料−残玉全返済料。途中利確を含む。flat時の過去収支は条件に使わない。',
        '順行': '相手の現在値と相手新規建値の差を、準備時に公開済みの固定ATRで割る。最大順行ではなく現在の順行0.25ATR以上。',
        '停止': '理由1又は32で残玉ゼロとなった約定時点に、当該親の既払料込み現金が負。未来のtrades/cycles/net_tradesは読まず、注文現金から確定する。',
        '公開機会': 'その停止時計より後の最初の有効自己観測で、当該行の自己注文を適用した後も同方向保有し、新規行より後なら数える。自己新規と同じ公開行、既に自己返済済み、反対保有は除外。',
        '同時計の新規と停止': '相手停止時計と自己新規時計が同じでも、後の自己行で初めて厳密過去として届く場合は公開機会となる。その内訳を分け、停止自体が新規後に起きたこととは区別する。',
        '禁止した処理': ['自己の将来終了行・最終損益の参照', '相手の未来終了行・未来勝敗ラベルの参照',
                        '今回条件による新しい売買再生', '自己の勝敗によるgate選択', '現在API取得'],
        '商品別': summaries,
        '監査': {'口座': len(books), '自己新規': len(all_entries), '厳密過去時計違反': violations,
                 '状態配列によらない注文直接照合': direct_count,
                 '共通時計の未来切断一致': cut_count, '同時計イベントの除外': '全件証跡に行・CID・新規返済区分を記録'},
        '証跡': str(detail_path.relative_to(ROOT)), '証跡SHA256': digest(detail_path),
        '入力SHA256': fingerprints,
    }
    output = HERE / '相手GUの保有と負け停止が当時参照できた件数.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'商品別': summaries, '監査': result['監査']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
