"""夜間の画像確認結果を、短い説明と根拠データへまとめる。"""

import json
from pathlib import Path
import pickle

import matplotlib.pyplot as plt
import numpy as np

from render_night129 import HERE, ROOT, PUBLIC, IMAGES, read


def tape_image(row: dict, refs: dict) -> Path:
    """
    機能: 約定Lastが同値の間の気配再評価を、経過秒ではなく原行順で描画する。
    引数: row(dict)は保存親、refs(dict)は保存入力参照。
    返り値: Pathは生成した画像位置。新たな売買は作らない。
    """
    scene, symbol = row["session"], row["symbol"]
    packet = pickle.loads((ROOT/refs[scene]["path"]).read_bytes())
    ready, q = (packet[k][scene, symbol] for k in ("inputs", "quotes"))
    end = row["exit_row"]
    begin = int(np.searchsorted(ready["time_s"], ready["time_s"][end], side="left"))
    stop = min(len(ready["last"]), int(np.searchsorted(ready["time_s"], ready["time_s"][end], side="right")))
    ids = np.arange(begin, stop)
    seq = ready["seq"][ids]
    fig, ax = plt.subplots(figsize=(15, 6))
    ax.plot(seq, ready["last"][ids], color="#ffb45a", linewidth=2., label="約定Last")
    ax.step(seq, q["bid"][ids], where="post", color="#53d8b1", linewidth=1., label="買気配")
    ax.step(seq, q["ask"][ids], where="post", color="#ed7387", linewidth=1., label="売気配（売建玉の清算側）")
    ax.step(seq, (q["bid"][ids]+q["ask"][ids])/2., where="post", color="#e1e5ed",
            linewidth=1.1, alpha=.8, label="正常気配の中心")
    ax.axhline(row["entry"]+row["width"], color="#f0ca57", linestyle="--", label="売建玉の初期停止線")
    ax.scatter(ready["seq"][end], row["exit"], marker="x", color="#ffffff", s=100, zorder=8)
    ax.annotate(f"保存返済 {row['exit']:,.0f}\n収支 {row['net']:+,.0f}円",
                (ready["seq"][end], row["exit"]), xytext=(-120,-55), textcoords="offset points",
                arrowprops={"arrowstyle":"->","color":"#ffffff"}, fontsize=11)
    ax.set_title("2026-10-08 ナイト・N27 日経：翌02:07:25と記録された原行列\n約定値が68,200のまま、実際の清算側気配だけが上昇", fontsize=14)
    ax.set_xlabel("原資料の行順（価格時計が同じでも別の更新。実経過時間ではない）")
    ax.set_ylabel("日経ラージ価格")
    ax.legend(loc="upper left", ncol=2)
    ax.grid(alpha=.4)
    fig.text(.02,.015,"保存入力の正常気配のみ。実受信時刻と板の厳密な経過秒は復元できない。注文・損益の再運転なし。",fontsize=10)
    fig.tight_layout(rect=(0,.05,1,1))
    path=IMAGES/"2026-10-08_Night_NK225_05_Last固定中の板再評価.png"
    fig.savefig(path,dpi=160)
    plt.close(fig)
    return path


def main() -> None:
    """
    機能: 最悪三場ずつの機構・反証・図へのリンクを公開用資料にまとめる。
    引数: なし。
    返り値: None。日本語ＭＤと機械可読ＪＳＯＮを書き出す。
    """
    source=read(HERE/"夜間図の索引と全入口の当時特徴.json")
    classified=read(HERE/"利確後の同方向再参加と一時間文脈の全親分類.json")
    manifest=read(ROOT/"work/daynight128_20261020/入力準備.json")
    refs={r["session"]:r for r in manifest["packets"]}
    notes={
        ("NK225","2026-09-29_Night"):(
            "23:48の買いは最高順行0ptで53秒後に停止。00:08の売りも40pt順行に留まり、00:15に100pt逆行で停止した。",
            "00:08は両市場の短期・20分下落が揃う一方、日経は60分前より240pt上だった。短期の下落と一時間の上昇が競合していた。",
            "60分方向との競合を条件として比較する。23:48の再買いは前親最高順行からさらに200pt上へ更新しており『帯だけが移動した再入場』説は当たらない。"),
        ("NK225","2026-10-02_Night"):(
            "23:55の売り69,910→23:57の70,000で−9,220円。02:26の売り69,630→02:33の69,710で−8,220円。",
            "23:55は直近下落に対して60分差は120pt上昇。02:26は両市場の売り方向が揃っており、同じ60分条件では除けない。",
            "23:55後は一度戻ってから再び大きく下落した。方向判断の全否定ではなく、短い停止幅で耐えられない戻しを含む。停止拡張の採用には全親の大損拡大との比較が必要。"),
        ("NK225","2026-10-07_Night"):(
            "23:33の買いは2分4秒で−8,220円。00:50の買いは60ptまで順行したが、約76.47ptの保護開始に届かず、02:00に−8,220円。",
            "最初の買いの入口では両市場の上昇が一致。次の買いも60分差が順方向であり、60分一致だけでは救えない。後者は01時台に両市場の上昇が失速する様子が見える。",
            "1R未達の利益をどう守るかは未解決。後者は返済直後に再上昇しており、戻りを全て早期退出する条件も勝ちを減らしうる。"),
        ("TOPIX","2026-09-22_Night"):(
            "00:37の売り4,127.5→01:07の4,131.5で−20,418円。最大順行2ptは保護開始の約3.92ptに不足した。",
            "入口で両市場の短期下落は一致。00:44頃から短期変化は戻るが、20分差には過去の下落が残った。",
            "『過去20分が下落』と『今も下落が進む』を分離する必要がある。ただし短期反対だけで降りる案は00128で勝ちも失っており、そのまま再採用しない。"),
        ("TOPIX","2026-10-06_Night"):(
            "23:07の買い4,208.5→23:16の4,204.5で−20,418円。その後23:28の売りも−20,418円となった。",
            "買いの入口までなら両市場は上昇しており、最高順行はわずか0.5pt。23:28の反対売りは60分上昇との競合が当時見えた。",
            "最初の上昇終端は後からなら分かるが、その場で確定できない。往復後半の反対方向への参加を60分文脈で比較する余地がある。"),
        ("TOPIX","2026-10-05_Night"):(
            "00:13の売り4,168.5→00:37の4,172.5で−20,418円。2.5pt順行したが保護開始の約3.51ptに届かなかった。",
            "入口では両市場の下落が一致。00:18以降に短い戻しが繰り返され、00:31頃には両市場の120秒差が明瞭に上向いた。",
            "入口の除外より、順行停止後の気配で継続根拠を更新する候補。ただし似た停滞後に大きく伸びる勝ち対照があり、停滞だけで全退出する根拠にはならない。"),
    }
    cases=[]
    text=["# 夜間：最悪三場ずつをチャートで確かめた結果","",
          "損失は一種類ではありません。**短期と長い流れの競合、順行が保護開始に届かない反転、約定値と気配のずれ**を分けて検証します。画像だけから後の反転を予知できたとは扱いません。","",
          "対象は N36、比較は N27。日経マイクロ10枚・TOPIXミニ5枚、手数料後。下の時刻は日本時間で、0時以降はセッション名の翌日です。","",
          "|商品・セッション|場全体の収支|具体的な失敗と、当時確認できたもの|図|",
          "|---|---:|---|---|"]
    for symbol in ("NK225","TOPIX"):
        for scene_result in source["selection"][symbol]:
            scene=scene_result["session"]
            detail,observable,hypothesis=notes[symbol,scene]
            targets=[r for r in source["targets"] if r["method"]=="N36" and
                     r["symbol"]==symbol and r["session"]==scene and r["net"]<0]
            links=[]
            for r in targets:
                prefix=f"画像/夜間/{scene}_{symbol}_{r['number']:02d}_負け"
                links.append(f"[{r['entry_time'][11:16]}入口まで]({prefix}_入口まで.png)／[その後]({prefix}_局所.png)")
            full=f"画像/夜間/{scene}_全場比較.png"
            text.append(f"|{symbol} {scene[:10]}|{scene_result['net']:+,.0f}円|{detail}<br>{observable}|[全場]({full})<br>{'<br>'.join(links)}|")
            cases.append(dict(symbol=symbol,session=scene,session_net=scene_result["net"],
                observed_failure=detail,known_at_the_time=observable,revision_hypothesis=hypothesis,
                full_image=full,trades=targets))
    special=next(r for r in source["targets"] if r.get("special")=="板再評価")
    tape=tape_image(special,refs).relative_to(PUBLIC).as_posix()
    text.extend(["","## 気配を見る必要がある具体例","",
        f"10/8ナイトの N27 日経売りは、翌02:05:42の68,140から02:07:25の68,280へ返済し−14,220円。**Lastが68,200のままでも、売建玉を返す売気配は68,280まで上がった**。Lastの足だけでは停止線接触を読み取れません。[同じ価格時計内の板の変化]({tape})／[入口まで](画像/夜間/2026-10-08_Night_NK225_05_板再評価_入口まで.png)。",
        "",
        "方向・確定足・突破線も気配中心で統一する検証が必要です。ただし、この例では約定値も建値に逆行しており、Lastと気配の差だけが全損失の原因ではありません。",
        "",
        "## 勝ち反例を含めた切り分け","",
        "- **60分と逆向きの入口**：固定されたN36親のうち日経9件は3勝6敗・−40,980円、TOPIX8件は4勝4敗・−30,844円。比較候補になるが、[10/8の日経売り](画像/夜間/2026-10-08_Night_NK225_02_勝ち対照_局所.png)はこの条件でも＋2,780円。除外すれば全て改善するとは言えません。",
        "- **利確後20分以内の同方向再参加**：日経5件は2勝3敗・−22,100円、TOPIX3件は1勝2敗・−16,254円。全8件が前親の最高順行気配を実際に更新。『帯だけ移動して、更新していない同じ波に入り直した』説は棄却します。",
        "- **伸びる前の停滞**：[10/16のTOPIX売り](画像/夜間/2026-10-16_Night_TOPIX_03_勝ち対照_局所.png)は01:51に入り、初めの停滞を経て＋79,582円。停滞や短い反対変化だけで退出すると、こうした勝ちも削ります。[この入口まで](画像/夜間/2026-10-16_Night_TOPIX_03_勝ち対照_入口まで.png)。",
        "",
        "分類の金額は保存取引の内訳であり、除外後に運転し直した成績ではありません。次の比較は①Lastと実売買気配の観測統一、②60分との競合の単独制御です。手当たり次第の幅調整より先に、見ている価格と時間軸の矛盾を確かめます。",
        "",
        "## 図の読み方と限界","",
        "1分足は原Last、白線と灰色帯は正常気配中心とbid〜ask。水色はN36、紫はN27。黄色は準備時の固定突破線、緑は保護開始、桃色は停止線。下段は当時公開済みの二市場変化です。入口図はその原行で右側を切り、当分の足も未観測部分を使っていません。",
        "",
        "原資料は価格時刻と行順です。実受信時刻や同時刻内の厳密な経過秒は復元できません。ラージ気配からミニ／マイクロの約定を代理しています。画像生成・この分類での新金融再生は0回です。",
        "",
        "[数値と仮説のJSON](夜間チャート観察と仮説.json)"])
    result=dict(cases=cases,plate_repricing_example=special,plate_sequence_image=tape,
        classification=classified["groups"],
        counterexamples=[r for r in source["targets"] if "control_for" in r],
        hypotheses=[
            {"id":"観測価格統一","status":"要再運転","reason":"Last固定の間に清算側気配が停止線へ達する原行がある。"},
            {"id":"自己六十分方向の競合","status":"要再運転","reason":"両商品で該当親集合が赤字。ただし黒字親も含む。"},
            {"id":"最高順行未更新の波再消費","status":"棄却","reason":"利確後二十分以内の再参加8件とも正常気配中心の前最高順行を更新済み。"},
            {"id":"停滞だけで退出","status":"単独採用不可","reason":"10月16日TOPIXの黒字対照にも初期停滞がある。"}],
        financial_replays=0,
        note="保存親の分類。仮に除外した運転成績ではない。全場は既知資料であり未知期間検証ではない。",
        evidence_source=str((HERE/"夜間図の索引と全入口の当時特徴.json").relative_to(ROOT)))
    (PUBLIC/"夜間チャート観察と仮説.md").write_text("\n".join(text)+"\n",encoding="utf8")
    (PUBLIC/"夜間チャート観察と仮説.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    print(PUBLIC/"夜間チャート観察と仮説.md")
    print(tape)


if __name__=="__main__":
    main()
