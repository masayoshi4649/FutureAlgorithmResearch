"""第二〜四巡の確定会計を再集計し、参加・利益保護・数量配分の追補を保存する。"""

import json
from pathlib import Path
import statistics
import time
import numpy as np
import integrate_knowledge131 as integration

ROOT = integration.ROOT
WORK = integration.WORK
COMMON = integration.COMMON
HERE = Path(__file__).resolve().parent

PARTICIPATION = """
<a id="00131_旧核維持と一回参加の実測"></a>

## 旧手法を保った一回の補完は全場参加を達成したが、追加部分の予測力は別に残った

**出典：** [00131_時間帯と値動き状態を切り替える全場参加](../../00131_時間帯と値動き状態を切り替える全場参加/README.md)。

**当時条件：** 決めた時刻まで主手法の実新規が0なら、一度だけTOPIXミニ5枚／日経マイクロ10枚を別に建てる。判定にはその時点までの注文だけを使い、後で主手法が参加しても追加を取り消さない。S03は日中14時・ロンドン16時30分以後の二市場方向、S07は日中12時30分・米国現物開始30分後の始値方向。地域別夏時間と資料資格を反映し、不明時は有効情報まで待つ。主手法の入口・出口は保持する。

**分母・実運転：** 第二巡8条件×43場×2商品＝688商品場は全て参加。8条件とも両商品で全場合計黒字となり、通常入口まで増やした第一巡12条件の全場合計赤字を改善した。ただし複数の機構を戻した比較であり、改善全額を「一回にした効果」と断定しない。S03の累計はTOPIX＋767,561円・日経＋256,880円。

**寄与を分けた反証：** S03の日中はTOPIXの旧無取引2場を追加2親で埋め、1勝1敗・−13,336円。日経は旧無取引1場を含む追加4親で2勝2敗・＋4,120円。夜間はTOPIX追加3親が2勝1敗・＋1,246円だが、日経追加14親は2勝12敗・−70,080円で、夜間合算も−8,040円だった。追加数が旧無取引数より多いのは、追加した後で主手法も参加する場があるため。将来の無取引を事後選別していない。

**使い方・限界：** 参加要件の補完と入口精度の改善は別に評価する。主手法・追加・合算を分け、同方向の最大保有は10枚／20枚、反対側も独立に制限する。全数値は手数料後・既知43場の開発結果であり、全場参加を将来の黒字保証とはしない。

**根拠：** [第二巡の全会計](../../../work/regime131_20261020/round2/全条件の会計.json)、[旧核と追加の寄与](../../../work/regime131_20261020/round2/旧核と追加の寄与.json)、[日中の当時条件と反例](../../../work/regime131_20261020/day_diagnosis/第二巡日中の追加はなぜ負けたか.md)。
"""

EXIT = """
<a id="00131_同じ一回入口の保護開始と幅を分離する"></a>

## 同じ入口で利益保護を早めると負け戻りは減ったが、勝ちの伸びも短くなった

**出典：** [00131_時間帯と値動き状態を切り替える全場参加](../../00131_時間帯と値動き状態を切り替える全場参加/README.md)。

**当時条件：** S03／S07の追加担当だけ、初期1R損切り・方向・新規時刻・5枚／10枚を固定。1.5R起動・1R追尾から、起動／幅を0.75／0.5、1／0.5、1／0.75、1.25／0.75Rの4組へ変更した。Rは発注時の既知ATR・20分帯半幅・観測8呼値の最大値。元手法と一回限りの追加という制約は維持した。

**分母・結果：** 第三巡8条件×43場×2商品＝688商品場。S07→T05の日経夜間は同じ追加20親で9勝11敗→14勝6敗、追加収支−43,400→＋26,600円。旧核込みの21場は11黒字10赤字→15黒字6赤字、＋18,640→＋88,640円、無取引0。TOPIXの同21追加親も9勝12敗→13勝8敗だが、追加収支は−126,278→−23,778円でなお赤字。旧核込みは12黒字9赤字→15黒字6赤字となった。

**救った負け：** 日経9月22日夜間、同じ23:00:06買い66,850。旧S07は130円順行しても起動142.5円に届かず、23:40:43に66,750返済で−10,220円。T05は23:13:41に66,930で返し＋7,780円。事後最大値で利確価格を選んだのではなく、固定した低い起動幅と戻り幅が発動した。

**失う勝ちと限界：** 9月25日夜間の23:00:00売り66,100は、旧23:06:59返済65,970・＋12,780円に対し、T05は23:02:26返済66,070・＋2,780円となり1万円を失った。日経T05追加の残る6敗は−88,320円で、保護起動前の失敗が残る。0.75R／0.5Rが普遍的最適とはせず、日中・夜間と両商品で、失う利益・赤字数・大勝ち除外後を比較する。これらは既知期間の改修比較。

**根拠：** [第三巡条件](../../../work/regime131_20261020/第三巡条件.json)、[第二巡の全会計](../../../work/regime131_20261020/round2/全条件の会計.json)、[第三巡の全会計](../../../work/regime131_20261020/round3/全条件の会計.json)、[変更前の全親・勝ち反例](../../../work/regime131_20261020/night_diagnosis/第二巡夜間の利益保護待ちと反例.md)、[第三巡の追加寄与](../../../work/regime131_20261020/round3/旧核と追加の寄与.json)。
"""

SIZING = """
<a id="00131_発注時の幅に反比例した減枚は予測を変えない"></a>

## 広い初期幅では追加枚数を減らすと、同じ勝敗のまま大きな負けを軽くできた

**出典：** [00131_時間帯と値動き状態を切り替える全場参加](../../00131_時間帯と値動き状態を切り替える全場参加/README.md)。

**当時条件：** T04／T05の追加担当の発注時に、基本枚数×予算呼値数×観測呼値÷初期Rの小数を切り捨て、最低1枚・基本枚数以下にする。基本はTOPIX5枚／日経10枚、予算は8・12・16・24呼値。式は `max(1, min(基本枚数, floor(基本枚数×予算呼値数×観測呼値÷R)))`。方向・新規と返済の時刻・停止価格・追尾条件は変えず、数量を保有後に選び直さない。観測ラージ呼値はTOPIX0.5pt／日経10円で、実ミニ・マイクロの刻みと区別する。

**分母・U06の実測：** 第四巡8条件×43場×2商品＝688商品場。12呼値予算のU06は、T05の夜間追加のうち日経4/20親・TOPIX4/21親だけを減枚した。日経では2勝の利益4,490円を失う代わりに2敗の損失28,542円を減らし、追加収支＋26,600→＋50,652円。合算21場は15黒字6赤字・無取引0のまま、累計＋88,640→＋112,692円、上位3黒字除外＋27,400→＋39,842円。赤字場の平均損失11,663→8,841円、中央値8,720円は不変、最大赤字28,220→16,440円だった。

**具体例と代償：** 日経10月15日夜間は発注時R290円なので10→4枚。23:00:00売り64,380→23:04:08返済64,660の負けを−28,220→−11,288円へ縮小した。一方、10月16日23:00の売りはR180円で10→6枚となり、元の勝ち＋7,780→＋4,668円へ減った。TOPIXも夜間の合算15黒字6赤字は同じまま＋233,240→＋280,828円となったが、T05由来の日中6追加親では減枚が0件で、日中の負けを解決する変更にはならなかった。

**使い方・限界：** 方向の精度を上げた結果ではなく、発注時に分かる損失幅へ数量を合わせた結果。大勝ちを消すことを目的にせず、失った勝ちと赤字数・平均／中央損失・大勝ち除外後を併記する。別の入口T04由来のU02では日経夜間の収支が−6,040→−7,830円と悪化した。一般の減枚効果とはしない。実測では最低1枚による予算超過0件だったが、極端なR・次気配への価格飛び・費用により実損失は予算を超え得る。

**根拠：** [第四巡条件](../../../work/regime131_20261020/第四巡条件.json)、[全条件の会計](../../../work/regime131_20261020/round4/全条件の会計.json)、[旧新の全数量と失った利益・減った損失](../../../work/regime131_20261020/round4/枚数変更と失う利益の対応.json)、[固定枚数の大敗と勝ち反例](../../../work/regime131_20261020/night_diagnosis/第三巡夜間の初期幅と固定枚数の損失集中.md)。
"""


def read(path: Path) -> dict:
    """
    機能: 保存済みJSONを読み込む。
    引数: path(Path)は保存資料。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def group(rows: list[dict], method: str, symbol: str, kind: str) -> dict:
    """
    機能: セッション会計から親数・合算と追加の損益を独立に集計する。
    引数: rows(list[dict])、method/symbol/kind(str)は保存行と抽出条件。
    返り値: dictは分母と金額。
    """
    selected = [r for r in rows if r["method"] == method and r["symbol"] == symbol
        and (kind == "全体" or r["kind"] == kind)]
    extra = [r["components"]["追加"] for r in selected]
    losses = [-r["net"] for r in selected if r["net"] < 0]
    return dict(sessions=len(selected), net=sum(r["net"] for r in selected),
        black=sum(r["net"] > 0 for r in selected), red=len(losses),
        empty=sum(r["entries"] == 0 for r in selected),
        without_top3=sum(sorted([r["net"] for r in selected], reverse=True)[3:]),
        mean_red=statistics.mean(losses), median_red=statistics.median(losses),
        worst=min(r["net"] for r in selected),
        extra_entries=sum(e["entries"] for e in extra),
        extra_wins=sum(e["net"] > 0 for e in extra),
        extra_losses=sum(e["net"] < 0 for e in extra),
        extra_net=sum(e["net"] for e in extra),
        extra_loss=sum(e["loss"] for e in extra))


def main() -> None:
    """
    機能: 引用数値・同じ新規・費用後会計を保存結果へ照合し、3追補を統合する。
    引数: なし。
    返り値: None。金融再生0、保存元は読み取り専用。
    """
    paths = [WORK / r / "全条件の会計.json" for r in ("round1_final", "round2", "round3", "round4")]
    accounts = {p.parent.name: read(p) for p in paths}
    changes_path = WORK / "round4/枚数変更と失う利益の対応.json"
    changes = read(changes_path)
    paths.append(changes_path)
    assert all(len(accounts[r]["rows"]) == 688 for r in ("round2", "round3", "round4"))
    assert all(r["entries"] > 0 for r in accounts["round2"]["rows"])
    for m in {r["method"] for r in accounts["round2"]["rows"]}:
        for symbol in ("TOPIX", "NK225"):
            assert group(accounts["round2"]["rows"], m, symbol, "全体")["net"] > 0
    groups = {}
    for ro, methods in (("round2", ("S03", "S07")), ("round3", ("T04", "T05", "T06")),
                        ("round4", ("U02", "U06"))):
        for method in methods:
            for symbol in ("TOPIX", "NK225"):
                for kind in ("Day", "Night", "全体"):
                    groups[f"{ro}/{method}/{symbol}/{kind}"] = group(accounts[ro]["rows"], method, symbol, kind)
    for name, net, black, red, extra_entries, extra_net in (
        ("round2/S03/TOPIX/全体", 767561, 33, 10, 5, -12090),
        ("round2/S03/NK225/全体", 256880, 25, 18, 18, -65960),
        ("round2/S07/NK225/Night", 18640, 11, 10, 20, -43400),
        ("round3/T05/NK225/Night", 88640, 15, 6, 20, 26600),
        ("round3/T05/TOPIX/Night", 233240, 15, 6, 21, -23778),
        ("round4/U06/NK225/Night", 112692, 15, 6, 20, 50652),
        ("round4/U06/TOPIX/Night", 280828, 15, 6, 21, 23810)):
        v = groups[name]
        assert (v["net"], v["black"], v["red"], v["extra_entries"], v["extra_net"]) == (
            net, black, red, extra_entries, extra_net), name
    # ----------------------------------------
    # 第三巡の8条件すべてで新規と旧核が同じことを、保存注文から照合する。
    compared = 0
    for ref in accounts["round3"]["cache"]:
        filename = f'{ref["symbol"]}_{ref["session"]}.npz'
        with np.load(WORK / "round2/measurement" / filename) as old, np.load(ROOT / ref["path"]) as new:
            for n in range(1, 9):
                before = "S03" if n <= 4 else "S07"
                after = f"T{n:02d}"
                np.testing.assert_array_equal(old[before + "__extra_orders"][:1],
                    new[after + "__extra_orders"][:1])
                np.testing.assert_array_equal(old[before + "__core_orders"], new[after + "__core_orders"])
                np.testing.assert_array_equal(old[before + "__extra_trades"][:, 10],
                    new[after + "__extra_trades"][:, 10])
                compared += 1
    assert compared == 688
    selected_pairs = [x for x in changes["pairs"] if x["method"] == "U06"
        and x["old_quantity"] != x["quantity"]]
    nk = [x for x in selected_pairs if x["symbol"] == "NK225"]
    top = [x for x in selected_pairs if x["symbol"] == "TOPIX"]
    assert len(nk) == 4 and len(top) == 4
    assert all(x["kind"] == "Night" for x in selected_pairs)
    assert sum(-x["change"] for x in nk if x["old_net"] > 0) == 4490
    assert sum(x["change"] for x in nk if x["old_net"] < 0) == 28542
    assert groups["round3/T05/NK225/Night"]["median_red"] == groups["round4/U06/NK225/Night"]["median_red"] == 8720
    # ----------------------------------------
    # 同じ法則内の追補とし、既存本文や案内を変更しない。
    integration.PLACEMENT.update({
        "00131_旧核維持と一回参加の実測": "無取引をなくす一回の参加と、通常入口を増やすことは別の変更",
        "00131_同じ一回入口の保護開始と幅を分離する": "起動幅未満の利益返しは多いが、全ての負けを出口だけで救えない",
        "00131_発注時の幅に反比例した減枚は予測を変えない": "初回予定リスクの整数数量は両商品で参加量を大きく変える",
    })
    changed_files = []
    for name, blocks in (("売買の工夫.md", (PARTICIPATION, SIZING)), ("出口.md", (EXIT,))):
        path = COMMON / name
        before = path.read_bytes()
        body = before.decode("utf-8")
        additions = []
        for block in blocks:
            body, addition = integration.add_block(body, block)
            links = integration.check_links(path, addition["addition"])
            assert all(x["exists"] for x in links)
            additions.append({k: v for k, v in addition.items() if k != "addition"})
        result = body.encode("utf-8")
        path.write_bytes(result)
        links = integration.check_links(path, body)
        assert all(x["exists"] for x in links)
        changed_files.append(dict(path=str(path.relative_to(ROOT)), before_sha256=integration.sha(before),
            after_sha256=integration.sha(result), additions=additions, relative_links=len(links)))
    proof = dict(passed=True, financial_replays=0, source_arrays_modified=False,
        groups=groups, third_round_same_entry_and_core_accounts=compared,
        quantity_changed_pairs=selected_pairs, modified_common_files=changed_files,
        sources={str(p.relative_to(ROOT)): integration.sha(p.read_bytes()) for p in paths},
        script_sha256=integration.sha(Path(__file__).read_bytes()),
        scope="第二〜四巡の保存会計の再集計。未知期間の試験ではない。案内と金融源は未変更。")
    target = HERE / f"第二三四巡知見の統合と分母照合_{time.time_ns()}.json"
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.as_posix(), "保存会計688件の入口同値・3追補", flush=True)


if __name__ == "__main__":
    main()
