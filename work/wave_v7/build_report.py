"""固定済みの予測・取引結果から、日本語の閲覧用報告書を生成する。"""

from __future__ import annotations

import html
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
DEST = ROOT / "アルゴリズム調査" / "00003_未来情報を使わない予測検証"
TEST_SESSIONS = ["2026-09-22_Day", "2026-09-22_Night", "2026-09-23_Day"]
MAIN_METHODS = ["過去だけで選択", "logistic_60/元4ATR", "lstm_60/元4ATR", "上昇固定/元4ATR"]
MAIN_PREDICTIONS = ["過去だけで選択", "logistic_60", "lstm_60", "上昇固定"]


def read_json(path: Path) -> dict:
    """UTF-8の結果JSONを読む。

    引数: path (Path) は対象ファイル。
    返り値: dict は保存済み結果。元ファイルは変更しない。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def money(value: float) -> str:
    """円の金額を万円表示へ変換する。

    引数: value (float) は円単位の金額。
    返り値: str は符号付きの万円表示。
    """
    amount = value / 10000
    return f"{amount:+.2f}".rstrip("0").rstrip(".") if abs(amount) > 1e-10 else "0"


def rate(value: float | None) -> str:
    """割合を百分率に整形する。

    引数: value (float/None) は割合または欠測。
    返り値: str は百分率または未評価表示。
    """
    return f"{value * 100:.1f}%" if value is not None and math.isfinite(value) else "—"


def label(name: str) -> str:
    """方式識別子を人向けの短い日本語にする。

    引数: name (str) は固定した方式名。
    返り値: str は意味を変えない表示名。
    """
    return name.replace("logistic_", "線形・").replace("lstm_", "LSTM・").replace("上昇固定", "常時ロング").replace("下降固定", "常時ショート").replace("元4ATR", "元の4ATR出口").replace("利益保護", "利益保護出口")


def session_label(name: str) -> str:
    """セッションの識別子を日本語表示にする。

    引数: name (str) は日付と区分。
    返り値: str は日本語のセッション名。
    """
    return name.replace("2026-", "").replace("_Day", " デイ").replace("_Night", " ナイト")


def aggregate(cells: list[dict], methods: list[str], sessions: list[str]) -> list[dict]:
    """指定期間・方式の確定した取引だけを銘柄別に合計する。

    引数: cells (list[dict]) はセッション結果、methods/sessions (list[str]) は対象。
    返り値: list[dict] は利益・損失・収支などの合計。
    """
    rows = []
    for method in methods:
        for symbol in ("NK225", "TOPIX"):
            relevant = [r for r in cells if r["方式"] == method and r["銘柄"] == symbol and r["セッション"] in sessions]
            if not relevant:
                continue
            row = {"方式": method, "銘柄": symbol}
            for field in ("利益円", "損失円", "収支円", "取引数", "費用倍収支円"):
                row[field] = sum(r[field] for r in relevant)
            rows.append(row)
    return rows


def md_table(headers: list[str], rows: list[list]) -> str:
    """Markdownの表を作る。

    引数: headers (list[str]) は列名、rows (list[list]) は表の値。
    返り値: str はMarkdown表。
    """
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers), *("| " + " | ".join(str(c) for c in row) + " |" for row in rows)])


def html_table(headers: list[str], rows: list[list], classes: str = "") -> str:
    """文字列をエスケープしたHTML表を作る。

    引数: headers (list[str]) は列名、rows (list[list]) は値、classes (str) は追加class。
    返り値: str はスクロール可能な表。
    """
    head = "".join(f"<th>{html.escape(str(v))}</th>" for v in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap {classes}"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def seed_scores() -> list[dict]:
    """良い乱数を選別せず、全3seedの非重複標本を集計する。

    引数: なし。凍結された入力と予測NPZを読む。
    返り値: list[dict] は期間・銘柄・seedごとの成績。
    """
    result = []
    with np.load(BASE / "dataset.npz", allow_pickle=False) as data:
        with np.load(BASE / "ml_predictions.npz", allow_pickle=False) as predictions:
            for j, horizon in enumerate((30, 60, 120)):
                for symbol_index, symbol in enumerate(("NK225", "TOPIX")):
                    for seed in (1729, 1730, 1731):
                        probability = predictions[f"lstm_seed{seed}_{horizon}"]
                        change = data["future_returns"][:, j]
                        mask = data["valid"] & (data["session_idx"] >= 2) & (data["symbol_idx"] == symbol_index)
                        mask &= (data["age"] - 45) % horizon == 0
                        mask &= np.isfinite(change) & (change != 0) & np.isfinite(probability)
                        up, down = mask & (change > 0), mask & (change < 0)
                        balanced = .5 * (np.mean(probability[up] >= .5) + np.mean(probability[down] < .5)) if up.any() and down.any() else None
                        result.append({"期間": horizon, "銘柄": symbol, "seed": seed, "標本数": int(mask.sum()),
                                       "正答率": float(np.mean((probability[mask] >= .5) == (change[mask] > 0))) if mask.any() else None,
                                       "均衡正答率": float(balanced) if balanced is not None else None})
    return result


def pending_labels() -> list[list]:
    """新セッションの未来ラベル未満了数を数える。

    引数: なし。取得済みセッションの入力NPZを読む。
    返り値: list[list] は銘柄・期間・締切以前の判断数・評価可能・未満了・足不足。
    """
    rows = []
    cutoff = int(datetime.fromisoformat(read_json(BASE / "live" / "取得記録.json")["cutoff"]).timestamp() * 1e9)
    with np.load(BASE / "live" / "dataset.npz", allow_pickle=False) as data:
        for symbol_index, symbol in enumerate(("NK225", "TOPIX")):
            mask = data["valid"] & (data["symbol_idx"] == symbol_index) & (data["time_ns"] <= cutoff)
            for j, horizon in enumerate((30, 60, 120)):
                known = mask & np.isfinite(data["future_returns"][:, j])
                not_yet = mask & ~known & (data["time_ns"] + horizon * 60_000_000_000 > cutoff)
                missing = mask & ~known & ~not_yet
                rows.append([symbol, horizon, int(mask.sum()), int(known.sum()), int(not_yet.sum()), int(missing.sum())])
    return rows


def prepare() -> dict:
    """報告に必要な表と表示用データを保存済み結果から作る。

    引数: なし。
    返り値: dict はHTML/Markdown共通の報告内容。
    """
    historical = read_json(BASE / "時間順検証.json")
    live = read_json(BASE / "live" / "未使用セッション結果.json")
    fetch = read_json(BASE / "live" / "取得記録.json")
    null = read_json(BASE / "コイントス対照.json")
    main = aggregate(historical["セッション収支"], MAIN_METHODS, TEST_SESSIONS)
    summary_rows = [[label(r["方式"]), r["銘柄"], money(r["利益円"]), money(r["損失円"]), money(r["収支円"]), r["取引数"], money(r["費用倍収支円"])] for r in main]
    accuracy = [r for r in historical["予測成績"] if r["方式"] in MAIN_PREDICTIONS and r["予測先分"] == 60 and r["標本間隔分"] == 60]
    accuracy.sort(key=lambda r: (MAIN_PREDICTIONS.index(r["方式"]), r["銘柄"]))
    accuracy_rows = [[label(r["方式"]), r["銘柄"], f'{r["正答数"]}/{r["方向判定数"]}', rate(r["正答率"]), rate(r["均衡正答率"])] for r in accuracy]
    selected = [r for r in historical["セッション収支"] if r["方式"] == "過去だけで選択"]
    selected_rows = [[session_label(r["セッション"]), r["銘柄"], label(r["選択方式"]), money(r["利益円"]), money(r["損失円"]), money(r["収支円"]), r["取引数"]] for r in selected]
    live_rows = [[label(r["方式"]), r["銘柄"], money(r["利益円"]), money(r["損失円"]), money(r["収支円"]), r["取引数"], r["未返済数"], money(r["未返済評価損益円"])] for r in live["セッション収支"]]
    null_rows = [[label(r["方式"]), r["銘柄"], money(r["平均収支円"]), money(r["下側5パーセント円"]), money(r["上側95パーセント円"]), money(r["平均費用倍収支円"])] for r in null["分布"]]
    seeds = seed_scores()
    seed_rows = [[r["期間"], r["銘柄"], r["seed"], r["標本数"], rate(r["正答率"]), rate(r["均衡正答率"])] for r in seeds]
    return dict(historical=historical, live=live, fetch=fetch, main=main, summary_rows=summary_rows,
                accuracy_rows=accuracy_rows, selected_rows=selected_rows, live_rows=live_rows,
                null_rows=null_rows, seed_rows=seed_rows, pending=pending_labels())


# ----------------------------------------


def write_markdown(report: dict) -> None:
    """最初に読むREADMEと詳細な日本語報告を生成する。

    引数: report (dict) は集計済み内容。
    返り値: None。成果物フォルダの2つのMarkdownだけを書く。
    """
    headers = ["方式", "銘柄", "利益", "損失", "収支", "返済件数", "費用倍の収支"]
    md = f'''# 00003 未来情報を使わない予測検証

**機械的な実行は可能。ATR・CUSUMにLSTMは不要です。ただし、この短い実データで「将来を安定して当てる優位性」を確認できたとは言えません。今回のLSTMは常時ロングを明確に上回りませんでした。**

[方式・セッションを切り替えて見るHTML](検証結果.html) ／ [実行条件](実行条件.md) ／ [資料一覧](README.md)

## 何を予測し、何を検証したか

時刻tまでに使える情報で方向を出し、その後30・60・120分の価格差を評価しました。主比較は60分先です。ATRは値動きの大きさを表す尺度であり、単独で未来の方向を予測するものではありません。CUSUMなどの機械ルールも、その時点の方向判定を将来へ当てはめる仮説として検証しました。

方向24系統×出口2種類の48条件と、線形/LSTM×30・60・120分×出口2種類の12条件、**合計60条件**を固定して比較しました。さらに常時ロング・ショート、30分ごとに方向を変えるコイントス100seedを同じ注文条件で比較しました。

保存5セッションは既に過去の探索で使われています。最初の2セッションで学習・選択して第3を評価し、次に最初の3で第4、最初の4で第5を評価しました。これは**既知の履歴の時間順再評価**です。未使用データの成績とは区別します。

## 機械実行する条件

新規注文作成時のATRをAとして固定します。買い方向なら追跡安値から1A反発、売り方向なら追跡高値から1A反落で新規。初期損切りは2.5A。元方式の出口は有利側極値から4A、利益保護出口は最大有利値幅が2.5Aに達した後に0.5Aへ狭めます。保護価格を不利側へ戻しません。足で判断・更新した条件は後続足から使います。

デイは09:30〜15:05未満、ナイトは17:45〜翌05:20未満に新規受付。未約定注文は25分を超えたら取消・再判定（25分ちょうどは有効）し、反対信号でも取消。返済後は45分待機。1銘柄1建玉。デイ15:35、ナイト翌05:50以降の実在足で強制返済するため、セッションを跨ぎません。

従来の手法①は「機械09」です。1分終値差/ATRから上方向max(0,累積+x−0.025)、下方向min(0,累積+x+0.025)を逐次更新し、±0.6375到達で方向を切り替え、累積をリセットします。ニューラルネットワークの学習は使いません。

未使用セッションへ事前選択された「機械14/利益保護」は、両指数の直近15分の回帰方向が同じで、両方のR²が0.20以上、対象銘柄のATR正規化回帰変位の絶対値が0.375以上の場合の方向を使います。注文条件は上記と共通です。

## 既知履歴の時間順再評価：9/22デイ〜9/23デイ

以下はラージ1枚、往復2ティック相当控除後、単位は万円。利益はプラス取引の合計、損失はマイナス取引の絶対値合計、収支=利益−損失です。「費用倍」は往復4ティックです。

{md_table(headers, report['summary_rows'])}

「過去だけで選択」は各時点までの48条件から、両銘柄で取引した条件を対象に、費用倍のATR収支で選択した手順です。評価対象セッションの収支は選択に使っていません。ただし方式群そのものは既知の履歴を使った過去研究から来ています。

{md_table(['セッション', '銘柄', '事前選択', '利益', '損失', '収支', '返済件数'], report['selected_rows'])}

全60条件・対照方式の各セッションの利益、損失、収支、取引数は[HTML](検証結果.html)で切り替えられます。[全セッション収支CSV](資料/セッション別収支.csv)も保存しています。

## 60分先の方向を本当に当てたか

60分間隔で評価し、同じ銘柄の予測対象区間が重ならない標本を主表示します。横ばいは正答率の分母から外し別集計。NK225、TOPIXとも方向判定は23標本です。両指数の標本間にも市場の相関があり、46個の完全独立標本とは扱いません。

{md_table(['方式', '銘柄', '正答/方向判定', '正答率', '均衡正答率'], report['accuracy_rows'])}

均衡正答率は「実際に上昇したときの正答率」と「実際に下落したときの正答率」の平均です。上昇ばかり予測して上昇相場で高得点になる効果を確認できます。**60分LSTMの均衡正答率は両銘柄50%。LSTMが方向を識別する優位性は今回確認できません。** 120分LSTMは毎分評価で100%上昇予測となり、見かけの63.29%正答は常時ロングと同じです。30分・120分を含む全結果は[予測成績CSV](資料/未来方向の予測成績.csv)にあります。

## 初めて読む9/23ナイトへの一回照合

条件・学習済みモデルの固定は **{report['fetch']['fixed_at']}**。取得開始は **{report['fetch']['started_at']}**。共通のデータ締切は **{report['fetch']['cutoff']}**。1分足の最終開始は19:13で、未確定の5分足は除外しました。状態1URLと足・板6URLを各1回取得し、再試行・再取得はしていません。

**これは、固定前から存在していた価格を含むセッションを初めて取得して再生した未使用テストです。実時間でその後の未来を待った運用、または実発注の成績ではありません。** 取得後にルール・学習済みモデルを変えず、事前固定した9方式を照合しました。機械14が全5セッションからの事前選択であり、この結果を見て別方式へ差し替えていません。

ナイト途中なので、確定損益と未返済の評価損益を分けます。評価損益は最終終値で評価し、往復2ティック相当も控除した参考額です。セッション終了までの収支ではありません。

{md_table(['方式', '銘柄', '利益', '損失', '確定収支', '返済件数', '未返済数', '未返済評価損益'], report['live_rows'])}

従来の手法①はNK225−17万円、TOPIX−7万円。事前選択の機械14/利益保護はNK225−17万円、TOPIX＋4.5万円でした。LSTMを加えても、この時点で損失を避けられたとは言えません。

60分間隔の予測評価は各銘柄1標本だけで、120分先はまだ0標本です。少数の100%/0%を有効性の根拠にしません。以下は取得締切19:14以前の毎分判断に限り、答え合わせできるラベルを数えています。未来の目標時刻が締切後なら未満了、それ以外で必要な足が足りないものは足不足とし、正解・不正解へ混ぜません。

{md_table(['銘柄', '予測先分', '締切以前の毎分判断', '評価可能', '未満了', '足不足'], report['pending'])}

## カンニングを防ぐ検査

1. 保存足20ファイルと板10ファイルを過去の記録と照合。保存5セッションに未使用の追加時刻はありませんでした。
2. 手法①のATR/CUSUMは両銘柄5セッション・240時刻で未来の足を削除して元足から特徴を再構築し、未来OHLCを大幅に改変しても過去の特徴・方向が一致。独立した逐次計算5590行でも方向が完全一致しました。
3. 各学習標本の未来ラベルが次の評価セッションより前に満了していることを確認。補完中央値・標準化係数は学習期間だけで算出しました。
4. 未来の特徴、教師、ラベル満了時刻を改変して再学習しても、3fold×3期間の標準化・線形係数・27 LSTMの重みが完全一致しました。
5. 予測時は教師列を削除し、未来特徴の改変・未来行の削除をしても過去予測が完全一致。保存モデルだけで別NPZを予測できます。
6. 新セッション取得前に条件・モデル等のSHA256を固定し、取得後も一致を確認。新セッションを学習・再選択へ戻していません。
7. 未使用セッションでも9方式×2銘柄×3打切時刻の54セルを確認し、未来の足を除いて再生しても過去に確定した取引が一致しました。

手法①の元足監査は、全24系統・全生板特徴が同じ強さで検査済みという意味ではありません。板には受信時刻がなく、保存順と最終約定時刻に基づく利用可能時刻の近似を使っています。実市場の配信遅延・訂正・板の約定順位は完全再現していません。

## コイントスで注文だけから利益が出るか

{md_table(['方式', '銘柄', '100seed平均収支', '下側5%', '上側95%', '費用倍平均'], report['null_rows'])}

同じ3評価セッションで乱数方向でも平均はプラスでしたが、分布は大きく、損失になるseedもあります。最も良いseedを選んでいません。注文の非対称性や期間の方向性でも利益が生じ得るため、プラス収支だけで方向予測の能力を証明できません。今回のコイントス対照は単一方向を30分ごとに更新する方式であり、新たな両建て最適化は行っていません。

## 機械学習の固定条件と全seed

両銘柄共通の価格20特徴、30/60/120分先の上昇・下落分類。線形はL2=0.01、Newton法60反復。LSTMは単方向1層16ユニット、過去30分、20epoch、batch128、Adam学習率0.001、seed1729/1730/1731。主結果は3seedの予測確率平均です。学習は5分間隔、予測は毎分。早期停止・良いseedの選別・取得後の再学習はしていません。RTX4090/CUDA12.8を使用しました。

以下は各期間と同じ間隔で抽出した非重複標本です。

{md_table(['予測先分', '銘柄', 'seed', '方向標本数', '正答率', '均衡正答率'], report['seed_rows'])}

前処理を学習期間だけで学ぶ原則は[scikit-learn公式文書](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage)、単方向・多層などのLSTMの指定は[PyTorch公式文書](https://docs.pytorch.org/docs/stable/generated/torch.nn.LSTM.html)を参照。線形モデル自体はNumPyで実装しています。

## 現時点での判断

実行可能性と予測の優位性は別です。ATR・CUSUM・注文条件は未来を参照せず機械化できます。LSTMは必須ではなく、今回の固定条件では明確な改善を確認できませんでした。ただし、LSTM一般が無効だという結論ではありません。

履歴の探索結果だけで採用を決めず、今回固定した条件を変えずに、未使用の完結した複数セッションで予測方向・利益返却・費用を継続評価する段階です。未完のセッションを好都合な終了点で確定収益にしません。

## 再現資料

- [検証計画](資料/検証計画.md)、[独立レビュー](資料/独立レビュー.md)、[元足の因果性監査](資料/因果性監査.md)
- [実行条件](実行条件.md)、[未使用セッションの打切り監査](資料/live_prefix_review.md)
- [入力監査](資料/data_audit.md)、[ML漏洩監査](資料/ml_causality_audit.json)、[学習記録](資料/ml_training_record.json)
- [凍結記録](資料/凍結記録.json)、[一回取得記録](資料/live/取得記録.json)、[未使用セッションの全結果](資料/live/未使用セッション結果.json)
- [全取引CSV](資料/全取引.csv)、[乱数100通りCSV](資料/コイントス100通り.csv)

実行用コードはプロジェクトの `work/wave_v7`。`資料` はその保存版です。報告書再生成は `py -3.12 -X utf8 work/wave_v7/build_report.py`。保存モデルでの予測は `work/wave_v7/ml_models.py predict --data 入力.npz --output 予測.npz`。API取得を伴う `fetch_once.py` は再実行しないでください。

学習を再現する場合は、凍結済みモデルを上書きしないよう**別の出力先を指定**します。例：`work/wave_v7/ml_gpu_env/Scripts/python.exe -X utf8 work/wave_v7/ml_models.py train --data work/wave_v7/dataset.npz --output-dir work/wave_v7_replay_ml`。再学習したモデルを、今回の未使用テストの固定モデルに差し替えません。
'''
    (DEST / "検証結果.md").write_text(md, encoding="utf-8")
    readme = '''# 00003 未来情報を使わない予測検証

最初に **[検証結果.html](検証結果.html)** を開いてください。

読む順序：

1. [検証結果.html](検証結果.html)：結論、機械/ML比較、各方式・セッションの利益/損失/収支、初めて読むナイトの途中結果。
2. [検証結果.md](検証結果.md)：機械実行の条件、時系列評価、カンニング防止の検査と限界。
3. [実行条件.md](実行条件.md)：機械実行時の具体的な入力・注文・返済条件。
4. [独立レビュー](資料/独立レビュー.md)・[元足の因果性監査](資料/因果性監査.md)・[未使用セッションの打切り監査](資料/live_prefix_review.md)：未来情報を入れていないことの検査。
5. [セッション別収支CSV](資料/セッション別収支.csv)・[全取引CSV](資料/全取引.csv)：全条件の数値。

既知5セッションの時間順再評価と、9/23ナイト19:14締切の初回取得データの照合を分けています。未返済の評価損益は確定収支に含めていません。

従来の5分足図解は [00001の売買ポイント図解](../00001_波検知と売買ポイントの調査/売買ポイント図解.html)、出口の図解は [00002の出口比較](../00002_出口の利益保護の検証/出口比較.html) を参照してください。

[全作業の一覧へ](../index.html)
'''
    (DEST / "README.md").write_text(readme, encoding="utf-8")


# ----------------------------------------


def write_html(report: dict) -> None:
    """外部依存のない切替式の日本語報告HTMLを生成する。

    引数: report (dict) は保存結果から作った表と元データ。
    返り値: None。検証結果.htmlだけを生成する。
    """
    dataset = {
        "historical": report["historical"]["セッション収支"], "live": report["live"]["セッション収支"],
        "accuracy": report["historical"]["予測成績"], "liveAccuracy": report["live"]["予測成績"],
        "names": report["historical"]["方式名"], "testSessions": TEST_SESSIONS,
    }
    encoded = json.dumps(dataset, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    replacements = {
        '<a href="検証結果.md">条件の詳細</a>': '<a href="実行条件.md">具体的な実行条件</a>',
        '<a href="資料/data_audit.md">入力監査</a></p>': '<a href="資料/data_audit.md">入力監査</a> · <a href="資料/live_prefix_review.md">未使用セッションの打切り監査</a></p>',
        '以下は毎分判断の満了・未満了です。': '以下は取得締切19:14以前の判断のみです。目標時刻が締切後の「未満了」と、それ以外で必要な足がない「足不足」を分け、正答率には混ぜません。',
        "@@SUMMARY@@": html_table(["方式", "銘柄", "利益", "損失", "収支", "返済件数", "費用倍収支"], report["summary_rows"]),
        "@@ACCURACY@@": html_table(["方式", "銘柄", "正答 / 方向判定", "正答率", "均衡正答率"], report["accuracy_rows"]),
        "@@SELECTED@@": html_table(["セッション", "銘柄", "過去から選択", "利益", "損失", "収支", "件数"], report["selected_rows"]),
        "@@LIVE@@": html_table(["方式", "銘柄", "利益", "損失", "確定収支", "返済件数", "未返済", "未返済評価損益"], report["live_rows"]),
        "@@PENDING@@": html_table(["銘柄", "予測先分", "締切以前の毎分判断", "評価可能", "未満了", "足不足"], report["pending"]),
        "@@NULL@@": html_table(["方式", "銘柄", "平均収支", "下側5%", "上側95%", "費用倍平均"], report["null_rows"]),
        "@@SEEDS@@": html_table(["予測先分", "銘柄", "seed", "方向標本数", "正答率", "均衡正答率"], report["seed_rows"]),
        "@@DATA@@": encoded,
    }
    page = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>00003｜未来情報を使わない予測検証</title>
<style>
:root{--ink:#172a3a;--muted:#566a79;--line:#d7e2e8;--accent:#166283;--bg:#f2f6f8;--good:#126752;--bad:#ae3d37}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 system-ui,"Yu Gothic UI",sans-serif}main{max-width:1250px;margin:auto;padding:30px 25px 70px}a{color:var(--accent);text-underline-offset:3px}.back{font-size:13px}h1{font-size:clamp(27px,4vw,40px);line-height:1.3;margin:12px 0 18px}h2{font-size:24px;line-height:1.4;margin:0 0 15px}h3{font-size:18px;margin:24px 0 10px}p{margin:10px 0}section{background:white;border:1px solid var(--line);border-radius:15px;padding:26px;margin:22px 0;scroll-margin-top:20px}.eyebrow{color:var(--accent);font-size:13px;font-weight:700;letter-spacing:.08em}.intro{font-size:19px;max-width:1000px}.hero{padding:28px;border-radius:16px;background:#e9f2f5;border-left:5px solid var(--accent)}.tags{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.tag{background:#fff;border:1px solid #c9dbe4;border-radius:30px;padding:5px 13px;font-size:13px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:22px 0}.card{padding:20px;background:#fff;border:1px solid var(--line);border-radius:14px}.card strong{display:block;font-size:20px;margin:5px 0}.muted{color:var(--muted)}.note{background:#fff8e9;border-left:4px solid #d29a38;padding:13px 16px;margin:16px 0;border-radius:4px}.table-wrap{overflow-x:auto;margin:17px 0;border:1px solid var(--line);border-radius:8px}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums;white-space:nowrap}th,td{padding:10px 13px;border-bottom:1px solid #e2eaee;text-align:right}th{background:#f0f5f7;color:#355364;font-size:13px}th:first-child,td:first-child{text-align:left}tbody tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:#fafcfd}.positive{color:var(--good);font-weight:650}.negative{color:var(--bad);font-weight:650}.controls{display:flex;align-items:end;gap:16px;flex-wrap:wrap;background:#f4f7f9;padding:18px;border-radius:10px;margin:18px 0}label{display:flex;flex-direction:column;gap:5px;font-size:13px;font-weight:600}select{border:1px solid #adc0cc;border-radius:7px;background:#fff;color:var(--ink);font:inherit;font-size:15px;padding:9px 11px;max-width:100%}.mini{font-size:13px}nav{display:flex;flex-wrap:wrap;gap:16px;margin-top:20px}nav a{font-size:14px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}.stat{padding:15px;border:1px solid var(--line);border-radius:9px;background:#fcfefe}.stat span{display:block;font-size:12px;color:var(--muted)}.stat strong{font-size:24px;font-variant-numeric:tabular-nums}.checks{padding-left:23px}.checks li{margin:10px 0}details{border-top:1px solid var(--line);padding:16px 0;margin-top:16px}summary{cursor:pointer;font-weight:650}code{font-size:13px;background:#edf3f5;padding:2px 5px;border-radius:4px}.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}.flow div{border:1px solid #c9dbe4;padding:15px;border-radius:9px;background:#f6fafb}.flow b{display:block;color:var(--accent)}footer{color:var(--muted);font-size:13px;padding:10px 0}#session-chart{width:100%;height:auto;border:1px solid var(--line);border-radius:9px;background:#fbfdfe}noscript{display:block;background:#fff8e9;padding:12px} @media(max-width:760px){main{padding:20px 12px 45px}section{padding:19px 14px}.cards,.flow{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}.intro{font-size:17px}.controls{padding:12px}select{width:100%}label{width:100%}}
</style></head><body><main>
<!--
[コンポーネント概要]
#overview は結論・検証の範囲・読む順序をまとめます。
#profit-controls は保存された方式と期間の選択だけを行い、学習・最適化は行いません。
#profit-table と #session-chart は選択条件の確定した損益を表示します。
#prediction-controls は同じ予測結果の先行時間と標本間隔を選択します。
#live-result は未使用セッションの確定収支と未返済評価損益を別列で表示します。
すべてのデータを文書内に埋め込み、外部通信は行いません。
-->
<a class="back" href="../index.html">← 全作業の一覧</a>
<header id="overview"><div class="eyebrow">00003 · NK225 / TOPIX · 2026年9月23日</div><h1>未来情報を使わない予測検証</h1>
<div class="hero"><p class="intro"><strong>機械的な実行は可能です。LSTMは必須ではありません。</strong><br>ただし今回の実データでは、将来を安定して当てる優位性までは確認できませんでした。LSTMも常時ロングを明確に上回っていません。</p></div>
<div class="tags"><span class="tag">機械48条件＋ML12条件</span><span class="tag">乱数100seed対照</span><span class="tag">未来情報の隔離を監査</span><span class="tag">未使用ナイトを一回照合</span><span class="tag">セッション内返済</span></div>
<nav><a href="#past-results">時間順の収支</a><a href="#prediction">予測の正答率</a><a href="#live-result">未使用ナイト</a><a href="#details">全方式のセッション別収支</a><a href="#audit">カンニング防止</a><a href="検証結果.md">詳細な報告書</a></nav></header>
<div class="cards"><div class="card"><span class="eyebrow">実行可能性</span><strong>確定足だけで逐次計算</strong><span class="muted">ATR・CUSUMは過去の状態を更新する機械ルール。モデル学習は不要です。</span></div><div class="card"><span class="eyebrow">予測の区別</span><strong>収支 ≠ 方向を当てる能力</strong><span class="muted">常時ロングや乱数方向でも利益が生じる期間でした。方向精度も別に比較します。</span></div><div class="card"><span class="eyebrow">未使用データ</span><strong>9/23ナイト 19:14まで</strong><span class="muted">途中経過の一回再生です。実発注や、取得後の未来を待った運用ではありません。</span></div></div>
<section><h2>どのように機械実行するか</h2><p>時刻tまでに利用できる情報から方向を出し、その後の30・60・120分を答え合わせしました。ATRは値動きの幅の尺度で、方向予測そのものではありません。</p><div class="flow"><div><b>① 方向を判定</b>機械ルール、または固定モデルが買い・売りを判定。</div><div><b>② 1ATRで新規</b>追跡安値から1A反発で買い、追跡高値から1A反落で売り。</div><div><b>③ 損切り・追跡</b>初期損切り2.5A。元出口は4A、保護出口は利益2.5Aで0.5Aへ。</div><div><b>④ セッション内で返済</b>デイ15:35、ナイト翌05:50以降の実在足で強制返済。</div></div><p class="mini muted">Aは新規注文作成時のATRで固定。1銘柄1建玉、返済後45分待機。新規受付はデイ09:30〜15:05未満、ナイト17:45〜翌05:20未満。足確定後の判断に1分の余裕を取り、後続足から条件を適用します。<a href="検証結果.md">条件の詳細</a></p></section>
<section id="past-results"><div class="eyebrow">既知の履歴 · 時間順再評価</div><h2>過去だけで選んで、次のセッションで試す</h2><p>9/21デイ・ナイトを最初の学習期間とし、9/22デイ、9/22ナイト、9/23デイの3セッションを順に評価。各回の学習・選択に、その回の評価期間は使いません。</p><div class="note">この5セッションは過去の探索で既に使用済みです。時間順に再評価しても、真の未使用データには戻りません。</div><p><strong>単位：万円。ラージ1枚、往復2ティック相当控除後。</strong> 利益はプラス取引の合計、損失はマイナス取引の絶対値。費用倍は往復4ティックです。</p>@@SUMMARY@@<p>過去だけで選択した手順はNK225＋37万円、TOPIX＋42万円でした。線形60分は常時ロングと同額。LSTM60分も、方向予測と収支の両面で明確な改善を示していません。</p><details><summary>各セッションで何を事前選択したか</summary>@@SELECTED@@<p class="mini">次セッションの収支は選択に不使用。48条件から、両銘柄で実際に取引した条件を対象に、費用倍での銘柄別ATR収支の小さい方→合計→固定識別子の順で選択しました。</p></details></section>
<section id="prediction"><h2>60分先の方向を当てたか</h2><p>同じ銘柄の予測対象区間が重ならないよう60分間隔で抽出。横ばいを除く方向判定は両銘柄とも23標本です。両指数の市場相関もあるため、46個の完全独立標本とは扱いません。</p>@@ACCURACY@@<p><strong>LSTM60分の均衡正答率は両銘柄50%。</strong> 均衡正答率は、実際に上昇した場合と下落した場合の正答率を等重みで平均した値です。上昇ばかり予測する効果を区別します。</p><p>120分LSTMは毎分評価で100%上昇予測となり、見かけの63.29%は常時ロングと同じでした。LSTM一般が無効だと結論したわけではありません。</p>
<details><summary>全方式・30分 / 60分 / 120分先の予測成績を見る</summary><div id="prediction-controls" class="controls"><label>方向方式<select id="prediction-method"></select></label><label>予測先<select id="horizon"><option value="30">30分</option><option value="60" selected>60分</option><option value="120">120分</option></select></label><label>標本間隔<select id="spacing"><option value="nonoverlap">予測先と同じ間隔</option><option value="5">5分間隔・重複あり</option></select></label></div><div id="prediction-table"></div><p class="mini muted">予測先が違うモデルを選んでも表の「予測先」が実際の採点対象です。5分間隔の重複標本を独立件数として有意性を主張していません。</p></details></section>
<section id="live-result"><div class="eyebrow">初めて読むセッション · 条件固定後の一回照合</div><h2>9/23ナイトの途中結果</h2><p>条件固定19:14:39、取得開始19:14:40、共通データ締切19:14。1分足の最終開始は19:13です。状態1URL、足・板6URLを各1回取得し、再試行・再取得なし。固定後に学習・再選択していません。</p><div class="note"><strong>取得前から存在していた価格を含むセッションを、初めて読み再生した試験です。</strong> 取得後の未来を実時間で待った運用や、実際の注文成績ではありません。</div><p>単位：万円。<strong>確定収支と未返済の評価損益を分離</strong>しています。未返済は最後の終値で評価し、往復2ティック相当も控除した参考額です。未完セッションの最終収支とは扱いません。</p>@@LIVE@@<p>従来の手法①（機械09）はNK225−17万円、TOPIX−7万円。全履歴から事前選択した機械14/利益保護はNK225−17万円、TOPIX＋4.5万円でした。結果を見て別方式へ差し替えていません。</p><h3>未来の答えがまだ分からない予測</h3><p>60分間隔の評価は各銘柄1標本だけ、120分先は0標本です。100%/0%になっても能力の根拠にはしません。以下は毎分判断の満了・未満了です。</p>@@PENDING@@<p><a href="資料/live/未使用セッション結果.json">一回照合の全結果</a> · <a href="資料/live/取得記録.json">取得記録</a> · <a href="資料/凍結記録.json">固定した条件</a></p></section>
<section id="details"><h2>全方式のセッション別収支</h2><p>ここでの切替は結果の閲覧だけです。成績の良い条件を採用し直す操作ではありません。主比較は後半3セッションです。</p><div id="profit-controls" class="controls"><label>表示期間<select id="period"><option value="test">時間順評価の3セッション</option><option value="all">既知の全5セッション・学習期間を含む</option><option value="live">未使用ナイト・途中</option></select></label><label>方式<select id="method"></select></label><label>銘柄<select id="symbol"><option value="all">両銘柄</option><option>NK225</option><option>TOPIX</option></select></label></div><p id="method-description" class="muted"></p><div id="totals" class="stats"></div><svg id="session-chart" viewBox="0 0 1000 250" role="img" aria-label="各セッションの確定収支"></svg><div id="profit-table"></div><p class="mini muted">グラフ・合計は確定取引のみ。全5セッション表示は学習に使った期間も含むため、MLや時間順選択の評価範囲と揃いません。存在しない評価行は0とせず表示しません。</p></section>
<section id="audit"><h2>カンニングを防ぐために確認したこと</h2><ol class="checks"><li><strong>当時確定していた足だけで計算。</strong> 手法①の元足を240時刻で切断・未来OHLCを改変して再構築し、過去の特徴と方向が一致しました。</li><li><strong>独立した逐次ATR・CUSUMと照合。</strong> 5590行で方向一致、ATRの最大誤差は1.42×10⁻¹⁴でした。</li><li><strong>学習は過去だけ。</strong> ラベル満了が評価開始前かを検査。補完・標準化も各学習期間だけで計算します。</li><li><strong>未来の教師・特徴を改変して再学習。</strong> 全3fold×3期間の標準化・線形係数・27 LSTMの重みが完全一致しました。</li><li><strong>教師のない入力で予測。</strong> 未来行の削除や未来特徴の改変でも、過去の15予測配列が完全一致しました。</li><li><strong>初回取得前に条件とモデルを固定。</strong> SHA256を記録し、取得後も変更がないことを確認しました。</li></ol><p class="mini muted">元足の監査は手法①のATR/CUSUMが対象で、全24系統・全生板特徴を同じ強さで検査済みとはしていません。板の受信時刻は保存されておらず、利用可能時刻は保存順・最終約定時刻に基づく近似です。実配信遅延・約定順位・訂正は完全再現していません。</p><p><a href="資料/独立レビュー.md">独立レビュー</a> · <a href="資料/因果性監査.md">元足の監査</a> · <a href="資料/ml_causality_audit.json">MLの監査</a> · <a href="資料/data_audit.md">入力監査</a></p></section>
<section><h2>コイントスと注文だけでも利益が出るか</h2><p>同じ後半3セッションで、30分ごとの乱数方向を100seedすべて検証しました。単位：万円。</p>@@NULL@@<p>平均がプラスでも、損失になるseedがあり分布は大きい結果です。注文条件や相場の方向性でも収益が生じるため、プラス収支だけで予測能力を認定しません。最も良いseedは選んでいません。</p><p class="mini muted">今回は単一方向を30分ごとに更新する対照で、新たな両建て最適化は行っていません。</p></section>
<section><h2>固定した機械学習の条件</h2><p>同じ20価格特徴で、線形はL2=0.01・Newton法60反復。LSTMは単方向1層16ユニット・過去30分・20epoch・batch128・Adam 0.001。seed1729/1730/1731の確率平均を主結果にしています。GPUはRTX4090/CUDA12.8です。</p><p>学習標本は5分間隔、予測は毎分。早期終了・良いseedの選別・取得後の再学習はしていません。</p><details><summary>LSTMの全3seedを確認する</summary><p>予測先と同じ間隔で抽出した非重複標本。すべてのseedを表示します。</p>@@SEEDS@@</details><p><a href="資料/ml_training_record.json">学習とモデルの記録</a> · <a href="資料/検証計画.md">検証前に固定した計画</a></p></section>
<section><h2>この結果から採用判断できる範囲</h2><p><strong>機械実行できることは確認できました。安定した予測優位を確認できた段階ではありません。</strong> 今回の条件を変えず、未使用の完結した複数セッションで、方向精度・利益返却・費用を続けて評価する必要があります。</p><p>LSTMは今回必須ではなく、追加すれば改善するという結果も得られませんでした。これはLSTM一般の無効性を意味しません。</p><p><a href="検証結果.md">詳細な報告書</a> · <a href="資料/セッション別収支.csv">全方式の収支CSV</a> · <a href="資料/全取引.csv">全取引CSV</a> · <a href="資料/未来方向の予測成績.csv">全予測成績CSV</a></p><p class="mini">従来の5分足図解：<a href="../00001_波検知と売買ポイントの調査/売買ポイント図解.html">元手法</a> · <a href="../00002_出口の利益保護の検証/出口比較.html">出口比較</a></p></section>
<footer>保存結果だけを埋め込んだHTMLです。外部通信・注文送信・再学習は行いません。実行用コードは work/wave_v7、資料フォルダは保存版です。</footer>
<noscript>方式切替にはJavaScriptを使用します。主要比較・未使用ナイトの全結果は上の固定表で閲覧できます。</noscript>
<script id="embedded-data" type="application/json">@@DATA@@</script><script>
"use strict";
const DATA = JSON.parse(document.getElementById("embedded-data").textContent);
/**
 * テキストをHTML用にエスケープします。
 * @param {unknown} value - 表示する値。
 * @returns {string} 安全なHTML文字列。
 */
function escapeText(value){return String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));}
/**
 * 方式名を日本語の短い表示へ変換します。
 * @param {string} value - 固定された識別子。
 * @returns {string} 表示名。
 */
function methodLabel(value){return value.replace("logistic_","線形・").replace("lstm_","LSTM・").replace("上昇固定","常時ロング").replace("下降固定","常時ショート").replace("元4ATR","元の4ATR出口").replace("利益保護","利益保護出口");}
/**
 * 円を万円で表示します。
 * @param {number} value - 円単位の金額。
 * @returns {string} 符号付き万円表示。
 */
function money(value){const x=value/10000;return (x>0?"+":"")+Number(x.toFixed(2)).toLocaleString("ja-JP");}
/**
 * セッション名を日本語へ変換します。
 * @param {string} value - セッション識別子。
 * @returns {string} 短いセッション表示。
 */
function sessionLabel(value){return value.replace("2026-","").replace("_Day"," デイ").replace("_Night"," ナイト");}
/**
 * 表の各セルをエスケープしてHTMLにします。
 * @param {string[]} headers - 列の名前。
 * @param {unknown[][]} rows - 表示する行。
 * @returns {string} 表を包むHTML。
 */
function table(headers,rows){return '<div class="table-wrap"><table><thead><tr>'+headers.map(x=>'<th>'+escapeText(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(x=>'<td>'+escapeText(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
/**
 * 選択した表示期間に存在する方式だけを設定します。
 * @param {boolean} initial - 初回かどうか。
 * @returns {void} 選択肢と結果を更新します。
 */
function setMethods(initial){const period=document.getElementById('period').value;const source=period==='live'?DATA.live:DATA.historical;const select=document.getElementById('method');const previous=select.value;let names=[...new Set(source.map(x=>x['方式']))];names.sort((a,b)=>a==='過去だけで選択'?-1:b==='過去だけで選択'?1:a.localeCompare(b,'ja'));select.innerHTML=names.map(x=>'<option value="'+escapeText(x)+'">'+escapeText(methodLabel(x))+'</option>').join('');select.value=names.includes(previous)?previous:(names.includes('過去だけで選択')?'過去だけで選択':names.includes('機械14/利益保護')?'機械14/利益保護':names[0]);renderProfit();}
/**
 * セッションごとの確定収支を符号付き棒で描きます。
 * @param {Object[]} rows - 選択中の収支行。
 * @returns {void} SVGを更新します。
 */
function renderChart(rows){const svg=document.getElementById('session-chart');const height=Math.max(150,rows.length*38+55);svg.setAttribute('viewBox','0 0 1000 '+height);const max=Math.max(10000,...rows.map(r=>Math.abs(r['収支円'])));let shapes='<text x="15" y="24" font-size="13" fill="#566a79">確定収支（万円）</text><line x1="570" x2="570" y1="36" y2="'+(height-10)+'" stroke="#9eb2c0"/>';rows.forEach((r,i)=>{const y=46+i*38;const width=Math.abs(r['収支円'])/max*300;const x=r['収支円']>=0?570:570-width;shapes+='<text x="15" y="'+(y+17)+'" font-size="14" fill="#172a3a">'+escapeText(sessionLabel(r['セッション'])+' '+r['銘柄'])+'</text><rect x="'+x+'" y="'+y+'" width="'+width+'" height="25" rx="3" fill="'+(r['収支円']>=0?'#28718c':'#b75b52')+'"/><text x="905" y="'+(y+17)+'" font-size="14" fill="#172a3a">'+money(r['収支円'])+'</text>';});svg.innerHTML=shapes;}
/**
 * 方式と期間の選択に対応する確定取引・未返済を表示します。
 * @returns {void} 合計、表、グラフを更新します。
 */
function renderProfit(){const period=document.getElementById('period').value;const method=document.getElementById('method').value;const symbol=document.getElementById('symbol').value;const source=period==='live'?DATA.live:DATA.historical;const rows=source.filter(r=>r['方式']===method&&(symbol==='all'||r['銘柄']===symbol)&&(period!=='test'||DATA.testSessions.includes(r['セッション'])));const fields=['利益円','損失円','収支円','取引数'];document.getElementById('totals').innerHTML=fields.map((f,i)=>{const total=rows.reduce((a,r)=>a+r[f],0);return '<div class="stat"><span>'+['確定利益（万円）','確定損失（万円）','確定収支（万円）','返済済み取引数'][i]+'</span><strong class="'+(i===2?(total>=0?'positive':'negative'):'')+'">'+(i===3?total:money(total))+'</strong></div>';}).join('');const family=method.split('/')[0];document.getElementById('method-description').textContent=family==='過去だけで選択'?'前のセッションまでの結果から、次に使う方式を固定した手順。':DATA.names[family]||'事前固定したモデルまたは方向対照。';let headers=['セッション','銘柄','利益','損失','確定収支','返済件数','費用倍収支'];let values=rows.map(r=>[sessionLabel(r['セッション']),r['銘柄'],money(r['利益円']),money(r['損失円']),money(r['収支円']),r['取引数'],money(r['費用倍収支円'])]);if(period==='live'){headers.push('未返済数','未返済評価損益');values=values.map((v,i)=>v.concat(rows[i]['未返済数'],money(rows[i]['未返済評価損益円'])));}document.getElementById('profit-table').innerHTML=table(headers,values);renderChart(rows);}
/**
 * 固定した予測成績から先行時間と間隔を選んで表示します。
 * @returns {void} 予測の件数・正答率を更新します。
 */
function renderPrediction(){const method=document.getElementById('prediction-method').value;const horizon=Number(document.getElementById('horizon').value);const selected=document.getElementById('spacing').value;const spacing=selected==='nonoverlap'?horizon:5;const rows=DATA.accuracy.filter(r=>r['方式']===method&&r['予測先分']===horizon&&r['標本間隔分']===spacing);const percent=x=>x==null?'—':(100*x).toFixed(1)+'%';document.getElementById('prediction-table').innerHTML=table(['銘柄','評価可能','予測数','横ばい','方向判定','正答','正答率','均衡正答率'],rows.map(r=>[r['銘柄'],r['評価可能'],r['予測数'],r['横ばい数'],r['方向判定数'],r['正答数'],percent(r['正答率']),percent(r['均衡正答率'])]));}
// ----------------------------------------
const predictionMethods=[...new Set(DATA.accuracy.map(x=>x['方式']))];document.getElementById('prediction-method').innerHTML=predictionMethods.map(x=>'<option value="'+escapeText(x)+'">'+escapeText(methodLabel(x))+'</option>').join('');document.getElementById('prediction-method').value='lstm_60';document.getElementById('period').addEventListener('change',()=>setMethods(false));document.getElementById('method').addEventListener('change',renderProfit);document.getElementById('symbol').addEventListener('change',renderProfit);['prediction-method','horizon','spacing'].forEach(id=>document.getElementById(id).addEventListener('change',renderPrediction));setMethods(true);renderPrediction();
</script></main></body></html>'''
    for needle, content in replacements.items():
        page = page.replace(needle, content)
    (DEST / "検証結果.html").write_text(page, encoding="utf-8")


def main() -> None:
    """保存済み最終結果を読み、3つの報告成果物を作る。

    引数: なし。
    返り値: None。凍結したデータ・モデル・研究コードは変更しない。
    """
    DEST.mkdir(parents=True, exist_ok=True)
    report = prepare()
    write_markdown(report)
    write_html(report)
    print(f"報告生成完了: {DEST}")


if __name__ == "__main__":
    main()
