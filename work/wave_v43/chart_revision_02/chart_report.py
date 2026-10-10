"""結果前に指定した4方式の全注文と可変枚数保有を、確定5分足へ重ねる。"""

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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT/'アルゴリズム調査/00038_時間窓合議と入口の安定性'
C01 = 'B00_RB00_F25_N1'
METHODS = {
    'S100__A0__V000':'単一中央 × A0',
    'S100__'+C01+'__V000':'単一中央 × C01',
    'M2_100__A0__V000':'3窓多数決 × A0',
    'M2_100__'+C01+'__V000':'3窓多数決 × C01',
}
FACTORS = {'TOPIX':1000., 'NK225':10.}
REASONS = {1:'初期損失条件',2:'追跡返済',3:'カバー追跡返済',4:'カバー損切り',5:'判断撤回',
    6:'方向再開',7:'一部利確',8:'保有時間上限',9:'セッション内返済',10:'中立縮小',
    11:'利益保護',12:'米国帯縮小',13:'方向撤回',14:'場内損失予算',20:'組開始新規',
    30:'悪化による数量減量',31:'数量復元',32:'実組損失予算返済'}


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
    return dict(shape=list(value.shape), dtype=str(value.dtype), SHA256=hashlib.sha256(value.tobytes()).hexdigest())


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


def records(ready: dict, ledger: dict, members: list[np.ndarray], state: np.ndarray, signal: str) -> tuple[dict,np.ndarray]:
    """機能: 全売買、保有階段、円時価と3構成票・実使用方向を図用に保存する。

    引数: ready/ledger (dict)、members (list[ndarray])、state (ndarray)、signal (str)。
    返り値: 図用記録と全原本曲線 (tuple[dict,ndarray])。方向帯は注文や保有を意味しない。
    """
    curve,totals=reconstruct(ready,ledger)
    orders=np.asarray(ledger['orders'],float).reshape((-1,8));trades=np.asarray(ledger['trades'],float).reshape((-1,11))
    times=ready['time_s'];n=len(times);factor=ledger['config']['point_value']
    matrix=np.column_stack([*members,state]);assert matrix.shape==(n,4) and np.isin(matrix,[-1,0,1]).all()
    expected=members[1] if signal=='S100' else np.median(matrix[:,:3],axis=1).astype(np.int8)
    np.testing.assert_array_equal(state,expected)
    # ----------------------------------------
    # 全約定行を保持し、5分時計以前の最終観測点を損益の補助標本へ追加する。
    clocks=np.arange(ready['start'],times[-1]+300,300);clocks=clocks[clocks<=times[-1]]
    past=np.searchsorted(times,clocks,side='right')-1
    chosen=sorted(set([int(v) for v in past if v>=0]+[int(o[0]) for o in orders]+[n-1]))
    tracking=[[float(ready['start']),-1,0.,0.,0.]]
    tracking += [[float(times[i]),i,float(curve[i,2]),float(curve[i,3]),float(curve[i,0]*factor)] for i in chosen]
    position=[[float(ready['start']),-1,0.,0.]]
    position += [[float(times[int(o[0])]),int(o[0]),float(curve[int(o[0]),2]),float(curve[int(o[0]),3])] for o in orders]
    position.append([float(times[-1]),n-1,0.,0.])
    changed=np.flatnonzero(np.any(matrix[1:]!=matrix[:-1],axis=1))+1
    indices=sorted(set([0,*changed.tolist(),n-1]))
    votes=[[float(times[i]),i,*map(int,matrix[i])] for i in indices]
    rendered_trades=[[float(times[int(t[6])]),float(times[int(t[7])]),int(t[2]),int(t[3]),
        float(t[4]),float(t[5]),float(t[10]*factor),int(t[9]),int(t[6]),int(t[7]),int(t[0]),int(t[1])] for t in trades]
    return dict(orders=[[float(times[int(o[0])]),*o.tolist()] for o in orders],trades=rendered_trades,
        tracking=tracking,position=position,votes=votes,totals=totals,signal=signal,factor=factor),curve


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


def synthetic() -> dict:
    """機能: 5枚開始・減量・復元・部分返済・全返済を注文列から人工検算する。

    引数: なし。返り値: 手計算・同時刻・投票表示の証跡 (dict)。
    """
    ready=dict(start=0.,limit=500.,time_s=np.array([0.,60.,60.,120.,180.,240.,300.]),
        last=np.array([100.,100.,99.,101.,104.,103.,103.]))
    orders=[[1,0,0,1,5,100,20,1],[2,1,0,-1,1,99,30,0],[3,2,0,1,1,101,31,1],
        [4,3,0,-1,2,104,7,0],[5,4,0,-1,2,103,2,0],[5,4,0,-1,1,103,2,0]]
    trades=[[0,0,1,1,100,99,1,2,0,30,-1],[0,0,1,2,100,104,1,4,0,7,8],
        [0,0,1,2,100,103,1,5,0,2,6],[0,1,1,1,101,103,3,5,0,2,2]]
    ledger=dict(orders=orders,trades=trades,config=dict(point_value=1000.,audit_cap=10))
    members=[np.array([0,1,1,1,0,-1,0],np.int8),np.array([0,0,1,1,0,-1,0],np.int8),np.array([0,0,0,1,0,-1,0],np.int8)]
    expected=np.median(np.column_stack(members),axis=1).astype(np.int8)
    value,curve=records(ready,ledger,members,expected,'M2_100')
    np.testing.assert_array_equal(curve[:,2],[0,5,4,5,3,0,0])
    np.testing.assert_array_equal(curve[:,0],[0,0,-5,3,18,15,15])
    assert value['totals']==dict(net_yen=15000.,gross_profit_yen=16000.,gross_loss_yen=1000.,
        profit_units=5,loss_units=1,zero_units=0,closed_units=6)
    assert value['position'][1][0]==value['position'][2][0]==60. and value['position'][1][1]!=value['position'][2][1]
    assert value['orders'][2][7]==31 and value['votes'][1][1]==1
    single,_=records(ready,ledger,members,members[1],'S100');assert single['signal']=='S100'
    empty=dict(orders=[],trades=[],config=ledger['config'])
    empty_value,_=records(ready,empty,members,expected,'M2_100');assert empty_value['totals']['net_yen']==0
    bad=deepcopy(ledger);bad['trades'][0][3]=2
    try:reconstruct(ready,bad)
    except AssertionError:pass
    else:raise AssertionError('返済数量改変を拒否しない')
    return dict(全合格=True,注文8列返済11列=True,減量復元部分返済の手計算一致=True,
        同秒でも別原本行維持=True,構成3票と使用方向を分離=True,中央単一は中央票だけ=True,
        無取引を架空約定にしない=True,数量改変拒否=True,新売買再生=False)


def html(payload: dict) -> str:
    """機能: 固定4方式を切り替える暗色の売買図を作る。

    引数: payload (dict)。返り値: 内蔵データだけのHTML (str)。
    """
    body='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>時間窓合議・５分足と売買</title>
<style>:root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#09111c;color:#e6eef8}body{max-width:1280px;margin:auto;padding:22px 18px;line-height:1.7}a{color:#8cc9ff}h1{font-size:25px}select{font:inherit;background:#17273a;color:#edf5ff;border:1px solid #526e8c;padding:6px;max-width:100%}.controls{display:flex;gap:16px;flex-wrap:wrap}canvas{display:block;width:100%;height:790px;background:#0d1827;border:1px solid #29415b;border-radius:8px}.muted{color:#a3b7ce}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}th,td{padding:7px 9px;border-bottom:1px solid #2a3c51;text-align:right}th{background:#182a40;color:#b7cfe8}details{background:#111f30;margin:16px 0;padding:10px}summary{cursor:pointer}.gain{color:#69ddb2}.loss{color:#ff8a99}</style>
<body><a href="時間窓合議と入口の安定性.html">結果へ戻る</a><h1>５分足と売買</h1><p>初回▲▼、減量□、復元◇、返済×。3窓の票と使用入口を別の帯で示します。</p>
<!--
[コンポーネント概要]
#method/#symbol/#session は固定4方式・2銘柄・13場の104画面を選びます。
#chart は全注文・5分足、構成3票と使用入口、保有数量と円時価です。
#order-table/#trade-table は全ての約定と返済です。
投票帯は売買許可方向であり、実際の保有や注文の発火を表すものではありません。
-->
<div class="controls"><label>方式 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div>
<p id="chart-summary"></p><p id="method-description" class="muted"></p><canvas id="chart" aria-label="確定5分足と全売買、3窓の票と使用入口、保有枚数と円時価"></canvas>
<p class="muted">票：緑＝買い・赤＝売り・灰＝中立。使用入口は明るい別配色。保有：買いは正、売りは負。</p>
<details><summary>読み方と条件</summary><p>単一S100は中央1.0倍の票だけを使い、0.8／1.2は参考表示です。M2_100は3票の同方向2票以上を使います。反対1票を許し、中立票を除外しません。入口方向の変化を新しい返済条件にはしていません。</p><p>A0は元の注文管理、C01はB00悪化で残存枠25%を1回減量し、新しいB00肯定で復元する既定方式です。初回TOPIX5枚／NK22510枚、上限10／20枚。費用0、指定価格約定、場内返済です。</p><p>橙□は数量減量、水色◇は復元新規、黄×は元返済、赤×は組損失予算の返済です。全約定は省略せず表へ載せています。時価曲線は5分時計以前の最終行・全約定行・最終観測点の標本です。投票の変更は全て残し、同秒の複数原本行は時間幅0になるため正確な順序は原本行番号で確認します。</p><p>4方式は結果前の固定対象で、全13場は既知データです。確定5分足全体を判断時点で知っていたという意味ではありません。構成票は同じ価格系列であり、独立した3予測ではありません。</p></details>
<details open><summary>全注文</summary><div id="order-table"></div></details><details><summary>全返済と損益</summary><div id="trade-table"></div></details>
<script type="application/json" id="chart-data">PAYLOAD</script><script>JAVASCRIPT</script></body></html>'''
    return body.replace('PAYLOAD',json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</',r'<\/')).replace('JAVASCRIPT',(HERE/'chart.js').read_text(encoding='utf-8'))


def prepare() -> dict:
    """機能: 4固定方式と図コード・人工検査の内容指紋を保存する。

    引数: なし。返り値: 表示規則 (dict)。新損益の読取はない。
    """
    proof=synthetic();save(HERE/'chart_synthetic.json',proof)
    paths=[HERE/name for name in ('chart_report.py','chart.js','chart_audit.py','chart_synthetic.json','chart_ui_synthetic.json','signals_fixed.json','completion_guard.py','追加完備の固定.json')]
    value=dict(方式=METHODS,全図示数=104,学習除外なし=True,注文列数=8,返済列数=11,
        全約定を表示=True,構成票=[.8,1.,1.2],単一は中央票のみ=True,合議は同方向2票以上=True,
        票と使用入口と保有を別表示=True,API取得数=0,新売買再生=False,人工=proof,
        SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in paths})
    path=HERE/'chart_fixed.json'
    if path.exists():assert read(path)==value,'固定済み図仕様の変更'
    else:save(path,value)
    return value


def main() -> None:
    """機能: 全体完備後だけ、保存台帳と原本を読んで104画面を正式生成する。

    引数: --prepare (bool)。返り値: なし (None)。売買の再計算はしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
    prepare()
    if args.prepare:return
    complete=read(HERE/'完備監査.json');fixed=read(HERE/'探索条件の固定.json');fixed_sha=digest(HERE/'探索条件の固定.json')
    assert complete['全合格'] and (complete['全条件数'],complete['全入力数'],complete['因果入力数'])==(32,832,128)
    assert complete['探索固定SHA256']==fixed_sha
    additional=read(HERE/'追加完備監査.json')
    assert additional['全合格'] and additional['追加完備完了']
    assert (additional['全条件数'],additional['全入力数'],additional['全指定波数'])==(32,832,256)
    assert additional['元完備SHA256']==digest(HERE/'完備監査.json')
    assert additional['追加固定SHA256']==digest(HERE/'追加完備の固定.json')
    for path,value in additional['参照資料SHA256'].items():assert digest(ROOT/path)==value,path
    for mapping in ('参照資料SHA256','出力SHA256'):
        for path,value in complete[mapping].items():assert digest(ROOT/path)==value,path
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes());assert len(inputs)==26
    members={};entries={};paths=[HERE.parent/'wave_v23/inputs.pkl']
    for folder,names,target in (('members',('C080','C100','C120'),members),('entries',('S100','M2_100'),entries)):
        for name in names:
            path=HERE/folder/(name+'.npz');paths.append(path)
            with np.load(path) as data:target[name]={tuple(key.split('|')):data[key] for key in data.files}
            assert set(target[name])==set(inputs)
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in paths}
    payload=dict(methods=METHODS,sessions=sorted({k[0] for k in inputs}),candles={},records={},reason_names=REASONS,preview=False)
    for key,ready in sorted(inputs.items()):
        path=ROOT/'candle_5min'/key[1]/(key[0]+'.csv');relative=path.relative_to(ROOT).as_posix()
        assert digest(path)==fixed['参照資料SHA256'][relative]
        sources[relative]=digest(path);payload['candles']['|'.join(key)]=candles(path,ready)
    checks=[]
    for identifier in METHODS:
        signal=identifier.split('__')[0]
        stored={}
        for folder in ('ledgers','sessions','audits'):
            path=HERE/folder/(identifier+'.json.gz');values=read(path)
            stored[folder]={(v['session'],v['symbol']):v for v in values}
            assert len(values)==26 and set(stored[folder])==set(inputs)
            sources[path.relative_to(ROOT).as_posix()]=digest(path)
        for key,ready in sorted(inputs.items()):
            value,curve=records(ready,stored['ledgers'][key],[members[c][key] for c in ('C080','C100','C120')],entries[signal][key],signal)
            for name,number in value['totals'].items():np.testing.assert_allclose(number,stored['sessions'][key][name],rtol=0,atol=1e-6,err_msg=name)
            assert hashlib.sha256(np.ascontiguousarray(curve[:,0]).tobytes()).hexdigest()==stored['audits'][key]['時価SHA256']
            payload['records'][identifier+'|'+'|'.join(key)]=value
            checks.append(dict(id=identifier,session=key[0],symbol=key[1],全合格=True,orders=len(value['orders']),
                trades=len(value['trades']),全原本曲線指紋一致=True,全金額枚数一致=True,票と使用方向一致=True))
    assert len(checks)==104
    for path,value in sources.items():assert digest(ROOT/path)==value,path
    OUT.mkdir(exist_ok=True);page=OUT/'５分足と売買.html';page.write_text(html(payload),encoding='utf-8')
    save(HERE/'chart_generation.json',dict(全合格=True,全図示数=104,結果=checks,参照SHA256=sources,
        固定SHA256=digest(HERE/'chart_fixed.json'),探索固定SHA256=fixed_sha,HTML_SHA256=digest(page),新売買再生=False,API取得数=0))
    print('104図の全原本曲線・売買・票を照合して生成。',flush=True)


if __name__=='__main__':main()


