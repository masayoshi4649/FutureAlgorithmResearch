"""方向予測なし60条件を保存23場へ適用し、過去区間だけで選ぶ。"""
from pathlib import Path
import importlib.util
import sys
import socket
import json
import hashlib
import pickle
import gzip
from design import HERE,catalog,freeze
from policy import execute

ROOT=HERE.parents[2]
# 他のresearch/designという短名へ依存させず、96探索の会計関数だけを複製名で参照する。
SEARCH=HERE.parent/'search'
spec=importlib.util.spec_from_file_location('独立探索会計参照',SEARCH/'research.py')
reference=importlib.util.module_from_spec(spec)
saved=sys.modules.get('design')
searchspec=importlib.util.spec_from_file_location('独立探索条件参照',SEARCH/'design.py')
searchdesign=importlib.util.module_from_spec(searchspec);searchspec.loader.exec_module(searchdesign)
sys.modules['design']=searchdesign
spec.loader.exec_module(reference)
if saved is None:sys.modules.pop('design',None)
else:sys.modules['design']=saved


def save(name: str,value: object) -> None:
    """機能: 今回の注文管理領域だけへJSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    path=HERE/name;path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2).encode('utf8')
    path.write_bytes(gzip.compress(data,mtime=0) if path.suffix=='.gz' else data)


def read(name: str) -> object:
    """機能: 保存済み今回成果を読む。

    引数: name(str)。返り値: 保存値(object)。
    """
    path=HERE/name;data=path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix=='.gz' else data)


def load() -> dict:
    """機能: 因果監査済み原本行の価格と当該行ATRだけを読み込む。

    引数: なし。返り値: 46入力(dict)。
    """
    inputs={}
    for i,source in enumerate(reference.SOURCES):
        path=ROOT/source/('inputs.pkl' if i==0 else 'new_inputs.pkl')
        found=pickle.loads(path.read_bytes())
        assert not(set(found)&set(inputs))
        inputs.update({k:{f:row[f] for f in reference.FIELDS} for k,row in found.items()})
    assert len(inputs)==46
    return inputs


def main() -> None:
    """機能: 事前固定・原本逐次再生・過去選択・期間別会計を実行する。

    引数: なし。返り値: なし(None)。
    """
    socket.socket.connect=reference.deny;socket.create_connection=reference.deny
    freeze();inputs=load();names=sorted({k[0] for k in inputs});assert len(names)==23
    all_rows={}
    for config in catalog():
        rows=[];ledgers=[]
        for key,ready in sorted(inputs.items()):
            trades,orders,state,legs=execute(config,ready)
            row=reference.summary(key,trades,float(state[13]));row['cycles']=int(state[9]);rows.append(row)
            assert sum(legs[:,0])==0
            assert abs(row['net']-state[11])<1e-7
            ledgers.append(dict(session=key[0],symbol=key[1],trades=trades.tolist(),orders=orders.tolist()))
        all_rows[config['id']]=rows
        save('sessions/'+config['id']+'.json',rows);save('ledgers/'+config['id']+'.json.gz',ledgers)
        print(config['id']+' 再生完了',flush=True)
    periods={'開発10':names[:10],'期間外9':names[10:19],'原因既読4':names[19:],'全23':names}
    values={identifier:{label:{symbol:reference.totals(rows,chosen,symbol) for symbol in ('TOPIX','NK225')} for label,chosen in periods.items()} for identifier,rows in all_rows.items()}
    ranking=sorted([(reference.score(rows,names[:10]),identifier) for identifier,rows in all_rows.items()],reverse=True)
    selected=[]
    for family in range(3):
        ids={s['id'] for s in catalog() if s['family']==family}
        selected.append(next(identifier for _,identifier in ranking if identifier in ids))
    save('結果一覧.json',values)
    save('過去10場選択.json',dict(第一候補=ranking[0][1],系統代表=selected,順位=[dict(id=i,score=s) for s,i in ranking],真正未見=False))
    walk=[]
    for index in range(10,len(names)):
        identifier=max(all_rows,key=lambda v:reference.score(all_rows[v],names[:index]))
        walk.append(dict(session=names[index],id=identifier,参照最終=names[index-1],rows=[r for r in all_rows[identifier] if r['session']==names[index]]))
    save('過去逐次選択.json',dict(選択=walk,集計={symbol:reference.totals([r for w in walk for r in w['rows']],names[10:],symbol) for symbol in ('TOPIX','NK225')}))
    save('完了.json',dict(再生完了=True,全場数=23,候補数=60,口座数=2760,原本行数=sum(len(v['seq']) for v in inputs.values()),API取得数=0,
                         対象=names,第一候補=ranking[0][1],系統代表=selected,実装SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}))


if __name__=='__main__':main()
