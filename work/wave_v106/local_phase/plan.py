"""元6条件と18変更の差を、金融前の八部品と同量比較へ固定する。"""

from pathlib import Path

import catalog
import common


def evidence(path: Path, pointer: str='/') -> dict:
    """
    機能: 小資料の参照位置と内容指紋を作る。
    引数: path(Path)、pointer(str)はROOT内資料とJSON/文章の対象。
    返り値: dictはpath/pointer/sha256。巨大原本を読むことはない。
    """
    return dict(path=path.relative_to(common.ROOT).as_posix(),pointer=pointer,sha256=common.digest(path))


def main() -> None:
    """
    機能: 入力33準備と人工合格を確認し、18数値の固定/八部品草案を新規保存する。
    引数: なし。小目録/source/人工を読む。
    返り値: None。登録と金融は根が行い、ここでは自動開始しない。
    """
    metadata_path=common.HERE/'全33場の直近位相準備.json';meta=common.read(metadata_path)
    assert meta['全合格'] and len(meta['sessions'])==33 and meta['新金融再生']==0
    for name,sha in meta['input_source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    proof_paths=[common.HERE/'直近位相と方向別待機取消の人工検査.json',common.HERE/'直近位相の未知静観とreadonly資格の補足人工.json',
        common.ROOT/'work/wave_v106/price_review/local_三点位相と方向別取消の独立人工.json']
    for path in proof_paths:
        proof=common.read(path);assert proof['全合格']
        for name,sha in proof.get('source_SHA256',{}).items():assert common.digest(common.ROOT/name)==sha,name
    production=[common.HERE/n for n in ('common.py','catalog.py','features.py','selection.py','selection_snapshot.py',
        'interface.py','data.py','prepare.py','artificial.py','extra_artificial.py','plan.py')]
    production += [common.HERE/'engine'/n for n in ('core.py','reference_core.py','fixture_source.py','accounting.py','accounting_reference.py')]
    implementation={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in production}
    base_result=common.ROOT/'work/wave_v106/range_price/finance/results.json'
    source_meta=common.ROOT/'work/wave_v106/range_price/全33場の価格境界反発準備.json'
    source_plan=common.ROOT/'work/wave_v106/range_price/試行計画.json'
    pending_plan=common.ROOT/'work/wave_v106/e01_pending_price/試行計画.json'
    regime_plan=common.ROOT/'work/wave_v106/regime_price/試行計画.json'
    old86=common.ROOT/'アルゴリズム調査/00086_二市場の状態で追従と指値反発を配分/README.md'
    earlier=[dict(比較元='元range_price24中のAUTO ER40の6条件',差='旧6点RANGE/反発/固定線/料金RRはexact。新規の短位相審査とR未fillの追加取消だけ変更。',evidence=[evidence(source_plan,'/spec'),evidence(base_result,'/cases')]),
        dict(比較元='E01待機指値の純価格逆方向取消12',差='旧W10/30/60の両気配変化とE01紙上親を使わず、六点120/60＋現在中値三点ER/2呼値を使う。入口も同時に審査し、単一口座で全後続の実候補を再処理。元knownTREND/価格R固定stop/中心を保持。',evidence=[evidence(pending_plan,'/spec')]),
        dict(比較元='旧純価格6点レジーム26',差='Cの双方300秒2/3/5bp同方向だけを判定した旧研究とは別に、R_PRICE新規と未fillへ直近120秒局所位相を適用。旧板R_OWNを使わず価格反発R。',evidence=[evidence(regime_plan,'/spec')]),
        dict(比較元='00086_二市場の状態で追従と指値反発を配分',差='旧全経路ERと10秒確認/8呼値階段の同時配分ではない。元R_PRICEの単一AUTOへ、三点の現在位相だけを追加する。',evidence=[evidence(old86,'追従J2と反発O06')])]
    base_ids=sorted({c['base_id'] for c in catalog.catalog()})
    spec=dict(
        entry=dict(condition_count=18,conditions=[{k:c[k] for k in ('local_policy','margin_ticks','range_entry')} for c in catalog.catalog()],
            inherited='AUTO ER40、C双方5分2bp、元価格Rの範囲内1呼値両quote反発と料金後RR1.25を保持。',
            own='既6点120/60秒価格＋当行実normal中値。own_known[row]かつ当行qokを維持。',
            peer='相手strictpast6点の120/60/0秒末三点。相手呼値を使用。',
            strong='ERshort=|p2-p0|/(|p1-p0|+|p2-p1|)>=0.6 かつ |p2-p0|/tick>=2。TV0は既知中立。',
            policies=dict(OWN_VETO='自己強方向がRsideと反対なら新規拒否。',BOTH_VETO='双方強方向がRsideと反対なら新規拒否。',ALIGNED='双方強方向がRsideへ揃った場合だけR新規許可。')),
        management=dict(single_position=True,additions=False,cooldown_seconds=30,
            old_pending='元R未fillのknownTREND両方向/固定stop/J/cut取消を保持。',
            local_pending='OWNは自己強反対、BOTH/ALIGNEDは双方強反対の追加取消。実pending sideでbuy/sell二列から選ぶ。ALIGNED同方向消失だけでは追加取消しない。',
            unknown='未fillの局所必要点が未知なら追加取消なし。元knownTREND/時間/固定stop取消を免除するわけではない。',
            C='新規支持/数量資格/episode/待機/保有は元exact。',
            repeat='新規拒否/待機取消した候補を後で復活しない。別原rowの新候補は単一口座状態と30秒cooldownの下で全後続再判定。'),
        exit=dict(R='元固定stop/中心target/既知timerのみ。局所/長期modeだけで保有後返済しない。',
            C='支持4呼値と始値0.1%停止の有利側＋旧0.4%広追尾。',start_offset_seconds=300,cut_offset_seconds=300,force_offset_seconds=60,session_flat=True),
        allocation=dict(quantity={'TOPIX':5,'NK225':10},products={'TOPIX':'TOPIXmini','NK225':'NK225micro'},
            caps_per_direction={'TOPIX':10,'NK225':20},hedge=False,portfolio=False),
        costs=dict(oneway_fees={'TOPIX':41.8,'NK225':11},multipliers={'TOPIX':1000,'NK225':10},rounding='各注文floor(q*片道料)、新規返済双方。',
            spread='買ask/売bidを実経済へ含める。J-NET仮定なし。'),
        execution=dict(entry_market='判断当行禁止、次正常quote。',entry_limit='公開当行禁止、最初の正常ask<=買線/bid>=売線で実気配約定。',
            priority='J/cut/forceの既知予定取消を先に、既livemarket/limitのfillを保持、残未fillだけ既TREND/stop OR 局所取消。',
            exit='固定stop/target初到達判断の次正常清算quote。次quote gapを固定線約定へ置換しない。',
            diagonal='fill_known_trendは元modeのみ。局所取消/fill局所条件は別診断。control15の欄名で取消原因を同一視しない。',
            assumptions='価格代理時計、ラージBBOを小商品へ代用。受信時計/待ち順位/実全量約定未検証。追加5秒悪化なし。'),
        data=dict(sessions=meta['sessions'],input_manifests=[evidence(metadata_path),evidence(source_meta),evidence(base_result)],
            known='既知33場。新未見期間0。元range_price cache33のみ各1読、short一回算定。旧104/原本/API再読0。',
            qualifications='確定6点のown尾部seq/highwater/原row上限、peer strictpast/asof15/各基準age15を保持。sample間全経路効率とは呼ばない。'),
        implementation=implementation)
    fixed=dict(全合格=True,configs=catalog.catalog(),sessions=meta['sessions'],source_SHA256=implementation,
        input_metadata=evidence(metadata_path),baseline_results=evidence(base_result),base_ids=base_ids,
        proofs=[evidence(p) for p in proof_paths],新金融再生=0,正式金融未開始=True,数学='根が結果前に指定した18条件。新結果による閾値選別/変更は0。')
    common.write(common.HERE/'事前固定.json',fixed)
    plan=dict(id=catalog.TRIAL_ID,name='過去レンジの直近進行でR新規と待機を止める18対照',purpose='新仮説',
        question='往復の過去形に含まれる直近一方向の進行を入口/未約定で避けると、赤字場を減らしながら元利益を保持できるか。',
        change='RだけOWN/BOTH逆方向veto又は両方aligned。旧6対照のC・全出口・価格線・費用・実量は保持。',
        repeat_reason='9/29 09:16:46のR買いは六点ER0.14でも直近4071.25→4069.75→4067.25。過去往復と現在進行を分ける差分の検証。',
        compares_to=[common.read(p)['id'] for p in (source_plan,pending_plan,regime_plan)],prior_similar=earlier,
        sacrifices=['直近の下げ/上げが本当の底/天井反発へつながる勝ちも失い得る。',
            'ALIGNEDは両方が反発した後なので価格/料金RRが不足して候補が消え得る。無取引を成功へ数えない。',
            '三点効率は全quote経路ではない。未知は救済せず、同row実約定を遡及取消しない。',
            '同条件同入力の比較元6会計を再利用し、新しい有効性の証拠に数えない。'],
        evidence=[evidence(p) for p in proof_paths]+[evidence(common.HERE/'経済源の方向別取消差分.json'),evidence(common.HERE/'入力と経済sourceの複製由来.json')],
        spec=spec,状態='結果前固定/入力準備/人工完了、未登録、新金融0。根のsourceレビュー/check/register後にのみ根runnerが実行。')
    common.write(common.HERE/'試行計画草案.json',plan)
    common.write(common.HERE/'既存取消手法との相違.json',dict(全合格=True,prior_similar=earlier,新金融再生=0,
        限界='部品概念が似ることを明示。同じ全経済条件を再試行したのではないが、過去の全未整理試行から完全に新規と証明する資料ではない。'))
    print('直近位相18の事前固定と八部品草案を保存、金融0',flush=True)


if __name__=='__main__':main()
