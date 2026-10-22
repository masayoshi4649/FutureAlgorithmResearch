"""既存の通常影待機対照を再集計し、10月22日の改修判断へ位置付ける。"""

import gzip
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / "work/wave_v67/observed"


def summarize(rows: list[dict], symbol: str, kind: str) -> dict:
    """
    機能: 保存済みの会計を商品・昼夜別に集計する。
    引数: rows(list[dict])は既存会計、symbol(str)は銘柄、kind(str)はDay又はall。
    返り値: dictは場数・収支・赤字の深さ。売買器は実行しない。
    """
    selected = [row for row in rows if row["symbol"] == symbol
                and (kind == "all" or row["session"].endswith("_Day"))]
    losses = [-row["net"] for row in selected if row["net"] < 0]
    return dict(symbol=symbol, kind=kind, sessions=len(selected),
        net=round(sum(row["net"] for row in selected), 6),
        gross=round(sum(row["gross"] for row in selected), 6),
        losing_sessions=len(losses), average_loss=statistics.mean(losses),
        maximum_loss=max(losses), campaigns=sum(row["campaigns"] for row in selected),
        first_session=min(row["session"] for row in selected),
        last_session=max(row["session"] for row in selected))


def main() -> None:
    """
    機能: 旧E01の通常影維持・解除対照を読み、現行T06との違いを明記して記録する。
    引数: なし。
    返り値: None。再計算するのは既存結果の集計だけで、金融再生・設定変更はしない。
    """
    result = dict(financial_replays=0, algorithm_changed=False, comparisons={}, evidence=[])
    for name in ("E01", "R10", "R01", "R11"):
        path = OLD / (name + ".json.gz")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            data = json.load(stream)
        result["comparisons"][name] = dict(variant=data["variant"], model=data["model"],
            statistics=[summarize(data["rows"], symbol, kind)
                        for symbol in ("TOPIX", "NK225") for kind in ("all", "Day")])
        result["evidence"].append(dict(path=path.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    result["limitations"] = [
        "00064の旧28場・ラージ観測価格モデル・提示立会手数料込み。現行T06の次正常気配モデルとは異なる。",
        "R10はE01、R11はEMA確認R01に対し、出口側の終了を起点に5分後から準備する方式。利確後だけの変更ではない。",
        "現在T06で利確後だけ1回再参加し、新しい二市場支持を要求する限定改修の成績は未測定。",
        "旧成績を引用した比較であり、新しい有効性の証拠に数えない。"]
    with (HERE / "再入場の既存対照.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    report = ROOT / "アルゴリズム調査/00135_十月二十二日の実約定と午後待機の確認/README.md"
    text = report.read_text(encoding="utf-8")
    heading = "## この待機を修正するべきか"
    assert heading not in text
    section = """

## この待機を修正するべきか

**現行運用では維持し、利確後に限定した再参加を改修候補とする。待機の一律解除は勧めない。** 「波の終了」は市場の終点を予知する判定ではなく、旧手法の仮想建玉が終わるまで次の準備を抑える規則である。その幅が最適だと証明されたわけでもない。

最も近い旧対照は、二市場EMA確認を維持したR01と、出口側の終了から5分後に再準備するR11。00064の保存結果から日中14場だけを再集計すると以下のとおり。初回TOPIXミニ5枚・日経マイクロ10枚、片方向上限10枚・20枚、手数料後。

| 商品 | 待機維持R01：収支／赤字場 | 待機短縮R11：収支／赤字場 | 最大赤字の変化 |
| --- | ---: | ---: | ---: |
| TOPIX | ＋477,226円／3場 | ＋327,692円／6場 | 48,589→76,842円 |
| 日経 | ＋143,800円／5場 | ＋116,640円／7場 | 27,100→47,320円 |

全28場でもR01→R11はTOPIX＋615,981→−12,045円、日経＋235,140→＋58,780円。通常影待機だけを外せば改善する、という結果ではなかった。旧観測価格モデルであり、現行T06の検証結果には置き換えない。利確後だけに限定した変更でもない。

現在の主担当に近い00129でも、二市場逆行撤退後の1回再参加はTOPIX DV07→DV08で22日中収支＋522,633→＋466,797円、最大赤字79,172→107,090円。日経DV05→DV06も＋260,800→＋257,860円、最大赤字25,100→36,320円だった。これは逆行撤退後の対照であり、利確後の再参加を直接否定するものではない。

待機を短くする利点は、10月22日のように利確後も続く方向へ再び参加できること。欠点は、往復や転換で古い方向判断を使い続け、得た利益を再参加の損切りで返しやすくなること。手数料だけでなく建て直す価格と後続の損切りも変わる。

次に比較するなら、**損切り後は従来の待機を維持し、利確後だけ、新しい押し戻りと二市場の再進行を確認して最大1回再参加する**限定改修が候補。具体的な閾値は未固定、改善効果は未検証。追加取引の合計利益だけでなく、黒字場を赤字へ変えた件数、赤字の平均・最大、大勝ち除外後収支を現行と比較して採否を決める。今回、稼働アプリを変更していない。

根拠：[00064の結果と約定模型](../00064_E01への回帰と知見を用いた改修/検証結果.md)、[今回の保存会計再集計](../../work/livecompare135_20261022/再入場の既存対照.json)、[00129の持続確認と再参加](../00129_チャートと板からの失敗機構再検証/日中の持続確認で改善した部分と残る負け.md)。
"""
    report.write_text(text + section, encoding="utf-8", newline="\n")
    # ----------------------------------------
    # 通常影待機の既存項目へ、過去実測の適用範囲と今回の未測定範囲を追記する。
    knowledge = ROOT / "アルゴリズム調査/共通/知見台帳/売買の工夫.md"
    text = knowledge.read_text(encoding="utf-8")
    start = text.index('<a id="00126_実玉早返済で通常影の待機を早めない"></a>')
    end = text.index('\n<a id=', start+5)
    note = """
**解除の既存対照と適用限界：** [00064_E01への回帰と知見を用いた改修](../../00064_E01への回帰と知見を用いた改修/検証結果.md)の保存観測値版を、[00135_十月二十二日の実約定と午後待機の確認](../../00135_十月二十二日の実約定と午後待機の確認/README.md)で再集計（金融再生0）。二市場EMA確認R01→出口側の終了後5分へ短縮するR11は、旧日中14場でTOPIX収支＋477,226→＋327,692円・赤字3→6場、日経＋143,800→＋116,640円・赤字5→7場。最大赤字も48,589→76,842円／27,100→47,320円へ増えた。これは通常影待機が一律に不要ではない証拠であり、現行T06の次正常気配会計での比較や、利確後だけの限定再参加の結果ではない。待機幅が最適との証明でもない。現在T06の利確後限定・新しい二市場支持による再参加は未測定。根拠：[旧四条件の全場・日中再集計](../../../work/livecompare135_20261022/再入場の既存対照.json)。

"""
    assert note.strip() not in text
    knowledge.write_text(text[:end]+note+text[end:], encoding="utf-8", newline="\n")
    print("旧対照の再集計と改修判断を00135・共通知見へ追記。金融再生0。")


if __name__ == "__main__":
    main()
