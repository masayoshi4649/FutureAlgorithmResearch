"""選んだ手法の各場利益・損失・収支と累計だけを暗色ＨＴＭＬへ載せる。"""

import html
import json
from common126 import HERE, PUBLIC, read, sha, save


def build() -> None:
    """
    機能: 監査済み会計を商品別に表示し、既存原版との比較も選択できるようにする。
    引数: なし。
    返り値: None。価格モデルを表題で区別し、説明やランキングは主表に加えない。
    """
    combined = read(HERE / "最終統合の価格モデル別比較と公開会計.json")
    assert combined["passed"]
    descriptions = {"next_normal_bbo": "次の有効な売買気配（ラージ板代理）",
                    "observed": "観測Last（参考・気配差未反映）"}
    models = [{k: m[k] for k in ("id", "selected", "methods", "rows", "sources")}
              | dict(label=descriptions[m["id"]]) for m in combined["models"]]
    for model, full in zip(models, combined["models"]):
        if not full["minimum_passed"]:
            chosen = next(m for m in model["methods"] if m["id"] == model["selected"])
            chosen["name"] += "（条件未達の比較代表）"
    payload = dict(models=models, sessions=combined["sessions"],
        quantities="TOPIXミニ：初回5枚・上限10枚 ／ 日経マイクロ：初回10枚・上限20枚",
        note="手数料0円・全て場内返済。利益／損失は返済ごとの正負。既知41セッションの比較。")
    json_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    template = r'''<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>E01改修のセッション損益</title>
<style>
:root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#10151e;color:#e5eaf2}*{box-sizing:border-box}body{max-width:1450px;margin:0 auto;padding:28px 22px 60px}h1{font-size:23px;margin:0 0 16px}p{font-size:13px;color:#aab7ca;margin:9px 0}select{background:#1a2535;color:#eef3ff;border:1px solid #465871;border-radius:5px;padding:9px 12px;font:inherit;max-width:100%}.controls{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}label{font-size:13px;display:flex;align-items:center;gap:8px}.scroll{overflow:auto;border:1px solid #334157;border-radius:7px;margin-top:18px}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap;font-variant-numeric:tabular-nums}th,td{padding:11px 10px;text-align:right;border-bottom:1px solid #29364a}th{background:#1c293b;color:#cfdbed}th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:#151e2d}thead tr:first-child th[colspan]{text-align:center}thead{position:sticky;top:0;z-index:2}thead th:first-child{background:#1c293b}tbody tr:nth-child(even){background:#151e2b}tbody tr:hover{background:#253248}tfoot{font-weight:bold;background:#233147}.positive{color:#69dfb0}.negative{color:#ff9caa}.cumulative{border-left:1px solid #42516b}#method-title{font-size:18px;margin-top:24px;color:#e8edf7}.total-cards{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}.card{background:#182334;border:1px solid #374760;border-radius:7px;padding:14px}.card b{font-size:14px}.totals{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px;font-size:13px}.totals strong{display:block;font-size:19px;margin-top:5px}.unit{font-size:12px;text-align:right}@media(max-width:650px){body{padding:20px 12px}.total-cards{grid-template-columns:1fr}h1{font-size:20px}}
</style>
<!--
[コンポーネント概要]
#model と #method は価格モデルと表示手法を選ぶ要素です。
#totals は二商品の累計利益・損失・収支です。
#sessions は全四十一場の会計と、その場までの累計収支です。
売買判断や選定を表示時に再計算せず、監査済み会計の加算だけを行います。
-->
<h1>E01改修のセッション損益</h1>
<p id="quantities"></p><p id="note"></p>
<div class="controls"><label>約定モデル <select id="model"></select></label><label>手法 <select id="method"></select></label></div>
<div id="method-title"></div><div id="totals" class="total-cards"></div>
<p class="unit">単位：円 ／ 損失は正の額で表示</p>
<div class="scroll"><table id="sessions"><thead><tr><th rowspan="2">セッション</th><th colspan="4">TOPIXミニ</th><th colspan="4">日経225マイクロ</th></tr><tr><th>利益</th><th>損失</th><th>収支</th><th>累計収支</th><th>利益</th><th>損失</th><th>収支</th><th>累計収支</th></tr></thead><tbody></tbody><tfoot></tfoot></table></div>
<script id="accounts" type="application/json">__PAYLOAD__</script><script>
const data=JSON.parse(document.getElementById('accounts').textContent);
const model=document.getElementById('model'),method=document.getElementById('method');
const number=value=>(value===0?0:Math.round(value)).toLocaleString('ja-JP');
/**
 * 保存した金額を色付きのセルへ変換します。
 * @param {number} value - 表示する円額。
 * @param {boolean} signed - 収支の符号で色を変えるか。
 * @param {boolean} cumulative - 累計列の境界を付けるか。
 * @returns {string} 金額セルのＨＴＭＬ。
 */
function cell(value,signed=false,cumulative=false){const c=(signed?(value>0?'positive':value<0?'negative':''):'')+(cumulative?' cumulative':'');return `<td class="${c}">${number(value)}</td>`;}
/**
 * 選択した手法の全場会計と累計を描きます。
 * @returns {void} 表示を更新し、売買判断は行いません。
 */
function render(){const m=data.models.find(x=>x.id===model.value),id=method.value,rows=m.rows.filter(x=>x.method===id),lookup=new Map(rows.map(x=>[x.session+'|'+x.symbol,x]));let running={TOPIX:0,NK225:0},totals={TOPIX:[0,0,0],NK225:[0,0,0]};document.querySelector('#sessions tbody').innerHTML=data.sessions.map(s=>{let out=`<tr><td>${s.replace('_Day',' 日中').replace('_Night',' 夜間')}</td>`;for(const symbol of ['TOPIX','NK225']){const r=lookup.get(s+'|'+symbol);if(!r)throw new Error('会計欠落 '+s+symbol);running[symbol]+=r.net;totals[symbol][0]+=r.profit;totals[symbol][1]+=r.loss;totals[symbol][2]+=r.net;out+=cell(r.profit)+cell(r.loss)+cell(r.net,true)+cell(running[symbol],true,true);}return out+'</tr>';}).join('');document.querySelector('#sessions tfoot').innerHTML='<tr><td>全41セッション 累計</td>'+['TOPIX','NK225'].map(s=>cell(totals[s][0])+cell(totals[s][1])+cell(totals[s][2],true)+cell(totals[s][2],true,true)).join('')+'</tr>';document.getElementById('totals').innerHTML=['TOPIX','NK225'].map(s=>`<div class="card"><b>${s==='TOPIX'?'TOPIXミニ':'日経225マイクロ'} 累計</b><div class="totals">`+['利益','損失','収支'].map((label,i)=>`<span>${label}<strong class="${i===2?(totals[s][i]>0?'positive':totals[s][i]<0?'negative':''):''}">${number(totals[s][i])}円</strong></span>`).join('')+'</div></div>').join('');document.getElementById('method-title').textContent=id+' ｜ '+m.methods.find(x=>x.id===id).name;}
/**
 * 約定モデルに対応する手法だけを選択肢へ入れます。
 * @returns {void} 初期手法を選択して全場を描きます。
 */
function changeModel(){const m=data.models.find(x=>x.id===model.value);method.replaceChildren(...m.methods.map(x=>new Option(x.id+' ｜ '+x.name,x.id)));method.value=m.selected;render();}
document.getElementById('quantities').textContent=data.quantities;document.getElementById('note').textContent=data.note;model.replaceChildren(...data.models.map(x=>new Option(x.label,x.id)));model.addEventListener('change',changeModel);method.addEventListener('change',render);changeModel();
</script></html>'''
    target = PUBLIC / "E01改修のセッション損益.html"
    assert not target.exists()
    target.write_text(template.replace("__PAYLOAD__", json_text), encoding="utf-8")
    save(HERE / "公開会計と主表の指紋.json", dict(passed=True,
        report=target.relative_to(HERE.parents[1]).as_posix(), sha256=sha(target), payload=payload))
    print("利益・損失・収支と累計の主表を保存", flush=True)


if __name__ == "__main__":
    build()
