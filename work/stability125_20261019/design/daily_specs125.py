"""保存済み会計と公開時点の小診断から、日次参加の未実行比較案を固定する。"""

from datetime import datetime,timezone,timedelta
import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def load(relative: str) -> tuple[dict,dict]:
    """
    機能: 明示した保存結果JSONだけを同一性付きで参照する。
    引数: relative(str)はrepo相対位置。
    返り値: tuple[dict,dict]は保存内容と位置・SHA256。原市場や価格配列を使用しない。
    """
    raw=(ROOT/relative).read_bytes()
    return json.loads(raw.decode('utf-8-sig')),dict(path=relative,sha256=hashlib.sha256(raw).hexdigest())


def main() -> None:
    """
    機能: 旧知見と公開三候補を整理し、数量を飾らない日次参加3案を保存する。
    引数: なし。
    返り値: None。利益目標の達成判定・新金融・原板読取・試行登録は行わない。
    """
    old,old_ref=load('work/stability119_20261017/v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json')
    new,new_ref=load('work/stability124_20261019/e01c/追加一場の固定少額E01二商品.json')
    assert old['全合格'] and new['passed']
    candidates=[]
    for account in new['accounts']:
        fak={int(r[3]):r for r in account['fak_events'] if int(r[1])==1}
        for key,g in account['gate_diagnostics'].items():
            event=fak[int(key)];v=g['vote'];stamp=v['candidate_price_time_s']
            candidates.append(dict(symbol=account['symbol'],side=g['side'],normal_row=int(key),
                raw_seq=v['candidate_raw_seq'],JST=datetime.fromtimestamp(stamp,timezone(timedelta(hours=9))).isoformat(),
                bid=event[7],ask=event[8],up_votes=v['up_votes'],down_votes=v['down_votes'],
                direction_votes=v['direction_votes'],signed_balance=v['balance'],old_threshold=g['threshold'],
                original_gate_accept=g['accepted'],original_gate_reason=g['reason'],
                threshold_0_gate_accept=v['known'] and v['direction_votes']>=2 and v['balance']>=0,
                threshold_025_gate_accept=v['known'] and v['direction_votes']>=2 and v['balance']>=.25,
                threshold_05_gate_accept=v['known'] and v['direction_votes']>=2 and v['balance']>=.5,
                quantity_if_changed=None,fill_if_changed=None,net_if_changed=None,
                missing_at_publication=['ATRとリスク数量の公開値','同時点の相手市場価格・票の独立小診断','公開後の現在根拠更新'],
                reason='original planned_qty=0はゲート拒否の結果で、閾値を変えた場合の枚数・約定を意味しない。'))
    assert len(candidates)==3 and sum(r['threshold_0_gate_accept'] for r in candidates)==2
    rows=old['rows']+new['rows'];dates=sorted({r['session'][:10] for r in rows})
    activity={s:dict(label_days=len(dates),active_label_days=len({r['session'][:10] for r in rows
        if r['symbol']==s and r['campaigns']>0}),active_sessions=sum(r['campaigns']>0 for r in rows if r['symbol']==s),
        sessions=sum(r['symbol']==s for r in rows),campaigns=sum(r['campaigns'] for r in rows if r['symbol']==s))
        for s in ('TOPIX','NK225')}

    # ----------------------------------------
    # 仮説と既測定を分け、数量・頻度・目標変更を方向予測の改善へ読み替えない。
    differences=[
        dict(fact='少額E01は低活動でも合計黒字',evidence='00119→00124',
            measured='旧40のTOPIX10黒0赤30無＋9596円、日経24黒1赤15無＋5286円。追加10/19は両無取引。',
            mechanism='強い更新票ゲート・公開ATRで小数量・一ラージ呼値の場純益目標・達成後場停止の複合。',
            not_proven='ゲート単独の因果効果、全日参加したときの方向精度、数量増加や0.5%目標への性能保持。'),
        dict(fact='高頻度の利益玉回転は玉勝率が高くても場全体赤字',evidence='00120',
            measured='ONCEのTOPIX735/800勝玉・29黒11赤で−479600円、日経1484/1598勝玉・25黒15赤で−483356円。',
            mechanism='細かい勝ちを外し、不利在庫を最後まで残す。失敗後再参加型では途中損切りの累積も増える。',
            not_proven='全ての利益回転・全ての両建てが不可能だという一般命題。'),
        dict(fact='利益を引けまで残しても方向差が不利なら固定損が残る',evidence='00122〜00124',
            measured='124 TOPIX3/3は10:10:25に買10売10、買平均4040.20／売平均4029.85で−103500円の建値差固定。',
            mechanism='同枚数両建て後は共通価格変化による損益が相殺される。単に利確を延ばすだけでは不利差を修復しない。',
            not_proven='一方向の保有を伸ばすこと自体の否定。'),
        dict(fact='広い方向条件や系統の多数決も両商品で安定しなかった',evidence='00119 初回・改善3',
            measured='選択後13場の選択単体はTOPIX−1017572円／日経−369680円。順逆・時間回避48政策の両商品合計黒字0。',
            mechanism='直前の進行が公開後も続く保証はなく、異なる入口名でも同時刻・同方向へ重なった。',
            not_proven='共同方向を見る情報が無価値ということ。入口と継続の条件を分けた新対照は必要。'),
        dict(fact='M3の旧初期成功は新しい費用後基準の証拠ではない',evidence='00014・00016・00017',
            measured='00016初回11場・固定1枚はTOPIX＋206000円／日経＋26000円。ただし費用0・指定価格約定の旧仕様。',
            mechanism='後の長期下落＋回復で方向撤回と出口の弱さを診断している。',
            not_proven='現データ41場・気配・料金を含む性能。旧金額を数量倍して新目標へ到達したとはしない。'),
        dict(fact='前場IVは方向予測ではなく場の荒さの粗い尺度',evidence='00124',
            measured='IV既知11場でもO00/O01は両商品5黒6赤。O01の改善差は追加1場だけ。',
            mechanism='エントリー間隔や数量は変えられるが、上昇か下落かの当たりを作ってはいない。',
            not_proven='IVと板を受信時刻付きで組み合わせる新情報の有効性。'),
    ]
    shared=dict(status='未実行の設計。登録・人工・金融は未着手。',
        unresolved=['0.5%の分母','1日の区切りとDay/Nightの合算方法','両商品それぞれの最低参加かどうか'],
        quantity='比較設計の仮数量は初回TOPIXミニ5枚／日経マイクロ10枚（旧片方向上限の50%）。上限は10／20。飾り1枚・数量0で頻度を満たさない。確定回答後に正式固定。',
        daily_state='対象日開始→参加前→新規予約→実約定→管理→全返済→当日終了。日内の実新規回数は約定数量>0で計数。',
        observation='保存された原行順と価格時計の過去だけ。相手は厳密過去・age5秒以内の正常Last/BBO。未知を買い/売りの根拠へ補完しない。',
        fallback='対象日の初回対象セッションで開始+105分まで実新規0なら、最初の正常かつ狭い気配で初回数量を一回成行予約。買方向/売方向は両市場の開始後価格変化を各現在までの高安幅で割った平均の符号。同点は自己の直近非零Last変化、それも無ければ日付偶奇の固定対照方向。',
        fallback_caveat='これは日次必須を満たすための独立した強制参加部品で、方向予測の優位を主張しない。低確度を理由に再び数量0へ落とさず損失も全部計上する。日内に正常・狭い気配が無ければ実約定保証は不可能で、達成失敗として明示。',
        execution='判断原行より後の最初の正常quoteで買ask/売bid。手数料は実数量の注文別切捨て。実小型板・真受信時計・待ち順位は未観測。',
        exit='全案の初期比較では初回建値から価格0.1%逆行で撤回、0.1%順行後は建値を最低線にし最高順行から0.1%戻りで返済予約。値幅・約定は観測刻みへ不利側に丸める。場末全返済。0.5%目標の分母確定までは利益達成判定へ使わない。',
        retry='一取引の完結後、同じ初回失敗を連打しない。新しい共同方向の撤回→再成立が必要。当日損失上限と再開回数は目標分母の確定後に固定。',
        option='当場IVの時刻補完は使わない。前場IVは方向と独立した数量・幅の追加対照に限り、最初の方向モデル選別へ混ぜない。')
    proposals=[
        dict(id='P125_A',name='E01を残し、方向票は多数派だけ要求する',
            simple='二市場で一致した元E01の候補に、直近更新が少なくとも逆優勢でないとき参加する。強い偏りだけを待たない。',
            entry='元E01_G_Uの新公開でknown、direction_votes>=2、signed_balance>=0。従来のTOP.5/NK.25から両商品共通0へ一部品変更。',
            management='実建値からの同じ保険停止・追尾を使い、元paper方向撤回でも返済。元の小円P1場目標は外して新利益目標定義へ接続する。',
            sources=['00119_戦略の自動選択と場内黒字の再探索','00124_追加セッションと日経オプションの検証'],
            change='入口ゲートの強度、小数量/小目標、日次未参加の三つを同時に成功扱いしない。ゲートだけの対照と数量・出口の対照を別々に置く。',
            why_retry='124で候補は存在したが全件ゲート201拒否だった。頻度変更の直接対象を特定できたため。',
            expected_failure='弱い多数派が単なる往復に過ぎず、受理を増やすほど逆行と費用が増える可能性。',
            not_new='過去00104〜00111の入口強度・価格制限系列と同家族。元ゲートを再提案しただけではない。'),
        dict(id='P125_B',name='公開時に弱くても、根拠が揃い直した瞬間に参加する',
            simple='一度見送った候補を放置せず、その方向が生きている間に現在の売買の偏りと実価格の進行を取り直す。',
            entry='同じE01 paper方向区間中、現在60秒方向票known・2票以上・signed_balance>=0、両市場の過去10秒Last変化が同方向かつ各1ラージ呼値以上進んだ最初の原行で公開。相手はstrict過去・age5秒以内。',
            management='候補はpaper方向撤回で失効。受理後は実建値の保険停止・追尾。公開の根拠を保有中へ永久固定しない。',
            sources=['00112_元の公開時点と継続中の参加機会の診断','00113_現在の注文活動と再進行から波の中間に参加','00124_追加セッションと日経オプションの検証'],
            change='00113の更新支持線による頻繁な返済は使わず、再評価する入口だけを一親一回へ限定。当前の価格票と出来高代理を独立二票とは数えない。',
            why_retry='公開一瞬で弱いことと、その方向区間で機会がないことは違う。124三候補の後の支持は小JSONに保存されず未測定だから別途測る。',
            expected_failure='10秒確認で既に値幅を消費し、旧00113のように初期逆行や気配横断費用を回収できない可能性。',
            not_new='00112/00113の現在再評価の再検証。新発明や124三候補が後で勝った証拠としない。'),
        dict(id='P125_C',name='当日の共同方向に一回参加し、実際の撤回まで持つ',
            simple='その場の始めから両指数が共通して進んだ方向へ、まとまった数量を一回建てる。小利確で止めず、方向撤回か追尾で降りる。',
            entry='開始30分後から、両市場の開始後Last変化が同符号・各0.05%以上で、直近30秒も同方向へ各1ラージ呼値以上進んだ最初の原行。未参加なら共通の締切fallback。',
            management='短い逆票一つでは返さず、両市場が当初共同方向の根拠価格を2呼値以上割り込んだとき方向撤回として返済予約。保険の初期停止と追尾は共通。',
            sources=['00070_始値と前終値の方向制限と連敗休止','00071_二指数の共同方向と先行追随','00119_戦略の自動選択と場内黒字の再探索'],
            change='119の足単位方向系列や直近仮想成績による切替を使わず、当場参照価格と価格撤回を固定する。多数条件探索で当日最良を選ばない。',
            why_retry='旧119の共同方向失敗を引き継ぐ基準として、最低日次参加と小円P1廃止を同じ表で比較するため。強い新優位の根拠はまだない。',
            expected_failure='直前の共同進行が丁度終わったところで参加し、両指数反転で同時に負ける。原理的には既知の追従失敗を抱える。',
            not_new='共同方向・開始後方向は既検証家族であり、再探索の基準候補。三案中で優先度は低い。'),
    ]
    required=[
        '入口候補数→票資格→予定数量>0→予約→次quote約定→完結の段階ごとに日数・件数・理由を保存する。',
        '公開時点のATR/R、Last、BBO、自己/相手のseq・age、現在票、予定q、仮説撤回価格、料金を全候補で保存する。',
        'ゲート拒否を通過へ変えた仮想損益を、元完結親の符号反転や元出口の値で代用しない。',
        'fallbackなし/ありを固定対照にし、通常入口PLと強制参加PLを分ける。後者の赤字を前者へ隠さない。',
        '共通パラメータを先に固定し、銘柄別調整は両市場の同じ尺度の意味が保てる場合だけ別試行へ分離する。',
        '追加10/19を見て作った仕様であることを明示し、新しい未見検証と呼ばない。',
        '最高順行・最大逆行・入口/継続/出口・強制参加のどこで損失が増えたかを全実親で分解する。',
        '日次0.5%の分母と日付定義が確定するまで利益達成の判定を作らない。',
    ]
    output=dict(passed=True,status='設計のみ・金融未実行',references=[old_ref,new_ref],
        candidates=candidates,three_candidates_do_not_prove='固定balance0では2/3が票ゲートを通るという保存値の再判定だけ。実約定・収支の新測定0。',
        activity=activity,activity_day_definition='保存セッション名の先頭日付による仮集計。ユーザーの1日の正式定義未確定。',
        differences=differences,shared=shared,proposals=proposals,required_tests=required,
        new_financial_accounts=0,original_market_reads=0,numerical_array_reads=0,API=0,real_orders=0,registry_changes=0)
    target=HERE/'低頻度黒字と日次必須の差及び入口三候補.json'
    assert not target.exists();target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,path=target.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        candidates=candidates,activity=activity,new_financial_accounts=0),ensure_ascii=False))


if __name__=='__main__':
    main()
