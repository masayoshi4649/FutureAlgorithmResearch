"""一回FAK十八条件、旧GU198と市場六対照396の再利用を八部品へ固定準備する。"""

import common
import catalog
import data


def clones() -> dict:
    """
    機能: 不変会計・数量対照・UID・保存部品が新所有域への同bytes写しであることを確かめる。
    引数: なし。
    返り値: dict は旧参照sourceのSHA256。旧module/JITをimportしない。
    """
    previous=common.ROOT/'work/e01_cross_market_20261014/engine';result={}
    names=('common.py','context.py','daily.py','exit_core.py','exit_policy.py','order_kernel.py','reuse.py',
        'storage.py','sizing_baseline.py','base_policy.py','ledger_storage.py','data.py')
    for name in names:
        ref=previous/name;assert (common.HERE/name).read_bytes()==ref.read_bytes(),name
        result[ref.relative_to(common.ROOT).as_posix()]=data.digest(ref)
    ref=previous/'sizing_engine.py';assert (common.HERE/'sizing_engine_legacy.py').read_bytes()==ref.read_bytes()
    result[ref.relative_to(common.ROOT).as_posix()]=data.digest(ref)
    return result


def prepare(formal: bool=False) -> None:
    """
    機能: 旧保存小JSONだけからinput33と六市場対照396台帳の指紋を束縛する。
    引数: formal(bool) は根だけの正式freezeか非金融草案か。
    返り値: None。旧GU本文・新金融・登録・実input・APIを読まない。
    """
    old=common.ROOT/'work/e01_cross_market_20261014/engine';older=common.ROOT/'work/wave_v106/e01_size_goal_anchor'
    old_fixed_path=old/'金融事前固定.json';old_result_path=old/'finance/結果.json'
    older_fixed_path=older/'金融事前固定.json';older_result_path=older/'finance/結果.json'
    proof_path=common.HERE/'十八対照のFAKと登録前拒否及び保存比較の人工検査.json'
    paths=(old_fixed_path,old_result_path,older_fixed_path,older_result_path,proof_path)
    old_fixed,old_result,older_fixed,older_result,proof=(data.read(p) for p in paths)
    assert all(v['全合格'] for v in (old_fixed,old_result,older_fixed,older_result,proof))
    assert old_result['source開始終端一致'] and old_result['source_SHA256']==old_fixed['source_SHA256']
    assert older_result['source開始終端一致'] and older_result['source_SHA256']==older_fixed['source_SHA256']
    assert proof['source_SHA256']==common.sources()
    sessions=old_fixed['sessions'];assert sessions==older_fixed['sessions'] and len(sessions)==33
    assert old_fixed['input_cache']==older_fixed['input_cache'] and set(old_fixed['input_cache'])==set(sessions)
    references={};mapping={};reused={};keys={(s,t) for s in sessions for t in catalog.QUANTITY}
    for (gate,target),cid in catalog.OLD_IDS.items():
        source=older_result if gate=='G25' and target=='P1' else old_result
        source_path=older_result_path if source is older_result else old_result_path
        entry=source['results'][cid];assert len(entry['rows'])==len(entry['ledgers'])==66
        assert {(r['session'],r['symbol']) for r in entry['rows']}==keys
        original=[c for c in source['configs'] if c['id']==cid];assert len(original)==1
        ref={r['session']+'|'+r['symbol']:r for r in entry['ledgers']};assert len(ref)==66
        references[cid]=ref;mapping[gate+'|'+target]=cid
        reused[cid]=dict(**{k:v for k,v in entry.items() if k!='ledgers'},
            config=dict(id=cid,entry_id=gate,execution_id='MARKET',target_id=target,quantity=catalog.QUANTITY,
                cap=catalog.CAP,min_votes=2,balance_threshold=catalog.GATES[gate][0]),source_config=original[0],
            source=source_path.relative_to(common.ROOT).as_posix(),SHA256=data.digest(source_path),
            reuse_scope='保存結果を引用。GU198と市場政策396の同値確認は新しい有効性証拠ではない。')
    configs=catalog.configs();source=common.sources();manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=data.digest(p)) for p in paths]
    spec=dict(entry=dict(conditions=configs,condition_count=18,
        gate='W60同代理。既知2票釣合い.25/.5/.75又は既知4票釣合い.5。未来最初気配で入口maskを消さない。',
        paper='元paper全feedの影5/10を維持。未約定でもpaper部分返済/全返済/次候補を進め、実qは実清算余力から再計算。'),
        management=dict(アンカー='最初受理q/公開ATR/spreadで利益線を一回固定、FAK未約定取消でも保持。後のfill又はqへ選び直さない。',
            不変='公開予定リスク1ATR＋spread＋注文別往復料。選択B5000/2000。実partial累積floor、最終残返済。'),
        exit=dict(純目標='P1=初受理q×観測T×倍率、ATR25=.25×初受理q×公開ATR×倍率。hardB5000/2000固定。',
            不変='元GU/静観/期限を維持、費用後場清算の初先着→次正常UID返済で場停止。',
            定義='新規のFAKだけ変更。固定返済理由94/95と主指標の完結親netは旧と同じ。'),
        allocation=dict(base_quantity=catalog.QUANTITY,direction_cap=catalog.CAP,quantity_selection_budget_yen=catalog.BUDGET,
            予約='予定qは公開時だけ固定、FAK失効は実UID/支払料/返済予約を作らない。後続qは元アルゴ通り。'),
        costs=dict(片道税込={'TOPIXmini':41.8,'NK225micro':11},円倍率=catalog.VALUE,
            課金='各実注文floor(qfee)、TOP209/5/NK11/1。未約定は0円。部分料・残UID料は相殺しない。'),
        execution=dict(FAK0='公開ask以下で買い／公開bid以上で売り。',FAK1='公開気配から不利1観測Tまで許す。',
            一回='公開後の最初goodだけ試し、価格内は当時BBO予定全量、外なら未約定失効。次の気配で同予約を復活させない。',
            順序='scheduled取消→旧queue返済→既pendingのFAK試行→当行paper。無効quoteは試行無し、途中paper撤回は旧取消。',
            不変='旧paperlineの意味は変更せず、FAKcapと試行は別19列へ保存。',
            限界='ラージ板の価格到達模型。実mini/microの待ち順位、部分FAK、真受信時刻は未測定。観測Tは実商品二呼値。'),
        data=dict(sessions=sessions,input_manifests=manifests,input_cache=old_fixed['input_cache'],reference_ledger_manifests=references,
            再利用='旧G25/G50/G75のP1/ATR25を各1読396台帳。pair198で七GU配列exact、市場6×66経済exact。旧GU再simulate0。',
            一次='根登録後input33各一読、新GU9route×66=594、新政策18×66=1188。既影paper再計算0。',
            診断='一次出力内でGU全候補と実政策接頭のFAK試行を分け、受理取消後のq/ATR持越しと昼夜の重複拒否タグを記録。',
            現在='時計不適合の現在ナイト不使用。原板/NPZ/API0。'),implementation=source)
    prepared=dict(id=catalog.TRIAL_ID,name='公開気配の一回FAKと少数票を切り分ける十八対照',purpose='新仮説',
        question='公開から初回正常気配までの価格悪化を拒否すると、避けた損失・失った勝ちと後参加はどう変わるか。',
        change='新規FAK0/1だけの執行差とmin4だけの票数差を、共通の二利益線で比較する。spreadguardは足さない。',
        repeat_reason='B01TOP唯一敗は公開ask4132.5から4133への買い悪化。旧B03無敗は二票7/15を含み、少数票と執行の部品を分ける必要がある。',
        compares_to=['104_E01同入口の出口尺度十対照と票強度及び価格応答六対照','106_E01予定リスク数量の初回受理目標アンカーP1P2四対照'],
        spec=spec,同bytesコピー=clones(),予定=dict(新条件=18,新GUengine=594,新政策会計=1188,保存GU再利用=198,
            旧市場台帳一読=396,旧基準経済同値確認=396,既input一読=33),
        未確定点=[],正式freeze=formal,登録=0,金融=0,実input読取=0,旧GU台帳読取=0,
        limitations=['価格capは広spreadの初期損失を制限しない。cap内の約定でも次返済でhard超過はあり得る。',
            'FAKで勝ちを捨てると実清算余力と後参加qが変わる。保存親削除や単純比例で成功を代用しない。',
            '最初受理が未約定でも、後のq/ATRへ場目標を交換しない。不整合が残れば別部品として次段で検証。',
            '旧GU198と396基準同値は再利用確認で、有効性の追加標本ではない。',
            'GU全feedの受理/試行診断には場利益停止後suffixが含まれる。実政策接頭と分けて表示する。'])
    if formal:
        import runner
        common.write('試行計画.json',prepared)
        common.write('金融事前固定.json',dict(全合格=True,sessions=sessions,configs=configs,input_cache=old_fixed['input_cache'],
            references=references,reference_mapping=mapping,reused_results=reused,source_SHA256=source,
            case_SHA256=runner.case_hashes(configs),計画SHA256=data.digest(common.HERE/'試行計画.json'),正式金融=0,実input=0,旧GU本文=0,API=0))
    else:common.write('試行計画草案.json',prepared)
    print('十八条件の'+('正式固定' if formal else '八部品草案')+'保存、実input/旧GU本文/金融0',flush=True)
