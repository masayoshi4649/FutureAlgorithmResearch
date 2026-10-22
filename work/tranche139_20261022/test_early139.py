"""早期入口を人工価格だけで確認する。市場データの金融再生は行わない。"""

import copy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

import early139


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def packet(kind='Day', seconds=4200, shift=.5):
    """
    機能: 継続上昇する二市場の人工原行を既存入力形式へ変換する。
    引数: kind(str)はDay/Night、seconds(int)は長さ、shift(float)は相手時刻のずれ。
    返り値: dictはinputs/quotesを持つ人工一場。
    """
    date = '2026-10-22'
    clock = '08:45:00' if kind == 'Day' else '17:00:00'
    start = datetime.fromisoformat(date + 'T' + clock).replace(tzinfo=ZoneInfo('Asia/Tokyo')).timestamp()
    us = datetime.fromisoformat(date + 'T22:30:00').replace(tzinfo=ZoneInfo('Asia/Tokyo')).timestamp()
    value = dict(inputs={}, quotes={})
    for symbol, offset, scale, tick in (('NK225', 0., 1., 10.), ('TOPIX', shift, .05, .5)):
        delta = np.arange(seconds + 1, dtype=float) + offset
        times = start + delta
        mid = 10000. * scale + delta * .4 * scale
        key = (date + '_' + kind, symbol)
        value['inputs'][key] = dict(session=key[0], time_s=times, last=mid.copy(),
                                   start=start, us_open=us, tick=tick)
        value['quotes'][key] = dict(bid=mid - tick * .5, ask=mid + tick * .5,
                                   quote_valid=np.ones(len(times), dtype=bool))
    return value


def direct(price, common, hold=15., mechanism='support', candidate_until=None):
    """
    機能: 支持の再成立と戻り確認の状態遷移を分離した人工特徴を作る。
    引数: price/common(ndarray)は中値と共通方向、hold(float)、mechanism(str)、candidate_until(float/None)。
    返り値: ndarrayは新規候補。
    """
    size = len(price)
    times = np.arange(size, dtype=float)
    market = np.ones((size, 12))
    market[:, 4:8] = common[:, None]
    features = np.ones((size, 9))
    features[:, 5] = 110.
    features[:, 6] = 90.
    ready = dict(time_s=times, atr=np.full(size, 2.), market=market,
                 good=np.ones(size, dtype=bool), price=price, phase=np.ones(size, dtype=np.int64),
                 quotes=dict(bid=price - .1, ask=price + .1), minute_features=features,
                 peer_minute_features=features, window_start=0., candidate_until=float(size) if candidate_until is None else candidate_until, window_end=float(size + 1))
    return early139.candidates({'NK225': ready}, dict(mechanism=mechanism, hold=hold, cooldown=300.))['NK225']['core_candidates']


def main():
    """
    機能: 未確定足排除・厳密過去接続・新成立・戻り確認を人工価格で確認する。
    引数: なし。
    返り値: None。実装SHA256付きの人工確認JSONを保存する。
    """
    checks = []

    def check(name, condition):
        """
        機能: 人工確認の真偽を記録し、偽なら直ちに停止する。
        引数: name(str)、condition(bool)。
        返り値: None。
        """
        assert condition, name
        checks.append(name)

    data = packet()
    prepared = early139.prepare(data)
    for symbol, ready in prepared.items():
        elapsed = ready['time_s'] - ready['window_start']
        check(symbol + 'の三足前ATR未公開', np.isnan(ready['atr'][elapsed < 180.]).all())
        check(symbol + 'の三足後ATR公開', np.isfinite(ready['atr'][elapsed >= 180.]).all())
        check(symbol + 'のEMA8準備', np.isnan(ready['minute_features'][elapsed < 480., 1]).all())
        check(symbol + 'のEMA20準備', np.isnan(ready['minute_features'][elapsed < 1200., 3]).all())
        known = ready['market'][:, 11] == 1.
        check(symbol + 'の相手厳密過去', (ready['market'][known, 8] < ready['time_s'][known]).all())
        check(symbol + 'の相手鮮度', (ready['time_s'][known] - ready['market'][known, 8] <= 15.).all())
        check(symbol + 'の日中窓', ready['candidate_until'] - ready['window_start'] == 3600. and ready['window_end'] - ready['window_start'] == 3900.)
    for mechanism, first_possible in (('support', 180.), ('ema38', 480.), ('ema520', 1200.)):
        result = early139.candidates(prepared, dict(mechanism=mechanism, hold=15., cooldown=300.))
        for symbol, ready in result.items():
            orders = ready['core_candidates']
            check(symbol + mechanism + 'の継続支持を一度だけ採用', len(orders) == 1)
            check(symbol + mechanism + 'の準備後成立', orders[0, 10] - ready['window_start'] >= first_possible + 15.)
            check(symbol + mechanism + 'の判断後約定', np.all(orders[:, 1] < orders[:, 0]))

    # ----------------------------------------
    # 原行の将来差替えと現在足の変化が、既知特徴へ遡らないことを確認する。
    changed = copy.deepcopy(data)
    for key, ready in changed['inputs'].items():
        tail = ready['time_s'] > ready['start'] + 1500.
        changed['quotes'][key]['bid'][tail] += 1000.
        changed['quotes'][key]['ask'][tail] += 1000.
    later = early139.prepare(changed)
    for symbol, ready in prepared.items():
        prefix = ready['time_s'] <= ready['window_start'] + 1500.
        check(symbol + 'の特徴接頭不変', np.array_equal(ready['minute_features'][prefix], later[symbol]['minute_features'][prefix], equal_nan=True))
        check(symbol + 'の二市場接頭不変', np.array_equal(ready['market'][prefix], later[symbol]['market'][prefix], equal_nan=True))
    changed = copy.deepcopy(data)
    nkkey = next(key for key in changed['inputs'] if key[1] == 'NK225')
    changed['quotes'][nkkey]['bid'][330] += 10000.
    changed['quotes'][nkkey]['ask'][330] += 10000.
    altered = early139.prepare(changed)['NK225']
    check('現在足をATRへ入れない', np.array_equal(prepared['NK225']['minute_features'][:360], altered['minute_features'][:360], equal_nan=True))
    check('足確定後にだけ変化を反映', altered['atr'][360] > prepared['NK225']['atr'][360])

    # ----------------------------------------
    # 同時刻の相手を除き、欠損足と古い板を不明として扱う。
    equal = early139.prepare(packet(shift=0.))
    for symbol, ready in equal.items():
        known = ready['market'][:, 11] == 1.
        check(symbol + 'の同時刻相手排除', np.all(ready['market'][known, 8] < ready['time_s'][known]))
    missing = copy.deepcopy(data)
    for key in missing['inputs']:
        missing['quotes'][key]['quote_valid'][720:780] = False
    missing_ready = early139.prepare(missing)
    for symbol, ready in missing_ready.items():
        elapsed = ready['time_s'] - ready['window_start']
        check(symbol + 'の欠損足後再準備', np.isnan(ready['atr'][(elapsed >= 780.) & (elapsed < 960.)]).all())
    peer_gap = copy.deepcopy(data)
    tpkey = next(key for key in peer_gap['inputs'] if key[1] == 'TOPIX')
    keep = np.ones(len(peer_gap['inputs'][tpkey]['time_s']), dtype=bool)
    keep[300:400] = False
    for field in ('time_s', 'last'):
        peer_gap['inputs'][tpkey][field] = peer_gap['inputs'][tpkey][field][keep]
    for field in ('bid', 'ask', 'quote_valid'):
        peer_gap['quotes'][tpkey][field] = peer_gap['quotes'][tpkey][field][keep]
    gap_ready = early139.prepare(peer_gap)['NK225']
    check('十五秒を超える相手板を拒否', np.all(gap_ready['market'][316:400, 11] == 0.))

    # ----------------------------------------
    # 価格を上下反転しても、方向以外の入口時刻は変えない。
    mirrored = copy.deepcopy(data)
    for key, quotes in mirrored['quotes'].items():
        center = 10000. if key[1] == 'NK225' else 500.
        old_bid = quotes['bid'].copy()
        quotes['bid'] = 2. * center - quotes['ask']
        quotes['ask'] = 2. * center - old_bid
    mirrored_ready = early139.prepare(mirrored)
    for mechanism in ('support', 'ema38', 'ema520'):
        normal = early139.candidates(prepared, dict(mechanism=mechanism))
        reverse = early139.candidates(mirrored_ready, dict(mechanism=mechanism))
        for symbol in normal:
            left, right = normal[symbol]['core_candidates'], reverse[symbol]['core_candidates']
            check(symbol + mechanism + 'の上下対称時刻', np.array_equal(left[:, :2], right[:, :2]))
            check(symbol + mechanism + 'の上下対称方向', np.array_equal(left[:, 3], -right[:, 3]))

    # ----------------------------------------
    # 休止中の成立を後から拾わず、戻りのない突破も戻り確認と混同しない。
    common = np.ones(500)
    common[21:26] = 0.
    common[330:341] = 0.
    orders = direct(np.full(500, 100.), common)
    check('休止中成立は消費し再成立だけ採用', np.array_equal(orders[:, 1], np.array([15., 356.])))
    boundary = direct(np.full(100, 100.), np.ones(100), hold=19., candidate_until=20.)
    check('期限前発注を期限後の次気配で約定', len(boundary) == 1 and boundary[0, 1] == 19. and boundary[0, 0] == 20.)
    boundary = direct(np.full(100, 100.), np.ones(100), hold=20., candidate_until=20.)
    check('期限以後の新発注判断は停止', len(boundary) == 0)
    trend = np.full(100, 109.)
    trend[10:] = 112.
    check('突破だけで戻りなしは不採用', len(direct(trend, np.ones(100), mechanism='retest')) == 0)
    retest = trend.copy()
    retest[20:30] = 110.2
    orders = direct(retest, np.ones(100), mechanism='retest')
    check('突破戻り再突破を採用', len(orders) == 1 and orders[0, 1] == 45.)
    reflected = 200. - retest
    reverse = direct(reflected, -np.ones(100), mechanism='retest')
    check('戻り確認の上下対称', np.array_equal(orders[:, :2], reverse[:, :2]) and orders[0, 3] == -reverse[0, 3])
    failed = retest.copy()
    failed[20:30] = 108.
    check('帯の大幅逆行後は旧設計失効', len(direct(failed, np.ones(100), mechanism='retest')) == 0)
    night = early139.prepare(packet(kind='Night', seconds=21000))
    for symbol, ready in night.items():
        check(symbol + 'の米国前固定窓', ready['candidate_until'] - ready['window_start'] == 18600. and ready['window_end'] - ready['window_start'] == 18900.)
    sources = {}
    for path in (HERE / 'early139.py', Path(__file__).resolve()):
        sources[path.relative_to(ROOT).as_posix()] = sha256(path.read_bytes()).hexdigest()
    output = dict(結果='全件合格', 人工確認数=len(checks), 確認=checks, 実装=sources, 金融再生=0, API=0, 実注文=0)
    (HERE / '早期入口_人工確認.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(結果=output['結果'], 人工確認数=len(checks)), ensure_ascii=False))


if __name__ == '__main__':
    main()
