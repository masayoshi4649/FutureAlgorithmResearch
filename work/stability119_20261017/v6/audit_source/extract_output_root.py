"""旧抽出器の指紋相対ROOTと追加出力位置が一致しない接続を小人工で反証する。"""

import ast
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
V6 = HERE.parent
ROOT = V6.parents[2]


def main() -> None:
    """
    機能: 旧fingerprintsの同一ASTをshaスタブだけで動かし出力ROOT外を検出する。
    引数: なし。元市場・CSV・cache本文を読まない。
    返り値: None。数値処理ではなくパスだけの人工証跡を保存する。
    """
    source = ROOT / 'work/wave_v48/update_20261001/replay_added_session.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'fingerprints')
    namespace = dict(ROOT=V6 / 'legacy_root', Path=Path, ThreadPoolExecutor=ThreadPoolExecutor,
                     sha=lambda path: '0' * 64)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(source), 'exec'), namespace)
    outside = V6 / 'prepared/人工/new_inputs.pkl'
    found = None
    try:
        namespace['fingerprints']([outside])
    except ValueError as exc:
        found = str(exc)
    assert found is not None
    inside = V6 / 'legacy_root/work/v6_prepared/人工/new_inputs.pkl'
    assert namespace['fingerprints']([inside]) == {'work/v6_prepared/人工/new_inputs.pkl': '0' * 64}
    output = HERE / '旧抽出出力のmirror相対ROOT外エラーの人工反証.json'
    assert not output.exists()
    output.write_text(json.dumps(dict(再現=True, 原因='extract終端fingerprintsのp.relative_to(ROOT)へmirror外preparedを渡す',
        現出力位置=outside.as_posix(), 旧ROOT=(V6 / 'legacy_root').as_posix(), 例外=found,
        回避確認='preparedを所有mirror内へ置けば旧AST不変で相対位置を生成できる。',
        元市場読取=0, CSV読取=0, cache読取=0, 金融=0), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(found)


if __name__ == '__main__':
    main()
