"""旧E01の二十三場を、既存素材と既存信号生成器から再構成する。"""

from pathlib import Path
import importlib.util
import pickle
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def module() -> object:
    """機能: 過去の追加再生実装を変更せず読み込む。

    引数: なし。返り値: 読込モジュール(object)。
    """
    path = ROOT / 'work/wave_v50/update_20261001_day/replay_added_session.py'
    spec = importlib.util.spec_from_file_location('e01_v67_prior', path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


def main() -> None:
    """機能: 保存素材の重複を拒否し、旧二十三場の入力と信号を保存する。

    引数: なし。返り値: なし(None)。
    """
    prior = module()
    folders = [ROOT / 'work/wave_v47',
        ROOT / 'work/wave_v48/update_20260930', ROOT / 'work/wave_v48/update_20261001',
        ROOT / 'work/wave_v50/update_20261001_day', ROOT / 'work/wave_v50/update_20261002_two',
        ROOT / 'work/wave_v50/update_20261007_added']
    inputs, features = {}, {}
    for i, folder in enumerate(folders):
        prefix = '' if i == 0 else 'new_'
        more = pickle.loads((folder / (prefix + 'inputs.pkl')).read_bytes())
        assert not set(more) & set(inputs)
        inputs.update(more)
        features.update(pickle.loads((folder / (prefix + 'features_depth.pkl')).read_bytes()))
    assert len(inputs) == 46
    prior.previous.HERE = HERE / 'prepared/old23'
    prior.previous.HERE.mkdir(parents=True, exist_ok=True)
    signals = prior.previous.signals(inputs, features, ROOT)
    target = prior.previous.HERE
    for name, value in (('new_inputs.pkl', inputs), ('new_features_depth.pkl', features), ('signals.pkl', signals)):
        (target / name).write_bytes(pickle.dumps(value, pickle.HIGHEST_PROTOCOL))
    print('旧23場の入力・方向・途中判断を再構成しました', flush=True)


if __name__ == '__main__':
    main()
