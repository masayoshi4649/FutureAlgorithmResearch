"""D07判断式の外部化について、保存Go版との同値検証を事前登録する。"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OLD = ROOT / 'work/d07_port'
TOOL = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def digest(path):
    """資料の内容指紋を計算する。

    引数: path(Path)は対象ファイル。返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    """既存Go版を固定し、式外部化の独立同値試験を登録する。

    引数: なし。返り値: None。金融再生・API取得・実注文は行わない。
    """
    receipt = HERE / '登録受領.json'
    if receipt.exists():
        assert json.loads(receipt.read_text(encoding='utf8'))['returncode'] == 0
        return
    baseline_paths = [OLD/'run01'/name for name in (
        '結果要約.json', '実行条件.json', '実行時実装.zip',
        'D07全約定照合.json', 'go結果.jsonl')]
    baseline_paths += [OLD/'fixtures/manifest.json']
    baseline = {path.relative_to(ROOT).as_posix(): digest(path) for path in baseline_paths}
    (HERE/'基準結果指紋.json').write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding='utf8')

    # ----------------------------------------
    # 改修中の版は登録時点の資料として固定し、実行版は別に保存する。
    app = ROOT/'App/SessionTrader'
    paths = sorted((app/'internal').rglob('*.go'))
    paths += sorted((app/'conf').rglob('*.toml'))
    paths += [app/'go.mod', app/'go.sum', Path(__file__)]
    archive = HERE/'登録時実装.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in paths:
            z.write(path, path.relative_to(ROOT).as_posix())

    proposal = json.loads((OLD/'移植照合計画.json').read_text(encoding='utf8'))
    proposal.update({
        'id': '145_D07判断式外部化のGo同値照合_20261026',
        'name': 'D07の外部Expr判断式と従来Go版の全50場同値照合',
        'purpose': '独立再検証',
        'question': 'D07の判断式を外部定義へ移しても全831約定を変えず、契約不正時は発注を止めて式の指紋を追跡できるか。',
        'change': '実装表現だけをGo固定条件から外部Expr式へ移す。判定値はbool/float、関数は許可一覧、実行エラーはPortfolio境界で保持し発注停止。戦略条件の探索・調整はしない。',
        'repeat_reason': 'Web版D07の判断規則を外部化する依頼に伴い、数量・判断時刻・約定時刻・所有玉・理由の意図しない差とエラー継続を独立に検出する。',
        'compares_to': ['145_D07のGo移植独立照合_20261026'],
        'evidence': [
            {'path': 'work/d07_port/移植照合結果.md'},
            {'path': 'アルゴリズム調査/00145_利益の分割回収と再参加の全場検証/売買条件.md'}
        ],
    })
    proposal['spec']['implementation'] = {
        archive.relative_to(ROOT).as_posix(): digest(archive),
        (HERE/'基準結果指紋.json').relative_to(ROOT).as_posix(): digest(HERE/'基準結果指紋.json'),
    }
    proposal['verification'] = {
        'baseline': baseline,
        'execution_snapshot': '実行ごとにGoソース・外部判断式・SHA256をwork/d07_rules/runNNへ事前保存する。',
        'same_result': '旧Go版の全831約定と完全同一を必須。研究版に対しては829件一致＋既知2件の場末因果修正を維持。',
        'review': '構文・型・許可関数・欠損/非有限値・実行失敗・発注境界・ルール指紋のログ追跡を人工例と静的レビューで確認する。',
    }
    proposal['spec']['data']['scope'] += ' 今回も同じ保存済み入力であり、新しい収益性証拠に数えない。'
    plan = HERE/'外部化照合計画.json'
    plan.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding='utf8')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    for action in ('check', 'register'):
        print(action+'開始', flush=True)
        with (HERE/(action+'.json')).open('wb') as out, (HERE/(action+'.stderr')).open('wb') as err:
            result = subprocess.run([sys.executable, str(TOOL), action, '--proposal', str(plan)], cwd=ROOT, env=env, stdout=out, stderr=err)
        if result.returncode:
            raise RuntimeError((HERE/(action+'.stderr')).read_text(encoding='utf8'))
        print(action+'完了', flush=True)
    receipt.write_text(json.dumps({'returncode': 0, 'trial_id': proposal['id'], 'proposal_sha256': digest(plan), 'archive_sha256': digest(archive), 'baseline_manifest_sha256': digest(HERE/'基準結果指紋.json')}, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
