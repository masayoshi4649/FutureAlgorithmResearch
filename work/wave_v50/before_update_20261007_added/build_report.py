"""00042の表示形式で、新候補二方式と元の基準の説明・損益を整理する。"""

from html import escape
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE=ROOT/'work/wave_v49/early'
OUT=ROOT/'アルゴリズム調査/00044_新候補2手法と基準の説明と損益'
TITLE='新候補2手法の説明と損益.html'
MODULE=ROOT/'work/wave_v48/build_report.py'
loader=importlib.util.spec_from_file_location('元42の表示部品',MODULE)
style=importlib.util.module_from_spec(loader);loader.loader.exec_module(style)
SYMBOLS=style.SYMBOLS
FIELDS=style.FIELDS
METHODS=[
    dict(id='E01',label='新候補1｜E01',title='損切りを少し早める',stop=.75,activation=1.5,width=3.,
        exit='初期損切りを1ATRから0.75ATRへ。1.5ATR伸びたら幅3ATRで追跡し、3ATR伸びた後は幅0.75ATRへ狭めて残りを返済します。',
        benefit='入口と利益を伸ばす仕組みを保ち、最初の逆行を少し早く切ります。選定時の16場では損小利大と黒字セッション数を維持した損失軽減候補です。',
        weakness='小さな押し戻しの後に伸びる取引も切るため、合計利益は元の手法より減りました。最大下落の改善は控えめです。'),
    dict(id='E08',label='新候補2｜E08',title='小さな順行から利益を守る',stop=.5,activation=.5,width=.5,
        exit='初期損切りを0.5ATRへ。0.5ATR伸びた時点から幅0.5ATRで追跡し、戻ったら残りを返済します。大きく伸びても幅は広げません。',
        benefit='深い逆行を早く切り、利益が小さいうちから追跡します。最大途中下落の抑制を重視し、選定時の16場では特にNKで下落額が減りました。',
        weakness='利益も早く確定するため、元の大勝ちを多く失います。黒字セッション数も減り、約8割という目標には届いていません。'),
    dict(id='E00',label='比較基準｜元の候補1',title='利益を早めに守る',stop=1.,activation=1.5,width=3.,
        exit='初期損切りは1ATR。1.5ATR伸びたら幅3ATRで追跡し、3ATR伸びた後は幅0.75ATRへ狭めて残りを返済します。',
        benefit='00042の候補1と同じ手法です。多少の押し戻しを許して大きな波を取り、伸びた後は減量と追跡幅の短縮で利益を守ります。',
        weakness='往復相場では、利益保護が始まる1.5ATRへ届く前の損切りが重なります。今回の比較では利益も最大下落も大きい基準です。')
]


def read(path):
    """機能: 保存済みJSON又は圧縮JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def digest(path):
    """機能: 入力内容の指紋を返す。

    引数: path(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def registered_updates():
    """機能: 明示登録した検証済み追加フォルダだけを取得する。

    引数: なし。返り値: フォルダ名の一覧(list[str])。
    """
    path=HERE/'追加結果一覧.json'
    names=read(path) if path.exists() else []
    assert isinstance(names,list) and len(names)==len(set(names))
    assert all(isinstance(name,str) and (HERE/name).resolve().parent==HERE for name in names)
    return names


def data_for(spec,references,complete):
    """機能: 一方式の既存決済帳・集計を照合し、表示用に整理する。

    引数: spec/references/complete(dict)。返り値: 一方式の説明・各場・全体数値(dict)。
    """
    loaded={}
    for kind,suffix in [('sessions','.json.gz'),('ledgers','.json.gz'),('summaries','.json')]:
        path=SOURCE/kind/(spec['id']+suffix);key=path.relative_to(ROOT).as_posix()
        references[key]=digest(path)
        assert references[key]==complete['出力SHA256'][key]
        loaded[kind]=read(path)
    sessions=loaded['sessions'];ledgers=loaded['ledgers'];expected=loaded['summaries']['periods']['全16']
    assert len(sessions)==len(ledgers)==32
    base_sessions=list(sessions)
    for folder in registered_updates():
        extra=HERE/folder
        check=read(extra/'complete.json');assert check['全合格']
        references[(extra/'complete.json').relative_to(ROOT).as_posix()]=digest(extra/'complete.json')
        additions={}
        for kind,suffix in [('sessions','.json.gz'),('ledgers','.json.gz'),('summaries','.json')]:
            path=extra/kind/(spec['id']+suffix);key=path.relative_to(ROOT).as_posix()
            references[key]=digest(path)
            assert references[key]==check['出力SHA256'][key]
            additions[kind]=read(path)
        assert not {(r['session'],r['symbol']) for r in additions['sessions']} & {(r['session'],r['symbol']) for r in sessions}
        assert min(r['session'] for r in additions['sessions'])>max(r['session'] for r in sessions)
        sessions+=additions['sessions'];ledgers+=additions['ledgers']
        count=len({r['session'] for r in sessions})
        expected=additions['summaries']['periods'][f'全{count}']
    keys={(r['session'],r['symbol']) for r in sessions}
    assert len(keys)==len(sessions)==len(ledgers) and keys=={(r['session'],r['symbol']) for r in ledgers}
    names={r['session'] for r in sessions}
    assert keys=={(session,symbol) for session in names for symbol in SYMBOLS}
    assert sessions[:32]==base_sessions
    for ledger in ledgers:
        symbol=ledger['symbol'];config=ledger['config'];settings=SYMBOLS[symbol]
        assert config['initial_qty']==settings['initial'] and config['audit_cap']==settings['cap']
        assert config['point_value']==settings['multiplier']
        assert config['stop_atr']==spec['stop'] and config['activation_atr']==spec['activation'] and config['main_trail']==spec['width']
        assert config['tighten_atr']==3. and config['tight_width']==.75
        trades=ledger['trades'];mult=settings['multiplier']
        actual=dict(gross_profit_yen=sum(t[10]*mult for t in trades if t[10]>0),
            gross_loss_yen=-sum(t[10]*mult for t in trades if t[10]<0),net_yen=sum(t[10]*mult for t in trades),
            profit_units=sum(t[3] for t in trades if t[10]>0),loss_units=sum(t[3] for t in trades if t[10]<0),zero_units=sum(t[3] for t in trades if t[10]==0))
        row=next(r for r in sessions if (r['session'],r['symbol'])==(ledger['session'],symbol))
        assert all(abs(row[k]-actual[k])<1e-6 for k in FIELDS)
        assert max(row['max_long'],row['max_short'])<=settings['initial']<=settings['cap']
    overview={}
    for symbol in SYMBOLS:
        subset=[r for r in sessions if r['symbol']==symbol]
        total={f:sum(r[f] for r in subset) for f in FIELDS}
        for f in FIELDS[:3]:assert abs(total[f]-expected[symbol][f])<1e-6
        assert abs(total['gross_profit_yen']-total['gross_loss_yen']-total['net_yen'])<1e-6
        payoff=(total['gross_profit_yen']/total['profit_units'])/(total['gross_loss_yen']/total['loss_units'])
        assert abs(payoff-expected[symbol]['average_unit_payoff'])<1e-10
        overview[symbol]=dict(total,win_sessions=sum(r['net_yen']>0 for r in subset),session_count=len(subset),
            average_unit_payoff=payoff,drawdown_yen=expected[symbol]['drawdown_yen'])
    return dict(spec=spec,sessions=sessions,overview=overview)


def method_panel(method,number):
    """機能: 手法の説明三欄と、横並びの金額・枚数表を作る。

    引数: method(dict)、number(int)。返り値: HTML(str)。
    """
    spec=method['spec']
    entry='NKとTOPIXの保持中の主方向が一致し、30秒変化の同方向支持が有効なら準備。買いは追跡安値から0.25ATR反発、売りは追跡高値から0.25ATR反落したら入ります。'
    middle='1.5ATR伸びた後、直近2分と30秒がともに逆向きなら、残る枠の約半分を一度返済。減らした分は戻しません。2ATR順行では所定の一部を利確します。'
    steps=''.join(f'<div class="step"><span>{i}</span><h3>{heading}</h3><p>{escape(body)}</p></div>' for i,heading,body in [('01','入口',entry),('02','途中の判断',middle),('03','出口',spec['exit'])])
    kpis=''.join(f'<div>{SYMBOLS[s]["name"]}：<strong>{v["win_sessions"]}/{v["session_count"]}場が黒字</strong> ／ 1枚平均利益÷平均損失 <strong>{v["average_unit_payoff"]:.2f}倍</strong> ／ 最大途中下落 {style.yen(v["drawdown_yen"])}円</div>' for s,v in method['overview'].items())
    return f'''<section id="method-{number}" class="panel" role="tabpanel" aria-labelledby="tab-{number}" data-id="{spec['id']}">
<h2>{escape(spec['label'])}｜{escape(spec['title'])}</h2><code>F50_NONE__E11 → {spec['id']}</code><div class="steps">{steps}</div>
<div class="thought"><p><strong>この方法の狙い：</strong>{escape(spec['benefit'])}</p><p><strong>弱点：</strong>{escape(spec['weakness'])}</p></div>
<div class="kpis">{kpis}</div><h3>各セッションの利益・損失・収支（円）</h3>
{style.financial_table(method)}
<details><summary>返済した勝ち枚数・負け枚数を見る</summary><p class="muted">延べ返済枚数です。再エントリー分を含むため、同時保有上限とは異なります。1枚平均利益÷平均損失は、利益額÷勝ち枚数を、損失額÷負け枚数で割った値です。</p>{style.financial_table(method,True)}</details></section>'''


def main():
    """機能: 00042の表示形式を使い、新フォルダへ三方式の資料を生成する。

    引数: なし。返り値: なし(None)。既存報告・原本・売買条件は変更しない。
    """
    OUT.mkdir(parents=True,exist_ok=True);HERE.mkdir(exist_ok=True)
    previous={str(p.relative_to(ROOT)):digest(p) for p in (ROOT/'アルゴリズム調査/00042_有望4手法の説明とセッション損益/有望4手法の説明と損益.html',ROOT/'アルゴリズム調査/00043_赤字原因とエントリー見送り/赤字原因と改善案の検証.html')}
    references={str(MODULE.relative_to(ROOT)):digest(MODULE)}
    if (HERE/'追加結果一覧.json').exists():
        references[(HERE/'追加結果一覧.json').relative_to(ROOT).as_posix()]=digest(HERE/'追加結果一覧.json')
    complete=read(SOURCE/'完了.json');assert complete['全合格']
    references[str((SOURCE/'完了.json').relative_to(ROOT))]=digest(SOURCE/'完了.json')
    methods=[data_for(spec,references,complete) for spec in METHODS]
    names=sorted({r['session'] for r in methods[0]['sessions']})
    count=len(names)
    assert count>=16 and all({r['session'] for r in m['sessions']}==set(names) for m in methods)
    added=names[16:]
    latest_updates = (sorted({r['session'] for r in read(HERE/registered_updates()[-1]/'sessions'/'E01.json.gz')})
                      if added else [])
    update_label = '・'.join(style.session_label(name,True) for name in latest_updates)
    update_note=(f'<p><strong>更新：{update_label}を追加。</strong> 3方式の条件・枚数を固定して検証しました。</p>' if added else '')
    phase_note=(f'最初の16場は新候補の探索に使用。その後の{len(added)}場は条件を固定して追加検証しています。' if added else '新候補は全16場を使った探索結果です。')
    period=f'{style.session_label(names[0],True)}〜{style.session_label(names[-1],True)}'
    # ----------------------------------------
    # 検算済みの値から、00042と同じ比較一覧と章の切替を組み立てる。
    overview=[]
    for number,method in enumerate(methods,1):
        cells=[]
        for symbol in SYMBOLS:
            v=method['overview'][symbol]
            cells.append(f'<td class="{"profit" if v["net_yen"]>=0 else "loss"}">{style.yen(v["net_yen"],True)}円</td><td>{v["win_sessions"]}/{count}場</td><td>{style.yen(v["drawdown_yen"])}円</td>')
        overview.append(f'<tr class="{"featured" if number==1 else ""}"><td>{method["spec"]["label"]}<br>{method["spec"]["title"]}</td>'+''.join(cells)+'</tr>')
    tabs=''.join(f'<button id="tab-{n}" role="tab" aria-controls="method-{n}" aria-selected="{"true" if n==1 else "false"}" data-tab="{n}">{m["spec"]["label"]}<br>{m["spec"]["title"]}</button>' for n,m in enumerate(methods,1))
    css=style.CSS+'\n.tabs{grid-template-columns:repeat(3,1fr)}@media(max-width:740px){.tabs{grid-template-columns:1fr}}'
    page=f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>新候補2手法の説明とセッション損益</title><style>{css}</style></head><body>
<!--
[コンポーネント概要]
.settings は同時保有上限と初回枚数、.overview は全期間比較です。
.tabs は新候補E01・E08と元の比較基準の章を選択します。
.panel は入口・途中・出口の説明、各場と週・全期間の金額・枚数を表示します。
data-value は表示値を検算するための原値です。通信や売買実行はありません。
-->
<a href="../index.html">作業一覧</a><h1>新候補2手法の説明とセッション別損益</h1>
{update_note}
<p><strong>E01は初期損切りを早める案、E08は小さな順行から追跡する案。</strong> 00042の候補1を比較基準として併記します。3方式の入口は同じで、変えるのは初期損切りと追跡の開始・幅です。</p>
<div class="settings"><div><strong>TOPIXミニ：片方向上限10枚／初回5枚</strong></div><div><strong>NK225マイクロ：片方向上限20枚／初回10枚</strong></div></div>
<p class="muted">初回を超える増玉・減量後の復元はなく、実際の最大保有は5枚・10枚。費用0・指定価格約定・全玉をセッション内に返済。利益だけでなく損切り分も含めています。</p>
<h2>全{count}セッションの比較</h2><div class="scroll"><table class="overview"><thead><tr><th rowspan="2">手法</th><th colspan="3">TOPIXミニ</th><th colspan="3">NK225マイクロ</th></tr><tr><th>収支</th><th>黒字場</th><th>最大途中下落</th><th>収支</th><th>黒字場</th><th>最大途中下落</th></tr></thead><tbody>{''.join(overview)}</tbody></table></div>
<p class="muted">対象：{period}。最大途中下落は含み損益込みの資産推移で測ります。黒字場の割合と取引1回ごとの勝率は別です。</p>
<p><strong>ATRは、直前までの値動きから求める通常の値幅の目安。</strong> 注文準備時に固定します。初期損切りが0.75ATRなら、買いは入口より0.75ATR下、売りは0.75ATR上が基本です。</p>
<p class="muted">{phase_note} 長期の優位が確定した手法ではありません。</p>
<nav class="tabs" role="tablist" aria-label="手法を選択">{tabs}</nav>
{''.join(method_panel(m,n) for n,m in enumerate(methods,1))}
<details id="common-rules"><summary>共通の機械条件と、変更した数値</summary><ul>
<li><strong>方向：</strong>確定1分足の15本・60本EMAで判定。差が0.15ATR超、長い平均の3本差分も同方向へ0.02ATR超で開始し、平均の差が反対符号になるまで方向を保持。相手市場も同方向の時だけ準備します。最新の傾きが常に一致する条件ではありません。</li>
<li><strong>短期確認と入口：</strong>30秒変化が主方向へ0.05ATR超なら120秒有効。追跡待ちは300秒、反発・反落の幅は0.25ATR。条件が失われたら未約定注文を取り消します。</li>
<li><strong>途中の減量：</strong>元の通常運転で1.5ATR順行を確認後、2分変化がmax(0.25ATR,2呼値)、30秒変化がmax(0.1ATR,1呼値)をともに逆方向へ超えたら、残る枠の50%を一度返済。切捨て・最低1枚・少なくとも1枠を残し、復元しません。先に全返済した取引には作用しません。</li>
<li><strong>部分利確：</strong>2ATR順行でTOPIX2枚・NK5枚に相当する所定枠を終了。先に減量済みなら二重に返済しません。</li>
<li><strong>初期ストップ：</strong>E01は0.75ATR、E08は0.5ATR、元の基準は1ATR。呼値に丸めます。別途維持する初回枚数×1ATRの組全体損失予算とは区別します。</li>
<li><strong>追跡：</strong>E01・元基準は1.5ATR順行で幅3ATR、3ATR順行後は0.75ATR。E08は0.5ATR順行で幅0.5ATRのまま。追跡ストップは緩めません。短縮水準を既に通過していれば次観測価格で返済し、過去の有利な価格へ遡りません。</li>
<li><strong>時間終了：</strong>初回から最大360分。デイ15:35・ナイト05:50に返済を指示して後続有効行で実行。全建玉をセッション内で閉じます。</li>
<li><strong>再エントリー：</strong>早く返済しても、元の広い幅の通常運転を仮想的に続け、その終了＋5分休止後の次の新規準備まで待ちます。この待機込みで初回時刻・方向・価格・枚数を3方式で揃えています。</li>
<li><strong>使うデータ：</strong>そのセッション内の公開済み情報だけ。1分足は開始＋120秒、5分足ATRは開始＋360秒、相手方向はさらに60秒遅延。EMAは毎場初期化し、方向判定には通常63本程度必要です。板の厚さや補充を直接用いる3方式ではありません。</li>
</ul></details>
<p class="muted">詳しい比較は<a href="../00043_赤字原因とエントリー見送り/赤字原因と改善案の検証.html">00043</a>。数値・検算・再現方法は<a href="README.md">資料案内</a>。ナイトはセッション開始日の週に集計しています。</p>
<script>
/**
 * 機能: 選んだ手法の説明と損益だけを表示する。
 * @param {{number}} number 1から3の章番号。
 * @returns {{undefined}} 返り値なし。
 */
function selectMethod(number){{if(![1,2,3].includes(number))number=1;document.querySelectorAll('.panel').forEach((p,i)=>{{p.hidden=i!==number-1;}});document.querySelectorAll('[data-tab]').forEach(b=>{{b.setAttribute('aria-selected',String(Number(b.dataset.tab)===number));}});}}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>selectMethod(Number(b.dataset.tab))));selectMethod(1);
</script></body></html>'''
    # ----------------------------------------
    # 新作業だけを保存し、元報告の指紋を照合して検証資料を添付する。
    (OUT/TITLE).write_text(page,encoding='utf8')
    payload=dict(全合格=True,方式数=3,対象セッション数=count,会計入力数=count*6,数量前提=SYMBOLS,
        新規API取得数=0,新規売買再生=bool(added),追加検証セッション=added,今回追加セッション=latest_updates,候補=methods,参照SHA256=references,
        HTML_SHA256=digest(OUT/TITLE),過去HTML指紋=previous)
    for path,value in previous.items():assert digest(ROOT/path)==value
    text=json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)
    (HERE/'報告データ.json').write_text(text,encoding='utf8')
    (OUT/'報告データ.json').write_text(text,encoding='utf8')
    evidence=OUT/'検証資料';evidence.mkdir(exist_ok=True)
    shutil.copy2(SOURCE/'条件の事前固定.json',evidence/'条件の事前固定.json')
    for name in ('早期保護比較の独立監査.json','早期保護の既成立注文監査.json'):
        shutil.copy2(ROOT/'work/wave_v49/audit'/name,evidence/name)
    for folder in registered_updates():
        target=evidence/folder;target.mkdir(exist_ok=True)
        for name in ('complete.json','入力独立監査.json','固定.json'):
            path=HERE/folder/name
            if path.exists():shutil.copy2(path,target/name)
    print(f'新2方式と元基準、{count*6}口座・週と全期間の金額/枚数を生成',flush=True)


if __name__=='__main__':main()
