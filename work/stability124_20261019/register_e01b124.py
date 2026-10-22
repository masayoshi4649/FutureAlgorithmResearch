"""CSV読取終端だけを資格表示するE01修正版を、初回停止と分けて登録する。"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from common124 import HERE,ROOT,SCENE,read,save,sha

TRIAL='124b_追加CSVの排他的終端を維持した少額E01再接続'
MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def main(artpath: Path) -> None:
    """
    機能: 入力終端以後だけを除外する修正を旧経済の変更と分けて固定・登録する。
    引数: artpath(Path)は修正前後の範囲と全経済人工の合格証跡。
    返り値: None。金融実行はこの登録完了後の別工程だけで行う。
    """
    artificial=read(artpath);assert artificial['passed']
    sources=dict(artificial['sources'])
    for path in [HERE/'common124.py',Path(__file__).resolve()]:sources[path.relative_to(ROOT).as_posix()]=sha(path)
    for p,h in sources.items():assert sha(ROOT/p)==h,p
    origin=read(HERE/'固定計画.json');inputref=origin['input_manifest']
    assert sha(ROOT/inputref['path'])==inputref['sha256']
    fixed=dict(sources=sources,input_manifest=inputref,e01_artificial=dict(path=artpath.relative_to(ROOT).as_posix(),sha256=sha(artpath)))
    save(HERE/'固定計画_E01b.json',fixed)
    proposal=dict(id=TRIAL,name='CSVの場末追加行を旧範囲へ制限するE01再接続',purpose='不具合修正',
        question='旧15:40排他範囲を保ったconsumer表示で、追加一場の旧固定少額E01二商品を機械的に検証できるか。',
        change='新CSVに旧消費終端15:40以後の行が追加されたため初回は金融0で停止。原本と旧sourceは維持し、CSVの合法終端行だけconsumer viewで除外・記録する。',
        repeat_reason='124の格子190会計とは別。E01初回はstage入力資格で停止し金融0。経済source変更なしで入力範囲を旧条件へ合わせ、別源・別登録として追加2会計を行う。',
        compares_to=['124_追加一場の凍結評価と前完了場IV固定十二条件','119h_少額E01の時計逆行行除外による入力停止修正'],
        evidence=[dict(path=(HERE/'e01/金融前CSV資格停止.json').relative_to(ROOT).as_posix()),fixed['e01_artificial']],
        spec=dict(entry=dict(固定='旧TOPIX E01_ADAPT_G50_ADAPT75_P1、NK E01_ADAPT_G25_ADAPT100_P1。数値経済同bytes。'),
            management=dict(継承='旧ATR/親目標・減量・支持撤回と損失停止を変更しない。CSV終端以後を新規・指標へ逆流させない。'),
            exit=dict(継承='旧finish=True、全実玉場内返済。未清算は成功に数えない。'),
            allocation=dict(継承='TOPIXミニ片方向10、NKマイクロ片方向20を上限とする旧リスク予算。固定少額設定で実使用は別記。'),
            costs=dict(継承='TOPIXmini41.8、NKmicro11円/片道枚。各注文合計で円未満切捨て。気配差も会計に含む。'),
            execution=dict(継承='判断後正常BBO・指値不利許容・FAKを旧同条件維持。真受信順・実小型板は未観測。'),
            data=dict(input_manifests=[inputref],sessions=[SCENE],原本='124が一回複写した6本のみ。旧原本再読0。',
                CSV資格='全行のTZ付き有限時刻・単調性・開始前拒否を維持。合法な>=endだけ除外し元row/timeを保存。Dayのend15:40は排他的。',
                旧引用='旧40完成会計はSHA d0f1f86cb955a2da7016f0a33f6ff097eb64edb14068e8d0a0b4278aebca963bから表示で引用。再金融0。'),
            implementation=sources))
    save(HERE/'試行計画_E01b.json',proposal)
    for command,name in [('check','事前照合_E01b全出力.json'),('register','正式登録_E01b全出力.json')]:
        p=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),command,'--proposal',str(HERE/'試行計画_E01b.json')],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/name,dict(終了コード=p.returncode,stdout=p.stdout,stderr=p.stderr));print(command,p.returncode,flush=True)
        assert p.returncode==0,p.stderr[-1000:]


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--artificial',type=Path,required=True)
    main(parser.parse_args().artificial.resolve())
