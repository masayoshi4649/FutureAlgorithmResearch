"""窓の不明境界・拒否後消費・U全ready競合を、独立した小人工接口で検査する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

import artificial


api = artificial.api
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COUNTS = {}


def check(name: str, condition: bool) -> None:
    """
    機能: 独立期待の局所条件を確認する。
    引数: name(str)、condition(bool)は検査名と独立期待。
    返り値: None。不成立でAssertionErrorを送出する。
    """
    assert condition, name
    COUNTS[name] = COUNTS.get(name, 0)+1


def raw_price_fixture(times: list[float], bid: list[float], ask: list[float]) -> dict:
    """
    機能: 価格窓だけを孤立検査する人工の観測・資格列を作る。
    引数: times/bid/ask(list[float])は同数の原行観測。
    返り値: dictは価格部品専用入力。C/R状態又は売買は生成しない。
    """
    n = len(times)
    assert len(bid) == len(ask) == n
    return dict(raw_seq=np.arange(n, dtype=np.int64)+1000, price_time_s=np.array(times, float),
        bid=np.array(bid, float), ask=np.array(ask, float), bbo_valid=np.ones(n, bool),
        qualified=np.ones(n, bool), price_reset_reason=np.zeros(n, np.uint16))


def build(raw: dict) -> dict:
    """
    機能: 原行価格部品を根の窓と数値で計算する。
    引数: raw(dict)は小人工価格列。
    返り値: dictはsourceと基準を保持するpeer価格特徴。
    """
    return api.prices.build(raw, dict(tick=1.), api.core.publications(raw), api.POLICY)


def abstract_packet(source: dict, family: str, side: int, begin: int, end: int, support: float) -> dict:
    """
    機能: U消費規則だけを孤立検査する、段階索引付きの抽象ready部品を作る。
    引数: source(dict)、family(str)、side/begin/end(int)、support(float)は部品状態。
    返り値: dictは抽象C/R packet。この組合せの市場での出現又は利益は主張しない。
    """
    n = len(source['raw_seq'])
    column, anchor = (0 if side == 1 else 1), begin-6
    ready = np.zeros((n, 2), bool)
    ready[begin:end+1, column] = True
    anchors = np.full((n, 2), -1, np.int64)
    anchors[begin:end+1, column] = source['raw_seq'][anchor]
    phases = np.zeros((n, 2), np.int8)
    phases[begin:end+1, column] = 3 if family == 'C' else 4
    event = np.zeros((1, 22))
    event[0, :6] = [begin, side if family == 'C' else -side, side, 5, 0, 3 if family == 'C' else 4]
    event[0, 6:12] = [anchor, anchor+1, -1 if family == 'C' else anchor+2, begin-1, begin, begin-1]
    event[0, 12:19] = [source['price_time_s'][anchor], support-1., support+1.,
        support if family == 'C' else support-5., 100., support if family == 'R' else support-9., 100.]
    return dict(config=dict(family=family), qualified=source['qualified'], ready=ready,
        anchor_raw_seq=anchors, phases=phases, events=event,
        event_anchor_raw_seq=np.array([source['raw_seq'][anchor]], np.int64),
        event_raw_seq=np.array([source['raw_seq'][begin]], np.int64))


def main() -> None:
    """
    機能: peer窓と候補消費の個別反例を、正式資料及び金融なしで確認する。
    引数: なし。
    返り値: None。非金融人工証跡だけを保存する。
    """
    target = HERE/'価格窓境界と拒否後消費及びU新根拠の人工検査.json'
    assert not target.exists()
    paths = [HERE/name for name in ('core.py', 'prices.py', 'api.py', 'artificial.py', 'protocol_artificial.py')]
    before = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    times = np.arange(51, dtype=float).tolist()
    constant = raw_price_fixture(times, [100.]*51, [101.]*51)
    baseline = build(constant)
    check('窓前のlatest基準を時計だけで選ぶ', baseline['windows']['10']['reference_raw_row'][45] == 35
          and baseline['windows']['3']['reference_raw_row'][45] == 42 and baseline['windows']['30']['reference_raw_row'][45] == 15)
    check('既知横ばいはneutral', baseline['windows']['10']['direction_t1'][45] == api.prices.NEUTRAL)
    for up, expected in ((True, 1), (False, -1)):
        changed = deepcopy(constant)
        sign = 1 if up else -1
        changed['bid'][45:], changed['ask'][45:] = 100.+sign, 101.+sign
        feature = build(changed)['windows']['10']
        check('1呼値境界とP10T2を分ける', feature['direction_t1'][45] == expected and feature['direction_t2'][45] == api.prices.NEUTRAL)
        changed['bid'][45:], changed['ask'][45:] = 100.+2*sign, 101.+2*sign
        feature = build(changed)['windows']['10']
        check('2呼値境界でT2支持', feature['direction_t2'][45] == expected)
    crossed = raw_price_fixture(times, [100.]*51, [103.]*51)
    crossed['bid'][45], crossed['ask'][45] = 101., 102.
    feature = build(crossed)['windows']['10']
    check('spread正常でも両変化逆符号はambiguous', feature['ambiguous_sign'][45] and not feature['ambiguous_spread'][45]
          and feature['direction_t1'][45] == api.prices.AMBIGUOUS)
    widened = deepcopy(constant)
    widened['ask'][45] = 103.
    feature = build(widened)['windows']['10']
    check('spread拡大は方向判定より優先', feature['ambiguous_spread'][45] and feature['direction_t1'][45] == api.prices.AMBIGUOUS)
    exact = deepcopy(constant)
    exact['ask'][45] = 102.
    check('spreadちょうど2tickは拡大ambiguousでない', not build(exact)['windows']['10']['ambiguous_spread'][45])
    for name, alteration in (
        ('raw price reset', lambda raw: raw['price_reset_reason'].__setitem__(40, 8)),
        ('raw quote不明', lambda raw: raw['bbo_valid'].__setitem__(40, False)),
        ('raw seq断裂', lambda raw: raw['raw_seq'].__setitem__(slice(40, None), raw['raw_seq'][40:]+1)),
        ('raw clock欠測', lambda raw: raw['price_time_s'].__setitem__(40, np.nan)),
        ('raw clock逆行', lambda raw: raw['price_time_s'].__setitem__(40, 38.5))):
        changed = deepcopy(constant)
        alteration(changed)
        feature = build(changed)['windows']['10']
        at = int(np.searchsorted(feature['source_time_s'], 45.))
        check(name+'をneutralへ救済しない', feature['direction_t1'][at] == api.prices.UNKNOWN and bool(feature['unknown_reason'][at] & 16))
    future = deepcopy(constant)
    future['price_reset_reason'][46:] = 8
    future['bid'][46:], future['ask'][46:] = 999., 1000.
    check('基準から公表源までinclusiveで未来は不参照', build(future)['windows']['10']['unknown_reason'][45] == 0)
    for location in (35, 45):
        changed = deepcopy(constant)
        changed['qualified'][location] = False
        check('a/k common資格を必須とする', build(changed)['windows']['10']['direction_t1'][45] == api.prices.UNKNOWN)
    gap = raw_price_fixture([0., 10., 26., 30.], [100.]*4, [101.]*4)
    check('公表間隔15秒超過でunknown', bool(build(gap)['windows']['30']['unknown_reason'][3] & 32))
    old = raw_price_fixture([0., 25.], [100.]*2, [101.]*2)
    check('a年齢W15より大きいとunknown', bool(build(old)['windows']['3']['unknown_reason'][1] & 8))
    same = raw_price_fixture([0., 1., 1., .5, 2.], [100.]*5, [101.]*5)
    public = api.core.publications(same)
    check('新max最初だけで同clock後半と逆行は不採用', np.array_equal(public['rows'], [0, 1, 4]))
    own = dict(price_time_s=np.array([1., 1.1, 2., 17., 17.0001]))
    selected = api.core.peer_rows(own, same, public)
    check('strictpast同時計を採用しない', np.array_equal(selected['rows'], [0, 1, 1, 4, 4]))
    check('freshness15秒境界', np.array_equal(selected['fresh'], [True, True, True, True, False]))

    # ----------------------------------------
    # 抽象readyの組合せは消費・競合規則だけを検査し、C/R市場仮説は別実状態人工で検査する。
    payload, execution = artificial.activity_fixture('C', False, .5)
    account = payload['accounts']['TOPIX']
    restored = api.core.restore_account(account, execution['TOPIX'])
    raw = restored['raw']
    toy = dict(packets={})
    toy['packets']['C1'] = abstract_packet(account['source'], 'C', 1, 40, 50, 107.)
    toy['packets']['R1'] = abstract_packet(account['source'], 'R', 1, 42, 50, 103.)
    candidates = api.core.union_candidates(toy, raw)
    check('U消費済根拠はsupport採択に混ぜない', [value['row'] for value in candidates] == [40, 42]
          and candidates[1]['support_price'] == 103. and len(candidates[1]['self_lineages']) == 1
          and candidates[1]['self_lineages'][0]['family'] == 'R' and len(candidates[1]['competition_ready_episodes']) == 2)
    for side in (1, -1):
        toy['packets']['C1'] = abstract_packet(account['source'], 'C', side, 40, 50, 104.)
        toy['packets']['R1'] = abstract_packet(account['source'], 'R', side, 40, 50, 106.)
        candidates = api.core.union_candidates(toy, raw)
        check('U同方向新根拠2つは1pulse両消費', len(candidates) == 1 and len(candidates[0]['episodes']) == 2)
        check('U近い新根拠support買max売min', candidates[0]['support_price'] == (106. if side == 1 else 104.))
    toy['packets']['C1'] = abstract_packet(account['source'], 'C', 1, 40, 43, 104.)
    toy['packets']['R1'] = abstract_packet(account['source'], 'R', -1, 42, 50, 106.)
    candidates = api.core.union_candidates(toy, raw)
    check('既消費readyも反対競合を保つ', [value['row'] for value in candidates] == [40, 44]
          and candidates[1]['side'] == -1 and candidates[1]['self_lineages'][0]['family'] == 'R')

    # ----------------------------------------
    # 共通初回原行でgateに落ちたepisodeを、後でpeerが支持しても復活させない。
    toy['packets']['C1'] = abstract_packet(account['source'], 'C', 1, 40, 50, 101.)
    toy['packets']['R1']['ready'][:] = False
    candidates = api.core.union_candidates(toy, raw)
    peer = api.core.restore_account(payload['accounts']['NK225'], execution['NK225'])
    public = api.core.publications(peer['raw'])
    features = api.prices.build(peer['raw'], peer['item'], public, api.POLICY)
    selection = api.core.peer_rows(raw, peer['raw'], public)
    filtered = api.filter_case(dict(id='U_P10', family='U', gate='P10'), candidates, raw,
        peer['raw'], features, selection, restored['normal'])
    check('拒否候補は後の同episode支持で復活しない', len(candidates) == 1 and candidates[0]['row'] == 40
          and not filtered['raw']['event'].any() and not filtered['candidates'][0]['accepted']
          and features['windows']['10']['direction_t1'][int(selection['public_indexes'][42])] == api.prices.UP)
    neutral_gate = api.gate_decision(candidates[0], 'N10', raw, peer['raw'], features, selection)
    check('N中立採用は支持ありと呼ばない', neutral_gate['accepted'] and neutral_gate['status'] == 'NEUTRAL' and neutral_gate['mode'] == 'NOT_OPPOSE')
    check('OWNはpeer使用と支持説明を持たない', api.gate_decision(candidates[0], 'OWN', raw, peer['raw'], features, selection)['peer'] is None)

    ending = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    check('開始終端source一致', beginning_equal(before, ending))
    proof = dict(全合格=True, 人工専用=True, 検査件数=COUNTS, source_SHA256=ending,
        新104正式準備=0, 新金融=0, 正式活動cache読取=0, 原本読取=0, NPZ読取=0, API取得=0,
        限界='窓境界は価格部品人工、U消費は抽象ready組合せ人工。全C/R仮説そのものは別の103実状態人工を使用。収益又は正式活動を検査していない。')
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=COUNTS, SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


def beginning_equal(before: dict, after: dict) -> bool:
    """
    機能: 小さいsource指紋の開始終端同一性を確認する。
    引数: before/after(dict)は指紋一覧。
    返り値: boolは完全一致。
    """
    return before == after


if __name__ == '__main__':
    main()
