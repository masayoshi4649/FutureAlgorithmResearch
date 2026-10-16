"""一度だけ保存小結果を読み、GU候補不足・持越し・FAK0新赤字を既記録から分ける。"""

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
EXPECTED='bc50b5db84cb3f9afe329c9966863a302b0b11a8722e050207cc49c1862860b6'


def run() -> None:
    """
    機能: 根授権の結果小JSON一読だけで原因を射影し、次部品の検証範囲を固定する。
    引数: なし。
    返り値: None。新金融・元input・新旧台帳・APIは読まず、金融sourceも変更しない。
    """
    output=HERE/'FAK十八条件の候補不足と持越し及び日経新損失の小診断.json';assert not output.exists()
    path=ROOT/'work/e01_improve_20261014/engine/finance/結果.json';saved=path.read_bytes()
    sha=hashlib.sha256(saved).hexdigest();assert sha==EXPECTED;d=json.loads(saved.decode('utf-8'));del saved
    assert d['全合格'] and d['source開始終端一致']
    rows_by={cid:{(r['session'],r['symbol']):r for r in case['rows']} for cid,case in d['results'].items()}
    rows_by.update({cid:{(r['session'],r['symbol']):r for r in case['rows']} for cid,case in d['reused_results'].items()})
    configs={c['id']:c for c in d['configs']};pairs=[];carry=[];losses=[];summary={}
    for cid,case in d['results'].items():
        summary[cid]={s:dict(net=case['symbols'][s]['収支'],share=case['symbols'][s]['利益割合'],
            active=case['symbols'][s]['活動場'],black=case['symbols'][s]['黒字場'],red=case['symbols'][s]['赤字場'],
            no_trade=case['symbols'][s]['無取引場'],all_targets=case['stability'][s]['all_targets']) for s in ('TOPIX','NK225')}
        for record in d['fak_diagnosis'][cid]:
            if not record['carryover_after_unfilled_initial']:continue
            s=record['symbol'];q0=record['first_anchor']['数量'];qa=record['first_actual']['quantity']
            boundary=record['fixed_exit_boundary'];anchor=boundary['anchor'];future=record['first_actual']
            ratio=q0/qa if configs[cid]['target_id']=='P1' else anchor['quantity']*anchor['published_atr']/(qa*future['published_ATR'])
            session=record['session'];net=rows_by[cid][session,s]['収支']
            contribution=[x for x in d['各場寄与'][cid] if x['session']==session and x['symbol']==s];assert len(contribution)==1
            carry.append(dict(case_id=cid,session=session,symbol=s,net=net,nominal_target_scale_ratio=ratio,
                first_anchor=record['first_anchor'],first_actual=future,target_yen=boundary['target_yen'],contribution=contribution[0]))
        if configs[cid]['execution_id']=='FAK0':
            for change in d['各場寄与'][cid]:
                s=change['symbol'];session=change['session'];fresh=rows_by[cid][session,s]
                before=rows_by[change['baseline_id']][session,s]
                if s!='NK225' or fresh['収支']>=0 or change['収支変化']>=0:continue
                witness=[r for r in d['fak_diagnosis'][cid] if r['session']==session and r['symbol']==s];assert len(witness)==1
                losses.append(dict(case_id=cid,session=session,symbol=s,before_net=before['収支'],net=fresh['収支'],
                    new_negative_from_nonnegative=before['収支']>=0,contribution=change,first_diagnosis=witness[0]))
    for gate in ('G25','G50','G75','G50N4'):
        for symbol in ('TOPIX','NK225'):
            for execution in ('MARKET','FAK0','FAK1'):
                key=gate+'|'+execution
                if key not in d['GU_activity_summary']:continue
                value=d['GU_activity_summary'][key][symbol]
                pairs.append(dict(route=key,symbol=symbol,Day=value.get('Day'),Night=value.get('Night'),all=value['全33']))
    carry_summary={}
    for cid in configs:
        carry_summary[cid]={}
        for s in ('TOPIX','NK225'):
            group=[r for r in carry if r['case_id']==cid and r['symbol']==s]
            carry_summary[cid][s]=dict(count=len(group),positive=sum(r['net']>0 for r in group),negative=sum(r['net']<0 for r in group),
                net=sum(r['net'] for r in group),ratio_less_one=sum(r['nominal_target_scale_ratio']<1 for r in group),
                ratio_equal_one=sum(r['nominal_target_scale_ratio']==1 for r in group),ratio_greater_one=sum(r['nominal_target_scale_ratio']>1 for r in group))
    value=dict(全合格=True,source_SHA256={str(Path(__file__).relative_to(ROOT).as_posix()):hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        結果一読SHA256=sha,結果一読回数=1,summary=summary,GU_day_night=pairs,carryover=carry,carryover_summary=carry_summary,
        FAK0_NK_worsened_negative=losses,
        adaptive_hypothesis='公開balanceが強境界以上なら一T、他は零Tを当時固定する案は、新規全feed再生が必要。保存FAK0/1の勝ち親を選び直して合成しない。',
        limitations=['GU_day_nightは政策停止後suffixを含む。政策活動はrowsの実親から別集計する。',
            '持越し比は名目線の比較であり、既実現益や将来再参加を無視した必要値幅・改善PLではない。',
            '小結果は初actualのBBOと公開ATRを保持するが、全候補balanceや全親途中MAEは保持しない。適応境界の全候補採否をこの小資料から再現しない。',
            'spreadをarrival時に条件として失効させる案は、実API純価格FAKとは別模型。ライブbotで到着気配を見て発注するなら更なる次quote約定が必要。'],
        新金融=0,台帳本文=0,元input=0,原板=0,NPZ=0,API=0,金融source変更=0)
    output.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(SHA256=hashlib.sha256(output.read_bytes()).hexdigest(),GU_day_night=pairs,
        carryover_summary=carry_summary,losses=[dict(case_id=r['case_id'],session=r['session'],before=r['before_net'],after=r['net'],
            contribution=r['contribution'],first=r['first_diagnosis']['first_actual']) for r in losses]),ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':run()
