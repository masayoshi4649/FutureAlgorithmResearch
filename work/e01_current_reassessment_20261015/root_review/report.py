"""完成金融の一読射影から、簡潔な比較と全33場の損益を公開する。"""

from datetime import datetime, timezone, timedelta
import hashlib
import html
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PUBLIC=ROOT/'アルゴリズム調査/00113_現在の注文活動と再進行から波の中間に参加'
SOURCE=HERE/'finance/結果.json'
TITLE='現在の活動と再進行から参加する手法と全セッション損益.html'
ACCOUNT='現在の活動と再進行の公開会計.json'
BASE_ID='E01_EVID_VOL_SELECTED_TARGET'
JST=timezone(timedelta(hours=9))


def money(value: float | None) -> str:
    """
    機能: 円額を正負と未知の区別を保って短く表示する。
    引数: value(float|None) は円額。
    返り値: str は整数円又は未定義。
    """
    return '未定義' if value is None else f'{value:+,.0f}'


def ratio(value: float | None) -> str:
    """
    機能: 無取引等で未定義の金額割合を零へ補完せず表示する。
    引数: value(float|None) は0～1の割合。
    返り値: str は百分率又は未定義。
    """
    return '未定義' if value is None else f'{value*100:.1f}%'


def method(config: dict | None) -> tuple[str,str]:
    """
    機能: 英文IDを入口と出口の平易な説明へ結ぶ。
    引数: config(dict|None) は新条件又は保存基準。
    返り値: tuple[str,str] は短い名前と説明。
    """
    if config is None:
        return '旧基準：出来高選択・固定利確','旧E01の初回方向で一度審査する保存基準。今回とは入口母集団と途中・出口も異なる。'
    entry={
        'CURRENT_VOL_SEL':('① 活動','現在の出来高方向代理が偏り、確定水準を越えた両気配がさらに進んだら入る。'),
        'CURRENT_VOL_PRICE':('② 活動＋両市場','①に日経とTOPIXの同方向の価格更新を加える。'),
        'CURRENT_VOL_PRICE_RESPONSE':('③ 反対活動を耐えた再進行','②に、新しい反対活動が出ても大きく崩れず、その後両気配が再進行する確認を加える。')
    }[config['entry_id']]
    exit_label={'TARGET':'固定利確','TIGHT_TRAIL':'狭い利益トレール','WIDE_TRAIL':'広い利益トレール'}[config['exit_id']]
    return entry[0]+'／'+exit_label,entry[1]+' 支持線の崩れか現金損切りで撤退し、順行時は'+exit_label+'で返済。保有時間は固定しない。'


def normalized(value: dict) -> dict:
    """
    機能: 九新金融と保存基準の定義をそろえ、出典と再利用区分を保つ。
    引数: value(dict) は一読済み完成結果。
    返り値: dict は十表示条件と全場小会計。旧経済を再金融しない。
    """
    cases={}
    for cid,case in value['results'].items():
        name,description=method(case['config'])
        rows=[dict(session=r['session'],symbol=r['symbol'],profit=r['利益'],loss=r['損失'],net=r['収支'],
                   campaigns=r['親数'],winning_lots=r['勝ち枚数'],losing_lots=r['負け枚数'],fees=r['費用']) for r in case['rows']]
        metrics={}
        for symbol in ('TOPIX','NK225'):
            metrics[symbol]={}
            for label,new in (('full','全場'),('top3','上位3黒字場除外'),('day','デイ'),('night','ナイト'),('first','前半'),('last','後半')):
                z=case['periods'][symbol][new]
                metrics[symbol][label]=dict(profit=z['aggregate']['利益'],loss=z['aggregate']['損失'],net=z['aggregate']['収支'],
                    profit_share=z['aggregate']['利益割合'],sessions=z['session_count'],positive=z['positive_sessions'],negative=z['losing_sessions'],
                    active=z['active_sessions'],no_trade=z['no_trade_sessions'],mean_session_net=z['mean_session_net_yen'],
                    mean_positive_session_net=z['mean_positive_session_net_yen'],worst_session_loss=z['worst_negative_session_abs_yen'],
                    pass_all=z['all_stability_targets'],primary_pass=z['all_main_targets'],
                    tests=dict(share65=z['target65'],red20=z['target_red20'],coverage=z['target_worst_mean']))
            metrics[symbol]['directions']=case['periods'][symbol]['方向']
        cases[cid]=dict(name=name,description=description,config=case['config'],rows=rows,metrics=metrics,new_financial=True)
    base=value['保存基準']['case']
    name,description=method(None)
    cases[BASE_ID]=dict(name=name,description=description,config=None,rows=base['rows'],metrics=base['metrics'],new_financial=False)
    for cid,case in cases.items():
        assert len(case['rows'])==66
        for symbol in ('TOPIX','NK225'):
            rows=[r for r in case['rows'] if r['symbol']==symbol]
            for field in ('profit','loss','net'):
                assert abs(sum(r[field] for r in rows)-case['metrics'][symbol]['full'][field])<1e-5
            assert {r['session'] for r in rows}==set(value['sessions'])
            assert sum(r['campaigns'] for r in rows)==(case['metrics'][symbol]['full'].get('campaigns') or sum(r['campaigns'] for r in rows))
    return dict(全合格=True,sessions=value['sessions'],cases=cases,表示主候補=value['表示主候補'],掲載比較=10,
                新金融口座=value['新金融口座'],保存基準会計=66,保存基準再金融=0,未読追加場=['2026-10-13_Night','2026-10-14_Day'],
                基準の出典=value['保存基準']['出典'],留保=['既知33場の探索。新2場の金融は未測定。',
                '出来高増加の方向代理は真の攻撃注文量や参加者心理ではない。','価格時計は受信時計ではない。ラージ気配でmini/microを代理、実商品のqueue/部分約定は未測。'])


def clock(point: dict) -> str:
    """
    機能: 保存価格時計を日本時間の観測時刻へ変換する。
    引数: point(dict) はprice_time_sを持つ一次診断。
    返り値: str は日時。真の受信時刻とは呼ばない。
    """
    return datetime.fromtimestamp(point['price_time_s'],JST).strftime('%m/%d %H:%M:%S')


def losses(result: dict, cid: str) -> str:
    """
    機能: 事前主候補の赤字上位3場から最大負け親の当時根拠を具体表示する。
    引数: result(dict)、cid(str) は一次完成結果と事前候補。
    返り値: str は損失時刻・BBO・当時票・実返済を持つHTML。
    """
    case=result['results'][cid]
    blocks=[]
    for symbol,label in (('TOPIX','TOPIX'),('NK225','日経')):
        bad=sorted((r for r in case['rows'] if r['symbol']==symbol and r['収支']<0),key=lambda r:r['収支'])[:3]
        for row in bad:
            pp=[p for p in case['parent_diagnostics'] if p['symbol']==symbol and p['session']==row['session']]
            assert pp
            p=min(pp,key=lambda p:p['net_yen'])
            enter=p['entry'];exit=p['exits'][0];z=enter['判断']
            up,down=z['volume_up'],z['volume_down']
            blocks.append(f'<li><b>{label} {html.escape(row["session"])}：場収支{money(row["収支"])}円</b>。最大負け親は'
                f'{clock(z)}判断、{clock(enter["約定"])}に{"買い" if p["side"]>0 else "売り"} {enter["quantity"]}枚 @ {enter["price"]:g}。'
                f'判断時BBO {z["bid"]:g}/{z["ask"]:g}、出来高代理 上{up}/下{down}、'
                f'自己/相手価格票 {z["own_price_count"]}/{z["peer_price_count"]}、相手時刻差{z["peer_price_age_seconds"]:g}秒。'
                f'{clock(exit["判断"])}に{html.escape(exit["reason_label"])}、{clock(exit["約定"])} @ {exit["price"]:g}で返済し、'
                f'親収支{money(p["net_yen"])}円。保有中の最良純清算は{money(p["best_parent_liquidation_yen"])}円（事後診断）。</li>')
    return '<ul>'+''.join(blocks)+'</ul>' if blocks else '<p>この候補の赤字場はありません。活動数と利益規模も別に確認してください。</p>'


def render(account: dict, result: dict) -> str:
    """
    機能: 簡潔な十比較と、選んだ手法の全場損益を暗色で表示する。
    引数: account/result(dict) は検算済み公開射影と一次結果。
    返り値: str は自己完結HTML。外部通信しない。
    """
    main=account['表示主候補']
    cases=account['cases']
    ids=[main]+[cid for cid in cases if cid!=main]
    passes=[cid for cid in ids if cases[cid]['new_financial'] and all(cases[cid]['metrics'][s]['full']['primary_pass'] for s in ('TOPIX','NK225'))]
    summary=[];chapters=[];options=[]
    for index,cid in enumerate(ids):
        case=cases[cid]
        options.append(f'<option value="c{index}">{html.escape(case["name"])}</option>')
        for symbol,label in (('TOPIX','TOPIXミニ10枚'),('NK225','日経マイクロ20枚')):
            z=case['metrics'][symbol]['full']
            summary.append(f'<tr><td>{html.escape(case["name"])}</td><td>{label}</td><td>{money(z["mean_session_net"])}円</td>'
                f'<td>{ratio(z["profit_share"])}</td><td>{z["negative"]}/{z["sessions"]}</td><td>{z["no_trade"]}</td>'
                f'<td>{money(-z["worst_session_loss"])}円</td><td>{money(z["mean_positive_session_net"])}円</td>'
                f'<td>{"数式合格" if z["primary_pass"] else "未達"}</td></tr>')
        rows=[]
        lookup={(r['session'],r['symbol']):r for r in case['rows']}
        for session in account['sessions']:
            cells=[f'<td>{html.escape(session.replace("_Day"," デイ").replace("_Night"," ナイト"))}</td>']
            for symbol in ('TOPIX','NK225'):
                r=lookup[(session,symbol)]
                css='pos' if r['net']>0 else 'neg' if r['net']<0 else 'zero'
                cells.extend([f'<td>{r["profit"]:,.0f}</td>',f'<td>{r["loss"]:,.0f}</td>',
                    f'<td class="{css}">{money(r["net"])}<small>{r["campaigns"]}親・利益{r["winning_lots"]}枚／損失{r["losing_lots"]}枚</small></td>'])
            rows.append('<tr>'+''.join(cells)+'</tr>')
        foot='<tr><th>合計</th>'+''.join(f'<th>{case["metrics"][s]["full"][k]:+,.0f}</th>' for s in ('TOPIX','NK225') for k in ('profit','loss','net'))+'</tr>'
        trims=' / '.join(label+' '+money(case['metrics'][symbol]['top3']['mean_session_net'])+'円/場・金額利益'+ratio(case['metrics'][symbol]['top3']['profit_share']) for symbol,label in (('TOPIX','TOPIX'),('NK225','日経')))
        chapters.append(f'<section id="c{index}" class="method" {"" if index==0 else "hidden"}><h2>{html.escape(case["name"])}</h2>'
            f'<p>{html.escape(case["description"])}</p><p class="muted">ID：{html.escape(cid)}。上位3黒字場除外：{trims}。</p>'
            '<div class="scroll"><table><thead><tr><th rowspan="2">セッション</th><th colspan="3">TOPIXミニ10枚（円）</th><th colspan="3">日経マイクロ20枚（円）</th></tr>'
            '<tr><th>利益</th><th>損失</th><th>収支・枚数</th><th>利益</th><th>損失</th><th>収支・枚数</th></tr></thead>'
            '<tbody>'+''.join(rows)+'</tbody><tfoot>'+foot+'</tfoot></table></div></section>')
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+f'<title>{html.escape(TITLE.removesuffix(".html"))}</title>'+'''<style>
    :root{color-scheme:dark;background:#101720;color:#e5edf7;font-family:Meiryo,sans-serif}body{margin:0;line-height:1.7}main{max-width:1250px;margin:auto;padding:28px 20px}h1{font-size:26px}h2{font-size:21px}p{overflow-wrap:anywhere}.card,section{background:#182333;border:1px solid #34455e;border-radius:12px;padding:20px;margin:20px 0}a{color:#90c5ff}.muted,small{color:#acbed3}small{display:block;white-space:nowrap;font-size:11px}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:10px 8px;border-bottom:1px solid #34455e;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{color:#bbd4ef;background:#1f2e43}.pos{color:#70dfb4}.neg{color:#ff9595}.zero{color:#a5b4c7}select{font:inherit;max-width:100%;padding:10px;color:#eff5ff;background:#22344f;border:1px solid #758daa;border-radius:6px}li{margin:14px 0}[hidden]{display:none}summary{cursor:pointer;font-weight:bold}@media(max-width:650px){main{padding:18px 12px}h1{font-size:21px}.card,section{padding:14px}}
    </style></head><body><main>'''+f'<h1>波の中間へ参加する手法：全33セッションの損益</h1><p class="card"><b>既知33場の主基準に両銘柄で合格：{len(passes)}/9新条件。</b> '
        '損益は手数料後。TOPIXの目安は損失・無取引込み平均＋10万円/場。両商品とも金額利益65%以上、赤字20%以下、最大赤字を平均黒字1場で補う。'
        '新9条件と旧基準1条件の計10比較。追加2場は未測定で、表の0円へ混ぜていません。</p>'
        '<p>入口は現在活動→両市場→反対活動を受けた再進行の3段階。参照価格は直前確定5分の高安で、形だけから未来を予測しません。支持線を有利な側だけへ動かし、保有時間を固定せず返済します。</p>'
        '<details class="card"><summary>10条件の一覧（銘柄別）</summary><div class="scroll"><table><thead><tr><th>手法</th><th>商品</th><th>平均収支/場</th><th>金額利益割合</th><th>赤字場</th><th>無取引</th><th>最大赤字</th><th>平均黒字</th><th>主基準</th></tr></thead><tbody>'+''.join(summary)+'</tbody></table></div></details>'
        '<label for="method">全場損益を見る手法：</label><select id="method">'+''.join(options)+'</select>'+''.join(chapters)+
        '<details class="card"><summary>事前主候補の赤字上位3場：当時の判断と返済</summary>'+losses(result,main)+'</details>'
        '<p class="muted">利益割合＝完結親の正損益合計÷（正損益合計＋負損益絶対値合計）。勝率や資金利回りではありません。損失欄は絶対値。最大同方向保有10mini/20micro、全返済は場内。ラージ気配と価格時計による代理検証で、実受信順・mini/microの待ち順位は未測です。</p>'
        f'<p><a href="{ACCOUNT}">公開会計</a>・<a href="README.md">読む順序と検証の意図</a></p>'+'''</main>
    <!--
    [コンポーネント概要]
    #method は表示する手法を選びます。.method は各手法の全33場損益です。
    選択した一章だけ表示し、全手法のデータを文書内に保持します。外部通信はしません。
    -->
    <script>
    /**
     * 手法の全場損益を切り替えます。
     * @param {Event} event - 選択変更イベント。
     * @returns {void} 選んだ章だけを表示します。
     */
    function changeMethod(event){document.querySelectorAll('.method').forEach(section=>{section.hidden=section.id!==event.target.value;});}
    document.querySelector('#method').addEventListener('change',changeMethod);
    </script></body></html>''')


def main() -> None:
    """
    機能: 完成後の目的を記録して結果を一読し、十比較と全場を公開する。
    引数: なし。
    返り値: None。実台帳本文や入力cacheは読まず、新金融も行わない。
    """
    purpose=HERE/'公開の一読目的.json'
    assert not purpose.exists() and not (PUBLIC/TITLE).exists() and not (PUBLIC/ACCOUNT).exists()
    purpose.write_text(json.dumps(dict(目的='完成済み金融の全33場と十比較を公開し、事前候補の赤字具体例を一次診断から載せる。',
        元金融結果=1,入力cache=0,台帳本文=0,新金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    raw=SOURCE.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    owned=HERE/'公開用の同bytes結果.json'
    assert not owned.exists()
    owned.write_bytes(raw)
    result=json.loads(raw.decode('utf-8'))
    assert result['全合格'] and result['counts']==dict(TradeGatecache=33,TradeExitcache=33,現在特徴商品=66,新金融口座=594)
    account=normalized(result)
    account['金融出典']=dict(path=SOURCE.relative_to(ROOT).as_posix(),SHA256=digest)
    (PUBLIC/ACCOUNT).write_text(json.dumps(account,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (PUBLIC/TITLE).write_text(render(account,result),encoding='utf-8')
    check=dict(全合格=True,十条件=True,各条件六十六会計=True,会計件数=660,新金融=0,公開元金融一読=1,入力cache=0,台帳本文=0,API=0,
               金融SHA256=digest,HTML_SHA256=hashlib.sha256((PUBLIC/TITLE).read_bytes()).hexdigest(),公開会計_SHA256=hashlib.sha256((PUBLIC/ACCOUNT).read_bytes()).hexdigest())
    (HERE/'十比較と全三十三場の公開射影.json').write_text(json.dumps(check,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(check,ensure_ascii=False))


if __name__=='__main__':
    main()
