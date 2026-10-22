"""市場前の旧源同bytes・初期化一文差・公開map・所有JITを独立に確認する。"""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
V6 = HERE.parent
ROOT = V6.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(V6))
import adapter_v6 as adapter
import legacy_runtime as legacy
import plan_v6 as plan
import source_v6 as source

CHECKS = 0


def check(value: bool, label: str) -> None:
    """
    機能: SOURCEと人工の一致を数え、不一致なら停止する。
    引数: value(bool) は判定、label(str) は説明。
    返り値: None。
    """
    global CHECKS
    assert bool(value), label
    CHECKS += 1


def digest(path: Path) -> str:
    """
    機能: Python又は人工metadataの同bytes指紋を返す。
    引数: path(Path) はsource又は人工証跡。
    返り値: str はSHA256。元市場と金融cacheには用いない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(owner_proof: Path) -> None:
    """
    機能: owner完成境界を受け、旧数値と所有接続のSOURCE確認だけを行う。
    引数: owner_proof(Path) は完成後に指定された人工証跡。
    返り値: None。原板・CSV・実入力・旧金融結果は読まない。
    """
    owner_proof = owner_proof.resolve()
    assert owner_proof.is_relative_to(V6)
    proof_bytes = owner_proof.read_bytes()
    proof = json.loads(proof_bytes.decode('utf-8'))
    before = plan.sources()
    check(proof['全合格'] is True and proof['source_SHA256'] == before, 'owner完成source全束へ接続')
    mirror = json.loads((V6 / '旧源の所有コピー対応.json').read_text(encoding='utf-8'))
    check(mirror['全合格'] is True, '旧源mirror完成metadata')
    for relative, item in mirror['source_mapping'].items():
        old, new = ROOT / relative, ROOT / item['owned_path']
        check(old.suffix == new.suffix == '.py' and new.resolve().is_relative_to(source.MIRROR), '同bytes対象は所有Pythonだけ')
        a, b = old.read_bytes(), new.read_bytes()
        check(a == b and hashlib.sha256(a).hexdigest() == item['SHA256'], '旧源とmirror同bytes')
    for name in source.ENGINE_NAMES:
        old = (ROOT / 'work/e01_adaptive_price_20261014/engine' / name).read_bytes()
        if name == 'common.py':
            check(old.count(b'ROOT=HERE.parents[2]') == 1, 'commonのrepo位置変更は一箇所')
            old = old.replace(b'ROOT=HERE.parents[2]', b'ROOT=HERE.parents[3]')
        check((V6 / 'engine' / name).read_bytes() == old, '旧106数値源は位置以外不変:' + name)
    check(adapter.ACTUAL == {'TOPIX': 'E01_ADAPT_G50_ADAPT75_P1', 'NK225': 'E01_ADAPT_G25_ADAPT100_P1'}, '旧二設定だけを固定')
    original_config = None
    with legacy.isolated(discover=False):
        legacy.SOURCE_READ_ACTIVE = True
        original_config = legacy.numba.config.original
        rt = legacy.runtime()
        modules = adapter.engine_modules()
        selected = adapter.selected_configs(modules)
        check({symbol: value['id'] for symbol, value in selected.items()} == adapter.ACTUAL, '実数値catalogと旧二設定接続')
        check(rt['correct_arrays'].__globals__['CHANGED'] == ('volume_delta_usable', 'volume_delta'), '旧補正ASTの必要定数も注入')
        old_tree = ast.parse((source.MIRROR / 'work/wave_v85/strategy.py').read_text(encoding='utf-8-sig'))
        initialize = next(node for node in old_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'initialize')
        check(ast.unparse(initialize.body[1]) == 'base.integration.reference.initialize()', '除去する一文は旧26包括読取だけ')
        initialize.body.pop(1)
        namespace = {}
        filename = str(source.MIRROR / 'work/wave_v85/strategy.py')
        exec(compile(ast.fix_missing_locations(ast.Module(body=[initialize], type_ignores=[])), filename, 'exec'), namespace)
        actual, expected = rt['initialize'].__code__, namespace['initialize'].__code__
        check(actual.co_code == expected.co_code and actual.co_names == expected.co_names, '旧initialize後半のbytecode不変')
        for constant in (v for v in actual.co_consts if isinstance(v, str)):
            check(constant in expected.co_consts, '旧initializeの定数不変')
        legacy.numba.config.CACHE_DIR = '旧JITへの不正な保存先要求'
        check(legacy.numba.config.CACHE_DIR == original_config.CACHE_DIR == legacy.CACHE, '旧sourceのJIT保存先要求は所有先へ固定')
        check(Path(legacy.CACHE).resolve().is_relative_to(V6), 'legacyJITは新所有域')
        for value in tuple(sys.modules.values()):
            raw = getattr(value, '__file__', None)
            if raw is None:
                continue
            path = Path(raw).resolve()
            if path.is_relative_to(ROOT / 'work'):
                check(path.is_relative_to(V6), '実importしたrepo Pythonは新所有域だけ')
        for path in (ROOT / 'book/TOPIX/人工.jsonl', source.MIRROR / 'book/TOPIX/人工.jsonl',
                     source.MIRROR / 'candle_1min/TOPIX/人工.csv', source.MIRROR / 'work/wave_v23/inputs.pkl'):
            rejected = False
            try:
                path.read_bytes()
            except AssertionError:
                rejected = True
            check(rejected, 'SOURCE境界は原板/足/cache本文をopen前に拒否')
    check(legacy.SOURCE_READ_ACTIVE is False, 'SOURCE範囲の終了を復元')
    tape = dict(seq=np.asarray([0, 2, 4], np.int64), time_s=np.asarray([1., 2., 3.]), last=np.asarray([100., 101., 102.]),
                bid=np.asarray([99., 100., 101.]), ask=np.asarray([100., 101., 102.]))
    ready = dict(seq=np.asarray([2, 4], np.int64), time_s=np.asarray([2., 3.]), last=np.asarray([101., 102.]))
    mapped = adapter.quote_mapping(ready, tape)
    check(np.array_equal(mapped['bid'], [100., 101.]) and mapped['quote_valid'].all(), '正常mapは同seq/time/Lastのみ')
    altered = {key: value.copy() for key, value in ready.items()}
    altered['last'][0] += .5
    rejected = False
    try:
        adapter.quote_mapping(altered, tape)
    except AssertionError:
        rejected = True
    check(rejected, 'Last不一致を未来近傍行へ救済しない')
    bad = {key: value.copy() for key, value in tape.items()}
    bad['ask'][1] = bad['bid'][1]
    check(not adapter.quote_mapping(ready, bad)['quote_valid'][0], '同seqでも交差気配は約定無資格')
    check(plan.sources() == before, '独立SOURCE人工の前後で全経済源不変')
    output = dict(全合格=True, 検査数=CHECKS, source_SHA256=before,
        owner_proof=dict(path=owner_proof.relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(proof_bytes).hexdigest()),
        監査源SHA256=digest(Path(__file__)), 元市場読取=0, CSV読取=0, 旧入力cache読取=0, 金融結果読取=0, 金融再実行=0,
        old_math='旧mirror同bytes、実12源common位置だけ差、旧初期化包括読取一文だけ除去し後半bytecode保持。',
        時刻='旧48/85源の遅延公開・seq順とFAKはコピー不変。真受信時計や実小型板の物理約定は未証明。',
        留保='SOURCEと小人工の接続監査。旧33の再運転及び新しい有効性標本ではない。')
    target = HERE / '旧源同bytesと初期化差分及び公開mapと所有JITの独立監査.json'
    assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=CHECKS), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner-proof', required=True, type=Path)
    args = parser.parse_args()
    try:
        main(args.owner_proof)
    except BaseException as exc:
        path = HERE / 'source_False.json'
        assert not path.exists()
        path.write_text(json.dumps(dict(全合格=False, 検査数=CHECKS, 型=type(exc).__name__, 例外=str(exc)),
                                   ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
