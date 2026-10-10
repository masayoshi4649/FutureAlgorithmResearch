"""比較と独立集計だけを高速化し、旧監査と同じ全件検査を新規に実行する。"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import fast_comparison
import conditional_accounting_audit as original
import accounting_reconstruction_vectorized as reconstruction

HERE, ROOT = original.HERE, original.ROOT
read, save, digest = original.read, original.save, original.digest
PROBE = False
PROTOCOL_SHA = ''
ORIGINAL_SAVE = original.save


def install() -> None:
    """機能: この監査プロセス内の数値比較と独立再構成だけを差し替える。

    引数: なし。返り値: なし (None)。旧ソース・注文器・入力・判定式は変更しない。
    """
    fast_comparison.install()
    original.previous.reconstruct = reconstruction.reconstruct
    original.legacy.connection.baseline.previous.reconstruct = reconstruction.reconstruct


def baseline_path(identifier: str) -> Path:
    """機能: 保存した旧監査又は切替前の旧監査実体を参照する。

    引数: identifier (str)。返り値: 旧明細の候補パス (Path)。
    """
    archived = HERE / 'accounting_v1/accounting_details' / (identifier + '.json.gz')
    return archived if archived.exists() else HERE / 'accounting_details' / (identifier + '.json.gz')


def version_fields(identifier: str) -> dict:
    """機能: 全明細と一覧に監査版・固定指紋・旧実体同値の有無を加える。

    引数: identifier (str)。返り値: 版メタデータ (dict)。
    """
    path = baseline_path(identifier)
    old_exists = path.exists() and read(path).get('監査版') is None
    return dict(監査版=2, 監査固定SHA256=PROTOCOL_SHA, 旧版実体同値=True if old_exists else None)


def save_detail(path: Path, value: dict) -> None:
    """機能: 新版の監査明細を保存し、存在する旧版全実体と厳密同値を要求する。

    引数: path (Path)、value (dict)。返り値: なし (None)。旧版実体は上書きしない。
    """
    assert path.parent.name == 'accounting_details'
    prior = baseline_path(value['id'])
    metadata = version_fields(value['id'])
    if metadata['旧版実体同値']:
        assert value == read(prior), '旧監査の全明細と値が変わりました: ' + value['id']
    if PROBE:
        assert metadata['旧版実体同値'] is True
        path = HERE / 'performance_probe/accounting_details' / path.name
    ORIGINAL_SAVE(path, {**value, **metadata})


def initialize(destination: str = '', probe: bool = False) -> None:
    """機能: 元監査の入力初期化後にこのプロセスだけ高速比較へ接続する。

    引数: destination (str)、probe (bool)。返り値: なし (None)。
    """
    global PROBE, PROTOCOL_SHA
    original.initialize(destination)
    PROBE = probe
    PROTOCOL_SHA = digest(HERE / 'accounting_fixed_v2.json')
    original.save = save_detail
    install()


def evaluate(spec: dict) -> dict:
    """機能: 元監査の全検査を省かず呼び、版情報を全条件一覧にも結ぶ。

    引数: spec (dict)。返り値: 元監査値と監査版 (dict)。
    """
    result = original.evaluate(spec)
    return {**result, **version_fields(spec['id'])}


def freeze() -> dict:
    """機能: 旧監査と同じ対象・閾値を引き継ぎ、速度改訂だけの実装を固定する。

    引数: なし。返り値: 新版固定記録 (dict)。
    """
    old = original.freeze()
    files = [Path(__file__), HERE / 'fast_comparison.py', HERE / 'accounting_reconstruction_vectorized.py',
        HERE / 'comparison_equivalence.json', HERE / 'accounting_selftest_v2.json',
        HERE / 'reconstruction_vectorized_build.json', HERE / 'reconstruction_vectorized_audit.json',
        HERE / 'accounting_fixed.json']
    value = dict(old)
    value.update(固定日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 監査版=2,
        性能変更='NumPy testingの同じ数値比較を一巡で検算。独立会計の有限配列max/minをNumPy化。旧監査全関数を同じ経路で実行。',
        旧監査固定SHA256=digest(HERE / 'accounting_fixed.json'),
        参照SHA256={**old['参照SHA256'], **{p.relative_to(ROOT).as_posix(): digest(p) for p in files}},
        全件再実施=True, 監査対象変更=False, 検査閾値変更=False, 売買条件変更=False)
    path = HERE / 'accounting_fixed_v2.json'
    if path.exists():
        expected = read(path)
        assert {k: v for k, v in expected.items() if k != '固定日時'} == {k: v for k, v in value.items() if k != '固定日時'}
        return expected
    save(path, value)
    return value


def main() -> None:
    """機能: 新版合成・既通過15プローブ、又は全840/補助64をゼロから監査する。

    引数: --prepare/--probe/--supplementary (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true'); parser.add_argument('--probe', action='store_true')
    parser.add_argument('--supplementary', action='store_true'); parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    comparisons = fast_comparison.self_test()
    install()
    synthetic = original.self_test()
    assert synthetic == read(HERE / 'accounting_selftest.json'), '旧人工6条件の全値同一'
    save(HERE / 'comparison_equivalence.json', comparisons)
    save(HERE / 'accounting_selftest_v2.json', synthetic)
    protocol = freeze()
    if args.prepare:
        print('比較1260と旧人工6の同値を固定。元検査内容は同じ。', flush=True); return
    destination = 'supplementary' if args.supplementary else ''
    initialize(destination, args.probe)
    fixed = original.FIXED
    specs = fixed['conditions']
    if args.probe:
        specs = specs[:15]
        assert all(baseline_path(s['id']).exists() for s in specs)
    elif args.supplementary:
        mode = read(HERE / '選択固定.json')['選択']['selected_exit_mode_id']
        specs = read(HERE / 'supplementary_design_fixed.json')['全分岐'][mode]
        completed = read(HERE / '補助乱数診断.json')
        assert completed['条件IDs'] == [s['id'] for s in specs]
    assert read(HERE / '主再生の完了.json')['全条件数'] == 840
    before = {name: digest(ROOT / name) for name in fixed['SHA256']}
    assert before == fixed['SHA256']
    originals = original.legacy.original_hashes()
    assert originals == read(HERE / 'input_causality_before_pnl.json')['原本78SHA256']
    started = time.perf_counter(); output = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize, initargs=(destination, args.probe)) as pool:
        futures = {pool.submit(evaluate, spec): spec['id'] for spec in specs}
        for future in as_completed(futures):
            output.append(future.result())
            print(f'v2 {len(output)}/{len(specs)} {futures[future]} 全検査一致', flush=True)
    assert len(output) == len({r['id'] for r in output}) == len(specs)
    assert {r['id'] for r in output} == {s['id'] for s in specs}
    raw = sum(len(r['last']) for r in original.INPUTS.values())
    assert sum(r['原本行会計数'] for r in output) == raw * len(specs)
    assert before == {name: digest(ROOT / name) for name in before}
    assert originals == original.legacy.original_hashes() and freeze() == protocol
    if args.probe:
        assert all(r['旧版実体同値'] is True for r in output)
        files = [HERE / 'performance_probe/accounting_details' / (s['id'] + '.json.gz') for s in specs]
        old_files = [baseline_path(s['id']) for s in specs]
        value = dict(全値同一=True, 条件数=len(specs), 入力数=len(specs) * 26,
            対象ID=[s['id'] for s in specs], 新版SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in files},
            旧版SHA256={p.relative_to(ROOT).as_posix(): digest(p) for p in old_files},
            監査固定SHA256=digest(HERE / 'accounting_fixed_v2.json'), 経過秒=time.perf_counter() - started)
        save(HERE / 'performance_probe_equivalence.json', value)
        print({'既15全値同一': True, '経過秒': value['経過秒']}, flush=True); return
    count = len(specs) * len(original.INPUTS)
    result = dict(全監査合格=True, 対象条件数=len(specs), 全入力数=count, 一条件原本行数=raw,
        全原本行会計数=raw * len(specs), prefix検査数=count, 未来価格ATR入口悪化根拠改変数=count, 買売反射数=count,
        全保存数値一致=True, 全台帳配列一致=True, 全時価曲線SHA一致=True, ATR全保有行検算=True,
        短縮線独立検算=True, 返却独立検算=True, 影会計一致=True, 準備接続検査=True,
        全新規一致=True, 全退出影以前=True, 全段階接続一致=True,
        固定A0旧版同値条件数=sum(r['固定A0旧版同値'] for r in output),
        監査規則=protocol, 合成検査=synthetic, 条件=sorted(output, key=lambda r: r['id']),
        詳細=(destination + '/' if destination else '') + 'accounting_details/{id}.json.gz',
        参照SHA256=before, 原本78SHA256=originals, 探索固定SHA256=digest(HERE / '探索条件の固定.json'),
        API取得数=0, 現在保存物使用=False, 成績による対象選別=False, 規則変更=False,
        補助診断=args.supplementary, 監査版=2, 監査固定SHA256=digest(HERE / 'accounting_fixed_v2.json'),
        旧版実体同値条件数=sum(r['旧版実体同値'] is True for r in output), 実行秒=time.perf_counter() - started)
    save(HERE / destination / 'accounting_audit.json', result)
    (HERE / destination / 'accounting_audit.md').write_text(
        f'# 条件付き追跡の全件独立監査\n\n全{len(specs)}条件×26入力を新版で再検査。全注文会計・影と同じ全新規・影以前の全退出・原本行ごとの保護線・全三段階保存値が一致した。'
        '全件で37%切断・73%未来値改変・売買反射を実施した。比較式・対象・閾値は旧監査と同じで、速度改訂の証跡を別保存している。'
        '\n\n原本78と売買実装は前後不変、APIと保存ライブを使っていない。未知期間の利益を保証するものではない。\n', encoding='utf-8')
    print({k: result[k] for k in ('全監査合格', '対象条件数', '全入力数', '全原本行会計数', '実行秒')}, flush=True)


if __name__ == '__main__':
    main()
