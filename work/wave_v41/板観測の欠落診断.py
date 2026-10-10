"""固定4例の同価格数量を原本全行で読み、公開間の欠落原因を区別する。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLDER=HERE.parent/'wave_v40'
BASE=json.dumps(dict(board_anchor=True,seed_seconds=30.,trial_seconds=30.,away_atr=.5,
    break_ticks=2.,expiry_seconds=1800.,momentum_atr=.1),sort_keys=True)


def digest(path: Path) -> str:
    """機能: 読取資料の実体SHA256を得る。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1048576):value.update(block)
    return value.hexdigest()


def save(name: str, value: dict) -> None:
    """機能: 日本語の診断仕様と結果を有限JSONで保存する。

    引数: name (str)、value (dict)。返り値: なし (None)。
    """
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')


def number(value: object) -> float | None:
    """機能: 有限の非負数量・正価格の検査用に数値を読む。

    引数: value (object)。返り値: 有限値又はNone (float|None)。
    """
    try:result=float(value)
    except (ValueError,TypeError):return None
    return result if math.isfinite(result) and not isinstance(value,bool) else None


def at_price(raw: dict, direction: int, price: float) -> dict:
    """機能: 同側固定Pが、価格範囲外・非掲載・品質不明のどれかを区別する。

    引数: raw (dict)、direction (int)、price (float)。返り値: 同価格数量の観測 (dict)。
    真の約定・取消は分類しない。反対側数量を同側へ流用しない。
    """
    side='Sell' if direction==1 else 'Buy'
    other='Buy' if direction==1 else 'Sell'
    levels=[]
    for level in range(1,11):
        value=raw.get(f'{side}{level}') or {}
        p,q=number(value.get('Price')),number(value.get('Qty'))
        levels.append((p if p is not None and p>0 else None,q if q is not None and q>=0 else None))
    prices=[p for p,q in levels if p is not None]
    matches=[(i+1,q) for i,(p,q) in enumerate(levels) if p==price]
    opposite=any(number((raw.get(f'{other}{i}') or {}).get('Price'))==price for i in range(1,11))
    quantity=None;rank=None
    if len(matches)>1:reason='同価格重複'
    elif len(matches)==1 and matches[0][1] is not None:
        rank,quantity=matches[0];reason='同側で観測'
    elif len(matches)==1:reason='同価格数量不正'
    elif not prices:reason='同側価格不明'
    elif price<min(prices) or price>max(prices):reason='同側10段価格範囲外'
    else:reason='同側範囲内だが段に非掲載'
    far=None
    if reason=='同側10段価格範囲外':
        far='遠方10段の外' if (direction==1 and price>max(prices)) or (direction==-1 and price<min(prices)) else '最良側を越えた価格'
    stamp=raw.get('CurrentPriceTime');time=None
    if stamp:
        parsed=datetime.fromisoformat(stamp)
        assert parsed.tzinfo is not None
        time=parsed.timestamp()
    return dict(quantity=quantity,reason=reason,rank=rank,range_min=min(prices) if prices else None,
        range_max=max(prices) if prices else None,outside_direction=far,opposite_visible=opposite,time_s=time,
        side_complete=all(p is not None and q is not None for p,q in levels))


def aggregate(rows: list[dict], start_quantity: float | None = None) -> dict:
    """機能: 観測列の減少と最初の減少後の増加を、欠測を跨がず集計する。

    引数: rows (list[dict])、start_quantity (float|None)。返り値: 差分集計 (dict)。
    最初の行を初期数量とし、試行前からの差分は持ち込まない。
    """
    previous=start_quantity;decrease=0.;increase=0.;first=None;known=True
    publications=[];last_release=None;unknown=Counter()
    for row in rows:
        q=row['quantity']
        if q is None:
            known=False;unknown[row['reason']]+=1
        elif previous is not None:
            delta=q-previous
            if delta<0:
                decrease-=delta
                if first is None:first=row['seq']
            elif delta>0 and first is not None:increase+=delta
        previous=q
        release=row['release_seq']
        state=dict(release_seq=release,release_time_s=row['release_time_s'],last_material_seq=row['seq'],
            decrease=decrease,increase_after_decrease=increase,quantity_known=known,
            ratio=increase/decrease if known and decrease>0 else None)
        if release==last_release:publications[-1]=state
        else:publications.append(state);last_release=release
    return dict(row_count=len(rows),quantity_known=known,decrease=decrease,
        increase_after_decrease=increase,ratio=increase/decrease if known and decrease>0 else None,
        first_decrease_seq=first,unknown=dict(unknown),publications=publications)


def hidden_examples(rows: list[dict]) -> list[dict]:
    """機能: 同じCurrentPriceTime内の減少後増加を、公開時刻を添えて抜き出す。

    引数: rows (list[dict])。返り値: 時間順の先頭3例 (list[dict])。
    """
    result=[];group=[];stamp=None
    groups=[]
    for row in rows:
        if row['time_s']!=stamp:
            if group:groups.append(group)
            group=[];stamp=row['time_s']
        group.append(row)
    if group:groups.append(group)
    for group in groups:
        previous=None;down=None
        for row in group:
            if previous is not None and previous['quantity'] is not None and row['quantity'] is not None:
                if down is None and row['quantity']<previous['quantity']:
                    down=(previous,row)
                elif down is not None and row['quantity']>previous['quantity']:
                    result.append(dict(material_time_s=row['time_s'],before_seq=down[0]['seq'],
                        before_qty=down[0]['quantity'],decrease_seq=down[1]['seq'],decrease_qty=down[1]['quantity'],
                        increase_previous_seq=previous['seq'],increase_previous_qty=previous['quantity'],
                        increase_seq=row['seq'],increase_qty=row['quantity'],
                        release_seq=row['release_seq'],release_time_s=row['release_time_s']))
                    break
            if row['quantity'] is None:down=None
            previous=row
        if len(result)==3:break
    return result


def synthetic() -> dict:
    """機能: 相殺された変化・可視外・公開前利用禁止の小さい反例を確認する。

    引数: なし。返り値: 合格証拠 (dict)。
    """
    rows=[dict(seq=i,quantity=q,reason='同側で観測',time_s=100. if i<3 else 101.,
               release_seq=0 if i==0 else 3,release_time_s=100. if i==0 else 101.)
          for i,q in enumerate([10.,5.,12.,10.])]
    all_rows=aggregate(rows);snap=aggregate([rows[0],rows[-1]])
    assert snap['decrease']==0 and all_rows['decrease']==7 and all_rows['increase_after_decrease']==7
    assert len(all_rows['publications'])==2 and all_rows['publications'][0]['decrease']==0
    assert hidden_examples(rows)[0]['release_time_s']==101.
    missing=[dict(v) for v in rows];missing[1].update(quantity=None,reason='同側10段価格範囲外')
    assert aggregate(missing)['ratio'] is None
    raw={f'Sell{i}':dict(Price=100.+i,Qty=10.) for i in range(1,11)}
    assert at_price(raw,1,120.)['reason']=='同側10段価格範囲外'
    raw['Sell5']['Price']=104.5
    assert at_price(raw,1,105.)['reason']=='同側範囲内だが段に非掲載'
    changed=[dict(v) for v in rows];changed[-1]['quantity']=999.
    assert aggregate(changed)['publications'][0]==all_rows['publications'][0]
    return dict(全合格=True,同時刻内の相殺を検出=True,次時刻公開前へ遡及しない=True,
        可視外は0にしない=True,価格範囲外と範囲内非掲載を区別=True,未来変更で公開済み集計不変=True)


def main() -> None:
    """機能: 時系列先頭の各市場2例だけを原本全行で診断する。

    引数: なし。返り値: なし (None)。売買・採否変更・再探索・通信はしない。
    """
    cache=pickle.loads((OLDER/'band_cache.pkl').read_bytes())[BASE]
    depth=pickle.loads((OLDER/'released_depth.pkl').read_bytes())
    frames=pickle.loads((HERE.parent/'wave_v23/features_depth.pkl').read_bytes())
    pool=[]
    for key,bands in sorted(cache.items()):
        for band in bands:
            if band['status']=='breakout' and band['features']['two_trials_complete'] and not band['features']['quantity_comparable']:
                pool.append((key,band))
    chosen=[]
    for symbol in ['TOPIX','NK225']:
        chosen.extend([(key,band) for key,band in pool if key[1]==symbol][:2])
    assert len(chosen)==4
    specification=dict(選択='旧基準板帯の二試行完了breakoutかつu不明を、各銘柄時系列先頭2件',
        対象=[dict(session=k[0],symbol=k[1],band_id=b['band_id'],price=b['price']) for k,b in chosen],
        集約='試行開始公開行を初期数量とし、次の公開seqまでに存在した原本差分をその公開で開示',
        品質='旧公開の数量品質不明を持ち越す厳密版と、P局所観測だけの診断を区別。後者を新ルール採用しない',
        非対象='売買・収支・全候補再選抜・新データ取得',
        参照SHA256={str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in
            [OLDER/'band_cache.pkl',OLDER/'released_depth.pkl',HERE.parent/'wave_v23/features_depth.pkl',Path(__file__)]})
    save('板観測の欠落診断_仕様.json',specification)
    artificial=synthetic()
    oldhash=json.loads((HERE.parent/'wave_v23/入力確認.json').read_text(encoding='utf-8'))['原本SHA256']
    paths={f'book/{key[1]}/{key[0]}.jsonl' for key,band in chosen}
    before={p:digest(ROOT/p) for p in paths}
    assert all(before[p]==oldhash[p] for p in paths)
    # ----------------------------------------
    # 選ばれた試行範囲だけを読み、試行間の数量差分は作らない。
    records={}
    for path in paths:
        ranges=[(t['start']['seq'],t['end']['seq']) for key,band in chosen
            if path==f'book/{key[1]}/{key[0]}.jsonl' for t in band['trials']]
        material={}
        with (ROOT/path).open('rb') as stream:
            for seq,line in enumerate(stream):
                if seq>max(end for start,end in ranges):break
                if any(start<=seq<=end for start,end in ranges):material[seq]=json.loads(line)
        records[path]=material
    cases=[]
    for key,band in chosen:
        e=depth[key];frame=frames[key];path=f'book/{key[1]}/{key[0]}.jsonl';material=records[path]
        trials=[]
        for trial in band['trials']:
            rows=[]
            for seq in range(trial['start']['seq'],trial['end']['seq']+1):
                value=at_price(material[seq],band['direction'],band['price'])
                index=int(np.searchsorted(e['seq'],seq,side='left'))
                assert index<len(e['seq']) and e['seq'][index]>=seq
                row=dict(seq=seq,**value,release_seq=int(e['seq'][index]),release_time_s=float(e['time_s'][index]))
                assert row['time_s'] is None or row['time_s']<=row['release_time_s']
                rows.append(row)
            all_stats=aggregate(rows)
            byseq={r['seq']:r for r in rows}
            snapshots=[];endpoints=[]
            for sample in trial['samples']:
                raw=byseq[sample['seq']]
                if sample['quantity'] is not None:assert sample['quantity']==raw['quantity']
                snapshots.append(dict(raw,quantity=sample['quantity'],reason=sample['unknown_reason'] or '同側で観測'))
                if sample['quantity'] is None:
                    feature=frame.loc[frame.seq==sample['seq']]
                    assert len(feature)==1
                    feature=feature.iloc[0]
                    public_index=int(np.searchsorted(e['seq'],sample['seq']))
                    endpoints.append(dict(seq=sample['seq'],time_s=sample['time_s'],
                        old_reason=sample['unknown_reason'],
                        current_depth_valid=bool(e['depth_valid'][public_index]),
                        previous_block_resets=int(feature['continuity_reset_count']),
                        previous_block_first_seq=int(feature['source_first_seq']),
                        previous_block_last_seq=int(feature['source_last_seq']),
                        **{k:v for k,v in raw.items() if k not in ['seq','time_s']}))
            sampled=aggregate(snapshots)
            assert sampled['decrease']==trial['decrease']
            assert sampled['increase_after_decrease']==trial['increase_after_decrease']
            assert sampled['ratio']==trial['recovery_ratio']
            old_quality_ok=not any(s['unknown_reason']=='数量品質不明' for s in trial['samples'])
            strict_ratio=all_stats['ratio'] if old_quality_ok else None
            hidden=hidden_examples(rows)
            prefix_checks=0
            for release in all_stats['publications']:
                cut=[r for r in rows if r['seq']<=release['release_seq']]
                got=aggregate(cut)['publications'][-1]
                assert got==release
                prefix_checks+=1
            trials.append(dict(number=trial['number'],start=trial['start'],end=trial['end'],
                published=sampled,raw_all=all_stats,old_quality_ok=old_quality_ok,
                strict_all_rows_ratio=strict_ratio,
                p_local_ratio_diagnostic_only=all_stats['ratio'],
                old_unknown_endpoints=endpoints,same_clock_hidden_examples=hidden,
                all_raw_reason_counts=dict(Counter(r['reason'] for r in rows)),
                同じCurrentPriceTimeの数量変化数=sum(a['time_s']==b['time_s'] and a['quantity'] is not None
                    and b['quantity'] is not None and a['quantity']!=b['quantity'] for a,b in zip(rows,rows[1:])),
                全公開prefix確認数=prefix_checks,raw_rows=rows))
        cases.append(dict(session=key[0],symbol=key[1],band_id=band['band_id'],price=band['price'],
            direction=band['direction'],created=band['created'],terminal=band['terminal'],trials=trials,
            旧比較可能=False,原本全行で旧品質維持の比較可能=all(t['strict_all_rows_ratio'] is not None for t in trials),
            P局所品質だけなら比較可能=all(t['p_local_ratio_diagnostic_only'] is not None for t in trials)))
    assert {p:digest(ROOT/p) for p in paths}==before
    for p,h in specification['参照SHA256'].items():assert digest(ROOT/p)==h
    result=dict(全合格=True,対象帯数=4,対象試行数=8,結果=cases,人工検査=artificial,
        原本SHA256=before,原本不変=True,仕様SHA256=digest(HERE/'板観測の欠落診断_仕様.json'),
        売買再生=False,条件再選抜=False,API取得数=0,現在保存物使用=False)
    save('板観測の欠落診断.json',result)
    lines=['# 板観測の欠落診断','',
        '旧基準帯で二試行が完了し突破したのに、数量比率uが不明だった事例を、各銘柄の時系列先頭2件に固定した。4例だけの診断であり、全候補がどれだけ増えるかや利益改善は検証していない。','',
        '公開37行を原本866行へ展開すると、減少0だった6試行のすべてで減少が見つかった。一方、途中の可視外も見つかり、旧品質を維持して2試行とも比較可能へ変わった帯は4件中1件だけだった。全行化には観測上の価値があるが、比較不能の全面解消ではない。','',
        '|例|P|試行|公開/原本行数|公開の減/増|全行の減/増|旧u|旧品質維持の全行u|原本の可視外行数|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    fmt=lambda v:'不明' if v is None else f'{v:g}'
    for c in cases:
        for t in c['trials']:
            p,a=t['published'],t['raw_all'];outside=t['all_raw_reason_counts'].get('同側10段価格範囲外',0)
            lines.append(f'|{c["symbol"]} {c["session"]} #{c["band_id"]}|{c["price"]:g}|{t["number"]}|{p["row_count"]}/{a["row_count"]}|{p["decrease"]:g}/{p["increase_after_decrease"]:g}|{a["decrease"]:g}/{a["increase_after_decrease"]:g}|{fmt(p["ratio"])}|{fmt(t["strict_all_rows_ratio"])}|{outside}|')
    lines += ['', '## 具体的な欠落','']
    for c in cases:
        lines.append(f'**{c["symbol"]} {c["session"]} 帯{c["band_id"]}・P={c["price"]:g}**')
        for t in c['trials']:
            reasons=Counter(s['reason'] for s in t['old_unknown_endpoints'])
            lines.append(f'- 試行{t["number"]}: 公開端点の不明を原本で分類すると {dict(reasons)}。同一最終約定時刻内の数量変化は{t["同じCurrentPriceTimeの数量変化数"]}回。')
            if t['same_clock_hidden_examples']:
                h=t['same_clock_hidden_examples'][0]
                clock=datetime.fromtimestamp(h['material_time_s'],timezone(timedelta(hours=9))).isoformat()
                release=datetime.fromtimestamp(h['release_time_s'],timezone(timedelta(hours=9))).isoformat()
                lines.append(f'  例（同じ最終約定時刻 {clock}）: 減少は原本行{h["before_seq"]}の{h["before_qty"]:g}→行{h["decrease_seq"]}の{h["decrease_qty"]:g}、増加は行{h["increase_previous_seq"]}の{h["increase_previous_qty"]:g}→行{h["increase_seq"]}の{h["increase_qty"]:g}。公開行{h["release_seq"]}（{release}）に到達してから利用可能。')
            outside=[s for s in t['old_unknown_endpoints'] if s['reason']=='同側10段価格範囲外']
            if outside:
                first=outside[0]
                lines.append(f'  最初の可視外は原本行{first["seq"]}、P={c["price"]:g}に対して同側価格範囲{first["range_min"]:g}〜{first["range_max"]:g}（{first["outside_direction"]}）。反対側にPがあるか: {first["opposite_visible"]}。')
            quality=[s for s in t['old_unknown_endpoints'] if s['old_reason']=='数量品質不明']
            if quality:
                first=quality[0]
                lines.append(f'  数量品質不明の原本行{first["seq"]}ではcurrent10段適格={first["current_depth_valid"]}、前ブロックreset={first["previous_block_resets"]}（素材行{first["previous_block_first_seq"]}〜{first["previous_block_last_seq"]}）。同じ公開行でPの数量は{fmt(first["quantity"])}と観測できるが、旧品質条件では不明のままとなる。')
        lines.append(f'旧公開の数量品質条件を維持して比較可能へ変わったか: {c["原本全行で旧品質維持の比較可能"]}。P局所品質だけの参考値では: {c["P局所品質だけなら比較可能"]}。\n')
    lines += ['## 実装判断','',
        '原本の各行を順番に読み、試行開始公開行を初期数量とし、その後の差分を次の公開seqへ集約する実装は可能。同秒の過程を当該秒の先頭へ戻して使わず、公開seqに到達するまで封印する。保存スナップショット間の差分なので、これも約定量・取消量や同じ参加者の補充の測定にはならない。',
        '全行化で減少0が解消しても、同側10段の外へ出た数量を回復することはできない。むしろ公開端点では見えなかった途中の可視外が増える場合がある。見えない数量を0にしたり、欠測を跨ぐ差分を作れば、単なる観測改善ではなく別の仮定になる。',
        '旧reset由来の数量品質不明をP局所品質へ置き換える変更は、全行集計とは分けて比較する必要がある。この診断のP局所値はその区別のための参考値であり、新条件へ採用していない。',
        '以上は原本全行集約の実装可能性と観測内容の違いを示す。利益や汎用性の改善は一切示していない。新売買、再探索、API取得、原本変更は行っていない。']
    (HERE/'板観測の欠落診断.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(dict(全合格=True,対象帯数=4,対象試行数=8,旧品質維持で比較可能となった帯数=sum(c['原本全行で旧品質維持の比較可能'] for c in cases)),flush=True)


if __name__=='__main__':main()
