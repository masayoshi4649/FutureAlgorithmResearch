"""保険入口の完全一致を確認し、停止基準の違いによる返済値と損失幅を分解する。"""
from collections import defaultdict
from pathlib import Path
import importlib.util
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROUND=HERE.parent
ROOT=ROUND.parents[2]


def module(name,path):
    """
    機能: 旧解析の読み取り会計を固有名で参照する。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


source=module('wave87_structure_analysis_prior',ROUND.parent/'round8/analysis/diagnose.py')
prior=source.prior


def extract(result,ledgers,inputs):
    """
    機能: 同じ保険入口へ新規時の初期停止価格・名目リスクを接続する。
    引数: result/ledgers/inputs(dict)。
    返り値: list[dict]。停止価格での約定を保証する指標とはしない。
    """
    records=source.extract(result,ledgers,inputs)
    for record in records:
        if not record['sat_active']:continue
        key=(record['session'],record['symbol']);ledger=ledgers[key]
        ee=ledger['structure_events'];matched=ee[ee[:,1]==record['campaign']]
        assert len(matched)==1
        e=matched[0];assert e[0]==record['sat_entry_row'] and e[3]<e[0]
        scale=1000 if record['symbol']=='TOPIX' else 10
        fee=41.8 if record['symbol']=='TOPIX' else 11
        risk=e[8]*(e[7]-e[6]);oldrisk=e[8]*(e[7]-e[5])
        record['初期停止']=dict(方式=int(e[2]),極値元行=int(e[3]),過去極値=e[4],
            旧建値基準線=e[5],実初期線=e[6],建値=e[7],初期線までの損失幅=risk,
            初期線までの損失ATR=risk/e[10],旧基準の損失ATR=oldrisk/e[10],
            固定ATR=e[10],呼値=inputs[key]['tick'],初期線までの損失呼値数=risk/inputs[key]['tick'],
            線で返済できた場合の名目料金込損失=risk*e[9]*scale+2*np.floor(e[9]*fee+1e-8),
            新規当行破断済み=bool(e[11]))
    return records


def pairs(groups,model,fixed):
    """
    機能: 四入口それぞれで、停止方式間の全新規と根拠を一致検査する。
    引数: groups(dict)、model(str)、fixed(dict)。
    返り値: list[dict]。収支差を返済値差と料金差へ恒等分解する。
    """
    output=[]
    for prepare in ('00','50'):
        for confirm in (0,1):
            identifiers=[f'K_P{prepare}_C{confirm}_S{x}' for x in range(4)]
            maps=[{(x['session'],x['symbol'],x['campaign']):x for x in groups[ident]} for ident in identifiers]
            assert all(x.keys()==maps[0].keys() for x in maps)
            for target in (1,2,3):
                for key,x in maps[0].items():
                    y=maps[target][key]
                    assert x['sat_active']==y['sat_active'] and x['core_net']==y['core_net']
                    if not x['sat_active']:continue
                    for name in ('sat_entry_row','sat_entry_seq','sat_entry_price','sat_direction','sat_quantity','保険入口根拠'):
                        assert x[name]==y[name],(key,name)
            for first,last in ((0,1),(0,2),(0,3),(1,2),(1,3)):
                for symbol in ('TOPIX','NK225'):
                    for period in ('前16','後14','全30'):
                        keys=[k for k in maps[0] if k[1]==symbol and k[0] in fixed[period]]
                        left=[maps[first][k] for k in keys];right=[maps[last][k] for k in keys]
                        entry_same=0;exit_diff=0.;fee_diff=0.;initial_same=0;initial_diff=0;details=[]
                        for x,y in zip(left,right):
                            if not x['sat_active']:continue
                            entry_same+=1
                            scale=x['sat_direction']*x['sat_quantity']*(1000 if symbol=='TOPIX' else 10)
                            change=scale*(y['sat_exit_price']-x['sat_exit_price']);charge=x['sat_fees']-y['sat_fees']
                            assert abs(change+charge-(y['sat_net']-x['sat_net']))<1e-6
                            exit_diff+=change;fee_diff+=charge
                            same=bool(abs(x['初期停止']['実初期線']-y['初期停止']['実初期線'])<1e-9)
                            if same:
                                initial_same+=1
                                assert x['sat_exit_row']==y['sat_exit_row'] and x['sat_exit_price']==y['sat_exit_price']
                            else:initial_diff+=1
                            details.append(dict(session=x['session'],組=x['campaign'],新規行=x['sat_entry_row'],
                                初期線同値=same,元線=x['初期停止']['実初期線'],新線=y['初期停止']['実初期線'],
                                元損失ATR=x['初期停止']['初期線までの損失ATR'],新損失ATR=y['初期停止']['初期線までの損失ATR'],
                                元収支=x['sat_net'],新収支=y['sat_net'],返済価格差寄与=change,
                                料金差寄与=charge,既通過=x['保険入口根拠']['予約公開時に既通過']))
                        partitions=[]
                        for dimension,selector in (
                            ('初期線同値',lambda x,y:abs(x['初期停止']['実初期線']-y['初期停止']['実初期線'])<1e-9),
                            ('元保険黒字',lambda x,y:x['sat_net']>0),
                            ('元玉黒字',lambda x,y:x['core_net']>0)):
                            for state in (True,False):
                                aa=[];bb=[]
                                for x,y in zip(left,right):
                                    if x['sat_active'] and selector(x,y)==state:aa.append(x);bb.append(y)
                                price_change=sum(x['sat_direction']*x['sat_quantity']*(1000 if symbol=='TOPIX' else 10)*(y['sat_exit_price']-x['sat_exit_price']) for x,y in zip(aa,bb))
                                charges=sum(x['sat_fees']-y['sat_fees'] for x,y in zip(aa,bb))
                                change=sum(y['sat_net']-x['sat_net'] for x,y in zip(aa,bb))
                                assert abs(change-price_change-charges)<1e-6
                                partitions.append(dict(分類=dimension,該当=state,元=prior.summarize(aa),新=prior.summarize(bb),
                                    差額=change,返済値差寄与=price_change,料金差寄与=charges))
                        output.append(dict(model=model,symbol=symbol,period=period,元条件=identifiers[first],新条件=identifiers[last],
                            元=prior.summarize(left),新=prior.summarize(right),差額=sum(y['sat_net']-x['sat_net'] for x,y in zip(left,right)),
                            返済価格差寄与=exit_diff,料金差寄与=fee_diff,新規完全一致件数=entry_same,
                            初期停止線同値件数=initial_same,初期停止線非同値件数=initial_diff,同値又は旧勝敗別=partitions,全対応=details))
    return output


def main():
    """
    機能: 全34結果保存後、入口を変えず停止だけを広げた効果を集計する。
    引数: なし。
    返り値: None。元結果を読み取るだけで売買再生はしない。
    """
    fixed=prior.read(ROUND/'事前固定.json');identifiers=[c['id'] for c in fixed['catalog']]
    expected=[ROUND/m/'results'/(ident+'.json') for m in fixed['models'] for ident in identifiers]
    assert len(expected)==34 and all(p.exists() for p in expected),'全34結果が必要です'
    prepare=module('wave87_structure_input_prepare',ROOT/'work/wave_v85/prepare.py')
    inputs,signals,fingerprints=prepare.load_inputs(True);del signals
    assert fingerprints==fixed['input_SHA256']
    periods=[];causes=[];records=[];comparisons=[];sources={};risk=[]
    for model in fixed['models']:
        groups={}
        for ident in identifiers:
            path=ROUND/model/'results'/(ident+'.json');ledger_path=ROUND/model/'ledgers'/(ident+'.pkl')
            result=prior.read(path);assert prior.sha(ledger_path)==result['ledger_SHA256']
            own=extract(result,pickle.loads(ledger_path.read_bytes()),inputs);groups[ident]=own;records.extend(own)
            sources[str(path.relative_to(ROOT))]=prior.sha(path)
            sources[str(ledger_path.relative_to(ROOT))]=result['ledger_SHA256']
            for symbol in ('TOPIX','NK225'):
                for period in ('前16','後14','全30'):
                    subset=[x for x in own if x['symbol']==symbol and x['session'] in fixed[period]]
                    q=result['periods'][period][symbol]
                    periods.append(dict(model=model,id=ident,symbol=symbol,period=period,**prior.summarize(subset),
                        最大下落=q['max_drawdown'],黒字場=q['positive_sessions'],赤字場=q['negative_sessions'],最大一場除外=q['best_session_removed']))
                    dimensions={'元玉最終収支':lambda x:'元玉黒字' if x['core_net']>0 else ('元玉赤字' if x['core_net']<0 else '元玉ゼロ'),
                        '保険返済理由':lambda x:x.get('sat_reason_name','保険なし'),
                        '入口既通過':lambda x:x.get('保険入口根拠',{}).get('新規注文方式','保険なし'),
                        '元玉方向':lambda x:'買い' if x['core_direction']>0 else '売り',
                        '時間帯':lambda x:'デイ' if x['session'].endswith('_Day') else 'ナイト'}
                    for dimension,select in dimensions.items():
                        bins=defaultdict(list)
                        for x in subset:bins[select(x)].append(x)
                        for label,items in bins.items():causes.append(dict(model=model,id=ident,symbol=symbol,period=period,
                            分類=dimension,区分=label,**prior.summarize(items)))
                    active=[x for x in subset if x['sat_active']]
                    if active:
                        widths=[x['初期停止']['初期線までの損失ATR'] for x in active]
                        distributions={}
                        for name in ('固定ATR','呼値','初期線までの損失幅','初期線までの損失ATR','初期線までの損失呼値数','線で返済できた場合の名目料金込損失'):
                            values=[x['初期停止'][name] for x in active]
                            distributions[name]={label:float(value) for label,value in zip(('最小','百分位25','中央値','百分位75','百分位95','最大'),np.percentile(values,[0,25,50,75,95,100]))}
                        risk.append(dict(model=model,id=ident,symbol=symbol,period=period,件数=len(active),
                            初期損失ATR最小=float(min(widths)),初期損失ATR中央値=float(np.median(widths)),初期損失ATR最大=float(max(widths)),
                            最悪実保険損失=float(max(0.,-min(x['sat_net'] for x in active))),
                            新規当行線破断済み件数=sum(x['初期停止']['新規当行破断済み'] for x in active),分布=distributions))
            print(model,ident,'初期停止と独立保険会計一致',flush=True)
        comparisons.extend(pairs(groups,model,fixed))
    output=dict(定義=dict(主仮説='K_P50_C1_S2',範囲='全34保存結果・既知30場。結果から代表を差し替えない。',
        入口='四入口のS0/S1/S2/S3は全新規行・価格・数量・方向・公開根拠が一致する。',
        効果='差額は独立保険の返済値変化と料金差。元玉は不変。初期停止線までの名目リスクと実損失を区別する。',
        構造='S1/S3初期線同値なら以後の保険返済も一致を要求。過去極値という名称自体を優位の理由にしない。',
        事後='元玉最終黒字赤字・最悪損失・保持期間のMFE/MAEは説明用で、取引へ戻していない。'),
        入力SHA256=fingerprints,資料SHA256=sources,期間成績=periods,分類別=causes,初期リスク=risk,
        停止基準の全対応比較=comparisons,全親組=records)
    target=HERE/'同じ入口の停止価格と返済差の全分解.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('入口完全一致・返済差分解を保存しました',len(records),flush=True)


if __name__=='__main__':main()
