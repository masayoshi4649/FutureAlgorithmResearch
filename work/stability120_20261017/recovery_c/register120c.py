"""不利玉が上限まで残った原因に対し、小試行と合計停止を別登録する。"""

import argparse
import copy
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import plan120 as P
import catalog120c


HERE=Path(__file__).resolve().parent
BASELINE=P.HERE/'root_owned/段階トレーリングと利益玉部分返済の全四十場.json'
BASELINE_SHA='c99743d739c9d24a08088f1b5ebdc78af8285b19e9704773965ea05f13890ce1'


def prepare() -> None:
    """
    機能: 基準の所有結果の価格射影80個を次の入力参照へ固定する。
    引数: なし。
    返り値: None。価格配列・元119入力・原市場・金融再生は0。
    """
    assert P.digest(BASELINE)==BASELINE_SHA
    old=P.read(BASELINE)
    inputs=[dict(path=r['path'],sha256=r['sha256'],symbol=r['symbol'],session=r['session']) for r in old['cache']]
    assert len(inputs)==80
    P.save(HERE/'入力目録.json',dict(inputs=inputs,sessions=old['sessions'],
        baseline=dict(path=BASELINE.relative_to(P.ROOT).as_posix(),sha256=BASELINE_SHA),
        意味='基準3840は保存引用。内包quotes5列だけを新24条件に使い、旧金融は再実行しない。'))


def freeze(auditpath: Path) -> None:
    """
    機能: 新四管理の独立人工と六つの源を、経済再生前に登録する。
    引数: auditpath(Path)は新源の人工監査。
    返り値: None。条件の変更箇所・原因・比較元を保存する。
    """
    auditpath=auditpath.resolve()
    audit=P.read(auditpath)
    assert audit['passed'] is True and audit['engine_sha256']==P.digest(HERE/'engine120c.py')
    sources={(HERE/name).relative_to(P.ROOT).as_posix():P.digest(HERE/name)
        for name in ('register120c.py','run120c.py','runtime120c.py','engine120c.py','catalog120c.py')}
    sources[(P.HERE/'catalog120.py').relative_to(P.ROOT).as_posix()]=P.digest(P.HERE/'catalog120.py')
    manifest=dict(path=(HERE/'入力目録.json').relative_to(P.ROOT).as_posix(),sha256=P.digest(HERE/'入力目録.json'))
    P.save(HERE/'固定計画.json',dict(sources=sources,input_manifest=manifest,
        specs=catalog120c.specifications(),artificial_audit=dict(passed=True,
            path=auditpath.relative_to(P.ROOT).as_posix(),sha256=P.digest(auditpath))))
    proposal=copy.deepcopy(P.read(P.HERE/'試行計画.json'))
    proposal.update(id='120c_小試行と含み益で支える追加及び方向別の合計停止',
        name='不利時の少枚数を直接条件にした段階追尾',purpose='条件比較',
        question='利益玉を回しても不利方向が上限に達した原因を、初回一枚・利益条件追加・方向別固定予算で軽減できるか',
        change='CREDITは初回各方向一枚、同方向清算純益>=3単位×(新規予約数+1)だけ追加、方向別清算純損3単位で全返済。ONEで片方向限定、LIMITで最初次quoteの価格限定、COSTでspread一単位制限を順次追加。',
        repeat_reason='120bは全48共通合計黒字0。HEDGE中間狭追尾TOPの利確純益7,465,388円に対し総損失11,396,780円、うち場末11,395,288円。不利玉が少枚数という仮説が崩れた。元HARDの一枚ごとの停止と異なり、方向別全在庫の損失枠を一枚分へ固定する。00097等の利益後増玉思想と共通するが、新入口・純益予約資格・方向合計停止・再準備が違う。基準3840を再生せず、同じ既知40場の新1920だけ実行する。',
        compares_to=['120b_段階追尾の建玉保存反例を修正した境界検査付き再測定',
            '119c_小試行と当初リスクを増やさない順行追加の対照'],
        evidence=[dict(path=p) for p in (
            BASELINE.relative_to(P.ROOT).as_posix(),
            'work/stability120_20261017/root_owned/四十八条件の場内安定指標.json',
            'work/stability120_20261017/audit_result120b/保存全四十八政策八十入力の注文玉時価の独立会計監査.json',
            'アルゴリズム調査/00097_初回小枚数と利益で支える増玉の安定性/README.md',
            auditpath.relative_to(P.ROOT).as_posix())])
    proposal['spec']['implementation']=sources
    proposal['spec']['data']=dict(input_manifests=[manifest],sessions=P.read(HERE/'入力目録.json')['sessions'],
        入力='基準b保存80NPZ内の同一quotes5列を各一読、基準金融再生0、原市場0。全40は既知開発。')
    proposal['spec']['entry']['追加資格']='CREDIT以後は方向ごと初回1枚。予約済数量を消費済リスクへ数え、既存の清算純益>=3単位×(予約済+1)を追加に要求。'
    proposal['spec']['management']=dict(方向='CREDITは両方向可、ONE以後は反対の保有又は新規予約中に入らず待機極値を現中値へ戻す。全返済後は全空き枠を現中値から再準備。',
        追加='含み益は当時評価であり将来損失の保証ではない。逆行中と方向返済予約中は追加しない。')
    proposal['spec']['exit']['方向別停止']='一枚個別ではなく同方向全残玉の費用後清算net<=-3単位で全返済。新規予約を取消し、次正常気配の実約定を使う。場中の複数回損切り合計は3単位を超え得る。'
    proposal['spec']['allocation']['数量']='新4管理×3幅×2追尾=24、両商品40場の1920口座。比較上限10mini/20micro、初回1枚。'
    proposal['spec']['execution']['新規保護']='LIMIT以後は判断ask/bid±観測一刻みを最初次正常気配だけで審査、超過なら失効。COSTは判断及びfillのspread<=1単位。返済に価格限定を使わず値飛び損失を記録。'
    P.save(HERE/'試行計画.json',proposal)
    for command,name in (('check','事前照合の全出力.json'),('register','正式登録の全出力.json')):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(P.MANAGER),command,'--proposal',str(HERE/'試行計画.json')],
            cwd=P.ROOT,capture_output=True,text=True,encoding='utf-8')
        P.save(HERE/name,dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
        print(command,process.returncode,flush=True)
        assert process.returncode==0


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('prepare','freeze'))
    parser.add_argument('--audit',type=Path)
    args=parser.parse_args()
    if args.command=='prepare':
        prepare()
    else:
        assert args.audit
        freeze(args.audit)
