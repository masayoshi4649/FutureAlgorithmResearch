"""固定済みの秒売買結果を比較する。新しい条件選定や売買再生は行わない。"""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib
import json
import pickle
import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
HASHES = {}
JST = timezone(timedelta(hours=9))
METHODS = ('S3_P6_M0_C5', 'S3_P6_M1_C5', 'S3_P6_M2_C30', 'A6_P6_M0', 'A6_P6_M1', 'R32',
           'S6_P6_M0_C30', 'S6_P6_M1_C30')


def load(path):
    """
    機能: 保存結果を読み、出典の指紋を記録する。
    引数: path (Path)。
    返り値: object の読み込み内容。
    """
    data = path.read_bytes()
    HASHES[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return pickle.loads(data) if path.suffix == '.pkl' else json.loads(data.decode('utf-8'))


# ----------------------------------------
def stamp(seconds):
    """
    機能: 代理時計を日本時間で表示する。
    引数: seconds (float)。
    返り値: str の日時。
    """
    return datetime.fromtimestamp(float(seconds), JST).isoformat()


# ----------------------------------------
def stats(values):
    """
    機能: 実際の判断から約定までの待ち秒を要約する。
    引数: values (list[float])。
    返り値: dict の件数、中央値、95百分位、最大値。
    """
    return dict(件数=len(values), 中央値秒=float(np.median(values)) if values else None,
                百分位95秒=float(np.percentile(values, 95)) if values else None,
                最大秒=float(max(values)) if values else None)


# ----------------------------------------
def trades_for(ledgers, symbol, sessions):
    """
    機能: 同一の入口判断をキーとして決済取引と注文を対応させる。
    引数: ledgers (dict)、symbol (str)、sessions (list[str])。
    返り値: dict。キーは場・自己判断行・判断秒・方向。
    """
    out = {}
    for (session, market), ledger in ledgers.items():
        if market != symbol or session not in sessions: continue
        orders = ledger['orders']
        for t in ledger['trades']:
            own = orders[orders[:, 2] == t[0]]
            e, x = own[own[:, 7] == 1][0], own[own[:, 7] == 0][0]
            assert len(own) == 2 and abs(t[10] - (t[9] - e[8] - x[8])) < 1e-6
            key = (session, int(e[1]), float(e[10]), int(t[3]))
            assert key not in out
            out[key] = dict(trade=t, entry=e, exit=x)
    return out


# ----------------------------------------
def path_change(old, new):
    """
    機能: 遅れ変更で入口自体が増減する効果と共通入口の価格・出口変更を分ける。
    引数: old/new (dict) は入口キー付き取引。
    返り値: dict の加法分解。後付けで同時刻以外の入口を対応させない。
    """
    both = old.keys() & new.keys(); only_old = old.keys() - new.keys(); only_new = new.keys() - old.keys()
    matched_delta = sum(new[k]['trade'][10] - old[k]['trade'][10] for k in both)
    vanished = sum(old[k]['trade'][10] for k in only_old); added = sum(new[k]['trade'][10] for k in only_new)
    old_net = sum(v['trade'][10] for v in old.values()); new_net = sum(v['trade'][10] for v in new.values())
    result = dict(旧取引数=len(old), 新取引数=len(new), 共通入口数=len(both), 消えた入口数=len(only_old), 増えた入口数=len(only_new),
                  旧収支円=float(old_net), 新収支円=float(new_net), 収支差円=float(new_net-old_net),
                  共通入口の収支差円=float(matched_delta), 消えた入口の旧収支円=float(vanished), 増えた入口の新収支円=float(added),
                  共通入口の新規約定行変化数=sum(old[k]['entry'][0] != new[k]['entry'][0] for k in both),
                  共通入口の返済判断時計変化数=sum(old[k]['exit'][10] != new[k]['exit'][10] for k in both),
                  共通入口の返済理由変化数=sum(old[k]['exit'][6] != new[k]['exit'][6] for k in both),
                  共通入口の返済約定行変化数=sum(old[k]['exit'][0] != new[k]['exit'][0] for k in both))
    result['加法一致'] = abs(new_net-old_net-(matched_delta+added-vanished)) < 1e-6
    assert result['加法一致']
    result['注意'] = '共通入口も返済判断や保有経路が変わる。単一の完成済み取引へ5秒分の費用を後引きした比較ではない。'
    return result


# ----------------------------------------
def compare_metrics(old, new):
    """
    機能: 利益の減少と損失の減少を区別する。
    引数: old/new (dict) は期間会計。
    返り値: dict の前後の数値と差。
    """
    fields = ('profit', 'loss', 'net', 'trades', 'profit_share', 'payoff', 'average_net',
              'winning_sessions', 'losing_sessions', 'no_trade_sessions')
    return dict(前={k: old[k] for k in fields}, 後={k: new[k] for k in fields},
                利益増減円=new['profit']-old['profit'], 損失削減円=old['loss']-new['loss'],
                収支改善円=new['net']-old['net'], 取引増減=new['trades']-old['trades'],
                金額利益割合差=new['profit_share']-old['profit_share'] if None not in (new['profit_share'],old['profit_share']) else None)


# ----------------------------------------
def max_loss_trace(ledger):
    """
    機能: A6成行のTOPIX最大損失を原本の連続行と注文時計で確認する。
    引数: ledger (dict) は遅れ5秒のA6成行全口座。
    返り値: dict の事後診断。原本を変更せず未来を売買判断へ戻さない。
    """
    key, trade = min(((k,t) for k,l in ledger.items() if k[1]=='TOPIX' for t in l['trades']), key=lambda v:v[1][10])
    session, symbol = key
    orders = ledger[key]['orders'][ledger[key]['orders'][:,2] == trade[0]]
    entry, exit_order = orders[orders[:,7]==1][0], orders[orders[:,7]==0][0]
    meta = load(ROOT/'work/wave_v77/inputs/metadata.json'); ready = book = None
    for name in meta['input_paths']['ready']+['work/wave_v77/inputs/extra_inputs.pkl']:
        data=load(ROOT/name)
        if key in data: ready=data[key]
        del data
    for name in meta['input_paths']['features']+['work/wave_v77/inputs/extra_features.pkl']:
        data=load(ROOT/name)
        if key in data: book=data[key]
        del data
    assert ready is not None and book is not None
    indices = dict(入口根拠=int(entry[16]), 新規判断=int(entry[1]), 新規約定=int(entry[0]), 返済判断=int(exit_order[1]), 返済約定=int(exit_order[0]))
    sequence = ready['seq']; times=ready['time_s']; bid=book['bid']; ask=book['ask']
    start=max(0,indices['入口根拠']-1); end=indices['返済約定']+1
    data_rows=[]
    for j in range(start,end+1):
        data_rows.append(dict(準備行=j, 原本seq=int(sequence[j]), 代理時計=stamp(times[j]),
                              bid=float(bid[j]), ask=float(ask[j]), 買数量=float(book['bid_qty'][j]), 売数量=float(book['ask_qty'][j]),
                              直前行から代理時計間隔秒=float(times[j]-times[j-1]) if j else None,
                              約定入口からの返済側値幅呼値=float((bid[j]-trade[5])/ready['tick'])))
    desired={r['原本seq']:r for r in data_rows}; verified=0
    raw_path=ROOT/'book'/symbol/(session+'.jsonl'); h=hashlib.sha256()
    with raw_path.open('rb') as stream:
        for seq,line in enumerate(stream):
            h.update(line)
            if seq not in desired: continue
            raw=json.loads(line); r=desired[seq]
            assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()==datetime.fromisoformat(r['代理時計']).timestamp()
            assert raw['Buy1']['Price']==r['bid'] and raw['Sell1']['Price']==r['ask']
            assert raw['Buy1']['Qty']==r['買数量'] and raw['Sell1']['Qty']==r['売数量']
            verified+=1
    assert verified==len(data_rows)
    HASHES[str(raw_path.relative_to(ROOT))]=h.hexdigest()
    order_details={name:dict(判断=stamp(o[10]), 到着予定=stamp(o[11]), 約定=stamp(o[12]),
                             待ち秒=float(o[12]-o[10]), 価格=float(o[5]), 理由番号=int(o[6]))
                   for name,o in [('新規',entry),('返済',exit_order)]}
    stop_price=trade[5]-3*ready['tick']
    ei,di,xi=indices['新規約定'],indices['返済判断'],indices['返済約定']
    price_rows = [r for r in data_rows if r['準備行'] in indices.values()]
    decision_loss = (trade[5]-bid[di])*10000
    wait_loss = (bid[di]-trade[6])*10000
    assert abs(trade[10]+decision_loss+wait_loss+836)<1e-6
    return dict(手法='A6_P6_M0', 発注遅れ秒=5, セッション=session, 商品=symbol, 組=int(trade[0]),
                収支円=float(trade[10]), 新規価格=float(trade[5]), 返済価格=float(trade[6]), 損切り設定呼値=3,
                想定発動価格=float(stop_price), 実際返済判断bid=float(bid[di]), 返済待ち後bid=float(trade[6]),
                設定幅による価格損失円=15000, 発動観測時点までの追加価格損失円=float(decision_loss-15000),
                返済判断後の追加価格損失円=float(wait_loss), 手数料円=836,
                新規約定から返済判断秒=float(exit_order[10]-entry[12]), 約定から約定の保有秒=float(exit_order[12]-entry[12]),
                発動直前観測bid=float(bid[di-1]), 発動直前観測時計=stamp(times[di-1]),
                発動直前から判断観測の代理時計間隔秒=float(times[di]-times[di-1]),
                新規約定から返済約定までの最大代理時計間隔秒=float(np.diff(times[ei:xi+1]).max()),
                注文時計=order_details, 特徴行=indices, 特徴時点の観測=price_rows,
                原本独立照合行数=verified, 原本連続観測=data_rows,
                注意='CurrentPriceTimeは最後の約定の代理時計であり、実際の板受信間隔や通信断を証明しない。損切り幅は発注条件であって最大損失額の保証ではない。')


# ----------------------------------------
def clean(value):
    """
    機能: NumPy型をJSON保存できる値へ変換する。
    引数: value (object)。
    返り値: object のJSON互換値。
    """
    if isinstance(value,dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [clean(v) for v in value]
    if isinstance(value,np.generic): return clean(value.item())
    if isinstance(value,float) and not np.isfinite(value): return None
    return value


# ----------------------------------------
def main():
    """
    機能: 保存済みの最終結果を比較して診断だけを追記する。
    引数: なし。
    返り値: None。新しい売買条件選定や再生は行わない。
    """
    fixed=load(BASE/'初回事前固定.json')
    periods={'全30':fixed['全30'],'前16':fixed['前16'],'後14':fixed['後14']}
    summaries={}; ledgers={}; waits={}; paths={}; comparisons={}; rarity={}
    for delay in (0,1,5):
        summaries[str(delay)]={}
        for method in METHODS:
            result=load(BASE/f'final/delay{delay}/results/{method}.json')
            summaries[str(delay)][method]={p:result['periods']['対象' if p=='全30' else p] for p in periods}
            ledgers[(delay,method)]=load(BASE/f'final/delay{delay}/ledgers/{method}.pkl')
            for period,sessions in periods.items():
                for symbol in ('TOPIX','NK225'):
                    group=trades_for(ledgers[(delay,method)],symbol,sessions)
                    saved=summaries[str(delay)][method][period][symbol]
                    assert len(group)==saved['trades'] and sum(t['trade'][10] for t in group.values())==saved['net']
                    if method in ('S3_P6_M0_C5','A6_P6_M0'):
                        waits[f'{method}|遅れ{delay}|{period}|{symbol}']={label:stats([float(t[col][12]-t[col][10]) for t in group.values()])
                                                                           for label,col in [('新規','entry'),('返済','exit')]}
    for method in METHODS:
        paths[method]={}
        for period,sessions in periods.items():
            paths[method][period]={symbol:path_change(trades_for(ledgers[(0,method)],symbol,sessions),
                                                      trades_for(ledgers[(5,method)],symbol,sessions)) for symbol in ('TOPIX','NK225')}
    for old,new in [('S3_P6_M0_C5','A6_P6_M0'),('S3_P6_M1_C5','A6_P6_M1'),('S3_P6_M2_C30','R32'),
                    ('S6_P6_M0_C30','A6_P6_M0'),('S6_P6_M1_C30','A6_P6_M1')]:
        comparisons[old+'→'+new]={period:{symbol:compare_metrics(summaries['5'][old][period][symbol],summaries['5'][new][period][symbol])
                                               for symbol in ('TOPIX','NK225')} for period in periods}
    max_loss=max_loss_trace(ledgers[(5,'A6_P6_M0')])
    output=dict(範囲='前半で固定した代表・対照の前16、後14、全30。全30は既知資料。後半による新条件選定は行わない。',
                新再生=False, 条件変更=False,
                比較上の注意=['S3→A6は入口家族、3秒確認の有無、休止5→30秒が同時に変わる。単一改修の効果とみなさない。',
                              'S6_C30→A6は同じ失速反転家族・同じ管理幅・同じ休止30秒で確認の有無を比較する。ただし生状態は機会数を大幅に増やす。',
                              '遅れ0秒も判断行の次の有効観測を待つ。0秒は同じ行で即約定する理想価格ではない。',
                              '発注遅れ5秒は最短の到着待ち。次の有効気配まで待つため実際の約定待ちは5秒を超える。',
                              '実際の板受信時計とmini/micro板がなく、秒単位の実運用性能は確証できない。'],
                各固定案の期間会計=summaries, 改修前後5秒比較=comparisons, 遅れ0から5の経路分解=paths,
                成行の実待ち時間=waits, 最大損失の具体的経路=max_loss, 出典SHA256=HASHES)
    target=HERE/'最終代表の改善限界と遅延経路.json'
    target.write_text(json.dumps(clean(output),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(clean(dict(保存=str(target), 最大損失={k:v for k,v in max_loss.items() if k not in ('原本連続観測','特徴時点の観測')},
                               待ち全30={k:v for k,v in waits.items() if '遅れ5|全30' in k},
                               経路全30={k:v['全30'] for k,v in paths.items() if k in ('S3_P6_M0_C5','A6_P6_M0','A6_P6_M1')})),ensure_ascii=False))


if __name__=='__main__': main()
