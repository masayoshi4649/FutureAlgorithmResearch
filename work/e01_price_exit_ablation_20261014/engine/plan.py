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
    previous=common.ROOT/'work/e01_protect_reentry_20261014/engine';out={}
    names={name:name for name in ('common.py','data.py','daily.py','order_kernel.py','ledger_storage.py','storage.py','statistics.py','price_votes.py')}
    names.update({'core.py':'baseline_core.py','artificial.py':'fixtures.py'})
    for old,new in names.items():
        path=previous/old;assert path.read_bytes()==(common.HERE/new).read_bytes()
        out[path.relative_to(common.ROOT).as_posix()]=data.digest(path)
    return out


def metadata() -> None:
    """
    機能: 108正式固定の33input目録と根の十二ON小射影を新目的へ保存する。
    引数: なし。
    返り値: None。元金融/公開会計/packet/台帳本文は読まない。
    """
    path=common.ROOT/'work/e01_protect_reentry_20261014/engine/金融事前固定.json';before=data.read(path)
    reference=common.HERE/'comparisons/108十二条件の保存小会計.json';ref=data.read(reference)
    assert data.digest(reference)=='14c6bc436ad917ff85837e94ff038d36e23a417787dd3cbe723766fabaaca4c5'
    assert before['正式freeze'] and len(before['sessions'])==len(before['input_cache'])==33
    assert ref['全合格'] and ref['source_SHA256']==before['source_SHA256'] and len(ref['cases'])==12
    common.write('既33入力と108_ON十二条件の保存小目録.json',dict(全合格=True,sessions=before['sessions'],input_cache=before['input_cache'],
        comparison_reference=ref,input_source=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=data.digest(path)),
        comparison_source=dict(path=reference.relative_to(common.ROOT).as_posix(),SHA256=data.digest(reference)),
        根小射影の元目的読取=1,元金融読取=0,元公開会計読取=0,大型input=0,旧台帳=0,新金融=0,API=0))
    print('33input目録と108十二ON保存小会計を保存。大型読取0。')


def prepare(formal: bool=False) -> None:
    """
    機能: 価格票/保護/新geometryを八部品へ固定し、根の登録より前の金融を禁止する。
    引数: formal(bool) は根だけの正式freeze。Falseは草案準備。
    返り値: None。大型input/金融/registryは実行しない。
    """
    meta_path=common.HERE/'既33入力と108_ON十二条件の保存小目録.json'
    art_path=common.HERE/'反対価格票退出の単独OFFとON同値及び接頭の人工検査.json'
    meta,art=(data.read(p) for p in (meta_path,art_path));source=common.sources();configs=catalog.configs()
    assert art['全合格'] and art['source_SHA256']==source and meta['全合格']
    spec=dict(entry=dict(conditions=configs,condition_count=12,
        価格票='正常Lastの非零隣接差一更新一票、equal無し。cutoff以前の最後正常Last基準、票cutoff<clock<=end。',
        自己='当該normal原行まで。同clock後半の未来行を入れない。',
        相手='最後正常PriceTimeが自己clockよりstrict過去、age<=60。相手60秒窓はその選択peer末端時計が終点であり自己当行終点の窓ではない。同時計又は未来補完無し。',
        資格='自己/peer現在窓既知、各更新票>=2かつpaper方向balance>=.25。volume票とは別。',
        余裕='pub仮N=(買ask/売bid)*q*m、spread*q*m+注文別往復floor料<=.5*.00075*pub仮N。'),
        management=dict(実親='受理予約ごと新actualCID、失効欠番保持。UIDは実fillだけ発行。paper CID別。初実fill N固定。',
            geometry='実flat/失効/未約定撤回時の正常Last anchor。未知なら次正常で初期化し、その同row再参加しない。',
            参照価格='現在paper親の公開価格をgeometry尺度に固定、paper変更で更新。実filledNを上書きしない。',
            消費='新geometry公開審査を消費しanchor再基準。旧拒否/失効注文を復活させず後の新geometryと現在票で別公開。',
            PULL='方向極値から.00025*paper公開価格の押し戻り→後行のtroughから.000125*同価格回復。',
            BREAK='flatanchorから方向へ.00025*現在paper公開価格突破。',
            ADAPTIVE='両現在方向balance>=.75ならBREAK、それ以外PULL。一geometryを維持しモード変更だけで再基準しない。'),
        exit=dict(親='TARGET.00125N、TIGHT arm.00075/draw.00025/floor.0005N、WIDE arm.00125/draw.000375/floor.00075N、共通stop.00075N。',
            撤回='paper全退出/方向相違で次normal全返済。paper部分EXITは実量へ写さない。',
            反対='独立退出reason152だけ無効。自己/peer反対票で実保有を返済しない。入口票/強票によるFAK価格限界は108のまま。',
            場='firstObserved場内Last*cap*mを一回固定、loss.0025/profit.00375純清算firstcrossで次normal全返済/以後新規禁止。',
            清算='親local=全場fee清算−entry前完結net。現在までの高水準だけ、事後ピーク不使用。'),
        allocation=dict(quantity=catalog.CAP,cap=catalog.CAP,paper='旧影初回5/10は不変更、実初回は常に10/20。',
            buffer='受理/失効/再参加数がpaper親数を超えても注文/UID/系譜bufferを動的拡張する。'),
        costs=dict(実注文片道税込={'TOPIXmini':41.8,'NK225micro':11},倍率=catalog.VALUE,
            floor='各新規/各返済注文ごと1円未満切捨て。失効未約定は料無し。'),
        execution=dict(FAK='公開当時両方向balance>=.75なら1観測T、他0。買ask上限/売bid下限を固定しfirstnormal一回fillor失効。',
            撤回予約='未約定は最初paper EXIT（部分も）で永久取消。同rowの既予約firstnormal約定が先。',
            期間='全ENTRYは[start+300,limit-300)、返済timerはrecord.limit/quiet。保有時間を5分に固定する規則ではない。',
            順序='timer→以前の返済予約→以前FAK→当行paper→親/場制御→新geometry公開。triggerと同row観測返済無し。',
            限界='ラージ気配によるmini/micro代理、観測T=.5pt/10円、実商品二呼値。queue/部分約定/物理受信先後は未測。'),
        data=dict(sessions=meta['sessions'],input_cache=meta['input_cache'],
            input_manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=data.digest(p)) for p in (meta_path,art_path)],
            範囲='同33packet各一読。二市場新価格票は同loadedpacketから一回、12全状態を別再運転。原board/NPZ/API0。',
            比較=meta['comparison_source'],比較解釈='108十二ONは同再参加/出口の全場/上位三除外/買売会計を保存再利用。親別/各場対応が未収録なら未測のまま。再金融しない。'),
        implementation=source)
    proposal=dict(id=catalog.TRIAL_ID,name='二市場の反対価格票退出だけを外す継続十二対照',purpose='新仮説',
        question='60秒両反対価格更新票が一時的な押し戻りを撤回と誤認していないか。',
        change='reason152独立退出だけOFF。売買枚数/入口票/FAK/geometry/純損失/保護/影撤回/場停止/期間/費用は108同一。',
        repeat_reason='108 ORIGIN_TARGETのTOP24/29親が反対価格票退出。追加PULLも粗赤字だったので、出口部品だけを切り分ける。',
        compares_to=['108_E01利益保護三出口と二市場価格票四再参加の十二対照'],spec=spec,同bytesコピー=clones(),
        予定=dict(新条件OFF=12,保存対照ON=12,既input一読=33,価格票準備口座=66,新account金融=792,ON再金融=0,旧台帳本文=0),
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
    print('反対価格票退出OFF十二条件の'+('正式固定' if formal else '八部品草案')+'を保存。金融0。')
