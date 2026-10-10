"""旧帯の時刻を変えず、公開済みの原本数量特徴だけで入口候補を比較する。"""

from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent/'wave_v40'


def _legacy_modules() -> tuple[object, object]:
    """機能: 旧価格品質・相手確認を別名で読み込み、同名モジュール汚染を残さない。

    引数: なし。返り値: 旧帯・旧入口のモジュール(tuple[module,module])。
    """
    def load(name: str, path: Path) -> object:
        """機能: 指定した実体だけを別名で読み込む。

        引数: name(str)、path(Path)。返り値: モジュール(module)。
        """
        definition = importlib.util.spec_from_file_location(name, path)
        assert definition is not None and definition.loader is not None
        value = importlib.util.module_from_spec(definition)
        definition.loader.exec_module(value)
        return value
    bands = load('_v42_旧帯', LEGACY/'band_events.py')
    previous = sys.modules.get('band_events')
    try:
        sys.modules['band_events'] = bands
        entry = load('_v42_旧入口', LEGACY/'entry_signals.py')
    finally:
        if previous is None:
            sys.modules.pop('band_events', None)
        else:
            sys.modules['band_events'] = previous
    assert Path(entry.__file__).resolve() == LEGACY/'entry_signals.py'
    assert entry.band_events is bands
    return bands, entry


legacy_bands, legacy_entry = _legacy_modules()


def band_settings(spec: dict) -> dict:
    """機能: 旧cacheと同一の帯設定を採否から分離して返す。

    引数: spec(dict)。返り値: 旧帯設定(dict)。
    """
    return legacy_entry.band_settings(spec)


def cache_key(spec: dict) -> str:
    """機能: 数量観測版や採否によらない旧正準キーを返す。

    引数: spec(dict)。返り値: 旧band_cacheのキー(str)。
    """
    return legacy_entry.cache_key(spec)


def peer_prices(events: dict) -> dict:
    """機能: 旧B12と同じ価格品質・5分窓の相手特徴を作る。

    引数: events(dict[str,ndarray])。返り値: 相手公開特徴(dict)。数量比率は参照しない。
    """
    return legacy_entry.peer_prices(events)


def peer_at(peer: dict, now: float, direction: int) -> tuple[bool, dict]:
    """機能: 旧B12と同じ追加60秒・鮮度120秒で相手確認を行う。

    引数: peer(dict)、now(float)、direction(int)。返り値: 合否と根拠(tuple[bool,dict])。
    """
    return legacy_entry.peer_at(peer, now, direction)


def feature_for(band: dict, panel: dict | None, source: str) -> dict:
    """機能: 旧帯の同一性と新比率の公開時刻を検査して使用特徴を選ぶ。

    引数: band(dict)、panel(dict|None)、source(str:old/strict/local)。返り値: 使用特徴(dict)。
    将来に確定する比率を過去の突破へ戻す入力は拒否する。
    """
    if source == 'old':
        return band['features']
    if source not in ('strict', 'local') or panel is None:
        raise ValueError('原本観測の版又は対応パネルがありません')
    for name in ('band_id', 'direction', 'price', 'atr', 'tick', 'created', 'terminal'):
        assert band[name] == panel[name], ('旧帯とパネルの対応不一致', name, band['band_id'])
    old = band['features']
    feature = panel['features_'+source]
    assert feature['two_trials_complete'] == old['two_trials_complete']
    assert feature['price_comparable'] == old['price_comparable']
    if not feature['two_trials_complete']:
        assert feature['quantity_comparable'] is False
        assert feature['u1'] is None and feature['u2'] is None
        return feature
    for name in ('b1', 'b2', 'price_weakens'):
        assert feature[name] == old[name], ('価格特徴を変更したパネル', name)
    trials = panel['trials']
    assert len(trials) == len(band['trials']) == 2
    available = []
    ratios = []
    for original, observed in zip(band['trials'], trials):
        assert original['complete'] and observed['complete_available']
        assert original['number'] == observed['number']
        assert original['start'] == observed['start'] and original['end'] == observed['end']
        end = original['end']['seq']
        assert observed['ratio_available_seq'] == end
        publication = observed['publications'][-1]
        assert publication['complete_available'] and publication['release_seq'] == end
        assert publication['material_last_seq'] <= publication['release_seq']
        assert publication['ready_index'] == original['end']['ready_index']
        ratio = observed['u_'+source]
        assert ratio == publication['u_'+source]
        if ratio is not None:
            assert np.isfinite(ratio) and ratio >= 0 and publication['decrease'] > 0
            assert publication['raw_quantity_known']
            if source == 'strict':
                assert publication['old_quantity_known_so_far']
        ratios.append(ratio)
        available.append(end)
    assert [feature['u1'], feature['u2']] == ratios
    assert feature['quantity_comparable'] == all(value is not None for value in ratios)
    assert feature['available_seq'] == max(available)
    if band['status'] == 'breakout':
        assert max(available) < band['terminal']['seq'], '突破後の比率で過去を救済しています'
    return feature


def eligible(band: dict, mode: str, feature: dict | None = None) -> bool:
    """機能: 完了後の初回突破に対し、数量可用性と条件の大小を分けて判定する。

    引数: band(dict)、mode(str)、feature(dict|None)。返り値: 条件採用(bool)。
    """
    if mode not in {'weaken', 'price_matched', 'price', 'all', 'quantity', 'last', 'mean', 'strengthen'}:
        raise ValueError('未定義の入口判定: '+str(mode))
    if band['status'] != 'breakout':
        return False
    feature = band['features'] if feature is None else feature
    if not feature['two_trials_complete'] or not feature['price_comparable']:
        return False
    if mode == 'all':
        return True
    price = feature['price_weakens'] is True
    if mode == 'price':
        return price
    if not feature['quantity_comparable']:
        return False
    u1, u2 = feature['u1'], feature['u2']
    if u1 is None or u2 is None or not np.isfinite([u1, u2]).all() or min(u1, u2) < 0:
        raise ValueError('比較可能とされた数量比率が不正です')
    if mode == 'price_matched':
        return price
    if mode == 'quantity':
        return bool(u2 < u1)
    if mode == 'weaken':
        return bool(price and u2 < u1)
    if mode == 'last':
        return bool(price and u2 < 1.)
    if mode == 'mean':
        return bool(price and (u1+u2)/2 < 1.)
    return bool(price and u2 > u1)


def direction_bit(seed: int, key: tuple[str, str], seq: int) -> int:
    """機能: 公開候補の原本seqだけから再現可能な方向符号を得る。

    引数: seed(int)、key(tuple[str,str])、seq(int)。返り値: -1又は1(int)。
    同seed・同機会の3方式では同じ符号を使い、実約定と将来損益を参照しない。
    """
    assert type(seed) is int and 0 <= seed < 64
    salt = f'v42|{seed}|{key[0]}|{key[1]}|{seq}'.encode('utf-8')
    return 1 if hashlib.sha256(salt).digest()[0] & 1 else -1


def make(spec: dict, key: tuple[str, str], inputs: dict, bands: list[dict],
         peer: dict, panel: list[dict] | dict | None = None) -> tuple[np.ndarray, dict]:
    """機能: 同じ帯群へ観測版と採否だけを適用し、公開済みの入口候補を作る。

    引数: spec/inputs/peer(dict)、key(tuple[str,str])、bands(list[dict])、
    panel(list[dict]|dict[int,dict]|None)は当該設定・市場の追加パネル。
    返り値: 原本行の符号と根拠(tuple[ndarray,dict])。保有・休止による採否は注文器で行う。
    """
    ready = inputs[key]
    pulse = np.zeros(len(ready['seq']), np.int8)
    counts = Counter()
    details = []
    source = spec['feature_source']
    band_ids = [band['band_id'] for band in bands]
    assert len(band_ids) == len(set(band_ids))
    if source == 'old':
        observed = {}
    else:
        if isinstance(panel, list):
            observed = {row['band_id']: row for row in panel}
            assert len(observed) == len(panel)
        elif isinstance(panel, dict):
            observed = panel
        else:
            raise ValueError('当該設定・市場の原本観測パネルが必要です')
        assert set(observed) == set(band_ids), 'パネルの帯集合が一致しません'
        assert all(identifier == value['band_id'] for identifier, value in observed.items())
    for band in bands:
        counts['全帯'] += 1
        counts['終了:'+band['status']] += 1
        feature = feature_for(band, observed.get(band['band_id']), source)
        counts['二試行完了'] += int(feature['two_trials_complete'])
        counts['板比較可能'] += int(feature['quantity_comparable'])
        completed_break = bool(band['status'] == 'breakout' and feature['two_trials_complete'] and feature['price_comparable'])
        counts['完了後の初回突破'] += int(completed_break)
        counts['完了後突破の板比較可能'] += int(completed_break and feature['quantity_comparable'])
        if not eligible(band, spec['mode'], feature):
            continue
        terminal = band['terminal']
        row = terminal['ready_index']
        direction = int(band['direction'])
        assert 0 <= row < len(pulse) and ready['seq'][row] == terminal['seq']
        assert ready['time_s'][row] == terminal['time_s']
        assert terminal['time_s'] > band['created']['time_s']
        assert len(band['trials']) == 2 and all(trial['complete'] for trial in band['trials'])
        assert terminal['event_index'] > band['trials'][1]['end']['event_index']
        counts['自己条件通過'] += 1
        confirmation = None
        if spec['peer']:
            okay, confirmation = peer_at(peer, terminal['time_s'], direction)
            if not okay:
                counts['相手確認不成立'] += 1
                continue
        if spec['invert']:
            direction = -direction
        if spec['seed'] is not None:
            direction *= direction_bit(spec['seed'], key, terminal['seq'])
        assert pulse[row] == 0, '同じ原本行に複数帯を採用'
        pulse[row] = direction
        counts['全候補'] += 1
        evidence = None
        if source != 'old':
            evidence = [dict(number=trial['number'], ratio_available_seq=trial['ratio_available_seq'],
                publication=trial['publications'][-1]) for trial in observed[band['band_id']]['trials']]
        details.append(dict(band_id=band['band_id'], decision=terminal, direction=direction,
            band_direction=band['direction'], price=band['price'], features=feature,
            feature_source=source, ratio_evidence=evidence, peer=confirmation))
    metadata = dict(段階件数=dict(counts), 候補=details, 母集団キー=cache_key(spec),
        数量観測=source, 口座保有休止前の候補=True)
    json.dumps(metadata, ensure_ascii=False, allow_nan=False)
    return pulse, metadata
