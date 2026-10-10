"""全返済台帳を別集計し、260条件の表示数値と主副の判定を検算する。"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import importlib.util
import json
import math
from pathlib import Path
import pickle
import re
from urllib.parse import unquote, urlsplit

import report


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
definition=importlib.util.spec_from_file_location('_v42_旧独立表監査',HERE.parent/'wave_v40/report_audit.py')
independent=importlib.util.module_from_spec(definition)
definition.loader.exec_module(independent)
read=independent.read
digest=independent.digest
close=independent.close
from_trades=independent.from_trades
aggregate=independent.aggregate
Tables=independent.Tables
verify_rows=independent.verify_rows
FIELDS=report.MONEY_FIELDS+report.UNIT_FIELDS
SYMBOLS=report.SYMBOLS


def monday(session: str) -> str:
    """機能: セッション開始日から週の所属を独立に求める。

    引数: session(str)。返り値: 月曜日の日付(str)。
    """
    value=date.fromisoformat(session[:10])
    return (value-timedelta(days=value.weekday())).isoformat()


def independent_flow(identifier: str, ledgers: list[dict], cache: dict, panels: dict) -> dict:
    """機能: 旧標本と新パネルのD/Iから、表示する主3方式の段階を再集計する。

    引数: identifier(str)、ledgers(list[dict])、cache/panels(dict)。返り値: 銘柄別件数(dict)。
    原本からパネルの再抽出は既存入力監査が担当し、ここでは表示への結合を独立確認する。
    """
    assert identifier in ('F00','F01','F02')
    totals={symbol:{field:0 for field in report.FLOW_FIELDS} for symbol in SYMBOLS}
    for ledger in ledgers:
        key=(ledger['session'],ledger['symbol']);info=ledger['入口根拠'];canonical=info['母集団キー']
        group=cache[canonical][key];extra={r['band_id']:r for r in panels[canonical][key]}
        local={field:0 for field in report.FLOW_FIELDS};qualified=[]
        for band in group:
            local['bands']+=1
            trials=band['trials'];complete=len(trials)==2 and all(t['complete'] for t in trials)
            old_values=[independent.trial_values(band,t) for t in trials]
            assert complete==band['features']['two_trials_complete']
            local['two_trials']+=int(complete)
            if identifier=='F00':ratios=[item[0] for item in old_values]
            else:
                ratios=[];source='strict' if identifier=='F01' else 'local'
                observed=extra[band['band_id']]
                for trial in observed['trials']:
                    publication=trial['publications'][-1]
                    usable=bool(trial['complete_available'] and publication['raw_quantity_known']
                        and (source=='local' or publication['old_quantity_known_so_far']) and publication['decrease']>0)
                    ratio=publication['increase_after_decrease']/publication['decrease'] if usable else None
                    close(trial['u_'+source],ratio,(identifier,key,band['band_id'],'原本比率'))
                    ratios.append(ratio)
                assert complete==observed['features_'+source]['two_trials_complete']
            comparable=complete and len(ratios)==2 and all(value is not None for value in ratios)
            if band['status']!='breakout':continue
            assert complete and band['terminal']['event_index']>trials[1]['end']['event_index']
            local['completed_breakout']+=1;local['breakout_comparable']+=int(comparable)
            if comparable and ratios[1]<ratios[0] and old_values[1][1]<old_values[0][1]:qualified.append(band)
        local['candidates']=len(qualified);local['trades']=len(ledger['trades'])
        assert [b['band_id'] for b in qualified]==[r['band_id'] for r in info['候補']],(identifier,key,'候補集合')
        counts=info['段階件数']
        for a,b in (('全帯','bands'),('二試行完了','two_trials'),('完了後の初回突破','completed_breakout'),
            ('完了後突破の板比較可能','breakout_comparable'),('全候補','candidates')):
            assert counts.get(a,0)==local[b],(identifier,key,a)
        for saved,band in zip(info['候補'],qualified):
            assert saved['decision']==band['terminal'] and saved['direction']==band['direction']
        chain=[local[field] for field in report.FLOW_FIELDS]
        assert chain==sorted(chain,reverse=True)
        for field in report.FLOW_FIELDS:totals[key[1]][field]+=local[field]
    return totals


def expectations(specs: list[dict], sessions: dict, totals: dict, flow: dict) -> tuple:
    """機能: 財務・20比較・差分・段階表の全行期待値を独立計算する。

    引数: specs(list[dict])、sessions/totals/flow(dict)。返り値: 4数表の期待辞書(tuple)。
    """
    profit={};comparison={};differences={};stages={}
    for spec in specs:
        identifier=spec['id']
        for symbol in SYMBOLS:
            own=[row for row in sessions[identifier] if row['symbol']==symbol]
            assert len(own)==13
            for row in own:profit[(identifier,symbol,row['session'])]=row
            profit[(identifier,symbol,'全13セッション')]=totals[identifier][symbol]
            for first in ('2026-09-21','2026-09-28'):
                profit[(identifier,symbol,first+'週')]=aggregate([row for row in own if monday(row['session'])==first])
            if identifier in report.COMPARISONS:comparison[(identifier,symbol,'全13セッション')]=totals[identifier][symbol]
    for identifier,parent in report.OBSERVATIONS:
        for symbol in SYMBOLS:
            a,b=totals[identifier][symbol],totals[parent][symbol]
            differences[(identifier,symbol,parent)]={field:a[field]-b[field] for field in report.DIFFERENCE_FIELDS}
    for identifier in ('F00','F01','F02'):
        for symbol in SYMBOLS:stages[(identifier,symbol,'全13セッション')]=flow[identifier][symbol]
    return profit,comparison,differences,stages


def verify_html(main_html: str, all_html: str, payload: dict, expected: tuple, preview: bool) -> tuple:
    """機能: 可視文字・属性数値・全選択・2仮説の判定をHTMLから再抽出する。

    引数: main_html/all_html(str)、payload(dict)、expected(tuple)、preview(bool)。
    返り値: 数値セル数と解析済み2画面(tuple)。
    """
    pages=[]
    for source in (main_html,all_html):
        page=Tables();page.feed(source);page.close()
        assert page.preview==preview and page.current is None and page.current_cell is None
        assert len(page.ids)==len(set(page.ids))
        pages.append(page)
    main_page,all_page=pages
    profit,comparison,differences,stages=expected
    cells=verify_rows(all_page.rows,profit,FIELDS)
    for kind,values,fields in (('comparison',comparison,report.COMPARISON_FIELDS),
        ('difference',differences,report.DIFFERENCE_FIELDS),('flow',stages,report.FLOW_FIELDS)):
        cells+=verify_rows([r for r in main_page.rows if r['kind']==kind],values,fields)
    assert len(all_page.rows)==8320 and len(main_page.rows)==58
    assert all_page.options==[spec['id'] for spec in payload['specs']]
    assert all_page.sections==[(spec['id'],i>0) for i,spec in enumerate(payload['specs'])]
    desired={identifier+':'+key:payload['assessment']['仮説別'][identifier][key]
        for identifier in ('F01','F02') for key in report.VERDICTS}
    assert main_page.verdict==desired
    assert '全13セッションは既知' in main_html and '学習除外はありません' in main_html
    return cells,pages


def selftest() -> dict:
    """機能: 新成績を読まずに260条件の全画面と破損拒否を検査する。

    引数: なし。返り値: 人工の集計・表示検査(dict)。正式HTMLは保存しない。
    """
    import design
    specs=design.catalog()+design.supplementary()
    names=[f'2026-09-{day:02d}_{part}' for day in (21,22,23,24,25,28) for part in ('Day','Night')]+['2026-09-29_Day']
    sessions={};totals={};index={}
    for spec in specs:
        identifier=spec['id'];saved=[];totals[identifier]={}
        for symbol in SYMBOLS:
            own=[];factor=1000. if symbol=='TOPIX' else 10.
            for i,name in enumerate(names):
                pnl=(-5.,0.,10.,2.,-1.)[i%5];d=1 if i%2 else -1
                ledger=dict(trades=[[0,1,d,100.,100.+d*pnl,2.,pnl,1,0,0]],stats=[pnl,abs(pnl)+2.])
                row=from_trades(ledger,factor)
                row.update(session=name,symbol=symbol,minimum_yen=min(0.,pnl-1.)*factor,
                    maximum_yen=max(0.,pnl+1.)*factor,held_minutes=1.,candidates=1,accepted=1,cancelled=0)
                saved.append(row);own.append(row)
            total=aggregate(own);total['candidates']=13
            totals[identifier][symbol]=total
        sessions[identifier]=saved;index[identifier]=dict(spec=spec,symbols=totals[identifier])
    flow={identifier:{symbol:dict(bands=50,two_trials=40,completed_breakout=30,breakout_comparable=20,candidates=13,trades=13)
        for symbol in SYMBOLS} for identifier in ('F00','F01','F02')}
    assessment=dict(仮説別={identifier:dict(基礎候補=False,板の比較付加価値=identifier=='F02',実行感度=False,
        窓距離感度=False,既知経済目安合格=False) for identifier in ('F01','F02')})
    payload=dict(specs=specs,index=index,sessions=sessions,assessment=assessment,flow=flow)
    expected=expectations(specs,sessions,totals,flow)
    main_html=report.render_main(payload,True);all_html=report.render_all(payload,True)
    cells,_=verify_html(main_html,all_html,payload,expected,True)
    broken=(all_html.replace('data-value="', 'data-value="1',1),
        re.sub(r'(<td[^>]*data-field="profit_yen"[^>]*>)[^<]+',r'\g<1>999,999',all_html,count=1),all_html.replace('data-id="F00"','data-id="F99"',1),
        all_html.replace('value="F00"','value="F99"',1))
    rejected=0
    for value in broken:
        try:verify_html(main_html,value,payload,expected,True)
        except (AssertionError,ValueError):rejected+=1
    # 数値改変用の表示が必ず存在する対象を別に作る。
    valid='<tr data-kind="profit" data-id="F01" data-symbol="TOPIX" data-period="人工"><td data-field="net_yen" data-value="1000">1,000</td></tr>'
    for value in (valid.replace('1000','1001'),valid.replace('>1,000<','>1,001<'),valid+valid,''):
        parser=Tables();parser.feed(value)
        try:verify_rows(parser.rows,{('F01','TOPIX','人工'):{'net_yen':1000.}},('net_yen',))
        except AssertionError:rejected+=1
    assert rejected==8,rejected
    assert independent.ratios(0.,0.,0,0)==(None,None)
    data=[]
    for i,(net,high,low,dd) in enumerate(((5,12,-4,16),(-8,3,-12,15),(10,18,-3,8))):
        row=from_trades(dict(trades=[[0,1,1,100,100+net,2,net,1,0,0]],stats=[net,dd]),1.)
        row.update(session=f'2026-01-0{i+1}_Day',maximum_yen=high,minimum_yen=low);data.append(row)
    close(aggregate(data)['drawdown_yen'],19.,'セッション接続DD')
    return dict(全合格=True,全条件選択数=260,損益行数=8320,比較行数=40,差分行数=12,段階行数=6,
        可視数値セル数=cells,破損拒否数=rejected,実損益読取=False,正式HTML保存=False,
        SHA256={path.relative_to(ROOT).as_posix():digest(path) for path in (Path(__file__),HERE/'report.py',HERE.parent/'wave_v40/report_audit.py',HERE.parent/'wave_v40/report.py')})


def run() -> dict:
    """機能: 完備後の全6760台帳を独立集計し、2ページの全数値を照合する。

    引数: なし。返り値: 全数表の監査証跡(dict)。売買器は呼ばない。
    """
    report.verify_guard()
    manifest=read(HERE/'report_manifest.json');refs=dict(manifest['参照資料SHA256'])
    for relative,value in refs.items():assert digest(ROOT/relative)==value,relative
    for relative,value in manifest['出力SHA256'].items():assert digest(ROOT/relative)==value,relative
    assert manifest['生成実装SHA256']==digest(HERE/'report.py')
    fixed=read(HERE/'探索条件の固定.json');specs=fixed['主条件']+fixed['補助条件']
    assert len(specs)==len({spec['id'] for spec in specs})==260
    index=read(HERE/'全条件の期間集計.json.gz');assessment=read(HERE/'assess_results.json')
    complete=read(HERE/'主再生の完了.json');calculated={};totals={};selected={};ntrades=nrows=0
    for spec in specs:
        identifier=spec['id'];assert index[identifier]['spec']==spec
        path=HERE/'ledgers'/(identifier+'.json.gz');ledgers=read(path)
        relative=path.relative_to(ROOT).as_posix();refs[relative]=digest(path)
        assert refs[relative]==complete['参照SHA256'][relative]
        if identifier in ('F00','F01','F02'):selected[identifier]=ledgers
        ledger_map={(r['session'],r['symbol']):r for r in ledgers}
        saved=read(HERE/'sessions'/(identifier+'.json.gz'))
        assert len(saved)==len(ledgers)==len(ledger_map)==26
        own=[]
        for row in saved:
            key=(row['session'],row['symbol']);ledger=ledger_map[key]
            value=from_trades(ledger,1000. if row['symbol']=='TOPIX' else 10.)
            for field in ('profit_yen','loss_yen','net_yen','profit_units','loss_units','zero_units','trades',
                'net_r','max_win_yen','long_trades','short_trades','drawdown_yen'):
                close(row[field],value[field],(identifier,key,field))
            candidates=len(ledger['入口根拠']['候補'])
            close(row['candidates'],candidates,(identifier,key,'候補数'))
            value.update(session=row['session'],symbol=row['symbol'],minimum_yen=row['minimum_yen'],
                maximum_yen=row['maximum_yen'],candidates=candidates)
            own.append(value);ntrades+=value['trades'];nrows+=1
        calculated[identifier]=own;totals[identifier]={}
        for symbol in SYMBOLS:
            rows=[r for r in own if r['symbol']==symbol];assert len(rows)==13
            total=aggregate(rows);total['candidates']=sum(r['candidates'] for r in rows)
            for field,value in total.items():
                if field!='net_units':close(index[identifier]['symbols'][symbol][field],value,(identifier,symbol,field))
            totals[identifier][symbol]=total
    cache_path=HERE.parent/'wave_v40/band_cache.pkl';panel_path=HERE/'trial_panel.pkl'
    cache=pickle.loads(cache_path.read_bytes());panels=pickle.loads(panel_path.read_bytes())
    flow={identifier:independent_flow(identifier,ledgers,cache,panels) for identifier,ledgers in selected.items()}
    expected=expectations(specs,calculated,totals,flow)
    payload=dict(specs=specs,assessment=assessment)
    main_path=report.OUT/report.MAIN;all_path=report.OUT/report.ALL
    cells,pages=verify_html(main_path.read_text(encoding='utf-8'),all_path.read_text(encoding='utf-8'),payload,expected,manifest['暫定版'])
    for path,page in zip((main_path,all_path),pages):
        for href in page.links:
            url=urlsplit(href);assert not url.scheme and not url.netloc
            target=(path.parent/unquote(url.path)).resolve()
            if target==HERE/'report_audit.json':continue
            assert target.is_file(),target
            if url.fragment:assert unquote(url.fragment) in independent.parse(target).ids
    for relative,value in refs.items():assert digest(ROOT/relative)==value,relative
    assert nrows==6760
    return dict(全合格=True,全条件数=260,全台帳数=nrows,全返済数=ntrades,損益表示行数=8320,
        比較表示行数=40,差分表示行数=12,段階表示行数=6,可視数値セル数=cells,
        全返済からの金額枚数R一致=True,全期間週各場一致=True,全260選択対象一致=True,
        主副の判定分離一致=True,全リンク一致=True,全13既知=True,学習除外なし=True,
        全数表暫定版=manifest['暫定版'],段階件数=flow,
        限定='場内DD・極値は完備会計で検証済みの保存値に依拠し、場間DD接続は独立式で再計算。数量比率のD/Iは入力監査済み公開パネルから独立再除算。',
        参照資料SHA256=refs,出力SHA256=manifest['出力SHA256'],監査実装SHA256=digest(Path(__file__)),
        報告実装SHA256=digest(HERE/'report.py'),新売買再生=False)


def main() -> None:
    """機能: 人工だけ又は完備後の全数表監査を実行し、今回領域へ保存する。

    引数: --selftest(bool)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--selftest',action='store_true');args=parser.parse_args()
    value=selftest() if args.selftest else run()
    path=HERE/('report_selftest.json' if args.selftest else 'report_audit.json')
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps({key:v for key,v in value.items() if key not in ('参照資料SHA256','出力SHA256','SHA256')},ensure_ascii=False))


if __name__=='__main__':main()
