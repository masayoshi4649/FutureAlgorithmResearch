"""全候補の仕様・実装・入力指紋を固定し、公式ツールで照合してから一度だけ登録する。"""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGINE = ROOT / 'work/research145_engine'
RESIDUAL = ROOT / 'work/research145_residual'
TOOL = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def read(path):
    """
    機能: UTF-8の設定・目録を読む。
    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    """
    機能: 元資料を変更せず内容指紋を作る。
    引数: path(Path)。返り値: strはSHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    """
    機能: 計画又は受領記録を保存する。
    引数: path(Path)、value(dict)。返り値: None。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def main():
    """
    機能: 事前照合成功時だけ新試行を登録する。金融再生は実行しない。
    引数: なし。返り値: None。登録済みなら再登録しない。
    """
    receipt = HERE / '登録受領145.json'
    if receipt.exists() and read(receipt).get('returncode') == 0:
        print('登録は完了済みです。再登録しません。', flush=True)
        return
    earlier = read(ROOT / 'work/nikkei143_20261024/第三巡計画143.json')
    coverage = ROOT / 'work/research145_data/全保存資料の再照合145.json'
    inputs = read(coverage)
    addon = read(ENGINE / '候補仕様145.json')
    residual = read(RESIDUAL / '残玉条件145.json')
    implementation = dict(earlier['spec']['implementation'])
    files = [ENGINE / n for n in ['config145.py', 'source145.py', 'trader145.py', 'run145.py', 'test145.py', '候補仕様145.json']]
    files += [RESIDUAL / n for n in ['residual145.py', 'run_residual145.py', 'test_residual145.py', '残玉条件145.json']]
    files += [HERE / '研究手順145.md']
    for p in files:
        implementation[str(p.relative_to(ROOT)).replace('\\', '/')] = digest(p)
    archive = HERE / '登録時の実装145.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, expected in implementation.items():
            path = ROOT / name
            assert digest(path) == expected
            z.write(path, name)
    frozen_audit = HERE / '登録時の既存診断145.md'
    frozen_audit.write_bytes((ROOT / 'work/research145_audit/既存TG04の敵対的診断と検証基準.md').read_bytes())
    plan = {
        'id': '145_利益保護と回転再参加の三十改修条件',
        'name': '利益の分割回収と再参加・反転の全保存場比較',
        'purpose': '条件比較',
        'question': '広い帯に合わせて保護開始を遠ざけず、利益玉回転・再加速・確認反転・部分利確後保護を使えば、大きな値幅の利益回収と各場の安定性を両立できるか。',
        'change': '追加V16条件（基準含む）、残玉R12条件（基準含む）と基本部分利確後P4条件。手数料は内部会計も0、保有50%目標を撤廃。時間0/60/300/900秒と状態再確認を分離する。',
        'repeat_reason': '00144で10/26午前追加の1.25R保護開始前に利益4.1万→1千を確認。全50場原板診断では基本の部分利確後残3枚も主原因。高ボラの持続成功と往復回帰の失敗を分け、新しい再参加条件まで評価する。',
        'compares_to': ['143_第三巡_確定利益内の残玉と後続機会の比較', '144_十月二十六日午前TG04少枚数の出口診断'],
        'configs': {'addon': addon, 'residual_and_partial': residual,
            'combinations': ['各担当の単体変更を基準相手と合成', '前半30場で各担当を選択し後半20場へ固定', '昼夜別に前半から選択し後半へ固定', '全50場の開発選択同士を合成（事後選抜と明示）'],
            'ranking': '赤字場数の少なさ→場収支中央値の高さ→累計収支の高さ→最大赤字の小ささ。基準も選択肢へ含む。'},
        'spec': {
            'entry': {'元源': 'TG04基本CG=昼O17/夜O02、別入口CS=昼S01/夜L00。追加A3は旧昼夜入口。元通知の判断行以前は参照しない。',
                '追加再参加': '黒字全退出後の待機0/60/300/900秒は全入口に適用。待機後は旧入口の再成立、又は新しい押戻り0.75単位と再加速0.25単位・支持15秒による追加入口で再参加する。押戻り条件を全入口の必須条件としない。', 'ドテン': addon['specification']['ドテン'],
                '新候補切替': 'R06以降は新候補通知後に旧残玉を実返済してから待機・現在30/120秒勢い再評価。反対新規は次正常気配。P群は基本だけ、別入口CS04を固定。'},
            'management': {'追加仕様': addon['specification'], '残玉と部分返済': residual,
                '最高値': '実際に保有・判定した時点までの極値だけを使う。事後の場全体幅・終値方向を入力しない。'},
            'exit': {'追加': '初回損切りRと利益単位を分離。部分利確・回転・全退出後再準備も全損失込み。',
                '基本': 'P群は利益を伴う部分利確の実約定後からだけ残玉の最高進捗/支持破綻を使う。',
                '場末': '元デイ15:35/ナイト05:50判断、次正常気配。元源の既知場末差は別に監査する。'},
            'allocation': {'product': 'NK225mini', 'max_per_side': 10, 'core': 5, 'addon': 3, 'secondary': 2, '貸借': 'なし。新規予約と実保有を含め逐次監査。'},
            'costs': {'fee_per_contract': 0, 'point_value': 100, 'profit_budget_fee': 0, 'lose_streak_fee': 0, 'spread': '実在するラージ売買気配差を保持。手数料とは分離。',
                '互換検証': '旧A3/S01/L00を元費用38.5円で再生し旧保存経路との同値を検査してよい。これは新候補の収益比較に含めない独立実装検証。'},
            'execution': {'模型': '原価格時計による判断後の次正常ラージBBO。mini自身の約定、伝送遅延、注文順位は再現しない。', '反転': '旧玉返済確認後に新しい判断・次正常気配で逆新規。'},
            'data': {'sessions': inputs['sessions']['NK225'], 'input_manifests': [{'path': str(coverage.relative_to(ROOT)).replace('\\', '/'), 'sha256': digest(coverage)}],
                '部分資料': '10/26午前は仮説の発端で、当日全体の取引比較に混ぜず00144の原板機構診断を引用。',
                '対象': '両市場50場・100raw全14,423,267行を既存全行解析との全文SHA一致で再照合。適格14,338,109行。'},
            'implementation': {str(archive.relative_to(ROOT)).replace('\\', '/'): digest(archive)},
        },
        'evidence': [{'path': str(frozen_audit.relative_to(ROOT)).replace('\\', '/'), 'sha256': digest(frozen_audit)}],
    }
    proposal = HERE / '固定計画145.json'
    save(proposal, plan)
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    for command in ('check', 'register'):
        stdout = HERE / f'{command}145.json'
        stderr = HERE / f'{command}145.stderr.txt'
        print(command + 'を開始します。', flush=True)
        with stdout.open('wb') as out, stderr.open('wb') as err:
            result = subprocess.run([sys.executable, str(TOOL), command, '--proposal', str(proposal)],
                cwd=ROOT, env=env, stdout=out, stderr=err)
        if result.returncode:
            print(stderr.read_text(encoding='utf-8'), flush=True)
            raise RuntimeError(f'{command}が失敗しました。金融再生は開始しません。')
        if command == 'check':
            assert read(stdout)['proposal_complete']
        print(command + 'が完了しました。', flush=True)
    save(receipt, {'returncode': 0, 'trial_id': plan['id'], 'proposal_sha256': digest(proposal),
         'archive_sha256': digest(archive), 'registration_output_sha256': digest(HERE / 'register145.json'),
         'implementation': implementation})


if __name__ == '__main__':
    main()
