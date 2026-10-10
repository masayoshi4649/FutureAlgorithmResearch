"""結果前に指定した4方式の全注文と1枚保有を、確定5分足へ重ねる。"""

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
OUT = ROOT/'アルゴリズム調査/00037_原本全行の板観測と対照比較'
METHODS = {'F00':'旧公開端点の数量と押し戻り弱化', 'F01':'原本全行・旧品質維持',
           'F02':'原本全行・P局所品質', 'F05':'数量不明も含む価格弱化だけ'}
METHOD_SOURCES = {'F00':'old','F01':'strict','F02':'local','F05':'old'}
PRIOR = HERE.parent/'wave_v40'
FACTORS = {'TOPIX':1000., 'NK225':10.}
REASONS = {0:'新規', 1:'損切り', 2:'利確', 3:'30分返済', 4:'場末返済'}


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


def records(ready: dict, ledger: dict, factor: float) -> dict:
    """機能: 全注文から現金・在庫・時価損益を復元し、図用記録を作る。

    引数: ready/ledger (dict)、factor (float) は1ポイントの円倍率。
    返り値: 注文・返済・数量・損益曲線の図示記録 (dict)。売買を再生しない。
    """
    orders = np.asarray(ledger['orders'], float).reshape((-1,7))
    trades = np.asarray(ledger['trades'], float).reshape((-1,10))
    n = len(ready['last']); times = ready['time_s']
    cash_delta = np.zeros(n); qty_delta = np.zeros(n); realized_delta = np.zeros(n)
    for row in orders:
        index = int(row[0]); assert index == row[0] and 0 <= index < n
        cash_delta[index] -= row[2]*row[3]*row[4]
        qty_delta[index] += row[2]*row[3]
    for trade in trades:
        realized_delta[int(trade[1])] += trade[6]
    cash = np.cumsum(cash_delta); quantity = np.cumsum(qty_delta)
    realized = np.cumsum(realized_delta); equity = cash+quantity*ready['last']
    peak = np.maximum.accumulate(np.r_[0.,equity])[1:]
    curve = np.column_stack((realized,equity,quantity,peak-equity))
    assert np.isin(quantity,[-1,0,1]).all() and quantity[-1] == 0
    np.testing.assert_allclose(cash[-1], trades[:,6].sum(), rtol=0, atol=1e-7)
    if '全結果指紋' in ledger:
        for name,value in (('orders',orders),('trades',trades),('curve',curve)):
            assert fingerprint(value) == ledger['全結果指紋'][name], name
    # ----------------------------------------
    # 全約定行は省略せず、5分時計の過去asof点と最終観測点も追加する。
    clocks = np.arange(ready['start'], times[-1]+300., 300.)
    clocks = clocks[clocks <= times[-1]]
    sample = np.searchsorted(times, clocks, side='right')-1
    indices = sorted(set([int(v) for v in sample if v >= 0]+[int(v) for v in orders[:,0]]+[n-1]))
    tracking = [[float(ready['start']),-1,0.,0.]]
    tracking += [[float(times[i]),i,float(quantity[i]),float(equity[i]*factor)] for i in indices]
    position = [[float(ready['start']),-1,0]]
    position += [[float(times[int(v[0])]),int(v[0]),int(quantity[int(v[0])])] for v in orders]
    position += [[float(times[-1]),n-1,0]]
    profits = trades[:,6]*factor
    return dict(orders=[[float(times[int(row[0])]),*row.tolist()] for row in orders],
        trades=[[float(times[int(row[0])]),float(times[int(row[1])]),*row.tolist()] for row in trades],
        tracking=tracking,position=position,factor=factor,
        totals=dict(net_yen=float(profits.sum()),profit_yen=float(profits[profits>0].sum()),
            loss_yen=float(-profits[profits<0].sum()),trades=len(trades),
            profit_units=int(np.sum(profits>0)),loss_units=int(np.sum(profits<0)),zero_units=int(np.sum(profits==0))))


def candles(path: Path, ready: dict) -> list:
    """機能: 読取専用の確定5分足を保存値のまま選ぶ。

    引数: path (Path)、ready (dict)。返り値: 時刻とOHLC (list[list[float]])。
    """
    result = []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            stamp = datetime.fromisoformat(row['time']).timestamp()
            if row['closed'].strip().lower() == 'true' and ready['start'] <= stamp <= ready['limit']:
                value = [stamp, *[float(row[name]) for name in ('open','high','low','close')]]
                assert np.isfinite(value).all()
                result.append(value)
    return result


def adopted_bands(ready: dict, ledger: dict, bands: list[dict], panels: list[dict], source: str) -> list[dict]:
    """機能: 約定した新規の判断行を、採用根拠と共通帯へ結び付ける。

    引数: ready/ledger (dict)、bands/panels (list[dict])、source (str:old/strict/local)。
    返り値: 約定済み帯の図示記録 (list[dict])。新uを旧uへ差し替えない。
    """
    selected = {int(value['decision']['ready_index']):value for value in ledger['入口根拠']['候補']}
    assert len(selected) == len(ledger['入口根拠']['候補'])
    by_id = {int(value['band_id']):value for value in bands}
    assert len(by_id) == len(bands)
    by_panel = {int(value['band_id']):value for value in panels}
    assert len(by_panel) == len(panels)
    assert source in ('old','strict','local') and ledger['入口根拠']['数量観測']==source
    result=[]
    for order in ledger['orders']:
        if not int(order[6]):continue
        entry_row,decision_row=int(order[0]),int(order[1])
        candidate=selected[decision_row];band=by_id[int(candidate['band_id'])]
        assert candidate['direction']==order[2] and candidate['decision']==band['terminal']
        assert candidate['price']==band['price'] and candidate['feature_source']==source
        features=band['features'];ratio_evidence=None
        if source!='old':
            panel=by_panel[int(band['band_id'])]
            for name in ('band_id','direction','price','atr','tick','created','terminal'):
                assert panel[name]==band[name],name
            features=panel['features_'+source]
            assert features['available_seq']<band['terminal']['seq']
            ratio_evidence=[]
            assert len(panel['trials'])==len(band['trials'])==2
            for number,(new_trial,old_trial) in enumerate(zip(panel['trials'],band['trials']),1):
                assert new_trial['number']==old_trial['number']==number
                assert new_trial['start']==old_trial['start'] and new_trial['end']==old_trial['end']
                assert old_trial['complete'] and new_trial['complete_available']
                publication=new_trial['publications'][-1]
                assert publication['release_seq']==new_trial['ratio_available_seq']==old_trial['end']['seq']
                assert publication['material_last_seq']<=publication['release_seq']<band['terminal']['seq']
                assert features['u'+str(number)]==new_trial['u_'+source]==publication['u_'+source]
                ratio_evidence.append(dict(number=number,ratio_available_seq=new_trial['ratio_available_seq'],publication=publication))
        assert candidate['features']==features and candidate['ratio_evidence']==ratio_evidence
        assert decision_row<entry_row and ready['seq'][decision_row]==band['terminal']['seq']
        assert ready['time_s'][decision_row]==band['terminal']['time_s']
        trials=[]
        for number in (1,2):
            trial=next((t for t in band['trials'] if t['number']==number),None)
            complete=trial is not None and trial['complete'] and trial['end']['ready_index']<=decision_row
            trials.append(dict(number=number,complete=bool(complete),
                start=trial['start'] if trial is not None else None,
                end=trial['end'] if complete else None))
        result.append(dict(band_id=int(band['band_id']),price=float(band['price']),
            band_direction=int(band['direction']),direction=int(candidate['direction']),
            created=band['created'],decision=band['terminal'],trials=trials,
            entry_time=float(ready['time_s'][entry_row]),entry_row=entry_row,
            atr=float(band['atr']),features=features,feature_source=source,
            old_features=band['features'],ratio_evidence=ratio_evidence,peer=candidate['peer']))
    return result


def synthetic() -> dict:
    """機能: 同時刻行・指定価格返済・空台帳の図示会計を人工確認する。

    引数: なし。返り値: 成功証拠 (dict)。
    """
    ready = dict(start=0.,limit=150.,time_s=np.array([0.,60.,60.,120.,180.]),
        last=np.array([100.,101.,102.,104.,103.]))
    ledger = dict(orders=[[1,0,1,1,101,0,1],[3,1,-1,1,103,2,0]],
        trades=[[1,3,1,101,103,1,2,2,0,1]])
    output = records(ready,ledger,1000.)
    assert output['totals']['net_yen'] == 2000 and output['position'][1:3] == [[60.,1,1],[120.,3,0]]
    assert output['tracking'][-1][-1] == 2000 and output['trades'][0][9] == 2
    empty = records(ready,dict(orders=[],trades=[]),10.)
    assert empty['totals']['trades'] == 0 and empty['totals']['net_yen'] == 0
    assert all(row[2] == row[3] == 0 for row in empty['tracking'])
    created=dict(event_index=0,ready_index=0,seq=10,time_s=0.)
    decision=dict(reason='early_breakout',event_index=1,ready_index=1,seq=11,time_s=60.)
    trial=dict(number=1,start=created,end=decision,complete=False)
    features=dict(two_trials_complete=False,u1=None,u2=None,b1=None,b2=None)
    band=dict(band_id=7,price=101.,direction=1,created=created,terminal=decision,
        trials=[trial],atr=1.,features=features)
    cause=dict(band_id=7,price=101.,direction=1,decision=decision,features=features,peer=None,
        feature_source='old',ratio_evidence=None)
    sample=dict(orders=[[2,1,1,1,102,0,1]],入口根拠={'候補':[cause],'数量観測':'old'})
    observed=adopted_bands({**ready,'seq':np.arange(10,15)},sample,[band],[],'old')
    assert len(observed)==1 and all(not t['complete'] and t['end'] is None for t in observed[0]['trials'])
    assert observed[0]['entry_row']==2 and observed[0]['decision']['ready_index']==1
    rejected=0
    for field in ['direction','price']:
        altered={**cause,field:999}
        try:adopted_bands({**ready,'seq':np.arange(10,15)},dict(orders=sample['orders'],入口根拠={'候補':[altered],'数量観測':'old'}),[band],[],'old')
        except AssertionError:rejected+=1
    assert rejected==2
    # ----------------------------------------
    # 旧uと異なる新uを二種類渡し、正しい出典だけを表示することを確認する。
    ending=dict(reason='breakout',event_index=3,ready_index=3,seq=13,time_s=120.)
    old_features=dict(two_trials_complete=True,u1=5.,u2=4.,b1=.2,b2=.1)
    old_band=dict(band_id=8,price=101.,direction=1,created=created,terminal=ending,
        trials=[dict(number=1,start=created,end=created,complete=True),
                dict(number=2,start=created,end={**decision,'reason':'completed'},complete=True)],
        atr=1.,tick=1.,features=old_features)
    panel={k:deepcopy(old_band[k]) for k in ('band_id','direction','price','atr','tick','created','terminal')}
    panel['features_strict']={**old_features,'u1':2.,'u2':1.,'available_seq':11}
    panel['features_local']={**old_features,'u1':3.,'u2':.5,'available_seq':11}
    panel['trials']=[]
    for trial in old_band['trials']:
        number=trial['number'];end=trial['end']
        publication=dict(release_seq=end['seq'],material_last_seq=end['seq'],
            u_strict=panel['features_strict']['u'+str(number)],u_local=panel['features_local']['u'+str(number)])
        panel['trials'].append(dict(number=number,start=trial['start'],end=end,complete_available=True,
            ratio_available_seq=end['seq'],publications=[publication],u_strict=publication['u_strict'],u_local=publication['u_local']))
    for source in ('strict','local'):
        evidence=[dict(number=t['number'],ratio_available_seq=t['ratio_available_seq'],publication=t['publications'][-1]) for t in panel['trials']]
        candidate=dict(band_id=8,price=101.,direction=1,decision=ending,features=panel['features_'+source],
            peer=None,feature_source=source,ratio_evidence=evidence)
        account=dict(orders=[[4,3,1,1,103,0,1]],入口根拠={'候補':[candidate],'数量観測':source})
        item=adopted_bands({**ready,'seq':np.arange(10,15)},account,[old_band],[panel],source)[0]
        assert item['features']!=item['old_features'] and item['features']==panel['features_'+source]
        assert item['feature_source']==source and item['old_features']==old_features
        bad=deepcopy(account);bad['入口根拠']['候補'][0]['features']=old_features
        try:adopted_bands({**ready,'seq':np.arange(10,15)},bad,[old_band],[panel],source)
        except AssertionError:rejected+=1
        else:raise AssertionError('旧uを新uとして表示しました')
    assert rejected==4
    return dict(全合格=True,同時刻の約定行を維持=True,指定価格返済の会計一致=True,
        空台帳を架空売買で埋めない=True,入口根拠と帯を接続=True,未完試行を完了扱いしない=True,
        根拠方向価格の破損2拒否=True,新旧uの誤接続2拒否=True,新旧u別表示=True,売買再生なし=True)


def prepare() -> dict:
    """機能: 掲載4方式・104画面と表示検算コードを固定する。

    引数: なし。返り値: 表示固定仕様 (dict)。売買成績による選別はしない。
    """
    proof = synthetic(); save(HERE/'chart_synthetic_audit.json',proof)
    paths = [HERE/name for name in ('chart_report.py','chart.js','chart_audit.py',
        'chart_synthetic_audit.json','chart_ui_synthetic.json','探索条件の固定.json',
        'trial_panel.pkl','trial_observation_audit.json')]
    paths += [PRIOR/'band_cache.pkl',PRIOR/'check_band_causality.json']
    value = dict(方式=METHODS,全図示数=104,学習専用セッション数=0,
        全注文と全返済を表示=True,保有枚数は1枚の符号付き在庫=True,
        帯表示='新規約定の判断行を採用根拠と帯IDへ接続。価格P・試行完了・突破を表示。',
        数量比率='F00/F05は旧公開端点、F01はfeatures_strict、F02はfeatures_local。旧値は参考の別欄。',
        時価損益標本='5分時計以前の最終原本行、全約定行、最終観測行。取引判断には使用しない。',
        SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in paths},人工=proof)
    path = HERE/'chart_fixed.json'
    if path.exists(): assert read(path) == value, '既存の図固定を上書きしない'
    else: save(path,value)
    return value


def html(payload: dict) -> str:
    """機能: 全データを内蔵した暗色の図ページを組み立てる。

    引数: payload (dict)。返り値: HTML (str)。外部通信は行わない。
    """
    template = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>５分足と売買・原本全行の板観測</title>
<style>:root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#09111c;color:#e6eef8}body{max-width:1280px;margin:auto;padding:22px 18px;line-height:1.7}a{color:#8cc9ff}h1{font-size:25px}select{font:inherit;background:#17273a;color:#edf5ff;border:1px solid #526e8c;padding:6px;max-width:100%}.controls{display:flex;gap:16px;flex-wrap:wrap}canvas{display:block;width:100%;height:640px;background:#0d1827;border:1px solid #29415b;border-radius:8px}.muted{color:#a3b7ce}.badge{color:#ffd68e;background:#49341b;padding:3px 9px;border-radius:5px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}th,td{padding:7px 9px;border-bottom:1px solid #2a3c51;text-align:right}th{background:#182a40;color:#b7cfe8}details{background:#111f30;margin:16px 0;padding:10px}summary{cursor:pointer}.gain{color:#69ddb2}.loss{color:#ff8a99}</style>
<body><a href="原本全行の板観測と対照比較.html">結果へ戻る</a><h1>５分足と売買</h1><p>買い▲・売り▼が新規、×が返済。紫の水平線は、実際の新規に使った帯価格です。</p>
<!--
[コンポーネント概要]
#method/#symbol/#session は事前指定4方式・2銘柄・13区間の全104画面を選択します。
#chart は確定5分足と全新規・全返済、1/-1保有と標本化時価損益です。
#chart-summary は円損益と約定済み帯・全候補の件数です。全13区間を評価します。
#order-table/#trade-table は省略しない全注文・全返済です。
#band-table は新規約定に対応する帯の生成、試行完了、突破の公開時点です。
外部通信・注文送信・未掲載方式への成績選択は行いません。
-->
<div class="controls"><label>方式 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">NK225マイクロ</option></select></label><label>セッション <select id="session"></select></label></div>
<p id="chart-summary"></p><canvas id="chart" aria-label="確定5分足、全売買、1枚の保有方向、時価損益"></canvas>
<p class="muted">各銘柄1枚。緑▲は買い新規、赤▼は売り新規。返済×は赤＝損切り、黄＝利確、青＝30分、灰＝場末。全13セッションは既知データです。</p>
<details><summary>図の読み方</summary><p>掲載はF00/F01/F02/F05の固定4方式です。全13セッションに学習除外はありません。成績による差替はしません。</p><p>帯価格Pの線は生成から突破まで。小さい丸1/2は試行の完了、紫の菱形は突破の判断です。新規約定に使わなかった候補や不採用帯は描きません。数量比率が不明の場合は数値を補わず、そのまま表示します。</p><p>F00は旧公開端点、F01は原本全行の数量変化と旧品質、F02は原本全行のP局所品質、F05は数量不明も含む価格弱化だけです。帯価格・試行・突破の時刻は旧帯と共通です。</p><p>数量帯は全約定時点の階段、時価損益は5分時計の過去asofと全約定点・最終観測の標本です。曲線の間の全原本変動までは描いていません。確定5分足全体を売買判断時点で知っていたという意味ではありません。</p><p>新規は観測価格。返済は指定価格、1r損切り・2r利確・30分・場末返済。rは判断時点の公開ATRと2呼値の大きい方を呼値へ切上げて固定。注文は判断の次原本行以降に有効、費用0です。表の使用uは各方式の数量観測値です。F01/F02では新しい原本集計を示し、旧公開端点uは参考の別欄です。可視外や減少0は不明のままで、数量変化を約定・取消・同一参加者の補充とは断定しません。</p></details>
<details><summary>約定に使った帯と判断時点</summary><div id="band-table"></div></details>
<details open><summary>全注文</summary><div id="order-table"></div></details><details><summary>全返済と損益</summary><div id="trade-table"></div></details>
<script type="application/json" id="chart-data">PAYLOAD</script><script>JAVASCRIPT</script></body></html>'''
    return template.replace('PAYLOAD',json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/'))\
        .replace('JAVASCRIPT',(HERE/'chart.js').read_text(encoding='utf-8'))


def main() -> None:
    """機能: 完備後に保存資料を独立復元し、正式104画面を生成する。

    引数: --prepare (bool)。返り値: なし (None)。正式生成は完備後だけ許す。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    args=parser.parse_args();fixed=prepare()
    if args.prepare: return
    specification=read(HERE/'探索条件の固定.json');specsha=digest(HERE/'探索条件の固定.json')
    complete=read(HERE/'主再生の完了.json')
    assert (complete['全条件数'],complete['全入力数'],complete['因果入力数'])==(260,6760,1040)
    assert complete['固定SHA256']==specsha
    proof=read(HERE/'完備監査.json')
    assert proof['検証完了'] and proof['固定SHA256']==specsha
    for path,sha in proof['参照資料SHA256'].items(): assert digest(ROOT/path)==sha,path
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    sessions=sorted({k[0] for k in inputs});assert len(sessions)==13 and len(inputs)==26
    payload=dict(methods=METHODS,sessions=sessions,training_sessions=[],candles={},records={},
        reason_names=REASONS,preview=False)
    cache=pickle.loads((PRIOR/'band_cache.pkl').read_bytes())
    panel=pickle.loads((HERE/'trial_panel.pkl').read_bytes())
    source_paths=[PRIOR/'band_cache.pkl',HERE/'trial_panel.pkl',HERE.parent/'wave_v23/inputs.pkl']
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in source_paths};checks=[]
    by_spec={s['id']:s for s in specification['主条件']}
    for key,ready in sorted(inputs.items()):
        path=ROOT/'candle_5min'/key[1]/(key[0]+'.csv')
        relative=path.relative_to(ROOT).as_posix();assert digest(path)==specification['原本78SHA256'][relative]
        sources[relative]=digest(path);payload['candles']['|'.join(key)]=candles(path,ready)
    for identifier in METHODS:
        source=METHOD_SOURCES[identifier]
        assert by_spec[identifier]['feature_source']==source
        ledger_path=HERE/'ledgers'/(identifier+'.json.gz');session_path=HERE/'sessions'/(identifier+'.json.gz')
        for path in (ledger_path,session_path):sources[path.relative_to(ROOT).as_posix()]=digest(path)
        ledgers={(r['session'],r['symbol']):r for r in read(ledger_path)}
        values={(r['session'],r['symbol']):r for r in read(session_path)}
        assert set(ledgers)==set(values)==set(inputs)
        for key,ready in sorted(inputs.items()):
            record=records(ready,ledgers[key],FACTORS[key[1]])
            for name,value in record['totals'].items():
                np.testing.assert_allclose(value,values[key][name],rtol=0,atol=1e-7,err_msg=name)
            record['training']=False
            cache_key=ledgers[key]['入口根拠']['母集団キー']
            record['bands']=adopted_bands(ready,ledgers[key],cache[cache_key][key],panel[cache_key][key],source)
            record['candidate_count']=len(ledgers[key]['入口根拠']['候補'])
            assert len(record['bands'])==sum(bool(order[6]) for order in ledgers[key]['orders'])
            payload['records'][identifier+'|'+'|'.join(key)]=record
            checks.append(dict(id=identifier,session=key[0],symbol=key[1],全注文会計一致=True,
                全保存曲線指紋一致=True,帯根拠一致=True,新旧数量比率出典一致=True,学習専用=False,
                orders=len(record['orders']),trades=len(record['trades']),bands=len(record['bands'])))
    assert len(payload['records'])==len(checks)==104
    for path,sha in sources.items():assert digest(ROOT/path)==sha,path
    OUT.mkdir(exist_ok=True);destination=OUT/'５分足と売買.html';destination.write_text(html(payload),encoding='utf-8')
    save(HERE/'chart_generation.json',dict(全合格=True,全図示数=104,暫定=False,結果=checks,
        固定SHA256=digest(HERE/'chart_fixed.json'),探索固定SHA256=specsha,
        HTML_SHA256=digest(destination),参照SHA256=sources,API取得数=0,現在保存物使用=False))
    print('固定4方式・104画面を保存台帳と照合して生成。',flush=True)


if __name__=='__main__':main()
