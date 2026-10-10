"""固定条件の全集合を結び、未完備の探索を正式結果へ進めない。"""

from __future__ import annotations

import pickle
import numpy as np
import runner
import assessment
import trade_statistics as statistics


def verify() -> tuple[dict,dict]:
    """機能: 240条件・全6240口座・960因果と各保存指紋を照合する。

    引数: なし。返り値: 経済判定・完備証跡 (tuple[dict,dict])。未知での成功は宣言しない。
    """
    here,root=runner.HERE,runner.ROOT
    fixed=runner.read(here/'探索条件の固定.json')
    done=runner.read(here/'主再生の完了.json')
    fixed_sha=runner.digest(here/'探索条件の固定.json')
    assert done['全独立会計合格'] and done['固定SHA256']==fixed_sha
    assert (done['全条件数'],done['全入力数'],done['因果入力数'])==(240,6240,960)
    refs={}
    for mapping in (fixed['実装と入力SHA256'],fixed['原本78SHA256'],done['参照SHA256']):
        for relative,sha in mapping.items():
            assert runner.digest(root/relative)==sha,relative
            refs[relative]=sha
    inputs=pickle.loads((here.parent/'wave_v23/inputs.pkl').read_bytes())
    keys=set(inputs);sessions=sorted({k[0] for k in keys});assert len(keys)==26 and len(sessions)==13
    lengths={k:len(v['seq']) for k,v in inputs.items()};del inputs
    specs=fixed['主条件']+fixed['補助条件'];assert len(specs)==240
    expected={s['id'] for s in specs}
    index=runner.read(here/'全条件の期間集計.json.gz');assert set(index)==expected
    account_count=causal_count=rows_count=0
    for spec in specs:
        identifier=spec['id'];summary=runner.read(here/'summaries'/(identifier+'.json'))
        assert summary==index[identifier] and summary['spec']==spec and summary['固定SHA256']==fixed_sha
        certificate=runner.read(here/'completed'/(identifier+'.json'))
        assert certificate['id']==identifier and certificate['spec']==spec and certificate['固定SHA256']==fixed_sha
        paths={(here/folder/(identifier+suffix)).relative_to(root).as_posix()
            for folder,suffix in (('sessions','.json.gz'),('ledgers','.json.gz'),('responses','.json.gz'),('audits','.json.gz'),('summaries','.json'))}
        assert set(certificate['保存SHA256'])==paths
        assert all(done['参照SHA256'][path]==certificate['保存SHA256'][path] for path in paths)
        rows=runner.read(here/'sessions'/(identifier+'.json.gz'))
        ledger=runner.read(here/'ledgers'/(identifier+'.json.gz'))
        response=runner.read(here/'responses'/(identifier+'.json.gz'))
        proof=runner.read(here/'audits'/(identifier+'.json.gz'))
        for values in (rows,ledger,response,proof['検査']):
            assert len(values)==26 and {(r['session'],r['symbol']) for r in values}==keys
        assert proof['id']==identifier and proof['全独立会計合格']
        assert proof['全入力数']==26 and proof['因果入力数']==4 and proof['全原本行数']==sum(lengths.values())
        for item in proof['検査']:
            key=(item['session'],item['symbol'])
            assert item['原本行数']==lengths[key]
            assert item['全注文の成立脱落一致'] and item['全原本行会計一致'] and item['場内返済']
            assert item['API取得数']==0
            if key[0] in ('2026-09-24_Night','2026-09-29_Day'):
                for field in ('過去部分一致','未来改変一致','上下反射一致'):assert item['代表因果'][field]
                assert item['代表因果']['prefix行']==int(lengths[key]*.37)
                assert item['代表因果']['future行']==int(lengths[key]*.73)
                causal_count+=1
            else:assert '代表因果' not in item
            account_count+=1;rows_count+=lengths[key]
        for item in ledger:
            key=(item['session'],item['symbol']);array_shapes=item['全結果指紋']
            assert set(array_shapes)=={'orders','trades','curve','stats'}
            for name,width in (('orders',7),('trades',10)):
                values=np.asarray(item[name],float).reshape((-1,width))
                assert runner.fingerprint(values)==array_shapes[name]
            assert runner.fingerprint(np.asarray(item['stats'],float))==array_shapes['stats']
            assert array_shapes['curve']['shape']==[lengths[key],4]
            assert item['入口パルス指紋']['shape']==[lengths[key]]
            assert item['stats'][5]==item['stats'][6]==0
            if key[0] in sessions[:2]:assert len(item['orders'])==len(item['trades'])==0
        for symbol in ('TOPIX','NK225'):
            assert statistics.aggregate([r for r in rows if r['symbol']==symbol])==summary['symbols'][symbol]
        for name in ('completed',):
            path=here/name/(identifier+'.json');refs[path.relative_to(root).as_posix()]=runner.digest(path)
    assert (account_count,causal_count)==(6240,960) and rows_count==done['全原本行会計数']
    verdict=assessment.assess(index)
    for name in ('探索条件の固定.json','主再生の完了.json','全条件の期間集計.json.gz','complete.py'):
        path=here/name;refs[path.relative_to(root).as_posix()]=runner.digest(path)
    proof=dict(検証完了=True,全条件数=240,全会計入力数=account_count,全原本行会計数=rows_count,
        因果入力数=causal_count,全原本場内返済=True,初期2学習専用確認=True,
        固定SHA256=fixed_sha,参照資料SHA256=refs,ガードSHA256=runner.digest(here/'complete.py'),
        現在API取得数=0,保存ライブ使用=False,未知での有効性確認=False,全体目標達成=False)
    return verdict,proof


def main() -> None:
    """機能: 全証拠が一致した場合だけ正式な経済判定を保存する。

    引数: なし。返り値: なし (None)。未完成を成功扱いしない。
    """
    verdict,proof=verify()
    runner.save(runner.HERE/'assess_results.json',verdict)
    path=runner.HERE/'assess_results.json';proof['参照資料SHA256'][path.relative_to(runner.ROOT).as_posix()]=runner.digest(path)
    runner.save(runner.HERE/'完備監査.json',proof)
    print('全240条件・6240入力・960因果の保存照合完了。既知経済基準と未知の有効性を区別。',flush=True)


if __name__=='__main__':main()
