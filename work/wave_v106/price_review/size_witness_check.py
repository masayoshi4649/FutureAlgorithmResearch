"""完成小射影299だけから予定整数量をDecimalで独立再計算する。"""

from collections import Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

from size_pure_check import decimal_amount, decimal_fee


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/size_availability'
TOL=Decimal('0.0000001')


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 完成済み小JSONを同bytes一読して指紋と内容を返す。
    引数: path(Path) は射影・固定計画・開始記録又は独立純算術proof。
    返り値: tuple[dict,str] は資料とSHA256。元packetや原NPZへ接続しない。
    """
    saved=path.read_bytes();return json.loads(saved),hashlib.sha256(saved).hexdigest()


def gate(value: dict, mode: str) -> tuple[bool,int]:
    """
    機能: 当時W60の三採否を独立真偽表で判定する。
    引数: value(dict)、mode(str) は当時票及び政策。
    返り値: tuple[bool,int] は公開採否と理由。実busyや口座停止は判断しない。
    """
    if not value['known']:return (True,0) if mode=='VETO' else (False,100+value['reason'])
    if value['direction_votes']<2:return (True,0) if mode=='VETO' else (False,200)
    balance=Decimal(str(value['balance']));assert balance.is_finite()
    if mode=='CONFIRM':return (True,0) if balance>=Decimal('.25') else (False,201)
    return (False,202) if balance<=Decimal('-.25') else (True,0)


def group(rows: list[dict], mode: str) -> dict:
    """
    機能: 全公開又は元公開採否の分母で、未知・予定q0・正量を独立集計する。
    引数: rows(list[dict]) は実小射影、mode(str) は全公開又は三採否。
    返り値: dict は可用性。取引・勝ち・無取引場の成績とは呼ばない。
    """
    selected=rows if mode=='全公開' else [r for r in rows if gate(r['W60'],mode)[0]]
    known=[r for r in selected if r['sizing']['known']];zero=sum(r['independent_quantity']==0 for r in known)
    return dict(公開分母=len(selected),予定量既知=len(known),予定量未知=len(selected)-len(known),
        q0公開=zero,正量公開=len(known)-zero,q0割合_全公開分母=zero/len(selected) if selected else None,
        q0割合_予定量既知分母=zero/len(known) if known else None,
        数量分布=dict(Counter(str(r['independent_quantity']) for r in known)))


def run() -> None:
    """
    機能: 実299全q、近接境界、系譜、三採否、33場joinと射影実行の一読記録を検算する。
    引数: なし。完成小射影と小計画だけ。
    返り値: None。追補proofへ保存し、owner源・巨大入力・金融を扱わない。
    """
    target=SOURCE/'公開299のATR両気配と予定数量可用性.json'
    projection,projection_sha=read(target)
    assert projection_sha=='67014ed5401371e86bcbf32f2e5bc94a5cb07e9c27954c8a133040574c3e74fa' and projection['全合格']
    plan,plan_sha=read(SOURCE/'公開299予定リスクの非金融固定計画.json')
    start,start_sha=read(SOURCE/'公開予定リスク測定開始.json')
    pure,pure_sha=read(HERE/'size_予定リスク純算術の独立確認.json')
    assert pure['全合格'] and projection['計画SHA256']==plan_sha==start['計画SHA256']
    assert projection['source_SHA256']==plan['source_SHA256']==pure['source_SHA256']
    assert projection['開始終端source不変'] and projection['初回全予算のみ'] and not projection['remainingbudget運転']
    assert len(plan['sessions'])==len(set(plan['sessions']))==len(plan['input33'])==projection['大型読取']==33
    assert projection['一致検査']['tradegate33別目的一読']==33 and projection['一致検査']['公開原行時計一致']==299
    assert start['全合格'] and start['新金融']==projection['新金融']==0
    source_current={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.glob('*.py')}
    assert source_current==projection['source_SHA256']
    rows=projection['witness'];assert len(rows)==299;keys=set();counts=Counter();near=[];q_differences=[]
    lineages=[];last={}
    for row in rows:
        symbol=row['symbol'];cap=5 if symbol=='TOPIX' else 10;budget=Decimal(5000 if symbol=='TOPIX' else 2000)
        key=(row['session'],symbol,row['paper_parent']);assert key not in keys;keys.add(key)
        assert row['session'] in plan['sessions'] and row['side'] in (-1,1) and row['original_qty']==cap
        stamp=row['price_time_s'];assert math.isfinite(stamp)
        assert row['JST']==datetime.fromtimestamp(stamp,timezone(timedelta(hours=9))).isoformat()
        base=row['W60'];assert base['candidate_raw_row']==row['raw_row'] and base['candidate_raw_seq']==row['raw_seq'] and base['candidate_price_time_s']==stamp
        assert base['last_vote_raw_row']<=row['raw_row']
        pair=(row['session'],symbol)
        if pair in last:
            assert row['publish_normal_row']>last[pair][0] and row['raw_row']>last[pair][1] and row['raw_seq']>last[pair][2]
        last[pair]=(row['publish_normal_row'],row['raw_row'],row['raw_seq']);counts['同親原行時計JST確認']+=1
        assert row['quote_valid'] and all(math.isfinite(row[k]) for k in ('ATR','bid','ask')) and row['ATR']>0 and 0<row['bid']<row['ask']
        sizing=row['sizing'];assert sizing['known'] and sizing['reason']==0 and sizing['maximum_quantity']==cap
        assert len(sizing['risk_by_quantity'])==cap
        exact_qty=0;old=Decimal(-1);minimum_distance=None
        for q,saved in enumerate(sizing['risk_by_quantity'],1):
            amount=decimal_amount(row['ATR'],row['bid'],row['ask'],symbol,q);assert amount>old;old=amount
            assert abs(amount-Decimal(str(saved['planned_risk_yen'])))<=TOL
            affordable=amount<=budget;assert saved['quantity']==q
            distance=abs(amount-budget);minimum_distance=distance if minimum_distance is None else min(minimum_distance,distance)
            if distance<=TOL:near.append(dict(session=row['session'],symbol=symbol,parent=row['paper_parent'],quantity=q,Decimal差=str(amount-budget)))
            if affordable:exact_qty=q
            if saved['affordable']!=affordable:q_differences.append(dict(key=key,q=q,Decimal額=str(amount),float額=saved['planned_risk_yen']))
            counts['全整数予定額と採否Decimal検算']+=1
        assert exact_qty==sizing['proposed_quantity'],(key,exact_qty,sizing)
        row['independent_quantity']=exact_qty
        for mode in ('VETO','CONFIRM','KNOWN_VETO'):
            accepted,reason=gate(base,mode)
            assert row['old_gate'][mode]==dict(allowed=accepted,reason=reason);counts['三元採否確認']+=1
        unit=Decimal(1000 if symbol=='TOPIX' else 10);fee=decimal_fee(1,symbol)
        maximum_atr_for_one=(budget-2*fee)/unit-(Decimal(str(row['ask']))-Decimal(str(row['bid'])))
        lineages.append(dict(session=row['session'],symbol=symbol,parent=row['paper_parent'],normal_row=row['publish_normal_row'],
            raw_row=row['raw_row'],raw_seq=row['raw_seq'],JST=row['JST'],minimum_budget_distance_yen=str(minimum_distance),
            one_lot_maximum_ATR=float(maximum_atr_for_one),published_ATR=row['ATR'],independent_quantity=exact_qty))
    assert not q_differences and not near
    whole={};per_session={}
    for symbol in ('TOPIX','NK225'):
        part=[r for r in rows if r['symbol']==symbol]
        whole[symbol]={mode:group(part,mode) for mode in ('全公開','VETO','CONFIRM','KNOWN_VETO')}
        assert whole[symbol]==projection['商品別'][symbol]
        assert whole[symbol]['全公開']['公開分母']==plan['expected'][symbol]['publish']
        for mode in ('VETO','CONFIRM','KNOWN_VETO'):assert whole[symbol][mode]['公開分母']==plan['expected'][symbol][mode]
    for session in plan['sessions']:
        per_session[session]={symbol:{mode:group([r for r in rows if r['session']==session and r['symbol']==symbol],mode)
            for mode in ('全公開','VETO','CONFIRM','KNOWN_VETO')} for symbol in ('TOPIX','NK225')}
        assert per_session[session]==projection['各場'][session];counts['33場join集計一致']+=1
    assert source_current=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.glob('*.py')}
    proof=dict(全合格=True,対象='完成小射影299の整数予定リスク可用性の独立追補',検査件数=dict(counts),
        実公開数=299,全整数q計算数=counts['全整数予定額と採否Decimal検算'],実例でDecimal採否又は数量不一致=0,
        予算境界1e_7円以内の実例数=len(near),境界接近実例=near,商品別=whole,各場=per_session,系譜と一枚許容量=lineages,
        影響解釈='純人工で留保したIEEE境界隣接差は実299に1e-7円以内の近接例がなく、今回のq0集計はDecimalでも全件同じ。',
        分母='元paper新規公開。三gateの公開採否から派生。実busy・利益停止・損失余力・fillをまだ計算していない。',
        source=[dict(path=target.relative_to(ROOT).as_posix(),SHA256=projection_sha,pointer='/witness'),
            dict(path=(SOURCE/'公開299予定リスクの非金融固定計画.json').relative_to(ROOT).as_posix(),SHA256=plan_sha),
            dict(path=(SOURCE/'公開予定リスク測定開始.json').relative_to(ROOT).as_posix(),SHA256=start_sha),
            dict(path=(HERE/'size_予定リスク純算術の独立確認.json').relative_to(ROOT).as_posix(),SHA256=pure_sha)],
        ownerSource開始終端一致=True,source_SHA256=source_current,
        一読guard='CLI/開始/False/成果不在のowner静的guardと、開始記録・source不変・33packet一読完了件数を結合した。元packet33の再読で再確認したものではない。',
        読取小JSON数=4,読取元packet=0,大型入力=0,原板=0,原NPZ=0,新金融=0,API=0,ownerSource変更=0,
        検査source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    out=HERE/'size_公開299の全qと境界及び33場分母の独立確認.json';assert not out.exists()
    saved=(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8');out.write_bytes(saved)
    print(hashlib.sha256(saved).hexdigest(),flush=True)
    print('実299 / 全整数2255 / Decimal不一致0 / 1e-7円接近0',flush=True)


if __name__=='__main__':run()
