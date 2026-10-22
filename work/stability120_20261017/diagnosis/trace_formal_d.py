"""最終dの監査所有二場だけから、固定実注文の反復損失を記述する。"""

from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent/'formal_d'
ROOT=HERE.parents[3]


def main() -> None:
    """
    機能: COST_LAST最悪二場を一読保全し、既存の独立追加・停止記述関数で診断する。
    引数: なし。
    返り値: None。数値エンジン・元cache・市場・金融再生は実行しない。
    """
    spec=importlib.util.spec_from_file_location('保存信用追加の診断',HERE.parent/'trace_formal_c.py')
    reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
    helper=reference.saved_helper()
    plan=json.loads((HERE/'COST_LAST最悪二場の監査所有copyを各一読する目録.json').read_text(encoding='utf8'))
    small=json.loads((HERE/'Last基準二十四小会計と中値c同条件の比較.json').read_text(encoding='utf8'))
    scenes=[];logs=[]
    for item in plan['inputs']:
        data=(ROOT/item['owned_path']).read_bytes();assert hashlib.sha256(data).hexdigest()==item['sha256']
        copy=HERE/'owned'/item['symbol']/(item['session']+'.npz');copy.parent.mkdir(parents=True,exist_ok=True)
        assert not copy.exists();copy.write_bytes(data)
        with np.load(BytesIO(data),allow_pickle=False) as src:
            q={k:src['quotes__'+k].copy() for k in ('row','time','last','bid','ask')}
            orders=src['orders'];orders=orders[orders[:,0]==item['policy_index'],1:].copy()
            lots=src['lots'];lots=lots[lots[:,0]==item['policy_index'],1:].copy()
        row=item['selected_row'];columns=small['columns'];ld=[dict(zip(columns['lot_columns'],x)) for x in lots]
        assert sum(x['net'] for x in ld)==row['net'] and len(ld)==row['closed_lots']
        extra=reference.extra(orders,lots,q,row,columns,helper)
        start,close,end=helper.scene_times(item['session'])
        good=np.isfinite(q['time'])&(q['time']>=start)&(q['time']<=end)&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['bid']<=q['ask'])
        accepted=np.flatnonzero(good&(q['time']>=np.maximum.accumulate(np.where(good,q['time'],-np.inf))))
        neworders=[dict(zip(columns['order_columns'],x)) for x in orders if x[1]==1]
        contrary=0
        for o in neworders:
            idx=int(np.searchsorted(q['row'][accepted],o['decision_row']));assert idx>0
            i,j=accepted[idx],accepted[idx-1];side=o['side']
            assert side*(q['last'][i]-q['last'][j])>0
            mid=(q['bid'][i]+q['ask'][i])/2;previous=(q['bid'][j]+q['ask'][j])/2
            contrary+=int(side*(mid-previous)<=0)
        scenes.append(dict(symbol=item['symbol'],session=item['session'],row=row,credit_and_stop=extra,
            entry_Last_direction_verified=len(neworders),entry_mid_flat_or_opposite=contrary))
        logs.append(dict(path=item['owned_path'],SHA256=item['sha256'],reads=1))
    out=HERE/'Last基準最悪二場の反復停止と実追加及び追尾未起動損失.json';assert not out.exists()
    value=dict(全合格=True,結果SHA256=small['結果SHA256'],source_SHA256=small['source_SHA256'],scenes=scenes,read_log=logs,
        元結果原本追加読取=0,原measurement_cache読取=0,原市場読取=0,原prepared読取=0,金融再生=0,
        留保='観測Last起点への変更であり完全約定テープではない。新しい条件の救済利益や未知成功を算出しない。')
    out.write_text(json.dumps(helper.clean(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(helper.clean({'全合格':True,'診断':[{k:s[k] for k in ('symbol','session','row','credit_and_stop')} for s in scenes]}),ensure_ascii=False)[:1800])


if __name__=='__main__':main()
