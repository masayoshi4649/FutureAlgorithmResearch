"""利確目標だけの変更を八部品草案へ結び、正式登録・金融は根へ留保する。"""

import common
import catalog


def draft() -> None:
    """
    機能: 旧数量版の固定入力と同条件会計を引用し、結果前の四比較草案を保存する。
    引数: なし。保存小JSONと小sourceだけを読む。
    返り値: None。正式freeze・登録・金融・大型cache読取は行わない。
    """
    previous=common.ROOT/'work/wave_v106/e01_risk_sizing'
    fixed_path=previous/'金融事前固定.json';result_path=previous/'finance/結果.json'
    artificial_path=common.HERE/'初回受理目標と未約定取消及び旧数量同値の人工検査.json'
    fixed,result,proof=(common.read(p) for p in (fixed_path,result_path,artificial_path))
    assert fixed['全合格'] and result['全合格'] and proof['全合格']
    assert proof['source_SHA256']==common.sources()
    assert result['source_SHA256']==fixed['source_SHA256'] and result['source開始終端一致']
    configs=catalog.configs();comparisons={}
    for config in configs:
        before=result['results'][config['baseline_id']]
        assert len(before['rows'])==len(before['ledgers'])==66
        assert {(r['session'],r['symbol']) for r in before['rows']}=={(s,t) for s in fixed['sessions'] for t in catalog.QUANTITY}
        comparisons[config['id']]=dict(id=config['baseline_id'],source=result_path.relative_to(common.ROOT).as_posix(),
            SHA256=common.digest(result_path),row_count=66,ledger_count=66)
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p))
        for p in (fixed_path,result_path,artificial_path,common.HERE/'複写由来.json')]
    spec=dict(entry=dict(conditions=configs,condition_count=4,
        母条件='元E01のW60 CONFIRM又はVETO/D0。元paper全feedを再計算せず保存を使用。',
        数量='元数量版と同一。公開当行ATR＋spread＋注文別往復floor料を、当時M=max(0,L2+実清算)内に収める最大整数q。',
        非救済='q0・UNKNOWN・母拒否・busy・静観・期限の非受理候補から目標を作らない。未来fillへ選び直さない。'),
        management=dict(アンカー='最初に受理した実新規予約qで一回固定。約定無しでも固定保持。',
            系譜='size_events.actual_pending==1の時系列最初の原行・原seq・価格代理時計・paper親を保存。',
            固定='受理後に未約定取消されてもqを交換しない。後の再参加数量や次気配価格へ追従しない。',
            途中='影5/10、元GU判断、実partial累積floor、予約順序、実料・当時清算を全て同bytesで維持。'),
        exit=dict(唯一の変更='goal=元P1又はP2の円額×最初受理q/full。円端数があれば理論値のまま比較し、料は注文別整数floorのまま。',
            元目標={'TOPIX':{'P1':2500,'P2':5000},'NK225':{'P1':1000,'P2':2000}},
            分母={'TOPIX':5,'NK225':10},損失不変={'TOPIX':5000,'NK225':2000},
            先着='費用後清算が固定利益又は不変L2へ最初に達した行で停止し、残UIDを次正常気配で全返済。場内の以後新規無し。'),
        allocation=dict(base_quantity=catalog.QUANTITY,direction_cap=catalog.CAP,
            不変='公開q計算・qty予約・後続q・返済丸めは旧数量版と同一。利益目標の結果を影feedへ戻さない。'),
        costs=dict(片道税込={'TOPIXmini':41.8,'NK225micro':11},円倍率=catalog.VALUE,
            課金='不変daily/UID会計。各新規/部分/全返済floor(qfee)、TOP209/5・NK11/1の整数分数。',
            主評価='完結親net正負合計。実部分返済玉の正負は別副表として保存。'),
        execution=dict(不変='D0新規は公開後最初正常ask/bid、返済は判断後次正常気配。timer取消→以前のfill→当行paper公開の順序。',
            目標固定時計='将来の実fillではなく最初の発注受理行。当行未約定。受理後取消でも固定。',
            限界='ラージ気配の価格到達模型。実mini/micro板と待ち順位、真の受信時刻は未観測。'),
        data=dict(sessions=fixed['sessions'],input_manifests=manifests,
            入力='正式金融開始後だけ既33packetを各一読。現時点は小固定JSONと源のみ。',
            比較='旧数量四条件の同母・同P1/P2・同L2会計を保存再利用。旧利益に比例計算するだけの代用をしない。',
            現在='価格時計不適合の現ナイト素材は未使用。原板/NPZ/API0。'),
        implementation=common.sources())
    common.write(common.HERE/'試行計画草案.json',dict(id=catalog.TRIAL_ID,name='初回受理数量へ利確目標を対応させる四対照',
        purpose='新仮説',question='予定リスクで初回枚数を減らしても、元と同程度の順行値幅で利確できるか。',
        change='円利確目標だけを最初の受理q/fullへ対応。公開qty・実料・shadow・partial・L2・次正常気配は不変。',
        repeat_reason='旧数量版は固定円goalを残したため、少数量で必要順行値幅が増大した。今回はその尺度不整合だけを直す対照。',
        compares_to=['106_E01公開時の予定リスク数量と絶対円P1P2_L2四対照'],spec=spec,比較元=comparisons,
        予定=dict(条件=4,GU共有engine=132,政策会計=264,旧数量比較口座=264,既input一読=33),
        未確定点=['経済仕様の受理時固定は根が確定済み。正式driver・許可guard・登録時のsource束縛はまだ根レビュー前。'],
        limitations=['利確を小さくしてL2を据え置くため、平均黒字と最大赤字の比を悪化させる可能性がある。',
            '必要ptは初回qに比例する円goalにより揃うが、手数料や再参加qの違いは残る。以後qtyへgoalを交換しない。',
            '初回受理が取消され、次の数量が異なる場合も最初goalを保持する。受理無しの場はgoal未定義・無取引で勝ちではない。',
            '利益到達後の次気配悪化、旧GU先行返済、公開UNKNOWN/q0/busyによる活動消失は改善保証されない。'],
        正式freeze=0,登録=0,金融=0,大型cache読取=0,原板=0,NPZ=0,API=0))
    print('四条件の八部品草案保存。正式freeze・登録・金融は根の確認待ち。',flush=True)


if __name__=='__main__':draft()
