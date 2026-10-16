"""旧115の実新規・返済時刻を固定した逆売買の参考会計を、保存BBOから再集計する。"""

from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
from numbers import Real
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ORIGINAL = ROOT / 'work/quantity_execution_20261015/finance/結果.json'
EXPECTED = 'f2a61c69044487164dd119aa97faf37be71f1a48683e784bea2531e237861a80'
PLAN = HERE / '固定時刻の反転参考会計の目的と一読固定.json'
OUTPUT = HERE / '固定時刻で買売を反転した十二条件の参考会計.json'
CAP = {'TOPIX': 10, 'NK225': 20}
MULT = {'TOPIX': 1000, 'NK225': 10}
UNIT_FEE = {'TOPIX': Fraction(209, 5), 'NK225': Fraction(11)}
MAIN = 'QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1'


def digest(raw: bytes) -> str:
    """
    機能: 同一読取bytesのSHA256を計算する。
    引数: raw(bytes)。
    返り値: str は十六進指紋。
    """
    return hashlib.sha256(raw).hexdigest()


def exact(value: object) -> Fraction:
    """
    機能: 真偽・未知・非有限以外の実数を厳密数へ移す。
    引数: value(object)。
    返り値: Fraction。金額の未知をゼロへ置換しない。
    """
    assert isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    return Fraction(str(value))


def integer(value: object) -> int:
    """
    機能: 配列由来の有限整数を確認する。
    引数: value(object)。
    返り値: int。真偽は整数として扱わない。
    """
    number = exact(value)
    assert number.denominator == 1
    return int(number)


def fee(q: int, symbol: str) -> Fraction:
    """
    機能: 元と同じ実注文枚数のfloor料を厳密に求める。
    引数: q(int)、symbol(str)。
    返り値: Fraction は整数円料。
    """
    q = integer(q)
    assert q > 0 and symbol in CAP
    value = UNIT_FEE[symbol]*q
    return Fraction(value.numerator//value.denominator)


def write(path: Path, content: dict) -> None:
    """
    機能: 自所有域へ証跡を新規保存する。
    引数: path(Path)、content(dict)。
    返り値: None。既成果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def amounts(nets: list[object]) -> dict:
    """
    機能: 完結親netを相殺前の正負へ分ける。
    引数: nets(list[object])。
    返り値: dict は利益・損失・net・親数。空の割合はNone。
    """
    values = [exact(value) for value in nets]
    p = sum((v for v in values if v > 0), Fraction())
    loss = -sum((v for v in values if v < 0), Fraction())
    return dict(利益=float(p), 損失=float(loss), 収支=float(p-loss), 親数=len(values),
        勝ち親=sum(v>0 for v in values), 負け親=sum(v<0 for v in values), 零親=sum(v==0 for v in values),
        利益割合=float(p/(p+loss)) if p+loss else None)


def mirror_leg(leg: dict, endpoints: dict, quantity: int, symbol: str) -> dict:
    """
    機能: 同じ新規・返済時点の反対BBOで逆売買し、恒等式を独立価格計算と照合する。
    引数: leg/endpoints(dict)、quantity(int) は親全新規量、symbol(str)。
    返り値: dict は元と反転の実脚参考会計。出口を再判定した戦略ではない。
    """
    q, side = integer(leg['q']), integer(leg['side'])
    assert q>0 and side in (-1,1) and quantity == CAP[symbol]
    assert q==integer(endpoints['q']) and side==integer(endpoints['side'])
    assert integer(leg['entry_row'])==integer(endpoints['entry_row'])
    assert integer(leg['exit_row'])==integer(endpoints['exit_row'])
    a, b = endpoints['新規'], endpoints['返済']
    ab, aa, bb, ba = [exact(value) for value in (a['bid'],a['ask'],b['bid'],b['ask'])]
    assert 0 < ab < aa and 0 < bb < ba
    original_entry, original_exit = (aa,bb) if side>0 else (ab,ba)
    mirror_entry, mirror_exit = (ab,ba) if side>0 else (aa,bb)
    assert original_entry==exact(leg['entry_price']) and original_exit==exact(leg['exit_price'])
    midpoint = side*q*MULT[symbol]*((bb+ba-ab-aa)/2)
    crossing = q*MULT[symbol]*(aa-ab+ba-bb)/2
    allocated = fee(quantity,symbol)*q/quantity
    exit_fee = fee(q,symbol)
    assert allocated == exact(leg['entry_fee_allocated']) and exit_fee == exact(leg['exit_fee'])
    cost = allocated+exit_fee
    gross = side*q*MULT[symbol]*(original_exit-original_entry)
    mirrored_gross = -side*q*MULT[symbol]*(mirror_exit-mirror_entry)
    original_net = gross-cost
    mirrored_net = mirrored_gross-cost
    assert midpoint-crossing==gross==exact(leg['gross_yen'])
    assert original_net==exact(leg['net_yen'])
    assert -midpoint-crossing==mirrored_gross
    assert mirrored_net==-midpoint-crossing-cost
    assert original_net+mirrored_net==-2*(crossing+cost)
    return dict(parent=integer(leg['parent']), uid=integer(leg['uid']), q=q, side=side, mirror_side=-side,
        entry_row=integer(leg['entry_row']), exit_row=integer(leg['exit_row']),
        元新規価格=float(original_entry), 元返済価格=float(original_exit),
        反転新規価格=float(mirror_entry), 反転返済価格=float(mirror_exit),
        中値差粗損益=float(midpoint), 気配差負担=float(crossing), 元と共通の料=float(cost),
        元粗損益=float(gross), 元net=float(original_net), 反転粗損益=float(mirrored_gross), 反転net=float(mirrored_net))


def calculate(result: dict) -> dict:
    """
    機能: 全十二条件の親・脚・全66場を固定時刻の逆売買参考会計へ写す。
    引数: result(dict) は旧115完成結果。
    返り値: dict。新有効性標本にも、実際の反転戦略の成績にも数えない。
    """
    assert result['全合格'] is True and result['金融'] is True
    cases = [config['id'] for config in result['configs']]
    sessions = result['sessions']
    assert len(cases)==len(set(cases))==12 and len(sessions)==len(set(sessions))==33
    parent_index = {(p['case'],p['symbol'],p['session'],integer(p['parent']),integer(p['uid'])):p for p in result['parents']}
    assert len(parent_index)==len(result['parents'])
    leg_groups = {}
    for leg in result['actual_legs']:
        key = (leg['case'],leg['symbol'],leg['session'],integer(leg['parent']),integer(leg['uid']))
        assert key in parent_index
        leg_groups.setdefault(key,[]).append(leg)
    diagnostics = {(d['case'],d['symbol'],d['session']):d for d in result['diagnostics']}
    old_rows = {(r['case'],r['symbol'],r['session']):r for r in result['rows']}
    assert len(diagnostics)==len(old_rows)==len(result['rows'])==792
    pp, ll, rr = [], [], []
    processed = set()
    for key, diagnostic in diagnostics.items():
        cid, symbol, session = key
        assert cid in cases and symbol in CAP and session in sessions
        own = []
        for breakdown in diagnostic['parent_breakdown']:
            pk = (*key,integer(breakdown['parent']),integer(breakdown['uid']))
            assert pk in parent_index and pk not in processed
            processed.add(pk)
            parent = parent_index[pk]
            q = integer(parent['quantity'])
            assert q == CAP[symbol]
            legs = leg_groups[pk]
            assert sum(integer(leg['q']) for leg in legs)==q
            remaining = list(breakdown['legs'])
            mirrored = []
            for leg in legs:
                matching = [i for i,point in enumerate(remaining) if
                    integer(point['q'])==integer(leg['q']) and integer(point['side'])==integer(leg['side']) and
                    integer(point['entry_row'])==integer(leg['entry_row']) and integer(point['exit_row'])==integer(leg['exit_row'])]
                assert matching
                point = remaining.pop(matching[0])
                value = mirror_leg(leg,point,q,symbol)
                ll.append(dict(case=cid,symbol=symbol,session=session,**value))
                mirrored.append(value)
            assert not remaining
            summed = {field:sum((exact(leg[field]) for leg in mirrored),Fraction()) for field in
                ('中値差粗損益','気配差負担','元と共通の料','元粗損益','元net','反転粗損益','反転net')}
            for a,b in (('中値差粗損益','中値差粗損益'),('気配差負担','気配差負担'),('元と共通の料','手数料'),('元net','収支')):
                assert summed[a]==exact(breakdown[b])
            for a,b in (('元粗損益','gross_yen'),('元と共通の料','fee_yen'),('元net','net_yen')):
                assert summed[a]==exact(parent[b])
            assert summed['元と共通の料']==fee(q,symbol)+sum((fee(integer(leg['q']),symbol) for leg in legs),Fraction())
            record = dict(case=cid,symbol=symbol,session=session,parent=pk[3],uid=pk[4],quantity=q,
                side=integer(parent['side']),mirror_side=-integer(parent['side']),
                **{field:float(value) for field,value in summed.items()})
            own.append(record)
            pp.append(record)
        original = amounts([p['元net'] for p in own])
        reverse = amounts([p['反転net'] for p in own])
        for field in ('利益','損失','収支','親数','勝ち親','負け親','零親'):
            assert exact(original[field])==exact(old_rows[key][field])
        midpoint = sum((exact(p['中値差粗損益']) for p in own),Fraction())
        spread = sum((exact(p['気配差負担']) for p in own),Fraction())
        cost = sum((exact(p['元と共通の料']) for p in own),Fraction())
        assert midpoint==exact(diagnostic['中値差粗損益']) and spread==exact(diagnostic['気配差負担'])
        assert cost==exact(diagnostic['手数料'])==exact(old_rows[key]['費用'])
        assert midpoint-spread-cost==exact(original['収支'])
        assert -midpoint-spread-cost==exact(reverse['収支'])
        own_legs = [leg for leg in ll if (leg['case'],leg['symbol'],leg['session'])==key]
        qty = {label:sum(leg['q'] for leg in own_legs if test(exact(leg['反転net']))) for label,test in
            (('勝ち返済枚数',lambda value:value>0),('負け返済枚数',lambda value:value<0),('零返済枚数',lambda value:value==0))}
        rr.append(dict(case=cid,symbol=symbol,session=session,元会計=original,固定時刻反転=reverse,
            中値差粗損益=float(midpoint),気配差負担=float(spread),共通料=float(cost),**qty))
    assert processed==set(parent_index) and len(ll)==len(result['actual_legs']) and len(rr)==792
    aggregate = {}
    for cid in cases:
        groups = {}
        for symbol in CAP:
            rows = [r for r in rr if r['case']==cid and r['symbol']==symbol]
            parents = [p for p in pp if p['case']==cid and p['symbol']==symbol]
            assert len(rows)==33 and {row['session'] for row in rows}==set(sessions)
            original = amounts([p['元net'] for p in parents])
            reverse = amounts([p['反転net'] for p in parents])
            for kind in ('元会計','固定時刻反転'):
                totals = original if kind=='元会計' else reverse
                for field in ('利益','損失','収支'):
                    assert exact(totals[field])==sum((exact(row[kind][field]) for row in rows),Fraction())
            groups[symbol] = dict(元会計=original, 固定時刻反転=reverse,
                元赤字場数=sum(row['元会計']['収支']<0 for row in rows),
                反転赤字場数=sum(row['固定時刻反転']['収支']<0 for row in rows),
                反転黒字場数=sum(row['固定時刻反転']['収支']>0 for row in rows),
                無取引場数=sum(row['固定時刻反転']['親数']==0 for row in rows),
                場数=33, 平均反転収支=sum(row['固定時刻反転']['収支'] for row in rows)/33)
        aggregate[cid] = dict(symbols=groups,
            両商品の固定時刻反転収支合計=sum(groups[s]['固定時刻反転']['収支'] for s in CAP),
            合計の留保='mini10枚/micro20枚の円合算。商品間の収益性順位や別標本の数には使わない。')
    return dict(全合格=True,結果種類='保存会計の固定時刻・逆売買の参考計算',新金融=False,
        原金融SHA256=EXPECTED,固定式='net_mirror = −midgross − spread − fee',
        sessions=sessions,cases=cases,rows=rr,parents=pp,legs=ll,aggregate=aggregate,
        counts=dict(比較場=792,完結親=len(pp),返済脚=len(ll),新金融=0,追加有効性標本=0),
        留保='同じ新規/返済時刻・同じ数量/分割のまま逆BBOで売買。出口を再判定する方向反転戦略ではない。')


def markdown(data: dict) -> str:
    """
    機能: 商品別全33場を含む参考表を自所有域のMarkdownへ出力できる文字列にする。
    引数: data(dict) は検算済み参考会計。
    返り値: str。各条件を同時運転したポートフォリオとは扱わない。
    """
    lines = ['# 固定した新規・返済時刻で買売を逆にした参考計算','',
        '**新しい方向反転アルゴリズムの成績ではない。** 同じ時刻・数量で反対BBOを使うと、中値移動の符号だけ反転し、気配差と料は残る。',
        '式：反転net＝−中値差粗損益−気配差負担−手数料。元netをそのまま符号反転した金額ではない。','']
    for cid in data['cases']:
        lines += ['## '+cid,'','| 場 | TOPIX元net | 固定時刻反転net | 日経元net | 固定時刻反転net |',
                  '| --- | ---: | ---: | ---: | ---: |']
        for session in data['sessions']:
            pair = {row['symbol']:row for row in data['rows'] if row['case']==cid and row['session']==session}
            values = [pair[symbol][kind]['収支'] for symbol in CAP for kind in ('元会計','固定時刻反転')]
            lines.append('| '+session+' | '+' | '.join(f'{value:,.0f}' for value in values)+' |')
        group = data['aggregate'][cid]['symbols']
        vals = [group[symbol][kind]['収支'] for symbol in CAP for kind in ('元会計','固定時刻反転')]
        lines += ['| 合計 | '+' | '.join(f'{value:,.0f}' for value in vals)+' |','']
    lines += ['元115結果の一目的再集計。原NPZ・event・台帳・APIは未読、新金融0。'
              '反転後の利確・損切り・追尾を再判定した結果は、別の正式試験で確認する。','']
    return '\n'.join(lines)


def prepare() -> None:
    """
    機能: 目的・固定式・入力SHA・一読予算を本文読取前に保存する。
    引数: なし。
    返り値: None。元115source/dataへ書かない。
    """
    assert not PLAN.exists() and not OUTPUT.exists()
    write(PLAN,dict(状態='SOURCE_ONLYと人工の後、根授権の一目的読取で参考集計。',
        目的='旧115全十二条件の実時刻・数量を固定し、反対BBOの会計をFractionと直接価格式で検算する。',
        入力=dict(path=ORIGINAL.relative_to(ROOT).as_posix(),SHA256=EXPECTED,最大bytes=64*1024*1024),
        reader_SHA256=digest(Path(__file__).read_bytes()),
        読取予算=dict(旧115完成結果=1, 原NPZ=0,eventNPZ=0,台帳=0,API=0,新金融=0),
        処理='同bytesのSHA照合後、私有copyを先に保存してからparse。全12×66、全親/脚/診断を照合。',
        式='net_mirror = −midgross − spread − fee。同数量注文別floor料と新規料配賦を維持。',
        留保='保存会計の参考計算。反転後に出口を再判定した戦略でも、新たな有効性標本でもない。'))


def run() -> None:
    """
    機能: 指定した旧金融結果だけ一読し、同bytes保全の後に参考表を保存する。
    引数: なし。
    返り値: None。原入力・実台帳は読まず、金融を再生しない。
    """
    assert not OUTPUT.exists()
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    assert plan['reader_SHA256']==digest(Path(__file__).read_bytes())
    assert plan['入力']['SHA256']==EXPECTED
    before=ORIGINAL.stat()
    assert before.st_size<=plan['入力']['最大bytes']
    raw=ORIGINAL.read_bytes()
    after=ORIGINAL.stat()
    assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    assert digest(raw)==EXPECTED
    copy=HERE/'旧115完成結果の同bytes私有コピー.json'
    assert not copy.exists()
    copy.write_bytes(raw)
    data=calculate(json.loads(raw.decode('utf-8')))
    assert data['aggregate'][MAIN]['symbols']['TOPIX']['固定時刻反転']['収支']==-2168124
    assert data['aggregate'][MAIN]['symbols']['NK225']['固定時刻反転']['収支']==-745720
    data['目的固定SHA256']=digest(PLAN.read_bytes())
    data['今回目的の読取']=dict(旧115完成結果=1,原NPZ=0,eventNPZ=0,台帳=0,API=0,新金融=0)
    write(OUTPUT,data)
    md=HERE/'固定時刻反転の参考計算と全33場.md'
    assert not md.exists()
    md.write_text(markdown(data),encoding='utf-8')
    print(json.dumps(dict(全合格=True,SHA256=digest(OUTPUT.read_bytes()),counts=data['counts'],主候補=data['aggregate'][MAIN]),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    assert args.prepare_only != args.run
    prepare() if args.prepare_only else run()
