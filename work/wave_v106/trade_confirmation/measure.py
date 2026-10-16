"""保存原行の実値・公表出来高から、価格反発候補の観測可用性だけを測る。"""

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import pickle
import socket
import sys
import time

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
IDS = ('R_ONLY_ER40_M1_LIMIT', 'R_ONLY_ER40_M2_LIMIT')
FIELDS = ('raw_seq', 'price_time_s', 'last', 'bid', 'ask', 'volume', 'volume_time_s',
          'volume_delta_known', 'volume_delta_usable', 'volume_delta_observed', 'volume_delta',
          'price_reset_reason', 'lp_reset_reason', 'volume_reset_reason',
          'received_at_present', 'execution_to_raw_index', 'normal_execution_row')
METADATA = ROOT/'work/wave_v106/range_price/全33場の価格境界反発準備.json'
NPZ_METADATA = (ROOT/'work/wave_v103/input_v2/metadata.json', ROOT/'work/wave_v104/holdout_input/metadata.json')


def read(path: Path) -> dict:
    """
    機能: 小さいUTF-8資料だけを読み、入力計画と由来を取得する。
    引数: path(Path)はJSON位置。
    返り値: dictは保存された資料。原本や金融台帳は読まない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: 小sourceと資料の内容指紋を求める。
    引数: path(Path)は小資料の位置。
    返り値: strはSHA256。巨大入力は実読取bytesから別に照合する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: dict) -> None:
    """
    機能: 所有領域へ測定証跡を新規保存する。
    引数: name(str)はファイル名、value(dict)はJSON互換値。
    返り値: None。既存証跡を上書きしない。
    """
    path = HERE/name
    assert not path.exists() and path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8', newline='\n')


def number(value: float) -> float | None:
    """
    機能: 不明な原数値をJSONのnullへ保存する。
    引数: value(float)は観測値又はNaN。
    返り値: float|Noneは同じ観測値又は不明。中値や0を補完しない。
    """
    return float(value) if np.isfinite(value) else None


def point(raw: dict, row: int) -> dict:
    """
    機能: 候補当時の実原行と独立した価格・出来高時計を保存する。
    引数: raw(dict)は保存NPZ列、row(int)は当時までの原行。
    返り値: dictはseq、原CurrentPrice、原累計出来高、気配と時計の観測。
    """
    if row < 0:
        return dict(row=None, raw_seq=None)
    return dict(row=int(row), raw_seq=int(raw['raw_seq'][row]),
        price_time_s=number(raw['price_time_s'][row]), volume_time_s=number(raw['volume_time_s'][row]),
        last=number(raw['last'][row]), volume=number(raw['volume'][row]),
        bid=number(raw['bid'][row]), ask=number(raw['ask'][row]),
        price_reset_reason=int(raw['price_reset_reason'][row]),
        lp_reset_reason=int(raw['lp_reset_reason'][row]), volume_reset_reason=int(raw['volume_reset_reason'][row]))


def observe(raw: dict, row: int, prior_normal_raw: int, side: int, tick: float) -> dict:
    """
    機能: 現在と直前原行の実値差を分離し、保存資格付き出来高増と反発方向代理を測る。
    引数: raw(dict)、row/prior_normal_raw(int)、side(int:買1/売-1)、tick(float)は当時入力。
    返り値: dictは可用性・差・代理群。未来、損益、取消主体や真の約定方向は参照しない。
    """
    previous = row-1
    seq_pair = previous >= 0 and int(raw['raw_seq'][row]) == int(raw['raw_seq'][previous])+1
    values = previous >= 0 and all(np.isfinite(raw['volume'][r]) and raw['volume'][r] >= 0 for r in (previous, row))
    value_delta = float(raw['volume'][row]-raw['volume'][previous]) if values and seq_pair else np.nan
    value_known = bool(values and seq_pair and value_delta >= 0)
    clock_pair = previous >= 0 and all(np.isfinite(raw['price_time_s'][r]) for r in (previous, row))
    price_reverse = bool(int(raw['price_reset_reason'][row]) & 8)
    prior_price_reverse = previous >= 0 and bool(int(raw['price_reset_reason'][previous]) & 8)
    known, usable = bool(raw['volume_delta_known'][row]), bool(raw['volume_delta_usable'][row])
    if known:
        assert value_known and raw['volume_delta_observed'][row] == value_delta
    if usable:
        assert known and clock_pair and not price_reverse and not prior_price_reverse
        assert raw['volume_delta'][row] == value_delta
    last_pair = previous >= 0 and seq_pair and all(np.isfinite(raw['last'][r]) and raw['last'][r] > 0 for r in (previous, row))
    last_delta = float((raw['last'][row]-raw['last'][previous])/tick) if last_pair else np.nan
    quote_pair = previous >= 0 and np.isfinite(raw['bid'][previous]) and np.isfinite(raw['ask'][previous]) and 0 < raw['bid'][previous] < raw['ask'][previous]
    last_valid = np.isfinite(raw['last'][row]) and raw['last'][row] > 0
    proxy_known = bool(usable and value_delta > 0 and seq_pair and quote_pair and last_valid)
    proxy_side = None
    if proxy_known:
        proxy_side = 1 if raw['last'][row] >= raw['ask'][previous] else -1 if raw['last'][row] <= raw['bid'][previous] else 0
    if not usable:
        group = '出来高差の当時使用資格が不明'
    elif value_delta == 0:
        group = '既知の出来高差0'
    elif not last_pair:
        group = '出来高増・現在値の前後比較不明'
    elif side*last_delta > 0:
        group = '出来高増・現在値が反発方向へ変化'
    elif side*last_delta < 0:
        group = '出来高増・現在値が逆方向へ変化'
    else:
        group = '出来高増・現在値が同価格'
    volume_clock_changed = previous >= 0 and np.isfinite(raw['volume_time_s'][row]) and np.isfinite(raw['volume_time_s'][previous]) and raw['volume_time_s'][row] != raw['volume_time_s'][previous]
    price_clock_changed = clock_pair and raw['price_time_s'][row] != raw['price_time_s'][previous]
    baseline = prior_normal_raw
    interval = slice(max(0, baseline+1), row+1)
    interval_usable = baseline >= 0 and bool(np.all(raw['volume_delta_usable'][interval]))
    interval_delta = float(np.sum(raw['volume_delta'][interval])) if interval_usable else np.nan
    baseline_last_pair = baseline >= 0 and np.isfinite(raw['last'][baseline]) and raw['last'][baseline] > 0 and last_valid
    baseline_last_delta = float((raw['last'][row]-raw['last'][baseline])/tick) if baseline_last_pair else np.nan
    return dict(current=point(raw,row), previous_raw=point(raw,previous), prior_normal=point(raw,baseline),
        seq_continuous=bool(seq_pair), volume_value_pair_known=value_known, volume_value_delta=number(value_delta),
        volume_delta_known=known, volume_delta_usable=usable, volume_increased=bool(usable and value_delta > 0),
        volume_clock_changed=bool(volume_clock_changed), price_clock_changed=bool(price_clock_changed),
        last_pair_known=bool(last_pair), last_change_ticks=number(last_delta),
        last_changed=bool(last_pair and last_delta != 0), last_moved_in_rebound_direction=bool(last_pair and side*last_delta > 0),
        aggressor_proxy_known=proxy_known, aggressor_proxy_side=proxy_side,
        aggressor_proxy_matches_rebound=bool(proxy_known and proxy_side == side),
        aggressor_proxy_oppose_rebound=bool(proxy_known and proxy_side == -side),
        prior_normal_interval_raw_rows=int(row-baseline) if baseline >= 0 else None,
        prior_normal_interval_volume_known=bool(interval_usable), prior_normal_interval_volume_delta=number(interval_delta),
        prior_normal_last_change_ticks=number(baseline_last_delta),
        price_clock_reverse=price_reverse, previous_price_clock_reverse=bool(prior_price_reverse),
        group=group, last_touch_model_material=bool(proxy_known))


# ----------------------------------------


def pending_observation(raw: dict, record: dict, normal: dict, qok: np.ndarray,
                        candidate: dict) -> dict:
    """
    機能: 一候補の公開後待機区間で、BBO最初到達と原Lastの1呼値通過＋出来高増を観測比較する。
    引数: raw/record/normal/candidate(dict)、qok(ndarray[bool])は不変入力と候補。
    返り値: dictは事後の観測到達点。実注文・損益・新政策は作らず、入口特徴には戻さない。
    """
    row=int(candidate['row']);side=int(candidate['side']);limit=float(candidate['planned_entry'])
    stop=float(candidate['stop_price']);tick=float(record['tick']);eps=tick*1e-8;mapping=raw['execution_to_raw_index']
    future=np.arange(row+1,len(record['seq']),dtype=np.int64)
    stamps=record['time_s'][future]
    before=(stamps>=record['limit']-300)|normal['quiet'][future]|np.isfinite(normal['quiet_start_s'][future])
    reached=qok[future]&((record['ask'][future]<=limit+eps) if side==1 else (record['bid'][future]>=limit-eps))
    cancel=normal['range_pending_trend'][future]|(qok[future]&(side*((record['bid'][future] if side==1 else record['ask'][future])-stop)<=eps))
    endings=np.flatnonzero(before|reached|cancel)
    endrow=int(future[endings[0]]) if len(endings) else None
    if endrow is None:
        endraw=len(raw['raw_seq']);kind='保存末尾まで到達も取消条件も未観測'
    else:
        i=int(endings[0]);endraw=int(mapping[endrow])
        kind='元の静観又は新規期限' if before[i] else '最初BBO到達' if reached[i] else '元TREND又は固定停止の取消条件'
    start_raw=int(mapping[row])+1
    candidates=np.arange(start_raw,endraw,dtype=np.int64)
    if len(candidates):
        last=raw['last'][candidates]
        valid=(raw['volume_delta_usable'][candidates]&(raw['volume_delta'][candidates]>0)&np.isfinite(last)&(last>0))
        through=(last<=limit-tick+eps) if side==1 else (last>=limit+tick-eps)
        selected=candidates[valid&through]
    else:
        selected=np.empty(0,np.int64)
    first=int(selected[0]) if len(selected) else None
    simultaneous=False
    if endrow is not None:
        j=endraw;last=raw['last'][j]
        simultaneous=bool(raw['volume_delta_usable'][j] and raw['volume_delta'][j]>0 and np.isfinite(last) and last>0
            and ((last<=limit-tick+eps) if side==1 else (last>=limit+tick-eps)))
    return dict(終点種別=kind,終点normal_row=endrow,終点原行=point(raw,endraw) if endrow is not None else None,
        当行公開を除外=True,終点より前のLast一呼値通過と出来高増=first is not None,
        最初の通過原行=point(raw,first) if first is not None else None,通過観測行数=int(len(selected)),
        終点同原行の通過と出来高増=simultaneous,
        分母='受付内R候補の独立待機観測。実保有・休止・他候補との競合を再生していない。',
        使用='候補後の観測比較だけ。事後の通過有無は入口の当時条件へ戻さない。')


def sources() -> dict:
    """
    機能: 観測code、原field仕様、固定候補選択sourceの指紋を結果前に記録する。
    引数: なし。
    返り値: dict[str,str]はroot相対位置とSHA256。金融sourceは対象にしない。
    """
    paths = [HERE/'measure.py', HERE/'artificial.py']
    paths += [ROOT/p for p in ('work/wave_v103/input/core.py','work/wave_v103/input_v2/correction.py',
        'work/wave_v103/input_v2/入力schema.json','work/wave_v104/peer/core.py',
        'work/wave_v103/activity/core.py','work/wave_v104/holdout_input/core.py',
        'work/wave_v106/range_price/catalog.py','work/wave_v106/range_price/selection.py',
        'work/wave_v106/range_price/features.py','work/wave_v106/range_price/common.py',
        'work/wave_v106/regime_price/features.py','work/wave_v106/range_price/engine/core.py')]
    return {p.relative_to(ROOT).as_posix():digest(p) for p in paths}


def plan() -> dict:
    """
    機能: 大型保存入力を読む前に、全33場と各一読のmanifest及び観測定義を固定する。
    引数: なし。
    返り値: dictは非金融の計画。旧104rawの不足を補う保存NPZだけを追加する。
    """
    meta = read(METADATA); old, additional = (read(p) for p in NPZ_METADATA)
    assert meta['全合格'] and len(meta['sessions']) == 33 and old['全合格'] and additional['全合格']
    npz = {}
    for session in meta['sessions']:
        source = old if session in old['sessions'] else additional
        for symbol in SYMBOLS:
            item = source['accounts'][session+'|'+symbol]
            npz[session+'|'+symbol] = dict(path=item['出力位置'],SHA256=item['出力SHA256'],
                raw_rows=item['raw_rows'],normal_rows=item['normal_execution_rows'],tick=item['tick'])
    assert len(npz) == 66
    return dict(目的='反発候補当時のCurrentPriceと公表累計出来高の可用性。勝敗や新注文は評価しない。',
        固定時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(),sessions=meta['sessions'],ids=list(IDS),
        source_SHA256=sources(),input_manifests=[dict(path=p.relative_to(ROOT).as_posix(),SHA256=digest(p)) for p in (METADATA,*NPZ_METADATA)],
        packet_inputs=meta['cache'],npz_inputs=npz,
        変更理由='104rawは価格時計・出来高時計・BBO・reset・mapのみで、原Last/累計出来高は失われている。原本を再読せず不変103v2/104追加Day NPZへ対応させる。',
        機械条件=dict(対象='R_ONLY_ER40_M1_LIMIT及びM2_LIMITの保存と同じ料込RR通過判断row。実取引親や勝敗ではない。',
            受付='[start+300,limit-300)、旧J静観外・当時正常BBO。全候補も別件数保存。',
            差分='直前raw rowとの原seq連続・累計値非負非減少を別flag、保存volume_delta_known/usableとresetを保持。',
            現在値='原CurrentPrice(last)だけ。直前raw及び反発基準の直前normalとの差を保存し、中値から補完しない。',
            方向代理='usable出来高増＋当行Last>=直前raw askは買攻撃代理、Last<=直前raw bidは売攻撃代理。間は方向不明に近い中間価格。真の約定方向は断定しない。',
            時計='CurrentPriceTime、TradingVolumeTimeは別時計。停滞は差0や取引なしを意味しない。受信時計は不在。',
            指値素材='FirstLastTouch＋出来高増モデルの原fieldがあるかだけ測る。native queue約定、時刻別全約定、取消・補充・約定主体は復元できない。'),
        追加到達比較='受付内R候補の公開後・元期限静観/既知TREND/固定停止で切る待機区間。BBO到達と同行取消ならBBO優先、期限静観は先。BBO到達より前のLast1呼値通過＋usable出来高増を観測し、同原行は別記。実注文や利益への差は測らない。',
        最大読取=dict(保存range入力=33,保存原行NPZ=66,旧104大型packet=0,原book=0,現在API=0,新金融=0,金融結果=0),
        人工証跡SHA256=digest(HERE/'原値更新と出来高及び接頭の人工検査.json'))


def load_bytes(item: dict) -> bytes:
    """
    機能: 保存入力の一回読取bytesで指紋を照合する。
    引数: item(dict)は固定path/SHA256。
    返り値: bytesはその一読の内容。原本bookは許可しない。
    """
    path = ROOT/item['path']
    assert path.resolve().is_relative_to((ROOT/'work').resolve())
    value = path.read_bytes()
    assert hashlib.sha256(value).hexdigest() == item['SHA256'], path
    return value


def modules() -> tuple[object, object]:
    """
    機能: 不変range候補の観測選択だけを接続する。
    引数: なし。
    返り値: tuple[object,object]は固定catalog/selection。engineや金融をimportしない。
    """
    folder = ROOT/'work/wave_v106/range_price'
    sys.path.insert(0,str(folder))
    for name in ('common','features','catalog','selection'):
        assert name not in sys.modules
        spec=importlib.util.spec_from_file_location(name,folder/(name+'.py'))
        value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return sys.modules['catalog'],sys.modules['selection']


def counts(records: list[dict]) -> dict:
    """
    機能: 観測有無の分母を固定し、勝敗と無発火を数えず群別件数を保存する。
    引数: records(list[dict])は候補当時観測。
    返り値: dictは件数と同じ分母の百分率。成功確率や取引勝率とは呼ばない。
    """
    flags=('seq_continuous','volume_value_pair_known','volume_delta_known','volume_delta_usable',
        'volume_increased','volume_clock_changed','price_clock_changed','last_pair_known','last_changed',
        'last_moved_in_rebound_direction','aggressor_proxy_known','aggressor_proxy_matches_rebound',
        'aggressor_proxy_oppose_rebound','prior_normal_interval_volume_known','last_touch_model_material')
    total=len(records)
    observed={name:sum(bool(r[name]) for r in records) for name in flags}
    return dict(判断候補数=total,件数=observed,割合={k:100*v/total if total else None for k,v in observed.items()},
        群=dict(Counter(r['group'] for r in records)),
        出来高時計同値でも出来高増=sum(r['volume_increased'] and not r['volume_clock_changed'] for r in records),
        価格時計同値でも現在値変化=sum(r['last_changed'] and not r['price_clock_changed'] for r in records),
        直前normalから出来高増=sum(r['prior_normal_interval_volume_known'] and r['prior_normal_interval_volume_delta']>0 for r in records),
        公開後待機観測=waiting_counts([r['pending_observation'] for r in records if 'pending_observation' in r]),
        分母='保存入口条件の当時判断候補。保有中・pending中・休止中に実参加しなかった候補も含む。')


def waiting_counts(records: list[dict]) -> dict:
    """
    機能: 未来側を含む公開後の到達観測を、入口当時の特徴率と別分母で保存する。
    引数: records(list[dict])は受付内候補の独立待機観測。
    返り値: dictはBBO前通過の件数。金融勝率・native約定確率とは呼ばない。
    """
    total=len(records);reached=[r for r in records if r['終点種別']=='最初BBO到達']
    count=sum(r['終点より前のLast一呼値通過と出来高増'] for r in records)
    return dict(受付内待機候補数=total,最初BBO到達候補数=len(reached),終点種別=dict(Counter(r['終点種別'] for r in records)),
        終点前のLast一呼値通過と出来高増=count,全待機候補内百分率=100*count/total if total else None,
        BBO到達群でBBOより前の通過=sum(r['終点より前のLast一呼値通過と出来高増'] for r in reached),
        BBO到達同原行の通過=sum(r['終点同原行の通過と出来高増'] for r in reached),
        金融再生=0,実注文数ではない=True)


def measure() -> dict:
    """
    機能: 固定後の33packet/66NPZを一回ずつ読み、当時R判断rowの観測だけを保存する。
    引数: なし。
    返り値: dictは可用性と群分類。損益ラベル・新注文・金融再生は生成しない。
    """
    fixed=read(HERE/'非金融測定の事前固定.json'); assert fixed['source_SHA256']==sources()
    for item in fixed['input_manifests']:
        assert digest(ROOT/item['path'])==item['SHA256']
    catalog,selection=modules();configs={c['id']:c for c in catalog.catalog() if c['id'] in IDS}
    collected={i:{s:[] for s in SYMBOLS} for i in IDS};session_counts={};reads=Counter();raw_total=0;received=0
    for session in fixed['sessions']:
        saved=load_bytes(fixed['packet_inputs'][session]);reads['保存range入力']+=1
        packet=pickle.loads(gzip.decompress(saved));del saved
        assert packet['session']==session
        session_counts[session]={}
        for symbol in SYMBOLS:
            raw_bytes=load_bytes(fixed['npz_inputs'][session+'|'+symbol]);reads['保存原行NPZ']+=1
            with np.load(io.BytesIO(raw_bytes),allow_pickle=False) as archive:
                raw={k:archive[k] for k in FIELDS}
            del raw_bytes
            raw_total+=len(raw['raw_seq']);received+=int(np.count_nonzero(raw['received_at_present']))
            record=packet['prepared'][symbol]['record'];mapping=raw['execution_to_raw_index']
            for k,rk in (('raw_seq','seq'),('price_time_s','time_s'),('last','price'),('bid','bid'),('ask','ask')):
                np.testing.assert_array_equal(raw[k][mapping],record[rk])
            m=packet['measured'][symbol];t=record['time_s'];accept=(t>=record['start']+300)&(t<record['limit']-300)&~packet['quiet'][symbol]['active']&m['qok']
            session_counts[session][symbol]={}
            for identifier in IDS:
                normal=selection.build(packet,symbol,configs[identifier]);rows=[]
                for d in normal['decisions']:
                    row=int(d['row']);j=int(mapping[row]);p=int(m['previous_normal_row'][row]);previous=int(mapping[p]) if p>=0 else -1
                    assert d['raw_seq']==int(raw['raw_seq'][j]) and d['raw_row']==j
                    value=observe(raw,j,previous,int(d['side']),float(record['tick']))
                    value.update(session=session,symbol=symbol,id=identifier,normal_row=row,raw_row=j,
                        side=int(d['side']),reception=bool(accept[row]),prior_normal_row=p,
                        declared_limit=d['planned_entry'],fixed_stop=d['stop_price'],fixed_target=d['target_price'])
                    if accept[row]:
                        value['pending_observation']=pending_observation(raw,record,normal,m['qok'],d)
                    rows.append(value)
                collected[identifier][symbol].extend(rows)
                session_counts[session][symbol][identifier]=dict(全候補=counts(rows),受付内=counts([r for r in rows if r['reception']]))
            del raw
        del packet
        print(json.dumps(dict(完了場=session,完了場数=len(session_counts),保存入力読取=dict(reads)),ensure_ascii=False),flush=True)
    aggregates={i:{s:dict(全候補=counts(v),受付内=counts([r for r in v if r['reception']])) for s,v in accounts.items()} for i,accounts in collected.items()}
    assert sources()==fixed['source_SHA256']
    return dict(全合格=True,sessions=fixed['sessions'],ids=list(IDS),aggregate=aggregates,by_session=session_counts,
        observations=collected,source_SHA256=fixed['source_SHA256'],事前固定SHA256=digest(HERE/'非金融測定の事前固定.json'),
        開始終端source一致=True,保存入力読取=dict(reads),保存原行数=raw_total,受信時刻保存原行数=received,
        原book読取=0,旧104大型packet読取=0,新金融再生=0,金融結果読取=0,API取得=0,実注文=0,
        限界=['CurrentPriceは原値だけを使い、気配中値で補完していない。累計差は直前rawとの比較で未知/resetを0にしない。',
            '攻撃側は出来高増を伴うLast対直前BBOの代理であり、全出来高の方向や同一約定主体ではない。',
            '価格・出来高時計の停滞は取引なしを意味しない。受信時計不在で実受信先後は未証明。',
            '候補件数は実注文件数ではなく、同じ相場のM1/M2群は重複する。勝敗・収益改善は未測定。',
            'FirstLastTouch＋出来高増の因果モデルは保存原値で作れる場合があるが、取引順序・queue順位・native約定可能性を証明しない。'])


def main() -> None:
    """
    機能: 事前固定又は明示許可された一回の非金融測定を行う。
    引数: CLIの--fix-only/--root-observation-reviewed(bool)。
    返り値: None。失敗を保存し自動再実行せず、通信を禁止する。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--fix-only',action='store_true');parser.add_argument('--root-observation-reviewed',action='store_true')
    args=parser.parse_args(); assert args.fix_only != args.root_observation_reviewed
    if args.fix_only:
        write('非金融測定の事前固定.json',plan());print('事前固定完了・大型保存入力未読');return
    def denied(*args: object, **kwargs: object) -> None:
        """
        機能: この測定のネットワーク接続を拒否する。
        引数: args/kwargs(object)は接続要求。
        返り値: None。常に例外で停止する。
        """
        raise RuntimeError('非金融保存入力測定は通信禁止')
    socket.create_connection=denied;socket.socket.connect=denied
    assert not (HERE/'R反発判断の原値と出来高可用性.json').exists() and not (HERE/'観測可用性False.json').exists()
    started=time.monotonic()
    try:
        result=measure();result['処理秒']=time.monotonic()-started;write('R反発判断の原値と出来高可用性.json',result)
        print(json.dumps(dict(全合格=True,結果SHA256=digest(HERE/'R反発判断の原値と出来高可用性.json'),aggregate=result['aggregate']),ensure_ascii=False),flush=True)
    except Exception as error:
        write('観測可用性False.json',dict(全合格=False,例外=repr(error),自動再試行=0,新金融再生=0,API取得=0,原book読取=0))
        raise


if __name__=='__main__':
    main()
