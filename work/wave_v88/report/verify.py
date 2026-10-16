"""22配分の保存会計と全表示を、通信遮断した実ブラウザで照合する。"""
from pathlib import Path
import hashlib
import importlib.util
import json
from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00084_異なる戦略への配分と同時運転'
MAIN=OUT/'異なる3手法の配分と全セッション損益.html'


def read(path):
    """
    機能: 保存済みのJSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def check(result,fixed):
    """
    機能: 元の場会計を独立集約し、表示に使う期間会計を確認する。
    引数: result/fixed(dict)。
    返り値: None。
    """
    assert len(result['rows'])==60
    for row in result['rows']:
        assert abs(row['profit']-row['loss']-row['net'])<1e-6
        assert abs(row['gross']-row['fees']-row['net'])<1e-6
        assert row['new_lots']==row['closed_lots']
        cap=10 if row['symbol']=='TOPIX' else 20
        assert row['max_long']<=cap and row['max_short']<=cap
    for p in ('前16','後14','全30'):
        for symbol in ('TOPIX','NK225'):
            rows=[r for r in result['rows'] if r['symbol']==symbol and r['session'] in fixed[p]]
            a=result['periods'][p][symbol]
            for f in ('profit','loss','net','gross','fees','campaigns','wins','losses','new_lots','closed_lots'):
                assert abs(a[f]-sum(r[f] for r in rows))<1e-6,(p,symbol,f)
            assert a['positive_sessions']==sum(r['net']>0 for r in rows)
            assert a['no_trade_sessions']==sum(r['campaigns']==0 for r in rows)
            expected=a['profit']/(a['profit']+a['loss']) if a['profit']+a['loss'] else None
            assert a['profit_share']==expected


def main():
    """
    機能: 表示全切替・広狭描画を検査し、最終公開指紋と画像を保存する。
    引数: なし。
    返り値: None。取引コード・数値結果・公開HTMLを変更しない。
    """
    digest=hashlib.sha256(MAIN.read_bytes()).hexdigest()
    source=MAIN.read_text(encoding='utf-8')
    soup=BeautifulSoup(source,'html.parser')
    data=json.loads(soup.select_one('#report-data').string)
    fixed=read(WORK/'事前固定.json');analysis=read(WORK/'analysis/比較結果.json')
    assert data['selected']==analysis.get('selected') and data['primary']=='A0622'
    assert len(data['results'])==22 and data['sessions']==fixed['全30']
    for identifier,result in data['results'].items():
        assert result==read(WORK/'results'/f'{identifier}.json')
        check(result,fixed)
        for period in ('前16','後14','全30'):
            for symbol in ('TOPIX','NK225'):
                parts=data['source_contributions'][identifier][period][symbol]
                for field in ('profit','loss','net','campaigns'):
                    assert abs(sum(p[field] for p in parts.values())-result['periods'][period][symbol][field])<1e-6
    for identifier,periods in data['risk_attribution'].items():
        for period,products in periods.items():
            for symbol,value in products.items():
                assert value['portfolio']==data['results'][identifier]['periods'][period][symbol]
                assert abs(value['net_change']-(value['portfolio']['net']-value['allocated_gu_only']['net']))<1e-6
                assert abs(value['drawdown_change']-(value['portfolio']['max_drawdown']-value['allocated_gu_only']['max_drawdown']))<1e-6
    assert data['diagnosis']==analysis['diagnosis']
    for symbol,rows in data['diagnosis'][data['primary']].items():
        assert len(rows)==3
        for row in rows:
            original=next(r for r in data['results'][data['primary']]['rows'] if r['symbol']==symbol and r['session']==row['session'])
            assert row['net']==original['net']==sum(s['net'] for s in row['sources'].values())
            for name,value in row['sources'].items():
                assert value['net']==original['source_totals'][name]['net']
    spec=importlib.util.spec_from_file_location('隔離描画88',ROOT/'work/wave_v52/review/verify_report.py')
    renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)
    renderer.OUT=OUT;renderer.VISUAL=HERE/'visual'
    renderer.PROBE='<script>'+(HERE/'probe.js').read_text(encoding='utf-8')+'</script>'
    csp='<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:">'
    errors='<script>window.browserErrors=[];window.addEventListener("error",e=>browserErrors.push(e.message));window.addEventListener("unhandledrejection",e=>browserErrors.push(String(e.reason)));</script>'
    source=source.replace('<head>','<head>'+csp+errors)
    views=[(source,'主全体広幅',1450,1550,''),(source,'主全体狭幅',520,1650,''),
        (source,'全30損益',1450,2450,'<script>document.querySelector("main").replaceChildren(document.getElementById("sessions"));window.scrollTo(0,0);</script>'),
        (source,'期間と費用',1450,2000,'<script>const p=document.getElementById("period-detail"),r=document.getElementById("risk-detail"),d=document.getElementById("diversity-detail");p.open=r.open=d.open=true;document.querySelector("main").replaceChildren(p,r,d);window.scrollTo(0,0);</script>'),
        (source,'赤字場の源別収支',1450,1050,'<script>const p=document.getElementById("failure-detail");p.open=true;document.querySelector("main").replaceChildren(p);window.scrollTo(0,0);</script>')]
    outputs=[]
    for view in views:
        proof=renderer.render(*view);outputs.append(proof);print(json.dumps(proof,ensure_ascii=False),flush=True)
    assert digest==hashlib.sha256(MAIN.read_bytes()).hexdigest()
    result=dict(全合格=True,目視確認=False,保存結果一致数=22,保存会計口座数=1320,HTML_SHA256=digest,
        通信遮断='CSP接続禁止と到達不能proxy。データ取得・注文なし。',画面=outputs)
    (HERE/'表示の独立検査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
