"""取消の公開後に古い指値を復活させた架空台帳を、四引数会計で拒否する。"""

from copy import deepcopy
from pathlib import Path

import artificial
import common
import accounting

HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 同原map/公表後TREND/静観の不正な候補台帳を独立会計で拒否する。
    引数: なし。
    返り値: None。既人工出力を不正fixtureへ写すだけで新金融を生成しない。
    """
    target=HERE/'四引数会計の同原行と待機取消拒否人工.json';assert not target.exists()
    paths=[HERE/n for n in ('core.py','accounting.py','accounting_guard_artificial.py','artificial.py')]+[HERE.parent/'interface.py']
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths};checks={}
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10
        for side in (1,-1):
            p,c,cfg=artificial.fixture(symbol,side,2,2)
            artificial.clearing(p,350,side,c['entry_limit_prices'][330]-side*p['record']['tick']);artificial.clearing(p,400,side,c['target_prices'][330])
            out=artificial.play(p,c,cfg,q)
            for reason in ('既知TREND取消','予定静観取消','元event方向不一致','元map不一致','公開mode不一致'):
                changed=deepcopy(c)
                if reason=='既知TREND取消':changed['range_pending_trend'][340]=True
                elif reason=='予定静観取消':changed['quiet_start_s'][340]=340.
                elif reason=='元event方向不一致':changed['event'][330]*=-1
                elif reason=='元map不一致':changed['execution_to_raw_index']+=1
                else:changed['entry_modes'][330]=1
                rejected=False
                try:accounting.inspect(('人工',symbol),p['record'],out,changed)
                except AssertionError:rejected=True
                assert rejected,reason;checks[reason]=checks.get(reason,0)+1
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(target,dict(全合格=True,人工専用=True,検査件数=checks,source_SHA256=before,開始終端source一致=True,
        正式input読取=0,新金融再生=0,原板読取=0,API取得=0))
    print('取消/同原行会計の拒否人工 '+str(sum(checks.values()))+'件',flush=True)


if __name__=='__main__':main()
