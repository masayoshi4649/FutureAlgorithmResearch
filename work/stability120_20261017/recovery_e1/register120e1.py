"""利益カバーを先に外す仕様と、組全体の回収まで残す仕様を分けて登録する。"""

import argparse
import copy
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import plan120 as P
import catalog120e1


HERE=Path(__file__).resolve().parent


def main(auditpath: Path) -> None:
    """
    機能: 逆側が枚数で追い越し利益を維持する仮説を、実金融前に固定・照合・登録する。
    引数: auditpath(Path)は新状態機械の独立人工合格証跡。
    返り値: None。旧96条件の負成績を本仕様の否定根拠として流用しない。
    """
    auditpath=auditpath.resolve()
    audit=P.read(auditpath)
    assert audit['passed'] is True and audit['engine_sha256']==P.digest(HERE/'engine120e1.py')
    sources={(HERE/name).relative_to(P.ROOT).as_posix():P.digest(HERE/name)
        for name in ('register120e1.py','run120e1.py','runtime120e1.py','engine120e1.py','catalog120e1.py')}
    sources[(P.HERE/'catalog120.py').relative_to(P.ROOT).as_posix()]=P.digest(P.HERE/'catalog120.py')
    sources[(P.HERE/'prepare120e1.py').relative_to(P.ROOT).as_posix()]=P.digest(P.HERE/'prepare120e1.py')
    manifest=dict(path=(HERE/'入力目録.json').relative_to(P.ROOT).as_posix(),sha256=P.digest(HERE/'入力目録.json'))
    P.save(HERE/'固定計画.json',dict(sources=sources,input_manifest=manifest,
        specs=catalog120e1.specifications(),artificial_audit=dict(passed=True,
            path=auditpath.relative_to(P.ROOT).as_posix(),sha256=P.digest(auditpath))))
    proposal=copy.deepcopy(P.read(P.HERE/'recovery_d/試行計画.json'))
    proposal.update(id='120e1_十八条件の実行時人工を非空にして金融前に再固定',
        name='上下対称の利益回転と逆側カバー保持',purpose='不具合修正',
        question='反対建玉が元側を追い越し、その利益を個別返済せず残したときに全建玉損失を回収できるか',
        change='初回一枚後のLast極値段階追加を両方向に許す。KEEP/RESCUEは利益玉の個別返済と方向別停止を除き、全玉清算資産から組開始cashを引く組全体純損益で利益追尾。ROTATEは上下対称の個別利益追尾を行い、旧bの追加起動幅を除く。',
        repeat_reason='eは事前登録済みだが、実行前runtimeの人工BBO幅がunitを超えて全modeの新規ゼロとなる空同値guardを発見し、金融未実行0で中止。engine/catalogの経済bodyは同bytesのまま、runtimeの人工だけtick整合したbid=x/ask=x+10とし全caseentries>0を追加して別登録する。ユーザーが逆側追加がカバーして追い越す意図を再確認し、さらに上昇で買い増/反落で利益買いを追尾返済しつつ売り増、その上下対称反復を明確化。旧96条件は組全体カバー保持の直接検証ではなく、Last/新規保護と個別利益追尾の現在条件も異なるため、保持二対照と個別回転一対照を金融前に固定する。',
        compares_to=['120e_逆側カバーを外さず組全体回収まで維持する段階追尾','120d_段階追尾の極値を中値から最終約定値へ変えた対照',
            '120b_段階追尾の建玉保存反例を修正した境界検査付き再測定'],
        evidence=[dict(path=p) for p in (
            'work/stability120_20261017/diagnosis/formal_b/利益玉を回しても不利な在庫が少なくならなかった原因.md',
            'work/stability120_20261017/recovery_d/試行計画.json',auditpath.relative_to(P.ROOT).as_posix())])
    proposal['spec']=dict(
        entry=dict(価格='正常当時Lastの動く極値から3+j単位、買は反発/売は反落。各枠一枚。組の初回予約中は他新規なし。',
            単位='最初の当時BBO中値×0.0125/0.025/0.05%を観測刻みへ四捨五入、場内固定。ATRなし。',
            追加資格='初回一枚fill後は両方向の空き枠で段階追加。旧c/dの同方向利益信用条件は使わない。全正常quoteのLastで極値を更新し、spreadは発注/約定資格だけへ適用する（dCOSTの広気配中の極値凍結とは異なる）。新規spreadと価格保護を満たす場合だけ実約定。'),
        management=dict(方向='買/売両方向を同時保有可。KEEP/RESCUEは勝ちカバーを組回収前に個別利確しない。ROTATEは利益玉だけの個別追尾返済。',
            追加='各方向上限まで。KEEPでは両側上限の同枚数ロックも維持。RESCUEでは飽和時から追ったLast極値の3単位反発/反落で、反対の最悪負け一枚を次気配返済し差分方向を作る。途中実損も同じ組純損益へ残す。'),
        exit=dict(玉別='KEEP/RESCUEは個別返済なし。ROTATEは個別netpeak>0で起動し、peak−当時net>=trail単位かつ当時net>0でその玉を次気配返済。返済枠は現在Lastへresetし再利用。全三管理とも方向別3単位停止なし。',
            組='組開始cashを固定。basket純益=全玉費用後清算equity−開始cash。KEEP/RESCUEは最高が(trail+1)単位以上で起動、trail単位戻りかつ当時組純益>0で全玉返済予約。ROTATEは組追尾なし。次気配で赤字になれば実損として残す。',
            対照='KEEP、飽和時反対一枚削減RESCUE、個別利益回転ROTATEの三管理。trail1/3単位。',
            時刻='新規Day15:00/Night05:20まで、全返済判断15:20/05:40。全返済予約で全新規取消、全flat完了原行では再開禁止。完了原行Lastへ全極値reset、翌原行からその水準の3+j単位到達で新規可。EOF架空約定なし。'),
        allocation=dict(数量='TOPIXミニ片方向10枚・日経マイクロ20枚、全注文一枚。3管理×3幅×2追尾=18新政策×両商品40場=1440新口座。',
            評価='全玉清算時価と未払返済料を含む。既払新規料はcash計上。前組損失を場全体会計から消さない。'),
        costs=copy.deepcopy(proposal['spec']['costs']),
        execution=dict(先後='判断原行より後の最初の正常原行で買ask/売bid、一枚別注文。返済先行、新規の同原行返済なし。',
            資格='元原行順・非逆行価格時計・有限Last/BBO、0<bid<=ask。',
            新規保護='判断/最初次気配のspread<=一単位、買価格<=判断ask+一観測tick、売価格>=判断bid−tick。超過なら一回取消。',
            限界='5秒最悪試験ではない。ラージBBO代理、真受信順・実小型板・待ち順位未観測。'),
        data=dict(input_manifests=[manifest],sessions=P.read(HERE/'入力目録.json')['sessions'],
            入力='b保存80NPZ内quotes5列のみ各一回。旧b/c/d金融の再生0、原市場/現在API/実注文0。'),
        implementation=sources)
    P.save(HERE/'試行計画.json',proposal)
    for command,name in (('check','事前照合の全出力.json'),('register','正式登録の全出力.json')):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(P.MANAGER),command,'--proposal',str(HERE/'試行計画.json')],
            cwd=P.ROOT,capture_output=True,text=True,encoding='utf-8')
        P.save(HERE/name,dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
        print(command,process.returncode,flush=True)
        assert process.returncode==0


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--audit',type=Path,required=True)
    main(parser.parse_args().audit)
