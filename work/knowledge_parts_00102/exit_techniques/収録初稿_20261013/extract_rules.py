"""既存の小さい会計・診断資料だけから、出口及び注文部品の知見を収録する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CACHE = {}
RULES = []
SYMBOLS = ("TOPIX", "NK225")
IFD = "work/wave_v65/結果.json"
IFD_OLD = "work/wave_v65/旧出口の全力枚数比較.json"
HEDGE = "work/wave_v70/analysis/管理の効果と限界.json"
PROTECT = "work/wave_v85/analysis/4部品の有無比較.json"
NARROW = "work/wave_v86/analysis/比較結果.json"
REENTRY = "work/wave_v86/analysis/利確後限定の独立解釈.json"
ALLOCATE = "work/wave_v88/analysis/比較結果.json"
PAUSE = "work/wave_v89/analysis/比較結果.json"
RETURN = "work/wave_v93/analysis/比較結果.json"
RISK = "work/wave_v104/支持幅と再参加及び利益保険の損失診断.json"


def load(path: str) -> object:
    """
    機能: 保存JSON又はsourceを一回読み、同じbytesのSHAと共に保持する。
    引数: path(str)はプロジェクト相対資料。
    返り値: objectはJSON構造又はsource文字列。金融部品をimportしない。
    """
    if path not in CACHE:
        raw = (ROOT/path).read_bytes()
        value = json.loads(raw) if path.endswith(".json") else raw.decode("utf-8")
        CACHE[path] = (value, hashlib.sha256(raw).hexdigest())
    return CACHE[path][0]


# ----------------------------------------
def resolve(path: str, pointer: str) -> object:
    """
    機能: JSON pointerで出典の数値又は対照群を確認する。
    引数: path/pointer(str)は保存資料と標準JSON pointer。
    返り値: objectは該当値。存在しない場所は例外にし推定補完しない。
    """
    value = load(path)
    for token in pointer.split("/")[1:]:
        key = token.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def source(path: str, pointer: str = "", selector: str = "") -> dict:
    """
    機能: 実際に読んだ資料と数値位置を同じ内容指紋で結ぶ。
    引数: path/pointer/selector(str)。selectorは非JSON sourceの関数等。
    返り値: dictはpath/pointer/sha256。source文字列はpointer対象外を明記する。
    """
    if path.endswith(".json"):
        resolve(path, pointer)
    else:
        load(path)
    value = dict(path=path, pointer=pointer if path.endswith(".json") else None, sha256=CACHE[path][1])
    if selector:
        value["selector"] = selector
    return value


def number(symbol: str, label: str, path: str, pointer: str, kind: str = "金額", unit: str = "円",
           scope: str = "既知30セッション", horizon: str = "新規から場内全返済", denominator: str = "対照の全決済親") -> dict:
    """
    機能: 保存された一つの数値をそのまま商品別の測定として収録する。
    引数: symbol/label/path/pointer/kind/unit/scope/horizon/denominator(str)。
    返り値: dictは値と出典。確率n/Nがない数値では両件数をnullにする。
    """
    value = resolve(path, pointer)
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    return dict(symbol=symbol, label=label, kind=kind, successes=None, total=None, value=value,
        unit=unit, denominator=denominator, horizon=horizon, scope=scope, source=source(path, pointer))


def frequency(symbol: str, label: str, path: str, pointer: str, n_key: str, total_key: str,
              denominator: str, scope: str, horizon: str, interpretation: str) -> dict:
    """
    機能: 同じ保存群にある件数n/Nの観測頻度を定義付きで作る。
    引数: symbol/label/path/pointer/n_key/total_key/denominator/scope/horizon/interpretation(str)。
    返り値: dictはn/Nと分母定義。未来の取引確率又は独立標本とは呼ばない。
    """
    group = resolve(path, pointer)
    n, total = int(group[n_key]), int(group[total_key])
    assert 0 <= n <= total and total > 0
    return dict(symbol=symbol, label=label, kind="観測頻度", successes=n, total=total, value=n/total,
        unit="割合", denominator=denominator, horizon=horizon, scope=scope, source=source(path, pointer),
        numerator_pointer=pointer+"/"+n_key, denominator_pointer=pointer+"/"+total_key, interpretation=interpretation)


def rule(ident: str, stage: str, title: str, condition: str, mechanical: dict, observed: str,
         use: dict, limits: list, measurements: list, evidence: list) -> None:
    """
    機能: 機械条件、対照効果、有効場面の確定範囲を一つの部品として保存する。
    引数: 識別/段階/見出し/条件/実測(str)、機械条件/用途(dict)、限界/測定/出典(list)。
    返り値: None。大勝ちの結果から当時の切替条件を逆算しない。
    """
    assert stage in ("入口", "継続判断", "出口", "売買の工夫")
    RULES.append(dict(id=ident, stage=stage, title=title, condition=condition,
        mechanical_condition=mechanical, observed=observed, use=use,
        limitations=limits, measurements=measurements, evidence=evidence))


# ----------------------------------------
def main() -> None:
    """
    機能: 主要10部品の保存済み数値を抽出し、pointer及び件数を検査する。
    引数: なし。
    返り値: None。新金融、原板、API、旧source変更は全て行わない。
    """
    measures = []
    for symbol in SYMBOLS:
        point = "/methods/0/summary/"+symbol
        measures.append(frequency(symbol, "0.1%損切りと利益保護での決済勝率", IFD, point, "wins", "trades",
            "同候補・実満額で場内決済した親", "既知25セッション", "新規後から場内返済", "最終的な方向到達率とは別の、損切りを先に含む実決済頻度"))
        measures.append(frequency(symbol, "先に損切り後、残り場内で0.1%へ到達した頻度", IFD, point,
            "stopped_then_target", "stop_count", "初期損切りで実返済した親", "既知25セッション", "実返済後から残りの場内",
            "返済後の未来経路による事後診断。入口/出口へ渡せない"))
        measures.append(number(symbol, "新IFD主案の収支", IFD, point+"/net", scope="既知25セッション"))
        old_index = next(i for i, item in enumerate(load(IFD_OLD)) if item["symbol"] == symbol)
        measures.append(number(symbol, "同候補・同全力枚数の旧出口収支", IFD_OLD, f"/{old_index}/net", scope="既知25セッション"))
    rule("EXIT_IFD_SEQUENCE_01", "出口", "いつか目標到達と、損切り前の利確は別", "0.1%まで動く候補でも途中で0.1%逆行したら先に損切りされる。",
        dict(比較="S0.10_T0.01対同候補旧出口", 初回枚数="TOPIX10/NK20", 初期損切り="実fillから0.1%",
             利益発動="0.11%順行", 最初保護床="0.1%", 追尾幅="0.01%", 実行="判断後の次行BBO、場内全返済"),
        "TOPIXは5/19勝・−405,884円、NKは11/23勝・−18,120円。損切り後に目標へ届いた親もTOPIX10/14・NK10/12あった。",
        dict(実測="行順を含む損切り/目標競争が損益を決める", 仮説="入口直後の逆行耐性と費用込み目標を別々に設計する。ただし広い損切りの有用性はこの事後頻度だけでは不明"),
        ["候補3の少数取引に限定。全入口一般の確率ではない", "到達後の利益床は次quoteの約定保証ではない", "旧出口と新出口で保有時間や後続採否が変わり得る"], measures,
        [source(IFD,"/methods/0/config"),source(IFD_OLD),source("work/wave_v65/replay.py",selector="trace/one。返済後採点は判断へ入力しない")])

    measures = []
    for symbol in SYMBOLS:
        point = "/H03/同許容幅の保険なし対照/管理集計/"+symbol
        measures.append(number(symbol,"同じ停止幅で保険を加えた収支差",HEDGE,point+"/収支差",kind="対照差額",scope="既知28セッション"))
        measures.append(number(symbol,"同じ停止幅で保険を加えた損失削減率",HEDGE,point+"/負組損失削減率",kind="金額比",unit="割合",scope="既知28セッション"))
        p="/H03/元玉保険分類/"+symbol+"/反転利確注文"
        group=resolve(HEDGE,p)
        measures.append(dict(symbol=symbol,label="選択された保険利確注文群の非赤字頻度",kind="条件付き観測頻度",
            successes=group["注文群数"]-group["実約定後赤字注文群数"],total=group["注文群数"],value=1.,unit="割合",
            denominator="利益見込み条件を満たして実際に出した保険全返済注文群",horizon="その注文群の次行実約定",scope="既知28セッション",
            source=source(HEDGE,p),calculation="(注文群数−実約定後赤字注文群数)/注文群数",interpretation="保険単独の選択後頻度。元玉を含む全体勝率ではない"))
    rule("ORDER_HEDGE_PROFIT_02", "売買の工夫", "利益保険だけ返済しても元玉損失は残る", "逆行時の反対玉を、順行後の反転で利益確定する。",
        dict(比較="T2L0_H03対同停止幅T2L0_D32", 初回="TOP10/NK20", 逆行追加="8呼値ごと上限の25%を端数切上げ",
             保険返済="保険平均4呼値順行後に4呼値反転、往復料後の利益見込みが必要", 元玉停止="32呼値", 期限="共通60分枠", 実行="次有効原行BBO"),
        "保険利確54/54群・75/75群は非赤字でも、同幅の無保険よりTOPIX−609,258円・NK−316,570円。保険損失を含む全体の利益改善はなかった。",
        dict(実測="逆行の後に反転して保険が利益化した個別例では損失を補った", 仮説="元方向へ戻る時に含み損の保険を残す弱点を別の損失停止で制御する余地。未検証"),
        ["B00の16呼値停止との比較は幅変更が交絡するため同幅D32を使用", "保険利確の高い勝率だけを手法全体の勝率にしない", "各段玉の個別OCO、保険損切り、再展開冷却は未検証"], measures,
        [source(HEDGE,"/H03/同許容幅の保険なし対照"),source("work/wave_v70/results/T2L0_H03.json","/config"),source("work/wave_v70/report.py",selector="summary/main")])

    measures=[]
    for symbol in SYMBOLS:
        p="/H03対N03の終端差額/"+symbol
        for field,label in [("両建てより縮小復帰が有利な金額","同じネット露出で縮小復帰が節約した総額"),("終端気配差費用","省けた終端の気配差費用"),("終端追加手数料","省けた終端の追加手数料")]:
            measures.append(number(symbol,label,HEDGE,p+"/"+field,kind="費用対照",scope="既知28セッション",denominator="同じ仮想保険判断のH03/N03全親"))
    rule("ORDER_NET_REDUCTION_03", "売買の工夫", "同じ両建て判断を元玉の縮小・復帰へ写す", "反対玉を建てる代わりに元玉を減らし、保険を外す時に元方向へ復帰する。",
        dict(比較="T2L0_H03対T2L0_N03", 判断="保険の仮想判断・次行待ちを同じに保持", 実行="ネット枚数を一致させる元玉減量と復帰", 終了="終端の相殺玉の両側決済を省く"),
        "全28場の終端差はTOPIX208,822円=気配差187,500円＋料21,322円、NK120,980円=108,000円＋12,980円として一致した。",
        dict(実測="同じ価格露出を維持できるこの模型では、不要な終端往復を省くほど費用が小さい", 仮説="他の保険手法でもネット目標への写像が同値なら再利用可能。途中約定/queueの異なる実市場までは未確認"),
        ["新しい方向優位を作る部品ではない", "復帰にも気配差と手数料が掛かり、全往復費用が消えるわけではない", "源の仮想判断に実数量や実損益を戻すと同じ比較ではなくなる"],measures,
        [source(HEDGE,"/H03対N03の終端差額"),source("work/wave_v70/results/T2L0_N03.json","/config"),source("work/wave_v70/audit/両建てと減玉対照の全行監査.json")])

    measures=[]
    for symbol in SYMBOLS:
        index=next(i for i,x in enumerate(load(PROTECT)["summaries"]) if (x["部品"],x["model"],x["period"],x["symbol"])==("P","observed","全30",symbol))
        p=f"/summaries/{index}"
        for key,label in [("収支悪化数","利益半分保護で総収支が悪化した対照頻度"),("損失削減数","利益半分保護で総損失を削った対照頻度")]:
            measures.append(frequency(symbol,label,PROTECT,p,key,"組合せ数","他3部品同一の8有無対照","既知30セッション","各対照の全場合計","8組は同じ価格経路を共有し、8独立標本又は次の勝率ではない"))
        measures.append(number(symbol,"利益保護による収支差中央値",PROTECT,p+"/収支差中央値",kind="対照差額",denominator="他3部品同一の8有無対照"))
    rule("EXIT_HALF_PROFIT_04", "出口", "利益の半分保護は損失だけを選別しない", "十分伸びた実組利益の最大値から半分へ戻ったら全返済する。",
        dict(比較="Pあり/なし、他G/D/C同一の8対照", 利益評価="実現と残玉CurrentPrice、既払料と全返済見込料込み", 発動="最大利益>=1.5R。R=初回数量×準備時ATRの金額幅", 床="最大利益の50%", 実行="次保存観測で残玉返済"),
        "総損失を削った対照はTOPIX7/8・NK8/8だが、総収支は双方8/8で悪化。中央値は−71,756.5円・−17,650円。",
        dict(実測="大きく順行後に戻った個別親を利益化した。既知全期間では勝ち組の利益減が上回った", 仮説="全日共通にせず、当時の停滞を区別して発動する案は別検証が必要"),
        ["事後に『戻る親だけ』へ有効にする切替は不可", "同じ対照経路を共有するため頻度を将来確率として外挿しない", "観測CurrentPriceモデルで、小型実板の執行を証明しない"],measures,
        [source(PROTECT,"/対象"),source("work/wave_v85/catalog.py",selector="specification.P及び優先順")])

    measures=[]
    for symbol in SYMBOLS:
        for index,code in [(0,"元広幅"),(2,"0.5ATR幅")]:
            p=f"/比較/observed/{index}/商品別/{symbol}"
            measures.append(frequency(symbol,code+"の親決済勝率",NARROW,p,"campaign_wins","campaigns","初回から全返済までの実組","既知30セッション","場内全返済","同じ元の再参加待ちを保持した通し対照"))
            for key,label in [("campaign_profit","総利益"),("campaign_loss","総損失"),("net","収支"),("max_drawdown","最大時価下落")]:
                measures.append(number(symbol,code+"の"+label,NARROW,p+"/"+key))
    rule("EXIT_NARROW_TRAIL_05", "出口", "狭幅トレールは勝率と利益幅を交換する", "0.75ATR進んだら0.5ATR幅へ狭める。再参加待ちは変えない。",
        dict(比較="T2_S対E01_G_U", 発動="準備時ATRの0.75倍順行", 追尾="固定0.5ATR幅、緩めない", 再参加="元のshadow終了+300秒", 数量="TOP初回5/上限10、NK初回10/上限20、追加なし"),
        "TOPIX親勝率55/136→81/136、NK61/142→83/142へ上がったが、収支は620,729→350,170円・220,860→135,060円。総利益の減少が総損失削減を上回った。",
        dict(実測="短い順行が戻る親を早く確定し、全体DDも減少した", 仮説="大波と小波を当時情報で区別できれば使い分け余地があるが、相場の終値分類を使う選択は未検証"),
        ["勝率だけで損小利大達成と評価しない", "同じ元待機の対照であり、再参加頻度変更の効果を混ぜない", "全30は既知探索で後半も未見とは呼ばない"],measures,
        [source(NARROW,"/比較/observed/2"),source("work/wave_v86/catalog.py",selector="catalogのT2/S及びspecification")])

    measures=[]
    for symbol in SYMBOLS:
        index=next(i for i,x in enumerate(load(REENTRY)["入口追加消失"]) if (x["model"],x["before"],x["after"],x["symbol"])==("observed","T2_S","T2_P1",symbol))
        p=f"/入口追加消失/{index}/追加"
        measures.append(frequency(symbol,"利確後1分再参加で追加された親の勝率",REENTRY,p,"wins","cycles","基準T2_Sにない追加入口の実親","既知30セッション","再新規から全返済","追加親だけの事後同入口比較。全手法勝率ではない"))
        for key,label in [("net","追加親の手数料後収支"),("gross","追加親の手数料前収支"),("fees","追加親の手数料"),("average_loss","追加親の平均損失")]:
            measures.append(number(symbol,label,REENTRY,p+"/"+key,denominator="T2_SにないT2_P1追加親"))
    rule("ORDER_FAST_REENTRY_06", "売買の工夫", "利確後の回転増だけでは失った利益を補えない", "料金後黒字で全返済した時だけ、1分後から新たな同入口を準備する。",
        dict(比較="T2_P1対同出口T2_S", 黒字定義="全部分返済合算の親net>1e-7円", 黒字後="次観測で古い影/待機破棄、返済時刻+60秒以降の新準備", 赤字後="通常shadow終了+300秒", 利益返済="T2の0.5ATR幅を同じに維持"),
        "追加親はTOPIX142/305勝・−552,457円、NK120/272勝・−325,340円。手数料前も−425,000円・−265,500円で、費用だけでは説明できない。",
        dict(実測="共通する118/123親の損益は同じで、追加親の損失を独立に分解できた", 仮説="同じ価格帯の再使用を避け新しい支持形成を要求する案は、この1分待ち部品とは別の条件"),
        ["直前の利益は次の価格方向の根拠ではない", "追加/消失親は事後説明。未来の親結果を採否へ使用できない", "『全ての早期再参加は無効』という一般化はしない"],measures,
        [source(REENTRY,"/簡潔な解釈"),source("work/wave_v86/phase2/catalog.py",selector="specificationの黒字後/赤字ゼロ後/時計")])

    measures=[]
    for symbol in SYMBOLS:
        p="/risk_attribution/A0820/全30/"+symbol
        for field,label in [("net_change","同8/16枚追従へ逆張り2/4枚を加えた収支差"),("drawdown_change","逆張り追加による最大下落増分")]:
            measures.append(number(symbol,label,ALLOCATE,p+"/"+field,kind="同数量対照差額",denominator="追従8/16枚単独対追従8/16+逆張り2/4"))
        for group,label in [("allocated_gu_only","追従8/16単独"),("portfolio","追従8/16+逆張り2/4")]:
            measures.append(frequency(symbol,label+"の黒字セッション頻度",ALLOCATE,p+"/"+group,"positive_sessions","sessions","既知全30場、無取引を勝ちにしない","既知30セッション","セッション末の確定収支","金額利益割合とは異なる場単位の頻度"))
    rule("ORDER_FIXED_DIVERSITY_07", "売買の工夫", "異なる思想の配分でも補完性は別確認", "追従8と逆張り2の枠を固定して同時に動かす。空き枠を貸さない。",
        dict(比較="A0820対同追従数量のallocated_gu_only", 数量="TOP追従8/逆張り2、NK16/4", 源="GU追従とM3中期逆張り", 実目標="各紙上残数にfloor(q*R/Q)、親内復元なし", 実行="源公開後の次有効CurrentPrice、源ごと実料金"),
        "逆張り追加で収支はTOPIX252,302円・NK75,464円増えたがDDも40,980円・25,232円増加。黒字場は21/30→18/30・18/30→19/30。",
        dict(実測="一方の取引が他方を補う場も存在したが、同数量対照の損失安定化は両方に共通しなかった", 仮説="同時保有時の相関と当時の有効条件による配分は別のアルゴリズム。結果を見た日替わり配分は不可"),
        ["追従10/20を8/16へ減らしたDD削減と、逆張りの補完効果を分離する", "親G/Lを源別で合算し損失を他源利益で消して勝率を作らない", "ラージCurrentPrice模型で小型BBO約定は未確認"],measures,
        [source(ALLOCATE,"/risk_attribution/A0820/全30"),source("work/wave_v88/catalog.py",selector="specificationの独立判断/整数減量/会計")])

    measures=[]
    for symbol in SYMBOLS:
        p="/differences/B0622_C16_P60/全30/"+symbol
        for key,label in [("saved_loss","参加停止で避けた負親の損失"),("missed_profit","参加停止で逃した正親の利益"),("delta","停止なしに対する収支差")]:
            measures.append(number(symbol,label,PAUSE,p+"/"+key,kind="同親採否対照差額",denominator="同配分の常時参加口座と採否口座"))
    rule("MANAGEMENT_VIRTUAL_PAUSE_08", "継続判断", "過去の回復確認を待つと最初の勝ちを逃す", "常時動かす仮想口座の最近16完了親の利益割合が60%以上なら新規参加する。",
        dict(比較="B0622_C16_P60対B0622_ALL", 集計="商品×源別の最新16完了親G/(G+L)、最低4完了までは許可", 時計="新規時計よりstrictに古い公開済完了だけ", 履歴="過去場持越、建玉は場内flat", 途中="実採否を仮想源へ戻さず、採用後出口は同じ"),
        "避けた損失はTOPIX2,547,992円・NK1,485,152円だが、逃した利益3,116,229円・1,614,992円が上回り、−568,237円・−129,840円。",
        dict(実測="不調な親の参加を減らせたが、成績回復の公開を待つため反発の初勝ちが採用されにくかった", 仮説="原因状態の復帰を使う停止解除は、過去利益割合方式と別に検証する必要がある"),
        ["過去窓の60%/80%は次の親の成功確率ではない", "取引を止めて無取引が増えても勝ちとは扱わない", "全30は既知、81条件に両商品利益80%なし"],measures,
        [source(PAUSE,"/differences/B0622_C16_P60/全30"),source("work/wave_v89/catalog.py",selector="specificationの金額割合/公開/時計/差分証明")])

    measures=[]
    for symbol in SYMBOLS:
        for code,label in [("C02","構造停止後そのまま再準備"),("C09","双方中心帰還まで休止")]:
            p=f"/results/{code}/periods/全31/{symbol}"
            measures.append(number(symbol,label+"の収支",RETURN,p+"/net",scope="既知31セッション"))
            measures.append(frequency(symbol,label+"の決済親勝率",RETURN,p,"winning_campaigns","campaigns","初回新規から全返済の親","既知31セッション","場内全返済","予定損益比又は中心到達率とは別の実親勝率"))
    rule("MANAGEMENT_NEW_THESIS_09", "継続判断", "失敗後の再参加は現在の根拠を取り直す", "観測極値を破って実損失で終わったら、自己と相手が失敗時の中心へ戻るまで反発参加を止める。",
        dict(比較="C09対同入口/停止C02", 休止成立="構造停止の証拠を保存した返済が実net<0", 中心="失敗した親の自己/相手中心を固定保存", 解除="返済後の自己正常quoteとさらに新しい相手公開が各中心±0.25幅へ帰還", 再準備="解除行より後、新しい基準。古い待機は使い回さない"),
        "双方帰還休止はTOPIX612,620円・NK158,840円改善したが、TOPIXは−780,964円、NKは最大利益日除外−61,560円が残った。より厳しい全窓更新C10は両方で悪化した。",
        dict(実測="失敗した同仮説への反復参加を抑える効果は保存対照で確認した", 仮説="中心帯以外の支持帯/新anchor方式は別の未検証条件であり、この対照の成功として転記しない"),
        ["初期停止/目標到達の順序問題は再参加だけで解けない", "中心への事後帰還8/11や6/6を、損切り前に勝てる確率と混同しない", "統合主C11の成功ではなく、C09とC02の部品対照"],measures,
        [source(RETURN,"/comparison_pairs/C09"),source("work/wave_v93/analysis/説明補足.json","/cause_notes/再参加"),source("work/wave_v93/engine.py",selector="failure_paused。実netと停止証拠、failure_self_seen/peer_seen、release_row")])

    measures=[]
    for symbol in SYMBOLS:
        p="/summary/C_OWN_T2/"+symbol
        measures.append(frequency(symbol,"全損失のうち利益追尾が発動する前の損失頻度",RISK,p+"/損失取引","net_loss_before_activation","count",
            "C_OWN_T2の手数料後損失親のみ","既知32セッション・各1枚","新規から場内全返済","損失を条件にした原因頻度。全入口の損失確率とは別"))
        measures.append(frequency(symbol,"全親での利益追尾発動頻度",RISK,p+"/全取引","profit_trail_activated","count",
            "C_OWN_T2の全実親","既知32セッション・各1枚","新規から場内全返済","当時の正常清算BBOで利益発動した親"))
        measures.append(frequency(symbol,"利益追尾発動親のうち利益で終えた頻度",RISK,p+"/利益取引","count","profit_trail_activated",
            "この群だけでは全発動親が分母にならないため下の算定へ置換","既知32セッション・各1枚","新規から場内全返済","分母は全取引の発動親へ正確に置換"))
        item=measures[-1]; total=int(resolve(RISK,p+"/全取引/profit_trail_activated"));item.update(total=total,value=item["successes"]/total,
            denominator="全実親のうち利益追尾が発動した親",denominator_pointer=p+"/全取引/profit_trail_activated",
            interpretation="発動後の選択群での勝率。入口時点の成功率として使えない")
        measures.append(number(symbol,"初期有効停止線までの距離中央値",RISK,p+"/全取引/quantiles/entry_stop_distance_ticks/1",kind="距離",unit="呼値",scope="既知32セッション・各1枚"))
    rule("EXIT_RISK_BEFORE_PROFIT_10", "出口", "利益追尾は発動前の損失を直せない", "固定支持2呼値の初期線で損切りし、費用回収＋2呼値順行してから床と2呼値追尾を開始する。",
        dict(比較="C_OWN_T2の保存親診断、B2/B4/Oとは同入口でも占有と後続親が変わる", 初期線="買max(support-2tick,E-S)、売min(support+2tick,E+S)",
             S="始値0.1%を呼値切上げ", F="実往復料/(q*m)を呼値切上げ", 発動="正常清算bestがE+d*(F+2tick)", 追尾="2tick、fee床E+d*F、有利側だけ更新", 数量="各1枚", 約定="次正常BBO"),
        "損失親のTOPIX287/291・NK149/151は追尾発動前。初期距離中央値は両4呼値で、利益幅2呼値と釣り合わない。発動済みだけなら145/149・89/91が利益でも、入口全体を高勝率とは言えない。",
        dict(実測="主な損失は入口と初期線の区間にあり、発動後利益を守る部品を直してもその損失は直接減らせない", 仮説="初期リスクと利益追尾を独立R単位にする105案は人工仕様まで。収益改善と確率は未検証"),
        ["損失群/発動群という事後選択の分母を入口確率と混同しない", "1枚の料床と全量の料床/Rは丸めが違い、円額比例で済ませない", "停止線は次quoteの損失上限ではない", "価格代理時計の保持秒数は真の通信時間ではない"],measures,
        [source(RISK,"/summary/C_OWN_T2"),source("work/wave_v104/engine/core.py",selector="simulateのsupport_line/initial_lineとprofit_trail"),source("work/wave_v105/engine/実行接口と制御台帳の仕様.json","/未検証")])

    assert len(RULES)==10 and len({r["id"] for r in RULES})==10
    checks=0
    for item in RULES:
        assert item["evidence"] and item["limitations"] and item["measurements"]
        assert set(x["symbol"] for x in item["measurements"])==set(SYMBOLS)
        for metric in item["measurements"]:
            resolve(metric["source"]["path"],metric["source"]["pointer"])
            if metric["successes"] is not None:
                assert 0<=metric["successes"]<=metric["total"] and metric["total"]>0
                assert abs(metric["value"]-metric["successes"]/metric["total"])<1e-12
            checks+=1
    output=dict(rules=RULES, scope="既存保存資料だけの部品知見。全期間既知・商品別、未取引を勝ちにしない",
        新金融再生=0,原板読取=0,NPZ読取=0,API取得=0,旧source変更=0,
        制約="観測頻度・同条件対照・費用恒等式・事後原因診断を区別。仮説は新しい実運用の勝率又は有効条件として昇格させない")
    target=HERE/"exit_technique_rules.json"
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    proof=dict(全合格=True,部品件数=10,測定件数=checks,入力SHA256={k:v[1] for k,v in CACHE.items()},
        抽出sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        出力SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),新金融再生=0,原板読取=0,API取得=0,
        範囲="JSON pointer存在、両商品、件数範囲、n/N恒等式、有限JSON。原会計の独立再監査ではない")
    (HERE/"収録範囲と指紋及びpointer検査.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(dict(全合格=True,部品件数=10,測定件数=checks,出力SHA256=proof["出力SHA256"]),ensure_ascii=False))


if __name__ == "__main__":
    main()
