"""共通正本を変更せず、管理登録と閲覧データの結合を私有コピーで検査する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import traceback
from unittest.mock import patch


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMMON = ROOT/'アルゴリズム調査/共通/知見台帳'
PRIVATE = HERE/'registration_fixture_LF版'
OUTPUT = HERE/'common_integration_artificial.json'
COUNTS = {}
_spec = importlib.util.spec_from_file_location('知見台帳の私有結合管理', COMMON/'manage.py')
manage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(manage)


def check(name: str, condition: bool) -> None:
    """
    機能: 管理と表示の人工期待を確認し、日本語件数を保存する。
    引数: name(str)、condition(bool)は検査項目と成立条件。
    返り値: None。不成立は例外として停止する。
    """
    assert condition, name
    COUNTS[name] = COUNTS.get(name, 0)+1


def digest(path: Path) -> str:
    """
    機能: 正本・source・証跡の内容指紋を計算する。
    引数: path(Path)はファイル。
    返り値: strはSHA256。生板又は金融再生を実行しない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fresh(name: str, original: dict[str, bytes]) -> Path:
    """
    機能: 管理のDATAだけを小さい私有コピーへ切り替える。
    引数: name(str)、original(dict[str,bytes])は検査名と正本三JSON及びbundleの原bytes。
    返り値: Pathは新しい私有DATA。共通正本やsourceは変更しない。
    """
    target = PRIVATE/name
    assert not target.exists()
    target.mkdir(parents=True)
    for filename, saved in original.items():
        (target/filename).write_bytes(saved)
    manage.DATA = target
    return target


def unchanged(target: Path, original: dict[str, bytes]) -> bool:
    """
    機能: 登録拒否時に全正本とbundleのbytesがそのままか確認する。
    引数: target(Path)、original(dict[str,bytes])は私有コピーと変更前。
    返り値: boolは四ファイル全一致。
    """
    return all((target/name).read_bytes() == saved for name, saved in original.items())


def proposal(base: dict, identifier: str) -> dict:
    """
    機能: 完全な104仕様のcloneから、成績を持たない人工計画を作る。
    引数: base(dict)、identifier(str)は既存試行と私有ID。
    返り値: dictは人工登録計画。新しい利益又は完了状態は付与しない。
    """
    return dict(id=identifier, name='人工だけの登録検査', purpose='条件比較',
        question='管理登録が保存前に拒否又は理由付き登録できるか', change='人工だけの条件記録',
        repeat_reason='保存と照合の結合検査。市場・金融の新結果ではない',
        compares_to=[base['id']], spec=deepcopy(base['spec']), evidence=[])


def rejected(name: str, value: dict, original: dict[str, bytes]) -> None:
    """
    機能: 不正又は重複の計画が正本変更前に拒否されることを確認する。
    引数: name(str)、value(dict)、original(dict[str,bytes])は検査名・人工計画・原bytes。
    返り値: None。私有コピーだけを使い、共通DATAに登録しない。
    """
    target = fresh(name, original)
    try:
        manage.store_trial(value)
    except (AssertionError, KeyError, ValueError, TypeError):
        check(name+'の保存前拒否', True)
    else:
        raise AssertionError(name+'が登録された')
    check(name+'の正本とbundle不変', unchanged(target, original))
    check(name+'では履歴やstaging未作成', not (target/'history').exists() and not list(target.glob('*.tmp')))


def registered(name: str, value: dict, original: dict[str, bytes], original_rows: list[dict]) -> None:
    """
    機能: 理由付き登録が元188行を維持し、bundleと履歴を正しく更新するか確認する。
    引数: name(str)、value(dict)、original(dict[str,bytes])、original_rows(list[dict])は私有登録入力。
    返り値: None。人工追加行は私有コピーにのみ保存する。
    """
    target = fresh(name, original)
    row = manage.store_trial(value)
    table = manage.read(target/'trials.json')
    check(name+'で元188行を保持', table['trials'][:-1] == original_rows and len(table['trials']) == 189)
    check(name+'を未実行で保存', row == table['trials'][-1] and row['status'] == '未実行' and 'result' not in row)
    previous = hashlib.sha256(original['trials.json']).hexdigest()
    history = target/'history'/('trials_'+previous+'.json')
    check(name+'の履歴bytesを保持', history.read_bytes() == original['trials.json'])
    loaded = manage.load(deep=True)
    check(name+'の正本とbundle一致', (target/'view-data.js').read_text(encoding='utf-8') == manage.bundle(loaded))
    check(name+'の他二正本を保持', (target/'knowledge.json').read_bytes() == original['knowledge.json']
        and (target/'studies.json').read_bytes() == original['studies.json'])


def source_links(value: dict) -> int:
    """
    機能: 実app.jsのsourceLinkをNodeの小DOM模擬で呼び、file相対リンクを確認する。
    引数: value(dict)は検証済み三正本。
    返り値: intは確認したユニーク出典リンク数。実ブラウザ描画とは区別する。
    """
    links = set()
    groups = (value['knowledge']['findings'], value['trials']['trials'],
        value['trials']['repetition_audit'], value['studies']['studies'])
    for rows in groups:
        for row in rows:
            links.update(item['path'] for item in row.get('evidence', []))
            links.update(row[field] for field in ('readme', 'report') if row.get(field))
    script = r'''
const fs=require('fs'),vm=require('vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const sandbox={window:{},document:{createElement:tag=>({tag,textContent:'',className:''}),getElementById:id=>({})}};
vm.runInNewContext(fs.readFileSync(input.script,'utf8'),sandbox);
const values=input.paths.map(path=>{const node=sandbox.sourceLink(path,'根拠');return {path,tag:node.tag,href:node.href,url:node.href?decodeURIComponent(new URL(node.href,input.base).href):null};});
const bad=input.bad.map(path=>({path,tag:sandbox.sourceLink(path,'根拠').tag}));
const text=sandbox.element('p','<script>alert(1)</script>');
process.stdout.write(JSON.stringify({values,bad,text:text.textContent}));
'''
    bad = ('../秘密', '/tmp/秘密', 'C:/秘密', 'http://example.test', 'javascript:alert(1)', 'a//b')
    saved = json.dumps(dict(script=str(COMMON/'view/app.js'), paths=sorted(links),
        base=(COMMON/'index.html').as_uri(), bad=bad), ensure_ascii=False)
    process = subprocess.run(['node', '-e', script], input=saved, capture_output=True,
        text=True, encoding='utf-8', check=True)
    actual = json.loads(process.stdout)
    for item in actual['values']:
        expected = manage.local_path(item['path'])
        check('実JSの根拠相対リンクがproject内実在先へ一致', item['tag'] == 'a' and item['url'] == expected.as_uri().replace('%20', ' ')
            if '%' not in expected.as_uri().replace('%20', ' ') else item['tag'] == 'a' and item['url'] == __import__('urllib.parse', fromlist=['unquote']).unquote(expected.as_uri()))
    check('実JSで不正パス6種をリンク化しない', all(item['tag'] == 'span' for item in actual['bad']))
    check('実JSでHTML文字列を文字として保持', actual['text'] == '<script>alert(1)</script>')
    return len(links)


def run() -> dict:
    """
    機能: 共通正本と管理コードを結合し、私有登録と全95仕様照合を検査する。
    引数: なし。
    返り値: dictは独立結合証跡。金融・原板・API・共通正本変更は0。
    """
    assert not PRIVATE.exists() and not OUTPUT.exists()
    observed = [COMMON/name for name in ('manage.py', 'duplicate_check.py', 'README.md', 'index.html',
        'view/app.js', 'view/style.css', 'data/knowledge.json', 'data/trials.json', 'data/studies.json', 'data/view-data.js')]
    start = {str(path.relative_to(ROOT)): digest(path) for path in observed}
    original = {name: (COMMON/'data'/name).read_bytes() for name in (*manage.FILES, 'view-data.js')}
    loaded = manage.load(deep=True)
    check('正本188知見14索引100', len(loaded['trials']['trials']) == 188 and len(loaded['knowledge']['findings']) == 14 and len(loaded['studies']['studies']) == 100)
    check('正本三JSONと生成bundle完全一致', (COMMON/'data/view-data.js').read_text(encoding='utf-8') == manage.bundle(loaded))
    rows = loaded['trials']['trials']
    completed = [row for row in rows if row.get('spec') is not None]
    check('104の完全specが95件', len(completed) == 95 and all(row['id'].startswith('104_') for row in completed))
    analyzer = manage.analyzer()
    fingerprints = set()
    for row in completed:
        result = analyzer.analyze(deepcopy(row), [row])
        independent = hashlib.sha256(json.dumps(row['spec'], ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        check('完全spec95の型を保った同一性照合', result['proposal_complete'] and len(result['matches']) == 1
            and result['matches'][0]['kind'] == '完全同一' and result['reusable'])
        check('完全spec95の独立正規指紋一致', result['提案指紋']['全体'] == independent)
        fingerprints.add(independent)
    check('95条件に完全同一の重複なし', len(fingerprints) == 95)
    for row in [row for row in rows if '105' in row['id']]:
        check('105を実行成功として登録していない', ('未実行' in row['status'] or '金融未実行' in row['status'])
            and row.get('spec') is None)
    incompletes = analyzer.analyze(completed[0], rows)
    check('未整理93試行は重複なしの証明にならない', len(incompletes['incomplete_history']) == 93 and not incompletes['重複なしの証明'])
    link_count = source_links(loaded)
    # ----------------------------------------
    base = completed[0]
    dataset = HERE/'新データ登録専用の人工目録.json'
    dataset.write_text(json.dumps(dict(人工専用=True, 市場再生なし=True, sessions=['人工新データ1場']), ensure_ascii=False)+'\n', encoding='utf-8')
    new_data = proposal(base, '人工新データ')
    new_data['purpose'] = '新データ'
    new_data['spec']['data']['sessions'] = ['人工新データ1場']
    new_data['spec']['data']['input_manifests'] = [dict(path=str(dataset.relative_to(ROOT)), sha256=digest(dataset))]
    value = deepcopy(new_data)
    value['id'] = '人工不正根拠'
    value['evidence'] = [dict(path='work/存在しない人工根拠.json', sha256='0'*64)]
    rejected('無効evidence', value, original)
    value = deepcopy(new_data)
    value['id'] = base['id']
    rejected('重複ID', value, original)
    rejected('完全同一通常登録', proposal(base, '人工完全同一'), original)
    value = deepcopy(new_data)
    value['id'] = '人工不正目録'
    value['spec']['data']['input_manifests'][0]['sha256'] = '0'*64
    rejected('目録SHA不一致', value, original)
    value = deepcopy(new_data)
    value['id'] = '人工不正実装'
    first = next(iter(value['spec']['implementation']))
    value['spec']['implementation'][first] = '0'*64
    rejected('実装SHA不一致', value, original)
    value = deepcopy(new_data)
    value['id'] = '人工上位参照'
    value['spec']['data']['input_manifests'][0]['path'] = '../存在しない目録.json'
    rejected('目録上位参照', value, original)
    registered('新データ理由付き登録', new_data, original, rows)
    check('新データ差を条件差と混同しない', any(item['id'] == base['id'] and item['kind'] == '新データ'
        for item in manage.read(manage.DATA/'trials.json')['trials'][-1]['preflight']['matches']))
    independent = proposal(base, '人工独立再検証')
    independent['purpose'] = '独立再検証'
    registered('同一条件独立登録', independent, original, rows)
    # ----------------------------------------
    target = fresh('view置換失敗復旧', original)
    original_replace = Path.replace

    def failing_replace(path: Path, destination: Path) -> Path:
        """
        機能: 私有view置換だけを人工OSErrorにして正本復旧を確認する。
        引数: path/destination(Path)は置換元先。
        返り値: Pathは通常置換結果。人工viewの場合だけ例外を送出する。
        """
        if path == target/'view-data.js.tmp':
            raise OSError('人工のview置換失敗')
        return original_replace(path, destination)

    try:
        with patch.object(Path, 'replace', failing_replace):
            manage.store_trial(new_data)
    except OSError:
        check('view置換失敗で例外を保持', True)
    else:
        raise AssertionError('人工view置換失敗が起きなかった')
    check('view置換失敗時も正本とbundleを復旧', unchanged(target, original))
    manage.DATA = COMMON/'data'
    end = {str(path.relative_to(ROOT)): digest(path) for path in observed}
    check('共通source正本bundleを一切変更しない', start == end)
    return dict(全合格=True, 人工登録は私有コピーのみ=True, 検査項目数=len(COUNTS), 検査件数=COUNTS,
        正本試行数=188, 知見数=14, 保存先索引=100, 完全spec照合=95,
        不完全過去試行=93, 相対根拠リンク数=link_count, 共通開始終端SHA256=start,
        私有source_SHA256={str(Path(__file__).relative_to(ROOT)): digest(Path(__file__))},
        共通正本編集=0, 共通source編集=0, 原板読取=0, 巨大cache読取=0, 金融再生=0, 現在API=0, 実注文=0,
        根拠確認='manage.load(deep=True)の全evidence・spec.data目録・spec.implementation指紋を実照合。金融公開JSONはhashのみ、再生しない。',
        限界='Nodeの実app.jsによるリンク検査は実ブラウザ描画ではない。95明示仕様の一致であり、残り93と未登録履歴の重複不存在は証明しない。')


def main() -> None:
    """
    機能: 独立結合の成功又は失敗を所有域へ保存する。
    引数: なし。
    返り値: None。Falseも保存し、共通正本を変更しない。
    """
    try:
        value = run()
    except Exception as error:
        OUTPUT.write_text(json.dumps(dict(全合格=False, 失敗=str(error), traceback=traceback.format_exc(),
            検査件数=COUNTS, 共通正本編集=0, 金融再生=0), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise
    OUTPUT.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=value['全合格'], 検査項目数=len(COUNTS), 総件数=sum(COUNTS.values())), ensure_ascii=False))


if __name__ == '__main__':
    main()
