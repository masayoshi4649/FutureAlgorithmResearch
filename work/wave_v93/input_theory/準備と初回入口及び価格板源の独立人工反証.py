"""準備の資格、入口時の追加資格、価格源と板源の混同を損益前に検査する。"""

from copy import deepcopy
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STRATEGY = ROOT / 'work/wave_v94/strategy.py'
ENGINE = ROOT / 'work/wave_v94/engine.py'
CATALOG = ROOT / 'work/wave_v94/catalog.py'
DESIGN = ROOT / 'work/wave_v94/結果前の設計案_r1.json'


def module(name: str, path: Path) -> object:
    """
    機能: mainや売買を呼ばず、仕様及び純状態関数を読む。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def fixture() -> tuple[dict, dict]:
    """
    機能: 資格判定を個別に変更できる人工の二市場特徴列を作る。
    引数: なし。
    返り値: tuple[dict,dict]は価格列と旧板列。実価格経路又は取引結果ではない。
    """
    grid = np.arange(300., 421., 5.)
    size = len(grid)
    price = dict(grid=grid, markets={})
    execution = dict(grid=grid, markets={})
    for multiplier, symbol in enumerate(('TOPIX', 'NK225'), 1):
        value = 1000. * multiplier
        current = dict(index=np.arange(size), raw_seq=1000*multiplier+np.arange(size),
                       time_s=grid-2., value=np.full(size,value), valid=np.ones(size,bool))
        windows = {seconds: dict(source_valid=np.ones(size,bool), efficiency=np.full(size,.1),
                                 total_variation=np.full(size,20.), ret_bp=np.zeros(size))
                   for seconds in (30,300)}
        bounds = dict(source_valid=np.ones(size,bool), position_valid=np.ones(size,bool),
                      width=np.full(size,20.), low=np.full(size,value-10.), high=np.full(size,value+10.))
        price['markets'][symbol] = dict(current=current, windows=windows, ranges={180:bounds})
        flow = dict(source_valid=np.ones(size,bool), valid=np.ones(size,bool),
                    missing_ofi=np.zeros(size,bool), nonzero_ofi_count=np.zeros(size,np.int32),
                    ofi_ratio=np.zeros(size))
        execution['markets'][symbol] = dict(flow={15:flow})
    return price, execution


def equal(first: np.ndarray, second: np.ndarray) -> None:
    """
    機能: 不明値を含む源及び状態列を比較する。
    引数: first/second(ndarray)。
    返り値: None。不一致なら停止する。
    """
    if np.issubdtype(first.dtype,np.floating) or np.issubdtype(second.dtype,np.floating):
        np.testing.assert_allclose(first,second,rtol=0,atol=1e-9,equal_nan=True)
    else:
        np.testing.assert_array_equal(first,second)


def state_checks(strategy: object, config: dict) -> list[dict]:
    """
    機能: 現在観測性をG0準備へ紛れ込ませず、G1/G2に分けた純状態を確認する。
    引数: strategy(object)、config(dict)。
    返り値: list[dict]は人工の正負判定。売買関数は呼ばない。
    """
    cases = []
    for kind in ('正常な往復', '30秒窓不明', '300秒ER不明', '総変動ゼロ',
                 '範囲不明', '現在価格不明', '正常な共同上方向', '正常な共同下方向',
                 '相手源が更新しない'):
        price, execution = fixture()
        if kind == '30秒窓不明':
            price['markets']['TOPIX']['windows'][30]['source_valid'][:] = False
            price['markets']['TOPIX']['windows'][30]['ret_bp'][:] = np.nan
        elif kind == '300秒ER不明':
            price['markets']['NK225']['windows'][300]['efficiency'][:] = np.nan
        elif kind == '総変動ゼロ':
            price['markets']['TOPIX']['windows'][300]['total_variation'][:] = 0.
            price['markets']['TOPIX']['windows'][300]['efficiency'][:] = np.nan
        elif kind == '範囲不明':
            price['markets']['NK225']['ranges'][180]['source_valid'][:] = False
        elif kind == '現在価格不明':
            price['markets']['TOPIX']['current']['valid'][:] = False
            price['markets']['TOPIX']['current']['value'][:] = np.nan
        elif kind in ('正常な共同上方向', '正常な共同下方向'):
            direction = 1 if kind == '正常な共同上方向' else -1
            for market in price['markets'].values():
                market['windows'][300]['efficiency'][:] = 1.
                market['windows'][300]['ret_bp'][:] = 4.*direction
                market['windows'][30]['ret_bp'][:] = 1.*direction
        elif kind == '相手源が更新しない':
            price['markets']['NK225']['current']['raw_seq'][:] = 2000
        before = pickle.dumps((price,execution),protocol=5)
        value = strategy.price_state(price,execution,config)
        if kind == '正常な往復':
            assert value['mode'][-1] == value['price_mode'][-1] == 2
            assert value['price_observable'].all()
        elif kind == '30秒窓不明':
            assert value['raw_mode'][-1] == value['mode'][-1] == 2
            assert value['price_mode'][-1] == 0 and not value['price_observable'].any()
        elif kind in ('300秒ER不明','総変動ゼロ','範囲不明','現在価格不明'):
            assert value['raw_mode'][-1] == value['mode'][-1] == value['price_mode'][-1] == 0
            assert not value['price_observable'].any()
        elif kind in ('正常な共同上方向','正常な共同下方向'):
            assert value['mode'][-1] == (1 if kind == '正常な共同上方向' else -1)
            assert value['price_observable'].all() and value['price_mode'][-1] == 0
        else:
            assert value['raw_mode'][-1] == 2
            assert value['mode'][-1] == value['price_mode'][-1] == 0
        assert before == pickle.dumps((price,execution),protocol=5)
        cases.append({'条件':kind,'元準備raw_mode':int(value['raw_mode'][-1]),
                      '元準備mode':int(value['mode'][-1]),'現在price_mode':int(value['price_mode'][-1]),
                      '現在観測可能':bool(value['price_observable'][-1]),'入力不変':True})
    return cases


def source_checks(strategy: object, config: dict) -> list[dict]:
    """
    機能: 旧準備の返り値を固定した接続検査で、価格の差替えが板源を上書きしないと確認する。
    引数: strategy(object)、config(dict)。
    返り値: list[dict]はI1/I2/I3の接続結果。旧準備内部及び売買は実行しない。
    """
    price, execution = fixture()
    size = len(price['grid'])
    session = '人工場'
    original_signals = {}
    records = {}
    for position,symbol in enumerate(('TOPIX','NK225')):
        record = dict(seq=np.arange(size),time_s=price['grid']-3.)
        records[session,symbol] = record
        index = np.arange(size)
        execution['markets'][symbol]['current'] = dict(index=index,mid=np.full(size,3000.+position),valid=np.ones(size,bool))
        signal = dict(grid=price['grid'],mode=np.zeros(size,np.int8),raw_mode=np.zeros(size,np.int8),
                      valid=np.ones(size,bool),common=np.zeros(size,np.int8),
                      quality=np.ones(size,bool),reset=np.zeros(size,bool),event=np.zeros(size,np.int8),
                      mapped=np.arange(size),trend_width=10.,current_valid=np.ones(size,bool),
                      peer_mid=np.full(size,4000.+position),peer_source=index,
                      peer_valid=np.ones(size,bool),own_source=index,
                      own_source_time=price['grid']-3.,peer_source_time=price['grid']-4.,
                      reverse_long=np.zeros(size,bool),reverse_short=np.ones(size,bool))
        original_signals[session,symbol] = dict(record=record,signal=signal)
    material = dict(prices=records,grids={session:execution},price_lanes={lane:{session:price} for lane in ('I1','I2','I3')})
    old_prepare = strategy.LEGACY.prepare
    preserved = ('quality','reset','event','mapped','trend_width','current_valid','peer_mid','peer_source',
                 'peer_valid','own_source','own_source_time','peer_source_time','reverse_long','reverse_short')
    checks = []
    try:
        strategy.LEGACY.prepare = lambda material,config:deepcopy(original_signals)
        for lane in ('I1','I2','I3'):
            selected = dict(config,price_lane=lane)
            before = pickle.dumps(material,protocol=5)
            output = strategy.prepare(material,selected)
            for key,value in output.items():
                current = value['signal']
                for field in preserved:
                    source = original_signals[key]['signal'][field]
                    if isinstance(source,np.ndarray):
                        equal(current[field],source)
                    else:
                        assert current[field] == source
                own = price['markets'][key[1]]['current']
                assert not np.array_equal(own['raw_seq'],current['own_source'])
                equal(current['price_own_raw_seq'],own['raw_seq'])
                equal(current['price_own_time'],own['time_s'])
                assert not np.array_equal(current['price_own_time'],current['own_source_time'])
            assert before == pickle.dumps(material,protocol=5)
            checks.append({'入力lane':lane,'保持した旧執行及び板欄':list(preserved),
                           '価格rawseq及びclockを別欄へ保存':True,'同一源と偽装しない':True,'入力不変':True})
    finally:
        strategy.LEGACY.prepare = old_prepare
    return checks


def main() -> None:
    """
    機能: 新53の対照、純状態、源接続及び初回ゲート順序を損益前に独立検査する。
    引数: なし。
    返り値: None。新理論JSONだけ保存し、simulate/execute/playは呼ばない。
    """
    hashes = {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (STRATEGY,ENGINE,CATALOG,DESIGN)}
    strategy,catalog = module('独立準備入口源94',STRATEGY),module('独立準備条件94',CATALOG)
    conditions = catalog.catalog()
    assert len(conditions) == 53 and catalog.PRIMARY == 'I3_G1_S0_T1'
    config = next(value for value in conditions if value['id'] == catalog.PRIMARY)
    states = state_checks(strategy,config)
    sources = source_checks(strategy,config)
    engine = ast.parse(ENGINE.read_text(encoding='utf-8'))
    tree = next(node for node in engine.body if isinstance(node,ast.FunctionDef) and node.name=='simulate')
    gated = [node for node in ast.walk(tree) if isinstance(node,ast.If) and ast.unparse(node.test)=='gated_entry']
    assert len(gated) == 1
    assert any(isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='gate_consumed' for target in node.targets)
               and isinstance(node.value,ast.Constant) and node.value.value is True for node in gated[0].body)
    parent_blocks = [node for node in ast.walk(tree) if isinstance(node,ast.If) and ast.unparse(node.test)=='accepted']
    assert len(parent_blocks) == 1 and gated[0].lineno < parent_blocks[0].lineno
    source_text = ast.get_source_segment(ENGINE.read_text(encoding='utf-8'),tree)
    assert 'gate_consumed' in source_text and 'allowed = allowed and peer_ok and not gate_consumed' in source_text
    assert 'accepted = price_observable and (context_kind != 2 or price_mode == 2)' in source_text
    for path in (STRATEGY,ENGINE,CATALOG,DESIGN):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == hashes[str(path.relative_to(ROOT))]
    value = {'全人工合格':True,'純状態検査':states,'源接続検査':sources,
             '初回入口順序の静的確認':{'ゲート判定後は受理及び不受理の双方で消費':True,
                                  '受理処理より先に消費':True,'次の回復判定は消費済みなら不許可':True,
                                  'G1は可観測性及びG2は現在price_mode2を明示追加':True},
             '対照上の結論':['30秒が不明でも旧準備mode2は残すG0対照。G1/G2はその初回入口で拒否できる別軸。',
                             'ER又は価格総変動又は範囲が不明なら準備自体も成立しない。',
                             'G1は現在の観測が可能である条件であって、現在の往復予測が正しいという条件ではない。',
                             'I3の価格源は原本LP系列、回復証拠及び注文執行は旧BBO系列。index同士を比較せず各rawseq及びclockを別記する。',
                             '将来中心へ戻るという事後情報は入口へ使わない。LPの観測追加で返済行を早めない。'],
             '検査の範囲':['源接続では旧prepareの返り値だけ固定した。旧prepareの内部、実板prefix及び全注文同一性は独立監査の別検査。',
                            '入口消費のAST確認は静的確認。実際の再準備・回復順序は人工売買監査で確認が必要。',
                            '特徴列の人工資格を検査したもので、実価格経路に対応する新取引又は利益の試算ではない。',
                            'CurrentPriceTimeは代理時計。実受信順及びクロス銘柄到着時間の証明ではない。'],
             '正式条件数':53,'結果前主':catalog.PRIMARY,'参照SHA256':hashes,
             '理論コードSHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             '全62生成を実行':0,'新条件売買実行':0,'新損益閲覧':0,'新損益計算':0,'API取得':0,'実注文':0}
    path = HERE / '修正版の準備及び初回入口と別価格板源の独立人工反証.json'
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'保存先':str(path),'SHA256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      '純状態人工数':len(states),'源接続数':len(sources),'新損益計算':0},ensure_ascii=False))


if __name__ == '__main__':
    main()
