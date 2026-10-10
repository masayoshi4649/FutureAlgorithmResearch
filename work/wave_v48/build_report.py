"""有望4方式を入口・途中・出口とセッション別損益へ簡潔に整理する。"""

from html import escape
from datetime import date, timedelta
import gzip
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE=HERE.parent/'wave_v47'
OUT=ROOT/'アルゴリズム調査/00042_有望4手法の説明とセッション損益'
SYMBOLS={'TOPIX':dict(name='TOPIXミニ',initial=5,cap=10,multiplier=1000),
    'NK225':dict(name='NK225マイクロ',initial=10,cap=20,multiplier=10)}
FIELDS=('gross_profit_yen','gross_loss_yen','net_yen','profit_units','loss_units','zero_units')
METHODS=[
    dict(id='F50_NONE__E11',title='利益を早めに守る',width=.75,
        middle='一度1.5ATR伸びた後、直近2分と30秒がともに逆向きになったら、残っている枠の約半分を一度返済。減らした分は戻しません。',
        benefit='減量後の買い直し・売り直しを省き、伸びた利益を早く確保します。最初の14場で、勝つ頻度と利益保護を重視して選んだ第一候補です。',
        weakness='大きく押してから再び伸びる波では、早く降り過ぎることがあります。'),
    dict(id='F50_NONE__E10',title='押し戻しを少し待つ',width=1.5,
        middle='一度1.5ATR伸びた後、直近2分と30秒がともに逆向きになったら、残っている枠の約半分を一度返済。減らした分は戻しません。',
        benefit='候補1より戻りを許容し、途中の揺れを越えて持ち続けることを狙います。出口を狭め過ぎない比較候補です。',
        weakness='候補1より持ち続ける分、流れが転換したときには利益を多く返すことがあります。'),
    dict(id='C01__E10',title='少し減らし、回復したら戻す',width=1.5,
        middle='直近2分と30秒がともに逆向きになったら、約25%を一度返済。新しい同方向の動きを確認したら、まだ終了していない枠だけ戻します。',
        benefit='悪化時には小さく減らし、回復後の上昇・下落へ再び参加します。押し戻しの後にも続く波を狙います。',
        weakness='回復を確認して戻した直後に再逆行すると、復元しない候補より損失が増えることがあります。'),
    dict(id='A0__E10',title='途中の枚数判断を省く',width=1.5,
        middle='短期の逆行では枚数を変えません。共通の部分利確と、価格による損切り・追跡返済だけで管理します。',
        benefit='途中の悪化・回復判定を省ける、最も単純な比較候補です。短い逆行に左右されず、残った枚数で波に乗り続けます。',
        weakness='悪化時にも枚数を減らさないため、逆行が続いたときの損失が増えることがあります。')
]

CSS='''
:root{color-scheme:dark;background:#0b121b;color:#e4edf8;font-family:Meiryo,"Yu Gothic UI",sans-serif}
*{box-sizing:border-box}body{max-width:1250px;margin:auto;padding:28px 24px;line-height:1.75}h1{font-size:26px;margin:10px 0}h2{font-size:21px;margin:20px 0 10px}h3{font-size:17px;margin:0 0 8px}p{margin:10px 0}a{color:#8dcbff}.muted{color:#a8bad1;font-size:13px}.settings{display:flex;gap:18px;flex-wrap:wrap;background:#15253a;border:1px solid #385675;padding:14px 18px;border-radius:10px;margin:16px 0}.settings strong{color:#fff}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0}th,td{padding:8px 9px;border-bottom:1px solid #2c4159;text-align:right;white-space:nowrap}th{color:#c6d9f0;background:#172b43}th:first-child,td:first-child{text-align:left}.profit{color:#72d8ae}.loss{color:#ff9aaa}.total{background:#15303a;font-weight:bold}.overview td:first-child{white-space:normal;min-width:220px}.overview tr.featured{background:#132b30}.tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:24px 0 8px}.tabs button{background:#15273d;color:#dbe9fb;font:inherit;font-size:14px;border:1px solid #435e7e;border-radius:7px;padding:10px;cursor:pointer}.tabs button[aria-selected="true"]{background:#205886;border-color:#8dccff;color:#fff}.tabs button:focus-visible{outline:3px solid #eac276}.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0}.step{background:#132237;border:1px solid #2d4968;border-radius:9px;padding:15px}.step p{font-size:14px;margin:0}.step span{color:#8fc7ff;font-size:13px}.thought{border-left:3px solid #76bce9;padding-left:14px;margin:14px 0}.thought p{font-size:14px}.kpis{display:flex;flex-wrap:wrap;gap:18px;margin:14px 0;font-size:14px}.kpis strong{color:#8cdfc0}.group-top{border-top:2px solid #5a7899}.group-bottom{border-bottom:2px solid #5a7899}details{border:1px solid #2d435e;padding:12px 15px;margin-top:16px}summary{cursor:pointer;color:#bedcf9}li{margin:7px 0}code{font-size:12px;color:#a9bbd1;overflow-wrap:anywhere}.nojs{color:#a8bad1}.panel[hidden]{display:none}@media(max-width:740px){body{padding:16px}h1{font-size:22px}.steps{grid-template-columns:1fr}.tabs{grid-template-columns:repeat(2,1fr)}th,td{padding:7px}table{font-size:12px}}@media print{.tabs,.nojs{display:none}.panel[hidden]{display:block}body{max-width:none}.panel{break-before:page}details{display:block}details>*{display:block}.scroll{overflow:visible}}
'''


def read(path: Path) -> object:
    """機能: 保存JSON又は圧縮JSONを読む。

    引数: path(Path)。返り値: 内容(object)。
    """
    data=path.read_bytes()
    return json.loads((gzip.decompress(data) if path.suffix=='.gz' else data).decode('utf-8'))


def yen(value: float, signed: bool = False) -> str:
    """機能: 円額を桁区切りで表示し、負のゼロを除く。

    引数: value(float)、signed(bool)。返り値: 表示文字列(str)。
    """
    value=0 if value==0 else value
    return format(value,'+,.0f' if signed else ',.0f')


def registered_updates() -> list[str]:
    """機能: 検証済み追加結果の登録順を取得し、重複と範囲外の参照を拒否する。

    引数: なし。返り値: 作業内の追加結果フォルダ名(list[str])。
    """
    registry=HERE/'追加結果一覧.json'
    folders=read(registry) if registry.exists() else []
    assert isinstance(folders,list) and len(folders)==len(set(folders))
    assert all(isinstance(name,str) and (HERE/name).resolve().parent==HERE for name in folders)
    return folders


def data_for(spec: dict, references: dict) -> dict:
    """機能: 旧14場と登録済みの追加結果を読み、数量・倍率・合計を照合する。

    引数: spec(dict)、references(dict)。返り値: 方式別表示データ(dict)。
    """
    rows=[];ledgers=[]
    for stage in ('exit_integration','integration_followup/new'):
        for kind,target in (('sessions',rows),('ledgers',ledgers)):
            path=SOURCE/stage/kind/(spec['id']+'.json.gz')
            references[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
            target+=read(path)
    assert len(rows)==len(ledgers)==28
    base_assessment=SOURCE/'integrated_assessment.json'
    references[str(base_assessment.relative_to(ROOT))]=hashlib.sha256(base_assessment.read_bytes()).hexdigest()
    expected=read(base_assessment)['全14期間'][spec['id']]
    for symbol in SYMBOLS:
        original=[r for r in rows if r['symbol']==symbol]
        assert all(abs(sum(r[field] for r in original)-expected[symbol][field])<1e-7 for field in FIELDS)
    registry=HERE/'追加結果一覧.json'
    additions=registered_updates()
    if registry.exists():
        references[str(registry.relative_to(ROOT))]=hashlib.sha256(registry.read_bytes()).hexdigest()
    for folder in additions:
        extra=HERE/folder
        complete=extra/'complete.json';assert read(complete)['全合格']
        references[str(complete.relative_to(ROOT))]=hashlib.sha256(complete.read_bytes()).hexdigest()
        for kind,target in (('sessions',rows),('ledgers',ledgers)):
            path=extra/kind/(spec['id']+'.json.gz')
            references[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
            target+=read(path)
        assessment=extra/'assessment.json'
        references[str(assessment.relative_to(ROOT))]=hashlib.sha256(assessment.read_bytes()).hexdigest()
        expected=read(assessment)[spec['id']]
    keys={(r['session'],r['symbol']) for r in rows}
    assert len(keys)==len(rows)==len(ledgers)
    assert keys=={(r['session'],r['symbol']) for r in ledgers}
    names=sorted({r['session'] for r in rows});count=len(names)
    overview={}
    for symbol,settings in SYMBOLS.items():
        subset=sorted((r for r in rows if r['symbol']==symbol),key=lambda r:r['session'])
        assert sorted(r['session'] for r in subset)==names
        for ledger in (r for r in ledgers if r['symbol']==symbol):
            config=ledger['config']
            assert config['initial_qty']==settings['initial'] and config['audit_cap']==settings['cap']
            assert config['point_value']==settings['multiplier'] and config['tight_width']==spec['width']
            assert config['add_mode']==0 and config['add_qty']==0
            assert all(order[4]==settings['initial'] for order in ledger['orders'] if order[6]==20 and order[7]==1)
        for row in subset:
            assert abs(row['gross_profit_yen']-row['gross_loss_yen']-row['net_yen'])<1e-7
            assert max(row['max_long'],row['max_short'])<=settings['initial']<=settings['cap']
        totals={field:sum(r[field] for r in subset) for field in FIELDS}
        assert all(abs(totals[field]-expected[symbol][field])<1e-7 for field in FIELDS)
        overview[symbol]=dict(totals,win_sessions=sum(r['net_yen']>0 for r in subset),session_count=count,
            average_unit_payoff=expected[symbol]['average_unit_payoff'],drawdown_yen=expected[symbol]['drawdown_yen'],
            cycle_win_rate=expected[symbol]['cycle_wins']/expected[symbol]['cycles'],
            first_week={f:sum(r[f] for r in subset if r['session'][:10]<='2026-09-25') for f in FIELDS},
            second_week={f:sum(r[f] for r in subset if r['session'][:10]>='2026-09-28') for f in FIELDS})
    return dict(spec=spec,sessions=rows,overview=overview)


def session_label(name: str, year: bool = False) -> str:
    """機能: セッション識別子を日本語の日時表示へ変換する。

    引数: name(str)、year(bool)。返り値: 日時表示(str)。
    """
    return (name if year else name[5:]).replace('-','/').replace('_Day',' デイ').replace('_Night',' ナイト')


def period_rows(method: dict) -> list[tuple[str,dict,bool]]:
    """機能: 全セッションと開始日所属の週・全期間合計を横並びに揃える。

    引数: method(dict)。返り値: 期間名・銘柄値・合計判別の列(list[tuple[str,dict,bool]])。
    """
    result=[]
    names=sorted({r['session'] for r in method['sessions']});weeks={}
    for name in names:
        values={s:next(r for r in method['sessions'] if r['session']==name and r['symbol']==s) for s in SYMBOLS}
        result.append((session_label(name),values,False))
        day=date.fromisoformat(name[:10]);monday=day-timedelta(days=day.weekday())
        weeks.setdefault(monday,[]).append(name)
    for number,week in enumerate(weeks.values(),1):
        start=date.fromisoformat(week[0][:10]);end=date.fromisoformat(week[-1][:10])
        label=f'第{number}週 {start.month}/{start.day}〜{end.month}/{end.day}'
        values={s:{f:sum(r[f] for r in method['sessions'] if r['session'] in week and r['symbol']==s) for f in FIELDS} for s in SYMBOLS}
        result.append((label,values,True))
    result.append((f'全{len(names)}セッション',method['overview'],True))
    return result


def financial_table(method: dict, units: bool = False) -> str:
    """機能: セッション別と週・全期間の金額又は枚数をHTML表にする。

    引数: method(dict)、units(bool)。返り値: HTML(str)。
    """
    fields=('profit_units','loss_units','zero_units') if units else ('gross_profit_yen','gross_loss_yen','net_yen')
    labels=('勝ち枚','負け枚','同値枚') if units else ('利益','損失','収支')
    kind='units' if units else 'money'
    head='<tr><th rowspan="2">2026年・セッション開始日</th>'+''.join(f'<th colspan="3" class="group-top">{v["name"]}</th>' for v in SYMBOLS.values())+'</tr><tr>'+''.join('<th>'+x+'</th>' for _ in SYMBOLS for x in labels)+'</tr>'
    body=[]
    for index,(label,values,total) in enumerate(period_rows(method)):
        cells=[]
        for symbol in SYMBOLS:
            for field in fields:
                value=values[symbol][field]
                css='profit' if field=='net_yen' and value>0 else 'loss' if field=='net_yen' and value<0 else ''
                cells.append(f'<td class="{css}" data-symbol="{symbol}" data-field="{field}" data-value="{value}">{yen(value,field=="net_yen")}</td>')
        body.append(f'<tr class="{"total" if total else ""}" data-row="{index}"><td>{label}</td>'+''.join(cells)+'</tr>')
    return f'<div class="scroll"><table data-method="{method["spec"]["id"]}" data-kind="{kind}"><thead>{head}</thead><tbody>'+''.join(body)+'</tbody></table></div>'


def method_panel(method: dict, number: int) -> str:
    """機能: 一方式の入口・途中・出口、考察、全場損益を一章へまとめる。

    引数: method(dict)、number(int)。返り値: HTML(str)。
    """
    spec=method['spec'];width=spec['width']
    entry='NKとTOPIXの大きな流れが一致し、直近30秒も同じ向きなら準備。買いは追跡安値から0.25ATR反発、売りは追跡高値から0.25ATR反落したら入ります。'
    exit_text=f'2ATR伸びたら所定の一部を利確。追跡は1.5ATR順行から幅3ATRで始め、3ATRまで伸びたら幅{width:g}ATRへ狭め、戻ったら残りを返済します。'
    steps=''.join(f'<div class="step"><span>{i}</span><h3>{title}</h3><p>{escape(text)}</p></div>' for i,title,text in [('01','入口',entry),('02','途中の判断',spec['middle']),('03','出口',exit_text)])
    kpis=''.join(f'<div>{SYMBOLS[s]["name"]}：<strong>{v["win_sessions"]}/{v["session_count"]}場が黒字</strong> ／ 1枚平均利益÷平均損失 <strong>{v["average_unit_payoff"]:.2f}倍</strong> ／ 最大途中下落 {yen(v["drawdown_yen"])}円</div>' for s,v in method['overview'].items())
    return f'''<section id="method-{number}" class="panel" role="tabpanel" aria-labelledby="tab-{number}">
<h2>候補{number}｜{escape(spec['title'])}</h2><code>{spec['id']}</code><div class="steps">{steps}</div>
<div class="thought"><p><strong>この方法の狙い：</strong>{escape(spec['benefit'])}</p><p><strong>弱点：</strong>{escape(spec['weakness'])}</p></div>
<div class="kpis">{kpis}</div><h3>各セッションの利益・損失・収支（円）</h3>
{financial_table(method)}
<details><summary>返済した勝ち枚数・負け枚数を見る</summary><p class="muted">延べ返済枚数です。再エントリー分を含むため、同時保有上限とは異なります。</p>{financial_table(method,True)}</details></section>'''


def main() -> None:
    """機能: 保存済み4候補を平易な説明と検算可能な損益表へ変換する。

    引数: なし。返り値: なし(None)。原本取得、再探索、売買条件変更を行わない。
    """
    OUT.mkdir(parents=True,exist_ok=True);references={};methods=[data_for(spec,references) for spec in METHODS]
    names=sorted({r['session'] for r in methods[0]['sessions']});count=len(names)
    assert all({r['session'] for r in method['sessions']}==set(names) for method in methods)
    latest=session_label(names[-1],True);period=f'{session_label(names[0],True)}〜{latest}'
    added=names[14:]
    update_note=(f'<p><strong>更新：{latest}を追加。</strong> 4手法・枚数・条件は変更せず、選定後の追試として集計しました。</p>' if added else '')
    overview=[]
    for number,method in enumerate(methods,1):
        cells=[]
        for symbol in SYMBOLS:
            value=method['overview'][symbol]
            cells.append(f'<td class="{"profit" if value["net_yen"]>=0 else "loss"}">{yen(value["net_yen"],True)}円</td><td>{value["win_sessions"]}/{count}場</td>')
        overview.append(f'<tr class="{"featured" if number==1 else ""}"><td>候補{number}｜{method["spec"]["title"]}</td>'+''.join(cells)+'</tr>')
    tabs=''.join(f'<button id="tab-{n}" role="tab" aria-controls="method-{n}" aria-selected="{"true" if n==1 else "false"}" data-tab="{n}">{n}．{m["spec"]["title"]}</button>' for n,m in enumerate(methods,1))
    script='''
/**
 * 機能: 選んだ手法の説明と損益だけを表示する。
 * @param {number} number - 1から4の候補番号。
 * @returns {undefined} 返り値なし。
 */
function selectMethod(number){if(![1,2,3,4].includes(number))number=1;document.querySelectorAll('.panel').forEach((p,i)=>{p.hidden=i!==number-1;});document.querySelectorAll('[data-tab]').forEach(b=>{b.setAttribute('aria-selected',String(Number(b.dataset.tab)===number));});}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>selectMethod(Number(b.dataset.tab))));selectMethod(1);
'''
    html=f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>有望4手法の説明とセッション損益</title><style>{CSS}</style></head><body>
<!--
[コンポーネント概要]
.settings は片方向の保有上限と実際の初回枚数を表示します。
.overview は4候補の全期間収支、.tabs は各候補の章を選ぶ操作です。
.panel は入口・途中・出口の平易な説明と、セッション別・週別損益をまとめます。
data-value は表示数値の検算用の原値です。通信や売買実行は行いません。
-->
<a href="../index.html">作業一覧</a><h1>有望4手法の説明とセッション別損益</h1>
{update_note}
<p><strong>まず候補1を中心に比較。</strong> 4手法は入口が共通で、途中の減量・復元と、利益が伸びた後の追跡幅が異なります。</p>
<div class="settings"><div><strong>TOPIXミニ：片方向上限10枚／初回5枚</strong></div><div><strong>NK225マイクロ：片方向上限20枚／初回10枚</strong></div></div>
<p class="muted">これまでの指定どおり、10枚・20枚は同時保有の上限です。この4候補は初回を超えて積み増さず、実際の最大保有は5枚・10枚。以下はこの枚数で検証した収支で、上限まで使った仮の倍額表示ではありません。費用0・指定価格約定・全建玉をセッション内に返済。</p>
<h2>全{count}セッションの比較</h2><div class="scroll"><table class="overview"><thead><tr><th>手法</th><th>TOPIXミニ収支</th><th>黒字場</th><th>NKマイクロ収支</th><th>黒字場</th></tr></thead><tbody>{''.join(overview)}</tbody></table></div>
<p class="muted">対象：{period}。黒字場の割合は、取引1回ごとの勝率とは別です。</p>
<p><strong>ATR＝直前までの値動きから求める「通常の値幅の目安」。</strong> 初回の注文準備時に固定します。3ATRはその3倍、0.75ATRは4分の3です。</p>
<p class="muted">共通の損切り基準は初回枚数×1ATR相当の損失。保有は最大360分で、場末には全返済します。途中の利益だけを取り出さず、損切り分も以下の収支に含めています。</p>
<nav class="tabs" role="tablist" aria-label="手法を選択">{tabs}</nav>
{''.join(method_panel(method,n) for n,method in enumerate(methods,1))}
<details id="common-rules"><summary>4手法に共通する損切り・機械条件</summary><ul>
<li><strong>方向：</strong>確定1分足の15本・60本EMA（新しい価格を重くする移動平均）で判定。差が0.15ATR超、長い平均の3本差分も同方向へ0.02ATR超で方向開始。平均の差が反対符号になるまで保持し、相手市場も同方向の時だけ新規を準備します。</li>
<li><strong>短期確認：</strong>30秒の価格変化が主方向へ0.05ATR超。根拠は120秒有効、新規の追跡待ちは300秒。方向条件がなくなれば取消。ATRは確定5分足から計算し、未来足は使いません。</li>
<li><strong>途中の悪化・回復：</strong>2分変化がmax(0.25ATR,2呼値)、30秒変化がmax(0.1ATR,1呼値)を同方向へ超えるかで判断。板の厚さを使う条件ではありません。</li>
<li><strong>損切り：</strong>初回枚数×1ATR相当の損失を返済判断の基準にします。途中の減量・復元でこの予算を増やしません。価格の飛びや次行での発注により、この額を超える場合はあります。</li>
<li><strong>部分利確：</strong>2ATR順行で初回の所定枠（TOPIX2枚・NK5枚）を終了。先に減量済みの枠は二重に返済せず、その後も復元しません。減量の25%・50%は残る枠数から切捨て、最低1枚・少なくとも1枠を残します。</li>
<li><strong>時間終了：</strong>初回から最大360分。日中15:35、夜間05:50には全返済を指示し、後続の有効行で実行。セッションをまたぎません。</li>
<li><strong>再エントリー：</strong>早く返済した場合も、元の広い追跡幅で仮想運転を続け、その終了と5分休止後の次の新規準備を待ちます。この待機も検証したルールの一部です。</li>
<li><strong>情報の公開：</strong>1分足は開始＋120秒、5分足ATRは開始＋360秒、相手方向はさらに60秒遅延。EMAを毎場初期化するため、中央条件の最初の方向判定には通常63本の足が必要。序盤から常に取引できる方式ではありません。</li>
</ul></details>
<p class="muted">最初の14場は候補選定に使用したデータです。その後の{len(added)}場は条件を固定して追加検証しています。詳細な検証過程は<a href="../00041_入口途中出口の分解検証/分解と結論.html">00041</a>、再現と資料は<a href="README.md">README</a>へ。</p>
<script>{script}</script></body></html>'''
    target=OUT/'有望4手法の説明と損益.html';target.write_text(html,encoding='utf-8')
    payload=dict(全合格=True,方式数=4,対象セッション数=count,会計入力数=count*8,数量前提=SYMBOLS,
        元条件変更=False,追加検証セッション=added,新売買再生=bool(added),現在API取得数=0,候補=methods,参照SHA256=references,
        HTML_SHA256=hashlib.sha256(target.read_bytes()).hexdigest())
    (HERE/'報告データ.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    update_links='\n'.join(f'- [{session_label(read(HERE/folder/"complete.json")["対象"],True)}の追加検証](../../work/wave_v48/{folder}/独立確認.md)' for folder in registered_updates())
    readme=f'''# 00042 有望4手法の説明とセッション損益

最初に見るファイルは **[有望4手法の説明と損益.html](有望4手法の説明と損益.html)** です。

読む順序：

1. 冒頭の枚数前提と、4候補の全期間収支を確認。
2. 手法ボタンを選び、入口・途中・出口の3欄と、各セッションの利益・損失・収支を読む。
3. 必要に応じて、返済枚数と共通の機械条件を開く。

TOPIXミニは片方向上限10枚・初回5枚、NK225マイクロは上限20枚・初回10枚です。既存4候補は初回を超える追加をしません。上限いっぱいの初回10枚・20枚へ変更した収支ではありません。

対象は{period}の全{count}セッション。費用0・指定価格約定・セッション内で全返済。ナイトは開始日で表示しています。勝ち枚／負け枚は延べ返済枚数です。

最初の14場は00041の保存結果です。その後の{len(added)}場は、同じ4手法・枚数・条件のまま保存原本で追加検証しました。現在セッションAPIは取得していません。元14場の成績と00041は変更していません。

- [元の部品検証](../00041_入口途中出口の分解検証/分解と結論.html)
- [勝率の再評価](../00041_入口途中出口の分解検証/8割の勝ちと損小利大.html)
- [表示用データと入力指紋](../../work/wave_v48/報告データ.json)
- [元14場の独立確認](../../work/wave_v48/before_update_20260930/独立確認.md)
{update_links}

再生成：

```powershell
python -X utf8 work/wave_v48/build_report.py
```

今後の追加結果は `work/wave_v48/追加結果一覧.json` に明示登録した検証済み資料から読み込みます。未検証の原本を自動で成績へ混ぜません。
'''
    (OUT/'README.md').write_text(readme,encoding='utf-8')
    print(f'4手法・{count*8}口座の金額/数量/倍率を確認し、説明と損益を1つのHTMLへ保存。',flush=True)


if __name__=='__main__':main()
