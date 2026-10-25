"""全損失と同じ条件の勝ちについて、当時原板の数量・変化・価格を接続する。"""

import hashlib
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent


def clean(value):
    """
    機能: 非有限値・numpy型をJSON用に変換する。
    引数: value(object)は保存対象。
    返り値: objectは標準型と欠測None。
    """
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,np.ndarray)):return [clean(v) for v in value]
    if isinstance(value,(np.floating,float)):return float(value) if np.isfinite(value) else None
    if isinstance(value,np.integer):return int(value)
    if isinstance(value,np.bool_):return bool(value)
    return value


def window(raw, seq, seconds):
    """
    機能: 判断原行以前の価格時計窓について原行変化を集計する。
    引数: raw(dict)、seq(int)、seconds(float)は全原板特徴と終端。
    返り値: dictは原行窓の量。秒あたり受信率・約定方向・取消を断定しない。
    """
    t=raw['time_s'][:seq+1];now=t[-1]
    eligible=np.flatnonzero(np.isfinite(t)&(t>=now-seconds)&(t<=now))
    lo=int(eligible[0]);sl=slice(lo,seq+1)
    ofi=raw['ofi'][sl];abs_ofi=np.nansum(np.abs(ofi))
    valid=raw['book_valid'][sl]
    rows=np.arange(lo,seq+1)[valid]
    incb=np.nansum(raw['same_price_buy_increase'][sl]);decb=np.nansum(raw['same_price_buy_decrease'][sl])
    incs=np.nansum(raw['same_price_sell_increase'][sl]);decs=np.nansum(raw['same_price_sell_decrease'][sl])
    total=incb+decb+incs+decs
    return dict(window_price_clock_seconds=seconds,first_seq=lo,last_seq=seq,raw_rows=seq-lo+1,
        normal_books=int(valid.sum()),clock_known_rows=int(np.isfinite(t[sl]).sum()),
        price_clock_same_rows=int(raw['price_clock_same'][sl].sum()),
        distinct_price_clocks=int(len(np.unique(t[sl][np.isfinite(t[sl])]))),
        changed_books=int(raw['book_changed'][sl].sum()),bbo_price_changes=int(raw['bbo_price_changed'][sl].sum()),
        beginning_mid=float(raw['mid'][rows[0]]) if len(rows) else np.nan,
        ending_mid=float(raw['mid'][rows[-1]]) if len(rows) else np.nan,
        price_change=float(raw['mid'][rows[-1]]-raw['mid'][rows[0]]) if len(rows) else np.nan,
        ofi_sum=float(np.nansum(ofi)),ofi_direction_fraction=float(np.nansum(ofi)/abs_ofi) if abs_ofi else 0.,
        ofi_normalized_mean=float(np.nanmean(raw['ofi_normalized'][sl])),
        distance_imbalance_median=float(np.nanmedian(raw['distance_imbalance'][sl])),
        distance_imbalance_last=float(raw['distance_imbalance'][seq]),
        buy_increase=float(incb),buy_decrease=float(decb),sell_increase=float(incs),sell_decrease=float(decs),
        quantity_pressure_fraction=float((incb+decs-decb-incs)/total) if total else 0.,
        reported_volume_increment=float(np.nansum(raw['volume_delta'][sl])))


def snapshot(raw, seq):
    """
    機能: その行の板・数量・価格時計窓を保存する。
    引数: raw(dict)、seq(int)は全原行配列と対象行。
    返り値: dictは未来原行を使わない観測情報。
    """
    assert int(raw['seq'][seq])==seq
    result=dict(seq=seq,line_no=seq+1,byte_offset=int(raw['byte_offset'][seq]),
        line_sha256=raw['line_sha256'][seq].tobytes().hex(),
        bid=float(raw['bid'][seq]),ask=float(raw['ask'][seq]),last=float(raw['last'][seq]),
        spread=float(raw['spread'][seq]),volume=float(raw['volume'][seq]),
        time_s=float(raw['time_s'][seq]),volume_time_s=float(raw['volume_time_s'][seq]),
        price_clock_same=bool(raw['price_clock_same'][seq]),book_changed=bool(raw['book_changed'][seq]),
        distance_imbalance=float(raw['distance_imbalance'][seq]),
        weighted_buy_depth=float(raw['weighted_buy_depth'][seq]),weighted_sell_depth=float(raw['weighted_sell_depth'][seq]),
        buy_price=raw['buy_price'][seq],buy_qty=raw['buy_qty'][seq],
        sell_price=raw['sell_price'][seq],sell_qty=raw['sell_qty'][seq])
    result['window30']=window(raw,seq,30.)
    result['window120']=window(raw,seq,120.)
    return result


def extract(raw, rows, stem):
    """
    機能: 核心判断・返済の原文行を直接読み、行SHAを検証して保存する。
    引数: raw(dict)、rows(set[int])、stem(str)は原位置と出力名。
    返り値: list[dict]は抜粋内行と元行の対応。原資料を変更しない。
    """
    source=Path(str(raw['source_path']))
    assert source.stat().st_size==int(raw['source_size'])
    assert source.stat().st_mtime_ns==int(raw['source_mtime_ns'])
    target=HERE/'decision_excerpts'/f'{stem}.jsonl';target.parent.mkdir(exist_ok=True)
    index=[]
    with source.open('rb') as stream,target.open('wb') as out:
        for pos,seq in enumerate(sorted(rows),1):
            stream.seek(int(raw['byte_offset'][seq]));line=stream.read(int(raw['byte_length'][seq]))
            assert hashlib.sha256(line).digest()==raw['line_sha256'][seq].tobytes()
            payload=json.loads(line)
            assert payload['Buy1']['Price']==raw['bid'][seq] and payload['Sell1']['Price']==raw['ask'][seq]
            out.write(line)
            index.append(dict(excerpt_line=pos,seq=seq,line_no=seq+1,sha256=hashlib.sha256(line).hexdigest()))
    return index


def main():
    """
    機能: 六口座の全親について、原板の当時情報と実際の成否を並べる。
    引数: なし。
    返り値: None。単なる原文接続・集計であり売買条件の再生をしない。
    """
    known=json.loads((HERE/'全損失親と価格転換141.json').read_text(encoding='utf-8'))
    records=[];archives=[]
    lines=['# 原板と売買の接続','',
        '全6原板は別担当のスクリプトが全行走査。ここでは全損失親と同条件の勝ち親について、判断・約定行を元ファイルから直接読み、行SHAとBBOを照合した。全原文を人間・LLMが読んだという意味ではない。',
        '板数量の増加・減少は連続表示価格の差であり、新規注文・約定・取消の識別ではない。OFIも最良気配の変化指標であり成行売買の量ではない。窓は価格時計の30秒前から判断seqまでの原行であり、受信時計の30秒・更新速度とは違う。符号は＋が買い寄り、−が売り寄り。','']
    for r in known['records']:
        stem=f'{r["symbol"]}_{r["session"]}'
        with np.load(HERE/'raw_features'/f'{stem}.npz') as z:raw={k:z[k] for k in z.files}
        needed=set();parent_rows=[];cache={}
        allparents=r['actual_parents']+r['baseline_only_losses']
        lines += [f'## {r["session"]} {r["symbol"]} / {r["method"]}','',
            '|採用|親|方向・損益|入口判断|30秒中値差|30秒OFI比|距離加重偏り中央値|同価格数量圧力比|返済判断の30秒中値差 / OFI比|',
            '|---|---:|---|---|---:|---:|---:|---:|---|']
        for p in allparents:
            orders=[]
            for o in p['orders']:
                copies={k:v for k,v in o.items() if k not in ('decision','fill')}
                for stage in ('decision','fill'):
                    seq=o[stage]['seq'];needed.add(seq)
                    if seq not in cache:cache[seq]=snapshot(raw,seq)
                    copies[stage]=dict(original=o[stage],raw=cache[seq])
                orders.append(copies)
            used=p in r['actual_parents']
            parent_rows.append(dict(parent=p['parent'],net=p['net'],side=p['side'],role=p['role'],adopted=used,
                                    tickets=p['tickets'],orders=orders))
            entry,exit=orders[0]['decision'],orders[-1]['decision']
            a,b=entry['raw']['window30'],exit['raw']['window30']
            lines.append(f'|{"採用" if used else "B5対照"}|{p["parent"]}|{"買" if p["side"]>0 else "売"} {p["net"]:+,.0f}円|{entry["original"]["time"]}|{a["price_change"]:g}|{a["ofi_direction_fraction"]:.3f}|{a["distance_imbalance_median"]:.3f}|{a["quantity_pressure_fraction"]:.3f}|{b["price_change"]:g} / {b["ofi_direction_fraction"]:.3f}|')
        archives.append(dict(stem=stem,source_path=str(raw['source_path']),source_sha256=str(raw['source_sha256']),
                             lines=extract(raw,needed,stem)))
        records.append(dict(session=r['session'],symbol=r['symbol'],method=r['method'],parents=parent_rows))
        print(stem,'全親',len(parent_rows),'判断約定原文',len(needed),flush=True)
    content=dict(purpose='原板との接続。新金融再生0、原文の全量LLM読込はしていない。',records=records,archives=archives)
    (HERE/'原板と売買の接続141.json').write_text(json.dumps(clean(content),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (HERE/'原板と売買の接続141.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
