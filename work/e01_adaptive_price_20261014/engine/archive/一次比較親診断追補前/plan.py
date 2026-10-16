"""公開時の強支持だけ許容1とする八条件を、旧固定許容の比較と別に固定準備する。"""

import common
import catalog
import data


def clones() -> dict:
    """
    機能: 不変の注文/数量/返済/会計及び固定FAK対照が同bytesの新所有コピーか確認する。
    引数: なし。
    返り値: dict は旧参照sourceのSHA256。旧module又はcacheをimportしない。
    """
    previous=common.ROOT/'work/e01_improve_20261014/engine';result={}
    names=('common.py','context.py','daily.py','exit_core.py','exit_policy.py','order_kernel.py','reuse.py',
        'storage.py','sizing_baseline.py','base_policy.py','ledger_storage.py','data.py','sizing_engine_legacy.py')
    for name in names:
        ref=previous/name;assert (common.HERE/name).read_bytes()==ref.read_bytes(),name
        result[ref.relative_to(common.ROOT).as_posix()]=data.digest(ref)
    ref=previous/'sizing_engine.py';assert (common.HERE/'constant_engine.py').read_bytes()==ref.read_bytes()
    result[ref.relative_to(common.ROOT).as_posix()]=data.digest(ref)
    return result


def prepare(formal: bool=False) -> None:
    """
    機能: 永続小metadataから八比較台帳と旧24小会計を引用し、八部品草案又は根の正式固定を作る。
    引数: formal(bool) は根だけの正式freeze。Falseは未金融の準備。
    返り値: None。00105結果の再読、台帳本文、実input、金融、登録、APIを行わない。
    """
    metadata_path=common.HERE/'旧二十四小会計と八比較の目録.json'
    proof_path=common.HERE/'公開支持の許容固定と八政策接続の人工検査.json'
    metadata,proof=(data.read(p) for p in (metadata_path,proof_path))
    assert metadata['全合格'] and proof['全合格'] and proof['source_SHA256']==common.sources()
    sessions=metadata['sessions'];assert len(sessions)==33 and len(metadata['references'])==8 and len(metadata['reused_results'])==24
    source=common.sources();configs=catalog.configs();keys={(s,t) for s in sessions for t in catalog.QUANTITY}
    for cid,refs in metadata['references'].items():
        assert len(refs)==66 and set(refs)=={s+'|'+t for s,t in keys}
        assert {(r['session'],r['symbol']) for r in metadata['reused_results'][cid]['rows']}==keys
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=data.digest(p)) for p in (metadata_path,proof_path)]
    spec=dict(entry=dict(conditions=configs,condition_count=8,
        gate='W60同代理、既知方向票>=2かつside釣合い>=.25又は.5。入口maskは固定許容版と同じ。',
        paper='元paper全feedを続行し、拒否/失効後も実q/busy/再参加を機械再生する。'),
        management=dict(アンカー='最初受理q/公開ATR/spreadで場利益線を一回固定。失効取消でも保持。',
            不変='公開1ATR+spread+注文別往復料で残余力内の実qを選ぶ。実partial累積floor・最後残返済。'),
        exit=dict(純目標='P1=初受理q×観測T×円倍率、ATR25=.25×初受理q×公開ATR×円倍率。hardB5000/2000固定。',
            不変='元GU/既知静観/期限、費用後場清算の初先着→次正常UID返済と場停止を維持。'),
        allocation=dict(base_quantity=catalog.QUANTITY,direction_cap=catalog.CAP,quantity_selection_budget_yen=catalog.BUDGET,
            予約='公開qは以後固定。失効は実UID/新規料を作らず、後参加は別候補で数量再計算。'),
        costs=dict(片道税込={'TOPIXmini':41.8,'NK225micro':11},円倍率=catalog.VALUE,
            課金='注文毎floor(qfee)、TOP209/5/NK11/1。実部分返済料/残UID返済料を含む。'),
        execution=dict(許容='新規公開当行balance>=.75又は1.0だけ不利1観測Tを許容し、それ以外0。公開時に予約へ固定。',
            一回='最初goodで価格内なら当時BBO全量、外なら失効。以後好転しても同予約を復活しない。',
            順序='scheduled取消→旧queue返済→既pendingの一回FAK→当行paper。入口maskへ未来気配を混ぜない。',
            境界='買公開ask＋許容T以下、売公開bid−許容T以上。試行行の票/配列値で公開許容を再選択しない。',
            限界='spreadガード無し。観測ラージT=.5pt/10円は実mini/micro二呼値。native順位/部分FAK/真受信順は未測定。'),
        data=dict(sessions=sessions,input_manifests=manifests,input_cache=metadata['input_cache'],reference_ledger_manifests=metadata['references'],
            再利用='00105固定FAK八条件の528台帳各1読。P1/ATR25ペア264の七GU配列同値と全528政策経済同値を確認。新有効性標本にしない。',
            一次='根登録後input33各一読、新GU四route264・新政策八条件528。paper再計算無し。',
            小metadata='00105結果を原因診断1読とは別目的で1読し、永続小射影を保存。以後prepare/freezeは同射影再利用。',
            比較='FAK0主比較、FAK1副比較を同paper親の5寄与へ分ける。旧24保存小会計は比較表示だけ。',
            診断='同一次入力から実親の公開票/固定許容/注文rowseq価格時計と正常観測清算MAEを小保存。未来極値は事後専用。',
            禁止='原板/NPZ/API/現在不適合入力は不使用。',
            transitive_source_finance=metadata['source_finance'],transitive_source_fixed=metadata['source_fixed']),implementation=source)
    prepared=dict(id=catalog.TRIAL_ID,name='支持の強さで注文価格を切り替えるE01八対照',purpose='新仮説',
        question='強い公開票だけ1観測Tを許容すれば、固定0/1の失う勝ちと避け損失を改善できるか。',
        change='公開許容選択だけ変更、票gate/q/受理アンカー/途中/出口/費用は保持。',
        repeat_reason='固定0はDay勝ちを失効させ、固定1の強入口は両合格でも7/8活動場。旧親合算ではなく全feedの後参加を比較する。',
        compares_to=['105_E01公開気配FAK二許容と票強度四条件の十八対照'],spec=spec,同bytesコピー=clones(),
        予定=dict(新条件=8,新GUengine=264,新政策会計=528,保存GU再利用=264,旧固定許容台帳一読=528,
            旧基準経済同値確認=528,既input一読=33,旧保存表示条件=24),
        未確定点=[],正式freeze=formal,登録=0,金融=0,実input読取=0,旧GU台帳読取=0,
        limitations=['許容1は悪化を追う対価も払い、許容0は勝ちを捨てる。適応成績を保存条件の都合よい合算で推定しない。',
            '価格capはspread又は損失上限を制限しない。実商品native注文能力/queueを確認した模型ではない。',
            '未約定初受理のq/ATR尺度は保持し、その後実数量との尺度差を今回交換しない。',
            '無取引は勝ちに数えず、疎活動の三基準合格を全日安定と呼ばない。',
            '清算MAEは事後診断。親期間重複時は同時全玉清算だけ保存し、その親のMAEへ流用しない。'])
    filename='試行計画.json' if formal else '試行計画草案.json';common.write(filename,prepared)
    import runner
    fixed=dict(全合格=True,正式freeze=formal,sessions=sessions,configs=configs,input_cache=metadata['input_cache'],
        references=metadata['references'],reference_mapping=metadata['reference_mapping'],reused_results=metadata['reused_results'],
        source_SHA256=source,case_SHA256=runner.case_hashes(configs),計画SHA256=data.digest(common.HERE/filename))
    common.write('金融事前固定.json' if formal else '準備固定.json',fixed)
    print('適応FAK八条件の'+('正式固定' if formal else '未金融草案')+'を保存',flush=True)
