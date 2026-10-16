"""登録後の保存36結果を、安定性と実入口時点の票及び費用へ戻して診断する。"""

import argparse
from collections import Counter
from datetime import datetime,timezone,timedelta
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np


sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
GATE=HERE.parent
ROOT=HERE.parents[3]
RESULT=GATE/'finance/results.json'
BASELINE=ROOT/'work/wave_v106/range_price/finance/results.json'
INPUT=GATE/'全33場の取引更新代理準備_v2.json'
JST=timezone(timedelta(hours=9))
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def digest(path: Path) -> str:
    """
    機能: 小sourceと完成由来資料のSHAを確認する。
    引数: path(Path)は小さい資料。
    返り値: strはSHA256。大cacheは一回読取bytesから確認する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 日本語JSONの保存資料を読む。
    引数: path(Path)は読み取る資料。
    返り値: dictは保存された内容。金融条件を変更しない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(name: str, value: dict) -> None:
    """
    機能: 新しい診断証跡だけを所有領域へ保存する。
    引数: name(str)は名前、value(dict)はJSON互換値。
    返り値: None。登録済みsource/plan/金融結果を上書きしない。
    """
    path=HERE/name;assert not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')


def fix() -> None:
    """
    機能: 完成結果を読む前に、診断目的・一回読取範囲・事後順位の分母を固定する。
    引数: なし。
    返り値: None。数値結果や巨大inputはまだ読まない。
    """
    meta=read(INPUT);finance_fixed=read(GATE/'金融開始前の固定_v2.json')
    assert meta['全合格'] and len(meta['sessions'])==33 and len(meta['configs'])==36
    value=dict(全合格=True,目的='固定36の事後安定性と赤字3場の因果入口/実費用/失った利益を確認。新条件を作らない。',
        source_SHA256={str(Path(__file__).relative_to(ROOT)).replace('\\','/'):digest(Path(__file__))},
        immutable_financial_sources=finance_fixed['source_SHA256'],input_metadata=dict(path=INPUT.relative_to(ROOT).as_posix(),SHA256=digest(INPUT)),
        input_cache=meta['cache'],sessions=meta['sessions'],configs=meta['configs'],
        financial_results=RESULT.relative_to(ROOT).as_posix(),baseline_results=BASELINE.relative_to(ROOT).as_posix(),
        baseline_results_SHA256=finance_fixed['baseline_results_SHA256'],
        読取='新results1回、旧4AUTO結果JSON1回。全36各銘柄赤字worst3に必要な新ledger/対応baseline ledgerをpath重複排除して各1回。新inputは必要場だけ各1回。原板/NPZ/API/新金融0。',
        事後順位='最小の両商品活動黒字率→最小の上位3利益場除外収支/(総利益+総損失)→最小の金額利益割合、降順。無活動/無利益は順位末尾。これは新採用基準ではない。',
        分母='活動場はcampaigns>0、無取引は勝ちに含めない。活動中央値と全33中央値を別記。',
        具体原因='全36各銘柄worst赤字3場の実親を当時票へ照合。MFE/利益返しは保有中の事後正常清算BBO。失った利益と新後続は保存baselineの同entryseq/sideへ対応。',
        金融結果読取=0,原book読取=0,現在snapshot読取=0,API取得=0,新金融再生=0)
    write('診断読取前の固定.json',value);print('診断目的と一回読取範囲を固定しました。')


def metrics(rows: list[dict], symbol: str) -> dict:
    """
    機能: 同商品だけの利益/損失割合と活動安定性を保存会計から再集計する。
    引数: rows(list[dict])は66小会計、symbol(str)は商品。
    返り値: dictは全33及び活動場の安定性。銘柄金額を単純合算しない。
    """
    selected=[r for r in rows if r['symbol']==symbol];assert len(selected)==33
    active=[r for r in selected if r['campaigns']>0];positive=[r for r in active if r['net']>1e-5];negative=[r for r in active if r['net']<-1e-5]
    profit=sum(r['profit'] for r in selected);loss=sum(r['loss'] for r in selected);net=sum(r['net'] for r in selected)
    assert abs(net-(profit-loss))<1e-5
    best=sorted(selected,key=lambda r:(-r['net'],r['session']))[:3];without=net-sum(r['net'] for r in best if r['net']>0)
    monetary=profit+loss;worst=min(selected,key=lambda r:(r['net'],r['session']))
    splits={}
    for label,field,names in (('買売','directions',('買い','売り')),('C_R','sources',('J2','O06'))):
        splits[label]={name:{k:sum(r[field][name][k] for r in selected) for k in ('profit','loss','net','gross','fees','campaigns','winning_lots','losing_lots')} for name in names}
    return dict(profit=profit,loss=loss,net=net,profit_share=profit/monetary if monetary else None,
        active_sessions=len(active),positive_sessions=len(positive),losing_sessions=len(negative),no_trade_sessions=33-len(active),
        positive_active_rate=len(positive)/len(active) if active else None,
        median_active_net=float(np.median([r['net'] for r in active])) if active else None,
        median_all33_net=float(np.median([r['net'] for r in selected])),without_top3_net=without,
        without_top3_monetary_ratio=without/monetary if monetary else None,removed_top3_positive_sessions=[dict(session=r['session'],net=r['net']) for r in best if r['net']>0],
        worst_session=dict(session=worst['session'],net=worst['net']),fees=sum(r['fees'] for r in selected),
        campaigns=sum(r['campaigns'] for r in selected),**splits)


def clock(record: dict, row: int) -> dict:
    """
    機能: 原seqと価格代理時計を実行normal行に結ぶ。
    引数: record(dict)、row(int)は保存価格列と行。
    返り値: dictは当時原seq、価格時計と日本時間。受信時刻ではない。
    """
    return dict(normal_row=row,raw_seq=int(record['seq'][row]),price_time_s=float(record['time_s'][row]),
        JST=datetime.fromtimestamp(float(record['time_s'][row]),JST).isoformat())


def trade_key(record: dict, trade: np.ndarray) -> str:
    """
    機能: 親番号の変化を超えて、同じ入口原seqと方向へ対応させる。
    引数: record(dict)、trade(ndarray)は同正常価格と実親。
    返り値: strは入口判断seqと方向の鍵。
    """
    return str(int(record['seq'][int(trade[15])]))+'|'+str(int(trade[4]))


def describe(record: dict, ledger: dict, trade: np.ndarray, feature: dict | None) -> dict:
    """
    機能: 実親の当時方向票と、順行/気配差/費用/利益返しを別々に診断する。
    引数: record/ledger(dict)、trade(ndarray)、feature(dict|None)は保存入力・経済・当時票。
    返り値: dictは事後原因。最大順行や最終勝敗を当時条件へ戻さない。
    """
    parent=int(trade[0]);start=int(trade[2]);end=int(trade[3]);decision=int(trade[15]);side=int(trade[4]);qty=int(trade[5])
    entry=float(trade[6]);exit=float(trade[7]);mult=1000. if record['symbol']=='TOPIX' else 10.;fee=float(trade[8]+trade[9])
    indexes=np.arange(start,end+1);valid=(record['quote_valid'][indexes]&np.isfinite(record['bid'][indexes])&np.isfinite(record['ask'][indexes])&
        (record['bid'][indexes]>0)&(record['ask'][indexes]>record['bid'][indexes]));indexes=indexes[valid];assert len(indexes)
    clearing=record['bid'][indexes] if side==1 else record['ask'][indexes];movement=side*(clearing-entry)
    best=int(np.argmax(movement));worst=int(np.argmin(movement));maximum=float(movement[best]*qty*mult-fee)
    mid=(record['bid']+record['ask'])/2.;mid_gross=side*(mid[end]-mid[start])*qty*mult
    gross=float(trade[10]);net=float(trade[11]);best_mid=max(0.,float(np.max(side*(mid[indexes]-mid[start]))))
    category='利益あり' if net>0 else '清算利益を返して赤字' if maximum>1e-5 else '中値順行はあったが気配差/費用を越えなかった' if best_mid>0 else '方向順行なく赤字'
    exit_order=next(o for o in ledger['orders'] if int(o[2])==parent and not o[7])
    source='C進行' if int(trade[1])==0 else 'R価格反発'
    return dict(parent_id=parent,source=source,side='買い' if side==1 else '売り',quantity=qty,net=net,gross=gross,fees=fee,
        decision=clock(record,decision),entry=dict(**clock(record,start),price=entry),exit_decision=clock(record,int(exit_order[1])),exit=dict(**clock(record,end),price=exit),
        contemporaneous_votes=feature,entry_gate_allowed=bool(ledger['entry_filter'][decision]) if 'entry_filter' in ledger else None,
        exit_reason=int(trade[13]),category=category,
        midpoint_gross=mid_gross,BBO_cost_relative_to_mid=mid_gross-gross,
        max_favourable_ticks=max(0.,float(movement[best]))/record['tick'],max_adverse_ticks=max(0.,float(-movement[worst]))/record['tick'],
        best_liquidation_net=maximum,best_clock=clock(record,int(indexes[best])),
        positive_liquidation_seen=maximum>1e-5,profit_given_back=max(0.,maximum-net) if maximum>1e-5 else 0.,
        after_entry_observation='MFE/利益返しは実保有区間の事後値。Lastは当時代理票だけで中値から補完していない。')


def run() -> None:
    """
    機能: root完了通知後の保存結果だけを読み、36小結と各最悪3赤字場の原因を保存する。
    引数: なし。
    返り値: None。新売買や新金融を作らず、キャッシュ/台帳はpath毎一回だけ読む。
    """
    fixed=read(HERE/'診断読取前の固定.json')
    assert fixed['source_SHA256']=={str(Path(__file__).relative_to(ROOT)).replace('\\','/'):digest(Path(__file__))}
    for name,sha in fixed['immutable_financial_sources'].items():assert digest(ROOT/name)==sha,name
    reads=Counter();payload=RESULT.read_bytes();results=json.loads(payload);result_sha=hashlib.sha256(payload).hexdigest();reads['完成36結果']=1
    assert results['全合格'] and results['sessions']==fixed['sessions'] and results['configs']==fixed['configs'] and results['account_count']==2376
    baseline_payload=BASELINE.read_bytes();baseline=json.loads(baseline_payload);baseline_sha=hashlib.sha256(baseline_payload).hexdigest();reads['完成4基準結果JSON']=1
    assert baseline_sha==fixed['baseline_results_SHA256']
    small={identifier:{s:metrics(case['rows'],s) for s in ('TOPIX','NK225')} for identifier,case in results['cases'].items()}
    ranking=[]
    for identifier,value in small.items():
        usable=all(value[s]['active_sessions']>0 and value[s]['profit_share'] is not None for s in ('TOPIX','NK225'))
        rank_values=[min(value[s][key] for s in ('TOPIX','NK225')) if usable else -1e100 for key in ('positive_active_rate','without_top3_monetary_ratio','profit_share')]
        ranking.append(dict(id=identifier,rank_values=rank_values,eligible_for_descriptive_rank=usable))
    ranking.sort(key=lambda r:tuple([-v for v in r['rank_values']]+[r['id']]))
    selected=ranking[0]['id'];targets={};configs={c['id']:c for c in fixed['configs']}
    for identifier,case in results['cases'].items():
        for symbol in ('TOPIX','NK225'):
            losses=sorted([r for r in case['rows'] if r['symbol']==symbol and r['net']<-1e-5],key=lambda r:(r['net'],r['session']))[:3]
            for row in losses:targets.setdefault(row['session'],{}).setdefault(symbol,[]).append(identifier)
    memo={};loaded_sha={}
    def unpack(item: dict) -> dict:
        """
        機能: 同じ保存台帳を各一回だけ読み、同bytesの指紋を確認する。
        引数: item(dict)はroot相対path/SHA256。
        返り値: dictは保存台帳。原本bookや金融関数を再生しない。
        """
        name=item['path']
        if name not in memo:
            value=(ROOT/name).read_bytes();assert hashlib.sha256(value).hexdigest()==item['SHA256']
            memo[name]=pickle.loads(gzip.decompress(value));loaded_sha[name]=item['SHA256'];reads['unique保存台帳']+=1
        return memo[name]
    details={i:{s:[] for s in ('TOPIX','NK225')} for i in results['cases']}
    for session,symbols in targets.items():
        item=fixed['input_cache'][session];saved=(ROOT/item['path']).read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256']
        packet=pickle.loads(gzip.decompress(saved));reads['unique診断input場']+=1;loaded_sha[item['path']]=item['SHA256']
        for symbol,identifiers in symbols.items():
            record=packet['prepared'][symbol]['record']
            for identifier in identifiers:
                cfg=configs[identifier];window=str(cfg['trade_window_seconds']);features=packet['trade_features'][symbol][window]
                ledger=unpack(results['cases'][identifier]['ledgers'][session][symbol]);old=unpack(baseline['cases'][cfg['baseline_id']]['ledgers'][session][symbol])
                current={trade_key(record,t):t for t in ledger['trades']};prior={trade_key(record,t):t for t in old['trades']}
                actual=[describe(record,ledger,t,features[int(t[15])]) for t in ledger['trades']]
                removed=[];added=[]
                for key in sorted(set(prior)-set(current)):
                    trade=prior[key];row=int(trade[15]);flag=bool(ledger['entry_filter'][row])
                    removed.append(dict(key=key,baseline_net=float(trade[11]),was_profit=bool(trade[11]>0),
                        entry_gate_allowed=flag,cause='公開gateによる直接拒否' if not flag else '別先行取引の採否による保有/待機/休止経路差',
                        trade=describe(record,old,trade,features[row])))
                for key in sorted(set(current)-set(prior)):
                    trade=current[key];added.append(dict(key=key,cause='元同じ公開候補が、変更した先行経路により新たに実参加。新しい未来条件ではない。',
                        trade=describe(record,ledger,trade,features[int(trade[15])])) )
                delta={field:0. for field in FIELDS}
                delta['避けた基準損失']=sum(-prior[k][11] for k in set(prior)-set(current) if prior[k][11]<0)
                delta['失った基準利益']=sum(prior[k][11] for k in set(prior)-set(current) if prior[k][11]>0)
                delta['共通入口の出口変化']=sum(current[k][11]-prior[k][11] for k in set(prior)&set(current))
                delta['新たな入口の収支']=sum(current[k][11] for k in set(current)-set(prior))
                delta['収支変化']=sum(t[11] for t in current.values())-sum(t[11] for t in prior.values())
                assert abs(delta['収支変化']-(delta['避けた基準損失']-delta['失った基準利益']+delta['共通入口の出口変化']+delta['新たな入口の収支']))<1e-5
                details[identifier][symbol].append(dict(session=session,net=sum(float(t[11]) for t in ledger['trades']),
                    baseline_id=cfg['baseline_id'],base_net=sum(float(t[11]) for t in old['trades']),five_contributions={k:float(v) for k,v in delta.items()},
                    actual_trades=actual,removed_baseline_trades=removed,new_later_trades=added,economic_alias=ledger.get('economic_alias')))
        del packet
    assert fixed['source_SHA256']=={str(Path(__file__).relative_to(ROOT)).replace('\\','/'):digest(Path(__file__))}
    write('全36の安定性とscope寄与の小結.json',dict(全合格=True,results=small,ranking=ranking,selected_descriptive_id=selected,
        descriptive_only=True,posthoc_rank_definition=fixed['事後順位'],diagnosis=results['diagnosis'],
        displayed_accounts=results['account_count'],actual_accounts=results['actual_financial_accounts'],economic_reused_accounts=len(results['economic_aliases']),
        完全全33既知=True,未見答え合わせ=0,無取引は勝ちに含めない=True,
        収益未達='事後順位首位でも新採用や将来安定を意味しない。中央値/上位3除外の両商品結果を必ず併記する。',
        result_SHA256=result_sha,baseline_SHA256=baseline_sha,金融再生=0,API取得=0))
    write('全36最悪3場の入口票と費用及び逃した利益.json',dict(全合格=True,details=details,selected_descriptive_id=selected,
        loaded_SHA256=loaded_sha,read_counts=dict(reads),source_SHA256=fixed['source_SHA256'],開始終端source一致=True,
        result_SHA256=result_sha,baseline_SHA256=baseline_sha,read_plan_SHA256=digest(HERE/'診断読取前の固定.json'),
        registered_source_change=0,new_finance=0,original_book=0,NPZ_read=0,current_snapshot=0,API=0,
        限界='当時票と事後経済を別に保存。最大順行/利益返し/最終勝敗は入口へ戻さず、Last攻撃側は代理。'))
    print(json.dumps(dict(全合格=True,事後記述首位=selected,首位=small[selected],読取=dict(reads)),ensure_ascii=False))


def main() -> None:
    """
    機能: 診断読取前固定又は根の金融完了通知後の一回解析を選ぶ。
    引数: CLI --fix-only/--root-finance-complete(bool)。
    返り値: None。金融/API/原本の新しい実行はしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--fix-only',action='store_true');parser.add_argument('--root-finance-complete',action='store_true')
    args=parser.parse_args();assert args.fix_only!=args.root_finance_complete
    if args.fix_only:fix();return
    def denied(*args: object,**kwargs: object) -> None:
        """
        機能: 保存診断のネットワーク接続を拒否する。
        引数: args/kwargs(object)は通信要求。
        返り値: None。常に拒否する。
        """
        raise RuntimeError('保存診断はAPI禁止')
    socket.create_connection=denied;socket.socket.connect=denied
    assert not (HERE/'全36の安定性とscope寄与の小結.json').exists();run()


if __name__=='__main__':main()
