"""新規の価格反発と自動選択を、金融前の八部品へ具体的に固定する。"""

import catalog
import common
import prepare


def differences() -> dict:
    """
    機能: 既公開レンジ研究をsource/READMEで照合し、新仮説との重複と差分を残す。
    引数: なし。
    返り値: dictは旧三研究の根拠と相違。金融再生や結果選定は行わない。
    """
    entries=[
        ('00086_二市場の状態で追従と指値反発を配分','work/wave_v90/catalog.py',
         'O06は基準8呼値から片側指値、1幅停止/3幅目標。二市場の全経路ERと10秒確認を使いJ2と配分。',
         'R_PRICEはfirst公表の6点価格だけで当時往復を定義し、実BBOの範囲内境界反発と固定中心/範囲外停止を使う。固定8呼値指値階段/10秒確認ではない。'),
        ('00089_予定リスクと中心利確及び失敗後再参加','work/wave_v93/catalog.py',
         '旧180秒中心と停止余地を審査。C05は中心対リスク2倍、C06は中心固定、C11は双方中心帰還で再参加。',
         '6点300秒sampleと純価格資格へ分離。旧板R_OWN段階を待たず1tick両quote反発で候補生成。丸め中心と範囲外停止から料込1.25倍、現mid範囲内を要求。'),
        ('00095_現在方向の価格源を分ける待機検証','work/wave_v99/catalog.py',
         '元P0候補を固定しBBO中値/独立Lastの現在支持源と待機政策を比較。range_budget=0。',
         '価格源の置換ではなく、二市場RANGEの新候補を作る。R_ONLYとRANGE先AUTOを比較し保有後のモード返済は入れない。')]
    rows=[]
    for folder,source,old,new in entries:
        paths=[common.ROOT/'アルゴリズム調査'/folder/'README.md',common.ROOT/source]
        rows.append(dict(元調査=folder,旧仕様=old,今回の差分=new,
            evidence=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=common.digest(p)) for p in paths]))
    return dict(全合格=True,照合範囲=rows,全歴代網羅=False,金融再生=0,
        新仮説='遅い板補充episodeの不発又は中心近傍で余地不足を、価格境界の初反発と事前料込RRへ置換する。改善成功は未検証。')


def specification() -> dict:
    """
    機能: 経済八部品を、24条件の境界と同row順序まで説明する。
    引数: なし。
    返り値: dictはentry/management/exit/allocation/costs/execution/data/implementation。
    """
    fixed=common.read(common.HERE/'価格境界反発の入力事前固定.json')
    implementation=dict(fixed['source_SHA256'])
    for p in [common.HERE/'plan.py',common.HERE/'interface.py',common.HERE/'engine/core.py',common.HERE/'engine/legacy_core.py']:
        implementation[p.relative_to(common.ROOT).as_posix()]=common.digest(p)
    return dict(
        entry=dict(condition_count=24,conditions=catalog.catalog(),
            offsets_seconds=[300,240,180,120,60,0],
            publication='新最大CurrentPriceTimeのfirst原行。自己公表<=判断原行、相手公表clock<自己clock。各点は要求時刻以前最新、age<=15。',
            price_qualification='六端点finite正bid/ask・ask>bid・場内finite価格clock。端点間から候補末尾まで原seq連続かつ既知priceclock highwater逆行なし。量/出来高fullqualified・混合reset・公表価格gap・途中非normalBBOを価格差の資格へ混ぜない。',
            range='二市場とも6点ER<=0.2又は0.4、6点span>=4呼値。ER=abs(last-first)/sum(abs(diff))、TV=0はRANGEにしない。',
            buy='当時sampleLow<=現在mid<=Low+0.25spanかつ現在bid/askが直前正常quoteよりともに1呼値以上上がる。',
            sell='High-0.25span<=現在mid<=sampleHighかつ現在bid/askが直前正常quoteよりともに1呼値以上下がる。',
            rr='判断時の買target=floor(centre/tick)、売target=ceil。買stop=floor((Low-margin)/tick)、売stop=ceil((High+margin)/tick)。margin1/2/4呼値。予定entryからstop余裕>=2呼値、料金後target利益>=1.25*(料金込初期損失)。',
            modes='R_ONLYはRだけ。AUTOはRANGE先に同R、その他二市場5分同方向>=2bpのTRENDのみ元C_OWN pulseを同方向に使う。UNKNOWN/NEUTRALは新規なし、R余地不足をCへ救済しない。',
            C='元normal event/support/quality/reset/選択支持roots/episodeをexact保持。未選択又は予約保有中に過ぎたCpulseを後で復活しない。'),
        management=dict(single_position=True,additions=False,cooldown_seconds=30,
            pending='一方だけ予約/保有。Rmarketは次正常quote、Rlimitは公開時buybid/sellask固定。未知は待つ。未約定時knownTREND又は清算側quoteの固定stop破れで永久取消。旧板仮想期限は使わない。',
            quiet='全条件J:08:45包含～09:15除外。静観開始の既知timerで予約取消/保有返済。米国静観は追加しない。',
            order='J/entrycut/force予定取消を先に、次に既live成行nextq/到達指値をfill。未fillの場合だけ同rowTREND/stop取消。実fill後を架空取消しない。',
            repeated='反発の実原seqを価格候補episodeとする。保有/予約/休止中の候補は当行消費、後へ持越さない。'),
        exit=dict(R='fill後は固定stop/target/forceのみ。TRENDモード変化だけでは返済しない。fillがstop外又はtarget到達なら当行判断し次正常quote返済。',
            C='元B4:固定支持4呼値と始値0.1%保険の有利側、始値0.4%広追尾。追加条件なし。',
            start_offset_seconds=300,entry_cut_offset_seconds=300,force_offset_seconds=60,
            finish='全玉をセッション内返済。時価評価に残返済料を含め、人工終端価格で救済しない。'),
        allocation=dict(products=dict(TOPIX='TOPIXmini',NK225='NK225micro'),
            entry_quantity=dict(TOPIX=5,NK225=10),cap_per_direction=dict(TOPIX=10,NK225=20),
            simultaneous_C_R=False,portfolio=False,
            C_ONLY_comparison='完成regime_priceのC_ONLY2bp/ER0.2・0.4/B4を量10/20から5/10へ派生。同prices/全order数量整数半分、料金TOP418->209/NK440->220。独立金融成功に数えない。'),
        costs=dict(per_contract_oneway=dict(TOPIX=41.8,NK225=11),per_order='各注文floor(quantity*片道料)。新規/返済双方。',
            multipliers=dict(TOPIX=1000,NK225=10),J_NET='立会料のみ',spread='買ask/売bidの実執行に含める'),
        execution=dict(MARKET='公開当行禁止。判断後の次正常ask/bidで実新規。',
            LIMIT='公開当行禁止。固定buybid以下のask又はsellask以上のbidへ最初到達、実live quote改善価格。',
            exit='最初の停止/目標到達判断後、次正常清算quote。次quoteのギャップを停止価格で約定した事にしない。',
            delayed_worst='追加5秒最悪約定は今回追加しない。待ち順位/実mini/micro板全量約定は未検証。'),
        data=dict(sessions=fixed['sessions'],
            input_manifests=[dict(path='work/wave_v106/range_price/価格境界反発の入力事前固定.json',sha256=common.digest(common.HERE/'価格境界反発の入力事前固定.json'))],
            known='全33場既知。追加未見検証0。旧104rawpacketと確定純価格v2preparedを各場各1読取、book/API0。',
            cached='同first価格時計6点は共有するが、当時rawrow上限/末尾highwater/seq/実BBO反発/現在範囲/RRは各normal行再審査。'),
        implementation=implementation)


def run() -> None:
    """
    機能: 結果前の差分資料と八部品草案を所有域へ新規保存する。
    引数: なし。
    返り値: None。正式登録と金融は別段階、ここでは始めない。
    """
    evidence=differences();common.write(common.HERE/'過去レンジ手法との相違.json',evidence)
    plan=dict(id=catalog.TRIAL_ID,name='範囲内の境界反発と二市場進行を自動選択する24対照',purpose='新仮説',
        question='板回復episodeの待機による不発/中心余地不足を、純価格境界の反発と料金込予定RRへ置換すれば活動と毎場の安定性を改善するか。',
        change='R_OWNの元板入口を使用しない新R_PRICE。R_ONLY12と同12AUTO、C_OWN入口/支持はexact。',
        repeat_reason='旧レンジ中心利確との差を先に確認し、原板量と価格観測資格を分離した新候補を結果前固定。',
        compares_to=['106_第六段階_旧基準参照ID修正後の純価格26再開'],
        prior_similar=evidence['照合範囲'],
        sacrifices=['6点間の全経路レンジ保証なし。','真の受信時計不明。','料金RRは次quote実fillのRRを保証しない。',
            'RANGE内でも幅/余地不足は新規しない。無取引は勝ちに含めない。',
            '大勝ち依存を避ける基準:中央値、上位3利益場除外、赤字場率/最大赤字を両商品別に判定。'],
        evidence=[dict(path='work/wave_v106/range_price/過去レンジ手法との相違.json',sha256=common.digest(common.HERE/'過去レンジ手法との相違.json'))],
        spec=specification(),状態='sourceと人工/入力事前固定。正式全normal可用性とengine結合人工の後に最終manifestを追加し登録する。金融未開始。')
    common.write(common.HERE/'試行計画草案.json',plan)


if __name__=='__main__':run()
