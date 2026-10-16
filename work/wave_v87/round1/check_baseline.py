"""追加条件なしの新経路を旧P1と照合し、変更の交絡を防ぐ。"""
from pathlib import Path
import importlib.util
import json
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def module(name, path):
    """
    機能: 検査専用名で実装を読む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def compare(before, after, prefix=''):
    """
    機能: 辞書内の既存全配列を完全一致で検査する。
    引数: before/after(dict)、prefix(str)。
    返り値: list[str] の照合済み項目。
    """
    checked = []
    for key, value in before.items():
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(value, after[key], err_msg=prefix+key)
            checked.append(prefix+key)
        elif isinstance(value, dict):
            checked.extend(compare(value, after[key], prefix+key+'.'))
    return checked


def main():
    """
    機能: 基準R0_S75を全60口座と二約定モデルで照合する。
    引数: なし。
    返り値: None。新しい改修条件の損益は計算しない。
    """
    strategy = module('wave87_round1_strategy', HERE/'strategy.py')
    catalog = module('wave87_round1_catalog', HERE/'catalog.py')
    prepare = module('wave87_prepare', HERE.parents[1]/'wave_v85/prepare.py')
    import numba
    numba.config.CACHE_DIR = str(HERE/'cache')
    inputs, signals, fingerprints = prepare.load_inputs(verify=True)
    features = strategy.initialize(inputs, signals)
    conf = next(c for c in catalog.catalog() if c['id']=='R0_S75')
    source = module('wave87_prior_catalog_check', HERE.parents[1]/'wave_v86/phase2/catalog.py')
    oldconf = next(c for c in source.catalog() if c['id']=='T2_P1')
    rows = []
    for observed in (True, False):
        for key in sorted(inputs):
            old, oldsettings = strategy.prior.play(oldconf, inputs[key], features[key], observed)
            new, newsettings = strategy.play(conf, inputs[key], features[key], observed)
            assert oldsettings == newsettings
            checked = compare(old, new)
            rows.append(dict(session=key[0], symbol=key[1], observed=observed, fields=checked, 完全一致=True))
        print('観測約定' if observed else '指定約定', '全60口座一致', flush=True)
    out = dict(全合格=True, バイパスなし=True, 口座件数=len(rows), 新改修損益未計算=True,
        入力SHA256=fingerprints, 検査=rows)
    (HERE/'基準P1の全配列完全一致.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
