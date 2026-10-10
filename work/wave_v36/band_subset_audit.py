"""同じ準備区間で、気配維持代理の採用が全量・純価格の部分集合になるか検算する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pickle
import socket

import band_signals as signal


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path: Path) -> str:
    """機能: 資料の内容を固定する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject_network(*args: object, **kwargs: object) -> None:
    """機能: 保存資料の検査で通信を拒否する。

    引数: args/kwargs (object)。返り値: なし (None)、常に例外。
    """
    raise RuntimeError('採用集合の検査は保存入力だけを使う')


def main() -> None:
    """機能: 全26入力の同条件採用集合を照合する。

    引数: なし。返り値: なし (None)。持続方向の行集合は比較しない。
    """
    socket.socket.connect = reject_network
    socket.create_connection = reject_network
    paths = [HERE/'band_signals.py', HERE/'band_design.py', Path(__file__),
        ROOT/'work/wave_v23/inputs.pkl', ROOT/'work/wave_v23/features_depth.pkl', HERE/'events.pkl']
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    inputs = pickle.loads(paths[3].read_bytes())
    features = pickle.loads(paths[4].read_bytes())
    events = pickle.loads(paths[5].read_bytes())
    groups, rows = {}, []
    signal.clear_cache()
    for scale in (.8, 1., 1.2):
        for spec in signal.catalog():
            params = spec['params']
            out = signal.build(spec, inputs, features, events, scale)
            for key, item in out.items():
                group = (scale, params['window_seconds'], params['branch'], params['peer_mode'], key)
                accepted = {ep['episode_id'] for ep in item['episodes'] if ep['accepted']}
                groups.setdefault(group, {})[(params['proxy'], params['volume_threshold'])] = accepted
        print(f'採用集合検査 窓倍率 {scale} の全90生成', flush=True)
    for group, entries in groups.items():
        scale, window, branch, peer, key = group
        price = entries['price', 0.]
        for threshold in (2., 5.):
            all_volume = entries['all_volume', threshold]
            stable = entries['stable_volume', threshold]
            assert stable <= all_volume <= price, group
            rows.append(dict(clock_scale=scale, window_seconds=window, branch=branch,
                peer_mode=peer, session=key[0], symbol=key[1], threshold=threshold,
                純価格採用数=len(price), 全量採用数=len(all_volume), 気配維持採用数=len(stable),
                採用episode部分集合一致=True))
    assert len(rows) == 3 * 2 * 3 * 3 * 26 * 2 == 2808
    assert before == {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    value = dict(全監査合格=True, 対応集合数=len(rows), 全入力数=26, 検査行=rows,
        比較対象='同じ準備episodeの採用集合。TTLが上書きされる持続方向行の集合ではない。',
        参照SHA256=before, 入力ソース前後不変=True, 売買再生=False,
        新損益読取=False, 現在保存物使用=False, API取得数=0)
    (HERE/'band_subset_audit.json').write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(dict(全監査合格=True, 対応集合数=len(rows)), flush=True)


if __name__ == '__main__':
    main()
