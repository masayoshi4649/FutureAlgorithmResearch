"""102全20の人工原素材を、独立数理・新19門番・実注文会計へ接続する。"""

import ast
from pathlib import Path
import traceback
import numpy as np

import common
import financial
import runtime_oracle
import support


def fixture(symbol: str, side: int = 1, profile: str = '持続順行') -> dict:
    """
    機能: 不変100の人工原板関数だけを抽出し、初回失敗又は持続順行の両方向素材を得る。
    引数: symbol(str)、side(int)は±1、profile(str)は持続順行又は初回失敗。
    返り値: dict。原候補・自己板・公開peer・LP原素材。売買出力を参照しない。
    """
    path = common.ROOT/'work/wave_v100/audit/artificial.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name == 'fixture')
    from copy import deepcopy
    namespace = dict(common=common,support=support,np=np,ast=ast,deepcopy=deepcopy)
    unit = ast.Module(body=[function],type_ignores=[])
    exec(compile(ast.fix_missing_locations(unit),str(path),'exec'),namespace)
    assert profile in ('持続順行','初回失敗')
    value = namespace['fixture'](symbol,1)
    scale,peer_scale = (1.,20.) if symbol == 'TOPIX' else (20.,1.)
    record,signal = value['record'],value['signal']
    if profile == '持続順行':
        # 元候補95を変えず、その後に全玉の追加資格を満たす継続的順行を置く。
        moves = np.full(len(record['bid']),35.)
        moves[99:141] = np.arange(27.,69.)
        record['bid'][99:] = (3999.5+moves[99:])*scale
        record['ask'][99:] = record['bid'][99:]+.5*scale
        record['price'][99:] = (record['bid'][99:]+record['ask'][99:])*.5
        signal['entry_peer_bbo'][99:,3] = (3999.5+moves[99:])*peer_scale
        signal['entry_peer_bbo'][99:,4] = signal['entry_peer_bbo'][99:,3]+.5*peer_scale
    if side == -1:
        center = value['reference_open']
        old_bid = record['bid'].copy()
        record['bid'],record['ask'] = 2*center-record['ask'],2*center-old_bid
        record['price'] = 2*center-record['price']
        signal['event'] *= -1
        peer_center = 80000. if symbol == 'TOPIX' else 4000.
        peer = signal['entry_peer_bbo']
        old_peer_bid = peer[:,3].copy()
        peer[:,3],peer[:,4] = 2*peer_center-peer[:,4],2*peer_center-old_peer_bid
    helper = common.module('101人工の不変旧LP素材',common.ROOT/'work/wave_v99/engine_preflight/support.py')
    key = record['session'],symbol
    helper.attach_support({key:value})
    assert value['record']['session'] == '2099-01-01_Day'
    assert value['reference_open'] == (4000. if symbol == 'TOPIX' else 80000.)
    assert (value['record']['bid'] > 0).all() and (value['record']['ask'] > value['record']['bid']).all()
    return value


def main() -> None:
    """
    機能: 本体動作合格の通知後に全20条件/両商品/買売を独立oracleへ照合する。
    引数: なし。
    返り値: None。不合格を別ファイルに保存して停止。正式原板の新P/Lを計算しない。
    """
    catalog = common.module('102独立人工条件',common.BASE/'catalog.py')
    strategy = common.module('102独立人工本体',common.BASE/'strategy.py')
    paths = [common.BASE/name for name in ('catalog.py','strategy.py','engine.py','結果前の設計案.json','結果前の数理明確化.json')]
    paths += [common.HERE/name for name in ('common.py','math_oracle.py','compare_utils.py','financial.py',
              'support.py','watch.py','runtime_oracle.py','artificial.py')]
    paths += [common.ROOT/'work/wave_v100/audit/artificial.py',
              common.ROOT/'work/wave_v97/根台帳の保存往復を確かめる.py',
              common.ROOT/'work/wave_v99/engine_preflight/support.py']
    signatures = common.fingerprints(paths)
    counts = dict(人工条件=20,経路=0,注文=0,完了親=0,cohort=0,実追加=0,全原板会計=0,独立保有行=0,独立追加門番行=0)
    for config in catalog.catalog():
        for symbol in catalog.SYMBOLS:
            for side in (1,-1):
                try:
                    value = fixture(symbol,side)
                    key = value['record']['session'],symbol
                    support.verify_material(key,value['artificial_support_material'],value)
                    output = strategy.play(config,key,{key:value})
                    finance = financial.verify_account(value['record'],config,output)
                    independent = runtime_oracle.compare(value,config,output)
                    assert len(output['trades']) > 0, '入口支持と触発に未到達のfixture'
                    actual_additions = int((output['orders'][:,8] == 16).sum())
                    if config['trend_growth_mode']:
                        assert actual_additions > 0, '増玉条件なのに実追加へ未到達'
                    else:
                        assert actual_additions == 0
                    counts['経路'] += 1
                    counts['実追加'] += actual_additions
                    for name in ('注文','cohort','全原板会計'):
                        counts[name] += finance['counts'][name]
                    counts['完了親'] += finance['counts']['決済親']
                    counts['独立保有行'] += independent['独立保有行']
                    counts['独立追加門番行'] += independent['独立追加門番行']
                except Exception as error:
                    serial = 1
                    failure = common.HERE/f'人工不合格_{serial:05d}.json'
                    while failure.exists():
                        serial += 1
                        failure = common.HERE/f'人工不合格_{serial:05d}.json'
                    common.save(failure,dict(合格=False,条件=config['id'],商品=symbol,方向=side,
                        完了件数=counts,例外型=type(error).__name__,原因=str(error),詳細=traceback.format_exc(),
                        正式102損益=0,API取得=0,実注文=0,SHA256=signatures))
                    raise
        print(config['id']+': 両商品/反射の独立raw入口・追加・停止・全玉会計が一致',flush=True)
    assert counts['経路'] == 80
    assert common.fingerprints(paths) == signatures
    common.save(common.HERE/'全20人工の独立初回と増玉及び停止と全原板会計.json',dict(
        合格=True,検査件数=counts,
        数学='独立Fractionで実注文料金・固定R0・加重価格全体丸め・B×初回S余裕・当該行通常追尾後旧線の予算・全統合線等号・activeを再算定。全増玉人工に実追加を要求。',
        状態の範囲='原候補と公開peerから最初入口、全実追加と最初返済を再生。保有11数理と別19門番全列を独立比較。旧70補助flags全列の独立再構成とはしない。',
        会計='全実注文の次normal BBO・全量一返済・cohort最大剰余料金・親16・全原板清算時価を照合。',
        正式102損益=0,API取得=0,実注文=0,SHA256=signatures))


if __name__ == '__main__':
    main()
