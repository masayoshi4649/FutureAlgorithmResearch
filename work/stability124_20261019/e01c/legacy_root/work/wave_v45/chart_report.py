"""固定四方式の元影到達と実売買を、完備後だけ五分足へ表示する。"""
from __future__ import annotations
import argparse
from copy import deepcopy
import csv
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00040_50パーセント減量版の反証'
METHODS={'A0__V000':'元の価格管理 A0','G000_F25_N1__V000':'開始制限なし C01',
         'G150_F25_N1__V000':'順行後に25%減量（前回主案）','G150_F50_N1__V000':'順行後に50%減量（今回主案）'}
GATED_METHODS=frozenset(('G150_F25_N1__V000','G150_F50_N1__V000'))
FACTORS={'TOPIX':1000.,'NK225':10.}
REASONS={1:'初期損失条件',2:'追跡返済',7:'一部利確',8:'保有時間上限',9:'セッション内返済',11:'利益保護',20:'組開始新規',30:'悪化による数量減量',31:'数量復元',32:'実組損失予算返済'}


def digest(path: Path) -> str:
    """機能: 保存資料の内容指紋を作る。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1048576): value.update(block)
    return value.hexdigest()


def read(path: Path) -> object:
    """機能: JSON又はgzip JSONを読み出す。

    引数: path (Path)。返り値: 保存内容 (object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path: Path, value: object) -> None:
    """機能: 有限のJSON証拠を保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')


def fingerprint(value: np.ndarray) -> dict:
    """機能: 主保存と同じ形・型・全配列指紋を作る。

    引数: value (ndarray)。返り値: 指紋辞書 (dict)。
    """
    return dict(shape=list(value.shape), dtype=value.dtype.str, SHA256=hashlib.sha256(value.tobytes()).hexdigest())


def reconstruct(ready: dict, ledger: dict) -> tuple[np.ndarray,dict]:
    """機能: 8列注文と11列返済から全原本行の現金・在庫・損益を復元する。

    引数: ready/ledger (dict)。返り値: 8列曲線と金額枚数集計 (tuple[ndarray,dict])。
    1枚エンジンの列配置を使わず、復元新規と部分返済も元脚へ対応させる。
    """
    orders=np.asarray(ledger['orders'],float).reshape((-1,8))
    trades=np.asarray(ledger['trades'],float).reshape((-1,11))
    n=len(ready['last']);assert np.isfinite(ready['last']).all()
    changes=np.zeros((n,4));campaign=np.full(n,-1.,float)
    legs=[];cursor=0;last_order=-1
    for order in orders:
        row,source,group,side,qty,price,reason,opening=order
        assert all(v==int(v) for v in (row,source,group,side,qty,reason,opening))
        row,source,group,side,qty,reason,opening=map(int,(row,source,group,side,qty,reason,opening))
        assert 0<=source<row<n and row>=last_order and side in (-1,1) and qty>0 and opening in (0,1)
        last_order=row;changes[row,0]-=side*qty*price
        if opening:
            assert reason in (20,31)
            legs.append(dict(side=side,remaining=qty,price=price,row=row,group=group))
            changes[row,1 if side>0 else 2]+=qty
            if reason==20:campaign[row:]=group
        else:
            assert cursor<len(trades)
            trade=trades[cursor];cursor+=1;leg=legs[int(trade[1])]
            assert leg['remaining']>=qty and leg['side']==-side and leg['row']<row
            np.testing.assert_array_equal(trade[[0,2,3,4,5,6,7,9]],
                [group,-side,qty,leg['price'],price,leg['row'],row,reason])
            gain=-side*qty*(price-leg['price']);assert abs(gain-trade[10])<1e-7
            changes[row,3]+=gain;leg['remaining']-=qty
            changes[row,1 if side<0 else 2]-=qty
    assert cursor==len(trades) and all(leg['remaining']==0 for leg in legs)
    cash,longs,shorts,realized=np.cumsum(changes,axis=0).T
    net=longs-shorts;equity=cash+net*ready['last']
    high=np.maximum.accumulate(np.maximum(0.,equity));dd=np.maximum.accumulate(high-equity)
    curve=np.column_stack([equity,realized,longs,shorts,dd,cash,net,campaign])
    assert np.all(longs>=0) and np.all(shorts>=0) and longs[-1]==shorts[-1]==0
    assert np.all(longs<=ledger['config']['audit_cap']) and np.all(shorts<=ledger['config']['audit_cap'])
    for name,array in (('orders',orders),('trades',trades),('curve',curve)):
        if 'result_fingerprints' in ledger:assert fingerprint(array)==ledger['result_fingerprints'][name],name
    factor=ledger['config']['point_value'];pnls=(trades[:,5]-trades[:,4])*trades[:,2]*trades[:,3]*factor
    totals=dict(net_yen=float(pnls.sum()),gross_profit_yen=float(pnls[pnls>0].sum()),
        gross_loss_yen=float(-pnls[pnls<0].sum()),profit_units=int(trades[pnls>0,3].sum()),
        loss_units=int(trades[pnls<0,3].sum()),zero_units=int(trades[pnls==0,3].sum()),closed_units=int(trades[:,3].sum()))
    np.testing.assert_allclose(cash[-1]*factor,totals['net_yen'],rtol=0,atol=1e-6)
    return curve,totals


def candles(path: Path, ready: dict) -> list:
    """機能: 原本の確定5分足を数値のまま読み取る。

    引数: path (Path)、ready (dict)。返り値: 時刻/OHLC (list)。
    """
    output=[]
    with path.open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            stamp=datetime.fromisoformat(row['time']).timestamp()
            if row['closed'].strip().lower()=='true' and ready['start']<=stamp<=ready['limit']:
                value=[stamp,*[float(row[c]) for c in ('open','high','low','close')]]
                assert np.isfinite(value).all();output.append(value)
    return output


def records(ready: dict, ledger: dict, method: str) -> tuple[dict,np.ndarray]:
    """機能: 全注文・保有・円時価と、元影の基準価格・到達印を作る。

    引数: ready/ledger (dict)、method (str)。返り値: 図データと原本全行曲線 (tuple)。
    到達は減量約定と区別する。保存された到達行を別の売買時刻へ動かさない。
    """
    curve,totals=reconstruct(ready,ledger)
    orders=np.asarray(ledger['orders'],float).reshape((-1,8));trades=np.asarray(ledger['trades'],float).reshape((-1,11))
    times=ready['time_s'];n=len(times);factor=ledger['config']['point_value']
    clocks=np.arange(ready['start'],times[-1]+300,300);clocks=clocks[clocks<=times[-1]]
    past=np.searchsorted(times,clocks,side='right')-1
    chosen=sorted(set([int(v) for v in past if v>=0]+[int(o[0]) for o in orders]+[n-1]))
    tracking=[[float(ready['start']),-1,0.,0.,0.]]+[
        [float(times[i]),i,float(curve[i,2]),float(curve[i,3]),float(curve[i,0]*factor)] for i in chosen]
    position=[[float(ready['start']),-1,0.,0.]]+[
        [float(times[int(o[0])]),int(o[0]),float(curve[int(o[0]),2]),float(curve[int(o[0]),3])] for o in orders]
    position.append([float(times[-1]),n-1,0.,0.])
    groups={int(c[0]):c for c in ledger['shadow_cycles']}
    openings={int(o[2]):o for o in ledger['shadow_orders'] if o[6]==20 and o[7]==1}
    assert set(groups)==set(openings)
    levels=[]
    for group,cycle in sorted(groups.items()):
        start,end=int(cycle[1]),int(cycle[2]);opening=openings[group]
        assert opening[0]==start and opening[3]==cycle[8] and cycle[5]>0
        level=opening[5]+1.5*cycle[8]*cycle[5]
        levels.append([float(times[start]),float(times[end]),float(level),group,start,end,
                       int(cycle[8]),float(cycle[5]),float(opening[5])])
    arms=[]
    assert method in METHODS
    if method not in GATED_METHODS:assert ledger['arm_events']==[]
    seen=set()
    for event in ledger['arm_events']:
        group=int(event['campaign']);row=int(event['row']);cycle=groups[group];opening=openings[group]
        assert group not in seen;seen.add(group)
        assert int(cycle[1])<=row<int(cycle[2]) and event['time_s']==times[row]
        assert event['seq']==ready['seq'][row] and event['direction']==cycle[8]
        assert event['initial_atr']==cycle[5] and event['anchor']==opening[5]
        assert 1.5<=event['mfe_atr'] and event['original_source_row']<=row
        movement=cycle[8]*(ready['last'][int(cycle[1]):row+1]-opening[5])/cycle[5]
        hits=np.flatnonzero(np.isfinite(movement)&(movement>=1.5))
        assert len(hits) and int(cycle[1])+int(hits[0])==row
        arms.append([float(times[row]),row,group,float(ready['last'][row]),int(cycle[8]),
                     float(event['initial_atr']),float(event['anchor']),float(event['mfe_atr']),
                     int(event['original_source_row'])])
    rendered_trades=[[float(times[int(t[6])]),float(times[int(t[7])]),int(t[2]),int(t[3]),
        float(t[4]),float(t[5]),float(t[10]*factor),int(t[9]),int(t[6]),int(t[7]),int(t[0]),int(t[1])] for t in trades]
    return dict(orders=[[float(times[int(o[0])]),*o.tolist()] for o in orders],trades=rendered_trades,
        tracking=tracking,position=position,levels=levels,arms=arms,totals=totals,method=method,factor=factor),curve


def artificial_fixture(reduction: int = 1) -> tuple:
    """機能: 到達・減量・復元・部分利確を含む人工台帳を作る。

    引数: reduction(int) は人工の減量枚数1又は2。返り値: readyとledger (tuple)。
    実注文器も実損益資料も使わず、異なる数量の表示と会計を確認する。
    """
    ready=dict(start=0.,limit=500.,time_s=np.array([0.,60.,60.,120.,180.,240.,300.]),
               last=np.array([100.,100.,99.,101.,104.,103.,103.]),seq=np.arange(7)*3)
    assert reduction in (1,2)
    q=reduction;remaining=3-q
    orders=[[1,0,0,1,5,100,20,1],[2,1,0,-1,q,99,30,0],[3,2,0,1,q,101,31,1],
            [4,3,0,-1,2,104,7,0],[5,4,0,-1,remaining,103,2,0],[5,4,0,-1,q,103,2,0]]
    trades=[[0,0,1,q,100,99,1,2,0,30,-q],[0,0,1,2,100,104,1,4,0,7,8],
            [0,0,1,remaining,100,103,1,5,0,2,3*remaining],[0,1,1,q,101,103,3,5,0,2,2*q]]
    ledger=dict(orders=orders,trades=trades,config=dict(point_value=1000.,audit_cap=10),
                shadow_cycles=[[0,1,5,15,10,2,5,5,1,2]],shadow_orders=[orders[0]],arm_events=[])
    return ready,ledger


def synthetic() -> dict:
    """機能: 図の価格基準と減量・復元会計を人工値へ照合する。

    引数: なし。返り値: 人工の成功証拠 (dict)。人工売買はゲート規則の再生ではない。
    """
    ready,ledger=artificial_fixture()
    base,curve=records(ready,ledger,'G000_F25_N1__V000')
    np.testing.assert_array_equal(curve[:,0],[0,0,-5,3,18,15,15])
    assert base['totals']['net_yen']==15000 and base['levels'][0][2]==103 and not base['arms']
    ledger['arm_events']=[dict(row=4,seq=12,time_s=180.,campaign=0,direction=1,initial_atr=2.,anchor=100.,
                               extreme=104.,mfe_atr=2.,original_source_row=4,plan_source_row=4)]
    gated,_=records(ready,ledger,'G150_F25_N1__V000')
    assert gated['arms'][0][:4]==[180.,4,0,104.] and gated['levels']==base['levels']
    other_ready,other=artificial_fixture(2);other['arm_events']=deepcopy(ledger['arm_events'])
    doubled,other_curve=records(other_ready,other,'G150_F50_N1__V000')
    assert doubled['arms']==gated['arms'] and doubled['levels']==gated['levels']
    np.testing.assert_array_equal(other_curve[:,0],[0,0,-5,1,16,13,13])
    assert doubled['totals']['net_yen']==13000 and doubled['totals']['closed_units']==7
    broken=deepcopy(ledger);broken['arm_events'][0]['row']=3
    try:records(ready,broken,'G150_F25_N1__V000')
    except AssertionError:pass
    else:raise AssertionError('早い到達印を拒否できません')
    return dict(全合格=True,元影1_5初期ATR価格基準=True,到達印と売買を区別=True,
                到達前倒し拒否=True,減量復元部分返済一致=True,同秒原本行保持=True,
                二つの減量枚数を区別=True,同到達でも異なる金額枚数を表示=True,新売買再生=False)


def html(payload: dict) -> str:
    """機能: 内蔵台帳だけで切り替わる暗色の比較図を作る。

    引数: payload (dict)。返り値: HTML (str)。外部通信は含まない。
    """
    source='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>50パーセント減量版・５分足と売買</title>
<style>:root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#09111c;color:#e6eef8}body{max-width:1280px;margin:auto;padding:22px 18px;line-height:1.7}a{color:#8cc9ff}h1{font-size:25px}select{font:inherit;background:#17273a;color:#edf5ff;border:1px solid #526e8c;padding:6px;max-width:100%}.controls{display:flex;gap:16px;flex-wrap:wrap}canvas{display:block;width:100%;height:790px;background:#0d1827;border:1px solid #29415b;border-radius:8px}.muted{color:#a3b7ce}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}th,td{padding:7px 9px;border-bottom:1px solid #2a3c51;text-align:right}th{background:#182a40;color:#b7cfe8}details{background:#111f30;margin:16px 0;padding:10px}summary{cursor:pointer}.gain{color:#69ddb2}.loss{color:#ff8a99}</style>
<body><a href="50パーセント減量版の反証.html">結果へ戻る</a><h1>５分足と売買</h1><p>影で到達◆、初回▲▼、減量□、復元◇、返済×。破線は初回建値から1.5初期ATRの価格です。</p>
<!--
[コンポーネント概要]
#method/#symbol/#session は固定4方式・2銘柄・13場の104図を選択する。
#chart は原本5分足・全売買・元影の価格基準・実保有枚数と円時価を表示する。
#arm-table は許可の初回到達を示し、減量の発注・約定と区別する。
#order-table/#trade-table は全件の保存台帳を表示する。
-->
<div class="controls"><label>方式 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div>
<p id="chart-summary"></p><p id="method-description" class="muted"></p><canvas id="chart" aria-label="確定5分足と全売買、元影の順行基準、保有枚数と円時価"></canvas>
<p class="muted">紫◆は25%版・50%版の影が順行幅へ到達した時点。減量は、その後の新しい悪化公開と元の発注条件を満たしてからです。</p>
<details><summary>読み方と条件</summary><p>A0は元の価格管理。C01は新しいB00悪化で残存枠25%を1回減量し、新しい同方向B00で復元します。25%版・50%版は、価格が1.5初期ATR順行した後の別公開まで減量を待ちます。今回主案は減量割合を50%に固定します。</p><p>薄い破線は4方式共通の影の初回建値±1.5初期ATRを参考表示し、元影組の期間だけ描きます。A0/C01には到達ゲートがないので◆は描きません。25%版・50%版の◆も実減量・利益確保の保証ではありません。旧初期損切り・2ATR利確・3ATR追跡・組損失予算・期限は維持します。</p><p>初回TOPIX5枚／NK22510枚、上限10／20枚、費用0、指定価格約定、場内返済。円時価は5分時計以前の最終原本行と全約定点を標本にしています。同秒の別行は時間幅0になるので表の原本行で順序を確認できます。</p><p>固定した4方式の全13場は既知データです。今回主案の50%版は前回の探索副案から選んだ既知成績です。今回の反証中は差し替えていません。この4方式の中央は旧成果を同一条件で引き継ぎ、新しい独立標本とは数えません。初期ATR倍の価格幅と、部分利確後の組損益Rは同義ではありません。</p></details>
<details><summary>元影の1.5初期ATR到達</summary><div id="arm-table"></div></details><details open><summary>全注文</summary><div id="order-table"></div></details><details><summary>全返済と損益</summary><div id="trade-table"></div></details>
<script type="application/json" id="chart-data">PAYLOAD</script><script>JAVASCRIPT</script></body></html>'''
    return source.replace('PAYLOAD',json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</',r'<\/')).replace('JAVASCRIPT',(HERE/'chart.js').read_text(encoding='utf-8'))


def prepare() -> dict:
    """機能: 固定4方式と表示規則・人工だけを指紋で保存する。

    引数: なし。返り値: 図規則 (dict)。新しい実損益は読まない。
    """
    proof=synthetic();save(HERE/'chart_synthetic.json',proof)
    paths=[HERE/name for name in ('chart_report.py','chart.js','chart_audit.py','chart_synthetic.json','chart_ui_synthetic.json','chart_browser_audit.py','chart_visual_check.py')]
    value=dict(方式=METHODS,全図示数=104,注文列数=8,返済列数=11,共通参考線は1_5初期ATR=True,
               到達印は25及び50パーセント版の保存armだけ=True,全約定表示=True,人工=proof,API取得数=0,新売買再生=False,
               SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in paths})
    path=HERE/'chart_fixed.json'
    if path.exists():assert read(path)==value,'図規則固定後の変更'
    else:save(path,value)
    return value


def main() -> None:
    """機能: 全体完備の後だけ104図を保存資料から生成する。

    引数: --prepare (bool)。返り値: なし (None)。売買再生はしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
    prepare()
    if args.prepare:return
    complete=read(HERE/'完備監査.json');fixed=read(HERE/'探索条件の固定.json')
    assert complete['全合格'] and (complete['全条件数'],complete['全入力数'],complete['因果入力数'])==(153,3978,612)
    assert complete['既知引継条件数']==11 and complete['新規再生条件数']==142
    assert complete['旧成果六資料全バイト一致'] is True and complete['旧集計経済情報全一致'] is True
    assert set(METHODS)<=set(fixed['既知再利用'])
    assert complete['探索固定SHA256']==digest(HERE/'探索条件の固定.json')
    for group in ('参照資料SHA256','出力SHA256'):
        for name,value in complete[group].items():assert digest(ROOT/name)==value,name
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes());assert len(inputs)==26
    sources={(HERE/name).relative_to(ROOT).as_posix():digest(HERE/name)
             for name in ('完備監査.json','探索条件の固定.json','chart_fixed.json')}
    payload=dict(methods=METHODS,sessions=sorted({k[0] for k in inputs}),candles={},records={},reason_names=REASONS,preview=False)
    sources['work/wave_v23/inputs.pkl']=digest(HERE.parent/'wave_v23/inputs.pkl')
    for key,ready in sorted(inputs.items()):
        path=ROOT/'candle_5min'/key[1]/(key[0]+'.csv');relative=path.relative_to(ROOT).as_posix()
        assert digest(path)==fixed['参照資料SHA256'][relative]
        sources[relative]=digest(path);payload['candles']['|'.join(key)]=candles(path,ready)
    checks=[]
    for identifier in METHODS:
        stored={}
        for folder in ('ledgers','sessions','audits','gate_use'):
            path=HERE/folder/(identifier+('.json' if folder=='gate_use' else '.json.gz'));values=read(path)
            stored[folder]={(v['session'],v['symbol']):v for v in values}
            assert len(values)==26 and set(stored[folder])==set(inputs)
            sources[path.relative_to(ROOT).as_posix()]=digest(path)
        for key,ready in sorted(inputs.items()):
            ledger=stored['ledgers'][key]
            assert ledger['arm_events']==stored['gate_use'][key]['arm_events']
            value,curve=records(ready,ledger,identifier)
            for name,number in value['totals'].items():np.testing.assert_allclose(number,stored['sessions'][key][name],rtol=0,atol=1e-6)
            assert hashlib.sha256(np.ascontiguousarray(curve[:,0]).tobytes()).hexdigest()==stored['audits'][key]['時価SHA256']
            payload['records'][identifier+'|'+'|'.join(key)]=value
            checks.append(dict(id=identifier,session=key[0],symbol=key[1],全合格=True,全原本曲線指紋一致=True,
                               全金額枚数一致=True,到達根拠一致=True,到達数=len(value['arms'])))
    assert len(checks)==104
    for key in inputs:
        suffix='|'+'|'.join(key)
        reference=payload['records']['A0__V000'+suffix]['levels']
        assert all(payload['records'][method+suffix]['levels']==reference for method in METHODS)
        assert payload['records']['G150_F25_N1__V000'+suffix]['arms']==payload['records']['G150_F50_N1__V000'+suffix]['arms']
    for name,value in sources.items():assert digest(ROOT/name)==value,name
    OUT.mkdir(exist_ok=True);page=OUT/'５分足と売買.html';page.write_text(html(payload),encoding='utf-8')
    save(HERE/'chart_generation.json',dict(全合格=True,全図示数=104,結果=checks,参照SHA256=sources,
        固定SHA256=digest(HERE/'chart_fixed.json'),探索固定SHA256=digest(HERE/'探索条件の固定.json'),
        HTML_SHA256=digest(page),新売買再生=False,API取得数=0))
    print('全104図の原本曲線・売買・元影到達を照合して正式生成。',flush=True)


if __name__=='__main__':main()
