"""三段階の原因・改修結果・全場会計を短い暗色レポートにする。"""

import html
import json
from common130 import HERE, PUBLIC, read


def money(value):
    """
    機能: 円額を符号付き整数へ整形する。
    引数: value(float)は円額。
    返り値: strは表示文字列。
    """
    return f"{round(value):+,}"


def main():
    """
    機能: 確定会計と文章から、全43場を参照できるHTMLを作る。
    引数: なし。最終全場比較_確定.jsonと結論.jsonを読む。
    返り値: None。金融再生や外部通信は行わない。
    """
    result = read(HERE / "最終全場比較_確定.json")
    conclusion = read(HERE / "結論.json")
    names = {r["method"]: r.get("name", r["method"]) for r in result["rows"]}
    methods = {kind: sorted({r["method"] for r in result["rows"] if r["kind"] == kind})
               for kind in ("Day", "Night")}
    options = {}
    for kind in ("Day", "Night"):
        options[kind] = "".join(
            f'<option value="{m}"{" selected" if m == conclusion["night"] else ""}>'
            f'{m}：{html.escape(names[m])}</option>' for m in methods[kind])
    cards = []
    for item in conclusion["causes"]:
        image = item.get("image")
        picture = (f'<a href="{image}"><img src="{image}" loading="lazy" alt="{html.escape(item["title"])}"></a>'
                   if image else "")
        cards.append(f'<article><h3>{html.escape(item["title"])}</h3>'
            f'<p>{html.escape(item["summary"])}</p><details><summary>なぜを三段階と具体時刻で確認</summary>'
            + "".join(f'<p><b>{i+1}.</b> {html.escape(why)}</p>' for i, why in enumerate(item["why"]))
            + f'<p>{html.escape(item["change"])}</p>{picture}</details></article>')
    allrows = []
    for s in result["summary"]:
        regimes = s["regimes"]
        allrows.append(f'<tr><td>{s["method"]}</td><td>{s["symbol"]}</td>'
            f'<td>{money(s["net"])}</td><td>{s["black"]}/{s["red"]}/{s["flat"]}/{s["breakeven"]}</td>'
            f'<td>{money(s["worst"])}</td><td>{money(s["without_top3"])}</td>'
            + "".join(f'<td>{money(regimes.get(k, {}).get("net", 0))}</td>' for k in ("上昇", "下落", "同値"))
            + f'<td>{money(s["halves"]["後半"]["net"])}</td></tr>')
    payload = json.dumps(dict(rows=result["rows"], summary=result["summary"], names=names),
                         ensure_ascii=False).replace("</", "<\\/")
    document = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>夜間のなぜ三段階と改善後の全セッション損益</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#101722;color:#e0e9f5;font:16px/1.7 system-ui,"Meiryo",sans-serif}main{max-width:1550px;padding:24px;margin:auto}h1{font-size:27px}h2{font-size:21px;margin-top:28px}h3{font-size:17px;margin:0}a{color:#90caff}p{margin:9px 0}.muted,small{color:#a9bad1}.notice{border-left:4px solid #e7bc71;padding:12px;background:#1b2738}.cards,#selected-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px}article{background:#172334;border:1px solid #35475f;border-radius:9px;padding:16px}details{margin:15px 0}summary{cursor:pointer;color:#9acbff}img{width:100%;height:auto}.controls{display:flex;gap:18px;flex-wrap:wrap;margin:15px 0}label{flex:1;min-width:260px}select{width:100%;padding:10px;font:inherit;color:#e0e9f5;background:#223249;border:1px solid #596e8b;border-radius:6px}.scroll{overflow:auto;max-height:740px;border:1px solid #34445d;margin-top:15px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{padding:9px 11px;text-align:right;border-bottom:1px solid #30415a}th{background:#273952;position:sticky;top:0}td:first-child,th:first-child{text-align:left}tfoot{background:#263a54;font-weight:bold}.positive{color:#72dfb9}.negative{color:#ff9ba9}
</style></head><body><main>
<a href="../index.html">調査一覧</a><h1>夜間のなぜ三段階と改善後の損益</h1>
<p class="notice"><strong>__HEADLINE__</strong></p><p>__FINDING__</p>
<p class="muted">TOPIXミニ5枚／日経マイクロ10枚、新規追加なし。部分返済は2＋3枚／5＋5枚。提示手数料込み、場内全返済。全43場は既知の開発資料で、未知の将来検証ではない。</p>
<h2>何が負けを生み、何を直したか</h2><div class="cards">__CARDS__</div>
<p><a href="出口と途中判断のなぜ三段階.md">出口の具体時刻・勝ちを消す反例</a>　<a href="入口原板の三段階診断.md">入口の原板と観測限界</a>　<a href="反復結果となぜ三段階.md">改修後の再診断</a></p>
<!--
機能: 保存済み会計を選択し、全43場と累計を表示する。
day-method/night-method は条件、session-body は全場、session-total は合計。
引数: 選択された手法文字列と下部の保存JSON。
返り値: DOMの表示。新たな売買判断や損益再生はしない。
-->
<h2>各セッションの利益・損失・収支</h2>
<div class="controls"><label>日中（今回の再生はせず、保存結果を引用）<select id="day-method">
<option value="別" selected>銘柄別候補：TOPIX DV07／日経 DV05</option>__DAY__</select></label>
<label>夜間（両商品に同じ条件を適用）<select id="night-method">__NIGHT__</select></label></div>
<p class="muted">__DEFAULT__　無取引は勝ちに含めない。利益・損失は部分返済と残玉を同じ新規単位へ合算した全費用後の正負。途中だけの利確を勝ちとして数えない。</p>
<div id="selected-summary"></div>
<div class="scroll"><table id="session-table"><thead><tr><th rowspan="2">セッション</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経マイクロ</th></tr>
<tr><th>利益</th><th>損失</th><th>収支</th><th>累計</th><th>利益</th><th>損失</th><th>収支</th><th>累計</th></tr></thead><tbody id="session-body"></tbody><tfoot id="session-total"></tfoot></table></div>
<details><summary>全条件を比較する（上昇・下落・大勝ち除外）</summary><div class="scroll"><table id="all-comparison">
<thead><tr><th>条件</th><th>商品</th><th>収支</th><th>黒/赤/無取引/取引後ゼロ</th><th>最悪場</th><th>上位3黒字除外</th><th>上昇場</th><th>下落場</th><th>同値場</th><th>後半</th></tr></thead>
<tbody>__ALLROWS__</tbody></table></div></details>
<p class="muted">上昇・下落は採点用の事後分類で、売買判断には使わない。公表時計と原行順の範囲で過去を参照し、約定は判断後の次正常原行のラージ気配で代用。実受信順での二市場情報の同時利用、実ミニ・マイクロ約定、通信遅延は未検証。</p>
<p><a href="README.md">仕様・実装・監査</a>　<a href="調査の前提.md">観測と検証の前提</a>　<a href="../../work/night_why130_20261020/最終全場比較_確定.json">全数値の保存元</a></p>
</main><script type="application/json" id="saved-data">__DATA__</script><script>
const saved=JSON.parse(document.getElementById("saved-data").textContent);
/**
 * 円額を桁区切りで表示する。
 * @param {number} value - 円額。
 * @returns {string} 符号付きの表示。
 */
function money(value){return (value>0?"+":"")+Math.round(value).toLocaleString("ja-JP");}
/**
 * 円額を表セルへ変換する。
 * @param {number} value - 円額。
 * @returns {string} 色付きの表セル。
 */
function cell(value){return `<td class="${value>0?"positive":value<0?"negative":""}">${money(value)}</td>`;}
/**
 * 選択された昼夜・商品の条件を特定する。
 * @param {string} kind - Day又はNight。
 * @param {string} symbol - TOPIX又はNK225。
 * @returns {string} 手法ID。
 */
function chosen(kind,symbol){
 const day=document.getElementById("day-method").value;
 return kind==="Night"?document.getElementById("night-method").value:day==="別"?(symbol==="TOPIX"?"DV07":"DV05"):day;
}
/**
 * 保存済み会計から全43場の表示を更新する。
 * 引数: なし。選択値を参照する。
 * 返り値: なし。累計表示のみ再計算する。
 */
function update(){
 const rows=saved.rows.filter(r=>r.method===chosen(r.kind,r.symbol));
 const scenes=[...new Set(rows.map(r=>r.session))].sort(), sums={TOPIX:[0,0,0],NK225:[0,0,0]};
 document.getElementById("session-body").innerHTML=scenes.map(scene=>{
  let row=`<tr><td>${scene.replace("_Day"," デイ").replace("_Night"," ナイト")}</td>`;
  for(const symbol of ["TOPIX","NK225"]){
   const r=rows.find(r=>r.session===scene&&r.symbol===symbol), total=sums[symbol];
   [r.profit,r.loss,r.net].forEach((v,i)=>total[i]+=v);
   row+=cell(r.profit)+cell(-r.loss)+cell(r.net)+cell(total[2]);
  }
  return row+"</tr>";
 }).join("");
 document.getElementById("session-total").innerHTML="<tr><td>全43場合計</td>"+["TOPIX","NK225"].map(s=>{
  const v=sums[s];return cell(v[0])+cell(-v[1])+cell(v[2])+cell(v[2]);
 }).join("")+"</tr>";
 document.getElementById("selected-summary").innerHTML=["Day","Night"].flatMap(kind=>["TOPIX","NK225"].map(symbol=>{
  const method=chosen(kind,symbol),s=saved.summary.find(s=>s.method===method&&s.symbol===symbol);
  return `<article><h3>${kind==="Day"?"日中":"夜間"} ${method} / ${symbol}</h3><p>収支 <b>${money(s.net)}円</b><br>黒字${s.black}・赤字${s.red}・無取引${s.flat}場${s.breakeven?"・取引後ゼロ"+s.breakeven+"場":""}<br>最悪 ${money(s.worst)}円<br>上位3黒字除外 ${money(s.without_top3)}円<br><small>新規${s.entries}組</small></p></article>`;
 })).join("");
}
document.getElementById("day-method").addEventListener("change",update);
document.getElementById("night-method").addEventListener("change",update);
update();
</script></body></html>"""
    values = dict(HEADLINE=html.escape(conclusion["headline"]), FINDING=html.escape(conclusion["finding"]),
                  DEFAULT=html.escape(conclusion["default"]), CARDS="".join(cards),
                  DAY=options["Day"], NIGHT=options["Night"], ALLROWS="".join(allrows), DATA=payload)
    for name, value in values.items():
        document = document.replace("__" + name + "__", value)
    (PUBLIC / "夜間のなぜ三段階と改善後の損益.html").write_text(document, encoding="utf-8")
    print("公開:", len(result["rows"]), "商品場", flush=True)


if __name__ == "__main__":
    main()
