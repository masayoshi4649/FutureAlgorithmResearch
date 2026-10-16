"""根が一回取得した全NDJSONだけを、未完了Nightとして非金融準備する。"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import socket

import common
import core


ARTIFICIAL=common.HERE/'現ナイト契約確定とC及びsix接続の人工検査.json'
TARGET=common.HERE/'未完了ナイトの入力準備.json'


def sources() -> dict:
    """
    機能: 現在場の接続sourceと結果前固定の依存を登録する。
    引数: なし。
    返り値: dict[str,str]はsource SHA256。本文/旧cacheのhashは含めない。
    """
    design=json.loads((common.HERE/'現ナイトの同パイプライン接続と途中終端の計画.json').read_text(encoding='utf8'))
    paths=[common.ROOT/p for p in design['source_SHA256']]
    paths += [common.HERE/n for n in ('common.py','core.py','prepare.py','artificial.py','states_snapshot.py')]
    paths += [common.HERE.parent/'current_capture/capture.py']
    return {p.relative_to(common.ROOT).as_posix():common.digest(p) for p in paths}


def snapshot(item: dict, symbol: str) -> dict:
    """
    機能: 正常HTTP完結と固定snapshotの場/商品/世代を本文読取前に検査する。
    引数: item(dict)は根が保存した取得情報、symbol(str)は商品。
    返り値: dictは場/世代/asof/受信上限。トレーラー不取得は合格にしない。
    """
    assert item['curl終了コード']==0 and item['HTTP要求回数']==1 and item['自動再試行']==0
    capture=common.module('106現場取得の完結ヘッダー検査だけ',common.HERE.parent/'current_capture/capture.py')
    actual=capture.headers(Path(item['ヘッダー位置']),symbol);assert actual==item['snapshot']
    text=Path(item['ヘッダー位置']).read_bytes().decode('iso-8859-1')
    types=[line.split(':',1)[1].strip() for line in text.splitlines() if line.lower().startswith('content-type:')]
    assert len(types)==1 and types[0].startswith('application/x-ndjson')
    asof=datetime.fromisoformat(actual['as-of'].replace('Z','+00:00'));assert asof.tzinfo is not None
    return dict(session=core.SESSION,code=symbol,generation=actual['generation'],as_of=asof.isoformat(),sequence=int(actual['sequence']))


def run(manifest_path: Path) -> None:
    """
    機能: 一回取得された二商品の本文を各一読取し、途中入力だけを保存する。
    引数: manifest_path(Path)は根の取得情報JSON。
    返り値: None。金融、API再取得、旧33原本/cache再読はしない。
    """
    assert not TARGET.exists();proof=json.loads(ARTIFICIAL.read_text(encoding='utf8'));assert proof['全合格']
    before=sources();assert proof['source_SHA256']==before
    assert manifest_path.resolve()==(common.HERE.parent/'current_capture/取得完了.json').resolve()
    fetched=json.loads(manifest_path.read_text(encoding='utf8'))
    assert fetched['全合格'] and fetched['session']==core.SESSION and fetched['HTTP要求合計']==2
    assert fetched['現セッション取得回数']==1 and set(fetched['symbols'])==set(core.SYMBOLS)
    snapshots={s:snapshot(fetched['symbols'][s],s) for s in core.SYMBOLS}
    assert len({v['generation'] for v in snapshots.values()})==1,'二商品でセッション世代が一致しない'
    extracted={}
    for symbol in core.SYMBOLS:
        item=fetched['symbols'][symbol];path=Path(item['原本位置'])
        assert path.resolve()==(common.HERE.parent/'current_capture/snapshot'/f'{symbol}.jsonl').resolve();before_stat=path.stat()
        with path.open('rb') as stream:extracted[symbol]=core.extract_stream(stream,core.SESSION,symbol)
        after_stat=path.stat();assert (before_stat.st_size,before_stat.st_mtime_ns)==(after_stat.st_size,after_stat.st_mtime_ns)
        diagnostic=extracted[symbol]['diagnosis']
        assert diagnostic['本文bytes']==before_stat.st_size==item['bytes']
        assert diagnostic['本文行数']==snapshots[symbol]['sequence'],'無範囲指定の全履歴件数不一致'
    packet=core.build(extracted);coverage={}
    for symbol in core.SYMBOLS:
        record=packet['prepared'][symbol]['record'];stamps=record['time_s'];start=record['start']
        opening=packet['references'][core.SESSION+'|'+symbol]['ref_open']
        first=int((stamps<=start+300.).sum())
        assert stamps[0]<start+300. and first>=2 and stamps[-1]>=start+300.,'最初5分に正常履歴がない'
        assert opening['known_from_i']==0
        coverage[symbol]=dict(開始=start,通常終了=record['end'],通常limit=record['limit'],
            最初の価格代理時計=float(stamps[0]),最後の価格代理時計=float(stamps[-1]),最初5分normal行数=first,
            開場から初観測までの秒=float(stamps[0]-start),
            始値参照=opening,source_snapshot=snapshots[symbol],原行抽出=extracted[symbol]['diagnosis'],
            予定force前=bool(stamps[-1]<record['limit']-60.))
    normal_cases={c['id']:{s:core.normal(packet,s,c) for s in core.SYMBOLS} for c in core.configs()}
    packet['normal_cases']=normal_cases;packet['configs']=core.configs()
    common.immutable(packet);path=common.HERE/'prepared'/(core.SESSION+'.pkl.gz');sha=common.write(path,packet)
    assert before==sources()
    common.write(TARGET,dict(全合格=True,session=core.SESSION,途中終端=True,finish=False,
        configs=core.configs(),cache=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=sha),
        accounts=coverage,source_SHA256=before,開始終端source一致=True,
        取得manifestSHA256=common.digest(manifest_path),人工SHA256=common.digest(ARTIFICIAL),
        API取得=0,根のAPI取得=2,元book読取=0,旧33cache読取=0,本文各一回読取=2,新金融再生=0,
        会計境界='元limit/end不変更。正式financial指示後もfinish=False、保有/未約定を保持。実現収支とfee込み清算時価/残枚数を別記。'))
    print('現在Nightの一回NDJSON→元C/six/3固定入口準備。金融0',flush=True)


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 入力準備側からAPIや注文の通信を禁止する。
    引数: args(tuple)、kwargs(dict)は通信呼出引数。
    返り値: None。常に例外を発生させる。
    """
    raise RuntimeError('根の保存NDJSONのみを利用。入力側API/注文は許可されていません')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='根の一回取得後だけ未完了現在Nightを準備')
    parser.add_argument('--root-current-input-reviewed',action='store_true',required=True)
    parser.add_argument('--manifest',type=Path,required=True);args=parser.parse_args()
    socket.socket.connect=deny;socket.create_connection=deny
    try:run(args.manifest)
    except BaseException as error:
        path=common.HERE/'現ナイト入力準備False.json'
        if not path.exists():common.write(path,dict(全合格=False,例外=repr(error),自動再取得=False,新金融再生=0,API取得=0))
        raise
