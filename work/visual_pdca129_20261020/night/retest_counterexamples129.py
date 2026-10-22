"""新入口で失った旧勝ちと、早期停止案に反する勝ちを描画・記録する。"""

from datetime import datetime
import json
import pickle
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
from render_retest129 import HERE, TASK, ROOT, OLD, IMAGES, draw, build
from render_night129 import read, stamp, candle, ohlc, JST


def missed_chart(packet: dict, inputs: dict, case: dict, path: object) -> dict:
    """
    機能: 旧勝ちの保有区間と、新手法が待っていた固定線を一図にする。
    引数: packet/inputs/case(dict)、path(Path)は原入力・観測価格・旧勝ち・保存先。
    返り値: dictは0.75R到達後の戻り有無。売買を再生しない。
    """
    scene, symbol = case["session"], case["symbol"]
    rd = inputs[scene, symbol]
    raw = packet["inputs"][scene, symbol]
    ts, start = rd["time_s"], rd["start"]
    side, stage, boundary, width, armrow = case["prepared_state"][:5]
    assert int(side) == case["side"]
    armrow = int(armrow)
    entrytime = datetime.fromisoformat(case["entry_time"]).timestamp()
    exittime = datetime.fromisoformat(case["exit_time"]).timestamp()
    left, right = max(start, entrytime-900.), min(rd["limit"], exittime+300.)
    ids = np.flatnonzero((ts >= left) & (ts <= right))
    q = packet["quotes"][scene, symbol]
    good = q["quote_valid"][ids] & (q["bid"][ids] > 0.) & (q["ask"][ids] > q["bid"][ids])
    mid = np.where(good, (q["bid"][ids]+q["ask"][ids])*.5, np.nan)
    fig, ax = plt.subplots(figsize=(15, 6))
    candle(ax, ohlc(raw), start, left, right)
    ax.plot((ts[ids]-start)/60., mid, color="#eeeeee", linewidth=.8, label="正常気配中値")
    xx = [(left-start)/60., (right-start)/60.]
    for value, color, label in ((boundary,"#ffca6b","新手法の固定突破線"),
                               (boundary+side*.75*width,"#c59bff","先行進行0.75R"),
                               (boundary+side*.25*width,"#83baff","必要な戻り0.25R")):
        ax.hlines(value, *xx, color=color, linestyle="--", label=label)
    ax.plot([(entrytime-start)/60., (exittime-start)/60.], [case["entry"],case["exit"]], color="#55e3ca")
    ax.scatter((entrytime-start)/60., case["entry"], marker="^" if side>0 else "v", s=65, color="#55e3ca")
    ax.scatter((exittime-start)/60., case["exit"], marker="x", s=55, color="#55e3ca")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=.3)
    ax.set_xlim(*xx)
    ax.xaxis.set_major_locator(MultipleLocator(5))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: datetime.fromtimestamp(start+60*v,JST).strftime("%H:%M")))
    ax.set_title(f"{scene} {symbol}　{case['new_method']}では同方向取引なし\n旧{case['baseline']} {case['entry_time'][11:19]}→{case['exit_time'][11:19]} {case['net']:+,.0f}円")
    ax.set_ylabel("ラージ価格")
    fig.text(.01,.01,"旧親の保存売買。線は旧判断時点に新入口が固定していた境界。旧利益の欠落額は、新旧運転の差額ではない。",fontsize=9)
    fig.tight_layout(rect=(0,.04,1,1))
    fig.savefig(path,dpi=140)
    plt.close(fig)
    prices = rd["last"]
    subset = np.arange(armrow, np.searchsorted(ts,exittime,side="right"))
    reach = subset[side*(prices[subset]-boundary) >= .75*width]
    reached = int(reach[0]) if len(reach) else -1
    after = subset[subset > reached] if reached >= 0 else np.array([],dtype=int)
    returned = after[side*(prices[after]-boundary) <= .25*width]
    return dict(**case, first_reach_time=stamp(ts[reached]) if reached>=0 else None,
                returned_before_old_exit=bool(len(returned)),
                return_first_time=stamp(ts[int(returned[0])]) if len(returned) else None,
                file=path.relative_to(ROOT).as_posix())


def main() -> None:
    """
    機能: 指定された旧勝ち三例と極値破綻後の勝ち二例を保存する。
    引数: なし。
    返り値: None。入口判断前の分類と事後描画を区別して記録する。
    """
    data = read(HERE/"再試験入口の全親と固定線診断.json")
    refs = {r["session"]:r for r in read(OLD/"入力準備.json")["packets"]}
    targets = [("NV15","TOPIX","2026-10-02_Night","NV02"),
               ("NV17","NK225","2026-10-01_Night","N36"),
               ("NV17","TOPIX","2026-10-15_Night","NV02")]
    result = []
    for method,symbol,scene,base in targets:
        case = max([r for r in data["lost_old_winners"] if r["new_method"]==method and
                    r["symbol"]==symbol and r["session"]==scene and r["baseline"]==base],key=lambda r:r["net"])
        packet = pickle.loads((ROOT/refs[scene]["path"]).read_bytes())
        prepared = build(packet,"last" if method=="NV15" else "mid")
        path = IMAGES/f"{scene}_{symbol}_{method}_失った旧勝ち.png"
        result.append(missed_chart(packet,prepared[0],case,path))
    for symbol,scene,number in (("TOPIX","2026-10-16_Night",3),("NK225","2026-09-29_Night",3)):
        row = next(r for r in data["rows"] if r["method"]=="NV17" and r["symbol"]==symbol and
                   r["session"]==scene and r["number"]==number)
        packet = pickle.loads((ROOT/refs[scene]["path"]).read_bytes())
        prepared = build(packet,"mid")
        for cut in (False,True):
            path = IMAGES/f"{scene}_{symbol}_NV17_{number:02d}_極値破綻の勝ち反例{'入口まで' if cut else ''}.png"
            draw(packet,prepared,row,path,cut)
    path = HERE/"再試験が失った直進勝ちと反例.json"
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
