"""今回の固定条件追加検証の結果と未実行計画を試行台帳へ記録する。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MANAGER = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def read(path):
    """
    機能: 結果又は台帳を読む。
    引数: path(Path)はUTF-8のJSON。
    返り値: dictは保存内容。
    """
    with path.open(encoding='utf-8-sig') as stream:
        return json.load(stream)


def reference(path):
    """
    機能: 証拠資料の内容指紋を得る。
    引数: path(Path)は既存資料。
    返り値: dict[str,str]は相対位置とSHA256。
    """
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=digest)


def save(path, value):
    """
    機能: 完了記録を新規保存する。
    引数: path(Path)は保存先、value(dict)は内容。
    返り値: None。既存記録は変更しない。
    """
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    """
    機能: 合格済み会計の完了状態と旧計画の未実行を対象4件だけに反映する。
    引数: なし。既存結果と独立監査の合格を前提とする。
    返り値: None。金融再生はせず、旧台帳を内容指紋付きで退避する。
    """
    result = HERE / 'results/追加セッションの会計.json'
    golden = HERE / 'golden_results/追加セッションの会計.json'
    audit = HERE / 'audit/独立注文会計と45場合計.json'
    display = HERE / 'report_display_audit.json'
    for path in (result, golden, audit, display):
        assert read(path)['passed'], path
    assert len(read(result)['rows']) == 4 and len(read(golden)['golden']) == 4
    ledger = MANAGER.parent / 'data/trials.json'
    before = reference(ledger)
    backup = ledger.parent / 'history' / ('trials_' + before['sha256'] + '.json')
    if not backup.exists():
        shutil.copyfile(ledger, backup)
    document = read(ledger)
    updates = {
        '132_採用条件の接続同値検査': ('未実行・入力資格検査の修正版へ移行', '金融再生前にsignalsの階層検査不備を検出。数値核を変えずv2へ移行し、この計画では金融再生0。', [HERE / 'input_audit_v2.json']),
        '132_採用条件の追加2場検証': ('未実行・入力資格検査の修正版へ移行', '金融再生前にsignalsの階層検査不備を検出。数値核を変えずv2へ移行し、この計画では金融再生0。', [HERE / 'input_audit_v2.json']),
        '132_v2_採用条件の接続同値検査': ('同値検査完了・新たな有効性証拠には数えない', '旧2セッション4商品場の注文・親取引会計・曲線が00131保存結果と一致。旧公開値は再利用。', [golden]),
        '132_v2_採用条件の追加2場検証': ('追加2場の固定条件検証完了', 'パラメータの再探索なし。追加2場4商品場を同じ数値核で再生し、独立注文会計と45場の表示を照合。研究仮想約定でありGo実稼働の約定記録ではない。', [result, audit, display]),
    }
    changed = []
    for item in document['trials']:
        if item['id'] in updates:
            assert item['status'] == '未実行', item['id']
            status, explanation, evidence = updates[item['id']]
            item.update(status=status, result=explanation)
            item['evidence'] += [reference(path) for path in evidence]
            changed.append(item['id'])
    assert set(changed) == set(updates)
    document['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    temporary = ledger.with_suffix('.json.132tmp')
    assert not temporary.exists()
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    temporary.replace(ledger)
    del document
    save(HERE / '試行完了の変更記録.json', dict(passed=True, before=before, after=reference(ledger), changed=changed, financial_replays=0))
    # ----------------------------------------
    # 事前登録時に指紋を検査済み。完了時は今回の証拠と台帳表示の整合だけを確認します。
    for command in ('build', 'verify'):
        output = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(MANAGER), command], cwd=ROOT, text=True, capture_output=True, encoding='utf-8')
        save(HERE / ('最終台帳_' + command + '.json'), dict(returncode=output.returncode, stdout=output.stdout, stderr=output.stderr))
        print(command, output.returncode, flush=True)
        assert output.returncode == 0, output.stderr[-2000:]


if __name__ == '__main__':
    main()
