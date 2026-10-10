"""原監査を保持し、状態不一致を合格へ変えない診断版だけを別名で生成する。"""

import ast
from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

HELPER='''
def phase_diagnostic(control: np.ndarray, expected: np.ndarray, budget: np.ndarray, times: np.ndarray) -> dict:
    """機能: 減量状態の契約差を全行記録し、経済検査の合格とは分離する。

    引数: control/expected/budget/times (ndarray)。返り値: 状態契約と全不一致行 (dict)。
    """
    actual=control[:,2]
    assert actual.shape==expected.shape and np.isfinite(actual).all() and np.isfinite(expected).all()
    bad=np.flatnonzero(np.abs(actual-expected)>1e-6)
    rows=[]
    for i in bad:
        known=bool(budget[i] and control[i,13] and control[i,8]==0 and
            ((actual[i]==1 and expected[i]==0) or (actual[i]==3 and expected[i]==2)))
        rows.append(dict(row=int(i),時刻秒=float(times[i]),組=int(control[i,1]),
            実状態=float(actual[i]),期待状態=float(expected[i]),実予約=float(control[i,8]),
            実予算予約=bool(control[i,13]),独立予算予約=bool(budget[i]),
            復元資格枚数=float(control[i,6]),既知の取消後残存型=known))
    return dict(状態契約合格=len(bad)==0,状態不一致行数=len(bad),状態不一致=rows,
        既知残存型に限定=all(r['既知の取消後残存型'] for r in rows))

'''


def sha(path: Path) -> str:
    """機能: 実装の内容指紋を取得する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 原版の一比較だけを記録へ置換し、逆置換ASTと全assertを照合する。

    引数: なし。返り値: なし (None)。原監査・既存固定・成績は変更しない。
    """
    source_path=HERE/'adaptive_slot_audit.py'
    source=source_path.read_text(encoding='utf-8')
    old="    close(control[:,2],phase,'全行の減量状態')"
    new='    phase_proof=phase_diagnostic(control,phase,expected_budget,times)'
    old_return='    return dict(影の独立公開と執行=transmitted,'
    new_return='    return dict(**phase_proof,影の独立公開と執行=transmitted,'
    assert source.count(old)==source.count(old_return)==1
    candidate=source.replace(old,new).replace(old_return,new_return)+HELPER
    reverse=candidate.removesuffix(HELPER).replace(new,old).replace(new_return,old_return)
    assert reverse==source and ast.dump(ast.parse(reverse))==ast.dump(ast.parse(source))
    before_assert=[ast.dump(n) for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Assert)]
    after_assert=[ast.dump(n) for n in ast.walk(ast.parse(candidate.removesuffix(HELPER))) if isinstance(n,ast.Assert)]
    assert before_assert==after_assert
    target=HERE/'adaptive_slot_diagnostic.py'
    target.write_text(candidate,encoding='utf-8')
    # ----------------------------------------
    # 全口座再生・全数値照合を原版のまま残し、出力先と合否の二分だけを別にする。
    accounting_path=HERE/'adaptive_accounting_audit.py'
    accounting=accounting_path.read_text(encoding='utf-8').split('\ndef selftest()')[0]
    replacements=[('import adaptive_slot_audit as slots','import adaptive_slot_diagnostic as slots'),
        ("'adaptive_accounting_details'","'adaptive_accounting_diagnostic_details'"),
        ('全監査合格=True','経済監査合格=True,状態契約合格=all(p[\'状態契約合格\'] for p in evidence),'
         '全監査合格=all(p[\'状態契約合格\'] for p in evidence),'
         '状態不一致行数=sum(p[\'状態不一致行数\'] for p in evidence),'
         '既知残存型に限定=all(p[\'既知残存型に限定\'] for p in evidence)'),
        ('監査固定SHA256=fixed_sha',"監査固定SHA256=fixed_sha,診断固定SHA256=runner.digest(HERE/'adaptive_accounting_diagnostic_fixed.json')")]
    derived=accounting
    for old_text,new_text in replacements:
        assert old_text in derived
        derived=derived.replace(old_text,new_text)
    recovered=derived
    for old_text,new_text in reversed(replacements):
        recovered=recovered.replace(new_text,old_text)
    assert recovered==accounting
    assert ast.dump(ast.parse(recovered))==ast.dump(ast.parse(accounting))
    core=HERE/'adaptive_accounting_diagnostic_core.py'
    core.write_text(derived,encoding='utf-8')
    record=dict(全合格=True,既知状態比較だけ記録化=True,逆置換全文一致=True,逆置換AST一致=True,
        原assert全文全順序一致=True,原assert数=len(before_assert),状態不一致を合格へ変更=False,
        全口座会計の逆置換全文AST一致=True,出力先と状態経済合否以外の会計不変=True,
        既存コード変更=False,API取得数=0,現在保存物使用=False,
        参照SHA256={p.relative_to(ROOT).as_posix():sha(p) for p in (source_path,target,accounting_path,core,Path(__file__))})
    (HERE/'adaptive_phase_diagnostic_build.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('原assert全維持・比較一箇所のみ診断記録化・原版不変',len(before_assert),flush=True)


if __name__=='__main__':
    main()
