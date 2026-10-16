"""人工原行だけで、活動cacheと同一行normal投影の未来不変を確認する。"""

from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import subprocess
import sys
import traceback

import numpy as np

import core
import data


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COUNTS = {}


def check(name: str, condition: bool) -> None:
    """
    機能: 人工の必要条件を確認して検査件数を数える。
    引数: name(str)、condition(bool)は項目名と独立期待。
    返り値: None。不成立でAssertionErrorを送出する。
    """
    assert condition, name
    COUNTS[name] = COUNTS.get(name, 0) + 1


def fixture(family: str, reflect: bool = False, peer: bool = False) -> dict:
    """
    機能: 完全10段・原行時計・normal双方向mapの小人工原行を作る。
    引数: family(str)はC/R、reflect/peer(bool)は売買反射及び相手時計0.1秒先行。
    返り値: dictは人工だけの103状態入力。保存原本を読まない。
    """
    rows = [{}, {}, dict(askq=40., delta=100., last=101.)]
    if family == 'C':
        rows += [dict(bid=101., ask=102., bidq=60., delta=999., last=102.),
                 dict(bid=101., ask=102., bidq=60., delta=100., last=102.)]
    else:
        rows += [dict(askq=90.), dict(bid=99., ask=100., askq=60., delta=999., last=99.),
                 dict(bid=99., ask=100., askq=60., delta=100., last=99.)]
    rows += [dict(rows[-1], delta=0.) for _ in range(3)]
    n = len(rows)
    raw = dict(raw_seq=np.arange(n, dtype=np.int64)+9007199254740993,
        price_time_s=400.+np.arange(n, dtype=float)-(.1 if peer else 0.),
        last=np.zeros(n), bid=np.zeros(n), ask=np.zeros(n), bid_qty=np.zeros(n), ask_qty=np.zeros(n),
        volume_delta=np.zeros(n), volume=np.zeros(n),
        bid_prices=np.zeros((n, 10)), ask_prices=np.zeros((n, 10)),
        bid_quantities=np.zeros((n, 10)), ask_quantities=np.zeros((n, 10)),
        normal_execution_row=np.arange(n, dtype=np.int32), execution_to_raw_index=np.arange(n, dtype=np.int64))
    raw['volume_time_s'] = raw['price_time_s'].copy()
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
        last = changes.get('last', (bid+ask)/2.)
        bp, ap, bq, aq = bid-np.arange(10), ask+np.arange(10), np.full(10, bidq), np.full(10, askq)
        if reflect:
            bid, ask, bidq, askq, last = 201.-ask, 201.-bid, askq, bidq, 201.-last
            bp, ap, bq, aq = 201.-ap, 201.-bp, aq, bq
        raw['bid'][row], raw['ask'][row], raw['last'][row] = bid, ask, last
        raw['bid_qty'][row], raw['ask_qty'][row] = bidq, askq
        raw['bid_prices'][row], raw['ask_prices'][row] = bp, ap
        raw['bid_quantities'][row], raw['ask_quantities'][row] = bq, aq
        if row:
            raw['volume_delta'][row] = changes.get('delta', 0.)
    raw['volume'][:] = np.cumsum(np.nan_to_num(raw['volume_delta']))
    return raw


def prefix(raw: dict, length: int) -> dict:
    """
    機能: 人工原行の接頭だけを残し、normal対応も同じ接頭内へ切る。
    引数: raw(dict)、length(int)は入力と保持原行数。
    返り値: dictは新人工接頭。将来正常行への参照を残さない。
    """
    result = {name: value[:length].copy() for name, value in raw.items() if name != 'execution_to_raw_index'}
    result['execution_to_raw_index'] = raw['execution_to_raw_index'][raw['execution_to_raw_index'] < length].copy()
    return result


def compare(left: object, right: object) -> bool:
    """
    機能: 共有配列を含む人工cacheを辞書・列・数値配列ごとに比較する。
    引数: left/right(object)は比較対象。
    返り値: boolは値の一致。NaNを同位置の未知として比較する。
    """
    if isinstance(left, np.ndarray):
        return isinstance(right, np.ndarray) and left.dtype == right.dtype and np.array_equal(left, right, equal_nan=True)
    if isinstance(left, dict):
        return isinstance(right, dict) and set(left) == set(right) and all(compare(value, right[name]) for name, value in left.items())
    if isinstance(left, (list, tuple)):
        return isinstance(right, type(left)) and len(left) == len(right) and all(compare(a, b) for a, b in zip(left, right))
    return left == right


def main() -> None:
    """
    機能: 人工だけで19route、発火非移動、厳密過去lineage、接頭及び保存を検査する。
    引数: なし。
    返り値: None。正式64入力・金融・APIを呼ばず人工証跡を保存する。
    """
    target = HERE/'人工発火の正常列直接投影と未来不変.json'
    assert not target.exists()
    paths = [HERE/name for name in ('core.py', 'data.py', 'prepare.py', 'artificial.py', 'states_snapshot.py')]
    paths += [HERE.parent/'catalog.py', HERE.parent/'engine/states.py']
    beginning = {str(path.relative_to(ROOT)): core.digest(path) for path in paths}
    schema_path = HERE/'活動cache仕様.json'
    if not schema_path.exists():
        core.save(schema_path, core.schema())
    values = core.catalog()
    for family in ('C', 'R'):
        for reflected in (False, True):
            raw = {symbol: fixture(family, reflected, peer=symbol == 'NK225') for symbol in core.SYMBOLS}
            original = deepcopy(raw)
            items = {symbol: dict(symbol=symbol, session='人工', tick=1., start=0., end=1100., limit=1000.) for symbol in core.SYMBOLS}
            full = core.build_session('人工', raw, items, values)
            python = core.build_session('人工', raw, items, values, python=True)
            check('全12local及び14singleとunionのPythonJIT一致', compare(full, python))
            check('活動summaryのJSON保存とcache深一致', full['summary'] == json.loads(json.dumps(full['summary'], ensure_ascii=False, allow_nan=False)))
            check('原人工入力不変', compare(raw, original))
            check('19routeと旧対象外null', len(full['case_routes']) == 19 and full['case_routes']['OLD_G0'] is None)
            for symbol in core.SYMBOLS:
                account = full['accounts'][symbol]
                check('14singleのlocal12再利用', len(account['packets']) == 12 and len(account['case_to_packet']) == 14
                      and account['case_to_packet']['C_OWN'] == 'C1' and account['case_to_packet']['R_OWN'] == 'R1')
                check('15pulseとportfolio3の既cacheroute', len(account['pulses']) == 15
                      and all(full['case_routes'][ident]['legs'] == ['C1', 'R1'] for ident in ('P20', 'P50', 'P80')))
                for ident, pulse in account['pulses'].items():
                    for decision in pulse['decisions']:
                        check('判断seqの大整数保持', decision['raw_seq'] == int(raw[symbol]['raw_seq'][decision['row']]))
                        check('当該normal原行だけ対応', decision['normal_row'] == decision['row'])
                        for record in decision['lineage']:
                            check('自己段階に未来原行なし', all(stage is None or stage['row'] <= decision['row'] for stage in record['own']['stages'].values()))
                            if record['peer'] is not None:
                                check('相手は厳密過去かつ15秒内', 0 < record['own']['price_time_s']-record['peer']['price_time_s'] <= 15.)
                own = account['pulses'][family+'1']
                if symbol == 'TOPIX':
                    check('人工ではsamefamily paired実発火あり', own['summary']['raw_pulses'] == 1)
            length = 5 if family == 'C' else 6
            short_raw = {symbol: prefix(value, length) for symbol, value in raw.items()}
            short = core.build_session('人工', short_raw, items, values)
            changed = deepcopy(raw)
            for value in changed.values():
                value['depth_transition_valid'][length:] = False
                value['volume_delta_usable'][length:] = False
                value['last'][length:] *= 2.
                value['bid_quantities'][length:] *= 10.
            future = core.build_session('人工', changed, items, values)
            for symbol in core.SYMBOLS:
                for ident, packet in full['accounts'][symbol]['packets'].items():
                    for name in ('qualified', 'volume_direction_proxy', 'ready', 'anchor_raw_seq', 'phases', 'raw_seq', 'price_time_s'):
                        check('local接頭切断と未来変更不変', compare(packet[name][:length], short['accounts'][symbol]['packets'][ident][name])
                              and compare(packet[name][:length], future['accounts'][symbol]['packets'][ident][name][:length]))
                for ident, pulse in full['accounts'][symbol]['pulses'].items():
                    before = [value for value in pulse['decisions'] if value['row'] < length]
                    after = [value for value in future['accounts'][symbol]['pulses'][ident]['decisions'] if value['row'] < length]
                    check('raw及びnormal発火とlineage接頭未来不変', compare(pulse['event'][:length], short['accounts'][symbol]['pulses'][ident]['event'])
                          and compare(before, short['accounts'][symbol]['pulses'][ident]['decisions']) and compare(before, after)
                          and compare(pulse['normal_event'][:length], short['accounts'][symbol]['pulses'][ident]['normal_event']))
            missing = deepcopy(raw)
            row = 4 if family == 'C' else 5
            current = missing['TOPIX']
            current['execution_to_raw_index'] = np.delete(current['execution_to_raw_index'], row)
            current['normal_execution_row'][:] = -1
            current['normal_execution_row'][current['execution_to_raw_index']] = np.arange(len(current['execution_to_raw_index']))
            without = core.build_session('人工', missing, items, values)
            pulse = without['accounts']['TOPIX']['pulses'][family+'1']
            check('非対応pulseを次正常行へ移さない', pulse['summary']['raw_pulses'] == pulse['summary']['non_normal_pulses'] == 1
                  and pulse['summary']['normal_pulses'] == 0 and not pulse['normal_event'].any()
                  and pulse['decisions'][0]['row'] == row and pulse['decisions'][0]['normal_row'] is None)

    # ----------------------------------------
    # 受付境界は旧出口の以上/未満を厳密に保ち、価格時計だけで投影を行う。
    raw = dict(raw_seq=np.arange(4, dtype=np.int64), price_time_s=np.array([299., 300., 699.9, 700.]),
        price_time_valid=np.ones(4, bool), normal_execution_row=np.arange(4, dtype=np.int32), execution_to_raw_index=np.arange(4, dtype=np.int64))
    pulse = dict(event=np.array([1, -1, 1, -1], np.int8), decisions=[dict(row=row, raw_seq=row, side=1 if row%2 == 0 else -1) for row in range(4)])
    projected = core.project(pulse, raw, dict(start=0., limit=1000.))
    check('受付はstart300以上limit300未満', [value['in_reception'] for value in projected['decisions']] == [False, True, True, False]
          and projected['summary']['reception_normal_pulses'] == 2)
    zero = core.project(dict(event=np.zeros(4, np.int8), decisions=[]), raw, dict(start=0., limit=1000.))
    check('発火0は未活動で金融勝敗を付けない', zero['summary']['raw_pulses'] == 0 and 'wins' not in zero['summary'])
    invalid = deepcopy(raw)
    invalid['normal_execution_row'][2] = 1
    refused = False
    try:
        core.project(pulse, invalid, dict(start=0., limit=1000.))
    except AssertionError:
        refused = True
    check('矛盾normalmap拒否', refused)

    # ----------------------------------------
    # 新NPZは一回bytes読取で指紋と配列を確認し、活動cacheも往復保存する。
    folder = HERE/'人工保存'
    folder.mkdir(exist_ok=True)
    source = folder/'人工だけ.npz'
    assert not source.exists()
    np.savez_compressed(source, example=np.arange(6, dtype=np.int64))
    wanted = core.digest(source)
    original_reader = Path.read_bytes
    calls = []
    def counted(path: Path) -> bytes:
        """
        機能: 人工NPZのbytes読取回数だけを数える。
        引数: path(Path)は人工又は通常資料。
        返り値: bytesは元内容。正式NPZをこの人工で開かない。
        """
        if path == source:
            calls.append(path)
        return original_reader(path)
    try:
        Path.read_bytes = counted
        loaded = data.read_npz_once(source, wanted)
    finally:
        Path.read_bytes = original_reader
    check('同一bytesでNPZ一回読取hash', len(calls) == 1 and np.array_equal(loaded['example'], np.arange(6)))
    saved = folder/'人工一場.pkl.gz'
    fingerprint = data.dump_session(saved, full)
    restored = pickle.loads(gzip.decompress(saved.read_bytes()))
    check('gzip一場cacheの全数値とlineage往復', compare(full, restored) and core.digest(saved) == fingerprint)
    command = subprocess.run([sys.executable, '-X', 'utf8', str(HERE/'prepare.py')], capture_output=True, text=True, encoding='utf-8')
    check('root活動許可フラグなし拒否', command.returncode == 2 and not (HERE/'cache').exists())
    ending = {str(path.relative_to(ROOT)): core.digest(path) for path in paths}
    check('開始終端source一致', beginning == ending)
    core.save(target, dict(全合格=True, 人工専用=True, 検査件数=COUNTS, source_SHA256=ending,
        仕様SHA256=core.digest(schema_path), 状態複製とengine一致=core.digest(HERE/'states_snapshot.py') == core.digest(HERE.parent/'engine/states.py'),
        正式口座読取=0, 原本再抽出=0, 旧金融結果読取=0, 正式金融再生=0, 現在API取得=0, 実注文=0,
        限界='小人工での投影とcache接口だけ。正式全32の活動・収益・注文成立はまだ未計算。'))
    print(json.dumps(dict(全合格=True, 検査件数=COUNTS, 証跡SHA256=core.digest(target)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        index = 1
        while (HERE/f'人工False_{index:05d}').exists():
            index += 1
        folder = HERE/f'人工False_{index:05d}'
        folder.mkdir()
        for name in ('core.py', 'data.py', 'prepare.py', 'artificial.py'):
            (folder/name).write_bytes((HERE/name).read_bytes())
        core.save(folder/'False.json', dict(全合格=False, 内容=str(error), traceback=traceback.format_exc(),
            検査件数=COUNTS, 正式口座読取=0, 正式金融再生=0, 現在API取得=0))
        raise
