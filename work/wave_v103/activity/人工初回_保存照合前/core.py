"""損益を使わず、確定入口の状態・発火・同一原行の正常列対応を保存する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
STAGE_NAMES = ('anchor', 'prepared', 'recovery', 'moved', 'ready', 'first_price_move')


def module(name: str, path: Path) -> object:
    """
    機能: 確定済みの条件又は所有領域内の状態複製を読取接続する。
    引数: name(str)は固有名、path(Path)はソース位置。
    返り値: objectはモジュール。旧結果・金融モジュールを読み込まない。
    """
    if name in sys.modules:
        return sys.modules[name]
    specification = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(specification)
    sys.modules[name] = result
    specification.loader.exec_module(result)
    return result


def digest(path: Path) -> str:
    """
    機能: 小さい直接資料又は新cacheの指紋を求める。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。生原本又は旧金融結果のhashには使わない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    """
    機能: UTF-8の入力由来・設計・活動診断を読む。
    引数: path(Path)はJSON資料。
    返り値: dictは内容。損益結果には使用しない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 所有活動領域へ新しい日本語JSONを保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。既存証跡を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def catalog() -> list[dict]:
    """
    機能: 根の確定19条件を読むだけで取得する。
    引数: なし。
    返り値: list[dict]は14single・union1・portfolio3・旧対照1。
    """
    values = module('103活動だけの19条件', HERE.parent/'catalog.py').catalog()
    assert len(values) == 19 and sum(value['kind'] == 'single' for value in values) == 14
    assert sum(value['kind'] == 'union' for value in values) == 1
    assert sum(value['kind'] == 'portfolio' for value in values) == 3
    assert sum(value['kind'] == 'previous' for value in values) == 1
    return values


def states() -> object:
    """
    機能: engine確定実装と同一bytesの複製を所有領域で接続する。
    引数: なし。
    返り値: objectは状態機械。JIT cacheも活動領域内へ書く。
    """
    assert digest(HERE/'states_snapshot.py') == digest(HERE.parent/'engine/states.py')
    return module('103活動の不変状態複製', HERE/'states_snapshot.py')


def schema() -> dict:
    """
    機能: 活動cacheと数え方を、金融結果を見る前に明示する。
    引数: なし。
    返り値: dictはAPI・route・資格・時計及び集計の定義。
    """
    return dict(version=1, API='data.load_session(session:str,verify:bool=True)->dict',
        保存='cache/{session}.pkl.gz。gzip mtime=0、pickle protocol=5。所有sourceが生成したcacheだけを読む。',
        payload=['schema_version', 'session', 'case_routes', 'accounts', 'summary'],
        accounts=dict(item='v2口座metadataのcopy', source='原seq、価格代理時計、出来高時計、normal双方向map、四reset理由、共通qualified',
            normal_record='旧執行5列と完全同一のseq/time_s/price/bid/ask及びstart/end/limit/tick。v2のみから構成。',
            packets='states.run返り値を保存。C_OWN/R_OWNはC1/R1のlocalを参照、12local実計算。',
            case_to_packet='14singleから12localへの対応。', pulses='14single及びU_C1R1のraw event・decisions・相手源・原行lineage・直接normal投影'),
        条件数=19, single数=14, local種類数=12, union数=1, portfolio数=3,
        旧対照='OLD_G0のroute及びsummaryはnull。旧金融結果は読まない。',
        配分='P20/P50/P80はC1/R1 pulseを二腿として参照する。合計は腿pulse数であり、実注文数又は枚数ではない。',
        受付='価格代理時計が[start+300,limit-300)内。旧出口と同じ開始以上・終了未満。',
        対応='normal_execution_row>=0の同一原行へだけ写す。非対応pulseを将来正常行へ移動しない。受付外の消費も復活させない。',
        local集計='方向別phase原行数、ready原行数とreadyセル数、基準episode数、ready episode数、ready立上り数、各段階event数。',
        pulse集計='買売別の全raw発火・normal同一行対応・非対応・受付内外・受付内normal対応。保有・返済優先・cooldown・fillは未判定。',
        決定由来='原判断row/raw_seq/価格代理時計/normal_row及び当時自己・相手episodeと各段階row/raw_seq/時計。未来の段階を混ぜない。',
        発火0='未活動。勝ち・利益又は安定性とは扱わない。',
        限界='CurrentPriceTimeは価格代理時計。ReceivedAt欠測により二市場の実受信先後は不明。表示減少は約定・取消を同定できず、出来高方向も代理。活動の存在だけを確認し、収益を証明しない。')


def routes(values: list[dict]) -> dict:
    """
    機能: 19条件をlocal/pulse既cacheへ対応させ、金融数量を変更しない。
    引数: values(list[dict])は根の19条件。
    返り値: dictは単一、union、二腿route又は旧対象外null。
    """
    result = {}
    for config in values:
        ident, kind = config['id'], config['kind']
        if kind == 'previous':
            result[ident] = None
        elif kind == 'portfolio':
            result[ident] = dict(kind=kind, legs=['C1', 'R1'], allocations=deepcopy(config['allocations']),
                                per_direction_caps=deepcopy(config['per_direction_caps']))
        elif kind == 'union':
            result[ident] = dict(kind=kind, pulse=ident, packets=['C1', 'R1'])
        else:
            packet = config['family']+'1' if ident.endswith('_OWN') else ident
            result[ident] = dict(kind=kind, pulse=ident, packet=packet, use_peer=bool(config['use_peer']))
    assert len(result) == 19
    return result


def state_summary(packet: dict) -> dict:
    """
    機能: local状態の原行・準備・独立基準を方向別に数える。
    引数: packet(dict)はstates.runの返り値。
    返り値: dictは金融を含まない件数。準備喪失後の回復を別基準と混同しない。
    """
    result = dict(raw_rows=len(packet['raw_seq']), qualified_rows=int(packet['qualified'].sum()),
                  ready_rows=int(packet['ready'].any(axis=1).sum()), ready_cells=int(packet['ready'].sum()), sides={})
    for column, side in enumerate((1, -1)):
        phases, ready, anchors = packet['phases'][:, column], packet['ready'][:, column], packet['anchor_raw_seq'][:, column]
        transition = ready.copy()
        if len(ready) > 1:
            transition[1:] &= ~ready[:-1] | (anchors[1:] != anchors[:-1])
        events = packet['events'][packet['events'][:, 2] == side]
        result['sides'][str(side)] = dict(phase_rows={str(int(phase)): int((phases == phase).sum()) for phase in np.unique(phases)},
            ready_rows=int(ready.sum()), episodes=len(np.unique(anchors[anchors >= 0])),
            ready_episodes=len(np.unique(anchors[ready])), ready_transitions=int(transition.sum()),
            event_codes={str(code): int((events[:, 3] == code).sum()) for code in range(1, 10)},
            reset_reasons={str(reason): int(((events[:, 3] == 8) & (events[:, 4] == reason)).sum()) for reason in range(1, 6)})
    result['episodes'] = sum(value['episodes'] for value in result['sides'].values())
    result['ready_episodes'] = sum(value['ready_episodes'] for value in result['sides'].values())
    return result


def stage_lookup(packet: dict) -> dict:
    """
    機能: 同じepisodeの当時ログを、整数seqを丸めず索引化する。
    引数: packet(dict)は状態と疎なevent。
    返り値: dict[(int,int),list[int]]は基準seq・方向からevent位置への索引。
    """
    lookup = {}
    for index, anchor in enumerate(packet['event_anchor_raw_seq']):
        side = int(packet['events'][index, 2])
        lookup.setdefault((int(anchor), side), []).append(index)
    return lookup


def lineage(packet: dict, raw: dict, row: int, side: int, lookup: dict) -> dict:
    """
    機能: 判断行以下の自己又は相手の段階原行を因果的に記録する。
    引数: packet/raw(dict)、row/side(int)、lookup(dict)は当時の対象とepisode索引。
    返り値: dictは現在原行と既知段階。未来eventを検索結果へ入れない。
    """
    column = 0 if side == 1 else 1
    anchor = int(packet['anchor_raw_seq'][row, column])
    indexes = lookup.get((anchor, side), [])
    chosen = [index for index in indexes if packet['events'][index, 0] <= row]
    assert chosen, '準備episodeの過去ログがありません'
    index = chosen[-1]
    event = packet['events'][index]
    stages = {}
    for offset, name in enumerate(STAGE_NAMES, 6):
        source = int(event[offset])
        stages[name] = None if source < 0 else dict(row=source, raw_seq=int(raw['raw_seq'][source]),
                                                   price_time_s=float(raw['price_time_s'][source]))
        assert source <= row
    return dict(row=row, raw_seq=int(raw['raw_seq'][row]), price_time_s=float(raw['price_time_s'][row]),
        volume_time_s=float(raw['volume_time_s'][row]), anchor_raw_seq=anchor,
        phase=int(packet['phases'][row, column]), ready=bool(packet['ready'][row, column]),
        last_event_index=index, stages=stages)


def project(pulse: dict, raw: dict, item: dict) -> dict:
    """
    機能: raw発火を同一原行のnormalへ直接投影し、受付内外・非対応を分ける。
    引数: pulse/raw/item(dict)は当時発火、v2原行、期間metadata。
    返り値: dictは元発火とnormal発火・判断対応・買売別集計。未来正常行を探さない。
    """
    n, mapping = len(raw['raw_seq']), raw['execution_to_raw_index']
    event = pulse['event']
    assert event.shape == (n,) and event.dtype == np.int8 and np.isin(event, (-1, 0, 1)).all()
    assert np.array_equal(raw['normal_execution_row'][mapping], np.arange(len(mapping)))
    assert np.array_equal(np.flatnonzero(raw['normal_execution_row'] >= 0), mapping)
    emitted = np.flatnonzero(event)
    decisions = pulse['decisions']
    assert [value['row'] for value in decisions] == emitted.tolist()
    normal_event = event[mapping].copy()
    accepted = (raw['price_time_valid'] & np.isfinite(raw['price_time_s'])
        & (raw['price_time_s'] >= item['start'] + 300.) & (raw['price_time_s'] < item['limit'] - 300.))
    records = []
    for old in decisions:
        row = int(old['row'])
        value = deepcopy(old)
        assert value['raw_seq'] == int(raw['raw_seq'][row]) and value['side'] == int(event[row])
        normal_row = int(raw['normal_execution_row'][row])
        value.update(price_time_s=float(raw['price_time_s'][row]),
                     normal_row=None if normal_row < 0 else normal_row, in_reception=bool(accepted[row]))
        records.append(value)
    summary = dict(raw_pulses=len(emitted), normal_pulses=int(np.count_nonzero(normal_event)), sides={})
    for side in (1, -1):
        mask = event == side
        normal = raw['normal_execution_row'] >= 0
        summary['sides'][str(side)] = dict(raw_pulses=int(mask.sum()), normal_pulses=int((mask & normal).sum()),
            non_normal_pulses=int((mask & ~normal).sum()), reception_pulses=int((mask & accepted).sum()),
            outside_reception_pulses=int((mask & ~accepted).sum()),
            reception_normal_pulses=int((mask & accepted & normal).sum()),
            reception_non_normal_pulses=int((mask & accepted & ~normal).sum()))
    for field in ('non_normal_pulses', 'reception_pulses', 'outside_reception_pulses',
                  'reception_normal_pulses', 'reception_non_normal_pulses'):
        summary[field] = sum(value[field] for value in summary['sides'].values())
    assert summary['raw_pulses'] == summary['normal_pulses'] + summary['non_normal_pulses']
    assert summary['raw_pulses'] == summary['reception_pulses'] + summary['outside_reception_pulses']
    return dict(pulse, decisions=records, normal_event=normal_event,
                normal_decisions=[value for value in records if value['normal_row'] is not None], summary=summary)


def annotate(pulse: dict, own_raw: dict, peer_raw: dict, own_packets: dict, peer_packets: dict) -> None:
    """
    機能: 発火に当時の自己・相手episode段階及び厳密過去時計を付す。
    引数: pulse/own_raw/peer_raw/own_packets/peer_packets(dict)は発火と状態。
    返り値: None。pulseの新しいdecisionsだけへlineageを付ける。
    """
    own_lookup = {family: stage_lookup(packet) for family, packet in own_packets.items()}
    peer_lookup = {family: stage_lookup(packet) for family, packet in peer_packets.items()}
    for decision in pulse['decisions']:
        row, side = decision['row'], decision['side']
        episodes = decision.get('episodes', [decision.get('episode')])
        peers = decision.get('peer_rows', [decision.get('peer_row', -1)])
        history = []
        for episode, peer_row in zip(episodes, peers, strict=True):
            family = episode[0]
            own = lineage(own_packets[family], own_raw, row, side, own_lookup[family])
            assert own['anchor_raw_seq'] == int(episode[2])
            peer = None if peer_row < 0 else lineage(peer_packets[family], peer_raw, int(peer_row), side, peer_lookup[family])
            if peer is not None:
                assert peer['price_time_s'] < own['price_time_s'] and own['price_time_s'] - peer['price_time_s'] <= 15.
            history.append(dict(episode=episode, own=own, peer=peer))
        decision['lineage'] = history


def build_session(session: str, raw: dict, items: dict, values: list[dict] | None = None, python: bool = False) -> dict:
    """
    機能: 2口座を一度の状態計算から19route・pulse・可用性cacheへ構成する。
    引数: session(str)、raw/items(dict[symbol,dict])、values(list[dict]|None)、python(bool)は人工比較用。
    返り値: dictは一場の状態及び活動。保有・出口・料金・損益を計算しない。
    """
    assert set(raw) == set(items) == set(SYMBOLS)
    values = catalog() if values is None else values
    engine, route = states(), routes(values)
    single = [config for config in values if config['kind'] == 'single']
    local = {config['id']: config for config in single if not config['id'].endswith('_OWN')}
    assert len(local) == 12
    packets = {symbol: {ident: engine.run(raw[symbol], items[symbol], config, python=python)
                       for ident, config in local.items()} for symbol in SYMBOLS}
    result = dict(schema_version=1, session=session, case_routes=route, accounts={}, summary={})
    for symbol in SYMBOLS:
        other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        current, opposite, item = raw[symbol], raw[other], items[symbol]
        pulse_cache, summaries = {}, {}
        local_summaries = {ident: state_summary(packet) for ident, packet in packets[symbol].items()}
        for config in single:
            ident, family = config['id'], config['family']
            packet_id = route[ident]['packet']
            own, peer = packets[symbol][packet_id], packets[other][packet_id]
            pulse = engine.pulses(own, peer, current, opposite, use_peer=config['use_peer'])
            projected = project(pulse, current, item)
            annotate(projected, current, opposite, {family: own}, {family: peer})
            pulse_cache[ident] = projected
            summaries[ident] = dict(kind='single', packet=packet_id, local=local_summaries[packet_id], pulse=projected['summary'])
        components = {family: dict(own=packets[symbol][family+'1'], peer=packets[other][family+'1'], peer_raw=opposite) for family in ('C', 'R')}
        union = project(engine.union_pulses(components, current), current, item)
        annotate(union, current, opposite, {family: packets[symbol][family+'1'] for family in ('C', 'R')},
                 {family: packets[other][family+'1'] for family in ('C', 'R')})
        pulse_cache['U_C1R1'] = union
        summaries['U_C1R1'] = dict(kind='union', local={ident: local_summaries[ident] for ident in ('C1', 'R1')}, pulse=union['summary'])
        for config in values:
            if config['kind'] == 'previous':
                summaries[config['id']] = None
            elif config['kind'] == 'portfolio':
                summaries[config['id']] = dict(kind='portfolio', allocations=config['allocations'][symbol],
                    legs={ident: summaries[ident] for ident in ('C1', 'R1')},
                    leg_pulses=sum(pulse_cache[ident]['summary']['raw_pulses'] for ident in ('C1', 'R1')),
                    reception_normal_leg_pulses=sum(pulse_cache[ident]['summary']['reception_normal_pulses'] for ident in ('C1', 'R1')))
        mapping = current['execution_to_raw_index']
        normal_record = {destination: current[source][mapping].copy() for source, destination in
            (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'), ('bid', 'bid'), ('ask', 'ask'))}
        normal_record.update({name: item[name] for name in ('start', 'end', 'limit', 'tick')})
        normal_record.update(symbol=symbol, session=session)
        source = {name: current[name] for name in ('raw_seq', 'price_time_s', 'volume_time_s', 'normal_execution_row',
            'execution_to_raw_index', 'price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason')}
        source['qualified'] = packets[symbol]['C1']['qualified']
        result['accounts'][symbol] = dict(item=deepcopy(item), source=source, normal_record=normal_record,
            packets=packets[symbol], case_to_packet={value['id']: route[value['id']]['packet'] for value in single},
            pulses=pulse_cache, summaries=summaries)
        result['summary'][symbol] = summaries
    return result
