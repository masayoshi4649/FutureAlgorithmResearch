"""readonly実入力資格と静観優先、未知待機を私有人工で補足する。"""

from copy import deepcopy
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode=True
import common
import features

ART=common.module('106局所位相の補足人工素材',common.HERE/'artificial.py')


def main() -> None:
    """
    機能: 未知/ALIGNED消失の待機、既知静観/期限優先、保有不変とreadonly JITを確認する。
    引数: なし。私有人工だけを使う。
    返り値: None。新金融/正式入力/原板/APIは使用しない。
    """
    checks=[];paths=[Path(__file__),common.HERE/'artificial.py',common.HERE/'features.py',common.HERE/'interface.py',common.HERE/'engine/core.py']
    source={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}
    for symbol in ('TOPIX','NK225'):
        q=5 if symbol=='TOPIX' else 10
        for side in (1,-1):
            p,normal,cfg=ART.FIXTURE.fixture(symbol,side,2,2)
            ART.FIXTURE.clearing(p,400,side,p['reference_open']-side*p['record']['tick'])
            short=ART.packet_fixture(side)['short'][symbol]
            for name in ('own','peer'):
                short[name]['direction'][:]=0;short[name]['known'][:]=True
            short['own']['known'][350]=False;short['peer']['direction'][350]=-side
            for policy in ('OWN_VETO','BOTH_VETO','ALIGNED'):
                normal['local_cancel_buy']=features.decisions(short,1,policy)[1]
                normal['local_cancel_sell']=features.decisions(short,-1,policy)[1]
                out=ART.INTERFACE.play(p,normal,cfg,q,python=True)
                assert out['trades'][0,2]==400 and not out['pending_cancel_diagnostics']
            checks.append(f'{symbol}/{side}/未知行を逆方向取消へ置換しない')
            short['own']['known'][350]=True;short['own']['direction'][:]=side;short['peer']['direction'][:]=0
            short['peer']['direction'][330]=side
            normal['local_cancel_buy']=features.decisions(short,1,'ALIGNED')[1]
            normal['local_cancel_sell']=features.decisions(short,-1,'ALIGNED')[1]
            out=ART.INTERFACE.play(p,normal,cfg,q,python=True)
            assert out['trades'][0,2]==400 and not out['pending_cancel_diagnostics']
            checks.append(f'{symbol}/{side}/ALIGNED準備後の同方向消失は追加取消しない')

            quiet=deepcopy(normal);quiet['quiet'][400:450]=True;quiet['quiet_start_s'][400]=400.
            out=ART.INTERFACE.play(p,quiet,cfg,q,python=True)
            assert not len(out['orders'])
            checks.append(f'{symbol}/{side}/初reach同行の既知J取消はlivefillより先')
            cutp,cutnormal,cfg=ART.FIXTURE.fixture(symbol,side,2,2)
            ART.FIXTURE.clearing(cutp,700,side,cutp['reference_open']-side*cutp['record']['tick'])
            cutnormal['local_cancel_buy']=np.zeros(1001,bool);cutnormal['local_cancel_sell']=np.zeros(1001,bool)
            out=ART.INTERFACE.play(cutp,cutnormal,cfg,q,python=True)
            assert not len(out['orders'])
            checks.append(f'{symbol}/{side}/初reach同行のentry期限取消はlivefillより先')

            held,hcase,cfg=ART.FIXTURE.fixture(symbol,side,2,1)
            hcase['local_cancel_buy']=np.ones(1001,bool);hcase['local_cancel_sell']=np.ones(1001,bool)
            out=ART.INTERFACE.play(held,hcase,cfg,q,python=True);old=ART.reference(held,hcase,cfg,q)
            for name in ART.ARRAYS:np.testing.assert_array_equal(out[name],old[name])
            checks.append(f'{symbol}/{side}/fill後の局所反対だけでは保有出口を変えない')

            normal['local_cancel_buy'][:]=False;normal['local_cancel_sell'][:]=False
            common.immutable(p)
            for name in ('quiet','quiet_start_s','execution_to_raw_index'):normal[name].flags.writeable=False
            py=ART.INTERFACE.play(p,normal,cfg,q,python=True);jit=ART.INTERFACE.play(p,normal,cfg,q,python=False)
            for name in ART.ARRAYS:np.testing.assert_array_equal(py[name],jit[name])
            checks.append(f'{symbol}/{side}/実loader相当readonly価格と静観及び新writable列のJIT一致')
    assert source=={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}
    common.write(common.HERE/'直近位相の未知静観とreadonly資格の補足人工.json',dict(全合格=True,検査件数=len(checks),検査=checks,
        source_SHA256=source,正式input読取=0,新金融再生=0,原板読取=0,API取得=0))
    print(f'局所位相の未知/静観/readonly {len(checks)} 件合格、金融0',flush=True)


if __name__=='__main__':main()
