"""旧入力を保持し追加場を含む全過去端点と反対証拠価格を独立に照合する。"""

from bisect import bisect_left
from pathlib import Path

import numpy as np

import common


def endpoint(targets, times, eligible, reset):
    """
    機能: 厳密過去の最新時計の先頭だけを採用し古い有効行への救済を禁止する。
    引数: targets/times (ndarray[float])、eligible/reset (ndarray[bool])。
    返り値: ndarray[int32] の端点行。30秒を超える行は欠測。
    """
    result = np.full(len(targets), -1, np.int32)
    stamps = times.tolist()
    for i, target in enumerate(targets):
        previous = bisect_left(stamps, float(target)) - 1
        if previous < 0:
            continue
        row = bisect_left(stamps, stamps[previous])
        if eligible[row] and not reset[row] and 0 < target - stamps[row] <= 30:
            result[i] = row
    return result


def main():
    """
    機能: 全62口座の厳密端点・現在値・30秒300秒の価格と気配変化を検査する。
    引数: なし。
    返り値: None。取引又は損益の計算・閲覧を行わない。
    """
    import sys
    sys.path.insert(0, str(common.WORK))
    import data
    value = data.load_inputs()
    records = []
    for key, record in sorted(value['prices'].items()):
        session, symbol = key
        market = value['grids'][session]['markets'][symbol]
        grid = value['grids'][session]['grid']
        feature = value['features'][key]
        times, bid, ask = record['time_s'], record['bid'], record['ask']
        assert (np.diff(times) >= 0).all() and (np.diff(record['seq']) > 0).all()
        now = endpoint(grid - 1., times, feature['quality'], feature['reset'])
        np.testing.assert_array_equal(now, market['current']['index'])
        good = now >= 0
        assert (times[now[good]] < (grid - 1)[good]).all()
        assert (np.searchsorted(times, times[now[good]], side='left') == now[good]).all()
        for saved, raw in [('last','price'), ('bid','bid'), ('ask','ask')]:
            common.same(market['current'][saved][good], record[raw][now[good]])
        common.same(market['current']['mid'][good], (bid[now[good]]+ask[now[good]])/2)
        compared = 0
        for seconds in (30, 300):
            window = market['windows'][seconds]
            old = endpoint(grid - 1. - seconds, times, feature['quality'], feature['reset'])
            np.testing.assert_array_equal(old, window['old'])
            np.testing.assert_array_equal(now, window['now'])
            accepted = window['source_valid']
            assert ((now[accepted] >= 0) & (old[accepted] >= 0) & (old[accepted] < now[accepted])).all()
            current_mid = (bid[now[accepted]]+ask[now[accepted]])/2
            past_mid = (bid[old[accepted]]+ask[old[accepted]])/2
            common.same(window['ret_bp'][accepted], (current_mid/past_mid-1)*10000)
            common.same(window['bid_change_ticks'][accepted], (bid[now[accepted]]-bid[old[accepted]])/record['tick'])
            common.same(window['ask_change_ticks'][accepted], (ask[now[accepted]]-ask[old[accepted]])/record['tick'])
            compared += int(accepted.sum())
        reference = value['metadata']['references']['|'.join(key)]['ref_open']
        assert reference['known_from_i'] == 0
        assert reference['source_time'] <= times[0] and reference['reference_time'] <= times[0]
        records.append(dict(session=session, symbol=symbol, 原板行=len(times), 過去格子数=len(grid),
                            既知現在=int(good.sum()), 二窓価格証拠=compared, tick=record['tick'],
                            始値既知行=reference['known_from_i']))
        print(f'{session} {symbol} 厳密端点・両気配逆進行の価格証拠合格', flush=True)
    common.save('全62口座の厳密過去端点と二市場価格気配証拠の独立検査.json',
                dict(全合格=True, 口座=records, 完結損益計算=0, 損益閲覧=0, 現在API取得=0, 実注文=0,
                     制約='原板保存順を受信順の代理とし、CurrentPriceTimeを時計とする。真の受信時刻を証明しない。',
                     SHA256=common.fingerprint([Path(__file__),Path(common.__file__),*value['paths']])))


if __name__ == '__main__':
    main()
