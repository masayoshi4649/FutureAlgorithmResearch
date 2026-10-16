"""十四経済対照を八部品へ固定し、正式金融を根の登録後へ限定する。"""

import common
import catalog
import data


def clones() -> dict:
    """
    機能: 注文/会計/公開票と旧対照が同bytes新所有コピーであることを確認する。
    引数: なし。
    返り値: dict は旧source指紋。旧module/cacheを実行importしない。
    """
    previous=common.ROOT/'work/e01_adaptive_price_20261014/engine';result={}
    for local,old in ((n,n) for n in ('common.py','data.py','daily.py','order_kernel.py','storage.py','ledger_storage.py','entry_policy.py','base_policy.py')):
        ref=previous/old;assert (common.HERE/local).read_bytes()==ref.read_bytes()
        result[ref.relative_to(common.ROOT).as_posix()]=data.digest(ref)
    ref=previous/'sizing_engine.py';assert (common.HERE/'legacy_engine.py').read_bytes()==ref.read_bytes()
    result[ref.relative_to(common.ROOT).as_posix()]=data.digest(ref)
    return result


def prepare(formal: bool=False) -> None:
    """
    機能: 事前指定の十四条件・同33入力・17源人工を八部品草案又は正式固定へ結ぶ。
    引数: formal(bool) は根だけの正式freeze。Falseは金融前準備。
    返り値: None。大型input/台帳/金融/登録/APIを実行しない。
    """
    import runner
    meta_path=common.HERE/'旧選択小会計と三十三入力の目録.json'
    proof_path=common.HERE/'十四容量と実親分離及び登録接口の人工検査_v2.json'
    meta,proof=(data.read(p) for p in (meta_path,proof_path))
    assert meta['全合格'] and proof['全合格'] and proof['source_SHA256']==common.sources()
    sessions=meta['sessions'];assert len(sessions)==len(meta['input_cache'])==33
    configs=catalog.configs();source=common.sources();manifests=[dict(path=p.relative_to(common.ROOT).as_posix(),sha256=data.digest(p)) for p in (meta_path,proof_path)]
    spec=dict(entry=dict(conditions=configs,condition_count=14,
        gate='選択:TOPG50/strong.75、NKG25/strong1。追加二条件は共通G25/strong.75。W60既知二票、公開0/1T許容固定。',
        paper='保存paper5/10の全候補を維持。未約定は最初paper退出で取消、firstnormal FAK同行はfill先。'),
        management=dict(実親='paper CID/vcoreから実parent/UID/q/N/高水準を分離。busy次paper候補で実保有状態を上書きしない。',
            名目='初実fillのN=E×初q×倍率を固定。未来fill価格を過去公開へ逆算しない。',
            順序='scheduled→既返済queue→既pendingFAK→当行paper→親/場制御。GU当行予約を保持しstopは未予約残だけ追加、別注文fee。',
            後続='親利益返済後も候補を続行。場lossラッチだけ以後新規禁止。'),
        exit=dict(親停止='純損失.00125N。TARGETは純利益.005N。TRAILはarm.00375N/draw.00125N/floor.0025N。',
            PARTIAL='親局所純清算.0025Nで初qの1/4floorを一度返済予約。q<4は無し、その後同TRAIL。',
            GU='元paper退出の累積比率を実qへ写す＋共通親stop。旧GU経済同値ではなく新リスク付き対照。',
            場='最初観測された場内有限正価格×容量×倍率×.0025を固定。場清算firstcross→次normal全UID返済と永久停止。',
            基準='親local=前完結親netを除いた実清算。全払料/残UID返済料/部分実現を含む。次quote悪化で停止線を超え得る。'),
        allocation=dict(cap=catalog.CAP,fixed_half=catalog.HALF,requested='fixed全量10/20又はrisk最大10/20。paper初回5/10と分離。',
            BQ='公開paper価格×容量×倍率×.00125。RISKはavailable=BQ+min(0,場清算net)から1ATR+spread+注文別往復料で最大整数。',
            fixed='半/全量はBQでclipしない。normal/有限正ATR/票/quiet/実busyは必要。',
            枯渇='RISKは場損失が続けばq0へなり活動が消えることがある。固定量と同じ活動を仮定しない。'),
        costs=dict(片道税込={'TOPIXmini':41.8,'NK225micro':11},円倍率=catalog.VALUE,
            課金='各実注文floor(qfee)。GU予約とstop残を別注文として各切捨て。未約定料0、parentnetと玉netは別。'),
        execution=dict(FAK='公開時の強支持のみ不利1観測T許容、それ以外0。一回最初normalで全量価格内fill又は失効。',
            返済='観測triggerは当行返済無し、次normalで実残UID。既知timerは初正常で清算。未知quoteは補完しない。',
            限界='観測ラージT=.5pt/10円は実mini/micro二呼値。nativequeue/部分FAK/受信時計は未測定。'),
        data=dict(sessions=sessions,input_cache=meta['input_cache'],input_manifests=manifests,
            予定='33packet各一読、各十四caseの実状態が異なるため924accountを全運転。旧GU/台帳再利用0。',
            引用='旧選択2の小会計だけ引用し、規模改善や追加効能の標本に数えない。旧結果は目的別小射影1読後再利用。',
            診断='一次出力から全実親のentry/exits/q/N/票/cap/費用/MAE/MFE/原paper退出差を小保存。極値は事後専用。',
            不使用='価格時計不適合の現在ナイト・原板/NPZ/APIは不使用。',transitive_source_finance=meta['source_finance']),implementation=source)
    proposal=dict(id=catalog.TRIAL_ID,name='保有容量と一取引利益の十四再検証',purpose='新仮説',
        question='最大容量と長い実親出口により、損失/無取引込み全33場平均netをTOP10万円へできるか。',
        change='紙上初回5/10とactualrequestedを分離。小P1場終了を廃し、親純損失/目標/高水準/部分と場lossを独立実状態へ接続。',
        repeat_reason='旧1/2枚＋小P1終了は全場平均TOP10万円を評価しない。全量/長出口は後候補busy/余力を変えるので保存GUから比例推定できない。',
        compares_to=['106_E01公開支持強度による一回FAK許容切替八対照'],spec=spec,同bytesコピー=clones(),
        予定=dict(新条件=14,既input一読=33,新account金融=924,旧GU再利用=0,旧台帳本文=0,旧保存引用条件=2),
        未確定点=[],正式freeze=formal,金融=0,実input読取=0,旧台帳本文読取=0,登録=0,
        limitations=['TOP平均は損失/無取引込み全33場net/33。上位三場除外は残場数を分母とする別判定。親平均netは参考だけ。NK円床は未指定。',
            '容量換算pt=net/(容量×倍率)は算術比較で、variable/partialの必要生値幅又は原資ROIへ転用しない。',
            '固定量は旧5000/2000risk選択を外す。予定BQ・親stop・場stopは独立。価格gapでリスク線超過は可能。',
            '全実親完結は実UID残0で判定し、paper未返済を除外条件にしない。',
            '無取引/損失後q0は勝ちに数えず、疎活動や前16後17・上位3除外を別表示。'])
    filename='試行計画.json' if formal else '試行計画草案.json';common.write(filename,proposal)
    common.write('金融事前固定.json' if formal else '準備固定.json',dict(全合格=True,正式freeze=formal,sessions=sessions,configs=configs,
        input_cache=meta['input_cache'],reused_results=meta['reused_results'],source_SHA256=source,case_SHA256=runner.case_hashes(configs),
        計画SHA256=data.digest(common.HERE/filename)))
    print('十四経済条件の'+('正式固定' if formal else '金融前草案')+'を保存',flush=True)
