"""保存特徴のみで三遅延の状態を準備し、旧FD一致と未来切断を確認する。"""

import argparse
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

import signals


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.dont_write_bytecode = True


def deny(*args, **kwargs):
    """
    機能: 保存特徴の信号準備で外部通信を禁止する。
    引数: args (tuple)、kwargs (dict)。
    返り値: None。常に例外で処理を止める。
    """
    raise RuntimeError('信号準備では保存特徴のみを参照する')


def digest(path):
    """
    機能: 入出力のSHA256を一定メモリーで計算する。
    引数: path (Path)。
    返り値: str はSHA256。
    """
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        while data := stream.read(4*1024*1024):
            hasher.update(data)
    return hasher.hexdigest()


def cut(value, length, total):
    """
    機能: 格子対応の保存特徴を指定位置まで切断する。
    引数: value (object)、length/total (int)。
    返り値: object は配列だけを過去へ切り詰めた構造。
    """
    if isinstance(value, dict):
        return {key: cut(item, length, total) for key, item in value.items()}
    if isinstance(value, np.ndarray) and len(value) == total:
        return value[:length].copy()
    return value


def main():
    """
    機能: 一遅延の信号を保存し、旧29場FD・旧30場common・切断の一致を検査する。
    引数: CLI --delay (int、1/5/15)。
    返り値: None。完成出力を上書きせず、損益を計算しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--delay', type=int, choices=[1,5,15], default=5)
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    folder = HERE / 'prepared'
    folder.mkdir(exist_ok=True)
    target = folder / f'signals_delay{args.delay}.pkl'
    assert not target.exists(), '保存済み信号は上書きしない'
    input_path = ROOT / f'work/wave_v77/inputs/grids_delay{args.delay}.pkl'
    prior_path = ROOT / f'work/wave_v76/prepared/signals_delay{args.delay}.pkl'
    common_path = ROOT / f'work/wave_v77/prepared/signals_delay{args.delay}.pkl'
    grids = pickle.loads(input_path.read_bytes())
    old = pickle.loads(prior_path.read_bytes())['FD15']
    common = pickle.loads(common_path.read_bytes())
    assert len(grids) == len(common) == 30 and len(old) == 29
    states = signals.build(grids)
    counts = []
    cuts = 0
    for session, state in states.items():
        np.testing.assert_array_equal(state['common'], common[session]['common'])
        np.testing.assert_array_equal(state['valid'], common[session]['valid'])
        if session in old:
            reference = old[session]
            for name in ('grid', 'source_top', 'source_nk'):
                np.testing.assert_array_equal(state[name], reference[name])
            np.testing.assert_array_equal(state['fd_valid'], reference['valid'])
            for side in ('long', 'short'):
                np.testing.assert_array_equal(state[f'fd_{side}'], reference['management'][15][f'opposite_{side}'])
        for side in ('long', 'short'):
            assert np.all(~state[f'fd_price_{side}'] | state[f'fd_{side}'])
        assert not np.any(state['fd_long'] & state['fd_short'])
        assert not np.any(state['fd_price_long'] & state['fd_price_short'])
        counts.append({'場': session, '格子数': len(state['grid']),
                       **{name: int(state[name].sum()) for name in
                          ('valid','current300_valid','fd_long','fd_short','fd_price_long','fd_price_short')},
                       '共通上': int((state['common'] == 1).sum()), '共通下': int((state['common'] == -1).sum())})
        for portion in (.25, .5, .75):
            length = int(len(state['grid'])*portion)
            prefix = signals.session_state(cut(grids[session], length, len(state['grid'])))
            for name, values in state.items():
                np.testing.assert_array_equal(prefix[name], values[:length])
            cuts += 1
    target.write_bytes(pickle.dumps(states, protocol=5))
    proof = {'遅延秒': args.delay, '場数': len(states), '既往FD15完全一致場数': len(old),
             '旧common及び価格有効性完全一致場数': len(common), '途中切断一致数': cuts,
             'F2はF1の部分集合': True, '損益計算': 0, 'API取得': 0, '実注文': 0,
             '仕様': '生FD15反対合意＋双方30秒の売買両気配1呼値逆行を同時に15秒、開始後双方参照行更新。無効又は格子欠落で確認破棄。',
             '既知範囲': '全30場は過去の研究で既知。将来の未見確認とは呼ばない。',
             '時計': '最終約定時計の代理。共通受信時計による先行関係を証明しない。',
             '集計': counts,
             'SHA256': {str(path.relative_to(ROOT)): digest(path) for path in
                        [HERE/'signals.py', HERE/'prepare_signals.py', input_path, prior_path, common_path, target]}}
    (folder/f'信号照合_delay{args.delay}.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k not in ('集計','SHA256')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
