"""具体的な失敗と改修結果を、短い本文と全場表で公開する。"""

import argparse
import html
import json
from common129 import HERE, PREV, PUBLIC, ROOT, read, reference


def money(value):
    """
    機能: 円額を符号付き整数で表示する。
    引数: value(float)は円額。
    返り値: strは表示文字列。
    """
    return f"{int(round(value)):+,}"


def main():
    """
    機能: 保存集計から暗色HTMLを作り、全場・全条件の参照を残す。
    引数: --result/--day/--night(str)は集計位置と初期表示条件。
    返り値: None。金融核や現在APIは呼ばない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--day", default="DV07")
    parser.add_argument("--night", default="N36")
    args = parser.parse_args()
    result = read(HERE/args.result)
    rows = result["rows"]
    methods = []
    for method in sorted({r["method"] for r in rows}):
        r = next(r for r in rows if r["method"] == method)
        methods.append(dict(id=method, name=r.get("name", method), kind=r["kind"]))
    names = {r["id"]: r["name"] for r in methods}
    evidence = [
        ("日中：短い反発で勝ちを切る問題を改善",
         "9月28日の日経は、瞬間撤退では売りを17秒で切って−6,220円。"
         "60秒の持続確認により、その後の下落を保有して＋48,280円を残せた。"
         "ただし、1分続く逆行から回復した10月8日の勝ちは依然切ってしまう。",
         "日中の持続確認で改善した部分と残る負け.md",
         "画像/持続確認/2026-09-28_Day_NK225_DV05.png"),
        ("夜間：見ていた現在値と売買気配が違った",
         "10月8日ナイト翌02:07:25、現在値68,200・出来高不変でも気配が上昇。売りの返済は68,280になった。"
         "中値で判断し直しても安定性は改善せず、早く入ると利益保護も早く始まる副作用があった。",
         "夜間チャート観察と仮説.md",
         "画像/夜間/2026-10-08_Night_NK225_05_Last固定中の板再評価.png"),
        ("夜間：見送り中に古い発注準備を残さない",
         "短期だけ順行し、両市場の120秒の動きは強く逆向きだった。発注を待つだけでは、後に不利な価格で入り直して同額の損失。"
         "準備を破棄するNV25は日経の最悪場を−13,220円から−8,220円へ縮めたが、無取引は8/21場。TOPIXの安定化には至らなかった。",
         "夜間再試験の失敗と勝ちの観察.md", ""),
    ]
    cards = []
    for title, description, link, image in evidence:
        pic = (f'<details><summary>売買位置の画像を見る</summary><a href="{image}">'
               f'<img loading="lazy" src="{image}" alt="{html.escape(title)}"></a></details>') if image else ""
        cards.append(f'<article><h3>{title}</h3><p>{description}</p><a href="{link}">具体時刻と反例</a>{pic}</article>')
    options = {}
    for kind, selected in (("Day", args.day), ("Night", args.night)):
        options[kind] = "".join(f'<option value="{m["id"]}"{" selected" if m["id"]==selected else ""}>'
            f'{m["id"]}：{html.escape(m["name"])}</option>' for m in methods if m["kind"] == kind)
    allrows = []
    for s in result["summary"]:
        regime = s.get("regimes", {})
        ups = regime.get("上昇", {}).get("net", 0.)
        downs = regime.get("下落", {}).get("net", 0.)
        unchanged = regime.get("同値", {}).get("net", 0.)
        allrows.append(f'<tr><td>{s["method"]}</td><td>{s["symbol"]}</td>'
            f'<td>{money(s["net"])}</td><td>{s["black"]} / {s["red"]} / {s["flat"]}</td>'
            f'<td>{money(s["worst"])}</td><td>{money(s["without_top3"])}</td>'
            f'<td>{money(ups)}</td><td>{money(downs)}</td><td>{money(unchanged)}</td>'
            f'<td>{money(s["halves"]["後半"]["net"])}</td></tr>')
    payload = json.dumps(dict(rows=rows, summary=result["summary"], names=names), ensure_ascii=False).replace("</", "<\\/")
    source = f"../../work/visual_pdca129_20261020/{args.result}"
    document = """<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>チャートで失敗を確かめた改修と全セッション損益</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0e1520;color:#e3eaf5;font:16px/1.7 system-ui,"Meiryo",sans-serif}main{max-width:1550px;margin:auto;padding:28px}
h1{font-size:27px;margin:5px 0 15px}h2{font-size:21px;margin:30px 0 12px}h3{font-size:17px;margin:0 0 8px}p{margin:9px 0}.muted,small{color:#a6b5cb}a{color:#8fc9ff}article,.box{border:1px solid #33425c;background:#151f2e;border-radius:10px;padding:19px;margin:14px 0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}.cards article{margin:0}.controls{display:flex;gap:20px;flex-wrap:wrap}label{flex:1;min-width:300px}select{width:100%;padding:9px;background:#202e43;border:1px solid #576b89;color:#edf4ff;border-radius:6px;font:inherit}table{border-collapse:collapse;width:100%;font-size:14px;white-space:nowrap}th,td{border-bottom:1px solid #2b3a51;padding:9px 12px;text-align:right}th{background:#223149;color:#cfddf2;position:sticky;top:0}th:first-child,td:first-child{text-align:left}tfoot td{background:#243650;font-weight:700}.scroll{overflow:auto;max-height:750px;border:1px solid #33425c;border-radius:8px}.positive{color:#69d5b7}.negative{color:#f49aaa}summary{cursor:pointer;color:#9bc9fb;padding:8px 0}details{margin-top:12px}img{width:100%;height:auto}#selected-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px}.notice{border-left:4px solid #f3bd68;padding-left:13px}
</style>
<main><a href="../index.html">調査一覧</a><h1>チャートで失敗を確かめた改修と全セッション損益</h1>
<p class="notice"><strong>日中は、逆行の持続確認で損失を縮める改善を確認。夜間は、両銘柄共通の安定性をまだ確認できていない。</strong> 合計黒字だけで完成とは判定しない。</p>
<p>日中の比較候補はTOPIXの120秒確認DV07、日経の60秒確認DV05。TOPIXは旧勝ちを残して3件の損失を計37,500円削減。赤字場数は両商品とも6/22のまま。共通120秒のDV07は日経の総収支を旧D17より5,500円減らすため、両商品で全面改善したわけではない。</p>
<p class="muted">通常はTOPIXミニ5枚／日経マイクロ10枚。数量比較NV18〜21は初期2枚／4枚、追加型の上限5枚／10枚。提示手数料込み、場内全返済。全43場は既知の開発資料。ラージの次正常原行気配を約定代理とし、実受信時計・実ミニ板の再現ではない。</p>
<h2>何を直し、何が残ったか</h2><div class="cards">__CARDS__</div>
<p><a href="検証の進め方.md">検証手順</a>　<a href="日中の持続確認で改善した部分と残る負け.md">日中の改善と残る負け</a>　<a href="夜間再試験の失敗と勝ちの観察.md">夜間の改修で生じた失敗</a>　<a href="利益床の範囲で追加する数量仕様.md">数量の変更</a></p>
<!--
機能: 条件を選び、保存済み会計の全場表を表示する。新規の売買判断は行わない。
day-method/night-method は昼夜の選択、selected-summary は比較指標、session-body は全43場。
引数: 画面選択文字列と下部JSONの保存会計。返り値: 選択条件の表示DOM。
-->
<h2>各セッションの利益・損失・収支</h2><div class="controls">
<label>日中<select id="day-method">__DAY__</select></label><label>夜間<select id="night-method">__NIGHT__</select></label></div>
<p class="muted">夜間の初期表示N36は従来基準。最新の準備破棄型はNV24・NV25。選択は過去結果の表示だけで、無取引は黒字に数えない。NV04・05・07・08は60分差に不要な途中資料まで要求していたため、修正版NV10〜13も確認する。終値高安を使うNV06・09の全区間資格は意図した条件。</p>
<div id="selected-summary"></div><div class="scroll"><table id="session-table">
<thead><tr><th rowspan="2">セッション</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経マイクロ</th></tr>
<tr><th>利益</th><th>損失</th><th>収支</th><th>累計</th><th>利益</th><th>損失</th><th>収支</th><th>累計</th></tr></thead>
<tbody id="session-body"></tbody><tfoot id="session-total"></tfoot></table></div>
<details><summary>全条件の比較（__COUNT__条件、銘柄間の円額は合算しない）</summary><div class="scroll"><table id="all-comparison">
<thead><tr><th>手法</th><th>商品</th><th>収支</th><th>黒字 / 赤字 / 無取引</th><th>最悪場</th><th>上位3黒字場除外</th><th>上昇場収支</th><th>下落場収支</th><th>同値場収支</th><th>後半収支</th></tr></thead>
<tbody>__ALLROWS__</tbody></table></div></details>
<p class="muted">利益・損失は、同じ新規建玉の部分返済をまとめ、全手数料を差し引いた完結親単位の正負。再参加は別親。場の収支＝利益−損失。上昇・下落区分は事後採点専用で、注文判断には使用しない。</p>
<p><a href="__SOURCE__">全数値の保存元</a>　<a href="README.md">実装・監査と資料案内</a></p>
</main><script type="application/json" id="saved-data">__DATA__</script><script>
const saved = JSON.parse(document.getElementById("saved-data").textContent);
/**
 * 機能: 円額を日本語の桁区切りで表示する。
 * @param {number} value - 保存された円額。
 * @returns {string} 符号付き円額。
 */
function money(value){return (value>0?"+":"")+Math.round(value).toLocaleString("ja-JP");}
/**
 * 機能: 円額セルを色付きで作る。
 * @param {number} value - 表示する円額。
 * @returns {string} 数値だけを含む表セル。
 */
function cell(value){return `<td class="${value>0?"positive":value<0?"negative":""}">${money(value)}</td>`;}
/**
 * 機能: 昼夜の保存会計を選択して43場と合計を表示する。
 * 引数: なし。画面の選択値を参照する。
 * 返り値: なし。金融再生やサーバー接続はしない。
 */
function update(){
 const chosen={Day:document.getElementById("day-method").value,Night:document.getElementById("night-method").value};
 const rows=saved.rows.filter(r=>r.method===chosen[r.kind]);
 const sessions=[...new Set(rows.map(r=>r.session))].sort();
 const sums={TOPIX:{profit:0,loss:0,net:0},NK225:{profit:0,loss:0,net:0}};
 let body="";
 for(const scene of sessions){
  body+=`<tr><td>${scene.replace("_Day"," デイ").replace("_Night"," ナイト")}</td>`;
  for(const symbol of ["TOPIX","NK225"]){
   const r=rows.find(r=>r.session===scene&&r.symbol===symbol);
   for(const key of ["profit","loss","net"]) sums[symbol][key]+=r[key];
   body+=cell(r.profit)+cell(-r.loss)+cell(r.net)+cell(sums[symbol].net);
  }
  body+="</tr>";
 }
 document.getElementById("session-body").innerHTML=body;
 document.getElementById("session-total").innerHTML="<tr><td>全43場の合計</td>"+["TOPIX","NK225"].map(s=>cell(sums[s].profit)+cell(-sums[s].loss)+cell(sums[s].net)+cell(sums[s].net)).join("")+"</tr>";
 document.getElementById("selected-summary").innerHTML=["Day","Night"].flatMap(kind=>["TOPIX","NK225"].map(symbol=>{
  const s=saved.summary.find(s=>s.method===chosen[kind]&&s.symbol===symbol);
  const selected=rows.filter(r=>r.kind===kind&&r.symbol===symbol);
  const quantity=selected.reduce((v,r)=>v+r.quantity,0), maxQuantity=Math.max(...selected.map(r=>r.max_quantity));
  return `<article><h3>${kind==="Day"?"日中":"夜間"} ${s.method} / ${symbol}</h3><p>収支 <b>${money(s.net)}円</b><br>黒字${s.black}・赤字${s.red}・無取引${s.flat}場<br>最悪 ${money(s.worst)}円<br>大勝ち3場を除くと ${money(s.without_top3)}円<br><small>新規${s.entries}組・延べ${quantity}枚／最大同時${maxQuantity}枚</small></p></article>`;
 })).join("");
}
document.getElementById("day-method").addEventListener("change",update);
document.getElementById("night-method").addEventListener("change",update);
update();
</script></html>"""
    replacements = {"__CARDS__": "".join(cards), "__DAY__": options["Day"], "__NIGHT__": options["Night"],
                    "__COUNT__": str(len(methods)), "__ALLROWS__": "".join(allrows),
                    "__SOURCE__": source, "__DATA__": payload}
    for key, value in replacements.items():
        document = document.replace(key, value)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC/"チャートで検証した改修と全セッション損益.html").write_text(document, encoding="utf-8")
    print("公開HTMLを更新", len(rows), "商品場行", len(methods), "条件", flush=True)


if __name__ == "__main__":
    main()
