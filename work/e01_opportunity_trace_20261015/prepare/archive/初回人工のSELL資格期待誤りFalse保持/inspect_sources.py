"""許可されたsourceだけの契約調査を指紋へ結び、旧金融・入力本文を読まない。"""

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE_PATHS=(
    'AGENTS.md','アルゴリズム調査/調査方針.md',
    'アルゴリズム調査/共通/知見台帳/README.md','アルゴリズム調査/共通/知見台帳/入口.md',
    'アルゴリズム調査/共通/知見台帳/継続.md','アルゴリズム調査/共通/知見台帳/出口.md','アルゴリズム調査/共通/知見台帳/売買の工夫.md',
    'work/wave_v103/input/core.py','work/wave_v103/input_v2/correction.py','work/wave_v104/holdout_input/core.py',
    'work/wave_v106/trade_gate/votes.py','work/wave_v106/e01_trade_gate/votes.py',
    'work/wave_v106/e01_trade_gate/prepare.py','work/wave_v106/e01_trade_gate/data.py',
    'work/wave_v106/e01_trade_exit/votes.py','work/wave_v106/e01_trade_exit/features.py',
    'work/wave_v106/e01_trade_exit/prepare.py','work/wave_v106/e01_trade_exit/data.py','work/wave_v106/e01_trade_exit/rebind_input.py',
    'work/wave_v106/e01_pending_price/prices.py','work/wave_v106/e01_pending_price/prepare.py',
    'work/wave_v106/e01_reference/prepare.py','work/wave_v106/e01_reference/bridge.py','work/wave_v87/round10/strategy.py',
    'work/e01_fak_evidence_20261014/engine/common.py','work/e01_fak_evidence_20261014/engine/data.py',
    'work/e01_fak_evidence_20261014/engine/price_votes.py','work/e01_fak_evidence_20261014/engine/entry_gate.py',
    'work/e01_fak_evidence_20261014/engine/core.py','work/e01_fak_evidence_20261014/engine/interface.py',
    'work/e01_fak_evidence_20261014/engine/ledger_storage.py','work/e01_fak_evidence_20261014/engine/catalog.py')


def fingerprint(relative: str) -> dict:
    """
    機能: 明示sourceのSHA256と関数又は列宣言位置を保存する。
    引数: relative(str) は許可されたroot相対source又は共通知見MD。
    返り値: dict は指紋と行番号。cache/JSON/NPZを読み込まない。
    """
    assert relative in SOURCE_PATHS
    path=ROOT/relative;assert path.suffix in ('.py','.md')
    saved=path.read_bytes();text=saved.decode('utf-8-sig')
    anchors={}
    for line,row in enumerate(text.splitlines(),1):
        stripped=row.strip()
        if stripped.startswith(('def ','FIELDS=','FLOAT_FIELDS =','DEPTH_FIELDS =','BOOL_FIELDS =','REASON_FIELDS =')):
            key=stripped.split('(')[0].strip();anchors[key]=line
    return dict(SHA256=hashlib.sha256(saved).hexdigest(),anchors=anchors)


def run() -> None:
    """
    機能: source契約と非金融の段階別診断案を新prepare領域へ保存する。
    引数: なし。
    返り値: None。新アルゴ/金融/試行登録又は大型入力を実行しない。
    """
    target=HERE/'source契約と非金融機会診断の準備案.json';assert not target.exists()
    before={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'work/e01_fak_evidence_20261014/engine').glob('*.py')}
    refs={name:fingerprint(name) for name in SOURCE_PATHS}
    votes=('work/wave_v106/trade_gate/votes.py','work/wave_v106/e01_trade_gate/votes.py','work/wave_v106/e01_trade_exit/votes.py')
    assert len({refs[p]['SHA256'] for p in votes})==1
    value=dict(全合格=True,状態='SOURCE_ONLY。schema宣言を確認、実cache完成内容/機会/効果は未測。',
        公開候補='00112_元の公開時点と継続中の参加機会の診断（番号確定は根担当）',source=refs,source111開始終端=before,
        source同値=dict(corrected_volume_votes_三領域同bytes=True),
        保存素材=[
            dict(id='TradeGate33',manifest='work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json',
                accounts=['symbol','record','quotes','feed','quiet','quiet_force','quiet_windows','paper_SHA256','mapping','trade_features'],
                record=['price','seq','time_s','start','end','limit','tick'],quotes=['bid','ask','quote_valid','seq','time_s'],
                volume_scope='10/30/60秒のfeed[:,7]==1公開rowのみ。raw/ΔV/量/時計/reset系列を捨てる。',
                remeasure_all_normal_alone=False,depth_qty=False,received_clock=False),
            dict(id='TradeExit33',manifest='work/wave_v106/e01_trade_exit/全33場の保有中取引更新票.json',
                source_rebind='work/wave_v106/e01_trade_exit/非有限clock系譜修正と完成全33入力の同値補完.json',
                accounts=['symbol','record','quotes','votes'],
                votes=['known','reason','up_votes','down_votes','balance','reference_raw_row','first_vote_raw_row','candidate_raw_row','candidate_raw_seq','candidate_price_time_s'],
                windows=[10,30,60],volume_scope='全normal行。balanceはunsigned、当時paper sideを一度掛ける。全raw票表ではない。',
                feed_or_quiet=False,depth_qty=False,received_clock=False,
                freshness='first_vote_raw_rowは窓始の原行境界。最後の実方向票seq/時刻は未保存、現在窓適格とdistinct新根拠を混同しない。'),
            dict(id='SourceWindows',source='work/wave_v106/e01_pending_price/prices.py:windows/account',
                scope='first公表の端点価格差とraw時系列不正prefix。全normalのLast/両BBO経路・ΔV・量・深板を代替しない。'),
            dict(id='原行NPZ66',manifest='work/wave_v106/trade_gate/入力測定前の固定_v2.json:raw_inputs',
                source='103v2（旧32）又は104holdout_inputで同correct_arraysを適用した44列',
                exact_votes_minimum=['raw_seq','price_time_s','last','bid','ask','volume_delta','volume_delta_usable','volume_reset_reason'],
                normal_map='execution_to_raw_index',
                quality_audit_additions=['volume','volume_time_s','volume_delta_observed','volume_delta_known','price_reset_reason','volume_value_valid','volume_time_valid','volume_in_session','volume_time_not_after_price'],
                depth=['bid_prices[N,10]','bid_quantities[N,10]','ask_prices[N,10]','ask_quantities[N,10]','bid_element_valid[N,10]','ask_element_valid[N,10]','best_quantity_valid','depth_valid'],
                other_clocks=['volume_time_s','trading_value_time_s'],received_at='存在boolのみ。値/共通受信連番は無い。')],
        必須結合検査=[
            'TradeGateとTradeExitのsession/symbol及びrecord/quotesのseq/time/Last/BBO/資格全一致。normalrow番号だけでjoinしない。',
            'candidate_raw_row == TradeGate.mapping、candidate_raw_seq == record.seq、candidate_price_time_s == record.time_sを全行照合。',
            '全PUB rowでは同corrected votesのknown/reason/up/down/countとpaper side×unsignedbalanceを公開signed票へ一致。known総票0はNone/NaNを区別、unknownのdebug票を採用しない。',
            'TradeExit最終manifest/原入力source署名/非有限clock補完を確認。archive旧metadata単独を正式源としない。'],
        公開制御=dict(feed_columns=['公開normal_row','元判断row','paper_CID','side','paper_qty','公開Last','paper_reason','new_flag','role','初回公開ATR'],
            origin='feed新規rowで一回だけ。拒否/busy/失効後の継続方向を再審査0。',
            first_reject_priority=['予定静観/場停止/期限','actual held/pending/exit予約 busy','同行paper撤回','start+300及びlimit−300資格','現在normal/Last/ATR不正','入口情報資格','公開spread＋往復料余裕'],
            first_reject_codes=[92,93,161,162,94,151,153,96,95,154],
            multiple_flags='未知/不足票/釣合い/spread等の重なりは別併記。最初のreasonを唯一原因としない。',
            fixed_qty='111は10/20固定。旧risk sizingのqty0をこの機会不足へ混ぜない。',
            FAK='公開cap固定→最初goodquoteで1回fill/失効。timer取消はfill前、未知quoteなら待機、後の好価格で同予約復活なし。',
            source_curve='equity/liquid/local/peak/long/short/paid/reserve/actualCID/sceneStop/sceneGoal/paperCID/方向/paper残量の14列。',
            exact_busy='record/flowだけでactual忙しい状態を確定できない。PUB/執行/判断/曲線の保存台帳参照が別許可された場合だけ接頭から再構成。'),
        指標算定可否=[
            dict(id='SMA/EMA',minimal='normal Last又はmidとPriceTime/seq',status='算術可能、期間/価格/完成足/asof/欠測の定義は未固定。',
                caution='同clock多normalを行数で平均すると更新密度の重み。未知区間を未来点で埋めない。形だけの売買0。'),
            dict(id='セッション高安/既知支持抵抗',minimal='当時までの正常Last/両BBO',status='当時走査高安は可能。過去セッションは別固定の入力許可が要る。',caution='未来の戻りでpivot認定0、新最高から形の予測0。'),
            dict(id='VWAPproxy/参加コストproxy',minimal='raw Last＋usableΔV、又はTradingValue/Volumeと各時計/単位',status='TradeGate/Exit cacheだけでは量が無く不可。NPZには必要候補列を宣言。',
                formula='sum(Last×usableΔV)/sum(usableΔV)は集約増分をLastへ配賦した代理。TradingValue/Volumeは単位・範囲・時計検査前にVWAPと断言しない。',
                caution='真の保有玉平均コスト/参加主体/損益心理/買売攻撃量は復元不可。表示板qtyは約定volumeではない。'),
            dict(id='水準と注文集中',minimal='当時水準＋新flow＋BBO価格/表示数量の反応＋二市場の当時方向',status='仮説のみ。実注文の集中や心理は未測。',caution='SMA/EMA/VWAPproxyだけ又は5/15min形だけで採否を決めない。')],
        後の読取案=dict(段階1='TradeGate33とTradeExit33を各一目的1読、選択111 SEL_TARGET台帳66は別授権されれば各1読。金融再生0。',
            段階2='distinct fresh方向票/量加重/深板/clock原因が必要なら修正NPZ66の必要列を一読射影。原book/API0。',
            集計分母=['元PUB候補','paper方向継続区間','normal観測行','連続適格区間'],
            注意='normal行数を独立参加機会/取引勝率にしない。現支持の成立は実約定/費用後成功ではない。',
            観測手順=['元公開を理由/重複flagで分解','firstgoodQuote/取消/失効を原seqと価格proxy時計で照合','継続paper方向中の現在flow/peer資格を時系列射影','忙しい/場停止/静観を別stateとして分類','当時までの水準とquote反応を併記'],
            純人工予定=['同clock未来seq排除','peer strict過去','PUB signed対全normal unsigned一致','unknown/debug票区別','旧PUB値持越し無し','static表示数量と約定増分の区別','busy/初回失効/取消接頭','指標未来suffix不変']),
        事後ラベル=[
            dict(session='2026-09-21_Day',time='10:45',direction='long'),dict(session='2026-09-22_Day',time='09:20',direction='short'),
            dict(session='2026-09-23_Day',time='09:05',direction='short'),dict(session='2026-09-22_Night',time='00:40',direction='long')],
        ラベル制限='ユーザー指定波の診断ラベルのみ。入口へ日付/時刻/方向をハードコード0。Nightは場名と暦日を分け、proxy時計で翌日該当を確認するまで決め打ちしない。',
        未測仮説='頭尻尾を当てず、現在のflowとquote反応が当時水準を受け入れ、二市場が共通方向を示す波の中間でfresh根拠を使う。00108価格PULL/BREAKの粗赤字を同じまま再金融しない。',
        goal=dict(TOPIX='全セッションnet算術平均100000円＋金額比65/赤字20/最大赤字<=平均黒字',NK225='旧三基準、円額床未指定'),
        実行=dict(source契約のみ=True,大型本文=0,cache=0,packet=0,NPZ=0,金融本文=0,元ledger=0,金融=0,API=0,試行登録=0,公共共通編集=0),
        未完了='実cacheの同source/同列一致・機会数・新参加の有効性は未測。根の目録/人工署名/一読scope確定まで本文reader又は新アルゴを作らない。')
    after={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'work/e01_fak_evidence_20261014/engine').glob('*.py')}
    assert before==after and len(before)==17
    value['source111不変']=True
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('SOURCE_ONLY契約 '+str(len(refs))+'資料、111源17不変、大型本文/金融/API0。SHA '+hashlib.sha256(target.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':run()
