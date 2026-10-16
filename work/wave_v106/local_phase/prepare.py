"""確定range_price33入力を各一回読み、未来値を使わず短期位相を保存する。"""

import argparse
from pathlib import Path

import numpy as np

import catalog
import common
import features
import selection

SOURCE=common.ROOT/'work/wave_v106/range_price/全33場の価格境界反発準備.json'
ART=common.HERE/'直近位相と方向別待機取消の人工検査.json'
TARGET=common.HERE/'全33場の直近位相準備.json'


def sources() -> dict:
    """
    機能: 入力準備に関わる小sourceを固定する。
    引数: なし。
    返り値: dict[str,str]はROOT相対sourceとSHA256。金融結果を読む必要はない。
    """
    return {p.relative_to(common.ROOT).as_posix():common.digest(p) for p in
        [common.HERE/n for n in ('common.py','catalog.py','features.py','selection_snapshot.py','selection.py','prepare.py','data.py')]}


def activity(packet: dict) -> dict:
    """
    機能: 元R候補の受付内拒否とC保持、方向別取消行数を勝敗と区別して集計する。
    引数: packet(dict)は元入力と全normal短期位相。
    返り値: dictは18条件商品ごとの候補数。待機取消の実件数や勝ち数ではない。
    """
    result={}
    for symbol in ('TOPIX','NK225'):
        record=packet['prepared'][symbol]['record'];m=packet['measured'][symbol];short=packet['short'][symbol]
        reception=m['qok']&~packet['quiet'][symbol]['active']&(record['time_s']>=record['start']+300)&(record['time_s']<record['limit']-300)
        result[symbol]=dict(normal_rows=len(record['seq']),own_known=int(short['own']['known'].sum()),
            peer_known=int(short['peer']['known'].sum()),conditions={})
        for cfg in catalog.catalog():
            normal=selection.build(packet,symbol,cfg)
            before=(normal['original_R_event']!=0)&reception
            accepted=(normal['event']!=0)&(normal['entry_families']==2)&reception
            rejected=normal['local_phase_rejected']&reception
            assert int(before.sum())==int(accepted.sum()+rejected.sum())
            result[symbol]['conditions'][cfg['id']]=dict(R受付内基準候補=int(before.sum()),
                R受付内許可=int(accepted.sum()),R受付内拒否=int(rejected.sum()),
                R受付内買=int((accepted&(normal['event']==1)).sum()),R受付内売=int((accepted&(normal['event']==-1)).sum()),
                C受付内=int(((normal['event']!=0)&(normal['entry_families']==1)&reception).sum()),
                追加買取消条件行=int(normal['local_cancel_buy'].sum()),追加売取消条件行=int(normal['local_cancel_sell'].sum()))
    return result


def register() -> dict:
    """
    機能: 準備前に元33場と入力指紋、18数式及び人工合格を固定する。
    引数: なし。小目録/source/人工だけを読む。
    返り値: dictは入力事前固定。大cacheと金融台帳をまだ読まない。
    """
    meta=common.read(SOURCE);art=common.read(ART)
    assert meta['全合格'] and art['全合格'] and len(meta['sessions'])==33
    for name,sha in art['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    for name,sha in meta['source_SHA256'].items():assert common.digest(common.ROOT/name)==sha,name
    plan=dict(全合格=True,sessions=meta['sessions'],cache=meta['cache'],configs=catalog.catalog(),
        input_source_SHA256=sources(),元入力=dict(path=SOURCE.relative_to(common.ROOT).as_posix(),SHA256=common.digest(SOURCE)),
        人工=dict(path=ART.relative_to(common.ROOT).as_posix(),SHA256=common.digest(ART)),
        入力読取='確定range_price33cache各1回。一回の既normal気配/sixから短期位相を算定。旧104/book/APIを読まない。',
        新金融再生=0,原板読取=0,API取得=0)
    common.write(common.HERE/'直近位相の入力事前固定.json',plan)
    return plan


def run() -> None:
    """
    機能: 事前固定した33場を一回だけ準備し、元気配/六点を保持した新cacheを保存する。
    引数: なし。元cacheを同bytesでhashしpickleから読む。
    返り値: None。金融関数を呼ばず、失敗はFalseで保存する。
    """
    assert not TARGET.exists();plan=common.read(common.HERE/'直近位相の入力事前固定.json')
    assert plan['input_source_SHA256']==sources()
    assert common.digest(common.ROOT/plan['元入力']['path'])==plan['元入力']['SHA256']
    caches,activities={},{ }
    try:
        for session in plan['sessions']:
            old=plan['cache'][session];packet=common.unpack(old)
            assert packet['session']==session
            common.immutable(packet)
            packet['short']={symbol:features.build(packet,symbol) for symbol in ('TOPIX','NK225')}
            packet['local_phase_schema_version']=1
            activities[session]=activity(packet)
            path=common.HERE/'input'/f'{session}.pkl.gz';common.write(path,packet)
            caches[session]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path),元入力=old)
            print(session+'：直近位相準備、金融0',flush=True)
            del packet
        assert plan['input_source_SHA256']==sources()
        common.write(TARGET,dict(全合格=True,sessions=plan['sessions'],cache=caches,activity=activities,
            input_source_SHA256=plan['input_source_SHA256'],開始終端source一致=True,
            元range_pricecache読取=33,旧104cache読取=0,新金融再生=0,原板読取=0,API取得=0,
            事前固定SHA256=common.digest(common.HERE/'直近位相の入力事前固定.json'),
            限界=['短期効率は三点sampleで全quote経路ではない。','当行midだけは実normal現在値、相手はstrictpast公表点。',
                '価格代理時計は受信時計ではない。','C量資格/元R RANGE/料金RR/既knownTREND取消は変えない。',
                '取消条件行数は実待機取消数ではなく、候補数は決済勝率ではない。']))
    except BaseException as exc:
        common.write(common.HERE/'直近位相の入力準備失敗.json',dict(全合格=False,例外=repr(exc),完了場=list(caches),新金融再生=0))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='直近位相入力の結果前準備')
    parser.add_argument('--register-only',action='store_true')
    parser.add_argument('--input-preparation-approved',action='store_true')
    args=parser.parse_args();assert args.register_only!=args.input_preparation_approved
    register() if args.register_only else run()
