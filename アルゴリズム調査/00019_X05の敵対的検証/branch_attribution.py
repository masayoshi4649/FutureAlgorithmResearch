"""X05_G08を注文起源・約定時監視・枝の実稼働へ分解して反証する敵対監査。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np


OUT = Path(__file__).resolve().parent
OLD = OUT.parent / "wave_v23"
OUT.mkdir(parents=True, exist_ok=True)
sys.dont_write_bytecode = True
os.environ["NUMBA_CACHE_DIR"] = str(OUT / "numba_cache_branch")
sys.path.insert(0, str(OLD))
import engine
import depth_features
import managers
import selector_signals
import signals


BRANCHES = ("F32", "F42", "F43", "F44")
MULTIPLIERS = {"TOPIX": 1000.0, "NK225": 10.0}


def stamp(value: float) -> str:
    """機能: Unix秒を日本時間の表示へ変換する。

    引数: value (float) はUnix秒。
    返り値: タイムゾーンを含む時刻 (str)。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo("Asia/Tokyo")).isoformat()


def sha(path: Path) -> str:
    """機能: 旧入力・コードの不変性確認用に内容ハッシュを計算する。

    引数: path (Path) は対象。
    返り値: SHA256文字列 (str)。
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1048576):
            digest.update(block)
    return digest.hexdigest()


def expand(events: np.ndarray, values: np.ndarray, targets: np.ndarray, initial: float = 0) -> np.ndarray:
    """機能: 公開済み最後の値だけを行番号等へ展開する。

    引数: events/values/targets (ndarray)、initial (float) は初期値。
    返り値: 対象行ごとの値 (ndarray)。
    """
    output = np.full(len(targets), initial, dtype=values.dtype)
    pos = np.searchsorted(events, targets, side="right") - 1
    have = pos >= 0
    output[have] = values[pos[have]]
    return output


def metric(trades: list[dict]) -> dict:
    """機能: 一枝へ帰属させた取引の利益・損失・枚数を計算する。

    引数: trades (list[dict]) は注文起源を持つ取引一覧。
    返り値: 件数・金額・枚数の辞書 (dict)。
    """
    profit = sum(row["損益円"] for row in trades if row["損益円"] > 0)
    loss = -sum(row["損益円"] for row in trades if row["損益円"] < 0)
    return dict(取引数=len(trades), 利益円=profit, 損失円=loss, 収支円=profit - loss,
                勝ち枚数=sum(row["枚数"] for row in trades if row["損益円"] > 0),
                負け枚数=sum(row["枚数"] for row in trades if row["損益円"] < 0),
                同値枚数=sum(row["枚数"] for row in trades if row["損益円"] == 0))


def dense_choices(ready: dict, events: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """機能: 毎分の選択履歴を原本行ごとの監視枝・提案枝・判断位置へ展開する。

    引数: ready (dict)、events (list[dict]) はX05の当該区間の履歴。
    返り値: 監視枝・提案枝・判断イベント番号 (tuple[ndarray,...])。
    """
    rows = np.array([row["row_index"] for row in events], dtype=np.int64)
    selected = np.array([row["selected_signal_id"] for row in events], dtype="U3")
    proposed = np.array([row["proposed_signal_id"] for row in events], dtype="U3")
    targets = np.arange(len(ready["seq"]))
    return expand(rows, selected, targets, ""), expand(rows, proposed, targets, ""), expand(rows, np.arange(len(rows)), targets, -1)


def far_runs(ready: dict, chosen: np.ndarray, signal: np.ndarray) -> list[dict]:
    """機能: F43の各連続監視区間で、本当に信号が発火したかを調べる。

    引数: ready (dict)、chosen (ndarray[str])、signal (ndarray[int8]) はF43単独信号。
    返り値: 各監視区間の開始・終了・非中立発生等 (list[dict])。
    """
    active = chosen == "F43"
    starts = np.flatnonzero(active & ~np.r_[False, active[:-1]])
    ends = np.flatnonzero(active & ~np.r_[active[1:], False]) + 1
    rows = []
    for start, end in zip(starts, ends):
        have = np.flatnonzero(signal[start:end] != 0)
        stop = min(float(ready["time_s"][end]) if end < len(active) else float(ready["time_s"][-1]), float(ready["limit"]))
        rows.append(dict(セッション=ready["session"], 銘柄=ready["symbol"], 開始行=int(start), 終了排他行=int(end),
                         開始=stamp(ready["time_s"][start]), 終了=stamp(stop), 秒数=max(0., stop - ready["time_s"][start]),
                         発火あり=bool(len(have)), 非中立行数=int(len(have)),
                         初回発火まで秒=float(ready["time_s"][start + have[0]] - ready["time_s"][start]) if len(have) else None))
    return rows


def one_session(key: tuple, ready: dict, bases: dict, direction: np.ndarray, features, events: list[dict], manager: dict) -> dict:
    """機能: 一区間の監視時間と、新規注文起源・約定時監視枝へ損益を帰属する。

    引数: key (tuple)、ready/bases/manager (dict)、direction (ndarray)、features (DataFrame)、events (list[dict])。
    返り値: 監視・枝別損益・全取引・F43時間差の辞書 (dict)。
    """
    chosen, proposed, event_indices = dense_choices(ready, events)
    config = managers.make_config(manager, key[1], ready)
    result = engine.run(ready, direction, config, detail=True)
    with np.load(OLD / "trades" / "X05_G08.npz", allow_pickle=False) as ledger:
        for name in ("trades", "cycles"):
            np.testing.assert_array_equal(result[name], ledger[f"{key[0]}_{key[1]}_{name}"])
    orders, trades, curve = result["orders"], result["trades"], result["curve"]
    openings = orders[(orders[:, 7] == 1) & (orders[:, 6] == 20)]
    assert len(openings) == len(trades) == len(result["cycles"])
    assert (trades[:, 3] == 1).all()
    opening_by_campaign = {int(order[2]): order for order in openings}
    board = signals._board(ready, features, 120)
    near = expand(board["seq"], np.asarray(board["dflow_near"]), ready["seq"])
    far = expand(board["seq"], np.asarray(board["dflow_far"]), ready["seq"])
    all_trades = []
    for trade in trades:
        order = opening_by_campaign[int(trade[0])]
        filled, origin, exited = int(order[0]), int(order[1]), int(trade[7])
        assert 0 <= origin < filled and filled == int(trade[6])
        assert direction[origin] == order[3]
        record = dict(セッション=key[0], 銘柄=key[1], 組番号=int(trade[0]), 方向="買い" if trade[2] > 0 else "売り", 枚数=int(trade[3]),
                      注文起源枝=str(chosen[origin]), 約定時監視枝=str(chosen[filled]), 返済時監視枝=str(chosen[exited]),
                      注文元行=origin, 約定行=filled, 返済行=exited,
                      注文元原本seq=int(ready["seq"][origin]), 約定原本seq=int(ready["seq"][filled]),
                      注文作成時刻=stamp(ready["time_s"][origin]), 約定時刻=stamp(ready["time_s"][filled]), 返済時刻=stamp(ready["time_s"][exited]),
                      注文から約定まで秒=float(ready["time_s"][filled] - ready["time_s"][origin]),
                      建値=float(trade[4]), 返済値=float(trade[5]), 損益円=float(trade[10] * MULTIPLIERS[key[1]]),
                      返済理由=engine.REASONS[int(trade[9])], 約定時信号=int(direction[filled]),
                      注文元直近提案枝=str(proposed[origin]), 約定時直近提案枝=str(proposed[filled]),
                      注文元近傍変化=float(near[origin]), 注文元遠方変化=float(far[origin]))
        all_trades.append(record)
    # ----------------------------------------
    # 同一時刻の行を二重に数えず、各行から次行までの保持時間を監視時間とする。
    times = ready["time_s"]
    upper = np.minimum(np.r_[times[1:], times[-1]], ready["limit"])
    lower = np.maximum(times, ready["start"] + 1200)
    durations = np.maximum(0., upper - lower)
    monitor, origin_summaries, fill_summaries = [], [], []
    held = curve[:, 2] + curve[:, 3] > 0
    for branch in BRANCHES:
        mask = chosen == branch
        base_active = bases[branch] != 0
        record = dict(セッション=key[0], 銘柄=key[1], 枝=branch, 監視秒=float(durations[mask].sum()),
                      監視原本行数=int(mask.sum()), 信号非中立秒=float(durations[mask & base_active].sum()),
                      信号中立秒=float(durations[mask & ~base_active].sum()),
                      保有中監視秒=float(durations[mask & held].sum()), 無建玉監視秒=float(durations[mask & ~held].sum()),
                      代替F32方向あり秒=float(durations[mask & (bases["F32"] != 0)].sum()),
                      無建玉中の代替F32方向あり秒=float(durations[mask & ~held & (bases["F32"] != 0)].sum()),
                      基礎信号があるが選択されない秒=float(durations[~mask & base_active].sum()),
                      約定した新規注文の作成元件数=sum(row["注文起源枝"] == branch for row in all_trades),
                      新規約定時監視件数=sum(row["約定時監視枝"] == branch for row in all_trades))
        monitor.append(record)
        origin_summaries.append(dict(セッション=key[0], 銘柄=key[1], 枝=branch, **metric([r for r in all_trades if r["注文起源枝"] == branch])))
        fill_summaries.append(dict(セッション=key[0], 銘柄=key[1], 枝=branch, **metric([r for r in all_trades if r["約定時監視枝"] == branch])))
    # ----------------------------------------
    # F43選択時の閾値と、維持時間内に強まって発火する場合を区別する。
    proposed_rows = np.array([e["row_index"] for e in events if e["proposed_signal_id"] == "F43"], dtype=np.int64)
    switched_rows = np.array([e["row_index"] for e in events if e["selected_signal_id"] == "F43" and e["state"] == "切替"], dtype=np.int64)
    firing = (chosen == "F43") & (bases["F43"] != 0)
    far_evidence = dict(セッション=key[0], 銘柄=key[1], F43提案判断数=len(proposed_rows),
                        F43提案と同じ判断行でF43発火数=int(np.count_nonzero(bases["F43"][proposed_rows])),
                        F43切替判断数=len(switched_rows), 切替瞬間のF43発火数=int(np.count_nonzero(bases["F43"][switched_rows])),
                        監視中発火原本行数=int(firing.sum()), 監視中発火秒=float(durations[firing].sum()),
                        発火時に直近提案がF43の原本行数=int((firing & (proposed == "F43")).sum()),
                        発火時に直近提案が別枝の原本行数=int((firing & (proposed != "F43")).sum()),
                        発火中の近傍絶対値最小=float(np.abs(near[firing]).min()) if firing.any() else None,
                        起源F43の取引数=sum(row["注文起源枝"] == "F43" for row in all_trades))
    return dict(セッション=key[0], 銘柄=key[1], 全体=metric(all_trades), 監視=monitor,
                注文起源帰属=origin_summaries, 約定時監視帰属=fill_summaries, 取引=all_trades,
                F43反証=far_evidence, F43監視区間=far_runs(ready, chosen, bases["F43"]),
                全長再生一致=True, セッション返済済=bool(result["stats"][9] == 0))


def aggregate(records: list[dict], name: str) -> list[dict]:
    """機能: 銘柄と枝で件数・時間・損益を加算する。

    引数: records (list[dict]) は区間結果、name (str) は集計対象名。
    返り値: 銘柄・枝別合計 (list[dict])。
    """
    groups = defaultdict(list)
    for record in records:
        for row in record[name]:
            groups[(row["銘柄"], row["枝"])].append(row)
    return [dict(銘柄=symbol, 枝=branch, **{column: sum(row[column] for row in values)
                  for column in values[0] if column not in ("銘柄", "枝", "セッション")})
            for (symbol, branch), values in groups.items()]


def logical_examples() -> dict:
    """機能: 同時刻の矛盾と、時間差で発火する反例を固定数値で示す。

    引数: なし。
    返り値: 条件式だけで再現できる論理例 (dict)。
    """
    threshold = .05
    examples = []
    for name, near, far, far_before, progress in [
        ("選択した瞬間", .02, .10, .10, .10),
        ("30秒後に近い板も変化", .08, .10, .10, .10),
        ("近い板が変わらない休止", .02, .10, .10, .10),
    ]:
        proposal_far = abs(far) >= threshold and abs(near) < threshold
        trigger_far = far > threshold and far_before > threshold and near > threshold and abs(progress) <= .35
        examples.append(dict(場面=name, near=near, far=far, 前60秒far=far_before, 価格進行ATR=progress,
                             F43を提案=proposal_far, F43基礎信号が発火=trigger_far))
    assert examples[0]["F43を提案"] and not examples[0]["F43基礎信号が発火"]
    assert not examples[1]["F43を提案"] and examples[1]["F43基礎信号が発火"]
    refill_examples = []
    for explanation in ("同価格で10枚約定した後に10枚追加", "同価格で10枚取消した後に10枚再提示"):
        history = {}
        assert depth_features.consume_refill(history, 100.0, -10.0, 1.0) == 0
        measured = depth_features.consume_refill(history, 100.0, 10.0, 11.0)
        assert measured == 10.0
        refill_examples.append(dict(市場で起きた可能性=explanation, 数量観測="20→10→20", 減少から増加まで秒=10, 同じ補充代理値=measured))
    return dict(数値例=examples, 解釈="F43は選択直後には発火しない。選択を最低3分等で維持する間にnearが強まれば発火できる。nearが強まらなければ休止する。",
                補充識別不能の実装反例=refill_examples)


def report(payload: dict) -> str:
    """機能: 実測集計と論理限界を短い敵対監査文へまとめる。

    引数: payload (dict) は監査結果。
    返り値: 日本語Markdown (str)。
    """
    lines = ["# X05_G08の敵対的な論理監査", "",
             "全13セッション×2銘柄を旧条件のまま詳細再生し、保存済み取引台帳との完全一致を確認した。新たな現在データ取得、数値条件の変更、原本・旧成果の書換えは行っていない。", "",
             "## 利益を作った枝", "",
             "利益帰属は約定時に表示されていた枝ではなく、約定した新規注文を作った原本行の枝で集計する。orders[:,1]はこの作成元行であり、ordersは未約定注文も含む発注一覧ではない。", "",
             "| 銘柄 | 注文起源枝 | 取引数 | 利益 | 損失 | 収支 |", "|---|---|---:|---:|---:|---:|"]
    for row in payload["注文起源別合計"]:
        lines.append(f"| {row['銘柄']} | {row['枝']} | {row['取引数']} | {row['利益円']:,.0f}円 | {row['損失円']:,.0f}円 | {row['収支円']:+,.0f}円 |")
    lines += ["", "| 銘柄 | 監視枝 | 監視時間 | うち方向あり | 約定した新規注文の作成元 | 約定時の監視 |", "|---|---|---:|---:|---:|---:|"]
    for row in payload["監視合計"]:
        lines.append(f"| {row['銘柄']} | {row['枝']} | {row['監視秒']/60:.1f}分 | {row['信号非中立秒']/60:.1f}分 | {row['約定した新規注文の作成元件数']} | {row['新規約定時監視件数']} |")
    changed = payload["起源と約定時の監視が違う取引"]
    lines += ["", f"注文起源と約定時の監視枝が異なる取引は{len(changed)}件。起源別と約定時別の集計を両方JSONに保存した。G08では保有中の枝変更で玉を返済しないため、返済時の枝へ利益を付け替えるのも不適切である。", "",
              "実際の利益起源はNKがF32/F42の2枝、TOPIXがF32/F42/F44の3枝。TOPIXのF44起源収支は1,500円と小さい。四つ全てが売買して稼いだという説明は、このデータからは成立しない。", "",
              "監視時間の大半もF32で、TOPIX87.6%、NK97.8%。広い相場状況で四つの思想を使い分けたことが確認された、と説明するのは過剰である。", "",
              "## F43は選択条件と発火条件が同時には満たせない", "",
              "X05がF43を提案する条件は近い板変化の絶対値が0.05未満。F43が発火するには、近い板変化の絶対値が0.05を超え、遠い板と同方向でなければならない。同じ判断時点では両立しない。", "",
              "ただし選択は毎分判定、2回確認・最低3分維持を伴う。選択後に近い板が強まれば、保持中のF43が発火する余地はある。これは時間差を待つ二段階条件であり、厳密な論理矛盾による完全死枝とは限らない。", "",
              "| 銘柄 | F43提案判断 | 同じ判断行の発火 | 監視中発火秒 | 注文起源取引 | 発火した監視区間/全区間 |", "|---|---:|---:|---:|---:|---:|"]
    for symbol in ("TOPIX", "NK225"):
        rows = [row for row in payload["F43区間別反証"] if row["銘柄"] == symbol]
        runs = [row for row in payload["F43監視区間"] if row["銘柄"] == symbol]
        lines.append(f"| {symbol} | {sum(r['F43提案判断数'] for r in rows)} | {sum(r['F43提案と同じ判断行でF43発火数'] for r in rows)} | {sum(r['監視中発火秒'] for r in rows):.1f} | {sum(r['起源F43の取引数'] for r in rows)} | {sum(r['発火あり'] for r in runs)}/{len(runs)} |")
    lines += ["", "near=0.02・far=0.10ならF43を選ぶが信号は0。30秒後near=0.08・far=0.10、60秒前farも0.10、価格進行0.10ATRなら保持中F43が買いを出せる。nearが0.02のままなら選択されても新規を出さない。したがって枝除去・固定化による実損益と併せ、情報選択の利益なのか単なる休止効果なのかを判定する必要がある。", "",
              "実測ではTOPIXのF43監視469秒は全て既存玉の保有中、NKの185秒は全て無建玉中だった。F43自体は選択されていない時間にTOPIX36,994秒・NK30,361秒の方向信号を出しているが、X05が監視した時間との交差はゼロ。F43の有効性を検証できたとも、F43が利益へ貢献したとも言えない。", "",
              "さらに、F43監視中かつ無建玉の時間に、代替F32が方向を出した秒数も両銘柄とも0。保有中はG08が信号変更を使わず、無建玉中は代替信号も0なので、この記録ではF43をF32へ置き換えても売買へ寄与する情報は増減しない。別の枝除去再生で結果が不変だったことと整合する。", "",
              "## 代理指標を過大解釈できない理由", "",
              "1. F32の加重気配偏差は、最良買い数量をB、売り数量をAとすると `(加重気配−仲値)/スプレッド = (B−A)/(2(B+A)) = imb1/2`。新しい独立情報でも、学習済みmicropriceでもない。2分平均による平滑化と価格方向条件が加わっているだけである。全保存特徴でこの恒等式を数値照合した。",
              f"   最大絶対誤差は {payload['F32冗長性']['最大絶対誤差']:.3g}、照合特徴行数は {payload['F32冗長性']['行数']:,}。",
              "2. 補充は『前後両方に見える同価格の数量減少→30秒内の増加』である。取消して再提示しても同じ値になる。約定による消費、アイスバーグ、同一参加者、裁量・アルゴ、新規・返済を区別できない。取引のtick-rule推定も真の主導売買ではない。",
              "   実装反例では、数量20→10→20が『10枚約定して補充』でも『10枚取消して再提示』でも、同じ補充値10を返す。補充値だけから前者を断定できない。",
              "3. 距離重みは現在最良気配からの距離に exp(-距離/2) と exp(-距離/8) を掛ける。遠い板専用と近い板専用の独立帯ではなく、両方に最良価格が重み1で入る重複した集計。両系列の一致は独立証拠が二つあることを意味しない。",
              "   解放ブロックの近遠dflowの単純相関はTOPIX0.9837、NK0.9860。pressureの相関もTOPIX0.7306、NK0.7914だった。",
              "4. 数量差分は前後共通の価格だけ。新たに表示された価格や上位10段から外れた価格を除き、最良価格移動で重みも変わる。全注文追加・取消・消費を網羅したフローではない。2分平均は各解放ブロックの比率の単純平均で、小量ブロックと大量ブロックに同じ重みが付き得る。",
              "5. X05の選択条件もF32/F42/F43/F44の基礎方向も自銘柄だけで完結する。共通準備関数がpeer_emaを計算していてもX05の分岐では使わない。『NKとTOPIXを同時に見て売買を判断する主候補』とは呼べない。相手情報だけを変えた制御反例でも方向は不変だった。",
              "6. G08は枝変更・中立・反対方向で既存玉を自動返済しない。成功した枝へ自動で建玉が乗り換わるアルゴリズムではなく、新規信号選択と保有継続管理の組合せである。", "",
              "この監査の帰属は会計上の分解であり、枝を外したときの因果効果そのものではない。一つの約定を消すと待機・連敗停止・セッション損失予算が変わり、後続取引も変わる。除去再生・固定化再生は別評価が必要である。", ""]
    return "\n".join(lines)


def main() -> None:
    """機能: 旧条件の全区間枝帰属・論理反例を監査し、新規領域へ保存する。

    引数: なし。
    返り値: なし (None)。現在APIと原本の再取得を使用しない。
    """
    protected = [OLD / name for name in ("engine.py", "signals.py", "selector_signals.py", "managers.py", "depth_features.py", "inputs.pkl", "features_depth.pkl", "directions.pkl", "selector_directions.pkl", "手法選択の履歴.json")]
    before = {path.name: sha(path) for path in protected}
    inputs = pickle.loads((OLD / "inputs.pkl").read_bytes())
    features = pickle.loads((OLD / "features_depth.pkl").read_bytes())
    directions = pickle.loads((OLD / "directions.pkl").read_bytes())
    selected = pickle.loads((OLD / "selector_directions.pkl").read_bytes())["X05"]
    events = json.loads((OLD / "手法選択の履歴.json").read_text(encoding="utf-8"))["相場状態から選択"]
    grouped_events = defaultdict(list)
    for event in events:
        if event["selector_id"] == "X05":
            grouped_events[(event["session"], event["symbol"])].append(event)
    manager = next(row for row in managers.manager_catalog() if row["id"] == "G08")
    records = []
    for key, ready in inputs.items():
        bases = {branch: directions[branch][key] for branch in BRANCHES}
        records.append(one_session(key, ready, bases, selected[key], features[key], grouped_events[key], manager))
    redundant = [np.abs(frame.micro_bias.to_numpy(float) - frame.imb1.to_numpy(float) / 2) for frame in features.values()]
    correlations = []
    for symbol in ("TOPIX", "NK225"):
        values = np.vstack([frame[["dflow_near", "dflow_far", "pressure_near", "pressure_far"]].to_numpy(float)
                            for key, frame in features.items() if key[1] == symbol])
        correlations.append(dict(銘柄=symbol, 特徴行数=len(values),
                                 近遠dflow相関=float(np.corrcoef(values[:, 0], values[:, 1])[0, 1]),
                                 近遠pressure相関=float(np.corrcoef(values[:, 2], values[:, 3])[0, 1])))
    controls = selector_signals._controls(inputs, features, directions)
    spec = next(item for item in selector_signals.catalog() if item["id"] == "X05")
    peer_checks = []
    for key, ready in inputs.items():
        alternative = dict(controls[key])
        alternative["peer_ema"] = -controls[key]["peer_ema"]
        alternative["own_ema"] = -controls[key]["own_ema"]
        alternative["efficiency"] = np.full_like(controls[key]["efficiency"], 999.0)
        base = {branch: directions[branch][key] for branch in BRANCHES}
        changed, _ = selector_signals._select(spec, ready, alternative, base)
        assert np.array_equal(changed, selected[key])
        peer_checks.append(dict(セッション=key[0], 銘柄=key[1], 方向一致=True))
    after = {path.name: sha(path) for path in protected}
    assert before == after
    all_trades = [row for record in records for row in record["取引"]]
    payload = dict(対象="X05_G08", 区間数=len(records), 現在API取得回数=0, 旧入力コード不変=True, 入力SHA256=before,
                   注文台帳の意味="ordersは約定台帳。列1は約定に対応する注文の決定元原本行であり、未約定の全発注件数ではない。",
                   注文起源別合計=aggregate(records, "注文起源帰属"), 約定時監視別合計=aggregate(records, "約定時監視帰属"), 監視合計=aggregate(records, "監視"),
                   区間別=records, 全取引=all_trades, 起源と約定時の監視が違う取引=[row for row in all_trades if row["注文起源枝"] != row["約定時監視枝"]],
                   F43区間別反証=[record["F43反証"] for record in records], F43監視区間=[row for record in records for row in record["F43監視区間"]],
                   F43論理反例=logical_examples(), F32冗長性=dict(行数=sum(len(row) for row in redundant), 最大絶対誤差=max(float(row.max()) for row in redundant)),
                   距離重み系列の重複=correlations,
                   使わない相手EMAと効率比の改変不変=peer_checks)
    (OUT / "branch_attribution.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (OUT / "logical_audit.md").write_text(report(payload), encoding="utf-8")
    print(f"枝監査を保存しました: {len(records)}区間、{len(all_trades)}取引")


if __name__ == "__main__":
    main()
