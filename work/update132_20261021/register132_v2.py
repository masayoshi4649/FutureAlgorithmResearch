"""採用済み条件の追加データ検証と接続同値検査を実行前に登録する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TOOL = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def reference(path):
    """
    機能: 実在する入力・実装の位置と内容指紋を得る。
    引数: path(Path)はプロジェクト内のファイル。
    返り値: dict[str,str]は相対位置とSHA256。
    """
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def save(path, value):
    """
    機能: 事前計画と照合記録を新規保存する。
    引数: path(Path)は保存位置、value(dict)はJSON内容。
    返り値: None。既存ファイルは上書きしない。
    """
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def register(mode):
    """
    機能: 固定4系統の同値検査又は追加検証を事前照合し登録する。
    引数: mode(str)はgolden又はadditional。
    返り値: None。金融再生は行わない。
    """
    golden = mode == 'golden'
    manifest = HERE / ('golden_manifest.json' if golden else 'inputs_v1/input_manifest.json')
    inputs = json.loads(manifest.read_text(encoding='utf-8-sig'))
    description = json.loads((HERE / 'driver_description_v2.json').read_text(encoding='utf-8-sig'))
    stem = '同値検査の試行計画_v2' if golden else '試行計画_v2'
    purpose = '独立再検証' if golden else '新データ'
    reason = ('接続用driverが旧4商品場の注文・親損益・評価曲線を保存済み採用結果と同一に再現するか確認する。有効性の新証拠には数えない。'
              if golden else 'ユーザー追加の10月20日ナイト・10月21日デイで、条件を選び直さず現行の採用条件を確認する。旧43場会計は保存値を再利用する。')
    plan = dict(
        id='132_v2_' + ('採用条件の接続同値検査' if golden else '採用条件の追加2場検証'),
        name='現行アルゴリズムの' + ('接続同値検査' if golden else '追加2セッション検証'),
        purpose=purpose,
        question=reason,
        change='金融未実行のv1でsignals階層の入力検査不備を検出し、v2で資格検査のみ修正。判断・出口・配分・費用は00131採用条件のまま。新driverで同じ数値核へ接続する。' + ('対象は既存2場。' if golden else '追加2場だけを金融再生する。'),
        repeat_reason=reason,
        compares_to=['131_round3_旧核維持と独立初回参加', '131_round4_旧核維持と独立初回参加'],
        evidence=[reference(HERE / 'driver_description_v2.json')],
        spec=dict(
            entry=dict(selection=description['selection'], configs=description['configs'], 固定条件='00131の昼夜別採用条件。追加データによる再探索なし。'),
            management=dict(条件='旧主担当と初回追加の独立管理を維持。両ラージ板の当時公開情報だけで判断。'),
            exit=dict(条件='旧主担当の返済・追加担当の初期損切りとトレーリングを維持。セッション内全返済。'),
            allocation=dict(主担当=dict(TOPIXmini=5, NK225micro=10), 追加担当=dict(TOPIXmini=5, NK225micro='最大10枚。夜U06はfloor(10×120/R)、1〜10枚'), 片方向上限=dict(TOPIXmini=10, NK225micro=20)),
            costs=dict(TOPIXmini=41.8, NK225micro=11, 課金='新規・返済の注文ごとに1円未満切捨て。親取引の全返済後損益で利益損失を分ける。'),
            execution=dict(条件='00131の研究会計を維持。ラージ次正常原行BBOでmini/micro約定を代理。実受信時計・実約定・途中起動の再現ではない。'),
            data=dict(input_manifests=[reference(manifest)], sessions=[p['session'] for p in inputs['packets']], 範囲=reason, 照合範囲='00129〜00131の固定計画と採用会計を確認。未整理の過去全試行に重複なしと主張しない。'),
            implementation=description['sources'],
        ),
        mode=mode, sessions=[p['session'] for p in inputs['packets']], input_manifest=reference(manifest),
        sources=description['sources'], configs=description['configs'], selection=description['selection'],
    )
    path = HERE / (stem + '.json')
    save(path, plan)
    for action in ('check', 'register'):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(TOOL), action, '--proposal', str(path)], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        payload = dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        save(HERE / (stem + '_' + action + '.json'), payload)
        if result.returncode:
            print(result.stderr)
            raise SystemExit(result.returncode)
        summary = json.loads(result.stdout)
        print(json.dumps(dict(mode=mode, action=action, complete=summary.get('proposal_complete', summary.get('preflight', {}).get('proposal_complete')), id=summary.get('id')), ensure_ascii=False))


if __name__ == '__main__':
    register('golden')
    register('additional')
