"""保存された全条件を、元玉不変の差額として独立追加だけへ分解する。"""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib
import importlib.util
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROUND=HERE.parent
ROOT=ROUND.parents[2]
JST=timezone(timedelta(hours=9))
REASONS={81:'初期停止',82:'追尾返済',83:'コア終了後の次観測',84:'米国静観',85:'場末'}


def read(path):
    """
    機能: 保存済み日本語JSONを読む。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 証拠ファイルの指紋を計算する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(value):
    """
    機能: 代理価格時計を日本時間で表す。
    引数: value(float)。
    返り値: str。
    """
    return datetime.fromtimestamp(float(value),JST).isoformat()


def account(values):
    """
    機能: 対象単位の利益と損失を相殺前に集計する。
    引数: values(list[float])。
    返り値: dict。ゼロを勝ちへ含めない。
    """
    values=np.asarray(values,float)
    profit=float(values[values>0].sum());loss=float(-values[values<0].sum())
    wins=int((values>0).sum());losses=int((values<0).sum())
    return dict(件数=len(values),利益=profit,損失=loss,収支=float(values.sum()),
        勝ち=wins,負け=losses,ゼロ=int((values==0).sum()),
        金額利益割合=profit/(profit+loss) if profit+loss else None,
        平均利益=profit/wins if wins else None,平均損失=loss/losses if losses else None)


def summarize(records):
    """
    機能: 全親組と、実際に新規した追加だけの会計を並べる。
    引数: records(list[dict])。
    返り値: dict。追加なしを追加勝率の分母へ含めない。
    """
    active=[x for x in records if x['sat_active']]
    return dict(親組数=len(records),元玉=account([x['core_net'] for x in records]),
        合算=account([x['combined_net'] for x in records]),追加単独=account([x['sat_net'] for x in active]),
        追加なし組数=len(records)-len(active),
        追加料金前=sum(x['sat_gross'] for x in records),追加料金=sum(x['sat_fees'] for x in records),
        元勝ちから合算負け=account([x['sat_net'] for x in records if x['core_net']>0 and x['combined_net']<0]),
        元負けから合算勝ち=account([x['sat_net'] for x in records if x['core_net']<0 and x['combined_net']>0]),
        追加料金だけで赤字=account([x['sat_net'] for x in active if x['sat_gross']>=0 and x['sat_net']<0]),
        追加初期停止=account([x['sat_net'] for x in active if x['sat_reason']==81]),
        コア終了後まで保有=account([x['sat_net'] for x in active if x['sat_exit_row']>x['core_exit_row']]))


def extract(result,ledgers,inputs):
    """
    機能: 保存台帳を親組へ対応させ、追加単独会計と公開線の時系列を復元する。
    引数: result/ledgers/inputs(dict)。
    返り値: list[dict]。実行条件は一切変更しない。
    """
    output=[]
    config=result['config']
    for key,ledger in sorted(ledgers.items()):
        ready=inputs[key];value=1000. if key[1]=='TOPIX' else 10.;fee=41.8 if key[1]=='TOPIX' else 11.
        core=ledger['core_ledger'];events=ledger['satellite_events']
        core_net=defaultdict(float);total_net=defaultdict(float)
        for trade in core['net_trades']:core_net[int(trade['組'])]+=trade['収支']
        for trade in ledger['net_trades']:total_net[int(trade['組'])]+=trade['収支']
        sat_orders=ledger['satellite_orders'];sat_trades=ledger['satellite_trades']
        local=[]
        for cycle in core['cycles']:
            cid=int(cycle[0]);first=int(cycle[1]);last=int(cycle[2]);direction=int(cycle[8]);atr=float(cycle[5])
            oo=sat_orders[sat_orders[:,2]==cid];tt=sat_trades[sat_trades[:,0]==cid]
            gross=float(tt[:,10].sum()*value);fees=float(np.floor(oo[:,4]*fee+1e-8).sum());net=gross-fees
            assert abs(core_net[cid]+net-total_net[cid])<1e-7
            item=dict(model=result['model'],id=config['id'],session=key[0],symbol=key[1],campaign=cid,
                core_entry_row=first,core_entry_seq=int(ready['seq'][first]),core_entry_jst=stamp(ready['time_s'][first]),
                core_exit_row=last,core_exit_jst=stamp(ready['time_s'][last]),core_direction=direction,
                core_net=float(core_net[cid]),core_final_reason=int(cycle[9]),combined_net=float(total_net[cid]),
                atr=atr,sat_active=bool(len(tt)),sat_gross=gross,sat_fees=fees,sat_net=net,
                sat_direction=direction*config['relation'],sat_reason=None,sat_entry_row=None,sat_exit_row=None,
                sat_stage='追加なし',sat_mfe_atr=None,sat_mae_atr=None)
            if len(tt):
                assert len(tt)==1 and len(oo)==2 and sum(oo[:,7])==1
                t=tt[0];entry=int(t[6]);exit=int(t[7]);sd=int(t[2]);qty=int(t[3]);price=float(t[4]);close=float(t[5])
                ee=events[events[:,1]==cid]
                start=ee[(ee[:,2]==2)&(ee[:,0]==entry)]
                assert len(start)==1
                trail=ee[(ee[:,2]==3)&(ee[:,9]==82)&(ee[:,0]<exit)]
                status='追尾始動後' if len(trail) else '追尾始動前'
                path=ready['last'][entry:exit+1];valid=np.isfinite(path)&(path>0)
                progress=sd*(path[valid]-price)/atr
                order_entry=oo[oo[:,7]==1][0];order_exit=oo[oo[:,7]==0][0]
                assert int(order_entry[1])<entry and int(order_exit[1])<exit
                core_oo=core['orders'][(core['orders'][:,2]==cid)&(core['orders'][:,0]<=entry)]
                held_after=int(sum(o[4] if o[7] else -o[4] for o in core_oo))
                core_slice=core['orders'][(core['orders'][:,2]==cid)&(core['orders'][:,0]>=entry)&(core['orders'][:,0]<exit)]
                after_held=int(start[0,7]);opposite_net=False
                for o in core_slice:
                    after_held+=int(o[4]) if o[7] else -int(o[4])
                    if config['relation']<0 and qty>after_held:opposite_net=True
                if config['relation']<0 and qty>int(start[0,7]):opposite_net=True
                native_line=None
                if int(t[9]) in (81,82):
                    sources=ee[(ee[:,2]==3)&(ee[:,0]==order_exit[1])]
                    assert len(sources)==1
                    line=float(sources[0,6])
                    native_line=dict(公開行=int(order_exit[1]),公開時刻=stamp(ready['time_s'][int(order_exit[1])]),
                        線=line,約定値=close,線からの不利価格差=sd*(line-close),
                        料金前悪化額=sd*(line-close)*qty*value)
                item.update(sat_direction=sd,sat_quantity=qty,sat_entry_row=entry,sat_entry_seq=int(ready['seq'][entry]),
                    sat_entry_jst=stamp(ready['time_s'][entry]),sat_exit_row=exit,sat_exit_jst=stamp(ready['time_s'][exit]),
                    sat_entry_price=price,sat_exit_price=close,sat_reason=int(t[9]),sat_reason_name=REASONS[int(t[9])],
                    sat_stage=status,sat_mfe_atr=float(progress.max(initial=0)),sat_mae_atr=float(-progress.min(initial=0)),
                    core_qty_before_sat_entry=int(start[0,7]),core_qty_after_sat_entry_row=held_after,
                    opened_on_core_final_row=entry==last,opposite_net_during_holding=opposite_net,
                    post_core_exit_rows=max(0,exit-last),
                    post_core_exit_proxy_seconds=max(0.,float(ready['time_s'][exit]-ready['time_s'][last])),
                    native_line=native_line)
            local.append(item)
        row=next(r for r in result['rows'] if (r['session'],r['symbol'])==key)
        for field,column in [('combined_net','net'),('core_net','core_net'),('sat_gross','satellite_gross'),('sat_fees','satellite_fees'),('sat_net','satellite_net')]:
            assert abs(sum(x[field] for x in local)-row[column])<1e-6,(key,field)
        output.extend(local)
    return output


def compare_directions(groups,model,symbol,fixed):
    """
    機能: 同じ開始線で同方向又は反対方向に建てた固定対照を対応させる。
    引数: groups(dict)、model/symbol(str)、fixed(dict)。
    返り値: list[dict]。出口を再生した保存結果で比較し、損益の符号だけを反転しない。
    """
    out=[]
    for suffix in ('05_S25','05_S50','10_S25','10_S50','10_W'):
        forward=[x for x in groups['C_F'+suffix] if x['symbol']==symbol]
        reverse=[x for x in groups['C_H'+suffix] if x['symbol']==symbol]
        a={(x['session'],x['core_entry_seq'],x['core_direction']):x for x in forward}
        b={(x['session'],x['core_entry_seq'],x['core_direction']):x for x in reverse}
        assert a.keys()==b.keys()
        assert all(a[k]['sat_entry_row']==b[k]['sat_entry_row'] for k in a)
        for period in ('前16','後14','全30'):
            keys=[k for k in a if k[0] in fixed[period]]
            out.append(dict(model=model,symbol=symbol,条件=suffix,period=period,
                同方向=summarize([a[k] for k in keys]),反対方向=summarize([b[k] for k in keys]),
                反対から同方向を引いた収支=sum(b[k]['sat_net']-a[k]['sat_net'] for k in keys),
                同じ開始の追加入口一致=True))
    return out


def main():
    """
    機能: 親から全結果完了通知を受けた後、全二十二保存結果だけを解析する。
    引数: なし。
    返り値: None。売買再生を呼び出さず、分析フォルダへ証拠を保存する。
    """
    fixed=read(ROUND/'事前固定.json');identifiers=[c['id'] for c in fixed['catalog']]
    expected=[ROUND/model/'results'/(ident+'.json') for model in fixed['models'] for ident in identifiers]
    assert all(path.exists() for path in expected),'全22保存結果が必要です'
    spec=importlib.util.spec_from_file_location('wave87_sat_analysis_prepare',ROOT/'work/wave_v85/prepare.py')
    prepare=importlib.util.module_from_spec(spec);sys.modules[spec.name]=prepare;spec.loader.exec_module(prepare)
    inputs,signals,fingerprints=prepare.load_inputs(verify=True);del signals
    assert fingerprints==fixed['input_SHA256']
    periods=[];sessions=[];details=[];causes=[];worst=[];direction_comparison=[];sources={}
    for model in fixed['models']:
        groups={}
        for ident in identifiers:
            path=ROUND/model/'results'/(ident+'.json');ledger_path=ROUND/model/'ledgers'/(ident+'.pkl')
            result=read(path);assert sha(ledger_path)==result['ledger_SHA256']
            records=extract(result,pickle.loads(ledger_path.read_bytes()),inputs)
            groups[ident]=records;details.extend(records)
            sources[str(path.relative_to(ROOT))]=sha(path);sources[str(ledger_path.relative_to(ROOT))]=result['ledger_SHA256']
            for symbol in ('TOPIX','NK225'):
                own=[x for x in records if x['symbol']==symbol]
                for period in ('前16','後14','全30'):
                    subset=[x for x in own if x['session'] in fixed[period]]
                    periods.append(dict(model=model,id=ident,symbol=symbol,period=period,**summarize(subset)))
                    partitions={
                        'コア方向':lambda x:'買い' if x['core_direction']>0 else '売り',
                        '追加方向':lambda x:'追加なし' if not x['sat_active'] else ('買い' if x['sat_direction']>0 else '売り'),
                        '時間帯':lambda x:'デイ' if x['session'].endswith('_Day') else 'ナイト',
                        '追尾始動':lambda x:x['sat_stage'],
                        '追加返済理由':lambda x:x.get('sat_reason_name','追加なし'),
                        '元玉最終理由':lambda x:str(x['core_final_reason'])}
                    for dimension,selector in partitions.items():
                        bins=defaultdict(list)
                        for item in subset:bins[selector(item)].append(item)
                        for label,items in bins.items():causes.append(dict(model=model,id=ident,symbol=symbol,
                            period=period,分類=dimension,区分=label,**summarize(items)))
                own_sessions=[]
                for session in fixed['全30']:
                    items=[x for x in own if x['session']==session]
                    record=dict(model=model,id=ident,symbol=symbol,session=session,**summarize(items))
                    sessions.append(record);own_sessions.append(record)
                for metric,label in [('合算','合算収支下位'),('追加単独','追加差額下位')]:
                    for row in sorted(own_sessions,key=lambda x:x[metric]['収支'])[:3]:
                        own_trades=[x for x in own if x['session']==row['session']]
                        worst.append(dict(分類=label,**row,全親組=own_trades))
            print(model,ident,'追加単独会計と全親組差分一致',flush=True)
        for symbol in ('TOPIX','NK225'):direction_comparison.extend(compare_directions(groups,model,symbol,fixed))
    theory=ROUND.parent/'theory/独立追加と保険カバーの既検証差と理論反証.json'
    output=dict(定義=dict(
        主仮説='C_F10_S25。元GUは全条件で不変。合算差額は独立追加の料金後収支に完全一致する。',
        範囲='全22保存結果・全30既知場。新規条件やパラメータ探索、追加の売買再生は行わない。',
        会計='追加は1親組1回、部分返済なし。追加の無取引を勝ちへ含めず、全親組の合算成績も同時に示す。',
        原因区分='始動前後は追加トレールの始動を意味する。元玉初期停止の終わり方は別の元玉最終理由で分類する。',
        救済='元の赤字を黒字へ変えた例だけで評価しない。元の黒字を赤字へ変えた例と全親組を集計する。',
        理論='同方向追加は順行継続、反対追加は順行後の戻りを取る仮説。単純な損益反転ではなく、それぞれの独立出口を再生した保存結果。',
        時計='原本保存順とCurrentPriceTime代理時計。コア終了からの秒差を通信遅延そのものとは呼ばない。',
        事後='保有期間のMFE/MAEと最悪場は損失原因説明のみ。未来値を取引や選定へ使わない。'),
        input_SHA256=fingerprints,source_SHA256=sources,既往理論=dict(path=str(theory),SHA256=sha(theory)),
        期間成績=periods,全セッション=sessions,分類別=causes,方向比較=direction_comparison,
        最悪場=worst,全親組=details)
    target=HERE/'独立追加の全会計と原因分解.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('解析保存',target,'親組',len(details),flush=True)


if __name__=='__main__':main()
