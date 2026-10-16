"""初回前半の固定代表だけを分解し、改修前の損失原因を調べる。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import pickle
import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
JST = timezone(timedelta(hours=9))
HASHES = {}


def load(path):
    """
    機能: 指定した既存ファイルを読み、その指紋を残す。
    引数: path (Path)。
    返り値: object のJSON又はpickle保存内容。
    """
    data = path.read_bytes()
    HASHES[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return pickle.loads(data) if path.suffix == '.pkl' else json.loads(data.decode('utf-8'))


# ----------------------------------------
def stamp(seconds):
    """
    機能: 代理時計の秒値を日本時間へ変換する。
    引数: seconds (float)。
    返り値: str の日本時間。
    """
    return datetime.fromtimestamp(float(seconds), JST).isoformat()


# ----------------------------------------
def clean(value):
    """
    機能: NumPy由来の値を欠測nullのJSON互換値へ変換する。
    引数: value (object)。
    返り値: object のJSON互換値。
    """
    if isinstance(value, dict): return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [clean(v) for v in value]
    if isinstance(value, np.ndarray): return clean(value.tolist())
    if isinstance(value, np.generic): return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value): return None
    return value


# ----------------------------------------
def aggregate(trades):
    """
    機能: 一群の取引の二種類の損益分解を合計する。
    引数: trades (list[dict])。
    返り値: dict の損益・費用・発注遅延・再入口統計。
    """
    fields = ('収支円', '中値経路円', '新規対中値不利円', '返済対中値不利円', '手数料円',
              '新規判断から約定の不利円', '返済判断から約定の不利円', '判断気配の仮収支円')
    out = {f: sum(t[f] for t in trades) for f in fields}
    out.update(取引数=len(trades), 利益円=sum(max(0., t['収支円']) for t in trades),
               損失円=sum(max(0., -t['収支円']) for t in trades), 勝ち数=sum(t['収支円'] > 0 for t in trades),
               負け数=sum(t['収支円'] < 0 for t in trades))
    out['同時点中値分解一致'] = abs(out['収支円'] - (out['中値経路円'] - out['新規対中値不利円'] - out['返済対中値不利円'] - out['手数料円'])) < 1e-6
    out['判断約定分解一致'] = abs(out['収支円'] - (out['判断気配の仮収支円'] - out['新規判断から約定の不利円'] - out['返済判断から約定の不利円'])) < 1e-6
    assert out['同時点中値分解一致'] and out['判断約定分解一致']
    out['新規待ち秒中央値'] = float(np.median([t['新規待ち秒'] for t in trades])) if trades else None
    out['返済待ち秒中央値'] = float(np.median([t['返済待ち秒'] for t in trades])) if trades else None
    out['新規直後の3呼値損切り幅到達数'] = sum(t['新規直後不利呼値'] >= 3 - 1e-8 for t in trades)
    out['負けのうち一度は費用後含み益'] = sum(t['収支円'] < 0 and t['MFE円'] > 0 for t in trades)
    out['同方向120秒以内再入口数'] = sum(t['同方向120秒以内再入口'] for t in trades)
    out['同方向120秒以内再入口収支'] = sum(t['収支円'] for t in trades if t['同方向120秒以内再入口'])
    out['負け直後120秒以内再入口数'] = sum(t['負け直後120秒以内再入口'] for t in trades)
    out['負け直後120秒以内再入口収支'] = sum(t['収支円'] for t in trades if t['負け直後120秒以内再入口'])
    out['同一確認状態の再入口数'] = sum(t['同一確認状態の再入口'] for t in trades)
    out['同一確認状態の再入口収支'] = sum(t['収支円'] for t in trades if t['同一確認状態の再入口'])
    return out


# ----------------------------------------
def examine(config, session, symbol, ledger, ready, books, signal):
    """
    機能: 一口座の全取引を、入口根拠・待機・保有経路へ分ける。
    引数: config/ledger/ready/books/signal (dict)、session/symbol (str)。
    返り値: list[dict] の各組診断。将来経路は事後説明にのみ使用する。
    """
    key = (session, symbol); r, b = ready[key], books[key]
    times, bid, ask = r['time_s'], b['bid'], b['ask']; mid = (bid + ask) / 2
    value = 1000. if symbol == 'TOPIX' else 10.
    finite = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid)
    known = np.maximum.accumulate(np.where(finite, np.arange(len(times)), -1))
    states = signal['states'][config['signal']]
    starts = np.zeros(len(states), np.int32)
    for i in range(1, len(states)):
        starts[i] = i if states[i] == 0 or states[i] != states[i-1] else starts[i-1]
    output = []
    for ti, row in enumerate(ledger['trades']):
        cid, ei, xi = map(int, row[:3]); d, quantity = int(row[3]), int(row[4]); scale = quantity * value
        orders = ledger['orders'][ledger['orders'][:,2] == cid]
        assert len(orders) == 2
        entry, exit_order = orders[orders[:,7] == 1][0], orders[orders[:,7] == 0][0]
        decision_e, decision_x = int(known[int(entry[1])]), int(known[int(exit_order[1])])
        assert min(decision_e, decision_x) >= 0
        q_e = ask[decision_e] if d == 1 else bid[decision_e]
        q_x = bid[decision_x] if d == 1 else ask[decision_x]
        g = int(np.searchsorted(signal['grid'], entry[15]))
        assert signal['grid'][g] == entry[15]
        path_quote = bid[ei:xi+1] if d == 1 else ask[ei:xi+1]
        fees = row[7] + row[8]
        path = d * (path_quote - row[5]) * scale - fees
        ok = finite[ei:xi+1]
        evidence = {}
        for label, s in (('self', symbol), ('peer', 'NK225' if symbol == 'TOPIX' else 'TOPIX')):
            j = int(signal['source_'+label][g]); rr, bb = ready[(session,s)], books[(session,s)]
            evidence[s] = dict(準備行=j, 原本seq=int(rr['seq'][j]), 代理時計=stamp(rr['time_s'][j]),
                               bid=float(bb['bid'][j]), ask=float(bb['ask'][j]), 買数量=float(bb['bid_qty'][j]), 売数量=float(bb['ask_qty'][j]),
                               F10=float(signal['flow_'+label+'10'][g]), R10呼値=float(signal['ret_'+label+'10'][g]),
                               R30呼値=float(signal['ret_'+label+'30'][g]), 実古さ秒=float(entry[10]-rr['time_s'][j]))
        previous = output[-1] if output else None
        elapsed = entry[10] - previous['返済秒'] if previous else np.inf
        same = bool(previous and d == previous['方向値'])
        result = dict(ID=f'{config["id"]}:{session}:{symbol}:{cid}', セッション=session, 商品=symbol, 組=cid,
                      方向値=d, 方向='買い' if d == 1 else '売り', 枚数=quantity,
                      新規判断=stamp(entry[10]), 新規到着予定=stamp(entry[11]), 新規約定=stamp(entry[12]),
                      返済判断=stamp(exit_order[10]), 返済到着予定=stamp(exit_order[11]), 返済約定=stamp(exit_order[12]),
                      新規価格=float(row[5]), 返済価格=float(row[6]), 返済理由=int(exit_order[6]),
                      収支円=float(row[10]), 手数料円=float(fees), 中値経路円=float(d*(mid[xi]-mid[ei])*scale),
                      新規対中値不利円=float(d*(row[5]-mid[ei])*scale), 返済対中値不利円=float(-d*(row[6]-mid[xi])*scale),
                      新規判断から約定の不利円=float(d*(row[5]-q_e)*scale), 返済判断から約定の不利円=float(-d*(row[6]-q_x)*scale),
                      判断気配の仮収支円=float(d*(q_x-q_e)*scale-fees),
                      新規直後不利呼値=float(-d*((bid[ei] if d == 1 else ask[ei])-row[5])/r['tick']),
                      新規待ち秒=float(entry[12]-entry[10]), 返済待ち秒=float(exit_order[12]-exit_order[10]),
                      保有秒=float(times[xi]-times[ei]), MFE円=float(np.max(path[ok])), MAE円=float(np.min(path[ok])),
                      同方向120秒以内再入口=bool(same and elapsed <= 120),
                      負け直後120秒以内再入口=bool(previous and elapsed <= 120 and previous['収支円'] < 0),
                      同一確認状態の再入口=bool(previous and same and int(starts[g]) == previous['状態開始格子']),
                      返済秒=float(exit_order[12]), 状態開始格子=int(starts[g]), 入口根拠=evidence,
                      原本時点={name:dict(準備行=j, 原本seq=int(r['seq'][j]), 代理時計=stamp(times[j]), bid=float(bid[j]), ask=float(ask[j]),
                                     買数量=float(b['bid_qty'][j]), 売数量=float(b['ask_qty'][j]))
                              for name,j in [('新規判断',int(entry[1])),('新規約定',ei),('返済判断参照',int(exit_order[1])),('返済約定',xi)]})
        output.append(result)
    return output


# ----------------------------------------
def verify_raw(examples, ready, books):
    """
    機能: 選んだ事後説明例の原本行の時計・最良気配・数量を照合する。
    引数: examples (list[dict])、ready/books (dict)。
    返り値: dict の原本抜出しと照合件数。全原本全行の特徴再計算ではない。
    """
    wanted = {}
    for trade in examples:
        for symbol, info in trade['入口根拠'].items(): wanted.setdefault((trade['セッション'],symbol),set()).add(info['原本seq'])
        for info in trade['原本時点'].values(): wanted.setdefault((trade['セッション'],trade['商品']),set()).add(info['原本seq'])
    output = {}; total = 0
    for key, positions in sorted(wanted.items()):
        session,symbol = key; path = ROOT / 'book' / symbol / (session+'.jsonl')
        r,b = ready[key],books[key]; lookup={int(seq):i for i,seq in enumerate(r['seq'])}; rows=[]
        with path.open('rb') as file:
            h=hashlib.sha256()
            for seq,line in enumerate(file):
                h.update(line)
                if seq not in positions: continue
                raw=json.loads(line);j=lookup[seq];bid=raw['Buy1'];ask=raw['Sell1']
                dt=datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()
                assert dt==r['time_s'][j]==b['time_s'][j]
                assert float(bid['Price'])==b['bid'][j] and float(ask['Price'])==b['ask'][j]
                assert float(bid['Qty'])==b['bid_qty'][j] and float(ask['Qty'])==b['ask_qty'][j]
                rows.append(dict(原本seq=seq, 時刻=raw['CurrentPriceTime'], Buy1=bid, Sell1=ask));total+=1
        HASHES[str(path.relative_to(ROOT))]=h.hexdigest()
        assert len(rows)==len(positions)
        output[session+'|'+symbol]=rows
    return dict(合格=True, 原本口座数=len(wanted), 独立照合行数=total, 原本抜出し=output,
                照合項目='CurrentPriceTime、最良bid/ask価格と数量を準備/特徴と比較。原本seqは対応のキー。',
                注意='表示数量の増減の原因が成行・取消・補充のどれかを断定しない。')


# ----------------------------------------
def main():
    """
    機能: 初回主3だけを前16場で診断し、全取引・悪い場・管理対照を保存する。
    引数: なし。
    返り値: None。diagnosis配下だけへ保存し、新再生や後14の損益は読まない。
    """
    HERE.mkdir(exist_ok=True)
    selection=load(BASE/'初回前半選定.json');fixed=load(BASE/'初回事前固定.json')
    sessions=fixed['前16'];allowed=set(sessions)
    meta=load(ROOT/'work/wave_v77/inputs/metadata.json');ready={};books={}
    for kind,target,extra in (('ready',ready,'extra_inputs.pkl'),('features',books,'extra_features.pkl')):
        for name in meta['input_paths'][kind]+['work/wave_v77/inputs/'+extra]:
            target.update({k:v for k,v in load(ROOT/name).items() if k[0] in allowed})
    signals={k:v for k,v in load(BASE/'prepared/signals.pkl').items() if k[0] in allowed}
    all_trades={};overview={};results={}
    for config in selection['代表']:
        ident=config['id'];result=load(BASE/'first/results'/f'{ident}.json');results[ident]=result
        ledgers=load(BASE/'first/ledgers'/f'{ident}.pkl');assert all(k[0] in allowed for k in ledgers)
        trades=[]
        for (session,symbol),ledger in ledgers.items():
            trades.extend(examine(config,session,symbol,ledger,ready,books,signals[(session,symbol)]))
        all_trades[ident]=trades;overview[ident]={}
        for symbol in ('TOPIX','NK225'):
            group=[t for t in trades if t['商品']==symbol];a=aggregate(group);saved=result['periods']['前16'][symbol]
            assert a['収支円']==saved['net'] and a['取引数']==saved['trades']
            assert abs(a['新規対中値不利円']+a['返済対中値不利円']-saved['spread_drag'])<1e-6
            assert abs(a['新規判断から約定の不利円']+a['返済判断から約定の不利円']-saved['decision_to_fill_cost'])<1e-6
            a['返済理由別']={str(reason):aggregate([t for t in group if t['返済理由']==reason]) for reason in sorted({t['返済理由'] for t in group})}
            a['注文要求数']=saved['entry_requests'];a['取消不成立数']=saved['cancellations']
            overview[ident][symbol]=a
    baseline=selection['代表'][0]['id'];examples=[];worst={}
    for symbol in ('TOPIX','NK225'):
        rows=sorted([r for r in results[baseline]['rows'] if r['symbol']==symbol],key=lambda v:v['net'])[:3]
        worst[symbol]=[]
        for row in rows:
            group=[t for t in all_trades[baseline] if t['商品']==symbol and t['セッション']==row['session']]
            examples.extend(sorted(group,key=lambda t:t['収支円'])[:2])
            wins=[t for t in group if t['収支円']>0]
            if wins:examples.append(wins[0])
            worst[symbol].append(dict(セッション=row['session'],会計=aggregate(group)))
    raw=verify_raw(examples,ready,books)
    profiles={}
    for p in range(1,7):
        ident=f'S3_P{p}_M0_C5';r=load(BASE/'first/results'/f'{ident}.json')
        profiles[ident]={'設定':r['config'],'前16':{s:{k:a[k] for k in ('net','trades','profit_share','payoff','gross','spread_drag','fees','average_hold_seconds')}
                                                  for s,a in r['periods']['前16'].items()}}
    output={'対象':'初回前半で固定した主3。後14の新損益・改修結果は未参照。','再生実施':False,
            '分解の注意':'中値経路−約定対中値の不利−手数料と、判断気配の仮収支−判断約定の不利は代替的な分解。遅延費用を中値分解へ再び引くと二重計上。中値で約定できるとの仮定ではない。',
            '待機指値の注意':'M2は反対気配が指値を1呼値通過した後に元指値で約定する保守的仮定。1呼値spreadなら新規直後の返済側まで最低2呼値不利。約定対中値不利には通常の半spreadだけでなくこの差も入り、全てを市場のスプレッドと呼ばない。',
            '主3の全取引集計':overview,'成行代表の赤字上位3場':worst,'説明用取引':examples,'原本照合':raw,
            '管理6対照':profiles,'保有120秒の推定':'P6は120秒だけでなく利確4呼値・損切り3呼値も同時に変わる。長く大きく待って固定費を薄めることが相対的優位の一因かもしれないが、保有時間単独の効果は識別できない。',
            '全取引':all_trades,'出典SHA256':HASHES}
    target=HERE/'初回主3の損失原因.json';target.write_text(json.dumps(clean(output),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(clean({'保存':str(target),'主3集計':overview,'原本照合行数':raw['独立照合行数']}),ensure_ascii=False))


if __name__=='__main__': main()
