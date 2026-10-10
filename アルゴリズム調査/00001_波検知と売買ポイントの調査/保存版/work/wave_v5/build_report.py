"""検知・両建て・無作為方向を同じ単位でセッション収支へまとめる。"""

from __future__ import annotations

from dataclasses import asdict
import json

import numpy as np
import pandas as pd

from search import OUT, ConfigV5, evaluate, load_data_v5, ranking_metrics, save_json
from hedge import HedgeConfig, simulate as simulate_hedge

MULTIPLIERS = {"NK225": 1000., "TOPIX": 10000.}


def read_json(name: str) -> dict:
    """機能: 保存された研究結果だけを読み込む。

    引数: name (str)。返り値: 内容 (dict)。
    """
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def table(headers: list[str], rows: list[list]) -> str:
    """機能: 数値比較を日本語資料向けの表に整える。

    引数: headers (list[str])、rows (list[list])。返り値: 表 (str)。
    """
    return "\n".join(["|" + "|".join(headers) + "|", "|" + "|".join(["---"] * len(headers)) + "|"] +
                     ["|" + "|".join(map(str, row)) + "|" for row in rows])


def convert_hedge_cell(cell: dict, normalize_ranking: bool = False) -> dict:
    """機能: 両建て・無作為方向の集計列を方向戦略と共通の列へ変換する。

    引数: cell (dict)、normalize_ranking (bool) は順位用の総絶対枚数補正。
    返り値: 共通列 (dict)。収支は脚ごとの費用後利益と損失から計算する。
    """
    quantity = cell["gross_absolute_entry_quantity"] if normalize_ranking else 1
    return dict(session=cell["session"], symbol=cell["symbol"], count=cell["cycle_count"],
        legs=cell["count"], closed=cell["closed"], profit=cell["profit_points"], loss=cell["loss_points"],
        net=cell["net_points"], stress=cell["stress_points"], wins=cell["wins"],
        net_atr=cell["net_atr"] / quantity, stress_atr=cell["stress_atr"] / quantity,
        dd_atr=cell["realized_dd_atr"] / quantity, dd=cell["realized_dd_points"],
        micro15_count=0, cost=(20 if cell["symbol"] == "NK225" else 1) * cell["closed"])


def choose_hedge(frame: pd.DataFrame) -> tuple[str, dict, list[dict]]:
    """機能: 全種平均または両建てセルの順位を、方向戦略と同じ指標で計算する。

    引数: frame (DataFrame)。返り値: 条件名・順位指標・共通セル (tuple)。
    """
    choices = []
    for key, group in frame.groupby("config", sort=False):
        cells = [convert_hedge_cell(c, True) for c in group.to_dict("records")]
        choices.append((key, ranking_metrics(cells), [convert_hedge_cell(c) for c in group.to_dict("records")]))
    return sorted(choices, key=lambda x: (not x[1]["eligible"], -x[1]["score"], x[0]))[0]


def money_rows(cells: list[dict]) -> list[list]:
    """機能: セッション別の利益・損失・差引をラージ各一枚の万円へ換算する。

    引数: cells (list[dict])。返り値: 表の行 (list[list])。
    """
    rows = []
    for c in sorted(cells, key=lambda x: (x["session"], x["symbol"])):
        factor = MULTIPLIERS[c["symbol"]] / 10000
        session = c["session"].replace("2026-", "").replace("_Day", " 日中").replace("_Night", " 夜間")
        rows.append([session, c["symbol"], f'{c["count"]:g}', f'{c["profit"] * factor:.2f}',
                     f'{abs(c["loss"]) * factor:.2f}', f'{c["net"] * factor:+.2f}', f'{c["stress"] * factor:+.2f}'])
    for symbol in ("NK225", "TOPIX"):
        chosen = [c for c in cells if c["symbol"] == symbol]
        factor = MULTIPLIERS[symbol] / 10000
        rows.append(["合計", symbol, f'{sum(c["count"] for c in chosen):g}',
            *[f'{abs(sum(c[field] for c in chosen)) * factor:.2f}' for field in ("profit", "loss")],
            *[f'{sum(c[field] for c in chosen) * factor:+.2f}' for field in ("net", "stress")]])
    return rows


def direction_description(cfg: dict, name: str) -> str:
    """機能: 実行条件を短い日本語の検知・入口・返済説明にする。

    引数: cfg (dict)、name (str)。返り値: 説明文 (str)。
    """
    entry = {"signal_limit": "方向を検知した後、価格の許容幅を付けた指値条件で入る",
             "stop": f'基準価格から{cfg["offset"]:g}ATRだけ方向側に進んだら逆指値で入る',
             "pullback": f'方向に逆らう{cfg["offset"]:g}ATRの押し目・戻りを待って入る',
             "trail": f'追跡安値から{cfg["offset"]:g}ATR反発したら買い、追跡高値から同幅反落したら売る'}.get(cfg["entry"], cfg["entry"])
    mode = cfg["exit_mode"]
    if mode == "fixed_bracket":
        exit_text = f'IFD-OCO相当として、新規時ATRの{cfg["stop_loss"]:g}倍で損切り、{cfg["take_profit"]:g}倍で利確'
    else:
        initial = min(2.5, cfg["trail"]) if mode == "nativebaseline" else cfg["stop_loss"]
        basis = "新規時" if cfg["trail_basis"] == "entry" else "その時点で既知の"
        exit_text = f'初期損切りは新規時ATRの{initial:g}倍。その後は{basis}ATRの{cfg["trail"]:g}倍の追跡幅で返済'
    return (f'**{name}**で買い／売り方向を判断する（感度倍率{cfg["param"]:g}）。'
            f'セッション開始から{cfg["warmup"]}分待ち、{entry}。{exit_text}する。'
            f'返済後は{cfg["cooldown"]}分待って次の取引へ進む。')


def main() -> None:
    """機能: 主候補と注文単独の代表を区別して、全セッションの収支を保存する。

    引数: なし。返り値: なし (None)。同じデータで選ぶ探索結果として明記する。
    """
    primary = read_json("方向主候補.json")
    direction_table = pd.read_csv(OUT / "方向全条件比較.csv")
    hedge = pd.read_csv(OUT / "両建て_セル.csv")
    coin = pd.read_csv(OUT / "コイントス_セッション平均.csv")
    distribution = pd.read_csv(OUT / "コイントス_条件別分布.csv")
    hedge_plan = read_json("両建て_探索計画.json")
    hedge_configs = {item["key"]: {k: v for k, v in item.items() if k != "key"} for item in hedge_plan["条件"]}
    data = load_data_v5()
    methods = [dict(id="方向主候補", name="方向を検知する主候補", config=primary["config"],
                    description=direction_description(primary["config"], primary["name"]), cells=primary["cells"], trades=primary["trades"],
                    metrics=primary["summary"], quantity=1)]
    for mode in ("fixed_bracket", "small_stop_trail"):
        row = direction_table[direction_table.exit_mode.eq(mode)].iloc[0]
        item = read_json(f"方向候補_{row.config}.json")
        methods.append(dict(id=mode, name="方向検知＋固定損小利大" if mode == "fixed_bracket" else "方向検知＋小損切りと追跡",
                            config=item["config"], description=direction_description(item["config"], item["name"]),
                            cells=item["cells"], trades=item["trades"], metrics=item["summary"], quantity=1))
    for mode in ("固定利確", "勝ち脚追跡"):
        key, metrics, cells = choose_hedge(hedge[hedge.exit_mode.eq(mode)])
        cfg = HedgeConfig(**hedge_configs[key])
        trades = [t for item in data.values() for t in simulate_hedge(item, cfg)[0]]
        if mode == "固定利確":
            description = f'買い１枚と売り１枚から始め、各脚を{cfg.stop:g}ATRで損切り、{cfg.target:g}ATRで利確する。各新規に利確・損切りを付けるIFD-OCO相当。'
        else:
            description = f'買い１枚と売り１枚から始め、{cfg.stop:g}ATR逆行した脚を損切りする。残った脚を新規時ATRの{cfg.target:g}倍で追跡して利益を伸ばす。'
        description += f'開始{cfg.warmup}分待ち、両脚の返済後{cfg.cooldown}分待って再開する。'
        methods.append(dict(id=f"両建て_{mode}", name=f"両建て＋{mode}", config=asdict(cfg), description=description,
                            cells=cells, trades=trades, metrics=metrics, quantity=2))
    key, metrics, cells = choose_hedge(coin)
    coin_cfg = HedgeConfig(**hedge_configs[key])
    methods.append(dict(id="コイントス平均", name="片側コイントス・100種平均", config=asdict(coin_cfg),
        description=f'各回の売買方向を公平なコイントスで決める。出口は{coin_cfg.exit_mode}、初期損切り{coin_cfg.stop:g}ATR、利確／追跡幅{coin_cfg.target:g}ATR、開始{coin_cfg.warmup}分待ち、返済後{coin_cfg.cooldown}分待機。100通りの平均収支で条件を比較し、最も儲かった乱数種は選ばない。',
        cells=cells, trades=[], metrics=metrics, quantity=1,
        distribution=distribution[distribution.config.eq(key)].to_dict("records")))

    # ----------------------------------------
    # 費用後の利益と損失を両方表示する。両建ては各脚を分けたまま合計する。
    rows, headline = [], []
    for method in methods:
        for c in method["cells"]:
            multiplier = MULTIPLIERS[c["symbol"]]
            assert np.isclose(c["profit"] - c["loss"], c["net"])
            rows.append(dict(手法=method["name"], セッション=c["session"], 銘柄=c["symbol"], 回数=c["count"],
                脚数=c.get("legs", c["count"]), 最大初期枚数=method["quantity"],
                利益価格幅=c["profit"], 損失価格幅=abs(c["loss"]), 収支価格幅=c["net"], 厳格収支価格幅=c["stress"],
                利益円=c["profit"] * multiplier, 損失円=abs(c["loss"]) * multiplier,
                収支円=c["net"] * multiplier, 厳格収支円=c["stress"] * multiplier,
                一枚あたり比較収支円=c["net"] * multiplier / method["quantity"]))
        totals = {symbol: {field: sum(c[field] for c in method["cells"] if c["symbol"] == symbol)
                           for field in ("net", "stress", "profit", "loss", "count")} for symbol in MULTIPLIERS}
        headline.append([method["name"], *[f'{totals[s]["net"] * MULTIPLIERS[s] / 10000:+.2f}' for s in MULTIPLIERS],
                         *[f'{totals[s]["stress"] * MULTIPLIERS[s] / 10000:+.2f}' for s in MULTIPLIERS],
                         "満たす" if method["metrics"]["eligible"] else "満たさない"])
        if method["trades"]:
            pd.DataFrame(method["trades"]).to_csv(OUT / f'{method["id"]}_全取引.csv', index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(OUT / "セッション別利益損失.csv", index=False, encoding="utf-8-sig")
    save_json(OUT / "報告対象手法.json", methods)

    # ----------------------------------------
    # 時系列と除外検証は主候補の全期間成績から区別する。
    folds = read_json("方向分割検証.json")
    fold_rows = []
    for fold in folds:
        for c in fold["cells"]:
            factor = MULTIPLIERS[c["symbol"]] / 10000
            fold_rows.append([fold["method"], c["session"], c["symbol"], f'{c["net"] * factor:+.2f}',
                              f'{c["stress"] * factor:+.2f}', fold["chosen"]["config"]])
    pd.DataFrame(fold_rows, columns=["方式", "検証セッション", "銘柄", "収支万円", "厳格収支万円", "選択条件"]).to_csv(
        OUT / "方向分割検証.csv", index=False, encoding="utf-8-sig")
    tradeoff = pd.read_csv(OUT / "入口と微細波比較.csv")
    focus = tradeoff[tradeoff.比較.isin(["基準", "新規方式_signal_limit", "新規方式_stop", "新規方式_pullback", "新規方式_trail",
        "方向確認_3分", "方向確認_5分", "追加１分遅延", "追加２分遅延", "追跡幅_1.5ATR", "追跡幅_2.5ATR", "追跡幅_4ATR", "損切り_0.5ATR", "損切り_1.5ATR"])]
    tradeoff_rows = [[r.比較, r.銘柄, r.件数, r.十五分以内, f'{r.保有時間中央値:g}',
        f'{r.収支 * MULTIPLIERS[r.銘柄] / 10000:+.2f}', f'{r.十五分以内収支 * MULTIPLIERS[r.銘柄] / 10000:+.2f}']
        for r in focus.itertuples(index=False)]
    risk = pd.read_csv(OUT / "終値評価リスク.csv")
    risk_rows = []
    for item in risk[risk.method.eq("方向主候補")].to_dict("records"):
        factor = MULTIPLIERS[item["symbol"]] / 10000
        risk_rows.append([item["session"], item["symbol"], f'{item["realized_loss_points"] * factor:.2f}',
                          f'{item["worst_aggregate_unrealized_loss_points"] * factor:.2f}',
                          f'{item["max_drawdown_points"] * factor:.2f}'])
    header = ["セッション", "銘柄", "取引／組数", "利益合計", "損失合計", "差引収支", "費用倍の収支"]
    lines = ["# エントリー・微細な波・両建てと損小利大の比較", "",
        "保存済み５セッション、両銘柄を使用。今回は現在セッションAPIを取得していない。9月23日デイの原本は引けの足まで追加されたが、前回確定済みだった区間は一致している。前回既に見た期間なので、今回の結果は新たな未使用期間での合格ではなく、既知データ上の探索結果である。", "",
        f"方向検知は24系統を中心とする{len(direction_table):,}条件、両建て108条件、同じ注文条件の片側コイントス108条件×100種を比較した。指定された全波の捕捉を選定条件から外した。４ティック控除後も両銘柄合計が正、銘柄ごと平均１回以上、セッション当たり12回以下を優先し、収支の低い銘柄・悪いセッション・実現ドローダウンも得点に入れた。", "",
        "## 金額と利益・損失の定義", "",
        "**以下はラージ１枚、単位は万円。両建ては買い１枚＋売り１枚。** 利益合計は費用控除後に利益だった取引だけの合計、損失合計は損失取引の絶対額。差引収支＝利益合計−損失合計。各脚の往復費用を２ティック控除し、費用倍は４ティック控除。実際の約定結果や税引後利益ではなく、保存価格による仮想売買である。", "",
        "NK225は１円幅×1,000円、TOPIXは１ポイント×10,000円で換算。したがって基準の往復控除はNK225２万円、TOPIX１万円／脚。これは手数料・スプレッド・滑りをまとめた比較仮定で、証券会社の実料金ではない。[JPX・日経225先物](https://www.jpx.co.jp/derivatives/products/domestic/225futures/01.html)、[JPX・TOPIX先物](https://www.jpx.co.jp/derivatives/products/domestic/topix-futures/)。", "",
        "ATRは直近の通常の値動き幅の目安。ここでは確定済み５分足の真の値幅を係数1/12で指数平均し、最低２ティックとした。新規時ATR固定なら保有中の幅を広げない。", "",
        "## 全期間の比較", "", table(["手法", "NK収支", "TOP収支", "NK費用倍", "TOP費用倍", "選定制約"], headline), "",
        "両建ては初期２枚の総絶対枚数なので、片建て１枚と同じ枚数ではない。CSVに両建て収支を２で割った比較値も保存した。枚数補正をしても、両建て中の価格変動が相殺される性質や必要証拠金まで同一になるわけではない。", ""]
    for method in methods:
        lines.extend([f'## {method["name"]}', "", method["description"], "", table(header, money_rows(method["cells"])), ""])
        if method["id"] == "方向主候補":
            time_exits = sum("時刻" in trade["reason"] for trade in method["trades"])
            lines.extend(["主候補の具体的な方向判定は、１分終値差をその時点のATRで割り、上方向と下方向へ別々に累積する。各分0.025を微小変動として差し引き、片側の累積が0.6375に達したらその側へ方向を切り替えて累積を初期化する。反対側が成立するまでは方向を維持する。将来の極値から波を判定しない。", "",
                f'今回の主候補は12取引中{time_exits}取引がセッション終盤の時刻返済。保有中央値はNK225357.5分、TOPIX343分であり、細かく出入りする方式ではない。初期損切り2.5ATRと追跡4ATRの幅を許容して大きな方向を保持する。設定JSONのstop_loss/take_profitは追加返済方式用の項目で、nativebaselineでは使用せず、上記の幅で動く。', ""])
        if method["id"].startswith("両建て"):
            lines.extend(["回数は両建ての組数で、脚数はその２倍。利益・損失は各脚を分けて集計している。両建て中は同量の買いと売りの値動き損益が相殺され、負け脚を返済してから残る方向の値動きで組全体の利益を狙う。", ""])
        if method["id"] == "コイントス平均":
            lines.extend(["100種平均なので回数・利益・損失は小数となる。これは実現した一本の売買経路ではなく、同じ相場上の方向乱数に対する平均である。100日分の市場標本ではない。", "",
                table(["銘柄", "100種中の利益割合", "５〜95百分位収支・万円", "最小〜最大収支・万円"],
                    [[d["symbol"], f'{d["positive_seed_fraction"]:.0%}',
                      f'{d["p05_net_points"] * MULTIPLIERS[d["symbol"]] / 10000:+.2f}〜{d["p95_net_points"] * MULTIPLIERS[d["symbol"]] / 10000:+.2f}',
                      f'{d["min_net_points"] * MULTIPLIERS[d["symbol"]] / 10000:+.2f}〜{d["max_net_points"] * MULTIPLIERS[d["symbol"]] / 10000:+.2f}'] for d in method["distribution"]]), ""])
    lines.extend(["## 同じ検知法で入口と微細な波の扱いだけを変える", "",
        "主候補の他条件を固定し、一項目ずつ変えた比較。追跡幅の比較では初期損切り2.5ATRを固定し、追跡幅と同時に初期損切りまで狭くならないようにした。微細な往復の代理として保有15分以内の件数と、その取引群の収支を表示した。15分以内が全て無意味な波という定義ではない。この比較で良かった変更へ主候補を選び直していない。", "",
        table(["変更", "銘柄", "件数", "15分以内件数", "保有中央値・分", "全収支・万円", "15分以内収支・万円"], tradeoff_rows), "",
        "入口の反発・反落幅を1ATRから0.25ATRへ縮めると、合計収支はNK225189→206万円、TOPIX62→78万円になった一方、NK225には８万円の確定損失が発生した。早い入口で利益が増える場合もあり、遅いほど良いという単純な関係ではない。全設定の順位基準は収支合計だけでなくATR基準の低調なセッションと実現DDも含むため、合計最大の条件を主候補としていない。", "",
        "返済追跡幅を4ATRから1.5ATRへ狭めると、NK225は６→19取引、TOPIXは６→17取引に増え、収支は189→53万円、62→21万円へ低下した。15分以内の往復は５件・６件、その群の収支は−40万円・−８万円。小さな値動きで返済し過ぎる負担が今回の標本で現れた。", "",
        "入口を待つと不利な初動を避けられる一方、押し戻りが来ない一方向の波には入れない。追跡幅を狭くすると利益を早く守れる一方、小さな揺れで返済して往復費用と再新規が増える。結果は方式ごとに異なるので、全ての波を取れるかより、見送り・細かい損切り・残せた利益の合計で比べた。", "",
        "## 確定損失と保有中の損失", "",
        "確定損失ゼロは含み損ゼロではない。各新規時に往復費用を全額控除し、保有中の脚を各１分終値で評価した。下表の最大DDはそのセッション内の資産高値からの最大低下、含み損は保有中建玉の価格損益だけの最悪値。両者は別指標で、いずれも瞬間最大値ではない。主候補はNK225で29万円の含み損、最大32万円のDDを観測した。", "",
        table(["セッション", "銘柄", "確定損失・万円", "最悪含み損・万円", "最大DD・万円"], risk_rows), "",
        "全５方式・50セルで時価評価の最終残高が実現収支と一致することを検算した。両建ての相殺される合算含み損と、各脚単独の含み損も `終値評価リスク.csv` に分けている。", "",
        "## セッションを選択対象から外した検算", "",
        "時系列は最初の３セッションで選んで４番目へ、最初の４セッションで選んで５番目へ適用。一セッション除外は残り４セッションで条件を選び、除外したセッションへ適用した。どちらも検証側をその回の条件順位に含めていない。ただし研究者は全期間を過去の探索で既に見ているため、将来運用の独立な保証にはならない。", "",
        table(["方式", "検証セッション", "銘柄", "収支・万円", "費用倍・万円"], [row[:5] for row in fold_rows]), "",
        "方向戦略は最初の４セッションだけで選び直すと、別の回帰・押し戻り候補が選ばれ、9月23日のNK225は−54万円（費用倍−58万円）だった。５セッション全体から選んだ主候補の全セッション黒字を、そのまま次の相場でも再現する裏付けにはできない。", "",
        "両建ても一セッションを除外して選ぶ５回の合計はNK225＋54万円、TOPIX＋4.5万円、費用倍では＋６万円・−13.5万円へ落ちた。片側コイントス平均は同じ比較で−20.72万円・−11.105万円。時間順・除外検証の全セルと、訓練期間に適格条件がなかった場合の区別は `両建て_代表比較.md` と `両建てコイントス_期間外比較.csv` に記録した。", "",
        "## 執行の共通条件と限界", "",
        "全てセッション内返済。日中15:35、夜間05:50以後の最初の実在足で閉じ、新規は30分前に停止する。現在時点より先の足を指標へ使わず、分の情報は確定後さらに１分遅らせて新規判定する。無約定分を埋めた架空の約定は作らない。", "",
        "トレーリングは確定した１分足の極値を使い、次の足から保護を更新する。ネイティブAPIの連続trailと同一の成績ではない。固定利確・損切りに同足で触れ、順序不明なら損切り優先。ただし始値ですでに成立していた条件の順序は尊重し、利確の有利な始値ギャップは指値価格で頭打ちにする。", "",
        "AGENTSのmarketは返済専用。新規の即時型も許容価格付きlimitで近似する。両建ては買いと売りの二本の新規であり、同方向二条件を扱うOCOではない。それぞれの脚にIFDまたはIFD-OCO相当の返済条件を置く。同時に同価格で二脚が約定すること、片脚未約定・注文到着・部分約定・取消照合は再現できていない。費用を倍にした結果も併記した。", "",
        "生板の数量・注文フローを使う検知も比較したが、板の受信時刻がないため次の異なる最終約定時刻まで待って利用している。新日中のTOPIXには板から作る価格と保存足との0.5ポイント差が３項目あり、価格と約定は保存足を正本にした。`データ監査.md`、`注文監査.md`、`独立監査.md` に記録した。", "",
        "## 成果物", "",
        "`セッション別利益損失.csv` が表示した全手法の利益・損失・収支の正本。`報告対象手法.json` に設定と取引、`方向全条件比較.csv` と `方向全条件セッション.csv` に全方向条件、`両建て_セル.csv` と `コイントス_セッション平均.csv` に全注文条件を保存した。`入口と微細波比較.csv` には一項目ずつ変えた全比較を含む。", ""])
    (OUT / "検証結果.md").write_text("\n".join(lines), encoding="utf-8")
    print(table(["手法", "NK収支", "TOP収支", "NK費用倍", "TOP費用倍", "選定制約"], headline))


if __name__ == "__main__":
    main()
