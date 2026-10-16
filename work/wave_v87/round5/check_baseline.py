"""閾値.05の四対照を、round3の全配列へ一致確認する。"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import strategy
import catalog


def compare(before, after, prefix=''):
    """
    機能: 元結果に含まれる全配列を再帰し、全要素と形状の一致を検査する。
    引数: before/after (dict)、prefix (str) は項目名。
    返り値: list[str] の確認済み配列名。
    """
    checked = []
    for name, value in before.items():
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(value, after[name], err_msg=prefix+name)
            checked.append(prefix+name)
        elif isinstance(value, dict):
            checked.extend(compare(value, after[name], prefix+name+'.'))
    return checked


def fingerprint(short):
    """
    機能: 共有短期配列の全列を指紋化して書換えを検出する。
    引数: short (dict[str,ndarray]) は一口座の公開特徴。
    返り値: dict[str,str] のSHA256。
    """
    return {name: hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()
            for name, value in short.items()}


def main(sessions):
    """
    機能: 許可された既存閾値だけを二モデル再生し、原版一致と共有配列不変を確かめる。
    引数: sessions (list[str]) は対象場。空なら全60口座。
    返り値: None。新閾値.25/.5の実データ売買は実行しない。
    """
    inputs, signals, hashes = strategy.prepare.old.load_inputs(verify=True)
    features = strategy.initialize(inputs, signals)
    configs = [c for c in catalog.catalog() if c['threshold_atr'] == .05]
    old_catalog = strategy.module('wave87_round5_comparator_catalog', HERE.parent/'round3/catalog.py')
    reference = {c['id']: c for c in old_catalog.catalog()}
    keys = [key for key in sorted(inputs) if not sessions or key[0] in sessions]
    assert keys
    checks = []
    for key in keys:
        before_hash = fingerprint(features[key]['short'])
        for observed in (True, False):
            for config in configs:
                before, settings = strategy.prior.play(reference[config['round3_id']], inputs[key], features[key], observed)
                after, after_settings = strategy.play(config, inputs[key], features[key], observed)
                assert settings == after_settings
                fields = compare(before, after)
                assert fingerprint(features[key]['short']) == before_hash
                checks.append(dict(ID=config['id'], 元ID=config['round3_id'], セッション=key[0], 銘柄=key[1],
                                   観測約定=observed, 全配列一致=True, 共有特徴不変=True, 配列=fields))
        print(key[0], key[1], '四対照・両約定の全配列一致', flush=True)
    output = dict(全合格=True, 全60口座=len(keys) == 60, 照合数=len(checks), 新強度売買再生=False,
                  入力SHA256=hashes, 元特徴指紋=strategy.prepare.old.sha(strategy.prepare.OUT/'short.pkl'), 検査=checks)
    name = '閾値005四対照の全配列一致.json' if not sessions else '閾値005四対照の先行照合.json'
    (HERE/name).write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='新閾値の売買を行わず既存四対照の全配列を照合する')
    parser.add_argument('--sessions', default='')
    arguments = parser.parse_args()
    main([value for value in arguments.sessions.split(',') if value])
