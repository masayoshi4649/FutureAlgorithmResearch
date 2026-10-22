"""金融前に独立期待線・既存返却・前場限定を人工確認する。"""

from __future__ import annotations

import ast
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
GRID = ROOT / "work/stability124_20261019/grid"
sys.path.insert(0, str(GRID))
import engine123 as E
import catalog124 as C


def module(name: str, path: Path):
    """
    機能: 共有作業を変更せず指定したPython源を別名で読み込む。
    引数: name(str)は一意名、path(Path)は読む源。
    返り値: moduleは読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def digest(path: Path) -> str:
    """
    機能: 使用した源の指紋を作る。
    引数: path(Path)は小さい所有資料。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact(a, b) -> bool:
    """
    機能: 全返却配列と辞書の厳密な同値を確認する。
    引数: a/b(object)は比較する返却値。
    返り値: boolは型構造・内容が同じ場合のみ真。
    """
    if isinstance(a, np.ndarray):
        return isinstance(b, np.ndarray) and np.array_equal(a, b, equal_nan=True)
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(exact(a[k], b[k]) for k in a)
    if isinstance(a, (tuple, list)):
        return type(a) is type(b) and len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b))
    return bool(a == b)


def quotes(prices: np.ndarray, spread: float = 0., start: float = 0.) -> dict:
    """
    機能: 人工Last経路を原行・時計・対称気配付きへ変換する。
    引数: prices(ndarray)は人工価格、spread(float)は気配差、start(float)は開始時計。
    返り値: dictは五列の人工入力。
    """
    return dict(row=np.arange(len(prices), dtype=np.int64), time=start + np.arange(len(prices), dtype=float),
                last=prices.astype(float), bid=prices.astype(float) - spread / 2, ask=prices.astype(float) + spread / 2)


def setting(symbol: str, end: float, cap: int | None = None) -> dict:
    """
    機能: 実市場を読まず人工比較の費用・倍率・締切を作る。
    引数: symbol(str)は商品、end(float)は予定終端、cap(int|None)は数量上書き。
    返り値: dictはcoreへ渡す商品設定。
    """
    top = symbol == 'TOPIX'
    return dict(cap=cap if cap is not None else (10 if top else 20), multiplier=1000. if top else 10.,
                fee=41.8 if top else 11., observed_tick=.5 if top else 10., session_start=0.,
                entry_end=end - 200., close_time=end - 100., session_end=end)


def source_check() -> dict:
    """
    機能: core不変とwrapperのunit以外の構文不変を確認する。
    引数: なし。
    返り値: dictは旧源と現在源の指紋。
    """
    old = ROOT / 'work/stability123_20261017'
    assert (GRID / 'core123.py').read_bytes() == (old / 'core123.py').read_bytes()
    before = ast.parse((old / 'engine123.py').read_text(encoding='utf-8'))
    after = ast.parse((GRID / 'engine123.py').read_text(encoding='utf-8'))
    old_func = next(n for n in before.body if isinstance(n, ast.FunctionDef) and n.name == 'evaluate')
    new_func = next(n for n in after.body if isinstance(n, ast.FunctionDef) and n.name == 'evaluate')
    assert new_func.args.args[-1].arg == 'unit' and len(new_func.args.args) == len(old_func.args.args) + 1
    new_func.args.args.pop()
    assert len(new_func.args.defaults) == 1 and new_func.args.defaults.pop().value == 1.
    old_func.body.pop(0)
    new_func.body.pop(0)
    for node in ast.walk(new_func):
        if isinstance(node, ast.keyword) and node.arg == 'unit':
            assert isinstance(node.value, ast.Name) and node.value.id == 'unit'
            node.value = ast.Constant(value=1.)
    assert ast.dump(before, include_attributes=False) == ast.dump(after, include_attributes=False)
    return {name: digest(GRID / name) for name in ('core123.py', 'engine123.py', 'catalog124.py')}


def parameter_check() -> list[dict]:
    """
    機能: 独立の手計算表で未知・比率端点・呼値上丸め・数量を検証する。
    引数: なし。
    返り値: list[dict]は人工条件の確認件数。
    """
    specs = C.specifications()
    assert [s['id'] for s in specs] == [f'O{i:02}' for i in range(12)]
    low = [(3,3),(3,2.5),(3,1.5),(2.5,3),(1.5,3),(2.5,2.5),(1.5,1.5),(1.5,1.5),(6,6),(3,3),(3,10),(15,15)]
    high = [(3,3),(3,4.5),(3,6),(4.5,3),(6,3),(4.5,4.5),(6,6),(6,6),(1.5,1.5),(3,3),(3,10),(15,15)]
    middle = [(3,3),(3,3.5),(3,4),(3.5,3),(4,3),(3.5,3.5),(4,4),(4,4),(2.5,2.5),(3,3),(3,10),(15,15)]
    cases = []
    for symbol, full_cap, unit in [('TOPIX',10,1.),('NK225',20,20.)]:
        for iv, ratio, expected in [(1.,.5,low),(15.,.5,low),(37.5,1.25,middle),(60.,2.,high),(200.,2.,high)]:
            for j, spec in enumerate(specs):
                p = C.parameters(spec, dict(known=True, iv_median_percent=iv), symbol)
                cap = full_cap
                if j in (7,9):
                    cap = full_cap if ratio <= 1 else (8 if symbol == 'TOPIX' else 16) if ratio == 1.25 else full_cap // 2
                assert (p['initial'], p['spacing']) == expected[j], (symbol, iv, spec, p)
                assert p['unit'] == unit and p['cap'] == cap and p['ratio'] == ratio
                assert p['used'] == (j not in (0,10,11))
                cases.append(dict(symbol=symbol, method=spec['id'], iv=iv, **p))
        for spec in specs:
            p = C.parameters(spec, dict(known=False, iv_median_percent=9999), symbol)
            e = (3.,10.) if spec['id'] == 'O10' else (15.,15.) if spec['id'] == 'O11' else (3.,3.)
            assert (p['initial'],p['spacing']) == e
            assert p['unit'] == unit and p['cap'] == full_cap and p['ratio'] is None and p['iv_pct'] is None and not p['used']
    return cases


def path_check() -> list[dict]:
    """
    機能: 全条件を上下人工経路で動かし先に定めた段線・UID・代理損益を照合する。
    引数: なし。
    返り値: list[dict]は人工経路の確認結果。
    """
    cases = []
    for symbol, origin, tick in [('TOPIX',4000.,.5),('NK225',68000.,10.)]:
        for iv in (15.,30.,60.):
            for spec in C.specifications():
                p = C.parameters(spec, dict(known=True, iv_median_percent=iv), symbol)
                for side in (1,-1):
                    prices = np.repeat(origin + side * np.arange(1000) * tick, 2)
                    q = quotes(prices)
                    cfg = setting(symbol, 2250., p['cap'])
                    result = E.evaluate(q,cfg,'CLOSE_PROXY',p['initial'],p['spacing'],p['unit'])
                    orders,lots,curves,summary,proxy,context = result
                    lines = origin + side * (p['initial'] + np.arange(p['cap']) * p['spacing']) * p['unit']
                    assert len(orders) == p['cap'] and np.all(orders[:,2] == side)
                    assert np.array_equal(orders[:,17],lines), (symbol,iv,spec['id'],side,orders[:,17],lines)
                    assert len(lots) == 0 and np.all(orders[:,1] == 1) and len(set(orders[:,0])) == len(orders)
                    assert np.array_equal(orders[:,0],proxy[:,0]) and np.all(orders[:,4] > orders[:,3])
                    assert np.all(orders[:,8] == (41 if symbol == 'TOPIX' else 11))
                    assert np.all(proxy[:,11] == (82 if symbol == 'TOPIX' else 22))
                    reference = q['bid'][-1] if side == 1 else q['ask'][-1]
                    expected_gross = side * (reference - orders[:,7]) * cfg['multiplier']
                    assert np.array_equal(proxy[:,9],np.full(len(proxy),reference))
                    assert np.array_equal(proxy[:,10],expected_gross)
                    assert np.array_equal(proxy[:,12],expected_gross - proxy[:,11])
                    assert summary['net'] == summary['cash'] == sum(proxy[:,12]) and summary['unclosed'] == 0
                    assert summary['entries'] == len(orders) and summary['max_long'] <= p['cap'] and summary['max_short'] <= p['cap']
                    assert context['reference_row'] == q['row'][-1] and context['age_seconds'] == 251.
                    cases.append(dict(symbol=symbol,method=spec['id'],iv=iv,side=side,entries=len(orders)))
    return cases


def gates_and_old_check() -> dict:
    """
    機能: unit固定の気配資格・不利許容・旧TOPIX返却を独立に確認する。
    引数: なし。
    返り値: dictは確認した人工条件の件数。
    """
    old = module('old_wrapper_for_audit124', ROOT / 'work/stability123_20261017/engine123.py')
    count = 0
    for symbol, origin, unit, tick in [('TOPIX',4000.,1.,.5),('NK225',68000.,20.,10.)]:
        prices = np.repeat(origin + np.arange(240) * tick,2)
        for initial, spacing in [(3.,3.),(1.5,6.),(15.,15.)]:
            for spread in (unit,unit+tick):
                q = quotes(prices,spread)
                cfg = setting(symbol,700.)
                result = E.evaluate(q,cfg,'CLOSE_PROXY',initial,spacing,unit)
                if spread > unit:
                    assert not len(result[0]),(symbol,initial,spacing,spread)
                else:
                    assert len(result[0]) > 0
                if symbol == 'TOPIX':
                    assert exact(result, old.evaluate(q,cfg,'CLOSE_PROXY',initial,spacing))
                count += 1
        # ----------------------------------------
        # 初回発火後に次行だけを不利許容の境界内外へ動かす。間隔を広げても許容は増えない。
        for initial,spacing in [(3.,3.),(15.,15.)]:
            for side in (1,-1):
                for jump, expected in [(tick,True),(tick+tick,False)]:
                    prices = np.array([origin,origin+side*initial*unit,origin+side*(initial*unit+jump)])
                    q = quotes(prices)
                    cfg = setting(symbol,10.)
                    cfg.update(entry_end=8.,close_time=9.)
                    result = E.evaluate(q,cfg,'CLOSE_PROXY',initial,spacing,unit)
                    assert (len(result[0]) == 1) == expected,(symbol,initial,side,jump,result[0])
                    assert result[3]['canceled'] >= (0 if expected else 1)
                    count += 1
    # ----------------------------------------
    # 非単調経路の全返却も比較し、旧unit1の互換を少数の最終額だけで済ませない。
    rng = np.random.default_rng(12420261019)
    prices = 4000. + np.cumsum(rng.integers(-8,9,size=900)) * .5
    q = quotes(prices,.5)
    for initial,spacing in [(3.,3.),(3.,10.),(15.,15.),(2.5,4.5)]:
        cfg=setting('TOPIX',1100.)
        assert exact(E.evaluate(q,cfg,'CLOSE_PROXY',initial,spacing,1.),old.evaluate(q,cfg,'CLOSE_PROXY',initial,spacing))
        count += 1
    return dict(cases=count,old_wrapper_sha256=digest(ROOT/'work/stability123_20261017/engine123.py'))


def chronology_check() -> dict:
    """
    機能: 前場特徴の時刻上限と人工の未来変更不変性を確認する。
    引数: なし。
    返り値: dictは所有特徴の既知未知と人工条件の照合。
    """
    selector=module('option_selector_audit124', ROOT/'work/stability124_20261019/options/signals124.py')
    path=ROOT/'work/stability124_20261019/options/前完了場IV固定特徴.json'
    assert digest(path)=='e36cb5c69bb45a0ab2c3cec91ed6edac1e06ea164083d04b0351135a43d1b443'
    feature=json.loads(path.read_text(encoding='utf-8'))
    known=[f for f in feature['features'] if f['known']]
    assert len(known)==11 and len(feature['features'])==41 and feature['unknown']==30
    for row in known:
        assert dt.datetime.fromisoformat(row['available_at']) < dt.datetime.fromisoformat(row['session_starts_at'])
        assert row['previous_session'] and all(s['session']==row['previous_session'] for s in row['selected'])
    sessions=['2026-10-15_Day','2026-10-15_Night','2026-10-16_Day']
    boundaries=[]
    for session, iv in [(sessions[0],20.),(sessions[1],60.)]:
        for side,delta in [('C',.5),('P',-.5)]:
            boundaries.append(dict(path=session+side,session=session,限月='202611',種別=side,権利行使価格=68000,
                samples=[dict(offset=0,sha256='人工',fraction=1.,fields=dict(IV=iv,Delta=delta))]))
    first=selector.select_features(boundaries,sessions)
    changed=copy.deepcopy(boundaries)
    for row in changed:
        if row['session']==sessions[1]:row['samples'][0]['fields']['IV']=199.
    second=selector.select_features(changed,sessions)
    assert exact(first[1],second[1]) and first[1]['iv_median_percent']==20.
    assert first[2]['iv_median_percent']==60. and second[2]['iv_median_percent']==199.
    assert not first[0]['known']
    assert selector.artificial_check()['passed']
    return dict(feature_sha256=digest(path),selector_sha256=digest(Path(selector.__file__)),sessions=41,known=11,unknown=30,
                current_session_mutation_cannot_change_its_fixed_previous_feature=True)


def main() -> None:
    """
    機能: 独立人工を全実行し金融前の確認証跡を保存する。
    引数: なし。
    返り値: None。
    """
    sources=source_check()
    params=parameter_check()
    paths=path_check()
    gates=gates_and_old_check()
    chronology=chronology_check()
    result=dict(passed=True,financial_accounts=0,原市場読取=0,実注文=0,source_sha256=sources,
        engine_sha256=sources['engine123.py'],core_sha256=sources['core123.py'],catalog_sha256=sources['catalog124.py'],
        parameter_cases=len(params),path_cases=len(paths),gate_old_cases=gates,chronology=chronology,
        確認=['未知IVと固定対照','IV比率の上下clip','幅の呼値上丸め','固定unitの気配資格と不利許容',
              'TOP旧wrapper全六返却exact','両商品上下の独立期待段線','全UID一回代理清算','往復fee82/22',
              '買bid売askの代理価格','前場available_at<当場start','当場IV変更の当場固定特徴への不変'],
        人工条件=params,人工上下=paths,script_sha256=digest(Path(__file__)))
    target=OUT/'十二条件と二商品及び前場限定の独立人工.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,path=target.relative_to(ROOT).as_posix(),sha256=digest(target),
        parameter_cases=len(params),path_cases=len(paths),gate_old_cases=gates['cases'],**sources),ensure_ascii=False))


if __name__=='__main__':
    main()
