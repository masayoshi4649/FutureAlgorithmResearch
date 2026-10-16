"""予約後の悪い実約定・未知基準・期限と場末の競合を少数の正負原板で反証する。"""

from pathlib import Path
import traceback
import numpy as np

import artificial
import common
import compare_utils as checks
import financial
import runtime_oracle
import support


def profile(symbol: str, side: int, name: str) -> dict:
    """
    機能: 事前に定めた初回97/追加予約99の原板境界を変更し、全支持素材を再接続する。
    引数: symbol(str)、side(int)、name(str)は有限境界名。
    返り値: dict。将来損益から候補や境界時刻を選ばない人工入力。
    """
    value = artificial.fixture(symbol,1)
    record,signal = value['record'],value['signal']
    scale,peer_scale = (1.,20.) if symbol == 'TOPIX' else (20.,1.)
    if name == '悪い次気配':
        record['ask'][100] = 4040.*scale
        record['price'][100] = (record['bid'][100]+record['ask'][100])*.5
    elif name == '予約後の資格悪化':
        signal['reset'][100],signal['quality'][100] = True,False
        signal['entry_peer_bbo'][100,5] = 0.
    elif name == '実fill時の未知peer':
        signal['entry_peer_bbo'][97,5] = 0.
        record['bid'][98],record['ask'][98],record['price'][98] = 4027.*scale,4027.5*scale,4027.25*scale
        signal['entry_peer_bbo'][98,3:5] = [4027.*peer_scale,4027.5*peer_scale]
    elif name == '初回期限と追加':
        record['time_s'][100:] += 1785.
        record['limit'] = float(record['time_s'][-1])
        signal['grid'] = record['time_s'].copy()
        signal['entry_peer_bbo'][:,2] = record['time_s']-1.
    elif name == '場末と追加':
        record['time_s'][100:] += 236.
        record['limit'] = 1096.
        signal['grid'] = record['time_s'].copy()
        signal['entry_peer_bbo'][:,2] = record['time_s']-1.
    else:
        raise AssertionError(name)
    if side == -1:
        old_bid = record['bid'].copy()
        record['bid'],record['ask'] = 2*value['reference_open']-record['ask'],2*value['reference_open']-old_bid
        record['price'] = 2*value['reference_open']-record['price']
        signal['event'] *= -1
        peer = signal['entry_peer_bbo']
        old_bid = peer[:,3].copy()
        center = 80000. if symbol == 'TOPIX' else 4000.
        peer[:,3],peer[:,4] = 2*center-peer[:,4],2*center-old_bid
    helper = common.module('101人工境界の原支持素材',common.ROOT/'work/wave_v99/engine_preflight/support.py')
    key = record['session'],symbol
    helper.attach_support({key:value})
    support.verify_material(key,value['artificial_support_material'],value)
    return value


def main() -> None:
    """
    機能: 少数の予約競合を両商品/反射で独立原行oracleへ照合する。
    引数: なし。
    返り値: None。不合格を現在指紋付きで保存して停止。正式原板を使わない。
    """
    catalog = common.module('101境界固定条件',common.BASE/'catalog.py')
    strategy = common.module('101境界実本体',common.BASE/'strategy.py')
    config = next(c for c in catalog.catalog() if c['id'] == 'G1_Q1_X1')
    names = ('悪い次気配','予約後の資格悪化','実fill時の未知peer','初回期限と追加','場末と追加')
    paths = [common.BASE/name for name in ('engine.py','strategy.py','catalog.py','実装前の仕様明確化.json')]
    paths += [common.HERE/name for name in ('common.py','math_oracle.py','compare_utils.py','financial.py','support.py',
              'watch.py','runtime_oracle.py','artificial.py','boundaries.py')]
    signatures = common.fingerprints(paths)
    results = []
    for name in names:
        for symbol in common.SYMBOLS:
            for side in (1,-1):
                try:
                    value = profile(symbol,side,name)
                    key = value['record']['session'],symbol
                    output = strategy.play(config,key,{key:value})
                    runtime_oracle.compare(value,config,output)
                    financial.verify_account(value['record'],config,output)
                    orders = output['orders']
                    adds = orders[orders[:,8] == 16]
                    events = output['growth_events']
                    if name == '悪い次気配':
                        assert adds[0,0] == 100 and adds[0,1] == 99 and output['trades'][0,5] == 2
                        assert orders[-1,1] == 100 and orders[-1,0] == 101
                        if symbol == 'TOPIX':
                            checks.exact(output['trades'][0,11],-8165,'実fill悪化を巻き戻さない')
                    elif name == '予約後の資格悪化':
                        assert adds[0,0] == 100 and adds[0,1] == 99
                        assert (events[(events[:,0] == 100),1] == 3).any()
                    elif name == '実fill時の未知peer':
                        assert (events[(events[:,0] == 98),1] == 5).any()
                        assert not ((events[:,0] == 98) & (events[:,1] == 2)).any()
                        assert adds[0,1] == 100
                    elif name == '初回期限と追加':
                        assert len(adds) == 0 and output['trades'][0,5] == 1
                        assert orders[-1,1] == 100 and orders[-1,8] == 3 and orders[-1,0] == 101
                    else:
                        assert len(adds) == 0 and output['trades'][0,5] == 1
                        assert orders[-1,8] == 4 and orders[-1,0] == 100
                        assert orders[-1,10] == value['record']['limit']-60.
                    results.append(dict(境界=name,商品=symbol,方向=side,注文=len(orders),
                        実追加=len(adds),初回絶対数量=int(orders[0,5]),親最終数量=int(output['trades'][0,5]),
                        純損益=float(output['trades'][0,11])))
                except Exception as error:
                    serial=1
                    destination=common.HERE/f'独立境界不合格_{serial:05d}.json'
                    while destination.exists():
                        serial+=1
                        destination=common.HERE/f'独立境界不合格_{serial:05d}.json'
                    common.save(destination,dict(合格=False,境界=name,商品=symbol,方向=side,
                        完了件数=len(results),原因=str(error),詳細=traceback.format_exc(),正式101損益=0,
                        API取得=0,実注文=0,SHA256=signatures))
                    raise
    assert len(results) == 20 and common.fingerprints(paths) == signatures
    common.save(common.HERE/'追加の悪fillと資格悪化及び未知復帰と期限場末の独立境界.json',dict(
        合格=True,人工境界=20,意味境界=5,結果=results,
        範囲='事前に定めたrow97初回fill/99追加判断周辺の因果順を両商品買売で検算。任意rawの全70flags証明又は収益性検証ではない。',
        金融本体変更=0,正式101損益=0,API取得=0,実注文=0,SHA256=signatures))
    print('20境界: 悪fill/予約後資格/未知基準/初回期限/場末が独立一致。',flush=True)


if __name__ == '__main__':
    main()
