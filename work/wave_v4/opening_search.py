"""全セッションに共通の初動待ちと再入待機を追加して検証する。"""

from dataclasses import asdict
import itertools
import json
import time

import pandas as pd

from engine import Config
from research import OUT, load_data, evaluate, summary, ranked, schedule_for, save_json


def main() -> None:
    """機能: 開始後30・45・60分の新規待機を、日付非依存の候補として比較する。

    引数: なし。返り値: なし (None)。現在の日中データを使わず、全保存期間で比較する。
    """
    data, cache = load_data(), {}
    candidates = [Config(family,param,entry,.5,trail,cooldown,trail_basis=basis,warmup=warmup)
        for family,param,entry,trail,cooldown,basis,warmup in itertools.product((1,3,4,7,9,10,14,18,23),(.75,1.,1.25),
            ("pullback","stop","trail"),(1.5,2.5,4.),(30,60),("entry","current"),(30,45,60))]
    save_json(OUT/"初動待ち探索計画.json",dict(開始=pd.Timestamp.now(tz="Asia/Tokyo"),条件数=len(candidates),
        理由="セッション開始直後の大きなATRと不安定な方向を待つ一般的仮説。指定波時刻への一致条件は使用しない。",条件=[asdict(c) for c in candidates]))
    base = pd.read_csv(OUT/"最終全条件比較.csv")
    base["warmup"] = 14
    base["config"] = base.config.astype(str)+"_14"
    rows = base.to_dict("records")
    symbol_rows = []
    started=time.monotonic()
    for i,cfg in enumerate(candidates,1):
        key=cfg.family,cfg.param
        if key not in cache:
            cache[key]=schedule_for(data,cfg)
        trades,targets,cells=evaluate(data,cfg,cache[key])
        result=summary(cfg,trades,targets,cells)
        rows.append(result)
        for symbol in ("NK225","TOPIX"):
            ts=[t for t in trades if t["symbol"]==symbol]
            labels=[t for t in targets if t["symbol"]==symbol]
            ss=[t for t in cells if t["symbol"]==symbol]
            symbol_rows.append(dict(**asdict(cfg),config=cfg.key,symbol=symbol,
                target_pass=sum(t["passed"] for t in labels),coverage_pass=sum(t["coverage_pass"] for t in labels),
                frequency_ok=all(1<=t["count"]<=6 for t in ss),count=len(ts),max_count=max(t["count"] for t in ss),
                net_points=sum(t["net_points"] for t in ts),stress_points=sum(t["stress_points"] for t in ts),
                max_opposite=max(t["opposite_coverage"] for t in labels),min_coverage=min(t["correct_coverage"] for t in labels),
                min_capture=min(t["capture_ratio"] for t in labels)))
        if i%250==0:
            print(json.dumps(dict(完了=i,全条件=len(candidates),秒=round(time.monotonic()-started),最大合格=max(r["target_pass"] for r in rows)),ensure_ascii=False),flush=True)
    table=ranked(rows)
    table.to_csv(OUT/"拡張全条件比較.csv",index=False,encoding="utf-8-sig")
    table.groupby(["family","reverse"],sort=False).head(1).to_csv(OUT/"拡張系統代表比較.csv",index=False,encoding="utf-8-sig")
    st=pd.DataFrame(symbol_rows)
    st["stress_positive"]=st.stress_points>0
    st=st.sort_values(["target_pass","frequency_ok","stress_positive","max_opposite","min_coverage","min_capture","config"],ascending=[False,False,False,True,False,False,True])
    st.to_csv(OUT/"初動待ち銘柄別比較.csv",index=False,encoding="utf-8-sig")
    for symbol in ("NK225","TOPIX"):
        row=st[st.symbol.eq(symbol)].iloc[0].to_dict()
        cfg=Config(**{field:row[field] for field in Config.__dataclass_fields__})
        trades,targets,cells=evaluate(data,cfg)
        save_json(OUT/f"初動候補_{symbol}.json",dict(config=asdict(cfg),summary=row,
            trades=[t for t in trades if t["symbol"]==symbol],targets=[t for t in targets if t["symbol"]==symbol],cells=[t for t in cells if t["symbol"]==symbol]))
    print(st.groupby("symbol").head(2).to_json(orient="records",force_ascii=False),flush=True)


if __name__=="__main__":
    main()
