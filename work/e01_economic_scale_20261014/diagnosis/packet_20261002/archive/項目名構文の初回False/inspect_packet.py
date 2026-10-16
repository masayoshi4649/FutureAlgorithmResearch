"""10月2日ナイトの保存packet一読から、価格推移と保存列の資格だけを診断する。"""

import argparse
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import pickle
import traceback
from zoneinfo import ZoneInfo
import numpy as np

HERE=Path(__file__).resolve().parent
STUDY=HERE.parents[1]
ROOT=HERE.parents[3]
SESSION='2026-10-02_Night'


def digest(payload: bytes) -> str:
    """
    機能: 一読したsource又は保存packetを同bytesで指紋へ結ぶ。
    引数: payload(bytes) は保存バイト。
    返り値: str はSHA256。大型資料を再読しない。
    """
    return hashlib.sha256(payload).hexdigest()


def sources() -> dict:
    """
    機能: 今回だけの非金融診断sourceを拘束する。
    引数: なし。
    返り値: dict は所有source相対pathとSHA256。金融17源は変更しない。
    """
    return {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in sorted(HERE.glob('*.py'))}


def write(name: str, value: dict) -> None:
    """
    機能: 新診断域へ未保存JSONをUTF-8で保存する。
    引数: name(str)、value(dict) は新証跡名と内容。
    返り値: None。NaNと上書きを拒否し、原入力/金融/公開を変更しない。
    """
    target=HERE/name;assert target.resolve().is_relative_to(HERE) and not target.exists()
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def safe(value: object) -> object:
    """
    機能: 保存値だけをJSON型へ写し、非有限値はNoneとして未補完にする。
    引数: value(object) は小射影対象。
    返り値: object は保存可能構造。未来値又は零へ救済しない。
    """
    if isinstance(value,np.ndarray):return safe(value.tolist())
    if isinstance(value,np.generic):return safe(value.item())
    if isinstance(value,float):return value if math.isfinite(value) else None
    if isinstance(value,dict):return {str(k):safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [safe(v) for v in value]
    if isinstance(value,(str,int,bool)) or value is None:return value
    return {'型':type(value).__name__,'未補完':True}


def schema(value: object) -> dict:
    """
    機能: 全key/型/shapeを列挙し、保存されない支持量/出来高/深板を作らない。
    引数: value(object) は保存口座又は配列。
    返り値: dict は保存構造のschema。配列本文はここに複写しない。
    """
    if isinstance(value,np.ndarray):return {'型':'ndarray','dtype':value.dtype.str,'shape':list(value.shape)}
    if isinstance(value,dict):return {'型':'dict','全key':list(map(str,value)),'内容':{str(k):schema(v) for k,v in value.items()}}
    if isinstance(value,(tuple,list)):return {'型':type(value).__name__,'長さ':len(value),'内容':[schema(v) for v in value]}
    return {'型':type(value).__name__}


def normal(account: dict) -> np.ndarray:
    """
    機能: 保存quote_validと有限正BBO/価格時計から既存正常価格行を選ぶ。
    引数: account(dict) は一商品保存口座。
    返り値: ndarray[bool,N] は現在保存列の価格資格。量/深板/受信資格は追加しない。
    """
    q,r=account['quotes'],account['record']
    return q['quote_valid']&np.isfinite(q['bid'])&np.isfinite(q['ask'])&(q['bid']>0)&(q['ask']>q['bid'])&np.isfinite(r['time_s'])


def point(account: dict, row: int) -> dict:
    """
    機能: 指定正常又は周辺行の原seq/価格代理時計/Last/BBO/資格を未補完で保存する。
    引数: account(dict)、row(int) は保存口座とnormal列index。
    返り値: dict は原入力対応点。PriceTimeを受信時計と呼ばない。
    """
    r,q=account['record'],account['quotes'];t=float(r['time_s'][row]);bid,ask=float(q['bid'][row]),float(q['ask'][row])
    output=dict(normal_row=int(row),raw_seq=int(r['seq'][row]),raw_index=int(account['mapping'][row]),
        price_time_s=t,price_time_JST=datetime.fromtimestamp(t,ZoneInfo('Asia/Tokyo')).isoformat() if math.isfinite(t) else None,
        last_price=float(r['price'][row]),bid=bid,ask=ask,spread=ask-bid,
        quote_valid=bool(q['quote_valid'][row]),normal=bool(normal(account)[row]))
    return safe(output)


def peer_point(peer: dict, own_time: float) -> dict:
    """
    機能: 当時自己価格時計より厳密過去の最後正常peerを価格時計模型で選ぶ。
    引数: peer(dict)、own_time(float) は相手保存口座と自己当行代理clock。
    返り値: dict はstrict過去点/年齢又は未知。物理受信先後を保証しない。
    """
    rows=np.flatnonzero(normal(peer));times=peer['record']['time_s'][rows]
    assert np.all(times[1:]>=times[:-1])
    pos=int(np.searchsorted(times,own_time,side='left')-1)
    if pos<0:return {'既知':False,'理由':'厳密過去正常peer無し'}
    row=int(rows[pos]);age=float(own_time-times[pos]);assert age>0
    return dict(既知=True,age_price_proxy_seconds=age,比較点age15秒以内=age<=15.,観測=point(peer,row),
        資格='strict PriceTimeだけ。受信先後/途中全raw/数量/深板を証明したものではない。')


def paper_state(account: dict, row: int) -> dict:
    """
    機能: 保存paper feedの当行までから方向と残仮想数量だけを復元する。
    引数: account(dict)、row(int) は同一保存口座と観測行。
    返り値: dict は影方向/親/公開ATR。実新規/実保有又は反転成功と混ぜない。
    """
    position=0;parent=None;atr=None;published=None
    for order in account['feed']:
        if int(order[0])>row:break
        if int(order[7])==1:
            assert position==0;parent=int(order[2]);atr=float(order[9]);published=int(order[0])
        position+=int(order[3])*int(order[4])
    return safe(dict(影方向=int(np.sign(position)),影残数量=abs(position),影親=parent,影公開ATR=atr,影公開行=published,
        定義='保存feedまでの影数量。実held/新しい支持根拠を代用しない。'))


def sample_path(account: dict, peer: dict, start: int, end: int, peak: int, entry_price: float) -> dict:
    """
    機能: 買清算bidの逐次高値と戻り価格だけを記録し、事後選択利益を算出しない。
    引数: account/peer(dict)、start/end/peak(int)、entry_price(float) は実保有期間と保存起点。
    返り値: dict は60代理秒代表点と事後極値後の初戻り点。売買政策ではない。
    """
    rows=np.flatnonzero(normal(account)[start:end+1])+start;assert len(rows)>0 and peak in rows
    times=account['record']['time_s'];assert np.all(times[1:]>=times[:-1])
    selected=[int(rows[0])];lasttime=times[rows[0]]
    for row in rows[1:]:
        if times[row]>=lasttime+60.:selected.append(int(row));lasttime=times[row]
    if selected[-1]!=int(rows[-1]):selected.append(int(rows[-1]))
    prices=account['quotes']['bid'][rows];running=np.maximum.accumulate(prices)
    peak_price=float(account['quotes']['bid'][peak]);after=rows[rows>peak];draws={}
    widths={'1pt':1.,'2pt':2.,'4pt':4.,'現既定drawの価格換算':entry_price*.00125}
    for label,width in widths.items():
        hits=after[account['quotes']['bid'][after]<=peak_price-width]
        draws[label]=None if not len(hits) else dict(起点='既保存の事後最大清算行。ここからの戻りは事後記述だけ。',
            幅price=width,自己=point(account,int(hits[0])),相手strict過去=peer_point(peer,float(times[hits[0]])),
            当時paper=paper_state(account,int(hits[0])))
    return dict(全実保有正常点数=len(rows),60価格代理秒以上隔てた代表点=[dict(自己=point(account,row),
        相手strict過去=peer_point(peer,float(times[row])),当時paper=paper_state(account,row)) for row in selected],
        事後最大点以後の初戻り観測=draws,
        全保有中の逐次最大bid=float(running[-1]),
        限界='戻り観測点を返済判断/仮想利益へ置換しない。新しい追尾arm/価格qual/再参加条件はここで決めない。')


def prepare() -> None:
    """
    機能: 指定一場一packetの別目的読取計画を本文前に保存する。
    引数: なし。
    返り値: None。保存meta/既小診断だけを読み、大型packet本文読取0で固定する。
    """
    raw=(STUDY/'engine/金融事前固定.json').read_bytes();fixed=json.loads(raw)
    detail_path=STUDY/'diagnosis/全量二出口と選択版の具体損失.json';detail_bytes=detail_path.read_bytes();detail=json.loads(detail_bytes)
    parents=detail['対象']['TOPIX|全量目標']['赤字上位場'][0]['損失上位親'];target=[p for p in parents if p['session']==SESSION and p['parent']==2]
    assert len(target)==1 and target[0]['side']==1;target=target[0]
    write('保存一場の価格経路とschemaの固定計画.json',dict(全合格=True,session=SESSION,input=fixed['input_cache'][SESSION],
        source_SHA256=sources(),金融source_SHA256=fixed['source_SHA256'],金融固定SHA256=digest(raw),
        小診断=dict(path=detail_path.relative_to(ROOT).as_posix(),SHA256=digest(detail_bytes)),
        対象親=target,予定={'指定保存packet':1,'原board':0,'NPZ':0,'API':0,'新金融':0,'新台帳':0},
        範囲='両商品account全key/type/shape。TOP親2入口/ピーク/広幅判断前後各五行、広幅周囲各二十行、保有区間代表60代理秒。',
        peer='同packetNKの当行PriceTime厳密過去最後正常点のみ。物理受信順不明を維持。',
        新支持='保存列の有無と影feed持続方向/公開ATRだけを整理。無い量/深板/現在出来高を補完しない。',
        保護価格='既事後極値以後1/2/4ptと旧draw換算幅の最初の観測点を価格としてだけ示す。仮想売買/利益は作らない。',
        再取得=False,自動再開始=False,金融=0,大型読取=0))
    print('一場保存packetの別目的計画を固定。本文読0。')


def run() -> None:
    """
    機能: 根授権の一packetを一bytes読/hash検算しschemaと正常経路を小保存する。
    引数: なし。CLI根授権flagが必要。
    返り値: None。source始終一致と読取計数を保存。失敗時はFalseを残して停止する。
    """
    assert not (HERE/'開始.json').exists() and not (HERE/'False.json').exists()
    plan=json.loads((HERE/'保存一場の価格経路とschemaの固定計画.json').read_bytes());source=sources();assert plan['source_SHA256']==source
    write('開始.json',dict(source_SHA256=source,目的='10/2Night一保存packetの別目的。価格/保存資格診断だけ。'))
    count=0
    try:
        path=ROOT/plan['input']['path'];assert path.resolve().is_relative_to(ROOT/'work')
        payload=path.read_bytes();count+=1;assert digest(payload)==plan['input']['SHA256']
        packet=pickle.loads(gzip.decompress(payload));assert packet['session']==SESSION
        accounts=packet['accounts'];top,peer=accounts['TOPIX'],accounts['NK225'];p=plan['対象親']
        for account in accounts.values():
            r,q=account['record'],account['quotes'];n=len(r['price'])
            assert len(r['seq'])==len(r['time_s'])==len(q['bid'])==len(q['ask'])==len(q['quote_valid'])==len(account['mapping'])==n
            np.testing.assert_array_equal(r['seq'],q['seq']);np.testing.assert_array_equal(r['time_s'],q['time_s'])
        anchors={'公開':p['entry']['source_row'],'実入口':p['entry']['row'],'事後最大清算':p['first_parent_liquidation_argmax']['row'],
            '広幅判断':p['exits'][-1]['source_row'],'実返済':p['exits'][-1]['row']}
        for event in (p['entry'],p['exits'][-1]):
            assert int(top['record']['seq'][event['row']])==event['raw_seq']
            assert float(top['quotes']['bid'][event['row']])==event['bid'] and float(top['quotes']['ask'][event['row']])==event['ask']
        windows={}
        for label,row in anchors.items():
            radius=20 if label in ('広幅判断','実返済') else 5
            windows[label]=[dict(自己=point(top,i),相手strict過去=peer_point(peer,float(top['record']['time_s'][i])),
                当時paper=paper_state(top,i)) for i in range(max(0,row-radius),min(len(top['record']['price']),row+radius+1))]
        first,last=p['entry']['row'],p['exits'][-1]['row'];chosen=top['feed']
        feed=[dict(raw_feed_row=safe(o),公開又は返済行=point(top,int(o[0])),影親=int(o[2]),影方向=int(o[3]),
            影枚数=int(o[4]),新規=bool(o[7]),paper価格=float(o[5]),公開ATR=float(o[9]),
            公開W60=safe(top['trade_features']['60'].get(int(o[0])))) for o in chosen if first<=int(o[0])<=last or int(o[2])==2]
        schema_value={s:schema(a) for s,a in accounts.items()}
        available={s:dict(account全key=list(a),record全key=list(a['record']),quotes全key=list(a['quotes']),
            元保存fieldの意味='record.price=Last、record.time_s=CurrentPriceTime代理、quotesは同原seqの保存BBO。',
            未追加='現在量/全normal出来高/10段/支持episode/受信時計は、存在しない限り未保存。trade_featuresは公開行限定。') for s,a in accounts.items()}
        result=dict(全合格=True,session=SESSION,対象親2=p,保存schema=schema_value,保存列可用性=available,指定観測点周辺=windows,
            価格経路=sample_path(top,peer,first,last,p['first_parent_liquidation_argmax']['row'],p['entry']['price']),
            保有中と当該影親の保存feed=feed,
            読取計数={'保存packet':count,'原board':0,'NPZ':0,'API':0,'新金融':0,'台帳':0},入力SHA256=digest(payload),
            source開始終端一致=source==sources(),source_SHA256=source,
            限界=['全raw途中clock/reset/深板をこのnormal保存物だけで証明しない。',
                'CurrentPriceTimeは価格代理時計。相手strict過去は時計模型であり物理受信順ではない。',
                '価格戻りは時系列観測だけ。別退出の約定/利益又は再参加できた数量を計算していない。'])
        assert result['source開始終端一致'];write('一場の保存列と広気配前後及び戻り価格の診断.json',safe(result))
        print(json.dumps(dict(全合格=True,保存packet読取=count,anchor=anchors,record列=list(top['record']),quotes列=list(top['quotes'])),ensure_ascii=False))
    except BaseException:
        write('False.json',dict(全合格=False,原因=traceback.format_exc(),保存packet読取=count,自動再開始=False));raise


def main() -> None:
    """
    機能: 計画保存と根授権の別目的一読診断を分離する。
    引数: CLI --prepare又は--root-one-packet-permitted(bool)。
    返り値: None。金融/注文/APIを実行しない。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--root-one-packet-permitted',action='store_true')
    args=parser.parse_args()
    if args.prepare:prepare()
    else:run()


if __name__=='__main__':main()
