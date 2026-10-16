"""後15完了の根明示後だけ、旧P0/J10の保存経済を前94へ独立照合する。"""

import argparse
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
OLD=WORK.parent/'wave_v94'


def read(path: Path) -> object:
    """
    機能: 許可されたP0_R0又はJ10の台帳及び指紋だけを読む。
    引数: path(Path)。
    返り値: objectはJSON又はpickle。新P1〜P3の成績は読まない。
    """
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix=='.pkl' else json.loads(stream.read().decode('utf-8'))


def sha(path: Path) -> str:
    """
    機能: 大きな保存台帳を一定メモリーで指紋化する。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def main() -> None:
    """
    機能: 現在の旧2対照62口座ずつを前94の保存台帳へ完全一致させる。
    引数: --root-back-complete(bool)は後15完了の根明示を受けた段階に限定する。
    返り値: Noneは新レビュー領域の証跡。新しい売買やP1〜P3の会計読取は行わない。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--root-back-complete',action='store_true')
    args=parser.parse_args()
    assert args.root_back_complete,'後15完了の根明示前は正式保存結果を読みません'
    for part in ('front','back'):
        assert len(list((WORK/part/'results').glob('*.json')))==38
    assert (WORK/'前16参考代表.json').exists() and (WORK/'事前固定.json').exists()
    pairs={'P0_R0':'J8','J10':'J10'};checks=[];fingerprints={}
    array_fields=('orders','trades','events','stats','slots','range_parent_diagnostics')
    hash_fields=('curve_SHA256','source_curve_SHA256','target_trace_SHA256','range_state_SHA256',
                 'risk_state_SHA256','price_source_SHA256','source_curve_column_SHA256')
    for current,previous in pairs.items():
        for part in ('front','back'):
            old_result_path=OLD/part/'results'/(previous+'.json')
            new_result_path=WORK/part/'results'/(current+'.json')
            old_result,new_result=read(old_result_path),read(new_result_path)
            old_path=OLD/part/'ledgers'/(previous+'.pkl');new_path=WORK/part/'ledgers'/(current+'.pkl')
            assert sha(old_path)==old_result['ledger_SHA256'] and sha(new_path)==new_result['ledger_SHA256']
            old_saved,new_saved=read(old_path),read(new_path)
            assert old_saved.keys()==new_saved.keys()
            assert old_result['rows']==new_result['rows']
            assert old_result['periods']==new_result['periods'] and old_result['stability']==new_result['stability']
            for key in sorted(new_saved):
                old,new=old_saved[key],new_saved[key]
                assert old['input_rows']==new['input_rows']
                for field in array_fields:np.testing.assert_array_equal(old[field],new[field])
                for field in hash_fields:assert old[field]==new[field],(current,key,field)
                for field in ('trace_changes','range_state_changes','risk_state_changes','price_source_changes'):
                    np.testing.assert_array_equal(old[field],new[field])
                assert len(new['loss_reentry_events'])==0
                checks.append(dict(現在ID=current,旧ID=previous,場=key[0],商品=key[1],全原行数=new['input_rows']))
            for path in (old_result_path,new_result_path,old_path,new_path):
                fingerprints[str(path.relative_to(ROOT))]=sha(path)
    assert len(checks)==124
    fingerprints[str(Path(__file__).relative_to(ROOT))]=sha(Path(__file__))
    for name in ('engine.py','strategy.py','research.py','catalog.py','事前固定.json'):
        path=WORK/name;fingerprints[str(path.relative_to(ROOT))]=sha(path)
    proof=dict(全合格=True,後15完了の根明示後=True,旧2対照口座数=124,各旧対照62口座=True,
               保存経済及び全原行指紋完全一致=True,新P1からP3損益閲覧=0,売買再実行=0,
               検査=checks,SHA256=fingerprints,API取得=0,実注文=0)
    path=HERE/'現在P0及びJ10全62保存経済の前94との独立完全一致.json'
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in proof.items() if key not in ('検査','SHA256')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
