"""変更後の三基準を、保存元・少数合格・未取引の扱いから敵対的に確認する。"""

from collections import defaultdict
from fractions import Fraction
import hashlib
from pathlib import Path
import json
import math
import statistics

from range_engine_check import digest, load


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/new_goal'


def read(path: Path) -> dict:
    """
    機能: 保存された小会計と再集計結果だけを解析する。
    引数: path(Path)はJSONの位置。
    返り値: dictは解析内容。新金融・raw・NPZ・APIを呼ばない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def original_row(value: dict) -> dict:
    """
    機能: 検査対象の六項目を、元公開会計の列名から独立に取り出す。
    引数: value(dict)は元一場一商品会計。
    返り値: dictは正規化六項目。正負損益を場収支へ相殺し直さない。
    """
    pairs = {'profit':'利益','loss':'損失','net':'収支','campaigns':'親数','fees':'費用'}
    result = dict(session=value['session'],symbol=value['symbol'])
    for key,other in pairs.items(): result[key] = value[key] if key in value else value[other]
    return result


def metric(rows: list[dict]) -> dict:
    """
    機能: 整数場数と費用後P/Lから三条件を独立算定する。
    引数: rows(list[dict])は一商品の完結場。
    返り値: dictは分母・金額割合・平均黒字補填の計算値。
    """
    gain = sum(r['profit'] for r in rows); loss = sum(r['loss'] for r in rows)
    green = [r['net'] for r in rows if r['net']>0]; red = [-r['net'] for r in rows if r['net']<0]
    active = [r for r in rows if r['campaigns']>0]
    average = sum(green)/len(green) if green else None
    maximum = max(red) if red else 0
    share = gain/(gain+loss) if gain+loss else None
    samples = [r['profit']/(r['profit']+r['loss']) for r in active if r['profit']+r['loss']]
    tests = dict(金額利益65以上=share is not None and share>=.65-1e-12,
        赤字全場20以下=5*len(red)<=len(rows),最大赤字は平均黒字以下=average is not None and maximum<=average+1e-9)
    return dict(profit=gain,loss=loss,net=gain-loss,profit_share=share,profit_factor=gain/loss if loss else None,
        sessions=len(rows),active=len(active),no_trade=len(rows)-len(active),green=len(green),red=len(red),
        flat_active=sum(r['net']==0 for r in active),red_all=len(red)/len(rows) if rows else None,
        red_active=len(red)/len(active) if active else None,mean_green=average,
        median_green=statistics.median(green) if green else None,worst_red=maximum,
        mean_red=sum(red)/len(red) if red else None,loss_recovery_ratio=maximum/average if average else None,
        median_net=statistics.median(r['net'] for r in rows) if rows else None,
        active_median_net=statistics.median(r['net'] for r in active) if active else None,
        session_share_mean=sum(samples)/len(samples) if samples else None,session_share_mean_samples=len(samples),
        tests=tests,pass_all=all(tests.values()),active_red_test=bool(active and 5*len(red)<=len(active)),
        pass_active=all(tests.values()) and bool(active and 5*len(red)<=len(active)))


def equal(actual: object, expected: object) -> None:
    """
    機能: 算術参考値の浮動残差だけを許し、Noneと件数を厳密比較する。
    引数: actual/expected(object)は結果と独立期待値。
    返り値: None。不明を0や100%として救済しない。
    """
    if expected is None: assert actual is None
    elif isinstance(expected,(int,bool,str,dict)): assert actual==expected
    else: assert math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-7),(actual,expected)


def main() -> None:
    """
    機能: 公開10資料・358IDの全33場及び条件値と、単独合格の大勝ち依存を確認する。
    引数: なし。保存台帳を再生せず、再集計sourceも変更しない。
    返り値: Noneは所有領域の敵対監査証跡。独立試行数を増やさない。
    """
    target = HERE/'goal107_保存元と新三基準及び希少活動の独立監査.json'; assert not target.exists()
    path = SOURCE/'保存全候補の65比率と赤字頻度及び平均黒字補填力.json'; data = read(path)
    assert data['全合格'] and data['source_sha256']==digest(SOURCE/'reaggregate.py')
    assert all(data[k]==0 for k in ('新金融再生','原板読込','NPZ読込','API取得'))
    originals = {}; displays = 0; sources = {}; quantity_notes = {}; model_notes = {}
    for item in data['inputs']:
        source = ROOT/item['path']; assert digest(source)==item['sha256']; public = read(source)
        sources[item['path']]=item['sha256']; assert public.get('全合格',True)
        configs = {c['id']:c for c in public.get('configs',[])}
        for ident,case in public.get('cases',public.get('results',{})).items():
            displays += 1; rows = sorted([original_row(r) for r in case['rows']],key=lambda r:(r['symbol'],r['session']))
            if ident in originals: assert originals[ident]==rows
            else: originals[ident]=rows
            config = case.get('config') or case.get('case') or configs.get(ident,{})
            model_notes.setdefault(ident,[]).append(dict(公開元=source.name,execution=config.get('execution'),resting=config.get('method')))
            quantity = config.get('quantity') or config.get('数量')
            if isinstance(quantity,dict):
                assert all(0<quantity[m]<=cap for m,cap in (('TOPIX',10),('NK225',20)))
                quantity_notes.setdefault(ident,[]).append(quantity)
    assert displays==360 and len(originals)==len(data['cases'])==358
    assert set(originals)==set(data['cases'])
    sessions = sorted({r['session'] for r in next(iter(originals.values()))}); assert len(sessions)==33
    both_full = []; both_robust = []; per = {m:dict(full_pass=[],robust_pass=[],active_pass=[]) for m in ('TOPIX','NK225')}
    numerical_groups = defaultdict(list); audit_count = 0
    for ident,case in data['cases'].items():
        assert case['rows']==originals[ident]
        canonical = json.dumps(case['rows'],sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')
        rowhash = hashlib.sha256(canonical).hexdigest(); assert rowhash==case['monetary_row_hash']; numerical_groups[rowhash].append(ident)
        for r in case['rows']:
            assert r['profit']>=0 and r['loss']>=0 and math.isclose(r['net'],r['profit']-r['loss'],rel_tol=0,abs_tol=1e-6)
            assert r['campaigns']>=0 and int(r['campaigns'])==r['campaigns']
            if r['campaigns']==0: assert r['profit']==r['loss']==r['net']==r['fees']==0
        for symbol in ('TOPIX','NK225'):
            rows = sorted([r for r in case['rows'] if r['symbol']==symbol],key=lambda r:r['session'])
            assert [r['session'] for r in rows]==sessions
            metric_full = metric(rows); expected = case['symbols'][symbol]
            for key,value in metric_full.items(): equal(expected['full'][key],value); audit_count += 1
            best = sorted([r for r in rows if r['net']>0],key=lambda r:(-r['net'],r['session']))[:3]
            assert expected['removed']==[dict(session=r['session'],net=r['net']) for r in best]
            removed = {r['session'] for r in best}; tail = metric([r for r in rows if r['session'] not in removed])
            for key,value in tail.items(): equal(expected['without_top3'][key],value); audit_count += 1
            robust = metric_full['pass_all'] and tail['tests']['金額利益65以上'] and tail['tests']['最大赤字は平均黒字以下']
            assert expected['robust_pass']==robust
            # 33場・赤字最大6場・正場除外最大3なら、除外後全場赤字20%は自動的に保持される。
            if robust: assert tail['tests']['赤字全場20以下']
            if not case['ideal_reference']:
                if metric_full['pass_all']: per[symbol]['full_pass'].append(ident)
                if robust: per[symbol]['robust_pass'].append(ident)
                if metric_full['pass_active']: per[symbol]['active_pass'].append(ident)
        assert case['ideal_reference']==(case['config'].get('execution')=='旧現在値参考')
        if not case['ideal_reference'] and all(case['symbols'][m]['full']['pass_all'] for m in ('TOPIX','NK225')): both_full.append(ident)
        if not case['ideal_reference'] and all(case['symbols'][m]['robust_pass'] for m in ('TOPIX','NK225')): both_robust.append(ident)
    assert per==data['summary']['per_symbol'] and both_full==data['summary']['both_full_pass']==[] and both_robust==data['summary']['both_robust_pass']==[]
    assert data['summary']['display_cases']==360 and data['summary']['distinct_ids']==358 and data['summary']['eligible_ids']==357
    assert data['summary']['ideal_reference_ids']==['L_D20_PRICE']
    actual_groups = [g for g in numerical_groups.values() if len(g)>1]; assert actual_groups==data['summary']['economic_same_account_groups']
    # ----------------------------------------
    # 無取引による分母の薄まり・場内相殺・ゼロ収支活動を、手計算可能な会計人工で確認する。
    M = load('新目標の静的再集計検査対象',SOURCE/'reaggregate.py')
    empty = [dict(session=f'人工{i:02}',symbol='TOPIX',profit=0,loss=0,net=0,campaigns=0,fees=0) for i in range(33)]
    zero = M.statistics(empty); assert zero['profit_share'] is None and zero['mean_green'] is None and not zero['pass_all']
    rare = [dict(r) for r in empty]; rare[0].update(profit=1000,net=1000,campaigns=1)
    for row in rare[1:5]: row.update(loss=1,net=-1,campaigns=1)
    scarce = M.statistics(rare); assert scarce['pass_all'] and not scarce['pass_active'] and scarce['green']==1 and scarce['red']==4 and scarce['no_trade']==28
    trimmed = M.measure(rare); assert not trimmed['robust_pass'] and trimmed['without_top3']['mean_green'] is None
    flat = [dict(session='人工',symbol='TOPIX',profit=10,loss=10,net=0,campaigns=1,fees=0)]
    same = M.statistics(flat); assert same['active']==1 and same['no_trade']==0 and same['flat_active']==1 and same['profit_share']==.5
    mixed = [dict(session='人工',symbol='TOPIX',profit=900,loss=800,net=100,campaigns=2,fees=0),
        dict(session='人工2',symbol='TOPIX',profit=100,loss=0,net=100,campaigns=1,fees=0)]
    mix = M.statistics(mixed); assert mix['mean_green']==100 and math.isclose(mix['profit_share'],float(Fraction(5,9)))
    chosen = sorted(set(per['TOPIX']['full_pass']+per['NK225']['full_pass']+[
        'E01_TRADE_W60_VETO_D0_P1L8','E01_TRADE_W60_KNOWN_VETO_D0_P1L8','E01_TRADE_W60_CONFIRM_D0_P1L8']))
    candidate_notes = {ident:{m:dict(全場=data['cases'][ident]['symbols'][m]['full'],上位3除外=data['cases'][ident]['symbols'][m]['without_top3'])
        for m in ('TOPIX','NK225')} for ident in chosen}
    proof = dict(全合格=True,範囲='00103公開10資料の同じ33場・360掲載/358IDを保存元へ照合し、三基準・除外後・希少活動の定義を確認。全過去試行の金融再生ではない。',
        結果SHA256=digest(path),集計sourceSHA256=digest(SOURCE/'reaggregate.py'),レビューsource_SHA256=digest(Path(__file__)),
        公開保存元SHA256=sources,主数値照合項目数=audit_count,全掲載=360,全ID=358,理想参考除外=['L_D20_PRICE'],主評価ID=357,
        銘柄別数値合格=per,同条件両銘柄数値合格=both_full,同条件両銘柄頑健性合格=both_robust,
        少数合格と代表=candidate_notes,数量が明示されたID=len(quantity_notes),約定モデルの公開記載=model_notes,
        会計人工=dict(無取引不合格=True,希少活動が全場三条件だけでは合格する=True,上位除外でその依存を排除=True,
            零収支活動を無取引に置換しない=True,黒字平均は場内損失を差引いた収支=True),
        新金融=0,原板=0,NPZ=0,API=0,元固定source編集=0,
        留意点=['TOPIX数値合格2IDは同じ掲載会計で、2黒字4赤字27無取引。日経の6IDは各1黒字32無取引、別1IDも3黒字4赤字26無取引。いずれも大勝ち上位を除くと基準を保てない。',
            '経済同値groupは六項目の掲載会計同値だけ。全注文・最大含み損・実装仕様の同値を追加証明するものではない。',
            'PRICE文字列ではなく、execution=旧現在値参考を除外した。価格だけの入口と理想約定を混同しない。',
            '主65は金額合計比。各活動場比の単純平均は参考であり、同じ閾値の追加必須条件にしていない。',
            '評価基準変更後の保存会計再集計で、新しい未知場検証や利益法則の追加証拠ではない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('変更後三基準の敵対的独立監査合格',audit_count,digest(target))


if __name__=='__main__': main()
