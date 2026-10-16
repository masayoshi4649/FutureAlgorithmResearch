"""G0の実保有中だけを原quoteで辿り、固定5閾値の記述統計を保存する。売買は作らない。"""

import argparse
from datetime import datetime, timedelta, timezone
from fractions import Fraction as F
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys

sys.dont_write_bytecode=True
import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
SYMBOLS=('TOPIX','NK225')
IDENT='G0_Q1_X1'
MULTIPLES=(.5,1.,1.5,2.,3.)
JST=timezone(timedelta(hours=9))
EPSILON=1e-5


def read(path: Path) -> object:
    """
    機能: 許可された保存資料を読取専用で読む。
    引数: path(Path)。
    返り値: object。JSON又はpickle。読込時に売買を実行しない。
    """
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix=='.pkl' else json.loads(stream.read().decode('utf-8'))


def digest(path: Path) -> str:
    """
    機能: 使用根拠の指紋を現在内容から算出する。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def module(name: str, path: Path) -> object:
    """
    機能: 既独立会計の純関数と保存入力だけを接続する。
    引数: name(str)、path(Path)。
    返り値: object。main及び新しい金融戦略は実行しない。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value
    spec.loader.exec_module(value)
    return value


def fee(symbol: str) -> int:
    """
    機能: 固定1枚の片道注文費用を独立に切り捨てる。
    引数: symbol(str)。
    返り値: int。TOPIXmini41円、NK225micro11円。
    """
    return math.floor(F('41.8') if symbol=='TOPIX' else F(11))


def text_time(value: float) -> str:
    """
    機能: 価格代理時計を日本時間表示へ写す。
    引数: value(float)。
    返り値: str。真受信時計の認定ではない。
    """
    return datetime.fromtimestamp(float(value),JST).isoformat() if value>=1e9 else f'人工時計{value:g}秒'


def normal_quotes(record: dict) -> np.ndarray:
    """
    機能: 旧本体と同じ正常自己BBOの定義を独立評価する。
    引数: record(dict)。
    返り値: ndarray[bool]。価格支持や未来方向でquoteを除かない。
    """
    bid,ask=np.asarray(record['bid']),np.asarray(record['ask'])
    return np.asarray(record['quote_valid'],bool)&np.isfinite(bid)&np.isfinite(ask)&(bid>0)&(ask>bid)


def confirm_reference(key: tuple, record: dict, reference: dict, initial_bp: float) -> tuple:
    """
    機能: セッション最初から既知の幅参照をraw prefixへ戻し固定Sを作る。
    引数: key(tuple[str,str])、record/reference(dict)、initial_bp(float)。
    返り値: tuple[float,dict]。Sと根拠。未来高安・後で現れた始値欄を使わない。
    """
    session,symbol=key;seq=int(reference['source_seq']);known=int(reference['known_from_i'])
    assert known==int(reference['source_ready_i'])==0 and reference['source_session']==session
    assert seq<=int(record['seq'][0]) and float(reference['source_time'])<=float(record['time_s'][0])
    path=ROOT/'book'/symbol/(session+'.jsonl');raw=None;line_count=0
    with path.open('rb') as stream:
        for index,line in enumerate(stream):
            line_count+=1
            if index==seq:
                raw=json.loads(line);break
    assert raw is not None
    stamp=datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()
    assert stamp==reference['source_time']
    kind=reference['kind']
    if kind=='feed_OpeningPrice_current_session':
        opening=datetime.fromisoformat(raw['OpeningPriceTime']).timestamp()
        assert record['start']<=opening<=record['time_s'][0]
        assert opening==reference['reference_time'] and float(raw['OpeningPrice'])==float(reference['value'])
        assert seq==int(record['seq'][0]) and not reference['fallback']
    else:
        assert kind=='observed_session_open_CurrentPrice' and reference['fallback']
        assert float(raw['CurrentPrice'])==float(reference['value']) and stamp==reference['reference_time']
        assert record['start']<=stamp<=record['time_s'][0]
    reference_price=F(str(reference['value']));tick=F(str(record['tick']))
    assert reference_price>0 and tick>0 and initial_bp>0
    quantum=max(2,math.ceil(reference_price*F(str(initial_bp))/10000/tick))
    width=float(quantum*tick)
    return width,dict(参照価格=float(reference_price),既知原行=known,参照原seq=seq,
        参照価格時計=text_time(stamp),参照種別=kind,幅bp=initial_bp,呼値=float(tick),初期幅S=width,
        raw先頭読取行数=line_count,幅の因果性='既知原行0の参照値と固定bp及び呼値から決定。後続quoteの高安は幅の算出へ使わない。')


def witness(record: dict, row: int | None, quote: float | None = None) -> dict | None:
    """
    機能: 到達原行の時計・原seq・清算quoteを保持する。
    引数: record(dict)、row(int|None)、quote(float|None)。
    返り値: dict|None。未到達を架空の到達へ補完しない。
    """
    if row is None: return None
    return dict(原行=row,原seq=int(record['seq'][row]),価格時計=text_time(record['time_s'][row]),
        価格時計秒=float(record['time_s'][row]),清算quote=quote)


def diagnose(record: dict, parent: dict, width: float) -> dict:
    """
    機能: 実初回fillから実出口までの正常清算quoteを方向別に辿る。
    引数: record/parent(dict)、width(float)は初回固定S。
    返り値: dict。固定5閾値の初到達順、最大順逆行と最終赤字の返却利益診断。
    """
    side=int(parent['side']);begin=int(parent['entry_row']);end=int(parent['exit_row'])
    assert side in (-1,1) and 0<=begin<=end<len(record['time_s']) and width>0
    assert parent['initial_quantity']==parent['final_quantity']==1 and parent['adding_orders']==0
    normal=normal_quotes(record);assert normal[begin] and normal[end]
    assert parent['entry_price']==record['ask' if side==1 else 'bid'][begin]
    assert parent['exit_price']==record['bid' if side==1 else 'ask'][end]
    assert parent['entry_time']==record['time_s'][begin] and parent['exit_time']==record['time_s'][end]
    indexes=np.arange(begin,end+1,dtype=np.int64)[normal[begin:end+1]]
    quotes=np.asarray(record['bid' if side==1 else 'ask'])[indexes]
    distance=side*(quotes-float(parent['entry_price']))
    assert len(indexes)>0 and np.isfinite(distance).all()
    adverse=np.flatnonzero(distance<=-width)
    stop=None if not len(adverse) else int(indexes[adverse[0]])
    limits={}
    for multiple in MULTIPLES:
        touched=np.flatnonzero(distance>=multiple*width)
        gain=None if not len(touched) else int(indexes[touched[0]])
        assert gain is None or stop is None or gain!=stop
        if gain is None and stop is None: order='両側未到達'
        elif gain is not None and (stop is None or gain<stop): order='利益側が先'
        else: order='損失側が先'
        quote=None if gain is None else float(record['bid' if side==1 else 'ask'][gain])
        limits[f'{multiple:g}S']=dict(幅=multiple*width,到達=gain is not None,
            利益初到達=witness(record,gain,quote),初回損失Sとの到達順=order,
            利益先=gain is not None and (stop is None or gain<stop),
            損失Sの後に利益到達=gain is not None and stop is not None and gain>stop)
    maximum_index=int(np.argmax(distance));minimum_index=int(np.argmin(distance))
    maximum_signed=float(distance[maximum_index]);minimum_signed=float(distance[minimum_index])
    multiplier=1000 if record['symbol']=='TOPIX' else 10
    cost=2*fee(record['symbol'])
    assert parent['fees']==cost
    assert parent['net']==side*(parent['exit_price']-parent['entry_price'])*multiplier-cost
    maximum_net=maximum_signed*multiplier-cost
    stop_quote=None if stop is None else float(record['bid' if side==1 else 'ask'][stop])
    return dict(**parent,初期幅S=width,実保有原行数=end-begin+1,正常清算原行数=len(indexes),
        除外quote原行数=end-begin+1-len(indexes),固定閾値=limits,初回損失S到達=witness(record,stop,stop_quote),
        最大順行=max(0.,maximum_signed),最大順行S=max(0.,maximum_signed)/width,
        最高清算の方向差=maximum_signed,最高清算の時刻=witness(record,int(indexes[maximum_index]),float(quotes[maximum_index])),
        最大逆行=max(0.,-minimum_signed),最大逆行S=max(0.,-minimum_signed)/width,
        最悪清算の時刻=witness(record,int(indexes[minimum_index]),float(quotes[minimum_index])),
        最高清算の費用後利益=maximum_net,一時費用後黒字=maximum_net>EPSILON,最終赤字=parent['net']< -EPSILON,
        最終赤字で一時黒字だった=parent['net']< -EPSILON and maximum_net>EPSILON,
        最終赤字で一度も清算黒字なし=parent['net']< -EPSILON and maximum_net<=EPSILON)


def fraction(count: int, total: int) -> float | None:
    """
    機能: 全親又は全赤字親を分母に到達割合を計算する。
    引数: count/total(int)。
    返り値: float|None。分母0を勝率100%へ変換しない。
    """
    return count/total if total else None


def summarize(rows: list[dict]) -> dict:
    """
    機能: 全親と全赤字親を残したまま固定5閾値を記述集計する。
    引数: rows(list[dict])は実親の診断。
    返り値: dict。到達割合を新戦略の勝率と呼ばない。
    """
    red=[row for row in rows if row['最終赤字']]
    thresholds={}
    for multiple in MULTIPLES:
        name=f'{multiple:g}S'
        reached=sum(row['固定閾値'][name]['到達'] for row in rows)
        first=sum(row['固定閾値'][name]['利益先'] for row in rows)
        red_reached=sum(row['固定閾値'][name]['到達'] for row in red)
        red_first=sum(row['固定閾値'][name]['利益先'] for row in red)
        loss_first=sum(row['固定閾値'][name]['初回損失Sとの到達順']=='損失側が先' for row in rows)
        neither=sum(row['固定閾値'][name]['初回損失Sとの到達順']=='両側未到達' for row in rows)
        assert first+loss_first+neither==len(rows)
        thresholds[name]=dict(全親数=len(rows),利益到達親数=reached,全親中の利益到達割合=fraction(reached,len(rows)),
            利益側先の親数=first,全親中の利益先割合=fraction(first,len(rows)),損失側先の親数=loss_first,両側未到達親数=neither,
            全赤字親数=len(red),赤字親中の利益到達親数=red_reached,赤字親中の利益到達割合=fraction(red_reached,len(red)),
            赤字親中の利益先親数=red_first,赤字親中の利益先割合=fraction(red_first,len(red)),
            赤字親中の損失S後の利益到達親数=sum(row['固定閾値'][name]['損失Sの後に利益到達'] for row in red))
    return dict(全親数=len(rows),最終黒字親数=sum(row['net']>EPSILON for row in rows),最終赤字親数=len(red),
        最終同値親数=sum(abs(row['net'])<=EPSILON for row in rows),
        一時費用後黒字親数=sum(row['一時費用後黒字'] for row in rows),
        赤字親中の一時費用後黒字親数=sum(row['最終赤字で一時黒字だった'] for row in rows),
        赤字親中の一度も清算黒字なし親数=sum(row['最終赤字で一度も清算黒字なし'] for row in rows),
        赤字親中の最大順行0_5S未満親数=sum(row['最大順行S']<.5 for row in red),
        赤字親中の損失Sが0_5Sより先の親数=sum(row['固定閾値']['0.5S']['初回損失Sとの到達順']=='損失側が先' for row in red),
        固定閾値=thresholds,
        最大順行S分布={str(q):float(np.quantile([row['最大順行S'] for row in rows],q)) for q in (0,.25,.5,.75,1)} if rows else {},
        赤字親最大順行S分布={str(q):float(np.quantile([row['最大順行S'] for row in red],q)) for q in (0,.25,.5,.75,1)} if red else {},
        最大逆行S分布={str(q):float(np.quantile([row['最大逆行S'] for row in rows],q)) for q in (0,.25,.5,.75,1)} if rows else {},
        注意='分母は未到達を含む全親又は全赤字親。無取引セッションは別に残し、勝ちに加えない。到達率は売買実行の勝率ではない。')


def artificial() -> None:
    """
    機能: 買売反射・初損失順・不正quote・未到達の純診断を人工で確認する。
    引数: なし。
    返り値: None。原板や金融戦略を実行しない。
    """
    checked=[]
    for symbol in SYMBOLS:
        for side in (-1,1):
            for label,distances,invalid in (('利益1Sの後に損失S',[-1.,6.,11.,-3.,-11.],None),
                ('損失Sの後に利益2S',[-1.,-11.,20.],None),('両側未到達',[-1.,2.,4.],None),
                ('不正quoteの1Sを除外',[-1.,6.,11.,-3.,-11.],2)):
                quote=100.+side*np.asarray(distances);n=len(quote)
                bid=quote if side==1 else quote-1.;ask=quote+1. if side==1 else quote
                record=dict(symbol=symbol,bid=bid,ask=ask,quote_valid=np.ones(n,bool),seq=np.arange(n),time_s=np.arange(n,dtype=float))
                if invalid is not None: record['quote_valid'][invalid]=False
                multiplier=1000 if symbol=='TOPIX' else 10
                parent=dict(side=side,initial_quantity=1,final_quantity=1,adding_orders=0,entry_row=0,exit_row=n-1,
                    entry_price=100.,exit_price=float(quote[-1]),entry_time=0.,exit_time=float(n-1),fees=2*fee(symbol),
                    net=float(distances[-1])*multiplier-2*fee(symbol))
                value=diagnose(record,parent,10.)
                if label=='利益1Sの後に損失S':
                    assert value['固定閾値']['1S']['利益先'] and not value['固定閾値']['1.5S']['到達']
                    assert value['最終赤字で一時黒字だった'] and value['最大順行S']==1.1 and value['最大逆行S']==1.1
                elif label=='損失Sの後に利益2S':
                    assert value['固定閾値']['2S']['損失Sの後に利益到達'] and not value['固定閾値']['2S']['利益先']
                    assert value['固定閾値']['2S']['初回損失Sとの到達順']=='損失側が先'
                elif label=='両側未到達':
                    assert value['固定閾値']['0.5S']['初回損失Sとの到達順']=='両側未到達'
                else:
                    assert not value['固定閾値']['1S']['到達'] and value['最大順行S']==.6 and value['除外quote原行数']==1
                checked.append(value)
    result=summarize(checked);assert result['全親数']==16 and result['最終赤字親数']==8
    for name in result['固定閾値']:
        values=result['固定閾値'][name]
        assert values['利益側先の親数']+values['損失側先の親数']+values['両側未到達親数']==16
    assert summarize([])['固定閾値']['1S']['全親中の利益到達割合'] is None
    proof=dict(全合格=True,人工件数=16,固定閾値数=5,空分母を勝ちにしない=True,
        scope='純診断の買売反射・初到達原行順・不正quote除外・未到達分母。人工を合法金融戦略の成績とは呼ばない。',
        新売買実行=0,正式損益読取=0,実原板読取=0,追加Night読取=0,現在API取得=0,実注文=0,
        SHA256={Path(__file__).relative_to(ROOT).as_posix():digest(Path(__file__))})
    (HERE/'固定1枚到達順の私有人工診断.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False),flush=True)


def main() -> None:
    """
    機能: 許可された元31の固定1枚を原quoteで診断して記述統計だけを保存する。
    引数: CLI --root-g0-diagnosis-authorized(bool) 又は --artificial(bool)。
    返り値: None。パラメータ探索・新金融strategy・追加Night・未来情報での判断は実行しない。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--root-g0-diagnosis-authorized',action='store_true');group.add_argument('--artificial',action='store_true')
    args=parser.parse_args()
    if args.artificial: artificial();return
    assert args.root_g0_diagnosis_authorized
    fixed=read(WORK/'事前固定.json');assert len(fixed['全31'])==31 and fixed['全31既知']
    config=next(value for value in fixed['条件'] if value['id']==IDENT)
    assert config['trend_growth_mode']==0 and config['trend_initial_quantity']==1
    assert config['trend_protection_mode']==0 and config['trend_hold_seconds']==1800.
    for relative,expected in fixed['SHA256'].items(): assert digest(ROOT/relative)==expected,relative
    paths=[Path(__file__),WORK/'事前固定.json',HERE/'selection.py',HERE/'原因を実注文と同入口で独立に比較する.py',WORK/'data.py']
    paths.extend(WORK/part/kind/(IDENT+suffix) for part in ('front','back') for kind,suffix in (('results','.json'),('ledgers','.pkl')))
    before={path.relative_to(ROOT).as_posix():digest(path) for path in paths}
    selection=module('102固定1枚診断の独立注文会計',HERE/'selection.py')
    cause=module('102固定1枚診断の実親読取だけ',HERE/'原因を実注文と同入口で独立に比較する.py')
    data=module('102固定1枚診断の既知保存入力',WORK/'data.py'); material=data.load_inputs()
    assert set(material['prices'])=={(session,symbol) for session in fixed['全31'] for symbol in SYMBOLS}
    ledger={};saved_rows={}
    for part,period in (('front','前16'),('back','後15')):
        current=read(WORK/part/'results'/(IDENT+'.json'));path=WORK/part/'ledgers'/(IDENT+'.pkl')
        assert current['config']==config and current['ledger_SHA256']==digest(path)
        loaded=read(path);assert set(loaded)=={(session,symbol) for session in fixed[period] for symbol in SYMBOLS}
        ledger.update(loaded);saved_rows.update({(row['session'],row['symbol']):row for row in current['rows']})
    diagnostic=[];references={};sessions=[]
    counts=dict(口座=0,実親=0,全赤字親=0,実保有原行=0,正常清算原行=0,固定閾値=5,幅原本照合=0)
    for key in sorted(ledger):
        session,symbol=key;record=material['prices'][key];stored=ledger[key]
        actual=selection.account(stored,symbol)
        for field in ('net','profit','loss','fees','campaigns','lots'):
            selection.close(saved_rows[key][field],actual[field],session+'/'+symbol+'/'+field)
        reference=material['metadata']['references']['|'.join(key)]['ref_open']
        width,origin=confirm_reference(key,record,reference,float(config['trend_initial_stop_bp']))
        references['|'.join(key)]=origin;counts['幅原本照合']+=1
        physical=cause.parents(stored,session,symbol)
        parent_positions={name:i for i,name in enumerate(stored['trend_parent_columns'])}
        saved_parents=stored['trend_parent_diagnostics']
        for parent in physical:
            pid=parent['parent_id'];matches=saved_parents[saved_parents[:,parent_positions['parent_id']]==pid]
            assert len(matches)==1;old=matches[0]
            for name,value in (('entry_row',parent['entry_row']),('exit_row',parent['exit_row']),('side',parent['side']),
                ('quantity',1),('entry_price',parent['entry_price']),('initial_width',width),
                ('initial_line',parent['entry_price']-parent['side']*width)):
                assert old[parent_positions[name]]==value,name
            row=diagnose(record,parent,width);diagnostic.append(row)
            counts['実親']+=1;counts['全赤字親']+=int(row['最終赤字'])
            counts['実保有原行']+=row['実保有原行数'];counts['正常清算原行']+=row['正常清算原行数']
        sessions.append(dict(session=session,symbol=symbol,親数=len(physical),無取引=len(physical)==0,
            収支=actual['net'],診断=summarize([row for row in diagnostic if row['session']==session and row['symbol']==symbol])))
        counts['口座']+=1
    assert counts['口座']==62 and counts['幅原本照合']==62
    summary={symbol:{'全31':summarize([row for row in diagnostic if row['symbol']==symbol]),
        '買い':summarize([row for row in diagnostic if row['symbol']==symbol and row['side']==1]),
        '売り':summarize([row for row in diagnostic if row['symbol']==symbol and row['side']==-1])} for symbol in SYMBOLS}
    all_counts=summarize(diagnostic)
    for symbol in SYMBOLS:
        assert summary[symbol]['買い']['全親数']+summary[symbol]['売り']['全親数']==summary[symbol]['全31']['全親数']
    assert sum(summary[symbol]['全31']['全親数'] for symbol in SYMBOLS)==counts['実親']
    assert sum(summary[symbol]['全31']['最終赤字親数'] for symbol in SYMBOLS)==counts['全赤字親']
    ending={path.relative_to(ROOT).as_posix():digest(path) for path in paths};assert before==ending
    signatures=dict(ending,**{path.relative_to(ROOT).as_posix():digest(path) for path in material['paths']})
    result=dict(全合格=True,手法=IDENT,条件='固定1枚、増玉なし、元31のみ。実初回fillから実出口まで。',固定閾値S=list(MULTIPLES),
        検査件数=counts,商品別及び売買別=summary,両商品全31親数記述=all_counts,各セッション=sessions,
        全実親=diagnostic,全赤字親=[row for row in diagnostic if row['最終赤字']],幅の原本根拠=references,
        正常quote定義='quote_valid が真、bid/ask が有限、0<bid<ask。買玉はbid、売玉はask。entry/exit原行を含む。'
                     'LP支持・後の利益・品質分類で正常quoteを選別しない。',
        到達順定義='+0.5/1/1.5/2/3S と−Sの最初の正常原行で比較。価格代理時計が同秒でも原行順を使う。閾値の端数を有利へ丸めない。'
                 '実際の追尾停止線と初期−Sの診断閾値を同一視しない。',
        最大順行定義='実新規ask/bidを基準に正常清算quoteの方向差を取る。全区間の最大方向差が負なら最大順行は0と表示し、符号付き最高差も残す。',
        scope='記述統計。全親/全赤字親/未到達/無取引を保持。幅は最初の既知feed始値又は初約定観測と固定bpから作りraw prefixと実親初期Sへ照合。',
        解釈の限界='最大順行は実出口で打ち切られた期間の観測値。全セッション残時間の方向限界や新利確/新停止を実行した勝率ではない。'
                   '将来の高安・出口・到達順を売買判断へ使わない。両商品統合は親数の記述であり異倍率の金額ランキングではない。',
        新アルゴ実行=0,パラメータ探索=0,追加Night金融読取=0,現在API取得=0,実注文=0,過去成果変更=0,
        全31既知=True,開始終端依存一致=True,SHA256=signatures)
    target=HERE/'固定1枚の実保有中の到達順と返却利益の全31診断.json';assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,検査件数=counts,商品別及び売買別=summary),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
