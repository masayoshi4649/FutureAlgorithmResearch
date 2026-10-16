"""所有完成通知後だけ適応価格核心を私有コピーし、純参照・定数同値・未来反例を検査する。"""

from copy import deepcopy
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys
import traceback
import adaptive_reference as oracle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ENGINE = ROOT/'work/e01_adaptive_price_20261014/engine'
PRIVATE = HERE/'private_core_source'
JIT = HERE/'private_core_jit'
NAMES = ('sizing_engine.py','constant_engine.py','order_kernel.py','entry_policy.py','catalog.py',
         'base_policy.py','daily.py','context.py','reuse.py','exit_core.py','exit_policy.py')
OLD_HELPER = ROOT/'work/e01_improve_20261014/audit/owned/fak_core_check_v2.py'
sys.path.insert(0,str(OLD_HELPER.parent))
spec = importlib.util.spec_from_file_location('旧独立人工配列化',OLD_HELPER)
old_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old_helper)
sys.path.remove(str(OLD_HELPER.parent))
material, subset = old_helper.material, old_helper.subset


def digest(raw: bytes) -> str:
    """
    機能: 小人工又は source の同 bytes 指紋を取得する。
    引数: raw(bytes) は保存内容。
    返り値: str は SHA256。大型入力や台帳は開かない。
    """
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    """
    機能: 所有完成済み核心 source だけに束縛し、独立帳簿と全12槽を非金融で確認する。
    引数: CLI 第1引数(str) は所有完成済み人工 artifact のファイル名。
    返り値: None。署名相違や人工不一致は False を保持し自動再実行しない。
    """
    assert len(sys.argv)==2
    artifact = ENGINE/sys.argv[1]
    target = HERE/'適応価格核心と定数12槽及び公開予約未来保全の独立人工.json'
    failed = HERE/'適応価格核心の独立人工False.json'
    assert not any(p.exists() for p in (PRIVATE,target,failed))
    owner_raw = artifact.read_bytes(); owner=json.loads(owner_raw.decode('utf-8-sig'))
    assert owner['全合格']
    sources={};PRIVATE.mkdir()
    for name in NAMES:
        path=ENGINE/name;raw=path.read_bytes();sha=digest(raw);key=path.relative_to(ROOT).as_posix()
        assert owner['source_SHA256'][key]==sha,(name,'所有完成署名不一致')
        sources[key]=sha;(PRIVATE/name).write_bytes(raw)
    # 新核心の定数比較 clone が旧00105の実経済と同 bytes であることを確認する。
    legacy=ROOT/'work/e01_improve_20261014/engine/sizing_engine.py'
    assert (PRIVATE/'constant_engine.py').read_bytes()==legacy.read_bytes()
    os.environ['NUMBA_CACHE_DIR']=str(JIT);sys.dont_write_bytecode=True;sys.path.insert(0,str(PRIVATE))
    import numpy as np
    import numba
    numba.config.CACHE_DIR=str(JIT)
    import sizing_engine as core
    import constant_engine as constant
    import catalog
    import context
    import entry_policy
    assert Path(core.__file__).resolve().parent==PRIVATE
    counts={};cases=[]

    def equal(actual: object, expected: object, label: str) -> None:
        """
        機能: 独立小配列と新 Python/JIT 経済を未知も保存して比較する。
        引数: actual/expected(object) は配列、label(str) は用途。
        返り値: None。不一致を例外とし比較数を記録する。
        """
        np.testing.assert_allclose(actual,expected,atol=1e-5,rtol=1e-11,equal_nan=True,err_msg=label)
        counts['配列照合']=counts.get('配列照合',0)+1

    def execute(account: dict, allowances: object, market: bool=False, sizing: bool=True, python: bool=False) -> tuple:
        """
        機能: 適応核心へ純人工配列だけを渡し、新源の私有 JIT を実行する。
        引数: account(dict)、allowances(object) は人工口座と許容、market/sizing/python(bool) は実行設定。
        返り値: tuple は旧12槽。正式入力や金融呼出しをしない。
        """
        r,q,s=account['record'],account['quotes'],account['symbol'];f=catalog.FEE_RATIO[s]
        fn=core.simulate.py_func if python else core.simulate
        return fn(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],account['feed'],
            account['quiet'],account['quiet_force'],r['limit'],catalog.CAP[s],r['tick'],0.,True,
            account['entry_filter'],sizing,catalog.BUDGET[s],1.,catalog.VALUE[s],f[0],f[1],not market,allowances)

    def compare(source: dict, rule: str, sizing: bool=True) -> tuple:
        """
        機能: 当公開行の0/1許容を独立帳簿へ固定し、実玉・UID・料・影・部分・接頭を照合する。
        引数: source(dict)、rule(str)、sizing(bool) は純人工と定数又は混合許容。
        返り値: tuple は新12槽。比較先の旧経済も私有 clone の人工だけ。
        """
        n=len(source['rows']);account=material(source)
        values=[0 if rule in ('0','市場') else 1 if rule=='1' else int(i%3==1) for i in range(n)]
        allowances=np.array(values,np.int8);mapping=dict(enumerate(values))
        expected=oracle.run(source,'市場' if rule=='市場' else 'FAK0',sizing=sizing,
                            adverse_by_publication=None if rule=='市場' else mapping)
        actual=execute(account,allowances,market=rule=='市場',sizing=sizing)
        pure=execute(account,allowances,market=rule=='市場',sizing=sizing,python=True)
        assert len(actual)==len(pure)==12
        for a,b in zip(actual,pure):equal(a,b,'Python/JIT全12槽')
        expected_orders=np.array([[o['row'],o['source'],o['cid'],o['side'],o['quantity'],o['price'],o['reason'],int(o['new'])]
                                 for o in expected['orders']],float).reshape(-1,8)
        equal(actual[0],expected_orders,'独立実注文')
        equal(actual[5],np.array([o['uid'] for o in expected['orders']],np.int64),'独立UID')
        equal(actual[7][:,[0,1,2,3,4,5,9]],np.array([[r['virtual_cid'],r['vcore'],r['real_cid'],r['held_long'],r['held_short'],int(r['pending']),r['queued']]
                                                  for r in expected['states']],float),'影実残玉予約queue')
        equal(actual[10],np.array([[r['paid'],r['reserved_exit_fee'],r['equity'],r['liquidation'],r['available']]
                                   for r in expected['fee_curve']]),'独立floor料清算')
        columns=[0,1,2,3,4,5,6,8,9,11,12,14,15]
        equal(actual[9][:,columns],np.array([[r['row'],r['cid'],r['side'],r['virtual_quantity'],r['selected_quantity'],r['published_atr'],
             np.nan if not sizing or r['published_spread'] is None else r['published_spread'],r['liquidation'],r['available'],r['paid'],r['reserve'],int(r['gate']),int(r['accepted'])]
             for r in expected['accepts']],float).reshape(-1,len(columns)),'公開数量')
        if sizing:
            ledger=dict(key=('純人工',source['symbol']),shadow_GU_orders=actual[0],shadow_GU_uids=actual[5],execution_events=actual[6],
                execution_states=actual[7],limit_events=actual[8],sizing_events=actual[9],sizing_fee_curve=actual[10])
            ctx=context.prepare(account,ledger,ledger,finish=source['rows'][-1]['time']>=source['end'])
            anchor=expected['anchor'];assert (ctx['anchor'] is None)==(anchor is None)
            if anchor is not None:
                assert ctx['anchor']['row']==anchor['row'] and ctx['anchor']['quantity']==anchor['selected_quantity']
                equal(ctx['anchor']['published_atr'],anchor['published_atr'],'固定初受理ATR')
                equal(ctx['anchor']['roundtrip_fee_yen'],2*oracle.fee(anchor['selected_quantity'],source['symbol']),'固定料尺度')
        if rule in ('0','1','市場'):
            r,q,s=account['record'],account['quotes'],account['symbol'];f=catalog.FEE_RATIO[s]
            prior=constant.simulate(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],account['feed'],account['quiet'],account['quiet_force'],
                r['limit'],catalog.CAP[s],r['tick'],0.,True,account['entry_filter'],sizing,catalog.BUDGET[s],1.,catalog.VALUE[s],f[0],f[1],rule!='市場',int(rule=='1'))
            for a,b in zip(actual,prior):
                np.testing.assert_array_equal(a,b);counts['旧定数exact12槽']=counts.get('旧定数exact12槽',0)+1
        if rule!='市場':
            attempts=actual[11][actual[11][:,1]==2];assert len(attempts)==len(expected['attempts'])
            for a,b in zip(attempts,expected['attempts']):
                equal(a[[0,2,3,6,13]],np.array([b['row'],b['cid'],b['publication'],b['limit'],int(b['filled'])]),'独立一次試行')
            for event in actual[11]:
                pub=int(event[3]);side=int(event[4])
                equal(event[9],values[pub],'公開固定許容')
                if account['quotes']['quote_valid'][pub]:
                    equal(event[6],account['quotes']['ask' if side==1 else 'bid'][pub]+side*source['tick']*values[pub],'公開固定cap')
                else:assert np.isnan(event[6])
        counts['純小feed実行']=counts.get('純小feed実行',0)+1
        return actual

    try:
        kinds=('再参加数量','通常同値','静観と第一正常が同列','紙上全返済と第一正常が同列',
            '紙上全返済だけが先着','累積部分返済','部分返済待機の重複防止','価格内の拡幅',
            '第一正常の前に不正気配','期限と第一正常が同列')
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for kind in kinds:
                    source=oracle.fixture(symbol,side,kind)
                    for rule in ('0','1','混合','市場'):
                        actual=compare(source,rule)
                        for cut in (1,2,4,5,7,10):
                            prefix=compare(subset(source,cut),rule)
                            for slot in (2,7,10):equal(prefix[slot],actual[slot][:cut+1],'未来未読prefix')
                            for slot in (0,6,8,9,11):equal(prefix[slot],actual[slot][actual[slot][:,0]<=cut],'当時eventprefix')
                        cases.append(dict(symbol=symbol,side=side,kind=kind,rule=rule))
                for variant in ('gate拒否','公開不明','予定q0','同価格時計','数量選択OFF'):
                    source=oracle.fixture(symbol,side,'通常同値')
                    if variant=='gate拒否':source['gate'][1]=False
                    if variant=='公開不明':source['rows'][1]['normal']=False
                    if variant=='予定q0':source['feed'][0]['atr']=10000.
                    if variant=='同価格時計':source['rows'][2]['time']=source['rows'][1]['time']
                    for rule in ('0','1','混合','市場'):compare(source,rule,sizing=variant!='数量選択OFF')
                source=oracle.fixture(symbol,side,'再参加数量');account=material(source)
                for initial in (0,1):
                    a=np.full(len(source['rows']),1-initial,np.int8);a[1]=initial
                    b=a.copy();b[2:]=1-b[2:]
                    x,y=execute(account,a),execute(account,b)
                    for slot in (2,7,10):equal(x[slot][:6],y[slot][:6],'未来許容の接頭不変')
                    for slot in (0,6,8,9,11):equal(x[slot][x[slot][:,0]<=5],y[slot][y[slot][:,0]<=5],'未来許容のevent不変')
                    attempts=x[11][x[11][:,1]==2]
                    assert attempts[0,13]==initial and attempts[0,9]==initial
                    bad=deepcopy(account);bad['quotes']['bid'][2]+=side*source['tick']*100;bad['quotes']['ask'][2]+=side*source['tick']*100
                    altered=execute(bad,a)
                    for slot in (2,7,10):equal(x[slot][:2],altered[slot][:2],'未来quoteの公開接頭不変')
                    for slot in (0,6,8,9,11):equal(x[slot][x[slot][:,0]<=1],altered[slot][altered[slot][:,0]<=1],'未来quoteの公開event不変')
                    assert altered[11][altered[11][:,1]==2][0,13]==0
                    counts['予約未来反例']=counts.get('予約未来反例',0)+1
        balances=(-1.,0.,.25,np.nextafter(.5,0),.5,np.nextafter(.75,0),.75,np.nextafter(.75,1),np.nextafter(1.,0),1.)
        for known in (False,True):
            for n in (0,1,2,3,4,20):
                for balance in balances:
                    for threshold in (.75,1.):
                        source=oracle.fixture('TOPIX',1,'通常同値');account=material(source)
                        account['trade_features']['60'][1].update(known=known,direction_votes=n,balance=balance)
                        allowance=entry_policy.allowances(account,threshold)
                        assert int(allowance[1])==int(known and n>=2 and balance>=threshold)
                        assert allowance.dtype==np.int8 and len(allowance)==len(source['rows'])
                        assert all(allowance[i]==0 for i in range(len(allowance)) if i not in (1,6))
                        counts['公開閾値真偽表']=counts.get('公開閾値真偽表',0)+1
        for path,sha in sources.items():assert digest((ROOT/path).read_bytes())==sha
        output=dict(全合格=True,状態='所有完成済み核心11部品の独立人工。全driver/freeze/register監査は別。',
            source_SHA256=sources,所有完成人工SHA256=digest(owner_raw),検査=counts,主人工条件=cases,
            独立sourceSHA256=digest(Path(__file__).read_bytes()),referenceSHA256=digest((HERE/'adaptive_reference.py').read_bytes()),
            旧独立配列化helperSHA256=digest(OLD_HELPER.read_bytes()),
            留保=['定数配列は旧00105同bytes私有cloneの全12槽exact。経済sourceの新効能を数えない。',
                '混合許容は公開行で予約へ固定。未来試行票やquoteでは公開mask/q/anchorを変えない。',
                '旧影・部分floor・実料・UID・次正常返済・quiet/paper同列順位を独立小feedと比較した。',
                '数量選択OFFのspread診断は新旧NaNで、正式受理contextの有資格ON検査と混ぜない。',
                '物理FAK到着・板深度/補充・mini/micro約定確度は人工の対象外。'],
            金融=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,旧源又は共有変更=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,核心源=11,検査=counts,SHA256=digest(target.read_bytes())),ensure_ascii=False))
    except Exception:
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),source_SHA256=sources,
            所有完成人工SHA256=digest(owner_raw),検査=counts,金融=0,入力=0,台帳=0,API=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':
    main()
