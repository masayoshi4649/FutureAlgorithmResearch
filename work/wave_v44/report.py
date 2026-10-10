"""減量の開始許可を、完備後だけ短い暗色数表へまとめる。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import html
import importlib.util
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00039_減量開始時点と利益保護'
MAIN='減量開始時点と利益保護.html'
ALL='全条件の損益.html'
SYMBOLS=('TOPIX','NK225')
PRIMARY='G150_F25_N1__V000'
CONTROL='G000_F25_N1__V000'
BASELINE='A0__V000'
EXPLORATORY='G150_F50_N1__V000'
CORE=(BASELINE,CONTROL,PRIMARY)
CLOCKS=tuple(prefix+'__'+variant for prefix in ('A0','G000_F25_N1','G150_F25_N1') for variant in ('E080','V000','E120'))
MONEY_FIELDS=('profit_yen','loss_yen','net_yen')
UNIT_FIELDS=('profit_units','loss_units','net_units','zero_units')
FINANCIAL=MONEY_FIELDS+UNIT_FIELDS
COMPARISON=('profit_yen','loss_yen','net_yen','profit_units','loss_units','unit_payoff','profit_factor','average_payoff','drawdown_yen','cycles')
ROBUSTNESS=('net_yen','drawdown_yen','removed_one','removed_session','removed_two','cycles','active_sessions','waves')
DIFFERENCE=('net_yen','drawdown_yen')
VERDICTS=('中央の基礎候補','中央の収益追加改善','全期間両銘柄で減量復元実約定','指定八波','十二感度の後七基礎','入口三時計の集中活動耐性','悪化情報の利益付加価値支持','回復情報の構造保存対照超過')
DECIMALS={'profit_factor':2,'average_payoff':2,'unit_payoff':2}
LABELS=dict(profit_yen='利益 円',loss_yen='損失 円',net_yen='収支 円',profit_units='勝ち 枚',
    loss_units='負け 枚',net_units='勝ち−負け 枚',zero_units='同値 枚',profit_factor='元組PF',
    average_payoff='平均元組勝敗比',unit_payoff='1枚平均勝敗比',drawdown_yen='最大下落 円',
    cycles='元組数',active_sessions='活動 場',removed_one='最大1勝除外 円',
    removed_session='最大黒字場除外 円',removed_two='上位2勝除外 円',waves='指定波 /8')
definition=importlib.util.spec_from_file_location('_v44_旧表示補助',HERE.parent/'wave_v40/report.py')
helpers=importlib.util.module_from_spec(definition);definition.loader.exec_module(helpers)
read,digest=helpers.read,helpers.digest


def number(value: float|int|None, field: str) -> str:
    """機能: 未定義を無限大に変えず、金額と比率の表示桁を統一する。

    引数: value(float|int|None)、field(str)。返り値: 表示文字(str)。
    """
    return '未定義' if value is None else f'{value:,.{DECIMALS.get(field,0)}f}'


def row_html(identifier: str, symbol: str, period: str, value: dict, fields: tuple,
             kind: str, label: str|None=None) -> str:
    """機能: 全セルを条件・銘柄・期間と可視数値へ対応させる。

    引数: identifier/symbol/period/kind(str)、value(dict)、fields(tuple)、label(str|None)。返り値: 行HTML(str)。
    """
    text=label if label is not None else period
    row=f'<tr data-kind="{kind}" data-id="{identifier}" data-symbol="{symbol}" data-period="{period}"><td>{html.escape(text)}</td>'
    for field in fields:
        v=value[field];encoded=html.escape(json.dumps(v,allow_nan=False),quote=True)
        sign=' positive' if field in ('net_yen','net_units') and v is not None and v>0 else ' negative' if field in ('net_yen','net_units') and v is not None and v<0 else ''
        row+=f'<td class="num{sign}" data-field="{field}" data-value="{encoded}">{number(v,field)}</td>'
    return row+'</tr>'


def table(rows: list[str], fields: tuple, first: str='期間', difference: bool=False) -> str:
    """機能: 横スクロール可能な暗色数表を構成する。

    引数: rows(list[str])、fields(tuple)、first(str)、difference(bool)。返り値: HTML(str)。
    """
    labels=dict(LABELS)
    if difference:labels.update(net_yen='収支差 円',drawdown_yen='最大下落差 円')
    return '<div class="scroll"><table><thead><tr><th>'+html.escape(first)+'</th>'+''.join('<th>'+labels[f]+'</th>' for f in fields)+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def week(session: str) -> str:
    """機能: ナイトも開始日の月曜日へ分類する。

    引数: session(str)。返り値: 週開始日(str)。
    """
    d=date.fromisoformat(session[:10]);return (d-timedelta(days=d.weekday())).isoformat()


def aggregate(rows: list[dict]) -> dict:
    """機能: 保存会計の全返済金額・枚数と元組を表示用に集約する。

    引数: rows(list[dict])。返り値: 表示指標(dict)。場内極値は監査済みの保存値を使う。
    """
    assert rows and len({r['symbol'] for r in rows})==1
    output={f:sum(r[s] for r in rows) for f,s in (
        ('profit_yen','gross_profit_yen'),('loss_yen','gross_loss_yen'),('net_yen','net_yen'),
        ('profit_units','profit_units'),('loss_units','loss_units'),('zero_units','zero_units'),('cycles','cycles'))}
    output['net_units']=output['profit_units']-output['loss_units']
    gain=sum(r['cycle_profit_yen'] for r in rows);loss=sum(r['cycle_loss_yen'] for r in rows)
    wins=sum(r['cycle_wins'] for r in rows);losses=sum(r['cycle_losses'] for r in rows)
    output['profit_factor']=gain/loss if loss else None
    output['average_payoff']=(gain/wins)/(loss/losses) if wins and losses and loss else None
    output['unit_payoff']=(output['profit_yen']/output['profit_units'])/(output['loss_yen']/output['loss_units']) if output['profit_units'] and output['loss_units'] and output['loss_yen'] else None
    offset=peak=drawdown=0.
    for row in sorted(rows,key=lambda x:x['session']):
        drawdown=max(drawdown,row['drawdown_yen'],peak-offset-row['min_equity_yen'])
        peak=max(peak,offset+row['max_equity_yen']);offset+=row['net_yen']
    output.update(drawdown_yen=drawdown,active_sessions=sum(r['cycles']>0 for r in rows))
    return output


def periods(rows: list[dict]) -> list[tuple[str,dict]]:
    """機能: 全13・開始週2つ・各13場を固定順に返す。

    引数: rows(list[dict])。返り値: 表示期間と集計(list[tuple])。
    """
    assert len(rows)==13
    result=[('全13セッション',aggregate(rows))]
    for start in ('2026-09-21','2026-09-28'):
        result.append((start+'週',aggregate([r for r in rows if week(r['session'])==start])))
    result.extend((r['session'],aggregate([r])) for r in sorted(rows,key=lambda x:x['session']))
    assert len(result)==16;return result


def directory(spec: dict) -> Path:
    """機能: 結果の役割によって事前固定された保存先を返す。

    引数: spec(dict)。返り値: 主又は補助の作業パス(Path)。
    """
    return HERE/'supplementary' if spec['role']=='supplementary' else HERE


def description(spec: dict) -> str:
    """機能: 結果を参照せず、今回変更した許可と固定した数量規則を短く説明する。

    引数: spec(dict)。返り値: 説明(str)。
    """
    text=f"H019の入口窓{spec['entry_scale']:g}倍。"
    if spec['policy']['kind']=='baseline':
        text+='元A0の価格注文と実組損失予算で返済。数量調整なし。'
    else:
        threshold=spec['gate_threshold_atr'];fraction=spec['policy']['reduce_fraction']*100
        maximum=spec['policy']['max_reductions']
        text+=('順行の開始制限なし。' if threshold==0 else f'影A0が初回ATRの{threshold:g}倍順行した後の新公開だけ減量に使用。')
        text+=f'生存枠の約{fraction:g}%を最大{maximum}回減量し、新しい同方向根拠で復元。'
        if spec['gate_mode']=='inverse':text+='悪化方向だけ逆判定。'
        if spec['gate_mode']=='any_valid':text+='方向判定を除き、新しい有効公開なら減量候補。'
        if spec['bad_scale']!=1:text+=f"悪化窓{spec['bad_scale']:g}倍。"
        if spec['good_scale']!=1:text+=f"回復窓{spec['good_scale']:g}倍。"
        for field,label in (('bad_seed','悪化'),('good_seed','回復')):
            if spec[field] is not None:text+=f'{label}方向を公開元ごとの固定乱数seed{spec[field]}で反転。'
    if spec['min_delay_seconds']:text+=f"注文伝達は最低{spec['min_delay_seconds']:g}秒。"
    if spec['observed_fill']:text+='条件成立後の観測価格で全約定。'
    return text


def robust_value(payload: dict, identifier: str, symbol: str, period: str) -> dict:
    """機能: 元組集中診断を採否の期間定義どおり表示へ写す。

    引数: payload(dict)、identifier/symbol/period(str)。返り値: 表示値(dict)。
    """
    c=payload['assessment']['全条件'][identifier]['期間別'][period][symbol]
    return dict(net_yen=c['収支円'],drawdown_yen=c['時価最大下落円'],removed_one=c['最大勝ち元組除外収支円'],
        removed_session=c['最大黒字場除外収支円'],removed_two=c['上位二勝ち元組同時除外収支円'],
        cycles=c['元組数'],active_sessions=c['稼働セッション数'],waves=payload['index'][identifier]['wave_passes'])


def render_main(payload: dict, preview: bool=False) -> str:
    """機能: 固定主案・従来C01・元A0の六行を先頭へ置き、改善と黒字を分離する。

    引数: payload(dict)、preview(bool)。返り値: 主HTML(str)。
    """
    decision=payload['assessment']
    chart='<a href="５分足と売買.html">５分足と売買</a>' if payload.get('chart_ready') else ''
    body=f'<nav><a href="{ALL}">全163条件の損益</a>{chart}</nav><h1>減量開始時点と利益保護</h1>'
    totals=[aggregate([r for r in payload['sessions'][PRIMARY] if r['symbol']==s]) for s in SYMBOLS]
    count=sum(v['net_yen']>0 for v in totals)
    status='主案の全13セッションは両市場黒字。' if count==2 else '主案の全13セッションは一方の市場だけ黒字。' if count==1 else '主案の全13セッションは両市場とも黒字に届かず。'
    status+='従来C01からの収益改善基準は'+('通過。' if decision['中央の収益追加改善'] else '未達。')
    body+='<div class="box"><strong>'+status+'</strong><p>既知比較の経済研究候補：'+('該当' if decision['既知比較の研究候補'] else '非該当')+'。感度・悪化／回復情報の価値は別判定です。</p></div>'
    relation=decision['中央比較'][CONTROL]['収益DD関係']['差']
    full=[r for r in relation if r['期間']=='all_symbols']
    later=[r for r in relation if r['期間']=='symbols']
    if all(r['収支差円']>0 for r in full) and any(r['収支差円']<0 for r in later) and all(r['最大下落差円']>0 for r in full):
        markets='・'.join(r['銘柄'] for r in later if r['収支差円']<0)
        body+='<p><strong>全13ではC01より増益。ただし後7の'+markets+'は減益で、両銘柄の最大下落も拡大しました。安定性の明確な優位は示せていません。</strong></p>'
    body+='<p>主案は、元A0の影建玉が初回ATRの1.5倍順行するまで減量を待ち、その後の新しい悪化根拠で約25%を1回縮小します。入口と元の返済注文は変えません。</p>'
    body+='<p class="muted">全13セッションと後7はすべて既知。TOPIXミニ初回5枚／NK225マイクロ初回10枚、片方向上限10／20枚。費用0・場内全返済。銘柄間の金額順位では比較しません。</p>'
    body+=f'<p><strong>次の反証候補（探索後の参考）：50%減量版。</strong>全13・後7の両市場でC01より増益でした。主案への差替えはせず、この50%版の時計・方向乱数対照は未実施です。採用・安定性の確定とは呼びません。<a href="{ALL}?method={EXPLORATORY}">{EXPLORATORY}の各場損益</a></p>'
    first=[];remaining=[]
    order=[next(s for s in payload['specs'] if s['id']==name) for name in CORE]
    order.extend(s for s in payload['specs'] if s['role']!='supplementary' and s['id'] not in CORE)
    labels={BASELINE:'A0：数量調整なし',CONTROL:'C01：開始制限なし',PRIMARY:'主案：1.5ATR後に許可'}
    for spec in order:
        identifier=spec['id']
        for symbol in SYMBOLS:
            value=aggregate([r for r in payload['sessions'][identifier] if r['symbol']==symbol])
            row=row_html(identifier,symbol,'全13セッション',value,COMPARISON,'comparison',labels.get(identifier,identifier)+' / '+symbol)
            (first if identifier in CORE else remaining).append(row)
    body+=table(first,COMPARISON,'方式・銘柄')
    body+='<p class="table-note">利益・損失と勝負枚数は全返済脚。1枚平均比は利益÷勝ち枚数と損失÷負け枚数の比。元組PF・平均比は減量と復元を一つの元組へ合算。最大下落は含み込み。未定義は合格にしません。</p>'
    exploration=[]
    for period,names in (('all_symbols',payload['names']),('symbols',payload['names'][6:])):
        for symbol in SYMBOLS:
            values=aggregate([r for r in payload['sessions'][EXPLORATORY] if r['symbol']==symbol and r['session'] in names])
            exploration.append(row_html(EXPLORATORY,symbol,period,values,COMPARISON,'exploratory',('全13' if period=='all_symbols' else '後7')+' / '+symbol))
    body+='<details><summary>次の反証候補：50%減量版の4期間・銘柄セル</summary>'+table(exploration,COMPARISON,'探索後の参考')+'<p>固定主案G150_F25_N1の感度・乱数結果を、この50%版へ転用しません。</p></details>'
    body+='<details><summary>主案の判定・同じ入口での改善幅</summary><div class="status">'
    labels=('黒字と集中の基礎','C01からの収益改善','減量・復元の実作動','指定8波','12感度の後7基礎','入口3時計の耐性','悪化情報の対照超過','回復情報の対照超過')
    for key,label in zip(VERDICTS,labels):
        value=decision[key]
        body+=f'<span class="{"yes" if value else "no"}" data-verdict="{key}" data-value="{str(value).lower()}">{label}：{"通過" if value else "未達"}</span>'
    body+='</div><p>経済研究候補は基礎・C01比収益改善・実作動を要求。改善は後7の両銘柄で増益、全13の両銘柄で非減益です。耐性付き・情報対照通過は追加の別ラベルです。</p>'
    differences=[]
    for reference,label in ((CONTROL,'主案−C01'),(BASELINE,'主案−A0')):
        for row in decision['中央比較'][reference]['収益DD関係']['差']:
            period=row['期間'];symbol=row['銘柄']
            values=dict(net_yen=row['収支差円'],drawdown_yen=row['最大下落差円'])
            differences.append(row_html(PRIMARY,symbol,period+'/'+reference,values,DIFFERENCE,'difference',label+' / '+('全13' if period=='all_symbols' else '後7')+' / '+symbol))
    body+=table(differences,DIFFERENCE,'同銘柄内の差',True)+'<p>最大下落差はマイナスが改善。主案・C01・A0の同じ入口では全ての影元組を比較し、未到達・未調整・損失組も除きません。</p></details>'
    body+='<details><summary>35主比較・感度の全期間値</summary>'+table(remaining,COMPARISON,'方式・銘柄')+'</details>'
    robust=[]
    for identifier in CLOCKS:
        for period in ('all_symbols','symbols'):
            for symbol in SYMBOLS:
                robust.append(row_html(identifier,symbol,period,robust_value(payload,identifier,symbol,period),ROBUSTNESS,'robustness',identifier+' / '+('全13' if period=='all_symbols' else '後7')+' / '+symbol))
    body+='<details><summary>入口時計と大勝ち除外</summary>'+table(robust,ROBUSTNESS,'方式・期間・銘柄')+'<p>最大1勝ち元組と最大黒字場の除外は別々。上位2勝の同時除外は補足です。指定波は全期間共通の8波で、後7の専用波ではありません。</p></details>'
    body+='<details><summary>機械的な入口・減量・復元・返済</summary><p>全てH019入口。元注文は準備時公開ATRをA0に固定し、0.25A0の追跡入口、初期組予算1A0、1.5A0順行から3A0幅追跡、2A0で当初枚数の約半分を利確、360分又は場末返済、全返済後5分休止です。</p><p>B00は2分と直近30秒の気配価格が保有と逆へ進む状態で、板数量は使いません。主案の許可距離は影建玉の価格順行÷初回ATRで、利益額Rではありません。同じ影組の初回到達を記録し、その行より後に公開されたB00だけを減量判断へ使います。同じ公開根拠を当行へ付け替えません。</p><p>減量数は現生存枠の割合切捨て、最低1枚・最低1枚を残す範囲。減量後の新しい同方向根拠で復元します。元の部分利確で退役した枠は復活させず、初期R・期限・元返済線もリセットしません。実組開始後の実現＋含み損益が −R 以下なら全返済を予約します。次行価格や伝達待ちで超過し得るため損失上限保証ではありません。</p></details>'
    body+='<details><summary>対照の意味と監査資料</summary><p>主35比較と悪化64・回復64の符号対照を全て表示。逆判定は悪化方向だけを反転し、方向除去は到達後の新しい有効公開なら減量候補とします。乱数は元の公開機会と順行ゲートを保つため、方式全体の無情報対照ではありません。最良seed・最良閾値へ主案を差し替えません。</p><p>ゲート自体の独立した予測価値は未判定です。今回の既知比較は、未知相場や全相場で利益を保証するものではありません。</p><ul>'
    sources=[('判定の全内訳','assess_results.json'),('事前固定条件','探索条件の固定.json'),('完備監査','完備監査.json'),('事前の反証計画','反証計画.md'),('入力ゲートの因果監査','gate_input_audit.json'),('注文接続の人工検査','check_runner.json'),('全数表の独立検算','report_audit.json')]
    if payload.get('posthoc'):
        sources.append(('減量時点別の全組差（事後の経路分類）','減量時点別の全組差.json'))
    for title,name in sources:body+=f'<li><a href="../../work/wave_v44/{name}">{title}</a></li>'
    body+='</ul></details>'
    return helpers.shell('減量開始時点と利益保護',body,preview)


def render_all(payload: dict, preview: bool=False) -> str:
    """機能: 全163固定条件の各銘柄・全13・2週・各13場を選択表示する。

    引数: payload(dict)、preview(bool)。返り値: 全条件HTML(str)。
    """
    body=f'<nav><a href="{MAIN}">短い比較へ戻る</a></nav><h1>全163条件の損益</h1><p>主35条件＋符号対照128条件。TOPIXミニ／NK225マイクロ、初回5／10枚。全期間は既知、費用0。週はナイトも開始日で分類します。</p><label for="method">手法 </label><select id="method">'
    for spec in payload['specs']:body+=f'<option value="{spec["id"]}">{html.escape(spec["id"])}</option>'
    body+='</select>'
    for i,spec in enumerate(payload['specs']):
        identifier=spec['id'];body+=f'<section class="method" id="method-{identifier}" data-method="{identifier}"'+(' hidden' if i else '')+'>'
        body+=f'<h2>{html.escape(identifier)}</h2><p>{html.escape(description(spec))}</p>'
        for symbol in SYMBOLS:
            values=periods([r for r in payload['sessions'][identifier] if r['symbol']==symbol])
            body+='<h3>'+symbol+'</h3>'+table([row_html(identifier,symbol,p,v,FINANCIAL,'profit') for p,v in values[:3]],FINANCIAL)
            body+='<details><summary>各13セッション</summary>'+table([row_html(identifier,symbol,p,v,FINANCIAL,'profit') for p,v in values[3:]],FINANCIAL)+'</details>'
        body+='</section>'
    body+='''<!--
機能: 選択された固定条件の表だけを表示する。
引数: select.value(str)。返り値: なし。数値再計算・順位選抜は行わない。
--><script>
const select=document.getElementById('method');
const requested=new URLSearchParams(location.search).get('method');
if(Array.from(select.options).some(option=>option.value===requested))select.value=requested;
/**
 * 機能: 選択した条件へ表示を切り替える。
 * 引数: なし。返り値: なし。
 */
function showMethod(){document.querySelectorAll('[data-method]').forEach(s=>{s.hidden=s.dataset.method!==select.value;});}
select.addEventListener('change',showMethod);showMethod();
</script>'''
    return helpers.shell('全163条件の損益',body,preview)


def verify_guard() -> dict:
    """機能: 完備後だけ結果を読み、全固定と主・補助の保存成果を照合する。

    引数: なし。返り値: 完備記録(dict)。暫定表示でも未完備は拒否する。
    """
    proof=read(HERE/'完備監査.json')
    assert proof['全合格'] is True and proof['全原本場内返済'] is True
    assert tuple(proof[k] for k in ('主条件数','補助条件数','全条件数','全入力数','因果入力数','旧単一窓一致入力数','全指定波数','必須出力数'))==(35,128,163,4238,652,156,1304,1141)
    assert proof['探索固定SHA256']==digest(HERE/'探索条件の固定.json')
    for field in ('参照資料SHA256','出力SHA256'):
        for relative,sha in proof[field].items():assert digest(ROOT/relative)==sha,relative
    return proof


def load_payload() -> tuple[dict,dict]:
    """機能: 完備後に主35＋補助128を、固定順序のまま表示へ接続する。

    引数: なし。返り値: 表示値・参照指紋(tuple[dict,dict])。
    """
    verify_guard();refs={}
    def source(path: Path) -> object:
        """機能: 読み込む資料を指紋へ結ぶ。

        引数: path(Path)。返り値: JSON内容(object)。
        """
        refs[path.relative_to(ROOT).as_posix()]=digest(path);return read(path)
    fixed=source(HERE/'探索条件の固定.json');assessment=source(HERE/'assess_results.json')
    specs=fixed['conditions']+fixed['supplementary'];assert len(specs)==len({s['id'] for s in specs})==163
    assert assessment['監査完了'] is True and set(assessment['全条件'])=={s['id'] for s in specs}
    assert assessment['主案ID']==PRIMARY and assessment['元C01ID']==CONTROL and assessment['元A0ID']==BASELINE
    index={};sessions={}
    for spec in specs:
        identifier=spec['id'];base=directory(spec)
        index[identifier]=source(base/'summaries'/(identifier+'.json'))
        sessions[identifier]=source(base/'sessions'/(identifier+'.json.gz'))
        assert index[identifier]['spec']==spec and len(sessions[identifier])==26
    for path in (HERE/'完備監査.json',HERE/'complete.py',HERE.parent/'wave_v40/report.py'):
        refs[path.relative_to(ROOT).as_posix()]=digest(path)
    posthoc=False
    if (HERE/'減量時点別の全組差.json').is_file():
        diagnostic=source(HERE/'減量時点別の全組差.json')
        assert diagnostic['全合格'] is True and diagnostic['追加採否'] is False
        assert diagnostic['完備監査SHA256']==digest(HERE/'完備監査.json')
        posthoc=True
    return dict(specs=specs,index=index,sessions=sessions,assessment=assessment,names=fixed['全セッション'],
        posthoc=posthoc,chart_ready=(OUT/'５分足と売買.html').is_file()),refs


def main() -> None:
    """機能: 全条件の完備後だけ二つの暗色HTMLと内容指紋を保存する。

    引数: --preview(bool)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    payload,refs=load_payload();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/MAIN).write_text(render_main(payload,args.preview),encoding='utf-8')
    (OUT/ALL).write_text(render_all(payload,args.preview),encoding='utf-8')
    for relative,sha in refs.items():assert digest(ROOT/relative)==sha,relative
    value=dict(暫定版=args.preview,全条件数=163,損益行数=5216,比較行数=70,差分行数=8,集中診断行数=36,探索参考行数=4,
        参照資料SHA256=refs,生成実装SHA256=digest(Path(__file__)),
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in (OUT/MAIN,OUT/ALL)})
    (HERE/'report_manifest.json').write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print('全163条件の比較と5,216行の損益表を生成。',flush=True)


if __name__=='__main__':main()


