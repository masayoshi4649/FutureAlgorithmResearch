"""新しい金融損益より前に、同じ候補と相手の一般方向を全32へ準備する。"""

import argparse
import gzip
from pathlib import Path
import pickle
import socket

import numpy as np

import base
import catalog


HERE = Path(__file__).resolve().parent


def sources() -> dict:
    """
    機能: 入口の根設計と現実装及び継承入力の小さい直接証跡を固定する。
    引数: なし。
    返り値: dict[str,str]は内容指紋。生原本や旧巨大台帳を再走査しない。
    """
    names = ['数値設計案.json', 'catalog.py', 'base.py', 'prepare.py', 'prepared_data.py',
             'peer/core.py', 'peer/prices.py', 'peer/api.py']
    paths = [HERE/name for name in names]
    paths += [base.PREVIOUS/'activity/data.py', base.PREVIOUS/'activity/全32の状態可用性と発火.json']
    paths += [base.PREVIOUS/name for name in ('base.py', 'engine/adapter.py', 'input/原本抽出前の32場登録.json')]
    paths += [base.ROOT/'work/wave_v102'/name for name in ('data.py', 'holdout_input/data.py', 'strategy.py')]
    paths += [base.ROOT/'work/wave_v94/strategy.py']
    paths += [HERE/'peer'/name for name in (
        '19入口の同一候補と価格窓及び支持lineageの人工検査.json',
        '価格窓境界と拒否後消費及びU新根拠の人工検査.json')]
    paths += [HERE/'review'/name for name in (
        '相手窓と支持追尾の独立人工.json', '入口競合消費と相手採否の独立人工.json',
        '停止予約と注文経済の独立人工.json', '旧気配資格と同出口接続の独立人工.json')]
    return {str(path.relative_to(base.ROOT)): base.digest(path) for path in paths}


def save(path: Path, value: dict) -> None:
    """
    機能: 今回だけの新しい日本語証跡を保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。既存証跡は上書きしない。
    """
    import json
    assert not path.exists() and path.resolve().is_relative_to(HERE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def plan() -> None:
    """
    機能: 根のsourceレビュー前に、予定32場と入口定義だけを固定する。
    引数: なし。
    返り値: None。正式入口準備も金融もまだ実行しない。
    """
    fixed = base.lineage()
    save(HERE/'入口準備前の固定.json', dict(全合格=True, **fixed, entries=catalog.entries(),
        source_SHA256=sources(), 新金融再生=0, 正式入口準備=0, 現在API=0, 実注文=0))


def formal() -> None:
    """
    機能: 根のレビュー後、完了103cacheを一場一回読み全19入口を準備する。
    引数: なし。
    返り値: None。金融を動かさず、同原行の採否と根拠cacheを保存する。
    """
    target = HERE/'入口準備の全32結果.json'
    assert not target.exists() and not list((HERE/'prepared').glob('*.pkl.gz'))
    fixed = base.read(HERE/'入口準備前の固定.json')
    before = sources()
    assert fixed['全合格'] and fixed['source_SHA256'] == before and fixed['entries'] == catalog.entries()
    prepared = base.load_prepared()
    loader = base.module('104正式入口の不変活動読取', base.PREVIOUS/'activity/data.py')
    api = base.module('104正式入口の相手方向接続', HERE/'peer/api.py')
    cache, activity = {}, {}
    for session in fixed['sessions']:
        original = loader.load_session(session)
        records = {symbol: prepared[session, symbol]['record'] for symbol in catalog.SYMBOLS}
        packet = api.prepared_session(original, records)
        activity[session] = {}
        for ident, accounts in packet['cases'].items():
            activity[session][ident] = {}
            for symbol, value in accounts.items():
                normal = value['normal']
                event = normal['event']
                record = records[symbol]
                accepted = (record['time_s'] >= record['start']+300.) & (record['time_s'] < record['limit']-300.)
                activity[session][ident][symbol] = dict(raw_pulses=int(np.count_nonzero(value['raw']['event'])),
                    normal_pulses=int(np.count_nonzero(event)), reception_normal_pulses=int(np.count_nonzero(event[accepted])),
                    reception_buy=int(np.sum((event == 1) & accepted)), reception_sell=int(np.sum((event == -1) & accepted)),
                    common_candidates=len(value['candidates']), rejected_candidates=sum(not row['accepted'] for row in value['candidates']))
                assert normal['entry_id'] == ident
                np.testing.assert_array_equal(normal['execution_to_raw_index'], packet['raw'][symbol]['execution_to_raw_index'])
        path = HERE/'prepared'/(session+'.pkl.gz')
        path.parent.mkdir(parents=True, exist_ok=True)
        assert not path.exists()
        with path.open('wb') as stream:
            with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0, compresslevel=3) as zipped:
                pickle.dump(packet, zipped, protocol=5)
        cache[session] = dict(path=str(path.relative_to(base.ROOT)), SHA256=base.digest(path))
        print(session+' 全19入口を準備・金融0', flush=True)
    assert sources() == before and len(cache) == 32
    aggregate = {ident: {symbol: dict(
        **{field: sum(activity[session][ident][symbol][field] for session in fixed['sessions'])
            for field in ('raw_pulses', 'normal_pulses', 'reception_normal_pulses', 'reception_buy', 'reception_sell', 'common_candidates', 'rejected_candidates')},
        reception_active_sessions=sum(activity[session][ident][symbol]['reception_normal_pulses'] > 0 for session in fixed['sessions']))
        for symbol in catalog.SYMBOLS} for ident in (entry['id'] for entry in catalog.entries())}
    save(target, dict(全合格=True, sessions=fixed['sessions'], 対象場数=32, 入口数=19, 口座数=64,
        cache=cache, activity=activity, aggregate=aggregate, source_SHA256=before,
        開始終端source一致=True, 不変活動cache一場読取=32, 原本再抽出=0,
        新金融再生=0, 現在API=0, 実注文=0,
        限界='入口の活動可用性だけ。保有中/受付休止/返済優先の実注文拒否と収益はまだ未判定。時計は価格代理。'))
    print('全32の19入口を保存。金融0。', flush=True)


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 保存データの準備から外部通信を拒否する。
    引数: args(tuple)、kwargs(dict)は通信引数。
    返り値: None。常に例外を送出する。
    """
    raise RuntimeError('保存32場の準備で外部接続しません')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--plan', action='store_true')
    choice.add_argument('--root-reviewed', action='store_true')
    options = parser.parse_args()
    socket.create_connection = deny
    socket.socket.connect = deny
    plan() if options.plan else formal()
