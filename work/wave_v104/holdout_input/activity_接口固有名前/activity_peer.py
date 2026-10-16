"""追加Dayの完了入力だけを、不変103活動と104の19入口へ一回接続する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path
import pickle
import socket
import sys
import traceback

import numpy as np

import core
import data


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLAN = HERE/'追加Day活動と19入口の保存前固定.json'
ARTIFICIAL = HERE/'追加Day活動peer接続の人工検査.json'
RESULT = HERE/'追加Dayの活動と19入口.json'
TARGET = HERE/'activity_peer'/(core.SESSION+'.pkl.gz')
STATE_PATH = HERE/'activity_runtime/states_snapshot.py'
STATE_NAME = '追加Day固定103状態複製'


def save(path: Path, value: dict) -> None:
    """
    機能: 所有域へ未存在の日本語JSONを保存する。
    引数: path(Path)は保存位置、value(dict)は証跡。
    返り値: None。旧source/cacheと完成証跡を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def read(path: Path) -> dict:
    """
    機能: 小さいinput metadata又は人工証跡だけを読む。
    引数: path(Path)は日本語JSON。
    返り値: dictは内容。旧金融結果、旧32activity/cache、raw原本は読まない。
    """
    assert path.suffix == '.json' and path.resolve().is_relative_to((ROOT/'work').resolve())
    return json.loads(path.read_text(encoding='utf-8'))


def dependency_paths() -> list[Path]:
    """
    機能: 数値、接続、入力由来と人工済み接口の小直接依存を列挙する。
    引数: なし。
    返り値: list[Path]はsourceと小証跡。NPZや旧巨大cacheはhashしない。
    """
    names = [
        'work/wave_v103/activity/core.py', 'work/wave_v103/catalog.py',
        'work/wave_v103/activity/states_snapshot.py', 'work/wave_v103/engine/states.py',
        'work/wave_v103/activity/人工発火の正常列直接投影と未来不変.json',
        'work/wave_v103/engine/独立状態と厳密過去接続及び実配分の人工検査_補足07確定.json',
        'work/wave_v104/catalog.py', 'work/wave_v104/数値設計案.json',
        'work/wave_v104/peer/core.py', 'work/wave_v104/peer/prices.py', 'work/wave_v104/peer/api.py',
        'work/wave_v104/peer/artificial.py', 'work/wave_v104/peer/state_fixture_source.py',
        'work/wave_v104/peer/19入口の同一候補と価格窓及び支持lineageの人工検査.json',
        'work/wave_v104/peer/価格窓境界と拒否後消費及びU新根拠の人工検査.json',
        'work/wave_v104/engine/19入口normalとO及び支持出口の結合人工.json']
    return [Path(__file__), STATE_PATH, *[ROOT/name for name in names],
            HERE/'core.py', HERE/'data.py', HERE/'入力schema.json', HERE/'metadata.json',
            HERE/'旧normal独立LPと完全prepareの人工検査.json']


def sources() -> dict[str, str]:
    """
    機能: 新場の活動前後で同一の小直接sourceと入力由来を固定する。
    引数: なし。
    返り値: dict[str,str]はルート相対位置とSHA256。原本又はNPZの再hashは0。
    """
    return {str(path.relative_to(ROOT)): data.digest(path) for path in dependency_paths()}


def parts() -> tuple[object, object, object, list[dict]]:
    """
    機能: 不変103のbuild_sessionを、同一SHAの所有state複製と不変104APIへ結ぶ。
    引数: なし。
    返り値: tupleは103活動モジュール、状態複製、104API、103の19route条件。
    数値関数は変更せず、states取得factoryとcache保存先だけを新所有域へ接続する。
    """
    original = ROOT/'work/wave_v103/activity/states_snapshot.py'
    assert data.digest(STATE_PATH) == data.digest(original) == data.digest(ROOT/'work/wave_v103/engine/states.py')
    activity = core.module('追加Dayの不変103活動関数', 'work/wave_v103/activity/core.py')
    state = core.module(STATE_NAME, str(STATE_PATH.relative_to(ROOT)))
    # ----------------------------------------
    # 既cacheのcanonical名を同じstateへ結び、旧状態sourceへのcache書込みを避ける。
    canonical = '103活動の不変状態複製'
    if canonical in sys.modules:
        existing = sys.modules[canonical]
        assert data.digest(Path(existing.__file__)) == data.digest(STATE_PATH)
    else:
        sys.modules[canonical] = state

    def state_provider() -> object:
        """
        機能: 不変build_sessionへ同一byteの新所有stateモジュールを供給する。
        引数: なし。
        返り値: objectは同一数学関数を持つ状態機械。新方式や資格の救済はしない。
        """
        return state

    activity.states = state_provider
    catalog = core.module('追加Day活動の旧103条件', 'work/wave_v103/catalog.py')
    peer = core.module('追加Dayの不変104peer接口', 'work/wave_v104/peer/api.py')
    values = catalog.catalog()
    assert len(values) == 19
    return activity, state, peer, values


def connect(raw: dict, items: dict, bundle: dict, python: bool = False) -> dict:
    """
    機能: 渡された同場の原行と完全旧prepareだけで、103活動と104の19入口を作る。
    引数: raw/items(dict[symbol,dict])は2口座、bundle(dict)は同新material/prepare、
          python(bool)は純人工でPython状態計算を選ぶ指定。
    返り値: dictはschema_version/session/activity/peer/prepared。金融及び暗黙loadはない。
    """
    assert set(raw) == set(items) == set(core.SYMBOLS)
    sessions = {item['session'] for item in items.values()}
    assert len(sessions) == 1
    session = sessions.pop()
    prepared = bundle['prepared']
    assert set(prepared) == {(session, symbol) for symbol in core.SYMBOLS}
    records = {symbol: prepared[session, symbol]['record'] for symbol in core.SYMBOLS}
    for symbol, record in records.items():
        assert record['session'] == session and record['symbol'] == symbol
        mapping = raw[symbol]['execution_to_raw_index']
        for source, name in (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'), ('bid', 'bid'), ('ask', 'ask')):
            np.testing.assert_array_equal(raw[symbol][source][mapping], record[name])
        assert record['quote_valid'].dtype == record['price_valid'].dtype == np.bool_
        assert record['quote_valid'].shape == record['price_valid'].shape == record['seq'].shape
    with core.owned_cache():
        activity_module, _, peer_module, values = parts()
        activity = activity_module.build_session(session, raw, items, values, python=python)
        peer = peer_module.prepared_session(activity, records)
    assert len(activity['case_routes']) == len(peer['cases']) == 19
    assert activity['case_routes']['OLD_G0'] is None
    assert set(activity['case_routes']) != set(peer['cases']), '103旧19routeと104新19入口を同一視しません'
    for symbol in core.SYMBOLS:
        account = activity['accounts'][symbol]
        for name in ('seq', 'time_s', 'price', 'bid', 'ask'):
            np.testing.assert_array_equal(account['normal_record'][name], records[symbol][name])
        assert peer['normal'][symbol]['record'] is records[symbol]
    return dict(schema_version=1, session=session, activity=activity, peer=peer, prepared=prepared)


def entry_activity(packet: dict) -> dict:
    """
    機能: 104入口ごとに受付内の買売pulseを数え、103routeとは別欄へ保存する。
    引数: packet(dict)はconnectの返り値。
    返り値: dictは非金融活動。無発火を勝ち、新規注文又は約定に数えない。
    """
    answer = {}
    for ident, accounts in packet['peer']['cases'].items():
        answer[ident] = {}
        for symbol, value in accounts.items():
            record = packet['prepared'][packet['session'], symbol]['record']
            event = value['normal']['event']
            reception = (record['time_s'] >= record['start']+300.) & (record['time_s'] < record['limit']-300.)
            answer[ident][symbol] = dict(raw_pulses=int(np.count_nonzero(value['raw']['event'])),
                normal_pulses=int(np.count_nonzero(event)), reception_normal_pulses=int(np.count_nonzero(event[reception])),
                reception_buy=int(np.sum((event == 1)&reception)), reception_sell=int(np.sum((event == -1)&reception)),
                common_candidates=len(value['candidates']), rejected_candidates=sum(not row['accepted'] for row in value['candidates']))
    return answer


def plan() -> None:
    """
    機能: NPZ/新bundle読取前に、新2口座、源source、人工済み依存及び保存契約を固定する。
    引数: なし。
    返り値: None。metadataと小sourceだけを読み、実活動・金融は行わない。
    """
    assert not PLAN.exists() and not RESULT.exists() and not TARGET.exists()
    metadata = data.metadata(True)
    assert data.digest(HERE/'metadata.json') == 'da1fa5013ebf3fd245fb48e1990df1dcad8a6cf5c003da386b42d31786dcad7b'
    own = read(ARTIFICIAL)
    assert own['全合格'] and own['人工専用'] and own['正式新NPZ読取'] == own['新bundle読取'] == own['金融再生'] == 0
    before = sources()
    assert own['source_SHA256'] == before
    save(PLAN, dict(全合格=True, session=core.SESSION, 口座数=2, source_SHA256=before,
        入力metadataSHA256=data.digest(HERE/'metadata.json'), 人工SHA256=data.digest(ARTIFICIAL),
        新NPZ={symbol: dict(path=item['出力位置'], SHA256=item['出力SHA256'], 予定読取=1)
               for symbol in core.SYMBOLS for item in [metadata['accounts'][core.SESSION+'|'+symbol]]},
        新bundle={name: dict(SHA256=value, 予定読取=1) for name, value in metadata['入力SHA256'].items()},
        保存契約=dict(schema_version=1, session=core.SESSION, activity='不変103原packet19route',
            peer='不変104一般方向19入口packet', prepared='同新bundleの完全旧102.prepare tuplekey2口座',
            path=str(TARGET.relative_to(ROOT))),
        state_factory='103 build_session source不変、states factoryのみ同一SHAの新所有複製へ接続。canonical名も同じbytesへalias。',
        旧103route数=19, 新104入口数=19, 両19を別物として表示=True,
        正式新NPZ読取=0, 新bundle読取=0, 正式新活動計算=0, 金融再生=0,
        原本再読=0, 旧32cache読取=0, 旧64base読取=0, 条件変更=0, 主変更=0,
        API取得=0, 実注文=0, goal操作=0))
    print('追加Dayの活動/19入口sourceと一回入力読取を固定。まだ実活動0', flush=True)


def artificial() -> None:
    """
    機能: 小人工だけで不変103活動→104入口と同bundleの物理record接続を検査する。
    引数: なし。
    返り値: None。正式新NPZ・新bundle・旧32cache・金融は読まず、新人工証跡を保存する。
    """
    assert not ARTIFICIAL.exists()
    before, checks, fixtures = sources(), {}, 0
    with core.owned_cache():
        fixture_source = core.module('追加Day活動の104人工原行生成だけ', 'work/wave_v104/peer/artificial.py')
        for family in ('C', 'R'):
            for reflect in (False, True):
                for tick in (.5, 10.):
                    label = family+str(reflect)+'呼値'+str(tick)
                    raw, items, prepared = {}, {}, {}
                    for symbol in core.SYMBOLS:
                        current = fixture_source.raw_fixture(family, reflect, tick, strong=symbol == 'NK225')
                        if symbol == 'NK225':
                            current['price_time_s'] -= .1
                            current['volume_time_s'] -= .1
                        n = len(current['raw_seq'])
                        current['execution_to_raw_index'] = np.arange(n, dtype=np.int64)
                        current['normal_execution_row'] = np.arange(n, dtype=np.int32)
                        raw[symbol] = current
                        items[symbol] = dict(symbol=symbol, session='人工追加Day', tick=tick,
                            start=0., end=1100., limit=1000., raw_rows=n, normal_execution_rows=n)
                        record = {destination: current[source].copy() for source, destination in
                            (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'), ('bid', 'bid'), ('ask', 'ask'))}
                        record.update(symbol=symbol, session='人工追加Day', tick=tick, start=0., end=1100., limit=1000.,
                                      quote_valid=np.ones(n, bool), price_valid=np.ones(n, bool))
                        prepared['人工追加Day', symbol] = dict(record=record, signal=dict(人工だけ=True), reference_open=100.*tick)
                    bundle = dict(prepared=prepared)
                    original = deepcopy((raw, items, bundle))
                    packet = connect(raw, items, bundle, python=True)
                    native = connect(raw, items, bundle, python=False)
                    checks[label+'PythonとJIT状態及びpeer全一致'] = fixture_source.compare(packet, native)
                    checks[label+'入力を改変しない'] = fixture_source.compare((raw, items, bundle), original)
                    checks[label+'19旧routeと19新入口を別保存'] = len(packet['activity']['case_routes']) == len(packet['peer']['cases']) == 19 and \
                        set(packet['activity']['case_routes']) != set(packet['peer']['cases'])
                    checks[label+'経済対照のpreparedを同bundleのまま結ぶ'] = packet['prepared'] is bundle['prepared'] and all(
                        packet['peer']['normal'][symbol]['record'] is prepared['人工追加Day', symbol]['record'] for symbol in core.SYMBOLS)
                    checks[label+'自己OWNに人工発火あり'] = all(np.any(packet['peer']['cases'][family+'_OWN'][symbol]['normal']['event']) for symbol in core.SYMBOLS)
                    payload = gzip.compress(pickle.dumps(packet, protocol=5), mtime=0)
                    restored = pickle.loads(gzip.decompress(payload))
                    checks[label+'全packetのpickle往復一致'] = fixture_source.compare(packet, restored) and all(
                        restored['peer']['normal'][symbol]['record'] is restored['prepared']['人工追加Day', symbol]['record'] for symbol in core.SYMBOLS)
                    altered = deepcopy(raw)
                    altered['TOPIX']['depth_valid'][-1] = False
                    altered['TOPIX']['depth_transition_valid'][-1] = False
                    unknown = connect(altered, items, bundle, python=True)
                    checks[label+'量資格不明と物理返済気配を分離'] = not unknown['peer']['normal']['TOPIX']['entry_quality'][-1] and \
                        bool(unknown['peer']['normal']['TOPIX']['quote_valid'][-1])
                    fixtures += 1
        assert sys.modules['103活動の不変状態複製'].__file__ == sys.modules[STATE_NAME].__file__
        checks['canonical名を所有state同bytesへ接続'] = True
        checks['不変103stateの同SHA複製'] = data.digest(STATE_PATH) == data.digest(ROOT/'work/wave_v103/activity/states_snapshot.py')
        import numba
        for module in (sys.modules[STATE_NAME], fixture_source.STATE):
            for value in vars(module).values():
                cache = getattr(value, '_cache', None) if type(value).__name__ == 'CPUDispatcher' else None
                locator = getattr(getattr(cache, '_impl', None), '_locator', None)
                if locator is not None:
                    assert Path(locator.get_cache_path()).resolve().is_relative_to(HERE.resolve())
        checks['両状態sourceのJIT保存先は所有域'] = numba.config.CACHE_DIR == core.CACHE
    assert sources() == before
    checks = {name: bool(value) for name, value in checks.items()}
    save(ARTIFICIAL, dict(全合格=all(checks.values()), 人工専用=True, 検査件数=len(checks), 検査=checks,
        source_SHA256=before, 人工素材数=fixtures, 正式新NPZ読取=0, 新bundle読取=0,
        原本再読=0, 旧32cache読取=0, 旧64base読取=0, 金融結果読取=0, 金融再生=0,
        API取得=0, 実注文=0, goal操作=0,
        限界='人工signalは接続同一性だけ。実正式preparedは完了した完全102.prepareを同bundleから一回読む。'))
    assert all(checks.values())
    print('追加Dayの活動peer小人工 '+str(len(checks))+'項目合格。正式新入力読取0', flush=True)


def formal() -> None:
    """
    機能: 根の別通知後だけ、新NPZ2各一回と新bundle一回から活動と19入口を保存する。
    引数: なし。
    返り値: None。原本、旧32cache、旧64base、金融結果は読まず、金融を実行しない。
    """
    assert PLAN.exists() and not RESULT.exists() and not TARGET.exists()
    fixed, before = read(PLAN), sources()
    assert fixed['全合格'] and fixed['source_SHA256'] == before
    assert data.digest(ARTIFICIAL) == fixed['人工SHA256']
    raw, items = {}, {}
    for symbol in core.SYMBOLS:
        raw[symbol], items[symbol] = data.load_account(core.SESSION, symbol, verify=True)
        assert items[symbol]['出力SHA256'] == fixed['新NPZ'][symbol]['SHA256']
    bundle = data.load_bundle(verify=True)
    packet = connect(raw, items, bundle)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with TARGET.open('wb') as stream:
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0, compresslevel=3) as compressed:
            pickle.dump(packet, compressed, protocol=5)
    fingerprint = data.digest(TARGET)
    assert sources() == before
    save(RESULT, dict(全合格=True, schema_version=1, session=core.SESSION,
        path=str(TARGET.relative_to(ROOT)), SHA256=fingerprint, source_SHA256=before,
        入力metadataSHA256=fixed['入力metadataSHA256'], 事前固定SHA256=data.digest(PLAN),
        旧103活動route数=19, 旧103活動=packet['activity']['summary'],
        新104入口数=19, 新104入口=entry_activity(packet),
        開始終端source一致=True, 同新bundlepreparedをcacheへ接続=True,
        新NPZ口座読取=2, 各NPZ読取回数=1, 新bundle読取=1, 原本再読=0,
        旧32cache読取=0, 旧64base読取=0, 金融再生=0, 金融結果読取=0,
        条件変更=0, 主変更=0, API取得=0, 実注文=0, goal操作=0,
        限界='活動・pulseだけで注文、約定、利益又は安定性を示さない。両市場は価格代理時計上のstrict過去。'))
    print('追加Dayの103活動と104の19入口及び同bundle旧preparedを保存。金融0', flush=True)


def load_complete(verify: bool = True) -> dict:
    """
    機能: 金融側が旧64baseを読まず、新活動/peer/完全preparedを一cache読取で得る。
    引数: verify(bool)は新cacheと小直接依存の照合要否。
    返り値: dictはschema_version/session/activity/peer/preparedのreadonly共有packet。
    """
    metadata = read(RESULT)
    assert metadata['全合格'] and metadata['金融再生'] == metadata['原本再読'] == 0
    assert metadata['session'] == core.SESSION and metadata['source_SHA256'] == sources()
    payload = TARGET.read_bytes()
    if verify:
        assert hashlib.sha256(payload).hexdigest() == metadata['SHA256']
    packet = pickle.loads(gzip.decompress(payload))
    assert packet['schema_version'] == 1 and packet['session'] == core.SESSION
    assert set(packet) == {'schema_version', 'session', 'activity', 'peer', 'prepared'}
    data.immutable(packet)
    return packet


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 活動準備中のAPI及び注文の通信を拒否する。
    引数: args(tuple)、kwargs(dict)は接続指定。
    返り値: None。常にRuntimeError。
    """
    raise RuntimeError('追加Day活動接続は新保存入力だけを使い、APIと注文を禁止します')


def main() -> None:
    """
    機能: 入力を読まない事前計画と、根の別確認後の活動計算をCLIで分離する。
    引数: CLI --artificial(bool)、--plan(bool)、--root-activity-peer-reviewed(bool)。
    返り値: None。フラグなしは正式新入力読取前に拒否する。
    """
    parser = argparse.ArgumentParser(description='追加Dayの活動及び19入口を金融0で接続する')
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--plan', action='store_true')
    choice.add_argument('--artificial', action='store_true')
    choice.add_argument('--root-activity-peer-reviewed', action='store_true')
    arguments = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    if arguments.artificial:
        artificial()
    elif arguments.plan:
        plan()
    else:
        formal()


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        index = 1
        while (HERE/f'活動peer不合格_{index:05d}.json').exists():
            index += 1
        save(HERE/f'活動peer不合格_{index:05d}.json', dict(全合格=False, 例外型=type(error).__name__,
            内容=str(error), 診断=traceback.format_exc(), 自動再実行=False,
            原本再読=0, 金融再生=0, 金融結果読取=0, API取得=0, 実注文=0, goal操作=0))
        raise
