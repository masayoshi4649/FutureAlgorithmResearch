"""初版466人工を継承し、登録入力と固定入力を直結するguardだけを追加確認する。"""

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
BASE = ENGINE.parent
ROOT = BASE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 許可された小さな独立証跡だけを読み込む。
    引数: path(Path)は監査又は入力目録のJSON。
    返り値: dictは内容。市場cacheを開かない。
    """
    assert path.stat().st_size < 2 * 1024 * 1024
    return json.loads(path.read_bytes().decode('utf8'))


def sha(path: Path) -> str:
    """
    機能: 完成source又は小証跡の指紋を計算する。
    引数: path(Path)はSOURCE_ONLY範囲のファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, name: str) -> object:
    """
    機能: 完成通知済みの部品をmainなしで読み込む。
    引数: path(Path)はsource、name(str)は私有module名。
    返り値: objectは部品。正式照合・登録・金融は実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def other_ast(path: Path) -> str:
    """
    機能: guard以外の全定義が変更されていないことを比較可能にする。
    引数: path(Path)は新旧driverのsource。
    返り値: strはguard定義だけを除いたAST。
    """
    tree = ast.parse(path.read_text(encoding='utf8'))
    tree.body = [node for node in tree.body
                 if not (isinstance(node, ast.FunctionDef) and node.name == 'verify_run_contract')]
    return ast.dump(tree, include_attributes=False)


def main() -> None:
    """
    機能: 源の差分と少数の登録guard反例だけを初版人工へ接続する。
    引数: CLIの--run-sha(str)は完成通知指紋、--previous-run(Path)は保全旧driver。
    返り値: None。新市場・金融・試行台帳は読み込まない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-sha', required=True)
    parser.add_argument('--previous-run', type=Path, required=True)
    args = parser.parse_args()
    assert re.fullmatch('[0-9a-f]{64}', args.run_sha)
    assert sha(ENGINE / 'run_v4.py') == args.run_sha
    before_path = HERE / '保存元三方針の順逆と四十八政策及び既存kernelの独立接続.json'
    before = read(before_path)
    assert before['全合格'] is True and before['確認数'] == 466
    old_run_path = args.previous_run.resolve()
    run_key = (ENGINE / 'run_v4.py').relative_to(ROOT).as_posix()
    assert sha(old_run_path) == before['source_SHA256'][run_key]
    assert other_ast(old_run_path) == other_ast(ENGINE / 'run_v4.py'), 'guard以外のdriver変更は禁止'
    run = load(ENGINE / 'run_v4.py', '_独立119d登録guard')
    plan = load(ENGINE / 'plan_v4.py', '_独立119d登録計画')
    sources = plan.economic_sources()
    for name, expected in before['source_SHA256'].items():
        if name != run_key:
            assert sources[name] == expected, name
    checks = ['旧466人工の源拘束継承', 'guard以外の全AST不変', '再利用六源の同bytes']

    # ----------------------------------------
    # 固定sourceは実sourceの七指紋、登録JSONと入力本文だけは完全な人工へ差し替える。
    with tempfile.TemporaryDirectory(prefix='登録接続_', dir=HERE) as temporary:
        folder = Path(temporary)
        sessions = [f'2026-01-{i:02d}_{period}' for i in range(1, 21) for period in ('Day', 'Night')]
        meta = dict(sessions=sessions, inputs=[dict(session=s, symbol=symbol) for s in sessions for symbol in ('TOPIX', 'NK225')],
                    source_ids=list(run.SOURCE_IDS), source_specs=[dict(id=name) for name in run.SOURCE_IDS])
        payload = (json.dumps(meta, ensure_ascii=False) + '\n').encode('utf8')
        (folder / '入力目録.json').write_bytes(payload)
        manifest = dict(path=(folder / '入力目録.json').relative_to(ROOT).as_posix(), sha256=hashlib.sha256(payload).hexdigest())
        proposal = dict(id=plan.TRIAL, spec=dict(implementation=sources, data=dict(input_manifests=[manifest], sessions=sessions)))
        objects = {'固定計画.json': dict(sources=sources, input_manifest=manifest),
            '試行計画.json': proposal,
            '正式照合の全出力.json': dict(終了コード=0, stdout=json.dumps(dict(proposal_complete=True))),
            '正式登録の全出力.json': dict(終了コード=0, stdout=json.dumps(dict(id=proposal['id'], spec=proposal['spec']))),
            '入力目録.json': meta}
        original_here, original_read = run.HERE, run.run_v2.read
        state = {'objects': copy.deepcopy(objects)}

        def fake_read(path: Path) -> dict:
            """
            機能: 登録guardに合成JSONだけを渡して原台帳読取を防ぐ。
            引数: path(Path)はguardが要求した小JSON位置。
            返り値: dictは合成辞書の独立コピー。未知ファイルは拒否する。
            """
            assert path.name in state['objects'], path
            return copy.deepcopy(state['objects'][path.name])

        run.HERE, run.run_v2.read = folder, fake_read
        try:
            fixed, observed, returned = run.verify_run_contract()
            assert fixed == objects['固定計画.json'] and observed == meta and returned == proposal
            checks.append('登録済み三小JSONと固定入力の正例')
            variants = []
            bad = copy.deepcopy(objects)
            bad['試行計画.json']['spec']['data']['input_manifests'][0]['sha256'] = 'f' * 64
            bad['正式登録の全出力.json']['stdout'] = json.dumps(dict(id=proposal['id'], spec=bad['試行計画.json']['spec']))
            variants.append(('登録と固定の入力SHA不一致', bad))
            bad = copy.deepcopy(objects)
            bad['試行計画.json']['spec']['data']['sessions'] = sessions[::-1]
            bad['正式登録の全出力.json']['stdout'] = json.dumps(dict(id=proposal['id'], spec=bad['試行計画.json']['spec']))
            variants.append(('登録と入力の場順不一致', bad))
            bad = copy.deepcopy(objects)
            bad['入力目録.json']['sessions'][-1] = sessions[0]
            variants.append(('場一覧の重複', bad))
            bad = copy.deepcopy(objects)
            bad['入力目録.json']['inputs'][-1] = copy.deepcopy(bad['入力目録.json']['inputs'][0])
            variants.append(('80入力の重複', bad))
            bad = copy.deepcopy(objects)
            bad['入力目録.json']['inputs'][-1]['symbol'] = '未知商品'
            variants.append(('場商品直積の不一致', bad))
            bad = copy.deepcopy(objects)
            bad['正式照合の全出力.json']['stdout'] = json.dumps(dict(proposal_complete=False))
            variants.append(('終了0でも照合不完全', bad))
            bad = copy.deepcopy(objects)
            bad['正式登録の全出力.json']['stdout'] = json.dumps(dict(id='別試行', spec=proposal['spec']))
            variants.append(('登録ID不一致', bad))
            bad = copy.deepcopy(objects)
            bad['固定計画.json']['input_manifest']['sha256'] = 'f' * 64
            variants.append(('小目録実SHA不一致', bad))
            bad = copy.deepcopy(objects)
            bad['入力目録.json']['source_specs'][-1]['id'] = '別の事後候補'
            variants.append(('元候補IDの変更', bad))
            for label, values in variants:
                state['objects'] = values
                failed = False
                try:
                    run.verify_run_contract()
                except AssertionError:
                    failed = True
                assert failed, label
                checks.append(label)
        finally:
            run.HERE, run.run_v2.read = original_here, original_read

    # ----------------------------------------
    # 実小目録だけを一回参照し、元索引と80入力の計画を確認する。NPZ本文は開かない。
    actual = read(ENGINE / '入力目録.json')
    assert len(actual['sessions']) == len(set(actual['sessions'])) == 40
    pairs = [(r['session'], r['symbol']) for r in actual['inputs']]
    assert len(pairs) == len(set(pairs)) == 80
    assert set(pairs) == {(s, y) for s in actual['sessions'] for y in ('TOPIX', 'NK225')}
    assert tuple(actual['source_ids']) == run.SOURCE_IDS == plan.SOURCE_IDS
    assert len(set(actual['source_indexes'])) == 3 and all(type(i) is int and i >= 0 for i in actual['source_indexes'])
    assert tuple(s['id'] for s in actual['source_specs']) == run.SOURCE_IDS
    assert all(re.fullmatch('[0-9a-f]{64}', item['SHA256']) and type(item['bytes']) is int and item['bytes'] > 0 for item in actual['inputs'])
    checks.append('実小目録の40唯一場と80直積及び元三索引')
    assert plan.economic_sources() == sources
    proof = dict(全合格=True, source_SHA256=sources, 追加確認数=len(checks), 追加確認=checks,
        継承=dict(path=before_path.relative_to(ROOT).as_posix(), sha256=sha(before_path), 確認数=466),
        修正前source=dict(path=old_run_path.relative_to(ROOT).as_posix(), sha256=sha(old_run_path)),
        入力目録=dict(path=(ENGINE / '入力目録.json').relative_to(ROOT).as_posix(), sha256=sha(ENGINE / '入力目録.json')),
        経済源の差分='runの登録入力・場集合guardのみ。反転・時刻・kernel計算は不変。',
        scope='金融前SOURCE_ONLY＋少数の登録guard人工。実際の正式登録は根担当。',
        原市場読取=0, 保存cache本文読取=0, 金融結果本文読取=0,
        試行台帳本文読取=0, 金融再生=0, 正式登録=0, API=0)
    output = HERE / '登録入力直結と四十八政策の完成七源独立接続.json'
    assert not output.exists()
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')
    print(json.dumps(dict(全合格=True, 追加確認数=len(checks), 証跡=output.name, SHA256=sha(output)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
