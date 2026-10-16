"""人工価格列で実返済を起点とする再準備と動的幅の境界を反証する。"""

from datetime import datetime, timedelta, timezone

import numpy as np

from support import components, compare_prefix, clip, save, source_hashes


JST = timezone(timedelta(hours=9))


def fixture(prices, offsets, *, reflected=False, source=None, bad=None, valid=None,
            anchor='2026-10-02T09:40:00+09:00', gate=None):
    """
    機能: 既知のATRと公開行だけを持つ人工原板・入口特徴を組み立てる。
    引数: prices/offsets (list[float])、reflected (bool)、source/bad/valid/gate (list|None)、anchor (str)。
    返り値: tuple[dict,dict]の原板素材・既公開特徴。
    """
    n = len(prices)
    sign = -1 if reflected else 1
    price = np.asarray(prices, float)
    if reflected:
        price = 200. - price
    first = datetime.fromisoformat(anchor).timestamp()
    stamps = first + np.asarray(offsets, float)
    zero = np.zeros(n, np.int8)
    missing = np.full(n, -1, np.int64)
    state = np.full(n, sign, np.int8)
    ready = dict(session='人工境界', symbol='TOPIX', time_s=stamps, last=price,
        atr=np.full(n, 4.), tick=.5, seq=np.arange(n, dtype=np.int64),
        start=first-3600., limit=stamps[-1]+7200., session_close=stamps[-1]+7800.,
        us_open=first+100000.)
    raw_bad = zero.copy() if bad is None else np.asarray(bad, np.int8)*sign
    raw_source = missing.copy() if source is None else np.asarray(source, np.int64)
    validity = np.ones(n, bool) if valid is None else np.asarray(valid, bool)
    feature = dict(columns=(state, raw_bad, raw_source, zero.copy(), missing.copy(), np.zeros(n, bool)),
        valid=validity, gate=np.ones(n, bool) if gate is None else np.asarray(gate, bool),
        ema=(state, np.arange(n), np.arange(n), np.ones(n, bool)),
        joint=dict(direction=zero.copy(), source=missing.copy(), peer_source=missing.copy(),
                   valid=np.zeros(n, bool), peer_row=missing.copy()))
    return ready, feature


def check_source_order(result):
    """
    機能: 全新規・返済が旧観測の注文根拠に従い、両影も同じ公開順を守るか確認する。
    引数: result (dict)。
    返り値: None。不正で停止する。
    """
    for label, value in [('実玉', result)] + [(k, result[k]) for k in ('shadow', 'normal_shadow') if k in result]:
        orders = value.get('orders')
        if orders is not None and len(orders):
            assert np.all(orders[:, 1] < orders[:, 0]), label
        for row in value.get('entry_preparations', []):
            assert row[3] < row[1], label


def reentry_boundaries(strategy, configs):
    """
    機能: 返済と同時計の次行、秒境界直前/丁度、観測飛越を売買反射付きで検査する。
    引数: strategy (module)、configs (dict[str,dict])。
    返り値: list[dict]の合格証跡。
    """
    checks = []
    for clock, cooldown in (('A0', 0.), ('A1', 60.), ('A5', 300.)):
        if cooldown == 0:
            offsets = [0., 1., 2., 3., 3., 3., 4., 5.]
            prices = [100., 101., 106., 104., 100., 101., 106., 104.]
            expected_prepare, expected_fill = 4, 5
        else:
            offsets = [0., 1., 2., 3., 3.+cooldown-1., 3.+cooldown,
                       3.+cooldown, 4.+cooldown, 5.+cooldown]
            prices = [100., 101., 106., 104., 100., 100., 101., 106., 104.]
            expected_prepare, expected_fill = 5, 6
        for reflected in (False, True):
            for observed in (False, True):
                ready, feature = fixture(prices, offsets, reflected=reflected)
                config = configs['T2_'+clock]
                result, _ = strategy.play(config, ready, feature, observed=observed)
                check_source_order(result)
                entries = result['orders'][result['orders'][:, 7] == 1]
                assert entries[:, 0].astype(int).tolist() == [1, expected_fill]
                assert result['prepare_events'][:, 1].astype(int).tolist() == [0, expected_prepare]
                first = result['reentry_events'][0]
                assert first[0] == 3 and first[1] == 4
                assert first[2] == ready['time_s'][3] + cooldown
                checks.append(dict(検査='同時計次行と休止境界', 条件=config['id'], ショート=reflected,
                    観測約定=observed, 全返済行=3, 新準備行=expected_prepare, 再新規行=expected_fill, 合格=True))
        # ----------------------------------------
        # 返済後の次観測が休止末を飛び越しても、反映時刻から休止を再計算しない。
        offsets = [0., 1., 2., 3., 3.+cooldown+90., 4.+cooldown+90., 5.+cooldown+90., 6.+cooldown+90.]
        ready, feature = fixture([100., 101., 106., 104., 100., 101., 106., 104.], offsets)
        result, _ = strategy.play(configs['T2_'+clock], ready, feature, observed=True)
        entries = result['orders'][result['orders'][:, 7] == 1]
        assert entries[:, 0].astype(int).tolist() == [1, 5]
        assert result['reentry_events'][0, 2] == ready['time_s'][3]+cooldown
        checks.append(dict(検査='次観測の90秒飛越でも実返済時計を保持', 条件='T2_'+clock, 合格=True))
    return checks


def dynamic_boundaries(strategy, configs):
    """
    機能: T4の保有後新根拠・MFE境界・次行有効・解除禁止を検査する。
    引数: strategy (module)、configs (dict[str,dict])。
    返り値: list[dict]の合格証跡。
    """
    checks = []
    prices = [100., 101., 105., 104.5, 104., 103., 100.]
    offsets = list(map(float, range(len(prices))))
    for reflected in (False, True):
        for observed in (False, True):
            for origin, expected in ((0, False), (1, False), (2, True)):
                sources = [-1, -1, origin, origin, origin, origin, origin]
                bad = [0, 0, -1, 1, 1, 1, 1]
                ready, feature = fixture(prices, offsets, reflected=reflected, source=sources, bad=bad)
                result, _ = strategy.play(configs['T4_A0'], ready, feature, observed=observed)
                check_source_order(result)
                events = result['dynamic_events']
                assert bool(len(events)) == expected, (origin, events)
                if expected:
                    assert len(events) == 1
                    assert events[0, 0] == 2 and events[0, 2] == 2
                    assert events[0, 4] == 1. and events[0, 6] == .5
                    # 短縮判断を当行価格へ遡及適用しない。
                    assert not np.any((result['orders'][:, 7] == 0) & (result['orders'][:, 0] == 2))
                    trail = result['shadow']['plans'][:, 13]
                    assert np.isfinite(trail[2])
                    assert (trail[3]-trail[2])*(-1 if reflected else 1) >= 0
                for count in (2, 3, 4, 5):
                    part, _ = strategy.play(configs['T4_A0'], clip(ready,count,len(prices)),
                        clip(feature,count,len(prices)), observed=observed)
                    compare_prefix(result, part, count)
                checks.append(dict(検査='T4の新規以前/同じ行を除外し1ATR丁度で短縮、次行有効',
                    根拠行=origin, ショート=reflected, 観測約定=observed, 短縮=expected, 合格=True))
    return checks


def quiet_boundaries(strategy, configs):
    """
    機能: 静観の開始・終了と欠測飛越で古い新規の復活や同観測再建てを拒否する。
    引数: strategy (module)、configs (dict[str,dict])。
    返り値: list[dict]の合格証跡。
    """
    checks = []
    config = configs['T2_A0']
    cases = [
        dict(name='保有を窓開始で返済し窓終了後に新準備',
             offsets=[0, 1, 2, 4, 5, 6, 1804, 1805, 1806, 1807, 1808],
             prices=[100,101,104,104,104,104,104,100,101,106,104], entries=[1,8], prepares=[0,7], force=4),
        dict(name='窓全体の観測欠測でも古い待機を新規約定させない',
             offsets=[0,1,1806,1807,1808,1809],
             prices=[100,100,102,103,108,106], entries=[4], prepares=[0,3], force=None),
        dict(name='窓全体の観測欠測では終了後の初観測で実返済して次観測から準備',
             offsets=[0,1,1806,1807,1808,1809,1810],
             prices=[100,101,102,100,101,106,104], entries=[1,4], prepares=[0,3], force=2),
    ]
    for case in cases:
        for reflected in (False, True):
            ready, feature = fixture(case['prices'], case['offsets'], reflected=reflected,
                                     anchor='2026-10-02T22:14:55+09:00')
            result, _ = strategy.play(config, ready, feature, observed=True)
            check_source_order(result)
            orders = result['orders']
            assert orders[orders[:,7]==1,0].astype(int).tolist() == case['entries'], case['name']
            assert result['prepare_events'][:,1].astype(int).tolist() == case['prepares'], case['name']
            forced = orders[orders[:,6]==71]
            if case['force'] is None:
                assert len(forced) == 0
            else:
                assert forced[:,0].astype(int).tolist() == [case['force']]
            for count in range(2,len(ready['last'])):
                part, _ = strategy.play(config,clip(ready,count,len(ready['last'])),
                    clip(feature,count,len(ready['last'])),observed=True)
                compare_prefix(result,part,count)
            checks.append(dict(検査=case['name'], ショート=reflected, 合格=True))
    return checks


def main():
    """
    機能: 人工列で公開順・時計・短縮を点検し、損益順位を計算せず保存する。
    引数: なし。
    返り値: None。
    """
    strategy, catalog, _, _ = components()
    strategy.base.integration.reference.initialize()
    hashes = source_hashes()
    configs = {v['id']: v for v in catalog.catalog()}
    checks = reentry_boundaries(strategy, configs)
    checks += dynamic_boundaries(strategy, configs)
    checks += quiet_boundaries(strategy, configs)
    assert source_hashes() == hashes
    save('実返済再参加と動的幅の人工境界.json', dict(全合格=True, 検査=checks, 実装SHA256=hashes))
    print('人工境界', len(checks), '件合格', flush=True)


if __name__ == '__main__':
    main()
