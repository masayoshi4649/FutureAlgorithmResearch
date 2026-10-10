"""出口変更の増益・早降り・再新規を分けて、日本語の比較資料へまとめる。"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import shutil

import pandas as pd

from shared import OUT, ROOT, SESSIONS, SYMBOLS, MULTIPLIERS, load_inputs, save_json
from search_exits import evaluate, is_baseline
from exit_engine import ExitRule


DEST = ROOT / "アルゴリズム調査" / "00002_出口の利益保護の検証"
NAMES = {"baseline":"元の固定４ATR", "fixed_trail":"最初から追跡幅を縮小", "current_atr":"現在のATRへ追跡幅を追随",
         "breakeven":"一定利益後に費用込み建値を保護", "stepped":"一定利益後に追跡幅を縮小",
         "profit_lock":"一定利益後に利益の一定割合を保護", "progressive":"利益段階に応じて順次縮小",
         "structure":"直近の確定高安で保護", "stagnation":"高安更新の停滞で返済",
         "reversal":"CUSUM反対方向の確認で返済", "target":"固定幅の指値利確"}


def money(value: float) -> str:
    """機能: 円を万円の短い表記へ変換する。

    引数: value (float) は円金額。
    返り値: 万円表記 (str)。単位文字は付けない。
    """
    return "0" if abs(value) < 1e-9 else f"{value/10000:+.2f}".rstrip("0").rstrip(".")


def totals(cells: list[dict], symbol: str) -> dict:
    """機能: セル指標を銘柄ごとに合計する。

    引数: cells (list[dict])、symbol (str)。
    返り値: 件数と金額合計 (dict)。
    """
    keys = ("count", "profit_yen", "loss_yen", "net_yen", "stress_yen", "giveback_yen")
    return {key:sum(c[key] for c in cells if c["symbol"] == symbol) for key in keys}


def trade_key(trade: dict) -> tuple:
    """機能: 同じ入口の取引を対応させる識別子を作る。

    引数: trade (dict)。返り値: セッション・銘柄・新規時刻 (tuple)。
    """
    return trade["session"], trade["symbol"], str(trade["entry_time"])


def main() -> None:
    """機能: 利益保護の比較候補を明示し、全結果と図解用のデータを出力する。

    引数: なし。
    返り値: なし (None)。比較候補は適格な採用候補と混同しない。
    """
    DEST.mkdir(parents=True, exist_ok=True)
    data, schedules, cfg, primary = load_inputs()
    ranked = json.loads((OUT / "比較対象.json").read_text(encoding="utf-8"))
    table = pd.read_csv(OUT / "出口全条件比較.csv")
    result = json.loads((OUT / "出口全条件取引.json").read_text(encoding="utf-8"))
    # ----------------------------------------
    # 最適と宣言せず、ユーザーが指摘した利益返却を改善できる具体的な取引例を図示する。
    rule = ExitRule("stepped", trigger=2.5, width=.5)
    full, full_cells = evaluate(data, schedules, cfg, rule, primary, False, trace=True)
    fixed, fixed_cells = evaluate(data, schedules, cfg, rule, primary, True, trace=True)
    note = "利益保護の挙動を確認する比較候補です。192条件を見た後に図示用として取り上げました。訓練期間の両銘柄の収支を元の90%以上保つ条件は未達で、採用決定ではありません。再新規込みの５セッション収支はNK225が189→159万円、TOPIXが62→70万円です。"
    description = "入口は元の方法①と同じ。初期損切り2.5A・追跡幅4Aを保ち、確定した有利値幅が2.5Aへ達した後だけ追跡幅を0.5Aへ縮めます。Aは新規注文作成時に固定したATR。変更した保護価格は次の実在１分足から有効、保護価格を不利な側へ戻しません。返済後45分待てば同じ入口ルールで再新規します。"
    payload = dict(baseline=ranked["baseline"], selected=dict(name="2.5ATRの利益後に0.5ATRで追跡する比較候補",
                   description=description, rule=asdict(rule), key=rule.key, trades=full, cells=full_cells),
                   fixed_entries=dict(name="元12入口を固定した同じ出口", trades=fixed, cells=fixed_cells),
                   selection=dict(eligible=False, description=note, rank_reference=ranked["selected"]["rule"],
                                  definition="図示候補。訓練順位最高とは区別", train=list(SESSIONS[:4]), check=SESSIONS[4]))
    save_json(OUT / "図解対象.json", payload)
    sensitivity = []
    for delay in (1, 2):
        delayed = ExitRule(**(asdict(rule) | dict(delay=delay)))
        ts, cs = evaluate(data, schedules, cfg, delayed, primary, False)
        sensitivity.append(dict(rule=asdict(delayed), trades=ts, cells=cs))
    save_json(OUT / "利益保護候補の遅延感度.json", sensitivity)
    source = {trade_key(t):t for t in ranked["baseline"]["trades"]}
    paired = []
    for t in fixed:
        old = source[trade_key(t)]
        multiple = MULTIPLIERS[t["symbol"]]
        paired.append(dict(セッション=t["session"], 銘柄=t["symbol"], 新規時刻=str(t["entry_time"]),
            元返済時刻=str(old["exit_time"]), 候補返済時刻=str(t["exit_time"]),
            元収支円=old["net_points"]*multiple, 候補収支円=t["net_points"]*multiple,
            増減円=(t["net_points"]-old["net_points"])*multiple,
            元最高評価からの低下円=old["giveback_points"]*multiple, 候補最高評価からの低下円=t["giveback_points"]*multiple))
    pd.DataFrame(paired).to_csv(OUT / "元12入口の増益と減益.csv", index=False, encoding="utf-8-sig")
    methods = [("元の4ATR", ranked["baseline"]), ("利益保護・元入口固定", payload["fixed_entries"]),
               ("利益保護・再新規込み", payload["selected"]), ("訓練順位最高・固定利確5ATR・制約未達", ranked["selected"])]
    records = [dict(方式=name, セッション=c["session"], 銘柄=c["symbol"], 取引数=c["count"],
                    利益円=c["profit_yen"], 損失円=c["loss_yen"], 収支円=c["net_yen"], 費用倍収支円=c["stress_yen"],
                    最高評価からの低下円=c["giveback_yen"], 固定入口重複数=c["overlapping_anchors"])
               for name, method in methods for c in method["cells"]]
    pd.DataFrame(records).to_csv(OUT / "出口比較セッション収支.csv", index=False, encoding="utf-8-sig")

    # ----------------------------------------
    # 数値は計算結果から生成し、有利な単独取引と再新規後の収支を分けて記述する。
    lines = ["# 含み益を戻し過ぎる出口の検証", "",
        "結論：元の固定４ATRは利益の保護が遅い。9/23のNK225は費用後最大含み益35万円から最終９万円へ、26万円を戻した。利益が十分出てから保護を強める方式なら、この取引を11:21・66,610円で返済し、28万円を確保できた。ただし他の波を途中で降りる損失があり、全期間の両銘柄の収支をそれぞれ改善する出口は今回の192条件では確認できなかった。", "",
        "[５分足の出口比較HTML](出口比較.html) ／ [セッション別の利益・損失・収支](出口比較セッション収支.csv) ／ [元12入口ごとの増益・減益](元12入口の増益と減益.csv)", "",
        "## 何が問題だったか", "",
        "9/23の入口Aは約126.81円幅。4Aは約507.23円幅で、この取引の保有中の最大有利変動約370円幅より広い。利益を守る位置までストップが移らず、午後の戻りを受けた。入口時点の大きいATRを出口にも固定し続けたことが、具体的な原因の一つである。", "",
        "全12取引の１分終値ベースの費用後最大評価損益を足し合わせると381万円、最終収支は251万円で差は130万円。各取引の最大値は違う時刻であり、全ての天底で返済できる実現可能利益や、同時の口座最大資産ではない。", "",
        "## 比較した出口", "",
        "入口のCUSUM・1ATR追跡新規・初期45分待機・返済後45分待機・初期損切り2.5Aは固定。元方式を含む11系統192条件を比較した。固定４ATRの別名も含むため、元方式と意味が同じ２行を除いた改善側は190条件。", "",
        "|系統|考え方|", "|---|---|"]
    concepts = {"baseline":"元方式。比較の基準", "fixed_trail":"最初から0.75〜4Aへ狭める", "current_atr":"固定入口Aの代わりに現在利用可能なATRを使う",
        "breakeven":"一定の含み益に達した後、費用込み建値まで保護を上げる", "stepped":"一定利益までは4A、その後0.5〜2.5Aへ縮小",
        "profit_lock":"一定利益後、最大有利変動の40〜80%を保護", "progressive":"利益段階に応じて3A→2A→小さい幅へ変更",
        "structure":"過去3〜20本の安値・高値の外側へ保護を置く", "stagnation":"有利な高安を更新しなくなったら返済",
        "reversal":"利益が出た後などに、CUSUMの反対方向を確認して返済", "target":"1〜5Aの固定指値利確"}
    lines += [f"|{NAMES[k]}|{concepts[k]}|" for k in NAMES]
    lines += ["", "## 入口固定の診断と、再新規まで含む運用を区別する", "",
        "元の12取引と同じ時刻・価格・ATRで入る比較は、出口だけの効果を見る診断である。早く返済しても次の元入口まで入らないため、それ自体を実運用の結果と扱わない。独立に元入口を置くので、固定利確のように元より遅く返済する方式では建玉が重なる可能性がある。実運用側は１建玉のみで、出口後45分待ってから新たな入口を再生した。", "",
        "## 利益保護の比較候補", "", description, "", note, "",
        "9/23のNK225は09:35に66,910円で売り、2.5A（約317円幅）以上有利になった後、追跡幅を0.5A（約63円幅）へ縮小する。保有中の確定高安から条件を更新し、11:21の足で66,610円へ買い返済。天底の時刻を条件に埋め込んだものではない。", "",
        "|9/23デイ|元方式|同じ最初の入口の出口変更|再新規まで含む日中全体|", "|---|---:|---:|---:|"]
    for symbol in SYMBOLS:
        items = [next(c for c in m["cells"] if c["session"] == SESSIONS[-1] and c["symbol"] == symbol) for m in (ranked["baseline"], payload["fixed_entries"], payload["selected"])]
        lines.append(f"|{symbol}|{money(items[0]['net_yen'])}|{money(items[1]['net_yen'])}|{money(items[2]['net_yen'])}|")
    lines += ["", "金額は万円、ラージ１枚、往復２ティック控除後。NK225の再新規込み24万円には、最初の売り＋28万円、その後の買い＋７万円、さらに売り直した−11万円を全て含めた。28万円だけを当日の成績とはしていない。", "",
        "## 全セッションの利益・損失・収支", "",
        "利益保護候補の再新規込み。単位は万円。利益は利益取引の合計、損失は損失取引の絶対額。",
        "", "|セッション|NK利益|NK損失|NK収支|元NK収支|TOP利益|TOP損失|TOP収支|元TOP収支|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for session in SESSIONS:
        values = []
        for symbol in SYMBOLS:
            c = next(c for c in full_cells if (c["session"], c["symbol"]) == (session, symbol))
            b = next(c for c in ranked["baseline"]["cells"] if (c["session"], c["symbol"]) == (session, symbol))
            values += [c["profit_yen"], c["loss_yen"], c["net_yen"], b["net_yen"]]
        lines.append("|" + session.replace("2026-", "").replace("_Day", " デイ").replace("_Night", " ナイト") + "|" + "|".join(money(v) for v in values) + "|")
    lines += ["", "|方式|NK収支|TOP収支|NK費用倍|TOP費用倍|NK取引数|TOP取引数|",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for name, method in methods:
        n, t = (totals(method["cells"], s) for s in SYMBOLS)
        lines.append(f"|{name}|{money(n['net_yen'])}|{money(t['net_yen'])}|{money(n['stress_yen'])}|{money(t['stress_yen'])}|{n['count']}|{t['count']}|")
    plus = sum(max(0, row["増減円"]) for row in paired)
    minus = -sum(min(0, row["増減円"]) for row in paired)
    lines += ["", "## 早く降りたことで逃した利益", "",
        f"同じ12入口の対比較では、元方式より増益になった取引の増額合計は{money(plus)}万円、減益になった取引の減額合計は{money(minus)}万円。差は{money(plus-minus)}万円だった。利益の返却を減らしても、その後の大きな続伸・続落を持てなくなるため、収支が自動的に改善するわけではない。", "",
        "最高評価からの低下は `max(0, 保有中の最大有利値幅−最終値幅)`。含み益から赤字へ落ちた取引は赤字分も含み、最初から有利に動かなかった損切りもゼロ評価からの低下として含む。単なる『利益だけの返却』と混同しないよう、CSVと図解で定義を明示する。新規足の高安順序は不明なため終値のみ、退出足は返済価格だけを計上する。", "",
        "## 順位と期間分割", "",
        "最初の４セッションだけで順位を付け、9/23をその順位計算から外した。費用倍でも両銘柄が黒字かつ元収支の90%以上を保つ制約を、元と同じ出口を除いて満たした条件は０。制約未達の参考順位最高は固定利確5Aで、全期間NK184万円・TOP52万円。9/23の下落では目標に届かず、元方式の利益返却問題を解消しない。", "",
        "図示した2.5A到達後0.5A追跡は、利益保護の挙動と代償を見せるため、結果を見た後に取り上げた比較候補である。9/23を見て出口改善の仮説を考えているので、今回の確認期間は真の未使用データではない。最適出口が確定したとは扱わない。", "",
        "時間順３→４と一セッション除外の選定結果は資料内の出口の期間分割.jsonに保存した。未来セッションを訓練側に含む除外検証も、将来の独立検証とは区別する。", "",
        "## 保護更新の遅れと費用", "", "|更新への追加遅延|NK収支|TOP収支|NK費用倍|TOP費用倍|", "|---|---:|---:|---:|---:|"]
    for delay, cells in [(0, full_cells)] + [(s["rule"]["delay"], s["cells"]) for s in sensitivity]:
        n, t = (totals(cells, s) for s in SYMBOLS)
        lines.append(f"|{delay}実在足|{money(n['net_yen'])}|{money(t['net_yen'])}|{money(n['stress_yen'])}|{money(t['stress_yen'])}|")
    lines += ["", "保護更新は確定１分足の後から有効で、ネイティブAPIの連続trailとは同一ではない。既に置いた保護注文は遅延中も有効。追加遅延は実在する足の本数であり、欠損があれば１足が１分とは限らない。損切りを飛び越す始値は不利な価格で計上。順序不明の同足利確・損切りは損失側を優先する。", "",
        "## 再エントリーを単純に減らせばよいか", "",
        "出口比較の後に、利益保護の２方式だけで再新規待機を90分・120分へ延ばす二次感度も確認した。図示候補は45分待機でNK159万円・TOP70万円、90分ではNK96万円・TOP93万円、120分ではNK95万円・TOP58.5万円。長く待てば両銘柄が改善する関係ではない。返済後に反対方向の信号を一度確認する条件を足しても、今回の取引は変わらなかった。", "",
        "元45分の再新規取引だけの合計はNK＋51万円・TOP＋10.5万円。損失取引だけでなく利益も作っているため、一律に禁止することも解決にはならない。この比較は事後探索で、上の順位や候補を置き換えていない。[全セルと明細](資料/再エントリー感度.md)。", "",
        "## 保存物と再現", "", "前回の調査・HTML・原本は変更せず、この出口改善フォルダーへ追加した。実装・192条件・全取引・計画・監査は[資料](資料/)に保存。現在APIは取得していない。", "",
        "プロジェクトルートから `python -X utf8 work/wave_v6/search_exits.py` で固定計画を再生できる。図示用候補は `build_exit_report.py`、HTMLは `plot_comparison.py --input work/wave_v6/図解対象.json` で生成する。入力は前回凍結した20本の足で、そのハッシュを確認する。"]
    (OUT / "出口改善の検証結果.md").write_text("\n".join(lines), encoding="utf-8")
    for name in ("出口改善の検証結果.md", "出口比較セッション収支.csv", "元12入口の増益と減益.csv", "元方式の利益返却.md"):
        shutil.copy2(OUT / name, DEST / name)
    print(json.dumps(dict(図示候補=asdict(rule), 同入口増益円=plus, 同入口減益円=minus), ensure_ascii=False))


if __name__ == "__main__":
    main()
