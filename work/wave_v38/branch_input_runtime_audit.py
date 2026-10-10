"""入力窓口の検索パス復元と、注文器モジュールを新規汚染しないことを検査する。"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path: Path) -> str:
    """機能: 検査に使った入力窓口の内容を固定する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: fresh importと旧注文器が先にある人工状態を分けて検査する。

    引数: なし。返り値: なし (None)。注文器コード・売買を実行しない。
    """
    names = ('engine_partial_restore','engine_shadow_plan')
    before_modules = {name:sys.modules.get(name) for name in names}
    assert all(module is None for module in before_modules.values()), '単独プロセスで検査する'
    before_path = list(sys.path)
    api = importlib.import_module('branch_inputs_runtime')
    assert sys.path == before_path
    assert all(sys.modules.get(name) is before_modules[name] for name in names)
    impl = sys.modules['branch_inputs']
    public = ('initialize','entry_artifact','entry','condition_artifact','condition','publication_valid',
              'source_bits','random_direction','directions','branch_choice')
    assert all(getattr(api,name) is getattr(impl,name) for name in public)
    assert Path(impl.__file__).resolve() == HERE/'branch_inputs.py'
    # ----------------------------------------
    # path復元は、先に登録された旧注文器を直す機能ではないことを明示的に確認する。
    old_modules = {}
    for name in names:
        old = ModuleType(name); old.__file__ = str(HERE.parent/'wave_v37'/(name+'.py'))
        sys.modules[name] = old; old_modules[name] = old
    try:
        importlib.reload(api)
        assert sys.path == before_path
        assert all(sys.modules[name] is old_modules[name] for name in names)
        rejected = 0
        for name in names:
            try:
                assert Path(sys.modules[name].__file__).resolve() == HERE/(name+'.py')
            except AssertionError:
                rejected += 1
        assert rejected == 2
    finally:
        for name in names: sys.modules.pop(name,None)
    assert all(sys.modules.get(name) is None for name in names)
    value = dict(全合格=True, fresh_import検索パス不変=True, fresh_import注文器登録追加なし=True,
        公開10関数は元関数そのもの=True, 既登録旧注文器は黙って置換しない=True,
        旧注文器の明示パス検査拒否数=rejected, 注文器実行=False, 売買再生=False, 新損益読取=False,
        限界='先に登録済みの旧版はpath復元だけでは解決しない。runnerはv38注文器を明示パスから登録し__file__を検査する。',
        SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in
                (Path(__file__),HERE/'branch_inputs.py',HERE/'branch_inputs_runtime.py')})
    (HERE/'branch_input_runtime_audit.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print('検索パス不変・注文器新規登録なし・公開10関数同一・旧版誤参照2件拒否。')


if __name__ == '__main__':
    main()
