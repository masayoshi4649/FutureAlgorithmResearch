"""元玉不変の全額差分と、双方反対支持の有無による保険入口の差を説明する。"""
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
    機能: 凍結した解析会計又は読取器を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


prior=module('wave87_round7_sat_analysis',ROUND.parent/'round7/analysis/diagnose.py')


def extract(result,ledgers,inputs):
    """
    機能: 独立保険の金額と、実新規前に公開済みだった根拠を結合する。
    引数: result/ledgers/inputs(dict)。
    返り値: list[dict]。根拠の古さは事後説明であり追加の取引条件にしない。
    """
    records=prior.extract(result,ledgers,inputs)
    for record in records:
        if not record['sat_active']:continue
        key=(record['session'],record['symbol']);ledger=ledgers[key];ready=inputs[key]
        proofs=ledger['insurance_events']
        matched=proofs[proofs[:,1]==record['campaign']]
        assert len(matched)==1
        row=matched[0];entry=int(row[0]);permission=int(row[3]);extreme=int(row[5])
        assert entry==record['sat_entry_row'] and permission<entry and extreme<=permission
        item=dict(予約行=int(row[2]),最終許可行=permission,最終許可時刻=prior.stamp(ready['time_s'][permission]),
            順行極値=float(row[4]),極値行=extreme,極値時刻=prior.stamp(ready['time_s'][extreme]),
            予約線=float(row[6]),判断から新規の代理秒差=float(ready['time_s'][entry]-ready['time_s'][permission]),
            公開元={})
        for label,value_col,valid_col,source_col,time_col,release_col,clock_col in (
            ('自己',7,9,11,13,15,17),('相手',8,10,12,14,16,18)):
            value=float(row[value_col]);clock=float(row[clock_col]);source_time=float(row[time_col])
            item['公開元'][label]=dict(支持=value if np.isfinite(value) else None,有効=bool(row[valid_col]),
                終端原本行=int(row[source_col]),公開原本行=int(row[release_col]),
                終端時計=prior.stamp(source_time) if np.isfinite(source_time) else None,
                公開時計=prior.stamp(clock) if np.isfinite(clock) else None,
                判断時点の公開後代理秒数=float(ready['time_s'][permission]-clock) if np.isfinite(clock) else None)
        if result['config']['confirm']:
            assert row[9] and row[10]
            assert -record['core_direction']*row[7]>.05 and -record['core_direction']*row[8]>.05
            assert row[15]<=ready['seq'][permission] and row[18]<ready['time_s'][permission]
        first=record['core_entry_row'];direction=record['core_direction']
        core_orders=ledger['core_ledger']['orders']
        entry_order=core_orders[(core_orders[:,2]==record['campaign'])&(core_orders[:,7]==1)][0]
        item['準備までの順行ATR']=direction*(row[4]-entry_order[5])/record['atr']
        item['新規時の極値からの逆行ATR']=direction*(row[4]-record['sat_entry_price'])/record['atr']
        item['元玉新規行']=first
        reservation=int(row[2]);reservation_price=float(ready['last'][reservation])
        crossed=-direction*(reservation_price-row[6])>=-1e-9
        item['予約時現在値']=reservation_price
        item['予約公開時に既通過']=bool(crossed)
        item['新規注文方式']='既通過のため次観測成行' if crossed else '次観測以降の逆指値'
        item['予約線に対する不利建値差']=record['sat_direction']*(record['sat_entry_price']-row[6])
        item['予約線に対する不利建値金額']=item['予約線に対する不利建値差']*record['sat_quantity']*(1000 if key[1]=='TOPIX' else 10)
        if crossed:assert abs(record['sat_entry_price']-ready['last'][entry])<1e-9
        record['保険入口根拠']=item
    return records


def confirmation_pairs(groups,model,fixed):
    """
    機能: 同じ準備・逆行幅で、双方支持の追加だけが変えた入口を対応させる。
    引数: groups(dict)、model(str)、fixed(dict)。
    返り値: list[dict]。元玉が不変なので全親組を漏らさず比較する。
    """
    results=[]
    for pa in ('00','25','50'):
        for pb in ('25','50'):
            a_id=f'I_P{pa}_R{pb}_C0';b_id=f'I_P{pa}_R{pb}_C1'
            a={(x['session'],x['symbol'],x['campaign']):x for x in groups[a_id]}
            b={(x['session'],x['symbol'],x['campaign']):x for x in groups[b_id]}
            assert a.keys()==b.keys()
            for symbol in ('TOPIX','NK225'):
                for period in ('前16','後14','全30'):
                    bins=defaultdict(list)
                    keys=[k for k in a if k[1]==symbol and k[0] in fixed[period]]
                    for key in keys:
                        x=a[key];y=b[key]
                        assert x['core_net']==y['core_net']
                        if x['sat_active'] and y['sat_active']:
                            assert y['sat_entry_row']>=x['sat_entry_row']
                            label='同じ原本行の入口' if x['sat_entry_row']==y['sat_entry_row'] else '支持確認で遅れた入口'
                        elif x['sat_active']:label='価格だけでは入り支持確認では見送り'
                        elif y['sat_active']:label='支持確認でのみ入った入口'
                        else:label='双方とも保険なし'
                        bins[label].append(key)
                    parts=[]
                    for label,subset in bins.items():
                        left=[a[k] for k in subset];right=[b[k] for k in subset]
                        route=[]
                        for key in subset:
                            x=a[key];y=b[key]
                            if not x['sat_active'] or not y['sat_active']:continue
                            assert x['sat_direction']==y['sat_direction'] and x['sat_quantity']==y['sat_quantity']
                            scale=x['sat_quantity']*(1000 if symbol=='TOPIX' else 10)*x['sat_direction']
                            entry_change=-scale*(y['sat_entry_price']-x['sat_entry_price'])
                            exit_change=scale*(y['sat_exit_price']-x['sat_exit_price'])
                            fee_change=x['sat_fees']-y['sat_fees']
                            assert abs(entry_change+exit_change+fee_change-(y['sat_net']-x['sat_net']))<1e-6
                            route.append(dict(session=key[0],campaign=key[2],建値変化寄与=entry_change,
                                返済値変化寄与=exit_change,料金差寄与=fee_change,
                                価格だけ新規行=x['sat_entry_row'],支持確認新規行=y['sat_entry_row'],
                                価格だけ建値=x['sat_entry_price'],支持確認建値=y['sat_entry_price'],
                                支持確認で既通過=y['保険入口根拠']['予約公開時に既通過']))
                        parts.append(dict(区分=label,親組数=len(subset),価格だけ=prior.summarize(left),
                            双方支持=prior.summarize(right),差額=sum(b[k]['sat_net']-a[k]['sat_net'] for k in subset),
                            両方で保険を建てた組の建値変化寄与=sum(x['建値変化寄与'] for x in route),
                            両方で保険を建てた組の返済値変化寄与=sum(x['返済値変化寄与'] for x in route),
                            両方で保険を建てた組の料金差寄与=sum(x['料金差寄与'] for x in route),対応した建値返済=route))
                    results.append(dict(model=model,symbol=symbol,period=period,価格条件=a_id,支持条件=b_id,
                        価格だけ=prior.summarize([a[k] for k in keys]),双方支持=prior.summarize([b[k] for k in keys]),
                        差額=sum(b[k]['sat_net']-a[k]['sat_net'] for k in keys),内訳=parts))
    return results


def main():
    """
    機能: 全26結果の完了通知後、保存された売買だけを診断する。
    引数: なし。
    返り値: None。再生・条件探索・代表の選び直しは行わない。
    """
    fixed=prior.read(ROUND/'事前固定.json');identifiers=[x['id'] for x in fixed['catalog']]
    expected=[ROUND/model/'results'/(ident+'.json') for model in fixed['models'] for ident in identifiers]
    assert len(expected)==26 and all(path.exists() for path in expected),'全26結果が必要です'
    prepare=module('wave87_round8_analysis_prepare',ROOT/'work/wave_v85/prepare.py')
    inputs,signals,fingerprints=prepare.load_inputs(True);del signals
    assert fingerprints==fixed['input_SHA256']
    periods=[];sessions=[];causes=[];details=[];pairs=[];sources={};worst=[]
    for model in fixed['models']:
        groups={}
        for ident in identifiers:
            path=ROUND/model/'results'/(ident+'.json');ledger_path=ROUND/model/'ledgers'/(ident+'.pkl')
            result=prior.read(path);assert prior.sha(ledger_path)==result['ledger_SHA256']
            records=extract(result,pickle.loads(ledger_path.read_bytes()),inputs)
            groups[ident]=records;details.extend(records)
            sources[str(path.relative_to(ROOT))]=prior.sha(path)
            sources[str(ledger_path.relative_to(ROOT))]=result['ledger_SHA256']
            for symbol in ('TOPIX','NK225'):
                own=[x for x in records if x['symbol']==symbol]
                for period in ('前16','後14','全30'):
                    subset=[x for x in own if x['session'] in fixed[period]]
                    periods.append(dict(model=model,id=ident,symbol=symbol,period=period,**prior.summarize(subset)))
                    partitions={'元玉方向':lambda x:'買い' if x['core_direction']>0 else '売り',
                        '時間帯':lambda x:'デイ' if x['session'].endswith('_Day') else 'ナイト',
                        '追尾始動':lambda x:x['sat_stage'],
                        '保険返済理由':lambda x:x.get('sat_reason_name','保険なし'),
                        '元玉最終収支':lambda x:'元玉黒字' if x['core_net']>0 else ('元玉赤字' if x['core_net']<0 else '元玉ゼロ'),
                        '元玉黒字で保険停止':lambda x:'元玉黒字で保険初期停止' if x['core_net']>0 and x['sat_reason']==81 else 'その他',
                        '入口の既通過':lambda x:x.get('保険入口根拠',{}).get('新規注文方式','保険なし')}
                    for dimension,selector in partitions.items():
                        bins=defaultdict(list)
                        for item in subset:bins[selector(item)].append(item)
                        for label,items in bins.items():causes.append(dict(model=model,id=ident,symbol=symbol,
                            period=period,分類=dimension,区分=label,**prior.summarize(items)))
                own_sessions=[]
                for session in fixed['全30']:
                    row=dict(model=model,id=ident,symbol=symbol,session=session,
                        **prior.summarize([x for x in own if x['session']==session]))
                    sessions.append(row);own_sessions.append(row)
                for row in sorted(own_sessions,key=lambda x:x['追加単独']['収支'])[:3]:
                    worst.append(dict(**row,全親組=[x for x in own if x['session']==row['session']]))
            print(model,ident,'保険の全額差分と公開根拠一致',flush=True)
        pairs.extend(confirmation_pairs(groups,model,fixed))
    output=dict(定義=dict(主仮説='I_P50_R50_C1',範囲='全26結果・既知全30場。再探索なし。',
        会計='元玉は不変。差額は保険単独の料金後収支。救済例と元勝ちの毀損を全件含む。',
        支持='最新公開イベントの過去30秒変化/当時ATR。追加鮮度上限なし。現在直近30秒の支持とは異なる。',
        因果='約定当行の支持変化で既注文を取消していない。記録した最終許可行の根拠は新規行より前。',
        比較='価格だけと双方支持は同じコア親組を全件対応。入口が遅れると保有経路・出口も変わる。',
        時計='原本順とCurrentPriceTime代理時計。通信時計や実際の秒単位同期の保証ではない。',
        事後='MFE/MAE・最悪場・公開後の古さは事後の原因診断だけ。取引条件へ戻さない。'),
        input_SHA256=fingerprints,source_SHA256=sources,期間成績=periods,全セッション=sessions,
        分類別=causes,支持確認の対照=pairs,最悪場=worst,全親組=details)
    target=HERE/'逆行保険の全額差分と支持確認の分解.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('保存完了',len(details),'親組',flush=True)


if __name__=='__main__':main()
