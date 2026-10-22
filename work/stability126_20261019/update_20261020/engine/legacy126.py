"""旧48/85の数値源を同bytes所有mirrorで接続し、旧26入力の読取だけを注入へ置換する。"""

import ast
from contextlib import contextmanager
import importlib.abc
import importlib.util
import os
from pathlib import Path
import socket
import sys

import numba
import numpy as np

from source126 import HERE, ROOT, MIRROR, SMALL_FIXED, copy_source, digest, read, save


CACHE = str(HERE / 'jit_artificial')
DISCOVERED = set()
SOURCE_READ_ACTIVE = False


def source_read_guard(event: str, args: tuple) -> None:
    """
    機能: SOURCE発見中の市場・cache本文読取を実際のopen境界で拒否する。
    引数: event(str)、args(tuple)はPython監査イベント。
    返り値: None。Python/library/JITと明示小FIXED以外のrepo読取は例外。
    """
    if not SOURCE_READ_ACTIVE or event != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    path = Path(os.fsdecode(args[0])).resolve()
    mode = str(args[1] or '')
    flags = int(args[2] or 0)
    writing = any(c in mode for c in ('w', 'a', 'x', '+')) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
    if writing:
        assert path.is_relative_to(HERE), ('SOURCE段階の所有域外書込', str(path))
        return
    if not path.is_relative_to(ROOT):
        return
    if path.suffix in ('.py', '.pyc', '.pyd', '.dll', '.nbi', '.nbc'):
        return
    assert path in {MIRROR / p for p in SMALL_FIXED}, ('SOURCE段階の本文読取拒否', str(path))


sys.addaudithook(source_read_guard)


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 所有再生からの外部通信を拒絶する。
    引数: args(tuple)、kwargs(dict)は任意の接続引数。
    返り値: None。常に例外を送出する。
    """
    raise RuntimeError('保存入力以外のAPI及び注文接続は禁止です')


def ensure_source(path: Path, discover: bool) -> None:
    """
    機能: 動的import先を所有sourceへ限定し、SOURCE段階だけ不足Pythonを複写する。
    引数: path(Path)、discover(bool)は所有位置とsource発見の許可。
    返り値: None。正式数値段階で未固定sourceを増やさない。
    """
    path = path.resolve()
    assert not (path.is_relative_to(ROOT/'work') and not path.is_relative_to(HERE)), ('旧sourceの直接import拒否', str(path))
    if not path.is_relative_to(MIRROR):
        return
    if path.suffix == '.py':
        if not path.exists():
            assert discover, ('未固定の動的source', str(path))
            copy_source(path.relative_to(MIRROR).as_posix())
        DISCOVERED.add(path)


class SourceFinder(importlib.abc.MetaPathFinder):
    """標準名importにも所有mirrorのPythonだけを追加する探索器。"""

    def __init__(self, discover: bool) -> None:
        """
        機能: 発見段階か固定後実行かを保持する。
        引数: discover(bool)は不足sourceの複写許可。
        返り値: None。
        """
        self.discover = discover

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> object:
        """
        機能: 旧sourceのsys.pathに沿って所有コピーのmoduleを見つける。
        引数: fullname(str)、path(object)、target(object)はimport機構の引数。
        返り値: objectはmodule仕様又はNone。通常ライブラリには介入しない。
        """
        for folder in list(path or sys.path):
            base = Path(folder or '.').resolve()
            if not base.is_relative_to(MIRROR):
                continue
            candidate = base / (fullname.rsplit('.', 1)[-1] + '.py')
            origin = ROOT / candidate.relative_to(MIRROR)
            if candidate.exists() or (self.discover and origin.exists()):
                ensure_source(candidate, self.discover)
                return importlib.util.spec_from_file_location(fullname, candidate)
        return None


class CacheConfig:
    """旧sourceによるNumba保存先の上書きを新所有先へ限定する設定代理。"""

    def __init__(self, original: object) -> None:
        """
        機能: 代理先を保持する。
        引数: original(object)はNumbaの通常設定。
        返り値: None。
        """
        object.__setattr__(self, 'original', original)

    def __getattr__(self, name: str) -> object:
        """
        機能: JIT保存先だけを所有領域へ固定する。
        引数: name(str)は設定名。
        返り値: objectは設定値。
        """
        return CACHE if name == 'CACHE_DIR' else getattr(self.original, name)

    def __setattr__(self, name: str, value: object) -> None:
        """
        機能: 旧数値源の保存先要求を新所有先へ置換する。
        引数: name(str)、value(object)は要求設定。
        返り値: None。数値計算の設定は元のまま。
        """
        setattr(self.original, name, CACHE if name == 'CACHE_DIR' else value)


@contextmanager
def isolated(discover: bool = False) -> object:
    """
    機能: SOURCE発見及び正式実行のimportとJITを所有mirrorへ隔離する。
    引数: discover(bool)は不足Pythonだけの複写を許すSOURCE段階。
    返り値: contextmanagerは実行範囲。金融はこの関数だけでは開始しない。
    """
    global SOURCE_READ_ACTIVE
    old_source_flag = SOURCE_READ_ACTIVE
    SOURCE_READ_ACTIVE = discover
    old_config, old_dir = numba.config, numba.config.CACHE_DIR
    old_env = os.environ.get('NUMBA_CACHE_DIR')
    old_spec = importlib.util.spec_from_file_location
    old_path = list(sys.path)
    old_connect, old_create = socket.socket.connect, socket.create_connection
    finder = SourceFinder(discover)

    def spec_hook(name: str, location: object, *args: object, **kwargs: object) -> object:
        """
        機能: 動的importの位置にもSOURCE固定の境界を適用する。
        引数: name(str)、location(object)、args(tuple)、kwargs(dict)は標準import引数。
        返り値: objectは通常のmodule仕様。
        """
        if location is not None:
            ensure_source(Path(location), discover)
        return old_spec(name, location, *args, **kwargs)

    numba.config = CacheConfig(old_config)
    old_config.CACHE_DIR = CACHE
    os.environ['NUMBA_CACHE_DIR'] = CACHE
    sys.meta_path.insert(0, finder)
    importlib.util.spec_from_file_location = spec_hook
    socket.socket.connect, socket.create_connection = deny, deny
    try:
        yield
    finally:
        SOURCE_READ_ACTIVE = old_source_flag
        importlib.util.spec_from_file_location = old_spec
        sys.meta_path.remove(finder)
        sys.path[:] = old_path
        socket.socket.connect, socket.create_connection = old_connect, old_create
        numba.config = old_config
        old_config.CACHE_DIR = old_dir
        if old_env is None:
            os.environ.pop('NUMBA_CACHE_DIR', None)
        else:
            os.environ['NUMBA_CACHE_DIR'] = old_env


def module(name: str, relative: str) -> object:
    """
    機能: 固定された所有mirrorだけから旧moduleを接続する。
    引数: name(str)、relative(str)は固有名と旧repo相対位置。
    返り値: objectは旧数値module。原repoのPythonを実行importしない。
    """
    path = MIRROR / relative
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def function(relative: str, name: str, namespace: dict) -> object:
    """
    機能: I/Oを伴う上位moduleから必要な純関数を同じASTで取り出す。
    引数: relative/name(str)、namespace(dict)は所有sourceと関数環境。
    返り値: objectは数値式を変えない関数。任意の文の書換えはしない。
    """
    path = MIRROR / relative
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    found = [v for v in tree.body if isinstance(v, ast.FunctionDef) and v.name == name]
    assert len(found) == 1, (relative, name)
    single = ast.Module(body=found, type_ignores=[])
    exec(compile(ast.fix_missing_locations(single), str(path), 'exec'), namespace)
    return namespace[name]


def runtime() -> dict:
    """
    機能: 旧85E01・旧48抽出と補助純関数を新所有moduleで組み立てる。
    引数: なし。isolated内で呼び出す。
    返り値: dictは旧数値runtime。旧26cacheや金融結果を読まない。
    """
    old = module('v6_original_e01', 'work/wave_v85/strategy.py')
    extractor = module('v6_original_extract', 'work/wave_v48/update_20261001/replay_added_session.py')
    for name, relative in (('v6_source_reference', 'work/wave_v16/reference.py'),
                           ('v6_source_raw', 'work/wave_v8/raw_features.py'),
                           ('v6_source_depth', 'work/wave_v23/depth_features.py')):
        module(name, relative)
    core = module('v6_raw44', 'work/wave_v103/input/core.py')
    votes = module('v6_volume_votes', 'work/wave_v106/trade_gate/votes.py')
    correction_tree = ast.parse((MIRROR/'work/wave_v103/input_v2/correction.py').read_text(encoding='utf-8-sig'))
    changed_node = next(v for v in correction_tree.body if isinstance(v, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'CHANGED' for t in v.targets))
    correct = function('work/wave_v103/input_v2/correction.py', 'correct_arrays',
                       {'np': np, 'CHANGED': ast.literal_eval(changed_node.value)})
    feed = function('work/wave_v87/round10/strategy.py', 'order_feed', {'np': np})
    initialize = initialized_function(old)
    return dict(old=old, extractor=extractor, raw_core=core, votes=votes,
                correct_arrays=correct, order_feed=feed, initialize=initialize)


def initialized_function(old: object) -> object:
    """
    機能: 旧26読取initializeだけを除き、旧85initializeの後半を同一ASTで保持する。
    引数: old(object)は所有コピーの旧85戦略。
    返り値: objectは初期化関数。FIXEDと新INPUTSの注入後だけ呼ぶ。
    """
    source = MIRROR / 'work/wave_v85/strategy.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    fn = next(v for v in tree.body if isinstance(v, ast.FunctionDef) and v.name == 'initialize')
    assert ast.unparse(fn.body[1]) == 'base.integration.reference.initialize()'
    fn.body.pop(1)
    namespace = dict(vars(old))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(source), 'exec'), namespace)
    return namespace['initialize']


def inject(rt: dict, inputs: dict, signals: dict) -> dict:
    """
    機能: 元小FIXEDと今回のE01入力だけを旧initialize後半へ注入する。
    引数: rt/inputs/signals(dict)は所有runtimeと追加場素材。
    返り値: dictは元のgate/EMA/共同B00。旧26入力は読み込まない。
    """
    reference = rt['old'].base.integration.reference
    reference.old.FIXED = read(MIRROR / 'work/wave_v38/探索条件の固定.json')
    reference.FIXED = read(MIRROR / 'work/wave_v44/探索条件の固定.json')
    reference.INPUTS = inputs
    reference.old.INPUTS = inputs
    return rt['initialize'](inputs, signals)


def provenance() -> dict:
    """
    機能: 所有mirrorのsourceと元sourceの完全同bytes対応を返す。
    引数: なし。
    返り値: dictは数値式無変更の対応。実行時新規source追加を許す証明ではない。
    """
    mapping = {}
    for path in sorted((MIRROR / 'work').rglob('*.py')):
        relative = path.relative_to(MIRROR).as_posix()
        expected = digest(ROOT / relative)
        assert digest(path) == expected, relative
        mapping[relative] = dict(owned_path=path.relative_to(ROOT).as_posix(), SHA256=expected)
    return mapping


def discover() -> None:
    """
    機能: 数値源のimportだけを行い、動的依存の所有コピーと署名を作る。
    引数: なし。
    返り値: None。raw、CSVの意味内容、cache、旧金融を読み込まない。
    """
    with isolated(discover=True):
        rt = runtime()
        # 1分/5分足のsource接続も原本なしで行い、遅延importを先に固定する。
        rt['extractor'].replay.entry.set_root(MIRROR)
        reference = sys.modules['v6_source_reference']
        reference.previous.data.signals_module(allow_holdout=False)
    save(HERE / '旧源の所有コピー対応.json', dict(全合格=True, source_mapping=provenance(),
        imported_sources=sorted(p.relative_to(ROOT).as_posix() for p in DISCOVERED),
        元の包括初期化='旧26入力読取を呼ばず、小FIXED注入後に旧85initializeの最初の呼出し文だけを除いた同一ASTを実行。',
        原市場本文読取=0, 保存cache本文読取=0, 新金融=0, API=0))
    print('旧源の同bytes所有コピーとSOURCE import完了。入力本文/金融0。', flush=True)


if __name__ == '__main__':
    assert sys.argv[1:] == ['discover']
    discover()
