"""十二条件を保存目録・価格観測範囲・所有sourceへ結び、根の正式固定まで金融0を保つ。"""

import hashlib
import importlib.util
import json
import common
import catalog
import data


def case_hashes(configs: list[dict]) -> dict:
    """
    機能: 十二条件の全項目を正規JSONのSHA256へ結ぶ。
    引数: configs(list[dict]) は結果前条件。
    返り値: dict はID別指紋。表示名で経済条件を代用しない。
    """
    return {c['id']:hashlib.sha256(json.dumps(c,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest() for c in configs}


def clones() -> dict:
    """
    機能: 旧会計/価格票/ON核心/人工素材が新所有域の同bytes写しであることを検査する。
    引数: なし。
    返り値: dict は旧source位置と指紋。旧経済moduleをimportしない。
    """
    previous=common.ROOT/'work/e01_entry_information_20261014/engine';out={}
    names={name:name for name in ('common.py','data.py','daily.py','order_kernel.py','ledger_storage.py','storage.py','statistics.py','price_votes.py','fixtures.py')}
    names.update({'core.py':'baseline_core.py'})
    for old,new in names.items():
        path=previous/old;assert path.read_bytes()==(common.HERE/new).read_bytes()
        out[path.relative_to(common.ROOT).as_posix()]=data.digest(path)
    return out


def metadata() -> None:
    """
    機能: 110正式固定の33input目録と十二条件の公開保存小射影を新目的へ固定する。
    引数: なし。
    返り値: None。元金融/公開会計/packet/台帳本文は読まない。
    """
    path=common.ROOT/'work/e01_entry_information_20261014/engine/金融事前固定.json';before=data.read(path)
    reference=common.HERE/'comparisons/110十二比較の保存公開会計.json';ref=data.read(reference)
    assert data.digest(reference)=='a0e10058632c6891035eb15b0167f77cf35295e94f16929c660ea17d7acf9938'
    assert before['正式freeze'] and len(before['sessions'])==len(before['input_cache'])==33
    assert ref['全合格'] and len(ref['cases'])==12 and all(len(c['rows'])==66 for c in ref['cases'].values())
    common.write('既33入力と110十二条件の保存小目録.json',dict(全合格=True,sessions=before['sessions'],input_cache=before['input_cache'],
        comparison_reference=ref,input_source=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=data.digest(path)),
        comparison_source=dict(path=reference.relative_to(common.ROOT).as_posix(),SHA256=data.digest(reference)),
        根小射影の元目的読取=1,元金融読取=0,元公開会計読取=0,大型input=0,旧台帳=0,新金融=0,API=0))
    print('33input目録と110十二条件保存会計を保存。大型読取0。')


def prepare(formal: bool=False) -> None:
    """
    機能: 原新規の価格/出来高情報と唯一金融範囲を八部品へ固定する。
    引数: formal(bool) は根だけの正式freeze。Falseは草案準備。
    返り値: None。大型input/金融/registryは実行しない。
    """
    meta_path=common.HERE/'既33入力と110十二条件の保存小目録.json'
    art_path=common.HERE/'FAK追随票二以上と保存経済同値及び接頭の人工検査_v2.json'
    meta,art=(data.read(p) for p in (meta_path,art_path));source=common.sources();configs=catalog.configs()
    assert art['全合格'] and art['source_SHA256']==source and meta['全合格']
    spec=dict(entry=dict(conditions=configs,condition_count=12,
        価格票='正常Lastの非零隣接差一更新一票、equal無し。cutoff以前の最後正常Last基準、票cutoff<clock<=end。',
        自己='当該normal原行まで。同clock後半の未来行を入れない。',
        相手='最後正常PriceTimeが自己clockよりstrict過去、age<=60。相手60秒窓はその選択peer末端時計が終点であり自己当行終点の窓ではない。同時計又は未来補完無し。',
        資格='PRICE_BOTHは109現在自己/peer価格票の両方known/min2/.25を保存再利用。新VOL_SELECTEDは自己保存出来高票known/min2/signedTOP.5/NK.25、VOL25は両商品.25、VOL25_PRICE_BOTHはVOL25とPRICE両方。',
        出来高='trade_features60の当該paper公開normalrowだけ。正usable出来高増＋Last対直前rawBBOの1更新1方向代理票。真の攻撃注文量ではない。',
        符号='出来高balanceは保存時paper方向signed済み。採否は直接閾値比較し再signしない。known時にup+down/count/signed式と原mapping/seq/時計を照合。未知はvolume条件だけ拒否、peerVolume補完/後row持越し無し。',
        余裕='pub仮N=(買ask/売bid)*q*m、spread*q*m+注文別往復floor料<=.5*.00075*pub仮N。'),
        management=dict(再参加='全十二比較はORIGINのみ。PULL/BREAK/ADAPTIVE追加は不使用。公開row以外へ当該volume特徴を持ち越さない。',
            実親='受理予約ごと新actualCID、失効欠番保持。UIDは実fillだけ発行。paper CID別。初実fill N固定。',
            geometry='今回非有効。元paper新規当行の一回だけを審査し、busy/拒否/失効を復活させない。追加再参加0。',
            非復活='元新規当行だけ。後の新geometryによる追加公開は今回不使用。',
            非有効係数='旧核心のgeometry列/係数は診断又は互換だけ。全config.ORIGIN固定で追加公開には使わない。'),
        exit=dict(親='TARGET.00125N、TIGHT arm.00075/draw.00025/floor.0005N、WIDE arm.00125/draw.000375/floor.00075N、共通stop.00075N。',
            撤回='paper全退出/方向相違で次normal全返済。paper部分EXITは実量へ写さない。',
            反対='reason152独立退出OFFは109同一。入口情報を変えても保有に新volume取消/退出を足さない。',
            場='firstObserved場内Last*cap*mを一回固定、loss.0025/profit.00375純清算firstcrossで次normal全返済/以後新規禁止。',
            清算='親local=全場fee清算−entry前完結net。現在までの高水準だけ、事後ピーク不使用。'),
        allocation=dict(quantity=catalog.CAP,cap=catalog.CAP,paper='旧影初回5/10不変。全ORIGINのみ、実初回は10/20。PULL/BREAK/ADAPTIVE追加は使わない。',
            buffer='受理/失効/再参加数がpaper親数を超えても注文/UID/系譜bufferを動的拡張する。'),
        costs=dict(実注文片道税込={'TOPIXmini':41.8,'NK225micro':11},倍率=catalog.VALUE,
            floor='各新規/各返済注文ごと1円未満切捨て。失効未約定は料無し。'),
        execution=dict(FAK='公開当時両市場known・現在両価格count>=2・sidebalance>=.75なら1観測T、他0。volume入口資格は維持し、価格票不足だけで入口を消さない。買ask上限/売bid下限を公開に固定してfirstnormal一回fillor失効。',
            撤回予約='未約定は最初paper EXIT（部分も）で永久取消。同rowの既予約firstnormal約定が先。',
            期間='全ENTRYは[start+300,limit-300)、返済timerはrecord.limit/quiet。保有時間を5分に固定する規則ではない。',
            順序='timer→以前の返済予約→以前FAK→当行paper→親/場制御→新geometry公開。triggerと同row観測返済無し。',
            限界='ラージ気配によるmini/micro代理、観測T=.5pt/10円、実商品二呼値。queue/部分約定/物理受信先後は未測。'),
        data=dict(sessions=meta['sessions'],input_cache=meta['input_cache'],
            input_manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=data.digest(p)) for p in (meta_path,art_path)],
            範囲='同33packet各一読。二市場現在価格票は一回、自己volumeは保存公開辞書だけ。TOP六条件/NK三条件の全後続を運転し、NK VOL25三出口は同じ新VOL_SELECTED保存会計を参照する。PRICE_BOTH三条件とVOL25_PRICE_BOTH三条件の再運転0。原board/NPZ/API0。',
            内部同値='NK VOL_SELECTEDとVOL25は同じknown/min2/.25/同退出で経済同値。VOL_SELECTEDを唯一実行元、VOL25を内部aliasに固定。表示IDの違いを別試行又は追加効能証拠に数えない。',
            比較=meta['comparison_source'],比較解釈='110のPRICE_BOTH三条件とVOL25_PRICE_BOTH三条件396会計は受理時に両価格票各2以上が必要なので経済同値保存再利用。拒否pubの許容診断は変わり得て全九出力同値とは呼ばない。未コピー旧親経路は未測。残六母の保存会計は比較だけ。'),
        implementation=source)
    proposal=dict(id=catalog.TRIAL_ID,name='少ない価格票で1T追随を許可せず0T新規を残す十二比較',purpose='新仮説',
        question='1価格更新のbalance1を複数更新の強支持と同一視せず、不足時に0T注文を残すと損失と後参加がどう変わるか。',
        change='FAK1T許容に現在両価格票各2以上だけを追加。入口volume/price、退出/枚数/費用は110同じ。新TOP6/NK3を全feed運転、NK VOL25の99は新SELECTED保存参照、旧経済同値6条件396会計を再利用。',
        repeat_reason='110 SELECTED_TARGETの1Tかつ価格どちらか2票未満はTOP3親0勝3負−62508、NK5親2勝3負+1800。薄い強支持表示の追随だけを分離。保存親を削らず失効/後参加を全運転する。',
        compares_to=['110_E01原新規の価格票と出来高代理三入口を切り分ける十二比較'],spec=spec,同bytesコピー=clones(),
        予定=dict(比較条件=12,新表示条件=6,経済同値保存条件=6,唯一金融商品条件=9,内部同値商品条件=3,
            既input一読=33,価格票準備口座=66,新account金融=297,内部同値会計再利用=99,内部同値再金融=0,
            旧経済同値保存会計=396,掲載口座=792,旧経済同値再金融=0,旧台帳本文=0),
        保存同値範囲='実注文/UID/legs/清算曲線/受理pub/実親経済は同じ。拒否pubのcap1→0診断差は旧保存へ補完せず未測。',
        正式freeze=formal,未確定点=[],金融=0,大型input=0,API=0,
        limitations=['TOP主床は損失/無取引込み全33場平均net100000円。親平均は参考、NK円床未指定。',
            '価格更新票はLast方向の代理であり真の攻撃注文方向/出来高量ではない。保存normal間だけを測り全raw区間の資格を保証しない。',
            '同じ既知33場での仮説比較。新条件を未知場で成功した証拠と呼ばない。'])
    checker_path=common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
    module_spec=importlib.util.spec_from_file_location('保護再参加の純仕様完全性',checker_path)
    checker=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(checker)
    verdict=checker.analyze(proposal,[]);assert verdict['proposal_complete'],verdict['提案不完全理由']
    proposal['純完全性']=dict(完全=True,過去照合又は登録ではない=True,source_SHA256=data.digest(checker_path))
    name='試行計画.json' if formal else '試行計画草案.json';common.write(name,proposal)
    common.write('金融事前固定.json' if formal else '準備固定.json',dict(全合格=True,正式freeze=formal,
        sessions=meta['sessions'],configs=configs,input_cache=meta['input_cache'],comparison_reference=meta['comparison_reference'],
        source_SHA256=source,case_SHA256=case_hashes(configs),計画SHA256=data.digest(common.HERE/name)))
    print('価格票/出来高代理十二比較の'+('正式固定' if formal else '八部品草案')+'を保存。金融0。')
