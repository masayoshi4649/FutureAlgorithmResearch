"""単一口座の源切替、支持系譜、保有接頭とJITを追加で反証する。"""

from copy import deepcopy
from pathlib import Path
import traceback
import time

import numpy as np

import artificial
import catalog
import common
import interface

HERE=Path(__file__).resolve().parent
CHECKS={}


def check(label: str, value: bool) -> None:
    """
    機能: 追加人工の独立期待値を数える。
    引数: label(str)、value(bool)は名前と一致。
    返り値: None。不一致はsourceを保存して止める。
    """
    assert value,label;CHECKS[label]=CHECKS.get(label,0)+1


def main() -> None:
    """
    機能: C→Rの全後続、未採用pulse再利用禁止、支持維持、prefix/JITを確認する。
    引数: なし。
    返り値: None。正式33場金融を開始しない。
    """
    target=HERE/'源切替と支持維持及び保有接頭の追加人工.json';assert not target.exists()
    paths=[HERE/n for n in ('extension_artificial.py','artificial.py','core.py','interface.py','selection.py','features.py','catalog.py')]
    before={str(p.relative_to(common.ROOT)):common.digest(p) for p in paths}
    fixture=artificial.FIXTURE
    for symbol in ('TOPIX','NK225'):
        qty=10 if symbol=='TOPIX' else 20
        for side in (1,-1):
            p,c=fixture.fixture(symbol,side);r=deepcopy(c);r['entry_id']='R_OWN';r['event'][:]=0;r['support_price'][:]=np.nan;r['decisions']=[]
            tick=p['record']['tick'];opening=p['reference_open'];boundary=float(c['support_price'][330])-side*4*tick
            fixture.quote(p,340,boundary if side==1 else boundary-tick)
            support=float(p['record']['bid'][390] if -side==1 else p['record']['ask'][390])
            fixture.event(p,r,332,-side,opening if -side==1 else opening+tick)
            fixture.event(p,r,390,-side,support)
            normal=dict(deepcopy(c),entry_id='人工AUTO');n=len(c['event'])
            normal['entry_families']=np.where(normal['event']!=0,1,0).astype(np.int8);normal['target_prices']=np.full(n,np.nan)
            normal['decisions']+=deepcopy(r['decisions']);normal['decisions'].sort(key=lambda v:v['row'])
            for at in (332,390):
                normal['event'][at]=r['event'][at];normal['support_price'][at]=r['support_price'][at];normal['entry_families'][at]=2
            E=p['record']['ask'][391] if -side==1 else p['record']['bid'][391]
            target=E-side*5*tick;normal['target_prices'][332]=target;normal['target_prices'][390]=target
            fixture.quote(p,400,target if -side==1 else target-tick)
            cfg=catalog.setting('AUTO',3,.2,'R21')
            full=interface.play(p,normal,cfg,quantity=qty,python=True)
            check('C保有中のR候補は消費見送り、後の新Rだけ再参加',full['orders'][full['orders'][:,7]==1,1].tolist()==[330.,390.])
            check('CとRを一口座の親で順に回し両建てなし',len(full['trades'])==2 and full['trades'][:,1].tolist()==[0.,1.] and not np.any((full['target_trace'][:,0]>0)&(full['target_trace'][:,1]>0)))
            check('RだけB4支持と固定中心の出口',full['trades'][1,13]==10)
            for diag in full['raw_entry_diagnostics']:
                original=next(v for v in normal['decisions'] if v['row']==diag['decision_row'])
                check('実親の選択済み支持根拠は元episode exact',diag['episode']['selected_support_roots']==original['selected_support_roots'] and diag['fixed_support_price']==original['support_price'])
            # ----------------------------------------
            # Rが保有中の接頭は未返済のまま。変更された未来は過去注文へ混ぜない。
            length=399;small=deepcopy(p);small['record']={k:v[:length].copy() if isinstance(v,np.ndarray) else v for k,v in p['record'].items()}
            short={k:v[:length].copy() if isinstance(v,np.ndarray) else deepcopy(v) for k,v in normal.items()}
            short['decisions']=[v for v in short['decisions'] if v['row']<length]
            past=interface.play(small,short,cfg,quantity=qty,finish=False,python=True)
            check('保有中prefixに未来中心返済なし',len(past['orders'])==3 and len(past['trades'])==1 and past['target_trace'][-1,:2].sum()==qty)
            np.testing.assert_array_equal(past['orders'],full['orders'][full['orders'][:,0]<length])
            np.testing.assert_allclose(past['curve'],full['curve'][:length],atol=1e-4,rtol=0)
            future=deepcopy(p);future_case=deepcopy(normal);fixture.quote(future,399,opening+side*1000*tick)
            future_case['entry_quality'][399:]=False;future_case['entry_reset'][399:]=True;future_case['target_prices'][399:]=opening*10
            changed=interface.play(future,future_case,cfg,quantity=qty,python=True)
            np.testing.assert_array_equal(changed['orders'][changed['orders'][:,0]<length],past['orders'])
            np.testing.assert_allclose(changed['curve'][:length],past['curve'],atol=1e-4,rtol=0)
            check('未来quote/資格/対象変更でprefix不変',True)
            # ----------------------------------------
            # 正式と同じreadonly正常列・元qualification、選択eventだけ新writeableでJIT照合。
            common.immutable(p)
            for name in ('entry_quality','entry_reset','execution_to_raw_index'):normal[name].flags.writeable=False
            native=interface.play(p,normal,cfg,quantity=qty,python=False)
            for name in ('orders','trades','growth_cohorts','events','curve','source_curve','target_trace','judgments','control_events','candidate_controls'):
                np.testing.assert_array_equal(native[name],full[name])
            check('readonly正式signatureのPython/JIT全経済制御一致',True)
    assert before=={p:common.digest(common.ROOT/p) for p in before}
    common.save(HERE/'源切替と支持維持及び保有接頭の追加人工.json',dict(全合格=True,人工専用=True,検査件数=CHECKS,
        source_SHA256=before,開始終端source一致=True,新金融再生=0,原板読取=0,正式input読取=0,API取得=0))
    print('追加人工合格 '+str(sum(CHECKS.values()))+'検査',flush=True)


if __name__=='__main__':
    try:main()
    except Exception as error:
        folder=HERE/('追加人工False_'+time.strftime('%Y%m%d_%H%M%S'));folder.mkdir()
        for n in ('extension_artificial.py','core.py','interface.py'):(folder/n).write_bytes((HERE/n).read_bytes())
        common.save(folder/'False.json',dict(全合格=False,例外=str(error),traceback=traceback.format_exc(),完了検査=CHECKS,新金融再生=0))
        raise
