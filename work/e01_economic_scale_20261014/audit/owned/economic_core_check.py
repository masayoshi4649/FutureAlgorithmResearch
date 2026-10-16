"""所有完成済み核心を私有コピーし、経済尺度と実親分離を純参照v3へ独立照合する。"""

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import sys
import traceback
import economic_reference_v3 as oracle

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_economic_scale_20261014/engine'
PRIVATE=HERE/'private_economic_core'
JIT=HERE/'private_economic_jit'
NAMES=('common.py','catalog.py','core.py','daily.py','order_kernel.py','entry_policy.py','base_policy.py',
       'legacy_engine.py','interface.py')


def material(source: dict) -> dict:
    """
    機能: 独立小状態機械の行とpaper注文だけを核心API人工配列へ写す。
    引数: source(dict) は純人工。
    返り値: dict はrecord/quotes/feed/当公開票。実データをロードしない。
    """
    import numpy as np
    n=len(source['rows']);r=source['rows'];times=np.array([o['time'] for o in r]);seq=np.arange(500,500+n,dtype=np.int64)
    price=np.array([o['last'] for o in r]);feed=[]
    for o in source['feed']:
        feed.append([o['row'],max(0,o['row']-1),o['cid'],o['side'],o['quantity'],price[o['row']],1 if o['new'] else 2,int(o['new']),0,o.get('atr',1.)])
    features={o['row']:dict(known=o['known'],reason=0 if o['known'] else 16,direction_votes=o['votes'],balance=o['balance'],up_votes=o['votes'],down_votes=0)
              for o in source['feed'] if o['new']}
    return dict(symbol=source['symbol'],record=dict(time_s=times,price=price,seq=seq,tick=source['tick'],start=0.,limit=source['end']),
        quotes=dict(time_s=times,seq=seq,bid=np.array([o['bid'] for o in r]),ask=np.array([o['ask'] for o in r]),quote_valid=np.array([o['normal'] for o in r],bool)),
        feed=np.array(feed,float).reshape(-1,10),quiet=np.array([o['quiet'] for o in r],bool),quiet_force=np.array([o['quiet_force'] for o in r],bool),
        trade_features={'60':features})


def main() -> None:
    """
    機能: 完成済み経済核心9源を独立人工へ束縛し全7槽/PythonJIT/原行接頭を検査する。
    引数: なし。所有完成13署名artifactの核心subsetだけを用いる。
    返り値: None。私有source/JITと所有証跡だけ書き、正式金融は0。
    """
    target=HERE/'規模核心9源と全実親分母及び純v3の独立人工.json'
    failed=HERE/'規模核心の独立人工False.json'
    assert not any(p.exists() for p in (PRIVATE,target,failed))
    artifact=ENGINE/'十四容量と実親分離及び局所清算の人工検査.json'
    raw=artifact.read_bytes();owner=json.loads(raw.decode('utf-8-sig'));assert owner['全合格']
    sources={};PRIVATE.mkdir()
    for name in NAMES:
        path=ENGINE/name;data=path.read_bytes();sha=hashlib.sha256(data).hexdigest();key=path.relative_to(ROOT).as_posix()
        assert sha==owner['source_SHA256'][key],name
        sources[key]=sha;(PRIVATE/name).write_bytes(data)
    os.environ['NUMBA_CACHE_DIR']=str(JIT);sys.dont_write_bytecode=True;sys.path.insert(0,str(PRIVATE))
    import numpy as np
    import numba
    numba.config.CACHE_DIR=str(JIT)
    import core
    import catalog
    import entry_policy
    import interface
    counts={};cases=[]

    def equal(actual: object, expected: object, label: str) -> None:
        """
        機能: 私有核心と独立純配列を未知も含め照合する。
        引数: actual/expected(object) は比較配列、label(str) は用途。
        返り値: None。不一致は例外とし比較数を記録する。
        """
        np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=1e-11,equal_nan=True,err_msg=label)
        counts['配列照合']=counts.get('配列照合',0)+1

    def execute(source: dict, quantity: str, mode: str, python: bool=False) -> tuple:
        """
        機能: 公式と同じ純人工APIへ当公開票/数量/退出を渡す。
        引数: source(dict)、quantity/mode(str)、python(bool) は独立人工と実行系。
        返り値: tuple は核心7槽。正式input/JITへの書込はしない。
        """
        a=material(source);r,q=a['record'],a['quotes'];s=a['symbol'];fee=catalog.FEE_RATIO[s]
        gate=entry_policy.mask(a,'G50' if s=='TOPIX' else 'G25');allow=entry_policy.allowances(a,.75 if s=='TOPIX' else 1.)
        fn=core.simulate.py_func if python else core.simulate
        return fn(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],a['feed'],a['quiet'],a['quiet_force'],r['start'],r['limit'],
            source['cap'],r['tick'],source['multiplier'],fee[0],fee[1],gate['accepted'],allow,
            source['shadow_full'] if quantity=='HALF' else source['cap'],int(quantity=='RISK'),('GU','TARGET','TRAIL','PARTIAL').index(mode),
            .00125,.00125,.005,.00375,.00125,.0025,.0025,.25,.0025)

    def compare(source: dict, quantity: str, mode: str) -> tuple:
        """
        機能: 別状態機械の実価格cash/料金/原親/初名目/局所清算を新PythonJITへ比較する。
        引数: source(dict)、quantity/mode(str) は純人工設定。
        返り値: tuple は核心7槽。未完結paperによる実親除外を認めない。
        """
        book=oracle.run(source,quantity,mode);actual=execute(source,quantity,mode);pure=execute(source,quantity,mode,True)
        assert len(actual)==len(pure)==7
        for a,b in zip(actual,pure):equal(a,b,'Python/JIT全7槽')
        codes={'予定終了':92,'一回FAK':90,'場損失':143,'親損失':141,'親純目標':140,'親利益追尾':142,'四分の一':144,'元paper返済':91}
        expected=[]
        for o in book['orders']:
            reason=codes[o['reason']]
            if o['reason']=='予定終了' and source['rows'][o['row']]['time']>=source['end']:reason=93
            expected.append([o['row'],o['source'],o['paper_parent'],o['side'],o['quantity'],o['price'],reason,int(o['new'])])
        equal(actual[0],np.array(expected,float).reshape(-1,8),'独立実注文')
        equal(actual[1],np.array([o['uid'] for o in book['orders']],np.int64),'独立注文UIDと返済-1')
        curve=np.array([[o['equity'],o['liquidation'],o['parent_local'],np.nan if o['peak'] is None else o['peak'],
            o['long_quantity'],o['short_quantity'],o['paid'],o['reserved'],o['real_cid'],o['scene_stop']] for o in book['curve']])
        equal(actual[2],curve,'別cash帳簿の全10清算槽')
        origins=actual[6];new=[o for o in book['orders'] if o['new']]
        assert len(origins)==len(new)
        for origin,entry in zip(origins,new):
            equal(origin[[0,1,2,3,4,5,6,11]],np.array([entry['paper_parent'],entry['row'],entry['source'],entry['side'],entry['quantity'],entry['price'],
                entry['price']*entry['quantity']*source['multiplier'],entry['uid']]),'初実fill名目/UID')
            prior=sum(p['net'] for p in book['parents'] if p['exit_row']<=entry['row'] and p['uid']!=entry['uid'])
            equal(origin[7],prior,'前親確定net基準')
        if source['rows'][-1]['time']>=source['end']:
            a=material(source);config=next(c for c in catalog.configs() if c['entry_route']=='SELECTED' and c['quantity_mode']==quantity and c['exit_id']==mode)
            output=interface.play(a,config,'純人工',python=True)
            assert len(output['parent'])==len(book['parents']) and len(output['pure_parent_complete_ids'])==len(book['parents'])
            same_parent={p['親']:p for p in output['parent']}
            for p in book['parents']:
                before=same_parent[p['paper_parent']]
                equal(before['収支'],p['net'],'全完結実親net');equal(before['費用'],p['fee'],'親料');equal(before['枚数'],p['quantity'],'実初q')
            counts['全実親分母口座']=counts.get('全実親分母口座',0)+1
        counts['独立人工口座']=counts.get('独立人工口座',0)+1
        return actual

    try:
        kinds=('独立親と再参加','paper継続中targetclose','paper先取消','paper同行firstnormal','少量partial','q0後別親',
               '第一FAK失効','追尾後の返済gap','場損失後停止','partial予約後quiet')
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for kind in kinds:
                    source=oracle.fixture(symbol,side,kind)
                    for quantity in ('HALF','FULL','RISK'):
                        for mode in ('GU','TARGET','TRAIL','PARTIAL'):
                            actual=compare(source,quantity,mode)
                            for cut in (1,5,8,15):
                                prefix=deepcopy(source);prefix['rows']=prefix['rows'][:cut+1];prefix['feed']=[o for o in prefix['feed'] if o['row']<=cut]
                                p=compare(prefix,quantity,mode)
                                equal(p[2],actual[2][:cut+1],'未完成10槽接頭')
                                for slot in (0,3,4,5):equal(p[slot],actual[slot][actual[slot][:,0]<=cut],'未完成実イベント接頭')
                                equal(p[6],actual[6][actual[6][:,1]<=cut],'未完成実起点接頭')
                            cases.append(dict(symbol=symbol,side=side,kind=kind,quantity=quantity,exit=mode))
        for path,sha in sources.items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
        output=dict(全合格=True,状態='所有署名核心9部品の独立人工。driver/正式freezeは別監査。',source_SHA256=sources,
            所有完成人工SHA256=hashlib.sha256(raw).hexdigest(),検査=counts,主条件=cases,
            独立referenceSHA256=hashlib.sha256((HERE/'economic_reference_v3.py').read_bytes()).hexdigest(),
            独立checkerSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            留保=['同じechoではなく独立Decimal現金帳簿と実親phaseを用いた。所有Python/JIT同値だけを根拠にしていない。',
                '原GUも新親/場stop付き変更対照。旧GU exactは別prepared guardsOFF/HALF純対照。',
                '初実fill名目・原paper継続中の実完結分母・busy更新・前親net・q上限・部分料floorと接頭を検査。',
                '未来正常気配を未観測の利益へ置換しない。物理約定/実商品板/未知成功は証明していない。'],
            金融=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,旧源又は共有変更=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,核心9源=True,検査=counts,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),source_SHA256=sources,検査=counts,
            所有完成人工SHA256=hashlib.sha256(raw).hexdigest(),金融=0,入力=0,台帳=0,API=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
