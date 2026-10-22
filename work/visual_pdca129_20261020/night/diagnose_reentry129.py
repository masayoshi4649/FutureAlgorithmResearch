"""利確後の同方向再参加と一時間の文脈を、保存親取引を変えずに比較する。"""

import json
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(path: Path) -> dict:
    """
    機能: 日本語の保存資料を読む。
    引数: path(Path)は保存位置。
    返り値: dictは資料内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def summarize(rows: list[dict]) -> dict:
    """
    機能: 固定された保存親集合の勝敗と収支を集計する。
    引数: rows(list[dict])は取引を変えない診断対象。
    返り値: dictは件数、黒字・赤字数、利益・損失・収支。
    """
    return dict(count=len(rows), wins=sum(r["net"] > 0 for r in rows),
                losses=sum(r["net"] < 0 for r in rows),
                profit=sum(max(0., r["net"]) for r in rows),
                loss=sum(min(0., r["net"]) for r in rows), net=sum(r["net"] for r in rows))


def main() -> None:
    """
    機能: 全Ｎ３６親について過去の同方向利確と既知一時間変化を照合する。
    引数: なし。
    返り値: None。分類用ＪＳＯＮのみ作成し、注文・金融運転は変更しない。
    """
    source = read(HERE/"夜間図の索引と全入口の当時特徴.json")
    manifest = read(ROOT/"work/daynight128_20261020/入力準備.json")
    refs = {r["session"]: r for r in manifest["packets"]}
    out = []
    for scene in sorted({r["session"] for r in source["rows"]}):
        packet = pickle.loads((ROOT/refs[scene]["path"]).read_bytes())
        for symbol in ("NK225", "TOPIX"):
            ready, q = (packet[k][scene, symbol] for k in ("inputs", "quotes"))
            times, last = ready["time_s"], ready["last"]
            valid = q["quote_valid"] & (q["ask"] > q["bid"]) & (q["bid"] > 0.)
            mid = np.where(valid, (q["bid"]+q["ask"])/2., np.nan)
            rows = sorted([r for r in source["rows"] if r["method"]=="N36" and
                           r["session"]==scene and r["symbol"]==symbol], key=lambda r:r["entry_row"])
            for k, original in enumerate(rows):
                r = dict(original)
                side, d, width = r["side"], r["decision_row"], r["width"]
                known60 = max(0, int(np.searchsorted(times, times[d]-3600., side="right"))-1)
                r["sixty_mid_change_R"] = float(side*(mid[d]-mid[known60])/width)
                r["sixty_own_opposite"] = r["observable"]["sixty_change"] <= 0.
                r["sixty_mid_opposite"] = r["sixty_mid_change_R"] <= 0.
                p = next((prior for prior in reversed(rows[:k]) if prior["side"]==side), None)
                r["reentry"] = None
                r["profit_reentry20"] = r["near_prior_extreme"] = r["no_new_extension"] = False
                if p:
                    pe, px = p["entry_row"], p["exit_row"]
                    previous_peak = float(side*np.nanmax(side*mid[pe:px+1]))
                    elapsed = float(times[d]-times[px])
                    signed_distance = float(side*(mid[d]-previous_peak))
                    further_peak = float(np.nanmax(side*mid[px:d+1])-side*previous_peak)
                    r["reentry"] = dict(previous_number=p["number"], previous_net=p["net"],
                        previous_exit_time=p["exit_time"], elapsed_seconds=elapsed,
                        intervening_opposite_trades=k-rows.index(p)-1,
                        previous_best_mid=previous_peak,
                        previous_best_liquidation=p["entry"]+side*p["mfe"],
                        current_decision_mid=float(mid[d]), current_fill=r["entry"],
                        signed_distance_to_prior_peak=signed_distance,
                        distance_R=signed_distance/width,
                        known_extension_since_previous_exit=further_peak,
                        extension_R=further_peak/width)
                    r["profit_reentry20"] = p["net"] > 0 and elapsed <= 1200.
                    r["near_prior_extreme"] = r["profit_reentry20"] and signed_distance >= -ready["tick"]
                    r["no_new_extension"] = r["profit_reentry20"] and further_peak <= ready["tick"]
                out.append(r)
    # ----------------------------------------
    # 分類は事前指定の二十分と原呼値だけ。金額を見ながら閾値は探索しない。
    conditions = ("profit_reentry20", "near_prior_extreme", "no_new_extension",
                  "sixty_own_opposite", "sixty_mid_opposite")
    groups = {}
    for symbol in ("NK225", "TOPIX"):
        rows = [r for r in out if r["symbol"]==symbol]
        groups[symbol] = {"all": summarize(rows)}
        for key in conditions:
            yes, no = [r for r in rows if r[key]], [r for r in rows if not r[key]]
            groups[symbol][key] = dict(yes=summarize(yes), no=summarize(no),
                members=[dict(session=r["session"], number=r["number"], direction=r["direction"],
                              entry_time=r["entry_time"], exit_time=r["exit_time"], net=r["net"],
                              reentry=r["reentry"]) for r in yes])
    result = dict(financial_replays=0, rows=out, groups=groups,
        definition={
            "profit_reentry20": "同セッションの直前同方向親が手数料後黒字、終了後二十分以内。反対方向親を挟む件数も記録。",
            "near_prior_extreme": "上記のうち判断時正常気配中心が、前親保有中の最高順行気配中心から一ラージ呼値以上は逆行側に離れていない。",
            "no_new_extension": "上記のうち前親終了から判断までの正常気配中心が前親最高順行を一ラージ呼値超更新していない。",
            "sixty_own_opposite": "発注判断までの原Lastの六十分変化が新規方向と逆又はゼロ。",
            "sixty_mid_opposite": "同じ比較を正常気配中心で行う。原時計の六十分前以前行を利用。",
            "scope": "保存された親を分類した診断であり、対象を除いた戦略再運転の損益ではない。"},
        source="夜間図の索引と全入口の当時特徴.json")
    (HERE/"利確後の同方向再参加と一時間文脈の全親分類.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf8")
    print(json.dumps({s: {k: v if k=="all" else {"yes":v["yes"],"no":v["no"]} for k,v in a.items()}
                      for s,a in groups.items()}, ensure_ascii=False, indent=2))


if __name__=="__main__":
    main()
