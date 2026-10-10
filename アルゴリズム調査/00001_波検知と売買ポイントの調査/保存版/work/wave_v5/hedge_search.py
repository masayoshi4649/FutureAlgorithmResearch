"""両建て108条件と、全条件を同じ100種で評価する片側コイントス対照。"""

from __future__ import annotations

import csv
from dataclasses import asdict
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import pickle
import time

import numpy as np
import pandas as pd

from hedge import HedgeConfig, simulate


OUT = Path(__file__).resolve().parent
SEEDS = tuple(range(260925000, 260925100))
REPRESENTATIVE_SEED = SEEDS[0]


def save_json(path: Path, value: object) -> None:
    """機能: 日本語と日時を保持して検証記録を保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")


def configurations() -> list[HedgeConfig]:
    """機能: 出口18組と待機・開始条件の直積を事前列挙する。

    引数: なし。返り値: 比較条件108件 (list[HedgeConfig])。
    """
    return [HedgeConfig(mode, stop, target, cooldown, warmup)
            for mode, stop, target, cooldown, warmup in itertools.product(
                ("固定利確", "勝ち脚追跡"), (0.5, 1.0, 1.5), (2.0, 3.0, 4.0), (15, 30, 60), (15, 45))]


def seed_summary(rows: list[dict], cfg: HedgeConfig) -> tuple[list[dict], list[dict]]:
    """機能: 全固定種の分布とセッション平均を、勝った種だけを選ばず集計する。

    引数: rows (list[dict]) は全種のセル、cfg (HedgeConfig) は注文条件。
    返り値: 銘柄別分布とセッション別平均 (tuple[list[dict], list[dict]])。
    """
    frame = pd.DataFrame(rows)
    summary = []
    for symbol, group in frame.groupby("symbol"):
        sums = group.groupby("seed").agg(net=("net_points", "sum"), stress=("stress_points", "sum"),
                                         trades=("count", "sum"), cycles=("cycle_count", "sum"))
        values = sums.net.to_numpy()
        summary.append(dict(config=cfg.key, symbol=symbol, **asdict(cfg), seed_count=len(sums),
                            mean_net_points=float(values.mean()), median_net_points=float(np.median(values)),
                            p05_net_points=float(np.quantile(values, .05)), p95_net_points=float(np.quantile(values, .95)),
                            min_net_points=float(values.min()), max_net_points=float(values.max()),
                            std_between_seeds=float(values.std(ddof=1)), positive_seed_fraction=float((values > 0).mean()),
                            mean_stress_points=float(sums.stress.mean()), mean_count=float(sums.trades.mean()),
                            mean_two_contract_net_points=float(values.mean() * 2),
                            mean_two_contract_stress_points=float(sums.stress.mean() * 2)))
    columns = ["count", "closed", "cycle_count", "wins", "positive_points", "negative_points", "net_points",
               "stress_points", "net_atr", "stress_atr", "pair_wins", "pair_positive_points", "pair_negative_points",
               "net_points_per_initial_absolute_contract", "equivalent_two_contract_net_points", "equivalent_two_contract_stress_points"]
    columns += ["profit_points", "loss_points", "realized_dd_atr", "realized_dd_points", "net_atr_per_initial_absolute_contract", "stress_atr_per_initial_absolute_contract"]
    sessions = frame.groupby(["session", "symbol"])[columns].mean().reset_index()
    sessions["config"] = cfg.key
    sessions["mode"] = "片側コイントス100種平均"
    sessions["seed_count"] = len(SEEDS)
    sessions["gross_absolute_entry_quantity"] = 1
    sessions["win_rate"] = sessions["wins"] / sessions["closed"].replace(0, np.nan)
    return summary, sessions.to_dict("records")


def freeze(configs: list[HedgeConfig], data: dict) -> dict:
    """機能: 結果を見る前に範囲・乱数種・執行規則・実装ハッシュを固定する。

    引数: configs (list[HedgeConfig])、data (dict) は入力目録取得用。
    返り値: 計画記録 (dict)。既存記録と食い違うコードでの再実行は拒否する。
    """
    hashes = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in ("hedge.py", "hedge_search.py", "test_hedge.py")}
    plan = dict(凍結時刻=pd.Timestamp.now(tz="Asia/Tokyo"), 両建て条件数=len(configs), コイントス条件種数=len(configs) * len(SEEDS),
                条件=[dict(key=cfg.key, **asdict(cfg)) for cfg in configs], 乱数種=SEEDS, 代表種=REPRESENTATIVE_SEED,
                セッション=sorted({key[0] for key in data}), 入力セル数=len(data), 実装SHA256=hashes,
                新規="買売各１枚。過去に確定した参照価格±１ATRの買い上限と売り下限を共に満たす実在始値で同時約定近似。市場新規ではない。",
                返済="各脚の固定損切りと固定利確、または負け脚損切り後の残存１脚追跡。追跡は足確定後に更新して次の実在足から。両方接触は損切り優先。",
                再開="両脚返済後の待機時間が終わってから。期限30分前は新規停止。日中15:35、夜間05:50以後最初の実在足で返済。",
                費用="各脚往復２ティック、追加感度４ティック。両建て１組の基本費用４ティック、厳格費用８ティック。増額なし。",
                枚数比較="片側１枚の素の結果と２枚換算を併記する。総絶対枚数を揃えるもので、価格感応度・必要証拠金・破産確率まで同一にはしない。",
                選定="指定波合格で順位を付けない。全条件の全セッション結果と全乱数種を保存。コイントスは種平均と分布で比較し、良かった種を採用しない。",
                制約="１分足始値は両方向の実際の約定価格ではなく、両注文の原子的同時約定も保証しない。片脚のみ先に約定する実運用のずれや板数量はこの近似に含まれない。API取得無し。")
    path = OUT / "両建て_探索計画.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old["実装SHA256"] != hashes:
            raise RuntimeError("凍結計画の実装が変わっています。変更理由を別に記録してから扱ってください。")
        return old
    save_json(path, plan)
    return plan


def report(hedge_cells: pd.DataFrame, coin_distributions: pd.DataFrame) -> None:
    """機能: 収支が良い種を選ばず、両建て・片側の範囲と代表表を記録する。

    引数: hedge_cells/coin_distributions (DataFrame) は全条件の集計。
    返り値: なし (None)。日本語レポートを保存する。
    """
    totals = hedge_cells.groupby(["config", "symbol", "exit_mode"]).agg(
        positive_points=("positive_points", "sum"), negative_points=("negative_points", "sum"),
        net_points=("net_points", "sum"), stress_points=("stress_points", "sum"),
        pair_count=("cycle_count", "sum"), leg_count=("count", "sum"), wins=("wins", "sum"),
        min_session_net=("net_points", "min"), losing_sessions=("net_points", lambda x: int((x < 0).sum())),
    ).reset_index()
    totals.to_csv(OUT / "両建て_条件別集計.csv", index=False, encoding="utf-8-sig")
    joint = totals.pivot(index="config", columns="symbol", values="stress_points")
    both_positive = int(joint.gt(0).all(axis=1).sum())
    lines = ["# 両建てと注文単独の探索", "",
             "買い１枚・売り１枚を同時に開始する108条件と、同じ新規許容価格・出口・待機条件の片側コイントスを各100種で比較した。良かった乱数種を選ばず、全種の平均と分布を残している。", "",
             f"両銘柄の５セッション合計が往復４ティック／脚控除後に共に正となった両建て条件は {both_positive}/{len(joint)} 件。これは全条件探索後の保存データ上の結果で、将来の利益保証や未使用期間での検証ではない。", "",
             "|出口|銘柄|両建て合計収支の最小〜最大|４ティック控除の最小〜最大|コイントス平均収支の最小〜最大（１枚）|",
             "|---|---|---:|---:|---:|"]
    for (mode, symbol), group in totals.groupby(["exit_mode", "symbol"]):
        coin = coin_distributions[(coin_distributions.exit_mode == mode) & (coin_distributions.symbol == symbol)]
        lines.append(f'|{mode}|{symbol}|{group.net_points.min():+.2f}〜{group.net_points.max():+.2f}|{group.stress_points.min():+.2f}〜{group.stress_points.max():+.2f}|{coin.mean_net_points.min():+.2f}〜{coin.mean_net_points.max():+.2f}|')
    lines.extend(["", "各セッションの利益額合計・損失額合計・差引収支は `両建て_セル.csv` と `コイントス_セッション平均.csv` に全条件を保存した。`count` は脚の取引数、`cycle_count` は両建てなら組数である。`positive_points/negative_points` は費用控除後の各脚利益・損失の合計、`pair_positive_points/pair_negative_points` は組を合算してから利益組・損失組へ分けた値である。", "", "NK225は円幅、TOPIXはポイントで、両者をそのまま足さない。片側は１枚の結果に加えて２枚換算を保存し、両建ての総絶対枚数２へ揃えた。ただし両建て中の価格感応度は相殺されるため、枚数を揃えても全てのリスクや必要証拠金が等しくなるわけではない。", "", "新規は既知価格±１ATRの買い上限・売り下限を同時に満たす実在１分足始値による条件指値の約定近似である。実際の最良売買気配・同時約定・注文遅延・片脚のみ約定する危険は再現していない。各脚往復２ティックと４ティックで摩擦を比較した。元の生板はこの執行近似へ直接使っていない。", "", "固定出口は各脚の新規に対して、同じ返済方向の利確指値と損切り逆指値を付けるIFD-OCO相当である。両建て自体を一つのOCOと呼んでいない。勝ち脚追跡は小さい固定損切りで片脚が消えた後、残る脚だけを追跡する。足の高安が確定してから追跡価格を更新し、同じ足へ遡って返済しない。再開は両脚がなくなった後だけで、増額や倍掛けをしない。", "", "全脚明細は `両建てとコイントス_全取引.pkl.gz` の逐次pickleレコードに保存している。条件・種ごとの辞書をEOFまで順に読み込めば、全取引と全セルを再現できる。代表種は結果を見る前に固定した260925000で、勝った種ではない。100種は同じ５セッション上の乱数変動であり、100の独立した市場期間ではない。", ""])
    (OUT / "両建て検証.md").write_text("\n".join(lines), encoding="utf-8")


def run() -> None:
    """機能: 計画を固定して全条件・全種を実行し、各セルと全脚を保存する。

    引数: なし。返り値: なし (None)。原本・v4・現在APIには変更や取得を行わない。
    """
    from data import load_data_v5
    data = load_data_v5()
    configs = configurations()
    freeze(configs, data)
    hedge_rows, coin_summaries, session_means, representative = [], [], [], []
    began = time.monotonic()
    with gzip.open(OUT / "両建てとコイントス_全取引.pkl.gz", "wb", compresslevel=3) as ledger, gzip.open(OUT / "コイントス_セル.csv.gz", "wt", encoding="utf-8-sig", newline="", compresslevel=3) as cells_file:
        writer = None
        for number, cfg in enumerate(configs, 1):
            base_trades, base_cells = [], []
            for key, item in data.items():
                trades, cell = simulate(item, cfg)
                cell.update(asdict(cfg))
                base_trades.extend(trades)
                base_cells.append(cell)
            hedge_rows.extend(base_cells)
            pickle.dump(dict(config=asdict(cfg), seed=None, trades=base_trades, cells=base_cells), ledger, protocol=5)
            seed_rows = []
            for seed in SEEDS:
                seed_trades, seed_cells = [], []
                for key, item in data.items():
                    trades, cell = simulate(item, cfg, seed=seed)
                    cell.update(asdict(cfg))
                    seed_trades.extend(trades)
                    seed_cells.append(cell)
                seed_rows.extend(seed_cells)
                if writer is None:
                    writer = csv.DictWriter(cells_file, fieldnames=list(seed_cells[0]))
                    writer.writeheader()
                writer.writerows(seed_cells)
                pickle.dump(dict(config=asdict(cfg), seed=seed, trades=seed_trades, cells=seed_cells), ledger, protocol=5)
                if seed == REPRESENTATIVE_SEED:
                    representative.extend(seed_cells)
            distribution, means = seed_summary(seed_rows, cfg)
            coin_summaries.extend(distribution)
            session_means.extend(means)
            if number % 6 == 0:
                pd.DataFrame(hedge_rows).to_csv(OUT / "両建て_セル.csv", index=False, encoding="utf-8-sig")
                pd.DataFrame(coin_summaries).to_csv(OUT / "コイントス_条件別分布.csv", index=False, encoding="utf-8-sig")
                print(json.dumps(dict(完了条件=number, 全条件=len(configs), 秒=round(time.monotonic() - began)), ensure_ascii=False), flush=True)
    pd.DataFrame(session_means).to_csv(OUT / "コイントス_セッション平均.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(representative).to_csv(OUT / "コイントス_事前固定代表種.csv", index=False, encoding="utf-8-sig")
    hedge_frame, coin_frame = pd.DataFrame(hedge_rows), pd.DataFrame(coin_summaries)
    report(hedge_frame, coin_frame)
    save_json(OUT / "両建て_実行記録.json", dict(完了時刻=pd.Timestamp.now(tz="Asia/Tokyo"), 所要秒=time.monotonic() - began,
              両建てセル数=len(hedge_rows), コイントスセル数=len(configs) * len(SEEDS) * len(data), 全返済=bool(hedge_frame["count"].eq(hedge_frame.closed).all())))


if __name__ == "__main__":
    run()
