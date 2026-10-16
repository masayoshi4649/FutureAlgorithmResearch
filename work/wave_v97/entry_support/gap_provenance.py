"""A7の10秒gap取消を原本の時計と保持seqへ追い、受信中断と取引時計を混同しない。"""

from collections import Counter, deque
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import pickle
import socket

import numpy as np

from diagnose import HERE, ROOT, WORK, SYMBOLS, deny, module, sha


def finite(value: object) -> float | None:
    """
    機能: 原板数値を欠測と有限値へ分け、未知をゼロへ置換しない。
    引数: value(object)。
    返り値: float又はNone。
    """
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def clock_fields(raw: dict, prefix: str = '') -> dict:
    """
    機能: 外側及び買売気配の入れ子にあるTime・timestamp・受信保存At欄を全て列挙する。
    引数: raw(dict)、prefix(str)は入れ子の経路。
    返り値: dict[str,object]。非null時計が無い箇所を価格時計で補完しない。
    """
    result = {}
    for key,value in raw.items():
        name = prefix + key
        lower = key.lower()
        if ('time' in lower or lower in ('receivedat','received_at','recordedat','recorded_at',
            'capturedat','captured_at','recv_at','updatedat','updated_at','createdat','created_at')):
            result[name] = value
        if isinstance(value,dict):
            result.update(clock_fields(value,name+'.'))
    return result


def snapshot(raw: dict) -> dict:
    """
    機能: gap前後の最良気配・数量・現在値・出来高と原本時計欄だけを抽出する。
    引数: raw(dict)。
    返り値: dictは状態と時計。保存時刻や受信時刻を架空に追加しない。
    """
    buy, sell = raw.get('Buy1') or {}, raw.get('Sell1') or {}
    bid, ask = finite(buy.get('Price')), finite(sell.get('Price'))
    bq, aq = finite(buy.get('Qty')), finite(sell.get('Qty'))
    status = '不明'
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        status = '正常' if bid < ask else 'ロック' if bid == ask else '交差'
    if bq is None or aq is None or bq <= 0 or aq <= 0:
        status = '最良数量不正'
    clocks = clock_fields(raw)
    requested = ('CurrentPriceTime','BidTime','AskTime','TradingVolumeTime','ReceivedAt','received_at',
        'RecordedAt','recorded_at','Timestamp','timestamp','ServerTime','Buy1.Time','Sell1.Time',
        'Buy1.Timestamp','Sell1.Timestamp')
    present = {name:name in clocks for name in requested}
    for name in requested:
        clocks.setdefault(name,None)
    return dict(CurrentPrice=finite(raw.get('CurrentPrice')), TradingVolume=finite(raw.get('TradingVolume')),
        bid=bid, ask=ask, bid_qty=bq, ask_qty=aq, 最良状態=status,
        時計欄=clocks, 要求時計の原本存在=present)


def clock(text: object) -> float | None:
    """
    機能: timezone付き原本時計だけをUnix秒へ変換する。
    引数: text(object)。
    返り値: float又はNone。書かれていない受信時計を補間しない。
    """
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    return parsed.timestamp() if parsed.tzinfo is not None else None


def source_rows(key: tuple, record: dict, events: np.ndarray) -> tuple[list[dict], dict]:
    """
    機能: 原本を前から一度読み、gapの前後及び直前同clock最大65原行を独立に診断する。
    引数: key(tuple[str,str])、record(dict)、events(ndarray[float])はA7取消イベント。
    返り値: tuple[list[dict],dict]は全gap行の診断と読取原本前方指紋。
    """
    targets = {}
    for event in events:
        row = int(event[0])
        assert row > 0
        gap = float(record['time_s'][row] - record['time_s'][row-1])
        assert gap > 10. + 1e-8
        previous_seq, current_seq = map(int, record['seq'][[row-1,row]])
        targets[current_seq] = dict(原行=row, 前保持原seq=previous_seq, 現保持原seq=current_seq,
            前代理時計=float(record['time_s'][row-1]), 現代理時計=float(record['time_s'][row]),
            gap秒=gap, 主取消理由=int(event[2]), 取消flags=int(event[55]),
            候補原行=int(event[11]), 候補番号=int(event[10]), 候補代理時計=float(event[13]),
            方向=int(event[9]), 取消前phase=int(event[8]))
    if not targets:
        return [], dict(原本='', 読取原行数=0, 原本前方SHA256=None)
    path = ROOT/'book'/key[1]/(key[0]+'.jsonl')
    previous_targets = {v['前保持原seq'] for v in targets.values()}
    previous = {}
    windows = {}
    recent = deque(maxlen=64)
    h = hashlib.sha256()
    keys = set()
    top_keys = set()
    read_rows = 0
    answer = []
    active_target = sorted(targets.items())
    cursor = 0
    omitted = Counter()
    for sequence, line in enumerate(path.open('rb')):
        if sequence > max(targets):
            break
        h.update(line)
        read_rows += 1
        target_seq, target = active_target[cursor]
        if target['前保持原seq'] < sequence < target_seq:
            raw = json.loads(line)
            now = snapshot(raw)
            stamp = clock(raw.get('CurrentPriceTime'))
            keys.update(now['時計欄'])
            omitted['原本に存在する除外行'] += 1
            omitted[now['最良状態']] += 1
            if stamp is None:
                omitted['時計不明'] += 1
            elif record['start'] <= stamp < record['end'] and now['CurrentPrice'] is not None and now['CurrentPrice'] > 0 and now['最良状態']=='正常':
                omitted['原本で正常最良現在値場内時計'] += 1
        if sequence in previous_targets:
            raw = json.loads(line)
            top_keys.update(raw)
            previous[sequence] = snapshot(raw)
            keys.update(previous[sequence]['時計欄'])
            text = raw.get('CurrentPriceTime')
            block = []
            for seq, raw_line in reversed([*recent,(sequence,line)]):
                old_raw = json.loads(raw_line)
                if old_raw.get('CurrentPriceTime') != text:
                    break
                point = snapshot(old_raw)
                point['原seq'] = seq
                point['深板値'] = tuple((old_raw.get(f'{label}{depth}') or {}).get(name)
                    for label in ('Buy','Sell') for depth in range(1,11) for name in ('Price','Qty'))
                block.append(point)
            block.reverse()
            windows[sequence] = block
        if sequence in targets:
            raw = json.loads(line)
            top_keys.update(raw)
            point = snapshot(raw)
            keys.update(point['時計欄'])
            target = targets[sequence]
            old = previous[target['前保持原seq']]
            assert clock(old['時計欄'].get('CurrentPriceTime')) == target['前代理時計']
            assert clock(point['時計欄'].get('CurrentPriceTime')) == target['現代理時計']
            i = target['原行']
            assert old['CurrentPrice'] == record['price'][i-1] and point['CurrentPrice']==record['price'][i]
            assert old['bid']==record['bid'][i-1] and old['ask']==record['ask'][i-1]
            assert point['bid']==record['bid'][i] and point['ask']==record['ask'][i]
            block = windows.pop(target['前保持原seq'])
            prices = {(p['bid'],p['ask']) for p in block}
            quantities = {(p['bid_qty'],p['ask_qty']) for p in block}
            lasts = {p['CurrentPrice'] for p in block}
            volumes = {p['TradingVolume'] for p in block}
            details = dict(target, 場=key[0], 商品=key[1], 保持原seq連続=sequence==target['前保持原seq']+1,
                gap前後の原本板=dict(前=old,後=point), 原本除外行=dict(omitted),
                直前同clock観測=dict(観測原行数=len(block), 最良価格組数=len(prices), 最良数量組数=len(quantities),
                    深板組数=len({p['深板値'] for p in block}), 現在値組数=len(lasts), 累積出来高組数=len(volumes),
                    原seq先頭=block[0]['原seq'], 原seq末尾=block[-1]['原seq'],
                    最良価格変化=len(prices)>1, 最良数量変化=len(quantities)>1),
                gap前後最良価格変化=(old['bid'],old['ask'])!=(point['bid'],point['ask']),
                gap前後現在値変化=old['CurrentPrice']!=point['CurrentPrice'])
            answer.append(details)
            omitted = Counter()
            cursor += 1
            if cursor==len(active_target):
                break
        recent.append((sequence,line))
    assert len(answer)==len(targets)
    actual_keys = {key for row in answer for name in ('前','後')
        for key,value in row['gap前後の原本板'][name]['時計欄'].items() if value is not None}
    receive = [key for key in actual_keys if any(word in key.lower() for word in ('receive','recv','capture','record','server','timestamp'))]
    return answer, dict(原本=str(path.relative_to(ROOT)), 読取原行数=read_rows, 原本前方SHA256=h.hexdigest(),
        時計候補欄=sorted(keys), 実非null時計欄=sorted(actual_keys), 原本外側欄=sorted(top_keys),
        非nullの気配受信保存時計候補=sorted(receive))


def main() -> None:
    """
    機能: A7全31のgapを原本へ追い、解釈の限界と次の論理対照を金融条件を変えず保存する。
    引数: なし。
    返り値: Noneは時計provenanceの独立診断JSON。
    """
    socket.socket.connect=deny
    socket.create_connection=deny
    data=module('gapの原本時計入力97',WORK/'data.py')
    material=data.load_inputs()
    ledgers, paths={},[]
    for part in ('front','back'):
        path=WORK/part/'ledgers/A7_X3.pkl'
        with path.open('rb') as stream:
            ledgers.update(pickle.load(stream))
        paths.append(path)
    rows, raw_proofs=[],[]
    for key,ledger in sorted(ledgers.items()):
        events=np.asarray(ledger['entry_wait_events'])
        canceled=events[(events[:,1]==3)&((events[:,55].astype(np.int64)&4)!=0)]
        if not len(canceled):
            continue
        current,raw_proof=source_rows(key,material['prices'][key],canceled)
        rows.extend(current)
        raw_proofs.append(raw_proof)
        print('/'.join(key)+f': {len(current)} gapの原本CurrentPriceTime・seq・実板を照合',flush=True)
    summary={}
    for symbol in SYMBOLS:
        selected=[r for r in rows if r['商品']==symbol]
        summary[symbol]=dict(gapflags取消=len(selected), gap主理由=sum(r['主取消理由']==3 for r in selected),
            保持原seq連続=sum(r['保持原seq連続'] for r in selected),
            保持原seq非連続=sum(not r['保持原seq連続'] for r in selected),
            同clockで直前最良価格変化=sum(r['直前同clock観測']['最良価格変化'] for r in selected),
            同clockで直前最良数量変化=sum(r['直前同clock観測']['最良数量変化'] for r in selected),
            gap前後最良価格変化=sum(r['gap前後最良価格変化'] for r in selected),
            gap前後現在値変化=sum(r['gap前後現在値変化'] for r in selected),
            gap中央値秒=float(np.median([r['gap秒'] for r in selected])) if selected else None,
            除外行の最良状態=dict(sum((Counter(r['原本除外行']) for r in selected),Counter())))
    clock_summary = {}
    all_clock_keys = sorted({key for row in rows for point in row['gap前後の原本板'].values() for key in point['時計欄']})
    for name in all_clock_keys:
        values = [point['時計欄'].get(name) for row in rows for point in row['gap前後の原本板'].values()]
        parsed = [clock(value) for value in values]
        delta = []
        for row in rows:
            old = clock(row['gap前後の原本板']['前']['時計欄'].get(name))
            new = clock(row['gap前後の原本板']['後']['時計欄'].get(name))
            if old is not None and new is not None:
                delta.append(new-old)
        clock_summary[name] = dict(非null数=sum(value is not None for value in values),
            timezone付き可読数=sum(value is not None for value in parsed),
            CurrentPriceTimeと一致=sum(value is not None and value==row['gap前後の原本板'][side]['時計欄'].get('CurrentPriceTime')
                for row in rows for side in ('前','後') for value in [row['gap前後の原本板'][side]['時計欄'].get(name)]),
            前後進行数=sum(value>0 for value in delta), 前後不変数=sum(value==0 for value in delta),
            前後逆行数=sum(value<0 for value in delta), 差最小秒=min(delta) if delta else None,
            差最大秒=max(delta) if delta else None)
    paths += [Path(__file__),HERE/'diagnose.py',WORK/'data.py',WORK/'engine.py',WORK/'strategy.py',WORK/'事前固定.json',
              ROOT/'work/wave_v83/data.py',ROOT/'work/wave_v91/inputs/metadata.json']
    proof=dict(全合格=True, 判定='10秒gapは真の受信間隔ではなく原本CurrentPriceTimeの間隔',
        集計=summary, 全時計候補の非null及び前後大小=clock_summary, 原本前方照合=raw_proofs, 全gap明細=rows,
        取得中断かどうか='共通受信・保存時計が無いので不明。原seqはJSONL保存順であり取引所の欠落検出用sequenceではない。seq連続を通信正常の証明にせず、CurrentPriceTimeの飛びを受信中断の証明にしない。',
        同clock板変化の意味='同じ取引代理時計のまま板が変わる原行を観測できる。価格経路は約定時計の経過だけと同一ではない。ただし、観測されなかった実時間中の極値や真の配信遅延は確定できない。',
        研究解釈='gapで候補が消えたケースは、その先の押し回復仮説を測定していない。否定された収益手法とせず、今回の時計断裂規則の下で未成立として区別する。',
        次の論理対照=[
            '原seq欠落・最良不正・代理時計逆行と、Last取引時計が飛ぶだけの正常連続原板を別状態にする。',
            '正常観測を保持する対照でも、候補TTLを延長せず、gap行で即時発注せず、現在資格と新しい両源を再確認する。',
            '未観測又は不正板区間を跨ぐ押しpeak/extremeは保証できない。取消又はgap後の別phase再基準を比較し、旧価格閾値の都合のよい延長や補完をしない。',
            'clock更新をseqだけで代用すると二市場の公表順を保証できない。時計上限・源の分離・未確認時の発注禁止は独立に保つ。'],
        新売買実行=0, 条件変更=0, 損益集計に利用=0, API取得=0, 実注文=0,
        SHA256={str(p.relative_to(ROOT)):sha(p) for p in paths})
    destination=HERE/'A7の10秒gap全原本時計と保持seq及び同clock実板変化の独立診断.json'
    destination.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,集計=summary,判定=proof['判定'],
        全時計候補の非null及び前後大小=clock_summary,新売買実行=0),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
