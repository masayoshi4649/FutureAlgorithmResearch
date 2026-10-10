"""旧独立監査の判定を維持し、同期短縮影の別式計画だけを新領域へ追加する。"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def sha(path: Path) -> str:
    """機能: 元と派生した監査コードの内容指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    """機能: 変更位置を限定した独立影監査と、呼出先だけ差し替えた枠監査を生成する。

    引数: なし。返り値: 逆置換・AST・全assert保存の証跡(dict)。旧ファイルは変更しない。
    """
    old_path=HERE.parent/'wave_v38/adaptive_shadow_oracle.py'
    old=old_path.read_text(encoding='utf-8');text=old
    additions=[]
    replacements=[
        ('from numba import njit','from numba import njit\nimport adaptive_shadow_oracle as baseline_oracle'),
        ('                tick,start,limit,q0):','                tick,start,limit,q0,tighten_atr,tight_width,prepare_allow):'),
        ('                proposed=_tick(extreme-d*3*a,tick,-d)',
         '                width=tight_width if tighten_atr>0 and d*(extreme-anchor)>=tighten_atr*a else 3.\n                proposed=_tick(extreme-d*width*a,tick,-d)'),
        ('                if state[i]!=0 and np.isfinite(atr[i]) and atr[i]>0:',
         '                if prepare_allow[i] and state[i]!=0 and np.isfinite(atr[i]) and atr[i]>0:'),
        ('        curves[\'opening_price\'],curves[\'opening\'],pid,curves[\'split\'],ready[\'tick\'],ready[\'start\'],ready[\'limit\'],q0)',
         '        curves[\'opening_price\'],curves[\'opening\'],pid,curves[\'split\'],ready[\'tick\'],ready[\'start\'],ready[\'limit\'],q0,\n        config[\'tighten_atr\'],config[\'tight_width\'],allow)'),
    ]
    for before,after in replacements:
        assert text.count(before)==1,before
        text=text.replace(before,after,1);additions.append((before,after))
    before="    curves=account(ready,result);pid=np.full(n,-1,np.int64)"
    after="""    assert min_delay_seconds==0., '今回の統合は伝達0秒だけ'
    assert (config['tighten_atr'],config['tight_width']) in ((0.,1.),(3.,1.5),(3.,.75))
    assert config['entry_atr']==.25 and config['stop_atr']==1. and config['main_trail']==3.
    assert config['split_target']==2. and config['activation_atr']==1.5 and config['timeout_min']==360.
    scheduler=result['scheduler']
    baseline_config=dict(config,tighten_atr=0.,tight_width=1.)
    baseline_proof=baseline_oracle.audit(ready,scheduler,baseline_config,state,0.,observed_fill)
    assert all(baseline_proof[k] is True for k in ('影全会計一致','独立公開計画一致','独立準備一致','最新成熟計画一致','全行注文成立不成立一致'))
    allow=np.zeros(n,np.bool_)
    fresh=scheduler['prepare_events'][:,1].astype(np.int64)
    assert np.all((fresh>=0)&(fresh<n)) and len(np.unique(fresh))==len(fresh)
    allow[fresh]=True
    assert np.asarray(result['schedule_prepare_allow']).dtype==np.bool_
    assert np.array_equal(allow,result['schedule_prepare_allow'])
    for field in ('prepare_events','entry_preparations'):_compare(result[field],scheduler[field],'同期初回/'+field)
    _compare(result['orders'][result['orders'][:,7]==1],scheduler['orders'][scheduler['orders'][:,7]==1],'同期初回注文')
    curves=account(ready,result);pid=np.full(n,-1,np.int64)"""
    assert text.count(before)==1
    text=text.replace(before,after,1);additions.append((before,after))
    restored=text
    for before,after in reversed(additions):
        assert restored.count(after)==1
        restored=restored.replace(after,before,1)
    assert restored==old
    old_ast=ast.parse(old);new_ast=ast.parse(text)
    old_functions={f.name:ast.dump(f,include_attributes=False) for f in old_ast.body if isinstance(f,ast.FunctionDef)}
    new_functions={f.name:ast.dump(f,include_attributes=False) for f in new_ast.body if isinstance(f,ast.FunctionDef)}
    changed=[name for name in old_functions if old_functions[name]!=new_functions[name]]
    assert changed==['publication','audit']
    target=HERE/'integration_shadow_oracle.py';target.write_text(text,encoding='utf-8')
    slot_old_path=HERE.parent/'wave_v38/adaptive_slot_audit.py';slot_old=slot_old_path.read_text(encoding='utf-8')
    before='import adaptive_shadow_oracle as shadow_oracle';after='import integration_shadow_oracle as shadow_oracle'
    assert slot_old.count(before)==1
    slot=slot_old.replace(before,after,1)
    assert slot.replace(after,before,1)==slot_old
    old_asserts=sum(isinstance(x,ast.Assert) for x in ast.walk(ast.parse(slot_old)))
    assert old_asserts==sum(isinstance(x,ast.Assert) for x in ast.walk(ast.parse(slot)))
    slot_target=HERE/'integration_slot_audit.py';slot_target.write_text(slot,encoding='utf-8')
    return dict(全合格=True,影監査の変更関数=changed,影監査逆置換完全一致=True,
        枠監査はimport一箇所だけ=True,枠監査全assert数=old_asserts,元影を旧独立監査で全検査=True,
        新旧SHA256={p.relative_to(ROOT).as_posix():sha(p) for p in (Path(__file__),old_path,target,slot_old_path,slot_target)},
        新Night使用=False,新売買再生=False)


if __name__=='__main__':
    value=build();(HERE/'integration_audit_build.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('独立影2関数の限定追加、枠監査import以外完全一致',flush=True)
