"""最悪場の基準入口で実際に参照した時計とOFIの証拠範囲を独立点検する。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
IDENT='J2_F0_B0_H0_R0'


def load(path: Path) -> object:
    """機能: 保存資料を読み取る。

    引数: path(Path)。返り値: 復元内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf-8'))


def timestamp(value: float) -> str:
    """機能: 原本の数値時計を日本時間の秒表示へ変換する。

    引数: value(float)。返り値: 日本時間文字列(str)。
    """
    return datetime.fromtimestamp(value,timezone(timedelta(hours=9))).isoformat(timespec='milliseconds')


def number(value: object) -> float | None:
    """機能: 非有限の特徴量を不明として保存する。

    引数: value(object)。返り値: 有限数値又はNone(float|None)。
    """
    answer=float(value)
    return answer if np.isfinite(answer) else None


def main() -> None:
    """機能: 最悪6口座の全新規の参照順序とOFI状態を確認する。

    引数: なし。返り値: なし(None)。未来の損益は説明欄だけで、入口採否を再生成しない。
    """
    meta=load(ROOT/'work/wave_v77/inputs/metadata.json');ready={};features={}
    for path in meta['input_paths']['ready']:ready.update(load(ROOT/path))
    for path in meta['input_paths']['features']:features.update(load(ROOT/path))
    ready.update(load(ROOT/'work/wave_v77/inputs/extra_inputs.pkl'))
    features.update(load(ROOT/'work/wave_v77/inputs/extra_features.pkl'))
    grids=load(ROOT/'work/wave_v77/inputs/grids_delay5.pkl')
    legacy=load(ROOT/'work/wave_v77/prepared/legacy_delay5.pkl')
    result=load(ROOT/f'work/wave_v78/results/{IDENT}.json')
    ledgers=load(ROOT/f'work/wave_v78/ledgers/{IDENT}.pkl')
    target={symbol:sorted((r for r in result['rows'] if r['symbol']==symbol),key=lambda r:r['net'])[:3]
        for symbol in ('TOPIX','NK225')}
    records=[];counts=Counter();full_balance={}
    for symbol,rows in target.items():
        excluded={r['session'] for r in rows}
        rest=[r for r in result['rows'] if r['symbol']==symbol and r['session'] not in excluded]
        full_balance[symbol]=dict(最悪3場=[r['session'] for r in rows],最悪3収支=sum(r['net'] for r in rows),
            残27収支=sum(r['net'] for r in rest),残27利益=sum(r['profit'] for r in rest),残27損失=sum(r['loss'] for r in rest))
        for row in rows:
            key=(row['session'],symbol);r=ready[key];f=features[key];ledger=ledgers[key];session=grids[key[0]]
            for order in ledger['orders'][ledger['orders'][:,7]==1]:
                fill,decision,cid,side=map(int,order[:4]);clock=float(r['time_s'][decision])
                candidates=np.flatnonzero((session['grid']<=clock)&(clock-session['grid']<=10.))
                assert len(candidates),('参照格子なし',key,decision)
                g=int(candidates[-1]);grid_clock=float(session['grid'][g]);markets={};price_sources={}
                assert np.searchsorted(r['time_s'],grid_clock,side='left')==decision,('格子の最初の原本行',key,cid)
                base=legacy[key]['candidates'];matched=base[(base[:,1]==decision)&(base[:,2]==side)]
                assert len(matched)==1
                old_grid,old_decision,old_direction,own_source,peer_source=map(int,matched[0])
                old_clock=r['start']+300.+15.*old_grid
                assert old_decision==decision and old_direction==side
                assert legacy[key]['own_source'][old_grid]==own_source and legacy[key]['peer_source'][old_grid]==peer_source
                for name,source in ((symbol,own_source),('NK225' if symbol=='TOPIX' else 'TOPIX',peer_source)):
                    sr=ready[(key[0],name)];sf=features[(key[0],name)];source_clock=sr['time_s'][source]
                    assert source_clock<old_clock-5. and source==np.searchsorted(sr['time_s'],source_clock,side='left')
                    price_sources[name]=dict(参照行=source,原本seq=int(sr['seq'][source]),参照時計=timestamp(source_clock),
                        判断時点との秒差=float(clock-source_clock),bid=float(sf['bid'][source]),ask=float(sf['ask'][source]))
                for name in ('TOPIX','NK225'):
                    m=session['markets'][name];current=m['current'];source=int(current['index'][g])
                    source_clock=float(ready[(key[0],name)]['time_s'][source])
                    assert source_clock<grid_clock-5.
                    assert source==np.searchsorted(ready[(key[0],name)]['time_s'],source_clock,side='left')
                    flow=m['flow'][15]
                    sufficient=bool(flow['source_valid'][g] and flow['valid'][g] and not flow['missing_ofi'][g]
                        and flow['nonzero_ofi_count'][g]>=3 and np.isfinite(flow['ofi_ratio'][g]))
                    signed=side*float(flow['ofi_ratio'][g])
                    evidence='支持' if sufficient and signed>=.1 else '明確逆行' if sufficient and signed<=-.1 else '中立' if sufficient else '不明'
                    assert evidence!='明確逆行',('J2の逆OFI除外と不一致',key,cid,name)
                    counts[(name,evidence)]+=1
                    w=m['windows'][300]
                    markets[name]=dict(参照行=source,原本seq=int(ready[(key[0],name)]['seq'][source]),
                        参照時計=timestamp(source_clock),判断時点との秒差=clock-source_clock,
                        格子時点との秒差=grid_clock-source_clock,価格有効=bool(current['valid'][g]),
                        板10段有効=bool(current['q_valid'][g]),OFI証拠=evidence,
                        OFI符号比=number(flow['ofi_ratio'][g]),OFI非零数=int(flow['nonzero_ofi_count'][g]),
                        OFI窓有効=bool(flow['source_valid'][g]),方向を掛けた300秒変化bp=number(side*w['ret_bp'][g]),
                        過去300秒窓有効=bool(w['source_valid'][g]),最良偏り=number(current['best_imbalance'][g]),
                        距離偏り=number(current['depth_imbalance'][g]))
                eligible=np.flatnonzero(np.isfinite(f['bid'])&np.isfinite(f['ask'])&(f['bid']>0)&(f['ask']>=f['bid'])&(np.arange(len(f['bid']))>decision))
                assert fill==eligible[0] and order[5]==(f['ask'][fill] if side==1 else f['bid'][fill])
                trade=ledger['trades'][ledger['trades'][:,0]==cid];assert len(trade)==1
                close=ledger['orders'][(ledger['orders'][:,0]==trade[0,2])&(ledger['orders'][:,7]==0)][0]
                records.append(dict(商品=symbol,セッション=key[0],組=int(cid),方向='買い' if side==1 else '売り',
                    新規判断時計=timestamp(clock),新規約定時計=timestamp(r['time_s'][fill]),共通格子時計=timestamp(grid_clock),
                    約定遅れ秒=float(r['time_s'][fill]-clock),新規気配=float(order[5]),
                    従来価格入口の15秒格子時計=timestamp(old_clock),従来価格入口の参照市場=price_sources,
                    旧入口から判断までの不利呼値=float(side*((f['ask'][decision]-f['ask'][own_source]) if side==1 else (f['bid'][decision]-f['bid'][own_source]))/r['tick']),
                    返済判断時計=timestamp(r['time_s'][int(close[1])]),返済約定時計=timestamp(r['time_s'][int(close[0])]),
                    返済理由=int(close[6]),確定損益=float(trade[0,10]),参照市場=markets,
                    参照市場の意味='J2追加条件を判定した5秒格子。従来の価格入口15秒格子の参照市場とは分ける。'))
    proof=dict(合格=True,対象ID=IDENT,対象口座数=6,対象セッション数=len({r['セッション'] for r in records}),
        新規数=len(records),OFI証拠集計={f'{name}_{state}':count for (name,state),count in counts.items()},
        最悪場と残り=full_balance,全新規=records,
        解釈='J2追加5秒格子は観測十分な明確逆OFIを拒否する方式。従来価格入口15秒格子の参照行とは異なる場合がある。両板の積極支持を必須としていない。支持/中立/不明を区別し、結果損益は採点用だけに併記。',
        時計の限界='最終約定時計の代理上での厳密過去参照。現実に同時受信した二市場の状態を保証しない。',
        原本取引者心理の推定='取消・約定・補充を個別に識別する注文ID/全イベント情報を持たないため、集計板差から断定しない。',
        既知資料内の診断=True,新アルゴリズム損益再生=0,API取得=0,実注文=0,
        SHA256={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in
            (ROOT/f'work/wave_v78/results/{IDENT}.json',ROOT/f'work/wave_v78/ledgers/{IDENT}.pkl',HERE/'entry_quality.py')})
    HERE.mkdir(parents=True,exist_ok=True)
    (HERE/'最悪6口座の入口時計とOFI証拠監査.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k not in ('全新規','SHA256')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
