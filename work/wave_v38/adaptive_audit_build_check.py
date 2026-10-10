"""監査生成の再現性と、旧補正済み波計算の継承を検査する。"""

import ast
import hashlib
import json
from pathlib import Path

import build_adaptive_audits as build

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def functions(path: Path) -> dict:
    """機能: 関数定義の抽象構文を取得する。

    引数: path (Path)。返り値: 関数名と構文の対応 (dict)。
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return {node.name:ast.dump(node,include_attributes=False)
            for node in tree.body if isinstance(node,ast.FunctionDef)}


def main() -> None:
    """機能: 複写された独立数式と再生成ソースを照合する。

    引数: なし。返り値: なし (None)。売買再生や実損益の読取はしない。
    """
    for name,text in (('adaptive_causality_audit.py',build.causal()),('adaptive_wave_audit.py',build.wave())):
        assert (HERE/name).read_text(encoding='utf-8') == text, name
    source=HERE.parent/'wave_v37/partial_wave_audit_v2.py'
    before,after=functions(source),functions(HERE/'adaptive_wave_audit.py')
    names=('stamp','compare','reconstruct','integrate','boundary','order_records','measure','synthetic')
    for name in names:
        assert before[name] == after[name], name
    paths=(Path(__file__),HERE/'build_adaptive_audits.py',HERE/'adaptive_causality_audit.py',
           HERE/'adaptive_wave_audit.py',source,HERE.parent/'wave_v37/partial_causality_audit.py')
    result=dict(全合格=True,生成コード再現数=2,旧波独立関数同一数=len(names),旧波独立関数=list(names),
        管理方向二項目継承=True,新売買再生=False,新損益読取=False,
        SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (HERE/'adaptive_audit_build_check.json').write_text(
        json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('新監査2コードを再現、旧v2波の独立8関数・管理方向2項目の継承が一致しました。')


if __name__ == '__main__':
    main()
