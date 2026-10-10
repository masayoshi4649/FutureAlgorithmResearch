"""原本全行の試行観測を旧標本の別式・切断・未来変更・反射で検査する。"""

from __future__ import annotations

from copy import deepcopy
from collections import Counter
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import trial_observation as builder
import published_reference

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
OLD=OUT.parent/'wave_v40'


def sha(path: Path) -> str:
    """機能: 読取資料の実体指紋を得る。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1048576):h.update(block)
    return h.hexdigest()


def write(name: str, value: dict) -> None:
    """機能: 有限JSONで日本語証拠を保存する。

    引数: name (str)、value (dict)。返り値: なし (None)。
    """
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')


def same(actual: object, expected: object, path: str='') -> None:
    """機能: 全構造を比較し、反射時の浮動丸め以外を厳密に検査する。

    引数: actual/expected (object)、path (str)。返り値: なし (None)。
    """
    if isinstance(expected,dict):
        assert isinstance(actual,dict) and set(actual)==set(expected),path
        for key in expected:same(actual[key],expected[key],path+'/'+key)
    elif isinstance(expected,list):
        assert isinstance(actual,list) and len(actual)==len(expected),path
        for i,(a,b) in enumerate(zip(actual,expected)):same(a,b,path+f'/{i}')
    elif isinstance(expected,float):
        assert isinstance(actual,(int,float)) and abs(actual-expected)<=1e-8,(path,actual,expected)
    else:assert actual==expected,(path,actual,expected)


def projected(panel: list[dict], cutoff: int) -> list[dict]:
    """機能: 完成パネルから切断前に公開済みの事実だけを独立に抽出する。

    引数: panel (list[dict])、cutoff (int)。返り値: 当時知ることのできたパネル (list[dict])。
    """
    result=[]
    for source in panel:
        if source['created']['seq']>cutoff:continue
        b=deepcopy(source)
        if b['terminal'] is not None and b['terminal']['seq']>cutoff:b['terminal']=None
        trials=[]
        for old in b['trials']:
            if old['start']['seq']>cutoff:continue
            t=deepcopy(old);t['publications']=[p for p in t['publications'] if p['release_seq']<=cutoff]
            assert t['publications'];last=t['publications'][-1]
            if t['end'] is not None and t['end']['seq']>cutoff:t['end']=None
            for key in ['complete_available','u_strict','u_local','raw_row_count','public_sample_count']:
                t[key]=last[key]
            t['ratio_available_seq']=t['end']['seq'] if t['complete_available'] else None
            trials.append(t)
        b['trials']=trials
        complete=len(trials)==2 and all(t['complete_available'] for t in trials)
        if not complete:
            for mode in ['strict','local']:
                b['features_'+mode]=dict(two_trials_complete=False,quantity_comparable=False,
                    price_comparable=False,u1=None,u2=None,b1=None,b2=None,quantity_change=None,
                    pushback_change=None,quantity_weakens=None,price_weakens=None,available_seq=None)
        result.append(b)
    return result


def transform(material: dict, *, cutoff: int | None=None, mirror: float | None=None) -> dict:
    """機能: 原本10段列を変形し、再集計に供する。

    引数: material (dict)、cutoff (int|None)、mirror (float|None)。返り値: 変形原本列 (dict)。
    完成した累積値を操作する方法は使わない。
    """
    m={key:value.copy() for key,value in material.items()}
    if mirror is not None:
        m['bid_prices'],m['ask_prices']=mirror-material['ask_prices'],mirror-material['bid_prices']
        m['bid_qty'],m['ask_qty']=material['ask_qty'].copy(),material['bid_qty'].copy()
    else:
        future=m['release_seq']>cutoff
        m['bid_prices'][future]+=100000.;m['ask_prices'][future]+=100000.
        m['bid_qty'][future]=123456.;m['ask_qty'][future]=654321.
    return m


def mirrored_bands(bands: list[dict], anchor: float) -> list[dict]:
    """機能: 固定帯の価格と方向だけを対称変換し、時刻を動かさない。

    引数: bands (list[dict])、anchor (float)。返り値: 反射帯 (list[dict])。
    """
    result=deepcopy(bands)
    for b in result:b['direction']*=-1;b['price']=anchor-b['price']
    return result


def original_check(material: dict, bands: list[dict]) -> int:
    """機能: 公開標本を原本へ接続し、別実装の旧D/I/u検算を全試行に行う。

    引数: material (dict)、bands (list[dict])。返り値: 照合した試行数 (int)。
    """
    total=0
    for band in bands:
        for t in band['trials']:
            published_reference.verify(t)
            rows=np.searchsorted(material['seq'],[s['seq'] for s in t['samples']])
            assert np.array_equal(material['seq'][rows],[s['seq'] for s in t['samples']])
            side='ask' if band['direction']==1 else 'bid'
            for row,sample in zip(rows,t['samples']):
                if sample['quantity'] is None:continue
                match=material[side+'_prices'][row]==band['price']
                assert match.sum()==1
                q=material[side+'_qty'][row][match][0]
                assert float(q)==sample['quantity']
            total+=1
    return total


def fixture() -> tuple[dict,list[dict]]:
    """機能: 端点一定でも同秒内の減増がある二試行を人工的に作る。

    引数: なし。返り値: 原本列と固定帯 (tuple[dict,list[dict]])。
    """
    seq=np.arange(10,dtype=np.int64);release=np.array([0,3,3,3,6,6,6,9,9,9],np.int64)
    prices=np.repeat(np.arange(101.,111.)[None,:],10,axis=0)
    amounts=np.full((10,10),20.);amounts[:,0]=[10,6,12,10,7,10,10,5,15,10]
    m=dict(seq=seq,time_s=100.+np.floor(seq/3),release_seq=release,
        release_time_s=100.+release/3,release_ready_index=release.copy(),
        ask_prices=prices,bid_prices=prices-11,ask_qty=amounts,bid_qty=amounts.copy())
    loc=lambda i:dict(event_index=i//3,ready_index=i,seq=i,time_s=100.+i/3)
    ts=[]
    for num,start,end in [(1,0,3),(2,6,9)]:
        samples=[dict(**loc(i),quantity=10.,unknown_reason=None,mid=100.5) for i in [start,end]]
        ts.append(dict(number=num,start=loc(start),end=loc(end),complete=True,sample_count=2,
            quantity_known=True,unknown_reasons=['可視減少0'],quantity_start=10.,decrease=0.,
            increase_after_decrease=0.,recovery_ratio=None,maximum_pushback_atr=.1,
            elapsed_seconds=1.,first_decrease=None,samples=samples))
    band=dict(band_id=1,direction=1,price=101.,atr=10.,tick=1.,created=loc(0),terminal=None,
        trials=ts,features=dict(two_trials_complete=True,quantity_comparable=False,price_comparable=True,
            u1=None,u2=None,b1=.1,b2=.1,quantity_change=None,pushback_change=0.,quantity_weakens=None,price_weakens=False))
    return m,[band]


def synthetic() -> dict:
    """機能: 未完早期確定・欠測連結・旧品質流用を人工反例で拒否する。

    引数: なし。返り値: 人工検査結果 (dict)。
    """
    m,b=fixture();base=builder.build(m,b)
    assert base[0]['features_strict']['quantity_comparable']
    assert base[0]['trials'][0]['u_strict']==1.
    for cut in [0,1,2,3,4,5,6,7,8]:
        part=builder.build(m,b,cut);same(part,projected(base,cut))
        alt=builder.build(transform(m,cutoff=cut),b);same(projected(alt,cut),projected(base,cut))
        for band in part:
            for t in band['trials']:
                if not t['complete_available']:assert t['u_strict'] is None and t['u_local'] is None
    old=deepcopy(b);old[0]['trials'][0]['samples'][0]['quantity']=None
    altered=builder.build(m,old)[0]['trials'][0]
    assert altered['u_strict'] is None and altered['u_local']==1.
    absent={k:v.copy() for k,v in m.items()};absent['ask_prices'][1,0]=1000.
    assert builder.build(absent,b)[0]['trials'][0]['u_local'] is None
    zero={k:v.copy() for k,v in m.items()};zero['ask_qty'][:]=10.
    assert builder.build(zero,b)[0]['trials'][0]['u_local'] is None
    before={k:v.copy() for k,v in m.items()};before['ask_qty'][4:6,0]=[999.,1.]
    assert builder.build(before,b)[0]['trials'][1]==base[0]['trials'][1]
    unfinished=deepcopy(b);unfinished[0]['trials'][1]['complete']=False
    assert builder.build(m,unfinished)[0]['trials'][1]['u_local'] is None
    anchor=300.;mirror=builder.build(transform(m,mirror=anchor),mirrored_bands(b,anchor))
    same(mirror,mirrored_bands(base,anchor))
    return dict(全合格=True,prefix数=9,future数=9,reflection数=1,旧品質分離=True,
        欠測連結禁止=True,D0不明=True,試行間差分不混入=True,未来終了で早期確定しない=True,未完比率不明=True,
        旧標本独立人工=published_reference.selftest())


def main() -> None:
    """機能: 全原本26×10固定設定の追加パネルと全因果検査を生成する。

    引数: なし。返り値: なし (None)。旧帯・売買・採否は変更しない。
    """
    cache=pickle.loads((OLD/'band_cache.pkl').read_bytes())
    events=pickle.loads((OLD/'released_depth.pkl').read_bytes())
    inputs=pickle.loads((OUT.parent/'wave_v23/inputs.pkl').read_bytes())
    assert len(cache)==10 and len(events)==len(inputs)==26
    refs=[Path(__file__),OUT/'trial_observation.py',OUT/'published_reference.py',OUT/'設計.md',
          OLD/'band_cache.pkl',OLD/'released_depth.pkl',OLD/'check_band_causality.json',OUT.parent/'wave_v23/inputs.pkl']
    before={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in refs}
    hashes=json.loads((OUT.parent/'wave_v23/入力確認.json').read_text(encoding='utf-8'))['原本SHA256']
    rawhash={f'book/{k[1]}/{k[0]}.jsonl':hashes[f'book/{k[1]}/{k[0]}.jsonl'] for k in inputs}
    assert all(sha(ROOT/p)==h for p,h in rawhash.items())
    protocol=dict(結果後の追加検査=True,旧帯生成変更=False,仕様数=10,入力数=26,全セル数=260,
        cutoff=[.37,.73],品質=['strict旧公開品質維持','local同側P局所品質'],
        原本不明理由件数='原本1行につき排他分類。既知行は不明に含めない',
        比率None理由='未完・原本不明・旧品質・D0は重複するフラグ。足し合わせて試行数にしない',
        比較可能の対象='二試行完了のみ。生比率は終了公開seqまでNone',
        入力SHA256=before,原本SHA256=rawhash,売買再生=False,API取得数=0)
    write('trial_observation_protocol.json',protocol)
    artificial=synthetic();write('trial_observation_synthetic.json',artificial)
    panels={key:{} for key in cache};proofs=[];changes=[];original_trials=0;read_rows=0
    for key,ready in sorted(inputs.items()):
        path=ROOT/f'book/{key[1]}/{key[0]}.jsonl';settings={canonical:group[key] for canonical,group in cache.items()}
        material=builder.read_material(path,settings,events[key]);read_rows+=len(material['seq'])
        cuts=[int(ready['seq'][max(1,int(len(ready['seq'])*fraction))-1]) for fraction in [.37,.73]]
        changed=[transform(material,cutoff=cut) for cut in cuts]
        anchor=float(4*np.nanmax(material['ask_prices'])) if len(material['seq']) else 1.
        reflected=transform(material,mirror=anchor)
        for canonical,bands in settings.items():
            trial_count=original_check(material,bands);original_trials+=trial_count
            panel=builder.build(material,bands);assert len(panel)==len(bands)
            for cut,altered in zip(cuts,changed):
                limited=builder.build(material,bands,cut)
                same(limited,projected(panel,cut))
                future=builder.build(altered,bands)
                same(projected(future,cut),projected(panel,cut))
            mirror=builder.build(reflected,mirrored_bands(bands,anchor))
            same(mirror,mirrored_bands(panel,anchor))
            for old,new in zip(bands,panel):
                for name in ['band_id','direction','price','atr','tick','created','terminal']:
                    assert old[name]==new[name],name
                assert len(old['trials'])==len(new['trials'])
                for a,b in zip(old['trials'],new['trials']):
                    assert a['start']==b['start'] and a['end']==b['end']
                    assert a['complete']==b['complete_available']
                    for pub in b['publications']:
                        assert pub['material_last_seq']==pub['release_seq']
                        assert sum(pub['raw_unknown_reason_counts'].values())<=pub['raw_row_count']
                        if not pub['complete_available']:assert pub['u_strict'] is None and pub['u_local'] is None
                for mode in ['strict','local']:
                    f=new['features_'+mode];before_f=old['features']
                    if f['two_trials_complete']:
                        assert all(f[k]==before_f[k] for k in ['b1','b2','price_weakens','pushback_change'])
                    changes.append(dict(canonical=canonical,session=key[0],symbol=key[1],band_id=old['band_id'],
                        status=old['status'],mode=mode,old_comparable=before_f['quantity_comparable'],
                        new_comparable=f['quantity_comparable'],old_u1=before_f['u1'],old_u2=before_f['u2'],
                        new_u1=f['u1'],new_u2=f['u2'],old_quantity_weakens=before_f['quantity_weakens'],
                        new_quantity_weakens=f['quantity_weakens'],price_weakens=before_f['price_weakens']))
            panels[canonical][key]=panel
            proofs.append(dict(canonical=canonical,session=key[0],symbol=key[1],全合格=True,
                band_count=len(bands),trial_count=trial_count,prefix数=2,future数=2,reflection数=1,
                旧D_I_u独立一致=True,旧時刻価格不変=True))
        print(f'{len(proofs)//10}/26 原本全行・10設定の因果と旧比率一致',flush=True)
    assert len(proofs)==260
    for p,h in {**before,**rawhash}.items():assert sha(ROOT/p)==h,p
    (OUT/'trial_panel.pkl').write_bytes(pickle.dumps(panels,protocol=pickle.HIGHEST_PROTOCOL))
    counts=[]
    for canonical in cache:
        for symbol in ['TOPIX','NK225']:
            for mode in ['strict','local']:
                rows=[r for r in changes if r['canonical']==canonical and r['symbol']==symbol and r['mode']==mode and r['status']=='breakout']
                counts.append(dict(canonical=canonical,symbol=symbol,mode=mode,breakouts=len(rows),
                    old_comparable=sum(r['old_comparable'] for r in rows),new_comparable=sum(r['new_comparable'] for r in rows),
                    gained=sum(not r['old_comparable'] and r['new_comparable'] for r in rows),
                    lost=sum(r['old_comparable'] and not r['new_comparable'] for r in rows),
                    old_joint_weaken=sum(r['old_comparable'] and r['old_quantity_weakens'] and r['price_weakens'] for r in rows),
                    new_joint_weaken=sum(r['new_comparable'] and r['new_quantity_weakens'] and r['price_weakens'] for r in rows)))
    write('trial_observation_changes.json',dict(候補の観測変化=counts,帯別=changes,新規約定数ではない=True,売買再生=False))
    outputs={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in [OUT/'trial_panel.pkl',OUT/'trial_observation_changes.json']}
    result=dict(全合格=True,全セル数=260,入力数=26,仕様数=10,prefix数=520,future数=520,reflection数=260,
        原本読取対象行数=read_rows,旧標本の独立照合試行数=original_trials,検査=proofs,人工検査=artificial,
        参照SHA256=before,原本SHA256=rawhash,原本不変=True,出力SHA256=outputs,
        売買再生=False,API取得数=0,現在保存物使用=False)
    write('trial_observation_audit.json',result)
    print(dict(全合格=True,全セル数=260,原本読取対象行数=read_rows,独立照合試行数=original_trials),flush=True)


if __name__=='__main__':main()
