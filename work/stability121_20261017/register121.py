"""ユーザー指定の段間隔・利確幅・段数再起算を実金融前に照合登録する。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from catalog121 import specifications

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
TRIAL='121_TOPIX三ポイント段間隔と五ポイント追尾及び利確後の再起算'


def read(path: Path) -> dict:
    """
    機能: 小さい固定JSONを読み取る。
    引数: path(Path)は既存UTF-8 JSON。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 入力・源・証跡の同一性を識別する。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path,value: dict) -> None:
    """
    機能: 固定計画と記録を新規保存する。
    引数: path(Path)は未使用先、value(dict)はJSON互換内容。
    返り値: None。既存計画を上書きしない。
    """
    assert not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main(auditpath: Path) -> None:
    """
    機能: 独立人工合格と既存入力目録に拘束して条件比較を登録する。
    引数: auditpath(Path)は実市場を含まない独立人工監査。
    返り値: None。登録完了まで金融を実行しない。
    """
    auditpath=auditpath.resolve()
    audit=read(auditpath)
    assert audit['passed'] and audit['engine_sha256']==sha(HERE/'engine121.py')

    # ----------------------------------------
    # 既存四十場の基準と再利用する気配配列の参照だけを固定する。
    baseline=ROOT/'work/stability120_20261017/root_owned_e/カバーを維持する組全体追尾と全四十場.json'
    assert sha(baseline)=='63766637c69f8572465b1ec3cc3c735e8eef234c1657b3ca0542bd3b6fa9f2ba'
    old=read(baseline)
    rows=[r for r in old['runs'] if r['symbol']=='TOPIX' and r['method']=='ROTATE_S2_T1']
    assert len(rows)==40 and all(r['step']==1 for r in rows)
    parent=read(ROOT/'work/stability120_20261017/recovery_e1/入力目録.json')
    inputs=[r for r in parent['inputs'] if r['symbol']=='TOPIX']
    assert len(inputs)==40 and {r['session'] for r in inputs}==set(parent['sessions'])
    save(HERE/'入力目録.json',dict(inputs=inputs,sessions=parent['sessions'],baseline=dict(
        path=baseline.relative_to(ROOT).as_posix(),sha256=sha(baseline),method='ROTATE_S2_T1',
        rows=rows,全四十場step固定1確認=True),original_market_reads=0))
    sources={(HERE/name).relative_to(ROOT).as_posix():sha(HERE/name) for name in
        ('engine121.py','catalog121.py','runtime121.py','register121.py','run121.py','prepare_engine121.py')}
    prior=ROOT/'work/stability120_20261017/catalog120.py'
    sources[prior.relative_to(ROOT).as_posix()]=sha(prior)
    manifest=dict(path=(HERE/'入力目録.json').relative_to(ROOT).as_posix(),sha256=sha(HERE/'入力目録.json'))
    auditref=dict(path=auditpath.relative_to(ROOT).as_posix(),sha256=sha(auditpath),passed=True)
    save(HERE/'固定計画.json',dict(sources=sources,input_manifest=manifest,artificial_audit=auditref,
        specs=specifications(),baseline=read(HERE/'入力目録.json')['baseline']))

    # ----------------------------------------
    # 入口から約定までの差分を事前登録し、出力全体を保全する。
    proposal=dict(id=TRIAL,name='TOPIXの三ポイント段階新規と五ポイント利益追尾',purpose='条件比較',
        question='1pt個別追尾を5ptへ拡げ、新規を3/6/9ptに離し利確後の次新規を3ptへ戻すと、カバー保持と場内安定性が改善するか',
        change='保存済み3+j/1ptを再利用。新3+j/5pt、新3+3j/5pt、新3+3j/5ptで利確方向全空き段をゼロへ再起算の三対照。',
        repeat_reason='ユーザーがTOPIXの日内30〜100pt程度の動きに対し1pt追尾が狭すぎると指摘し、3/6/9pt追加と5pt戻りで利益玉返済、利確後3ptからの再起算を明示。旧e1は固定枠3+jかつ追尾1/3単位で全空き段再起算はない。確認した関連範囲の既存結果では代用できない。全過去未整理範囲の重複不存在とはしない。',
        compares_to=['120e1_十八条件の実行時人工を非空にして金融前に再固定'],
        evidence=[dict(path=p) for p in [auditref['path'],
            'work/stability121_20261017/audit/既存段階追尾と三間隔五ポイント及び再起算の照合.json',
            'アルゴリズム調査/共通/知見台帳/入口.md','アルゴリズム調査/共通/知見台帳/継続.md',
            'アルゴリズム調査/共通/知見台帳/出口.md','アルゴリズム調査/共通/知見台帳/売買の工夫.md']],
        spec=dict(
            entry=dict(条件='正常Lastの動く安値+(3+rank*spacing)ptで買い、高値−同幅で売り。一枚ずつ。第一段3pt、間隔1pt又は3pt。',
                未約定='新安値/新高値では空き枠だけ極値追従。保有玉建値固定。初回一枚約定まで他新規予約なし。'),
            management=dict(対照='固定枠再利用と利確後の方向別全空き段再起算。全正常行で未約定極値更新。',
                再起算='reason1返済の実約定純益が正ならその方向だけ新規予約取消、空き段を現在Lastの3/6/9…ptへ再割当。同原行の同方向新規禁止。既存玉・既返済予約・反対方向不変。'),
            exit=dict(利益追尾='玉別netpeak>0後、最高純益から5pt分戻りかつ現在純益>0で次気配返済。実約定が赤字なら損失計上し再起算しない。',
                損失='独立損切りなし。負け玉も場末強制返済。Day新規15:00/全返済判断15:20、Night05:20/05:40。EOF清算なし。'),
            allocation=dict(銘柄='TOPIXミニだけ、片方向最大10枚。全注文1枚。新3条件×同一既知40場=120会計。旧40会計は再利用。'),
            costs=dict(手数料='立会41.8円/片道一枚を一注文ずつ円未満切捨て=41円、往復82円。'),
            execution=dict(約定='判断より後の最初正常原行。買ask/売bid。返済先行。ラージ板によるミニ代理。',
                保護='発注/新規約定ともspread<=1pt固定。買は判断ask+0.5pt以内、売は判断bid−0.5pt以内。最初次行で未達なら取消。',
                限界='真受信順・ミニ板・待ち順位未観測。5秒最悪試験はしない。'),
            data=dict(input_manifests=[manifest],sessions=parent['sessions'],
                入力='保存済みTOPIX40NPZのquote5列だけ各一読。旧金融再生0、原板/API/実注文0。'),
            implementation=sources))
    save(HERE/'試行計画.json',proposal)
    for command,name in [('check','事前照合の全出力.json'),('register','正式登録の全出力.json')]:
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),command,'--proposal',str(HERE/'試行計画.json')],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/name,dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
        print(command,process.returncode,flush=True)
        assert process.returncode==0,process.stderr[-1000:]


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--audit',type=Path,required=True)
    main(parser.parse_args().audit)
