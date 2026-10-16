"""31場の選定と検証が完了した後、条件不変の20手法を追加一場へ適用する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
from pathlib import Path
import socket

import research


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SESSION = '2026-10-12_Night'
OUT = HERE / 'holdout_results'


def module(path: Path) -> object:
    """
    機能: 追加一場だけの入力読取を専用名で読み込む。
    引数: path (Path)。新しい入力loader。
    返り値: object。読取モジュール。
    """
    spec = importlib.util.spec_from_file_location('追加ナイト入力102', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run_one(config: dict, prepared: dict) -> str:
    """
    機能: 不変の一条件で追加ナイト両商品を再生し、全玉と全費用を保存する。
    引数: config (dict) は既に固定した条件、prepared (dict) は一場の入力。
    返り値: str。完了した条件ID。
    """
    target = OUT / 'results' / (config['id'] + '.json')
    assert not target.exists()
    rows, ledgers = [], {}
    for key in sorted(prepared):
        output = research.strategy.play(config, key, prepared)
        rows.append(research.accounting.account(key, output))
        ledgers[key] = research.ledger(output, prepared[key])
    assert len(rows) == 2 and set(ledgers) == {(SESSION, s) for s in research.catalog.SYMBOLS}
    path = OUT / 'ledgers' / (config['id'] + '.pkl')
    research.save(path, ledgers)
    research.save(target, dict(config=config, rows=rows,
        periods={'追加ナイト1': {s: research.accounting.aggregate(rows, s, [SESSION])
                               for s in research.catalog.SYMBOLS}},
        stability=research.stability(rows, config, prepared, [SESSION]),
        ledger_SHA256=research.data.digest(path)))
    return config['id']


def main() -> None:
    """
    機能: 既知31場確定を確認し、追加一場を別台帳と事前指紋付きで再生する。
    引数: CLI --root-all31-complete (bool)、--workers (int)。
    返り値: None。参考選定、条件、元31場の会計を変更しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-all31-complete', action='store_true')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    assert args.root_all31_complete
    socket.create_connection = research.deny
    socket.socket.connect = research.deny
    fixed = research.read(HERE / '事前固定.json')
    research.validate(fixed)
    selected = research.read(HERE / '前16参考代表.json')
    analysis = research.read(HERE / 'analysis/比較結果.json')
    assert analysis['全合格'] and analysis['primary'] == fixed['主']
    assert analysis['selected'] == selected['selected']
    assert selected['後15正式損益前選定'] and fixed['固定対象外の新追加場'] == SESSION
    for part, sessions in (('front', fixed['前16']), ('back', fixed['後15'])):
        for config in fixed['条件']:
            result = research.read(HERE / part / 'results' / (config['id'] + '.json'))
            assert result['config'] == config and len(result['rows']) == len(sessions) * 2
    plan_path = OUT / '追加再生前固定.json'
    assert not plan_path.exists() and not list((OUT / 'results').glob('*.json'))
    loader = module(HERE / 'holdout_input/data.py')
    material = loader.load_inputs()
    compatibility = HERE / 'holdout_input/現102のprepareと旧Day欄及び未来不変の入力互換.json'
    assert compatibility.exists()
    compatibility_proof = research.read(compatibility)
    assert compatibility_proof['全合格']
    compatibility_paths = []
    for group in ('旧入力cacheSHA256', '互換確認コードSHA256', '完成追加入力SHA256'):
        assert compatibility_proof[group]
        for name, expected in compatibility_proof[group].items():
            assert research.data.digest(ROOT / name) == expected, name
            compatibility_paths.append(ROOT / name)
    paths = [Path(__file__), HERE / '事前固定.json', HERE / '前16参考代表.json',
             HERE / 'analysis/比較結果.json', compatibility,
             HERE / 'audit/追加一場の40口座を独立確認する.py',
             *compatibility_paths, *material['paths']]
    assert all(path.exists() for path in paths)
    fingerprints = {str(path.relative_to(ROOT)): research.data.digest(path) for path in paths}
    research.save(plan_path, dict(全合格=True, 条件=fixed['条件'], 主=fixed['主'],
        前16参考=selected['selected'], 対象=[SESSION], 正式追加損益実行=0,
        追加損益による条件又は参考変更=0, 元31結果確定後=True,
        位置付け='本調査で未評価だった追加一場を同じ条件で確認。全20を比べた後の選び直しはしない。',
        SHA256=fingerprints, API取得=0, 実注文=0))
    prepared = research.strategy.prepare(material, fixed['条件'][0])
    assert set(prepared) == {(SESSION, s) for s in research.catalog.SYMBOLS}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_one, config, prepared) for config in fixed['条件']]
        for future in as_completed(futures):
            print(future.result() + ' 追加ナイト完了', flush=True)
    assert len(list((OUT / 'results').glob('*.json'))) == 20
    assert fingerprints == {str(path.relative_to(ROOT)): research.data.digest(path) for path in paths}
    research.save(OUT / '正式追加再生の終端.json', dict(全合格=True, 条件数=20, 口座数=40,
        対象=SESSION, 条件変更=0, 参考変更=0, 開始終端指紋一致=True,
        開始SHA256=fingerprints, SHA256=fingerprints, API取得=0, 実注文=0))


if __name__ == '__main__':
    main()
