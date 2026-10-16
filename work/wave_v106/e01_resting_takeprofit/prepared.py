"""保存GUの最初実新規だけと同normal気配を一読準備し、原出口を渡さない。"""

from collections import Counter
import gzip
import hashlib
import pickle
import numpy as np
import common
import policy


def load(item: dict) -> dict:
    """
    機能: 保存cache又は台帳を同bytes一回で読取り、固定済み指紋を照合する。
    引数: item(dict)はroot相対path/SHA256。
    返り値: dictは保存値。原板・原NPZ・API・注文再生をしない。
    """
    path=common.ROOT/item['path'];assert path.resolve().is_relative_to(common.ROOT/'work')
    saved=path.read_bytes();assert hashlib.sha256(saved).hexdigest()==item['SHA256']
    return pickle.loads(gzip.decompress(saved))


def fix() -> None:
    """
    機能: 小目録と人工の指紋・最初新規抽出目的を大型資料読取前に固定する。
    引数: なし。
    返り値: None。GU132/input33の本文はまだ読まない。
    """
    gp=common.ROOT/'work/wave_v106/e01_trade_gate/finance/結果.json'
    ip=common.ROOT/'work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json'
    gu,meta=common.read(gp),common.read(ip);art=common.read(common.HERE/'常設利確と次気配返済の人工検査.json')
    assert gu['全合格'] and meta['全合格'] and art['全合格'] and gu['sessions']==meta['sessions']
    assert art['source_SHA256']==common.source_hashes()
    refs={}
    for mode in ('CONFIRM','VETO'):
        ident=f'E01_TRADE_W60_{mode}_D0_GU';case=gu['results'][ident]
        assert len(case['ledgers'])==66
        refs[mode]={i['session']+'|'+i['symbol']:i for i in case['ledgers']}
    common.write(common.HERE/'入力読取前の固定.json',dict(全合格=True,sessions=meta['sessions'],GU=refs,input_cache=meta['cache'],
        source_SHA256=common.source_hashes(),人工SHA256=common.digest(common.HERE/'常設利確と次気配返済の人工検査.json'),
        小資料=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in (gp,ip)],
        読取目的='GU132は最初の実new order/UIDだけを原seqの最小fill順で取得。future勝敗・原返済・後続新規は選抜/金融へ使用しない。input33は同normal quote/record/Uquietだけを保存。',
        GU一読=132,input一読=33,原NPZ=0,新金融=0,API=0))


def run() -> None:
    """
    機能: 固定目的の保存GU132とinput33を各一読し、一場一親の新入力へ射影する。
    引数: なし。
    返り値: None。新損益・利確成否を計算せず、元GU出口を新入力へ保存しない。
    """
    fixed=common.read(common.HERE/'入力読取前の固定.json');assert fixed['source_SHA256']==common.source_hashes()
    assert not (common.HERE/'最初実新規と場内返済の全33入力.json').exists()
    caches={};counts=Counter();activity={}
    for session in fixed['sessions']:
        packet=load(fixed['input_cache'][session]);counts['input一読']+=1
        fresh=dict(session=session,accounts={});activity[session]={}
        for symbol in policy.QUANTITY:
            old=packet['accounts'][symbol];q=old['quotes'];record=old['record'];n=len(q['bid'])
            assert q['time_s'][-1]>=record['limit']
            for name in ('seq','time_s'):np.testing.assert_array_equal(q[name],record[name])
            own=dict(session=session,symbol=symbol,quotes=q,record=record,quiet=old['quiet'],quiet_force=old['quiet_force'],
                quiet_windows=old['quiet_windows'],entries={})
            activity[session][symbol]={}
            for mode in ('CONFIRM','VETO'):
                gu=load(fixed['GU'][mode][session+'|'+symbol]);counts['GU一読']+=1
                indices=np.flatnonzero(gu['orders'][:,7]==1)
                entry=None
                if len(indices):
                    ix=int(indices[0]);o=gu['orders'][ix].copy();row=int(o[0]);decision=int(o[1])
                    assert row==min(int(gu['orders'][j,0]) for j in indices)
                    assert int(o[4])==policy.QUANTITY[symbol] and policy.valid(q)[row]
                    assert o[5]==q['ask' if o[3]>0 else 'bid'][row] and 0<=decision<row<n
                    assert not own['quiet'][row] and not own['quiet_force'][row] and q['time_s'][row]<record['limit']
                    entry=dict(order=o,uid=int(gu['order_uids'][ix]),fill_raw_seq=int(q['seq'][row]),
                        decision_raw_seq=int(q['seq'][decision]),fill_price_time_s=float(q['time_s'][row]),
                        decision_price_time_s=float(q['time_s'][decision]),選抜='原order配列の最初実new。将来勝敗参照なし。')
                own['entries'][mode]=entry;activity[session][symbol][mode]=int(entry is not None)
                del gu
            fresh['accounts'][symbol]=own
        path=common.HERE/f'input/{session}.pkl.gz';common.write(path,fresh)
        caches[session]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path))
        print(session+' 最初実新規入力準備',flush=True)
    assert counts==Counter(input一読=33,GU一読=132) and common.source_hashes()==fixed['source_SHA256']
    common.write(common.HERE/'最初実新規と場内返済の全33入力.json',dict(全合格=True,sessions=fixed['sessions'],cache=caches,
        source_SHA256=common.source_hashes(),事前固定SHA256=common.digest(common.HERE/'入力読取前の固定.json'),
        activity=activity,read_counts=dict(counts),新金融=0,原NPZ=0,API=0))
