"""予定リスクの純算術を、Decimal と独立真偽表で敵対確認する。"""

import ast
from collections import Counter
from decimal import Decimal, ROUND_FLOOR
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
from types import SimpleNamespace


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/size_availability'
TOL=Decimal('0.0000001')


def load_risk() -> object:
    """
    機能: 副作用のない予定数量算術だけを指定ファイルから読む。
    引数: なし。source領域のrisk.pyに固定。
    返り値: object は純算術モジュール。project、人工main、金融sourceをimportしない。
    """
    spec=importlib.util.spec_from_file_location('size_予定数量の独立読取',SOURCE/'risk.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def old_gate(path: Path) -> tuple[object,str]:
    """
    機能: 旧公開gateの純関数だけをAST抽出し、既定採否との同値対照に使う。
    引数: path(Path) は登録済み旧policy.py。
    返り値: tuple[object,str] は関数とsourceSHA。module本体、キャッシュ、金融を実行しない。
    """
    saved=path.read_bytes();tree=ast.parse(saved);function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='verdict')
    namespace={'np':SimpleNamespace(isfinite=math.isfinite)}
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec'),namespace)
    return namespace['verdict'],hashlib.sha256(saved).hexdigest()


def decimal_fee(q: int, symbol: str) -> int:
    """
    機能: 有理十進の一注文料金を独立に切り捨てる。
    引数: q(int)、symbol(str) は数量と商品。
    返り値: int は料金。float乘算は使わない。
    """
    return int((Decimal(q)*Decimal('41.8' if symbol=='TOPIX' else '11')).to_integral_value(rounding=ROUND_FLOOR))


def decimal_amount(atr: float, bid: float, ask: float, symbol: str, q: int) -> Decimal:
    """
    機能: 保存可能な入力の十進表現から各整数qの予定額を独立計算する。
    引数: atr/bid/ask(float)、symbol(str)、q(int) は人工の当時観測値。
    返り値: Decimal は1ATR＋気配差＋注文別二料の予定額。実金融ではない。
    """
    multiplier=Decimal(1000 if symbol=='TOPIX' else 10)
    return Decimal(q)*(Decimal(str(atr))+Decimal(str(ask))-Decimal(str(bid)))*multiplier+2*decimal_fee(q,symbol)


def compare_risk(risk: object, atr: float, bid: float, ask: float, symbol: str,
                 counts: Counter, near: list[dict]) -> None:
    """
    機能: 全q額と採否をDecimalへ照合し、境界隣接の極小不一致を隠さず記録する。
    引数: risk(object)、観測3値(float)、symbol(str)、counts(Counter)、near(list[dict])。
    返り値: None。差が1e-7円を超える不一致なら拒否する。
    """
    value=risk.measure(atr,bid,ask,symbol);assert value['known'];cap=5 if symbol=='TOPIX' else 10
    budget=Decimal(5000 if symbol=='TOPIX' else 2000);assert len(value['risk_by_quantity'])==cap
    exact_q=0;old=Decimal(-1);float_old=-1.;eligible=[]
    for q,line in enumerate(value['risk_by_quantity'],1):
        exact=decimal_amount(atr,bid,ask,symbol,q);assert exact>old;old=exact
        assert line['quantity']==q and line['planned_risk_yen']>float_old;float_old=line['planned_risk_yen']
        assert abs(Decimal(str(line['planned_risk_yen']))-exact)<=TOL,(symbol,q,atr,exact,line)
        permitted=exact<=budget
        if permitted:exact_q=q
        if line['affordable']!=permitted:
            assert abs(exact-budget)<=TOL,(symbol,q,atr,exact,line)
            near.append(dict(symbol=symbol,quantity=q,ATR=atr,bid=bid,ask=ask,Decimal予定額=str(exact),
                float予定額=line['planned_risk_yen'],Decimal許可=permitted,float許可=line['affordable'],境界差円=str(exact-budget)))
        eligible.append(line['affordable']);counts['各q額と採否']+=1
    assert value['proposed_quantity']==max([0]+[q for q,ok in enumerate(eligible,1) if ok])
    assert 0<=value['proposed_quantity']<=cap and eligible==sorted(eligible,reverse=True)
    if value['proposed_quantity']!=exact_q:
        assert any(v['symbol']==symbol and v['ATR']==atr and v['bid']==bid and v['ask']==ask for v in near)
        counts['境界極小差による数量相違']+=1
    counts['全量決定と単調']+=1


def run() -> None:
    """
    機能: 元inputを読まず、純算術人工・旧gate同値・非金融射影sourceを検査する。
    引数: なし。
    返り値: None。source不変に結ぶ独立proofを保存する。
    """
    sources={p.name:(p.read_bytes(),hashlib.sha256(p.read_bytes()).hexdigest()) for p in SOURCE.glob('*.py')}
    assert set(sources)=={'risk.py','common.py','project.py','artificial.py'}
    risk=load_risk();counts=Counter();near=[];rng=random.Random(106107)
    for symbol in ('TOPIX','NK225'):
        cap=5 if symbol=='TOPIX' else 10;bid,ask=(100.,100.5) if symbol=='TOPIX' else (10000.,10010.)
        for q in range(cap+1):assert risk.fee(q,symbol)==decimal_fee(q,symbol);counts['注文別Decimal料']+=1
        assert decimal_fee(1,'TOPIX')*2==82 and decimal_fee(2,'TOPIX')+decimal_fee(3,'TOPIX')==208 and decimal_fee(5,'TOPIX')==209
        for illegal in (-1,True,1.0):
            try:risk.fee(illegal,symbol)
            except AssertionError:counts['不正数量拒否']+=1
            else:raise AssertionError(('料金の数量型不正を許可',illegal))
        budget=Decimal(5000 if symbol=='TOPIX' else 2000);multiplier=Decimal(1000 if symbol=='TOPIX' else 10)
        spread=Decimal(str(ask))-Decimal(str(bid))
        for q in range(1,cap+1):
            boundary=(budget-2*decimal_fee(q,symbol))/(Decimal(q)*multiplier)-spread
            assert boundary>0
            middle=float(boundary)
            for a in (middle-1e-7,middle,middle+1e-7,math.nextafter(middle,-math.inf),math.nextafter(middle,math.inf)):
                compare_risk(risk,a,bid,ask,symbol,counts,near)
        for i in range(600):
            a=10**rng.uniform(-4,3);width=(rng.randrange(1,7)*.5) if symbol=='TOPIX' else float(rng.randrange(1,7)*10)
            compare_risk(risk,a,bid,bid+width,symbol,counts,near)
        amounts=[.01,.1,.25,.75,1.,3.,5.,10.,30.,100.,1000.]
        qty=[risk.measure(a,bid,ask,symbol)['proposed_quantity'] for a in amounts]
        assert qty==sorted(qty,reverse=True);counts['ATR数量単調']+=1
        qty=[risk.measure(1.,bid,bid+(ask-bid)*i,symbol)['proposed_quantity'] for i in range(1,20)]
        assert qty==sorted(qty,reverse=True);counts['spread数量単調']+=1
        for a,b,c in ((math.nan,bid,ask),(math.inf,bid,ask),(0.,bid,ask),(-1.,bid,ask),
                      (1.,math.nan,ask),(1.,0.,ask),(1.,-1.,ask),(1.,bid,bid),(1.,ask,bid),
                      (1.,bid,math.inf),(1e308,bid,ask),(1e307,bid,ask)):
            v=risk.measure(a,b,c,symbol);assert not v['known'] and v['proposed_quantity'] is None and v['reason']!=0
            counts['未知とq0の区別']+=1
        zero=risk.measure(1e4,bid,ask,symbol);assert zero['known'] and zero['proposed_quantity']==0;counts['既知q0']+=1
    old,oldsha=old_gate(ROOT/'work/wave_v106/e01_trade_gate/policy.py')
    known,knownsha=old_gate(ROOT/'work/wave_v106/e01_known_veto/policy.py')
    for mode in ('VETO','CONFIRM','KNOWN_VETO'):
        for is_known in (False,True):
            for votes in (0,1,2,3,17):
                for balance in (-1.,-.2500001,-.25,-.2499999,0.,.2499999,.25,.2500001,1.):
                    base=dict(known=is_known,reason=0 if is_known else 16,direction_votes=votes if is_known else None,balance=balance if is_known else None)
                    actual=risk.gate(base,mode);expected=(known if mode=='KNOWN_VETO' else old)(base,mode)
                    allowed=is_known and votes>=2 and balance>=.25 if mode=='CONFIRM' else (not is_known or votes<2 or balance>-.25) if mode=='VETO' else is_known and votes>=2 and balance>-.25
                    assert actual==expected and actual[0]==allowed;counts['元gate同値と独立真偽']+=1
        unknown=dict(known=False,reason=8,direction_votes=None,balance=None)
        amount=risk.measure(.1,100.,100.5,'TOPIX')
        assert amount['known'] and amount['proposed_quantity']>0
        assert risk.gate(unknown,mode)[0]==(mode=='VETO');counts['票未知と数量既知の独立']+=1
    text=sources['project.py'][0].decode('utf-8-sig');tree=ast.parse(text)
    # ----------------------------------------
    # 純粋なsource確認。fix/run/mainや実入力loaderは呼ばない。
    required=('entry[9]','account[\'quotes\'][\'bid\'][normal_row]','account[\'quotes\'][\'ask\'][normal_row]',
        'base[\'candidate_raw_row\'] == raw_row','base[\'candidate_raw_seq\'] == seq',
        'base[\'candidate_price_time_s\'] == stamp','quote_valid','for session in fixed[\'sessions\']:',
        'assert checks[\'tradegate33別目的一読\'] == 33 and len(rows) == 299',
        "assert not (common.HERE/'公開予定リスク測定開始.json').exists()",'fixed[\'source_SHA256\'] == common.sources()')
    for needle in required:assert needle in text,needle;counts['同原行及び一回guard静的確認']+=1
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ('run','fix') for n in tree.body)
    assert sources=={p.name:(p.read_bytes(),hashlib.sha256(p.read_bytes()).hexdigest()) for p in SOURCE.glob('*.py')}
    out=HERE/'size_予定リスク純算術の独立確認.json';assert not out.exists()
    proof=dict(全合格=True,合格範囲='有効数量1..TOP5/NK10の注文別料、非隣接予算境界、1e-7円許容の予定額、元正常票採否。',
        確認件数=dict(counts),全検査数=sum(counts.values()),source開始終端一致=True,
        source_SHA256={('work/wave_v106/size_availability/'+k):v[1] for k,v in sources.items()},
        旧gateSourceSHA256={'work/wave_v106/e01_trade_gate/policy.py':oldsha,'work/wave_v106/e01_known_veto/policy.py':knownsha},
        Decimal厳密全境界同値=len(near)==0,境界隣接の不一致数=len(near),境界隣接の差=near,
        数値許容円=str(TOL),数値許容を超える不一致=0,
        重要留保=['sourceのfloat予定額とDecimal十進の予算境界は、IEEEの隣接値で10^-12円未満程度の差を生む。厳密十進全境界同値とは呼ばない。',
            'rootは現sourceを維持してこの数値許容留保を表示することを指定した。実金額損失上限の保証ではない。',
            'gateの既知二票以上balanceは、訂正済み保存votesの有限値契約で比較。不正なNaNを有効票と扱った保証ではない。',
            '299実射影の可用性はまだ未測。後で保存小射影の各qが予算1e-7円以内かを再集計すれば、q0主要率への境界影響を確認できる。'],
        射影静的確認=dict(当行='paper新規entry[0]の同normal-row ATR[9]と両BBO。初期支持価格や未来正常行へ代替しない。',
            系譜='mapping原row・record原seq・価格時計を当該W60候補に一致させる。quotesの原seq対応は既入力準備の合格契約を委譲。',
            資格='quote_valid=Falseは予定量未知Noneとして保つ。q0へ置換しない。',
            分母='元paper299公開と元三gateの候補分母。quiet/busy/完了場停止や実収支をまだ運転しない。',
            一回='CLI明示reviewed及び開始/False/成果不在のguard、33packet各bytes1読SHA一致、source開始終端一致。'),
        大型入力読取=0,原板=0,原NPZ=0,金融再生=0,API=0,owner_source編集=0,
        検査source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    saved=(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8');out.write_bytes(saved)
    print(hashlib.sha256(saved).hexdigest(),flush=True)
    print('全検査 '+str(proof['全検査数'])+' / IEEE隣接境界留保 '+str(len(near)),flush=True)


if __name__=='__main__':run()
