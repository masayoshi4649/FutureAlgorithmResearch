"""凍結済み入力の価格・最良気配・深板・時計を分離して診断し、売買は再実行しない。"""

from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import pickle
import re
import sys
from zoneinfo import ZoneInfo

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0,str(WORK))
import data

CLOCK_KEYS = re.compile(rb'"([^"\r\n]*(?:Time|time|Date|date|Stamp|stamp|Receiv|receiv|Receipt|receipt|Recv|recv|Update|update|Epoch|epoch|_at|At|Seq|seq)[^"\r\n]*)"\s*:')
RESET_LABELS = {1:'前比較板なし',2:'抽出済み原本行の不連続',4:'完全10段不正',8:'価格代理時計逆行',16:'累積出来高減少'}


def read(path):
    """
    機能: 既存入力又はC11の確定新規判断だけを読み取る。
    引数: path(Path)。
    返り値: object。ファイル変更や売買計算はしない。
    """
    if path.suffix=='.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: 診断に用いた保存内容の指紋を取得する。
    引数: path(Path)。
    返り値: str、SHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):
            value.update(block)
    return value.hexdigest()


def stamp(value):
    """
    機能: 欠測や不正な時計を新しい時刻へ置換せず識別する。
    引数: value(object)。
    返り値: float | None、Unix秒。
    """
    if not isinstance(value,str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.timestamp() if result.tzinfo is not None else None
    except ValueError:
        return None


def iso(value):
    """
    機能: 有限代理時計を日本時間へ表示する。
    引数: value(float | None)。
    返り値: str | None。
    """
    return datetime.fromtimestamp(value,ZoneInfo('Asia/Tokyo')).isoformat() if value is not None and math.isfinite(value) else None


def finite(value):
    """
    機能: 価格・数量の欠測を有限値と区別する。
    引数: value(object)。
    返り値: float | None。
    """
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError,TypeError):
        return None


def board_check(raw):
    """
    機能: LastPriceとは別に、最良気配と両側10段の有効性を原本から独立判定する。
    引数: raw(dict)。
    返り値: tuple、最良正常(bool)、深板正常(bool)、不正根拠(list[dict])、価格数量4値、分類(dict)。
    """
    bid,ask = raw.get('Buy1') or {},raw.get('Sell1') or {}
    b,a,bq,aq = (finite(bid.get('Price')),finite(ask.get('Price')),finite(bid.get('Qty')),finite(ask.get('Qty')))
    price_ok = b is not None and a is not None and 0<b<a
    qty_ok = bq is not None and aq is not None and bq>0 and aq>0
    best = price_ok and qty_ok
    errors = []
    deep_price = deep_qty = True
    for side in ('Buy','Sell'):
        previous = None
        for level in range(1,11):
            item = raw.get(f'{side}{level}') or {}
            price,qty = finite(item.get('Price')),finite(item.get('Qty'))
            if price is None or price<=0:
                deep_price = False
                errors.append(dict(段=f'{side}{level}',理由='価格欠測又は非正',価格=price,数量=qty))
            if qty is None or qty<0:
                deep_qty = False
                errors.append(dict(段=f'{side}{level}',理由='数量欠測又は負',価格=price,数量=qty))
            if price is None or price<=0:
                continue
            if previous is not None and (price>=previous if side=='Buy' else price<=previous):
                errors.append(dict(段=f'{side}{level}',理由='価格順序又は同価格重複',前価格=previous,価格=price,数量=qty))
                deep_price = False
            previous = price
    taxonomy = dict(最良価格欠測又は非正=b is None or a is None or b<=0 or a<=0,
                    最良ロック=b is not None and a is not None and b>0 and b==a,
                    最良交差=b is not None and a is not None and b>0 and a>0 and b>a,
                    最良数量不正=not qty_ok,最良価格正常で数量だけ不正=price_ok and not qty_ok,
                    最良正常で遠方価格順だけ不正=best and not deep_price and deep_qty,
                    最良正常で遠方数量だけ不正=best and deep_price and not deep_qty,
                    最良正常で遠方価格数量とも不正=best and not deep_price and not deep_qty)
    return bool(best),bool(best and deep_price and deep_qty),errors,(b,a,bq,aq),taxonomy


def old_flags(material):
    """
    機能: 旧深板validとreset理由を読取し、最小price列と既存resetへ照合する。
    引数: material(dict)。
    返り値: tuple[dict,list[Path]]、62口座中旧60の理由列と参照資料。
    """
    paths = [ROOT/'work/wave_v69/prepared/features.pkl',ROOT/'work/wave_v71/prepared/extra_features.pkl',
             ROOT/'work/wave_v77/inputs/extra_features.pkl']
    result = {}
    for path in paths:
        values = read(path)
        for key,record in values.items():
            assert key not in result
            np.testing.assert_array_equal(record['seq'],material['prices'][key]['seq'])
            np.testing.assert_array_equal(record['reset'],material['features'][key]['reset'])
            result[key] = dict(valid=record['valid'],reset_reason=record['reset_reason'])
        del values
    assert len(result)==60
    return result,paths


def endpoint(record,feature,target):
    """
    機能: 旧端点の失敗理由を、最新時計の先頭・30秒鮮度・品質・resetで別々に説明する。
    引数: record/feature(dict)、target(float)。
    返り値: dict、候補と採否の理由。後続同時計行へ救済しない。
    """
    times = record['time_s']
    previous = int(np.searchsorted(times,target,side='left')-1)
    if previous<0:
        return dict(候補行=None,理由=['前観測なし'],有効=False)
    row = int(np.searchsorted(times,times[previous],side='left'))
    reasons = []
    if target-times[row]>30:
        reasons.append('最終約定代理時計が30秒超古い')
    if not feature['quality'][row]:
        reasons.append('深板又は気配差を含む旧quality不合格')
    if feature['reset'][row]:
        reasons.append('板フロー用reset行')
    return dict(候補行=row,原本seq=int(record['seq'][row]),価格時計=iso(float(times[row])),
                鮮度秒=float(target-times[row]),理由=reasons,有効=not reasons)


def accepted_cases(material,flags):
    """
    機能: C11全17新規の当時最新公開格子と、両市場の長窓不明理由を独立に取り出す。
    引数: material/flags(dict)。
    返り値: tuple、ケース(list[dict])と原本照合対象seq(dict)。利益や損失は読まない。
    """
    cases,wanted = [],{}
    for stage in ('front','back'):
        path = WORK/stage/'ledgers/C11.pkl'
        for key,ledger in sorted(read(path).items()):
            record = material['prices'][key]
            grids = material['grids'][key[0]]
            mapped = np.full(len(record['time_s']),-1,np.int32)
            for g,time_value in enumerate(grids['grid']):
                row = int(np.searchsorted(record['time_s'],time_value,side='left'))
                if row<len(mapped) and record['time_s'][row]-time_value<=10:
                    mapped[row]=g
            published = np.maximum.accumulate(mapped)
            for order in np.asarray(ledger['orders'],float):
                if not order[7]:
                    continue
                decision = int(order[1])
                g = int(published[decision])
                assert g>=0
                at = float(grids['grid'][g])
                case = dict(場=key[0],取引商品=key[1],判断行=decision,判断原本seq=int(record['seq'][decision]),
                            判断時計=iso(float(record['time_s'][decision])),公開格子=iso(at),格子番号=g,
                            売買='買い' if order[4]==1 else '売り',市場={})
                for symbol in ('TOPIX','NK225'):
                    market = grids['markets'][symbol]
                    observed = material['prices'][key[0],symbol]
                    feature = material['features'][key[0],symbol]
                    frame = flags[key[0],symbol]
                    broken = ~frame['valid']|feature['reset']
                    current = endpoint(observed,feature,at-1.)
                    assert (current['候補行'] if current['有効'] else -1)==int(market['current']['index'][g])
                    source = dict(現在端点=current,窓={})
                    for window in (30,60,180,300):
                        value = market['windows'][window]
                        old = endpoint(observed,feature,at-1.-window)
                        assert (old['候補行'] if old['有効'] else -1)==int(value['old'][g])
                        lo,hi = int(value['old'][g]),int(value['now'][g])
                        bad = np.flatnonzero(broken[lo+1:hi+1])+lo+1 if lo>=0 and hi>=0 else np.array([],int)
                        bits = {name:int(((frame['reset_reason'][bad]&bit)!=0).sum()) for bit,name in RESET_LABELS.items()}
                        evidence = dict(旧端点=old,現在行=hi,旧行=lo,源有効=bool(value['source_valid'][g]),
                                        同一行=bool(value['same_row'][g]),板reset又はinvalid横断=bool(value['reset_or_invalid_cross'][g]),
                                        ER=float(value['efficiency'][g]) if np.isfinite(value['efficiency'][g]) else None,
                                        横断不正行数=len(bad),横断理由=bits)
                        if hi>=0:
                            failures = np.flatnonzero(broken[:hi+1])
                            start = int(failures[-1]+1) if len(failures) else 0
                            evidence['旧板連続正常区間秒'] = float(observed['time_s'][hi]-observed['time_s'][start]) if start<=hi else 0.
                            evidence['旧板連続正常区間行数'] = max(0,hi-start+1)
                        selected = np.unique(np.r_[bad[:2],bad[-2:]])
                        seqs = [int(observed['seq'][i]) for i in selected]
                        evidence['横断原本例seq'] = seqs
                        target = wanted.setdefault((key[0],symbol),set())
                        target.update(seqs)
                        if old['候補行'] is not None:
                            target.add(old['原本seq'])
                        if current['候補行'] is not None:
                            target.add(current['原本seq'])
                        source['窓'][str(window)] = evidence
                    case['市場'][symbol]=source
                wanted.setdefault(key,set()).add(case['判断原本seq'])
                cases.append(case)
    assert len(cases)==17
    return cases,wanted


def raw_scan(key,record,expected,wanted):
    """
    機能: 対象原本全行の時計keyと価格/最良/深板状態を走査し、旧board resetを独立再構成する。
    引数: key(tuple[str,str])、record(dict)、expected(dict|None)、wanted(set[int])。
    返り値: tuple、短期価格窓用の原観測配列、診断辞書、再構成深板旗(dict)。原本は変更しない。
    """
    path = ROOT/'book'/key[1]/f'{key[0]}.jsonl'
    columns = {name:[] for name in ('time','seq','last','mid','last_ok','quote_ok','depth_ok','clock_gap',
                                   'quote_price_error','quote_qty_error')}
    raw_count = Counter()
    keys = set()
    root_keys = set()
    samples = {}
    duplicate_examples = []
    same_clock_quote = same_clock_qty = same_clock_quote_all_clock_same = 0
    volume_clock_newer = 0
    ptr,prev_seq,prev_time,prev_valid,prev_volume = 0,None,None,False,None
    rebuilt_valid = np.zeros(len(record['seq']),bool)
    rebuilt_reason = np.zeros(len(record['seq']),np.uint8)
    prior_raw = None
    dropped = Counter()
    dropped_examples = []
    all_filtered_causes = Counter()
    current_cache = {}
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for seq,line in enumerate(stream):
            raw_count['全原本行']+=1
            h.update(line)
            keys.update(m.group(1).decode('utf-8') for m in CLOCK_KEYS.finditer(line))
            raw = json.loads(line)
            root_keys.update(raw.keys())
            text = raw.get('CurrentPriceTime')
            if text not in current_cache:
                current_cache[text]=stamp(text)
            t = current_cache[text]
            if t is None:
                raw_count['価格時計欠測又は不正']+=1
                if prev_seq is not None:
                    dropped['時計欠測又は不正']+=1
                    if len(dropped_examples)<3:
                        dropped_examples.append(dict(seq=seq,CurrentPriceTime=text,CurrentPrice=raw.get('CurrentPrice'),理由=['時計欠測又は不正']))
                continue
            if not record['start']<=t<record['end']:
                raw_count['観測場外']+=1
                continue
            raw_count['観測場内行']+=1
            last = finite(raw.get('CurrentPrice'))
            last_ok = last is not None and last>0
            best,depth,errors,quote,taxonomy = board_check(raw)
            b,a,bq,aq = quote
            mid = .5*(b+a) if best else np.nan
            raw_count['LastPrice不正']+=not last_ok
            raw_count['最良気配不正']+=not best
            raw_count['LastPrice正常で最良不正']+=last_ok and not best
            raw_count['LastPrice最良正常で10段不正']+=last_ok and best and not depth
            for label,flag in taxonomy.items():
                raw_count[label]+=bool(flag)
            raw_count['wrapper又はroot辞書外']+=not isinstance(raw,dict)
            all_clocks = {name:raw.get(name) for name in ('CurrentPriceTime','TradingVolumeTime','OpeningPriceTime','HighPriceTime','LowPriceTime','PreviousCloseTime')}
            if prior_raw is not None:
                old_t,old_quote,old_clocks,old_seq = prior_raw
                changed_quote = quote[:2]!=old_quote[:2]
                changed_qty = quote[2:]!=old_quote[2:]
                same = t==old_t
                same_clock_quote += same and changed_quote
                same_clock_qty += same and changed_qty
                all_same = all_clocks==old_clocks
                same_clock_quote_all_clock_same += same and changed_quote and all_same
                if same and changed_quote and all_same and len(duplicate_examples)<2:
                    duplicate_examples.append(dict(前seq=old_seq,現在seq=seq,全時計不変=all_clocks,
                                                   前BuySell価格数量=list(old_quote),現在BuySell価格数量=list(quote)))
            volume_t = stamp(raw.get('TradingVolumeTime'))
            volume_clock_newer += volume_t is not None and volume_t>t
            gap = prior_raw is not None and seq!=prior_raw[3]+1
            columns['time'].append(t);columns['seq'].append(seq)
            columns['last'].append(last if last_ok else np.nan);columns['mid'].append(mid)
            columns['last_ok'].append(last_ok);columns['quote_ok'].append(best);columns['depth_ok'].append(depth)
            columns['clock_gap'].append(gap)
            columns['quote_price_error'].append(any(taxonomy[k] for k in ('最良価格欠測又は非正','最良ロック','最良交差')))
            columns['quote_qty_error'].append(taxonomy['最良数量不正'])
            prior_raw = (t,quote,all_clocks,seq)
            selected = ptr<len(record['seq']) and seq==record['seq'][ptr]
            if not selected and prev_seq is not None:
                dropped['除外原本行']+=1
                dropped['LastPrice不正']+=not last_ok
                for label,flag in taxonomy.items():
                    dropped[label]+=bool(flag)
                if last_ok and best:
                    dropped['LastPrice最良正常なのに旧抽出不採用']+=1
                if len(dropped_examples)<3:
                    dropped_examples.append(dict(seq=seq,CurrentPriceTime=text,CurrentPrice=last,
                                                 Buy1=raw.get('Buy1'),Sell1=raw.get('Sell1'),
                                                 理由=[k for k,v in taxonomy.items() if v]+(['LastPrice不正'] if not last_ok else [])))
            if selected:
                reason = 1 if not prev_valid else 0
                if prev_seq is not None and seq!=prev_seq+1:reason|=2
                if not depth:reason|=4
                if prev_time is not None and t<prev_time:reason|=8
                volume = finite(raw.get('TradingVolume'))
                if volume is not None and volume<0:volume=None
                if prev_valid and prev_volume is not None and volume is not None and volume<prev_volume:reason|=16
                rebuilt_valid[ptr],rebuilt_reason[ptr] = depth,reason
                assert t==record['time_s'][ptr] and last==record['price'][ptr]
                assert b==record['bid'][ptr] and a==record['ask'][ptr]
                if seq in wanted:
                    samples[str(seq)] = dict(原本seq=seq,価格時計=text,LastPrice=last,Buy1=raw.get('Buy1'),Sell1=raw.get('Sell1'),
                                            最良正常=best,深板正常=depth,深板不正根拠=errors,独立reset理由=reason,
                                            reset理由名=[name for bit,name in RESET_LABELS.items() if reason&bit],
                                            TradingVolume=volume,前正常板出来高=prev_volume if prev_valid else None,
                                            全時計=all_clocks,前抽出seq=prev_seq,前価格時計=iso(prev_time),
                                            前抽出との間の除外原行=dict(dropped),除外原行例=dropped_examples,
                                            原価格と数量の分類=taxonomy)
                if reason&2:
                    all_filtered_causes.update(dropped)
                dropped = Counter()
                dropped_examples = []
                prev_seq,prev_time,prev_valid,prev_volume = seq,t,depth,volume
                ptr+=1
    assert ptr==len(record['seq'])
    if expected is not None:
        np.testing.assert_array_equal(rebuilt_valid,expected['valid'])
        np.testing.assert_array_equal(rebuilt_reason,expected['reset_reason'])
    assert set(wanted).issubset({int(s) for s in samples}), (key,set(wanted)-{int(s) for s in samples})
    arrays = {name:np.asarray(values,dtype=bool if name.endswith(('_ok','_error')) or name=='clock_gap' else np.int64 if name=='seq' else float)
              for name,values in columns.items()}
    info = dict(場=key[0],商品=key[1],原本SHA256=h.hexdigest(),原本統計=dict(raw_count),全原本時計key=sorted(keys),
                全原本root_key=sorted(root_keys),旧seqgapを作った除外原行の分類=dict(all_filtered_causes),
                同価格時計中の最良価格変化=int(same_clock_quote),同価格時計中の最良数量変化=int(same_clock_qty),
                全6時計不変で最良価格変化=int(same_clock_quote_all_clock_same),
                TradingVolumeTimeが価格時計より新しい行=int(volume_clock_newer),時計不足の具体例=duplicate_examples,
                原本照合例=samples,旧板valid及びreset全行一致=expected is not None,
                価格時計逆行=int((np.diff(arrays['time'])<0).sum()))
    print(f'{key[0]} {key[1]} 原本時計・LastPrice・最良・深板の独立診断 {raw_count["全原本行"]}行',flush=True)
    return arrays,info,dict(valid=rebuilt_valid,reset_reason=rebuilt_reason)


def invalid_runs(mask,times):
    """
    機能: 一時不正区間を原本行数と約定代理時計幅で測定し、実受信経過時間と区別する。
    引数: mask(bool配列)、times(float配列)。
    返り値: dict、区間数・行数・代理時計秒数の要約。
    """
    starts = np.flatnonzero(mask&~np.r_[False,mask[:-1]])
    ends = np.flatnonzero(mask&~np.r_[mask[1:],False])+1
    assert len(starts)==len(ends)
    lengths = ends-starts
    durations = times[ends-1]-times[starts]
    return dict(区間数=len(starts),最大連続行数=int(lengths.max(initial=0)),
                中央連続行数=float(np.median(lengths)) if len(lengths) else None,
                最大代理時計幅秒=float(durations.max(initial=0)),代理時計幅0秒区間数=int((durations==0).sum()),
                代理時計幅合計秒=float(durations.sum()))


def raw_window(arrays,target,seconds,channel):
    """
    機能: 原本の同価格時計先頭だけで、LastPrice又は最良中値の短窓可用性を別々に測定する。
    引数: arrays(dict[str,ndarray])、target/seconds(float)、channel(str:last/mid)。
    返り値: dict。未来の同時計後続、深板品質又は出来高resetを価格へ混ぜない。
    """
    times = arrays['time']
    if not len(times) or (np.diff(times)<0).any():
        return dict(源有効=False,理由=['代理時計不連続で別処理が必要'],ER=None)
    first = np.flatnonzero(np.r_[True,np.diff(times)!=0])
    flags = arrays['last_ok'] if channel=='last' else arrays['quote_ok']
    endpoint_rows = []
    reasons = []
    for name,at in (('現在',target),('旧',target-seconds)):
        p = int(np.searchsorted(times,at,side='left')-1)
        if p<0:
            endpoint_rows.append(-1);reasons.append(name+'前観測なし');continue
        row = int(np.searchsorted(times,times[p],side='left'))
        endpoint_rows.append(row)
        if at-times[row]>30:reasons.append(name+'代理時計30秒超古い')
        if not flags[row]:reasons.append(name+'当該価格源不正')
    now,old = endpoint_rows
    if now<0 or old<0:
        return dict(源有効=False,理由=reasons,ER=None)
    broken = (~flags)|arrays['clock_gap']
    crossed = int(broken[old+1:now+1].sum())
    if old==now:reasons.append('同一原観測')
    if crossed:reasons.append('価格値又は時計の不明を横断')
    valid = not reasons
    prices = arrays[channel][first]
    delta = np.abs(np.diff(prices))
    delta[~np.isfinite(delta)] = 0
    tv = np.r_[0.,np.cumsum(delta)]
    old_p,now_p = np.searchsorted(first,[old,now])
    variation = float(tv[now_p]-tv[old_p])
    displacement = float(arrays[channel][now]-arrays[channel][old])
    efficiency = abs(displacement)/variation if valid and variation>0 else None
    last_bad = np.flatnonzero(broken[:now+1])
    start = int(last_bad[-1]+1) if len(last_bad) else 0
    gaps = np.diff(times[old:now+1])
    return dict(源有効=valid,理由=reasons,ER=efficiency,総変動=variation if valid else None,
                変位=displacement if valid else None,現在原本seq=int(arrays['seq'][now]),旧原本seq=int(arrays['seq'][old]),
                現在価格時計=iso(float(times[now])),旧価格時計=iso(float(times[old])),
                実区間秒=float(times[now]-times[old]),同時計先頭数=int(now_p-old_p+1),
                横断不明行数=crossed,窓内代理時計30秒超間隔=int((gaps>30).sum()),
                最良価格不正横断行=int(arrays['quote_price_error'][old+1:now+1].sum()),
                最良数量不正横断行=int(arrays['quote_qty_error'][old+1:now+1].sum()),
                原行時計不明等のseqgap横断行=int(arrays['clock_gap'][old+1:now+1].sum()),
                最後の当該価格連続正常区間秒=float(times[now]-times[start]) if start<=now else 0.)


def summary(material,flags):
    """
    機能: 全62抽出口座の価格・気配・深板・reset・代理時計間隔を商品別に集計する。
    引数: material/flags(dict)。
    返り値: list[dict]、各場の入力診断。長い価格時計間隔を受信欠測と断定しない。
    """
    rows = []
    for key,record in sorted(material['prices'].items()):
        feature = material['features'][key]
        frame = flags[key]
        price = record['price_valid']
        quote = record['quote_valid']
        reasons = frame['reset_reason']
        np.testing.assert_array_equal(feature['reset'],reasons!=0)
        gaps = np.diff(record['time_s'])
        long = gaps[gaps>30]
        market = material['grids'][key[0]]['markets'][key[1]]
        rows.append(dict(場=key[0],商品=key[1],抽出行数=len(price),LastPrice不正行=int((~price).sum()),
                         最良価格不正行=int((~quote).sum()),深板不正行=int((~frame['valid']).sum()),
                         LastPrice最良正常で深板不正行=int((price&quote&~frame['valid']).sum()),
                         LastPrice最良正常でも旧reset行=int((price&quote&feature['reset']).sum()),
                         旧quality不合格行=int((~feature['quality']).sum()),
                         気配差2呼値超行=int((record['ask']-record['bid']>2*record['tick']+1e-9).sum()),
                         reset理由別={name:int(((reasons&bit)!=0).sum()) for bit,name in RESET_LABELS.items()},
                         原本seq欠番境界=int((np.diff(record['seq'])>1).sum()),
                         価格代理時計逆行=int((gaps<0).sum()),同時計後続行=int((gaps==0).sum()),
                         価格代理時計30秒超間隔件数=len(long),間隔合計秒=float(long.sum()),
                         間隔最大秒=float(gaps.max(initial=0)),間隔中央値秒=float(np.median(long)) if len(long) else None,
                         窓={str(w):dict(格子数=len(value['source_valid']),源有効=int(value['source_valid'].sum()),
                                          ER有限=int(np.isfinite(value['efficiency']).sum()),旧端点不明=int((value['old']<0).sum()),
                                          現在端点不明=int((value['now']<0).sum()),
                                          板reset又はinvalid横断=int(value['reset_or_invalid_cross'].sum()))
                             for w,value in market['windows'].items() if w in (30,300)}))
        rows[-1]['一時深板不正区間'] = invalid_runs(~frame['valid'],record['time_s'])
        rows[-1]['旧板価格経路不正区間'] = invalid_runs((~frame['valid'])|feature['reset'],record['time_s'])
    return rows


def causal_controls():
    """
    機能: 診断器自身が未読時計行をskipで連続化せず、未来同時計後続を先取りしない正負例を検査する。
    引数: なし。
    返り値: dict、人工検査結果。新候補の売買試験ではない。
    """
    arrays = dict(time=np.array([0.,10.,20.,20.,40.]),seq=np.array([0,1,2,3,4]),
                  last=np.array([100.,101.,102.,9000.,104.]),mid=np.array([100.,101.,102.,9000.,104.]),
                  last_ok=np.ones(5,bool),quote_ok=np.ones(5,bool),clock_gap=np.zeros(5,bool),
                  quote_price_error=np.zeros(5,bool),quote_qty_error=np.zeros(5,bool))
    normal = raw_window(arrays,21.,20.,'last')
    assert normal['ER']==1 and normal['現在原本seq']==2
    future = {k:v.copy() for k,v in arrays.items()}
    future['last'][3:]*=7
    assert raw_window(future,21.,20.,'last')==normal
    missing = {k:v.copy() for k,v in arrays.items()}
    missing['clock_gap'][2] = True
    failed = raw_window(missing,21.,20.,'last')
    assert not failed['源有効'] and failed['原行時計不明等のseqgap横断行']==1
    return dict(未来同時計後続の価格毒で先頭窓不変=True,原本時計欠測skipの次源を断裂に数える=True,
                同時計末尾を端点へ救済しない=True,人工売買実行=0)


def main():
    """
    機能: C11全受理時の入力不明を原観測から分類し、次段の価格品質分離の検討材料を保存する。
    引数: なし。
    返り値: None。1診断JSONだけ生成し、元キャッシュ/売買/会計/正式監査は変更しない。
    """
    material = data.load_inputs()
    flags,feature_paths = old_flags(material)
    cases,wanted = accepted_cases(material,flags)
    scan_keys = set(wanted)|{('2026-10-12_Day',s) for s in ('TOPIX','NK225')}
    scans = []
    for key in sorted(scan_keys):
        arrays,info,rebuilt = raw_scan(key,material['prices'][key],flags.get(key),wanted.get(key,set()))
        np.testing.assert_array_equal(rebuilt['reset_reason']!=0,material['features'][key]['reset'])
        flags[key]=rebuilt
        scans.append(info)
        for case in cases:
            if case['場']!=key[0]:continue
            target = datetime.fromisoformat(case['公開格子']).timestamp()-1.
            case['市場'][key[1]]['独立原観測価格窓'] = {channel:{str(w):raw_window(arrays,target,w,channel) for w in (30,60,300)}
                                                  for channel in ('last','mid')}
            for windows in case['市場'][key[1]]['独立原観測価格窓'].values():
                for window in windows.values():
                    if window.get('現在価格時計'):
                        assert datetime.fromisoformat(window['現在価格時計']).timestamp()>=material['prices'][key]['start']
                        assert datetime.fromisoformat(window['旧価格時計']).timestamp()>=material['prices'][key]['start']
    assert len(flags)==62
    total = {symbol:dict(新規数=0,旧両市場300ER不明=0,旧両市場30源有効=0,
                        原LastPrice両市場300ER有限=0,原最良中値両市場300ER有限=0,
                        原LastPrice両市場30ER有限=0,原最良中値両市場30ER有限=0)
             for symbol in ('TOPIX','NK225')}
    for case in cases:
        group = total[case['取引商品']]
        group['新規数']+=1
        markets = list(case['市場'].values())
        group['旧両市場300ER不明']+=not all(m['窓']['300']['ER'] is not None for m in markets)
        group['旧両市場30源有効']+=all(m['窓']['30']['源有効'] for m in markets)
        for channel,label in (('last','原LastPrice'),('mid','原最良中値')):
            for window in ('30','300'):
                group[f'{label}両市場{window}ER有限']+=all(m['独立原観測価格窓'][channel][window]['ER'] is not None for m in markets)
    sources = [Path(__file__),WORK/'事前固定.json',ROOT/'work/wave_v77/inputs/core.py',
               ROOT/'work/wave_v57/features.py',ROOT/'work/wave_v8/raw_features.py',*feature_paths,
               *[WORK/stage/'ledgers/C11.pkl' for stage in ('front','back')]]
    result = dict(位置付け='保存31場はすべて既知。入力品質の診断であり、新候補や新損益の実行ではない。',
                  C11受理要約=total,全62抽出入力=summary(material,flags),C11全17入口の両市場原観測=cases,
                  原本全時計と品質走査=scans,
                  診断器の原行欠測と同時計先頭の人工正負例=causal_controls(),
                  原LastPrice窓のセッション前参照=0,
                  事実の区別=[
                      'price_validは有限正LastPrice、quote_validは正常な最良価格対。旧qualityは完全10段validと2呼値以内気配差まで要求する。',
                      '旧mid ERは同価格時計先頭の中値を使うが、その窓のbrokenは完全10段valid及び補充フロー用resetから作る。価格値が正常でも深板不正や出来高減少でER窓が不明になるが、今回の大部分は最良気配除外に続く原本seq不連続である。',
                      '原本seqの欠番は旧bestquoteフィルタで除外した行でも起こる。これだけでネットワーク中断や真の価格観測欠測とは断定しない。',
                      '30秒超のCurrentPriceTime間隔は約定代理時計の飛び。受信clockがないので、無約定・受信欠測のどちらかを区別できない。',
                      '独立LastPrice/最良中値窓は入力可用性だけの反実仮想。これが有限でも新規方向の成功率や利益向上は証明していない。'],
                  次段検討メモ=[
                      '価格・最良気配・完全深板・出来高の資格及びresetを別チャンネルにし、それぞれ必要な部品へだけ適用する。深板だけ不正なら深板補充を休止し、正常LastPrice/BBO価格窓まで消す設計を再検討する。',
                      '価格窓は長さだけでなく最後の連続正常区間、時計鮮度、独立に可用な短窓を記録する。短30秒が有限でも、それを長300秒の同じ意味へ代用しない。',
                      '長窓不明時に一律全取引0とせず、当時正常な情報で仮説を支持又は棄却できるかを次の別対照で固定する。可用性改善だけで採用成功を認定しない。',
                      'TradingVolumeTimeは約定量の時計で、板受信clockではない。同時計で板が更新した保存seqを未来同時計末尾へ一括接続せず、旧strict過去先頭の対照を残す。真受信clockは今後の収集拡張で別途保存する。'],
                  新候補売買実行=0,新損益計算=0,元入力変更=0,元metadata変更=0,元core変更=0,元会計変更=0,
                  既存正式証跡変更=0,現在API取得=0,実注文=0,
                  SHA256={str(path.relative_to(ROOT)):digest(path) for path in sources})
    output = HERE/'C11の価格と板品質及び時計の原因診断.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(total,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
