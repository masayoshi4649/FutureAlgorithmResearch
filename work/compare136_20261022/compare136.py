"""同じ45場の保存結果を、数量差に依存しにくい比率で銘柄間比較する。"""

import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "アルゴリズム調査"
NAME = "00136_同期間でのTOPIXと日経の安定性比較"
SOURCE = RESEARCH / "00132_現行アルゴリズムの追加セッション検証/セッション損益.json"


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 同一商品・時間区分の既存会計から損益比と赤字頻度を集計する。
    引数: rows(list[dict])は保存済みのセッション会計。
    返り値: dictは比較指標。全て手数料後で、新たな金融再生は行わない。
    """
    wins = [row["net"] for row in rows if row["net"] > 0]
    losses = [-row["net"] for row in rows if row["net"] < 0]
    assert len(wins)+len(losses) == len(rows)
    assert all(row["entries"] > 0 for row in rows)
    average_win, average_loss = statistics.mean(wins), statistics.mean(losses)
    profit, loss = sum(row["profit"] for row in rows), sum(row["loss"] for row in rows)
    net = sum(row["net"] for row in rows)
    assert profit-loss == net
    return dict(sessions=len(rows), winning_sessions=len(wins), losing_sessions=len(losses),
        winning_fraction=len(wins)/len(rows), parent_profit=profit, parent_loss=loss,
        parent_profit_factor=profit/loss, net=net,
        average_winning_session=average_win, average_losing_session=average_loss,
        median_losing_session=statistics.median(losses), maximum_losing_session=max(losses),
        average_loss_to_average_win=average_loss/average_win,
        maximum_loss_to_average_win=max(losses)/average_win,
        without_top3_net=net-sum(sorted(wins, reverse=True)[:3]))


def main() -> None:
    """
    機能: 同じ45場の指標を公開し、勝つ頻度と負けの深さの区別を共通知見へ記録する。
    引数: なし。00132の保存結果だけを使用する。
    返り値: None。元会計と稼働アプリを変更しない。
    """
    payload = SOURCE.read_bytes()
    document = json.loads(payload.decode("utf-8-sig"))
    assert document["passed"]
    rows = document["rows"]
    pairs = {symbol: {row["session"]: row for row in rows if row["symbol"] == symbol}
             for symbol in ("TOPIX", "NK225")}
    assert set(pairs["TOPIX"]) == set(pairs["NK225"]) and len(pairs["TOPIX"]) == 45
    result = {}
    for symbol in pairs:
        result[symbol] = {}
        for kind in ("all", "Day", "Night"):
            selected = [row for row in pairs[symbol].values() if kind == "all" or row["kind"] == kind]
            result[symbol][kind] = aggregate(selected)
    output = dict(passed=True, financial_replays=0, API=0, algorithm_changed=False,
        source=dict(path=SOURCE.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(payload).hexdigest()),
        sessions=sorted(pairs["TOPIX"]), summary=result,
        caveats=["00131で選定された現行構成の既知期間比較。市場そのものの難易度や統計的有意差の証明ではない。",
                 "TOPIXミニ上限10枚・日経マイクロ上限20枚。円額を直接順位付けせず、各商品内の損益比を使う。",
                 "日中は両商品T06だが主担当係数が異なり、夜間はTOPIX T04・日経U06で方式も異なる。",
                 "手数料は立会料金、ラージ次正常気配による代理約定。10月22日のTOPIX単独結果は混ぜない。"])
    folder = RESEARCH / NAME
    folder.mkdir(exist_ok=False)
    with (folder / "比較.json").open("x", encoding="utf-8") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    top, nk = result["TOPIX"], result["NK225"]
    lines = []
    for kind, label in (("all", "全45場"), ("Day", "日中23場"), ("Night", "夜間22場")):
        t, n = top[kind], nk[kind]
        lines.append(f"| {label} | {t['winning_sessions']}/{t['sessions']}（{t['winning_fraction']:.1%}） | {n['winning_sessions']}/{n['sessions']}（{n['winning_fraction']:.1%}） |")
    text = """# TOPIXと日経のどちらが扱いやすいか

最初にこのREADMEを読んでください。根拠数値は[比較.json](比較.json)、元の全場表は[00132](../00132_現行アルゴリズムの追加セッション検証/現行アルゴリズムの全セッション損益.html)です。

**現在の採用構成では、黒字になる場の多さはTOPIX、負けの深さと利益・損失の比率は日経が有利。損小利大を重視するなら、日経をやや優先する判断です。** 市場そのものが易しいと証明したものではありません。

同じ45セッション（2026-09-21デイ～10-21デイ）の保存会計を再集計しました。手数料込み、無取引なし。10月22日のTOPIXだけの結果は比較へ加えていません。

| 黒字セッション | TOPIX | 日経 |
| --- | ---: | ---: |
""" + "\n".join(lines) + f"""

| 全45場の比較指標 | TOPIX | 日経 |
| --- | ---: | ---: |
| 親取引の総利益÷総損失 | {top['all']['parent_profit_factor']:.2f}倍 | {nk['all']['parent_profit_factor']:.2f}倍 |
| 平均赤字1場÷平均黒字1場 | {top['all']['average_loss_to_average_win']:.2f}倍 | {nk['all']['average_loss_to_average_win']:.2f}倍 |
| 最大赤字1場÷平均黒字1場 | {top['all']['maximum_loss_to_average_win']:.2f}倍 | {nk['all']['maximum_loss_to_average_win']:.2f}倍 |

TOPIXの黒字回数の優位は主に夜間から来ています。ただし夜間TOPIXは平均赤字49,448円に対し平均黒字約23,440円で、平均負け1回が平均勝ち約2.11回分。日経夜間は約0.81回分です。勝つ頻度だけで易しいとは評価しません。

日中の黒字数は日経16/23場、TOPIX15/23場と差は1場です。大きな優劣を断定する差ではありません。両商品とも全体・日中・夜間それぞれで上位3黒字場を除いても合計黒字ですが、多くは手法選定に使った既知資料です。

TOPIXミニ片方向上限10枚、日経マイクロ上限20枚。数量・倍率が異なるため収益額そのものを順位付けしていません。日中はT06、夜間はTOPIX T04／日経U06で、主担当の係数・夜間の仕組みも異なります。今回の比較は商品と採用手法の組合せの評価です。約定はラージ気配代理、料金は従来の立会料金であり、実商品の板やJ-NET約定を再現した比較ではありません。

既存会計の再集計のみで、新しい金融再生・API取得・アプリの変更はありません。[再集計スクリプト](../../work/compare136_20261022/compare136.py)。
"""
    (folder / "README.md").write_text(text, encoding="utf-8", newline="\n")
    # ----------------------------------------
    # 数量の異なる商品を比較する際の法則として、勝率と損失規模を分けて記録する。
    knowledge = RESEARCH / "共通/知見台帳/売買の工夫.md"
    note = f"""

<a id="00136_勝つ頻度と負けの相対規模を分ける"></a>

## 商品間の扱いやすさは、黒字の頻度と平均黒字に対する損失規模を分ける

**出典：** [00136_同期間でのTOPIXと日経の安定性比較](../../{NAME}/README.md)。元会計は[00132_現行アルゴリズムの追加セッション検証](../../00132_現行アルゴリズムの追加セッション検証/README.md)。

**条件・実測：** 現行構成、立会手数料後、各45場。TOPIX34/45場黒字（75.6%）、日経31/45場（68.9%）。親取引の総利益÷総損失は1.623／1.886。各銘柄の平均赤字場÷平均黒字場は1.134／0.788、最大赤字場÷平均黒字場は2.197／1.871。TOPIXは黒字頻度、日経は損失相対規模に利点がある。日中23場は15対16黒字、夜間22場は19対15黒字。夜間TOPIXの平均赤字は平均黒字の2.11倍で、勝つ頻度だけでは深い負けを把握できない。

**使える範囲・限界：** 数量と倍率が違う二商品を、円額の大小だけで比較しない。親取引の利益損失比と、場全体の勝敗・平均損失を混同しない。これは採用手法と商品の組合せの既知標本比較で、市場固有の予測しやすさ・統計的優越を測ったものではない。10月22日のTOPIX単独結果は除外。保存会計の再集計で金融再生0、当該場の全返済までの会計を使用。
"""
    with knowledge.open("a", encoding="utf-8") as stream:
        stream.write(note)
    index = RESEARCH / "index.html"
    text = index.read_text(encoding="utf-8")
    marker = '<main id="work-list">'
    assert text.count(marker) == 1 and NAME not in text
    card = f'<article class="task latest"><div class="number">作業00136・同期間45場比較</div><h2>TOPIXと日経の安定性比較</h2><p>黒字頻度と、通常の利益に対する損失規模を分けて比較。</p><a class="button" href="{NAME}/README.md">比較結果</a></article>'
    index.write_text(text.replace(marker, marker+"\n<!--00136開始-->"+card+"<!--00136終了-->", 1), encoding="utf-8", newline="\n")
    listing = RESEARCH / "README.md"
    text = listing.read_text(encoding="utf-8")
    first, rest = text.split("\n", 1)
    listing.write_text(first+f"\n\n最新：[00136：TOPIXと日経の安定性比較]({NAME}/README.md)。同じ45場で黒字頻度・利益損失比・損失の相対規模を比較。\n"+rest, encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
