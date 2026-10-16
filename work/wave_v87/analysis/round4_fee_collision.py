"""初めて追加する固定条件で、旧料金辞書の上書きを原注文から確認する。"""
from pathlib import Path
from collections import defaultdict
import importlib.util
import json
import sys
import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def module(name,path):
    """
    機能: 凍結済み実装を変更せず読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def main():
    """
    機能: 固定J1_Nの実口座で最初に現れる返済料金配賦衝突を記録する。
    引数: なし。
    返り値: None。戦略条件の追加・順位選定は行わない。
    """
    runner=module('wave87_round4_research',HERE.parent/'round4/research.py')
    fixed=runner.old.read(runner.FIXED);runner.validate(fixed)
    inputs,signals,hashes=runner.prepare.load_inputs(verify=True)
    strategy=runner.strategy_module();features=strategy.initialize(inputs,signals)
    config=next(c for c in fixed['catalog'] if c['id']=='J1_N')
    evidence=[]
    for model in ('observed','specified'):
        for key,ready in sorted(inputs.items()):
            if ready['symbol']!='TOPIX':continue
            result,settings=strategy.play(config,ready,features[key],observed=model=='observed')
            orders=result['orders'];trades=result['trades']
            fee=np.floor(orders[:,4]*41.8+1e-8)
            groups=defaultdict(list)
            for order_no,(o,f) in enumerate(zip(orders,fee)):
                if o[7]==0:groups[int(o[2]),int(o[0])].append((order_no,o,float(f)))
            collisions=[]
            for (cid,row),records in groups.items():
                if len(records)<=1:continue
                proper=sum(f for _,o,f in records)
                allocated=sum(o[4] for _,o,f in records)*records[-1][2]/records[-1][1][4]
                if abs(proper-allocated)<1e-8:continue
                selected=trades[(trades[:,0]==cid)&(trades[:,7]==row)]
                collisions.append(dict(組=cid,返済行=row,返済原本行=int(ready['seq'][row]),
                    代理時刻=float(ready['time_s'][row]),正しい返済注文料=proper,
                    旧辞書配賦料=float(allocated),誤差=float(allocated-proper),
                    注文=[dict(注文番号=no,原配列=o.tolist(),料金=f) for no,o,f in records],
                    決済脚原配列=selected.tolist()))
            if collisions:
                evidence.append(dict(model=model,session=ready['session'],symbol=ready['symbol'],
                    条件=config['id'],同時返済料金衝突=collisions))
                break
    assert len(evidence)==2
    runner.validate(fixed)
    out=dict(原因='親組と返済行のみの辞書キーが別注文を上書きする。数量別の切捨て料率が違う場合、全脚への配賦と実注文料が一致しない。',
        検証範囲='固定済J1_Nの両約定モデルについて最初の実衝突口座のみ再生。新条件・閾値の探索なし。売買コアは変更せず、会計失敗した出力を成績として使用しない。',
        必要修正='返済注文を順序付きで数量消費し、それぞれの注文料を対応決済脚へ配賦する。',
        取引実装SHA256=fixed['code_SHA256'],証拠=evidence)
    path=HERE/'第四段階の実注文における料金配賦衝突.json'
    path.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps([dict(model=x['model'],session=x['session'],衝突数=len(x['同時返済料金衝突']),
        料金差額=sum(c['誤差'] for c in x['同時返済料金衝突'])) for x in evidence],ensure_ascii=False),flush=True)


if __name__=='__main__':main()
