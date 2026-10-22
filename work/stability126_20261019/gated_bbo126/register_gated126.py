"""Ｇ・ＧＵと早期利益床及び公開気配予算を金融前に別登録する。"""

import argparse
from pathlib import Path
import subprocess
import sys

from common_gated126 import HERE,TASK,ROOT,TRIAL,PREPARED,LAST_RESULT,BASELINE,PREVIOUS,GATED,sha,read,save,sources
from catalog126g import catalog,specification

MANAGER = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def reference(path: Path, kind: str = 'metadata') -> dict:
    """
    機能: 明示資料の参照と指紋を作る。
    引数: path(Path)、kind(str)は位置と資料種別。
    返り値: dictはpath/sha256/kind。
    """
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=sha(path),kind=kind)


def main(artificial: Path, *, plan_only: bool = False) -> None:
    """
    機能: 独立人工、完成入口、旧ＢＢＯ結果、同値引用規則を固定し比較を登録する。
    引数: artificial(Path)は新フィルタと低閾値の独立人工、plan_only(bool)は提案保存選択。
    返り値: None。金融は親の別コマンドだけで開始する。
    """
    proof,current = read(artificial),sources()
    assert proof.get('passed',proof.get('全合格',False))
    required = [HERE/'catalog126g.py',HERE/'feed_filter126.py',TASK/'engine/bbo_next/core126.py',
                TASK/'engine/bbo_next/bbo_order_kernel126.py',TASK/'engine/bbo_next/policy_bbo126.py',
                TASK/'engine/policy126.py',TASK/'design/catalog126.py']
    for path in required:
        key = path.relative_to(ROOT).as_posix()
        assert proof['sources'][key] == current[key],('独立人工の源不一致',key)
    prepared,last,baseline,previous,gated = map(read,(PREPARED,LAST_RESULT,BASELINE,PREVIOUS,GATED))
    assert all(v['passed'] for v in (prepared,last,baseline,previous,gated))
    scenes = prepared['sessions']
    assert len(scenes) == 41 and previous['sessions'] == scenes and last['sessions'] == scenes
    assert len(previous['rows']) == 1312 and len(gated['rows']) == 164
    assert gated['sessions'] == scenes
    old = {(r['session'],r['symbol']) for r in baseline['rows']}
    assert len(old) == 60
    last_index = {(p['session'],p['symbol']):p for p in last['cache']}
    original = baseline['cache']
    paper_caches = [dict(path=original['path'],sha256=original['sha256'],kind='paper_cache',scope='旧三十場原版')]
    for scene in scenes:
        for symbol in ('TOPIX','NK225'):
            if (scene,symbol) not in old:
                item = last_index[scene,symbol]
                paper_caches.append(dict(path=item['path'],sha256=item['sha256'],kind='paper_cache',session=scene,symbol=symbol))
    assert len(paper_caches) == 23
    assert {(p['path'],p['sha256']) for p in previous['paper_reads']} == {
        (p['path'],p['sha256']) for p in paper_caches}
    gated_cache = dict(gated['unified_cache'],kind='gated_paper_cache')
    previous_caches = [dict(p,kind='previous_bbo_cache') for p in previous['cache']]
    assert len(previous_caches) == 82
    packets = [dict(path=p['path'],sha256=p['sha256'],session=p['session'],kind='market_packet') for p in prepared['packets']]
    assert {(p['path'],p['sha256']) for p in previous['input_reads']} == {(p['path'],p['sha256']) for p in packets}
    numeric_paths = required[2:]
    numerical = {p.relative_to(ROOT).as_posix():current[p.relative_to(ROOT).as_posix()] for p in numeric_paths}
    for key,digest in numerical.items():
        assert previous['sources'][key] == digest
    catalog_path = HERE/'五十三条件と公開気配及び同値引用の固定.json'
    save(catalog_path,dict(specs=catalog(),rules=specification(),displayed_accounts=4346,market_reads=0,financial_accounts=0))
    metadata = [reference(path) for path in (artificial,PREPARED,LAST_RESULT,BASELINE,PREVIOUS,GATED,catalog_path)]
    bindings = metadata+paper_caches+[gated_cache]+previous_caches+packets
    fixed = dict(sources=current,numerical_sources=numerical,bindings=bindings,sessions=scenes,specs=catalog(),
        input=reference(PREPARED),last=reference(LAST_RESULT),baseline=reference(BASELINE),
        previous=reference(PREVIOUS),gated=reference(GATED),artificial=reference(artificial),
        paper_caches=paper_caches,gated_cache=gated_cache,previous_caches=previous_caches,packets=packets,
        counts=dict(displayed_accounts=4346,financial_accounts_upper_bound=4346,original_market_reads=0,API=0,real_orders=0),
        dedup=dict(scope='同一商品場かつ同一packet・固定核・終了・枚数上限',
            key='固定初回ATR込み十列数値通知bytesと四個方策bytes',
            order='既十六結果をseed、今回五十三条件順に未登録キーだけ新金融',
            prohibited='商品場跨ぎ引用、未来PL・親終了・将来極値による判定'),
        execution='原Last影の新規通知公開行でQを判定し、許可親だけ凍結済み次正常原行BBO実玉核へ通知する。')
    save(HERE/'固定計画.json',fixed)
    spec = dict(
        entry=dict(規則='原版/G/GUの保存Last通知を引用。Qは通知公開行の正常気配、幅とLastからの不利差が各初回ATRの半分以下。拒否親の返済通知も過去採否から除外。',目録=reference(catalog_path)),
        management=dict(規則='既十六と低R三は同一数値核。低R三はP01の利益床開始だけ0.25/0.5/0.75R。二市場反対時だけ床昇格、相手15秒、未知補完なし。'),
        exit=dict(規則='元影0.75ATRと段階出口は保存通知維持。実玉1ATR予算と条件付き利益床は実建値BBO清算で評価し次正常原行。早期退出後も元影は続く。'),
        allocation=dict(規則='TOPIXミニ初回5枚/上限10枚、NKマイクロ初回10枚/上限20枚、増玉復元なし。'),
        costs=dict(規則='手数料零。ラージBBO代理の気配横断を反映。実ミニ・マイクロ板と部分約定は未再現。'),
        execution=dict(規則=fixed['execution'],同値引用=fixed['dedup'],選定='integrate126.compareの固定順。各場参加・両商品と上昇下落黒字等の最低条件を満たすかを先に判断。'),
        data=dict(input_manifests=bindings,sessions=scenes,reuse='旧16結果を同値seed。G/GU統合注文1、原版23、packet41、旧BBOcache82を各一読。4346表示と新金融・旧引用・段内引用を分離。'),
        implementation=current)
    proposal = dict(id=TRIAL,name='GとGU入口及び低R利益床と公開気配予算の五十三対照',purpose='条件比較',
        question='広すぎる入口気配と初回一リスク未満の利益返しを分けて改善し、両商品で全場安定性が残るか。',
        change='既知のG/GU入口と低R利益床及び公開時点のQを単因子対照で追加。金融核は変更せず同値保存結果は再計算しない。',
        repeat_reason='具体損失診断で判明した初回気配超過と一R未満利益返しへの固定PDCA。G/GU19ずつ・原低R3・Q12の53条件、当ターン最終範囲。',
        compares_to=['126_BBO_原版影と実建値予算を分けた次正常原行十六対照'],evidence=metadata,spec=spec)
    save(HERE/'試行計画.json',proposal)
    if plan_only:
        print('提案保存のみ・登録零・金融零',flush=True)
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
