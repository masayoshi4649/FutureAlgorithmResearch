"""十九間隔条件のうち保存基準一つを引用し、新十八条件を金融前に固定する。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from catalog123 import specifications

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
TRIAL='123_TOPIX途中利確なしで初回距離と新規段間隔を比較'


def read(path: Path) -> dict:
    """
    機能: 保存した小さいUTF-8 JSONを読む。
    引数: path(Path)は既存ファイル。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 計画・源・証跡の同一性を求める。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path,value: dict) -> None:
    """
    機能: 固定内容と会計を新規保存する。
    引数: path(Path)は未使用先、value(dict)はJSON互換内容。
    返り値: None。既存結果を上書きしない。
    """
    assert not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main(auditpath: Path) -> None:
    """
    機能: 独立した期待線人工と保存入力・基準会計を拘束して新比較を登録する。
    引数: auditpath(Path)は独立純人工合格証跡。
    返り値: None。実市場の再生は登録後だけ行う。
    """
    auditpath=auditpath.resolve();audit=read(auditpath)
    assert audit['passed'] and audit['engine_sha256']==sha(HERE/'engine123.py')
    assert audit['core_sha256']==sha(HERE/'core123.py')
    manifestpath=ROOT/'work/stability122_20261017/coverage/所有気配入力目録.json'
    assert sha(manifestpath)=='2363809654f49c8986f5c8d5cc71ae0715821352a0e04120e32aac13a27bdde7'
    manifest=dict(path=manifestpath.relative_to(ROOT).as_posix(),sha256=sha(manifestpath))
    oldpath=ROOT/'work/stability122_20261017/途中利確なしと引け一括の全四十場.json'
    assert sha(oldpath)=='ea3632b2e7bf2e9eb3e73addfede7f87deda0069efb30e4a3fd2647550dbab72'
    old=read(oldpath);rows=[r for r in old['runs'] if r['method']=='HOLD_CLOSE_6M'];assert len(rows)==40
    baseline=dict(path=oldpath.relative_to(ROOT).as_posix(),sha256=sha(oldpath),rows=rows,
        source_method='HOLD_CLOSE_6M',mapped_method='I3_G3')
    sources={(HERE/n).relative_to(ROOT).as_posix():sha(HERE/n) for n in
        ['core123.py','engine123.py','catalog123.py','runtime123.py','register123.py','run123.py','prepare123.py']}
    source='work/stability120_20261017/catalog120.py';sources[source]=sha(ROOT/source)
    binding=dict(path=auditpath.relative_to(ROOT).as_posix(),sha256=sha(auditpath),passed=True)
    specs=specifications();assert len(specs)==19 and sum(not s['reused'] for s in specs)==18
    save(HERE/'固定計画.json',dict(sources=sources,input_manifest=manifest,baseline=baseline,
        specs=specs,artificial_audit=binding))

    # ----------------------------------------
    # 幅以外の資格と終端を固定し、数量の差も含めた比較として登録する。
    proposal=dict(id=TRIAL,name='途中利確なしの初回距離と新規間隔',purpose='条件比較',
        question='同じ引け代理・費用で段間隔を変更すると、各場の安定性は改善するか。枚数減だけによる見かけの改善ではないか。',
        change='gap1/2/3/4/5/6/8/10/12/15pt、初回3固定と初回gapの二系統。3/3の重複は統合して保存40会計再利用。残る十八条件だけ測る。',
        repeat_reason='ユーザーが途中利確なし引け一括を確認後に間隔変更を依頼。旧120は入口単位とspread資格等が連動、121は途中利確あり。今回と完全一致する保存結果は122の3/3だけで、単なる既存幅の再集計ではない。全過去未整理範囲に重複なしとは宣言しない。',
        compares_to=['122_TOPIX途中利確ゼロと引け前六分代理一括精算'],
        evidence=[dict(path=p) for p in [binding['path'],
            'work/stability123_20261017/audit/同一引け代理での間隔探索と統計分母の事前照合.json',
            'アルゴリズム調査/共通/知見台帳/入口.md','アルゴリズム調査/共通/知見台帳/出口.md',
            'アルゴリズム調査/共通/知見台帳/継続.md','アルゴリズム調査/共通/知見台帳/売買の工夫.md']],
        spec=dict(
            entry=dict(価格='正常Lastの動く安値+(initial+rank*gap)ptで買い、高値−同幅で売り。一枚ずつ。',
                系統='initial=3固定、又はinitial=gap。gapは1/2/3/4/5/6/8/10/12/15。最初は一枚だけ予約し実約定後に他枠を許す。',
                資格='unit1pt固定。発注/約定時spread<=1pt、買<=判断ask+0.5pt/売>=判断bid−0.5ptの一回次正常原行判定。gapへ資格幅を連動しない。'),
            management=dict(保持='途中利確・損切りなし。保有建値固定。利確後再起算は発生しない。新規Day15:00/Night05:20締切。'),
            exit=dict(時刻='Day15:45/Night06:00予定。T−360〜Tの最後正常BBOをユーザー許可の終値代理に使用。',
                分離='通常ordersは新規だけ。proxy_lotsへ全UIDの終端会計を一回ずつ保存。参照実時計/原行と予定時刻を分ける。途中へ終端価格を逆流させず窓内無しは未測定。'),
            allocation=dict(数量='TOPIXミニ片方向最大10枚、全注文一枚。19uniqueうち18新×40場=720会計、保存基準40会計引用。',
                指標='全40場黒字数・中央値・最大赤字を優先。無取引と活動中net0を分離。上位3黒字除外net、総/平均枚数、平均黒字、全40平均、net/累計枚数も表示。'),
            costs=dict(料金='片道41.8円/枚を別注文で円未満切捨て41円。往復82円。'),
            execution=dict(新規='判断より後の最初正常原行の買ask/売bid。既存と同じ時計・原行資格。',
                終端='買bid/売askの代理精算。Last終端評価は同じ玉の感応度で新条件や実約定としない。実ミニ板・待ち順位・真受信順は未観測。'),
            data=dict(input_manifests=[manifest],sessions=old['sessions'],入力='122範囲監査の所有quotes五列40本を再利用。元板/API/既金融再生0。同じ既知40場。'),
            implementation=sources))
    save(HERE/'試行計画.json',proposal)
    for command,name in [('check','事前照合の全出力.json'),('register','正式登録の全出力.json')]:
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),command,'--proposal',str(HERE/'試行計画.json')],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/name,dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
        print(command,process.returncode,flush=True);assert process.returncode==0,process.stderr[-1000:]


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--audit',type=Path,required=True)
    main(parser.parse_args().audit)
