"""段階追尾の観測基準だけを中値から最終約定値へ変える対照を固定する。"""

import argparse
import copy
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import plan120 as P
import catalog120d


HERE=Path(__file__).resolve().parent


def main(auditpath: Path) -> None:
    """
    機能: 価格変動と気配幅変動を分離する最終対照を事前登録する。
    引数: auditpath(Path)は参照価格変更の独立人工監査。
    返り値: None。実入力は基準bの同一価格配列で、旧金融を再生しない。
    """
    auditpath=auditpath.resolve()
    audit=P.read(auditpath)
    assert audit['passed'] is True and audit['engine_sha256']==P.digest(HERE/'engine120d.py')
    sources={(HERE/name).relative_to(P.ROOT).as_posix():P.digest(HERE/name)
        for name in ('register120d.py','run120d.py','runtime120d.py','engine120d.py','catalog120d.py')}
    for name in ('catalog120.py','prepare120d.py'):
        sources[(P.HERE/name).relative_to(P.ROOT).as_posix()]=P.digest(P.HERE/name)
    manifest=dict(path=(HERE/'入力目録.json').relative_to(P.ROOT).as_posix(),sha256=P.digest(HERE/'入力目録.json'))
    P.save(HERE/'固定計画.json',dict(sources=sources,input_manifest=manifest,
        specs=catalog120d.specifications(),artificial_audit=dict(passed=True,
            path=auditpath.relative_to(P.ROOT).as_posix(),sha256=P.digest(auditpath))))
    proposal=copy.deepcopy(P.read(P.HERE/'recovery_c/試行計画.json'))
    proposal.update(id='120d_段階追尾の極値を中値から最終約定値へ変えた対照',
        name='最終約定値で追尾する利益条件付き追加',purpose='条件比較',
        question='中値の気配幅変動と実約定値変動を分け、同じ数量・出口なら収支が変わるか',
        change='新規待機の極値、再準備、上げ下げ判定だけLastへ変更。単位尺度はcと同じ最初の当時中値、数量・清算評価・出口・価格上限・実BBOfill・feesは同じ。',
        repeat_reason='基準bのTOP10/2Night21:29:50は中値4138→4124.5で売判断、Last4137→4139.5は上昇。次bid4110売の初期費用29582円だった。広気配の排除と別に、ユーザー案の下値/上値を実約定値で監視する対照を追加する。c24の結果を見たパラメータ変更ではなく、基準b診断からの単一部品差。全40既知、新しい独立標本0。',
        compares_to=['120c_小試行と含み益で支える追加及び方向別の合計停止',
            '120b_段階追尾の建玉保存反例を修正した境界検査付き再測定'],
        evidence=[dict(path=p) for p in (
            'work/stability120_20261017/diagnosis/formal_b/利益玉を回しても不利な在庫が少なくならなかった原因.md',
            'work/stability120_20261017/recovery_c/試行計画.json',
            auditpath.relative_to(P.ROOT).as_posix())])
    proposal['spec']['implementation']=sources
    proposal['spec']['data']['input_manifests']=[manifest]
    proposal['spec']['entry']['価格']='保存当該行のLastで極値を追い、安値+3/4/5…単位で買い、高値-同幅で売り。上昇更新だけ買い、下落更新だけ売り。'
    proposal['spec']['entry']['単位']='cから変えず、最初の当時BBO中値×0.0125/0.025/0.05%を観測刻みへ四捨五入。場中固定、ATRなし。'
    proposal['spec']['management']['方向']=proposal['spec']['management']['方向'].replace('中値','最終約定値')
    proposal['spec']['allocation']['数量']='新規の参照価格だけを変えた24条件×両商品40場=1920新口座。b/c保存会計を新金融へ足さない。'
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
