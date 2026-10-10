"""各パーツの実行可能損益と出口だけの診断を分けて暗色HTMLにする。"""

from __future__ import annotations

from html import escape
import json
from pathlib import Path

import replay_parts as replay
import component_signals
import warm_component_signals

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00041_入口途中出口の分解検証'
FIELDS=('gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units')
CSS='''
:root{color-scheme:dark;background:#0b121b;color:#e5edf8;font-family:Meiryo,sans-serif}body{max-width:1250px;margin:auto;padding:26px;line-height:1.8}a{color:#8bcaff}h1{font-size:26px}h2{font-size:20px;margin-top:26px}p{margin:12px 0}.muted{color:#acbed5}.box{background:#132237;border:1px solid #334b68;padding:18px;border-radius:10px;margin:16px 0}.warn{border-left:4px solid #f2bd77}select{font:inherit;background:#17283d;color:#ecf4ff;border:1px solid #536d8d;padding:7px;max-width:100%;width:100%}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px 10px;border-bottom:1px solid #2a405b;text-align:right;white-space:nowrap}th{background:#172b43;color:#bfd5ef}td:first-child,th:first-child{text-align:left}tr.total{background:#142b34;font-weight:bold}.gain{color:#79dcb5}.loss{color:#ff9cab}code{overflow-wrap:anywhere;font-size:12px}details{border:1px solid #2b415b;padding:14px;margin-top:16px}summary{cursor:pointer}button{background:#183755;color:#e8f4ff;padding:7px;border:1px solid #477496}
'''


def read(name: str) -> object:
    """機能: 今作業のJSONを読み出す。

    引数: name(str)。返り値: 内容(object)。
    """
    return replay.previous.read(HERE/name)


def minimal(row: dict, label: str | None = None, total: bool = False) -> dict:
    """機能: 金額と枚数の表示に必要な列だけを取り出す。

    引数: row(dict)、label(str|None)、total(bool)。返り値: 表示行(dict)。
    """
    value={field:(0 if row[field]==0 else row[field]) for field in FIELDS}
    assert abs(value['gross_profit_yen']-value['gross_loss_yen']-value['net_yen'])<1e-5
    value.update(symbol=row['symbol'],label=label or row['session'].replace('_Day',' デイ').replace('_Night',' ナイト'),total=total)
    value['money_ratio']=value['gross_profit_yen']/value['gross_loss_yen'] if value['gross_loss_yen'] else None
    value['unit_ratio']=(value['gross_profit_yen']/value['profit_units'])/(value['gross_loss_yen']/value['loss_units']) if value['profit_units'] and value['loss_units'] and value['gross_loss_yen'] else None
    return value


def display_rows(rows: list[dict]) -> list[dict]:
    """機能: 全セッションと各週・全期間合計を銘柄内で加算する。

    引数: rows(list[dict])。返り値: 表示行(list[dict])。
    """
    result=[]
    for symbol in ('TOPIX','NK225'):
        selected=sorted([r for r in rows if r['symbol']==symbol],key=lambda r:r['session'])
        assert len(selected)==len({r['session'] for r in selected})
        result += [minimal(r) for r in selected]
        periods=[('第1週 9/21〜25',[r for r in selected if r['session'][:10]<='2026-09-25']),
                 ('第2週 9/28〜29',[r for r in selected if r['session'][:10]>='2026-09-28']),
                 (f'全{len(selected)}セッション',selected)]
        for label,part in periods:
            if not part:continue
            total={f:sum(r[f] for r in part) for f in FIELDS};total['symbol']=symbol
            result.append(minimal(total,label,True))
    return result


def entry_description(spec: dict) -> str:
    """機能: 入口の数値と暖機の違いを短い日本語へ変換する。

    引数: spec(dict)。返り値: 説明(str)。
    """
    warm='reset' in spec;value=spec['reset'] if warm else spec
    scale=value['main_scale']
    return ('前場の確定足でEMA暖機。' if warm else 'EMAを各場で初期化。')+f"EMA{round(15*scale)}/{round(60*scale)}・相手確認{'あり' if value['peer_confirm'] else 'なし'}・"+(f"短期{round(30*value['short_scale'])}秒確認" if value['short_confirm'] else '短期確認なし（保持時間も変化）')+'。追跡新規0.25ATR、元出口は1ATR損切り・2ATR部分利確・3ATR追跡・360分。'


def viewer(title: str, methods: list[dict], diagnostic: bool = False) -> str:
    """機能: 全方式を切替表示する内蔵型HTMLを作る。

    引数: title(str)、methods(list[dict])、diagnostic(bool)。返り値: HTML(str)。
    """
    data=json.dumps(methods,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</',r'<\/')
    warning='同じ元建玉から出口だけを変えた独立実験です。建玉が重なる条件もあり、この診断収支を実運用口座の利益とは扱いません。' if diagnostic else '入口と途中判断の部品比較は既知13セッション。追加ナイトを含む固定方式は14セッション。期間を混ぜて順位付けしません。'
    script='''
const methods=JSON.parse(document.getElementById('financial-data').textContent),select=document.getElementById('method'),nf=new Intl.NumberFormat('ja-JP');
/**
 * 機能: 選択した方式の全セッション・週・全期間損益を表示する。
 * @returns {undefined} 返り値なし。
 */
function render(){const m=methods[Number(select.value)];document.getElementById('identifier').textContent=m.id;document.getElementById('description').textContent=m.description;
 document.getElementById('profits').innerHTML=m.rows.map(r=>`<tr class="${r.total?'total':''}"><td>${r.symbol==='TOPIX'?'TOPIXミニ':'NKマイクロ'}</td><td>${r.label}</td><td>${nf.format(r.gross_profit_yen)}</td><td>${nf.format(r.gross_loss_yen)}</td><td class="${r.net_yen>=0?'gain':'loss'}">${nf.format(r.net_yen)}</td><td>${r.profit_units}</td><td>${r.loss_units}</td><td>${r.profit_units-r.loss_units}</td><td>${r.zero_units}</td><td>${r.money_ratio===null?'—':r.money_ratio.toFixed(2)}</td><td>${r.unit_ratio===null?'—':r.unit_ratio.toFixed(2)}</td></tr>`).join('');}
methods.forEach((m,i)=>{const o=document.createElement('option');o.value=i;o.textContent=m.group+'｜'+m.name;select.append(o);});
const requested=new URLSearchParams(location.search).get('method')||'F50__E10',found=methods.findIndex(m=>m.id===requested);select.value=found>=0?found:0;select.addEventListener('change',render);render();
'''
    return f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>{CSS}</style><body>
<a href="分解と結論.html">分解と結論へ</a><h1>{escape(title)}</h1><p class="box warn">{warning}</p>
<!--
[コンポーネント概要]
#method は条件を切り替え、#profits はその方式の全セッション・週・全期間の金額と返済枚数を表示します。
#identifier は再現用ID、#description は日本語の短い条件説明です。外部通信や売買実行はありません。
-->
<label>方式 <select id="method"></select></label><p><code id="identifier"></code></p><p id="description"></p>
<p class="muted">費用0・指定値約定。TOPIXミニ1pt＝1,000円、NKマイクロ1pt＝10円。買い・売りそれぞれの保有上限は10枚／20枚。勝ち枚・負け枚は期間内に返済した延べ枚数で、同時保有上限とは別です。</p>
<div class="scroll"><table><thead><tr><th>銘柄</th><th>期間</th><th>利益円</th><th>損失円</th><th>{'診断' if diagnostic else ''}収支円</th><th>勝ち枚</th><th>負け枚</th><th>枚数差</th><th>同値枚</th><th>利益/損失額</th><th>1枚平均勝敗比</th></tr></thead><tbody id="profits"></tbody></table></div>
<p class="muted">1枚平均勝敗比＝（利益額÷勝ち枚数）÷（損失額÷負け枚数）。枚数差は勝ち枚−負け枚の集計であり、残っている建玉ではありません。比率の分母がない期間は「—」。損失は正の金額で表示します。</p>
<script type="application/json" id="financial-data">{data}</script><script>{script}</script></body></html>'''


def main() -> None:
    """機能: 完了済み全条件を省略せず実行損益と出口診断の別HTMLへ出す。

    引数: なし。返り値: なし(None)。公表索引の更新は行わない。
    """
    methods=[]
    for item in read('combined_baselines.json'):
        methods.append(dict(id=item['id'],name=item['name'],group='既存固定方式・追加ナイト込み',
            description='入口H019・元出口D273。減量と回復後復元の違いを固定したまま追加ナイトへ適用。',rows=display_rows(item['sessions'])))
    for spec in component_signals.catalog()+warm_component_signals.catalog():
        for base in replay.BASE_IDS:
            identifier=spec['id']+'__'+base
            rows=read('entry_sessions/'+identifier+'.json.gz')
            methods.append(dict(id=identifier,name=identifier,group='EMA暖機比較' if 'reset' in spec else '入口部品比較',
                description=entry_description(spec)+' 途中管理 '+base,rows=display_rows(rows)))
    mid=read('mid_result.json');assert mid['全合格']
    for condition in mid['条件別']:
        spec=condition['spec'];policy=spec['policy']
        description='数量調整なし。' if policy['kind']!='dynamic' else (
            (f"初回建値から{spec['gate_threshold_atr']:g}ATR順行後の新しい悪化で、" if spec['gate_threshold_atr']>0 else '順行到達ゲートなし。新しい悪化で、')+f"生存枠の{policy['reduce_fraction']:.0%}を一度減量。"+
            {'none':'復元しない。','signal':'回復方向の新情報を確認して復元。','timer':'有効な新しい公開を伴う120秒経過後に復元。'}[policy['restore_mode']])
        methods.append(dict(id='MID_'+spec['id'],name=spec['id'],group='途中判断比較',description=description,
            rows=display_rows([r for r in mid['全セッション'] if r['id']==spec['id']])))
    extra=HERE/'integrated_financial_methods.json'
    if extra.exists():methods+=read(extra.name)
    assert len({m['id'] for m in methods})==len(methods)
    # ----------------------------------------
    # 独立元組の出口診断は、実行可能な口座群とは別資料にする。
    diagnostics=[]
    for condition in read('exit_results.json')['結果']:
        rows=[]
        for symbol,periods in condition['symbols'].items():
            for name,value in periods.items():
                if not name.startswith('2026-'):continue
                rows.append(dict(symbol=symbol,session=name,gross_profit_yen=value['利益円'],gross_loss_yen=value['損失円'],
                    net_yen=value['診断収支円'],profit_units=value['利益枚数'],loss_units=value['損失枚数'],zero_units=value['同値枚数']))
        diagnostics.append(dict(id=condition['id'],name=condition['name'],group='出口だけの独立診断',
            description='旧A0の同じ102初回建玉を全て使用。元終了行で打ち切らず、自身の出口又は場末まで追跡。',rows=display_rows(rows)))
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'全条件の損益.html').write_text(viewer('パーツ別・全条件の損益',methods),encoding='utf-8')
    (OUT/'出口単独の比較.html').write_text(viewer('出口13条件・同じ建玉での比較',diagnostics,True),encoding='utf-8')
    replay.save(HERE/'financial_report_manifest.json',dict(方式数=len(methods),損益行数=sum(len(m['rows']) for m in methods),
        出口診断数=len(diagnostics),出口診断行数=sum(len(m['rows']) for m in diagnostics),全方式ID=[m['id'] for m in methods]))
    print(f'口座方式{len(methods)}件、出口診断13件を別HTMLへ保存。',flush=True)


if __name__=='__main__':main()
