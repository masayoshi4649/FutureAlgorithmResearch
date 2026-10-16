"""保存会計を独立再集計し、抽出台帳の現金・気配・予約・固定価格を検算する。"""

from collections import defaultdict
from datetime import date, timedelta, datetime
from decimal import Decimal, ROUND_FLOOR
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import statistics
import sys
import traceback
from zoneinfo import ZoneInfo

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/range_price'
COUNT=defaultdict(int)
ADDITIVE=('profit','loss','net','gross','fees','campaigns','winning_campaigns','losing_campaigns',
    'flat_campaigns','winning_lots','losing_lots','flat_lots','lots')
TARGET='R_ONLY_ER40_M1_LIMIT'


def read_json(path: Path) -> dict:
    """
    機能: 保存済み小会計を読み、書換えを行わない。
    引数: path(Path)はJSON正本。
    返り値: dictは解析した小会計。
    """
    return json.loads(path.read_text(encoding='utf8'))


def sha(path: Path) -> str:
    """
    機能: source又は保存入力の指紋を求める。
    引数: path(Path)は読取専用ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(value: bool, label: str) -> None:
    """
    機能: 条件を独立に検査して件数を残す。
    引数: value(bool)、label(str)は判定と検査名。
    返り値: None。不一致を成功扱いせず例外へ保存する。
    """
    assert value,label
    COUNT[label]+=1


def equal(actual: object, expected: object, label: str) -> None:
    """
    機能: 整数件数・手数料は厳密、経済金額は微小残差だけ許容して比較する。
    引数: actual/expected(object)、label(str)は数値又はNone。
    返り値: None。金額許容1e-7円、比率許容1e-10。
    """
    if expected is None:
        check(actual is None,label)
    elif isinstance(expected,(int,np.integer)) or label.endswith('/fees'):
        check(actual==expected,label)
    else:
        tolerance=1e-10 if any(k in label for k in ('share','average','payoff','rate')) else 1e-7
        check(abs(float(actual)-float(expected))<=tolerance,label)


def totals(rows: list[dict], cohort: bool=False) -> dict:
    """
    機能: 保存親の相殺前利益損失を独立に足し、割合と平均を再算定する。
    引数: rows(list[dict])、cohort(bool)は建玉群の件数名切替。
    返り値: dictは加算値とn/Nから再計算した指標。
    """
    fields=[key.replace('campaigns','cohorts') if cohort else key for key in ADDITIVE]
    result={key:sum(row[key] for row in rows) for key in fields}
    suffix='cohorts' if cohort else 'campaigns';nw=result['winning_'+suffix];nl=result['losing_'+suffix]
    p,l=result['profit'],result['loss']
    result.update(profit_share=p/(p+l) if p+l else None,average_win=p/nw if nw else None,
        average_loss=l/nl if nl else None,payoff=(p/nw)/(l/nl) if nw and nl else None)
    return result


def compare_totals(actual: dict, expected: dict, label: str) -> None:
    """
    機能: 独立合計と正本の数値を各項目で照合する。
    引数: actual/expected(dict)、label(str)は対象範囲。
    返り値: Noneは検査件数のみ更新する。
    """
    for key,value in expected.items():equal(actual[key],value,label+'/'+key)


def row_check(row: dict, qty: int) -> None:
    """
    機能: 全1584商品場行の金額・枚数・無活動・源と方向相殺を検査する。
    引数: row(dict)、qty(int)は掲載会計と固定初回枚数。
    返り値: None。無取引を黒字や予測成功へ含めない。
    """
    label='全行'
    equal(row['net'],row['profit']-row['loss'],label+'/GLnet')
    equal(row['net'],row['gross']-row['fees'],label+'/grossnet')
    equal(row['campaigns'],row['winning_campaigns']+row['losing_campaigns']+row['flat_campaigns'],label+'/counts')
    for kind in ('winning','losing','flat'):equal(row[kind+'_lots'],row[kind+'_campaigns']*qty,label+'/枚数')
    equal(row['lots'],row['campaigns']*qty,label+'/全枚数')
    equal(row['order_count'],2*row['campaigns'],label+'/注文数')
    equal(row['entry_order_count'],row['campaigns'],label+'/新規数');equal(row['adding_order_count'],0,label+'/増玉なし')
    compare_totals(row,totals([row]),label+'/割合再計算')
    compare_totals(row['cohorts'],{k.replace('campaigns','cohorts'):v for k,v in totals([row]).items()},label+'/親玉一致')
    for grouping in ('sources','directions'):
        children=list(row[grouping].values());compare_totals(row,totals(children),label+'/'+grouping)
    if row['campaigns']==0:
        check(row['net']==row['profit']==row['loss']==row['fees']==0 and row['profit_share'] is None,label+'/非活動は成功なし')
    check(row['maximums']['held_long']<=qty and row['maximums']['held_short']<=qty,label+'/実量上限')


def summary_check(rows: list[dict], summary: dict, sessions: list[str]) -> dict:
    """
    機能: 商品別合計・日週・期間最大下落と頑健性を独立に再計算する。
    引数: rows(list[dict])、summary(dict)、sessions(list[str])は時系列正本。
    返り値: dictは全33中央値、活動分母、前後半、大勝ち3場除外、方向別値。
    """
    check([r['session'] for r in rows]==sessions,'全33順序')
    result=totals(rows);compare_totals(summary,result,'集計')
    compare_totals(summary['cohorts'],totals([r['cohorts'] for r in rows],True),'集計玉')
    for grouping in ('sources','directions','cohort_directions'):
        for name in summary[grouping]:
            compare_totals(summary[grouping][name],totals([r[grouping][name] for r in rows],grouping=='cohort_directions'),'集計/'+grouping)
    for field in ('order_count','entry_order_count','adding_order_count'):equal(summary[field],sum(r[field] for r in rows),'集計/'+field)
    active=[r for r in rows if r['campaigns']];positive=[r for r in rows if r['net']>1e-5];negative=[r for r in rows if r['net']< -1e-5]
    for field,value in dict(positive_sessions=len(positive),losing_sessions=len(negative),no_trade_sessions=33-len(active),
        active_sessions=len(active),session_count=33,worst_session=min(r['net'] for r in rows),
        all_sessions_profitable=len(positive)==33,positive_session_rate=len(positive)/len(active) if active else None).items():
        equal(summary[field],value,'集計/'+field)
    cumulative=peak=drawdown=0.
    for r in rows:
        drawdown=max(drawdown,r['equity_drawdown'],peak-cumulative-r['equity_trough'])
        peak=max(peak,cumulative+r['equity_peak']);cumulative+=r['net']
    equal(summary['equity_drawdown'],drawdown,'集計/全期間下落')
    grouped={kind:defaultdict(list) for kind in ('days','weeks')}
    for row in rows:
        d=date.fromisoformat(row['session'][:10]);grouped['days'][str(d)].append(row)
        grouped['weeks'][str(d-timedelta(days=d.weekday()))].append(row)
    for kind,groups in grouped.items():
        check(set(summary[kind])==set(groups),'集計/'+kind+'目録')
        for name,children in groups.items():
            compare_totals(summary[kind][name],totals(children),'集計/'+kind)
            compare_totals(summary[kind][name]['cohorts'],totals([r['cohorts'] for r in children],True),'集計/'+kind+'/玉')
    best=max(grouped['days'],key=lambda name:sum(r['net'] for r in grouped['days'][name]))
    check(summary['best_day']==best,'集計/最大日')
    compare_totals(summary['without_best_day'],totals([r for r in rows if r['session'][:10]!=best]),'集計/最大日除外')
    check(summary['maximums']=={name:max(r['maximums'][name] for r in rows) for name in summary['maximums']},'集計/上限')
    winners=sorted(positive,key=lambda r:(-r['net'],r['session']))[:3]
    excluded={r['session'] for r in winners};without=[r for r in rows if r['session'] not in excluded]
    front,back=totals(rows[:16]),totals(rows[16:])
    return dict(利益=result['profit'],損失=result['loss'],収支=result['net'],手数料=result['fees'],
        PF=result['profit']/result['loss'] if result['loss'] else None,利益割合=result['profit_share'],
        親数=result['campaigns'],勝親=result['winning_campaigns'],負親=result['losing_campaigns'],
        黒字場=len(positive),赤字場=len(negative),無取引場=33-len(active),活動場=len(active),全場数=33,
        全33中央値=statistics.median(r['net'] for r in rows),活動場中央値=statistics.median(r['net'] for r in active) if active else None,
        最悪場=min(rows,key=lambda r:r['net'])['session'],最悪場収支=min(r['net'] for r in rows),
        前16収支=front['net'],後17収支=back['net'],後17赤字=sum(r['net']< -1e-5 for r in rows[16:]),
        最大利益3場除外収支=totals(without)['net'],除外した黒字場=[dict(session=r['session'],net=r['net']) for r in winners],
        買売={name:dict(親数=summary['directions'][name]['campaigns'],勝=summary['directions'][name]['winning_campaigns'],
            負=summary['directions'][name]['losing_campaigns'],収支=summary['directions'][name]['net']) for name in ('買い','売り')})


def unpack(item: dict, reads: dict) -> dict:
    """
    機能: 保存台帳を一回読み、指紋を検査して解凍する。
    引数: item(dict)はpath/SHA256、reads(dict)は読取範囲。
    返り値: dictは保存値。正式金融を再生しない。
    """
    path=ROOT/item['path'];content=path.read_bytes();actual=hashlib.sha256(content).hexdigest()
    check(actual==item['SHA256'],'入力SHA');check(item['path'] not in reads,'一ファイル一読取')
    reads[item['path']]=actual
    return pickle.loads(gzip.decompress(content))


def expand(item: dict, n: int) -> np.ndarray:
    """
    機能: 圧縮保存された正常行曲線を前行保持で復元する。
    引数: item(dict)はrows/values、n(int)は元行数。
    返り値: ndarrayは全行。未来補間を使用しない。
    """
    rows=item['rows'];values=item['values'];check(rows[0]==0 and np.all(np.diff(rows)>0),'曲線圧縮順序')
    return np.repeat(values,np.diff(np.r_[rows,n]),axis=0)


def physical(record: dict, output: dict, row: dict) -> None:
    """
    機能: 注文cashとDecimal料金から親・玉・源・全行清算を独立再構成する。
    引数: record/output/row(dict)は気配・保存台帳・掲載会計。
    返り値: None。実約定だけを保有へ数え、残返済料金を源別に控除する。
    """
    symbol=record['symbol'];mult=1000 if symbol=='TOPIX' else 10;feeunit=Decimal('41.8') if symbol=='TOPIX' else Decimal('11')
    n=len(record['seq']);qty=5 if symbol=='TOPIX' else 10;cap=2*qty
    qok=record['quote_valid']&np.isfinite(record['time_s'])&np.isfinite(record['bid'])&np.isfinite(record['ask'])&(record['bid']>0)&(record['ask']>record['bid'])
    orders=output['orders'];trades=output['trades'];cash=np.zeros((n,2));holds=np.zeros((n,2));source_trades=[[],[]]
    check(output['quantity']==qty,'固定枚数');check(len(orders)==2*len(trades),'単一親全量返済')
    check(len(set(trades[:,0]))==len(trades),'親id一意')
    for order in orders:
        fill,decision,source,action,q=int(order[0]),int(order[1]),int(order[3]),int(order[4]),int(order[5])
        fee=int((feeunit*Decimal(q)).to_integral_value(rounding=ROUND_FLOOR))
        check(q==qty and fill>decision and qok[fill],'物理新旧注文')
        check(order[6]==record['ask' if action==1 else 'bid'][fill] and order[9]==fee,'Decimal料金と当時BBO')
        check(order[6]/record['tick']==round(order[6]/record['tick']),'実呼値')
        cash[fill,source]-=action*q*order[6]*mult+fee;holds[fill,source]+=action*q
    cash=np.cumsum(cash,axis=0);holds=np.cumsum(holds,axis=0)
    check(np.max(np.abs(holds),initial=0)<=qty and np.all(np.sum(np.abs(holds),axis=1)<=qty),'単一共有位置上限')
    last=np.maximum.accumulate(np.where(qok,np.arange(n),-1));held=holds!=0;indices=np.maximum(last,0)
    expected=cash+np.where(holds>0,holds*record['bid'][indices,None],holds*record['ask'][indices,None])*mult
    fee=int((feeunit*Decimal(qty)).to_integral_value(rounding=ROUND_FLOOR));expected-=held*fee
    np.testing.assert_allclose(output['source_curve'],expected,rtol=0,atol=1e-7);COUNT['独立全行源曲線']+=2*n
    np.testing.assert_allclose(output['curve'],expected.sum(axis=1),rtol=0,atol=1e-7);COUNT['独立全行合算曲線']+=n
    np.testing.assert_array_equal(output['target_trace'][:,0],np.maximum(holds,0).sum(axis=1))
    np.testing.assert_array_equal(output['target_trace'][:,1],np.maximum(-holds,0).sum(axis=1));COUNT['独立全行保有数量']+=2*n
    check(np.max(output['target_trace'][:,:4],initial=0)<=cap,'予約含む枚数上限');check(not np.any(output['target_trace'][-1]),'場内返済予約なし')
    totals_actual=[]
    for trade in trades:
        parent=int(trade[0]);o=orders[orders[:,2]==parent];entry=o[o[:,7]==1];exits=o[o[:,7]==0]
        check(len(entry)==len(exits)==1,'親実入出一対');a,b=entry[0],exits[0]
        gross=-float(np.sum(o[:,4]*o[:,5]*o[:,6]))*mult;net=gross-float(o[:,9].sum())
        equal(trade[10],gross,'親/gross');equal(trade[11],net,'親/net');equal(trade[8]+trade[9],float(o[:,9].sum()),'親/fees')
        check(trade[2]==a[0] and trade[3]==b[0] and trade[4]==a[4] and a[4]==-b[4],'親原行価格方向')
        cohort=output['growth_cohorts'][output['growth_cohorts'][:,0]==parent]
        check(len(cohort)==1,'玉対応一対');equal(cohort[0,20],net,'玉/net');equal(cohort[0,19],gross,'玉/gross')
        source_trades[int(trade[1])].append(net);totals_actual.append(net)
    p=sum(max(x,0) for x in totals_actual);l=-sum(min(x,0) for x in totals_actual)
    equal(row['profit'],p,'実台帳/profit');equal(row['loss'],l,'実台帳/loss');equal(row['net'],p-l,'実台帳/net')
    for source,name in enumerate(('J2','O06')):
        equal(row['sources'][name]['profit'],sum(max(x,0) for x in source_trades[source]),'源/profit')
        equal(row['sources'][name]['loss'],-sum(min(x,0) for x in source_trades[source]),'源/loss')
    path=np.r_[0.,expected.sum(axis=1)];equal(row['equity_peak'],float(path.max()),'曲線/頂点');equal(row['equity_trough'],float(path.min()),'曲線/底点')
    equal(row['equity_drawdown'],float((np.maximum.accumulate(path)-path).max()),'曲線/下落')


def causality(record: dict, output: dict, normal: dict, config: dict) -> None:
    """
    機能: 実入口の純価格RR・過去六点・固定支持/退出源を自前算式で確認する。
    引数: record/output/normal/config(dict)は当時素材と保存注文。
    返り値: None。実fill悪化を過去へ戻して取消しない。
    """
    byparent={d['parent_id']:d for d in output['raw_entry_diagnostics']};tick=record['tick'];q=output['quantity'];m=1000 if record['symbol']=='TOPIX' else 10
    fees=2*(209 if record['symbol']=='TOPIX' else 110)
    for trade in output['trades']:
        parent=int(trade[0]);d=byparent[parent];decision=int(d['decision_row']);side=int(trade[4]);episode=d['episode']
        check(normal['event'][decision]==side and d['decision_raw_seq']==int(record['seq'][decision]),'当時原行候補対応')
        check(d['decision_raw_row']==normal['execution_to_raw_index'][decision] and d['fill_raw_row']==normal['execution_to_raw_index'][int(trade[2])],'原seq正常map')
        judgments=output['judgments'][output['judgments'][:,3]==parent]
        if d['family']=='R_PRICE':
            own,peer=episode['own_six'],episode['peer_six'];stamp=record['time_s'][decision]
            for sample,label in ((own,'自己'),(peer,'相手')):
                v=np.array(sample['midpoint']);tv=float(np.abs(np.diff(v)).sum());er=abs(float(v[-1]-v[0]))/tv if tv else 0.
                equal(sample['ER'],er,'六点ER');check(sample['known'] and sample['ER']<=config['range_er']+1e-10 and sample['span_ticks']>=4.-1e-10,'両市場RANGE')
                check(len(sample['times'])==6 and all(a>=0 and a<=15. for a in sample['ages']),'六点asof')
                check(max(sample['times'])<stamp if label=='相手' else max(sample['times'])<=stamp,'strict過去相手時計')
            check(max(own['rows'])<=d['decision_raw_row'],'自己未来行なし')
            low,high,centre=episode['fixed_low'],episode['fixed_high'],episode['fixed_centre'];mid=(record['bid'][decision]+record['ask'][decision])/2
            check(low<=mid<=high,'範囲外反発なし');check(mid<=low+.25*(high-low)+1e-8 if side>0 else mid>=high-.25*(high-low)-1e-8,'範囲内端quarter')
            target=np.floor(centre/tick+1e-10)*tick if side>0 else np.ceil(centre/tick-1e-10)*tick
            stop=np.floor((low-config['margin_ticks']*tick)/tick+1e-10)*tick if side>0 else np.ceil((high+config['margin_ticks']*tick)/tick-1e-10)*tick
            planned=record['ask' if side>0 else 'bid'][decision] if config['range_entry']=='MARKET' else record['bid' if side>0 else 'ask'][decision]
            profit=side*(target-planned)*q*m-fees;loss=side*(planned-stop)*q*m+fees
            equal(episode['target_price'],target,'固定/target');equal(episode['stop_price'],stop,'固定/stop');equal(episode['planned_entry'],planned,'予定/entry')
            equal(episode['planned_net_profit'],profit,'予定/profit');equal(episode['planned_net_loss'],loss,'予定/loss')
            check(profit>=1.25*loss and side*(planned-stop)>=2*tick-1e-8,'丸め後料金RR')
            check(np.all(judgments[:,28]==2) and np.all(judgments[:,17]==stop) and np.all(judgments[:,29]==target),'R停止固定でC保険不混入')
            clearing=record['bid' if side>0 else 'ask'][int(trade[2])];risk=side*(trade[6]-stop)*q*m+fees
            check(np.all(np.abs(judgments[:,27]-risk)<=1e-7),'実fillリスク')
            exits=output['orders'][(output['orders'][:,2]==parent)&(output['orders'][:,7]==0)]
            exitorder=exits[0];reason=int(exitorder[8]);row=int(exitorder[1]);quote=record['bid' if side>0 else 'ask'][row]
            if reason==11:check(side*(quote-stop)<=tick*1e-8,'Rstop当時判断')
            if reason==10:check(side*(quote-target)>=-tick*1e-8,'Rtarget当時判断')
        else:
            check(d['family']=='C' or int(d['source'])==0,'C源区別');check(normal['entry_quality'][decision] and not normal['entry_reset'][decision],'旧C量根拠保持')
            check(np.all(judgments[:,28]==1),'C出口保持')


def load_module(name: str, path: Path) -> object:
    """
    機能: 監査専用名前でsourceを接続する。
    引数: name(str)、path(Path)は純検査関数のsource。
    返り値: objectはmodule。金融execute/playは呼ばない。
    """
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value);return value


def iso(stamp: float) -> str:
    """
    機能: 価格clockを日本時刻へ表示する。
    引数: stamp(float)は保存CurrentPriceTime秒。
    返り値: strは受信時計ではない日本時刻。
    """
    return datetime.fromtimestamp(float(stamp),ZoneInfo('Asia/Tokyo')).isoformat()


def cost_trades(record: dict, output: dict) -> list[dict]:
    """
    機能: 実入口出口のmid変化・往復spread・費用と反転だけの数学値を分ける。
    引数: record/output(dict)は保存価格と実完結親。
    返り値: list[dict]は実行可能性を主張しない固定rowの事後診断。
    """
    m=1000 if record['symbol']=='TOPIX' else 10;answer=[]
    diagnostics={d['parent_id']:d for d in output['raw_entry_diagnostics']}
    for t in output['trades']:
        entry,exitrow=int(t[2]),int(t[3]);q,side=t[5],t[4]
        es=record['ask'][entry]-record['bid'][entry];xs=record['ask'][exitrow]-record['bid'][exitrow]
        em=(record['bid'][entry]+record['ask'][entry])/2;xm=(record['bid'][exitrow]+record['ask'][exitrow])/2
        midgross=side*q*m*(xm-em);spread=(es+xs)*q*m/2;fees=t[8]+t[9]
        equal(t[10],midgross-spread,'spread分解/gross');equal(t[11],midgross-spread-fees,'spread分解/net')
        reverse=-t[10]-2*spread-fees
        action=-side;re=q*m*action*((record['bid'][exitrow] if action>0 else record['ask'][exitrow])-(record['ask'][entry] if action>0 else record['bid'][entry]))-fees
        equal(reverse,re,'同row反転数学')
        d=diagnostics[int(t[0])];exitorder=output['orders'][(output['orders'][:,2]==t[0])&(output['orders'][:,7]==0)][0];decision=int(exitorder[1])
        qdecision=record['bid' if side>0 else 'ask'][decision];dprice=(qdecision-t[7])*side*q*m
        answer.append(dict(parent=int(t[0]),side='買い' if side>0 else '売り',quantity=int(q),
            公開価格時刻=iso(record['time_s'][int(t[15])]),入口価格時刻=iso(record['time_s'][entry]),判断価格時刻=iso(exitorder[10]),返済価格時刻=iso(record['time_s'][exitrow]),
            公開原seq=int(record['seq'][int(t[15])]),入口原seq=int(record['seq'][entry]),返済原seq=int(record['seq'][exitrow]),
            entry=float(t[6]),exit=float(t[7]),stop=d.get('fixed_price_stop'),target=d['episode'].get('target_price'),
            原価格粗損益=float(t[10]),手数料=float(fees),収支=float(t[11]),mid変動粗損益=float(midgross),往復気配差負担=float(spread),
            同row反転数学収支=float(reverse),返済判断後悪化額=float(dprice),exit_reason=int(t[13]),
            実fill逆行余地ticks=float(side*(t[6]-d.get('fixed_price_stop',t[6]))/record['tick']) if d['family']=='R_PRICE' else None,
            固定stopはfill時既破れ=bool(d.get('fill_fixed_stop_broken',False)),mode='LIMIT' if output['orders'][output['orders'][:,2]==t[0]][0,14]==12 else 'MARKET'))
    return answer


def main() -> None:
    """
    機能: 全小会計と機械選定した実台帳を一度読取り、独立監査証跡を保存する。
    引数: なし。根の正式金融完了通知後にだけ実行する。
    返り値: None。source不変更、金融再生0、元板/NPZ/API0。
    """
    target=HERE/'range_保存全33損益と抽出台帳の独立監査.json';check(not target.exists(),'同監査再実行なし')
    fixed=read_json(SOURCE/'事前固定.json');results=read_json(SOURCE/'finance/results.json');manifest=read_json(SOURCE/'全33場の価格境界反発準備.json')
    before={name:sha(ROOT/name) for name in fixed['source_SHA256']}
    check(before==fixed['source_SHA256'],'事前固定源一致');check(results['configs']==fixed['configs'] and results['sessions']==fixed['sessions'],'全条件不変')
    check(results['全合格'] and results['account_count']==1584 and results['baseline_replays']==results['original_book_reads']==results['current_API_reads']==0,'根実行範囲')
    sessions=results['sessions'];stability={};samples=set();rowindex={}
    for config in results['configs']:
        ident=config['id'];case=results['cases'][ident];check(len(case['rows'])==66,'全66商品場')
        check(len({(r['session'],r['symbol']) for r in case['rows']})==66,'掲載口座一意')
        stability[ident]={}
        for symbol in ('TOPIX','NK225'):
            rows=[r for r in case['rows'] if r['symbol']==symbol]
            for row in rows:row_check(row,config['quantity'][symbol]);rowindex[(ident,row['session'],symbol)]=row
            stability[ident][symbol]=summary_check(rows,case['summary'][symbol],sessions)
            active=[r for r in rows if r['campaigns']]
            if active:samples.add((ident,active[0]['session'],symbol))
    oldpath=ROOT/'work/wave_v106/regime_price/finance/results.json';prior=read_json(oldpath)
    for er,case in results['derived_C_comparators'].items():
        old=prior['cases'][f'C_ONLY_B2_ER{int(float(er)*100)}_B4'];original={(r['session'],r['symbol']):r for r in old['rows']}
        check(len(case['rows'])==66,'半量対照全場')
        for row in case['rows']:
            source=original[(row['session'],row['symbol'])]
            for field in ('campaigns','winning_campaigns','losing_campaigns','flat_campaigns'):equal(row[field],source[field],'半量対照/'+field)
            for field in ('profit','loss','net','gross','fees','winning_lots','losing_lots','flat_lots','lots','equity_peak','equity_trough','equity_drawdown'):equal(row[field],source[field]/2,'半量対照/'+field)
            check(row['derived'] and row['quantity']==(5 if row['symbol']=='TOPIX' else 10),'半量表示数量')
    # ----------------------------------------
    # 同じ原実行rowで料金・気配負担を分ける全33対照だけは全66台帳を読む。
    for session in sessions:
        for symbol in ('TOPIX','NK225'):samples.add((TARGET,session,symbol))
    sys.path.insert(0,str(SOURCE));import selection
    accounting=load_module('独立保存R注文規則照合',SOURCE/'engine/accounting.py')
    reads={};inputreads={};selected_records=[];costs={s:[] for s in ('TOPIX','NK225')};worst={}
    for symbol in costs:
        worst[symbol]={r['session'] for r in sorted([r for r in results['cases'][TARGET]['rows'] if r['symbol']==symbol and r['net']<0],key=lambda r:(r['net'],r['session']))[:3]}
    configs={c['id']:c for c in results['configs']}
    for session in sessions:
        selected=sorted(key for key in samples if key[1]==session)
        if not selected:continue
        packet=unpack(manifest['cache'][session],inputreads)
        for ident,_,symbol in selected:
            item=results['cases'][ident]['ledgers'][session][symbol];out=unpack(item,reads);record=packet['prepared'][symbol]['record']
            check(out['row_count']==len(record['seq']),'正常列行数一致')
            for name in ('curve','source_curve','target_trace'):out[name]=expand(out[name],out['row_count'])
            physical(record,out,rowindex[(ident,session,symbol)])
            normal=selection.build(packet,symbol,configs[ident]);derived=accounting.inspect((session,symbol),record,out,normal)
            compare_totals(rowindex[(ident,session,symbol)],totals([derived]),'四引数物理検算')
            check(normal['decisions']==out['selection_diagnostics'],'保存候補原行一致')
            check(out['component_settings']==configs[ident] or out['config_id']==ident,'保存条件識別')
            causality(record,out,normal,configs[ident])
            selected_records.append(dict(id=ident,session=session,symbol=symbol,orders=len(out['orders']),parents=len(out['trades']),rows=len(record['seq']),SHA256=item['SHA256']))
            if ident==TARGET:
                value=cost_trades(record,out)
                costs[symbol].append(dict(session=session,rows=value,赤字上位3=session in worst[symbol]))
            del out,normal
        # ----------------------------------------
        # 各商品・各ERの初回活動場だけ、C派生の根拠を実注文と整数料金で確認する。
        for symbol in ('TOPIX','NK225'):
            for er in (.2,.4):
                ident=f'C_ONLY_B2_ER{int(er*100)}_B4';case=prior['cases'][ident]
                active=[r for r in case['rows'] if r['symbol']==symbol and r['campaigns']]
                if active and session==active[0]['session']:
                    old=unpack(case['ledgers'][session][symbol],reads);q=5 if symbol=='TOPIX' else 10;fee=209 if symbol=='TOPIX' else 110
                    check(np.all(old['orders'][:,5]==2*q) and np.all(old['orders'][:,9]==2*fee),'C半量整数費用根拠')
                    for t in old['trades']:
                        equal(t[11]/2,t[4]*q*(t[7]-t[6])*(1000 if symbol=='TOPIX' else 10)-2*fee,'C半量実親現金')
                    del old
        del packet
        print(session+'：小会計と抽出実台帳の独立検算',flush=True)
    costsummary={};causes={}
    for symbol,groups in costs.items():
        flat=[r for group in groups for r in group['rows']];rows=[r for r in results['cases'][TARGET]['rows'] if r['symbol']==symbol]
        net=sum(r['収支'] for r in flat);equal(net,sum(r['net'] for r in rows),'全33実気配診断収支')
        costsummary[symbol]=dict(実親数=len(flat),負親=sum(r['収支']<0 for r in flat),
            mid変動粗損益=sum(r['mid変動粗損益'] for r in flat),往復気配差負担=sum(r['往復気配差負担'] for r in flat),
            手数料=sum(r['手数料'] for r in flat),収支=net,
            値動きがmidで有利でも赤字=sum(r['mid変動粗損益']>0 and r['収支']<0 for r in flat),
            固定stopはfill時既破れ親=sum(r['固定stopはfill時既破れ'] for r in flat),
            同row反転数学収支=sum(r['同row反転数学収支'] for r in flat),
            同row反転の赤字場=sum(sum(r['同row反転数学収支'] for r in group['rows'])<0 for group in groups),
            同row反転の勝親=sum(r['同row反転数学収支']>0 for r in flat))
        causes[symbol]=[dict(session=group['session'],掲載会計=next(r for r in rows if r['session']==group['session']),
            全親数=len(group['rows']),最初の負親=next((r for r in group['rows'] if r['収支']<0),None),
            最悪負親=min(group['rows'],key=lambda r:r['収支']) if group['rows'] else None,
            合計mid変動粗損益=sum(r['mid変動粗損益'] for r in group['rows']),
            合計気配差負担=sum(r['往復気配差負担'] for r in group['rows']),合計料金=sum(r['手数料'] for r in group['rows']))
            for group in groups if group['赤字上位3']]
    # ----------------------------------------
    # 全33変更寄与の足し算は実損益へ一致させ、結果を将来の入力条件へ混ぜない。
    deltas={ident:{s:defaultdict(float) for s in ('TOPIX','NK225')} for ident in configs}
    fields=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
    for session in sessions:
        ds=read_json(SOURCE/'finance/session_contributions'/f'{session}.json')
        for ident in configs:
            for symbol in ('TOPIX','NK225'):
                d=ds[ident][symbol];equal(d['収支変化'],d['避けた基準損失']-d['失った基準利益']+d['共通入口の出口変化']+d['新たな入口の収支'],'変更寄与恒等式')
                for field in fields:deltas[ident][symbol][field]+=d[field]
    for ident,config in configs.items():
        for symbol in ('TOPIX','NK225'):
            for field in fields:equal(results['diagnosis'][ident][symbol][field],deltas[ident][symbol][field],'変更寄与全場集計')
            base=sum(r['net'] for r in results['derived_C_comparators'][str(config['range_er'])]['rows'] if r['symbol']==symbol)
            equal(deltas[ident][symbol]['収支変化'],stability[ident][symbol]['収支']-base,'変更寄与実収支差')
    check(before=={name:sha(ROOT/name) for name in before},'監査開始終端源一致')
    eligible=[ident for ident,value in stability.items() if all(v['収支']>0 and v['活動場']>=16 and v['親数']>=20 for v in value.values())]
    proof=dict(全合格=True,scope='全24条件×33場×2商品の保存小会計1584口座を独立再集計。実金融は機械抽出のみ、全台帳会計監査とは称さない。',
        全小会計口座=1584,半量派生対照口座=132,抽出実台帳数=len(selected_records),抽出条件='各条件・各商品の時系列最初の活動口座＋R_ONLY_ER40_M1_LIMIT全33×2。別途C半量実注文4口座。',
        検査件数=dict(COUNT),検査合計=sum(COUNT.values()),安定性=stability,両銘柄最低活動と黒字達成=eligible,
        実気配負担と同row反転数学=costsummary,細い停止の赤字上位3原因=causes,抽出実台帳=selected_records,
        保存入力読取=dict(range_packet=len(inputreads),台帳=len(reads),原板=0,旧大素材=0,NPZ=0,API=0),
        新金融再生=0,候補projection='selection.buildは保存入力から当時正常行条件を再構築するだけ。execute/playは呼ばない。',
        入力SHA256={**inputreads,**reads},source_SHA256=before,
        正本SHA256={str(p.relative_to(ROOT)):sha(p) for p in (SOURCE/'finance/results.json',SOURCE/'事前固定.json',SOURCE/'試行計画.json',SOURCE/'全33場の価格境界反発準備.json',oldpath)},
        開始終端source一致=True,レビューsource_SHA256=sha(Path(__file__)),
        限界=['全33は既知研究データ。将来の収益保証ではない。','中央値は全33と活動場を分け、無取引を勝ちに含めない。',
            'CurrentPriceTimeは受信時計ではない。同時計でも原seqで公表後を区別する。',
            '六点ERはsampleの往復であり全tick範囲の保証ではない。表示数量や約定待ち順番を再現していない。',
            '同row反転は元実注文rowを固定した価格費用の数学参考。別売買注文として実行できることや同じ経路を保つことを主張しない。',
            '抽出の実台帳数と全1584小会計検査を区別する。個別数量の補充理由をこの資料で新たに実証していない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print('独立保存会計合格',len(selected_records),'実台帳',sum(COUNT.values()),'検査',flush=True)


if __name__=='__main__':
    try:main()
    except BaseException as error:
        failure=HERE/'range_保存金融監査のFalse.json'
        check(not failure.exists(),'失敗証跡上書きなし')
        failure.write_text(json.dumps(dict(全合格=False,例外=repr(error),traceback=traceback.format_exc(),検査件数=dict(COUNT),新金融再生=0),ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        raise
