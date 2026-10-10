"""固定した２候補の現在ナイト再生を、追加区間と分けて暗色HTMLへまとめる。"""

from __future__ import annotations

import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

import pandas as pd

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
DEST = ROOT/'アルゴリズム調査'/'00010_候補２方式の現在セッション再生'
PAGE = '候補２方式の現在セッション再生.html'
SESSION = '2026-09-24_Night'
BOUNDARY = pd.Timestamp('2026-09-25T00:53:00+09:00').timestamp()
PRIMARY = {'NK225':'N03_R-1_L3_U1', 'TOPIX':'N15_R-1_A4_U0'}

# ----------------------------------------
# 過去の図解部品は読み取りだけで再利用する。
sys.path.insert(0, str(ROOT/'work/wave_v13'))
spec = importlib.util.spec_from_file_location('v15_report_parts', ROOT/'work/wave_v13/report.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
money, percent, clean = base.money, base.percent, base.clean


def read_json(name: str) -> object:
    """機能: 今回の保存済みJSON成果を読む。

    引数: name (str)。返り値: JSONの値 (object)。
    """
    return json.loads((WORK/name).read_text(encoding='utf-8-sig'))


def clock_text(value: float | str | None) -> str:
    """機能: 秒または日時を日本時間の表示へ揃える。

    引数: value (float|str|None)。返り値: 日時 (str)。
    """
    if value is None:
        return '—'
    stamp = pd.Timestamp(value, unit='s', tz='UTC').tz_convert('Asia/Tokyo') if isinstance(value,(int,float)) else pd.Timestamp(value)
    return stamp.strftime('%m/%d %H:%M:%S')


def ratio(value: float | None) -> str:
    """機能: 算出対象のない比率を無限大へ変えず表示する。

    引数: value (float|None)。返り値: 表示文字列 (str)。
    """
    return '算出対象なし' if value is None or pd.isna(value) else f'{value:.3f}'


def configs_and_rules() -> tuple[dict, dict]:
    """機能: 事前に指定された２条件と説明を読み取りだけで準備する。

    引数: なし。返り値: 条件と日本語説明 (tuple[dict,dict])。
    """
    original = json.loads((ROOT/'work/wave_v14/単独条件一覧.json').read_text(encoding='utf-8'))
    configs = {c['id']:c for c in original if c['id'] in PRIMARY.values()}
    profiles = {p['id']:p for p in json.loads((ROOT/'work/wave_v13/信号条件一覧.json').read_text(encoding='utf-8'))}
    rules = {key:base.rules_for(c,profiles) for key,c in configs.items()}
    rules[PRIMARY['NK225']].append('２枚のうち１枚だけが利確しても、残り１枚の損益を含めて１サイクルとして評価する。0.5ATRの順行だけで残玉の利益が守られるわけではない。丸めを無視すると0.75ATR超の順行で追跡が初期ストップより強まり、1.5ATRの順行で残玉のストップが建値に達する。')
    rules[PRIMARY['NK225']].append('今回の米国市場開始に対応する新規休止は日本時間22:15以上23:00未満。待機中の新規は取り消すが、保有玉の返済条件は継続する。')
    rules[PRIMARY['TOPIX']].append('上昇の未反映を検知した場合は、方向を反転し価格−0.5ATRへ売り逆指値を置く。下落の未反映なら価格＋0.5ATRへ買い逆指値を置く。通知だけでは入らず、反対方向への到達を待つ。')
    rules[PRIMARY['TOPIX']].append('OFIは板更新に現れる買い・売り圧力の数量差分。過去の圧力と値動きの関係から予想した変化に対し、実際の価格がどれだけ動いたかを比較する。今回はその未反映方向に追随する規則を反転して使う。')
    return configs,rules


def chart_controls() -> str:
    """機能: 銘柄切替・拡大操作と暗色チャートの表示領域を作る。

    引数: なし。返り値: HTML (str)。
    """
    return '''<div class="chart-controls"><label>銘柄<select id="symbol"><option>NK225</option><option>TOPIX</option></select></label><label class="wide">固定した候補<select id="method" disabled></select></label><label>セッション<select id="session" disabled></select></label><button id="primary">この銘柄の候補</button><button id="reset">セッション全体</button></div>
    <div id="rule" class="chart-rule"></div><div id="chart-summary" class="stats"></div>
    <div class="legend"><span class="green">▲ 買い新規</span><span class="orange">▼ 売り新規</span><span class="blue">● 返済</span><span class="purple">◆ 未返済の評価</span><span class="purple">縦線：00:53の追加区間境界</span></div>
    <div class="chart-box"><canvas id="price" height="490" aria-label="５分足と全脚の売買図"></canvas><div id="tooltip" class="tooltip"></div></div>
    <div class="chart-box"><canvas id="equity" height="190" aria-label="全建玉の評価と確定収支"></canvas></div>
    <p id="chart-note" class="note"></p><div id="trade-table" class="table-wrap"></div>'''


def script() -> str:
    """機能: 既存描画へ今回の未読境界と候補表記を追加する。

    引数: なし。返り値: JavaScript (str)。
    """
    value = base.SCRIPT
    value = value.replace("['利益',yen", "['返済脚の利益',yen").replace("['損失',yen", "['返済脚の損失',yen").replace('返済脚／未返済','返済脚／未返済脚')
    value = value.replace("...visibleTrades.map(t=>t.exit+120)", "...visibleTrades.map(t=>t.exit+120),...(DATA.curves[key()]||[]).map(r=>r[0]+120)")
    value = value.replace('drawEquity(start,end);}', "if(DATA.boundary>=start&&DATA.boundary<=end){const bx=g.X(DATA.boundary);ctx.strokeStyle='#c1a2ff';ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(bx,g.p.t);ctx.lineTo(bx,g.p.b);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#c1a2ff';ctx.fillText('追加区間 00:53 →',Math.min(bx+8,g.p.r-145),g.p.t+16);}drawEquity(start,end);}")
    return value


def chart_data(full: list[dict], configs: dict, rules: dict) -> dict:
    """機能: 実際の新規時刻・価格を使い、全体再生の図を準備する。

    引数: full (list[dict])、configs/rules (dict)。返り値: 図用データ (dict)。
    追加区間の差分用に変更した建値はチャートの新規マーカーへ使わない。
    """
    candles,curves,summaries={},{},{}
    legs=[]
    for row in full:
        symbol,method,session=row['銘柄'],row['方式'],row['セッション']
        bars=pd.read_csv(WORK/f'live/candle_5min/{symbol}/{session}.csv')
        candles[f'{session}|{symbol}']=[[pd.Timestamp(t['time']).timestamp(),t['open'],t['high'],t['low'],t['close']] for t in bars.to_dict('records')]
        key=f'{method}|{session}|{symbol}'
        curves[key]=row['equity'];summaries[key]=row['summary']
        for t in row['trades']:
            legs.append(dict(method=method,session=session,symbol=symbol,condition=t['条件設定時刻'],
                entry=t['新規時刻'],exit=t['返済評価時刻'],ep=t['新規価格'],xp=t['返済評価価格'],
                side=int(t['方向']),closed=bool(t['返済済み']),pnl=t['収支円'],reason=t['返済理由'],
                leg=int(t['脚番号'])+1,cycle=int(t['サイクル番号'])+1,atr=t['固定ATR'],
                mfe=t['最大順行幅'],holding=t['保有分']))
    return clean(dict(candles=candles,trades=legs,curves=curves,summaries=summaries,
        methods={m:dict(label=base.label_for(c),rules=rules[m],cap=c['max_legs']) for m,c in configs.items()},
        sessions={SESSION:'9/24 ナイト・開始から取得締切まで'},primary=PRIMARY,boundary=BOUNDARY))


def result_table(doc: object, rows: list[dict], label: str) -> None:
    """機能: 利益・損失・確定と含み・全玉最大下落を同じ表にする。

    引数: doc (Document)、rows (list[dict])、label (str)。返り値: なし (None)。
    """
    doc.text(label)
    table=[]
    for row in rows:
        s=row['summary']
        table.append([row['銘柄'],money(s['profit_yen']),money(abs(s['loss_yen']),False),
            money(s['closed_net_yen']),money(s['open_yen']),money(s['net_yen']),
            money(s['max_drawdown_yen'],False),f"{s['closed_count']} / {s['open_count']}"])
    doc.table(['銘柄','返済脚の利益','返済脚の損失（絶対額）','確定純損益','未返済の評価','合計評価','全玉最大下落','返済脚 / 未返済脚'],table)


def cycle_table(doc: object, rows: list[dict], field: str, label: str) -> None:
    """機能: 全脚をまとめた完了サイクルの平均勝敗とPFを示す。

    引数: doc (Document)、rows (list[dict])、field/label (str)。返り値: なし (None)。
    """
    doc.text(label)
    table=[]
    for row in rows:
        s=row[field]
        table.append([row['銘柄'],f"{s['complete_cycles']} / {s['incomplete_cycles']}",
            f"{s['wins']} / {s['losses']} / {s['flats']}",percent(s['win_rate']),
            money(s['avg_win']),money(s['avg_loss'],False),ratio(s['payoff_ratio']),ratio(s['profit_factor'])])
    doc.table(['銘柄','完了 / 未完了組','勝 / 負 / 引分','勝率','平均勝額','平均負額','損益比','PF'],table)


def document(full: list[dict], extra: list[dict], record: dict, configs: dict, rules: dict) -> object:
    """機能: 保存済み数値から結果・返済条件・検証範囲の本文を作る。

    引数: full/extra (list[dict])、record/configs/rules (dict)。返り値: 文書 (Document)。
    """
    doc=base.Document()
    doc.section('result','１．今回の２候補を、そのまま現在ナイトへ適用')
    doc.text('NK225は N03_R-1_L3_U1（適応平均の逆方向・同時２枚）、TOPIXは N15_R-1_A4_U0（板の価格応答差の逆方向・逆指値１枚）に固定した。今回のデータを見て、方向・入口・出口・枚数・時間帯を変更していない。')
    doc.text(f"対象は{clock_text(record['セッション開始'])}から{clock_text(record['取得締切未満'])}未満まで。今回初めて照合した追加区間は09/25 00:53:00以上であり、それより前は00009までに取得済みの参考部分。",'callout')
    doc.text('費用０・気配差控除０・条件価格で約定する仮定を維持。ラージ相当でNK225は価格差×1,000円、TOPIXは価格差×10,000円。NK225は最大２枚、TOPIXは最大１枚で、未返済を含む全玉を計算する。')
    result_table(doc,extra,'追加区間だけの収支（00:53直前の全玉評価を差し引いた増分）')
    doc.text('同じナイトの前半から継続する玉がある場合は、00:53以降の変化も追加収支へ含める。今回は両銘柄とも00:53で建玉がなく、追加区間の新規取引だけである。「確定」は追加区間内に返済した脚の損益、「未返済の評価」は締切時点で残る脚の損益。前半の収支を再加算しない。','note')
    result_table(doc,full,'ナイト開始からの全体再生（既知部分を含む参考値）')
    doc.text('17時からこの条件で稼働していた場合の履歴再生であり、今から建玉ゼロで始めた未来収益を示すものではない。実注文も行っていない。この１セッションの結果だけで安定した有効性を判断しない。','note')
    doc.end()
    doc.section('cycles','２．利益玉だけで数えず、全玉の結末で比較')
    cycle_table(doc,full,'cycle_summary','全体再生：同時に始めた玉がすべて返済されて初めて１サイクルが完了する。')
    cycle_table(doc,extra,'fresh_summary','追加区間で新しく開始したサイクルだけ（前半からの継続玉を除く）')
    rows=[]
    for row in extra:
        carried=[c for c in row['cycles'] if c.get('carried')]
        fresh=[c for c in row['cycles'] if not c.get('carried')]
        rows.append([row['銘柄'],len(carried),money(sum(c['net_yen'] for c in carried)),len(fresh),money(sum(c['net_yen'] for c in fresh)),money(row['boundary']['baseline_equity_yen'])])
    doc.table(['銘柄','前半から継続した組','継続分の追加損益','追加区間の新規組','新規分の損益','00:53直前の基準評価'],rows)
    for row in extra:
        s=row['fresh_summary']
        if s['incomplete_cycles']:
            doc.text(f"{row['銘柄']}の追加区間では、全玉を返済した組の合計が{money(s['complete_net'])}、まだ未完了の組が既返済分と含みを合わせて{money(s['incomplete_net'])}。未完了組の利益を、すでに完了した勝ちとして数えていない。",'callout')
    episodes=[]
    for row in extra:
        original=next(x for x in full if x['銘柄']==row['銘柄'])
        for c in row['cycles']:
            legs=[t for t in original['trades'] if int(t['サイクル番号'])==c['cycle_id']]
            first=min(legs,key=lambda t:t['新規時刻'])
            episodes.append([row['銘柄'],int(c['cycle_id'])+1,clock_text(first['新規時刻']),
                '買い' if first['方向']>0 else '売り',first['新規価格'],len(legs),
                money(c['closed_yen']),money(c['open_yen']),money(c['net_yen']),
                '全返済' if c['complete'] else '未完了'])
    doc.table(['銘柄','組','実際の新規時刻','方向','新規価格','枚数','追加区間の確定','追加区間の含み','組の追加評価','状態'],episodes)
    doc.text('今回のNK225は、00:54の組が−１万円、01:22の組が−２万円。その後01:42に65,880で２枚売り、１枚を01:44:30に65,820で利確して＋６万円、残りが＋31万円の評価になった。２連敗後の３組目が追加収支を押し上げている。連敗停止が常に改善するとは限らず、今回は固定どおり停止条件を追加していない。','note')
    doc.text('損益比＝平均勝額÷平均負額、PF＝完了サイクルの利益合計÷損失絶対額合計。未完了組の既返済利益は、勝ちサイクルへ加えない。勝率は引分も分母に含む。平均勝額または平均負額がなければ損益比は算出対象なし。損失がなければPFは算出対象なし、損失だけならPFは０となる。','note')
    doc.end()
    doc.section('charts','３．５分足と実際の入口・出口')
    doc.text('銘柄を切り替えると、その銘柄に固定した候補の全脚を表示する。NK225の同時２枚は同じ新規位置に重なるが、表では各１枚を分ける。表の行を選ぶと該当建玉の前後へ拡大する。紫の縦線より右側が今回の追加区間。')
    doc.parts.append(chart_controls())
    doc.markdown.append('[５分足・売買と全玉評価曲線]('+PAGE+'#charts)\n')
    doc.text('上段は全体再生の本来の新規・返済価格、下段は全玉評価と確定収支。追加区間の差分計算用に変更した建値を、新規マーカーには使わない。末尾の５分足は描画上の参考であり、未確定足を信号へ混ぜていない。','note')
    doc.end()
    doc.section('state','４．取得末尾の建玉と返済条件')
    doc.text('次の表は再生上の状態であり、実口座の建玉・注文ではない。ストップは表示末尾より後の有効な原本行から監視する条件。買い玉は価格がストップ以下、売り玉はストップ以上へ達すると返済する。')
    for row in full:
        state=row['state'];symbol=row['銘柄']
        doc.text(f"{symbol}：最終価格 {state['評価価格']:,.1f}、評価時刻 {clock_text(state['評価時刻秒'])}。")
        positions=[]
        for p in state['建玉']:
            positions.append([f"{int(p['サイクル番号'])+1}–{int(p['脚番号'])+1}",p['方向'],p['枚数'],clock_text(p['新規時刻秒']),
                p['新規価格'],p['評価価格'],money(p['含み損益円']),f"{p['固定ATR']:.4f}",p['初期損切り価格'],
                p['有効返済ストップ'],'追跡のみ' if p['利確価格'] is None else p['利確価格'],p['順行極値'],'あり' if p['返済予約中'] else 'なし'])
        if positions:
            doc.table(['組–脚','方向','枚数','新規時刻','新規価格','評価価格','含み','固定ATR','初期ストップ','現在有効ストップ','固定利確','順行極値','次行返済予約'],positions)
            for p in state['建玉']:
                direction=1 if p['方向']=='買い' else -1
                protected=direction*(p['有効返済ストップ']-p['新規価格'])*p['枚数']*({'NK225':1000,'TOPIX':10000}[symbol])
                doc.text(f"{symbol}のこの残玉が現在有効なストップ{p['有効返済ストップ']:,.1f}で返済される場合、指定価格約定の仮定では残玉の収支は{money(protected)}。現在の含み評価との差は{money(p['含み損益円']-protected,False)}。さらに順行すれば追跡価格も更新される。",'note')
        else:
            doc.text(f'{symbol}の未返済建玉はない。')
        pending=state['未約定新規']
        if pending:
            doc.table(['未約定の新規方向','方式','指定価格','条件設定','期限','固定ATR'],[[
                '買い' if pending['方向']>0 else '売り',pending['注文種別'],pending['指定価格'],clock_text(pending['設定時刻秒']),clock_text(pending['期限秒']),f"{pending['固定ATR']:.4f}"]])
        else:
            doc.text(f'{symbol}の未約定新規はない。')
    doc.text('両方式とも05:20以降は新規を停止し、05:50で全返済を判断して次の有効原本行で返済する。現在の未返済をセッション終了まで放置して持ち越す規則ではない。追跡条件が更新されれば、ここに表示したストップも利益保護が強まる方向へ変わる。','note')
    doc.end()
    doc.section('rules','５．２方式の機械的な入口・出口')
    for symbol,method in PRIMARY.items():
        doc.method(symbol+'：'+method,rules[method])
    doc.text('呼値はNK225が10ポイント、TOPIXが0.5ポイント。上方向の閾値は切上げ、下方向は切下げ。買いの損切り価格は切下げ、売りは切上げる。ATRは条件を採用した時点で固定し、保有中の未来のATRへ差し替えない。')
    doc.text('新規は保有なし・待機なし・返済後５分経過などを満たす原本行で受けた通知だけを採用する。過去に出た通知を、保有や待機が終わってから拾い直さない。')
    doc.end()
    doc.section('audit','６．固定・取得・検査の記録')
    doc.text('条件と計算コードを固定してから現在セッションの６URLを各１回取得。原時刻の同一時刻ブロックの封印、確定足の利用時刻、既存の信号遅延と原本順の約定規則を保持する。現在を読んだ後の条件選択・再探索は行わない。')
    links=[]
    for path in sorted(WORK.iterdir()):
        if path.is_file() and path.suffix in ['.md','.json'] and path.name not in ['結果_全体.json','結果_追加区間.json']:
            links.append(f'<a href="資料/{html.escape(path.name)}">{html.escape(path.name)}</a>')
            doc.markdown.append(f'- [{path.name}](資料/{path.name})\n')
    doc.parts.append('<div class="sources">'+' '.join(links)+'</div>')
    doc.parts.append('<p><a href="資料/結果_全体.json">全体の全脚・状態・資産曲線</a> ／ <a href="資料/結果_追加区間.json">追加区間の差分会計・全脚</a></p>')
    doc.markdown.append('\n[全体データ](資料/結果_全体.json) ／ [追加区間データ](資料/結果_追加区間.json)\n')
    doc.end()
    return doc


def navigation() -> None:
    """機能: 今回の結果を全体索引へ追加し、過去作業を保持する。

    引数: なし。返り値: なし (None)。
    """
    folder = DEST.name
    path = DEST.parent/'README.md'
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'\*\*最新は.*?\*\*',f'**最新は00010の[候補２方式の現在セッション再生]({folder}/{PAGE})です。固定したNK225・TOPIXの２方式について、ナイト全体と00:53以降の追加区間を分けて確認します。**',text,count=1)
    text = re.sub(r'^\| `00010_.*\n','',text,flags=re.M).replace('`00009_銘柄別の損小利大と建玉管理`（最新）','`00009_銘柄別の損小利大と建玉管理`')
    row=f'| `{folder}`（最新） | 候補２方式の全脚・現在建玉・追加区間の収支 | [５分足と結果]({folder}/{PAGE}) | [結果]({folder}/検証結果.md)・[案内]({folder}/README.md) |\n'
    text=text.replace('| --- | --- | --- | --- |\n','| --- | --- | --- | --- |\n'+row,1).replace('`00010_内容`','`00011_内容`')
    path.write_text(text,encoding='utf-8')
    path=DEST.parent/'index.html';text=path.read_text(encoding='utf-8')
    text=re.sub(r'\s*<!--00010開始-->.*?<!--00010終了-->','',text,flags=re.S)
    text=text.replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    text=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新は、固定した候補２方式を現在ナイトの開始から再生し、00:53以降の追加区間と分けて確認した資料です。</p>',text,count=1,flags=re.S)
    text=re.sub(r'<footer>最新作業は.*?</footer>','<footer>最新作業は00010です。過去の作業資料を残し、次の別作業は00011以降へ追加します。</footer>',text,count=1,flags=re.S)
    card=f'''<!--00010開始--><article class="task latest"><div class="number">作業00010 <span class="badge">最新</span></div><h2>候補２方式の現在セッション再生</h2><p>NK225は適応平均の逆方向・２枚分割返済、TOPIXは板の価格応答の逆方向・逆指値。全体再生と追加区間、現在建玉と返済条件を分けて確認します。</p><a class="button" href="{folder}/{PAGE}">結果と５分足売買図を開く →</a><p><a href="{folder}/検証結果.md">検証結果</a> · <a href="{folder}/README.md">読む順序</a></p></article><!--00010終了-->'''
    path.write_text(text.replace('</header>','</header>'+card,1),encoding='utf-8')


def main() -> None:
    """機能: 親で確定した再生結果を読み、HTML・MD・索引を生成する。

    引数: なし。返り値: なし (None)。市場データ取得・売買計算は行わない。
    """
    full=read_json('結果_全体.json');extra=read_json('結果_追加区間.json');record=read_json('評価記録.json')
    configs,rules=configs_and_rules()
    if {r['銘柄']:r['方式'] for r in full} != PRIMARY or {r['銘柄']:r['方式'] for r in extra} != PRIMARY:
        raise ValueError('固定した対象２方式と出力が一致しません')
    doc=document(full,extra,record,configs,rules)
    chart=chart_data(full,configs,rules)
    DEST.mkdir(parents=True,exist_ok=True)
    materials=DEST/'資料';materials.mkdir(exist_ok=True)
    for path in WORK.iterdir():
        if path.is_file() and path.suffix in ['.py','.md','.csv','.json']:
            shutil.copy2(path,materials/path.name)
    serialized=json.dumps(chart,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/')
    page='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>候補２方式の現在セッション再生｜00010</title><style>'''+base.CSS+'''</style></head><body>
<!--
[コンポーネント概要]
本文は固定した２方式の全体再生・追加区間・現在状態を分けて表示します。
#symbol は対象銘柄を切り替え、#method と #session は固定対象を表示します。
#price は５分足と本来の新規・返済、#equity は含み込み全玉評価と確定収支です。
#trade-table は各１枚の脚を表示し、行を選ぶと該当建玉へ拡大します。
#reset で全体へ戻します。紫の縦線は00:53の追加区間開始です。外部通信は行いません。
--><main><header><div class="eyebrow">作業00010 ／ 固定した候補２方式</div><h1>現在ナイトで再生した<br>入口・出口と残っている建玉</h1><p class="lead">NK225は２枚の分割返済、TOPIXは板の価格応答差。全体の参考値と00:53以降を分けて読む。</p><div class="badges"><span>費用０</span><span>指定価格約定</span><span>条件変更なし</span><span>実注文なし</span><span>セッション内返済</span></div></header><nav><a href="#result">収支</a><a href="#cycles">全玉の結末</a><a href="#charts">５分足売買図</a><a href="#state">現在建玉・返済条件</a><a href="#rules">入口・出口</a><a href="#audit">取得と検査</a><a href="../index.html">全作業</a></nav>'''+''.join(doc.parts)+'''<footer>ラージ換算。NK225：１ポイント1,000円、TOPIX：１ポイント10,000円。図と本文はオフラインで開けます。元データと過去の調査フォルダは変更していません。</footer></main><script type="application/json" id="data">'''+serialized+'''</script><script>'''+script()+'''</script></body></html>'''
    (DEST/PAGE).write_text(page,encoding='utf-8')
    (DEST/'検証結果.md').write_text('# 候補２方式の現在セッション再生\n\n[５分足と全建玉の図]('+PAGE+')\n\n'+'\n'.join(doc.markdown),encoding='utf-8')
    (DEST/'README.md').write_text(f'''# 00010 候補２方式の現在セッション再生

**最初に見るファイル：[検証結果と５分足売買図]({PAGE})**

読む順序：

1. 第１章で、00:53以降の追加区間とナイト全体の参考収支を確認する。
2. 第２章で、利益玉だけでなく全玉をまとめた平均勝額・平均負額・PFを読む。
3. 第３章で、NK225・TOPIXを切り替え、各脚の新規・返済と全玉評価曲線を見る。
4. 第４章で、取得末尾の未返済建玉と現在有効な返済条件を見る。
5. 第５章で固定した機械的ルールを読み、第６章の固定・取得・監査資料で確認する。

[検証結果.md](検証結果.md)は表と説明をまとめた文字版。

対象はNK225 `N03_R-1_L3_U1` とTOPIX `N15_R-1_A4_U0`。00:53以前は既知データであり、新たな未読照合は00:53以降だけ。
ナイト開始から稼働していた場合の再生で、今から開始した未来収益や実発注の実績ではない。
費用０・条件価格約定・ナイト05:50の全返済判断を維持する。

詳細：[全体結果](資料/結果_全体.json) ／ [追加区間結果](資料/結果_追加区間.json) ／ [評価記録](資料/評価記録.json) ／ [検証計画](資料/検証計画.md)

報告の再生成：`python work/wave_v15/report.py`。保存済み結果を読むだけで、市場APIへ接続しない。
''',encoding='utf-8')
    navigation()
    (WORK/'表示構文確認.js').write_text(script(),encoding='utf-8')
    print(json.dumps(dict(報告=str(DEST/PAGE),方式数=len(PRIMARY),全脚=len(chart['trades']),HTML_SHA256=hashlib.sha256((DEST/PAGE).read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
