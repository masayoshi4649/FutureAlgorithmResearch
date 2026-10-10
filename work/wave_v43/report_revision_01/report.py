"""同じ二出口の時間窓合議を、完備後だけ短い暗色数表へまとめる。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import html
import importlib.util
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00038_時間窓合議と入口の安定性'
MAIN='時間窓合議と入口の安定性.html'
ALL='全条件の損益.html'
SYMBOLS=('TOPIX','NK225')
MANAGERS=('A0','B00_RB00_F25_N1')
ORDER=('S100','M2_100','V2_100','U3_100','S080','S120','M2_080','M2_120','V2_080','V2_120','U3_080','U3_120')
MONEY_FIELDS=('profit_yen','loss_yen','net_yen')
UNIT_FIELDS=('profit_units','loss_units','net_units','zero_units')
FINANCIAL=MONEY_FIELDS+UNIT_FIELDS
COMPARISON=FINANCIAL+('profit_factor','average_payoff','unit_payoff','drawdown_yen','cycles','active_sessions')
ROBUSTNESS=('net_yen','drawdown_yen','removed_one','removed_session','removed_two','cycles','active_sessions','waves')
DIFFERENCE=('net_yen','drawdown_yen')
VERDICTS=('中央の基礎候補','中央の収益追加改善','三中心耐性','四執行基礎','指定八波')
DECIMALS={'profit_factor':2,'average_payoff':2,'unit_payoff':2}
LABELS=dict(profit_yen='利益 円',loss_yen='損失 円',net_yen='収支 円',profit_units='勝ち 枚',
    loss_units='負け 枚',net_units='勝ち−負け 枚',zero_units='同値 枚',profit_factor='元組PF',
    average_payoff='平均元組勝敗比',unit_payoff='1枚平均勝敗比',drawdown_yen='最大下落 円',
    cycles='元組数',active_sessions='活動 場',removed_one='最大1勝除外 円',
    removed_session='最大黒字場除外 円',removed_two='上位2勝除外 円',waves='指定波 /8')
definition=importlib.util.spec_from_file_location('_v43_旧表示補助',HERE.parent/'wave_v40/report.py')
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


def description(spec: dict) -> str:
    """機能: 固定した入口と出口を結果に依存しない一文で説明する。

    引数: spec(dict)。返り値: 短い説明(str)。
    """
    window=spec['window_id'];center=int(window[-3:])/100
    if window.startswith('S'):text=f'単一窓{center:g}倍のH019入口。'
    else:
        kind=window.split('_')[0]
        text=f'中心{center:g}倍の3窓で'+{'M2':'同方向2票以上','V2':'同方向2票以上かつ反対票なし','U3':'3票が同方向'}[kind]+'なら新規を準備。'
    text+=' 出口A0。' if spec['prior_manager']=='A0' else ' 出口C01：悪化で約25%減量、新しい同方向根拠で1回復元。'
    if spec['min_delay_seconds']:text+=f' 注文伝達に最低{spec["min_delay_seconds"]:g}秒。'
    if spec['observed_fill']:text+=' 全条件約定をその観測価格へ変更。'
    return text


def robust_value(payload: dict, identifier: str, symbol: str, period: str) -> dict:
    """機能: 採否の集中診断を可視の表へ対応させる。

    引数: payload(dict)、identifier/symbol/period(str)。返り値: 表示値(dict)。
    """
    c=payload['assessment']['全条件'][identifier]['期間別'][period][symbol]
    return dict(net_yen=c['収支円'],drawdown_yen=c['時価最大下落円'],removed_one=c['最大勝ち元組除外収支円'],
        removed_session=c['最大黒字場除外収支円'],removed_two=c['上位二勝ち元組同時除外収支円'],
        cycles=c['元組数'],active_sessions=c['稼働セッション数'],waves=payload['index'][identifier]['wave_passes'])


def render_main(payload: dict, preview: bool=False) -> str:
    """機能: 二出口を混ぜず、主中央と単一中央を先頭に比較する。

    引数: payload(dict)、preview(bool)。返り値: 主HTML(str)。
    """
    chart='<a href="５分足と売買.html">５分足と売買</a>' if payload.get('chart_ready') else ''
    body=f'<nav><a href="{ALL}">全32条件の損益</a>{chart}</nav><h1>時間窓合議と入口の安定性</h1>'
    decisions=[payload['assessment']['出口別'][m] for m in MANAGERS]
    if all(d['中央の基礎候補'] and d['中央の収益DD関係']['関係']=='対照優位' and not d['三中心耐性'] for d in decisions):
        body+='<div class="box"><strong>M2中央は両出口で黒字。ただし単一中央より収支が低く、時間窓への依存も解消しませんでした。</strong></div>'
    body+='<p>同じ入口を短め・中央・長めの3窓で判定し、2票以上なら入るM2が主案です。問いは、窓を変えても黒字を維持し、単一窓より収支を改善するか。出口A0と数量調整C01は別々に比較します。</p>'
    body+='<p class="muted">全13セッションと後7はすべて既知。TOPIXミニ初回5枚、NK225マイクロ初回10枚、片方向上限10／20枚、費用0・場内全返済。同じ価格の3窓なので、独立した3予測とは数えません。</p>'
    for manager,title in (('A0','出口A0：元の価格注文'),('B00_RB00_F25_N1','出口C01：1回の減量・復元')):
        decision=payload['assessment']['出口別'][manager]
        status='今回の研究候補基準を通過' if decision['既知比較の研究候補'] else ('黒字基礎は通過、合議の追加改善は未達' if decision['中央の基礎候補'] else '合議の研究候補基準は未達')
        body+='<h2>'+title+'</h2><div class="box"><strong>'+status+'</strong><div class="status">'
        for key,label in zip(VERDICTS,('中央の黒字基礎','中央の収益改善','3中心の耐性','4執行条件','指定8波')):
            value=decision[key]
            body+=f'<span class="{"yes" if value else "no"}" data-verdict="{manager}:{key}" data-value="{str(value).lower()}">{label}：{"通過" if value else "未達"}</span>'
        body+='</div><p class="table-note">研究候補は中央基礎・中央収益改善・3中心耐性の組合せ。執行と波は別判定です。合議固有の予測付加価値は未判定です。</p></div>'
        first=[];rest=[]
        for window in ORDER:
            identifier=f'{window}__{manager}__V000'
            for symbol in SYMBOLS:
                value=aggregate([r for r in payload['sessions'][identifier] if r['symbol']==symbol])
                row=row_html(identifier,symbol,'全13セッション',value,COMPARISON,'comparison',window+' / '+symbol)
                (first if window in ORDER[:2] else rest).append(row)
        body+=table(first,COMPARISON,'入口・銘柄')
        body+='<details><summary>ほかの時計中心も含む全基礎条件</summary>'+table(rest,COMPARISON,'入口・銘柄')+'</details>'
        body+='<p class="table-note">利益・損失は全返済脚を合算。PFと平均比は減量・復元を分割せず元組単位、1枚比は返済枚数で割った平均です。最大下落は含み込み。未定義の比率は合格にしません。</p>'
        rows=[];identifier=decision['主案ID']
        for c in decision['中央の収益DD関係']['差']:
            value=dict(net_yen=c['収支差円'],drawdown_yen=c['最大下落差円'])
            rows.append(row_html(identifier,c['銘柄'],c['期間'],value,DIFFERENCE,'difference',('全13' if c['期間']=='all_symbols' else '後7')+' / '+c['銘柄']))
        body+='<details><summary>M2中央 − 単一中央：'+html.escape(decision['中央の収益DD関係']['関係'])+'</summary>'+table(rows,DIFFERENCE,'期間・銘柄',True)+'<p>同銘柄内の差です。最大下落差はマイナスが改善。入口が違えば元組も異なり、同じ組番号同士の比較はしません。</p></details>'
        rows=[]
        for window in ('S080','S100','S120','M2_080','M2_100','M2_120'):
            identifier=f'{window}__{manager}__V000'
            for period in ('all_symbols','symbols'):
                for symbol in SYMBOLS:
                    rows.append(row_html(identifier,symbol,period,robust_value(payload,identifier,symbol,period),ROBUSTNESS,'robustness',window+' / '+('全13' if period=='all_symbols' else '後7')+' / '+symbol))
        body+='<details><summary>時計中心と大勝ち除外を確認</summary>'+table(rows,ROBUSTNESS,'入口・期間・銘柄')+'<p>最大1勝ち元組と最大黒字場の除外は別々の検査。上位2勝の同時除外は補足です。指定波は全条件で同じ8波の正方向ネット保有20分基準で、全13／後7に共通の参考値を表示しています。</p></details>'
    body+='<details><summary>入口・出口を簡潔に確認</summary><p>Sは単一窓。M2は同方向2票以上、V2は2票以上かつ反対票なし、U3は3票一致です。中立も3票の母数へ含め、合議後の保持は加えません。各窓はEMA主方向・60秒遅延した相手確認・短期価格・120秒の入口保持まで含む完全なH019入口です。</p><p>中央の構成は0.8／1／1.2倍。中心0.8は0.64／0.8／0.96倍、中心1.2は0.96／1.2／1.44倍。EMA期間等の詳細は固定信号設計へ記録しています。</p><p>注文は新規準備時の公開ATRをA0として固定。0.25A0の追跡入口、初期組予算1A0、1.5A0順行から幅3A0追跡、2A0で当初枚数の約半分を利確、360分又は場末返済、全返済後5分休止。C01のB00は2分と直近30秒の気配価格が保有と逆へ進む状態で、板数量は使いません。減量数は現生存枠の25%切捨てを基本に最低1枚、最低1枚を残す範囲。その後の新しいB00同方向根拠で1回だけ復元します。元の返済で退役した枠は復元しません。</p><p>両出口とも実現＋含みが初期組予算Rを割れば全返済を予約します。Rは初回枚数×初回ATR。次行価格や伝達待ちで予算超過があり、損失上限の保証ではありません。入口の合議撤回を保有玉の反転返済へは使いません。</p></details>'
    body+='<details><summary>この比較で言える範囲と監査</summary><p>主案M2中央を結果で入れ替えません。V2/U3・最良中心・良かった出口だけを採用した結果にはしません。過去許可率に合わせた間引き対照は未実施で、合議の独立した予測価値は証明していません。全期間は既知で、将来収益や全相場への保証でもありません。</p>'
    if payload.get('entry_diagnostic'):
        body+='<p>保存後の診断では、同じ原本行・同方向で入った組の収支差は0でした。差は入口時刻や方向が変わった取引から生じています。対応しない組には時刻ずれも含まれ、純粋な追加取引の損益とは呼びません。</p>'
    body+='<ul>'
    sources=[('判定の全内訳','assess_results.json'),('固定条件','探索条件の固定.json'),('追加完備監査','追加完備監査.json'),('信号設計','signal_design.md'),('事前の反証計画','反証計画.md'),('注文接続の人工検査','check_runner.json'),('全数表の独立検算','report_audit.json')]
    if payload.get('entry_diagnostic'):sources.append(('入口経路の事後診断','入口経路の事後診断.json'))
    if payload.get('assessment_independent'):sources.append(('採否結果の独立照合','採否結果の独立照合.json'))
    for title,name in sources:
        body+=f'<li><a href="../../work/wave_v43/{name}">{title}</a></li>'
    body+='</ul></details>'
    return helpers.shell('時間窓合議と入口の安定性',body,preview)


def render_all(payload: dict, preview: bool=False) -> str:
    """機能: 全32条件を選択でき、各銘柄の全13・2週・各場の金額と枚数を表示する。

    引数: payload(dict)、preview(bool)。返り値: 全条件HTML(str)。
    """
    body=f'<nav><a href="{MAIN}">短い比較へ戻る</a></nav><h1>全32条件の損益</h1><p>TOPIXミニ／NK225マイクロ。初回5／10枚、費用0、全13セッションは既知。週はナイトも開始日で分けます。</p><label for="method">手法 </label><select id="method">'
    for spec in payload['specs']:
        body+=f'<option value="{spec["id"]}">{html.escape(spec["id"])}</option>'
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
機能: 固定32条件のうち選択した表だけを表示する。
引数: select.value(str)。返り値: なし。数値の再計算・順位選抜はしない。
--><script>
const select=document.getElementById('method');
/**
 * 機能: 選択した条件の表を表示する。
 * 引数: なし。返り値: なし。
 */
function showMethod(){document.querySelectorAll('[data-method]').forEach(s=>{s.hidden=s.dataset.method!==select.value;});}
select.addEventListener('change',showMethod);showMethod();
</script>'''
    return helpers.shell('全32条件の損益',body,preview)


def verify_guard() -> dict:
    """機能: 完備後だけ結果を読み、固定と全保存成果の指紋を確認する。

    引数: なし。返り値: 完備記録(dict)。暫定版でもこの制約を緩めない。
    """
    extra=read(HERE/'追加完備監査.json')
    assert all(extra[k] is True for k in ('全合格','追加完備完了','元完備全合格','前後全参照不変'))
    assert (extra['全条件数'],extra['全入力数'],extra['全必須出力数'],extra['旧単一窓一致入力数'],extra['全指定波数'])==(32,832,224,156,256)
    assert extra['元完備SHA256']==digest(HERE/'完備監査.json')
    assert extra['追加固定SHA256']==digest(HERE/'追加完備の固定.json')
    assert extra['実装SHA256']==digest(HERE/'completion_guard.py')
    for field in ('必須成果SHA256','参照資料SHA256'):
        for relative,sha in extra[field].items():assert digest(ROOT/relative)==sha,relative
    proof=read(HERE/'完備監査.json')
    assert proof['全合格'] is True and (proof['全条件数'],proof['全入力数'],proof['因果入力数'],proof['旧単一窓一致入力数'])==(32,832,128,156)
    for field in ('参照資料SHA256','出力SHA256'):
        for relative,sha in proof[field].items():assert digest(ROOT/relative)==sha,relative
    return proof


def load_payload() -> tuple[dict,dict]:
    """機能: 完備後の全32条件を、固定順序のまま表示へ接続する。

    引数: なし。返り値: 表示値と全参照指紋(tuple)。
    """
    proof=verify_guard();refs={}
    def source(path: Path) -> object:
        """機能: 読み込む資料を内容指紋へ結ぶ。

        引数: path(Path)。返り値: JSON内容(object)。
        """
        refs[path.relative_to(ROOT).as_posix()]=digest(path);return read(path)
    fixed=source(HERE/'探索条件の固定.json');assessment=source(HERE/'assess_results.json')
    specs=fixed['conditions'];assert len(specs)==len({s['id'] for s in specs})==32
    assert assessment['監査完了'] and set(assessment['全条件'])=={s['id'] for s in specs}
    index={};sessions={}
    for spec in specs:
        identifier=spec['id'];index[identifier]=source(HERE/'summaries'/(identifier+'.json'))
        sessions[identifier]=source(HERE/'sessions'/(identifier+'.json.gz'))
        assert index[identifier]['spec']==spec and len(sessions[identifier])==26
    for name in ('完備監査.json','追加完備監査.json','追加完備の固定.json','completion_guard.py'):
        refs[(HERE/name).relative_to(ROOT).as_posix()]=digest(HERE/name)
    refs[(HERE.parent/'wave_v40/report.py').relative_to(ROOT).as_posix()]=digest(HERE.parent/'wave_v40/report.py')
    extra={}
    for field,name in (('entry_diagnostic','入口経路の事後診断.json'),('assessment_independent','採否結果の独立照合.json')):
        value=source(HERE/name);assert value['全合格'] is True;extra[field]=True
        if field=='entry_diagnostic':
            assert value['事後診断'] and not value['採否変更'] and all(r['同じ初回約定の収支差円']==0 for r in value['結果'])
    return dict(specs=specs,index=index,sessions=sessions,assessment=assessment,names=fixed['全セッション'],**extra,
        chart_ready=(OUT/'５分足と売買.html').is_file()),refs


def main() -> None:
    """機能: 完備後だけ主・全数表を生成し、指紋を保存する。

    引数: --preview(bool)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    payload,refs=load_payload();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/MAIN).write_text(render_main(payload,args.preview),encoding='utf-8')
    (OUT/ALL).write_text(render_all(payload,args.preview),encoding='utf-8')
    for relative,sha in refs.items():assert digest(ROOT/relative)==sha,relative
    value=dict(暫定版=args.preview,全条件数=32,損益行数=1024,比較行数=48,差分行数=8,集中診断行数=48,
        参照資料SHA256=refs,生成実装SHA256=digest(Path(__file__)),
        出力SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in (OUT/MAIN,OUT/ALL)})
    (HERE/'report_manifest.json').write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print('全32条件の主比較と1,024行の損益表を生成。',flush=True)


if __name__=='__main__':main()
