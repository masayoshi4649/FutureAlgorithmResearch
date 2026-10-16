"""保存活動cacheだけから、公表圧縮と相手準備不在による欠落を分ける。"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ACTIVITY = HERE.parent
ROOT = HERE.parents[3]
SYMBOLS = ('TOPIX', 'NK225')
FAMILIES = ('C1', 'R1')
RESULT = HERE/'二市場準備欠落と先頭時計公表圧縮の診断.json'
PLAN = HERE/'原因診断前のsourceと32cache固定.json'
EXPECTED_ACTIVITY = '6660e11717b969fd06e64a4b33e1171ae50b5c7c15fc379218882f5d66a4c93c'


def digest(path: Path) -> str:
    """
    機能: 小さいsource又は活動metadataの指紋を求める。
    引数: path(Path)は対象。
    返り値: strはSHA256。生原本・NPZ・金融結果に使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: UTF-8の活動由来資料を読む。
    引数: path(Path)はJSON資料。
    返り値: dictは内容。金融結果を開かない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 所有診断領域へ新しい証跡を保存する。
    引数: path(Path)、value(dict)は保存先と内容。
    返り値: None。正式活動source・cache又は既存証跡を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def sources() -> dict:
    """
    機能: 診断sourceと不変活動source及び終端を事前・終端照合へ固定する。
    引数: なし。
    返り値: dict[str,str]は小さい直接指紋。
    """
    paths = [Path(__file__)] + [ACTIVITY/name for name in ('core.py', 'data.py', 'prepare.py',
        'artificial.py', 'states_snapshot.py', '活動cache仕様.json', '全32活動測定前の固定.json',
        '人工発火の正常列直接投影と未来不変.json', '全32の状態可用性と発火.json')]
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def publications(times: np.ndarray) -> np.ndarray:
    """
    機能: 原行順で新最大の有限価格時計の最初行だけを復元する。
    引数: times(ndarray[float64])は保存価格代理時計。
    返り値: ndarray[int64]は公表原行。実受信時計とは扱わない。
    """
    indexes, maximum = [], -np.inf
    for row, stamp in enumerate(times):
        if np.isfinite(stamp) and stamp > maximum:
            indexes.append(row)
            maximum = stamp
    return np.asarray(indexes, np.int64)


def strict_sources(own_times: np.ndarray, peer_times: np.ndarray, public: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    機能: 自己価格時計より厳密に前の最新公表源と15秒以内資格を求める。
    引数: own_times/peer_times(ndarray[float64])、public(ndarray[int64])は保存原行。
    返り値: tuple[ndarray[int64],ndarray[bool]]は相手行又は-1、新鮮資格。
    """
    positions = np.searchsorted(peer_times[public], own_times, side='left')-1
    known = (positions >= 0) & np.isfinite(own_times)
    rows = np.full(len(own_times), -1, np.int64)
    rows[known] = public[positions[known]]
    fresh = np.zeros(len(own_times), bool)
    ages = own_times[known]-peer_times[rows[known]]
    fresh[known] = (ages > 0.) & (ages <= 15.)
    return rows, fresh


def epoch_ready(packet: dict, times: np.ndarray, public: np.ndarray) -> dict:
    """
    機能: 同じ公表epochの同時計後半に存在した準備を診断用に数える。
    引数: packet(dict)、times(ndarray[float64])、public(ndarray[int64])は保存状態。
    返り値: dictは時計群の準備有無と最初準備行。別公表仮説のpulseは作らない。
    """
    n, count = len(times), len(public)
    groups = np.searchsorted(public, np.arange(n), side='right')-1
    same_clock = np.zeros(n, bool)
    after = groups >= 0
    same_clock[after] = times[after] == times[public[groups[after]]]
    ready, first = np.zeros((count, 2), bool), np.full((count, 2), -1, np.int64)
    for column in range(2):
        good = after & same_clock & packet['qualified'] & packet['ready'][:, column]
        rows = np.flatnonzero(good)
        if len(rows):
            selected_groups, positions = np.unique(groups[rows], return_index=True)
            ready[selected_groups, column] = True
            first[selected_groups, column] = rows[positions]
    return dict(groups=groups, same_clock=same_clock, ready=ready, first_ready_row=first)


def count_episodes(anchors: np.ndarray, mask: np.ndarray) -> int:
    """
    機能: 一場・一方向の準備基準seqを重複せず数える。
    引数: anchors(ndarray[int64])、mask(ndarray[bool])は基準と対象原行。
    返り値: intはunique episode数。行数又は発火数と区別する。
    """
    selected = anchors[mask]
    assert np.all(selected >= 0)
    return len(np.unique(selected))


def reception(source: dict, item: dict) -> np.ndarray:
    """
    機能: 旧出口と同じ新規受付時計範囲を保存値から判定する。
    引数: source/item(dict)は原時計と期間metadata。
    返り値: ndarray[bool]は[start+300,limit-300)の行。
    """
    times = source['price_time_s']
    return np.isfinite(times) & (times >= item['start']+300.) & (times < item['limit']-300.)


def diagnose_account(symbol: str, family: str, accounts: dict, public: dict, selected: dict, fresh: dict, epochs: dict) -> dict:
    """
    機能: localreadyの方向別episodeを現公表・同時計圧縮・相手不在へ排他的に分ける。
    引数: symbol/family(str)、accounts/public/selected/fresh/epochs(dict)は保存活動と時計復元。
    返り値: dictは非金融原因件数。後半準備の真の受信先後は推定しない。
    """
    other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    account, peer = accounts[symbol], accounts[other]
    own, opposite = account['packets'][family], peer['packets'][family]
    source, peer_source = account['source'], peer['source']
    own_times, peer_times = source['price_time_s'], peer_source['price_time_s']
    receiving, peer_receiving = reception(source, account['item']), reception(peer_source, peer['item'])
    peer_rows, is_fresh = selected[symbol], fresh[symbol]
    indexes = np.full(len(own_times), -1, np.int64)
    known = peer_rows >= 0
    indexes[known] = np.searchsorted(public[other], peer_rows[known])
    valid_peer = np.zeros(len(own_times), bool)
    valid_peer[is_fresh] = opposite['qualified'][peer_rows[is_fresh]]
    family_epochs = epochs[other][family]
    actual = account['pulses'][family]['decisions']
    output = {}
    for column, side in enumerate((1, -1)):
        ready = own['qualified'] & own['ready'][:, column]
        within = ready & receiving
        anchors = own['anchor_raw_seq'][:, column]
        public_ready = own['qualified'][public[symbol]] & own['ready'][public[symbol], column]
        public_inside = public_ready & receiving[public[symbol]]
        receiver_rows, receiver_fresh = selected[other], fresh[other]
        usable_public = receiver_fresh & peer_receiving & opposite['qualified']
        applied = np.zeros(len(peer_times), bool)
        applied[usable_public] = own['qualified'][receiver_rows[usable_public]] & own['ready'][receiver_rows[usable_public], column]
        published_applied_anchors = own['anchor_raw_seq'][receiver_rows[applied], column]

        paired = np.zeros(len(own_times), bool)
        paired[valid_peer] = opposite['ready'][peer_rows[valid_peer], column]
        same_epoch_ready = np.zeros(len(own_times), bool)
        same_epoch_ready[is_fresh] = family_epochs['ready'][indexes[is_fresh], column]
        tail_missing = is_fresh & same_epoch_ready & ~paired
        masks = dict(現公表源で同family同方向準備=within & paired,
                     同時計後半だけに準備がある欠落候補=within & tail_missing,
                     新鮮公表clockがあるが同epoch同方向準備なし=within & is_fresh & ~same_epoch_ready,
                     厳密過去15秒内公表clockなし=within & ~is_fresh)
        assert np.array_equal(np.logical_or.reduce(list(masks.values())), within)
        assert np.all(np.sum(np.stack(list(masks.values())), axis=0) == within.astype(int))
        categories = {name: dict(ready_rows=int(mask.sum()), episodes=0) for name, mask in masks.items()}
        examples, present_no_pulse = [], dict(受付前に既消費=0, 受付内pulseあり=0, その他の発火抑止=0)
        pulse_anchors_inside = {int(value['episode'][2]) for value in actual if value['side'] == side and value['in_reception']}
        pulse_anchors_before = {int(value['episode'][2]) for value in actual if value['side'] == side and value['price_time_s'] < account['item']['start']+300.}
        for anchor in np.unique(anchors[within]):
            own_episode = within & (anchors == anchor)
            found = None
            for name, mask in masks.items():
                rows = np.flatnonzero(own_episode & mask)
                if len(rows):
                    found = name
                    categories[name]['episodes'] += 1
                    row = int(rows[0])
                    if found == '現公表源で同family同方向準備':
                        cause = '受付内pulseあり' if int(anchor) in pulse_anchors_inside else '受付前に既消費' if int(anchor) in pulse_anchors_before else 'その他の発火抑止'
                        present_no_pulse[cause] += 1
                    elif len(examples) < 5:
                        peer_row = int(peer_rows[row])
                        group = int(indexes[row])
                        later = int(family_epochs['first_ready_row'][group, column]) if group >= 0 else -1
                        examples.append(dict(分類=found, 自己row=row, 自己raw_seq=int(source['raw_seq'][row]),
                            自己価格代理時計=float(own_times[row]), 自己anchor_raw_seq=int(anchor),
                            現相手公表row=None if peer_row < 0 else peer_row,
                            現相手公表raw_seq=None if peer_row < 0 else int(peer_source['raw_seq'][peer_row]),
                            現相手公表価格代理時計=None if peer_row < 0 else float(peer_times[peer_row]),
                            同clock後半準備row=None if later < 0 else later,
                            同clock後半準備raw_seq=None if later < 0 else int(peer_source['raw_seq'][later]),
                            後半の実受信先後は不明=True))
                    break
            assert found is not None
        assert sum(value['episodes'] for value in categories.values()) == count_episodes(anchors, within)
        public_anchors = own['anchor_raw_seq'][public[symbol][public_ready], column]
        local_anchors = np.unique(anchors[ready])
        assert np.all(np.isin(public_anchors, local_anchors))
        local_inside_anchors = np.unique(anchors[within])
        hour = np.zeros(len(own_times), np.int8)
        finite = np.isfinite(own_times)
        hour[finite] = ((own_times[finite]+9*3600)//3600 % 24).astype(np.int8)
        output[str(side)] = dict(
            local_ready_rows=int(ready.sum()), local_ready_episodes=len(local_anchors),
            reception_local_ready_rows=int(within.sum()), reception_local_ready_episodes=len(local_inside_anchors),
            reception_normal_local_ready_rows=int((within & (source['normal_execution_row'] >= 0)).sum()),
            first_public_ready_rows=int(public_ready.sum()), first_public_ready_episodes=len(np.unique(public_anchors)),
            first_public_missing_local_episodes=len(np.setdiff1d(local_anchors, public_anchors)),
            reception_first_public_ready_rows=int(public_inside.sum()),
            reception_first_public_ready_episodes=count_episodes(own['anchor_raw_seq'][public[symbol], column], public_inside),
            receiver_reception_strictfresh_qualified_application_rows=int(applied.sum()),
            receiver_reception_strictfresh_applied_episodes=len(np.unique(published_applied_anchors)),
            reception_fresh_public_unqualified_rows=int((within & is_fresh & ~valid_peer).sum()),
            reception_fresh_qualified_public_unready_rows=int((within & valid_peer & ~paired).sum()),
            reception_episode_categories=categories,
            paired_ready_episode_pulse_status=present_no_pulse,
            reception_actual_pulses=sum(value['side'] == side and value['in_reception'] for value in actual),
            reception_ready_hours={f'{clock:02d}:00': dict(rows=int((within & (hour == clock)).sum()),
                episodes=count_episodes(anchors, within & (hour == clock))) for clock in range(24) if np.any(within & (hour == clock))},
            欠落原行の参考例=examples)
    return output


def artificial() -> dict:
    """
    機能: 公表復元・strictpast・15秒境界とepochの時計逆行除外を人工確認する。
    引数: なし。
    返り値: dictは人工合格件数。pulse又は金融を生成しない。
    """
    times = np.array([1., 1., .5, 2., 2., np.nan, 3.])
    public = publications(times)
    np.testing.assert_array_equal(public, [0, 3, 6])
    rows, fresh = strict_sources(np.array([1., 1.1, 2., 17., 17.1, np.nan]), times, public)
    np.testing.assert_array_equal(rows, [-1, 0, 0, 6, 6, -1])
    np.testing.assert_array_equal(fresh, [False, True, True, True, True, False])
    rows, fresh = strict_sources(np.array([18., 18.0001]), times, public)
    np.testing.assert_array_equal(fresh, [True, False])
    packet = dict(qualified=np.ones(7, bool), ready=np.zeros((7, 2), bool))
    packet['ready'][1, 0] = True
    packet['ready'][2, 1] = True
    packet['ready'][4, 1] = True
    epochs = epoch_ready(packet, times, public)
    np.testing.assert_array_equal(epochs['ready'], [[True, False], [False, True], [False, False]])
    np.testing.assert_array_equal(epochs['first_ready_row'], [[1, -1], [-1, 4], [-1, -1]])
    return dict(全合格=True, 公表先頭と逆行保持=1, strictpast=1, freshness境界=1, 同clockepoch準備=1, 逆行行を後半支持にしない=1)


def aggregate(sessions: dict) -> dict:
    """
    機能: episodeを場内で数えた値から全32の買売別原因件数を合計する。
    引数: sessions(dict)は各場・商品・family・方向の診断。
    返り値: dictは全32非金融合計。場を跨ぐ同一seqを統合しない。
    """
    result = {}
    for family in FAMILIES:
        result[family] = {}
        for symbol in SYMBOLS:
            result[family][symbol] = {}
            for side in ('1', '-1'):
                rows = [session[symbol][family][side] for session in sessions.values()]
                result[family][symbol][side] = {name: sum(row[name] for row in rows)
                    for name, value in rows[0].items() if isinstance(value, int)}
                for container in ('reception_episode_categories', 'paired_ready_episode_pulse_status'):
                    if container == 'reception_episode_categories':
                        result[family][symbol][side][container] = {category: {field: sum(row[container][category][field] for row in rows)
                            for field in ('ready_rows', 'episodes')} for category in rows[0][container]}
                    else:
                        result[family][symbol][side][container] = {category: sum(row[container][category] for row in rows) for category in rows[0][container]}
    return result


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 非金融原因診断からの外部通信を拒絶する。
    引数: args(tuple)、kwargs(dict)は通信引数。
    返り値: None。常にRuntimeErrorを送出する。
    """
    raise RuntimeError('原因診断は保存活動cacheだけを使い、外部通信しません')


def formal() -> None:
    """
    機能: 根の許可した原因分析を保存cacheだけで一回行う。
    引数: なし。
    返り値: None。原本・v2NPZ・旧結果・金融・新仮説pulseを再生しない。
    """
    assert not PLAN.exists() and not RESULT.exists()
    metadata_path = ACTIVITY/'全32の状態可用性と発火.json'
    assert digest(metadata_path) == EXPECTED_ACTIVITY
    metadata = read(metadata_path)
    assert metadata['全合格'] and metadata['対象場数'] == 32 and metadata['口座数'] == 64
    assert metadata['正式金融再生'] == metadata['旧金融結果読取'] == metadata['現在API取得'] == 0
    beginning = sources()
    for name, wanted in metadata['開始SHA256'].items():
        assert digest(ROOT/name) == wanted, name
    own_artificial = artificial()
    save(PLAN, dict(全合格=True, sessions=metadata['sessions'], source_SHA256=beginning,
        cache_SHA256={value['位置']: value['SHA256'] for value in metadata['cache'].values()},
        人工=own_artificial, 受付='[start+300,limit-300)', 時計='価格代理時計のみ、相手strictpastと15秒以内',
        後半候補='現在の最新公表clockと同じ原clock、次新最大公表の前だけ。受信先後は不明で採用可能性を主張しない。',
        金融再生=0, 新仮説pulse生成=0, 原本読取=0, NPZ読取=0, API取得=0))
    sessions, input_hashes, public_counts = {}, {}, {}
    for session in metadata['sessions']:
        reference = metadata['cache'][session]
        path = ROOT/reference['位置']
        assert path.resolve().is_relative_to((ACTIVITY/'cache').resolve())
        saved = path.read_bytes()
        assert hashlib.sha256(saved).hexdigest() == reference['SHA256']
        payload = pickle.loads(gzip.decompress(saved))
        assert payload['schema_version'] == 1 and payload['session'] == session
        accounts = payload['accounts']
        public = {symbol: publications(accounts[symbol]['source']['price_time_s']) for symbol in SYMBOLS}
        selected, fresh, epochs = {}, {}, {}
        for symbol in SYMBOLS:
            other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            selected[symbol], fresh[symbol] = strict_sources(accounts[symbol]['source']['price_time_s'], accounts[other]['source']['price_time_s'], public[other])
            for family in FAMILIES:
                np.testing.assert_array_equal(selected[symbol], accounts[symbol]['pulses'][family]['peer_rows'])
            epochs[symbol] = {family: epoch_ready(accounts[symbol]['packets'][family], accounts[symbol]['source']['price_time_s'], public[symbol]) for family in FAMILIES}
        sessions[session] = {symbol: {family: diagnose_account(symbol, family, accounts, public, selected, fresh, epochs) for family in FAMILIES} for symbol in SYMBOLS}
        public_counts[session] = {symbol: len(public[symbol]) for symbol in SYMBOLS}
        input_hashes[reference['位置']] = reference['SHA256']
        print(session+' C1/R1公表とsamefamily準備欠落を保存 / 金融0', flush=True)
    assert sources() == beginning and len(input_hashes) == 32
    result = dict(全合格=True, 対象場数=32, 口座数=64, families=list(FAMILIES), by_session=sessions,
        aggregate=aggregate(sessions), public_source_counts=public_counts, 人工=own_artificial,
        公表復元peer_rows全行一致口座family数=64*2, 開始終端source一致=True,
        開始SHA256=beginning, SHA256=sources(), 入力cacheSHA256=input_hashes, 事前固定SHA256=digest(PLAN),
        cache読取回数=32, 正式活動source変更=0, 正式活動cache変更=0,
        原本読取=0, NPZ読取=0, 旧結果読取=0, 金融再生=0, 新仮説pulse生成=0, API取得=0, 実注文=0,
        定義=dict(episode分類='受付内ready episodeについて、現公表で同family同方向→同clock後半候補→同clock群準備なし→新鮮clockなしの順に、少なくとも1原行の該当がある分類へ一度数える。原行の分類は同時に排他的。',
            public適用='相手の受付内qualified原行に対して、厳密に前で15秒内の公表源が当該方向readyである件数。相手自身readyを条件にしない。',
            同clock後半='次の新最大時計公表前の同時計原行にqualified+readyが存在することだけ。後半の真の受信順や実行可能性は不明。',
            ready行='原行数。経過秒数・取引数とは異なる。', 発火0='勝ちには含めない。'),
        限界='同clock後半の表示は現在の公表規則が切り捨てた状態の存在を診断する参考上限。真の受信時刻欠測のため、その状態が自己判断より先に届いていたとは証明できない。別公表仮説・別pulse・利益の試算を行っていない。')
    save(RESULT, result)
    print('全32の非金融原因診断完了 SHA256 '+digest(RESULT), flush=True)


def main() -> None:
    """
    機能: 根の追加原因分析許可を明示して保存cache診断だけを実行する。
    引数: CLI --root-diagnosis-authorized(bool)。
    返り値: None。フラグなしは正式cacheを読む前に拒否する。
    """
    parser = argparse.ArgumentParser(description='二市場準備欠落の非金融診断')
    parser.add_argument('--root-diagnosis-authorized', action='store_true', required=True)
    parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    formal()


if __name__ == '__main__':
    main()
