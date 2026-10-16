"""凍結した全件監査の条件ループだけを別プロセスへ配分する。"""

import argparse
import ast
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
AUDIT = WORK / 'audit'
FULL_PATH = AUDIT / 'full.py'
EVIDENCE_NAME = '並列実行_全53条件全31場の価格入口と別執行源及び全原板会計と安定性の独立検算.json'
PROOF_NAME = '凍結監査の全手順同一と実行並列化及び依存名補足.json'
sys.dont_write_bytecode = True
sys.path.insert(0, str(AUDIT))
import full
import common
import price_checks
import state_checks

# ----------------------------------------

# 読取モジュールの初期化後に保存先を新しい実行領域へ限定する。
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
# 元mainの末尾指紋収集にだけ不足している既存モジュール名を接続する。
full.state_checks = state_checks


def now() -> str:
    """
    機能: 並列実行の記録用UTC時計を取得する。
    引数: なし。
    返り値: strのISO形式時計。
    """
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    """
    機能: 新監査領域だけへ有限JSONを途中書込みなしで保存する。
    引数: path(Path)、value(dict)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.途中')
    temporary.write_text(json.dumps(common.clean(value), ensure_ascii=False,
                                     indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def ast_sha(nodes: list) -> str:
    """
    機能: 元mainからそのまま取り出した構文木の内容指紋を計算する。
    引数: nodes(list[ast.stmt])。
    返り値: strのSHA256。
    """
    value = ast.dump(ast.Module(body=nodes, type_ignores=[]), include_attributes=False)
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def parts() -> tuple:
    """
    機能: 凍結mainを前提・条件ループ・最終照合・保存内容へ無変更分割する。
    引数: なし。
    返り値: tupleの元構文木・実行コード・保存値式・同一性情報。
    """
    tree = ast.parse(FULL_PATH.read_text(encoding='utf-8'), filename=str(FULL_PATH))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    indexes = [index for index, node in enumerate(main.body)
               if isinstance(node, ast.For) and isinstance(node.target, ast.Name)
               and node.target.id == 'config' and isinstance(node.iter, ast.Name)
               and node.iter.id == 'conditions']
    assert len(indexes) == 1
    index = indexes[0]
    before, loop, after = main.body[:index], main.body[index:index + 1], main.body[index + 1:-1]
    saving = main.body[-1]
    assert isinstance(saving, ast.Expr) and isinstance(saving.value, ast.Call)
    assert isinstance(saving.value.func, ast.Attribute) and saving.value.func.attr == 'save'
    assert isinstance(saving.value.func.value, ast.Name) and saving.value.func.value.id == 'common'
    assert len(saving.value.args) == 2 and not saving.value.keywords
    rebuilt = before + loop + after + [saving]
    assert ast_sha(main.body) == ast_sha(rebuilt)
    before_code = compile(ast.Module(body=before, type_ignores=[]), str(FULL_PATH), 'exec')
    loop_code = compile(ast.Module(body=loop, type_ignores=[]), str(FULL_PATH), 'exec')
    after_code = compile(ast.Module(body=after, type_ignores=[]), str(FULL_PATH), 'exec')
    save_value = compile(ast.Expression(body=saving.value.args[1]), str(FULL_PATH), 'eval')
    description = dict(元main全体構文木SHA256=ast_sha(main.body),
                       分割再結合構文木SHA256=ast_sha(rebuilt),
                       前提構文木SHA256=ast_sha(before),
                       条件ループ構文木SHA256=ast_sha(loop),
                       後段照合構文木SHA256=ast_sha(after),
                       元保存呼出構文木SHA256=ast_sha([saving]),
                       元main文数=len(main.body), 再結合文数=len(rebuilt),
                       保存内容='元common.saveの第2引数式をそのまま評価し別領域へ保存')
    return before_code, loop_code, after_code, save_value, description


def verify_frozen(manifest: dict) -> None:
    """
    機能: 凍結181依存と全監査部品及びドライバの開始指紋を再検査する。
    引数: manifest(dict)。
    返り値: None。
    """
    for relative, digest in manifest['読取監査SHA256'].items():
        assert common.sha(common.ROOT / relative) == digest, relative
    assert common.sha(WORK / '事前固定.json') == manifest['事前固定SHA256']
    assert common.sha(Path(__file__)) == manifest['ドライバSHA256']
    fixed = full.read(WORK / '事前固定.json')
    assert len(fixed['SHA256']) == manifest['固定依存数'] == 181
    for relative, digest in fixed['SHA256'].items():
        assert common.sha(common.ROOT / relative) == digest, relative


def worker(index: int, assigned: list, manifest: dict) -> dict:
    """
    機能: 元mainの前提を満たし、割当条件の元ループを実行して全検算結果を保存する。
    引数: index(int)、assigned(list[dict])、manifest(dict)。
    返り値: dictの担当条件と完了時計。元検算関数は同一モジュールを直接呼ぶ。
    """
    verify_frozen(manifest)
    before, loop, _, _, description = parts()
    assert description == manifest['構文木同一性']
    scope = full.__dict__
    exec(before, scope)
    assert scope['conditions'] == manifest['全53条件']
    worker_start = now()
    completed = []
    for config in assigned:
        condition_start = now()
        # 条件間で共有されるものは加算件数と辞書のみ。条件結果を個別保存する。
        scope['conditions'] = [config]
        scope['counters'], scope['fingerprints'], scope['all_totals'] = {}, {}, {}
        exec(loop, scope)
        assert set(scope['all_totals']) == {config['id']}
        checkpoint = dict(全合格=True, 条件=config, worker=index,
                          開始UTC=condition_start, 完了UTC=now(),
                          事前固定SHA256=manifest['事前固定SHA256'],
                          凍結fullSHA256=manifest['凍結fullSHA256'],
                          条件ループ構文木SHA256=description['条件ループ構文木SHA256'],
                          検査件数=scope['counters'],
                          全31独立会計=scope['all_totals'], SHA256=scope['fingerprints'])
        write_json(HERE / 'checkpoints' / (config['id'] + '.json'), checkpoint)
        completed.append(config['id'])
        write_json(HERE / 'workers' / f'{index}.json',
                   dict(worker=index, 開始UTC=worker_start, 完了条件=completed,
                        対象条件=[item['id'] for item in assigned], 更新UTC=now(), 全完了=False))
    verify_frozen(manifest)
    summary = dict(worker=index, 開始UTC=worker_start, 完了条件=completed,
                   対象条件=[item['id'] for item in assigned], 完了UTC=now(), 全完了=True)
    write_json(HERE / 'workers' / f'{index}.json', summary)
    return summary


def build_manifest(workers: int) -> dict:
    """
    機能: 実行前に凍結コード・固定条件・全分割手順を別領域へ記録する。
    引数: workers(int)。
    返り値: dictの実行前指紋と全53条件。
    """
    fixed = full.read(WORK / '事前固定.json')
    _, _, _, _, description = parts()
    files = sorted(AUDIT.glob('*.py'))
    manifest = dict(開始UTC=now(), worker数=workers,
                    凍結fullSHA256=common.sha(FULL_PATH),
                    事前固定SHA256=common.sha(WORK / '事前固定.json'),
                    固定依存数=len(fixed['SHA256']),
                    読取監査SHA256=common.fingerprint(files),
                    ドライバSHA256=common.sha(Path(__file__)),
                    構文木同一性=description, 全53条件=fixed['条件'],
                    実行差='元mainの条件ループのプロセス配分及び順序、個別結果の加算集約、証跡保存先のみ',
                    不足依存名補足=dict(障害='元main末尾のPath(state_checks.__file__)にimportがなく未定義名になる',
                                        補足='凍結audit/state_checks.pyを通常importしfull.state_checksへ接続',
                                        作用='末尾指紋収集のモジュール名だけを補完。検算式・閾値・条件・関数は変更しない'),
                    実行環境=dict(Python=sys.version, 引数=sys.argv,
                                  NUMBA_CACHE_DIR=os.environ['NUMBA_CACHE_DIR'],
                                  バイトコード保存=False), 現在API取得=0, 実注文=0)
    assert manifest['固定依存数'] == 181
    assert manifest['事前固定SHA256'] == '94969a99b2e7373cb2c34a8f8c7cc23ea234ce26d1b32904e175f1e440efbc6b'
    assert len(manifest['全53条件']) == 53
    verify_frozen(manifest)
    write_json(HERE / '実行前凍結と全手順.json', manifest)
    return manifest


def assemble(manifest: dict, summaries: list, start_time: float) -> None:
    """
    機能: 全53条件を元順序で集め、元mainの後段・分析比較・件数検査と保存式を実行する。
    引数: manifest(dict)、summaries(list[dict])、start_time(float)。
    返り値: None。合格証跡と同一手順証明を別名保存する。
    """
    verify_frozen(manifest)
    before, _, after, saving, description = parts()
    scope = full.__dict__
    exec(before, scope)
    conditions = manifest['全53条件']
    expected_ids = {config['id'] for config in conditions}
    completed_ids = [ident for summary in summaries for ident in summary['完了条件']]
    assert len(completed_ids) == 53 and set(completed_ids) == expected_ids
    assert {path.stem for path in (HERE / 'checkpoints').glob('*.json')} == expected_ids
    checkpoint_hashes = {}
    for config in conditions:
        path = HERE / 'checkpoints' / (config['id'] + '.json')
        value = full.read(path)
        assert value['全合格'] and value['条件'] == config
        assert value['事前固定SHA256'] == manifest['事前固定SHA256']
        assert value['凍結fullSHA256'] == manifest['凍結fullSHA256']
        assert value['条件ループ構文木SHA256'] == description['条件ループ構文木SHA256']
        assert set(value['全31独立会計']) == {config['id']}
        for name, count in value['検査件数'].items():
            scope['counters'][name] = scope['counters'].get(name, 0) + count
        for relative, digest in value['SHA256'].items():
            assert common.sha(common.ROOT / relative) == digest, relative
        scope['fingerprints'].update(value['SHA256'])
        scope['all_totals'].update(value['全31独立会計'])
        checkpoint_hashes[str(path.relative_to(common.ROOT))] = common.sha(path)
    # 元の後段を完全実行する。root analysisの全rows・全8期間・安定性もここで比較する。
    exec(after, scope)
    evidence = eval(saving, scope)
    assert evidence['全合格'] and evidence['全期間既知']
    assert evidence['検査件数']['口座'] == 3286
    assert evidence['検査件数']['商品期間集計'] == 848
    verify_frozen(manifest)
    write_json(HERE / EVIDENCE_NAME, evidence)
    proof = dict(全合格=True, 全53条件省略なし=True, 元main前後前提及び後段省略なし=True,
                 凍結検算関数変更=0, 凍結監査ファイル変更=0, 固定181依存変更=0,
                 新損益による監査条件選別=0, 現在API取得=0, 実注文=0,
                 開始UTC=manifest['開始UTC'], 完了UTC=now(), 所要秒=time.monotonic() - start_time,
                 worker数=manifest['worker数'], worker完了=summaries,
                 凍結fullSHA256=manifest['凍結fullSHA256'],
                 事前固定SHA256=manifest['事前固定SHA256'],
                 読取監査SHA256=manifest['読取監査SHA256'],
                 構文木同一性=manifest['構文木同一性'],
                 実行差=manifest['実行差'], 不足依存名補足=manifest['不足依存名補足'],
                 全53チェックポイントSHA256=checkpoint_hashes,
                 証跡SHA256=common.fingerprint([HERE / EVIDENCE_NAME, Path(__file__),
                                             HERE / '実行前凍結と全手順.json']),
                 検査件数=evidence['検査件数'],
                 検算範囲='全53条件・全31既知場・3286口座・全原板清算・源別時価指紋・22列価格源・最初予約約定取消・状態・全親最初返済・8期間848商品集計・安定性・root analysis全値比較')
    write_json(HERE / PROOF_NAME, proof)
    print('全53条件の凍結監査同一手順による並列検算・3286口座・848商品期間合格証跡を別領域へ保存', flush=True)


def main() -> None:
    """
    機能: 元の全件監査を止めず、条件の実行配分だけを並列化して独立証跡を完成する。
    引数: なし。コマンドラインworker数(int)を読む。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description='凍結監査の実行並列化')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    assert 1 <= args.workers <= 3
    assert not (HERE / '実行前凍結と全手順.json').exists(), '既往実行を上書きしない'
    started = time.monotonic()
    manifest = build_manifest(args.workers)
    assigned = [manifest['全53条件'][index::args.workers] for index in range(args.workers)]
    summaries = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(worker, index, values, manifest) for index, values in enumerate(assigned)]
        for future in as_completed(futures):
            summaries.append(future.result())
    assemble(manifest, sorted(summaries, key=lambda value: value['worker']), started)


if __name__ == '__main__':
    main()
