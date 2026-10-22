"""根が確認した実会計版だけを公開用目録にまとめる。"""

import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
PHASES = [
    dict(directory='初回_戦略選択', source='public00119_戦略の自動選択と場内黒字の再探索',
         report='戦略の自動選択と全セッション損益.html', data='公開会計.json',
         title='戦略の自動選択と三枠配分',
         description='252政策と固定三枠。設定選択後の13場と、全40場を分離。',
         result='recovery119/戦略自動選択と全四十場の復元結果.json',
         expected='13bdd30ecf5ad8dd12ce4d8f0aec96a025e7bd1bb36e33fa8b30bc02de0d2c15'),
    dict(directory='改善1_復帰と価格保護', source='privatev2/public',
         report='安定黒字の再探索と全セッション損益.html', data='data.json',
         title='停止・復帰の確認と注文価格保護',
         description='36政策。反対への実際の戻りを確認し、不利な約定を制限。',
         result='v2/measurement/復帰確認と執行保護の全四十場.json',
         expected='7c56485d4b168928bd432cdb9644037ad2c4d733c19b3fc0168786a928b0586f'),
    dict(directory='改善2_張り方と増玉', source='privatev3/public',
         report='小枚数と順行増加の比較と全セッション損益.html', data='data.json',
         title='小枚数固定・全枚数固定・順行追加',
         description='36政策。同じ入口で数量と追尾幅を変え、実追加・平均建値・価格飛びを比較。',
         result='v3/measurement/小試行と順行追加の全四十場.json',
         expected='0e027e11a03e4f6a8c0bf9f1166e9f7487505ab91be5ea12b0d76eb9a88b0ca5'),
    dict(directory='改善3_順逆と時間回避', source='privatev4/public',
         report='順逆売買と時間回避の比較と全セッション損益.html', data='data.json',
         title='広い進行条件の順逆売買と時刻回避',
         description='48政策。新しい建玉で逆方向の損益と後続参加を再計算。米国時刻はDST対応。',
         result='v4/measurement/広い進行条件の順逆比較と全四十場.json',
         expected='9da66161eeab6557dfca24070dcb32c38d6a23311dc1eb46d68465c4003c406a'),
]


def digest(path: Path) -> str:
    """
    機能: 保存成果の指紋を求め、人工版との取り違えを防ぐ。
    引数: path(Path)は完成したファイル。
    返り値: strはSHA256。市場入力や金融計算は行わない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def create(extras: list[dict]) -> dict:
    """
    機能: 根が渡した追加段階を四段階へ結合し、実生成物の指紋を検査する。
    引数: extras(list[dict])は追加段階の位置・タイトル・正式結果の指紋。
    返り値: dictは公開時に使う小目録。まだ公開先へ書き込まない。
    """
    rows = []
    for source in [*PHASES, *extras]:
        row = source.copy()
        directory = BASE / row['source']
        proof = json.loads((directory / '生成証跡.json').read_text(encoding='utf-8'))
        if '全合格' in proof:
            assert proof['全合格'] is True and proof['合成fixture'] is False
            assert proof['元結果SHA256'] == row['expected']
            artifacts = proof['生成物SHA256']
        else:
            assert proof['passed'] is True and proof['fixture'] is False
            assert proof['result_sha256'] == row['expected']
            artifacts = proof['artifacts']
        names = [row['report'], row['data'], '生成証跡.json']
        row['files'] = [dict(name=name, sha256=digest(directory / name)) for name in names]
        for item in row['files']:
            if item['name'] != '生成証跡.json':
                assert item['sha256'] == artifacts[item['name']], item['name']
        assert digest(BASE / row['result']) == row['expected']
        row['source'] = directory.relative_to(ROOT).as_posix()
        row['result'] = (BASE / row['result']).relative_to(ROOT).as_posix()
        rows.append(row)
    return dict(root_checked=True, phases=rows,
                注意='人工fixtureを含めない。金融結果の再生は0、同じ保存成果の指紋検査と公開だけ。')
