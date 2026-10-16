"""保存済み再参加売買の悪化を、会計・当時の公開情報・原本行へ独立に分解する。"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import os
import pickle
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v86'
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'cache')


def read(path):
    """
    機能: 保存済みJSONを読取専用で開く。
    引数: path (Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def clean(value):
    """
    機能: numpy型と非有限値を保存可能な標準型へ直す。
    引数: value (object)。
    返り値: object。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def save(name, value):
    """
    機能: 新規監査領域だけへ日本語JSONを保存する。
    引数: name (str)、value (dict)。
    返り値: None。
    """
    target = (HERE / name).resolve()
    assert target.is_relative_to(HERE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def clock(stamp):
    """
    機能: 保存価格時計を日本時間表記へ変換する。
    引数: stamp (float)。
    返り値: str。受信時計ではない。
    """
    return datetime.fromtimestamp(float(stamp), timezone(timedelta(hours=9))).isoformat()


def groups(ledger):
    """
    機能: 決済脚を親組へまとめ、入口原本行と方向で対応する。
    引数: ledger (dict)。
    返り値: dict[tuple,dict]。
    """
    trades = defaultdict(list)
    for item in ledger['net_trades']:
        trades[int(item['組'])].append(item)
    result = {}
    for cid, legs in trades.items():
        first = legs[0]
        key = int(first['新規行']), int(first['方向'])
        result[key] = dict(cid=cid, entry=key[0], side=key[1],
            exit=max(int(t['返済行']) for t in legs), net=math.fsum(t['収支'] for t in legs),
            fee=math.fsum(t['手数料'] for t in legs), gross=math.fsum(t['利益損失前'] for t in legs), legs=legs)
    return result


def point(ready, row):
    """
    機能: 保存観測行を原本行・時刻・現在値へ対応させる。
    引数: ready (dict)、row (int)。
    返り値: dict。
    """
    row = int(row)
    return dict(入力行=row, 原本0始まり行=int(ready['seq'][row]), 原本1始まり行=int(ready['seq'][row])+1,
        時刻=clock(ready['time_s'][row]), 現在値=float(ready['last'][row]))


def evidence(ready, expanded, signal, row, side):
    """
    機能: 当該行までに公開された両市場EMAと保存入口方向を抜き出す。
    引数: ready (dict)、expanded (tuple)、signal (ndarray)、row/side (int)。
    返り値: dict。将来損益や将来価格を使わない。
    """
    result = dict(観測=point(ready,row), 保存入口方向=int(signal[row]))
    checks = []
    for label, data in zip(('自己','相手'), expanded):
        valid = np.isfinite(data['release'][row])
        result[label] = dict(公開時刻=clock(data['release'][row]) if valid else None,
            公開済足番号=int(data['source_index'][row]), 公開後秒=ready['time_s'][row]-data['release'][row],
            短長乖離ATR=data['gap'][row], 長期傾きATR=data['slow'][row], 短期傾きATR=data['fast'][row])
        checks.append(data['gap'][row]*side>.15 and data['slow'][row]*side>.02)
    result['両市場G成立'] = all(checks)
    return result


def diagnose(key, previous, current, ledger, ready, expanded, signal):
    """
    機能: 追加親組について前回全返済から新準備・新規・全返済までを事後追跡する。
    引数: key (tuple)、previous/current/ledger/ready (dict)、expanded (tuple)、signal (ndarray)。
    返り値: dict。当時の根拠と事後経路を分離する。
    """
    entry, end, side, cid = current['entry'], current['exit'], current['side'], current['cid']
    prep = next(p for p in ledger['entry_preparations'] if int(p[0])==cid and int(p[1])==entry)
    prepare_row, prepare_id = int(prep[3]), int(prep[2])
    setup = next(p for p in ledger['prepare_events'] if int(p[0])==prepare_id)
    order = next(o for o in ledger['orders'] if int(o[2])==cid and int(o[7])==1)
    source = int(order[1]); atr = float(setup[4]); price = float(order[5]); tick=float(ready['tick'])
    a = ready['last'][entry:end+1]
    excursion = side*(a-price)
    favourable_index=entry+int(np.nanargmax(excursion)); adverse_index=entry+int(np.nanargmin(excursion))
    # ----------------------------------------
    # 元の出口影と同じ0.75ATRの指定線を、損失方向に呼値丸めする。
    initial_stop = price-side*.75*atr
    initial_stop = math.floor(initial_stop/tick+1e-10)*tick if side>0 else math.ceil(initial_stop/tick-1e-10)*tick
    campaign = next(c for c in ledger['cycles'] if int(c[0])==cid)
    assert abs(campaign[5]-atr)<1e-9
    result = dict(セッション=key[0], 商品=key[1], 親組=cid, 方向='買い' if side>0 else '売り',
        収支=current['net'], 手数料=current['fee'], 手数料前=current['gross'],
        新規枚数=int(order[4]), 新規=point(ready,entry), 新規価格=price,
        新規準備=point(ready,prepare_row), 注文根拠更新=point(ready,source),
        準備時指定線=float(setup[3]), 初期ATR=atr, 初期損切りATR幅=.75*atr,
        初期損切り指定線=initial_stop, 丸め後初期損切り幅=side*(price-initial_stop),
        全返済=point(ready,end), 決済脚=current['legs'],
        当時の根拠=dict(新準備=evidence(ready,expanded,signal,prepare_row,side),
            注文根拠更新=evidence(ready,expanded,signal,source,side),
            約定直前観測=evidence(ready,expanded,signal,entry-1,side),約定時=evidence(ready,expanded,signal,entry,side)),
        事後推移=dict(最大順行=float(np.nanmax(excursion)),最大不利=float(-np.nanmin(excursion)),
            最大順行ATR=float(np.nanmax(excursion)/atr),最大不利ATR=float(-np.nanmin(excursion)/atr),
            最高順行時=point(ready,favourable_index),最大不利時=point(ready,adverse_index),
            保有秒=float(ready['time_s'][end]-ready['time_s'][entry]),
            約定直前からの観測間隔秒=float(ready['time_s'][entry]-ready['time_s'][entry-1]),
            返済まで最大観測間隔秒=float(np.max(np.diff(ready['time_s'][entry:end+1]))) if end>entry else 0.))
    crossings=np.flatnonzero(side*(a-initial_stop)<=1e-8)
    if len(crossings):
        result['事後推移']['初期損切り線への初到達']=point(ready,entry+int(crossings[0]))
    result['返済理由']=[{1:'初期組損切り',2:'主方向トレーリング',7:'部分利確',9:'場末返済',
        30:'順行後悪化の半減',32:'実組予算損切り',71:'予定静観返済'}.get(int(t['理由']),str(t['理由'])) for t in current['legs']]
    if previous is not None:
        start = previous['exit']; pdir=previous['side']; pentry=previous['entry']
        prior_prices=ready['last'][pentry:start+1]
        pmaxrow=pentry+int(np.nanargmax(prior_prices)); pminrow=pentry+int(np.nanargmin(prior_prices))
        peak=ready['last'][pmaxrow if side>0 else pminrow]
        between=ready['last'][start:entry+1]
        feedback=next((x for x in ledger['profit_reentry_events'] if int(x[1])==previous['cid']),None)
        reset=next((x for x in ledger['reentry_events'] if int(x[3])==previous['cid']),None)
        prior_evidence=evidence(ready,expanded,signal,start,side)
        g=np.ones(prepare_row-start+1,bool)
        newly_valid=np.ones(len(g),bool)
        for data in expanded:
            g &= (data['gap'][start:prepare_row+1]*side>.15)&(data['slow'][start:prepare_row+1]*side>.02)
            release=data['release'][start:prepare_row+1]
            age=ready['time_s'][start:prepare_row+1]-release
            newly_valid &= np.isfinite(data['gap'][start:prepare_row+1])&np.isfinite(data['slow'][start:prepare_row+1])
            newly_valid &= np.isfinite(release)&(age>=0)&(age<=180)
            newly_valid &= np.searchsorted(ready['time_s'],release,side='left')>start
        non_support=np.flatnonzero(newly_valid & ~g)
        result['前回との比較']=dict(前回親組=previous['cid'],前回方向=pdir,前回収支=previous['net'],
            前回全返済=point(ready,start),前回高値=point(ready,pmaxrow),前回安値=point(ready,pminrow),
            前回全返済から準備秒=ready['time_s'][prepare_row]-ready['time_s'][start],
            前回全返済から新規秒=ready['time_s'][entry]-ready['time_s'][start],
            再参加まで高値=float(np.nanmax(between)),再参加まで安値=float(np.nanmin(between)),
            前回順行極値から新規の順方向差=float(side*(price-peak)),
            前回方向と同じ=side==pdir,前回が黒字早期再参加許可=bool(feedback is not None and feedback[3]),
            前回返済イベント=feedback,次行リセットイベント=reset,
            新準備で自己公開足が更新=expanded[0]['source_index'][prepare_row]>expanded[0]['source_index'][start],
            新準備で相手公開足が更新=expanded[1]['source_index'][prepare_row]>expanded[1]['source_index'][start],
            前回全返済から新準備までG継続=bool(np.all(g)),
            有効かつ両公開元更新後の非支持確認=point(ready,start+int(non_support[0])) if len(non_support) else None,
            前回全返済時の根拠=prior_evidence)
    return result


def raw_extract(inputs, wanted):
    """
    機能: 必要な原本行だけを読み、現在値・時計を入力と照合し気配数量を保存する。
    引数: inputs (dict)、wanted (dict[tuple,set[int]])。
    返り値: dictの原本小窓と照合数。価格別数量の変化から意図を推定しない。
    """
    records=[]; checked=0
    original_hashes={(r['session'],r['symbol']):r['原本SHA256']
        for r in read(ROOT/'work/wave_v83/prepared/価格入力の照合.json')['各口座']}
    for key, rows in wanted.items():
        ready=inputs[key]; mapping={int(s):i for i,s in enumerate(ready['seq'])}
        requested={int(ready['seq'][r]) for r in rows}
        narrow={j for s in requested for j in range(max(0,s-1),s+2)}
        path=ROOT/'book'/key[1]/f'{key[0]}.jsonl'; sha=hashlib.sha256(); snapshots=[]
        with path.open('rb') as stream:
            for seq,line in enumerate(stream):
                sha.update(line)
                if seq not in narrow:
                    continue
                data=json.loads(line)
                if seq in mapping:
                    row=mapping[seq]
                    assert data['CurrentPrice']==ready['last'][row]
                    assert abs(datetime.fromisoformat(data['CurrentPriceTime']).timestamp()-ready['time_s'][row])<1e-6
                    checked+=1
                snapshots.append(dict(原本0始まり行=seq,原本1始まり行=seq+1,観測入力行=mapping.get(seq),
                    時計=data.get('CurrentPriceTime'),現在値=data.get('CurrentPrice'),
                    売買累計=data.get('TradingVolume'),売買累計時計=data.get('TradingVolumeTime'),
                    買板=[data.get(f'Buy{j}') for j in range(1,11)],売板=[data.get(f'Sell{j}') for j in range(1,11)]))
        assert requested <= {x['原本0始まり行'] for x in snapshots}
        assert sha.hexdigest()==original_hashes[key]
        records.append(dict(セッション=key[0],商品=key[1],原本=str(path.relative_to(ROOT)),SHA256=sha.hexdigest(),小窓=snapshots))
        print('原本照合',key,len(snapshots),flush=True)
    return dict(現在値と時計の一致行数=checked,既存指紋と原本SHA256一致ファイル数=len(records),原本小窓=records,
        限界='Buy1が買気配、Sell1が売気配。同価格数量増加は補充・既存注文変更等を分離できず、減少は約定・取消の区別がつかない。注文ID・真の受信時計はない。')


def main():
    """
    機能: 保存会計から悪化上位6口座を固定して原因・原本根拠を保存する。
    引数: なし。
    返り値: None。新しい条件の損益再生は行わない。
    """
    old_result=read(OLD/'observed/results/T2_S.json')
    new_result=read(OLD/'phase2/observed/results/T2_P1.json')
    old_ledger=pickle.loads((OLD/'observed/ledgers/T2_S.pkl').read_bytes())
    new_ledger=pickle.loads((OLD/'phase2/observed/ledgers/T2_P1.pkl').read_bytes())
    old_rows={(r['session'],r['symbol']):r for r in old_result['rows']}
    new_rows={(r['session'],r['symbol']):r for r in new_result['rows']}
    selected=[]
    for symbol in ('TOPIX','NK225'):
        selected += sorted([k for k in old_rows if k[1]==symbol],key=lambda k:new_rows[k]['net']-old_rows[k]['net'])[:3]
    save('対象6口座の事後選定.json',dict(選定='観測価格T2_P1−T2_Sの悪化額が大きい順に各商品3場。診断専用、改修の選抜条件ではない。',
        対象=[dict(セッション=k[0],商品=k[1],元収支=old_rows[k]['net'],新収支=new_rows[k]['net'],差=new_rows[k]['net']-old_rows[k]['net']) for k in selected]))
    # ----------------------------------------
    # 両市場の過去公開EMAだけを再構成し、売買再生は行わない。
    all_inputs=pickle.loads((ROOT/'work/wave_v67/prepared/old23/new_inputs.pkl').read_bytes())
    sessions={k[0] for k in selected};inputs={k:v for k,v in all_inputs.items() if k[0] in sessions};del all_inputs
    signals=pickle.loads((ROOT/'work/wave_v67/prepared/old23/signals.pkl').read_bytes())
    spec=importlib.util.spec_from_file_location('監査用旧E01',ROOT/'work/wave_v85/strategy.py')
    strategy=importlib.util.module_from_spec(spec);sys.modules[spec.name]=strategy;spec.loader.exec_module(strategy)
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache')
    strategy.base.gate.replay.entry.set_root(ROOT)
    models={k:strategy.base.gate.model(v) for k,v in inputs.items()}
    cases=[];wanted=defaultdict(set)
    for key in selected:
        ready=inputs[key];ledger=new_ledger[key]
        old,new=groups(old_ledger[key]),groups(ledger)
        shared=old.keys()&new.keys();removed=old.keys()-new.keys();added=new.keys()-old.keys()
        decomposition=dict(同入口差額=math.fsum(new[k]['net']-old[k]['net'] for k in shared),
            消えた元取引の差額=-math.fsum(old[k]['net'] for k in removed),
            追加黒字=math.fsum(new[k]['net'] for k in added if new[k]['net']>0),
            追加赤字=math.fsum(new[k]['net'] for k in added if new[k]['net']<0))
        assert abs(sum(decomposition.values())-(new_rows[key]['net']-old_rows[key]['net']))<1e-6
        expanded=strategy.base.gate.expanded(key,models,ready['time_s'])
        ordered=sorted(new.values(),key=lambda r:r['entry']); details=[]
        for pos,current in enumerate(ordered):
            if (current['entry'],current['side']) not in added:
                continue
            detail=diagnose(key,ordered[pos-1] if pos else None,current,ledger,ready,expanded,signals['entry'][key])
            details.append(detail)
        representatives=sorted([d for d in details if d['収支']<0],key=lambda r:r['収支'])[:2]
        for d in representatives:
            for name in ('新規','全返済','新規準備','注文根拠更新'):
                wanted[key].add(d[name]['入力行'])
            if '前回との比較' in d:
                for name in ('前回全返済','前回高値','前回安値'):
                    wanted[key].add(d['前回との比較'][name]['入力行'])
            peer=key[0],'NK225' if key[1]=='TOPIX' else 'TOPIX'
            for name in ('新規準備','注文根拠更新','新規'):
                row=d[name]['入力行']; stamp=ready['time_s'][row]
                peer_row=int(np.searchsorted(inputs[peer]['time_s'],stamp,side='left')-1)
                assert peer_row>=0 and inputs[peer]['time_s'][peer_row]<stamp
                wanted[peer].add(peer_row)
                d.setdefault('相手直前の保存原本対応',{})[name]=point(inputs[peer],peer_row)
        cases.append(dict(セッション=key[0],商品=key[1],元収支=old_rows[key]['net'],新収支=new_rows[key]['net'],
            差額=new_rows[key]['net']-old_rows[key]['net'],元組数=len(old),新組数=len(new),
            元手数料=old_rows[key]['fees'],新手数料=new_rows[key]['fees'],差額分解=decomposition,
            追加組数=len(details),追加赤字組数=sum(d['収支']<0 for d in details),
            全追加取引=details,原本照合代表親組=[d['親組'] for d in representatives]))
        print(key,decomposition,'追加',len(details),'最悪',[(d['親組'],d['収支']) for d in representatives],flush=True)
    save('再参加悪化6口座と全追加取引.json',dict(基準='T2_S',改修='T2_P1',約定='観測CurrentPrice、実手数料、追加待ちなし',
        注記=['全30既知の事後原因調査。最高安値・MFE・MAEはその時点から見た未来を含み、入口判定には使っていない。',
            '入口Gは公開済み両市場EMAであり、現在の両市場の板数量やOFIを同時確認する条件ではない。',
            '相手生板は自身の時計より厳密に前の最終行を説明用に表示し、元入口で使用した情報とは区別する。',
            '初期損切り指定線は初期ATRと価格から独立復元した値。実現損失の最大値ではなく、部分返済後には組損切り線が変わる。'],ケース=cases))
    raw=raw_extract(inputs,wanted)
    save('代表追加赤字の生板小窓と照合.json',raw)
    print('完了',len(cases),raw['現在値と時計の一致行数'],flush=True)


if __name__=='__main__':
    main()
