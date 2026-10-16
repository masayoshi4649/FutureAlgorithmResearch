"""Rのtimer、欠測、待機接頭を本体不変更で追加検算する。"""

from pathlib import Path

import numpy as np

import artificial
import common

HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: R保有のforce/J、待機cut、無効quoteのtarget不採用を独立期待値へ照合する。
    引数: なし。
    返り値: None。金融と正式cacheを実行しない。
    """
    target=HERE/'R場末と待機欠測の追加人工検査.json';assert not target.exists()
    paths=[HERE/n for n in ('core.py','common.py','artificial.py','extra_artificial.py')]+[HERE.parent/'interface.py']
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths};checks={}
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10
        for side in (1,-1):
            p,c,cfg=artificial.fixture(symbol,side);p['record']['quote_valid'][940:944]=False
            out=artificial.play(p,c,cfg,q)
            assert out['orders'][:,0].tolist()==[331.,944.] and out['orders'][1,1]==939 and out['orders'][1,10]==940 and out['orders'][1,8]==6
            checks['Rforce既知timer後の初quoteまで欠測待機']=checks.get('Rforce既知timer後の初quoteまで欠測待機',0)+1
            p,c,cfg=artificial.fixture(symbol,side,2,2);p['record']['quote_valid'][331:941]=False
            out=artificial.play(p,c,cfg,q);assert len(out['orders'])==0 and np.any((out['events'][:,3]==6)&(out['events'][:,0]==700))
            checks['未約定Rをcutで取消し未来正常quoteで復活させない']=checks.get('未約定Rをcutで取消し未来正常quoteで復活させない',0)+1
            for time,reason in ((340,9),(940,6)):
                p,c,cfg=artificial.fixture(symbol,side);c['quiet_start_s'][time]=time;c['quiet'][time:]=True
                out=artificial.play(p,c,cfg,q);assert out['orders'][1,0]==time and out['orders'][1,1]==time-1 and out['orders'][1,8]==reason
                label='R保有Jtimerで当時初quote返済' if reason==9 else 'forceとJ同rowは旧force優先'
                checks[label]=checks.get(label,0)+1
            p,c,cfg=artificial.fixture(symbol,side);artificial.clearing(p,340,side,c['target_prices'][330]);p['record']['quote_valid'][340]=False
            out=artificial.play(p,c,cfg,q);assert out['orders'][1,1]==341 and out['orders'][1,0]==342
            checks['不正quoteの中心接触を利確判断へ救済しない']=checks.get('不正quoteの中心接触を利確判断へ救済しない',0)+1
            p,c,cfg=artificial.fixture(symbol,side,2,2);small,case=artificial.prefix(p,c,350);out=artificial.play(small,case,cfg,q,finish=False)
            assert len(out['orders'])==0 and len(out['trades'])==0 and out['target_trace'][-1,4]==q
            checks['未約定接頭を架空約定又は未来取消でflatにしない']=checks.get('未約定接頭を架空約定又は未来取消でflatにしない',0)+1
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=checks,source_SHA256=before,開始終端source一致=True,
        正式input読取=0,新金融再生=0,原板読取=0,API取得=0))
    print('Rtimer追加人工 '+str(sum(checks.values()))+'件',flush=True)


if __name__=='__main__':main()
