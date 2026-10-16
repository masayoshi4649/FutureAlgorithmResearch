"""完成14源の私有コピーへ、先に固定した票と独立実玉参照を接続する。"""

import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import traceback
import numpy as np
from price_vote_reference import Point, window, peer
from protect_state_reference import Reference, Row

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ENGINE = ROOT / 'work/e01_protect_reentry_20261014/engine'
PRIVATE = HERE / 'private_protect_core'
CHECKS = {'価格票': 0, '独立小口座': 0, '配列': 0, '接頭': 0}


def qualified_points(account: dict) -> list[Point]:
    """
    機能: 独立逐次方式で過去の時計/原seqを資格へ重ねる。
    引数: account(dict) は人工のrecord/quotesのみ。
    返り値: list[Point] は当行までで正常かを固定した価格観測。
    """
    r, q = account['record'], account['quotes']; out = []; maxt = -math.inf; maxseq = -1
    for i, (clock, last, seq) in enumerate(zip(r['time_s'], r['price'], r['seq'])):
        good = (q['quote_valid'][i] and all(math.isfinite(v) for v in (clock, last, q['bid'][i], q['ask'][i])) and
                last > 0 and 0 < q['bid'][i] < q['ask'][i] and clock >= maxt and seq > maxseq)
        out.append(Point(float(clock), float(last), bool(good), int(seq)))
        if math.isfinite(clock): maxt = max(maxt, clock)
        maxseq = max(maxseq, int(seq))
    return out


# ----------------------------------------
def price_checks(votes: object) -> None:
    """
    機能: 単純窓の全行独立票と二市場strict過去を完成sourceへ照合する。
    引数: votes(object) は私有コピーの完成価格票module。
    返り値: None。乱数seed固定の合成だけを使用する。
    """
    rng = np.random.default_rng(108)
    for case in range(14):
        packet = {'accounts': {}}
        points = {}
        for product in ('TOPIX', 'NK225'):
            times = np.cumsum(rng.choice([0., .5, 1., 3., 10.], 180))
            if product == 'NK225': times -= .25
            prices = (4000. if product == 'TOPIX' else 65000.) + np.cumsum(rng.choice([-1., 0., 1.], 180))
            seq = np.arange(180, dtype=np.int64) * 2 + 1
            normal = np.ones(180, bool); normal[23] = False; normal[52] = False
            if case % 3 == 0: times[48] = times[47] - 1
            if case % 4 == 0: seq[81] = seq[80]
            if case % 5 == 0: prices[92] = np.nan
            bids = np.full(180, 4000. if product == 'TOPIX' else 65000.)
            a = dict(record=dict(time_s=times, price=prices, seq=seq),
                     quotes=dict(quote_valid=normal, bid=bids, ask=bids + (.5 if product == 'TOPIX' else 10.)))
            packet['accounts'][product] = a; points[product] = qualified_points(a)
        actual = votes.pair(packet)
        for product, observations in points.items():
            other = points['NK225' if product == 'TOPIX' else 'TOPIX']
            saved = actual[product]
            for i, p in enumerate(observations):
                expected = window(observations, i)
                assert bool(saved['own']['known'][i]) == expected['known']
                assert int(saved['own']['count'][i]) == expected['count']
                if expected['known']: assert math.isclose(saved['own']['balance'][i], expected['balance'])
                else: assert math.isnan(saved['own']['balance'][i])
                opponent = peer(other, p.clock) if p.normal else dict(known=False, count=0, balance=None)
                assert bool(saved['peer_known'][i]) == opponent['known']
                assert int(saved['peer_count'][i]) == (opponent['count'] if opponent['known'] else 0)
                if opponent['known']: assert math.isclose(saved['peer_balance'][i], opponent['balance'])
                else: assert math.isnan(saved['peer_balance'][i])
                CHECKS['価格票'] += 6


# ----------------------------------------
def fixture(symbol: str, side: int, mode: str, exit_id: str, kind: str) -> tuple[list, dict]:
    """
    機能: 独立参照を実装読み取り前に確定した小経路の部品から構成する。
    引数: symbol/mode/exit_id/kind(str)、side(int) は人工条件。
    返り値: tuple はRow列と紙上イベント辞書。全期間は完成政策の固定率を使用する。
    """
    base = 4000. if symbol == 'TOPIX' else 65000.; tick = .5 if symbol == 'TOPIX' else 10.
    clocks = [0., 300., 301., 302., 303., 304., 305., 306., 307., 308., 309., 310., 1000.]
    shifts = [0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0., 0.]
    normals = [True] * len(clocks); quiet = [False] * len(clocks); balances = [side] * len(clocks)
    events = {1: [dict(new=True, cid=40, side=side, q=5 if symbol == 'TOPIX' else 10, price=base)]}
    if kind == 'opposed_reentry':
        balances[3] = -side
        shift = math.ceil(base * .00025 / tick) * tick
        shifts[5:] = [shift] * (len(clocks) - 5)
        if mode == 'PULL': shifts[6] = 0.; shifts[7:] = [math.ceil(base * .000125 / tick) * tick] * (len(clocks) - 7)
    elif kind == 'fak_expire':
        shifts[2] = 3 * tick; shifts[3] = 0.; shifts[4:] = [8 * tick] * (len(clocks) - 4)
    elif kind == 'partial_cancel':
        normals[2] = False; events[2] = [dict(new=False, cid=40, side=-side, q=1, price=base)]
        shifts[3:] = [20 * tick] * (len(clocks) - 3)
    elif kind == 'same_row_withdraw':
        events[1].append(dict(new=False, cid=40, side=-side, q=1, price=base))
        shifts[3:] = [8 * tick] * (len(clocks) - 3)
    elif kind == 'loss_gap':
        shifts[3:] = [-math.ceil(base * .004 / tick) * tick] * (len(clocks) - 3)
        normals[4] = False; shifts[5:] = [2 * shifts[3]] * (len(clocks) - 5)
    elif kind == 'native_protection':
        shift = math.ceil(base * .002 / tick) * tick
        shifts[3:] = [shift] * (len(clocks) - 3); shifts[5:] = [shift - math.ceil(base * .0005 / tick) * tick] * (len(clocks) - 5)
    elif kind == 'quiet':
        quiet[3] = True; normals[3] = False
        events[4] = [dict(new=False,cid=40,side=-side,q=5 if symbol=='TOPIX' else 10,price=base),
                     dict(new=True,cid=41,side=side,q=5 if symbol=='TOPIX' else 10,price=base)]
        shifts[5:] = [10 * tick] * (len(clocks) - 5)
    else: raise AssertionError(kind)
    rows = []
    for clock, shift, valid, silent, balance in zip(clocks, shifts, normals, quiet, balances):
        bid = base + side * shift - (tick if side < 0 else 0.)
        vote = dict(known=valid, count=4 if valid else 0, balance=balance if valid else None)
        rows.append(Row(clock, base + side * shift, bid, bid + tick, valid, vote, vote, silent))
    return rows, events


def execute_actual(core: object, catalog: object, symbol: str, mode: str, exit_id: str, rows: list, events: dict, jit: bool) -> tuple:
    """
    機能: 純小Row/feedだけを完成coreへ渡し、私有JIT又はPython九出力を受け取る。
    引数: core/catalog(object)、symbol/mode/exit_id(str)、rows(list)、events(dict)、jit(bool)。
    返り値: tuple は一次九出力。実入力又は旧金融結果を取得しない。
    """
    array = lambda key: np.asarray([getattr(r, key) for r in rows], dtype=float)
    valid = np.asarray([r.normal for r in rows], bool); q = catalog.CAP[symbol]
    feed = []
    for i, group in events.items():
        for event in group: feed.append([i, max(0,i-1), event['cid'], event['side'], event['q'], event['price'], 0, int(event['new']), 0, 1. if event['new'] else 0.])
    feed = np.asarray(feed, float).reshape(-1,10)
    config = next(c for c in catalog.configs() if c['reentry_id']==mode and c['exit_id']==exit_id)
    own_known = np.asarray([r.own['known'] for r in rows], bool)
    own_count = np.asarray([r.own['count'] for r in rows], np.int64)
    own_balance = np.asarray([r.own['balance'] if r.own['balance'] is not None else np.nan for r in rows])
    num, den = catalog.FEE_RATIO[symbol]; fn = core.simulate if jit else core.simulate.py_func
    return fn(array('clock'),array('last'),array('bid'),array('ask'),valid,feed,np.asarray([r.quiet for r in rows],bool),np.zeros(len(rows),bool),
              valid,own_known,own_count,own_balance,own_known.copy(),own_count.copy(),own_balance.copy(),0.,1000.,q,
              .5 if symbol=='TOPIX' else 10.,catalog.VALUE[symbol],num,den,
              ('ORIGIN','PULL','BREAK','ADAPTIVE').index(mode),('TARGET','TIGHT_TRAIL','WIDE_TRAIL').index(exit_id),
              config['parent_stop_fraction'],config['parent_target_fraction'],config['arm_fraction'],config['draw_fraction'],config['floor_fraction'],
              config['session_stop_fraction'],config['session_profit_fraction'],config['pull_fraction'],config['recover_fraction'],config['break_fraction'],2)


def state_checks(core: object, catalog: object) -> None:
    """
    機能: 固定純参照から完成coreの注文/UID/局所起点/全場清算を限定配列比較する。
    引数: core/catalog(object) は私有の完成source。
    返り値: None。未知行や閉親表現差を架空の不一致へしない。
    """
    kinds = ('opposed_reentry','fak_expire','partial_cancel','same_row_withdraw','loss_gap','native_protection','quiet')
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            for mode in ('ORIGIN','PULL','BREAK','ADAPTIVE'):
                for exit_id in ('TARGET','TIGHT_TRAIL','WIDE_TRAIL'):
                    for kind in kinds:
                        rows,events = fixture(symbol,side,mode,exit_id,kind)
                        reference = Reference(symbol,mode,exit_id)
                        for i,row in enumerate(rows): reference.step(i,row,events.get(i,[]))
                        py = execute_actual(core,catalog,symbol,mode,exit_id,rows,events,False)
                        compiled = execute_actual(core,catalog,symbol,mode,exit_id,rows,events,True)
                        for a,b in zip(py[:8],compiled[:8]): np.testing.assert_allclose(a,b,equal_nan=True,atol=1e-5,rtol=1e-12); CHECKS['配列']+=1
                        assert py[8]==compiled[8]
                        expected = np.array([[o['row'],o['source'],o['cid'],o['side'],o['q'],o['price'],int(o['new'])] for o in reference.orders],float).reshape(-1,7)
                        np.testing.assert_array_equal(py[0][:,[0,1,2,3,4,5,7]],expected,err_msg=str((symbol,side,mode,exit_id,kind)))
                        np.testing.assert_array_equal(py[1],np.array([o['uid'] for o in reference.orders],np.int64))
                        np.testing.assert_allclose(py[2][:,1],[c['liquidation'] for c in reference.curve],atol=1e-5,rtol=1e-12)
                        np.testing.assert_array_equal(py[2][:,4]+py[2][:,5],[c['held'] for c in reference.curve])
                        CHECKS['配列']+=4; CHECKS['独立小口座']+=1
                        for cut in (2,4,7):
                            short = execute_actual(core,catalog,symbol,mode,exit_id,rows[:cut],{i:g for i,g in events.items() if i<cut},False)
                            np.testing.assert_array_equal(short[0],py[0][py[0][:,0]<cut])
                            np.testing.assert_allclose(short[2],py[2][:cut],equal_nan=True,atol=1e-5,rtol=1e-12)
                            CHECKS['接頭']+=1


# ----------------------------------------
def main() -> None:
    """
    機能: 所有最終14署名を私有コピーへ結び、純期待とsourceの実接続証跡を保存する。
    引数: なし。所有artificial/14sourceだけを読んで純合成を実行する。
    返り値: None。sourceや旧cacheを変更せず、Falseも保持する。
    """
    target = HERE / '現在票と十二実親出口の独立純期待及び完成14源接続_v3.json'
    assert not target.exists()
    sources = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ENGINE.glob('*.py'))}
    proofpath = ENGINE/'十二保護と新価格票及び独立実親の人工検査_v2.json'
    raw=proofpath.read_bytes();proof=json.loads(raw.decode('utf-8-sig'))
    assert proof['全合格'] and proof['source_SHA256']==sources and len(sources)==14
    PRIVATE.mkdir(exist_ok=True)
    for rel,sha in sources.items():
        source=ROOT/rel;destination=PRIVATE/source.name
        if destination.exists():assert hashlib.sha256(destination.read_bytes()).hexdigest()==sha
        else:shutil.copyfile(source,destination)
    sys.path.insert(0,str(PRIVATE));import common,core,catalog,price_votes
    try:
        price_checks(price_votes);state_checks(core,catalog)
        assert sources=={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ENGINE.glob('*.py'))}
        value=dict(全合格=True,所有最終source_SHA256=sources,所有人工SHA256=hashlib.sha256(raw).hexdigest(),検査=CHECKS,
                   独立参照source_SHA256={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in ('price_vote_reference.py','protect_state_reference.py','protect_source_check.py')},
                   確定変更='公開拒否でも新geometry審査を消費、同row全paper処理後に新origin採否。rootの金融前確定に基づきv4/sourceをarchive保全後、独立モデルへ反映。',
                   初版False='quiet初normal新paperORIGIN拒否でも、審査消費の正常Lastanchorは形成される。私のrefが通常イベントresetと審査消費resetを同一視して未知化したため、初版False/source保持後review_consumedを区別した。経済source14不変更。',
                   v2False='独立モデルのreview_consumed呼出をreturn_allへ誤適用した修正コードを保全し、公開審査消費admitだけへ移した。所有source変更無し。',
                   限界=['経済curveの親CID保持表現や全pub拒否ログは独立全列期待へ含めず、源/所有人工と最終specで別監査する。',
                         '合成全量FAK/価格代理時計の数学契約。実受信順・板深度・実部分約定を証明しない。'],
                   新金融=0,保存packet=0,台帳本文=0,原板=0,旧107結果=0,API=0)
    except BaseException:
        value=dict(全合格=False,所有最終source_SHA256=sources,検査=CHECKS,原因=traceback.format_exc(),
                   独立参照source_SHA256={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in ('price_vote_reference.py','protect_state_reference.py','protect_source_check.py')},
                   新金融=0,保存packet=0,台帳本文=0,原板=0,旧107結果=0,API=0)
        target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');raise
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('完成14源独立接続合格 '+str(CHECKS)+' SHA '+hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
