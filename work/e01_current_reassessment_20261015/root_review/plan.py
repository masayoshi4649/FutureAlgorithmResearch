"""九つの新経済条件と保存基準を、実入力前の八部品へ固定する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENGINE = HERE.parent/'engine'
sys.path.insert(0,str(ENGINE))
import catalog

META = HERE/'旧三十三場の入力と保存基準の一読目録.json'
ROOT_SOURCES = ('plan.py','finance.py','financial_metrics.py')


def sha(path: Path) -> str:
    """
    機能: 小資料又は私有sourceの指紋を求める。
    引数: path(Path) は読み取り対象。
    返り値: str はSHA256。大型の板又はcacheをここで開かない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 所有域の準備済みJSONを有限値として読む。
    引数: path(Path) は目録・人工・監査・正式固定。
    返り値: dict は内容。金融結果を自動参照しない。
    """
    value = json.loads(path.read_text(encoding='utf-8'))
    json.dumps(value,allow_nan=False)
    return value


def sources() -> dict:
    """
    機能: 今回の経済的処理と実行guardの実装を固定する。
    引数: なし。
    返り値: dict[str,str] はルート相対sourceとSHA256。
    """
    paths = sorted(ENGINE.glob('*.py'))+[HERE/name for name in ROOT_SOURCES]
    assert all(p.is_file() for p in paths)
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths}


def case_hashes(configs: list[dict]) -> dict:
    """
    機能: 各経済条件の全項目を表示IDと分離して固定する。
    引数: configs(list[dict]) は固定九条件。
    返り値: dict[str,str] は各条件の正規JSON指紋。
    """
    return {c['id']:hashlib.sha256(json.dumps(c,ensure_ascii=False,sort_keys=True,
            separators=(',',':'),allow_nan=False).encode()).hexdigest() for c in configs}


def prepare(artificial: Path, audits: list[Path], formal: bool) -> None:
    """
    機能: 現在活動と気配応答を三段階に分解し、三出口へ接続する計画を作る。
    引数: artificial(Path)、audits(list[Path]) は合格小証跡、formal(bool) は根の正式固定。
    返り値: None。試行登録・cache読取・金融・APIは別操作。
    """
    meta = read(META)
    fixed = meta['入力の固定']
    assert meta['全合格'] and fixed['全合格'] and len(fixed['sessions']) == len(fixed['inputs']) == 33
    artificial=artificial.resolve()
    audits=[p.resolve() for p in audits]
    art = read(artificial)
    assert art['全合格']
    for name,expected in art['source_SHA256'].items():
        assert sha(ROOT/name)==expected,name
    for path in audits:
        audit=read(path)
        assert audit['全合格']
        for name,expected in audit.get('source_SHA256',{}).items():
            assert sha(ROOT/name)==expected,name
    configs = catalog.configs()
    assert len(configs) == 9 and len({c['id'] for c in configs}) == 9
    manifest_paths = [META,artificial]+audits
    spec = dict(
        entry=dict(conditions=configs,condition_count=9,
            母集団='同源strictjoinした全normal。元E01の方向/PUB/ATR/紙上返済は入口条件へ使わない。',
            水準='当場start基準の直前確定5分Last高安。直前空bucketは未知、繰越無し。確定row<突破row。突破後はそのLを固定。',
            共通='最新L/sideの突破episode。各入口の必要knownが揃う最初の両BBO>L買/両BBO<L売の行でB0/A0を固定。後の別原行で両BBOが方向へ1観測tick以上進んで現在条件を満たしたら①②を公開。',
            現在活動='W60全normalのknown/count>=2/unsigned balanceを方向へ一回だけ向ける。TOP.5/NK.25。出来高増加更新の方向proxyで、攻撃注文量ではない。',
            二市場='②③は正常Last非零更新のW60、自己/peer各known/count>=2/sidebalance>=.25。peer末端は自己よりstrict過去、age<=60、同時計未来を入れない。',
            新反対票='③は突破rowより後だけ。同源同窓・既知連続・単調raw窓境界の反対票正差>=1。突破rowは突破前更新を含み得るので採用しない。失効と相殺されるので下限だけ。0/負差を新票なしと断定しない。',
            反応='最初の新反対票時のBp/Ap固定。後の別行で両BBOが方向へ2T進行し、突破以来B0/A0から逆行>1Tなし。',
            余裕='公開時のspread×q×倍率＋新規/返済の注文別floor料<=.5×.00075×公開気配名目。'),
        management=dict(
            episode='同L/side突破episodeで各入口最大一度公開。busy/費用拒否も消費。次は最新確定bucketのLへの切替後突破、又は両BBOがL反対側へ戻った後の新突破。',
            再武装境界='買episodeは両BBO<=L、売は両BBO>=Lで戻り。突破はstrict。返済/FAK失効だけでは同episodeを復活させない。',
            競合='当行の正閾値方向VOLで選び、同時両方向資格は成立しない。最新確定bucketの参照Lだけを使う。',
            保有線='実約定以後の新反対票による③反応だけで、買max(old,Bp−1T)、売min(old,Ap+1T)。未認定probe最新一つ、確定線後退禁止。',
            未知='未公開probeだけ取消。Lの未知と保有支持線は別。既存支持線・受理FAK・実fillを未知で消さない。',
            probe終了='①②は未知後の新known行でB0を取り直せるが無逆行の証明をしない。③はB0取得後の>1T逆行又は正常/必要known連続の切断で当該L/side episode内終了。L反対側への両BBO戻り/新bucket切替まで再B0禁止。',
            非再利用='入口③で使った反対票事象を保有支持更新へ使わない。新fill後に新たな事象を要求する。'),
        exit=dict(
            構造='初期支持線L±1T、買は両BBO<=L−1T、売は両BBO>=L+1Tのinclusive到達。次normalで返済。',
            現金='初回実fill名目N固定。stop.00075N。TARGET.00125N。TIGHT arm.00075/draw.00025/floor.0005N。WIDE arm.00125/draw.000375/floor.00075N。',
            場='firstObserved場内Last×cap×倍率を固定。loss.0025/profit.00375純清算firstcrossで次normal全返済と以後新規停止。',
            時間='固定保有時間を置かない。quietと場内期限で全返済。paper撤回151と二市場反対票152の独立返済は不使用。'),
        allocation=dict(quantity=dict(catalog.CAP),cap=dict(catalog.CAP),倍率=dict(catalog.VALUE),
            方針='TOPIXmini10/NK225micro20を初回から使用。最大同方向枚数と実使用枚数を別記。最大一つの実親。追加/両建て無し。'),
        costs=dict(実注文片道税込={'TOPIXmini':41.8,'NK225micro':11},
            floor='各新規と各返済注文の合計を1円未満切捨て。失効未約定の手数料無し。',
            分離='手数料とBBO気配差を分離し、midの無費用利益と同じと呼ばない。'),
        execution=dict(
            新規='公開時の両価格票known/各count>=2/sidebalance>=.75なら1観測T、他0T。買ask上限/売bid下限を公開時に固定、firstnormal一回FAK。',
            順序='timer→既返済予約→既FAK→現在観測/制御→新公開。現在判断を過去行へ巻き戻さず、当行約定と称しない。',
            期間='[start+300,limit−300)で新規公開。timer/quietの返済で場内清算。',
            価格時計='同源PriceTimeモデルを維持。受信時計・二市場共通seqは再現不能。',
            限界='ラージBBOによるmini/micro価格代理。観測TはTOP.5pt/NK10円＝実商品二呼値。queueと部分約定/実商品の気配は未測。5秒最悪約定は今回不使用。'),
        data=dict(sessions=fixed['sessions'],inputs=fixed['inputs'],
            input_manifests=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p)) for p in manifest_paths],
            範囲='各場TradeGate/TradeExitを同bytes各一読し、record/quotes/全原seq/clock/mappingとPUB票をstrictjoin。新9条件の全後続を運転。旧基準は保存結果を使う。',
            対照='00111 E01_EVID_VOL_SELECTED_TARGETの66保存会計。独立入口/紙上撤退削除/支持線など複数差分を含み、純入口効果とは呼ばない。',
            未読の追加場='2026-10-13_Night・2026-10-14_Dayは本作業でstatだけ記録、本文未読保持。過去全試行の既読照合は未完了、正式な未知データ認定ではない。今回の旧33場結果へ混ぜない。'),
        implementation=sources())
    proposal = dict(id=catalog.TRIAL_ID,name='現在の活動と両市場の気配再進行による三入口三出口',purpose='新仮説',
        question='初回E01の一回審査から独立し、現在活動・両市場の進行・新反対活動を受けた再進行を順に確認すると中央参加と損失抑制を両立できるか。',
        change='全normal独立の3入口×3Native出口。旧紙上方向/ATR/撤回への依存を外し、当時水準と気配応答から参照Lと保有支持線を別管理。',
        repeat_reason='00112では初回VOL不成立後に現在資格が成立したTOP102/124・NK83/95。勝率は未測であり、同じ機会と数えず新構造の実注文と全後続を検証する。',
        compares_to=['111_E01少ない価格票で追随せず入口を残す十二比較'],
        spec=spec,正式freeze=formal,未確定点=[],
        予定=dict(新経済条件=9,新金融口座=594,大型cache=66,基準保存会計=66,基準再金融=0,掲載比較=10,新二場本文=0,原板=0,NPZ=0,API=0),
        表示主候補='E01_CURRENT_VOL_PRICE_RESPONSE_WIDE_TRAIL',
        選択='③＋広いトレールを結果前の仮説主候補とする。9条件全件を載せ、後の成績順選択は既知33場での再選択と明示。',
        limitations=['新条件は既知33場での探索、未来成績を保証しない。',
                    '原板の心理・新規/返済内訳・補充数量そのものは保存proxyから直接測っていない。',
                    'TOP主床は全場平均net10万円、NK円額床は未指定。無取引は黒字に数えない。'])
    checker_path = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
    ms = importlib.util.spec_from_file_location('今回の八部品の純構造照合',checker_path)
    checker = importlib.util.module_from_spec(ms)
    ms.loader.exec_module(checker)
    verdict = checker.analyze(proposal,[])
    assert verdict['proposal_complete'],verdict['提案不完全理由']
    name = '試行計画.json' if formal else '試行計画草案.json'
    target = HERE/name
    assert not target.exists()
    target.write_text(json.dumps(proposal,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    name2 = '金融事前固定.json' if formal else '準備固定.json'
    second = HERE/name2
    assert not second.exists()
    second.write_text(json.dumps(dict(全合格=True,正式freeze=formal,sessions=fixed['sessions'],inputs=fixed['inputs'],
        configs=configs,source_SHA256=spec['implementation'],case_SHA256=case_hashes(configs),計画SHA256=sha(target),
        人工SHA256=sha(artificial),独立監査=[dict(path=p.relative_to(ROOT).as_posix(),SHA256=sha(p)) for p in audits]),
        ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('九新条件＋保存基準の'+('正式固定' if formal else '草案')+'を保存。金融0。')


def main() -> None:
    """
    機能: 根の条件固定だけをCLIから呼び、実金融とは分離する。
    引数: --artificial(Path)、--audit(list[Path])、--formal(bool)。
    返り値: None。準備済み監査が無ければ停止する。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--artificial',type=Path,required=True)
    parser.add_argument('--audit',type=Path,action='append',required=True)
    parser.add_argument('--formal',action='store_true')
    args=parser.parse_args()
    prepare(args.artificial,args.audit,args.formal)


if __name__ == '__main__':
    main()
