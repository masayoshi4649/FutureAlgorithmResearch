"""全現行手法の外部ルール化を、不変の旧Go版と比較するため事前登録する。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TOOL = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def digest(path):
    """実在ファイルのSHA256を求める。

    引数: path(Path)。返り値: strは内容指紋。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    """変更前資料を固定し、check/registerを実行する。

    引数: なし。返り値: None。金融再生・API取得・実注文は行わない。
    """
    receipt = HERE/'登録受領.json'
    if receipt.exists():
        assert json.loads(receipt.read_text(encoding='utf8'))['returncode'] == 0
        return
    prior = ROOT/'work/d07_rules/run04'
    archive = HERE/'変更前全内部Go.zip'
    if not archive.exists():
        shutil.copyfile(prior/'実行時実装.zip', archive)
    assert digest(archive) == digest(prior/'実行時実装.zip')
    files = [prior/name for name in ('結果要約.json', 'D07全約定照合.json', '実行条件.json', 'go結果.jsonl')]
    files += [
        ROOT/'work/d07_port/fixtures/manifest.json',
        ROOT/'work/sessiontrader143_port_20261025/fixtures_all/manifest.json',
        ROOT/'work/sessiontrader143_port_20261025/fixtures_all/legacy/manifest.json',
        ROOT/'App/SessionTrader/internal/strategy/testdata/selected_orders.json.gz',
    ]
    baseline = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    inventory = HERE/'変更前と入力の指紋.json'
    inventory.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding='utf8')
    oldplan = json.loads((ROOT/'work/d07_port/移植照合計画.json').read_text(encoding='utf8'))
    proposal = {
        'id': '145_全現行手法の外部ルール化同値照合_20261026',
        'name': '全7ルールプロファイルの外部化と変更前Go版の同値照合',
        'purpose': '独立再検証',
        'question': 'D07/TG04/PG04/T06両市場/T04/U06を個別ファイルへ外部化しても、従来の判断・数量・約定・所有・損益を変更しないか。',
        'change': '既存の入口・管理・出口の条件を商品別手法別のExprへ移す。ルールsampleを配布せず7個の実ファイルだけ初回配置し、再配布時は保持する。条件探索・パラメータ調整は行わない。',
        'repeat_reason': 'ユーザーの全現行ルール外部化の依頼に伴い、他手法の式混入、昼夜・商品取り違え、標準経路の変化を独立に検出する。',
        'compares_to': ['145_D07判断式外部化のGo同値照合_20261026'],
        'spec': {
            'entry': {'rule': '変更前run04ソースに実装された各現行手法の入口を維持。D07は従来51条件を維持し、他6プロファイルを追加。'},
            'management': {'rule': '同じ入力順・当時特徴を使用。親玉・担当・所有IDと予約をGoで維持。ルールの選択は商品と明示手法IDだけ。'},
            'exit': {'rule': '既存損切り・部分返済・トレーリング・残玉・場末条件を維持。既知の研究場末遡及修正以外の差は不合格。'},
            'allocation': {'rule': '現行配分を保存。D07/TG04/PG04はmini上限10枚。旧選定fixtureは保存枚数と追加参加設定を変更しない。'},
            'costs': {'rule': 'D07は研究費用0。TG04/PG04は既存38.5円片道切捨てと判断費用を維持。旧手法は保存fixtureの会計に従う。'},
            'execution': {'fill': '判断後の次正常原行BBO。ラージ気配による従来の代理約定。期待約定は判定入力へ渡さない。'},
            'data': {'sessions': oldplan['spec']['data']['sessions'],
                'input_manifests': [{'path': inventory.relative_to(ROOT).as_posix(), 'sha256': digest(inventory)}],
                'scope': '既存保存入力と期待値の再利用。独立同値検査であり収益性の新しい証拠へ数えない。旧手法fixture不足は旧Go版を同一入力で固定再生した結果と区別して保存する。'},
            'implementation': {archive.relative_to(ROOT).as_posix(): digest(archive), Path(__file__).relative_to(ROOT).as_posix(): digest(Path(__file__))},
        },
        'verification': {
            'profiles': ['d07','tg04','pg04','t06_topix','t06_nk225','t04','u06'],
            'D07': '前回Go版の既知50場831約定と全列完全一致を要求。',
            'TG04_PG04': '既存00143保存期待注文への全50場逐次照合。判断行・約定行・玉・担当・枚数・方向・理由を比較。',
            'legacy': '既存選定fixtureの4商品場と独立した旧Go版の同一入力出力を照合し、保存範囲を明示する。',
            'implementation_snapshot': '各再生直前にGo・依存・ルールファイルとSHAを保存。旧基準はrun04の不変ZIPを使用。',
        },
        'evidence': [{'path': 'work/d07_rules/照合結果.md'}, {'path': 'App/SessionTrader/docs/アルゴリズム.md'}],
    }
    plan = HERE/'全現行ルール照合計画.json'
    plan.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding='utf8')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    for action in ('check', 'register'):
        print(action+'開始', flush=True)
        with (HERE/(action+'.json')).open('wb') as out, (HERE/(action+'.stderr')).open('wb') as err:
            result = subprocess.run([sys.executable, str(TOOL), action, '--proposal', str(plan)], cwd=ROOT, env=env, stdout=out, stderr=err)
        if result.returncode:
            raise RuntimeError((HERE/(action+'.stderr')).read_text(encoding='utf8'))
        print(action+'完了', flush=True)
    receipt.write_text(json.dumps({'returncode': 0, 'trial_id': proposal['id'], 'proposal_sha256': digest(plan), 'baseline_archive_sha256': digest(archive)}, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
