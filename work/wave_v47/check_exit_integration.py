"""同期した初回と数量・短縮出口の接続を、旧人工入力と因果破損で確認する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

import exit_integration as runner
_paths=list(sys.path)
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'wave_v38'))
sys.path.append(str(Path(__file__).resolve().parent.parent/'wave_v33'))
import adaptive_statistics_selftest as fixtures
sys.path[:]=_paths
import integration_accounting_audit as independent

HERE=Path(__file__).resolve().parent


def digest(path: Path) -> str:
    """機能: 実際に検査したソースの指紋を返す。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prefix_check(a: tuple, b: tuple, cut: int) -> None:
    """機能: 実・出口影・通常影と許可列の全過去を比較する。

    引数: a/b(tuple)、cut(int)。返り値: なし。
    """
    runner.reference.gate_prefix(a,b,cut)
    for name in runner.engine.shadow_engine.FIELDS:
        left,right=a[0]['shadow']['scheduler'][name],b[0]['shadow']['scheduler'][name]
        if name in ('curve','atr_curve','plans','execution_plans'):
            left,right=left[:cut],right[:cut]
        elif name=='stats':
            continue
        else:
            column=runner.reference.causal.EVENTS[name]
            left,right=left[left[:,column]<cut],right[right[:,column]<cut]
        np.testing.assert_array_equal(left,right,err_msg='通常影/'+name)
    np.testing.assert_array_equal(a[0]['shadow']['schedule_prepare_allow'][:cut],b[0]['shadow']['schedule_prepare_allow'][:cut])


def main() -> dict:
    """機能: 12方式・両銘柄・活動有無を全人工再生して結果を保存する。

    引数: なし。返り値: 検算数と旧一致・因果証跡(dict)。実相場は使わない。
    """
    count=legacy_count=future_count=mirror_count=0
    for spec in runner.catalog():
        for symbol in ('TOPIX','NK225'):
            for inactive in (False,True):
                ready,columns,base_config=fixtures.artificial(spec,symbol,inactive)
                config=dict(base_config,tighten_atr=spec['tighten_atr'],tight_width=spec['tight_width'])
                valid=np.ones(len(ready['last']),np.bool_)
                actual=runner.play(spec,ready,columns,config,gate_valid=valid)
                runner.initial_identity(actual[0])
                independent.inspect(spec,ready,actual[0],config,actual[1])
                if spec['exit_id']=='E00':
                    old=runner.reference.play(spec,ready,columns,base_config,gate_valid=valid)
                    for field in runner.FIELDS:
                        np.testing.assert_array_equal(actual[0][field],old[0][field],err_msg=field)
                    for field in runner.engine.shadow_engine.FIELDS:
                        np.testing.assert_array_equal(actual[0]['shadow'][field],old[0]['shadow'][field],err_msg=field)
                    legacy_count+=1
                n=len(ready['last']);cut=max(2,int(n*.55))
                clipped=runner.reference.causal.clipped(ready,cut)
                small=runner.play(spec,clipped,tuple(v[:cut].copy() for v in columns),config,gate_valid=valid[:cut])
                prefix_check(actual,small,cut)
                changed=deepcopy(ready);changed['last'][cut:]+=20.
                changed_columns=tuple(v.copy() for v in columns)
                for k in (0,1,3):changed_columns[k][cut:]*=-1
                future=runner.play(spec,changed,changed_columns,config,gate_valid=valid)
                prefix_check(actual,future,cut);future_count+=1
                center=float(2*np.ceil(np.max(ready['last'])/ready['tick'])*ready['tick'])
                mirrored=dict(ready,last=center-ready['last'])
                mirrored_columns=tuple(-v if k in (0,1,3,6) else v.copy() for k,v in enumerate(columns))
                mirror=runner.play(spec,mirrored,mirrored_columns,config,gate_valid=valid)
                runner.reference.causal.reflected_result(actual[0],mirror[0],center,True)
                for name in ('shadow',):
                    runner.reference.causal.reflected_result(actual[0][name],mirror[0][name],center,False)
                runner.reference.causal.reflected_result(actual[0]['shadow']['scheduler'],mirror[0]['shadow']['scheduler'],center,False)
                mirror_count+=1;count+=1
    sources=[Path(__file__),HERE/'exit_integration.py',HERE/'exit_shadow_integrated.py',HERE/'exit_partial_integrated.py',
             Path(runner.reference.engine.__file__),Path(runner.reference.engine.shadow_engine.__file__)]
    proof=dict(全合格=True,人工入力数=count,E00全配列旧一致入力数=legacy_count,
        prefixと未来改変検査数=future_count,反射検査数=mirror_count,新ナイト使用=False,
        参照資料SHA256={p.relative_to(HERE.parents[1]).as_posix():digest(p) for p in sources})
    (HERE/'check_exit_integration.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(proof,ensure_ascii=False));return proof


if __name__=='__main__':main()
