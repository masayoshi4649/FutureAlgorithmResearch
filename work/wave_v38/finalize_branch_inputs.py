"""既監査の入力固定へ、数値関数を変えない実行窓口の証跡を結合する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path: Path) -> str:
    """機能: ファイルの指紋を取得する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """機能: UTF-8 の監査証跡を読み取る。

    引数: path (Path)。返り値: 保存内容 (dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    """機能: 入力因果監査と import 隔離監査を検算して最終固定を作る。

    引数: なし。返り値: なし (None)。売買関数と損益ファイルは使用しない。
    """
    fixed = read(HERE/'branch_input_fixed.json')
    causal = read(HERE/'branch_input_causality.json')
    runtime = read(HERE/'branch_input_runtime_audit.json')
    assert fixed['全入力監査合格'] and causal['全入力監査合格'] and runtime['全合格']
    assert causal['再利用列入力数'] == 520 and causal['新窓入力数'] == 156
    assert causal['新窓prefix数'] == causal['新窓future数'] == 312
    assert causal['新窓reflection数'] == 156
    assert causal['方向乱数入力数'] == 13312 and causal['分岐乱数入力数'] == 4992
    assert len(causal['原本78SHA256']) == 78
    assert not causal['新損益読取'] and not causal['売買再生']
    assert not causal['現在保存物使用'] and causal['API取得数'] == 0
    assert runtime['fresh_import検索パス不変'] and runtime['fresh_import注文器登録追加なし']
    assert runtime['公開10関数は元関数そのもの'] and runtime['既登録旧注文器は黙って置換しない']
    assert runtime['旧注文器の明示パス検査拒否数'] == 2
    assert not runtime['注文器実行'] and not runtime['売買再生'] and not runtime['新損益読取']
    references = dict(fixed['SHA256'])
    for name, sha in runtime['SHA256'].items():
        assert name not in references or references[name] == sha
        references[name] = sha
    for path in (HERE/'branch_input_fixed.json', HERE/'branch_input_runtime_audit.json',
                 HERE/'branch_input_contract.md', Path(__file__)):
        references[path.relative_to(ROOT).as_posix()] = digest(path)
    for name, sha in references.items():
        assert digest(ROOT/name) == sha, name

    # ----------------------------------------
    # 原固定を残し、窓口に必要な追加証跡だけを一つの参照集合へ結ぶ。
    result = dict(全入力監査合格=True, 実行窓口='branch_inputs_runtime',
        入力数値関数変更=False, 旧固定変更=False, 注文器の明示パス検査必要=True,
        再利用列入力数=520, 新窓入力数=156, 方向乱数入力数=13312, 分岐乱数入力数=4992,
        元入力固定SHA256=digest(HERE/'branch_input_fixed.json'),
        因果監査SHA256=digest(HERE/'branch_input_causality.json'),
        実行窓口監査SHA256=digest(HERE/'branch_input_runtime_audit.json'),
        原本78SHA256=causal['原本78SHA256'], SHA256=references,
        新損益読取=False, 売買再生=False, 現在保存物使用=False, API取得数=0)
    (HERE/'branch_input_runtime_fixed.json').write_text(
        json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('元入力固定を維持し、実行窓口・全入力監査・原本78指紋を結合しました。',flush=True)


if __name__ == '__main__':
    main()
