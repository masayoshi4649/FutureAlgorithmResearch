"""非金融可用性と現人工を確認し、数値不変更の最終試行計画を保存する。"""

from copy import deepcopy

import catalog
import common
import data
import plan


def activity_summary(meta: dict) -> dict:
    """
    機能: 全33場の価格状態と受付内候補を商品/固定条件ごとに合計する。
    引数: meta(dict)は完了した入力準備証跡。
    返り値: dictは候補件数/場数。実約定/勝敗と混同しない。
    """
    result={}
    for symbol in ('TOPIX','NK225'):
        result[symbol]={}
        for config in catalog.catalog():
            values=[meta['activity'][s][symbol]['条件'][config['id']] for s in meta['sessions']]
            result[symbol][config['id']]=dict(
                R受付内場=sum(v['R受付内']>0 for v in values),R受付内候補=sum(v['R受付内'] for v in values),
                R受付内買=sum(v['R受付内買'] for v in values),R受付内売=sum(v['R受付内売'] for v in values),
                C受付内場=sum(v['C受付内']>0 for v in values),C受付内候補=sum(v['C受付内'] for v in values),
                RANGE受付内行=sum(v['受付内状態']['RANGE'] for v in values),範囲内反発=sum(v['範囲内反発'] for v in values),
                予定RR拒否={str(k):sum(v['予定RR拒否'][str(k)] for v in values) for k in range(1,6)})
    return result


def run() -> None:
    """
    機能: 全33完了/依存指紋/人工を検査し、最終八部品と事前固定を保存する。
    引数: なし。
    返り値: None。旧金融結果・新金融・原本/APIは読まない。
    """
    meta=common.read(data.METADATA);assert meta['全合格'] and meta['新金融再生']==0
    assert len(meta['sessions'])==33 and meta['開始終端source一致']
    for path,sha in meta['source_SHA256'].items():assert common.digest(common.ROOT/path)==sha
    proof_paths=[common.HERE/'範囲内反発とAUTO接頭及び料込RRの人工検査.json']
    proof_paths += [common.HERE/'engine'/n for n in ('単一共有位置とR指値の人工検査.json',
        'R場末と待機欠測の追加人工検査.json','範囲入力と単一執行の結合人工検査.json',
        '選択後writable資格とreadonly静観のJIT人工検査.json')]
    proof_paths += [common.HERE.parent/'price_review/range_修正後の入力と料込RRの独立人工.json']
    for path in proof_paths:
        proof=common.read(path);assert proof['全合格'],path
        for p,sha in proof['source_SHA256'].items():assert common.digest(common.ROOT/p)==sha,(path,p)
    draft=common.read(common.HERE/'試行計画草案.json');final=deepcopy(draft)
    final['spec']['data']['input_manifests'].insert(0,dict(path=data.METADATA.relative_to(common.ROOT).as_posix(),sha256=common.digest(data.METADATA)))
    source_paths=list(common.HERE.glob('*.py'))+list((common.HERE/'engine').glob('*.py'))
    final['spec']['implementation'].update({p.relative_to(common.ROOT).as_posix():common.digest(p) for p in source_paths})
    final['evidence'] += [dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in proof_paths]
    final['状態']='全33の非金融可用性と現source人工が合格。固定24条件不変更。根の重複照合/登録通知前に正式金融を開始しない。'
    assert final['spec']['entry']==draft['spec']['entry'] and final['spec']['management']==draft['spec']['management']
    common.write(common.HERE/'全33可用性の集約.json',dict(全合格=True,候補可用性=activity_summary(meta),
        入力SHA256=common.digest(data.METADATA),金融再生=0,無発火を勝ちに含めない=True,
        限界='場数/候補数は実注文の場数/回数ではない。未fill/予約保有/30秒休止による候補消費を金融後に区別する。'))
    common.write(common.HERE/'試行計画.json',final)
    common.write(common.HERE/'事前固定.json',dict(全合格=True,configs=catalog.catalog(),sessions=meta['sessions'],
        input_manifest_SHA256=common.digest(data.METADATA),plan_SHA256=common.digest(common.HERE/'試行計画.json'),
        source_SHA256=final['spec']['implementation'],条件変更=0,新金融再生=0,
        financial_start='根の正式登録完了通知後、一回だけ24×66を開始する。'))
    print('24条件の最終八部品と全33可用性を固定、金融0',flush=True)


if __name__=='__main__':run()
