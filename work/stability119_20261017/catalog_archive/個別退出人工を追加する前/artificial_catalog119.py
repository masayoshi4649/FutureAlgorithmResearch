"""18条件の形・過去窓・相手時計・未知と売買対称を合成分足だけで検査する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import catalog119 as subject

ROOT = HERE.parents[1]
CHECKS = []


def check(name: str, value: bool) -> None:
    """
    機能: 合成検査の成否を保存して不成立を停止する。
    引数: name(str)、value(bool) は内容と成否。
    返り値: None。実データや金融は呼ばない。
    """
    CHECKS.append(dict(項目=name, 合格=bool(value)))
    assert value, name


def same(name: str, actual: np.ndarray, expected: np.ndarray) -> None:
    """
    機能: NaNを未知のまま配列の値と形を比較する。
    引数: name(str)、actual/expected(ndarray) は内容・実値・期待値。
    返り値: None。誤差を用いた未来値の補正はしない。
    """
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-10, equal_nan=True, err_msg=name)
    check(name, actual.shape == expected.shape)


def fixture(symbol: str, kind: str, n: int = 150) -> dict:
    """
    機能: 118型の価格・出来高・公開行を持つ合成分足を作る。
    引数: symbol/kind(str)、n(int) は商品・経路型・長さ。
    返り値: dict[str,ndarray] は実市場と無関係な正常分足。
    """
    tick = subject.TICKS[symbol]
    center = 4000 if symbol == 'TOPIX' else 60000
    index = np.arange(n, dtype=float)
    if kind == 'trend':
        path = .7 * index + .4 * np.sin(index / 2)
    elif kind == 'range':
        path = 5 * np.sin(index / 5) + .4 * np.sin(index)
    elif kind == 'mixed':
        path = np.where(index < 50, .15 * index, np.where(index < 100, 7.5 + .9 * (index - 50), 52.5 - .8 * (index - 100)))
        path += 2 * np.sin(index / 5)
    else:
        path = np.zeros(n)
    close = center + path * tick
    opening = np.concatenate(([center], close[:-1])) if n else np.empty(0)
    return dict(t_s=1800000000. + 60 * np.arange(1, n + 1), open=opening,
        high=np.maximum(opening, close) + tick, low=np.minimum(opening, close) - tick,
        close=close, volume=100. + index % 7, volume_known=np.ones(n, bool), valid=np.ones(n, bool),
        anchor=close + .2 * tick, pub_raw_row=np.arange(n, dtype=np.int64) * 11 + 2,
        pub_price_time_s=1800000000. + 60 * np.arange(1, n + 1) + 1.)


def cut(bars: dict, n: int) -> dict:
    """
    機能: 合成足を同一位置で短い接頭へ切る。
    引数: bars(dict)、n(int) は合成足と長さ。
    返り値: dict は独立した接頭配列。
    """
    return {key: value[:n].copy() for key, value in bars.items()}


def mirrored(bars: dict, center: float) -> dict:
    """
    機能: 価格経路を中心に鏡映し、買売対称の別素材を作る。
    引数: bars(dict)、center(float) は足と中心。
    返り値: dict は高安を入れ替えた鏡映素材。
    """
    result = deepcopy(bars)
    for key in ('open', 'close', 'anchor'):
        result[key] = 2 * center - bars[key]
    result['high'] = 2 * center - bars['low']
    result['low'] = 2 * center - bars['high']
    return result


def reset_prices(bars: dict, close: np.ndarray, tick: float) -> dict:
    """
    機能: 手作り経路から整合した始値・高安・公開価格だけを再構成する。
    引数: bars(dict)、close(ndarray)、tick(float) は合成足と新経路と呼値。
    返り値: dict は実市場とは関係ない手作り素材。
    """
    result = deepcopy(bars)
    opening = np.r_[close[0], close[:-1]]
    result.update(open=opening, close=close, high=np.maximum(opening, close) + tick,
                  low=np.minimum(opening, close) - tick, anchor=close + .2 * tick)
    return result


def deliberate_examples(symbol: str) -> None:
    """
    機能: 各尺度の加重戻り・失敗離脱・遅行・乖離と持続・開場離脱の発火を確認する。
    引数: symbol(str) は合成商品の種類。
    返り値: None。作った経路で発火することを性能と数えない。
    """
    other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    tick = subject.TICKS[symbol]
    center = 4000 if symbol == 'TOPIX' else 60000
    baseline = fixture(symbol, 'flat', 180)
    peer = fixture(other, 'trend', 180)
    for length in subject.SCALES:
        point = length + 20
        close = np.full(180, float(center))
        close[point - length] = center - 12 * tick
        close[point - 1] = center - 15 * tick
        close[point] = center - 14 * tick
        current = reset_prices(baseline, close, tick)
        built = subject.build(current, peer, symbol, center + 20 * tick)
        position = next(i for i, spec in enumerate(built['specs']) if spec['id'] == f'CENTER_L{length:02d}')
        check('加重戻りの手作り買事象', built['entry'][position, point] == 1)
        failed = reset_prices(baseline, np.full(180, float(center)), tick)
        failed['low'][point] = center - 4 * tick
        built = subject.build(failed, peer, symbol, None)
        position = next(i for i, spec in enumerate(built['specs']) if spec['id'] == f'FAIL_L{length:02d}')
        check('失敗離脱の手作り買事象', built['entry'][position, point] == 1)
        ambiguous = deepcopy(failed)
        ambiguous['high'][point] = center + 4 * tick
        built = subject.build(ambiguous, peer, symbol, None)
        check('両側離脱は方向不明', built['entry'][position, point] == 0)
        close = np.full(180, float(center))
        close[point:] += 2 * tick
        lag = reset_prices(baseline, close, tick)
        built = subject.build(lag, peer, symbol, center + 20 * tick)
        for identity in (f'LAG_L{length:02d}', f'GAP_L{length:02d}'):
            position = next(i for i, spec in enumerate(built['specs']) if spec['id'] == identity)
            check('遅行又は乖離解消の手作り買事象', built['entry'][position, point] == 1)
        trend = subject.build(fixture(symbol, 'trend', 180), peer, symbol, None)
        for identity in (f'COMMON_L{length:02d}', f'OPEN_L{length:02d}'):
            position = next(i for i, spec in enumerate(trend['specs']) if spec['id'] == identity)
            check('持続又は開始離脱の手作り事象', np.any(trend['entry'][position] == 1))


def main() -> None:
    """
    機能: 六系統三尺度の因果性・型・符号・未知分離のpure検査と証跡を保存する。
    引数: なし。
    返り値: None。原入力・金融・API・旧台帳を読まない。
    """
    destination = HERE / '十八条件の接頭と相手時計及び六系統分離の純人工_v2.json'
    assert not destination.exists()
    proof = dict(全合格=False, 原入力=0, 既金融=0, 新金融=0, API=0)
    try:
        for symbol in ('TOPIX', 'NK225'):
            deliberate_examples(symbol)
            other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            center = 4000 if symbol == 'TOPIX' else 60000
            other_center = 60000 if other == 'NK225' else 4000
            for kind in ('trend', 'range', 'mixed', 'flat'):
                own, peer = fixture(symbol, kind), fixture(other, 'mixed')
                previous = center + 20 * subject.TICKS[symbol]
                before = deepcopy(own)
                full = subject.build(own, peer, symbol, previous)
                check('18条件と仕様一意', len(full['specs']) == len({v['id'] for v in full['specs']}) == 18)
                for key, dtype in (('entry', np.int8), ('exit_long', np.bool_), ('exit_short', np.bool_), ('valid', np.bool_), ('width', np.float64)):
                    check('型と形' + key, full[key].shape == (18, len(own['t_s'])) and full[key].dtype == dtype)
                for length in (0, 1, 5, 10, 20, 41, 60, 90, 120, 150):
                    prefix = subject.build(cut(own, length), peer, symbol, previous)
                    for key in ('entry', 'exit_long', 'exit_short', 'valid', 'width'):
                        same('接頭不変' + key, prefix[key], full[key][:, :length])
                mirror = subject.build(mirrored(own, center), mirrored(peer, other_center), symbol, 2 * center - previous)
                same('買売の鏡映entry', mirror['entry'], -full['entry'])
                same('買売の鏡映long', mirror['exit_long'], full['exit_short'])
                same('買売の鏡映short', mirror['exit_short'], full['exit_long'])
                same('幅の鏡映', mirror['width'], full['width'])
                for key in own:
                    same('原配列不変' + key, own[key], before[key])
                for value in (None, np.nan, np.inf, 0, False):
                    gap_unknown = subject.build(own, peer, symbol, value)
                    check('前参照未知はgap無信号', not gap_unknown['entry'][15:].any() and not gap_unknown['valid'][15:].any())
                    same('前参照未知は他系統を変更しない', gap_unknown['entry'][:15], full['entry'][:15])
                no_volume = deepcopy(own)
                no_volume['volume_known'][:] = False
                missing = subject.build(no_volume, peer, symbol, previous)
                check('量未知は加重中心だけ無信号', not missing['entry'][6:9].any() and not missing['valid'][6:9].any())
                for indexes in ((0, 6), (9, 18)):
                    same('量未知は価格源を停止しない', missing['entry'][indexes[0]:indexes[1]], full['entry'][indexes[0]:indexes[1]])
                no_peer = deepcopy(peer)
                no_peer['pub_price_time_s'] += 1000000
                excluded = subject.build(own, no_peer, symbol, previous)
                check('相手未来公開を除外', not excluded['entry'][:3].any() and not excluded['entry'][12:15].any())
                for indexes in ((3, 12), (15, 18)):
                    same('相手未知は単独源を停止しない', excluded['entry'][indexes[0]:indexes[1]], full['entry'][indexes[0]:indexes[1]])
                chosen = subject.peer_index(own, peer)
                for row, index in enumerate(chosen):
                    allowed = [i for i in range(len(peer['t_s'])) if peer['valid'][i] and peer['t_s'][i] <= own['t_s'][row] - 60
                               and peer['pub_price_time_s'][i] <= own['pub_price_time_s'][row]]
                    check('相手逐次期待', index == (allowed[-1] if allowed else -1))
                damaged = deepcopy(own)
                damaged['valid'][55] = False
                for key in ('open', 'high', 'low', 'close', 'anchor'):
                    damaged[key][55] = np.nan
                damaged['pub_raw_row'][55] = -1
                result = subject.build(damaged, peer, symbol, previous)
                for spec, valid in zip(result['specs'], result['valid']):
                    check('欠足後の幅準備を再開', not valid[55:55 + spec['scale'] + 1].any())
        proof.update(全合格=True, 検査数=len(CHECKS), 検査=CHECKS,
            source_SHA256={(HERE / name).relative_to(ROOT).as_posix(): hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                           for name in ('catalog119.py', 'artificial_catalog119.py')},
            scope='18条件の合成仕様確認。採用可否・黒字率・予測精度・利益は未測定。')
    except BaseException as error:
        proof.update(全合格=False, 検査数=len(CHECKS), 検査=CHECKS, error=repr(error))
        raise
    finally:
        destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=len(CHECKS), 原入力=0, 新金融=0, API=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
