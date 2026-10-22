"""Last比較完了後に、実建値予算を持つ次原行ＢＢＯ段階だけを別登録する。"""

import argparse
from pathlib import Path
import subprocess
import sys

from common_bbo126 import HERE,TASK,ROOT,TRIAL,LAST_RESULT,BASELINE,PREPARED,sha,read,save,sources


sys.path.insert(0,str(TASK/'design'))
from catalog126 import catalog

MANAGER = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def main(artificial: Path, *, plan_only: bool = False) -> None:
    """
    機能: 独立人工・完成Last・元注文・全場packetを拘束して別比較を登録する。
    引数: artificial(Path)は独立純人工、plan_only(bool)は提案保存だけの選択。
    返り値: None。金融は行わず、条件の事後選択を持ち込まない。
    """
    proof = read(artificial)
    assert proof.get('passed',proof.get('全合格',False))
    current = sources()
    numerical = [HERE/'core126.py',HERE/'bbo_order_kernel126.py',HERE/'policy_bbo126.py',
                 TASK/'engine/policy126.py',TASK/'design/catalog126.py']
    for path in numerical:
        relative = path.relative_to(ROOT).as_posix()
        assert proof['sources'][relative] == current[relative], ('古い人工源',relative)
    last,baseline,prepared = read(LAST_RESULT),read(BASELINE),read(PREPARED)
    assert last['passed'] and prepared['passed'] and len(prepared['packets']) == 41
    assert len(last['rows']) == 1312 and last['new_financial_accounts'] == 1252
    old = {(r['session'],r['symbol']) for r in baseline['rows']}
    assert len(old) == 60
    reference = { (r['session'],r['symbol']):r for r in last['cache'] }
    scenes = prepared['sessions']
    assert scenes == last['sessions'] and len(scenes) == 41
    metadata = [dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),kind='metadata')
        for p in (artificial,LAST_RESULT,BASELINE,PREPARED,TASK/'design/原版E01の十六条件と単因子対照.json')]
    original = baseline['cache']
    paper_caches = [dict(path=original['path'],sha256=original['sha256'],kind='paper_cache',scope='旧三十場原版')]
    for scene in scenes:
        for symbol in ('TOPIX','NK225'):
            if (scene,symbol) in old: continue
            item = reference[scene,symbol]
            paper_caches.append(dict(path=item['path'],sha256=item['sha256'],kind='paper_cache',
                                     session=scene,symbol=symbol,scope='追加十一場原版'))
    assert len(paper_caches) == 23
    packets = [dict(path=p['path'],sha256=p['sha256'],kind='market_packet',session=p['session'])
               for p in prepared['packets']]
    fixed = dict(sources=current,bindings=metadata+paper_caches+packets,
        input=dict(path=PREPARED.relative_to(ROOT).as_posix(),sha256=sha(PREPARED)),
        last=dict(path=LAST_RESULT.relative_to(ROOT).as_posix(),sha256=sha(LAST_RESULT)),
        baseline=dict(path=BASELINE.relative_to(ROOT).as_posix(),sha256=sha(BASELINE)),
        artificial=dict(path=artificial.relative_to(ROOT).as_posix(),sha256=sha(artificial)),
        paper_caches=paper_caches,packets=packets,sessions=scenes,specs=catalog(),
        counts=dict(financial_accounts=1312,original_market_reads=0,API=0,real_orders=0),
        execution='原Last原版の公開通知、次正常原行BBO、実建値一ATR、元出口影維持。未来価格を発注行へ挿入しない。',
        preflight='全82原版通知に実予算理由32なしを新金融前に確認。不適合なら金融0で停止。')
    save(HERE/'固定計画.json',fixed)
    specification = dict(
        entry=dict(規則='原E01 E00のLast紙上新規通知を引用。待機中の影撤回は取消、既予約の正常行約定を当行の新情報で遡及取消しない。'),
        management=dict(条件目録=metadata[-1],規則='初回5/10、元の紙上半減・部分利確通知と実玉を別管理。P/A/Lを実組損益・実返済勝敗で判定し、全16条件を同時比較。'),
        exit=dict(規則='元Last紙上出口影0.75ATRと段階出口を維持。元実組1ATR予算を実建値とBBO清算で計算。新設P床とL場予算は次正常原行返済。新0.75ATR実stopは追加しない。'),
        allocation=dict(規則='TOPIXミニ初回5枚/片方向上限10、NKマイクロ初回10枚/上限20。増玉/復元なし。返済待ちの実保有を次親へ再利用しない。'),
        costs=dict(規則='手数料0。BBO横断と次原行の価格悪化は実会計へ反映。ラージ気配代理で実ミニ/マイクロ待ち順位・部分約定は未再現。'),
        execution=dict(規則=fixed['execution'],順序='先に既予約実約定、その後当行紙上通知と実予算判定。紙上部分返済待機は新設実予算の残返済より優先。'),
        data=dict(input_manifests=metadata+paper_caches+[metadata[3]],sessions=scenes,
            reuse='保存原版E00通知は全41を再利用。新金融は別約定の16×82=1312のみ。packet41/元注文cache23を各一読。原本と現在APIは0。'),
        implementation=fixed['sources'])
    proposal = dict(id=TRIAL,name='原版E01のLast影と実約定を分けた次原行BBO十六比較',purpose='条件比較',
        question='原Last比較の利益が実BBO次行約定と実建値一ATR予算でも維持され、P/A/Lの改善は両商品で残るか。',
        change='LastをBBOへ置換せず原版通知を固定引用。実玉のみ次正常原行で建て、実建値予算と実組P/A/Lから返済と再参加を判定する。',
        repeat_reason='原版Lastモデルの仮想粗利益と実行可能価格の混同を避ける別約定比較。旧00103のGU気配核を参考にするが、元mask0・費用0・元実予算・新三部品を別実装へ接続する。未知相場の独立有効性標本ではない。',
        compares_to=['126_原版E01の二市場利益保護と損失後再参加及び場損失の十六対照'],evidence=metadata,spec=specification)
    save(HERE/'試行計画.json',proposal)
    if plan_only:
        print('提案保存のみ・登録0・金融0',flush=True)
        return
    for command,name in (('check','事前照合の全出力.json'),('register','正式登録の全出力.json')):
        proc = subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),command,'--proposal',str(HERE/'試行計画.json')],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/name,dict(終了コード=proc.returncode,stdout=proc.stdout,stderr=proc.stderr))
        print(command,proc.returncode,flush=True)
        assert proc.returncode == 0,proc.stderr[-1200:]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--artificial',type=Path,required=True)
    parser.add_argument('--plan-only',action='store_true')
    args = parser.parse_args()
    main(args.artificial.resolve(),plan_only=args.plan_only)
