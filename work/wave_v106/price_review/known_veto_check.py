"""既知中立の入口を、結果前の境界・影・実玉・接頭人工で独立確認する。"""

from copy import deepcopy
from pathlib import Path
import json
import sys

import numpy as np

from range_engine_check import digest, load
from e01_trade_finance_audit import inspect_orders
import range_finance_audit as A


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/e01_known_veto'
OLD = ROOT/'work/wave_v106/e01_trade_gate'


def oracle(value: dict, mode: str) -> bool:
    """
    機能: 独立の論理式で入口情報資格と三政策の許可を判定する。
    引数: value(dict)は観測票、mode(str)は三種の政策識別子。
    返り値: boolは許可。未知や票不足を方向支持へ置換しない。
    """
    qualified = bool(value['known'] and value['direction_votes'] >= 2)
    if mode == 'VETO':
        return not (qualified and value['balance'] <= -.25)
    if not qualified:
        return False
    return value['balance'] >= .25 if mode == 'CONFIRM' else value['balance'] > -.25


def fixture(symbol: str, side: int, profitable: bool = False) -> dict:
    """
    機能: 部分返済待機中に別親が公開される独立の三親人工を作る。
    引数: symbol(str)、side(int)は商品と方向、profitable(bool)は場目標先着経路。
    返り値: dictは正常資格欠測・影三親・当時票を含む人工口座。
    """
    n = 17; tick = .5 if symbol == 'TOPIX' else 10.; quantity = 5 if symbol == 'TOPIX' else 10
    base = 4000. if symbol == 'TOPIX' else 68000.
    bid = np.full(n, base); ask = bid+tick
    if profitable:
        bid[4:] += 4*tick; ask[4:] = bid[4:]+tick
    if side < 0:
        bid, ask = 2*base-ask, 2*base-bid
    valid = np.ones(n, bool); valid[6:8] = False
    if profitable: valid[5] = False
    times = np.arange(n, dtype=float)
    partial = quantity//2
    feed = np.array([[1,0,0,side,quantity,base,0,1,0,5*tick],
        [4,0,0,-side,partial,base,0,0,0,0],
        [5,0,0,-side,quantity-partial,base,0,0,0,0],
        [6,0,1,side,quantity,base,0,1,0,5*tick],
        [9,0,1,-side,quantity,base,0,0,0,0],
        [10,0,2,side,quantity,base,0,1,0,5*tick],
        [14,0,2,-side,quantity,base,0,0,0,0]], float)
    features = {r: dict(known=True, reason=0, direction_votes=2, balance=0.) for r in (1,6,10)}
    quotes = dict(seq=np.arange(100,100+n,dtype=np.int64),time_s=times,bid=bid,ask=ask,quote_valid=valid)
    record = dict(time_s=times,price=(bid+ask)/2,seq=quotes['seq'],limit=100.,tick=tick)
    return dict(symbol=symbol,record=record,quotes=quotes,feed=feed,quiet=np.zeros(n,bool),
        quiet_force=np.zeros(n,bool),trade_features={'60':features},paper_SHA256='人工の不変紙上三親')


def cut(account: dict, rows: int) -> dict:
    """
    機能: 人工入力だけを接頭で切り、未返済と予約を保った短入力にする。
    引数: account(dict)、rows(int)は元人工と接頭行数。
    返り値: dictは未来を含まない接頭。終端強制返済の設定は増やさない。
    """
    value = deepcopy(account)
    value['record'] = {k:v[:rows] if isinstance(v,np.ndarray) else v for k,v in account['record'].items()}
    value['quotes'] = {k:v[:rows] for k,v in account['quotes'].items()}
    value['feed'] = account['feed'][account['feed'][:,0]<rows].copy()
    value['quiet'] = account['quiet'][:rows].copy(); value['quiet_force'] = account['quiet_force'][:rows].copy()
    return value


def main() -> None:
    """
    機能: 新金融前に独立真偽表・shadow・busy・次気配・UID料金・未来接頭を確認する。
    引数: なし。原資料・現在API・保存金融結果は一切読まない。
    返り値: Noneは所有領域の独立人工証跡。入口包含を収益包含と呼ばない。
    """
    target = HERE/'known_veto_三政策境界と影実玉接頭の独立人工.json'
    assert not target.exists()
    before = {p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    for name in ('common','catalog','daily','order_kernel','engine','policy','interface'):
        sys.modules[name] = load('known_veto独立_'+name,SOURCE/(name+'.py'))
    C,D,E,P,I = (sys.modules[n] for n in ('catalog','daily','engine','policy','interface'))
    old_policy = load('known_veto独立旧policy',OLD/'policy.py')
    checks = 0; table = []
    balances = (-1., -.25, float(np.nextafter(-.25,-np.inf)), float(np.nextafter(-.25,np.inf)),
        -.2, 0., .2, float(np.nextafter(.25,-np.inf)), .25, float(np.nextafter(.25,np.inf)), 1.)
    for known in (False,True):
        for count in (0,1,2,3,10):
            for balance in balances:
                v = dict(known=known,reason=8 if not known else 0,direction_votes=count if known else None,
                    balance=balance if known and count else None)
                new,_ = P.verdict(v,'KNOWN_VETO')
                confirm,_ = old_policy.verdict(v,'CONFIRM'); veto,_ = old_policy.verdict(v,'VETO')
                assert new == oracle(v,'KNOWN_VETO')
                assert confirm == oracle(v,'CONFIRM') and veto == oracle(v,'VETO')
                assert not confirm or new; assert not new or veto
                table.append(dict(既知=known,票=count,釣合=balance,肯定=confirm,既知中立=new,強逆拒否=veto)); checks += 5
    for malformed in (None,float('nan'),float('inf'),float('-inf')):
        try:
            P.verdict(dict(known=True,reason=0,direction_votes=2,balance=malformed),'KNOWN_VETO')
        except AssertionError:
            checks += 1
        else:
            raise AssertionError('不正な既知釣合を許可した')
    # ----------------------------------------
    # 新規公開以外の行は許可のまま。入口集合包含は実際の損益や取引集合を保証しない。
    artifacts = []
    configs = C.configs()
    assert len(configs) == 2 and {c['exit'] for c in configs} == {'GU','P1L8'}
    assert all(c['mode']=='KNOWN_VETO' and c['window_seconds']==60 and c['execution']=='D0' and c['offset_atr']==0 for c in configs)
    for symbol in ('TOPIX','NK225'):
        for side in (-1,1):
            a = fixture(symbol,side); quantity = 5 if symbol=='TOPIX' else 10
            gu = next(c for c in configs if c['exit']=='GU')
            accepted,_ = P.mask(a['feed'],len(a['record']['price']),a['trade_features']['60'],'KNOWN_VETO')
            assert np.all(accepted)
            got = I.execute(a,gu,True)
            assert [int(o[2]) for o in got[0][got[0][:,7]==1]] == [0,2]
            assert [int(o[0]) for o in got[0]] == [2,5,8,11,15]
            assert np.all(got[0][:,1]<got[0][:,0])
            assert got[7][6,1] == side*quantity and got[7][9,1] == 0
            assert not np.any(got[0][:,2]==1)
            out = I.account_output('人工',a,gu,got); inspect_orders(out,a['quotes'],symbol)
            if symbol=='TOPIX': np.testing.assert_array_equal(out['order_fees'],[209,83,125,209,209])
            else: np.testing.assert_array_equal(out['order_fees'],[110,55,55,110,110])
            # ----------------------------------------
            # 首親拒否のあと、影の部分返済と全部返済が残り、後続の親へ実参加できる。
            rejected = deepcopy(a); rejected['trade_features']['60'][1].update(known=False,reason=8,direction_votes=None,balance=None)
            rgot = I.execute(rejected,gu,True)
            assert [int(o[2]) for o in rgot[0][rgot[0][:,7]==1]] == [1,2]
            assert rgot[7][1,1] == side*quantity and rgot[7][5,1] == 0
            rout = I.account_output('人工拒否',rejected,gu,rgot); inspect_orders(rout,rejected['quotes'],symbol)
            # ----------------------------------------
            # 未来の票・時刻・価格を変えても、接頭の実注文と影状態は変わらない。
            for end in (3,6,8,10):
                truncated = I.execute(cut(a,end),gu,True)
                np.testing.assert_array_equal(truncated[0],got[0][got[0][:,0]<end])
                np.testing.assert_array_equal(truncated[7],got[7][:end])
                altered = deepcopy(a); altered['quotes']['bid'][end:]+=500.; altered['quotes']['ask'][end:]+=500.
                altered['record']['time_s'][end:]+=1000.
                for row,value in altered['trade_features']['60'].items():
                    if row>=end: value.update(known=False,reason=8,direction_votes=None,balance=None)
                future = I.execute(altered,gu,True)
                np.testing.assert_array_equal(future[0][future[0][:,0]<end],got[0][got[0][:,0]<end])
                np.testing.assert_array_equal(future[7][:end],got[7][:end]); checks += 4
            p = fixture(symbol,side,True); goal = next(c for c in configs if c['exit']=='P1L8')
            pgot = I.execute(p,goal,True); pout = I.account_output('人工場停止',p,goal,pgot)
            inspect_orders(pout,p['quotes'],symbol)
            assert pout['control']['種別']=='利益目標' and pout['control']['判断行']==4 and pout['control']['返済行']==8
            assert len(pout['orders'])==2 and not np.any(pout['orders'][1:,7]==1)
            assert pout['exit_target_uids'][-1]==pout['order_uids'][0]
            artifacts.append(dict(商品=symbol,方向=side,部分実注文=len(out['orders']),拒否後親=[p['親'] for p in rout['parent']],
                場停止判断=pout['control']['判断行'],返済行=pout['control']['返済行'],料金=out['summary']['費用'])); checks += 15
    # ----------------------------------------
    # 実行器と料金部品の数値変更はないことを独立のファイル指紋で確認する。
    for name in ('engine.py','daily.py','order_kernel.py','interface.py'):
        assert digest(SOURCE/name)==digest(OLD/name); checks += 1
    after = {p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    assert before==after
    proof = dict(全合格=True,範囲='既知中立ゲートの独立境界・次正常気配・影全親・実UID・部分料金・未来接頭人工。金融結果未読。',
        検査数=checks,独立会計検査数=sum(A.COUNT.values()),真偽表=table,人工=artifacts,source_SHA256=before,
        レビューsource_SHA256=digest(Path(__file__)),source開始終端一致=True,原板=0,原NPZ=0,正式cache=0,API=0,新金融=0,
        留意点=['CONFIRM⊆KNOWN_VETO⊆VETO は同じ公開行での許可集合だけ。影busy・次親参加・場停止が変わるため取引集合や収益の包含を主張しない。',
            '既知かつ方向票2以上が資格。−0.25丁度は拒否、少し上の中立は許可。unknownや票不足は推定しない。',
            '方向票はLast対直前BBOと公表正出来高差の1更新1票代理。真の攻撃数量や受信秒を追加証明しない。',
            'P1L8は初回5枚/10枚基準の全場料金後清算目標と損失予算。親ごとの1tick利確ではない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('既知中立の独立人工合格',checks,digest(target))


if __name__ == '__main__':
    main()
