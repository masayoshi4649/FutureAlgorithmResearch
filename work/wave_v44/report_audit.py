"""全返済脚と元組を別集計し、163条件の暗色表を全数照合する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import importlib.util
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import report


HERE,ROOT=report.HERE,report.ROOT
definition=importlib.util.spec_from_file_location('_v44_旧表抽出',HERE.parent/'wave_v40/report_audit.py')
parser_helper=importlib.util.module_from_spec(definition);definition.loader.exec_module(parser_helper)
Tables,read,digest,close=parser_helper.Tables,parser_helper.read,parser_helper.digest,parser_helper.close


def from_ledger(book: dict, saved: dict) -> dict:
    """機能: 各返済脚の価格・向き・数量から、元組損益と全表示金額を別計算する。

    引数: book/saved(dict)。返り値: 独立した場統計(dict)。場内時価極値は完備監査済み保存値。
    """
    factor=1000. if book['symbol']=='TOPIX' else 10.
    close(book['config']['point_value'],factor,'銘柄別の小口倍率')
    gains=[];quantities=[];groups={}
    for trade in book['trades']:
        assert len(trade)==11 and trade[2] in (-1,1) and trade[3]>0 and int(trade[3])==trade[3]
        assert all(math.isfinite(v) for v in trade)
        pnl=trade[2]*trade[3]*(trade[5]-trade[4])*factor
        gains.append(pnl);quantities.append(int(trade[3]));groups.setdefault(int(trade[0]),[]).append(pnl)
    cycles=[];seen=set()
    for cycle in book['cycles']:
        assert len(cycle)==10 and cycle[0] not in seen and cycle[4]>0 and cycle[8] in (-1,1)
        seen.add(cycle[0]);value=math.fsum(groups.get(int(cycle[0]),[]))
        close(cycle[3]*factor,value,'元組と返済脚の一致');cycles.append(value)
    assert seen==set(groups)
    row=dict(session=book['session'],symbol=book['symbol'],
        gross_profit_yen=math.fsum(p for p in gains if p>0),gross_loss_yen=-math.fsum(p for p in gains if p<0),
        net_yen=math.fsum(gains),profit_units=sum(q for p,q in zip(gains,quantities) if p>0),
        loss_units=sum(q for p,q in zip(gains,quantities) if p<0),zero_units=sum(q for p,q in zip(gains,quantities) if p==0),
        cycles=len(cycles),cycle_wins=sum(p>0 for p in cycles),cycle_losses=sum(p<0 for p in cycles),
        cycle_profit_yen=math.fsum(p for p in cycles if p>0),cycle_loss_yen=-math.fsum(p for p in cycles if p<0),
        maximum_trade_profit=max([0.]+cycles),two_largest_cycle_profits=sorted([p for p in cycles if p>0],reverse=True)[:2],
        closed_units=sum(quantities),drawdown_yen=saved['drawdown_yen'],min_equity_yen=saved['min_equity_yen'],
        max_equity_yen=saved['max_equity_yen'],_cycle_gains=cycles)
    return row


def aggregate(rows: list[dict]) -> dict:
    """機能: 場統計を合算し、場間の高値と安値の全組合せから最大下落を検算する。

    引数: rows(list[dict])。返り値: 表示用の期間統計(dict)。売買側集計は呼ばない。
    """
    rows=sorted(rows,key=lambda r:r['session']);assert rows
    output={k:math.fsum(r[source] for r in rows) for k,source in (
        ('profit_yen','gross_profit_yen'),('loss_yen','gross_loss_yen'),('net_yen','net_yen'),
        ('profit_units','profit_units'),('loss_units','loss_units'),('zero_units','zero_units'),('cycles','cycles'))}
    output['net_units']=output['profit_units']-output['loss_units']
    positive=[p for row in rows for p in row['_cycle_gains'] if p>0]
    negative=[-p for row in rows for p in row['_cycle_gains'] if p<0]
    win,loss=math.fsum(positive),math.fsum(negative)
    output['profit_factor']=win/loss if loss else None
    output['average_payoff']=(win/len(positive))/(loss/len(negative)) if positive and negative else None
    output['unit_payoff']=(output['profit_yen']*output['loss_units'])/(output['loss_yen']*output['profit_units']) if output['profit_units'] and output['loss_units'] and output['loss_yen'] else None
    offsets=[math.fsum(r['net_yen'] for r in rows[:i]) for i in range(len(rows))]
    peaks=[0.]+[offsets[i]+r['max_equity_yen'] for i,r in enumerate(rows)]
    falls=[r['drawdown_yen'] for r in rows]
    for i,r in enumerate(rows):
        falls.extend(p-offsets[i]-r['min_equity_yen'] for p in peaks[:i+1])
    output['drawdown_yen']=max([0.]+falls)
    output['active_sessions']=sum(bool(r['_cycle_gains']) for r in rows)
    output.update(removed_one=output['net_yen']-max([0.]+positive),
        removed_session=output['net_yen']-max([0.]+[r['net_yen'] for r in rows]),
        removed_two=output['net_yen']-math.fsum(sorted(positive,reverse=True)[:2]))
    return output


def week(session: str) -> str:
    """機能: セッション開始日から週を独立に分類する。

    引数: session(str)。返り値: 月曜日(str)。
    """
    d=date.fromisoformat(session[:10]);return (d-timedelta(days=d.weekday())).isoformat()


def expectations(specs: list[dict], sessions: dict, index: dict, names: list[str]) -> tuple:
    """機能: 全期間・全主比較・時計集中診断・元方式との差を台帳側統計から導出する。

    引数: specs(list[dict])、sessions/index(dict)、names(list[str])。返り値: 四表の期待値(tuple)。
    """
    profits={};comparison={};robustness={};differences={};periods={}
    for spec in specs:
        identifier=spec['id']
        for symbol in report.SYMBOLS:
            own=[r for r in sessions[identifier] if r['symbol']==symbol];assert len(own)==13
            total=aggregate(own);profits[(identifier,symbol,'全13セッション')]=total
            for start in ('2026-09-21','2026-09-28'):
                profits[(identifier,symbol,start+'週')]=aggregate([r for r in own if week(r['session'])==start])
            for row in own:profits[(identifier,symbol,row['session'])]=aggregate([row])
            for period,chosen in (('all_symbols',names),('symbols',names[6:])):
                value=aggregate([r for r in own if r['session'] in chosen]);periods[(identifier,symbol,period)]=value
                if identifier in report.CLOCKS:
                    robustness[(identifier,symbol,period)]=dict(value,waves=index[identifier]['wave_passes'])
            if spec['role']!='supplementary':comparison[(identifier,symbol,'全13セッション')]=total
    for reference in (report.CONTROL,report.BASELINE):
        for period in ('all_symbols','symbols'):
            for symbol in report.SYMBOLS:
                a,b=periods[(report.PRIMARY,symbol,period)],periods[(reference,symbol,period)]
                differences[(report.PRIMARY,symbol,period+'/'+reference)]={f:a[f]-b[f] for f in report.DIFFERENCE}
    exploratory={(report.EXPLORATORY,symbol,period):periods[(report.EXPLORATORY,symbol,period)]
                 for symbol in report.SYMBOLS for period in ('all_symbols','symbols')}
    return profits,comparison,robustness,differences,exploratory


def verify_rows(rows: list[dict], expected: dict, fields: tuple) -> int:
    """機能: 表の全行集合・数値属性・丸めた可視文字を独立に照合する。

    引数: rows(list[dict])、expected(dict)、fields(tuple)。返り値: 数値セル数(int)。
    """
    found=set();count=0
    for row in rows:
        key=(row['id'],row['symbol'],row['period']);assert key in expected and key not in found,key
        found.add(key);assert tuple(row['cells'])==fields,key
        for field in fields:
            cell=row['cells'][field];value=expected[key][field]
            close(cell['value'],value,(key,field))
            decimals=2 if field in ('profit_factor','average_payoff','unit_payoff') else 0
            shown='未定義' if value is None else f'{value:,.{decimals}f}'
            assert cell['text']==shown,(key,field,cell['text'],shown);count+=1
    assert found==set(expected),(len(found),len(expected))
    return count


def verify_html(main: str, all_html: str, payload: dict, expected: tuple, preview: bool) -> tuple:
    """機能: 黒字と追加改善の判定を分け、全163条件の全数値・選択・HTML構造を検査する。

    引数: main/all_html(str)、payload(dict)、expected(tuple)、preview(bool)。返り値: セル数と解析器(tuple)。
    """
    pages=[]
    for source in (main,all_html):
        parsed=Tables();parsed.feed(source);parsed.close()
        assert parsed.current is None and parsed.current_cell is None
        assert len(parsed.ids)==len(set(parsed.ids)) and parsed.preview==preview
        pages.append(parsed)
    a,b=pages;profits,comparison,robustness,differences,exploratory=expected
    count=verify_rows(b.rows,profits,report.FINANCIAL)
    for kind,values,fields in (('comparison',comparison,report.COMPARISON),('robustness',robustness,report.ROBUSTNESS),('difference',differences,report.DIFFERENCE),('exploratory',exploratory,report.COMPARISON)):
        count+=verify_rows([r for r in a.rows if r['kind']==kind],values,fields)
    assert len(b.rows)==5216 and len(a.rows)==118
    ids=[s['id'] for s in payload['specs']]
    assert b.options==ids and b.sections==[(identifier,i>0) for i,identifier in enumerate(ids)]
    assert a.verdict=={field:payload['assessment'][field] for field in report.VERDICTS}
    assert '全13セッションと後7はすべて既知' in main and 'ゲート自体の独立した予測価値は未判定' in main
    assert 'B00は2分と直近30秒の気配価格' in main and '板数量は使いません' in main
    assert '探索後の参考' in main and 'この50%版の時計・方向乱数対照は未実施' in main
    return count,pages


def selftest() -> dict:
    """機能: 新しい成績を読まず、163条件の全表示と改竄拒否を人工データで確認する。

    引数: なし。返り値: 人工証跡(dict)。正式HTMLは保存しない。
    """
    import design
    specs=design.catalog()+design.supplementary();names=[f'2026-09-{d:02d}_{part}' for d in (21,22,23,24,25,28) for part in ('Day','Night')]+['2026-09-29_Day']
    sessions={};index={};assessment=dict(全条件={},中央比較={},既知比較の研究候補=False,**{key:False for key in report.VERDICTS})
    for spec in specs:
        identifier=spec['id'];own=[]
        for symbol in report.SYMBOLS:
            factor=1000. if symbol=='TOPIX' else 10.
            for i,name in enumerate(names):
                amounts=(3.,-5.,0.) if i%2 else (5.,-2.,4.)
                trades=[[0,0,1,2,100,100+amounts[0],0,1,1,0,0],
                        [0,0,-1,1,100,100-amounts[1],0,2,1,0,0],
                        [1,0,1,3,100,100+amounts[2],3,4,1,0,0]]
                cycles=[[0,0,2,2*amounts[0]+amounts[1],5,1,0,0,1,0],
                        [1,3,4,3*amounts[2],5,1,0,0,1,0]]
                saved=dict(drawdown_yen=7*factor,min_equity_yen=-3*factor,max_equity_yen=25*factor)
                book=dict(symbol=symbol,session=name,config=dict(point_value=factor),trades=trades,cycles=cycles)
                own.append(from_ledger(book,saved))
        sessions[identifier]=own;index[identifier]=dict(spec=spec,wave_passes=5)
        details={}
        for period,selected in (('all_symbols',names),('symbols',names[6:])):
            details[period]={}
            for symbol in report.SYMBOLS:
                v=aggregate([r for r in own if r['symbol']==symbol and r['session'] in selected])
                details[period][symbol]=dict(収支円=v['net_yen'],時価最大下落円=v['drawdown_yen'],最大勝ち元組除外収支円=v['removed_one'],
                    最大黒字場除外収支円=v['removed_session'],上位二勝ち元組同時除外収支円=v['removed_two'],元組数=v['cycles'],稼働セッション数=v['active_sessions'])
        assessment['全条件'][identifier]=dict(期間別=details)
    expected=expectations(specs,sessions,index,names)
    for reference in (report.CONTROL,report.BASELINE):
        rows=[]
        for (identifier,symbol,combined),v in expected[3].items():
            period,other=combined.split('/')
            if reference==other:rows.append(dict(期間=period,銘柄=symbol,収支差円=v['net_yen'],最大下落差円=v['drawdown_yen']))
        assessment['中央比較'][reference]=dict(収益DD関係=dict(差=rows,関係='同値'))
    payload=dict(specs=specs,sessions=sessions,index=index,assessment=assessment,names=names)
    main=report.render_main(payload,True);all_html=report.render_all(payload,True)
    cells,_=verify_html(main,all_html,payload,expected,True)
    rejected=0
    broken=(all_html.replace('data-value="','data-value="1',1),
        re.sub(r'(<td[^>]*data-field="profit_yen"[^>]*>)[^<]+',r'\g<1>999,999',all_html,count=1),
        all_html.replace('data-id="A0__V000"','data-id="別条件"',1),
        all_html.replace('value="A0__V000"','value="別条件"',1))
    for value in broken:
        try:verify_html(main,value,payload,expected,True)
        except (AssertionError,ValueError):rejected+=1
    valid='<tr data-kind="profit" data-id="人工" data-symbol="TOPIX" data-period="場"><td data-field="net_yen" data-value="1000">1,000</td></tr>'
    for value in (valid.replace('1000','1001'),valid.replace('>1,000<','>1,001<'),valid+valid,''):
        parsed=Tables();parsed.feed(value)
        try:verify_rows(parsed.rows,{('人工','TOPIX','場'):{'net_yen':1000.}},('net_yen',))
        except AssertionError:rejected+=1
    assert rejected==8
    return dict(全合格=True,全条件選択数=163,損益行数=5216,比較行数=70,集中診断行数=36,差分行数=8,探索参考行数=4,
        可視数値セル数=cells,破損拒否数=rejected,実損益読取=False,正式HTML保存=False,
        参照資料SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in (Path(__file__),HERE/'report.py',HERE/'design.py',HERE.parent/'wave_v40/report.py',HERE.parent/'wave_v40/report_audit.py')})


def run() -> dict:
    """機能: 完備後だけ全4238台帳を別集計し、全財務表と集中診断を照合する。

    引数: なし。返り値: 全数表監査(dict)。新しい売買は再生しない。
    """
    proof=report.verify_guard();manifest=read(HERE/'report_manifest.json');refs=dict(manifest['参照資料SHA256'])
    for relative,sha in {**refs,**manifest['出力SHA256']}.items():assert digest(ROOT/relative)==sha,relative
    assert manifest['生成実装SHA256']==digest(HERE/'report.py')
    fixed=read(HERE/'探索条件の固定.json');specs=fixed['conditions']+fixed['supplementary'];names=fixed['全セッション']
    assessment=read(HERE/'assess_results.json');sessions={};index={};count=legs=0
    for spec in specs:
        identifier=spec['id'];base=report.directory(spec);path=base/'ledgers'/(identifier+'.json.gz');relative=path.relative_to(ROOT).as_posix()
        refs[relative]=digest(path);assert refs[relative]==proof['出力SHA256'][relative]
        books=read(path);mapping={(b['session'],b['symbol']):b for b in books}
        saved=read(base/'sessions'/(identifier+'.json.gz'));assert len(books)==len(mapping)==len(saved)==26
        assert set(mapping)=={(n,s) for n in names for s in report.SYMBOLS}
        own=[]
        for row in saved:
            book=mapping[(row['session'],row['symbol'])];value=from_ledger(book,row)
            for field,number in value.items():
                if field in ('session','symbol','_cycle_gains','two_largest_cycle_profits'):continue
                close(row[field],number,(identifier,row['session'],row['symbol'],field))
            assert row['two_largest_cycle_profits']==value['two_largest_cycle_profits']
            own.append(value);count+=1;legs+=len(book['trades'])
        sessions[identifier]=own;index[identifier]=read(base/'summaries'/(identifier+'.json'))
        for period,selected in (('all_symbols',names),('symbols',names[6:])):
            for symbol in report.SYMBOLS:
                v=aggregate([r for r in own if r['symbol']==symbol and r['session'] in selected]);saved_total=index[identifier][period][symbol]
                for name,field in (('profit_yen','gross_profit_yen'),('loss_yen','gross_loss_yen'),('net_yen','net_yen'),
                    ('profit_units','profit_units'),('loss_units','loss_units'),('zero_units','zero_units'),('cycles','cycles'),
                    ('drawdown_yen','drawdown_yen'),('average_payoff','average_cycle_payoff')):
                    close(saved_total[field],v[name],(identifier,period,symbol,name))
    assert count==4238
    expected=expectations(specs,sessions,index,names);payload=dict(specs=specs,assessment=assessment)
    # ----------------------------------------
    # 探索後の参考文も、主案へ昇格させず全4セルの実値で確認する。
    for symbol in report.SYMBOLS:
        for period,chosen in (('all_symbols',names),('symbols',names[6:])):
            a=aggregate([r for r in sessions[report.EXPLORATORY] if r['symbol']==symbol and r['session'] in chosen])
            b=aggregate([r for r in sessions[report.CONTROL] if r['symbol']==symbol and r['session'] in chosen])
            assert a['net_yen']>b['net_yen'],('探索後の増益説明',symbol,period)
    paths=(report.OUT/report.MAIN,report.OUT/report.ALL)
    cells,pages=verify_html(paths[0].read_text(encoding='utf-8'),paths[1].read_text(encoding='utf-8'),payload,expected,manifest['暫定版'])
    links=0
    for path,page in zip(paths,pages):
        for href in page.links:
            url=urlsplit(href);assert not url.scheme and not url.netloc
            target=(path.parent/unquote(url.path)).resolve()
            if target==HERE/'report_audit.json':continue
            assert target.is_file(),target
            if url.fragment:assert unquote(url.fragment) in parser_helper.parse(target).ids
            links+=1
    for relative,sha in refs.items():assert digest(ROOT/relative)==sha,relative
    return dict(全合格=True,全条件数=163,全台帳数=count,全返済脚数=legs,損益表示行数=5216,
        比較表示行数=70,集中診断表示行数=36,差分表示行数=8,探索参考表示行数=4,可視数値セル数=cells,全リンク数=links,
        全返済からの金額枚数一致=True,全元組の集中診断一致=True,全期間週各場一致=True,
        全163選択対象一致=True,黒字と改善の判定分離一致=True,全リンク一致=True,全数表暫定版=manifest['暫定版'],
        限定='場内DD・極値は完備会計で検証済み保存値。場間DD接続は独立式。元組は返済脚を再集計し、集中除外も別計算。',
        参照資料SHA256=refs,出力SHA256=manifest['出力SHA256'],監査実装SHA256=digest(Path(__file__)),
        報告実装SHA256=digest(HERE/'report.py'),新売買再生=False)


def main() -> None:
    """機能: 人工だけ又は完備後の全数表検査を実行し今回領域へ保存する。

    引数: --selftest(bool)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--selftest',action='store_true');args=parser.parse_args()
    value=selftest() if args.selftest else run();path=HERE/('report_selftest.json' if args.selftest else 'report_audit.json')
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in value.items() if k not in ('参照資料SHA256','出力SHA256')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
