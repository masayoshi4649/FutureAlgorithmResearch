"""結果の指定SHAを一度だけ読み、選択期で固定した少数候補の全場損益を表示する。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import statistics


HERE=Path(__file__).resolve().parent
DEFAULT_OUTPUT=HERE/'public00119_戦略の自動選択と場内黒字の再探索'
HTML_NAME='戦略の自動選択と全セッション損益.html'
SYMBOLS=('TOPIX','NK225')
PERIODS=('全40','確認13','追加確認3')
ADAPTIVE_FAMILY='ADAPT'
MONEY_FIELDS=('net','realized','profit','loss','fees','max_drawdown')
COUNT_FIELDS=('parents','wins','losses','closed_quantity','unclosed','canceled','fills','halted')
NULLABLE_FIELDS=('canceled','fills','halted')
SUMMARY_FIELDS=MONEY_FIELDS+COUNT_FIELDS
EPS=1e-7


def digest(data: bytes) -> str:
    """
    機能: 与えられた保存bytesの指紋を求める。
    引数: data(bytes)は既に一読した内容。
    返り値: strはSHA256。市場ファイルを追加取得しない。
    """
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    """
    機能: 有限値の日本語JSONをUTF-8へ直列化する。
    引数: value(object)は公開用の小会計又は生成証跡。
    返り値: bytes。NaNやInfinityを保存しない。
    """
    return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8')


def text(value: object) -> str:
    """
    機能: 保存文字列をHTML本文又は属性へ安全に埋め込む。
    引数: value(object)は手法名・説明・IDなど。
    返り値: strは引用符もエスケープした文字列。
    """
    return html.escape(str(value),quote=True)


def number(value: float|None,signed: bool=False,decimal: int=0) -> str:
    """
    機能: 金額を千位区切りで表示し、未定義の割合をゼロへ補完しない。
    引数: value(float|None)、signed(bool)、decimal(int)は表示条件。
    返り値: str。微小な負ゼロだけゼロとして表示する。
    """
    if value is None:
        return '—'
    val=0. if abs(float(value))<=EPS else float(value)
    if val==0:
        return '0'
    return format(val,('+' if signed else '')+',.'+str(decimal)+'f')


def validate(data: dict) -> tuple[dict,dict]:
    """
    機能: 四十場・二商品・全手法の小会計と、選択期の固定メタデータを検査する。
    引数: data(dict)は根担当が完成SHAを指定した結果、又は完全合成人工。
    返り値: tuple[dict,dict]は仕様ID表と(session,symbol,method)別の小会計。
        実価格・注文台帳・因果教師の再検査は行わない。
    """
    sessions=data['sessions'];splits=data['splits']
    assert len(sessions)==len(set(sessions))==40,'四十場の一意な目録が必要です。'
    assert all(isinstance(s,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}_(Day|Night)',s) for s in sessions)
    for label,count in [('設計参照21',21),('選択6',6),('既知確認10',10),('追加確認3',3),('確認13',13),('全40',40)]:
        assert len(splits[label])==len(set(splits[label]))==count
        assert [s for s in sessions if s in splits[label]]==splits[label]
    assert splits['全40']==sessions
    assert splits['設計参照21']+splits['選択6']+splits['確認13']==sessions
    assert splits['既知確認10']+splits['追加確認3']==splits['確認13']
    specs={s['id']:s for s in data['specs']}
    assert len(specs)==len(data['specs']) and specs and 'PORT' not in specs
    for ident,spec in specs.items():
        assert isinstance(ident,str) and ident
        for key in ('family','name','description'):
            assert isinstance(spec[key],str) and spec[key].strip(),(ident,key)
        assert isinstance(spec['is_adaptive'],bool)
        assert spec['exit_mode'] in (0,1,2) and spec['entry_mode'] in (0,1) and spec['guard'] in (0,1)
    rows={}
    for collection,methods in [('runs',set(specs)),('portfolios',{'PORT'})]:
        items=data[collection]
        assert len(items)==40*2*len(methods),(collection,'全場が必要です。')
        for source in items:
            key=source['session'],source['symbol'],source['method']
            assert key[0] in sessions and key[1] in SYMBOLS and key[2] in methods and key not in rows
            row=dict(session=key[0],symbol=key[1],method=key[2])
            for name in MONEY_FIELDS:
                val=source[name];assert isinstance(val,(int,float)) and not isinstance(val,bool) and math.isfinite(val),(key,name)
                row[name]=float(val)
            for name in COUNT_FIELDS:
                val=source[name]
                if name in NULLABLE_FIELDS and val is None:
                    row[name]=None
                    continue
                assert isinstance(val,(int,float)) and not isinstance(val,bool) and math.isfinite(val) and int(val)==val and val>=0,(key,name)
                row[name]=int(val)
            if collection=='portfolios':
                assert source.get('max_drawdown_is_upper_bound') is True
                row['max_drawdown_is_upper_bound']=True
            assert min(row['profit'],row['loss'],row['fees'],row['max_drawdown'])>=-EPS
            assert row['wins']+row['losses']<=row['parents']
            if row['unclosed']==0:
                assert abs(row['net']-row['realized'])<=1e-5,(key,'返済完了の現金一致')
                assert abs(row['profit']-row['loss']-row['realized'])<=1e-5,(key,'完結親P/L一致')
            if row['fills']==0:
                assert row['parents']==row['unclosed']==0 and abs(row['net'])<=EPS,(key,'無取引は利益でない')
            rows[key]=row
    for symbol in SYMBOLS:
        sel=data['selection'][symbol];chosen=sel['chosen'];eligible=sel['eligible_ids'];rank=sel['ranking']
        assert isinstance(sel['qualified'],bool)
        assert len(chosen)==len(set(chosen))<=3 and all(i in specs for i in chosen)
        assert len(eligible)==len(set(eligible)) and all(i in specs for i in eligible)
        assert all(i in eligible for i in chosen)
        assert len(rank)==len({r['id'] for r in rank})==len(specs)
        assert all(r['id'] in specs and isinstance(r['metrics'],dict) for r in rank)
        if sel['qualified']:
            assert chosen,'資格合格なのに採用源がありません。'
        else:
            assert not chosen
        assert len({specs[i]['family'] for i in chosen})==len(chosen)
    assert isinstance(data['source_SHA256'],dict) and data['source_SHA256']
    assert isinstance(data['cache'],list) and isinstance(data['read_log'],(list,dict))
    return specs,rows


def inactive(row: dict) -> bool:
    """
    機能: 約定回数の欠損をゼロ補完せず、親・残玉・料の会計条件から無取引を判定する。
    引数: row(dict)は必須会計と、nullableなfillsを持つ場集計。
    返り値: boolは無取引。fills不明のときも約定回数そのものを推定して保存しない。
    """
    if row['fills'] is not None:
        return row['fills']==0
    return row['parents']==row['closed_quantity']==row['unclosed']==0 and abs(row['fees'])<=EPS and abs(row['net'])<=EPS and abs(row['realized'])<=EPS


def candidates(data: dict,specs: dict) -> tuple[list[str],dict]:
    """
    機能: 保存済み選択順位から代表と自動選択代表を取り、PORTを加えて重複を除く。
    引数: data/specs(dict)は完成した選択結果と仕様。
    返り値: tuple[list[str],dict]は最大五IDと選定理由。確認期・全期の収支を参照しない。
    """
    result=[];why={}
    for symbol in SYMBOLS:
        rank=data['selection'][symbol]['ranking']
        picks=[(rank[0]['id'],symbol+'の選択6場・先頭順位')]
        adaptive=[r['id'] for r in rank if specs[r['id']].get('is_adaptive') is True or specs[r['id']]['family']==ADAPTIVE_FAMILY]
        if adaptive:
            picks.append((adaptive[0],symbol+'の選択6場・自動選択内の先頭順位'))
        for ident,reason in picks:
            if ident not in result:result.append(ident)
            why.setdefault(ident,[]).append(reason)
    if 'PORT' not in result:result.append('PORT')
    why['PORT']=['商品別の選択6場で固定した最大三つの源を、実枚数枠で再運転']
    assert 1<=len(result)<=5
    return result,why


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 掲載期間の親P/Lと場収支を別々に再集計する。
    引数: rows(list[dict])は同じ商品・方法の期間小会計。
    返り値: dictは黒字赤字・無取引・零収支・未清算、平均・中央値・最悪等。
        未清算場は成功に数えず、上位黒字除外の成功値も作らない。
    """
    assert rows
    count=Counter();nets=[];black=[]
    for row in rows:
        nets.append(row['net'])
        if row['unclosed']:
            count['unclosed_sessions']+=1
        elif inactive(row):
            count['inactive']+=1
        elif row['net']>EPS:
            count['positive']+=1;black.append(row['net'])
        elif row['net']<-EPS:
            count['negative']+=1
        else:
            count['flat']+=1
    p=sum(r['profit'] for r in rows);l=sum(r['loss'] for r in rows);net=sum(nets)
    unclosed=count['unclosed_sessions']
    assert sum(count.values())==len(rows)
    return dict(sessions=len(rows),profit=p,loss=l,net=net,realized=sum(r['realized'] for r in rows),
        positive=count['positive'],negative=count['negative'],inactive=count['inactive'],flat=count['flat'],
        unclosed_sessions=unclosed,mean=statistics.mean(nets),median=statistics.median(nets),worst=min(nets),
        top3_positive_excluded=net-sum(sorted(black,reverse=True)[:3]) if not unclosed else None,
        profit_share=p/(p+l) if p+l>EPS else None,parents=sum(r['parents'] for r in rows),
        wins=sum(r['wins'] for r in rows),losses=sum(r['losses'] for r in rows),
        closed_quantity=sum(r['closed_quantity'] for r in rows),fees=sum(r['fees'] for r in rows),
        all_sessions_positive=not unclosed and count['positive']==len(rows))


def explanation(ident: str,specs: dict) -> str:
    """
    機能: 候補の思想と注文・退出の違いを短い日本語へ整える。
    引数: ident(str)、specs(dict)は保存仕様。
    返り値: strは説明。数値結果から有望さを付け足さない。
    """
    if ident=='PORT':
        return '選択6場だけで決めた異なる源へ最大三枠を割り当て、同時に運転します。源ごとの損失を隠さず、全玉の返済と費用を合計します。'
    spec=specs[ident];base=spec['description'].strip()
    if spec['is_adaptive']:
        horizon=spec.get('horizon_minutes')
        label=str(horizon)+'分' if horizon in (20,60,120) else '固定窓'
        choice='異なる家族の上位二つが同方向のときだけ入ります。' if spec.get('method')=='distinct_family_consensus' else '最上位の教師が向く方向へ入ります。'
        base='過去'+label+'の含み損を含む全玉清算資産と下落幅を比べ、'+choice
    exits={0:'利確幅0.8・損切り幅1.2',1:'1幅順行後に1幅で追尾',2:'1幅で半分返済し、残りを広く追尾'}
    entries={0:'成行',1:'公開価格より0.2幅有利な指値'}
    detail=[]
    if spec.get('entry_mode') in entries:detail.append(entries[spec['entry_mode']])
    if spec.get('exit_mode') in exits:detail.append(exits[spec['exit_mode']])
    if spec.get('guard'):detail.append('場の損益枠で停止')
    return base+(' 注文・退出は'+ '、'.join(detail)+'です。' if detail else '')


def render(data: dict,specs: dict,rows: dict,chosen: list[str],why: dict,result_sha: str,source_result: Path|None=None) -> tuple[str,dict,str]:
    """
    機能: 少数候補のダークHTML、明細なし公開会計、案内Markdownを作る。
    引数: data/specs/rows/why(dict)、chosen(list[str])、result_sha(str)、source_result(Path|None)は一読した結果。
    返り値: tuple[str,dict,str]は表示成果物。金融や候補の再選択を行わない。
    """
    sessions=data['sessions'];cases={};panels=[];chapters=[]
    for ident in chosen:
        cases[ident]=dict(spec=specs.get(ident,dict(id='PORT',family='PORT',name='三枠の固定配分',description=explanation(ident,specs))),
            selected_by=why[ident],eligibility={sym:(data['selection'][sym]['qualified'] if ident=='PORT' else ident in data['selection'][sym]['eligible_ids']) for sym in SYMBOLS},
            rows=[rows[s,sym,ident] for s in sessions for sym in SYMBOLS],periods={})
        for symbol in SYMBOLS:
            cases[ident]['periods'][symbol]={label:aggregate([rows[s,symbol,ident] for s in data['splits'][label]]) for label in PERIODS}
    for label in PERIODS:
        body=[]
        for idx,ident in enumerate(chosen,1):
            for symbol in SYMBOLS:
                value=cases[ident]['periods'][symbol][label]
                share='—' if value['profit_share'] is None else f"{value['profit_share']*100:.1f}%"
                body.append('<tr data-method="'+text(ident)+'" data-symbol="'+symbol+'">'+
                    '<th><a href="#case'+str(idx)+'">'+text(str(idx)+' '+cases[ident]['spec']['name'])+'</a></th><td>'+symbol+'</td>'+
                    '<td>'+f"{value['positive']}/{value['negative']}/{value['inactive']}"+'</td><td>'+f"{value['flat']}/{value['unclosed_sessions']}"+'</td>'+
                    ''.join('<td>'+number(value[k],True,1 if k in ('mean','median') else 0)+'</td>' for k in ('mean','median','worst','top3_positive_excluded'))+
                    '<td>'+share+'</td></tr>')
        panels.append('<div class="period-panel" data-period="'+text(label)+'"'+(' hidden' if label!='確認13' else '')+'><div class="table-wrap"><table><caption>'+text(label)+'の場収支</caption><thead><tr><th>候補</th><th>商品</th><th>黒／赤／無</th><th>零／未清算</th><th>平均円</th><th>中央値円</th><th>最悪円</th><th>上位3黒字除外円</th><th>金額利益割合</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div></div>')
    for idx,ident in enumerate(chosen,1):
        spec=cases[ident]['spec'];lines=[]
        for scene in sessions:
            cells=['<th>'+text(scene.replace('_Day',' デイ').replace('_Night',' ナイト'))+'</th>']
            for symbol in SYMBOLS:
                r=rows[scene,symbol,ident];state='未清算'+str(r['unclosed'])+'枚' if r['unclosed'] else '—'
                cells.extend('<td>'+v+'</td>' for v in (number(r['profit']),number(r['loss']),number(r['net'],True),str(r['parents']),state))
            lines.append('<tr data-session="'+text(scene)+'">'+''.join(cells)+'</tr>')
        footer=['<th>全40場合計</th>']
        for symbol in SYMBOLS:
            v=cases[ident]['periods'][symbol]['全40']
            footer.extend('<td>'+v0+'</td>' for v0 in (number(v['profit']),number(v['loss']),number(v['net'],True),str(v['parents']),str(v['unclosed_sessions'])+'場' if v['unclosed_sessions'] else '—'))
        selected_note='／'.join(why[ident])+'。選択6場の資格：'+ '・'.join(sym+('達成' if cases[ident]['eligibility'][sym] else '未達・比較用') for sym in SYMBOLS)
        chapters.append('<section id="case'+str(idx)+'"><h2>'+text(str(idx)+' '+spec['name'])+'</h2><p>'+text(explanation(ident,specs))+'</p><p class="muted"><code>'+text(ident)+'</code> '+text(selected_note)+'</p><details><summary>全40場の利益・損失・収支・取引数</summary><div class="table-wrap"><table class="sessions" data-method="'+text(ident)+'"><thead><tr><th rowspan="2">セッション</th><th colspan="5">TOPIXミニ</th><th colspan="5">日経マイクロ</th></tr><tr>'+2*'<th>利益円</th><th>損失円</th><th>収支円</th><th>取引数</th><th>未清算</th>'+'</tr></thead><tbody>'+''.join(lines)+'</tbody><tfoot><tr>'+''.join(footer)+'</tr></tfoot></table></div></details></section>')
    portfolio='　'.join(symbol+': '+('、'.join(data['selection'][symbol]['chosen']) or '選択資格を満たす源なし') for symbol in SYMBOLS)
    trial_note='全'+str(len(specs))+'条件から、選択6場の順位だけで掲載'+str(len(chosen))+'候補を固定しました。'
    any_qualified=any(data['selection'][symbol]['qualified'] for symbol in SYMBOLS)
    notice='選択6場で固定した候補です。確認13場と追加3場の結果を、候補選びへ戻していません。' if any_qualified else '選択6場の資格を満たす候補はありません。以下の代表は比較用で、採用推奨ではありません。'
    css='body{margin:0;background:#0b1120;color:#e5edf9;font:16px/1.65 system-ui,sans-serif}main{max-width:1420px;margin:auto;padding:26px 20px}a{color:#8fc6ff}h1{font-size:27px}h2{font-size:20px;margin-top:28px}.note{background:#17243a;border-left:4px solid #77b8fc;padding:12px 16px}.muted{color:#aebdd3;font-size:14px}p{max-width:1120px}.table-wrap{overflow-x:auto;width:100%;border:1px solid #344256;border-radius:8px}table{border-collapse:collapse;white-space:nowrap;width:100%;font-size:14px}th,td{padding:8px 10px;text-align:right;border-bottom:1px solid #344256}th:first-child{text-align:left}thead,tfoot{background:#19283f}caption{text-align:left;padding:10px;color:#c1d9f5;font-weight:600}button{background:#17243a;border:1px solid #527299;color:#e5edf9;border-radius:6px;padding:8px 14px;margin:0 8px 10px 0;cursor:pointer}button[aria-selected=true]{background:#315988}summary{cursor:pointer;color:#a8d0ff;padding:9px 0}code{overflow-wrap:anywhere}.period-panel[hidden]{display:none}@media(max-width:600px){main{padding:16px 10px}h1{font-size:23px}body{font-size:15px}th,td{padding:8px}}'
    script='''/**
 * 機能: 選択済みの比較期間だけを表示します。
 * @param {string} label - 全40、確認13、追加確認3の表示名。
 * @returns {void} 表示状態だけを変更し、計算や候補選択は行いません。
 */
function showPeriod(label) {
  document.querySelectorAll('.period-panel').forEach(function(panel) {
    panel.hidden = panel.dataset.period !== label;
  });
  document.querySelectorAll('[data-period-button]').forEach(function(button) {
    button.setAttribute('aria-selected', String(button.dataset.periodButton === label));
  });
}
document.querySelectorAll('[data-period-button]').forEach(function(button) {
  button.addEventListener('click', function() { showPeriod(button.dataset.periodButton); });
});'''
    doc='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>戦略の自動選択と全セッション損益</title><style>'+css+'</style></head><body><!--\n[コンポーネント概要]\nmainは既に固定された少数候補と期間別成績を表示します。\n.period-panelは全40・確認13・追加3の切替表、.table-wrapは表だけの横スクロール領域です。\n各sectionは一つの候補の思想と全40場の会計を表示します。未清算・無取引を勝ちに数えません。\n外部通信、金融再生、候補再選択は行いません。\n--><main><h1>戦略の自動選択と全セッション損益</h1><p class="note">'+text(notice)+'</p><p>単体はTOPIXミニ10枚・日経マイクロ20枚。PORTは最大三枠の4＋3＋3枚／8＋6＋6枚です。手数料とラージ気配差を含め、場内返済を試みます。未清算が残った場は成功に数えません。</p><p class="muted">'+text(trial_note)+' 設計参照21場→選択6場→確認13場（既知10＋追加3）。追加3場は今回の選択に未使用ですが、全過去研究から完全に未見だったとは保証しません。黒・赤は場の差引収支、利益・損失は完結親ごとの相殺前合計です。</p><div role="tablist" aria-label="比較期間">'+''.join('<button type="button" data-period-button="'+text(label)+'" aria-selected="'+str(label=='確認13').lower()+'">'+text(label)+'</button>' for label in PERIODS)+'</div>'+''.join(panels)+'<p class="muted">黒／赤／無は黒字場・赤字場・無取引場。零は取引ありの零収支。未清算は別集計し、最終の収支は残玉の気配清算評価を含みます。未清算がある期間の上位3黒字除外は未評価。金額利益割合はP÷(P＋L)、P=L=0は—です。教師の良い過去成績は将来の予測確率ではありません。</p><h2>固定配分の中身</h2><p class="muted">'+text(portfolio)+'</p>'+''.join(chapters)+'<p class="muted">実ミニ・マイクロの板や待ち順位は未観測です。原行・価格時計による次正常BBOの代理約定で、真の受信時刻・実約定を証明した結果ではありません。多数の条件は同じ市場を共有し、独立した成功標本ではありません。</p><p><a href="公開会計.json">掲載候補の小会計</a>　<a href="README.md">案内と再現範囲</a></p></main><script>'+script+'</script></body></html>'
    project=HERE.parents[1]
    result_file=source_result.resolve() if source_result is not None else HERE/'measurement/戦略自動選択と全四十場の結果.json'
    final_public=project/'アルゴリズム調査/00119_戦略の自動選択と場内黒字の再探索'
    result_link=Path(os.path.relpath(result_file,final_public)).as_posix()
    public=dict(sessions=sessions,splits=data['splits'],candidate_ids=chosen,selection_reasons=why,
        cases=cases,selection={s:{k:data['selection'][s][k] for k in ('chosen','qualified','eligible_ids')} for s in SYMBOLS},
        result_SHA256=result_sha,source_SHA256=data['source_SHA256'],金融再生=0,原入力読取=0,市場取得=0,
        数量='単体TOPIXmini10/NK225micro20。PORTは最大三枠4/3/3と8/6/6。',
        未清算='終端netは評価を含む。未清算場を成功へ分類せず、親P/Lへ未清算評価を加えない。',
        PORT時価下落='max_drawdownは各枠の最大下落合計という上界。同時資産の実最大下落ではない。',
        元結果位置=result_file.relative_to(project).as_posix(),
        未保存メタ='取消・約定・停止回数が保存されていなければnullを保持。約定回数をゼロへ補完しない。')
    readme='# 00119 戦略の自動選択と場内黒字の再探索\n\n最初に[戦略の自動選択と全セッション損益]('+HTML_NAME+')を開いてください。上部で全40・確認13・追加3を切り替え、各候補の全40場表は折り畳みで確認できます。\n\n代表は各商品の選択6場の先頭順位・同期間の自動選択先頭順位とPORTを合併した最大5件です。確認13・追加3・全40で順位を付け直していません。資格未達の参考候補も区別します。\n\n手数料とラージ気配差込み、単体TOPIXmini10／NK225micro20。PORTは商品別の最大三枠で実数量を再運転。無取引・未清算を勝ちに数えません。既知データでの比較で、追加3場は今回の選択から分離しています。実小型板の待ち順位と真の受信時計は未観測です。PORTのmax_drawdownは枠別最大下落の合計という上界で、同時資産の実最大下落ではありません。\n\n[公開会計](公開会計.json)は掲載候補だけの場集計で、注文明細や巨大入力を含みません。[結果前の計画](../../work/stability119_20261017/試行計画.json)と[全条件の保存結果]('+result_link+')へのリンクは正式公開先00119からの相対位置です。作業stagingではこの二本は正式配置後に確認します。全条件の保存元結果SHA256は `'+result_sha+'` です。生成器は指定SHAの完成結果だけを一度読み、市場取得・金融再生を行いません。取消・約定・停止回数が未保存なら不明のまま残し、金額・完結親・残玉の会計から無取引を区別します。家族名が異なるだけで分散効果を認定しません。\n'
    return doc,public,readme


def generate(data: dict,output: Path,result_sha: str,fixture: bool=False,source_result: Path|None=None) -> dict:
    """
    機能: 既存公開物を上書きせず、検査した小会計から成果物三点と生成証跡を保存する。
    引数: data(dict)、output(Path)、result_sha(str)、fixture(bool)、source_result(Path|None)は入力と合成検査の区別。
    返り値: dictは生成物SHAと掲載件数。市場や元結果を再読しない。
    """
    specs,rows=validate(data);picked,why=candidates(data,specs)
    doc,public,readme=render(data,specs,rows,picked,why,result_sha,source_result)
    assert not output.exists(),'既存の公開フォルダを上書きしません。'
    output.mkdir(parents=True)
    artifacts={HTML_NAME:doc.encode('utf8'),'公開会計.json':json_bytes(public),'README.md':readme.encode('utf8')}
    for name,payload in artifacts.items():(output/name).write_bytes(payload)
    proof=dict(全合格=True,合成fixture=fixture,掲載候補=len(picked),候補ID=picked,全セッション=40,
        商品場行=len(picked)*80,元全条件商品場行=len(data['runs']),PORT商品場行=len(data['portfolios']),
        元結果SHA256=result_sha,生成物SHA256={k:digest(v) for k,v in artifacts.items()},
        report_source_SHA256=digest(Path(__file__).read_bytes()),選定規則='選択6の先頭と自動選択先頭を商品別に合併しPORT追加。確認期による再選択なし。',
        市場読取=0,金融再生=0,原入力=0,大型台帳=0,API=0)
    (output/'生成証跡.json').write_bytes(json_bytes(proof))
    return proof


def main() -> None:
    """
    機能: 根が完成SHAを指定した一目的の公開生成を実行する。
    引数: CLI --result(Path)、--expected-sha256(str)、--output(Path)は保存結果と出力先。
    返り値: None。SHA未指定・不一致・既存出力の場合は公開しない。
    """
    parser=argparse.ArgumentParser(description='指定完成結果だけを一読する公開生成。市場取得なし。')
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--fixture',action='store_true',help='完全合成入力の試験と明記する。市場取得や金融再生は行わない。')
    args=parser.parse_args()
    expected=args.expected_sha256.lower()
    assert re.fullmatch(r'[0-9a-f]{64}',expected),'完成結果のSHA256を明示してください。'
    assert not args.output.exists(),'結果を読む前に既存出力を拒否します。'
    raw=args.result.read_bytes()
    assert digest(raw)==expected,'指定された完成結果の指紋と一致しません。'
    data=json.loads(raw.decode('utf8'))
    proof=generate(data,args.output,expected,fixture=args.fixture,source_result=args.result)
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
