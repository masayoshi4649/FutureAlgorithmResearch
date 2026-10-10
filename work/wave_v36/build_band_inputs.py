"""監査を通過した価格帯信号を、損益を見る前に全条件保存して指紋化する。"""

from __future__ import annotations

import argparse
from pathlib import Path
import pickle

import numpy as np

import band_runner as runner
import band_signals as signals

HERE, ROOT = runner.HERE, runner.ROOT


def build() -> dict:
    """機能: 新信号90×時計3と旧H019×時計3を全26原本行へ保存する。

    引数: なし。返り値: 入力固定前の成果記録 (dict)。注文再生を呼ばない。
    """
    sources = [HERE / 'band_signals.py', HERE / 'band_design.py', HERE / 'events.pkl',
        HERE.parent / 'wave_v23/inputs.pkl', HERE.parent / 'wave_v23/features_depth.pkl']
    before = {p: runner.digest(p) for p in sources}
    inputs = pickle.loads((HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    features = pickle.loads((HERE.parent / 'wave_v23/features_depth.pkl').read_bytes())
    events = pickle.loads((HERE / 'events.pkl').read_bytes())
    assert len(inputs) == len(features) == len(events) == 26 and set(inputs) == set(events)
    for folder in ('directions', 'provenance', 'episodes'):
        (HERE / folder).mkdir(exist_ok=True)
    paths, activity, count = [], [], 0
    for scale in (.8, 1., 1.2):
        signals.clear_cache()
        for spec in runner.design.catalog():
            identifier = spec['id'] + f'__C{round(scale * 100):03d}'
            result = signals.build(spec, inputs, features, events, clock_scale=scale)
            assert set(result) == set(inputs)
            states, provenance, episodes = {}, {}, []
            for key, values in result.items():
                label, ready = '|'.join(key), inputs[key]
                direction, source, episode = (values[name] for name in ('direction', 'source_row', 'source_episode'))
                assert direction.dtype == np.int8 and len(direction) == len(ready['seq'])
                assert source.dtype == episode.dtype == np.int64
                assert source.shape == episode.shape == direction.shape
                assert np.isin(direction, (-1, 0, 1)).all()
                active = direction != 0
                assert np.all(source[~active] == -1) and np.all(episode[~active] == -1)
                assert np.all((source[active] <= ready['seq'][active]) & (source[active] >= 0))
                states[label] = direction
                provenance['source_row::' + label], provenance['source_episode::' + label] = source, episode
                episodes.append(dict(session=key[0], symbol=key[1], episodes=values['episodes'], activity=values['activity']))
                activity.append(dict(signal=spec['id'], clock_scale=scale, session=key[0], symbol=key[1], **values['activity']))
            state_path, proof_path = (HERE / folder / (identifier + '.npz') for folder in ('directions', 'provenance'))
            np.savez_compressed(state_path, **states)
            np.savez_compressed(proof_path, **provenance)
            episode_path = HERE / 'episodes' / (identifier + '.json.gz')
            runner.save(episode_path, episodes)
            paths += [state_path, proof_path, episode_path]
            count += 1
            print(f'方向保存 {count}/270 {identifier}', flush=True)
    for scale in (.8, 1., 1.2):
        label = f'H019__C{round(scale * 100):03d}'
        source = HERE.parent / 'wave_v35/entries' / (label + '.npz')
        target = HERE / 'directions' / (label + '.npz')
        with np.load(source, allow_pickle=False) as archive:
            assert set(archive.files) == {'|'.join(key) for key in inputs}
            for key in inputs:
                assert archive['|'.join(key)].dtype == np.int8 and len(archive['|'.join(key)]) == len(inputs[key]['seq'])
        target.write_bytes(source.read_bytes())
        assert runner.digest(target) == runner.digest(source)
        paths += [source, target]
    runner.save(HERE / '方向の作動件数.json.gz', activity)
    paths += [HERE / '方向の作動件数.json.gz', Path(__file__), HERE / 'band_signals.py', HERE / 'band_design.py',
        HERE / 'events.pkl', HERE / 'volume_quote_fixed.json', HERE / 'volume_quote_audit.json',
        HERE.parent / 'wave_v23/inputs.pkl', HERE.parent / 'wave_v23/features_depth.pkl']
    assert before == {p: runner.digest(p) for p in sources}, '入力作成中に実装又は素材が変わりました'
    artifact = dict(方向ファイル数=273, 新信号方向ファイル数=270, 旧比較方向ファイル数=3,
        新規根拠ファイル数=270, 新規区間明細数=270, 全26入力=True, 新損益再生=False,
        SHA256={p.relative_to(ROOT).as_posix(): runner.digest(p) for p in sorted(set(paths))})
    runner.save(HERE / 'input_artifacts.json', artifact)
    return artifact


def main() -> None:
    """機能: 明示指定時だけ全方向を作り、未監査の売買起動を許さない。

    引数: --build (bool)。返り値: なし (None)。入力固定は別の全監査接続後に行う。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', action='store_true', required=True)
    parser.parse_args()
    result = build()
    print({k: result[k] for k in ('方向ファイル数', '新信号方向ファイル数', '新損益再生')}, flush=True)


if __name__ == '__main__':
    main()
