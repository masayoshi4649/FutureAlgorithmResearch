"""追加三場の全損失親と価格転換を、保存注文と当時の特徴から診断する。"""

import hashlib
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as dates


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'work/aggressive140_20261024'
sys.path.insert(0, str(OLD))
import active140_v2 as active
from diagnose_changes140 import parents
from charts140 import order_markers

TZ = ZoneInfo('Asia/Tokyo')
FEATURE_NAMES = ('公開帯高値', '公開帯安値', '40分効率', '5分差', '40分差',
                 '短平均', '長平均', '場始価格', '足終端時計', '当時R', '判断中値',
                 '短ATR', '自30秒R', '自120秒R', '他5分差', '他40分差', '他40分効率',
                 '他場始価格', '他R', '他中値', '他30秒R', '他120秒R', '他参照時計', '他足終端時計')


def read(path):
    """
    機能: UTF-8の保存JSONを読む。
    引数: path(Path)は入力位置。
    返り値: dict/listは保存内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def clean(value):
    """
    機能: 非有限値を欠測としてJSONに保存できる型へ変換する。
    引数: value(object)は辞書・配列・数値等。
    返り値: objectはNaNをNoneへ置換した値。
    """
    if isinstance(value, dict):
        return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def stamp(value):
    """
    機能: 保存時計を日付付き日本時間にする。
    引数: value(float)はUnix秒。
    返り値: strは秒精度の日本時間。原行順の識別は別途seqで行う。
    """
    return datetime.fromtimestamp(float(value), TZ).strftime('%m-%d %H:%M:%S')


def fingerprint(path):
    """
    機能: 読んだ保存資料の指紋を得る。
    引数: path(Path)はファイル。
    返り値: dictは相対位置とSHA256。
    """
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def point(ready, quote, features, row):
    """
    機能: 指定原行で既知だった価格・公開特徴を記録する。
    引数: ready/quote(dict)、features(ndarray)、row(int)は保存入力と当時行。
    返り値: dictは判断行・原資料行・時刻・因果的特徴。
    """
    item = dict(row=int(row), seq=int(ready['seq'][row]), line_no=int(ready['seq'][row])+1, time=stamp(ready['time_s'][row]),
                time_s=float(ready['time_s'][row]), bid=float(quote['bid'][row]),
                ask=float(quote['ask'][row]), atr=float(ready['atr'][row]),
                trend_side=float(ready['trend_side'][row]), board_side=float(ready['board_side'][row]))
    item['features'] = dict(zip(FEATURE_NAMES, map(float, features[row])))
    peer_time = features[row, 22]
    assert not np.isfinite(peer_time) or peer_time < ready['time_s'][row]
    return item


def turns(ready, quote, features):
    """
    機能: 0.1%の反対進行で確認された転換について、極値行と確認行を分けて記録する。
    引数: ready/quote(dict)、features(ndarray)は価格と当時特徴。
    返り値: tuple[float,list]は場初正常中値から固定した幅と転換一覧。売買は行わない。
    """
    mid = (quote['bid']+quote['ask'])*.5
    valid = quote['quote_valid'] & np.isfinite(mid) & (ready['time_s'] >= ready['start'])
    rows = np.flatnonzero(valid)
    threshold = np.ceil(mid[rows[0]]*.001/ready['tick'])*ready['tick']
    high = low = int(rows[0])
    direction = 0
    result = []
    for ix in rows:
        if mid[ix] > mid[high]:
            high = int(ix)
        if mid[ix] < mid[low]:
            low = int(ix)
        extreme = -1
        if direction >= 0 and mid[high]-mid[ix] >= threshold:
            extreme, side, direction = high, -1, -1
            low = int(ix)
        elif direction <= 0 and mid[ix]-mid[low] >= threshold:
            extreme, side, direction = low, 1, 1
            high = int(ix)
        if extreme >= 0:
            result.append(dict(kind='高値後の下落' if side < 0 else '安値後の上昇',
                extreme=point(ready,quote,features,extreme), confirmed=point(ready,quote,features,int(ix)),
                extreme_mid=float(mid[extreme]), confirmed_mid=float(mid[ix]),
                confirmation_delay_seconds=float(ready['time_s'][ix]-ready['time_s'][extreme])))
    return float(threshold), result


def campaigns(orders, symbol, ready, quote, features):
    """
    機能: 全親の円会計を再確認し、注文時点・追加玉・事後の最大順逆行を整理する。
    引数: orders(ndarray)、symbol(str)、ready/quote(dict)、features(ndarray)。
    返り値: dict[int,dict]は全親。事後順逆行は入口判定へ使用しない。
    """
    result = parents(orders, symbol, ready['time_s'])
    multiplier = 100. if symbol == 'NK225' else 1000.
    middle = (quote['bid']+quote['ask'])*.5
    for pid, parent in result.items():
        part = orders[orders[:,2] == pid]
        parent['role'] = '追加担当' if pid >= 3_000_000 else '基準B5'
        parent['orders'] = []
        tickets = {}
        for row in part:
            fill, decision, _, side, qty = map(int,row[:5])
            new, uid, fee = map(int,row[7:])
            action = '初回新規' if new and uid == 0 else ('追加新規' if new else '返済')
            if new and uid == 999:
                action = '補完新規'
            item = dict(action=action, side=side, quantity=qty, price=float(row[5]), reason=int(row[6]),
                uid=uid, fee=fee, decision=point(ready,quote,features,decision),
                fill=point(ready,quote,features,fill))
            assert fill > decision
            ticket = tickets.setdefault(uid,dict(uid=uid, quantity=0, entry_price=0., net=0., initial=uid in (0,999)))
            ticket['net'] -= fee
            if new:
                ticket['quantity'],ticket['entry_price'],ticket['side'] = qty,float(row[5]),side
            else:
                ticket['net'] += ticket['side']*qty*(row[5]-ticket['entry_price'])*multiplier
            parent['orders'].append(item)
        parent['tickets'] = list(tickets.values())
        assert abs(sum(t['net'] for t in tickets.values())-parent['net']) < 1e-6
        lo,hi = int(part[0,0]),int(part[-1,0])
        rows = np.arange(lo,hi+1)[quote['quote_valid'][lo:hi+1]]
        move = parent['side']*(middle[rows]-part[0,5])
        best,worst = int(rows[np.argmax(move)]),int(rows[np.argmin(move)])
        parent['afterwards'] = dict(note='初回建値を基準とする事後中値幅。枚数加重の実損益ではない。',
            favorable_pt=float(move.max()),adverse_pt=float(-move.min()),
            favorable=point(ready,quote,features,best),adverse=point(ready,quote,features,worst))
    return result


def plotted_rows(ready, quote, start, first, time, own, before):
    """
    機能: 因果境界を守ったうえで、各描画区間の高安を落とさず行を間引く。
    引数: ready/quote(dict)、start/time(float)、first(int)、own/before(bool)。
    返り値: ndarray[int]は原行順の描画行。異常な一時気配も隠さない。
    """
    times=np.asarray(ready['time_s']);mid=(quote['bid']+quote['ask'])*.5
    mask=quote['quote_valid'] & np.isfinite(mid) & (times>=start)
    if before:
        mask &= np.arange(len(times)) <= first if own else times < time
    valid=np.flatnonzero(mask)
    if len(valid)<=3600:
        return valid
    result=[]
    for block in np.array_split(valid,900):
        result.extend((int(block[0]),int(block[np.argmin(mid[block])]),int(block[np.argmax(mid[block])]),int(block[-1])))
    return np.unique(result)


def picture(packet, symbol, method, base, actual, loss, destination):
    """
    機能: 最初の損失入口の判断直前までと全経路を、二市場・売買位置付きで図示する。
    引数: packet(dict)、symbol/method(str)、base/actual(ndarray)、loss(list)、destination(Path)。
    返り値: None。左は自市場の原行境界と相手の厳密過去、右は事後全経路。
    """
    ready=packet['inputs'][packet['session'],symbol]
    quote=packet['quotes'][packet['session'],symbol]
    first=min(p['orders'][0]['decision']['row'] for p in loss)
    time=float(ready['time_s'][first])
    peer='TOPIX' if symbol=='NK225' else 'NK225'
    plt.rcParams['font.family']='Meiryo'
    plt.style.use('dark_background')
    fig,axes=plt.subplots(2,2,figsize=(16,9),gridspec_kw={'width_ratios':[1,2]})
    for col in range(2):
        before=col==0
        for row,target in enumerate((symbol,peer)):
            rr=packet['inputs'][packet['session'],target];qq=packet['quotes'][packet['session'],target]
            ix=plotted_rows(rr,qq,ready['start'],first,time,target==symbol,before)
            dt=[datetime.fromtimestamp(float(t),TZ) for t in rr['time_s'][ix]]
            ax=axes[row,col]
            ax.plot(dt,(qq['bid'][ix]+qq['ask'][ix])*.5,color='#78c5ff',lw=1.)
            ax.set_ylabel(target);ax.grid(alpha=.18)
            ax.xaxis.set_major_formatter(dates.DateFormatter('%H:%M',tz=TZ))
            if row==0:
                order_markers(ax,base,ready['time_s'],quote,first,before,'#aab1bc','B5単独対照')
                added=actual[actual[:,2]>=3_000_000]
                order_markers(ax,added,ready['time_s'],quote,first,before,'#f4c85c','採用追加')
                if ax.get_legend_handles_labels()[0]:ax.legend(fontsize=7,loc='best')
        axes[0,col].set_title('最初の損失入口の判断まで '+stamp(time) if before else '事後の全経路（予測には使わない）')
    fig.suptitle(f'{packet["session"]}  {symbol} / {method}  原板中値と保存売買')
    fig.text(.5,.017,'星＝未約定の判断中値。B5対照は採用を意味しない。横軸は価格時計（受信時計ではない）。区間高安を保持。',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.045,1,.96));fig.savefig(destination,dpi=140);plt.close(fig)


def write_report(records):
    """
    機能: 全六口座の経路・転換・全損失親を省略せずMarkdownへ保存する。
    引数: records(list[dict])は診断記録。
    返り値: None。新しい金銭的予測力を主張しない。
    """
    lines=['# 追加三場・全損失親と価格転換の診断','',
        '保存済み注文と価格の事後診断。新条件の金融再生は0。時刻は日本時間の価格時計であり受信時計ではない。同時刻内は原文seqの順序で区別する。seqは0始まりで、原文行番号はseq+1。',
        '転換の極値時刻と、場初正常中値の0.1%（呼値切上げ）戻った確認時刻を分ける。0.1%は経路を列挙する固定の診断尺度であり、新しい売買条件ではない。最大順逆行は事後値。','']
    for r in records:
        lines += [f'## {r["session"]} / {r["symbol"]} / {r["method"]}','',
            f'基準B5 {r["baseline_net"]:+,.0f}円、比較手法 {r["actual_net"]:+,.0f}円。比較手法の全{len(r["actual_parents"])}親、損失{len(r["actual_losses"])}親を網羅。B5単独だけの損失も後掲。',
            f'経路: 始値中値 {r["path"]["open"]:g}、終値中値 {r["path"]["close"]:g}、高値 {r["path"]["high"]:g}（{r["path"]["high_time"]}）、安値 {r["path"]["low"]:g}（{r["path"]["low_time"]}）。','',
            '|転換|事後極値時刻・中値|反対進行の初確認時刻・中値|確認幅|','|---|---|---|---:|']
        for turn in r['turns']:
            lines.append(f'|{turn["kind"]}|{turn["extreme"]["time"]} / {turn["extreme_mid"]:g}|{turn["confirmed"]["time"]} / {turn["confirmed_mid"]:g}|{r["turn_threshold"]:g}|')
        for group in ('actual_losses','baseline_only_losses'):
            for p in r[group]:
                label='採用手法の損失' if group=='actual_losses' else '比較用B5だけの損失（採用なし）'
                lines += ['',f'### {label} / 親{p["parent"]} / {p["role"]} / {p["net"]:+,.0f}円','',
                    f'初回建値基準の事後中値: 最大順行{p["afterwards"]["favorable_pt"]:g}pt、最大逆行{p["afterwards"]["adverse_pt"]:g}pt。',
                    '|処理|判断時刻 / 原文seq|約定時刻 / 原文seq|売買・枚数・価格|当時40分効率|自/他40分差|自/他30秒R|当時R|',
                    '|---|---|---|---|---:|---|---|---:|']
                for o in p['orders']:
                    d,f=o['decision'],o['fill'];a=d['features']
                    fmt=lambda x:f'{x:.3g}' if np.isfinite(x) else '欠測'
                    lines.append(f'|{o["action"]}|{d["time"]} / {d["seq"]}|{f["time"]} / {f["seq"]}|{"買" if o["side"]>0 else "売"}{o["quantity"]}枚 @{o["price"]:g}|{fmt(a["40分効率"])}|{fmt(a["40分差"])}/{fmt(a["他40分差"])}|{fmt(a["自30秒R"])}/{fmt(a["他30秒R"])}|{fmt(a["当時R"])}|')
                lines.append('玉別収支: '+'、'.join(f'UID{x["uid"]} {x["quantity"]}枚 {x["net"]:+,.0f}円' for x in p['tickets'])+'。')
        lines += ['',f'![判断前と事後全経路](charts/{r["symbol"]}_{r["session"]}.png)','']
    (HERE/'全損失親と価格転換141.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    """
    機能: 既知三場の保存約定を価格行へ接続して診断資料と六画像を生成する。
    引数: なし。
    返り値: None。既存資料を書換えず、新金融戦略の再生をしない。
    """
    (HERE/'charts').mkdir(parents=True,exist_ok=True)
    manifest=read(OLD/'inputs/input_manifest.json')
    records=[];sources=[]
    for entry in manifest['packets']:
        path=ROOT/entry['path'];source=fingerprint(path);assert source['sha256']==entry['sha256'];sources.append(source)
        packet=pickle.loads(path.read_bytes());scene=packet['session'];prepared=active.prepare(packet,40)
        for symbol,method,folder in (('NK225','S36','round2_new'),('TOPIX','C33','new')):
            base_path=OLD/'new/measurement'/f'{symbol}_{scene}.npz'
            actual_path=OLD/folder/'measurement'/f'{symbol}_{scene}.npz'
            with np.load(base_path) as f:base=f['B5']
            with np.load(actual_path) as f:actual=f[method]
            sources.extend((fingerprint(base_path),fingerprint(actual_path)))
            r=packet['inputs'][scene,symbol];q=packet['quotes'][scene,symbol];a=prepared[symbol]['features']
            bp=campaigns(base,symbol,r,q,a);ap=campaigns(actual,symbol,r,q,a)
            loss=[p for p in ap.values() if p['net']<0]
            base_only=[p for pid,p in bp.items() if pid not in ap and p['net']<0]
            threshold,turning=turns(r,q,a)
            mid=(q['bid']+q['ask'])*.5;rows=np.flatnonzero(q['quote_valid'])
            high,low=int(rows[np.argmax(mid[rows])]),int(rows[np.argmin(mid[rows])])
            result=dict(session=scene,symbol=symbol,method=method,baseline_net=sum(p['net'] for p in bp.values()),
                actual_net=sum(p['net'] for p in ap.values()),baseline_parents=list(bp.values()),actual_parents=list(ap.values()),
                actual_losses=loss,baseline_only_losses=base_only,turn_threshold=threshold,turns=turning,
                path=dict(open=float(mid[rows[0]]),close=float(mid[rows[-1]]),high=float(mid[high]),low=float(mid[low]),
                          high_time=stamp(r['time_s'][high]),low_time=stamp(r['time_s'][low])))
            records.append(result)
            picture(packet,symbol,method,base,actual,loss,HERE/'charts'/f'{symbol}_{scene}.png')
            print(scene,symbol,'全損失親',len(loss),'B5のみ損失',len(base_only),flush=True)
    content=dict(purpose='保存済み注文の全損失と価格転換の診断。新金融再生0。',sources=sources,records=records)
    (HERE/'全損失親と価格転換141.json').write_text(json.dumps(clean(content),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    write_report(records)


if __name__=='__main__':
    main()
