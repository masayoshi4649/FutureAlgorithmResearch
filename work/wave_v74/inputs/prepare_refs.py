"""原板の参照値を保存順に確定し、始値・直前保存場の最終観測を未来補完なしで接続する。"""

from collections import deque
from datetime import datetime, timezone, timedelta
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TZ = timezone(timedelta(hours=9))
FIELDS = ('CurrentPrice', 'CurrentPriceTime', 'OpeningPrice', 'OpeningPriceTime',
          'PreviousClose', 'PreviousCloseTime', 'ClearingPrice', 'CalcPrice')
PATHS = {'ready':['work/wave_v69/prepared/inputs.pkl','work/wave_v71/prepared/extra_inputs.pkl'],
         'features':['work/wave_v69/prepared/features.pkl','work/wave_v71/prepared/extra_features.pkl']}


def digest(path: Path) -> str:
    """機能: 保存資料の内容指紋を読取専用で計算する。

    引数: path(Path)。
    返り値: SHA256の16進表記(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def stamp(value: object) -> float | None:
    """機能: 原板の日時文字列をUNIX秒へ変換する。

    引数: value(object)。
    返り値: 日時秒(float)又は欠損(None)。不正日時を未来値で補完しない。
    """
    try:
        return datetime.fromisoformat(value).timestamp() if isinstance(value,str) else None
    except ValueError:
        return None


def positive(value: object) -> bool:
    """機能: 参照価格として有限かつ正の数値か判定する。

    引数: value(object)。
    返り値: 有効価格ならTrue(bool)。
    """
    return isinstance(value,(float,int)) and math.isfinite(value) and value > 0


def text_time(value: float | None) -> str | None:
    """機能: 参照時計を日本時間の文字列へ変換する。

    引数: value(float|None)。
    返り値: 日本時間ISO文字列(str)又は欠損(None)。
    """
    return datetime.fromtimestamp(value,TZ).isoformat() if value is not None else None


def load_material() -> tuple[dict,dict]:
    """機能: 既存56口座と追加2口座の準備済み系列を変更せず結合する。

    引数: なし。
    返り値: readyとfeaturesの辞書(tuple[dict,dict])。重複キーは拒否する。
    """
    output = []
    for kind in ('ready','features'):
        merged = {}
        for name in PATHS[kind]:
            current = pickle.loads((ROOT/name).read_bytes())
            assert not set(merged)&set(current)
            merged.update(current)
        output.append(merged)
    assert set(output[0]) == set(output[1]) and len(output[0]) == 58
    return tuple(output)


def last_current(path: Path, count: int, start: float, end: float) -> dict | None:
    """機能: 原板末尾から場内の最後の新鮮約定値を検索する。

    引数: path(Path)、count(int)、start/end(float)。
    返り値: 価格と原本連番と時計(dict)又は欠損(None)。場外末尾が長くても前方値で代用しない。
    """
    row = count-1
    with path.open('rb') as stream:
        cursor = stream.seek(0,2)
        carry = b''
        while cursor > 0:
            left = max(0,cursor-65536)
            stream.seek(left)
            lines = (stream.read(cursor-left)+carry).split(b'\n')
            cursor = left
            carry = lines.pop(0) if left else b''
            for line in reversed(lines):
                if not line:
                    continue
                raw = json.loads(line)
                time = stamp(raw.get('CurrentPriceTime'))
                if positive(raw.get('CurrentPrice')) and time is not None and start <= time < end:
                    return dict(value=float(raw['CurrentPrice']),seq=row,time=time,kind='observed_CurrentPrice')
                row -= 1
    return None


def raw_probe(key: tuple, ready: dict, feature: dict) -> dict:
    """機能: 原板先頭・最初有効行・中間・末尾の欄と最初／最後の新鮮約定値を調べる。

    引数: key(tuple[str,str])、ready/feature(dict)。
    返り値: 原板サンプル、初約定観測、末約定観測、内容指紋など(dict)。
    行全体の再抽出は行わず、先頭と指定原板連番、末尾64行だけJSONを解析する。
    """
    n = len(ready['seq'])
    first = int(ready['seq'][0])
    targets = {0, first, int(ready['seq'][n//2]), int(ready['seq'][-1])}
    path = ROOT/'book'/key[1]/(key[0]+'.jsonl')
    samples, tail, earliest = {}, deque(maxlen=64), None
    sha = hashlib.sha256()
    count = 0
    end = float(ready['limit'])+300.
    with path.open('rb') as stream:
        for i, line in enumerate(stream):
            sha.update(line)
            count = i+1
            tail.append((i,line))
            if i <= first or i in targets or earliest is None:
                raw = json.loads(line)
                time = stamp(raw.get('CurrentPriceTime'))
                if earliest is None and positive(raw.get('CurrentPrice')) and time is not None and ready['start'] <= time < end:
                    earliest = dict(value=float(raw['CurrentPrice']), seq=i, time=time, kind='observed_CurrentPrice')
                if i in targets:
                    samples[i] = raw
    latest = None
    for i,line in reversed(tail):
        raw = json.loads(line)
        time = stamp(raw.get('CurrentPriceTime'))
        if positive(raw.get('CurrentPrice')) and time is not None and ready['start'] <= time < end:
            latest = dict(value=float(raw['CurrentPrice']),seq=i,time=time,kind='observed_CurrentPrice')
            break
    # ----------------------------------------
    # 有効準備行と同じ原板連番の価格・時計・気配を直接照合する。
    for row in (0,n//2,n-1):
        seq = int(ready['seq'][row])
        raw = samples[seq]
        assert stamp(raw.get('CurrentPriceTime')) == ready['time_s'][row]
        assert float(raw['CurrentPrice']) == ready['last'][row]
        assert float(raw['Buy1']['Price']) == feature['bid'][row]
        assert float(raw['Sell1']['Price']) == feature['ask'][row]
    assert earliest is not None, ('始値用の新鮮約定値なし',key)
    if latest is None:
        # 末尾64行がすべて場外なら、実際の最後の場内約定値が見つかるまで遡る。
        latest = last_current(path,count,float(ready['start']),end)
    assert latest is not None,('前場最終観測用の新鮮約定値なし',key)
    return dict(first_raw=samples[0], first_valid=samples[first], earliest=earliest, latest=latest,
        samples=[dict(seq=i, fields={name:raw.get(name) for name in FIELDS},
                      presence={name:name in raw for name in FIELDS},
                      bid=raw.get('Buy1',{}).get('Price'), ask=raw.get('Sell1',{}).get('Price'))
                 for i,raw in sorted(samples.items())],
        raw_rows=count, raw_SHA256=sha.hexdigest(), end=end)


def opening_ref(key: tuple, ready: dict, probe: dict) -> dict:
    """機能: 最初の有効行で現在場のfeed始値が使える場合だけ採用し、他は初約定観測を使う。

    引数: key(tuple[str,str])、ready/probe(dict)。
    返り値: 価格・利用開始行・原本由来・時刻を含む始値参照(dict)。
    後の行に現れたOpeningPriceを過去へ補完せず、古い他場の始値は採用しない。
    """
    raw = probe['first_valid']
    open_time = stamp(raw.get('OpeningPriceTime'))
    if (positive(raw.get('OpeningPrice')) and open_time is not None
            and ready['start'] <= open_time <= ready['time_s'][0] and open_time < probe['end']):
        price, seq, source_time, kind = (float(raw['OpeningPrice']),int(ready['seq'][0]),
                                        float(ready['time_s'][0]),'feed_OpeningPrice_current_session')
        reference_time = open_time
        fallback = False
    else:
        found = probe['earliest']
        price, seq, source_time, kind = found['value'],found['seq'],found['time'],'observed_session_open_CurrentPrice'
        reference_time = source_time
        fallback = True
    known = int(np.searchsorted(ready['seq'],seq,side='left'))
    known = max(known,int(np.searchsorted(ready['time_s'],source_time,side='left')))
    assert known < len(ready['seq']) and int(ready['seq'][known]) >= seq and ready['time_s'][known] >= source_time
    return dict(value=price,known_from_i=known,kind=kind,source_session=key[0],source_seq=seq,
                source_time=source_time,reference_time=reference_time,source_ready_i=known,
                source_raw_has_valid_quote=(seq == int(ready['seq'][known])),fallback=fallback,
                actual_exchange_open_guaranteed=(kind == 'feed_OpeningPrice_current_session'),
                discarded_feed_open=raw.get('OpeningPrice') if fallback else None,
                discarded_feed_open_time=raw.get('OpeningPriceTime') if fallback else None)


def previous_ref(key: tuple, ready: dict, predecessor: tuple | None, all_ready: dict, probes: dict) -> dict:
    """機能: 直前保存場の最後の新鮮約定値を現在場より前の既知参照として固定する。

    引数: key/predecessor(tuple|None)、ready/all_ready/probes(dict)。
    返り値: 前保存場の参照価格と由来(dict)。最初の保存場は欠損を保つ。
    公式終値や週末の存在しない価格を捏造しない。
    """
    if predecessor is None:
        return dict(value=None,known_from_i=-1,kind='missing_previous_saved_session',source_session=None,
                    source_seq=None,source_time=None,reference_time=None,source_ready_i=None,
                    fallback=False,missing_reason='最初の保存場より前の原本がないため補完しない。')
    previous = all_ready[predecessor]
    found = probes[predecessor]['latest']
    assert found['time'] < ready['start'] and probes[predecessor]['end'] <= ready['start']
    i = int(np.searchsorted(previous['seq'],found['seq'],side='left'))
    source_i = i if i < len(previous['seq']) and int(previous['seq'][i]) == found['seq'] else None
    gap = float(ready['start'] - probes[predecessor]['end'])
    day = datetime.fromtimestamp(previous['start'],TZ).date()
    next_day = datetime.fromtimestamp(ready['start'],TZ).date()
    return dict(value=found['value'],known_from_i=0,kind='previous_saved_session_last_CurrentPrice',
                source_session=predecessor[0],source_seq=found['seq'],source_time=found['time'],
                reference_time=found['time'],source_ready_i=source_i,fallback=bool(found.get('tail_fallback',False)),
                saved_end=probes[predecessor]['end'],gap_seconds=gap,weekend_gap=(next_day-day).days >= 3,
                actual_exchange_close_guaranteed=False,
                label='前保存セッションの最終観測値。公式終値ではない。')


def main() -> None:
    """機能: 全保存29場の参照値を固定し、原本同seqと時間の過去性を照合する。

    引数: なし。
    返り値: なし(None)。入力pickleを重複生成せず参照JSONだけを保存する。
    """
    assert not (HERE/'refmetadata.json').exists(),'完成済み参照値は上書きしない'
    ready, features = load_material()
    sessions = sorted({key[0] for key in ready})
    assert len(sessions) == 29
    previous_audit = json.loads((ROOT/'work/wave_v72/replay/保存範囲の照合.json').read_text(encoding='utf8'))
    expected_sha = {(r['session'],r['symbol']):r['SHA256'] for r in previous_audit['原本照合']}
    probes = {}
    for key,r in sorted(ready.items()):
        f=features[key]
        n=len(r['seq'])
        np.testing.assert_array_equal(r['seq'],f['seq'])
        np.testing.assert_array_equal(r['time_s'],f['time_s'])
        np.testing.assert_array_equal(r['last'],f['last'])
        assert np.all(np.diff(r['seq']) > 0) and np.all(np.diff(r['time_s']) >= 0)
        assert all(len(f[name]) == n for name in ('time_s','seq','bid','ask','mid','last','valid','reset'))
        probes[key]=raw_probe(key,r,f)
        assert probes[key]['raw_SHA256'] == expected_sha[key],('準備時以降の原本変更',key)
    references, rows = {}, []
    for symbol in ('TOPIX','NK225'):
        ordered=sorted((key for key in ready if key[1]==symbol),key=lambda key:ready[key]['start'])
        for j,key in enumerate(ordered):
            r,f,p=ready[key],features[key],probes[key]
            predecessor=ordered[j-1] if j else None
            if predecessor is not None:
                assert predecessor[0].endswith('_Day') != key[0].endswith('_Day'),('隣接保存場に欠落の可能性',key,predecessor)
                if key[0].endswith('_Night'):
                    assert predecessor[0][:10] == key[0][:10]
            ref_open=opening_ref(key,r,p)
            ref_prev=previous_ref(key,r,predecessor,ready,probes)
            # ----------------------------------------
            # フィードの日次前値は主アルゴへ接続せず、直前保存場参照と区別して記録する。
            first=p['first_valid']
            daily_time=stamp(first.get('PreviousCloseTime'))
            daily_value=float(first['PreviousClose']) if positive(first.get('PreviousClose')) else None
            daily=dict(value=daily_value,time=daily_time,time_text=first.get('PreviousCloseTime'),
                       source_seq=int(r['seq'][0]),known_from_i=0,
                       available=bool(daily_value is not None and daily_time is not None and daily_time <= r['time_s'][0]),
                       label='原板PreviousClose。日付付きの日次前値であり前保存場最終観測とは別。')
            references['|'.join(key)]=dict(session=key[0],symbol=symbol,ref_open=ref_open,ref_prev=ref_prev,
                daily_previous_feed=daily)
            n=len(r['seq'])
            rows.append(dict(session=key[0],symbol=symbol,n=n,start=float(r['start']),limit=float(r['limit']),
                end=float(p['end']),tick=float(r['tick']),start_text=text_time(r['start']),limit_text=text_time(r['limit']),
                first_time=float(r['time_s'][0]),last_time=float(r['time_s'][-1]),
                first_seq=int(r['seq'][0]),last_seq=int(r['seq'][-1]),
                valid_rows=int(f['valid'].sum()),reset_rows=int(f['reset'].sum()),
                first_spread_ticks=float((f['ask'][0]-f['bid'][0])/r['tick']),
                last_spread_ticks=float((f['ask'][-1]-f['bid'][-1])/r['tick']),
                field_lengths={name:list(value.shape) for name,value in f.items() if isinstance(value,np.ndarray)},
                raw_rows=p['raw_rows'],raw_SHA256=p['raw_SHA256'],raw_same_seq_samples=p['samples'],
                first_middle_last_seq_price_time_bidask_equal=True))
    output=dict(sessions=sessions,accounts=58,input_paths=PATHS,
        input_SHA256={name:digest(ROOT/name) for names in PATHS.values() for name in names},
        references=references,rows=rows,
        ready_keys=sorted(next(iter(ready.values())).keys()),feature_keys=sorted(next(iter(features.values())).keys()),
        total_valid_raw_rows=sum(len(r['seq']) for r in ready.values()),
        definitions={'ref_open':'最初有効行のOpeningPriceTimeが当該保存場内かつ当行以下の場合だけfeed価格を固定。それ以外は原板先頭から最初の場内CurrentPriceを観測始値とする。',
            'ref_prev':'直前完了保存場の通常監視区間内の最後の新鮮CurrentPrice。公式終値とは限らない。',
            'daily_previous_feed':'原板PreviousClose/PreviousCloseTimeの参考記録。ref_prevの代用はしない。',
            'fresh':'CurrentPriceが有限正値でCurrentPriceTimeが当該保存場のstart以上・end未満。受信時計がないため実時間鮮度の証明ではない。',
            'known_from_i':'当該価格の原板連番と時計の両方以上となる最初の準備済行。新規判断はこの行以降のみ。前場参照は現在場0行から、欠測は-1。',
            'end':'旧準備と同じ排他的通常監視末尾。Day15:40／Night翌05:55。返済期限はその5分前。',
            'weekend':'金曜Nightから月曜Dayへ参照値を渡す場合はweekend_gap=true。値は金曜Nightの最終保存観測を保持し、週末価格を合成しない。'},
        counts=dict(feed_session_open=sum(r['ref_open']['kind']=='feed_OpeningPrice_current_session' for r in references.values()),
            observed_session_open=sum(r['ref_open']['kind']=='observed_session_open_CurrentPrice' for r in references.values()),
            missing_previous=sum(r['ref_prev']['value'] is None for r in references.values()),
            weekend_predecessors=sum(r['ref_prev'].get('weekend_gap',False) for r in references.values())),
        sampled_feed_fields_only=True,全場原本指紋一致=True,原本同seq気配価格時計一致=True,
        売買損益未参照=True,未来補完なし=True,API取得=0,実注文=0,
        code_SHA256=digest(Path(__file__)))
    HERE.mkdir(parents=True,exist_ok=True)
    (HERE/'refmetadata.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print('29場58口座の参照固定と原本同seq照合が完了:',output['counts'],flush=True)


if __name__ == '__main__':
    main()
