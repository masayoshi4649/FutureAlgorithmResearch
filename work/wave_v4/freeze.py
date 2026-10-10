"""現在データを見る前に、共通候補・銘柄別対照・全系統代表を凍結する。"""

from dataclasses import asdict
import hashlib
import json

import pandas as pd

from engine import Config
from research import OUT, ROOT, SYMBOLS, load_data, evaluate, evaluate_by_symbol, save_json


def from_row(row: dict) -> Config:
    """機能: 比較表の行を型付き設定へ変換する。

    引数: row (dict)。返り値: 条件 (Config)。
    """
    defaults=asdict(Config(1))
    return Config(**{field:row.get(field,value) for field,value in defaults.items()})


def main() -> None:
    """機能: 未取得の日中を見る前に選択内容と入力・コードハッシュを保存する。

    引数: なし。返り値: なし (None)。既存固定記録があれば更新を拒否する。
    """
    path=OUT/"固定設定.json"
    if path.exists():
        raise RuntimeError("凍結済みの条件は更新しません")
    table=pd.read_csv(OUT/"拡張全条件比較.csv")
    eligible=table[table.target_pass.eq(6)&table.frequency_ok&table.both_stress_positive]
    if eligible.empty:
        raise RuntimeError("共通条件を満たす候補がありません")
    cfg=from_row(eligible.iloc[0].to_dict())
    selected={symbol:asdict(cfg) for symbol in SYMBOLS}
    alternative={"NK225":asdict(Config(3,.75,"pullback",.5,4,30,trail_basis="current")),
                 "TOPIX":asdict(Config(10,.75,"stop",.5,2.5,30,trail_basis="entry",warmup=45))}
    representatives=table.groupby(["family","reverse"],sort=False).head(1)
    candidates={}
    for row in pd.concat([representatives,table.head(12)]).to_dict("records"):
        candidate=from_row(row)
        candidates[candidate.key]=dict(config=asdict(candidate),name=row["name"])
    for value in alternative.values():
        candidate=Config(**value)
        candidates[candidate.key]=dict(config=value,name="事前固定の銘柄別対照")
    data=load_data()
    trades,targets,cells=evaluate_by_symbol(data,selected)
    assert len(targets)==6 and all(t["passed"] for t in targets)
    assert all(1<=c["count"]<=6 for c in cells)
    save_json(OUT/"採用_開発結果.json",dict(symbol_configs=selected,trades=trades,targets=targets,cells=cells))
    ats,atargets,acells=evaluate_by_symbol(data,alternative)
    save_json(OUT/"銘柄別対照_開発結果.json",dict(symbol_configs=alternative,trades=ats,targets=atargets,cells=acells))
    core=("engine.py","signals.py","targets.py","research.py","current_check.py","../wave_v2/book_features.py")
    inputs=[*ROOT.glob("candle_1min/*/*.csv"),*ROOT.glob("candle_5min/*/*.csv"),
            *OUT.parent.joinpath("wave_v2").glob("板特徴_*.csv"),*OUT.parent.joinpath("wave_v3_check").glob("板特徴_*.csv")]
    fixed=dict(fixed_at=pd.Timestamp.now(tz="Asia/Tokyo").isoformat(),config=asdict(cfg),symbol_configs=selected,
               alternative_symbol_configs=alternative,candidates=list(candidates.values()),development_conditions=len(table),
               selection="指定6波の新規検知、全セル1〜6回、両銘柄4ティック控除後正を必須とし、事前順位の先頭。",
               development_note="指定例を含む保存4セッションで探索。現在2026-09-23Dayはまだ取得していない。",
               code_sha256={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in core},
               input_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
               table_sha256=hashlib.sha256((OUT/"拡張全条件比較.csv").read_bytes()).hexdigest())
    save_json(path,fixed)
    print(json.dumps(dict(凍結時刻=fixed["fixed_at"],設定=asdict(cfg),候補群数=len(candidates),取引数=len(trades),指定波=targets,セル=cells),ensure_ascii=False,default=str))


if __name__=="__main__":
    main()
