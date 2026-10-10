"""統合の中央・主窓感度・追加ナイトを同じ基準で表示する。"""

from pathlib import Path
import pickle

import numpy as np

import replay_parts as replay
import financial_report as financial
import new_report as charts

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
QUANTITY_NAMES={'A0':'数量調整なし','C01':'悪化で25%減量・回復時に復元',
    'F50':'順行後50%減量・回復時に復元','F50_NONE':'順行後50%減量・復元なし'}
EXIT_NAMES={'E00':'追跡幅3ATRを維持','E10':'3ATR順行後に追跡幅1.5ATR','E11':'3ATR順行後に追跡幅0.75ATR'}


def read(path: Path) -> object:
    """機能: 統合結果の圧縮又は通常JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return replay.previous.read(path)


def pass_cells(identifier: str,summary: dict,rows: list[dict]) -> list[dict]:
    """機能: 全13と後7における黒字・枚数平均比・上位2勝ち除外を評価する。

    引数: identifier(str)、summary(dict)、rows(list[dict])。返り値: 四セル(list[dict])。
    """
    late=read(HERE.parent/'wave_v38/探索条件の固定.json')['後半7セッション'];result=[]
    for period in ('all_symbols','symbols'):
        for symbol in ('TOPIX','NK225'):
            value=summary[period][symbol]
            selected=[r for r in rows if r['symbol']==symbol and (period=='all_symbols' or r['session'] in late)]
            top=sorted([p for r in selected for p in r['two_largest_cycle_profits']],reverse=True)[:2]
            remaining=value['net_yen']-sum(top);payoff=value['average_unit_payoff']
            result.append(dict(id=identifier,period=period,symbol=symbol,net_yen=value['net_yen'],
                drawdown_yen=value['drawdown_yen'],average_unit_payoff=payoff,top2_removed=remaining,
                基礎合格=value['net_yen']>0 and payoff is not None and payoff>1 and remaining>0))
    return result


def main() -> None:
    """機能: 全36統合比較と中央12の追加適用を統合し、実口座値と図を保存する。

    引数: なし。返り値: なし(None)。追加損益による方式変更は行わない。
    """
    assert read(HERE/'exit_integration_complete.json')['全合格']
    assert read(HERE/'integration_followup/clock/complete.json')['全合格']
    assert read(HERE/'統合追加ナイトの入力前提完了.json')['全合格']
    fixed=read(HERE/'統合追試の固定.json')
    inputs=pickle.loads((HERE/'inputs.pkl').read_bytes());central={};sensitivity={};methods=[];plots=[]
    allcells=[];fullperiods={}
    for spec in fixed['追加ナイト']:
        identifier=spec['id'];folder=HERE/'exit_integration'
        old_summary=read(folder/'summaries'/(identifier+'.json'))
        rows=read(folder/'sessions'/(identifier+'.json.gz'))
        allcells+=pass_cells(identifier,old_summary,rows);central[identifier]=old_summary
        new_folder=HERE/'integration_followup/new'
        new_rows=read(new_folder/'sessions'/(identifier+'.json.gz'))
        rows+=new_rows
        ledgers=read(folder/'ledgers'/(identifier+'.json.gz'))+read(new_folder/'ledgers'/(identifier+'.json.gz'))
        assert len(rows)==len(ledgers)==28
        series={}
        for ledger in ledgers:
            key=ledger['session'],ledger['symbol'];ready=inputs[key]
            curve,totals=charts.chart.reconstruct(ready,ledger)
            expected=next(r for r in rows if (r['session'],r['symbol'])==key)
            for field,value in totals.items():assert abs(expected[field]-value)<1e-6
            series[key]=curve[:,0]
            if key[0]!=replay.NEW_SESSION:continue
            orders=np.asarray(ledger['orders'],float);times=ready['time_s'];factor=ledger['config']['point_value']
            points=charts.tracking_points(ready,curve,orders)
            plots.append(dict(id=identifier,name=identifier+'｜'+QUANTITY_NAMES[spec['quantity_id']]+'・'+EXIT_NAMES[spec['exit_id']],symbol=key[1],candles=charts.chart.candles(
                ROOT/'candle_5min'/key[1]/(key[0]+'.csv'),ready),orders=[[float(times[int(o[0])]),*o.tolist()] for o in orders],
                tracking=[[float(times[i]),float(curve[i,0]*factor),float(curve[i,2]),float(curve[i,3])] for i in points],
                totals=totals,start=ready['start'],end=float(times[-1]),cap=ledger['config']['audit_cap']))
        names=sorted({r['session'] for r in rows})
        fullperiods[identifier]={s:replay.previous.audit.statistics.period(rows,series,names,s,
            replay.previous.old.base.research.MULT[s]) for s in ('TOPIX','NK225')}
        description=f"入口は両市場の方向確認＋追跡新規。途中は{QUANTITY_NAMES[spec['quantity_id']]}。出口は{EXIT_NAMES[spec['exit_id']]}。早期返済後も元仮想運転の次の新規準備まで待つ。"
        methods.append(dict(id=identifier,name=identifier,group='同期統合・追加ナイト込み',description=description,rows=financial.display_rows(rows)))
    for spec in fixed['旧時間幅']:
        identifier=spec['id'];folder=HERE/'integration_followup/clock'
        summary=read(folder/'summaries'/(identifier+'.json'));rows=read(folder/'sessions'/(identifier+'.json.gz'))
        sensitivity[identifier]=summary;allcells+=pass_cells(identifier,summary,rows)
        methods.append(dict(id=identifier,name=identifier,group='同期統合・主時間幅の反証',
            description=f"主方向窓だけ{spec['main_scale']:g}倍、短期窓30秒は固定。他は中央統合と同じ。既知13場だけの感度比較。",rows=financial.display_rows(rows)))
    regions=[]
    for spec in fixed['追加ナイト']:
        identifier=spec['id'];ids={identifier,identifier+'__M080',identifier+'__M120'}
        values=[r for r in allcells if r['id'] in ids];assert len(values)==12
        regions.append(dict(id=identifier,全12セル合格=all(r['基礎合格'] for r in values),
            不合格セル=[r for r in values if not r['基礎合格']]))
    replay.save(HERE/'integrated_financial_methods.json',methods)
    replay.save(HERE/'integrated_assessment.json',dict(全合格=True,中央数=12,感度数=24,追加Night数=24,
        四セル群=allcells,主窓領域=regions,全14期間=fullperiods,新Night選抜に使用=False,
        単一口座独立会計数=12*28,図数=len(plots)))
    template=(HERE/'new_chart_template.html').read_text(encoding='utf-8')
    import json
    payload=json.dumps(plots,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</',r'<\/')
    template=template.replace('9月29日ナイト・５分足と売買','統合版・9月29日ナイトの売買')
    (financial.OUT/'統合版の５分足と売買.html').write_text(template.replace('@@PAYLOAD@@',payload),encoding='utf-8')
    print(json.dumps(dict(統合36条件完了=True,主窓領域合格=[r['id'] for r in regions if r['全12セル合格']],
        中央14合計={k:{s:v['net_yen'] for s,v in value.items()} for k,value in fullperiods.items()}),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
