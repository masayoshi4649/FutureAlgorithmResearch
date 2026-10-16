"""独立C/R状態と厳密過去接続を、損益を使わない人工原行で検査する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np

import adapter
import artificial
import states


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COUNTS = {}


def check(name: str, condition: bool) -> None:
    """
    機能: 人工の必要条件を確認し、満たした項目の件数を記録する。
    引数: name(str)は日本語の確認名、condition(bool)は独立した期待条件。
    返り値: None。不成立ならAssertionErrorを出し、合格証跡を保存しない。
    """
    assert condition, name
    COUNTS[name] = COUNTS.get(name, 0) + 1


def raw_fixture(rows: list[dict], reflect: bool = False) -> dict:
    """
    機能: 行ごとの別観測を持つ完全10段の人工入力を作る。
    引数: rows(list[dict])は価格・数量・出来高の局所変更、reflect(bool)は売買反射。
    返り値: dict。全103資格配列を持つ人工素材。原板ファイルを読まない。
    """
    n = len(rows)
    raw = dict(raw_seq=np.arange(n, dtype=np.int64) + 9007199254740993,
        price_time_s=np.arange(n, dtype=np.float64),
        last=np.zeros(n), bid=np.zeros(n), ask=np.zeros(n), bid_qty=np.zeros(n), ask_qty=np.zeros(n),
        volume_delta=np.zeros(n), volume=np.zeros(n), volume_time_s=np.arange(n, dtype=np.float64),
        bid_prices=np.zeros((n, 10)), ask_prices=np.zeros((n, 10)),
        bid_quantities=np.zeros((n, 10)), ask_quantities=np.zeros((n, 10)))
    for name in ('price_time_valid', 'in_session', 'price_row_valid', 'best_price_valid',
                 'best_quantity_valid', 'depth_valid', 'depth_transition_valid', 'volume_delta_usable'):
        raw[name] = np.ones(n, bool)
    for name in ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason'):
        raw[name] = np.zeros(n, np.uint16)
    raw['depth_transition_valid'][0] = raw['volume_delta_usable'][0] = False
    raw['volume_delta'][0] = np.nan
    for row, changes in enumerate(rows):
        bid, ask = changes.get('bid', 100.), changes.get('ask', 101.)
        bidq, askq = changes.get('bidq', 100.), changes.get('askq', 100.)
        last = changes.get('last', (bid + ask) / 2.)
        bp, ap = bid - np.arange(10), ask + np.arange(10)
        bq, aq = np.full(10, bidq), np.full(10, askq)
        for price, quantity in changes.get('bid_at', {}).items():
            bq[bp == price] = quantity
        for price, quantity in changes.get('ask_at', {}).items():
            aq[ap == price] = quantity
        if reflect:
            bid, ask, bidq, askq, last = 201. - ask, 201. - bid, askq, bidq, 201. - last
            bp, ap, bq, aq = 201. - ap, 201. - bp, aq, bq
        raw['bid'][row], raw['ask'][row], raw['last'][row] = bid, ask, last
        raw['bid_qty'][row], raw['ask_qty'][row] = bidq, askq
        raw['bid_prices'][row], raw['ask_prices'][row] = bp, ap
        raw['bid_quantities'][row], raw['ask_quantities'][row] = bq, aq
        if row:
            raw['volume_delta'][row] = changes.get('delta', 0.)
        for name in ('price_time_s', 'volume_time_s', 'depth_valid', 'depth_transition_valid',
                     'lp_reset_reason', 'volume_delta_usable'):
            if name in changes:
                raw[name][row] = changes[name]
    raw['volume'][:] = np.cumsum(np.nan_to_num(raw['volume_delta']))
    return raw


def basic_rows(family: str, strength: float = 1.) -> list[dict]:
    """
    機能: 価格移動行に大出来高を置いても、確認は後の別行になる経路を作る。
    引数: family(str)はC/R、strength(float)は活動強度。
    返り値: list[dict]。最初の正常基準は行1、C完了は行4、Rは行5。
    """
    rows = [{}, {}, dict(askq=40., delta=100. * strength, last=101.)]
    if family == 'C':
        rows += [dict(bid=101., ask=102., bidq=60., delta=999., last=102.),
                 dict(bid=101., ask=102., bidq=60., delta=100. * strength, last=102.)]
    else:
        rows += [dict(askq=90.), dict(bid=99., ask=100., askq=60., delta=999., last=99.),
                 dict(bid=99., ask=100., askq=60., delta=100. * strength, last=99.)]
    return rows


def run_checked(raw: dict, config: dict) -> dict:
    """
    機能: 現sourceのPython/JITを同じ人工入力で比較し、入力不変も確認する。
    引数: raw/config(dict)は人工103原行と単一条件。
    返り値: dict。JIT状態。比較に金融結果は用いない。
    """
    before = {name: value.copy() for name, value in raw.items()}
    compiled = states.run(raw, dict(tick=1.), config)
    python = states.run(raw, dict(tick=1.), config, python=True)
    for name in ('qualified', 'volume_direction_proxy', 'ready', 'anchor_raw_seq', 'phases',
                 'events', 'event_raw_seq', 'event_anchor_raw_seq'):
        check('PythonとJITの状態及び原行ログ一致', np.array_equal(compiled[name], python[name], equal_nan=True))
    check('人工入力を書き換えない', all(np.array_equal(raw[name], value, equal_nan=True) for name, value in before.items()))
    return compiled


def config(family: str, strength: float = 1., supply: bool = True, volume: bool = True) -> dict:
    """
    機能: 独立C/Rの人工設定を作る。
    引数: family(str)、strength(float)、supply/volume(bool)。
    返り値: dict。主の採択又は金融最適化を変更する設定ではない。
    """
    return dict(family=family, strength=strength, use_supply=supply, use_volume=volume)


def state_cases() -> list[dict]:
    """
    機能: 全14単一入口の両方向、固定分母、数量待機及び独立寿命を検査する。
    引数: なし。
    返り値: list[dict]。段階原行の人工例。正式活動件数や損益は計算しない。
    """
    catalog = adapter.module('103人工だけの条件草案', ROOT / 'work/wave_v103/catalog.py').catalog()
    examples = []
    for value in catalog:
        if value['kind'] != 'single':
            continue
        family = value['family']
        for reflect in (False, True):
            raw = raw_fixture(basic_rows(family, value['strength']), reflect)
            packet = run_checked(raw, value)
            column = int((family == 'R') != reflect)
            end = 4 if family == 'C' else 5
            check('全14単一条件の買売準備成立', bool(packet['ready'][end, column]))
            check('移動原行では完了しない', not packet['ready'][end - 1].any())
            rows = packet['events'][(packet['events'][:, 1] == (-1 if reflect else 1)) & (packet['events'][:, 3] == 5)][0]
            stages = [int(rows[index]) for index in ((6, 7, 9, 10) if family == 'C' else (6, 7, 8, 9, 10))]
            check('各段階は厳密に別原行', all(a < b for a, b in zip(stages, stages[1:])))
            check('大整数raw_seqを丸めず保持', int(packet['anchor_raw_seq'][end, column]) == int(raw['raw_seq'][1]))
            examples.append(dict(条件=value['id'], 反射=reflect, 方向=1 if column == 0 else -1, 段階原行=stages))

    # ----------------------------------------
    # 数量不足中は価格維持を要求し、移動開始前の出来高を遡及加算しない。
    for family in ('C', 'R'):
        for reflect in (False, True):
            rows = basic_rows(family)
            move = 3 if family == 'C' else 4
            rows[move]['bidq' if family == 'C' else 'askq'] = 20.
            rows[move + 1]['bidq' if family == 'C' else 'askq'] = 20.
            moved = deepcopy(rows[move + 1])
            moved['bidq' if family == 'C' else 'askq'] = 60.
            moved['delta'] = 999.
            rows.extend([moved, dict(moved, delta=0.), dict(moved, delta=100.)])
            packet = run_checked(raw_fixture(rows, reflect), config(family))
            column = int((family == 'R') != reflect)
            check('数量不足で待ち価格維持回復後に移動', packet['phases'][move, column] == (1 if family == 'C' else 2)
                  and packet['phases'][move + 2, column] == (2 if family == 'C' else 3))
            check('待機中と移動行出来高の遡及禁止', not packet['ready'][move + 3, column] and packet['ready'][move + 4, column])
            broken = basic_rows(family)
            broken[move]['bidq' if family == 'C' else 'askq'] = 20.
            broken[move + 1] = {}
            bad = run_checked(raw_fixture(broken, reflect), config(family))
            check('数量待機中の価格破れで再基準', bad['anchor_raw_seq'][-1, column] == bad['raw_seq'][-1]
                  and np.any((bad['events'][:, 3] == 8) & (bad['events'][:, 4] == 4)))

    # ----------------------------------------
    # Rの支持分母を元の同側へ固定し、同量反復を回復と呼ばない。
    for reflect in (False, True):
        rows = basic_rows('R')
        for row in (0, 1, 2, 3):
            rows[row]['bidq'] = 300.
        rows[4]['askq'] = rows[5]['askq'] = 60.
        rows.extend([dict(rows[5], askq=160., delta=0.), dict(rows[5], askq=160., delta=100.)])
        packet = run_checked(raw_fixture(rows, reflect), config('R'))
        column = 0 if reflect else 1
        check('R支持分母は開始同側数量', not packet['ready'][5, column] and not packet['ready'][6, column] and packet['ready'][7, column])
        repeats = [{}, {}, dict(askq=150.), dict(askq=100., last=101., delta=100.),
                   dict(askq=100.), dict(askq=100.), dict(askq=110.),
                   dict(bid=99., ask=100., askq=60.), dict(bid=99., ask=100., askq=60., last=99., delta=100.)]
        packet = run_checked(raw_fixture(repeats, reflect), config('R'))
        check('R同量反復では回復しない', packet['phases'][5, column] == 1 and packet['phases'][6, column] == 2 and packet['ready'][8, column])

    independent = raw_fixture(basic_rows('C'))
    c = run_checked(independent, config('C'))
    r = run_checked(independent, config('R'))
    check('R元方向到達でC基準をリセットしない', c['anchor_raw_seq'][-1, 0] == independent['raw_seq'][1]
          and r['anchor_raw_seq'][-1, 1] == independent['raw_seq'][3] and c['ready'][-1, 0])
    bad = deepcopy(independent)
    bad['lp_reset_reason'][3] = 1
    for family in ('C', 'R'):
        packet = run_checked(bad, config(family))
        check('情報不明は両方向とも破棄', (packet['anchor_raw_seq'][3] == -1).all()
              and (packet['anchor_raw_seq'][4] == bad['raw_seq'][4]).all())
    expired = raw_fixture(basic_rows('C'))
    expired['price_time_s'][3:] += 120.
    expired['volume_time_s'][3:] += 120.
    packet = run_checked(expired, config('C'))
    check('価格時計120秒で独立再基準', packet['anchor_raw_seq'][3, 0] == expired['raw_seq'][3])
    long_raw = raw_fixture([{} for _ in range(5003)])
    long_raw['price_time_s'] /= 1000.
    long_raw['volume_time_s'] /= 1000.
    packet = run_checked(long_raw, config('C'))
    check('原行5000で独立再基準', packet['anchor_raw_seq'][5001, 0] == long_raw['raw_seq'][5001])
    return examples


def book_proxy_cases() -> None:
    """
    機能: 固定価格の既知0と不明、一意方向及び単独代理の資格拒否を検査する。
    引数: なし。
    返り値: None。真の方向別約定量を観測したとの主張はしない。
    """
    prices, quantities = np.arange(100., 90., -1), np.full(10, 10.)
    for implementation in (states.fixed_quantity, states.fixed_quantity.py_func):
        check('競争的空領域だけ既知0', implementation(prices, quantities, 101., True, True) == 0.)
        check('遠端外を数量0にしない', np.isnan(implementation(prices, quantities, 90., True, True)))
        check('範囲内未表示価格は既知0', implementation(prices, quantities, 99.5, True, True) == 0.)
        check('不完全10段は不明', np.isnan(implementation(prices, quantities, 99., True, False)))
        check('売側反射対称のlookup', implementation(201. - prices, quantities, 100., False, True) == 0.
              and np.isnan(implementation(201. - prices, quantities, 111., False, True)))
    rows = [{}, {}, dict(bidq=40., askq=40., last=101., delta=100.)]
    raw = raw_fixture(rows)
    proxy = states.volume_direction_proxy(raw)
    check('重なる価格帯も代理は一方向だけ', proxy[2] == 1)
    c = run_checked(raw, config('C'))
    check('同一出来高を両意図へ加算しない', c['phases'][2, 0] == 1 and c['phases'][2, 1] == 0)
    mutations = [('last', 2, 100.5), ('last', 2, np.nan), ('volume_time_s', 2, 1.),
        ('raw_seq', 2, int(raw['raw_seq'][2]) + 2), ('lp_reset_reason', 2, 1),
        ('price_reset_reason', 2, 1), ('depth_reset_reason', 2, 1),
        ('volume_reset_reason', 2, 1), ('depth_transition_valid', 2, False),
        ('best_price_valid', 1, False), ('price_time_s', 2, .5),
        ('lp_reset_reason', 1, 1), ('volume_delta_usable', 2, False)]
    for name, row, value in mutations:
        changed = deepcopy(raw)
        changed[name][row] = value
        check('代理単独でも曖昧又は断裂を拒否', states.volume_direction_proxy(changed)[2] == 0)


def packet(raw: dict, family: str, ready: np.ndarray, anchors: np.ndarray | None = None) -> dict:
    """
    機能: peer接続と消費だけを分離して検査する既知人工状態を作る。
    引数: raw(dict)、family(str)、ready(ndarray[bool]N×2)、anchors(ndarray[int64]|None)。
    返り値: dict。有限時点の人工準備。状態段階の成立検査とは分けて記録する。
    """
    return dict(config=dict(family=family), ready=ready.copy(), qualified=np.ones(len(ready), bool),
                anchor_raw_seq=np.full(ready.shape, 11, np.int64) if anchors is None else anchors.copy())


def connection_cases() -> None:
    """
    機能: 厳密過去の最初公表源と、自動単一の消費済を含む方向競合を検査する。
    引数: なし。
    返り値: None。相手の同時計後半や未来状態へpulseを移動しない。
    """
    own_raw, peer_raw = raw_fixture([{}] * 6), raw_fixture([{}] * 6)
    own_raw['price_time_s'][:] = [10., 10.1, 11., 11.1, 20., 40.]
    peer_raw['price_time_s'][:] = [9., 10., 10., 9.5, 11., 21.]
    full = np.zeros((6, 2), bool)
    full[:, 0] = True
    own, peer = packet(own_raw, 'C', full), packet(peer_raw, 'C', full)
    peer['qualified'][1] = False
    anchors = np.arange(6, dtype=np.int64) + 11
    own['anchor_raw_seq'][:, 0] = anchors
    out = states.pulses(own, peer, own_raw, peer_raw)
    check('同時計源は厳密過去だけ', out['peer_rows'][0] == 0 and out['event'][0] == 1)
    check('最初新最大行は後半同時計で置換しない', out['peer_rows'][1] == 1 and out['event'][1] == 0 and out['peer_rows'][2] == 1)
    check('逆行行を並替えて公表しない', np.array_equal(states.publication(peer_raw)['rows'], [0, 1, 4, 5]))
    check('正常相手公表の次自己行で判断', out['event'][3] == 1 and out['peer_rows'][3] == 4)
    check('相手15秒超は拒否', out['peer_rows'][5] == 5 and out['event'][5] == 0)
    same = deepcopy(own)
    same['anchor_raw_seq'][:, 0] = 11
    single = states.pulses(same, peer, own_raw, peer_raw)
    check('同episodeは一度のみ消費', np.count_nonzero(single['event']) == 1)
    check('相手なし部品は独立に自己消費', np.count_nonzero(states.pulses(same, None, own_raw, None, False)['event']) == 1)

    # ----------------------------------------
    # 消費済C買の反対票は、新R売を抑える。旧Cが失効後だけ新Rを判断する。
    union_raw = raw_fixture([{}] * 4)
    union_raw['price_time_s'][:] = [10., 11., 12., 13.]
    peer_raw = raw_fixture([{}] * 4)
    peer_raw['price_time_s'][:] = [9., 10., 11., 12.]
    c_ready = np.array([[1, 0], [1, 0], [1, 0], [0, 0]], bool)
    r_ready = np.array([[0, 0], [0, 1], [0, 1], [0, 1]], bool)
    c_peer = np.tile([True, False], (4, 1))
    r_peer = np.tile([False, True], (4, 1))
    components = dict(C=dict(own=packet(union_raw, 'C', c_ready), peer=packet(peer_raw, 'C', c_peer), peer_raw=peer_raw),
                      R=dict(own=packet(union_raw, 'R', r_ready), peer=packet(peer_raw, 'R', r_peer), peer_raw=peer_raw))
    union = states.union_pulses(components, union_raw)
    check('消費済C買と新R売の競合を保留', np.array_equal(union['event'], [1, 0, 0, -1]))
    components['R']['own']['ready'][0] = [False, True]
    held = states.union_pulses(components, union_raw)
    check('反対同時保留は未消費を維持', np.array_equal(held['event'], [0, 0, 0, -1]))
    both = deepcopy(components)
    both['C']['own']['ready'][:] = [True, False]
    both['R']['own']['ready'][:] = [True, False]
    both['R']['peer']['ready'][:] = [True, False]
    both['R']['own']['ready'][0] = False
    combined = states.union_pulses(both, union_raw)
    check('同方向消費済と未消費は1pulse', np.array_equal(combined['event'], [1, 1, 0, 0]))
    check('同方向全episodeを一度消費', len(combined['decisions'][1]['episodes']) == 2)

    # ----------------------------------------
    # 未来状態変更とappendでも、当時の接頭判断及び公表源を変えない。
    original = states.union_pulses(both, union_raw)
    altered = deepcopy(both)
    altered['R']['peer']['ready'][3] = [False, True]
    altered['C']['own']['ready'][3] = [False, True]
    changed = states.union_pulses(altered, union_raw)
    check('未来peer又は自己の変更で接頭不変', np.array_equal(original['event'][:3], changed['event'][:3]))
    invalid = deepcopy(union_raw)
    invalid['price_time_s'][2] = np.nan
    invalid['price_time_valid'][2] = False
    check('自己時計不明はpeer未来検索へ進めない', states.pulses(both['C']['own'], both['C']['peer'], invalid, peer_raw)['peer_rows'][2] == -1)


def portfolio_cases() -> list[dict]:
    """
    機能: 実注文の1枚診断と、全3配分の実枚数・料金・予約上限を検査する。
    引数: なし。
    返り値: list[dict]。人工実数量接続例。利益額又は配分の優劣を判定しない。
    """
    previous, examples = adapter.reference_config(), []
    for symbol in ('TOPIX', 'NK225'):
        record, old_signal, opening = artificial.fixture(symbol, 1)
        event = np.zeros(len(record['time_s']), np.int8)
        event[330] = 1
        one_config = adapter.raw_config(previous)
        one_signal = adapter.signal_for_raw(record, old_signal, event, np.ones(len(event), bool), np.zeros(len(event), bool), opening, one_config)
        metadata = [dict(row=330, episode=('C', 1, 123), peer_row=329)]
        one = adapter.play_artificial(record, one_signal, one_config, metadata)
        diagnostic = one['raw_entry_diagnostics'][0]
        check('raw入口診断は実1枚と別行fill', diagnostic['quantity'] == 1 and diagnostic['decision_row'] == 330 and diagnostic['fill_row'] == 331)
        check('raw入口診断は当時episodeを保持', diagnostic['episode'] == metadata[0])
        choices = ((2, 8), (5, 5), (8, 2)) if symbol == 'TOPIX' else ((4, 16), (10, 10), (16, 4))
        for quantities in choices:
            signals = dict(C=one_signal, R=deepcopy(one_signal))
            output = adapter.portfolio_artificial(record, signals, previous, quantities)
            unit = 41.8 if symbol == 'TOPIX' else 11.
            fees = 0.
            for family, quantity in zip(('C', 'R'), quantities):
                leg = output['legs'][family]
                check('配分は各腿の実注文枚数', leg['orders'][0, 5] == quantity and leg['trades'][0, 5] == quantity
                      and leg['raw_entry_diagnostics'][0]['quantity'] == quantity)
                check('配分の旧SとD及び30分出口保持', leg['trend_parent_diagnostics'][0, 6] == one['trend_parent_diagnostics'][0, 6]
                      and leg['trend_parent_diagnostics'][0, 7] == one['trend_parent_diagnostics'][0, 7]
                      and leg['orders'][1, 1] == 2131 and leg['orders'][1, 0] == 2132)
                check('実注文単位の手数料切捨て', np.all(leg['orders'][:, 9] == np.floor(unit * quantity + 1e-8)))
                fees += 2 * np.floor(unit * quantity + 1e-8)
            check('保有と予約の合計片方向上限', np.all(output['target_trace'][:, :4] <= sum(quantities)))
            check('配分料金は実注文から合算', output['fees'] == fees)
            examples.append(dict(商品=symbol, C枚数=quantities[0], R枚数=quantities[1], 片方向上限=sum(quantities), 実注文料金合計=fees))
    return examples


def main() -> None:
    """
    機能: 現状態sourceと新実枚数接続の人工検査を実行し、現指紋を証跡へ結ぶ。
    引数: なし。
    返り値: None。既存の証跡は保持し、正式金融・全raw・APIを実行しない。
    """
    target = HERE / '独立状態と厳密過去接続及び実配分の人工検査.json'
    assert not target.exists(), '既存人工証跡を上書きしません'
    refs = [Path(__file__), HERE / 'states.py', HERE / 'adapter.py', HERE / 'artificial.py',
            ROOT / 'work/wave_v102/engine.py', ROOT / 'work/wave_v102/catalog.py',
            ROOT / 'work/wave_v103/catalog.py', ROOT / 'work/wave_v103/input/入力schema.json']
    refs += [ROOT / 'work/wave_v103' / name for name in ('数値設計草案.json', '数値設計補足01.json',
            '数値設計補足02.json', '数値設計補足03.json', '数値設計補足04.json', '数値設計補足05.json')]
    beginning = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    examples = state_cases()
    book_proxy_cases()
    connection_cases()
    portfolio = portfolio_cases()
    ending = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    check('検査開始終端の参照source一致', beginning == ending)
    proof = dict(全合格=True, 人工専用=True, 検査件数=COUNTS, 単一状態例=examples, 配分実数量例=portfolio,
        正式金融再生=0, 全raw読取=0, API取得=0, 実注文=0, 旧金融本体変更=0,
        開始終端SHA一致=True, 開始SHA256=beginning, SHA256=ending,
        限界='人工状態の因果性と段階接続だけ。実原板の活動及び接頭不変、収益性、受信の真の先後は未検証。出来高符号は最終価格と直前公開BBOの一意代理で、方向別真約定量ではない。102本体の初期数量欄と実注文欄を区別。旧人工証跡とその原source copyは保持。')
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=COUNTS, 単一状態例数=len(examples), 配分実数量例数=len(portfolio), 正式金融再生=0,
                         証跡SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        stamp = time.strftime('%Y%m%d_%H%M%S')
        folder = HERE / ('人工False_' + stamp)
        folder.mkdir(exist_ok=False)
        hashes = {}
        for name in ('state_artificial.py', 'states.py', 'adapter.py'):
            content = (HERE / name).read_bytes()
            (folder / name).write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        failure = dict(全合格=False, 人工専用=True, 例外=str(error), 完了確認件数=COUNTS,
                       原sourceSHA256=hashes, traceback=traceback.format_exc(), 正式金融再生=0)
        (folder / 'False.json').write_text(json.dumps(failure, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
