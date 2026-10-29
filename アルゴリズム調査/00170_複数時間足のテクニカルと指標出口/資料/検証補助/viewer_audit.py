"""Viewer約定正本から独立に保有と損益を再計算する。"""
import json
from pathlib import Path


def main():
    """
    機能: 所有ID、数量、売買原行、会計とViewer参照先を照合する。
    引数: なし。
    返り値: None。不一致は例外とし、別手法を選ばない。
    """
    here=Path(__file__).resolve().parent;study=here.parents[1]/'アルゴリズム調査/00170_複数時間足のテクニカルと指標出口'
    catalog=json.loads((study/'比較.resources.json').read_text(encoding='utf-8'))
    details=json.loads((here/'details-summary.json').read_text(encoding='utf-8'))
    rows={(r['symbol'],r['session'],r['config_id']):r for r in details['results']}
    seen=set();fills=0;bytes_total=0
    for resource in catalog['resources']:
        key=(resource['symbol'],resource['session'],resource['id'].split('/')[-1]);r=rows[key]
        assert key not in seen;seen.add(key)
        assert resource['method_id']==r['method_id']
        path=study/resource['pnl_path'];bytes_total+=path.stat().st_size
        positions={};profit=loss=0;entry_qty=close_qty=0;lastline=0
        for raw in path.read_text(encoding='utf-8').splitlines():
            t=json.loads(raw);fills+=1
            assert t['method_id']==r['method_id']
            assert t['source_line']>t['decision_line'] and t['source_line']>=lastline
            assert t['qty']>0 and not t.get('proxy',False);lastline=t['source_line']
            if t['type'] in ['LongN','ShortN']:
                assert t['position_id'] not in positions
                positions[t['position_id']]=[t['price'],t['qty'],1 if t['type']=='LongN' else -1];entry_qty+=t['qty']
            else:
                assert t['type'] in ['LongR','ShortR']
                p=positions[t['position_id']];assert t['qty']<=p[1]
                assert (p[2]==1 and t['type']=='LongR') or (p[2]==-1 and t['type']=='ShortR')
                pl=(t['price']-p[0])*p[2]*t['qty']*resource['point_value'];profit+=max(pl,0);loss+=max(-pl,0)
                p[1]-=t['qty'];close_qty+=t['qty']
                if p[1]==0:del positions[t['position_id']]
        assert not positions
        assert entry_qty==r['new_qty'] and close_qty==r['closed_qty']
        assert abs(profit-r['gross_profit_yen'])<0.001 and abs(loss-r['gross_loss_yen'])<0.001
    assert seen==set(rows)
    value={'判定':'一致','リソース数':len(seen),'約定片数':fills,'約定JSONL合計バイト':bytes_total,'検査':'所有ID別数量と売買原行順・判断次行・商品倍率・独立会計・全残玉ゼロ・目録参照先','原板の複製':False}
    (study/'表示資料監査.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(value,ensure_ascii=False))


if __name__=='__main__':main()
