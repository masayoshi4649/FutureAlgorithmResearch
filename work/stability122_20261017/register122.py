"""利確なしの一括返済と六分代理の契約を実データ再生前に登録する。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
TRIAL='122_TOPIX途中利確ゼロと引け前六分代理一括精算'


def read(path: Path) -> dict:
    """
    機能: UTF-8の保存JSONを読む。
    引数: path(Path)は既存の計画又は証跡。
    返り値: dictは保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 読み取り対象の内容を識別する。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path,value: dict) -> None:
    """
    機能: 計画と会計を上書きせず保存する。
    引数: path(Path)は未使用先、value(dict)は有限値又はNoneのJSON互換内容。
    返り値: None。
    """
    assert not path.exists(),path
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def specifications() -> list[dict]:
    """
    機能: 途中利確なしの通常時刻対照と引け代理を事前固定する。
    引数: なし。
    返り値: list[dict]は二つの終了方式。
    """
    return [dict(id='HOLD_EARLY',kind='EARLY',name='途中利確なし・15:20／05:40通常返済'),
        dict(id='HOLD_CLOSE_6M',kind='CLOSE_PROXY',name='途中利確なし・15:45／06:00一括代理精算')]


def main(auditpath: Path) -> None:
    """
    機能: 人工監査と所有入力目録へ拘束して新二条件を照合登録する。
    引数: auditpath(Path)は独立した純人工合格証跡。
    返り値: None。登録完了前に実市場の再生をしない。
    """
    auditpath=auditpath.resolve();audit=read(auditpath)
    assert audit['passed'] and audit['engine_sha256']==sha(HERE/'engine122.py')
    manifestpath=HERE/'coverage/所有気配入力目録.json'
    assert sha(manifestpath)=='2363809654f49c8986f5c8d5cc71ae0715821352a0e04120e32aac13a27bdde7'
    manifest=dict(path=manifestpath.relative_to(ROOT).as_posix(),sha256=sha(manifestpath))
    meta=read(manifestpath);assert len(meta['inputs'])==len(meta['sessions'])==40
    baselinepath=ROOT/'work/stability121_20261017/三ポイント間隔と五ポイント追尾の全四十場.json'
    assert sha(baselinepath)=='ade79de8165fefe68d6f6be861b38f991fc650bb6b658e70329cf667b9bacd1c'
    old=read(baselinepath)
    baseline=dict(path=baselinepath.relative_to(ROOT).as_posix(),sha256=sha(baselinepath),
        rows=[r for r in old['runs'] if r['method']=='G3_T5_RESET'])
    assert len(baseline['rows'])==40
    sources={(HERE/n).relative_to(ROOT).as_posix():sha(HERE/n) for n in ['engine122.py','runtime122.py','register122.py','run122.py']}
    for name in ['work/stability121_20261017/engine121.py','work/stability120_20261017/catalog120.py']:
        sources[name]=sha(ROOT/name)
    auditref=dict(path=auditpath.relative_to(ROOT).as_posix(),sha256=sha(auditpath),passed=True)
    save(HERE/'固定計画.json',dict(sources=sources,input_manifest=manifest,specs=specifications(),
        artificial_audit=auditref,baseline=baseline))

    # ----------------------------------------
    # 終値の代用許可を途中の入口や通常約定へ広げない仕様で登録する。
    proposal=dict(id=TRIAL,name='TOPIXの途中利確なしと引け一括精算',purpose='条件比較',
        question='勝ち玉を途中で外さず引けまで全玉を保持すると、同じ三ポイント段階新規の場内収支は改善するか',
        change='旧G3_T5_RESETの途中利益追尾を完全停止。通常15:20/05:40対照と、15:45/06:00の直前六分以内BBOを終値代理とする一括精算を比較する。',
        repeat_reason='ユーザーが途中利確一切なし、Day15:45/Night06:00一括精算を指定し、終値が不明なら直前六分の値でよいと明示。旧ONCEにも個別利確、KEEPにも組全体利確があり今回とは異なる。所有入力40場は引け同時刻0で直前301〜359秒の最終有効BBOあり。代理精算の結果は実引け約定の成績と区別する。',
        compares_to=['121_TOPIX三ポイント段間隔と五ポイント追尾及び利確後の再起算',
            '120e1_十八条件の実行時人工を非空にして金融前に再固定'],
        evidence=[dict(path=p) for p in [auditref['path'],
            'work/stability122_20261017/audit/途中返済なし三ポイント段階新規と終端一括の既試行照合.json',
            'work/stability122_20261017/coverage/TOPIX四十場の引け前六分と原板末尾.json']],
        spec=dict(
            entry=dict(条件='正常Lastの動く安値+3/6/9…ptで一枚ずつ買い、高値−同幅で売り。初回予約中は一枚だけ。',
                資格='既存121と同じ気配差<=1pt、判断ask+0.5pt以内の買/判断bid−0.5pt以内の売を次正常原行で一回判定。'),
            management=dict(保持='途中利確・損切り・組清算をしない。実装は既存の個別追尾を正の無限大幅で停止。利確後再起算は発生しない。',
                締切='既存比較と同じDay15:00/Night05:20で新規停止。既保有玉の建値固定。'),
            exit=dict(対照='HOLD_EARLYは15:20/05:40判断の次正常原行で通常BBO返済。',
                提案='HOLD_CLOSE_6Mは15:45/06:00まで保持する仮定。終端時点に既知の正常受理原行からT-360<=時刻<=Tの最後を採用し、買bid/売askの代理精算。',
                分離='代理玉は別proxy_lots台帳。参照実時刻/原行と予定精算時刻の両方を保存し、次原行約定や実引け価格へ偽装しない。窓内無しは未測定。終端値は新規判断へ使わない。'),
            allocation=dict(数量='TOPIXミニ片方向上限10枚、全新規一枚。新二条件×同じ既知40場=80会計。旧基準40会計は再利用。'),
            costs=dict(手数料='片道41.8円を一枚一注文で円未満切捨て41円、往復82円。BBO気配差は約定価格へ含む。'),
            execution=dict(通常='判断より後の最初正常原行、買ask/売bid、非逆行価格時計・有限Last/BBO。',
                代理='終端BBOで評価する価格代用仮定。実行可能な引け気配や実ミニ板・待ち順位を証明しない。保存入力最後と原板同秒末尾を差し替えない。'),
            data=dict(input_manifests=[manifest],sessions=meta['sessions'],
                入力='範囲監査が各一読保全したquotes五列40本。金融工程の元板/API/旧金融再生0。範囲確認だけ9/24元板末尾2MiB一読。'),
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
