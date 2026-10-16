"""NK225の赤字三場について、判断時の根拠とその後の失効を保存板から分離する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX','NK225')
BAD = ('2026-09-29_Night','2026-10-09_Day','2026-10-05_Day')
JST = timezone(timedelta(hours=9))
HASHES = {}


def read(relative):
    """
    機能: 過去の確定資料だけを読み、指紋を保存する。
    引数: relative (str) は相対パス。
    返り値: object は保存内容。
    """
    path = ROOT/relative
    data = path.read_bytes()
    HASHES[relative] = hashlib.sha256(data).hexdigest()
    return pickle.loads(data) if path.suffix == '.pkl' else json.loads(data.decode('utf-8'))


def stamp(value):
    """
    機能: 代理時計を日本時間へ表示する。
    引数: value (float) はUNIX秒。
    返り値: str は時差付き日時。真の受信時刻とは区別する。
    """
    return datetime.fromtimestamp(float(value),JST).isoformat()


def clean(value):
    """
    機能: 配列由来の数値をJSONへ変換し欠測をnullで残す。
    引数: value (object)。
    返り値: object はJSON互換の構造。
    """
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not np.isfinite(value):return None
    return value


def mapped_grid(times, grid):
    """
    機能: 旧方式と同じく判断格子を10秒以内の最初の原本行へ写像する。
    引数: times/grid (ndarray[float])。
    返り値: ndarray[int] は各原本行の最新格子番号。
    """
    out = np.full(len(times),-1,dtype=np.int32)
    for g,i in enumerate(np.searchsorted(times,grid,side='left')):
        if i < len(times) and times[i]-grid[g] <= 10.:out[i] = g
    return out


def endpoint(times, feature, deadline):
    """
    機能: 参照期限より厳密に過去の同時計先頭だけを採る。
    引数: times (ndarray)、feature (dict)、deadline (float)。
    返り値: int は参照行。無効・古い場合は-1で、過去救済しない。
    """
    last = int(np.searchsorted(times,deadline,side='left'))-1
    if last < 0:return -1
    i = int(np.searchsorted(times,times[last],side='left'))
    good = feature['valid'][i] and not feature['reset'][i] and 0 < deadline-times[i] <= 30.
    return i if good else -1


def sustained(grid, condition, valid, sa, sb, seconds=15.):
    """
    機能: 新しい両参照行を伴う連続条件を検査する。
    引数: grid/sa/sb (ndarray)、condition/valid (ndarray[bool])、seconds (float)。
    返り値: ndarray[bool] は確認済み旗。損益再生には用いない。
    """
    out = np.zeros(len(grid),dtype=bool)
    start = -1
    for i in range(len(grid)):
        if not valid[i] or not condition[i]:start=-1;continue
        if start < 0 or (i and grid[i]-grid[i-1] > 5.+1e-8):start=i
        if grid[i]-grid[start] >= seconds and sa[i]>sa[start] and sb[i]>sb[start]:out[i]=True
    return out


def first_event(mask, grid, begin, end):
    """
    機能: 保有区間で最初に成立した共同判断の時刻を返す。
    引数: mask (ndarray[bool])、grid (ndarray)、begin/end (float)。
    返り値: dict又はNone。将来経過の説明としてのみ使用する。
    """
    where = np.flatnonzero(mask & (grid>=begin) & (grid<=end))
    if not len(where):return None
    i = int(where[0])
    return {'格子':i,'時刻':stamp(grid[i]),'新規後秒':float(grid[i]-begin)}


def request_window(wanted, key, ready, index):
    """
    機能: 実参照行と直前直後二行の原本seqを抽出対象へ登録する。
    引数: wanted (dict)、key (tuple)、ready (dict)、index (int)。
    返り値: dict は準備行と原本行の対応。
    """
    if index < 0:return None
    indices = range(max(0,index-2),min(len(ready['seq']),index+3))
    items = []
    for i in indices:
        seq = int(ready['seq'][i])
        wanted.setdefault(key,{})[seq] = i
        items.append({'準備行':i,'原本seq':seq,'根拠行以前':i<=index})
    return {'参照準備行':index,'参照原本seq':int(ready['seq'][index]),'抽出窓':items}


def evidence_market(session, symbol, g, source, signal_time, side, ready, books, grids, wanted):
    """
    機能: 新規時に観測可能だった二市場の価格進行・数量・フローを記録する。
    引数: session/symbol (str)、g/source/side (int)、signal_time (float)、素材群 (dict)。
    返り値: dict は因果的な入口情報と参照原本位置。
    """
    key = session,symbol
    r,f,m = ready[key],books[key],grids[session]['markets'][symbol]
    times = r['time_s']
    old15 = endpoint(times,f,signal_time-5.-15.)
    old300 = endpoint(times,f,signal_time-5.-300.)
    current = int(m['current']['index'][g])
    values = {'旧入口参照行':source,'J2追加条件参照行':current,
        '旧入口参照JST':stamp(times[source]),'J2参照JST':stamp(times[current]),
        '旧入口参照時点の古さ秒':signal_time-times[source],
        '旧入口bid':f['bid'][source],'旧入口ask':f['ask'][source],
        '旧入口買数量':f['bid_qty'][source],'旧入口売数量':f['ask_qty'][source],
        '旧15秒参照行':old15,'旧300秒参照行':old300,
        '旧15秒参照JST':stamp(times[old15]) if old15>=0 else None,
        '旧300秒参照JST':stamp(times[old300]) if old300>=0 else None,
        '原本小窓':request_window(wanted,key,r,source)}
    for name,old in [('15秒',old15),('300秒',old300)]:
        values[name+'中値変化bp'] = (f['mid'][source]/f['mid'][old]-1)*10000 if old>=0 else None
        values[name+'買気配変化呼値'] = (f['bid'][source]-f['bid'][old])/r['tick'] if old>=0 else None
        values[name+'売気配変化呼値'] = (f['ask'][source]-f['ask'][old])/r['tick'] if old>=0 else None
    values['J2判断格子の現在'] = {k:v[g] for k,v in m['current'].items()}
    values['J2判断格子の15秒OFI'] = {k:v[g] for k,v in m['flow'][15].items()}
    values['300秒価格窓'] = {k:v[g] for k,v in m['windows'][300].items()}
    values['180秒直前レンジ'] = {k:v[g] for k,v in m['ranges'][180].items()}
    flow = m['flow'][15]
    sufficient = bool(flow['source_valid'][g] and flow['valid'][g] and not flow['missing_ofi'][g] and flow['nonzero_ofi_count'][g]>=3 and np.isfinite(flow['ofi_ratio'][g]))
    values['OFIが観測十分'] = sufficient
    values['OFIが入口方向を支持0_1以上'] = sufficient and side*flow['ofi_ratio'][g]>=.1
    values['OFIが明確に逆向き0_1以上'] = sufficient and side*flow['ofi_ratio'][g]<=-.1
    return values


def diagnose_trade(session, trade, role, ledgers, legacy, ready, books, grids, wanted):
    """
    機能: 既存一組の入口根拠、事後経路、費用寄与と崩壊時刻を分離する。
    引数: session/role (str)、trade (ndarray)、保存素材群 (dict)。
    返り値: dict は実台帳と一致する一組診断。取引の再計算・変更はしない。
    """
    key = session,'NK225'
    r,f,account,ss = ready[key],books[key],ledgers[key],grids[session]
    times = r['time_s'];grid = ss['grid']
    cid,entry,exit,side = int(trade[0]),int(trade[1]),int(trade[2]),int(trade[3])
    orders = account['orders']
    new = orders[(orders[:,2]==cid)&(orders[:,7]==1)][0]
    close = orders[(orders[:,2]==cid)&(orders[:,7]==0)][0]
    decision = int(new[1]);exit_decision = int(close[1])
    candidate = legacy[key]['candidates'][legacy[key]['candidates'][:,1]==decision]
    assert len(candidate)==1
    candidate = candidate[0]
    signal_time = r['start']+300.+15.*int(candidate[0])
    g = int(mapped_grid(times,grid)[decision]);assert g>=0
    sources = {'NK225':int(candidate[3]),'TOPIX':int(candidate[4])}
    market = {s:evidence_market(session,s,g,sources[s],signal_time,side,ready,books,grids,wanted) for s in SYMBOLS}
    indices = np.arange(entry,exit+1)
    good = np.isfinite(f['bid'][indices])&np.isfinite(f['ask'][indices])&(f['bid'][indices]>0)&(f['ask'][indices]>=f['bid'][indices])
    indices = indices[good]
    quotes = (f['bid'] if side==1 else f['ask'])[indices]
    points = side*(quotes-trade[5])
    net = points*200.-440.
    high_i = int(indices[np.argmax(net)]);low_i = int(indices[np.argmin(net)])
    positive = np.flatnonzero(net>0)
    giveback = None
    if len(positive):
        lost = np.flatnonzero((np.arange(len(net))>positive[0])&(net<=0))
        if len(lost):
            j = int(indices[lost[0]])
            giveback = {'時刻':stamp(times[j]),'原本seq':int(r['seq'][j]),'費用後含み損益':float(net[lost[0]])}
    mid_net = side*(f['mid'][exit]-f['mid'][entry])*200.
    spread = mid_net-trade[9]
    decision_quote = f['ask'][decision] if side==1 else f['bid'][decision]
    source_quote = f['ask'][sources['NK225']] if side==1 else f['bid'][sources['NK225']]
    entry_warning = side*(decision_quote-source_quote)/r['tick']
    a,b = (ss['markets'][s] for s in SYMBOLS)
    valid = a['current']['valid']&b['current']['valid']
    v300 = valid.copy();same300 = valid.copy();v30 = valid.copy()
    both_reverse = np.ones(len(grid),bool)
    own = b['windows'][30];peer = a['windows'][30]
    own_reverse = (side*own['bid_change_ticks']<=-1+1e-8)&(side*own['ask_change_ticks']<=-1+1e-8)
    for m in (a,b):
        w = m['windows'][300];v300 &= w['source_valid']&np.isfinite(w['ret_bp']);same300 &= w['source_valid']&(side*w['ret_bp']>=3.)
        w = m['windows'][30];v30 &= w['source_valid']&np.isfinite(w['ret_bp'])
        both_reverse &= (side*w['bid_change_ticks']<=-1+1e-8)&(side*w['ask_change_ticks']<=-1+1e-8)
    lose300 = v300&~same300
    x1 = sustained(grid,both_reverse,v30,a['current']['index'],b['current']['index'])
    x2 = sustained(grid,own_reverse&(side*peer['ret_bp']<=0),v30,a['current']['index'],b['current']['index'])
    scope = (grid>=times[entry])&(grid<=times[exit])
    changes = {'共同300秒の3bp支持が有効観測で消失':first_event(lose300,grid,times[entry],times[exit]),
        '両30秒両気配逆行の15秒確認':first_event(x1,grid,times[entry],times[exit]),
        '自己30秒両気配逆行と相手非順行の15秒確認':first_event(x2,grid,times[entry],times[exit]),
        '保有中格子数':int(scope.sum()),'300秒共同判断不能数':int((scope&~v300).sum())}
    for name,event in list(changes.items()):
        if not isinstance(event,dict):continue
        gg = event['格子'];rows = int(np.searchsorted(times,grid[gg],side='left'))
        if rows>=len(times) or times[rows]-grid[gg]>10:continue
        quote = f['bid'][rows] if side==1 else f['ask'][rows]
        event['その判断時の費用後清算評価'] = side*(quote-trade[5])*200.-440.
        event['判断時価格'] = float(quote)
        event['意味'] = '仮に新方式で返済する時刻と約定値ではない。過去観測による仮説失効の説明。'
    return {'セッション':session,'商品':'NK225','役割':role,'組番号':cid+1,'方向':'買い' if side==1 else '売り',
        '枚数':int(trade[4]),'判断格子JST':stamp(signal_time),'発注判断JST':stamp(times[decision]),
        '新規約定JST':stamp(times[entry]),'返済判断JST':stamp(times[exit_decision]),'返済約定JST':stamp(times[exit]),
        '入口判断準備行':decision,'入口判断原本seq':int(r['seq'][decision]),'J2追加判断格子JST':stamp(grid[g]),
        '新規価格':trade[5],'返済価格':trade[6],'返済理由番号':int(close[6]),'保有秒':times[exit]-times[entry],
        '利益損失分解':{'収支':trade[10],'売買価格差損益':trade[9],'料金':trade[7]+trade[8],
            '同じ約定時刻の中値差損益':mid_net,'気配差負担':spread,
            '恒等式確認':abs(mid_net-spread-trade[7]-trade[8]-trade[10])<1e-8},
        '入口時の可観測情報':market,
        '発注時追いかけ':{'不利方向の参照比呼値':entry_warning,'自発注判断価格':decision_quote,'旧根拠参照価格':source_quote,
            '1呼値超なら見送り案の対象':entry_warning>1.+1e-8,'次有効約定の追加不利呼値':side*(trade[5]-decision_quote)/r['tick']},
        '事後経路':{'最大順行pt':float(points.max()),'最大逆行pt':float(max(0.,-points.min())),
            '費用後最大清算評価':float(net.max()),'費用後最小清算評価':float(net.min()),
            '最大順行JST':stamp(times[high_i]),'最大逆行JST':stamp(times[low_i]),
            '初回含み益消失':giveback,'共同判断の変化':changes},
        '発注判断自身の生板窓':request_window(wanted,key,r,decision)}


def raw_windows(wanted, ready, books):
    """
    機能: 依頼された原本seqだけ十段価格数量を抽出し、同一価格の表示差を記録する。
    引数: wanted/ready/books (dict)。
    返り値: tuple[dict,dict] は小窓の生板証拠と原本照合件数。
    後続行は事後で入口根拠に使用しない。
    """
    output = {}
    checks = []
    for key, wanted_seq in wanted.items():
        session,symbol = key
        path = ROOT/'book'/symbol/f'{session}.jsonl'
        content = {}
        hasher = hashlib.sha256()
        with path.open('rb') as stream:
            for seq,line in enumerate(stream):
                hasher.update(line)
                if seq not in wanted_seq:continue
                raw = json.loads(line)
                levels = {side:[[float(raw[f'{side}{i}']['Price']),float(raw[f'{side}{i}']['Qty'])] for i in range(1,11)] for side in ('Buy','Sell')}
                index = wanted_seq[seq]
                r,f = ready[key],books[key]
                actual_time = datetime.fromisoformat(raw['CurrentPriceTime']).timestamp()
                assert int(r['seq'][index])==int(f['seq'][index])==seq
                assert actual_time==r['time_s'][index]==f['time_s'][index]
                assert levels['Buy'][0][0]==f['bid'][index]
                assert levels['Sell'][0][0]==f['ask'][index]
                assert levels['Buy'][0][1]==f['bid_qty'][index]
                assert levels['Sell'][0][1]==f['ask_qty'][index]
                assert float(raw['CurrentPrice'])==r['last'][index]==f['last'][index]
                content[seq] = {'原本seq':seq,'準備行':index,'CurrentPriceTime':raw['CurrentPriceTime'],
                    '現在値':raw.get('CurrentPrice'),'累積出来高':raw.get('TradingVolume'),
                    '出来高時刻':raw.get('TradingVolumeTime'),'買十段価格数量':levels['Buy'],'売十段価格数量':levels['Sell']}
        assert len(content)==len(wanted_seq)
        HASHES[str(path.relative_to(ROOT))] = hasher.hexdigest()
        checks.append({'セッション':session,'商品':symbol,'原本抽出行数':len(content),
            '原本seqと準備seqと特徴seq一致行数':len(content),
            'CurrentPriceTimeと両保存時計一致行数':len(content),
            'Buy1価格とbid一致行数':len(content),'Sell1価格とask一致行数':len(content),
            'Buy1数量とbid_qty一致行数':len(content),'Sell1数量とask_qty一致行数':len(content),
            '現在値と両保存最終値一致行数':len(content),
            '十段価格数量の原本抽出行数':len(content)})
        for seq,row in content.items():
            if seq-1 not in content:continue
            prior = content[seq-1]
            difference = {}
            for name in ('買十段価格数量','売十段価格数量'):
                before = dict(prior[name]);after = dict(row[name])
                difference[name] = [{'価格':price,'表示差':qty-before[price]} for price,qty in after.items() if price in before and qty!=before[price]]
            row['前原本行から同一表示価格の数量差'] = difference
        output['|'.join(key)] = list(content.values())
    total = sum(c['原本抽出行数'] for c in checks)
    return output, {'合格':True,'原本口座数':len(checks),'原本抽出照合行数':total,
        '各行7項目一致':True,'照合項目延べ件数':7*total,'口座別':checks,
        '範囲':'全原本を順番に読んでSHA256を記録し、依頼された小窓の行だけ価格・数量・代理時計・seq・最終値を照合。全原本全行の特徴再計算ではない。',
        '十段の扱い':'十段の全価格と数量は原本から直接抽出。特徴との独立一致は上記の最良気配・最良数量・時刻等7項目で、十段全部の一致照合をしたとは数えない。'}


def main():
    """
    機能: 赤字三場の全組と、各方向の直前黒字対照を診断する。
    引数: なし。
    返り値: None。担当ディレクトリだけへ説明用JSONを出力する。
    """
    meta = read('work/wave_v77/inputs/metadata.json')
    ready = {};books = {}
    for path in meta['input_paths']['ready']:ready.update(read(path))
    for path in meta['input_paths']['features']:books.update(read(path))
    ready.update(read('work/wave_v77/inputs/extra_inputs.pkl'));books.update(read('work/wave_v77/inputs/extra_features.pkl'))
    grids = read('work/wave_v77/inputs/grids_delay5.pkl')
    legacy = read('work/wave_v77/prepared/legacy_delay5.pkl')
    ledgers = read('work/wave_v78/ledgers/J2_F0_B0_H0_R0.pkl')
    results = read('work/wave_v78/results/J2_F0_B0_H0_R0.json')
    wanted = {};items = [];included = set()
    for session in BAD:
        for trade in ledgers[(session,'NK225')]['trades']:
            cid = int(trade[0]);included.add((session,cid))
            items.append(diagnose_trade(session,trade,'指定赤字場の全組',ledgers,legacy,ready,books,grids,wanted))
    # ----------------------------------------
    # 勝ち対照は各赤字場の各取引方向について、その場開始より前の直近黒字を一つ選ぶ。
    controls = []
    for session in BAD:
        for sign in sorted({int(t[3]) for t in ledgers[(session,'NK225')]['trades']}):
            pool = []
            start = ready[(session,'NK225')]['start']
            for key,value in ledgers.items():
                if key[1]!='NK225':continue
                for t in value['trades']:
                    exit_time = ready[key]['time_s'][int(t[2])]
                    if t[10]>0 and int(t[3])==sign and exit_time<start:pool.append((exit_time,key[0],t))
            if pool:
                _,control_session,trade = max(pool,key=lambda x:x[0])
                ck = control_session,int(trade[0])
                controls.append({'赤字場':session,'方向':sign,'対照場':control_session,'対照組':int(trade[0])+1})
                if ck not in included:
                    included.add(ck)
                    items.append(diagnose_trade(control_session,trade,'直前黒字の同方向対照',ledgers,legacy,ready,books,grids,wanted))
    extracted,raw_checks = raw_windows(wanted,ready,books)
    totals = {}
    for session in BAD:
        targets = [i for i in items if i['セッション']==session and i['役割']=='指定赤字場の全組']
        totals[session] = {k:sum(t['利益損失分解'][k] for t in targets) for k in ('収支','売買価格差損益','料金','同じ約定時刻の中値差損益','気配差負担')}
        expected = next(r for r in results['rows'] if r['session']==session and r['symbol']=='NK225')
        assert totals[session]['収支']==expected['net']
    output = {'対象':'基準J2_F0_B0_H0_R0の日経赤字上位三場', '三場会計':totals,
        '新損益再生':False,'再選定':False,'API取得':0,'実注文':0,
        '勝ち対照の規則':'各指定場の各取引方向について、当場開始より前に返済した直近の黒字組を一つ。重複は統合。黒字対照選択は診断専用。',
        '対照対応':controls,'全組診断':items,'生板小窓':extracted,'原本気配数量時計の照合':raw_checks,
        '事前と事後の分離':'入口時の可観測情報と発注時追いかけは判断以前だけ。事後経路のMFE/MAE・根拠失効・含み益消失は後の説明で、入口条件へ逆算しない。',
        '時計':'CurrentPriceTimeは最終約定の代理時計で受信時刻ではない。同時計の後続原本行は入口時に既知とは扱わない。格子参照は厳密な過去の同時計先頭。',
        '生板の限界':'Buy1が買気配、Sell1が売気配。同一価格の表示増減は注文追加・取消・約定消費を一意に区別しない。後続二行は事後確認だけ。補充や主体の焦りを断定しない。',
        '費用説明':'同じ実約定行の中値差損益−気配差負担−料金=収支。中値で再生した実行可能な戦略の成績ではない。',
        '出典SHA256':HASHES,'解析器SHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    HERE.mkdir(parents=True,exist_ok=True)
    target = HERE/'赤字三場の全組と入口根拠.json'
    target.write_text(json.dumps(clean(output),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'保存':str(target),'診断組数':len(items),'原本口座数':len(extracted),'会計':totals},ensure_ascii=False))


if __name__=='__main__':main()
