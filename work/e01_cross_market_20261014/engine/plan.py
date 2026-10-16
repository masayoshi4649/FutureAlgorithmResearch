"""十六対照と保存基準を八部品へ結び、根が確認後にだけ正式固定する。"""

import common
import catalog
import data


def clones() -> dict:
    """
    機能: 旧数量・執行・実料・保存集計の数学が同bytesの新所有複写であることを確認する。
    引数: なし。
    返り値: dict は旧参照pathとSHA256。旧moduleはimportしない。
    """
    old=common.ROOT/'work/wave_v106/e01_size_goal_anchor'
    names={'sizing_engine.py':'engine.py','order_kernel.py':'order_kernel.py','sizing_baseline.py':'baseline.py',
        'base_policy.py':'policy.py','daily.py':'daily.py','ledger_storage.py':'storage.py'}
    result={}
    for current,reference in names.items():
        path=old/reference;assert (common.HERE/current).read_bytes()==path.read_bytes(),current
        result[path.relative_to(common.ROOT).as_posix()]=data.digest(path)
    reuse_path=common.ROOT/'work/wave_v106/e01_size_loss_anchor/reuse.py'
    assert (common.HERE/'reuse.py').read_bytes()==reuse_path.read_bytes()
    result[reuse_path.relative_to(common.ROOT).as_posix()]=data.digest(reuse_path)
    return result


def prepare(formal: bool=False) -> None:
    """
    機能: 保存小JSONからinput33と旧CONFIRM P1台帳66の指紋を引用して計画を作る。
    引数: formal(bool) は根レビュー後の正式freezeか草案か。
    返り値: None。大型input/台帳・金融・登録を実行しない。
    """
    old=common.ROOT/'work/wave_v106/e01_size_goal_anchor';fixed_path=old/'金融事前固定.json';result_path=old/'finance/結果.json'
    proof_path=common.HERE/'十六対照と実行前拒否及び表示会計の人工検査.json'
    cause_path=common.HERE.parent/'diagnosis/同母二商品43実親の原因射影.json'
    fixed,result,proof=(data.read(p) for p in (fixed_path,result_path,proof_path))
    assert fixed['全合格'] and result['全合格'] and proof['全合格']
    assert result['source_SHA256']==fixed['source_SHA256'] and result['source開始終端一致']
    assert proof['source_SHA256']==common.sources()
    before=result['results'][catalog.BASELINE_ID];sessions=fixed['sessions']
    assert len(sessions)==33 and len(before['rows'])==len(before['ledgers'])==66
    keys={(s,t) for s in sessions for t in catalog.QUANTITY}
    assert {(r['session'],r['symbol']) for r in before['rows']}==keys
    refs={r['session']+'|'+r['symbol']:r for r in before['ledgers']};assert len(refs)==66
    assert set(fixed['input_cache'])==set(sessions)
    manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=data.digest(p)) for p in (fixed_path,result_path,proof_path,cause_path)]
    configs=catalog.configs();source=common.sources()
    spec=dict(entry=dict(conditions=configs,condition_count=16,
        共通='元E01 D0、W60既知方向票二以上・意図側釣合い.25以上。数量予約は公開ATR＋spread＋料から旧B内最大整数q。',
        強度='Bは同代理釣合い.5又は.75。Cは旧.25に保存normal十秒端点の自己又は相手両気配一呼値順行を追加。',
        全feed='B/C四maskは元paper後続feed全てを実行。旧親を削るだけで数量・busy・再参加の成功を代用しない。'),
        management=dict(アンカー='最初受理q・公開ATR・spreadで場の利益/損失/保全線を一回固定。受理取消でも保持。',
            清算='前親実現・発動前部分返済・現在保有・全実料・残UID返済料を含む場口座清算。親事後最大益を使わない。',
            保全='当時までの正常行清算高水準で保護線=max(0,peak-draw)を有利側のみ更新。発動後戻りの初先着で場停止。'),
        exit=dict(尺度='R=初受理q×公開ATR×円倍率。公開費用=初受理q×公開spread×円倍率＋二注文floor料。',
            十対照='純利確.125/.25/.5R、観測一呼値粗益−往復料、旧P1に.25/.5R+公開費用hard、.25R目標+.5R費用hard、三高水準保全。',
            六入口対照='強度二つ×旧P1又は.25R、自己/相手十秒価格応答×旧P1、いずれもhardB。',
            不変='元GU/静観/期限も維持。初先着後は次正常BBOで残UID全返済、場の以後新規なし。',
            理由='固定利確94、固定損失95、保全走査からの合成返済96。96がhard発動でもcontrol.種別=損失予算で区別。'),
        allocation=dict(base_quantity=catalog.QUANTITY,direction_cap=catalog.CAP,quantity_selection_budget_yen=catalog.BUDGET,
            不変='影5/10、実q最大5/10、partial累積floor、最終残返済。新目標を数量選択Bへ戻さない。'),
        costs=dict(片道税込={'TOPIXmini':41.8,'NK225micro':11},円倍率=catalog.VALUE,
            課金='注文別整数floor。TOP209/5・NK11/1、UID返済は相殺しない。主指標は完結親net、決済玉は副表。'),
        execution=dict(モデル='公開後最初正常ask/bidでD0新規、退出判断後次正常BBO。既知静観/期限取消優先。',
            C端点='自己end当行、start時計<=t−10の最後normalかつ前seq。peerend時計strict<tの最後normal、peerstart<=t−10。各基準age及びpeerend age<=15。',
            限界='Cは保存normal端点応答。消えたraw中間経路/全reset/物理受信先後未保証。価格時計は真受信時刻ではない。観測Tはラージ.5pt/10円で実mini/micro二呼値。'),
        data=dict(sessions=sessions,input_manifests=manifests,input_cache=fixed['input_cache'],baseline_ledger_manifest=refs,
            読取='根登録後input33各一読、旧CONFIRM P1台帳66各一読で旧GU七配列と同親比較を共有。原板/NPZ/現在API0。',
            再利用='旧基準P1は全66経済exact確認。旧GU66は追加有効性証拠に数えず、B/C264だけ新GU全feed再生。'),
        implementation=source)
    prepared=dict(id=catalog.TRIAL_ID,name='E01の銘柄差を出口尺度と入口応答で分ける十六対照',purpose='新仮説',
        question='費用後黒字へ届かない敗けと利益返しを、共通尺度の出口及び公開時入口応答の別部品で改善できるか。',
        change='入口固定の出口十、元出口に票強度/価格応答を足す六。候補値は43親の原因と反証から結果前固定。',
        repeat_reason='TOP負け七親中六/NK負け二親は費用後黒字無し、基準損失予算停止0。狭いloss線だけを直接敗因の修正と説明しない。',
        compares_to=['106_E01予定リスク数量の初回受理目標アンカーP1P2四対照'],spec=spec,同bytesコピー=clones(),
        予定=dict(新条件=16,保存GU再利用=66,新GUengine=264,新政策会計=1056,旧P1台帳一読=66,既input一読=33,旧基準経済同値確認=66),
        未確定点=[],正式freeze=formal,登録=0,金融=0,大型入力読取=0,台帳読取=0,原板=0,NPZ=0,API=0,
        limitations=['利確を小さくすると費用後黒字前の敗けを救えず、大勝ちを減らす可能性がある。',
            'highwater保全は非黒字の六/二敗けへ発動できない。利益前損失対策とは別仮説。',
            '受理後取消でも元q/ATR/spreadを保持。後参加が大きい場合も停止線を有利に選び直さない。',
            '公開費用込みhardは実fill後の損失保証ではない。次正常気配・部分返済の料で超過し得る。',
            '入口maskの包含は実取引集合の包含ではない。全33で失うwinnerと新参加の赤字も比較。'])
    if formal:
        import runner
        common.write('試行計画.json',prepared)
        common.write('金融事前固定.json',dict(全合格=True,sessions=sessions,configs=configs,input_cache=fixed['input_cache'],
            baseline=dict(id=catalog.BASELINE_ID,rows=before['rows'],symbols=before['symbols'],ledgers=refs,
                source=result_path.relative_to(common.ROOT).as_posix(),SHA256=data.digest(result_path)),
            source_SHA256=source,case_SHA256=runner.case_hashes(configs),計画SHA256=data.digest(common.HERE/'試行計画.json'),
            正式金融=0,大型入力=0,台帳=0,原板=0,NPZ=0,API=0))
    else:common.write('試行計画草案.json',prepared)
    print('十六対照の'+('正式事前固定' if formal else '八部品草案')+'保存、金融0',flush=True)
