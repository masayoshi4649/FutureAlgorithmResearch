"""全33入力保存後のJSON件数型だけを、旧入力再読なしで補完する。"""

from collections import Counter
import hashlib
import pickle

import numpy as np

import common
import prepare


def run() -> None:
    """
    機能: 完成済み新33cacheを各一読し、件数のPython int正規化を束縛する。
    引数: なし。
    返り値: None。旧E01cache/NPZ/Q/API/金融は再読・実行しない。
    """
    fixed=common.read(common.HERE/'入力測定前の固定.json')
    archive=common.HERE/'初回入力_件数形式False保持'
    previous=(archive/'prepare.py').read_text(encoding='utf-8')
    expected=previous.replace('公開許可数=sum(decisions)','公開許可数=int(sum(decisions))')
    expected=expected.replace('公開許可買=sum(ok and o[3]>0 for ok,o in zip(decisions,entries))','公開許可買=int(sum(ok and o[3]>0 for ok,o in zip(decisions,entries)))')
    expected=expected.replace('公開許可売=sum(ok and o[3]<0 for ok,o in zip(decisions,entries))','公開許可売=int(sum(ok and o[3]<0 for ok,o in zip(decisions,entries)))')
    assert expected==(common.HERE/'prepare.py').read_text(encoding='utf-8')
    for name in ('engine.py','order_kernel.py','daily.py','interface.py','policy.py','votes.py','catalog.py','runner.py'):
        assert (archive/name).read_bytes()==(common.HERE/name).read_bytes(),name
    art=common.read(common.HERE/'E01公開maskとUID料金及び接頭の人工検査.json')
    assert art['全合格'] and art['source_SHA256']==common.sources()
    source=common.sources();caches={};summaries={};read_count=0
    for session in fixed['sessions']:
        path=common.HERE/f'input/{session}.pkl.gz';saved=path.read_bytes();read_count+=1
        packet=pickle.loads(common.gzip.decompress(saved));assert packet['session']==session
        caches[session]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=hashlib.sha256(saved).hexdigest())
        summaries[session]={}
        for symbol,a in packet['accounts'].items():
            for n in ('seq','time_s'):np.testing.assert_array_equal(a['record'][n],a['quotes'][n])
            entries={int(o[0]) for o in a['feed'] if o[7]==1}
            for values in a['trade_features'].values():assert set(values)==entries
            summaries[session][symbol]={f'{w}_{mode}':prepare.activity(a,w,mode) for w in (10,30,60) for mode in ('CONFIRM','VETO')}
    assert read_count==33 and common.sources()==source
    total={}
    for symbol in ('TOPIX','NK225'):
        total[symbol]={}
        for key in summaries[fixed['sessions'][0]][symbol]:
            rows=[summaries[s][symbol][key] for s in fixed['sessions']]
            total[symbol][key]={k:sum(v[k] for v in rows) for k in rows[0] if k!='不明理由'}
            total[symbol][key]['公開許可あり場数']=sum(v['公開許可数']>0 for v in rows)
            total[symbol][key]['不明理由']=dict(sum((Counter(v['不明理由']) for v in rows),Counter()))
    proof=dict(全合格=True,原因='活動件数のnumpy整数直列化だけ。元33cache作成は完了していた。',
        初回FalseSHA256=common.digest(common.HERE/'入力準備False.json'),初回sourceと固定保持=True,
        原入力作成source_SHA256=fixed['source_SHA256'],補完source_SHA256=source,
        数学同値='prepare.activityの件数int化3箇所のみ。票・engine・料金・条件のexact bytes不変更。',
        原E01cache読取=0,原NPZ読取=0,Q読取=0,完成新cache読取=33,新金融=0,原book=0,API=0)
    common.write(common.HERE/'全33入力の末尾件数形式補完.json',proof)
    common.write(common.HERE/'全33場のE01取引更新準備.json',dict(全合格=True,sessions=fixed['sessions'],cache=caches,
        activity=summaries,aggregate=total,source_SHA256=source,原入力作成source_SHA256=fixed['source_SHA256'],
        開始終端source一致=True,初回source範囲='初回全33の原行normal照合後source不変assertまで完了。最後のJSON保存のみ失敗。',
        事前固定SHA256=common.digest(common.HERE/'入力測定前の固定.json'),
        一致検査={'旧E01cache一読':33,'原行NPZ一読':66,'原行normal一致':198},Q資料一読=1,
        追加旧入力読取=0,補完新cache読取=33,件数補完SHA256=common.digest(common.HERE/'全33入力の末尾件数形式補完.json'),
        原paper再計算=0,新金融=0,原book=0,API=0))
    print('完成33cacheから件数形式を補完、旧入力再読0、金融0',flush=True)


if __name__=='__main__':run()
