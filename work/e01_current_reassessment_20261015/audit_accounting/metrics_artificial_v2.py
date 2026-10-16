"""完結親netと全場平均の定義を、金融本文を使わず独立分数算術で確認する。"""

from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
SOURCE = BASE/'root_review/financial_metrics.py'


def oracle_amounts(values: list) -> dict:
    """
    機能: 有限の合成親netを相殺前の正負零に分ける独立分数oracle。
    引数: values(list[int|float])は実データを含まないtoy net。
    返り値: dictは金額・親数・未定義割合。対象sourceを呼ばない。
    """
    a = [Fraction(str(x)) for x in values]
    wins = [x for x in a if x > 0]; losses = [-x for x in a if x < 0]
    p, l = sum(wins, Fraction()), sum(losses, Fraction())
    return dict(利益=p, 損失=l, 収支=sum(a, Fraction()), 親数=len(a), 勝ち親=len(wins), 負け親=len(losses),
        零親=len(a)-len(wins)-len(losses), 利益割合=p/(p+l) if p+l else None, PF=p/l if l else None,
        平均利益=p/len(wins) if wins else None, 平均損失=l/len(losses) if losses else None)


def oracle_scope(rows: list, parents: list, symbol: str) -> dict:
    """
    機能: 場数・活動・平均黒字補填・TOPIX円床を対象sourceと独立に計算する。
    引数: rows/parents(list[dict])は同商品toy、symbol(str)はTOPIX又はNK225。
    返り値: dictは独立期待値。未取引を勝ちへ加えない。
    """
    a = oracle_amounts([p['収支'] for p in parents]); n = len(rows)
    nets = [Fraction(str(r['収支'])) for r in rows]
    positive = [v for v in nets if v > 0]; negative = [-v for v in nets if v < 0]
    active = sum(r['親数'] > 0 for r in rows)
    pm = sum(positive, Fraction())/len(positive) if positive else None
    worst = max(negative, default=Fraction())
    ordered = sorted(nets); midpoint = n//2
    median = ordered[midpoint] if n%2 else (ordered[midpoint-1]+ordered[midpoint])/2
    m = a['収支']/n; floor = Fraction(100000) if symbol == 'TOPIX' else None
    t65 = a['利益割合'] is not None and a['利益割合'] >= Fraction(65,100)
    t20 = Fraction(len(negative),n) <= Fraction(1,5)
    cover = pm is not None and worst <= pm
    return dict(aggregate=a, session_count=n, active_sessions=active, positive_sessions=len(positive),
        losing_sessions=len(negative), no_trade_sessions=n-active, flat_active_sessions=active-len(positive)-len(negative),
        red_full_rate=Fraction(len(negative),n), red_active_rate=Fraction(len(negative),active) if active else None,
        mean_session_net_yen=m, median_session_net_yen=median, mean_positive_session_net_yen=pm,
        worst_negative_session_abs_yen=worst, target65=t65, target_red20=t20, target_worst_mean=cover,
        all_stability_targets=t65 and t20 and cover, target_floor_yen=floor,
        target_mean_success=m>=floor if floor is not None else None,
        all_main_targets=t65 and t20 and cover and (floor is None or m>=floor),
        actual_quantity_cap=10 if symbol == 'TOPIX' else 20,
        net_capacity_points=a['収支']/(10000 if symbol == 'TOPIX' else 200))


def compare(actual: object, expected: object) -> int:
    """
    機能: 分数oracleと対象sourceの数値/None/boolを再帰照合する。
    引数: actual/expected(object)は同じkey構造。
    返り値: intは検査した葉の件数。数値許容差は1e-7円又は相対1e-12。
    """
    if isinstance(expected, dict):
        assert set(actual) == set(expected)
        return sum(compare(actual[k], v) for k, v in expected.items())
    if expected is None:
        assert actual is None
    elif isinstance(expected, bool):
        assert type(actual).__name__ in ('bool', 'bool_') and bool(actual) is expected
    elif isinstance(expected, (Fraction,int,float)):
        assert abs(float(actual)-float(expected)) <= max(1e-7,abs(float(expected))*1e-12)
    else:
        assert actual == expected
    return 1


def toy(groups: list, symbol: str) -> tuple[list, list]:
    """
    機能: toy親net群をP/Lを相殺せず場と親へ展開する。
    引数: groups(list[list[int|float]])、symbol(str)は合成の場別親と商品。
    返り値: tuple[list,list]は同じtoy母集団のrows/parents。
    """
    rows = []; parents = []
    for i, values in enumerate(groups):
        session = '2026-01-'+str(i+1).zfill(2)+('_Day' if i%2 == 0 else '_Night')
        a = oracle_amounts(values)
        rows.append(dict(session=session, symbol=symbol, **{k:float(a[k]) for k in ('利益','損失','収支')}, 親数=a['親数']))
        parents.extend(dict(session=session, symbol=symbol, 方向=1 if j%2 == 0 else -1, 収支=float(v)) for j,v in enumerate(values))
    return rows, parents


def main() -> None:
    """
    機能: 有効有限入力だけで金額定義・33場分母・除外集合を独立人工確認する。
    引数: なし。SOURCE一ファイルと私有toyだけ、cache/金融/API0。
    返り値: None。対象sourceの前後指紋と検算結果を所有域へ保存する。
    """
    raw = SOURCE.read_bytes(); sha = hashlib.sha256(raw).hexdigest()
    spec = importlib.util.spec_from_file_location('完結親金額定義のSOURCE人工', SOURCE)
    target = importlib.util.module_from_spec(spec); spec.loader.exec_module(target)
    rng = random.Random(113); checked = 0; cases = 0
    seeds = [[], [0], [1,-1], [1000,-900,-200], [100000], [99999.99], [300000,200000,180000,-80000]]
    for values in seeds:
        checked += compare(target.amounts(values), oracle_amounts(values)); cases += 1
    groups = [[[300000],[200000],[180000],[-80000],[]],
        [[300000],[200000],[180000],[-80000]]+[[]]*29,
        [[100000]]*33, [[99999.99]]*33, [[]]*33,
        [[1000,-900],[-200],[],[],[]], [[100,-100],[0],[],[],[]]]
    for _ in range(80):
        n = rng.randrange(1,34)
        groups.append([[rng.randrange(-1000000,1000001) for _ in range(rng.randrange(0,4))] for _ in range(n)])
    for group in groups:
        for symbol in ('TOPIX','NK225'):
            rows, parents = toy(group, symbol)
            checked += compare(target.scope(rows, parents, symbol), oracle_scope(rows, parents, symbol)); cases += 1
    rows, parents = toy([[300000],[200000],[180000],[-80000]]+[[]]*29, 'TOPIX')
    v = target.scope(rows,parents,'TOPIX')
    assert v['mean_session_net_yen'] == 600000/33 and v['no_trade_sessions'] == 29
    assert v['all_stability_targets'] and not v['all_main_targets']
    rr, pp = toy([[1000,-900],[-200],[],[],[]], 'NK225')
    assert target.scope(rr,pp,'NK225')['target_worst_mean'] is False
    combined_rows = []; combined_parents = []; sessions = [r['session'] for r in rows]
    for symbol in ('TOPIX','NK225'):
        r,p = toy([[100000]]*4+[[-150000]]+[[]]*28, symbol)
        combined_rows.extend(r); combined_parents.extend(p)
        out = target.periods(combined_rows,combined_parents,sessions,symbol)
        own = [x for x in combined_rows if x['symbol']==symbol]; pars = [x for x in combined_parents if x['symbol']==symbol]
        excluded = [r['session'] for r in sorted((r for r in own if r['収支']>0),key=lambda r:(-r['収支'],r['session']))[:3]]
        assert out['除外場'] == excluded
        for label, ids in (('全場',sessions),('前半',sessions[:16]),('後半',sessions[16:]),
            ('デイ',[s for s in sessions if s.endswith('_Day')]),('ナイト',[s for s in sessions if s.endswith('_Night')]),
            ('上位3黒字場除外',[s for s in sessions if s not in excluded])):
            scope = [x for x in own if x['session'] in ids]; subset = [x for x in pars if x['session'] in ids]
            expected = oracle_scope(scope, subset, symbol)
            actual = dict(out[label]); assert actual.pop('sessions') == ids
            checked += compare(actual, expected); cases += 1
        for label, direction in (('買い',1),('売り',-1)):
            checked += compare(out['方向'][label], oracle_amounts([p['収支'] for p in pars if p['方向']==direction])); cases += 1
    # ----------------------------------------
    # 無効な保存金額をfloatへ変える前に拒否する。
    import copy
    import numpy as np
    rejected = 0
    bad_values = [True, False, np.bool_(True), float('nan'), float('inf'), -float('inf'), '1', None]
    for bad in bad_values:
        try:
            target.amounts([bad])
        except (AssertionError, TypeError):
            rejected += 1
        else:
            raise AssertionError(('金額拒否漏れ', repr(bad)))
    for name in ('利益', '損失', '収支'):
        for bad in bad_values:
            r, p = toy([[1]], 'TOPIX')
            r[0][name] = bad
            try:
                target.scope(r,p,'TOPIX')
            except (AssertionError, TypeError):
                rejected += 1
            else:
                raise AssertionError(('場金額拒否漏れ',name,repr(bad)))
    for bad in bad_values:
        r, p = toy([[1]], 'NK225')
        p[0]['収支'] = bad
        try:
            target.scope(r,p,'NK225')
        except (AssertionError, TypeError):
            rejected += 1
        else:
            raise AssertionError(('親金額拒否漏れ',repr(bad)))
    for name in ('利益', '損失'):
        r,p=toy([[1]],'TOPIX'); r[0][name]=-1
        try:
            target.scope(r,p,'TOPIX')
        except AssertionError:
            rejected+=1
        else:
            raise AssertionError(('負のP/L拒否漏れ',name))
    for bad in (True, False, np.bool_(True), -1, 1., '1', None):
        r,p=toy([[1]],'TOPIX');r[0]['親数']=bad
        try:
            target.scope(r,p,'TOPIX')
        except (AssertionError, TypeError):
            rejected+=1
        else:
            raise AssertionError(('親数拒否漏れ',repr(bad)))
    r,p=toy([[1]],'TOPIX');r[0]['親数']=np.int64(1)
    for k in ('利益','損失','収支'):r[0][k]=np.float64(r[0][k])
    p[0]['収支']=np.int64(1)
    checked+=compare(target.scope(r,p,'TOPIX'),oracle_scope(r,p,'TOPIX'));cases+=1
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == sha
    proof = dict(全合格=True, scope='SOURCE_ONLY有限toy。完結親net/P,Lと全場平均/無取引/平均黒字補填/NK床None/上位3集合を独立Fractionで検算。',
        source=dict(path=SOURCE.relative_to(ROOT).as_posix(), SHA256=sha), 人工ケース=cases, 算術項目=checked,
        拒否境界=rejected, 範囲='有効有限入力を独立分数算術で検算し、Bool/非有限/文字/未知金額、負P/L、不正親数の先変換を拒否する。',
        新2場本文=0, 旧実cache=0, NPZ=0, 原板=0, 金融=0, API=0)
    out = HERE/'金額定義と全場分母及び補填力の独立純人工_v2.json'; assert not out.exists()
    out.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True, source_SHA256=sha, proof_SHA256=hashlib.sha256(out.read_bytes()).hexdigest(),
        人工ケース=cases, 算術項目=checked, 拒否境界=rejected, 金融=0, cache=0, API=0),ensure_ascii=False))


ROOT = BASE.parents[1]
if __name__ == '__main__':
    main()
