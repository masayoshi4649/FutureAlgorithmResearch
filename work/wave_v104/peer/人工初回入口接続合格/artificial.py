"""人工活動cacheで、19入口・因果peer窓・同一行投影・支持根拠を検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

import numpy as np

import api


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COUNTS = {}
_specification = importlib.util.spec_from_file_location('104人工fixture専用103状態複製', HERE/'state_fixture_source.py')
STATE = importlib.util.module_from_spec(_specification)
sys.modules[_specification.name] = STATE
_specification.loader.exec_module(STATE)


def check(name: str, condition: bool) -> None:
    """
    機能: 人工期待を確認し、日本語の件数を記録する。
    引数: name(str)、condition(bool)は検査項目と成立条件。
    返り値: None。不成立でAssertionErrorを送出する。
    """
    assert condition, name
    COUNTS[name] = COUNTS.get(name, 0)+1


def digest(path: Path) -> str:
    """
    機能: 小さい人工source又は設計指紋だけを計算する。
    引数: path(Path)はsource又は人工証跡。
    返り値: strはSHA256。正式cache・原本・NPZを読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config(family: str) -> dict:
    """
    機能: 変更しない自己C1/R1状態の人工設定を作る。
    引数: family(str)はC/R。
    返り値: dictは確定103の自己数値。104金融の条件を選ばない。
    """
    return dict(id=family+'1', family=family, strength=1., use_supply=True, use_volume=True)


def raw_fixture(family: str, reflect: bool, tick: float, strong: bool = False) -> dict:
    """
    機能: 40秒の既知履歴とC/R段階を持つ完全10段の人工原行を作る。
    引数: family(str)、reflect/strong(bool)、tick(float)は思想・反射・peer2tick・呼値。
    返り値: dictは103自己状態を実計算する小人工。保存原本を読まない。
    """
    rows = [{} for _ in range(40)] + [dict(askq=40., delta=100., last=101.)]
    distance = 2. if strong else 1.
    if family == 'C':
        movement = dict(bid=100.+distance, ask=101.+distance, bidq=60., delta=999., last=101.+distance)
        rows += [movement, dict(movement, delta=100.)]
    else:
        movement = dict(bid=100.-distance, ask=101.-distance, askq=60., delta=999., last=100.-distance)
        rows += [dict(askq=90.), movement, dict(movement, delta=100.)]
    rows += [dict(rows[-1], delta=0.) for _ in range(10)]
    n = len(rows)
    raw = dict(raw_seq=np.arange(n, dtype=np.int64)+9007199254740993,
        price_time_s=400.+np.arange(n, dtype=float), last=np.zeros(n), bid=np.zeros(n), ask=np.zeros(n),
        bid_qty=np.zeros(n), ask_qty=np.zeros(n), volume_delta=np.zeros(n), volume=np.zeros(n),
        bid_prices=np.zeros((n, 10)), ask_prices=np.zeros((n, 10)),
        bid_quantities=np.zeros((n, 10)), ask_quantities=np.zeros((n, 10)))
    for name in ('price_time_valid', 'in_session', 'price_row_valid', 'best_price_valid',
                 'best_quantity_valid', 'depth_valid', 'depth_transition_valid', 'volume_delta_usable'):
        raw[name] = np.ones(n, bool)
    for name in ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason'):
        raw[name] = np.zeros(n, np.uint16)
        raw[name][0] = 1
    raw['depth_transition_valid'][0] = raw['volume_delta_usable'][0] = False
    raw['volume_delta'][0] = np.nan
    for row, change in enumerate(rows):
        bid, ask = change.get('bid', 100.), change.get('ask', 101.)
        bidq, askq = change.get('bidq', 100.), change.get('askq', 100.)
        last = change.get('last', (bid+ask)/2.)
        bp, ap = bid-np.arange(10), ask+np.arange(10)
        bq, aq = np.full(10, bidq), np.full(10, askq)
        if reflect:
            bid, ask, bidq, askq, last = 201.-ask, 201.-bid, askq, bidq, 201.-last
            bp, ap, bq, aq = 201.-ap, 201.-bp, aq, bq
        raw['bid'][row], raw['ask'][row], raw['last'][row] = tick*bid, tick*ask, tick*last
        raw['bid_qty'][row], raw['ask_qty'][row] = bidq, askq
        raw['bid_prices'][row], raw['ask_prices'][row] = tick*bp, tick*ap
        raw['bid_quantities'][row], raw['ask_quantities'][row] = bq, aq
        if row:
            raw['volume_delta'][row] = change.get('delta', 0.)
    raw['volume'] = np.cumsum(np.nan_to_num(raw['volume_delta']))
    raw['volume_time_s'] = raw['price_time_s'].copy()
    return raw


def activity_fixture(family: str, reflect: bool, tick: float) -> tuple[dict, dict]:
    """
    機能: 103状態を人工で実計算し、2商品活動payloadと旧quote資格recordを作る。
    引数: family(str)、reflect(bool)、tick(float)は人工入口と対称性。
    返り値: tuple[dict,dict]は104 APIへの人工だけの入力。新金融は再生しない。
    """
    accounts, execution = {}, {}
    for symbol in api.core.SYMBOLS:
        raw = raw_fixture(family, reflect, tick, strong=symbol == 'NK225')
        if symbol == 'NK225':
            raw['price_time_s'] -= .1
            raw['volume_time_s'] -= .1
        packets = {part+'1': STATE.run(raw, dict(tick=tick), config(part), python=True) for part in ('C', 'R')}
        pulses = {part+'_OWN': STATE.pulses(packets[part+'1'], None, raw, None, use_peer=False) for part in ('C', 'R')}
        qualified = STATE.row_qualified(raw)
        n = len(raw['raw_seq'])
        source = {name: raw[name] for name in ('raw_seq', 'price_time_s', 'volume_time_s',
            'price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason')}
        source.update(qualified=qualified, normal_execution_row=np.arange(n, dtype=np.int32), execution_to_raw_index=np.arange(n, dtype=np.int64))
        record = dict(symbol=symbol, session='人工', seq=raw['raw_seq'].copy(), time_s=raw['price_time_s'].copy(),
            price=raw['last'].copy(), bid=raw['bid'].copy(), ask=raw['ask'].copy(), start=0., end=1100., limit=1000., tick=tick)
        item = dict(symbol=symbol, session='人工', raw_rows=n, normal_execution_rows=n, start=0., end=1100., limit=1000., tick=tick)
        accounts[symbol] = dict(item=item, source=source, normal_record=record, packets=packets, pulses=pulses)
        execution[symbol] = dict(record, quote_valid=np.ones(n, bool), price_valid=np.ones(n, bool))
    return dict(schema_version=1, session='人工', accounts=accounts), execution


def compare(left: object, right: object) -> bool:
    """
    機能: 原入力又は接口を、数値配列のNaNも含め再帰比較する。
    引数: left/right(object)は辞書・列・数値配列等。
    返り値: boolは値と型の一致。
    """
    if isinstance(left, np.ndarray):
        return isinstance(right, np.ndarray) and left.dtype == right.dtype and np.array_equal(left, right, equal_nan=True)
    if isinstance(left, dict):
        return isinstance(right, dict) and set(left) == set(right) and all(compare(value, right[name]) for name, value in left.items())
    if isinstance(left, (tuple, list)):
        return isinstance(right, type(left)) and len(left) == len(right) and all(compare(a, b) for a, b in zip(left, right))
    return left == right


def cut(payload: dict, execution: dict, length: int) -> tuple[dict, dict]:
    """
    機能: 人工cacheと旧recordの同じ原行接頭を切り、未来決定を保持しない。
    引数: payload/execution(dict)、length(int)は保持原行数。
    返り値: tuple[dict,dict]は接頭。将来正常行へ対応を移さない。
    """
    result, records = deepcopy(payload), deepcopy(execution)
    for symbol, account in result['accounts'].items():
        for name, value in list(account['source'].items()):
            account['source'][name] = value[:length].copy()
        account['source']['execution_to_raw_index'] = account['source']['execution_to_raw_index'][account['source']['execution_to_raw_index'] < length]
        for record in (account['normal_record'], records[symbol]):
            for name, value in list(record.items()):
                if isinstance(value, np.ndarray):
                    record[name] = value[:length].copy()
        for packet in account['packets'].values():
            for name in ('qualified', 'volume_direction_proxy', 'ready', 'anchor_raw_seq', 'phases', 'raw_seq', 'price_time_s'):
                packet[name] = packet[name][:length].copy()
            keep = packet['events'][:, 0] < length
            for name in ('events', 'event_raw_seq', 'event_anchor_raw_seq'):
                packet[name] = packet[name][keep].copy()
        for pulse in account['pulses'].values():
            for name in ('event', 'peer_rows'):
                pulse[name] = pulse[name][:length].copy()
            pulse['decisions'] = [value for value in pulse['decisions'] if value['row'] < length]
    return result, records


def main() -> None:
    """
    機能: 根確定19入口を、小人工原行と結果独立の期待で検査する。
    引数: なし。
    返り値: None。正式活動cache・原本・NPZ・API・金融を読まない。
    """
    target = HERE/'19入口の同一候補と価格窓及び支持lineageの人工検査.json'
    assert not target.exists()
    references = [HERE/name for name in ('core.py', 'prices.py', 'api.py', 'artificial.py', 'state_fixture_source.py')]
    references += [HERE.parent/'catalog.py', HERE.parent/'数値設計案.json']
    before = {str(path.relative_to(ROOT)): digest(path) for path in references}
    check('人工103状態複製は不変sourceと同一', digest(HERE/'state_fixture_source.py') == digest(ROOT/'work/wave_v103/activity/states_snapshot.py'))
    for family in ('C', 'R'):
        for reflect in (False, True):
            for tick in (.5, 10.):
                payload, execution = activity_fixture(family, reflect, tick)
                original = deepcopy((payload, execution))
                full = api.prepared_session(payload, execution)
                check('根19入口数と同一行BBO接続', len(full['cases']) == 19 and compare((payload, execution), original))
                ident = family+'_OWN'
                decisions = full['cases'][ident]['TOPIX']['raw']['decisions']
                check('実103自己状態から人工OWN発火あり', len(decisions) == 1)
                row, side = decisions[0]['row'], decisions[0]['side']
                expected_side = (1 if family == 'C' else -1)*(-1 if reflect else 1)
                check('売買及び呼値反射の自己入口方向', side == expected_side)
                for gate in api.core.GATES:
                    value = full['cases'][family+'_'+gate]['TOPIX']
                    check('同じ初回候補で全8gate判定', len(value['candidates']) == 1 and value['candidates'][0]['row'] == row)
                    check('相手2呼値の進行は全8gate採用', int(value['raw']['event'][row]) == side)
                    check('rawとnormalの原seqが一致', value['normal']['decisions'][0]['raw_seq'] == int(payload['accounts']['TOPIX']['source']['raw_seq'][row]))
                    if gate != 'OWN':
                        peer = value['normal']['decisions'][0]['peer']
                        check('peerは厳密過去15秒内', peer['price_time_s'] < value['normal']['decisions'][0]['price_time_s'] and 0 < peer['age_seconds'] <= 15.)
                packet = payload['accounts']['TOPIX']['packets'][family+'1']
                index = decisions[0]['self_lineages'][0]['event_index']
                expected_support = float(packet['events'][index, 15 if family == 'C' else 17])
                check('C固定列15とR支持列17を使う', decisions[0]['support_price'] == expected_support)
                length = row+1
                short_payload, short_exec = cut(payload, execution, length)
                short = api.prepared_session(short_payload, short_exec)
                changed_payload, changed_exec = deepcopy(payload), deepcopy(execution)
                for symbol in api.core.SYMBOLS:
                    changed_payload['accounts'][symbol]['source']['price_time_s'][length:] = np.nan
                    changed_exec[symbol]['time_s'][length:] = np.nan
                    changed_payload['accounts'][symbol]['normal_record']['time_s'][length:] = np.nan
                    changed_payload['accounts'][symbol]['normal_record']['bid'][length:] *= 2.
                    changed_payload['accounts'][symbol]['normal_record']['ask'][length:] *= 2.
                    changed_exec[symbol]['bid'][length:] *= 2.
                    changed_exec[symbol]['ask'][length:] *= 2.
                changed = api.prepared_session(changed_payload, changed_exec)
                for ident, pairs in full['cases'].items():
                    for symbol in api.core.SYMBOLS:
                        left = pairs[symbol]
                        for name in ('event', 'support_price'):
                            check('全19入口の接頭切断未来変更不変', compare(left['raw'][name][:length], short['cases'][ident][symbol]['raw'][name])
                                  and compare(left['raw'][name][:length], changed['cases'][ident][symbol]['raw'][name][:length]))
                        earlier = [decision for decision in left['raw']['decisions'] if decision['row'] < length]
                        check('当時selfpeer lineageの接頭不変', compare(earlier, short['cases'][ident][symbol]['raw']['decisions'])
                              and compare(earlier, [decision for decision in changed['cases'][ident][symbol]['raw']['decisions'] if decision['row'] < length]))

                # ----------------------------------------
                # 同一raw行にnormalがなければ、不明として保持して将来へ新規を移さない。
                missing_payload, missing_exec = deepcopy(payload), deepcopy(execution)
                account = missing_payload['accounts']['TOPIX']
                mapping = np.delete(account['source']['execution_to_raw_index'], row)
                account['source']['execution_to_raw_index'] = mapping
                account['source']['normal_execution_row'][:] = -1
                account['source']['normal_execution_row'][mapping] = np.arange(len(mapping))
                for record in (account['normal_record'], missing_exec['TOPIX']):
                    for name, value in list(record.items()):
                        if isinstance(value, np.ndarray):
                            record[name] = np.delete(value, row)
                missing = api.prepared_session(missing_payload, missing_exec)
                value = missing['cases'][family+'_OWN']['TOPIX']
                check('非normal raw候補を未来正常行へ移さない', value['raw']['event'][row] == side and not value['normal']['event'].any()
                      and np.isnan(missing['raw']['TOPIX']['bid'][row]) and value['raw']['decisions'][0]['normal_row'] is None)

    # ----------------------------------------
    # neutral/unknown/曖昧は数値が同じでも資格と方向を別に検査する。
    delta_bid, delta_ask = np.array([1., -1., 0., 1., .5]), np.array([1., -1., 0., -1., .5])
    known, ambiguous = np.ones(5, bool), np.array([False, False, False, True, False])
    check('支持反対中立曖昧は区別', np.array_equal(api.prices.classify(delta_bid, delta_ask, known, ambiguous, 1), [1, -1, 0, 2, 0]))
    known[2] = False
    check('不明を中立へ救済しない', api.prices.classify(delta_bid, delta_ask, known, ambiguous, 1)[2] == 3)

    payload, execution = activity_fixture('C', False, .5)
    account = payload['accounts']['NK225']
    account['source']['qualified'][20] = False
    account['source']['volume_reset_reason'][20] = 4
    restored = api.core.restore_account(account, execution['NK225'])
    check('量不明でも正常出口quote資格は維持', restored['normal']['quote_valid'][20] and not restored['normal']['entry_quality'][20])
    current = api.core.publications(restored['raw'])
    features = api.prices.build(restored['raw'], account['item'], current, api.POLICY)
    check('途中量のみ不明を価格反転へ代用しない', features['windows']['30']['unknown_reason'][42] == 0)
    execution['NK225']['quote_valid'][20] = False
    restored = api.core.restore_account(account, execution['NK225'])
    features = api.prices.build(restored['raw'], account['item'], api.core.publications(restored['raw']), api.POLICY)
    check('旧quote不明の中間行はwindow未知', (features['windows']['30']['unknown_reason'][42] & 16) != 0)
    refused = False
    invalid = deepcopy(execution['TOPIX'])
    invalid.pop('quote_valid')
    invalid['valid'] = np.ones(len(invalid['seq']), bool)
    try:
        api.core.restore_account(payload['accounts']['TOPIX'], invalid)
    except AssertionError:
        refused = True
    check('旧validへのfallback禁止', refused)

    ending = {str(path.relative_to(ROOT)): digest(path) for path in references}
    check('開始終端source一致', before == ending)
    proof = dict(全合格=True, 人工専用=True, 検査件数=COUNTS, 開始終端source一致=True, source_SHA256=ending,
        正式全32prepared生成=0, 新金融=0, 原本読取=0, NPZ読取=0, 正式活動cache読取=0, API取得=0, 実注文=0,
        限界='小人工の入口接口と因果窓のみ。103自己状態複製は人工源を進めるためだけであり、104productionは保存packetを再利用。正式活動や収益は未確認。')
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=COUNTS, SHA256=digest(target)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        index = 1
        while (HERE/f'人工False_{index:05d}').exists():
            index += 1
        folder = HERE/f'人工False_{index:05d}'
        folder.mkdir()
        for name in ('core.py', 'prices.py', 'api.py', 'artificial.py'):
            (folder/name).write_bytes((HERE/name).read_bytes())
        (folder/'False.json').write_text(json.dumps(dict(全合格=False, 内容=str(error), traceback=traceback.format_exc(),
            検査件数=COUNTS, 正式活動cache読取=0, 新金融=0), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise
