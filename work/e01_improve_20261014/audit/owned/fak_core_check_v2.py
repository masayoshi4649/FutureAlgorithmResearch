"""署名済み核心11源だけを私有コピーし、独立小feed期待値とPython/JITを照合する。"""

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import sys
import traceback

import fak_reference as oracle


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_improve_20261014/engine'
PRIVATE=HERE/'private_core_source_v2'
JIT=HERE/'private_core_jit_v2'
NAMES=('sizing_engine.py','sizing_engine_legacy.py','order_kernel.py','entry_policy.py','catalog.py',
       'base_policy.py','daily.py','context.py','reuse.py','exit_core.py','exit_policy.py')


def digest(saved: bytes) -> str:
    """
    機能: 小source又は人工資料の同bytes指紋を得る。
    引数: saved(bytes) は読み取った小資料。
    返り値: str はSHA256。入力や台帳をhash目的で再読しない。
    """
    return hashlib.sha256(saved).hexdigest()


def material(source: dict) -> dict:
    """
    機能: 独立小feedの列を正式核心APIに対応する人工配列へ写す。
    引数: source(dict) は純参照が定義した人工。
    返り値: dict はrecord/quotes/feed/休止と同じ入力条件。未来価格を公開gateへ流さない。
    """
    import numpy as np
    rows=source['rows'];n=len(rows);times=np.array([r['time'] for r in rows],float)
    bid=np.array([r['bid'] for r in rows]);ask=np.array([r['ask'] for r in rows])
    qok=np.array([r['normal'] for r in rows],bool);seq=np.arange(400,400+n,dtype=np.int64)
    prices=bid.copy();feed=[]
    for o in source['feed']:
        feed.append([o['row'],max(0,o['row']-1),o['cid'],o['side'],o['quantity'],prices[o['row']],
                     o['reason'],int(o['new']),0.,o['atr']])
    count=len(feed);feed=np.array(feed,float).reshape(count,10)
    gate=np.ones(n,bool)
    for row,accepted in source['gate'].items():
        if row<n:gate[row]=accepted
    return dict(symbol=source['symbol'],record=dict(price=prices,time_s=times,seq=seq,tick=source['tick'],
        limit=source['end'],start=0.,end=source['end']+300.),
        quotes=dict(time_s=times,seq=seq,bid=bid,ask=ask,quote_valid=qok),feed=feed,entry_filter=gate,
        quiet=np.array([r['quiet'] for r in rows],bool),quiet_force=np.array([r['quiet_force'] for r in rows],bool),
        trade_features={'60':{o['row']:dict(known=source['gate'].get(o['row'],True),reason=0 if source['gate'].get(o['row'],True) else 16,
            direction_votes=4 if o['row']==6 else 2,balance=1.,up_votes=4 if o['row']==6 else 2,down_votes=0)
            for o in source['feed'] if o['new']}})


def subset(source: dict, cut: int) -> dict:
    """
    機能: 人工の未来行と将来紙上注文を一緒に切る。
    引数: source(dict) は独立人工、cut(int) は含める最終row。
    返り値: dict は未完成接頭。期限を接頭の末尾へ付け替えない。
    """
    out=deepcopy(source);out['rows']=out['rows'][:cut+1]
    out['feed']=[o for o in out['feed'] if o['row']<=cut]
    return out


def main() -> None:
    """
    機能: owner完成通知の核心署名へ束縛し、純参照・旧市場exact・受理アンカー・接頭を非金融で検査する。
    引数: なし。driver/interfaceは更新中なので全源不変とは主張しない。
    返り値: None。自所有のproof又はFalseを保存、実金融・大型・台帳は0。
    """
    target=HERE/'署名済みFAK核心11源と純小feed及び旧市場の独立人工_v2.json'
    failed=HERE/'署名済みFAK核心11源の独立人工False_v2.json'
    assert not any(p.exists() for p in (target,failed,PRIVATE))
    artifact_path=ENGINE/'archive/driver最終束縛前/一回FAKと全feed再参加及び旧市場同値の人工検査.json'
    saved=artifact_path.read_bytes();owner=json.loads(saved.decode('utf-8-sig'))
    assert owner['全合格'];owner_sha=digest(saved)
    sources={};metadata_difference={}
    PRIVATE.mkdir()
    for name in NAMES:
        original=ENGINE/name;saved=original.read_bytes();sha=digest(saved)
        key=original.relative_to(ROOT).as_posix()
        if owner['source_SHA256'][key]!=sha:
            assert name=='catalog.py',(name,'owner署名と異なる')
            before=(HERE/'private_core_source/catalog.py').read_bytes()
            assert digest(before)==owner['source_SHA256'][key]
            oldlines=before.decode('utf-8-sig').splitlines();newlines=saved.decode('utf-8-sig').splitlines()
            diff=[(a,b) for a,b in zip(oldlines,newlines) if a!=b]
            assert len(oldlines)==len(newlines) and len(diff)==1
            assert diff[0][0].startswith('TRIAL_ID=') and diff[0][1]==diff[0][0].replace('104_','105_',1)
            metadata_difference=dict(旧SHA256=digest(before),新SHA256=sha,変更='登録番号104→105のTRIAL_ID一行だけ。経済係数/CaseIDs不変。')
        sources[key]=sha;(PRIVATE/name).write_bytes(saved)
    os.environ['NUMBA_CACHE_DIR']=str(JIT)
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(PRIVATE))
    import numpy as np
    import numba
    numba.config.CACHE_DIR=str(JIT)
    import sizing_engine as core
    import sizing_engine_legacy as legacy
    import context
    import entry_policy
    import catalog
    assert Path(core.__file__).resolve().parent==PRIVATE
    counts={};cases=[]

    def equal(left: object, right: object, label: str) -> None:
        """
        機能: 独立人工値と新核心配列を、未知を含む型shape付きで比較する。
        引数: left/right(object) は数値配列、label(str) は用途。
        返り値: None。不一致は例外にし照合配列数を記録する。
        """
        np.testing.assert_allclose(left,right,atol=1e-5,rtol=1e-11,equal_nan=True,err_msg=label)
        counts['配列照合']=counts.get('配列照合',0)+1

    def execute(account: dict, mode: str, sizing: bool=True, python: bool=False) -> tuple:
        """
        機能: 新核心の純人工APIだけを呼び、旧sourceや入力ロードを実行しない。
        引数: account(dict)、mode(str)、sizing/python(bool) は人工条件と実行系。
        返り値: tuple は新12配列。正式金融呼出しはしない。
        """
        r=account['record'];q=account['quotes'];s=account['symbol'];fee=catalog.FEE_RATIO[s]
        fn=core.simulate.py_func if python else core.simulate
        return fn(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],account['feed'],
            account['quiet'],account['quiet_force'],r['limit'],catalog.CAP[s],r['tick'],0.,True,
            account['entry_filter'],sizing,catalog.BUDGET[s],1.,catalog.VALUE[s],fee[0],fee[1],mode!='市場',1 if mode=='FAK1' else 0)

    def compare(source: dict, mode: str, sizing: bool=True) -> tuple:
        """
        機能: 独立10進帳簿と新Python/JITの実注文・影・数量・料・一回試行を突合する。
        引数: source(dict)、mode(str)、sizing(bool) は独立小人工。
        返り値: tuple は新12配列。副作用は私有JITのみ。
        """
        expected=oracle.run(source,mode,sizing=sizing);account=material(source)
        actual=execute(account,mode,sizing=sizing);pure=execute(account,mode,sizing=sizing,python=True)
        for left,right in zip(actual,pure):equal(left,right,'Python/JIT')
        orders=np.array([[o['row'],o['source'],o['cid'],o['side'],o['quantity'],o['price'],o['reason'],int(o['new'])]
                         for o in expected['orders']],float).reshape(-1,8)
        equal(actual[0],orders,'独立実注文')
        equal(actual[5],np.array([o['uid'] for o in expected['orders']],np.int64),'独立UID')
        states=expected['states']
        equal(actual[7][:,[0,1,2,3,4,5,9]],np.array([[r['virtual_cid'],r['vcore'],r['real_cid'],r['held_long'],r['held_short'],int(r['pending']),r['queued']]
                                                  for r in states],float),'影・実残玉・予約・queue')
        f=expected['fee_curve']
        equal(actual[10],np.array([[r['paid'],r['reserved_exit_fee'],r['equity'],r['liquidation'],r['available']] for r in f]),'独立料清算曲線')
        e=expected['accepts'];columns=[0,1,2,3,4,5,6,8,9,11,12,14,15]
        equal(actual[9][:,columns],np.array([[r['row'],r['cid'],r['side'],r['virtual_quantity'],r['selected_quantity'],r['published_atr'],
            np.nan if not sizing or r['published_spread'] is None else r['published_spread'],r['liquidation'],r['available'],r['paid'],r['reserve'],int(r['gate']),int(r['accepted'])]
            for r in e],float).reshape(-1,len(columns)),'独立公開数量')
        before=dict(key=('純人工',source['symbol']),shadow_GU_orders=actual[0],shadow_GU_uids=actual[5],
            execution_events=actual[6],execution_states=actual[7],limit_events=actual[8],sizing_events=actual[9],sizing_fee_curve=actual[10])
        finish=source['rows'][-1]['time']>=source['end']
        ctx=context.prepare(account,before,before,finish=finish) if sizing else None
        anchor=expected['anchor']
        if sizing:assert (ctx['anchor'] is None)==(anchor is None)
        if sizing and anchor is not None:
            assert ctx['anchor']['row']==anchor['row'] and ctx['anchor']['quantity']==anchor['selected_quantity']
            equal(ctx['anchor']['published_atr'],anchor['published_atr'],'受理ATR')
            equal(ctx['anchor']['roundtrip_fee_yen'],2*oracle.fee(anchor['selected_quantity'],source['symbol']),'受理往復料')
        if mode=='市場':
            r=account['record'];q=account['quotes'];s=account['symbol'];fee=catalog.FEE_RATIO[s]
            old=legacy.simulate(r['time_s'],r['price'],q['bid'],q['ask'],q['quote_valid'],account['feed'],
                account['quiet'],account['quiet_force'],r['limit'],catalog.CAP[s],r['tick'],0.,True,
                account['entry_filter'],sizing,catalog.BUDGET[s],1.,catalog.VALUE[s],fee[0],fee[1])
            for left,right in zip(actual[:11],old):
                np.testing.assert_array_equal(left,right)
                counts['旧市場exact配列']=counts.get('旧市場exact配列',0)+1
            assert actual[11].shape==(0,19)
        else:
            attempts=actual[11][actual[11][:,1]==2]
            assert len(attempts)==len(expected['attempts'])
            for a,b in zip(attempts,expected['attempts']):
                equal(a[[0,2,3,6,13]],np.array([b['row'],b['cid'],b['publication'],b['limit'],int(b['filled'])]),'一回価格試行')
            for a in actual[11]:
                pub=int(a[3]);side=int(a[4]);q=account['quotes'];tick=account['record']['tick']
                if q['quote_valid'][pub]:
                    equal(a[6],q['ask' if side>0 else 'bid'][pub]+side*(tick if mode=='FAK1' else 0.),'公開固定cap')
                else:
                    assert np.isnan(a[6])
        counts['独立小feed実行']=counts.get('独立小feed実行',0)+1
        return actual

    kinds=('再参加数量','通常同値','静観と第一正常が同列','紙上全返済と第一正常が同列',
        '紙上全返済だけが先着','累積部分返済','部分返済待機の重複防止','価格内の拡幅',
        '第一正常の前に不正気配','期限と第一正常が同列')
    try:
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for kind in kinds:
                    source=oracle.fixture(symbol,side,kind)
                    for mode in ('市場','FAK0','FAK1'):
                        actual=compare(source,mode)
                        for cut in (1,2,4,5,7,10):
                            prefix=compare(subset(source,cut),mode)
                            for slot in (2,7,10):equal(prefix[slot],actual[slot][:cut+1],'未完成prefix')
                            for slot in (0,6,8,9,11):equal(prefix[slot],actual[slot][actual[slot][:,0]<=cut],'当時イベントprefix')
                        cases.append(dict(symbol=symbol,side=side,kind=kind,mode=mode))
                for variant in ('gate拒否','公開不明','予定q0','同価格時計','数量選択OFF'):
                    source=oracle.fixture(symbol,side,'通常同値')
                    if variant=='gate拒否':source['gate'][1]=False
                    if variant=='公開不明':source['rows'][1]['normal']=False
                    if variant=='予定q0':source['feed'][0]['atr']=10000.
                    if variant=='同価格時計':source['rows'][2]['time']=source['rows'][1]['time']
                    for mode in ('市場','FAK0','FAK1'):
                        compare(source,mode,sizing=variant!='数量選択OFF')
        for threshold in (.25,.5,.75):
            for minimum in (2,4):
                for known in (True,False):
                    for votes in (0,1,2,3,4,8,20):
                        for balance in (-1.,.249999,.25,.499999,.5,.749999,.75,1.):
                            value=dict(known=known,reason=0 if known else 16,direction_votes=votes,balance=balance)
                            ok,reason=entry_policy.vote(value,threshold,minimum)
                            expected=known and votes>=minimum and balance>=threshold
                            assert ok==expected
                            assert reason==(0 if expected else 116 if not known else 200 if votes<minimum else 201)
                            counts['公開票真偽表']=counts.get('公開票真偽表',0)+1
        for path,sha in sources.items():
            assert digest((ROOT/path).read_bytes())==sha
        result=dict(全合格=True,状態='署名済み核心11部品の人工合格。driver/interface/全sourceの最終freeze監査ではない。',
            source_SHA256=sources,所有初回人工SHA256=owner_sha,登録番号メタ訂正=metadata_difference,検査=counts,主人工条件=cases,
            自所有source_SHA256=dict(reference=digest((HERE/'fak_reference.py').read_bytes()),checker=digest(Path(__file__).read_bytes())),
            検査範囲='原行時系列ではなく純小人工。新核心/旧市場私有clone/当時context/公開票だけ。核心以外の更新中源はimportしない。',
            注記=['静観/期限はfirstgoodより先。paper同行取消は第一正常の価格条件成立より後。成立実玉をpaper取消で消さない。',
                '未成立実新規はUID/fee/返済queueを作らず、影vcoreと後候補qを維持。初受理尺度は将来失効でも保持。',
                '価格内でも幅だけ拡大し得る人工を含む。FAKで初期清算損を保証しない。',
                '基準は65/20/平均黒字補填を維持。0行を勝ちや追加の最低活動達成と扱わない。',
                '初版source/Falseは不変保持。OFFのsizing診断spreadは新旧ともNaN、受理contextは正式sizingON契約なのでOFFでは旧11exactと注文/料/影/queueに限定した。',
                'catalogはroot/owner通知のTRIAL_ID一行のみ104→105を別メタ追補、初回owner全source署名と完全一致とは主張しない。' ],
            金融=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,旧source又は共有編集=0)
        target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,核心源=11,検査=counts,SHA256=digest(target.read_bytes())),ensure_ascii=False))
    except Exception:
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),source_SHA256=sources,
            所有初回人工SHA256=owner_sha,検査=counts,金融=0,入力=0,台帳=0,API=0,自動再実行=False),
            ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':
    main()
