"""場内完結の比較を、短い結論・時間軸比較・各場会計へ分けて公開する。"""

import csv
import hashlib
import html
import json
from pathlib import Path
import re
import statistics

from analyze import HERE, SYMBOLS, WEEKS, load, accounts, aggregate, rank


ROOT=HERE.parents[1]
FOLDER='00058_場内完結の時間軸と積極度の再検証'
OUT=ROOT/'アルゴリズム調査'/FOLDER
TITLE='場内完結450条件の説明と損益'
PRODUCTS={'TOPIX':'TOPIX mini','NK225':'NK225 micro'}
MODES={'quote':'売買気配・主評価','mid':'中値参考','passive':'待機指値の仮定'}
DESCRIPTIONS={
 'D1':('開始30分の高安突破','開始30分の高安を固定し、その外へ確定5分足が抜けたら順方向へ入る。最初の判断は35分後。再び内側へ戻ってからの再突破も対象。'),
 'D2':('押し目・戻りから再開','短長移動平均と長い平均の傾きが同方向のとき、短い平均まで戻って再び進み始めたら入る。'),
 'D3':('横ばい時の平均回帰','一方向への動きが弱く、平均から離れた価格がボリンジャーバンド内へ戻ったら、平均へ向けて逆張りする。'),
 'D4':('突破失敗の反転','過去の高安を抜けた境界を記憶し、次の1〜3本で内側へ戻ったら、突破と反対へ入る。'),
 'D5':('追従・回帰の自動選択','今までの値動きの方向効率が高ければD2、低ければD3。中間は見送る。未来の成績で方式を選ばない。'),
 'I1':('寿命を決めた往復格子','下に買い、上に売りを並べ、1間隔の利確・2間隔の損切り・元の建時刻からの期限で返済する。'),
 'I2':('在庫を減らす中心移動','買いが多ければ注文の中心を下げ、売りが多ければ上げる。反対注文の機会には、追加両建てより古い玉の返済を優先する。'),
 'I3':('逆方向への追加停止','上昇方向が確認できたら売り新規を止める。既存の売り玉は1間隔逆行したら整理する。下落時は逆。'),
 'I4':('含み益を確認した順張り追加','方向を確認して逆指値で入り、既存玉の含み益が入口費用を上回り、さらに1間隔進んだ場合だけ追加する。各玉に1間隔損切り・2間隔利確・追跡を置く。'),
 'I5':('期限付きカバー両建て','保有と反対に方向が出たら正味枚数を反対玉でカバーする。カバーに短い期限を置き、元玉の期限を延長せず、必要時は両側を返す。')}
CSS='''body{margin:0;background:#101720;color:#e3eaf3;font:16px/1.7 system-ui,sans-serif}main{max-width:1280px;margin:auto;padding:24px 24px 60px}h1{font-size:1.7rem;line-height:1.4}h2{font-size:1.2rem;margin:24px 0 12px}a{color:#93c8ff}p{margin:9px 0}section,.notice{background:#182432;border:1px solid #35485e;border-radius:9px;margin:18px 0;padding:17px}.notice{border-left:4px solid #8abcff}.muted{font-size:.87rem;color:#adc0d3}.wrap{overflow-x:auto;border:1px solid #34485c;border-radius:6px;margin:12px 0}table{border-collapse:collapse;white-space:nowrap;width:100%;font-size:.86rem}th,td{padding:8px 10px;text-align:right;border-bottom:1px solid #304256}th{background:#25374c}td:first-child,th:first-child{text-align:left}tr:nth-child(even){background:#14212e}.pos{color:#86e2b4}.neg{color:#ffaaa2}.muted small{font-size:.8rem}summary{cursor:pointer;color:#b0d1ff;padding:7px 0}nav{display:flex;gap:14px;flex-wrap:wrap}code{font-size:.86rem;color:#bbd9ff}@media(max-width:600px){main{padding:14px 12px 35px}h1{font-size:1.35rem}section{padding:12px}}'''


def esc(value: object) -> str:
    """機能: 表示値をHTMLへ安全に埋め込む。

    引数: value(object)。返り値: HTML安全文字列(str)。
    """
    return html.escape(str(value),quote=True)


def fmt(value: float | None, digits: int=0, colored: bool=False) -> str:
    """機能: 数値を区切り・符号・損益色付きで示す。

    引数: value(float|None)、digits(int)、colored(bool)。返り値: 表示文字列(str)。
    """
    if value is None:
        return '—'
    if abs(value)<1e-6:
        value=0.
    text=f'{value:,.{digits}f}'.replace('-','−')
    if colored:
        return f'<span class="{"pos" if value>0 else "neg" if value<0 else "zero"}">{"+" if value>0 else ""}{text}</span>'
    return text


def table(heads: list[str], rows: list[list[str]]) -> str:
    """機能: 列の多い比較を内部横スクロールで表示する。

    引数: heads(list[str])、rows(list[list[str]])。返り値: HTML表(str)。
    """
    return '<div class="wrap"><table><thead><tr>'+''.join(f'<th scope="col">{esc(h)}</th>' for h in heads)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{v}</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def page(title: str, body: str) -> str:
    """機能: 外部依存のない暗色HTMLを作る。

    引数: title/body(str)。返り値: HTML文書(str)。
    """
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><style>{CSS}</style></head><body>
<!--
[コンポーネント概要]
main は場内完結450条件の比較です。銘柄の円収支を合算しません。
.wrap は各場会計と時間軸比較を横スクロールする領域です。
details は取引規則・場別損益の詳細を開閉します。
.pos / .neg は暗色背景で利益と損失を区別する表示です。
--><main>{body}</main></body></html>'''


def parameters(method: dict) -> tuple[int,str,str]:
    """機能: 不変の条件IDから保有上限・幅・積極度を読む。

    引数: method(dict)。返り値: 分数・幅ID・積極度(tuple[int,str,str])。
    """
    match=re.search(r'_H(\d+)_(W\d+|D\d+)_(A\d)',method['id'])
    assert match,method['id']
    return int(match[1]),match[2],match[3]


def csv_save(name: str, rows: list[dict]) -> None:
    """機能: 全条件の会計をUTF-8 BOM付きCSVで保存し再読込する。

    引数: name(str)、rows(list[dict])。返り値: なし(None)。
    """
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    with (OUT/name).open(encoding='utf-8-sig',newline='') as f:
        actual=list(csv.DictReader(f))
    assert actual==[{k:'' if v is None else str(v) for k,v in r.items()} for r in rows]


def summary_table(methods: list[dict]) -> str:
    """機能: 金額・損益比・損失集中を同じ銘柄内で比較する。

    引数: methods(list[dict])。返り値: 比較HTML(str)。
    """
    rows=[]
    for m in methods:
        for s in SYMBOLS:
            v=aggregate(accounts(m,s))
            rows.append([f'<a href="#{esc(m["id"])}">{esc(m["id"])}</a>',esc(PRODUCTS[s]),fmt(v['net'],colored=True),
                fmt(v['pf'],2),fmt(v['payoff'],2),fmt(v['drawdown']),f'{v["positive_sessions"]}/25',fmt(v['without_best'],colored=True),
                f'{v["win_qty"]}/{v["loss_qty"]}',fmt(v['cycles']),fmt(m['native_hold']['quote'][s],1)])
    return table(['条件ID','商品','純収支円','総利益/総損失','平均勝/負','最大資産下落円','黒字場','最大黒字場除外円','勝/負枚','決済数※','保有中央値分'],rows)


def period_table(method: dict, per_session: bool=False) -> str:
    """機能: 主評価の実現利益・損失・費用・収支・枚数を期間別に示す。

    引数: method(dict)、per_session(bool)。返り値: HTML表(str)。
    """
    rows=[]
    periods=sorted({a['session'] for a in method['accounts']}) if per_session else [*WEEKS,'全25場']
    for period in periods:
        for s in SYMBOLS:
            subset=accounts(method,s)
            subset=[a for a in subset if a['session']==period] if per_session else subset if period=='全25場' else [a for a in subset if a['week']==period]
            v=aggregate(subset)
            label=period.replace('_Day',' 昼').replace('_Night',' 夜')+('〈5場・週途中〉' if period==WEEKS[-1] else '')
            rows.append([esc(label),esc(PRODUCTS[s]),fmt(v['gross_profit']),fmt(v['gross_loss']),fmt(v['fees']),fmt(v['net'],colored=True),
                f'{v["win_qty"]}/{v["loss_qty"]}/{v["flat_qty"]}',f'{v["max_long_qty"]}/{v["max_short_qty"]}'])
    return table(['期間','商品','実現利益円','実現損失円','手数料円','純収支円','勝/負/同値枚','最大買/売枚'],rows)


def family_matrix(methods: list[dict], family: str) -> str:
    """機能: 主幅を固定し、保有期限と運用積極度だけを比較する。

    引数: methods(list[dict])、family(str)。返り値: 比較表HTML(str)。
    """
    width='W10' if family.startswith('D') else 'D075'
    chosen=sorted((m for m in methods if m['family']==family and parameters(m)[1]==width),key=lambda m:(parameters(m)[0],parameters(m)[2]))
    assert len(chosen)==18,(family,len(chosen))
    rows=[]
    for m in chosen:
        minutes,_,aggression=parameters(m)
        row=[f'{minutes}分',esc(aggression)]
        for s in SYMBOLS:
            v=aggregate(accounts(m,s))
            row += [fmt(v['net'],colored=True),fmt(v['pf'],2),fmt(v['cycles']),fmt(v['drawdown']),fmt(m['native_hold']['quote'][s],1)]
        rows.append(row)
    return table(['保有上限','積極度','TOPIX純収支円','TOPIX利益損失比','TOPIX決済数※','TOPIX最大下落円','TOPIX保有中央値分','NK純収支円','NK利益損失比','NK決済数※','NK最大下落円','NK保有中央値分'],rows)


def main() -> None:
    """機能: 全450条件の省略なしCSVと、短い説明・比較・場別損益を出力する。

    引数: なし。返り値: なし(None)。選定基準や売買条件は変更しない。
    """
    datasets={b:load(b) for b in ('directional','inventory')}
    methods=[m for values in datasets.values() for m in values]
    findings=json.loads((HERE/'比較と選定.json').read_text(encoding='utf-8'))
    narrative=json.loads((HERE/'報告判断.json').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True,exist_ok=True)
    csv_rows=[]; weekly=[]
    for m in methods:
        minutes,width,aggression=parameters(m)
        for a in m['accounts']:
            csv_rows.append(dict(手法ID=m['id'],系統=m['family'],保有上限分=minutes,幅=width,積極度=aggression,
                約定モデル=MODES[a['price_mode']],セッション=a['session'],銘柄=a['symbol'],
                実現利益円=a['gross_profit'],実現損失円=a['gross_loss'],手数料円=a['fees'],純収支円=a['net'],
                勝ち枚数=a['win_qty'],負け枚数=a['loss_qty'],同値枚数=a['flat_qty'],
                最大買枚数=a['max_long_qty'],最大売枚数=a['max_short_qty'],最大資産下落円=a['drawdown'],
                決済数=a['cycles'],実保有中央値分=a.get('hold_median_minutes'),実保有最大分=a.get('hold_max_minutes',a.get('max_hold_minutes')),
                台帳=a.get('ledger',a.get('ledger_path',''))))
        for mode in sorted({a['price_mode'] for a in m['accounts']}):
            for s in SYMBOLS:
                for period in (*WEEKS,'全25場'):
                    v=aggregate(accounts(m,s,mode,weeks=WEEKS if period=='全25場' else (period,)))
                    weekly.append(dict(手法ID=m['id'],銘柄=s,約定モデル=MODES[mode],期間=period,
                        実現利益円=v['gross_profit'],実現損失円=v['gross_loss'],手数料円=v['fees'],純収支円=v['net'],
                        勝ち枚数=v['win_qty'],負け枚数=v['loss_qty'],同値枚数=v['flat_qty'],
                        利益損失比=v['pf'],平均勝ち負け比=v['payoff'],最大資産下落円=v['drawdown']))
    csv_save('全450条件のセッション損益.csv',csv_rows)
    csv_save('全450条件の週と全体損益.csv',weekly)
    # ----------------------------------------
    # 短い結論と、結果を見て選んだ参考条件を事前主条件から区別する。
    body=f'<nav><a href="../index.html">調査一覧</a><a href="全450条件.html">全条件比較</a><a href="README.md">資料案内</a></nav><h1>{TITLE}</h1><p class="muted">00058／既知25場・2026/9/21昼〜10/7昼。中期・短期の方向性270条件、在庫管理180条件。</p>'
    body+='<div class="notice">'+''.join(f'<p>{esc(t)}</p>' for t in narrative['結論'])+'</div>'
    body+='<p>全てセッション内で返済。手数料はTOPIX mini片道41.8円/枚、NK225 microは11円/枚、注文ごと1円未満切捨て。主評価はラージ板の買ask・売bidで、小型商品の実気配の代理です。</p>'
    rows=[]
    for branch in datasets:
        f=findings[branch]
        rows.append(['方向性' if branch=='directional' else '在庫管理',str(f['count']),str(f['positive']['quote']['TOPIX']),str(f['positive']['quote']['NK225']),
            str(f['common_positive']['quote']),str(len(f['stable'])),str(f['common_positive']['mid']),str(f['common_positive'].get('passive','—'))])
    body+=table(['分類','条件数','TOPIX黒字','NK黒字','両方黒字','安定基準通過','中値で両方黒字','指値仮定で両方黒字'],rows)
    body+='<p class="muted">安定基準＝両銘柄で全体黒字・3週区分黒字・最大黒字場除外も黒字・各20決済組/8稼働場以上。3週目は5場のみです。成績を保証する基準ではありません。</p>'
    body+='<h2>前回から何を変えたか</h2><p>前回の日経グリッドは、持越し玉で−814,600円、場内で返した玉は＋208,320円でした。しかし実際に場内型へ切り替えると−441,728円。早く決済できた勝ち玉だけを選ぶ見方は使えません。</p><p>今回は元の建時刻からの期限を固定し、再配置・追加・両建てで延長しません。逆方向への追加停止と既存玉の整理を分け、有利な方向への追加も比較しました。</p>'
    featured=[]
    for branch in datasets:
        for item in findings[branch]['ranking'][:1]:
            m=next(m for m in datasets[branch] if m['id']==item['id'])
            featured.append(m)
    body+='<h2>両銘柄共通で選ぶ参考条件</h2><p class="muted">両銘柄黒字を優先し、各20決済数/8稼働場以上の中で「悪い方の利益損失比」が最も高い条件。未知データで選んだ条件ではありません。各系統1件。</p>'+summary_table(featured)
    body+=''.join(f'<p>{esc(t)}</p>' for t in narrative['解釈'])
    singles=[]
    for branch in datasets:
        for symbol in SYMBOLS:
            best=findings[branch]['symbol_ranking'][symbol]
            if not best:
                continue
            choice=best[0]
            m=next(m for m in datasets[branch] if m['id']==choice['id'])
            v=choice['values']
            other=next(s for s in SYMBOLS if s!=symbol)
            singles.append(['方向性' if branch=='directional' else '在庫管理',esc(PRODUCTS[symbol]),f'<a href="#{esc(m["id"])}">{esc(m["id"])}</a>',
                fmt(v['net'],colored=True),fmt(v['drawdown']),fmt(v['without_best'],colored=True),fmt(aggregate(accounts(m,other))['net'],colored=True)])
            if all(previous['id']!=m['id'] for previous in featured):
                featured.append(m)
    body+='<h2>銘柄別の期間収支首位</h2><p class="muted">同じ銘柄内で各20決済数/8稼働場以上の純収支を比較した事後の首位です。損失額・数量・最大下落も含めて判断し、もう一方へ適用した結果を併記します。</p>'+table(['系統','順位対象','条件ID','対象の純収支円','対象の最大下落円','最大黒字場除外円','他方へ同じ条件の純収支円'],singles)
    adjacent=[]
    for branch in datasets:
        for symbol,values in findings[branch]['neighbors'].items():
            for v in values:
                adjacent.append(['方向性' if branch=='directional' else '在庫管理',esc(PRODUCTS[symbol]),esc(v['axis']),esc(v['id']),
                    fmt(v['values']['net'],colored=True),fmt(v['values']['drawdown']),fmt(v['values']['without_best'],colored=True)])
    body+='<details><summary>首位の条件を少し変えても黒字か</summary><p>保有時間・幅・積極度の一軸だけを、試した中の隣接設定へ変更した比較です。新しい条件を結果に合わせて追加したものではありません。</p>'+table(['系統','商品','変更軸','比較条件','純収支円','最大下落円','最大黒字場除外円'],adjacent)+'</details>'
    body+='<details><summary>積極度と保有時間の定義</summary><p>上限時間は5・15・30・60・120・240分。損切りや追跡はその前にも働きます。実際の保有分数は各場CSVに載せ、保存時計の空白による遅れも隠しません。例えばI4の主設定では中央値がTOPIX5.05分・NK2.16分。I4の上限120分と240分は全条件で売買が同一で、長い上限を設定しただけでは中期保有になりません。</p><p>方向性：A0は初回TOP2/NK4枚・追加なし・30分休止。A1は5/10枚・追加なし・10分休止。A2は5/10枚から利益方向に2/4枚ずつ追加、上限10/20枚、休止なし。</p><p>在庫管理：A0は1/2枚単位・片方向上限2/4枚・5分休止。A1は1/2枚単位・上限5/10枚・1分休止。A2は2/4枚単位・上限10/20枚・休止なし。数量と頻度をまとめた運用方針で、各要素の単独因果効果とは呼びません。</p></details>'
    for m in featured:
        name,description=DESCRIPTIONS[m['family']]
        body+=f'<section id="{esc(m["id"])}"><h2>{esc(name)}：参考条件</h2><p><code>{esc(m["id"])}</code></p><p>{esc(description)}</p>'
        body+='<details><summary>週・全体の利益/損失/収支と枚数</summary>'+period_table(m)+'</details><details><summary>25セッションの損益</summary>'+period_table(m,True)+'</details></section>'
    # ----------------------------------------
    # 各戦略の事前主条件と、時間・積極度だけを変えた比較を章にする。
    body+='<h2>戦略別：同じ幅で時間と積極度を変える</h2><p class="muted">各章の比較表は方向性0.1%、在庫0.075%の幅を固定。主条件は60分・A1です。幅も変えた全450条件は別表とCSVにあります。</p>'
    for branch,group in datasets.items():
        for family in dict.fromkeys(m['family'] for m in group):
            main=next(m for m in group if m['family']==family and m['primary'])
            name,description=DESCRIPTIONS[family]
            body+=f'<section id="主_{esc(main["id"])}"><h2>{family} {esc(name)}</h2><p>{esc(description)}</p>'
            if branch=='directional':
                body+='<p>入口後は初回建値から1幅損切り。1幅順行後に1幅トレーリング、期限で全返済。追加しても保護線を緩めず、当場損失予算に達したら終了します。</p>'
            else:
                body+='<p>全玉の含みと発生手数料で組全体・当場の損失予算を監視。利益玉だけを計上せず、全玉の結果を合算します。場内の最後には必ず全返済します。</p>'
            body+='<details><summary>6時間軸×3積極度の比較</summary>'+family_matrix(group,family)+'</details>'
            body+='<details><summary>事前主条件の全体・週損益</summary>'+period_table(main)+'</details>'
            body+='<details><summary>事前主条件の25セッション損益</summary>'+period_table(main,True)+'</details></section>'
    body+='<p class="muted">利益・損失は費用前、純収支＝利益−損失−手数料。勝/負/同値枚は往復費用を配分した決済枚数で、同時保有枚数とは別。利益損失比は費用後総利益/総損失、平均勝/負は費用後1枚平均利益/1枚平均損失です。決済組数は方向性では追加玉をまとめた一組、在庫管理では入口ロットごと。互いに独立した標本数とは扱いません。最大下落は全含みと発生費用込み。損失予算は判断線で、損失の上限保証ではありません。</p>'
    body+='<h2>前週までで選んだ場合</h2>'
    sequence=[]
    for branch,f in findings.items():
        for row in f['sequence']:
            chosen=row['selected']
            sequence.append(['方向性' if branch=='directional' else '在庫管理',row['testing'],esc(chosen['id'] if chosen else '該当なし（取引0）'),
                *[fmt(row['next_week'][s]['net'],colored=True) if chosen else '0' for s in SYMBOLS]])
    body+=table(['系統','適用週','先行週から選んだ条件','TOPIX純収支円','NK純収支円'],sequence)
    body+='<p class="muted">先行週まで両方黒字・各10決済組以上の中で小さいPF最大を選び、翌週には変えません。全資料は既知であり、真の未知検証とは呼びません。該当なしの0円は無取引で、収益手法の発見とは扱いません。</p>'
    body+='<h2>現在セッションの一回確認</h2>'+''.join(f'<p>{esc(t)}</p>' for t in narrative['現在確認'])
    live=HERE/'live'/'報告用途中会計.json'
    if live.exists():
        current=json.loads(live.read_text(encoding='utf-8'))
        body+=table(current['headers'],[[fmt(x,colored=True) if isinstance(x,(int,float)) else esc(x) for x in row] for row in current['rows']])
        body+='<p><a href="現在確認の途中会計.csv">現在確認の途中会計CSV（中値参考も収録）</a></p>'
    body+='<details><summary>再現資料と検証の限界</summary><p>全25場は既知です。450条件は実データ損益前に固定し、指標・入口・出口はその時点までの原本だけで判断しました。多条件からの事後選択が将来の収益性を証明するものではありません。中値・指値仮定は主気配とは独立再生で、同じ注文の価格置換とは異なります。</p><p>原本に受信時刻がないため保存CurrentPriceTimeと行順で再生しています。小型商品の実気配、待機指値の順番と全数量約定、証拠金、市場インパクトは再現していません。時間の空白では次に観測できた価格を使い、過去の期限価格へ遡って約定させません。</p><p>方向と保有量に応じた注文変更は<a href="https://arxiv.org/abs/1206.4810">Fodra–Labadieの在庫制約と方向判断の研究</a>も参考にしました。論文の完全再現や、日本先物で利益が出る根拠とはしていません。</p><nav><a href="全450条件のセッション損益.csv">全場CSV</a><a href="全450条件の週と全体損益.csv">週・全体CSV</a><a href="../../work/wave_v61/調査仕様.json">固定仕様</a><a href="../../work/wave_v61/review/前回から変更する根拠.md">前回からの根拠</a><a href="../../work/wave_v61/review/README.md">独立監査</a></nav></details>'
    body+='<p class="muted">I2の待機指値参考は、通過時に反対玉へ返済を割り当てられるネット在庫モデルです。待機時に新規/返済対象を固定する実APIの完全再現ではありません。主の条件成行評価では判断時に返済対象を固定しています。</p>'
    (OUT/(TITLE+'.html')).write_text(page(TITLE,body),encoding='utf-8')
    full=f'<nav><a href="{TITLE}.html">短い説明へ</a></nav><h1>全450条件の比較</h1><p>全て費用後の円収支。Hは保有上限分、W/Dは始値割合の幅、Aは積極度。中値と待機指値は独立した仮定です。</p>'
    for family in DESCRIPTIONS:
        rows=[]
        for m in methods:
            if m['family']!=family:
                continue
            row=[esc(m['id'])+(' ★主' if m['primary'] else '')]
            for s in SYMBOLS:
                main=aggregate(accounts(m,s))
                row += [fmt(main['net'],colored=True),fmt(aggregate(accounts(m,s,'mid'))['net'],colored=True)]
                if family.startswith('I'):
                    row.append(fmt(aggregate(accounts(m,s,'passive'))['net'],colored=True))
                row += [fmt(main['pf'],2),fmt(main['payoff'],2),fmt(main['drawdown']),fmt(main['cycles'])]
            rows.append(row)
        heads=['条件ID']
        for s in SYMBOLS:
            heads += [s+'気配',s+'中値']+([s+'指値仮定'] if family.startswith('I') else [])+[s+'利益損失比',s+'平均勝/負',s+'最大下落',s+'決済数※']
        full+=f'<h2>{family} {esc(DESCRIPTIONS[family][0])}</h2>'+table(heads,rows)
    full+='<p><a href="全450条件のセッション損益.csv">全条件の各セッション会計CSV</a></p>'
    (OUT/'全450条件.html').write_text(page('全450条件の比較',full),encoding='utf-8')
    evidence=dict(全場CSV行数=len(csv_rows),期間CSV行数=len(weekly),条件数=len(methods),会計一致=True,
        入力SHA={b:hashlib.sha256((HERE/b/'集計結果.json').read_bytes()).hexdigest() for b in datasets},
        HTML_SHA={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.html')})
    (HERE/'報告出力照合.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':
    main()
