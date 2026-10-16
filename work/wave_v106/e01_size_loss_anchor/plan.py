"""初回受理比例損失だけの対照を八部品へ結び、保存GUを再利用する。"""

import common
import catalog


def check_clones() -> dict:
    """
    機能: 実数量数学・影・料金・執行を元数量版の同bytesへ照合する。
    引数: なし。
    返り値: dict は確認済み直接sourceの指紋。旧moduleをimportしない。
    """
    previous=common.ROOT/'work/wave_v106/e01_size_goal_anchor'
    copies={'common.py':'common.py','daily.py':'daily.py','order_kernel.py':'order_kernel.py','policy.py':'policy.py',
        'engine.py':'engine.py','baseline.py':'baseline.py','data.py':'data.py','storage.py':'storage.py',
        'fixed_goal_interface.py':'fixed_goal_interface.py','fixed_loss_policy.py':'goal_policy.py'}
    result={}
    for current,old in copies.items():
        reference=previous/old
        assert (common.HERE/current).read_bytes()==reference.read_bytes(),current
        result[reference.relative_to(common.ROOT).as_posix()]=common.digest(reference)
    return result


def prepare(formal: bool=False) -> None:
    """
    機能: 旧利確アンカーの固定入力と同母会計を引用し、四比較を結果前固定する。
    引数: formal(bool) は正式結果前固定か草案v2か。保存小JSONとsourceだけを読む。
    返り値: None。根の許可を受けた固定準備のみ。登録・金融・大型cache読取は行わない。
    """
    previous=common.ROOT/'work/wave_v106/e01_size_goal_anchor'
    fixed_path=previous/'金融事前固定.json';result_path=previous/'finance/結果.json'
    artificial_path=common.HERE/'初回受理の比例損失と回復勝ち喪失及び旧GU同値の人工検査.json'
    fixed,result,proof=(common.read(p) for p in (fixed_path,result_path,artificial_path))
    assert fixed['全合格'] and result['全合格'] and proof['全合格']
    assert proof['source_SHA256']==common.sources()
    assert result['source_SHA256']==fixed['source_SHA256'] and result['source開始終端一致']
    configs=catalog.configs();comparisons={};clones=check_clones()
    for config in configs:
        before=result['results'][config['baseline_id']]
        assert len(before['rows'])==len(before['ledgers'])==66
        assert {(r['session'],r['symbol']) for r in before['rows']}=={(s,t) for s in fixed['sessions'] for t in catalog.QUANTITY}
        references={r['session']+'|'+r['symbol']:r for r in before['ledgers']}
        assert len(references)==66
        assert all(isinstance(r['path'],str) and len(r['SHA256'])==64 for r in references.values())
        comparisons[config['id']]=dict(id=config['baseline_id'],source=result_path.relative_to(common.ROOT).as_posix(),
            SHA256=common.digest(result_path),row_count=66,ledger_count=66,rows=before['rows'],symbols=before['symbols'],ledgers=references)
    assert len(fixed['sessions'])==33 and set(fixed['input_cache'])==set(fixed['sessions'])
    assert all(isinstance(r['path'],str) and len(r['SHA256'])==64 for r in fixed['input_cache'].values())
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p))
        for p in (fixed_path,result_path,artificial_path,common.HERE/'複写由来.json')]
    spec=dict(entry=dict(conditions=configs,condition_count=4,
        母条件='元E01のW60 CONFIRM又はVETO/D0。元paper全feedを再計算せず保存を使用。',
        数量='元数量版と同一。公開当行ATR＋spread＋注文別往復floor料を、当時M=max(0,L2+実清算)内に収める最大整数q。',
        非救済='q0・UNKNOWN・母拒否・busy・静観・期限の非受理候補から目標を作らない。未来fillへ選び直さない。'),
        management=dict(アンカー='最初に受理した実新規予約qで利益・損失の両停止線を一回固定。約定無しでも固定保持。',
            系譜='size_events.actual_pending==1の時系列最初の原行・原seq・価格代理時計・paper親を保存。',
            固定='受理後に未約定取消されてもqを交換しない。後の再参加数量や次気配価格へ追従しない。',
            途中='影5/10、元GU判断、実partial累積floor、予約順序、実料・当時清算を全て同bytesで維持。'),
        exit=dict(唯一の変更='daily.loss_ticks=2×最初受理q/full。利益goalは旧と同じP1/P2×初回q/full。円端数は理論値比較、料は注文別整数floor。',
            元目標={'TOPIX':{'P1':2500,'P2':5000},'NK225':{'P1':1000,'P2':2000}},
            分母={'TOPIX':5,'NK225':10},新規数量選択予算円={'TOPIX':5000,'NK225':2000},
            損失停止線='前項予算の同円を初回受理q/fullへ比例固定。無受理は停止線None。数量選択へこの縮小線を戻さない。',
            先着='費用後清算が固定利益又は比例損失線へ最初到達した行で停止し、残UIDを次正常気配で全返済。場内の以後新規無し。'),
        allocation=dict(base_quantity=catalog.QUANTITY,direction_cap=catalog.CAP,
            不変='公開q計算・qty予約・後続q・返済丸めは旧数量版と同一。利益目標の結果を影feedへ戻さない。'),
        costs=dict(片道税込={'TOPIXmini':41.8,'NK225micro':11},円倍率=catalog.VALUE,
            課金='不変daily/UID会計。各新規/部分/全返済floor(qfee)、TOP209/5・NK11/1の整数分数。',
            主評価='完結親net正負合計。実部分返済玉の正負は別副表として保存。'),
        execution=dict(不変='D0新規は公開後最初正常ask/bid、返済は判断後次正常気配。timer取消→以前のfill→当行paper公開の順序。',
            目標固定時計='将来の実fillではなく最初の発注受理行。当行未約定。受理後取消でも固定。',
            限界='ラージ気配の価格到達模型。実mini/micro板と待ち順位、真の受信時刻は未観測。'),
        data=dict(sessions=fixed['sessions'],input_manifests=manifests,
            保存input33の指紋=fixed['input_cache'],保存比較264の指紋={cid:ref['ledgers'] for cid,ref in comparisons.items()},
            入力='正式金融開始後だけ既33packetを各一読。現時点は小固定JSONと源のみ。',
            比較='旧goal四条件の同母・同P1/P2の264台帳を各一読。P1/P2間で保存GU使用七配列をexact確認して132共有。',
            GU再利用='shadow_GU_orders/uids、execution_events/states、limit_events、sizing_events、sizing_fee_curve。未使用の1/2/3/4槽はNone。新engine実行0。',
            現在='価格時計不適合の現ナイト素材は未使用。原板/NPZ/API0。'),
        implementation=common.sources())
    prepared_plan=dict(id=catalog.TRIAL_ID,name='初回受理数量へ損失停止線も対応させる四対照',
        purpose='新仮説',question='利確比例・損失固定の尺度不整合を解消すると、大損失と回復勝ちの両方はどう変わるか。',
        change='損失停止線だけ最初受理q/fullへ比例。公開数量選択予算・利益線・実料・影・partial・次正常気配は不変。',
        repeat_reason='旧goal版は平均黒字の小ささに対し固定L2の最大損失が残った。今回は損失尺度だけの対照。GUは前段同値を再利用し新しい証拠に数えない。',
        compares_to=['106_E01予定リスク数量の初回受理目標アンカーP1P2四対照'],spec=spec,
        比較元={cid:dict(id=ref['id'],source=ref['source'],SHA256=ref['SHA256'],row_count=66,ledger_count=66) for cid,ref in comparisons.items()},
        同bytesコピー=clones,
        予定=dict(条件=4,新GUengine=0,保存GU再利用=132,政策会計=264,旧利確アンカー比較口座=264,既input一読=33),
        counts=dict(新GUengine=0,保存GU再利用=132,新政策会計=264,旧利確アンカー台帳一読=264,既input一読=33,旧risk及びfull台帳読取=0,元paper再計算=0),
        未確定点=[],
        limitations=['損失線を狭めると、元の固定L2で回復して勝った親を失い得る。入口精度を改善したことにはならない。',
            '初期spreadと往復料だけで初fill直後に停止し得る。次quoteで比例線も超過するため最大損失保証ではない。',
            '初回受理取消後も両停止線を保持し、次のqに合わせ直さない。受理無しは両線未定義で勝ちではない。',
            '保存GUの七配列と同原行quoteを再利用する政策対照。GU再計算や過去勝敗の削除だけによる代用はしない。'],
        正式freeze=bool(formal),登録=0,金融=0,大型cache読取=0,原板=0,NPZ=0,API=0)
    if formal:
        import runner
        references={}
        for mode in ('CONFIRM','VETO'):
            old=fixed['旧fullP1L8参考rows'][mode]
            references[mode]=dict(id=old['id'],rows=old['rows'],symbols=old['symbols'],利用範囲='小会計rows参考だけ。台帳読取・金融再生無し。')
        common.write(common.HERE/'試行計画.json',prepared_plan)
        common.write(common.HERE/'金融事前固定.json',dict(全合格=True,sessions=fixed['sessions'],configs=configs,
            input_cache=fixed['input_cache'],comparisons=comparisons,旧fullP1L8参考rows=references,
            source_SHA256=common.sources(),case_SHA256=runner.case_hashes(configs),
            計画SHA256=common.digest(common.HERE/'試行計画.json'),正式金融=0,大型input読取=0,旧数量台帳読取=0,
            旧fullP1L8台帳読取=0,原板読取=0,NPZ読取=0,API=0))
        print('四条件・input33・比較264の正式事前固定完了。根の登録/金融待ち。',flush=True)
    else:
        common.write(common.HERE/'試行計画草案_v2.json',prepared_plan)
        print('四条件の八部品草案v2保存。正式登録・金融は根の確認待ち。',flush=True)


def freeze() -> None:
    """
    機能: 根が許可した正式driverと四条件を、結果前の計画及び固定へ保存する。
    引数: なし。
    返り値: None。登録・本番金融・大型入力読取は行わない。
    """
    prepare(formal=True)


if __name__=='__main__':prepare()
