"""保存会計だけから、時間帯・状態切替の全セッション損益を暗色HTMLへ表示する。"""

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path

from common131 import HERE, ROOT, LAST, PUBLIC


REPORT = HERE / "reportwork"
DEFAULT_NAME = "時間帯と値動き状態を切り替える手法の全セッション損益.html"
PRODUCTS = ("TOPIX", "NK225")
KINDS = ("Day", "Night")


def read_document(path):
    """
    機能: UTF-8の保存資料を読み、使用した内容の指紋を返す。
    引数: path(Path)はJSONの位置。
    返り値: tuple[dict又はlist,dict]は内容と参照位置・SHA256。
    """
    raw = path.read_bytes()
    ref = dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(raw).hexdigest())
    return json.loads(raw.decode("utf-8-sig")), ref


def statistics(rows):
    """
    機能: 保存された商品場の損益・参加数を表示用に合算する。
    引数: rows(list[dict])は一商品一条件の保存行。
    返り値: dictは累計・黒赤無取引・最大赤字・上位3黒字除外。
    """
    nets = [r["net"] for r in rows]
    positive = sorted((x for x in nets if x > 0), reverse=True)
    return dict(sessions=len(rows), profit=sum(r["profit"] for r in rows),
        loss=sum(r["loss"] for r in rows), net=sum(nets),
        black=sum(x > 0 for x in nets), red=sum(x < 0 for x in nets),
        empty=sum(r["entries"] == 0 for r in rows),
        breakeven=sum(r["entries"] > 0 and r["net"] == 0 for r in rows),
        entries=sum(r["entries"] for r in rows), worst=min(nets, default=0),
        maximum_loss=max(0, -min(nets, default=0)),
        without_top3=sum(nets)-sum(positive[:3]))


def normalized_rows(document, namespace, origin):
    """
    機能: 元会計を変更せず、巡別の識別子と表示列だけを持つ行へ写す。
    引数: document(dict)は保存会計、namespace/origin(str)は巡名と出典。
    返り値: list[dict]は表示行。同一識別子・商品・場の重複は拒否する。
    """
    seen = set()
    result = []
    for raw in document["rows"]:
        method, scene, product = str(raw["method"]), str(raw["session"]), str(raw["symbol"])
        kind = raw.get("kind", scene.rsplit("_", 1)[-1])
        assert kind in KINDS and product in PRODUCTS
        key = (method, scene, product)
        assert key not in seen, ("会計内重複", origin, key)
        seen.add(key)
        values = {name: float(raw[name]) for name in ("profit", "loss", "net")}
        assert values["profit"] >= 0 and values["loss"] >= 0
        assert abs(values["profit"]-values["loss"]-values["net"]) < .001, key
        assert int(raw["entries"]) == raw["entries"] and raw["entries"] >= 0
        result.append(dict(key=namespace+"::"+method, method=method, name=raw.get("name", method),
            namespace=namespace, origin=origin, kind=kind, session=scene, symbol=product,
            entries=int(raw["entries"]), **values))
    return result


def check_analysis(account, analysis, account_ref):
    """
    機能: 分析資料が同じ保存会計を参照し、主要再集計値が一致するかを確認する。
    引数: account/analysis/account_ref(dict)は会計・区分集計・会計指紋。
    返り値: intは照合した集計数。既存金融結果を再生成しない。
    """
    assert analysis.get("passed") is True
    assert analysis["source"] == account_ref, "区分別比較の参照先が会計と一致しません"
    checked = 0
    for group in analysis["summary"]:
        rows = [r for r in account["rows"] if r["method"] == group["method"] and r["symbol"] == group["symbol"]]
        summary = statistics(rows)
        for key in ("sessions", "profit", "loss", "net", "black", "red", "empty", "entries", "worst", "without_top3"):
            assert abs(float(summary[key])-float(group[key])) < .001, (group["method"], group["symbol"], key)
            checked += 1
        for kind in KINDS:
            actual = statistics([r for r in rows if r["kind"] == kind])
            expected = group["daynight"][kind]
            for key in ("sessions", "net", "black", "red", "empty", "worst", "without_top3"):
                assert abs(float(actual[key])-float(expected[key])) < .001, (group["method"], kind, key)
                checked += 1
    return checked


def resolve_default(requested, options, fallback):
    """
    機能: 外部結論の初期選択を巡別IDへ一意に解決する。
    引数: requested(str又はNone)、options(list[str])は利用可能ID、fallback(str)は既定候補。
    返り値: strは実在する巡別ID。曖昧な裸IDは拒否する。
    """
    if requested is None:
        return fallback if fallback in options else options[0]
    if requested in options:
        return requested
    matches = [key for key in options if key.split("::", 1)[1] == requested]
    assert len(matches) == 1, ("初期選択が存在しないか曖昧", requested, matches)
    return matches[0]


def collect(rounds, conclusion, include_baseline=True):
    """
    機能: 指定した複数巡と旧比較元を読み、全場表示用の一つの資料へまとめる。
    引数: rounds(list[Path])は巡フォルダ、conclusion(dict)は文章と初期選択、include_baseline(bool)は旧値引用。
    返り値: dictは表示データ・出典・選択候補。金融処理は呼ばない。
    """
    rows, reads, comparisons = [], [], []
    checked = 0
    used = set()
    for folder in rounds:
        namespace = folder.name
        assert namespace not in used, "同名巡フォルダは指定できません"
        used.add(namespace)
        account, account_ref = read_document(folder/"全条件の会計.json")
        analysis, analysis_ref = read_document(folder/"区分別の比較.json")
        assert account.get("passed") is True
        checked += check_analysis(account, analysis, account_ref)
        reads.extend([account_ref, analysis_ref])
        rows.extend(normalized_rows(account, namespace, account_ref["path"]))
        comparisons.extend(dict(key=namespace+"::"+s["method"], **s) for s in analysis["summary"])
    if include_baseline:
        baseline, reference = read_document(LAST/"最終全場比較_確定.json")
        assert baseline.get("passed") is True
        reads.append(reference)
        rows.extend(normalized_rows(baseline, "旧", reference["path"]))
    assert rows, "表示できる会計がありません"
    scenes = sorted({r["session"] for r in rows})
    names = {r["key"]:r["method"]+"："+r["name"] for r in rows}
    options, defaults = {}, {}
    supplied = conclusion.get("defaults", {})
    for kind in KINDS:
        options[kind], defaults[kind] = {}, {}
        for product in PRODUCTS:
            choices = sorted({r["key"] for r in rows if r["kind"] == kind and r["symbol"] == product},
                             key=lambda value:(value.startswith("旧::"),value))
            assert choices, (kind, product, "選択肢なし")
            options[kind][product] = choices
            requested = supplied.get(kind, {}).get(product)
            defaults[kind][product] = resolve_default(requested, choices, choices[0])
    return dict(rows=rows, sessions=scenes, names=names, options=options, defaults=defaults,
        analysis=comparisons, reads=reads, analysis_checks=checked,
        note="会計値は保存済み結果の引用。未収録は0円へ置換しない。")


def document(data, conclusion):
    """
    機能: 簡潔な結論・条件選択・全場表を持つ外部通信なしのHTMLを組み立てる。
    引数: data(dict)は表示会計、conclusion(dict)は外部文章。
    返り値: strは暗色HTML。JavaScriptは保存数値の集計と表示だけを行う。
    """
    title = conclusion.get("title", "時間帯と値動き状態を切り替える手法の損益")
    headline = conclusion.get("headline", "結論は未確定です。保存結果を比較しています。")
    finding = conclusion.get("finding", "")
    links = conclusion.get("links", [
        dict(label="市場時刻とニュースの根拠", href="../../work/regime131_20261020/news/ニュース予定根拠の確定.json"),
        dict(label="日中の無取引・勝ちを消す反例", href="../../work/regime131_20261020/day_diagnosis/日中の無取引と新入口への示唆.md"),
        dict(label="日中の原板照合追補", href="../../work/regime131_20261020/day_diagnosis/原板照合の追補.md"),
        dict(label="夜間の時間帯と機会", href="../../work/regime131_20261020/night_diagnosis/全夜間の時間帯と継続往復の観測.json")])
    link_html = "　".join('<a href="'+html.escape(x["href"],quote=True)+'">'+html.escape(x["label"])+"</a>" for x in links)
    controls = []
    for kind,label in (("Day","日中"),("Night","夜間")):
        for product,product_label in (("TOPIX","TOPIX"),("NK225","日経")):
            select = []
            for key in data["options"][kind][product]:
                chosen = " selected" if key == data["defaults"][kind][product] else ""
                name = ("旧比較 " if key.startswith("旧::") else key.split("::")[0]+" ") + data["names"][key]
                select.append('<option value="'+html.escape(key,quote=True)+'"'+chosen+'>'+html.escape(name)+"</option>")
            controls.append('<label>'+label+" "+product_label+'<select id="'+kind+"-"+product+'">'+"".join(select)+"</select></label>")
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    template = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:dark;font-family:system-ui,"Meiryo",sans-serif;color:#e7eef7;background:#101722}*{box-sizing:border-box}body{margin:0;line-height:1.6}main{max-width:1480px;margin:auto;padding:22px}h1{font-size:25px;margin:10px 0}p{margin:8px 0}a{color:#9bcfff}.muted{color:#aabbd1;font-size:13px}.notice{padding:12px 15px;background:#1e2b3e;border-left:4px solid #e6b86d;margin:14px 0}.controls{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:20px 0}label{font-size:14px;color:#c6d4e5}select{display:block;width:100%;margin-top:5px;background:#223147;color:#edf4fc;border:1px solid #536982;border-radius:6px;padding:10px;font:inherit}.cards{display:grid;grid-template-columns:1fr 1fr;gap:14px}article{padding:14px 17px;background:#172336;border:1px solid #344760;border-radius:8px}h2{font-size:18px;margin:0 0 5px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.metrics span{display:block;font-size:12px;color:#aabbd1}.metrics b{font-size:18px}.positive{color:#7de0b7}.negative{color:#ff9ca8}.missing{color:#f3c66a}.scroll{max-height:760px;overflow:auto;margin-top:17px;border:1px solid #35455d}table{border-collapse:separate;border-spacing:0;width:100%;white-space:nowrap;font-size:14px}th,td{padding:9px 10px;text-align:right;border-bottom:1px solid #30415a}th{background:#25364e}thead th{position:sticky;top:0;z-index:2}thead tr:nth-child(2) th{top:40px}th:first-child,td:first-child{text-align:left}tbody td:first-child{position:sticky;left:0;background:#172336;z-index:1}tbody tr:nth-child(even){background:#142030}tfoot{background:#263a54;font-weight:bold}caption{text-align:left;padding:8px;color:#c3d3e6}details{margin-top:16px}summary{cursor:pointer;color:#a7d2ff}.sources{overflow-wrap:anywhere}.warning{color:#f4c778}.count{font-size:11px;color:#aabbd1}button{background:#2b4160;border:1px solid #637a98;color:#e7eef7;padding:8px 12px;border-radius:5px;cursor:pointer}
@media(max-width:950px){.controls{grid-template-columns:1fr 1fr}.metrics{grid-template-columns:1fr 1fr}}@media(max-width:580px){main{padding:12px}.cards{grid-template-columns:1fr}h1{font-size:21px}}
</style></head><body><main>
<a href="README.md">仕様・読む順序</a><h1>__TITLE__</h1>
<p class="notice"><strong>__HEADLINE__</strong></p><p>__FINDING__</p>
<p class="muted">TOPIXミニ5枚／日経マイクロ10枚。提示手数料込み・場内返済。旧条件は保存会計を引用。既知43場での比較です。</p>
<!--
機能: 昼夜・商品別の条件を選び、全保存セッションの会計と累計を表示する。
Day-TOPIX、Day-NK225、Night-TOPIX、Night-NK225 は条件選択。
selected-summary は合算指標、session-body は全場、session-total は累計。
引数: saved-data の保存会計と選択文字列。
返り値: DOMの表示。新しい売買判断・仮想約定は生成しない。
-->
<div class="controls">__CONTROLS__</div>
<div id="selected-summary" class="cards"></div>
<p class="muted">黒／赤はセッション収支の正負。無取引を勝ちに含めません。最大赤字は一場の損失、上位3除外は大きい黒字3場を除いた累計です。</p>
<p id="missing-warning" class="warning" hidden></p>
<div class="scroll"><table id="session-table"><caption>各セッションの利益・損失・収支（円）</caption>
<thead><tr><th rowspan="2">セッション</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経マイクロ</th></tr>
<tr><th>利益</th><th>損失</th><th>収支</th><th>累計</th><th>利益</th><th>損失</th><th>収支</th><th>累計</th></tr></thead>
<tbody id="session-body"></tbody><tfoot id="session-total"></tfoot></table></div>
<details><summary>日中・夜間それぞれの安定性</summary><div class="scroll"><table id="split-table">
<thead><tr><th>区分・商品</th><th>条件</th><th>収支</th><th>黒／赤／無取引</th><th>最大赤字</th><th>上位3除外</th><th>新規数</th></tr></thead><tbody id="split-body"></tbody></table></div></details>
<details><summary>全条件の比較</summary><div class="scroll"><table id="comparison-table"><thead><tr><th>巡・条件</th><th>区分</th><th>商品</th><th>収支</th><th>黒／赤／無取引</th><th>最大赤字</th><th>上位3除外</th><th>新規数</th></tr></thead><tbody id="comparison-body"></tbody></table></div></details>
<p class="muted">利益・損失は新規から全返済までを一組にまとめた手数料後金額です。ラージの気配を代理に使用し、判断後の次正常原行で約定。実ミニ／マイクロの約定や通信遅延は未再現です。</p>
<p>__LINKS__</p>
<details class="sources"><summary>保存元と表示データ</summary><div id="source-links"></div></details>
</main><script type="application/json" id="saved-data">__DATA__</script>
<script>
"use strict";
const saved=JSON.parse(document.getElementById("saved-data").textContent);
const products=["TOPIX","NK225"], kinds=["Day","Night"];
const byRow=new Map(saved.rows.map(r=>[`${r.key}|${r.session}|${r.symbol}`,r]));
/**
 * 機能: 文字列をHTML表示用へエスケープする。
 * @param {string} value - 表示文字列。
 * @returns {string} 安全なHTML文字列。
 */
function escapeHtml(value){return String(value).replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));}
/**
 * 機能: 円額を符号付き整数へ表示する。
 * @param {number} value - 円額。
 * @returns {string} 桁区切り表示。
 */
function money(value){return (value>0?"+":"")+Math.round(value).toLocaleString("ja-JP");}
/**
 * 機能: 円額のセルを作る。
 * @param {number} value - 円額。
 * @returns {string} 正負色を付けた表セル。
 */
function cell(value){return `<td class="${value>0?"positive":value<0?"negative":""}">${money(value)}</td>`;}
/**
 * 機能: 一商品・指定条件の保存行を集計する。
 * @param {Array<object>} rows - 保存会計行。
 * @returns {object} 合計・黒赤無取引・損失規模。
 */
function stats(rows){
 const nets=rows.map(r=>r.net),wins=nets.filter(v=>v>0).sort((a,b)=>b-a);
 const sum=field=>rows.reduce((v,r)=>v+r[field],0);
 return {sessions:rows.length,profit:sum("profit"),loss:sum("loss"),net:sum("net"),
  black:nets.filter(v=>v>0).length,red:nets.filter(v=>v<0).length,
  empty:rows.filter(r=>r.entries===0).length,
  breakeven:rows.filter(r=>r.entries>0&&r.net===0).length,
  entries:sum("entries"),maximum_loss:Math.max(0,-Math.min(0,...nets)),
  without_top3:sum("net")-wins.slice(0,3).reduce((a,b)=>a+b,0)};
}
/**
 * 機能: 商品・区分の現在選択を返す。
 * @param {string} kind - Day又はNight。
 * @param {string} product - TOPIX又はNK225。
 * @returns {string} 巡と条件の識別子。
 */
function chosen(kind,product){return document.getElementById(`${kind}-${product}`).value;}
/**
 * 機能: 選択済みの会計行を返す。
 * @param {string} product - 商品名。
 * @param {string|null} kind - 区分。nullは昼夜両方。
 * @returns {Array<object>} 保存行。
 */
function selected(product,kind=null){return saved.rows.filter(r=>r.symbol===product&&(!kind||r.kind===kind)&&r.key===chosen(r.kind,product));}
/**
 * 機能: 黒字・赤字・無取引と取引後ゼロを表示する。
 * @param {object} value - 集計結果。
 * @returns {string} 件数表示。
 */
function counts(value){return `${value.black}／${value.red}／${value.empty}`+(value.breakeven?`（取引後ゼロ${value.breakeven}）`:"");}
/**
 * 機能: 保存会計から全セッションと累計、短い要約を更新する。
 * 引数: なし。四つの選択値を参照する。
 * 返り値: なし。表示のみを変更する。
 */
function update(){
 const total={TOPIX:[0,0,0],NK225:[0,0,0]},missing=[];
 document.getElementById("session-body").innerHTML=saved.sessions.map(scene=>{
  const kind=scene.endsWith("_Day")?"Day":"Night";
  let line=`<tr data-session="${escapeHtml(scene)}"><td>${escapeHtml(scene.replace("_Day"," デイ").replace("_Night"," ナイト"))}</td>`;
  for(const product of products){
   const row=byRow.get(`${chosen(kind,product)}|${scene}|${product}`);
   if(!row){missing.push(scene+" "+product);line+='<td class="missing" colspan="4">未収録</td>';continue;}
   total[product][0]+=row.profit;total[product][1]+=row.loss;total[product][2]+=row.net;
   line+=cell(row.profit)+cell(-row.loss)+cell(row.net)+cell(total[product][2]);
  }
  return line+"</tr>";
 }).join("");
 document.getElementById("session-total").innerHTML=`<tr><td>${saved.sessions.length}場 累計</td>`+
  products.map(p=>{const s=total[p];return cell(s[0])+cell(-s[1])+cell(s[2])+cell(s[2]);}).join("")+"</tr>";
 const warning=document.getElementById("missing-warning");warning.hidden=missing.length===0;
 warning.textContent=missing.length?`選択した条件に未収録が${missing.length}商品場あります。累計は収録済みだけで、0円補完していません。`:"";
 document.getElementById("selected-summary").innerHTML=products.map(product=>{
  const s=stats(selected(product)),name=product==="TOPIX"?"TOPIXミニ":"日経マイクロ";
  return `<article><h2>${name}・昼夜合計</h2><div class="metrics"><div><span>収支</span><b class="${s.net<0?"negative":"positive"}">${money(s.net)}円</b></div><div><span>黒／赤／無取引</span><b>${counts(s)}</b></div><div><span>最大赤字</span><b>${money(-s.maximum_loss)}円</b></div><div><span>上位3黒字除外</span><b>${money(s.without_top3)}円</b></div><div><span>収録場数／新規数</span><b>${s.sessions}場／${s.entries}回</b></div></div></article>`;
 }).join("");
 document.getElementById("split-body").innerHTML=kinds.flatMap(kind=>products.map(product=>{
  const key=chosen(kind,product),s=stats(selected(product,kind));
  return `<tr><td>${kind==="Day"?"日中":"夜間"} ${product}</td><td>${escapeHtml(key)}</td>${cell(s.net)}<td>${counts(s)}</td>${cell(-s.maximum_loss)}${cell(s.without_top3)}<td>${s.entries}</td></tr>`;
 })).join("");
}
/**
 * 機能: 全候補の保存会計を区分・商品別に表示する。
 * 引数: なし。saved.rowsを参照する。
 * 返り値: なし。比較表だけを作る。
 */
function showComparisons(){
 const groups=new Map();
 for(const row of saved.rows){const key=`${row.key}|${row.kind}|${row.symbol}`;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
 document.getElementById("comparison-body").innerHTML=[...groups.values()].map(rows=>{
  const first=rows[0],s=stats(rows);
  return `<tr><td>${escapeHtml(first.key)}</td><td>${first.kind==="Day"?"日中":"夜間"}</td><td>${first.symbol}</td>${cell(s.net)}<td>${counts(s)}</td>${cell(-s.maximum_loss)}${cell(s.without_top3)}<td>${s.entries}</td></tr>`;
 }).join("");
 const list=document.createElement("ul");
 for(const source of saved.reads){
  const item=document.createElement("li"),link=document.createElement("a");
  link.href="../../"+source.path;link.textContent=source.path;item.append(link);
  const digest=document.createElement("small");digest.textContent=" / SHA256 "+source.sha256;
  item.append(digest);list.append(item);
 }
 document.getElementById("source-links").append(list);
}
for(const kind of kinds)for(const product of products)document.getElementById(`${kind}-${product}`).addEventListener("change",update);
showComparisons();update();
</script></body></html>"""
    for key,value in dict(TITLE=html.escape(title),HEADLINE=html.escape(headline),FINDING=html.escape(finding),
                          CONTROLS="".join(controls),LINKS=link_html,DATA=payload).items():
        template = template.replace("__"+key+"__", value)
    return template


def main():
    """
    機能: 指定された保存会計と外部結論から公開用HTMLと表示証拠を作る。
    引数: --rounds(list[str])、--conclusion(str)、--output(str任意)、--no-baseline(bool)はCLI指定。
    返り値: None。書込み先は本作業の公開領域又はreportworkに限定する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", nargs="+", required=True)
    parser.add_argument("--conclusion", required=True)
    parser.add_argument("--output", default=str(PUBLIC/DEFAULT_NAME))
    parser.add_argument("--no-baseline", action="store_true")
    args = parser.parse_args()
    folders = [(Path(v) if Path(v).is_absolute() else HERE/v).resolve() for v in args.rounds]
    assert all(p.is_relative_to(HERE.resolve()) for p in folders)
    conclusion_path = Path(args.conclusion)
    if not conclusion_path.is_absolute():
        conclusion_path = HERE/conclusion_path
    conclusion, conclusion_ref = read_document(conclusion_path.resolve())
    data = collect(folders, conclusion, not args.no_baseline)
    data["reads"].append(conclusion_ref)
    target = Path(args.output).resolve()
    assert target.is_relative_to(PUBLIC.resolve()) or target.is_relative_to(REPORT.resolve()), target
    target.parent.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    rendered = document(data, conclusion)
    target.write_text(rendered, encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_data = REPORT/("表示用データ_"+stamp+".json")
    output_data.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    proof = dict(passed=True, output=target.relative_to(ROOT).as_posix(),
        output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        data=output_data.relative_to(ROOT).as_posix(), rows=len(data["rows"]),
        sessions=len(data["sessions"]), analysis_checks=data["analysis_checks"],
        sources=data["reads"], script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        financial_replays=0, note="保存数値の表示準備。ブラウザーの全選択・全セル確認は別途。")
    (REPORT/("表示準備_"+stamp+".json")).write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(target.as_posix(), len(data["sessions"]), "場", len(data["rows"]), "保存行")


if __name__ == "__main__":
    main()
