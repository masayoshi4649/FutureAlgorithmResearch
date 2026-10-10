"""追加四場の生板を一行ずつ解析し、現在一件しか渡さない注文管理器を追跡する。"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
from datetime import datetime,timedelta,timezone
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import socket
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
ORDER=HERE.parent/'order_methods'
JST=timezone(timedelta(hours=9))
SESSIONS=['2026-10-02_Night','2026-10-05_Day','2026-10-05_Night','2026-10-06_Day']
sys.path.insert(0,str(ORDER))
from policy import StreamingPolicy
from design import catalog


def module(name: str,path: Path):
    """機能: 原本・既存成果を変更せず、固有名で読取機能を参照する。

    引数: name(str)、path(Path)。返り値: モジュール(object)。
    """
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    sys.modules[name]=value;spec.loader.exec_module(value);return value


def read(path: Path) -> object:
    """機能: 保存JSON又は圧縮JSONを読む。

    引数: path(Path)。返り値: 保存値(object)。
    """
    data=path.read_bytes();return json.loads(gzip.decompress(data) if path.suffix=='.gz' else data)


def save(name: str,value: object) -> None:
    """機能: 今回のトレース領域だけにJSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    path=HERE/name;path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2).encode('utf8')
    path.write_bytes(gzip.compress(data,mtime=0) if path.suffix=='.gz' else data)


def reject(*args,**kwargs) -> None:
    """機能: 調査中のネットワーク接続を拒否する。

    引数: 任意の引数。返り値: なし(None)、常に例外を送出する。
    """
    raise RuntimeError('この原本トレースはネットワークへ接続しません')


def finite(value: object,default: float=0.) -> float:
    """機能: 板のJSON値を有限数へ安全に変換する。

    引数: value(object)、default(float)。返り値: 数値(float)。
    """
    try:result=float(value)
    except (TypeError,ValueError):return default
    return result if math.isfinite(result) else default


def select(raw: dict,start: float,end: float) -> tuple:
    """機能: 現在原本行だけから時刻・有効最良板を判定する。

    引数: raw(dict)、start/end(float)。返り値: 採否/理由/時刻/価格/気配(tuple)。
    """
    stamp=raw.get('CurrentPriceTime')
    if not stamp:return False,'時刻欠損',None,None,None
    dt=datetime.fromisoformat(stamp)
    if dt.tzinfo is None:raise ValueError('原本時刻にタイムゾーンがありません')
    now=dt.timestamp()
    if not start<=now<end:return False,'対象時間外',now,None,None
    buy=raw.get('Buy1') or {};sell=raw.get('Sell1') or {}
    bid=finite(buy.get('Price'));ask=finite(sell.get('Price'))
    bq=finite(buy.get('Qty'));aq=finite(sell.get('Qty'))
    if min(bid,ask,bq,aq)<=0:return False,'最良板不正',now,None,None
    if bid==ask:return False,'ロック板',now,None,None
    if bid>ask:return False,'交差板',now,None,None
    price=finite(raw.get('CurrentPrice'),math.nan)
    if price<=0:price=math.nan
    return True,'有効',now,price,(bid,ask,bq,aq)


def signature(policy: StreamingPolicy) -> tuple:
    """機能: 注文準備・判断・約定に関係する現在状態だけを署名する。

    引数: policy(StreamingPolicy)。返り値: 比較署名(tuple)。
    """
    return (policy.state[2],policy.state[9],*policy.legs[:,[0,6,7,8,9]].ravel().tolist())


def format_time(stamp: float) -> str:
    """機能: UTC秒を日本時間のISO文字列にする。

    引数: stamp(float)。返り値: 日本時間文字列(str)。
    """
    return datetime.fromtimestamp(stamp,JST).isoformat()


def trace_one(key: tuple,ready: dict,configs: list[dict],expected: dict) -> dict:
    """機能: 生板一ファイルを全行解析し、三方式へ現在一行を順次配信する。

    引数: key(tuple)、ready(dict)、configs(list[dict])、expected(dict)。返り値: 厳密照合結果(dict)。
    """
    session,symbol=key;source=ROOT/'book'/symbol/(session+'.jsonl');hasher=hashlib.sha256()
    policies={c['id']:StreamingPolicy(c,ready['start'],ready['limit'],symbol) for c in configs}
    emitted={c['id']:dict(session=session,symbol=symbol,orders=[],trades=[]) for c in configs}
    logdir=HERE/'logs';logdir.mkdir(exist_ok=True)
    files={};writers={};counts=Counter();previous_minute={};previous_seq=-1;previous_stamp=None;cursor=0
    columns=['時刻','原本行番号0起点','記録種類','現在価格','公開済ATR','最良買気配','最良売気配','最良買数量','最良売数量',
             '買建枚数','売建枚数','実現累計円','含み円','合計円','組番号','段階','OCO上値','OCO下値',
             '買保留注文','売保留注文','買判断原本行','売判断原本行','当行約定注文JSON']
    log_counts=Counter();first=final=None
    try:
        for identifier in policies:
            path=logdir/(identifier+'_'+session+'_'+symbol+'.csv')
            handle=path.open('w',encoding='utf-8-sig',newline='');files[identifier]=handle
            writers[identifier]=csv.writer(handle);writers[identifier].writerow(columns);previous_minute[identifier]=None
        with source.open('rb') as stream:
            for seq,line in enumerate(stream):
                hasher.update(line);counts['全原本行']+=1;raw=json.loads(line)
                accepted,reason,now,price,quote=select(raw,ready['start'],ready['limit']+300)
                counts[reason]+=1
                if now is not None:
                    assert previous_stamp is None or now>=previous_stamp,('原本時刻逆行',key,seq)
                    previous_stamp=now
                cached_here=cursor<len(ready['seq']) and int(ready['seq'][cursor])==seq
                assert accepted==cached_here,('独立フィルタと保存列の採否差',key,seq,reason)
                if not accepted:continue
                assert seq>previous_seq;previous_seq=seq
                assert now==float(ready['time_s'][cursor]),('原本時刻不一致',key,seq)
                saved_price=float(ready['last'][cursor])
                assert price==saved_price or (math.isnan(price) and math.isnan(saved_price)),('原本価格不一致',key,seq)
                atr=float(ready['atr'][cursor]);cursor+=1
                first=now if first is None else first;final=now
                # ----------------------------------------
                # 先の原本行も価格配列も判断器へ渡さず、現在の四つの値だけを渡す。
                for identifier,policy in policies.items():
                    before=signature(policy)
                    event=policy.on_tick(float(now),int(seq),float(price),atr)
                    emitted[identifier]['orders'].extend(event['orders']);emitted[identifier]['trades'].extend(event['trades'])
                    after=signature(policy);minute=int(now//60)
                    if before!=after or event['orders'] or minute!=previous_minute[identifier]:
                        tags=[]
                        if event['orders']:tags.append('約定')
                        if np.any(policy.legs[:,6]!=0) and before!=after:tags.append('判断')
                        if policy.state[2]!=before[0] or policy.state[9]!=before[1]:tags.append('組状態')
                        if not tags:tags.append('時価')
                        writers[identifier].writerow([format_time(now),seq,'+'.join(tags),price,atr,*quote,
                            event['net_positions']['long'],event['net_positions']['short'],float(policy.state[11]),
                            event['equity']-float(policy.state[11]),event['equity'],event['cycle'],int(policy.state[2]),
                            float(policy.state[6]) if policy.state[2]==1 else '',float(policy.state[7]) if policy.state[2]==1 else '',
                            int(policy.legs[0,6]),int(policy.legs[1,6]),int(policy.legs[0,8]) if policy.legs[0,6] else '',
                            int(policy.legs[1,8]) if policy.legs[1,6] else '',json.dumps(event['orders'],ensure_ascii=False,separators=(',',':'))])
                        log_counts[identifier]+=1;previous_minute[identifier]=minute
    finally:
        for handle in files.values():handle.close()
    assert cursor==len(ready['seq'])
    checks=[]
    for identifier,policy in policies.items():
        ledger=emitted[identifier];stored=expected[identifier][key]
        assert np.array_equal(np.asarray(ledger['orders']).reshape(-1,10),np.asarray(stored['orders']).reshape(-1,10)),(identifier,key,'注文')
        assert np.array_equal(np.asarray(ledger['trades']).reshape(-1,16),np.asarray(stored['trades']).reshape(-1,16)),(identifier,key,'返済')
        assert np.all(policy.legs[:,0]==0) and np.all(policy.legs[:,6]==0)
        assert abs(sum(t[6] for t in ledger['trades'])-policy.state[11])<1e-7
        save('ledgers/'+identifier+'_'+session+'_'+symbol+'.json.gz',ledger)
        path=logdir/(identifier+'_'+session+'_'+symbol+'.csv')
        checks.append(dict(id=identifier,注文数=len(ledger['orders']),返済数=len(ledger['trades']),収支=float(policy.state[11]),
                           最大含み込み下落=float(policy.state[13]),場末買枚数=0,場末売枚数=0,全注文全返済完全一致=True,
                           ログ=str(path.relative_to(HERE)),ログ行数=log_counts[identifier],ログSHA256=hashlib.sha256(path.read_bytes()).hexdigest()))
    output=dict(session=session,symbol=symbol,原本=str(source.relative_to(ROOT)),原本SHA256=hasher.hexdigest(),原本バイト数=source.stat().st_size,
                行数=dict(counts),保存列完全照合件数=cursor,開始=format_time(first),終了=format_time(final),方式=checks,全合格=True)
    save('audits/'+session+'_'+symbol+'.json',output)
    print(session+' '+symbol+' 全原本'+str(counts['全原本行'])+'行 / 逐次'+str(cursor)+'行×3方式 完全一致',flush=True)
    return output


def main() -> None:
    """機能: 四場八原本を逐次再生し、全比較と原本指紋を保存する。

    引数: CLI --session(str、省略時4場)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser(description='保存生板の一件ずつトレース')
    parser.add_argument('--session',choices=SESSIONS);args=parser.parse_args()
    socket.socket.connect=reject;socket.create_connection=reject
    overlay=module('原本逐次_既存入力参照',HERE.parent/'overlay/research.py')
    inputs,_=overlay.load()
    chosen=read(ORDER/'過去10場選択.json')['系統代表'];configs=[c for c in catalog() if c['id'] in chosen]
    expected={identifier:{(l['session'],l['symbol']):l for l in read(ORDER/'ledgers'/(identifier+'.json.gz'))} for identifier in chosen}
    fixed=dict(対象=[args.session] if args.session else SESSIONS,方式=configs,方針='一行parse→現在原本とcache完全照合→当該行ATR→三方式on_tick。',
               ATR='既存readyの当該seq値のみを渡す。過去確定5分足公開の因果監査を継承し、ATR抽出そのものの独立再実装は行わない。',
               現在API取得数=0,板数量を方向予測に使用=False,独立有効板判定=True,
               注意='CurrentPriceTimeは約定時刻であり受信時刻ではない。同時刻の原本順は保持するが実際の通信遅延を再現するものではない。')
    save('実行仕様.json',fixed)
    proofs=[]
    for session in fixed['対象']:
        for symbol in ('TOPIX','NK225'):
            proofs.append(trace_one((session,symbol),inputs[(session,symbol)],configs,expected))
    save('監査.json',dict(全合格=True,原本数=len(proofs),口座数=len(proofs)*3,方式=chosen,
                        全parse行数=sum(p['行数']['全原本行'] for p in proofs),有効原本照合数=sum(p['保存列完全照合件数'] for p in proofs),
                        CSV行数=sum(s['ログ行数'] for p in proofs for s in p['方式']),原本別=proofs,
                        実装SHA256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ORDER/'policy.py',ORDER/'design.py',ORDER/'監査.json']},
                        API取得数=0,アプリ変更=False,ATR抽出因果監査継承=True))


if __name__=='__main__':main()
