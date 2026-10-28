"""全現行ルールを不変の旧Go・保存期待値と比較し、実行版を固定する。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
APP = ROOT/'App/SessionTrader'
FIXTURE = ROOT/'work/sessiontrader143_port_20261025/fixtures_all'


def digest(path):
    """ファイルの内容指紋を計算する。

    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    """日本語を維持したJSONを保存する。

    引数: path(Path)、value(dict又はlist)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def prepare_baseline():
    """不変ZIPから旧Goと同一検査driverだけを独立領域へ配置する。

    引数: なし。返り値: Pathは旧アプリルート。金融再生は行わない。
    """
    target = HERE/'baseline_repo'
    app = target/'App/SessionTrader'
    if app.exists():
        raise RuntimeError('旧版領域は既にあります。比較元を上書きしません')
    target.mkdir()
    with zipfile.ZipFile(HERE/'変更前全内部Go.zip') as archive:
        for name in archive.namelist():
            if not name.startswith('App/SessionTrader/'):
                continue
            path = (target/name).resolve()
            assert path.is_relative_to(target.resolve())
            archive.extract(name, target)
    fixture = app/'internal/strategy/testdata/selected_orders.json.gz'
    fixture.parent.mkdir(exist_ok=True)
    shutil.copyfile(APP/'internal/strategy/testdata/selected_orders.json.gz', fixture)
    shutil.copyfile(APP/'internal/strategy/all_rules_fixture_test.go', app/'internal/strategy/all_rules_fixture_test.go')
    (app/'internal/strategy/all_rules_bridge_test.go').write_text('''package strategy
import "testing"
// allRulesExternalExpressions は変更前の内部条件をそのまま使います。
//
// 引数: t(*testing.T)、symbol/kind/method(string)。返り値: nilは旧Goの標準条件です。
func allRulesExternalExpressions(t *testing.T, symbol, kind, method string) map[string]string { return nil }
''', encoding='utf8')
    return app


def execute(app, folder, pattern, external, note):
    """コード・条件・依存を先に固定して、指定した同値検査を実行する。

    引数: app/folder(Path)、pattern/note(str)、external(bool)。返り値: dictは実行結果。
    """
    folder.mkdir()
    files = sorted((app/'internal').rglob('*.go')) + [app/'go.mod', app/'go.sum', Path(__file__)]
    if external:
        files += sorted((APP/'conf/rules').glob('*.toml'))
    fingerprints = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    archive = folder/'実行時実装.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in files:
            z.write(path, path.relative_to(ROOT).as_posix())
    env = dict(os.environ, SESSIONTRADER_FIXTURE143=str(FIXTURE),
        SESSIONTRADER_ALL_RULES_RECEIPT=str(HERE/'登録受領.json'),
        SESSIONTRADER_ALL_RULES_REPORT=str(folder/'旧4手法の全約定.json'))
    for name in ('SESSIONTRADER_D07_SCENE', 'SESSIONTRADER_D07_RULES', 'SESSIONTRADER_ALL_RULES_DIRECTORY'):
        env.pop(name, None)
    if external:
        env.update(SESSIONTRADER_ALL_RULES_DIRECTORY=str(APP/'conf/rules'),
            SESSIONTRADER_D07_ALL='1', SESSIONTRADER_D07_FIXTURE=str(ROOT/'work/d07_port/fixtures'),
            SESSIONTRADER_D07_REPORT=str(folder/'D07全約定.json'),
            SESSIONTRADER_NATIVE143_REPORT=str(folder/'TG04_PG04照合.json'))
    command = ['go', 'test', './internal/strategy', '-run', pattern, '-count=1', '-json']
    receipt = json.loads((HERE/'登録受領.json').read_text(encoding='utf8'))
    save(folder/'実行条件.json', {'trial_id': receipt['trial_id'], 'command': command,
        'implementation': fingerprints, 'archive_sha256': digest(archive), 'external': external, 'note': note,
        'legacy_protocol': '両市場50場ずつ。基本5/補完5/上限10、TOPIXmini41.8円・NK225mini38.5円片道切捨て。補完時刻は現行schedule標準。旧Goと新Goで同じdriver・当時入力・次正常気配を使用。',
        'scope': '独立同値確認。収益性の新しい証拠へ数えない。'})
    print(folder.name+'開始', flush=True)
    with (folder/'go結果.jsonl').open('wb') as out, (folder/'go標準エラー.txt').open('wb') as err:
        result = subprocess.run(command, cwd=app, env=env, stdout=out, stderr=err)
    changed = [name for name, expected in fingerprints.items() if not (ROOT/name).exists() or digest(ROOT/name) != expected]
    summary = {'returncode': result.returncode, '実行中変更ファイル': changed, 'go結果_sha256': digest(folder/'go結果.jsonl')}
    save(folder/'実行要約.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if result.returncode or changed:
        raise SystemExit(1)
    return summary


def main():
    """登録完了後だけ旧基準作成又は全7プロファイル照合を実行する。

    引数: mode(str)はbaseline又はcurrent。返り値: None。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('baseline', 'current'))
    parser.add_argument('--note', default='登録済み計画の全7プロファイル外部化同値照合。')
    args = parser.parse_args()
    receipt = json.loads((HERE/'登録受領.json').read_text(encoding='utf8'))
    assert receipt['returncode'] == 0
    assert digest(HERE/'変更前全内部Go.zip') == receipt['baseline_archive_sha256']
    inventory = json.loads((HERE/'変更前と入力の指紋.json').read_text(encoding='utf8'))
    assert all(digest(ROOT/name) == value for name, value in inventory.items()), '基準又は入力資料の変更'
    if args.mode == 'baseline':
        app = prepare_baseline()
        execute(app, HERE/'baseline_run', '^Test(AllRulesLegacyInputs|SelectedSavedOrders)$', False, args.note)
        rows = json.loads((HERE/'baseline_run/旧4手法の全約定.json').read_text(encoding='utf8'))
        assert len(rows) == 100, '旧4手法の場数不足'
        save(HERE/'baseline_run/固定結果.json', {'cases': len(rows), 'orders': sum(len(r['Orders']) for r in rows), 'report_sha256': digest(HERE/'baseline_run/旧4手法の全約定.json')})
        return
    fixed = json.loads((HERE/'baseline_run/固定結果.json').read_text(encoding='utf8'))
    assert digest(HERE/'baseline_run/旧4手法の全約定.json') == fixed['report_sha256']
    n = 1
    while (HERE/f'run{n:02d}').exists(): n += 1
    folder = HERE/f'run{n:02d}'
    execute(APP, folder, '^Test(AllRulesLegacyInputs|SelectedSavedOrders|Research143NativeIntegration|D07SavedIntegration|D07SavedAddon)$', True, args.note)
    old = json.loads((HERE/'baseline_run/旧4手法の全約定.json').read_text(encoding='utf8'))
    new = json.loads((folder/'旧4手法の全約定.json').read_text(encoding='utf8'))
    old_by_key = {(r['Session'], r['Symbol']): r for r in old}
    differences = []
    for row in new:
        previous = old_by_key.get((row['Session'], row['Symbol']))
        if row != previous:
            differences.append({'key': [row['Session'], row['Symbol']], 'actual': row, 'expected': previous})
    d07 = json.loads((folder/'D07全約定.json').read_text(encoding='utf8'))
    prior = json.loads((ROOT/'work/d07_rules/run04/D07全約定照合.json').read_text(encoding='utf8'))
    prior_by_scene = {r['Session']: r for r in prior}
    d07_bad = [r['Session'] for r in d07 if r['Actual'] != prior_by_scene[r['Session']]['Actual']]
    tgpg = json.loads((folder/'TG04_PG04照合.json').read_text(encoding='utf8'))['Results']
    result = {'legacy_cases': len(new), 'legacy_orders': sum(len(r['Orders']) for r in new), 'legacy_differences': len(differences),
        'd07_cases': len(d07), 'd07_orders': sum(r['Orders'] for r in d07), 'd07_difference_scenes': d07_bad,
        'tgpg_cases': len(tgpg), 'tgpg_passed': sum(r['Passed'] for r in tgpg), 'tgpg_exact': sum(r['Exact'] for r in tgpg)}
    result['passed'] = len(new) == 100 and not differences and len(d07) == 50 and not d07_bad and len(tgpg) == 100 and all(r['Passed'] for r in tgpg)
    save(folder/'旧4手法の差分.json', differences)
    save(folder/'最終照合要約.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
