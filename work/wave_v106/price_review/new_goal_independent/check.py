"""65%・赤字20%・最大赤字が平均黒字以下の新目標を独立計算する。"""

from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import statistics


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
EPS=Decimal('.0001')
SYMBOLS=('TOPIX','NK225')


def money(value: int | float) -> Decimal:
    """
    機能: 保存円額を十進数として独立計算に用いる。
    引数: value(int|float) は有限円額。
    返り値: Decimal は十進表現。非有限の不利又は有利補完を拒否する。
    """
    result=Decimal(str(value));assert result.is_finite();return result


def quantity(case: dict) -> dict:
    """
    機能: 実数量を条件又は保存派生の明示列から確認する。
    引数: case(dict) は統一抜粋の条件と会計。
    返り値: dict は商品別の新規基準枚数と根拠。
    """
    cfg=case['meta'].get('config') or {};q=cfg.get('quantity')
    if isinstance(q,dict):return dict(values=q,根拠='config.quantity')
    if case['id'].startswith('BASE_'):
        assert case['file']=='E01取引更新と損失予算の公開会計.json'
        return dict(values={'TOPIX':5,'NK225':10},根拠='e01_trade_report.py の保存比較と公開E01の固定初回枚数。')
    values={s:{int(r['quantity']) for r in case['rows'] if r['symbol']==s and 'quantity' in r} for s in SYMBOLS}
    assert all(len(v)==1 for v in values.values()),(case['id'],values)
    return dict(values={s:next(iter(v)) for s,v in values.items()},根拠='各場の半量派生 quantity 列、商品内で全33一致。')


def metric(rows: list[dict]) -> dict:
    """
    機能: 決済親金額・活動・場ごとの収支から最新三条件を計算する。
    引数: rows(list[dict]) は一商品の対象セッション。
    返り値: dict は三目標、黒赤無取引、平均黒字場と最大赤字額。
    """
    profits=[money(r['profit']) for r in rows];losses=[money(r['loss']) for r in rows];nets=[money(r['net']) for r in rows]
    assert all(p>=0 and l>=0 and abs(p-l-n)<=EPS for p,l,n in zip(profits,losses,nets))
    gain=sum(profits,Decimal(0));loss=sum(losses,Decimal(0));net=sum(nets,Decimal(0));assert abs(gain-loss-net)<=EPS
    positive=[n for n in nets if n>EPS];negative=[n for n in nets if n<-EPS]
    active=sum(r['campaigns']>0 for r in rows);empty=len(rows)-active
    assert all(abs(money(r['net']))<=EPS and abs(money(r['profit']))<=EPS and abs(money(r['loss']))<=EPS for r in rows if r['campaigns']==0)
    assert len(positive)+len(negative)<=active
    share=gain/(gain+loss) if gain+loss else None
    average=sum(positive,Decimal(0))/len(positive) if positive else None
    worst=max((-n for n in negative),default=Decimal(0))
    red_full=Decimal(len(negative))/len(rows) if rows else None
    red_active=Decimal(len(negative))/active if active else None
    goals=dict(金額利益割合65以上=share is not None and share>=Decimal('.65'),
        赤字全場率20以下=red_full is not None and red_full<=Decimal('.2'),
        最大赤字が平均黒字以下=average is not None and worst<=average+EPS)
    # ----------------------------------------
    # 近さは目標達否を変えない補助順序。商品をまたぐ円額の大小で順位を決めない。
    deficits=[max(Decimal(0),(Decimal('.65')-share)/Decimal('.65')) if share is not None else Decimal(999),
        max(Decimal(0),red_full/Decimal('.2')-1) if red_full is not None else Decimal(999),
        max(Decimal(0),worst/average-1) if average is not None and average>0 else Decimal(999)]
    return dict(profit=float(gain),loss=float(loss),net=float(net),profit_share=float(share) if share is not None else None,
        sessions=len(rows),active=active,no_trade=empty,positive=len(positive),negative=len(negative),flat_active=active-len(positive)-len(negative),
        red_full_rate=float(red_full) if red_full is not None else None,red_active_rate=float(red_active) if red_active is not None else None,
        average_positive_session_net=float(average) if average is not None else None,maximum_negative_session_loss=float(worst),
        maximum_loss_over_average_positive=float(worst/average) if average is not None and average else None,
        median_net=float(statistics.median(nets)) if nets else None,
        mean_net_all_sessions=float(net/len(rows)) if rows else None,
        goals=goals,pass_all=all(goals.values()),pass_all_red_active=goals['金額利益割合65以上'] and red_active is not None and red_active<=Decimal('.2') and goals['最大赤字が平均黒字以下'],
        passed_components=sum(goals.values()),distance_max=float(max(deficits)),distance_sum=float(sum(deficits)),
        少活動の留保=active<16,少活動の定義='16場未満を留保表示する。ユーザーの三目標へ活動条件を勝手に追加しない。')


def evaluate(case: dict, symbol: str) -> dict:
    """
    機能: 全33場と正の収支上位3場除外をそれぞれ再集計する。
    引数: case(dict) は統一会計、symbol(str) は商品。
    返り値: dict は全33及び除外後。除外後の平均黒字も取り直す。
    """
    indexed={r['session']:r for r in case['rows'] if r['symbol']==symbol}
    assert len(indexed)==33 and set(indexed)==set(case['sessions'])
    rows=[indexed[s] for s in case['sessions']]
    positives=sorted((r for r in rows if money(r['net'])>EPS),key=lambda r:money(r['net']),reverse=True)
    removed=positives[:3];removed_names={r['session'] for r in removed};remaining=[r for r in rows if r['session'] not in removed_names]
    full,cut=metric(rows),metric(remaining)
    assert abs(money(full['net'])-money(cut['net'])-sum((money(r['net']) for r in removed),Decimal(0)))<=EPS
    assert abs(money(full['profit'])-money(cut['profit'])-sum((money(r['profit']) for r in removed),Decimal(0)))<=EPS
    assert abs(money(full['loss'])-money(cut['loss'])-sum((money(r['loss']) for r in removed),Decimal(0)))<=EPS
    return dict(full33=full,top3_excluded=cut,excluded_sessions=[r['session'] for r in removed],
        removed_positive_count=len(removed),三場除外成立=len(removed)==3,
        除外後リスク基準='最大赤字を残る黒字セッションnetの平均と比較。元33の平均を使い回さない。')


def signature(case: dict, q: dict) -> str:
    """
    機能: 保存経済結果の全場列を正規化し、同値結果の水増しを避ける指紋を作る。
    引数: case/q(dict) は会計と数量。
    返り値: str はSHA。結果同値はアルゴリズム同一の証明とは扱わない。
    """
    keys=('profit','loss','net','fees','campaigns','winning_campaigns','losing_campaigns','winning_lots','losing_lots')
    rows=[]
    for r in sorted(case['rows'],key=lambda v:(v['session'],v['symbol'])):
        rows.append([r['session'],r['symbol']]+[str(money(r.get(k,0)).quantize(EPS).normalize()) for k in keys])
    saved=json.dumps(dict(q=q['values'],rows=rows),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(saved).hexdigest()


def artificial() -> None:
    """
    機能: 平均親利益との違い、混在利益場の除外、無取引の非勝ちを小人工で確認する。
    引数: なし。
    返り値: None。市場又は金融は再生しない。
    """
    base=[dict(session=str(i),symbol='TOPIX',profit=p,loss=l,net=p-l,campaigns=n) for i,(p,l,n) in enumerate(((200,100,2),(80,0,1),(70,0,1),(0,50,1),(0,0,0)))]
    value=metric(base);assert value['average_positive_session_net']==250/3 and value['no_trade']==1 and value['negative']==1
    assert value['profit_share']==350/500 and value['pass_all']
    removed=sorted((r for r in base if r['net']>0),key=lambda r:r['net'],reverse=True)[:3]
    cut=metric([r for r in base if r not in removed]);assert cut['profit']==0 and cut['loss']==50 and cut['average_positive_session_net'] is None and not cut['pass_all']
    empty=metric([dict(profit=0,loss=0,net=0,campaigns=0)]);assert empty['profit_share'] is None and not empty['pass_all']


def run() -> None:
    """
    機能: 根の新目標再集計を参照せず、全保存候補と別名を独立検算する。
    引数: なし。所有域の統一抜粋だけを読む。
    返り値: None。全候補達否・同値集約・近い候補を新JSONへ保存する。
    """
    artificial();path=HERE/'全schema統一会計行.json';saved=path.read_bytes();source=json.loads(saved)
    candidates=source['candidates'];assert len(candidates)==360
    cases=[];seen={};checks=0
    for c in candidates:
        q=quantity(c);sig=signature(c,q);meta=c['meta'];cfg=meta.get('config') or {}
        ideal=cfg.get('execution')=='PRICE' or c['id']=='L_D20_PRICE'
        derived=bool(meta.get('derived') or meta.get('saved_alias'))
        all_alias_rows=all('economic_alias' in r for r in c['rows'])
        prior=seen.get(c['id'])
        if prior is not None:assert sig==prior,(c['id'],c['file']);derived=True
        else:seen[c['id']]=sig
        value=dict(id=c['id'],file=c['file'],source_path=c['source_path'],source_SHA256=c['source_SHA256'],
            config=cfg,quantity=q,ideal_PRICE=ideal,明示派生又は再掲載=derived,同ID再掲載=prior is not None,
            alias_source_id=meta.get('alias_source_id'),全原行会計が保存alias=all_alias_rows,
            結果経済同値SHA256=sig,model='現在値の理想参考' if ideal else '固定指値到達全量仮定・待ち順位未確認' if cfg.get('method')=='RESTING' else '正常ラージBBO代理・実ミニmicro気配未確認',
            symbols={s:evaluate(c,s) for s in SYMBOLS})
        checks+=66;cases.append(value)
    independent=[c for c in cases if not c['ideal_PRICE'] and not c['明示派生又は再掲載']]
    groups={}
    for c in independent:groups.setdefault(c['結果経済同値SHA256'],[]).append(c)
    summary={}
    for period in ('full33','top3_excluded'):
        counts={s:dict(合格ID=[c['id'] for c in independent if c['symbols'][s][period]['pass_all']],
            活動16場以上の合格ID=[c['id'] for c in independent if c['symbols'][s][period]['pass_all'] and c['symbols'][s][period]['active']>=16]) for s in SYMBOLS}
        common=[c['id'] for c in independent if all(c['symbols'][s][period]['pass_all'] for s in SYMBOLS)]
        group_common=[dict(同値SHA256=key,IDs=[c['id'] for c in group]) for key,group in groups.items() if all(group[0]['symbols'][s][period]['pass_all'] for s in SYMBOLS)]
        nearest={}
        for s in SYMBOLS:
            ranked=sorted(independent,key=lambda c:(-c['symbols'][s][period]['passed_components'],c['symbols'][s][period]['distance_max'],c['symbols'][s][period]['distance_sum'],-c['symbols'][s][period]['active'],c['id']))
            chosen=[];fingerprints=set()
            for c in ranked:
                if c['結果経済同値SHA256'] in fingerprints:continue
                fingerprints.add(c['結果経済同値SHA256']);chosen.append(dict(id=c['id'],quantity=c['quantity'],model=c['model'],metric=c['symbols'][s][period],source_path=c['source_path']))
                if len(chosen)==5:break
            nearest[s]=chosen
        summary[period]=dict(商品別=counts,共通両商品合格ID=common,共通両商品合格経済群=group_common,最も近い保存候補=nearest)
    # ----------------------------------------
    # alias が原IDを明記する場合は、結果が同じことを独立照合する。比較元のbaselineはalias扱いしない。
    by_id={c['id']:c for c in cases};alias_checks=[]
    for c in cases:
        target=c['alias_source_id']
        if target in by_id:
            assert c['結果経済同値SHA256']==by_id[target]['結果経済同値SHA256'],(c['id'],target)
            alias_checks.append(dict(id=c['id'],source_id=target,同値=True))
    expected_cases=Counter(c['file'] for c in cases);assert sum(expected_cases.values())==360
    proof=dict(全合格=True,定義=dict(利益割合='実親利益円合計/(実親利益円合計+実親損失円合計)>=65%。',
        赤字='赤字セッション数/対象全セッション数<=20%。活動場分母も別表示。無取引は勝ちではない。',
        損失='最大赤字セッションのnet絶対額<=黒字セッションnetの算術平均。平均親利益とは別。',
        除外='商品・条件ごとにnet>0上位最大3場を除き、利益損失合計と平均黒字リスク基準をすべて取り直す。三場未満はその件数を明示。',
        金額許容='会計浮動誤差0.0001円のみ。目標割合の閾値は正確な十進数。',
        合格='ユーザーの三条件だけの達否。活動16場未満は留保タグであり追加の隠れ条件にはしない。',
        経済同値='同じID及び明示aliasは別の経済試行として数えない。異なるルールで保存結果が一致する群も複数の成功として数えないが、アルゴリズム同一の証明ではない。'),
        表示候補数=360,実用表示候補数=sum(not c['ideal_PRICE'] for c in cases),理想PRICE表示数=sum(c['ideal_PRICE'] for c in cases),
        同ID及び明示派生を除いた実用ID数=len(independent),保存経済同値群数=len(groups),資料別表示数=dict(expected_cases),
        summaries=summary,cases=cases,同ID系譜確認=alias_checks,
        結果入力=dict(path=path.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(saved).hexdigest(),source_files=source['files']),
        独立自己検査=dict(人工='無取引非勝ち・黒字場net平均・混在場の利益損失両方除外を確認。',検算行数=checks,
            全候補33場66商品期間=True,金額恒等式=True,除外金額恒等式=True,同ID及び指示alias照合=True),
        限界=['既知33場の保存結果の再評価。新金融成果や未見への勝率・効能の証拠ではない。',
            '少数活動なら三目標へ合格しても毎場安定して稼ぐ根拠にはならない。活動・無取引を必ず併記する。',
            '商品別枚数10/20と初回5/10等を区別し、商品の円額を単純順位比較しない。',
            '金額利益割合は投資元本へのROIではない。待ち順位、実小型商品気配を今回確認していない。'],
        root新再集計参照=0,公開編集=0,共通知見編集=0,金融再生=0,原板=0,原NPZ=0,API=0,
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    out=HERE/'最新65割合と20赤字及び一場損失の独立全候補確認.json';assert not out.exists()
    payload=(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8');out.write_bytes(payload)
    print('SHA '+hashlib.sha256(payload).hexdigest(),flush=True)
    print('表示360 / 実用独立ID '+str(len(independent))+' / 保存経済群 '+str(len(groups)),flush=True)
    for name,s in summary.items():
        print(name+' 合格 '+str({y:len(s['商品別'][y]['合格ID']) for y in SYMBOLS})+' 共通 '+str(s['共通両商品合格ID']),flush=True)
        for y in SYMBOLS:print(y+' nearest '+str(s['最も近い保存候補'][y][0]),flush=True)


if __name__=='__main__':run()
