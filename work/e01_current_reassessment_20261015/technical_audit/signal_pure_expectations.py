"""完成実装を呼ぶ前に、根の入口境界を独立人工の期待へ固定する。"""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import traceback

import signal_reference as R

HERE=Path(__file__).resolve().parent
OUTPUT=HERE/'突破と反対活動の入口状態の独立純期待.json'


def base() -> list[R.Observation]:
    """
    機能: 既知Lから突破・一気配進行・新反対票・二気配再進行の人工を作る。
    引数: なし。
    返り値: list[Observation] は根仕様の最小人工。実価格を使わない。
    """
    points=[]
    for row,(bid,ask) in enumerate(((98,99),(101,102),(102,103),(104,105),(105,106))):
        points.append(R.Observation(row,0,0,100.,95.,float(bid),float(ask),new_down=1 if row==2 else 0))
    return points


def fixtures() -> dict[str,tuple[list[R.Observation],list[tuple[int,int]]]]:
    """
    機能: 別行認定・未知・逆行・基準再取得・消費・再武装を手指定期待で分ける。
    引数: なし。
    返り値: dict は名称と人工列/期待(row,mode)。owner源から期待を生成しない。
    """
    result={}
    p=base();result['基本の突破と反対活動']=(p,[(2,0),(2,1),(3,2)])
    p=base();p[1]=replace(p[1],new_down=1);p[2]=replace(p[2],new_down=0)
    result['突破rowの新反対票は採らない']=(p,[(2,0),(2,1)])
    p=base();p[2]=replace(p[2],price_known=False,price_gate=(False,False));p[3]=replace(p[3],bid=103.,ask=104.);p[4]=replace(p[4],bid=104.,ask=105.)
    result['価格未知で③終了し①は継続②だけ再取得']=(p,[(2,0),(4,1)])
    p=base();p[2]=replace(p[2],normal=False);p[3]=replace(p[3],bid=103.,ask=104.);p[4]=replace(p[4],bid=104.,ask=105.)
    result['非正常で③終了し①②だけ再取得']=(p,[(4,0),(4,1)])
    p=[R.Observation(row,0,0,100.,95.,float(b),float(a),new_down=1 if row==4 else 0)
       for row,(b,a) in enumerate(((98,99),(104,105),(102,103),(103,104),(103,104),(105,106)))]
    result['③逆行超過後にLへ戻らずB0取り直し不可']=(p,[(5,0),(5,1)])
    p=[R.Observation(row,0,0,100.,95.,float(b),float(a),new_down=1 if row==2 else 0)
       for row,(b,a) in enumerate(((98,99),(103,104),(102,103),(104,105)))]
    result['逆行ちょうど一呼値は許容']=(p,[(3,0),(3,1),(3,2)])
    p=base()[:4]+[R.Observation(row,0,0,100.,95.,float(b),float(a),new_down=1 if row==6 else 0)
       for row,(b,a) in enumerate(((99,100),(101,102),(102,103),(104,105)),4)]
    result['両BBOがL反対側へ戻った後の再武装']=(p,[(2,0),(2,1),(3,2),(6,0),(6,1),(7,2)])
    p=base()[:4]+[R.Observation(row,1,4,100.,95.,float(b),float(a),new_down=1 if row==6 else 0)
       for row,(b,a) in enumerate(((101,102),(101,102),(102,103),(104,105)),4)]
    result['同じ値のLでも新確定bucketへ切替再武装']=(p,[(2,0),(2,1),(3,2),(6,0),(6,1),(7,2)])
    p=[R.Observation(row,0,0,100.,95.,float(b),float(a),new_down=1 if row==2 else 0)
       for row,(b,a) in enumerate(((98,99),(101,103),(102,103),(102,104),(104,105)))]
    result['片気配だけの進行では公開しない']=(p,[(3,0),(3,1),(4,2)])
    p=base();p[2]=replace(p[2],interval_known=False)
    result['新票下限が既知連続でなければ③に使わない']=(p,[(2,0),(2,1)])
    p=base();p[2]=replace(p[2],volume_gate=(False,False))
    result['突破時でなく現在認定rowで情報資格を要求']=(p,[(3,0),(3,1),(3,2)])
    p=base();p.extend([replace(p[-1],row=row,bid=106.+row,ask=107.+row,new_down=1) for row in range(5,9)])
    result['公開後拒否や失効でも同episode再公開無し']=(p,[(2,0),(2,1),(3,2)])
    p=base();p[0]=replace(p[0],high=float('nan'),low=float('nan'),bucket=-1)
    result['空Lを未来水準で補わない']=(p,[(2,0),(2,1),(3,2)])
    return result


def main() -> None:
    """
    機能: 売買鏡像と全接頭の純期待を保存し、owner源の合格とは分ける。
    引数: なし。
    返り値: None。実金融・元cache・owner source importを行わない。
    """
    assert not OUTPUT.exists()
    count=0;cases={}
    for name,(points,expected) in fixtures().items():
        events,state=R.run(points,1.)
        assert [(e['row'],e['mode']) for e in events]==expected,name
        count+=1
        reverse,_=R.run([R.mirror(p) for p in points],1.)
        assert [(e['row'],e['mode']) for e in reverse]==expected,name+' 売り鏡像'
        assert all(e['side']==1 for e in events) and all(e['side']==-1 for e in reverse)
        count+=1
        for length in range(1,len(points)+1):
            prefix,_=R.run(points[:length],1.)
            assert prefix==[e for e in events if e['row']<length],name+' 接頭'
            count+=1
        for e in events:
            assert e['confirmed']<e['break_row']<e['row']
            if e['mode']==2:
                assert e['break_row']<e['opposite_row']<e['row'] and e['opposite_lower']>=1
            count+=1
        groups={}
        for e in events:
            key=(e['episode'],e['mode'])
            assert key not in groups,name+' 同episode二重公開'
            groups[key]=True
            count+=1
        cases[name]=dict(期待row_mode=[list(x) for x in expected],買い=events,売り=reverse)
    value=dict(全合格=True,状態='根の仕様に基づく独立純期待。owner signal/native/正式specとの接続はまだ未完了。',
        検査数=count,case_count=len(cases),cases=cases,
        source_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'signal_reference.py',Path(__file__))},
        根裁定='③はB0取得後の正常/必要known切断又は>1T逆行でepisode内終了。①②のみ取消後B0再取得を許す。突破rowの反対票は使わない。',
        金融前の仕様精密化='取消後B0再取得を全modeに許す初稿との違いを、未金融の根裁定として保持。裁定前純参照はarchive/B0再取得裁定前の純参照。',
        新二場='本作業ではstatのみ・本文未読。過去全試行の既読有無未照合なので正式未見holdoutと称しない。',
        owner源実行=0,元cache=0,金融本文=0,金融=0,NPZ=0,実台帳=0,原board=0,API=0,共有編集=0)
    OUTPUT.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('独立signal純期待 '+str(count)+'合格。SHA '+hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':
    try:main()
    except Exception:
        p=HERE/'独立signal純期待初版False.json';assert not p.exists()
        p.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),owner源実行=0,元cache=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
