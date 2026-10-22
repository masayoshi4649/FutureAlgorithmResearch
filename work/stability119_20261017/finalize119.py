"""根が完成監査を確認した後だけ、119系列の検証終了を一括で台帳へ結ぶ。"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REGISTRY = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合'
PUBLIC = ROOT / 'アルゴリズム調査/00119_戦略の自動選択と場内黒字の再探索'
TARGETS = (
    dict(id='119_全玉清算教師と異なる戦略から場内安定黒字を探す',
         result='recovery119/戦略自動選択と全四十場の復元結果.json',
         sha256='13bdd30ecf5ad8dd12ce4d8f0aec96a025e7bd1bb36e33fa8b30bc02de0d2c15',
         proposal='試行計画.json', fixed='正式固定.json', source_key='source_SHA256',
         accounting=dict(raw_reads=82, initialization_failed_raw_reads=2,
                         completed_raw_reads=80, financial_accounts=20160,
                         portfolio_accounts=80, financial_replays_for_recovery=0,
                         saved_type_failure='NumPy集約型のJSON保存停止',
                         recovery_method='保存済み台帳から会計復元',
                         recovered_canceled=None, recovered_halted=None),
         text='252政策×両商品40場の20160会計と三枠80会計を検証。保存型の停止後は保存済み台帳から会計を復元し、金融再生はしていない。'),
    dict(id='119b_共同進行の失速復帰と事前価格保護の原因対照',
         result='v2/measurement/復帰確認と執行保護の全四十場.json',
         sha256='7c56485d4b168928bd432cdb9644037ad2c4d733c19b3fc0168786a928b0586f',
         proposal='v2/試行計画.json', fixed='v2/固定計画.json', source_key='sources',
         accounting=dict(raw_reads=0, financial_accounts=2880),
         text='失速後の復帰を確認する入口と事前価格保護を36政策×両商品40場で対照検証。'),
    dict(id='119c_小試行と当初リスクを増やさない順行追加の対照',
         result='v3/measurement/小試行と順行追加の全四十場.json', sha256=None,
         proposal='v3/試行計画.json', fixed='v3/固定計画.json', source_key='sources',
         accounting=dict(raw_reads=0, financial_accounts=2880),
         text='同じ6入口で小枚数固定・全枚数固定・順行増加と2追尾幅を36政策×両商品40場で対照検証。停止線の予算維持は実損失の上限保証ではない。'),
)
ADDITIONAL_IDS = {
    '119d_広い共同進行と離脱及び遅行追随を同時点で逆建て',
    '119e_両脚の費用と時間差を含む相対乖離の場内回帰',
    '119f_少額E01の商品別固定設定を追加七場へ適用',
    '119g_相対的な強さの継続と残差追尾の場内対照',
    '119h_少額E01の時計逆行行除外による入力停止修正',
    '119i_相対乖離の実際の復帰確認と残差追尾の対照',
    '119j_相対復帰の初期気配差を含む清算予算の対照',
}


def encoded(value: object) -> bytes:
    """
    機能: 非有限値を拒否して日本語JSONを保存形式へ変換する。
    引数: value(object)は原始型だけからなる保存対象。
    返り値: bytesは改行付きUTF-8。欠測値のNoneを零へ変えない。
    """
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def sha_bytes(payload: bytes) -> str:
    """
    機能: 既に所有しているバイト列の内容指紋を計算する。
    引数: payload(bytes)は保存前又は一読済みの内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def digest(path: Path) -> str:
    """
    機能: 内容を意味解析せずファイル指紋を計算する。
    引数: path(Path)は完成結果又は根拠ファイル。
    返り値: strはSHA256。金融計算や市場入力の読取は行わない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def local(name: str) -> Path:
    """
    機能: 正本ルート内の実在ファイルだけを根拠として認める。
    引数: name(str)は正本ルートからの相対パス。
    返り値: Pathは正規化済み絶対パス。上位参照と外部パスを拒否する。
    """
    assert isinstance(name, str) and name
    parts = name.replace('\\', '/').split('/')
    assert all(part not in ('', '.', '..') and ':' not in part for part in parts), name
    path = ROOT.joinpath(*parts).resolve()
    assert path.is_relative_to(ROOT) and path.is_file(), name
    return path


def relative(path: Path) -> str:
    """
    機能: 検証済みのローカルパスを台帳用の表記へ変換する。
    引数: path(Path)は正本ルート配下のファイル。
    返り値: strは区切りを統一した相対パス。
    """
    return path.resolve().relative_to(ROOT).as_posix()


def small_json(path: Path) -> dict:
    """
    機能: 完了根拠又は固定計画の小JSONだけを有限値として読み込む。
    引数: path(Path)は最大8MiBの辞書JSON。
    返り値: dictは内容。巨大金融結果の意味解析には使わない。
    """
    assert path.stat().st_size <= 8 * 1024 * 1024, path
    value = json.loads(path.read_bytes().decode('utf-8-sig'))
    assert isinstance(value, dict)
    encoded(value)
    return value


def reference(item: dict, label: str) -> dict:
    """
    機能: 根が指定した根拠の実在と内容指紋を照合する。
    引数: item(dict)はpath/sha256、label(str)は根拠の説明。
    返り値: dictは台帳へ保存できる検証済み根拠。
    """
    path = local(item['path'])
    expected = item['sha256']
    assert isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected)
    assert digest(path) == expected, item['path']
    return dict(path=relative(path), sha256=expected, label=label)


def append_unique(items: list, value: dict) -> None:
    """
    機能: 以前の根拠又は実行履歴を削除せず新しい項目だけを追加する。
    引数: items(list)は既存配列、value(dict)は追加したい項目。
    返り値: None。同じ辞書が既存なら追加しない。
    """
    assert isinstance(items, list)
    if value not in items:
        items.append(value)


def target_definitions(records: list) -> list[dict]:
    """
    機能: 目録が指定した試行を既定定義又は明示された追加定義へ結び付ける。
    引数: records(list)は根が確認した試行別の完成根拠。
    返り値: list[dict]は固定定義。旧三件の条件・指紋を目録で上書きしない。
    """
    assert isinstance(records, list) and records
    assert len({row['id'] for row in records}) == len(records)
    known = {row['id']: row for row in TARGETS}
    definitions = []
    for row in records:
        identity = row['id']
        if identity in known:
            assert 'definition' not in row, '既定試行の完成定義は上書きできません'
            definitions.append(known[identity])
            continue
        assert identity in ADDITIONAL_IDS, 'この終了反映で未承認の試行IDです'
        extra = copy.deepcopy(row['definition'])
        assert set(extra) == {'result', 'proposal', 'fixed', 'source_key', 'accounting', 'text'}
        assert extra['source_key'] in ('source_SHA256', 'sources')
        for key in ('result', 'proposal', 'fixed'):
            path = local(relative(HERE / extra[key]))
            assert path.is_relative_to(HERE)
        assert isinstance(extra['text'], str) and extra['text'].strip()
        counts = extra['accounting']
        assert isinstance(counts, dict)
        if identity == '119f_少額E01の商品別固定設定を追加七場へ適用':
            assert type(counts['raw_reads']) is int and counts['raw_reads'] >= 0
            assert counts['financial_accounts'] in (0, 14)
            if counts['financial_accounts'] == 0:
                assert counts['raw_reads'] == 42 and counts['input_preparation_failed'] is True
                extra['stopped'] = True
            else:
                assert counts['reused_financial_accounts'] == 66
        else:
            assert counts['raw_reads'] == 0
        if identity == '119h_少額E01の時計逆行行除外による入力停止修正':
            assert counts['financial_accounts'] == 14 and counts['reused_financial_accounts'] == 66
        assert type(counts['financial_accounts']) is int and counts['financial_accounts'] >= 0
        assert counts['financial_accounts'] > 0 or extra.get('stopped') is True
        extra.update(id=identity, sha256=None)
        definitions.append(extra)
    return definitions


def manager_module() -> object:
    """
    機能: 共通台帳の検証・ビュー生成部品だけを通常の副作用なしで読み込む。
    引数: なし。
    返り値: objectはmanage.pyの部品。ここでは台帳のloadを呼ばない。
    """
    spec = importlib.util.spec_from_file_location('_finalize119_manager', REGISTRY / 'manage.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_load(manager: object) -> tuple[dict, dict, dict]:
    """
    機能: 正本四JSONを各一回だけ解析し、同じバイト列を保全に渡す。
    引数: manager(object)は共通台帳管理部品。
    返り値: tuple[dict,dict,dict]は全正本、原バイト列、同時更新検出用stat。
    """
    originals = {}
    stamps = {}
    paths = {(manager.DATA / name).resolve() for name in manager.FILES}
    original_read, original_digest = manager.read, manager.digest

    def captured_read(path: Path) -> dict:
        """
        機能: 管理部品の正本読取を一回のバイト列取得へ結び付ける。
        引数: path(Path)は管理部品が指定した正本。
        返り値: dictは有限JSON。正本以外は通常読取へ渡す。
        """
        resolved = path.resolve()
        if resolved not in paths:
            return original_read(path)
        assert resolved not in originals, resolved
        before = resolved.stat()
        payload = resolved.read_bytes()
        after = resolved.stat()
        assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        originals[resolved] = payload
        stamps[resolved] = (after.st_size, after.st_mtime_ns)
        value = json.loads(payload.decode('utf-8-sig'))
        encoded(value)
        return value

    def captured_digest(path: Path) -> str:
        """
        機能: loadに必要な正本指紋を一読済みバイト列から得る。
        引数: path(Path)は正本又は検証根拠。
        返り値: strは内容指紋。根拠ファイルは通常のdeep検証を保つ。
        """
        resolved = path.resolve()
        return sha_bytes(originals[resolved]) if resolved in originals else original_digest(path)

    manager.read, manager.digest = captured_read, captured_digest
    try:
        data = manager.load(deep=True)
    finally:
        manager.read, manager.digest = original_read, original_digest
    assert set(originals) == paths
    return data, originals, stamps


def stage_write(path: Path, payload: bytes) -> None:
    """
    機能: 一時ファイルを排他的に作り内容をディスクへ送る。
    引数: path(Path)は未使用の一時パス、payload(bytes)は検証済み保存内容。
    返り値: None。既存一時ファイルを上書きしない。
    """
    with path.open('xb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def finalize(manifest_path: Path) -> dict:
    """
    機能: 指定試行の完成根拠を照合し、旧履歴を保全して台帳とビューを一括更新する。
    引数: manifest_path(Path)は根が完成後に作る可変件数の小根拠目録。
    返り値: dictは更新前後の指紋と検証範囲。収益目標の達成判定ではない。
    """
    assert (PUBLIC / 'README.md').is_file(), '公開README完成前には反映しません'
    manifest = small_json(manifest_path)
    assert manifest['全合格'] is True and manifest['根による完成確認'] is True
    records = manifest['trials']
    targets = target_definitions(records)
    prepared = {}
    for target in targets:
        item = next(row for row in records if row['id'] == target['id'])
        expected_result = HERE / target['result']
        assert local(item['result']['path']) == expected_result.resolve()
        if target['sha256'] is not None:
            assert item['result']['sha256'] == target['sha256']
        result = reference(item['result'], '入力停止の保存記録。金融未実行。' if target.get('stopped') else '検証を完了した保存結果。目標達成とは別。')
        audits = item['audits']
        assert isinstance(audits, list) and audits
        audits = [reference(e, '完成結果の独立会計又は読取監査。') for e in audits]
        readme, report = local(item['readme']), local(item['report'])
        assert readme.is_relative_to(PUBLIC) and report.is_relative_to(PUBLIC)
        assert readme.suffix == '.md' and report.suffix == '.html'
        proposal_path, fixed_path = HERE / target['proposal'], HERE / target['fixed']
        proposal, fixed = small_json(proposal_path), small_json(fixed_path)
        sources = fixed[target['source_key']]
        assert proposal['id'] == target['id'] and proposal['spec']['implementation'] == sources
        assert isinstance(sources, dict) and sources
        for name, expected in sources.items():
            assert digest(local(name)) == expected, name
        prepared[target['id']] = dict(result=result, audits=audits, proposal=proposal,
            fixed=dict(path=relative(fixed_path), sha256=digest(fixed_path)),
            sources=sources, readme=relative(readme), report=relative(report))

    # ----------------------------------------
    # 指定された全件の完成根拠が揃った後だけ台帳を一回loadする。
    manager = manager_module()
    data, originals, stamps = capture_load(manager)
    table = data['trials']
    old_rows = copy.deepcopy(table['trials'])
    unchanged = {r['id']: r for r in old_rows if r['id'] not in prepared}
    already = True
    for target in targets:
        found = [r for r in table['trials'] if r['id'] == target['id']]
        assert len(found) == 1
        row, ready = found[0], prepared[target['id']]
        assert row['spec'] == ready['proposal']['spec'], target['id']
        completed_status = '入力検証で中断' if target.get('stopped') else '検証完了'
        assert row['status'] in ('未実行', completed_status)
        if row['status'] == completed_status:
            assert row['completed_result'] == ready['result'], '異なる完成結果を上書きしません'
            assert row['completed_audits'] == ready['audits']
            assert row['completed_registered_sources'] == ready['sources']
            assert row['completion_accounting'] == target['accounting'], '異なる読取・会計由来を同値扱いしません'
            assert row['completed_fixed'] == ready['fixed'], '異なる固定計画を同値扱いしません'
            assert row['readme'] == ready['readme'] and row['report'] == ready['report']
            continue
        already = False
        previous_attempts = copy.deepcopy(row.get('execution_attempts', []))
        if target['id'] == TARGETS[0]['id']:
            assert any(a.get('raw_reads') == 2 and a.get('financial_rows') == 0
                       for a in previous_attempts), '初期化停止の2読取履歴が必要です'
        row['status'] = completed_status
        row['completed_result'] = ready['result']
        row['completed_audits'] = ready['audits']
        row['completed_registered_sources'] = ready['sources']
        row['completed_fixed'] = ready['fixed']
        row['completion_accounting'] = target['accounting']
        row['readme'], row['report'] = ready['readme'], ready['report']
        row['result'] = target['text'] + ('入力停止を保全し、金融口座を完成したとは数えない。' if target.get('stopped') else '全場・費用後の結果と留保を公開した。検証完了は採用又は安定黒字の達成を意味しない。')
        row['completion_limitations'] = ('既知40場内の開発・比較であり未知成功を証明しない。'
            '無取引・未清算は勝ちでない。Last同時点分解は約定可能価格又は別手法の収益ではない。'
            '原価格時計は受信時計でなく、実小型板の順番・約定量・取消遅延は未観測。'
            '旧00097/00098と共通する順行増加の思想は新発明と扱わない。')
        row.setdefault('evidence', [])
        for evidence in [ready['result'], ready['fixed'], *ready['audits']]:
            append_unique(row['evidence'], evidence)
        row.setdefault('execution_attempts', [])
        append_unique(row['execution_attempts'], dict(status=completed_status,
            completion_marker='119系列の終了反映', result=ready['result'],
            accounting=target['accounting'], independent_evidence=False))
        assert row['execution_attempts'][:len(previous_attempts)] == previous_attempts
    assert all(row == unchanged[row['id']] for row in table['trials'] if row['id'] in unchanged)
    manager.validate(data, deep=True)
    if already:
        assert (manager.DATA / 'view-data.js').read_text(encoding='utf-8') == manager.bundle(data)
        return dict(全合格=True, 既登録同値=True, 台帳更新=0, 金融再生=0)

    # ----------------------------------------
    # 正本と閲覧データを先に組み立て、旧正本を保存後に順番に原子的置換する。
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    target_path = (manager.DATA / 'trials.json').resolve()
    previous = originals[target_path]
    old_sha = sha_bytes(previous)
    payload = encoded(table)
    new_sha = sha_bytes(payload)
    data['source_sha256']['trials.json'] = new_sha
    view_payload = manager.bundle(data).encode('utf-8')
    manager.validate(data, deep=True)
    history = manager.DATA / 'history' / ('trials_' + old_sha + '.json')
    history.parent.mkdir(exist_ok=True)
    if history.exists():
        assert digest(history) == old_sha
    else:
        stage_write(history, previous)
    staged = manager.DATA / 'trials119_finalization.tmp'
    staged_view = manager.DATA / 'view119_finalization.tmp'
    view = manager.DATA / 'view-data.js'
    assert not staged.exists() and not staged_view.exists() and view.is_file()
    old_view = view.read_bytes()
    stage_write(staged, payload)
    stage_write(staged_view, view_payload)
    assert digest(staged) == new_sha and staged_view.read_bytes() == view_payload
    for path, stamp in stamps.items():
        current = path.stat()
        assert (current.st_size, current.st_mtime_ns) == stamp, '登録との同時更新を検出しました'
    replaced = False
    try:
        staged.replace(target_path)
        replaced = True
        staged_view.replace(view)
        assert digest(target_path) == new_sha and view.read_bytes() == view_payload
        manager.validate(data, deep=True)
    except BaseException:
        if replaced:
            target_path.write_bytes(previous)
            view.write_bytes(old_view)
        raise
    return dict(全合格=True, 状態='検証完了', 目標達成の宣言=False,
        完了ID=[r['id'] for r in targets], 元台帳SHA256=old_sha,
        更新台帳SHA256=new_sha, 閲覧データSHA256=sha_bytes(view_payload),
        旧台帳保全=relative(history), 台帳JSON解析=1, 台帳更新=1,
        正本四JSON各一読=True, 内容指紋の再検査あり=True,
        deep検証=True, 閲覧データ同期=True, 実行履歴の旧項目保持=True,
        完成結果={key: dict(result=value['result'], audits=value['audits'],
            registered_sources=value['sources']) for key, value in prepared.items()},
        共通MDの指紋固定=False, 原市場入力読取=0, 原cache読取=0,
        金融結果意味解析=0, 金融再生=0, API=0)


def main() -> None:
    """
    機能: 根の明示実行指定がある時だけ完了反映を実行する。
    引数: CLIの--root-finalize(bool)と--manifest(Path)は完成確認済み小根拠目録。
    返り値: None。小証跡JSONと短い終了結果だけを出力する。
    """
    parser = argparse.ArgumentParser(description='119系列の検証終了だけを一括反映。金融実行はしません。')
    parser.add_argument('--root-finalize', action='store_true', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    assert args.root_finalize
    path = args.manifest.resolve()
    assert path.is_relative_to(HERE) and path.is_file()
    manifest_sha = digest(path)
    proof_path = HERE / ('系列試行の完了反映とビュー同期_' + manifest_sha[:16] + '.json')
    proof = finalize(path)
    assert digest(path) == manifest_sha, '実行中に完成目録が変わりました'
    proof['完成根拠目録'] = dict(path=relative(path), sha256=manifest_sha)
    proof['終了反映source'] = dict(path=relative(Path(__file__)), sha256=digest(Path(__file__)))
    if proof_path.exists():
        previous_proof = small_json(proof_path)
        assert proof.get('既登録同値') is True, '以前の終了証跡を上書きしません'
        assert previous_proof['全合格'] is True
        assert previous_proof['完成根拠目録'] == proof['完成根拠目録']
        assert previous_proof['終了反映source'] == proof['終了反映source']
    else:
        stage_write(proof_path, encoded(proof))
    print('指定試行の検証完了を台帳とビューへ同期。目標達成の宣言・金融再生0。', flush=True)


if __name__ == '__main__':
    main()
