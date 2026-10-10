"""原本全行観測の主・副仮説と全260条件を、完備後だけ短い暗色数表にする。"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
from pathlib import Path
import pickle


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00037_原本全行の板観測と対照比較'
MAIN='原本全行の板観測と対照比較.html'
ALL='全条件損益.html'
COMPARISONS=tuple(f'F{i:02d}' for i in range(20))
SYMBOLS=('TOPIX','NK225')
MONEY_FIELDS=('profit_yen','loss_yen','net_yen')
UNIT_FIELDS=('profit_units','loss_units','net_units','zero_units')
COMPARISON_FIELDS=MONEY_FIELDS+UNIT_FIELDS+('profit_factor','average_payoff','net_r','drawdown_yen','trades','active_sessions')
FLOW_FIELDS=('bands','two_trials','completed_breakout','breakout_comparable','candidates','trades')
DIFFERENCE_FIELDS=('net_yen','net_r','drawdown_yen','candidates','trades')
OBSERVATIONS=(('F01','F00'),('F02','F01'),('F03','F18'),('F04','F03'),('F10','F01'),('F16','F02'))
VERDICTS=('基礎候補','板の比較付加価値','実行感度','窓距離感度')

definition=importlib.util.spec_from_file_location('_v42_旧報告補助',HERE.parent/'wave_v40/report.py')
helpers=importlib.util.module_from_spec(definition)
definition.loader.exec_module(helpers)
read=helpers.read
digest=helpers.digest
periods=helpers.periods
row_html=helpers.row_html
statistics=helpers.statistics
LABELS=dict(helpers.LABELS, candidates='候補', trades='実取引', bands='全帯', two_trials='二試行完了',
    completed_breakout='完了後突破',breakout_comparable='そのうち比率可用',net_units='勝ち−負け 枚')


def description(spec: dict) -> str:
    """機能: 固定された観測版と判定を一文にまとめる。

    引数: spec(dict)。返り値: 短い手法説明(str)。成績で説明を変更しない。
    """
    source={'old':'旧公開端点','strict':'原本全行・旧品質維持','local':'原本全行・P局所品質'}[spec['feature_source']]
    condition={'weaken':'u2<u1かつb2<b1','price_matched':'両比率可用かつb2<b1','price':'b2<b1だけ',
        'all':'二試行後の突破すべて','quantity':'u2<u1だけ','last':'両比率可用かつu2<1・b2<b1',
        'mean':'両比率可用かつ平均u<1・b2<b1','strengthen':'両比率可用かつu2>u1・b2<b1'}[spec['mode']]
    additions=[]
    if spec['peer']:additions.append('60秒待った相手価格も確認')
    if spec['invert']:additions.append('売買方向を反転')
    if spec['seed'] is not None:additions.append(f'固定seed{spec["seed"]}の方向符号')
    if spec['delay']:additions.append(f'注文伝達{spec["delay"]:g}秒')
    if spec['observed']:additions.append('観測価格で返済')
    if spec['role']=='sensitivity':
        additions.append(f'準備{spec["anchor_seconds"]:g}秒・試行{spec["trial_seconds"]:g}秒・離脱{spec["departure"]:g}ATR・突破{spec["break_ticks"]:g}呼値')
    return source+'で'+condition+('、'+'、'.join(additions) if additions else '')+'。'


def table(rows: list[str], fields: tuple, first: str='期間', differences: bool=False) -> str:
    """機能: 暗色で横スクロール可能な数表を組み立てる。

    引数: rows(list[str])、fields(tuple)、first(str)、differences(bool)。返り値: HTML(str)。
    """
    labels=dict(LABELS)
    if differences:labels.update(net_yen='収支差 円',net_r='合計R差',drawdown_yen='最大下落差 円',candidates='候補数差',trades='取引数差')
    head='<th>'+html.escape(first)+'</th>'+''.join('<th>'+labels[field]+'</th>' for field in fields)
    return '<div class="scroll"><table><thead><tr>'+head+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def shell(title: str, body: str, preview: bool) -> str:
    """機能: 共通の暗色画面に暫定表示を付ける。

    引数: title/body(str)、preview(bool)。返り値: 完全HTML(str)。
    """
    return helpers.shell(title,body,preview)


def render_main(payload: dict, preview: bool=False) -> str:
    """機能: 主F01と副F02の採否を分け、20比較を短い主画面にまとめる。

    引数: payload(dict)、preview(bool)。返り値: 主HTML(str)。
    """
    chart='<a href="５分足と売買.html">５分足と売買</a>' if payload.get('chart_ready') else ''
    body=f'<nav><a href="{ALL}">全260条件の損益</a>{chart}</nav><h1>原本全行の板観測と対照比較</h1>'
    body+='<p>同じ帯への二試行を比べ、数量の再増加比率uと価格の押し戻りbが共に弱くなった後の突破へ1枚で入ります。帯・試行・突破時刻は旧版のまま、数量の観測だけを原本全行へ広げました。</p>'
    for identifier,label in (('F01','主案：原本全行・旧品質維持'),('F02','副案：P局所品質')):
        verdict=payload['assessment']['仮説別'][identifier]
        status='事前の経済基準を通過' if verdict['既知経済目安合格'] else '事前の経済基準は未達'
        values=[payload['index'][identifier]['symbols'][symbol] for symbol in SYMBOLS]
        if any(value['trades']<20 for value in values):
            financial='両市場赤字' if all(value['net_yen']<0 for value in values) else (
                '両市場黒字' if all(value['net_yen']>0 for value in values) else '両市場黒字の条件は未達')
            status=financial+'・活動基準未達'
        body+=f'<div class="box"><strong>{identifier} {label}：{status}</strong><div class="status">'
        for key,title in zip(VERDICTS,('基礎成績','数量情報の追加価値','執行感度','窓・距離感度')):
            passed=verdict[key]
            body+=f'<span class="{"yes" if passed else "no"}" data-verdict="{identifier}:{key}" data-value="{str(passed).lower()}">{title}：{"通過" if passed else "未達"}</span>'
        body+='</div></div>'
    body+='<p class="muted">全13セッションは既知データで、学習除外はありません。TOPIXミニ／NK225マイクロ各1枚、費用0。副案・相手確認・良かった近傍で主案を差し替えません。</p>'
    comparison=[]
    for identifier in COMPARISONS:
        for symbol in SYMBOLS:
            value=helpers.add_units(payload['index'][identifier]['symbols'][symbol])
            comparison.append(row_html(identifier,symbol,'全13セッション',value,COMPARISON_FIELDS,'comparison',identifier+' '+symbol))
    body+='<h2>固定した20方式の損益</h2>'+table(comparison,COMPARISON_FIELDS,'方式・銘柄')
    body+='<p class="table-note">損失は正の額。枚数差は勝ち枚数−負け枚数。1回の返済は1枚です。PF＝総利益÷総損失、平均比＝平均勝ち額÷平均負け額。未定義は不合格。最大下落は含みを含む口座曲線、Rは各取引の初期予定損失です。</p>'
    body+='<details><summary>20方式の短い説明</summary>'
    for identifier in COMPARISONS:
        spec=payload['index'][identifier]['spec']
        body+=f'<p><strong>{identifier} {html.escape(spec["name"])}</strong><br>{html.escape(description(spec))}</p>'
    body+='</details><details><summary>旧観測・品質・相手確認を分けた差</summary>'
    rows=[]
    for identifier,parent in OBSERVATIONS:
        for symbol in SYMBOLS:
            a,b=payload['index'][identifier]['symbols'][symbol],payload['index'][parent]['symbols'][symbol]
            value={field:a[field]-b[field] for field in DIFFERENCE_FIELDS}
            rows.append(row_html(identifier,symbol,parent,value,DIFFERENCE_FIELDS,'difference',f'{identifier} − {parent} / {symbol}'))
    body+=table(rows,DIFFERENCE_FIELDS,'方式差・銘柄',True)
    body+='<p>F01−F00が原本全行化、F02−F01が品質変更、F03−F18が観測可能な機会の差、F04−F03が品質による機会差です。F10/F16は相手確認の追加。これらの差と、固定5対照＋同候補乱数中央値を上回る「数量情報の追加価値」は別の判定です。</p></details>'
    rows=[]
    for identifier in ('F00','F01','F02'):
        for symbol in SYMBOLS:
            rows.append(row_html(identifier,symbol,'全13セッション',payload['flow'][identifier][symbol],FLOW_FIELDS,'flow',identifier+' '+symbol))
    body+='<details><summary>観測から取引までの件数</summary>'+table(rows,FLOW_FIELDS,'方式・銘柄')
    body+='<p>「比率可用」は二試行完了後に突破した帯のうち、u1/u2が両方測れる件数。帯や候補が増えても、収益の改善とは限りません。可視外・数量不正・減少0・未完試行は不明のまま残します。</p></details>'
    body+='<details><summary>共通の売買と採否</summary><p>新規は判断の次原本行以降。判断時に公開済みのATRと2呼値の大きい方を呼値へ切り上げてrを固定し、1r損切り・2r利確。子注文も次行から有効です。30分後または場末に市場返済を予約し、返済後5分休止。セッション内で全返済します。</p><p>両市場で20決済・6活動場・買売各3、黒字、PFと平均比1.2以上、最大勝ち取引と最大黒字場を各々除いて非赤字が基礎です。追加価値はF01がF03/F06/F07/F08/F09、F02がF04/F12/F13/F14/F15と同候補64乱数中央値を合計Rで厳密に上回ること。4執行条件と8近傍は旧版の基準を維持します。</p><p>F08/F14は数量比率が増える側を選び、売買は突破方向。F09/F15は同じ候補の売買方向だけを反転します。再増加比率は保存された可視数量の変化であり、真の補充・約定量・参加者を識別しません。未来相場での利益保証ではありません。</p></details>'
    body+='<details><summary>監査・再現資料</summary><ul>'
    for title,name in (('全固定条件','探索条件の固定.json'),('仮説別の判定','assess_results.json'),
        ('完備確認','完備監査.json'),('入口の全検査','check_entry_signals.json'),
        ('原本観測の因果検査','trial_observation_audit.json'),('全数表の独立監査','report_audit.json')):
        body+=f'<li><a href="../../work/wave_v42/{name}">{title}</a></li>'
    body+='</ul></details>'
    return shell('原本全行の板観測と対照比較',body,preview)


def render_all(payload: dict, preview: bool=False) -> str:
    """機能: 260手法それぞれの全期間・2週・13場の金額と枚数を表示する。

    引数: payload(dict)、preview(bool)。返り値: 全損益HTML(str)。
    """
    body=f'<nav><a href="{MAIN}">短い比較へ戻る</a></nav><h1>全260条件の損益</h1><p>TOPIXミニ／NK225マイクロ各1枚。全13セッションは既知、費用0。週はセッション開始日で分けます。</p><label for="method">手法 </label><select id="method">'
    for spec in payload['specs']:
        body+=f'<option value="{spec["id"]}">{html.escape(spec["id"]+" "+spec["name"])}</option>'
    body+='</select>'
    fields=MONEY_FIELDS+UNIT_FIELDS
    for i,spec in enumerate(payload['specs']):
        identifier=spec['id']
        body+=f'<section class="method" id="method-{identifier}" data-method="{identifier}"'+(' hidden' if i else '')+'>'
        body+=f'<h2>{html.escape(identifier+" "+spec["name"])}</h2><p>{html.escape(description(spec))}</p>'
        for symbol in SYMBOLS:
            values=periods([row for row in payload['sessions'][identifier] if row['symbol']==symbol])
            body+=f'<h3>{symbol}</h3>'+table([row_html(identifier,symbol,p,v,fields,'profit') for p,v in values[:3]],fields)
            body+='<details><summary>各13セッション</summary>'+table([row_html(identifier,symbol,p,v,fields,'profit') for p,v in values[3:]],fields)+'</details>'
        body+='</section>'
    body+='''<!--
機能: 固定260条件のうち選択した表だけを表示する。
引数: select.value(str)。返り値: なし。順位や数値の再計算は行わない。
--><script>
const select=document.getElementById('method');
/**
 * 機能: 手法IDに対応する表を表示する。
 * 引数: なし。返り値: なし。
 */
function showMethod(){document.querySelectorAll('[data-method]').forEach(section=>{section.hidden=section.dataset.method!==select.value;});}
select.addEventListener('change',showMethod);showMethod();
</script>'''
    return shell('全260条件の損益',body,preview)


def verify_guard() -> dict:
    """機能: 結果読取前に完備成功と参照資料の現在指紋を要求する。

    引数: なし。返り値: 完備記録(dict)。暫定表示でも結果読取制約を緩めない。
    """
    proof=read(HERE/'完備監査.json')
    assert proof['検証完了'] is True and proof['全条件数']==260
    for relative,value in proof['参照資料SHA256'].items():assert digest(ROOT/relative)==value,relative
    return proof


def load_payload() -> tuple[dict,dict]:
    """機能: 完備後の固定全条件だけから表示値と指紋を作る。

    引数: なし。返り値: 表示値と参照資料(tuple[dict,dict])。
    """
    verify_guard();refs={}
    def source(path: Path) -> object:
        """機能: 読取資料を内容指紋へ結ぶ。

        引数: path(Path)。返り値: JSON内容(object)。
        """
        refs[path.relative_to(ROOT).as_posix()]=digest(path)
        return read(path)
    fixed=source(HERE/'探索条件の固定.json');complete=source(HERE/'主再生の完了.json')
    assert (complete['全条件数'],complete['全入力数'])==(260,6760) and complete['全独立会計合格']
    assert complete['固定SHA256']==digest(HERE/'探索条件の固定.json')
    index=source(HERE/'全条件の期間集計.json.gz');verdict=source(HERE/'assess_results.json')
    specs=fixed['主条件']+fixed['補助条件'];assert len(specs)==len(index)==260
    assert {spec['id'] for spec in specs}==set(index)
    sessions={}
    for spec in specs:
        identifier=spec['id'];assert index[identifier]['spec']==spec
        rows=source(HERE/'sessions'/(identifier+'.json.gz'))
        assert len(rows)==26 and len({(r['session'],r['symbol']) for r in rows})==26
        sessions[identifier]=rows
    cache_path=HERE.parent/'wave_v40/band_cache.pkl';panel_path=HERE/'trial_panel.pkl'
    cache=pickle.loads(cache_path.read_bytes());panels=pickle.loads(panel_path.read_bytes())
    for path in (cache_path,panel_path,HERE/'完備監査.json',HERE.parent/'wave_v40/report.py',HERE.parent/'wave_v39/trade_statistics.py'):
        refs[path.relative_to(ROOT).as_posix()]=digest(path)
    flow={}
    for identifier in ('F00','F01','F02'):
        flow[identifier]={symbol:{field:0 for field in FLOW_FIELDS} for symbol in SYMBOLS}
        for ledger in source(HERE/'ledgers'/(identifier+'.json.gz')):
            key=(ledger['session'],ledger['symbol']);info=ledger['入口根拠'];canonical=info['母集団キー']
            bands=cache[canonical][key];panel={r['band_id']:r for r in panels[canonical][key]}
            target=flow[identifier][key[1]]
            for band in bands:
                f=band['features'] if identifier=='F00' else panel[band['band_id']]['features_'+('strict' if identifier=='F01' else 'local')]
                target['bands']+=1;target['two_trials']+=int(f['two_trials_complete'])
                target['completed_breakout']+=int(band['status']=='breakout')
                target['breakout_comparable']+=int(band['status']=='breakout' and f['quantity_comparable'])
            target['candidates']+=len(info['候補']);target['trades']+=len(ledger['trades'])
        for symbol in SYMBOLS:
            sequence=[flow[identifier][symbol][field] for field in FLOW_FIELDS]
            assert sequence==sorted(sequence,reverse=True)
            assert flow[identifier][symbol]['trades']==index[identifier]['symbols'][symbol]['trades']
    return dict(specs=specs,index=index,sessions=sessions,assessment=verdict,flow=flow,
        chart_ready=(OUT/'５分足と売買.html').is_file()),refs


def main() -> None:
    """機能: 完備確認後だけ2ページを生成し、すべての表示元と出力を保存する。

    引数: --preview(bool)。返り値: なし(None)。売買・条件・採否は変更しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    payload,refs=load_payload();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/MAIN).write_text(render_main(payload,args.preview),encoding='utf-8')
    (OUT/ALL).write_text(render_all(payload,args.preview),encoding='utf-8')
    for relative,value in refs.items():assert digest(ROOT/relative)==value,relative
    manifest=dict(暫定版=args.preview,固定比較=list(COMPARISONS),全条件数=260,損益行数=8320,
        比較行数=40,差分行数=12,段階行数=6,参照資料SHA256=refs,生成実装SHA256=digest(Path(__file__)),
        出力SHA256={path.relative_to(ROOT).as_posix():digest(path) for path in (OUT/MAIN,OUT/ALL)})
    (HERE/'report_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(暫定版=args.preview,損益行数=8320,比較行数=40,出力=str(OUT)),ensure_ascii=False))


if __name__=='__main__':main()
