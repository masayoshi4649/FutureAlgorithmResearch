"""正式原因mainを呼ばず、実注文・拒否反復・同入口残差と無取引分母を人工で検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode=True
import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: 私有人工の純関数だけを接続し正式mainを実行しない。
    引数: name(str)、path(Path)。
    返り値: object。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 人工検査中にsourceが変わらないことを確認する。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sparse(value: np.ndarray) -> np.ndarray:
    """
    機能: 人工bodyの全行状態を独自の変化行へ保存する。
    引数: value(ndarray[float])。
    返り値: ndarray[float]。根research.ledgerは使わない。
    """
    indexes=[0]
    for row in range(1,len(value)):
        if not np.array_equal(value[row],value[row-1],equal_nan=True): indexes.append(row)
    if indexes[-1]!=len(value)-1: indexes.append(len(value)-1)
    return np.column_stack((np.asarray(indexes),value[indexes]))


def stored(output: dict) -> dict:
    """
    機能: 原因関数に必要な人工物理台帳と疎状態だけを組み立てる。
    引数: output(dict)。
    返り値: dict。正式金融又は実原板を開かない。
    """
    names=('orders','trades','growth_cohorts','growth_cohort_columns','growth_parent_diagnostics',
        'growth_events','growth_state_columns','growth_gate_state_columns')
    result={name:output[name] for name in names};result['input_rows']=len(output['growth_state_trace'])
    for name in ('growth_state','growth_gate_state'):
        value=output[name+'_trace']
        result[name+'_changes']=sparse(value)
        result[name+'_SHA256']=hashlib.sha256(value.tobytes()).hexdigest()
    return result


def main() -> None:
    """
    機能: 5条件の私有人工20口座と一致残差・未知段階拒否を検証する。
    引数: なし。
    返り値: None。新しい人工証跡だけを保存し、正式原因mainは実行しない。
    """
    paths=[Path(__file__),HERE/'原因を実注文と同入口で独立に比較する.py',HERE/'selection.py',
        WORK/'review_pre/局所人工の新余裕と据置及び19列を独立反証する.py',
        WORK/'catalog.py',WORK/'strategy.py',WORK/'engine.py']
    before={path.relative_to(ROOT).as_posix():digest(path) for path in paths}
    cause=module('102独立原因の人工純関数',paths[1])
    selection=module('102独立原因人工の既独立現金',HERE/'selection.py')
    artificial=module('102反証所有の私有短列だけ',WORK/'review_pre/局所人工の新余裕と据置及び19列を独立反証する.py')
    strategy=module('102原因検算の私有bodyだけ',WORK/'strategy.py')
    catalog=module('102原因人工の20定義だけ',WORK/'catalog.py')
    configs={value['id']:value for value in catalog.catalog()}
    rows={ident:[] for ident in cause.IDS}; parents={ident:[] for ident in cause.IDS}
    counts=dict(人工口座=0,実注文=0,実追加=0,疎復元及び19数理=0,同入口残差=0,無取引分母=0,小数量分母=0)
    sessions=['2000-01-03_人工買','2000-01-03_人工売','2000-01-04_人工無取引']
    prices={(session,symbol):dict(price=np.asarray([4000. if symbol=='TOPIX' else 70000.])) for session in sessions for symbol in cause.SYMBOLS}
    for ident in cause.IDS:
        config=configs[ident]
        for symbol in cause.SYMBOLS:
            for side,session in ((1,sessions[0]),(-1,sessions[1])):
                data=artificial.fixture(symbol,side);key=next(iter(data))
                output=artificial.run(strategy,config,data);ledger=stored(output)
                accounting=selection.account(ledger,symbol)
                rows[ident].append(dict(session=session,symbol=symbol,**accounting))
                actual_parents=cause.parents(ledger,session,symbol)
                assert sum(parent['net'] for parent in actual_parents)==accounting['net']
                parents[ident].extend(actual_parents)
                diagnostic=cause.gates(ledger,config,data[key]['record'])
                assert diagnostic['実追加注文数']==accounting['adding_order_count']
                assert diagnostic['実fill停止線短縮数']<=diagnostic['実追加注文数']
                assert diagnostic['余裕拒否エピソード数']<=diagnostic['余裕拒否原行数']
                assert diagnostic['据置拒否エピソード数']<=diagnostic['据置拒否原行数']
                counts['人工口座']+=1;counts['実注文']+=accounting['order_count']
                counts['実追加']+=diagnostic['実追加注文数'];counts['疎復元及び19数理']+=ledger['input_rows']
            empty=selection.totals([]);empty.update(cohorts=selection.totals([],cohort=True),actual_peak_quantity=0)
            rows[ident].append(dict(session=sessions[2],symbol=symbol,**empty))
            stable=cause.stability(rows[ident],parents[ident],symbol,prices,sessions)
            assert stable['全セッション数']==stable['共通分母場数']==3 and stable['活動セッション数']==2
            assert stable['無取引セッション数']==1 and stable['共通cap']==(10 if symbol=='TOPIX' else 20)
            assert stable['黒字セッション数']+stable['赤字セッション数']<=2
            negative=[min(row['net']/stable['共通単位円'][row['session']],0.)**2 for row in rows[ident] if row['symbol']==symbol]
            assert np.isclose(stable['下方RMS共通単位'],np.sqrt(sum(negative)/3))
            counts['無取引分母']+=1
    assert counts['人工口座']==20 and counts['疎復元及び19数理']==300

    # ----------------------------------------
    # 未一致親を落とさず、対応親差と両側残差を全額差へ再結合する。
    for symbol in cause.SYMBOLS:
        for ident in (cause.IDS[0],cause.IDS[2],cause.IDS[3]):
            result=cause.matched(parents[ident],parents[cause.IDS[1]],symbol,ident,cause.IDS[1])
            assert result['同入口親数']==2 and result['同入口差と未一致残差が全額差に一致']
            counts['同入口残差']+=1
        left=deepcopy([row for row in parents[cause.IDS[0]] if row['symbol']==symbol])
        right=deepcopy([row for row in parents[cause.IDS[1]] if row['symbol']==symbol])
        unmatched_left=deepcopy(left[0]); unmatched_left['initial_key']=('左だけ',*unmatched_left['initial_key'][1:]);unmatched_left['net']=-123.
        unmatched_right=deepcopy(right[0]); unmatched_right['initial_key']=('右だけ',*unmatched_right['initial_key'][1:]);unmatched_right['net']=57.
        left.append(unmatched_left);right.append(unmatched_right)
        result=cause.matched(left,right,symbol,'人工左','人工右')
        assert result['左未一致親数']==result['右未一致親数']==1
        assert result['左未一致親収支']==-123. and result['右未一致親収支']==57.
        assert result['全収支差']==result['同入口収支差']-180.
        counts['同入口残差']+=1

    # ----------------------------------------
    # 円額縮小だけで同じ赤字頻度を高確度へ読み替えず、共通capを保つ。
    for symbol in cause.SYMBOLS:
        original=cause.stability(rows[cause.IDS[4]],parents[cause.IDS[4]],symbol,prices,sessions)
        scaled_rows=deepcopy(rows[cause.IDS[4]]);scaled_parents=deepcopy(parents[cause.IDS[4]])
        for row in scaled_rows: row['net']*=.5;row['profit']*=.5;row['loss']*=.5
        for row in scaled_parents: row['net']*=.5
        scaled=cause.stability(scaled_rows,scaled_parents,symbol,prices,sessions)
        assert original['活動黒字割合']==scaled['活動黒字割合'] and original['赤字親割合']==scaled['赤字親割合']
        assert original['共通cap']==scaled['共通cap'] and original['共通分母場数']==scaled['共通分母場数']
        assert np.isclose(original['下方RMS共通単位']*.5,scaled['下方RMS共通単位'])
        counts['小数量分母']+=1
    refused=subprocess.run([sys.executable,'-X','utf8','-B',str(paths[1])],capture_output=True,text=True,encoding='utf-8')
    assert refused.returncode!=0 and '全31正式再生完了の明示通知前は新金融原因を読みません' in refused.stderr
    assert before=={path.relative_to(ROOT).as_posix():digest(path) for path in paths}
    proof=dict(全合格=True,検査件数=counts,未許可正式CLI拒否=True,scope='私有20口座の物理注文・疎復元・19拒否再計算と同入口/未一致親残差。'
        '無取引1/3を勝ちへ含めず、半額尺度で赤字頻度が変わらないことを独立確認。根sourceと金融mainを使わない。',
        正式前後損益閲覧=0,正式原因main実行=0,実原板読取=0,現在API取得=0,実注文=0,過去成果変更=0,SHA256=before)
    (HERE/'独立原因関数の私有人工と段階拒否.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,検査件数=counts,正式原因main実行=0),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
