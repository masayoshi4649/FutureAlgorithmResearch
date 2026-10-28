"""D07の独立移植照合を、保存資料と実装版を固定して事前登録する。"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TOOL = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def digest(path):
    """資料のSHA256を求める。

    引数: path(Path)。返り値: str。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    """既存保存結果へのGo同値試験だけをcheck/registerする。

    引数: なし。返り値: None。金融再生や発注を行わない。
    """
    receipt=HERE/'登録受領.json'
    if receipt.exists():
        assert json.loads(receipt.read_text(encoding='utf8'))['returncode']==0
        return
    fixture=json.loads((HERE/'fixtures/manifest.json').read_text(encoding='utf8'))
    archive=HERE/'照合開始時実装.zip'
    paths=sorted((ROOT/'App/SessionTrader/internal/strategy').glob('*.go'))
    paths.extend([Path(__file__),HERE/'extract.py'])
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path in paths:z.write(path,path.relative_to(ROOT).as_posix())
    proposal={
        'id':'145_D07のGo移植独立照合_20261026',
        'name':'D07のGo実装と既存50場の逐次同値照合',
        'purpose':'独立再検証',
        'question':'Goへ移植したD07が研究の判断・次正常気配約定・数量・担当別収支を維持するか。',
        'change':'言語と実約定分離実装をGoへ変更。研究条件を新規探索せず、保存期待注文と全行比較する。',
        'repeat_reason':'Web売買アプリの日経標準へD07を採用する依頼に対し、入口・部分利確・再参加・ドテン・残玉の移植誤差を検出する。',
        'compares_to':['145_担当別出口とドテンの中期支持確認'],
        'spec':{
            'entry':{'rule':'00145 D07。元TG04の源を維持、追加V05昼・V16夜。40分方向確認は夜の新ドテン経路だけ。'},
            'management':{'rule':'原行順・公開特徴で源と実玉を分離。昼CG_P01、夜CG_R05、CS_R00、追加は昼V05夜V16。'},
            'exit':{'rule':'昼部分利確後の残含み益peak50%、夜主残1の3R幅に160pt上限。元損切り・静観・場末維持。'},
            'allocation':{'product':'NK225mini','maximum_per_side':10,'core':5,'addon':3,'episode':2,'loan':False},
            'costs':{'policy_fee':0,'validation_fee':0,'note':'研究00145の0円条件。実口座の費用計上は別に保持。'},
            'execution':{'fill':'判断後の次正常原行BBO。ラージ気配をmini代理に用いる既存同値条件。','terminal':'既知の予定場末以前へ遡った旧判断は因果修正差として別記。その他の相違は不合格。'},
            'data':{'sessions':[x['session'] for x in fixture['cases']],
                'input_manifests':[{'path':(HERE/'fixtures/manifest.json').relative_to(ROOT).as_posix(),'sha256':digest(HERE/'fixtures/manifest.json')}],
                'scope':'00145と同じ既知50場。全原行、未来ラベル入力禁止。新しい有効性の証拠ではない。'},
            'implementation':{archive.relative_to(ROOT).as_posix():digest(archive)}
        },
        'evidence':[{'path':'アルゴリズム調査/00145_利益の分割回収と再参加の全場検証/売買条件.md'}]
    }
    path=HERE/'移植照合計画.json'
    path.write_text(json.dumps(proposal,ensure_ascii=False,indent=2),encoding='utf8')
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    for action in ['check','register']:
        print(action+'開始',flush=True)
        with (HERE/(action+'.json')).open('wb') as out,(HERE/(action+'.stderr')).open('wb') as err:
            result=subprocess.run([sys.executable,str(TOOL),action,'--proposal',str(path)],cwd=ROOT,env=env,stdout=out,stderr=err)
        if result.returncode:
            raise RuntimeError((HERE/(action+'.stderr')).read_text(encoding='utf8'))
        print(action+'完了',flush=True)
    receipt.write_text(json.dumps({'returncode':0,'trial_id':proposal['id'],'proposal_sha256':digest(path),'archive_sha256':digest(archive)},ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':
    main()
