"""赤字場の具体箇所を、当時の兆候と事後の回復を分けて診断する。"""

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import io
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = ROOT/'work/wave_v104'
IDS = ('C_N30_B4', 'U_P10_T2')
SYMBOLS = ('TOPIX', 'NK225')
COUNTS, INPUTS = Counter(), {}


def read(path: Path) -> dict:
    """
    機能: 既検算会計又は新診断計画の小JSONを読む。
    引数: path(Path)はJSON位置。
    返り値: dictは内容。金融再生、原本、NPZ、APIは呼ばない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 小sourceと小会計の内容指紋を求める。
    引数: path(Path)は保存資料。
    返り値: strはSHA256。巨大cacheはloadedの一回読取bytesから計算する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 日本語UTF-8の新診断だけを保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。旧成果及び完成資料を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def small(value: object) -> object:
    """
    機能: numpy数値と不明をJSONで区別できる型へ変換する。
    引数: value(object)は観測値。
    返り値: objectは数値、bool、列、辞書又はNone。不明を0へ補完しない。
    """
    if isinstance(value, dict):
        return {str(key): small(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [small(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def stamp(seconds: float) -> str:
    """
    機能: 原板の価格代理時計を日本時間の時刻へ表示する。
    引数: seconds(float)はepoch秒。
    返り値: strはミリ秒付き日本時刻。実受信順やネットワーク遅延は示さない。
    """
    return datetime.fromtimestamp(float(seconds), timezone(timedelta(hours=9))).isoformat(timespec='milliseconds')


def selected() -> tuple[dict, dict, dict]:
    """
    機能: 全33会計から条件・商品ごとに収支赤字の上位3場を機械的に選ぶ。
    引数: なし。
    返り値: tuple[dict,dict,dict]は選定、旧32各条件会計及び追加会計。
    """
    final = read(PREVIOUS/'金融全32の結果.json')
    extra = read(PREVIOUS/'holdout_finance/追加Day全121の損益.json')
    documents, chosen = {}, {}
    for ident in IDS:
        item = final['results'][ident]
        assert digest(ROOT/item['path']) == item['SHA256']
        document = read(ROOT/item['path'])
        documents[ident] = document
        for symbol in SYMBOLS:
            rows = document['rows']+extra['cases'][ident]['rows']
            assert len([row for row in rows if row['symbol'] == symbol]) == 33
            losers = sorted((row for row in rows if row['symbol'] == symbol and row['net'] < -1e-5), key=lambda row: (row['net'], row['session']))[:3]
            chosen[ident+'|'+symbol] = [dict(session=row['session'], net=row['net'], profit=row['profit'], loss=row['loss'], parents=row['campaigns']) for row in losers]
    return chosen, documents, extra


def plan() -> None:
    """
    機能: 重いcache読取前に対象90親、入力一回読取と固定診断述語を登録する。
    引数: なし。
    返り値: None。事後の損益から閾値を探さず診断計画だけを保存する。
    """
    chosen, documents, extra = selected()
    sessions = sorted({row['session'] for values in chosen.values() for row in values})
    normal = read(PREVIOUS/'入口準備の全32結果.json')
    activity = read(ROOT/'work/wave_v103/activity/全32の状態可用性と発火.json')
    addition = read(PREVIOUS/'holdout_input/追加Dayの活動と19入口.json')
    accounts = []
    for key, values in chosen.items():
        ident, symbol = key.split('|')
        for row in values:
            source = extra['cases'][ident] if row['session'] == extra['session'] else documents[ident]
            accounts.append(dict(case=ident, symbol=symbol, **row, ledger=source['ledgers'][row['session']+'|'+symbol]))
    assert len(accounts) == 12 and sum(value['parents'] for value in accounts) == 90
    save(HERE/'赤字上位場の入力と診断範囲の事前計画.json', dict(全合格=True, 選定=chosen, sessions=sessions, accounts=accounts,
        固定診断述語=dict(短期往復='入口直前30秒のmid総移動>=4呼値、純移動/総移動<=0.25、非零方向の反転>=2。',
            相手中立='実入口の保存済み相手判定がNEUTRAL。反対を見送ったという意味ではない。',
            入口余地1呼値以下='判断時entry quoteと自己清算quoteから、支持±k及びSの有利側までの残り余地<=1呼値。',
            同方向近価格再参加='直前の実完結親が赤字、同方向、判断時entry quoteが直前実entryの±2呼値内。',
            自己10秒未進行='入口直前10秒の方向付きmid純移動<=0呼値。'),
        固定診断窓=[10, 30], 事後回復参考窓秒=[30, 120],
        診断述語の用途='既存実親への参考ラベルだけ。見送った後の候補/注文/損益を再生せず、これを新アルゴ成績とは呼ばない。',
        旧104prepared={session: normal['cache'][session] for session in sessions if session != extra['session']},
        旧103activity={session: activity['cache'][session] for session in sessions if session != extra['session']},
        追加同packet=addition, sourceSHA256=digest(Path(__file__)),
        予定読取=dict(旧104prepared=8, 旧103activity=8, 追加同packet=1, 対象台帳=12),
        原本読取=0, NPZ読取=0, API取得=0, 新金融再生=0,
        限界='元timeは受信時刻ではない。数量減少は約定/取消を同定できず、表示外価格は0としない。上位赤字を選んだ事後診断であり一般性の実証ではない。'))
    print('赤字12口座・90親・必要9場の事前計画保存。重い入力まだ0。', flush=True)


def loaded(item: dict, label: str) -> dict:
    """
    機能: 計画内cache及び対象台帳のbytesを一回だけ読み同指紋を確認する。
    引数: item(dict)、label(str)はpath/SHA256と入力種別。
    返り値: dictは保存packet。原本やNPZを開かない。
    """
    path = ROOT/(item['path'] if 'path' in item else item['位置'])
    key = str(path.relative_to(ROOT))
    assert key not in INPUTS and path.suffixes[-2:] == ['.pkl', '.gz']
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    assert actual == item['SHA256']
    INPUTS[key] = dict(SHA256=actual, 範囲=label, 読取回数=1)
    COUNTS[label] += 1
    return pickle.loads(gzip.decompress(payload))


def deep_arrays(item: dict, schema: dict) -> dict:
    """
    機能: 保存済みv2 NPZを一回だけ読み、十段と出来高を含む全44列を先に確認する。
    引数: item/schema(dict)は位置/指紋と実保存schema。
    返り値: dict[str,ndarray]は不変の原seq派生配列。原JSONLを再読しない。
    """
    path = ROOT/item['path']
    key = str(path.relative_to(ROOT))
    assert key not in INPUTS and path.suffix == '.npz'
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    assert actual == item['SHA256']
    with np.load(io.BytesIO(payload), allow_pickle=False) as packet:
        assert set(packet.files) == set(schema['columns']) and len(packet.files) == 44
        source = {name: packet[name] for name in packet.files}
    n, m = len(source['raw_seq']), len(source['execution_to_raw_index'])
    assert n == item['raw_rows'] and m == item['normal_execution_rows']
    for name, field in schema['columns'].items():
        shape = tuple(n if size == 'N' else m if size == 'M' else size for size in field['shape'])
        assert source[name].shape == shape and str(source[name].dtype) == field['dtype'], name
        source[name].flags.writeable = False
    assert source['bid_prices'].shape == source['bid_quantities'].shape == source['ask_prices'].shape == source['ask_quantities'].shape == (n, 10)
    INPUTS[key] = dict(SHA256=actual, 範囲='v2十段量NPZ', 読取回数=1, raw_rows=n, normal_execution_rows=m, 実保存列数=44)
    COUNTS['v2十段量NPZ'] += 1
    return source


def publications(raw: dict) -> np.ndarray:
    """
    機能: 原seq順に観測した新最大価格時計の最初行を選ぶ。
    引数: raw(dict)は保存された104の原行BBO。
    返り値: ndarray[int]は公表行。後半同時計を未来から救済しない。
    """
    times = raw['price_time_s']
    high = np.maximum.accumulate(np.where(np.isfinite(times), times, -np.inf))
    return np.flatnonzero(np.isfinite(times)&(times > np.r_[-np.inf, high[:-1]]))


def snapshot(source: dict, row: int, support: float | None) -> dict:
    """
    機能: 一原seqのBBO、十段、出来高及び固定支持価格の表示量をそのまま示す。
    引数: source(dict)、row(int)、support(float|None)は元44列と自己支持価格又は相手の無指定。
    返り値: dictは具体板。十段外や不正値は不明であり0へ補完しない。
    """
    valid = bool(source['depth_valid'][row])
    book, at_support = {}, {}
    for side in ('bid', 'ask'):
        prices, quantities = source[side+'_prices'][row], source[side+'_quantities'][row]
        eligibility = source[side+'_element_valid'][row]
        book[side] = [dict(価格=small(price), 表示数量=small(quantity), 正常=bool(ok)) for price, quantity, ok in zip(prices, quantities, eligibility, strict=True)]
        matching = eligibility & (prices == support)
        at_support[side] = float(quantities[matching].sum()) if matching.any() and valid else None
    return dict(raw_row=row, raw_seq=int(source['raw_seq'][row]), 価格代理時刻=stamp(source['price_time_s'][row]),
        bid=small(source['bid'][row]), ask=small(source['ask'][row]), Last=small(source['last'][row]),
        累計出来高=small(source['volume'][row]), 出来高代理時計=small(source['volume_time_s'][row]),
        観測出来高差=small(source['volume_delta_observed'][row]), 使用可能出来高差=small(source['volume_delta'][row]),
        使用可能=bool(source['volume_delta_usable'][row]), 深板正常=valid,
        支持価格=support, 同価格表示数量=at_support, 十段=book)


def depth_change(source: dict, prior: int, current: int) -> dict:
    """
    機能: 二原行の同じ価格だけで表示量増減を比較し、十段から出入りした価格を分ける。
    引数: source(dict)、prior/current(int)は観測済みの2行。
    返り値: dictは同価格表示量変化。補充の代理であり約定/取消の識別ではない。
    """
    answer = {}
    normal = bool(source['depth_valid'][prior] and source['depth_valid'][current]
        and source['depth_reset_reason'][current] == 0)
    for side in ('bid', 'ask'):
        left = {float(p): float(q) for p, q, ok in zip(source[side+'_prices'][prior], source[side+'_quantities'][prior], source[side+'_element_valid'][prior], strict=True) if ok}
        right = {float(p): float(q) for p, q, ok in zip(source[side+'_prices'][current], source[side+'_quantities'][current], source[side+'_element_valid'][current], strict=True) if ok}
        common = sorted(set(left)&set(right))
        changes = [dict(価格=p, 前表示=left[p], 現表示=right[p], 差=right[p]-left[p]) for p in common if left[p] != right[p]] if normal else []
        answer[side] = dict(正常比較=normal, 同価格増加=sum(max(0., value['差']) for value in changes),
            同価格減少=sum(max(0., -value['差']) for value in changes), 変化=changes,
            十段を離れた価格=sorted(set(left)-set(right)), 十段へ入った価格=sorted(set(right)-set(left)))
    return answer


def window(source: dict, record: dict, end: int, seconds: int, side: int, support: float) -> dict:
    """
    機能: 現原行までの10/30秒mid往復、同価格量変化と方向代理出来高を診断する。
    引数: source/record(dict)、end(int)、seconds/side(int)、support(float)は既観測情報。
    返り値: dictは連続特徴と正常性。未来の勝敗又は価格を使わない。
    """
    times, tick = record['time_s'], record['tick']
    current = float(times[end])
    before = np.flatnonzero((np.arange(len(times)) <= end)&(times <= current-seconds))
    if not len(before):
        return dict(既知=False, 理由='必要な過去正常行がない')
    start = int(before[-1])
    indexes = np.arange(start, end+1)
    known = bool(current-times[start] <= seconds+15 and np.all(np.diff(times[indexes]) >= 0)
        and np.all(record['quote_valid'][indexes]) and np.isfinite(record['bid'][indexes]).all()
        and np.isfinite(record['ask'][indexes]).all() and np.all(record['ask'][indexes] > record['bid'][indexes]))
    if not known:
        return dict(既知=False, 理由='時計逆行/欠測/過古な参照又は不正quote')
    mid = (record['bid'][indexes]+record['ask'][indexes])*.5
    changes = np.diff(mid)/tick
    signs = np.sign(changes[changes != 0])
    total, net = float(np.abs(changes).sum()), float((mid[-1]-mid[0])/tick)
    mapping = source['execution_to_raw_index']
    a, b = int(mapping[start]), int(mapping[end])
    raw_rows = np.arange(a+1, b+1)
    flow = dict(買い方向代理=0., 売り方向代理=0., 方向不明量=0., 使用不能観測差=0.)
    fixed = dict(bid=dict(増加=0., 減少=0., 比較回数=0, 十段外又は不明=0), ask=dict(増加=0., 減少=0., 比較回数=0, 十段外又は不明=0))
    for row in raw_rows:
        observed = source['volume_delta_observed'][row]
        usable = source['volume_delta_usable'][row] and np.isfinite(source['volume_delta'][row]) and source['volume_delta'][row] > 0
        if usable:
            volume = float(source['volume_delta'][row])
            proxy = 0
            if source['volume_time_s'][row] == source['price_time_s'][row] and source['best_price_valid'][row-1]:
                proxy = 1 if source['last'][row] >= source['ask'][row-1] else -1 if source['last'][row] <= source['bid'][row-1] else 0
            flow['買い方向代理' if proxy == 1 else '売り方向代理' if proxy == -1 else '方向不明量'] += volume
        elif np.isfinite(observed) and observed > 0:
            flow['使用不能観測差'] += float(observed)
        for direction in ('bid', 'ask'):
            prior = source[direction+'_element_valid'][row-1] & (source[direction+'_prices'][row-1] == support)
            now = source[direction+'_element_valid'][row] & (source[direction+'_prices'][row] == support)
            if source['depth_transition_valid'][row] and prior.any() and now.any():
                delta = float(source[direction+'_quantities'][row][now].sum()-source[direction+'_quantities'][row-1][prior].sum())
                fixed[direction]['増加'] += max(0., delta)
                fixed[direction]['減少'] += max(0., -delta)
                fixed[direction]['比較回数'] += 1
            else:
                fixed[direction]['十段外又は不明'] += 1
    total_volume = flow['買い方向代理']+flow['売り方向代理']+flow['方向不明量']
    flow['方向判別代理割合'] = (flow['買い方向代理']+flow['売り方向代理'])/total_volume if total_volume else None
    return dict(既知=True, 参照normal行=start, 現normal行=end, 参照raw_seq=int(source['raw_seq'][a]),
        現raw_seq=int(source['raw_seq'][b]), 実時計差秒=float(current-times[start]),
        総移動呼値=total, 純移動呼値=net, 方向付き純移動呼値=side*net,
        効率=abs(net)/total if total else 0., 非零方向反転数=int(np.sum(signs[1:] != signs[:-1])),
        最大往復幅呼値=float(np.ptp(mid)/tick), spread平均呼値=float(np.mean((record['ask'][indexes]-record['bid'][indexes])/tick)),
        spread最大呼値=float(np.max((record['ask'][indexes]-record['bid'][indexes])/tick)),
        固定支持価格の表示量変化=fixed, 観測出来高と方向代理=flow)


def peer_snapshot(packet: dict, activity: dict, symbol: str, time: float, support: float) -> dict:
    """
    機能: 自己判断よりstrict過去の最初新最大価格時計の相手原行を示す。
    引数: packet/activity(dict)、symbol(str)、time/support(float)は相手市場と当時時計。
    返り値: dictは相手気配。先後不明を当時支持に救済しない。
    """
    raw, source = packet['raw'][symbol], activity['accounts'][symbol]['source']
    pub = publications(raw)
    position = int(np.searchsorted(raw['price_time_s'][pub], time, side='left'))-1
    if position < 0:
        return dict(既知=False, 理由='strict過去の公表なし')
    row = int(pub[position])
    age = time-float(raw['price_time_s'][row])
    # ----------------------------------------
    # 数量表示そのものは正常性を添えて示し、支持資格は不明と既知を分ける。
    quote = snapshot(source, row, None)
    quote.update({'自己との代理時計差秒': age, '15秒内正常相手': bool(0 < age <= 15 and raw['bbo_valid'][row]), 'strict過去': True})
    return quote


def parent(session: str, symbol: str, ident: str, ledger: dict, packet: dict, activity: dict, trade: np.ndarray,
           previous: dict | None) -> dict:
    """
    機能: 実親の当時入口兆候、保有内MFE/MAE、費用/逆行及び返済悪化を分ける。
    引数: session/symbol/ident(str)、ledger/packet/activity(dict)、trade(ndarray)、previous(dict|None)は同場の直前実親。
    返り値: dictは全損失/黒字を残す事後診断。売買へ未来を渡さない。
    """
    record, source = packet['normal'][symbol]['record'], activity['accounts'][symbol]['source']
    pid, side, qty = int(trade[0]), int(trade[4]), int(trade[5])
    entry, exit_row, entry_price, exit_price, net = int(trade[2]), int(trade[3]), float(trade[6]), float(trade[7]), float(trade[11])
    rows = ledger['orders'][ledger['orders'][:, 2] == pid]
    new, closing = rows[rows[:, 7] == 1][0], rows[rows[:, 7] == 0][0]
    decision, exit_decision = int(new[1]), int(closing[1])
    diag = next(row for row in ledger['raw_entry_diagnostics'] if int(row['parent_id']) == pid)
    support = float(packet['cases'][ledger['entry_id']][symbol]['normal']['support_price'][decision])
    assert support == diag['episode']['support_price'] and decision == diag['decision_row'] and entry == diag['fill_row']
    for raw_field, normal in (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('bid', 'bid'), ('ask', 'ask')):
        mapping = source['execution_to_raw_index']
        np.testing.assert_array_equal(source[raw_field][mapping[[decision, entry, exit_decision, exit_row]]], record[normal][[decision, entry, exit_decision, exit_row]])
    tick, multiplier = record['tick'], 1000 if symbol == 'TOPIX' else 10
    clearance = record['bid' if side == 1 else 'ask']
    entry_quote = record['ask' if side == 1 else 'bid']
    indexes = np.arange(entry, exit_row+1)
    valid = record['quote_valid'][indexes] & np.isfinite(clearance[indexes])
    actual = indexes[valid]
    gains = side*(clearance[actual]-entry_price)
    mfe_pos, mae_pos = int(np.argmax(gains)), int(np.argmin(gains))
    fees, spread = float(trade[8]+trade[9]), float(side*(entry_price-clearance[entry])*qty*multiplier)
    move = float(side*(exit_price-clearance[entry])*qty*multiplier)
    assert abs(move-spread-fees-net) < 1e-5
    delay = float(side*(clearance[exit_decision]-exit_price)*qty*multiplier) if record['quote_valid'][exit_decision] else None
    jc = {name: i for i, name in enumerate(ledger['judgment_columns'])}
    judgments = ledger['judgments'][ledger['judgments'][:, jc['parent_id']] == pid]
    first, last = judgments[0], judgments[-1]
    assert int(first[jc['row']]) == entry
    support_line, initial_line = support-side*int(ident[-1])*tick, entry_price-side*float(ledger['initial_width'])
    planned_line = side*max(side*support_line, side*(entry_quote[decision]-side*float(ledger['initial_width'])))
    planned_space = side*(clearance[decision]-planned_line)/tick
    front = {str(seconds): window(source, record, decision, seconds, side, support) for seconds in (10, 30)}
    thirty, ten = front['30'], front['10']
    neutral = diag['episode']['peer'].get('source_direction') == 'NEUTRAL'
    repeat = previous is not None and previous['net'] < 0 and previous['side'] == side and abs(entry_quote[decision]-previous['entry_price']) <= 2*tick
    flags = dict(短期往復=bool(thirty.get('既知') and thirty['総移動呼値'] >= 4 and thirty['効率'] <= .25 and thirty['非零方向反転数'] >= 2),
        相手中立=neutral, 入口余地1呼値以下=bool(planned_space <= 1+1e-8), 同方向近価格再参加=repeat,
        自己10秒未進行=bool(ten.get('既知') and ten['方向付き純移動呼値'] <= 0))
    labels = dict(損失=net < 0, T利益追尾発動前損失=bool(net < 0 and ident.startswith('U_') and not np.any(judgments[:, jc['profit_active']])),
        初期支持境界で損失=bool(net < 0 and int(closing[8]) == 1),
        返済判断からfillへ悪化=bool(delay is not None and delay > 0),
        判断時黒字からfill赤字=bool(net < 0 and delay is not None and net+delay > 0))
    after = {}
    for seconds in (30, 120):
        candidates = np.flatnonzero((np.arange(len(clearance)) > exit_row)&(record['time_s'] <= record['time_s'][exit_row]+seconds)&record['quote_valid'])
        if len(candidates):
            favorable = side*(clearance[candidates]-entry_price)
            peak_at = int(candidates[int(np.argmax(favorable))])
            after[str(seconds)] = dict(参考のみ=True, 元建値から最良清算方向差呼値=float(favorable.max()/tick),
                元建値で費用も回収可能な気配到達=bool(favorable.max()*qty*multiplier >= fees),
                最良時刻=stamp(record['time_s'][peak_at]), 最良raw_seq=int(source['raw_seq'][mapping[peak_at]]),
                最良quote=float(clearance[peak_at]), 最悪方向差呼値=float(favorable.min()/tick))
        else:
            after[str(seconds)] = dict(参考のみ=True, 観測なし=True)
    points = {}
    other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    for name, row in (('入口判断', decision), ('新規fill', entry), ('返済判断', exit_decision), ('返済fill', exit_row)):
        raw_row = int(mapping[row])
        points[name] = dict(normal行=row, raw_seq=int(source['raw_seq'][raw_row]), 価格代理時刻=stamp(record['time_s'][row]),
            自己snapshot=snapshot(source, raw_row, support), 相手snapshot=peer_snapshot(packet, activity, other, float(record['time_s'][row]), support))
    return dict(session=session, symbol=symbol, case=ident, parent=pid, side=side, quantity=qty,
        net=net, gross=float(trade[10]), fees=fees, entry_price=entry_price, exit_price=exit_price,
        原判断lineage=small(diag['episode']), 時点=points,
        入口時判断可能=dict(直前窓=front, 保存相手状態=diag['episode']['peer'].get('source_direction'),
            支持価格=support, 支持線=support_line, 判断時想定停止線=planned_line, 判断時残り清算余地呼値=planned_space,
            直前完結親=previous['parent'] if previous else None, 直前完結親赤字=previous['net'] < 0 if previous else None,
            診断述語=flags),
        保有後にだけ判明=dict(最大順行呼値=max(0., float(gains[mfe_pos]/tick)), 最大逆行呼値=max(0., float(-gains[mae_pos]/tick)),
            最良清算方向差呼値=float(gains[mfe_pos]/tick),
            最大順行時刻=stamp(record['time_s'][actual[mfe_pos]]), 最大逆行時刻=stamp(record['time_s'][actual[mae_pos]]),
            実初期停止線=float(first[jc['stop_after']]), 実初期リスク円=float(first[jc['initial_risk_yen']]),
            利益追尾発動=bool(np.any(judgments[:, jc['profit_active']])), 停止owner=int(last[jc['line_owner']]),
            返済理由=int(closing[8]), 最終停止線=float(last[jc['stop_after']]), 分類=labels),
        正確な現金分解=dict(費用円=fees, 入口spread費用円=spread, 初回清算気配から返済まで価格変化円=move,
            純価格逆行部分円=max(0., -move), 価格改善部分円=max(0., move),
            新規判断からfillへの不利変化円=float(side*(entry_price-entry_quote[decision])*qty*multiplier),
            返済判断からfillへの不利変化円=delay,
            恒等式='net=初回清算気配から返済まで価格変化−入口spread−両側料金。返済遅れは価格変化の内数。'),
        退出後の回復参考=after, 観測範囲=dict(entry_normal_row=entry, exit_normal_row=exit_row, entry_decision_row=decision, exit_decision_row=exit_decision),
        買売時計注記='時刻は原板の価格代理時計。受信時刻ではない。入口時述語と未来診断は別欄で、未来欄を売買へ渡さない。')


def sample(parent_row: dict, packet: dict, activity: dict) -> dict:
    """
    機能: 代表の負け親から入口前と返済周辺の少数原行を抽出する。
    引数: parent_row/packet/activity(dict)は診断親及び同場素材。
    返り値: dictは少数板推移。状態を再実行したり最良価格で返済し直さない。
    """
    symbol, bounds = parent_row['symbol'], parent_row['観測範囲']
    source, record = activity['accounts'][symbol]['source'], packet['normal'][symbol]['record']
    mapping = source['execution_to_raw_index']
    decision, opening, exit_decision, closing = (bounds[key] for key in ('entry_decision_row', 'entry_normal_row', 'exit_decision_row', 'exit_normal_row'))
    before = np.flatnonzero((np.arange(len(record['time_s'])) <= decision)&(record['time_s'] >= record['time_s'][decision]-10))
    candidates = list(map(int, before))+[decision, opening, max(opening, exit_decision-1), exit_decision, closing]
    candidates = sorted(set(candidates))
    if len(candidates) > 16:
        chosen = set(candidates[index] for index in np.linspace(0, len(candidates)-1, 11).astype(int))
        chosen.update((decision, opening, exit_decision, closing))
        candidates = sorted(chosen)
    rows, prior = [], None
    for normal in candidates:
        raw = int(mapping[normal])
        value = snapshot(source, raw, parent_row['入口時判断可能']['支持価格'])
        if prior is not None:
            value['前掲原行から同価格数量変化'] = depth_change(source, prior, raw)
        rows.append(value)
        prior = raw
    return dict(case=parent_row['case'], symbol=symbol, session=parent_row['session'], parent=parent_row['parent'], net=parent_row['net'],
        表示範囲='入口前10秒から実入口及び実返済周辺の最大16原行。省略行あり。', 原板推移=rows)


def run() -> None:
    """
    機能: 固定対象の90親を具体板に対応し、同場黒字親の見送り反証も保存する。
    引数: なし。
    返り値: None。診断だけを保存し、新金融や反実仮想取引は生成しない。
    """
    plan_value = read(HERE/'赤字上位場の入力と診断範囲の事前計画_保存十段NPZ確定.json')
    assert plan_value['sourceSHA256'] == digest(Path(__file__))
    assert not (HERE/'赤字上位場の具体板と当時兆候及び反証.json').exists()
    all_parents, examples = [], []
    old_diagnostic = read(PREVIOUS/'支持幅と再参加及び利益保険の損失診断.json')
    schema = read(ROOT/'work/wave_v103/input_v2/入力schema.json')
    assert len(schema['columns']) == 44 and all(name in schema['columns'] for name in
        ('bid_prices', 'ask_prices', 'bid_quantities', 'ask_quantities', 'volume', 'volume_delta_observed', 'volume_delta_usable'))
    for session in plan_value['sessions']:
        if session in plan_value['旧104prepared']:
            packet = loaded(plan_value['旧104prepared'][session], '旧104prepared一場')
        else:
            bundle = loaded(plan_value['追加同packet'], '追加同packet一場')
            packet = bundle['peer']
        activity = dict(session=session, accounts={})
        for market in SYMBOLS:
            source = deep_arrays(plan_value['十段NPZ'][session+'|'+market], schema)
            record = packet['normal'][market]['record']
            for raw_name, normal_name in (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'), ('bid', 'bid'), ('ask', 'ask')):
                np.testing.assert_array_equal(source[raw_name][source['execution_to_raw_index']], record[normal_name])
            for name in ('raw_seq', 'price_time_s', 'volume_time_s', 'execution_to_raw_index', 'normal_execution_row',
                'price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason'):
                np.testing.assert_array_equal(source[name], packet['raw'][market][name])
            activity['accounts'][market] = dict(source=source, normal_record=record)
        assert packet['session'] == session
        for item in (value for value in plan_value['accounts'] if value['session'] == session):
            symbol, ident = item['symbol'], item['case']
            ledger = loaded(item['ledger'], '対象台帳')
            assert ledger['entry_id'] == ident.rsplit('_', 1)[0]
            outcome, previous = [], None
            for trade in sorted(ledger['trades'], key=lambda row: row[2]):
                row = parent(session, symbol, ident, ledger, packet, activity, trade, previous)
                previous = row
                outcome.append(row)
                if session in plan_value['旧104prepared']:
                    prior = [old for old in old_diagnostic['parents'][ident][symbol] if old['session'] == session and old['parent'] == row['parent']]
                    assert len(prior) == 1 and prior[0]['actual_net'] == row['net']
                    assert prior[0]['support_price'] == row['入口時判断可能']['支持価格']
                COUNTS['全実親診断'] += 1
            assert len(outcome) == item['parents'] and abs(sum(row['net'] for row in outcome)-item['net']) < 1e-5
            assert abs(sum(max(0., row['net']) for row in outcome)-item['profit']) < 1e-5
            assert abs(sum(max(0., -row['net']) for row in outcome)-item['loss']) < 1e-5
            all_parents.extend(outcome)
            worst = min(outcome, key=lambda row: row['net'])
            same = [row for row in examples if row['case'] == ident and row['symbol'] == symbol]
            if not same:
                examples.append(sample(worst, packet, activity))
            elif worst['net'] < same[0]['net']:
                examples[examples.index(same[0])] = sample(worst, packet, activity)
        print(session+' 対象全親の原seq/板/時刻と損失内訳を保存準備', flush=True)
        del packet, activity
        if session not in plan_value['旧104prepared']:
            del bundle
    assert COUNTS['全実親診断'] == 90 and COUNTS['対象台帳'] == 12
    assert COUNTS['旧104prepared一場'] == 8 and COUNTS['追加同packet一場'] == 1 and COUNTS['v2十段量NPZ'] == 18
    summary, contrasts = {}, {}
    flag_names = list(plan_value['固定診断述語'])
    for ident in IDS:
        for symbol in SYMBOLS:
            values = [row for row in all_parents if row['case'] == ident and row['symbol'] == symbol]
            losses = [row for row in values if row['net'] < 0]
            wins = [row for row in values if row['net'] > 0]
            summary[ident+'|'+symbol] = dict(全親=len(values), 損失親=len(losses), 黒字親=len(wins),
                総利益=sum(row['net'] for row in wins), 総損失=-sum(row['net'] for row in losses),
                費用=sum(row['fees'] for row in values),
                損失親spread費用=sum(row['正確な現金分解']['入口spread費用円'] for row in losses),
                損失親純価格逆行=sum(row['正確な現金分解']['純価格逆行部分円'] for row in losses),
                損失親返済fill悪化=sum(max(0., row['正確な現金分解']['返済判断からfillへの不利変化円'] or 0) for row in losses),
                事後分類={label: sum(row['保有後にだけ判明']['分類'][label] for row in values) for label in values[0]['保有後にだけ判明']['分類']},
                退出後30秒で元建値費用回収気配あり=sum(row['退出後の回復参考']['30'].get('元建値で費用も回収可能な気配到達', False) for row in losses),
                退出後120秒で元建値費用回収気配あり=sum(row['退出後の回復参考']['120'].get('元建値で費用も回収可能な気配到達', False) for row in losses))
            contrasts[ident+'|'+symbol] = {}
            for flag in flag_names:
                tagged = [row for row in values if row['入口時判断可能']['診断述語'][flag]]
                contrasts[ident+'|'+symbol][flag] = dict(該当親数=len(tagged),
                    避ける損失参考=sum(-row['net'] for row in tagged if row['net'] < 0),
                    同時に捨てる実黒字=sum(row['net'] for row in tagged if row['net'] > 0),
                    捨てる実黒字親=[dict(session=row['session'], parent=row['parent'], net=row['net']) for row in tagged if row['net'] > 0],
                    該当損失親=[dict(session=row['session'], parent=row['parent'], net=row['net']) for row in tagged if row['net'] < 0],
                    新アルゴ損益ではない=True)
    save(HERE/'赤字上位場の具体板と当時兆候及び反証.json', small(dict(全合格=True, scope='全33小会計から赤字上位3場/条件商品を機械選択。対象12口座の損失・黒字全90親。',
        選定=plan_value['選定'], 検査件数=dict(COUNTS), 入力指紋と範囲=INPUTS, sourceSHA256=digest(Path(__file__)),
        計画SHA256=digest(HERE/'赤字上位場の入力と診断範囲の事前計画_保存十段NPZ確定.json'), 要約=summary,
        当時述語の見送り対照参考=contrasts, 全親=all_parents, 少数具体板推移=examples,
        検算='各12口座のparent件数/G/L/net一致、旧84親は旧診断の元支持・netに一致。費用/spread/価格変化の恒等式も全親一致。',
        反証='退出後回復は保有を延長すれば利益になる証明ではない。入口述語に該当した元黒字親を見送る損失は別欄。再参加を実際に止めた後の状態・損益は未再生。',
        データの限界='価格時計は受信時刻ではない。同じ時刻の後半相手情報を先頭の当時支持に救済しない。十段外は不明、数量減少は約定/取消を識別不能。出来高増分の方向は最終価格代理にすぎない。',
        次の変更案=dict(短期往復='自己の同価格往復が多い候補を単独対照で見送る。元黒字見送りは対照欄。',
            相手中立='相手Nでは既知中立を通す。P支持と同入口を切分けて比較。',
            入口余地='判断時の清算余地を下限化する。次quoteの飛びは判断時に確定できない。',
            再参加='損失後の同方向同価格を新価格帯まで再準備させる。後続元黒字を失う可能性も対照に残す。',
            出口='支持破れ後の実回復と元黒字の利益延長を分け、支持kと実Sと追尾kを混同しない。単なる幅拡大は損失を増やし得る。'),
        金融再生=0, counterfactual注文生成=0, 原本読取=0, NPZ読取=18, API取得=0, goal操作=0,
        先行schema例外読取='False2件保持。初回104prepared1、二回目104prepared1/103activity1/対象ledger1を追加で読取。最終処理では旧103activity再読0。')))
    print('全90親と4代表板推移の診断完了。未来情報の売買利用及び新金融0。', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--plan', action='store_true')
    modes.add_argument('--run', action='store_true')
    args = parser.parse_args()
    plan() if args.plan else run()
