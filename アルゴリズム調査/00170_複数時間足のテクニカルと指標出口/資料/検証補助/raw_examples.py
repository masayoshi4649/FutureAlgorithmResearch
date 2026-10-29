"""新研究の三つの具体例について、原板を変更せず節目だけを抽出します。"""

from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
STUDY = ROOT / "アルゴリズム調査" / "00170_複数時間足のテクニカルと指標出口"


def read_json(path: Path) -> object:
    """UTF-8 の資料を読み込みます。

    引数: path（Path型）は読取対象です。
    返り値: object型のJSON値です。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def finite_number(value: object) -> float | None:
    """有限の数値だけを採用します。

    引数: value（object型）は原板フィールドです。
    返り値: float型の数値又はNoneです。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def quote_facts(raw: dict, line: int) -> dict:
    """節目で使う最小限の気配・価格・数量を取り出します。

    引数: raw（dict型）は原行、line（int型）は物理行番号です。
    返り値: dict型の必要事実だけのレコードです。
    """
    buy, sell = raw.get("Buy1") or {}, raw.get("Sell1") or {}
    return {
        "line": line,
        "time": raw.get("CurrentPriceTime"),
        "last": finite_number(raw.get("CurrentPrice")),
        "bid": finite_number(buy.get("Price")),
        "bid_qty": finite_number(buy.get("Qty")),
        "ask": finite_number(sell.get("Price")),
        "ask_qty": finite_number(sell.get("Qty")),
        "trading_volume": finite_number(raw.get("TradingVolume")),
    }


def scan_example(example: dict, evidence: dict, market_path: Path) -> dict:
    """一つの玉の保有区間を物理行順に走査し、節目と含み極値を照合します。

    引数: example・evidence（dict型）は新研究の選定例、market_path（Path型）は原板です。
    返り値: dict型の節目事実と照合結果です。指標条件や売買判断は再実行しません。
    """
    entry, close, episode = example["entry"], example["close"], evidence["episode"]
    entry_line, close_line = entry["source_line"], close["source_line"]
    side = 1 if entry["type"] == "LongN" else -1
    quantity, entry_price = entry["qty"], entry["price"]
    point_value = 100 if evidence["symbol"] == "NK225" else 1000
    labels = {}
    for label, line in [
        ("新規判断", entry["decision_line"]),
        ("新規約定", entry_line),
        ("返済判断", close["decision_line"]),
        ("返済約定", close_line),
    ]:
        labels.setdefault(line, []).append(label)
    selected = {}
    peak, minimum = -math.inf, math.inf
    peak_facts, first_positive_facts = None, None
    maximum_read_line = 0
    before = market_path.stat()
    with market_path.open("rb") as stream:
        for line, raw_bytes in enumerate(stream, 1):
            maximum_read_line = line
            if line > close_line:
                break
            if line not in labels and not entry_line <= line <= close_line:
                continue
            raw = json.loads(raw_bytes)
            facts = quote_facts(raw, line)
            if line in labels:
                selected[line] = facts
            bid, ask = facts["bid"], facts["ask"]
            if entry_line <= line <= close_line and bid is not None and ask is not None and 0 < bid < ask:
                price = bid if side > 0 else ask
                points = side * (price - entry_price)
                facts["held_points_before_close"] = points
                facts["held_pnl_yen_before_close"] = points * quantity * point_value
                if points > peak:
                    peak, peak_facts = points, facts
                minimum = min(minimum, points)
                if points > 0 and first_positive_facts is None:
                    first_positive_facts = facts
    after = market_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("抽出中に原板の属性が変わりました")
    if peak_facts is None or len(selected) != len(labels):
        raise RuntimeError("必要な原行又は正常気配が不足しています")
    if first_positive_facts is not None:
        line = first_positive_facts["line"]
        labels.setdefault(line, []).append("初正益")
        selected[line] = first_positive_facts
    labels.setdefault(peak_facts["line"], []).append("最大含み")
    selected[peak_facts["line"]] = peak_facts
    first_positive_line = first_positive_facts["line"] if first_positive_facts else 0
    maximum_yen = peak * quantity * point_value
    minimum_yen = minimum * quantity * point_value

    # ----------------------------------------
    expected = {
        "初正益原行": (first_positive_line, episode["first_positive_line"]),
        "最大含み円": (maximum_yen, episode["max_unrealized_yen"]),
        "最小含み円": (minimum_yen, episode["min_unrealized_yen"]),
        "新規約定価格": (selected[entry_line]["ask"] if side > 0 else selected[entry_line]["bid"], entry_price),
        "返済約定価格": (selected[close_line]["bid"] if side > 0 else selected[close_line]["ask"], close["price"]),
    }
    for name, (actual, wanted) in expected.items():
        if actual is None or abs(actual - wanted) > 0.000001:
            raise RuntimeError(f"{name}不一致: 原板{actual}、約定資料{wanted}")
    milestones = []
    for line, facts in sorted(selected.items()):
        row = dict(facts)
        row["milestones"] = labels[line]
        row["qty_before"] = 0 if line <= entry_line else quantity
        row["qty_after"] = 0 if line >= close_line or line <= entry["decision_line"] else quantity
        milestones.append(row)
    return {
        "resource": example["resource"],
        "market_path": str(market_path),
        "position_id": entry["position_id"],
        "source_lines_read": min(maximum_read_line, close_line),
        "side": side,
        "quantity": quantity,
        "point_value": point_value,
		"quote_quantity_unit": "ラージ枚数",
		"mini_quantity_per_large": 10,
        "entry_price": entry_price,
        "close_price": close["price"],
        "profit_yen": episode["profit_yen"],
        "maximum_held_points": peak,
        "maximum_held_yen": maximum_yen,
        "minimum_held_yen": minimum_yen,
        "first_positive_line": first_positive_line,
        "milestones": milestones,
        "verified": True,
    }


def compact_comparison(summary: dict, evidence: dict) -> list[dict]:
    """同じ入口式の I・T・F について同一場の集計を取り出します。

    引数: summary・evidence（dict型）は新研究の全候補集計と具体例です。
    返り値: list[dict]型の三方式の場全体の比較です。
    """
    prefix = evidence["config_id"].rsplit("_", 1)[0]
    rows = []
    fields = ["config_id", "entry_count", "episodes", "final_equity_yen", "min_equity_yen", "max_drawdown_yen", "first_entry_line", "positive_then_negative"]
    for mode in ["I", "T", "F"]:
        result = next(row for row in summary["results"] if row["symbol"] == evidence["symbol"] and row["session"] == evidence["session"] and row["config_id"] == prefix + "_" + mode)
        rows.append({key: result[key] for key in fields})
    return rows


def number(value: float | None, signed: bool = False) -> str:
    """資料表向けの数値を表記します。

    引数: value（float又はNone型）は値、signed（bool型）は正の符号指定です。
    返り値: str型の表示文字列です。
    """
    if value is None:
        return "不明"
    return format(value, "+,.6f" if signed else ",.6f").rstrip("0").rstrip(".")


def render_case(index: int, facts: dict, visual: dict, evidence: dict) -> str:
    """一つの事例の原行表と同日比較、限定した解釈を作成します。

    引数: index（int型）は番号、facts・visual・evidence（dict型）は抽出根拠です。
    返り値: str型のMarkdown本文です。
    """
    descriptions = [
        ("日経・下落途中のBB帯内復帰", "画像では入口前に下落し、小反発を挟んだ後、入口後の戻りは続かず安値を切り下げた。原板では一度50ptの正益に達したが、保険損切りまで残った。", "H09の非トレンド判定とBB下側2σからの帯内復帰は、局所的な反発を検出する条件である。『厳密な長期下落トレンド条件が不成立』は、持続的な下落がないことや、その後もレンジが続くことの証明ではない。短い帯内復帰と本格反転を区別できなかった可能性がある。", "判断時点で既知なのは、それまでの確定足、直近の下落と小反発、当行の気配である。50ptの最大益とその後の200pt損失は事後に確定した経路であり、ピーク行を事前の利確点として指定することはできない。", "下落側の短期安値更新・BB中心線の傾きと帯内復帰を組み合わせる入口抑制、又は保有後の下値支持失効を別の固定IDで比較する。小さい利益床の効果は既存Fで確認し、新しい幅をこの一例の最大益へ合わせない。"),
        ("日経夜間・直近高値後のDI交差", "画像では入口直前の上昇・高値の後、入口後は上下を繰り返す価格帯に移り、買いの継続上昇にならなかった。", "H10は中足の+DI上抜け・ADX上昇を使うが、過去の高安変動から計算する方向・強さの回復は、次の買いで利益が得られる保証ではない。局所高値までの上昇を含む集計が、持続する上方向の優位として残った可能性がある。板数量の取消・補充・消費の原因はこの抽出から判定できない。", "判断時点では直近高値との位置、確定中足までのDI/ADX条件、当行BBOを観測できた。『この先レンジになる』『この価格が高値になる』は事後認識である。保有中に実行可能Bidが建値を超えなかった事実は逐次観測できるが、入口時点で全区間の最高Bidは分からない。", "DI交差時に直近高値までの余地や短足の更新失敗を確認する別入口、又はDI優勢の減衰に応じた出口を別固定IDで検証する。固定時間だけでレンジと断定せず、支持失効と再参加損失を併せて評価する。"),
        ("TOPIX夜間・RSI回復後の小反発と押し戻し", "画像では小反発後に押し戻されて返済し、その後に再び上昇した。表示範囲末までの累積確定損益-20,000円は、この玉の-15,000円と前の玉の-5,000円を含む。", "H03は非トレンド・弱いADXの場でRSIの30上抜けを反発の入口とする。小さいRSI回復は気配差を十分に超える値幅の持続を保証せず、今回の正益は0.5ptまでにとどまった。早期利益床の起動幅は約1.6294ptであり、この玉ではF床も起動しなかった。後の上昇は入口の反発がそのまま続いたことを意味しない。", "当時観測できたのはRSI回復と直近の小反発、新規約定行の0.5ptの気配差、保有後の0.5pt正益と押し戻しである。返済後の再上昇は返済判断時点では未知であり、後の高値を理由に『保持が正解だった』とは断定できない。", "TOPIXの気配刻み・スプレッドに対する必要値幅と利益床の関係を別IDで検証し、支持回復での再参加も独立して評価する。床幅を小さくすれば回収が増えると決めつけず、次原行約定と再参加後の損失を含める。"),
    ]
    title, observation, interpretation, causal_limit, proposal = descriptions[index]
    text = [f"## {index+1}. {title}", "", f"対象: `{facts['resource']}`。{evidence['entry']['timestamp']}に{number(facts['entry_price'])}でmini買い{facts['quantity']}枚、{evidence['close']['timestamp']}に{number(facts['close_price'])}で全返済。当該玉の収支は{number(facts['profit_yen'],True)}円、最高含みは{number(facts['maximum_held_yen'],True)}円（{number(facts['maximum_held_points'],True)}pt）、返済理由は「{evidence['close']['reason']}」。", "", f"原板: `{facts['market_path']}`。画像: `{visual['visual_file']}`。数値指紋: `{visual['data_sha256']}`。", "", "| 節目 | 原行 | 価格時計（日本時間） | Last | Buy1価格／ラージ数量 | Sell1価格／ラージ数量 | mini保有枚数 前→後 | 返済前評価損益 |", "|---|---:|---|---:|---:|---:|---:|---:|"]
    for row in facts["milestones"]:
        pnl = number(row.get("held_pnl_yen_before_close"),True) if row["qty_after"] or "返済約定" in row["milestones"] else "―"
        clock = row["time"].replace("T", " ").replace("+09:00", "") if row["time"] else "不明"
        text.append(f"| {'・'.join(row['milestones'])} | {row['line']} | {clock} | {number(row['last'])} | {number(row['bid'])}／{number(row['bid_qty'])} | {number(row['ask'])}／{number(row['ask_qty'])} | {row['qty_before']}→{row['qty_after']} | {pnl} |")
    if not facts["first_positive_line"]:
        text += ["", "初正益の原行はない。最大含み0円は建値までの回復であり、正益化ではない。"]
    text += ["", "### 原板と画像で確認したこと", "", observation]
    if index == 2:
        text += ["", "返済判断の162116行はBid=Askの同値気配だった。指標による返済判断を予約し、次の正常気配162117行のBid 4,072で返済している。同値気配自体を約定価格に使った結果ではない。"]
    text += ["", "### 指標が反応した局面の解釈", "", interpretation, "", "### 当時の観測と後知恵の区別", "", causal_limit, "", "### 同じ場のI・T・F比較", "", "| 方式 | 新規回数 | 完了取引数 | 場全体収支 | 最小時価収支 | 最大ドローダウン | 場の初回新規原行 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in facts["same_session_comparison"]:
        text.append(f"| {row['config_id']} | {row['entry_count']} | {row['episodes']} | {number(row['final_equity_yen'],True)} | {number(row['min_equity_yen'],True)} | {number(row['max_drawdown_yen'])} | {row['first_entry_line']} |")
    comparisons = [
        "この場は三方式とも同じ140538行で初回新規し、各1取引で終わった。I/Tは-200,000円、Fは0円であり、Fが200,000円良かった。F床の起動幅26.292ptに対して、この玉の実測最大益は50ptだった。最高50,000円を回収した結果ではなく、Fでも場収支は0円である。",
        "この場はTが+230,000円、I/Fが-150,000円だった。指標出口を外したTが良い日もあり、通常出口を早めれば常に改善するとはいえない。この差を、19:35まで最高含み0円だった一玉だけの評価へ読み替えない。",
        "同日のFとIはともに-20,000円で、早期利益床を加えてもこの日の結果は変わらなかった。Tは-5,000円と最終損失が小さい一方、最小時価は-40,000円、最大ドローダウン100,000円で、I/Fの-25,000円・30,000円より悪化した。後の上昇を含めても、保有継続が全ての評価軸で有利とはいえない。",
    ]
    text += ["", comparisons[index], "", "表は同じ場の全売買を含む。入口式は共通でも、出口と保有時間の差により2回目以後の入口機会は変わる。当該玉だけの同一入口対照と混同しない。", "", "### 改善案（未検証）", "", proposal, ""]
    return "\n".join(text)


def main() -> None:
    """新研究の三事例だけの小さい抽出資料と具体例文書を作成します。

    引数: なし。
    返り値: None型です。凍結実装と原板は変更しません。
    """
    visuals = read_json(WORK / "visual-checks.json")
    evidence = read_json(WORK / "loss-evidence.json")
    summary = read_json(WORK / "summary.json")
    manifest = read_json(STUDY / "入力目録.json")

    # ----------------------------------------
    examples = []
    sections = []
    for index, visual in enumerate(visuals):
        match = next(row for row in evidence if row["entry"]["position_id"] == visual["entry"]["position_id"])
        raw_input = next(row for row in manifest["files"] if row["symbol"] == match["symbol"] and row["session"] == match["session"])
        facts = scan_example(visual, match, Path(raw_input["path"]))
        facts["same_session_comparison"] = compact_comparison(summary, match)
        examples.append(facts)
        sections.append(render_case(index, facts, visual, match))

    # ----------------------------------------
    (WORK / "raw-examples.json").write_text(json.dumps(examples,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    introduction = """# 原板で確認した具体例

研究00170の選定後に確認した三つの例であり、全成績から独立した事前仮説検証ではない。原板は入力目録に固定された既存book.jsonlを読み取り専用で参照した。物理行順を変えず、新規判断・新規約定・初正益・最大含み・返済判断・返済約定の節目だけを抽出した。指標条件と売買判断の再実行や原板コピーは行っていない。

日経miniの1ptは1枚100円、TOPIXminiは1枚1,000円。各10枚、手数料0円。経済側Buy1がBid、Sell1がAskであり、買い新規はAsk、買い玉の評価と返済はBidを使用した。判断原行と次正常約定原行は分離している。同じ価格時計でも次物理行なら約定対象である。

原行表の評価損益は、その行でまだ当該玉を保有している場合の実行可能気配による値である。返済約定行の欄は返済直前の評価であり、返済後の含み損益は0円。最大含みは後から全保有区間を調べて得た診断値である。板数量は原板の表示数量であり、約定消費や注文取消を識別した値ではない。

参照BBOはラージの板、仮想売買数量はminiである。日経・TOPIXともラージ1枚はmini10枚相当なので、9月29日夜間DI例の新規Ask数量5ラージはmini50枚相当、返済Bid数量6ラージはmini60枚相当、TOPIX例の返済Bid数量1ラージはmini10枚相当である。生板のラージ数量をmini10枚と直接比較して不足と判断してはいけない。

本研究は参照ラージの次正常BBO価格でmini10枚全量を約定させる仮定で、実際のmini板は読んでいない。表示数量による約定制限・複数気配への分割・待機も再現していない。表の価格・収支は研究の仮定と整合するが、別商品のmini板でも同価格で全量約定できた証明ではない。ラージ数量の換算値は商品間の枚数尺度をそろえる参考であり、miniの実際の流動性を観測した値ではない。

機械抽出は`work/research170/raw_examples.py`、小さい根拠は`work/research170/raw-examples.json`、画像と数値の照合は`work/research170/visual-checks.json`、同日比較は`work/research170/summary.json`に基づく。初正益原行・最大/最小含み・新規Ask価格・返済Bid価格は、保存された約定/エピソード資料と独立照合した。

Iは指標通常出口と共通利益トレール、Tは通常指標出口なしの共通保護、FはIに早期利益床を加えた事前固定方式。共通保護は建値比で保険損切り0.30%、トレール起動0.10%・戻り0.05%。F床は+0.04%到達後に+0.01%を下限判断に使うが、次正常原行での約定なので利益額の保証ではない。

"""
    (STUDY / "原板で確認した具体例.md").write_text(introduction+"\n".join(sections),encoding="utf-8")
    print(json.dumps([{key:row[key] for key in ["resource","verified","first_positive_line","maximum_held_points","maximum_held_yen","same_session_comparison"]} for row in examples],ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
