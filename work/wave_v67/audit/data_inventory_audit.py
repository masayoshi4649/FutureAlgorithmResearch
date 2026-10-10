"""追加３場と旧25場の保存資料・契約・時計・最良気配を読み取りで独立検査する。"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
TZ=timezone(timedelta(hours=9))
NEW=('2026-10-07_Night','2026-10-08_Day','2026-10-08_Night')
SYMBOLS=('NK225','TOPIX')


def stamp_text(value):
    """機能: 保存約定時計を日本時間文字列に変換する。

    引数: value(float又はNone)。返り値: 日時文字列又はNone(str又はNone)。
    """
    return datetime.fromtimestamp(value,TZ).isoformat() if value is not None else None


def digest(path):
    """機能: 読み取り専用の原本又は既存キャッシュを分割ハッシュ計算する。

    引数: path(Path)。返り値: SHA256文字列(str)。
    """
    result=hashlib.sha256()
    with path.open('rb') as stream:
        while part:=stream.read(4*1024*1024):result.update(part)
    return result.hexdigest()


def bounds(session):
    """機能: 既存検証と同じ通常監視区間・早期返済期限を独立算出する。

    引数: session(str)。返り値: 開始・早期返済期限・排他的通常終端(tuple[float,float,float])。
    """
    date,kind=session.rsplit('_',1);day=datetime.fromisoformat(date).replace(tzinfo=TZ)
    start=day+timedelta(hours=8,minutes=45) if kind=='Day' else day+timedelta(hours=17)
    end=day+timedelta(hours=15,minutes=40) if kind=='Day' else day+timedelta(days=1,hours=5,minutes=55)
    return start.timestamp(),(end-timedelta(minutes=5)).timestamp(),end.timestamp()


def candle_audit(path,expected,seconds,start,end):
    """機能: 保存足の順序・区間・確定状態と原板最終価格から再構成したOHLCを検査する。

    引数: path(Path)、expected(dict)、seconds(int)、start/end(float)。返り値: 足監査(dict)。
    """
    rows=list(csv.DictReader(path.open(encoding='utf-8-sig')));mismatches=[];seen=[]
    missing_price=invalid_price=unclosed=volume_incomplete=0
    for row in rows:
        t=datetime.fromisoformat(row['time']).timestamp();bucket=int(t//seconds);seen.append(bucket)
        actual=[float(row[n]) for n in ('open','high','low','close')]
        invalid_price+=int(not all(math.isfinite(x) and x>0 for x in actual) or actual[2]>min(actual[0],actual[3]) or actual[1]<max(actual[0],actual[3]))
        assert start<=t<end and t%seconds==0,(path,row)
        unclosed+=row['closed'].lower()!='true';volume_incomplete+=row['volume_complete'].lower()!='true'
        if bucket not in expected:missing_price+=1;continue
        if actual!=expected[bucket]:mismatches.append(dict(time=row['time'],保存OHLC=actual,原板OHLC=expected[bucket]))
    assert all(a<b for a,b in zip(seen,seen[1:])),path
    return dict(ファイル=str(path.relative_to(ROOT)),SHA256=digest(path),行数=len(rows),最初=rows[0]['time'] if rows else None,
        最後=rows[-1]['time'] if rows else None,未確定数=unclosed,出来高不完全数=volume_incomplete,価格不正数=invalid_price,
        原板OHLC不一致数=len(mismatches),不一致標本=mismatches[:5],原板に存在しない保存足数=missing_price,
        保存足に存在しない原板足数=len(set(expected)-set(seen)))


def inspect_new(key):
    """機能: 一つの追加原本を全行読み、契約・約定時計・最良気配・足価格を独立監査する。

    引数: key(tuple[str,str])。返り値: 原本と足の監査(dict)。キャッシュは作成しない。
    """
    session,symbol=key;start,limit,end=bounds(session);tick=10. if symbol=='NK225' else .5
    path=ROOT/'book'/symbol/(session+'.jsonl');initial_stat=path.stat();hashing=hashlib.sha256()
    counters=Counter();contracts=Counter();names=Counter();types=Counter();exchanges=Counter();spreads=[]
    valid_times=[];valid_seqs=[];gaps=[];example_bad=[];bars={60:{},300:{}}
    previous_text=None;previous_stamp=None;first_stamp=None;last_stamp=None;last_raw=None;previous_quote=None
    min_volume=None;last_volume=None;depth_invalid=0
    with path.open('rb') as stream:
        for seq,line in enumerate(stream):
            hashing.update(line);counters['原本行数']+=1
            raw=json.loads(line);last_raw=raw
            contracts[str(raw.get('Symbol'))]+=1;names[str(raw.get('SymbolName'))]+=1
            types[str(raw.get('SecurityType'))]+=1;exchanges[str(raw.get('Exchange'))]+=1
            text=raw.get('CurrentPriceTime')
            if text is None or text=='':counters['時計欠測']+=1;continue
            if text==previous_text:t=previous_stamp;counters['同約定時計の後続原板行']+=1
            else:
                parsed=datetime.fromisoformat(text)
                if parsed.tzinfo is None:counters['時差欠測']+=1
                t=parsed.timestamp()
                if previous_stamp is not None and t<previous_stamp:counters['約定時計逆行']+=1
            previous_text,previous_stamp=text,t
            if first_stamp is None:first_stamp=t
            last_stamp=t
            if not start<=t<end:
                counters['場外時計']+=1
                counters['開始前時計' if t<start else '終端以降時計']+=1;continue
            counters['場内時計行数']+=1
            current=raw.get('CurrentPrice')
            if isinstance(current,(int,float)) and math.isfinite(current) and current>0:
                for seconds,expected in bars.items():
                    bucket=int(t//seconds)
                    if bucket not in expected:expected[bucket]=[float(current)]*4
                    else:
                        b=expected[bucket];b[1]=max(b[1],current);b[2]=min(b[2],current);b[3]=float(current)
            else:counters['場内最終価格不正']+=1
            try:
                bid,ask,bq,aq=[float(x) for x in (raw['Buy1']['Price'],raw['Sell1']['Price'],raw['Buy1']['Qty'],raw['Sell1']['Qty'])]
            except (KeyError,TypeError,ValueError):counters['最良値欠測']+=1;continue
            if not all(math.isfinite(x) for x in (bid,ask,bq,aq)) or min(bid,ask)<=0:
                counters['最良値不正']+=1;continue
            if bid==ask:counters['売買同値']+=1;continue
            if bid>ask:counters['売買逆転']+=1;continue
            if min(bq,aq)<=0:counters['最良数量不正']+=1;continue
            counters['有効入力行数']+=1;valid_seqs.append(seq);valid_times.append(t);spreads.append((ask-bid)/tick)
            counters['最良気配呼値外']+=int(abs(bid/tick-round(bid/tick))>1e-8 or abs(ask/tick-round(ask/tick))>1e-8)
            if previous_quote is not None and previous_quote[0]==t and previous_quote[1:]!=(bid,ask,bq,aq):counters['同時計で最良気配数量が更新']+=1
            previous_quote=(t,bid,ask,bq,aq)
            counters['API名BidPriceがSell1と一致']+=raw.get('BidPrice')==ask
            counters['API名AskPriceがBuy1と一致']+=raw.get('AskPrice')==bid
            volume=raw.get('TradingVolume')
            if isinstance(volume,(int,float)) and math.isfinite(volume):
                if last_volume is not None and volume<last_volume:counters['場内累積出来高逆行']+=1
                if min_volume is None:min_volume=volume
                last_volume=volume
            try:
                buy=[(float(raw[f'Buy{i}']['Price']),float(raw[f'Buy{i}']['Qty'])) for i in range(1,11)]
                sell=[(float(raw[f'Sell{i}']['Price']),float(raw[f'Sell{i}']['Qty'])) for i in range(1,11)]
                correct=all(p>0 and q>0 and math.isfinite(p+q) for p,q in buy+sell)
                correct=correct and all(buy[i][0]>buy[i+1][0] for i in range(9)) and all(sell[i][0]<sell[i+1][0] for i in range(9))
            except (KeyError,TypeError,ValueError):correct=False
            depth_invalid+=not correct
    final_stat=path.stat();assert initial_stat.st_size==final_stat.st_size and initial_stat.st_mtime_ns==final_stat.st_mtime_ns,path
    times=np.asarray(valid_times);seqs=np.asarray(valid_seqs);spr=np.asarray(spreads)
    assert len(times)>0 and np.all(np.diff(seqs)>0)
    changes=np.diff(times);largest=np.argsort(changes)[-5:][::-1]
    for i in largest:gaps.append(dict(秒=float(changes[i]),開始=stamp_text(times[i]),終了=stamp_text(times[i+1]),開始seq=int(seqs[i]),終了seq=int(seqs[i+1])))
    assert np.all(changes>=0) and counters['約定時計逆行']==0,(key,counters)
    assert set(contracts)==({'161120018'} if symbol=='NK225' else {'161120005'})
    assert set(names)==({'日経平均先物 26/12'} if symbol=='NK225' else {'TOPIX先物 26/12'})
    for field in ('時計欠測','場外時計','最良値欠測','最良値不正','売買同値','売買逆転','最良数量不正','有効入力行数'):counters[field]+=0
    assert counters['時計欠測']+counters['場外時計']+sum(counters[k] for k in ('最良値欠測','最良値不正','売買同値','売買逆転','最良数量不正','有効入力行数'))==counters['原本行数']
    report=dict(セッション=session,銘柄=symbol,原本=str(path.relative_to(ROOT)),原本SHA256=hashing.hexdigest(),原本サイズ=initial_stat.st_size,
        契約ID=dict(contracts),銘柄名=dict(names),商品種別=dict(types),市場=dict(exchanges),品質=dict(counters),
        原本最初の非欠測時計=stamp_text(first_stamp),原本末尾時計=last_raw.get('CurrentPriceTime'),原本末尾出来高時計=last_raw.get('TradingVolumeTime'),
        有効先頭seq=int(seqs[0]),有効末尾seq=int(seqs[-1]),有効最初時計=stamp_text(times[0]),有効最終時計=stamp_text(times[-1]),
        場開始=stamp_text(start),早期返済期限=stamp_text(limit),通常終端=stamp_text(end),早期返済期限後の有効行数=int(sum(times>=limit)),
        終端60秒内の有効行数=int(sum(times>=end-60)),最終時計から通常終端まで秒=float(end-times[-1]),最大有効時計空白=gaps,
        気配差呼値=dict(中央値=float(np.median(spr)),最大=float(spr.max()),複数呼値数=int(sum(spr>1)),五呼値超数=int(sum(spr>5))),
        有効行の不完全10段数=depth_invalid,場内累積出来高先頭=min_volume,場内累積出来高末尾=last_volume,
        足=[candle_audit(ROOT/kind/symbol/(session+'.csv'),bars[seconds],seconds,start,end) for kind,seconds in (('candle_1min',60),('candle_5min',300))])
    print(session,symbol,'有効',len(times),'最終',report['有効最終時計'],flush=True)
    return report


def main():
    """機能: ファイル一覧、新３場全文、旧50原本ハッシュとキャッシュ整合を検査して保存する。

    引数: なし。返り値: なし(None)。全原本・過去成果は読み取り専用。
    """
    HERE.mkdir(parents=True,exist_ok=True)
    cache=pickle.loads((ROOT/'work/wave_v60/inputs.pkl').read_bytes());quotes=pickle.loads((ROOT/'work/wave_v60/quotes.pkl').read_bytes())
    old_keys=set(cache);assert len(old_keys)==50 and set(quotes)==old_keys
    inventory=[]
    for symbol in SYMBOLS:
        groups={kind:{p.stem for p in (ROOT/kind/symbol).glob('*'+extension)} for kind,extension in (('book','.jsonl'),('candle_1min','.csv'),('candle_5min','.csv'))}
        assert groups['book']==groups['candle_1min']==groups['candle_5min']
        new_sessions=groups['book']-{k[0] for k in old_keys if k[1]==symbol}
        assert new_sessions==set(NEW),(symbol,new_sessions)
        inventory.append(dict(銘柄=symbol,各形式件数={k:len(v) for k,v in groups.items()},全一覧一致=True,セッション一覧=sorted(groups['book']),追加セッション=sorted(new_sessions)))
    baseline=json.loads((ROOT/'work/wave_v57/特徴監査.json').read_text(encoding='utf-8'))['原本別']
    later=json.loads((ROOT/'work/wave_v59/holdout/未読2場の入力抽出監査.json').read_text(encoding='utf-8'))['新2場の原本監査']
    expected={(r['セッション'],r['銘柄']):r['原本SHA256'] for r in baseline+later};assert set(expected)==old_keys
    old_details=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes=list(pool.map(digest,[ROOT/'book'/sy/(se+'.jsonl') for se,sy in sorted(old_keys)]))
    for key,sha in zip(sorted(old_keys),hashes):
        assert sha==expected[key],key
        ready,q=cache[key],quotes[key];start,limit,end=bounds(key[0])
        assert ready['start']==start and ready['limit']==limit
        np.testing.assert_array_equal(ready['seq'],q['seq']);np.testing.assert_array_equal(ready['time_s'],q['time_s'])
        assert np.all(np.diff(ready['seq'])>0) and np.all(np.diff(ready['time_s'])>=0)
        assert np.all(q['ask']>q['bid']) and np.all(q['mid']==(q['ask']+q['bid'])/2)
        assert start<=ready['time_s'][0]<ready['time_s'][-1]<end and ready['time_s'][-1]>limit
        old_details.append(dict(セッション=key[0],銘柄=key[1],原本SHA256=sha,一致=True,有効行数=len(ready['seq']),最後=stamp_text(ready['time_s'][-1])))
    with ThreadPoolExecutor(max_workers=3) as pool:new_details=list(pool.map(inspect_new,[(se,sy) for se in NEW for sy in SYMBOLS]))
    report=dict(結論='NK/TOP各28場で原板・1分足・5分足の一覧一致。旧25場の原本SHAと共通キャッシュは不変。新3場は同契約で早期返済期限と通常終端直前まで収録。',
        対象セッション数=28,口座数=56,一覧=inventory,旧50原本一致=True,旧キャッシュ有効行数=sum(len(r['seq']) for r in cache.values()),
        旧キャッシュSHA={name:digest(ROOT/'work/wave_v60'/name) for name in ('inputs.pkl','quotes.pkl')},旧原本=old_details,追加原本=new_details,
        連結可能=True,連結条件=['旧25場と新3場をセッション・銘柄キーで追加する。seqは各原本の0始まり行番号で、全期間の一意番号ではない。',
        'Night先頭のDay時計など開始前観測を除外し、Buy1を買い気配bid、Sell1を売り気配askとして抽出する。',
        '時刻欠測、売買同値、逆転、数量不正を除き、原本seq順を保つ。同時計行を一つの最後の板にまとめない。',
        '当場検証では特徴・建玉を場ごとに初期化する。全価格配列をそのまま跨いで移動窓へ渡さない。'],
        注意=['CurrentPriceTimeは最終約定時計であり受信時計ではない。原本行順は保持できても受信間隔と通信停止時間は復元できない。',
        '10/8Nightは保存の通常監視区間17:00〜翌05:55の終端直前まであり、05:50返済期限を超える。６時の引け・受信完了までを証明する資料は含まない。',
        '保存OHLCは最終約定価格、気配キャッシュはbid/askの中値。足価格と中値特徴を同じものとして扱わない。',
        'ラージ板の価格をmini/micro約定へ代理する制約は残る。契約確認は同限月を意味し、mini/micro実気配の一致を保証しない。'],
        コードSHA256=digest(Path(__file__)),現在API取得数=0,売買結果参照数=0,原本書込数=0)
    (HERE/'追加3場のデータと旧キャッシュの独立監査.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('結論','対象セッション数','口座数','旧50原本一致','旧キャッシュ有効行数','連結可能')},ensure_ascii=False))


if __name__=='__main__':main()
