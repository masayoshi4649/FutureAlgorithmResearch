"""保存paperと正常気配を接続し、新待機取消に必要な価格列だけを準備する。"""

import argparse
import gc
import hashlib
import pickle
import time
import traceback

import numpy as np

import common
import prices


quiet_module=common.module('106待機取消の不変U休止',common.ROOT/'work/wave_v85/time_filter.py')


def checked(item: dict) -> dict:
    """
    機能: 既保存packetを同bytesで一回読み、登録SHAを確認する。
    引数: item(dict)はroot相対path/SHA256。
    返り値: dictは保存入力。原本やpaper金融を実行しない。
    """
    path=common.ROOT/item['path'];saved=path.read_bytes()
    assert hashlib.sha256(saved).hexdigest()==item['SHA256'],path
    return pickle.loads(common.gzip.decompress(saved))


def register() -> dict:
    """
    機能: 33旧packet・66paper・66基準・全気配と源実装を本文読取前に固定する。
    引数: なし。
    返り値: dictは一回入力準備の固定。新金融の登録とは別に保存する。
    """
    assert not (common.HERE/'入力事前固定.json').exists()
    qmeta=common.read(common.REFERENCE/'prepared/入力準備の完了.json')
    reference=common.read(common.REFERENCE/'結果.json'); old=common.read(common.ROOT/'work/wave_v104/入口準備の全32結果.json')
    day=common.read(common.ROOT/'work/wave_v104/holdout_input/追加Dayの活動と19入口.json')
    art=common.read(common.HERE/'待機指値取消と元注文接続の人工検査.json')
    assert all(x['全合格'] for x in (qmeta,reference,old,day,art))
    for path,wanted in art['実装SHA256'].items():
        assert common.digest(common.ROOT/path)==wanted,path
    sessions=qmeta['全33'];assert len(sessions)==33
    packets={s:dict(day if s==day['session'] else old['cache'][s]) for s in sessions}
    paper={p:h for p,h in reference['紙上SHA256'].items() if p.startswith('paper/')}
    baseline={p:h for p,h in reference['台帳SHA256'].items() if p.startswith('ledgers/L_D20_BBO/')}
    assert len(paper)==len(baseline)==66
    small=[common.REFERENCE/'結果.json',common.REFERENCE/'prepared/入力準備の完了.json',
        common.HERE/'待機指値取消と元注文接続の人工検査.json',
        common.ROOT/'work/wave_v106/e01_pair_filter/UNKNOWN観測定義と原fieldの監査.json',
        common.ROOT/'work/wave_v106/e01_pair_filter/入口状態と保存損益の分類.json']
    value=dict(全合格=True,sessions=sessions,packets=packets,paper=paper,baseline=baseline,
        quotes=dict(path='work/wave_v106/e01_reference/prepared/quotes.pkl',SHA256=qmeta['全気配SHA256']),
        source_SHA256=common.source_hashes(),証跡SHA256={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in small},
        予定読取=dict(旧104=33,保存paper=66,Qpickle=1,基準実台帳=0),新金融=0,原本再読取=0,API=0)
    common.write(common.HERE/'入力事前固定.json',value)
    return value


def volume_gap(raw: dict, previous: int, current: int) -> dict:
    """
    機能: 価格代理時計公表gap中の出来高時計進行を、独立の原seq事実として測る。
    引数: raw(dict)、previous/current(int)は隣接公表原行。
    返り値: dictは時計差の観測。累計出来高増加や受信時計の代理へ変換しない。
    """
    v=raw['volume_time_s'][previous:current+1];p=raw['price_time_s'][previous:current+1]
    known=np.isfinite(v[1:])&np.isfinite(v[:-1]);delta=np.diff(v)
    return dict(価格公表差秒=float(p[-1]-p[0]),開始原seq=int(raw['raw_seq'][previous]),
        終了原seq=int(raw['raw_seq'][current]),原行数=len(v),出来高時計不明=int((~np.isfinite(v)).sum()),
        出来高時計進行回数=int((known&(delta>0)).sum()),出来高時計逆行回数=int((known&(delta<0)).sum()),
        同価格時計中の出来高時計進行回数=int((known&(delta>0)&(np.diff(p)==0)).sum()),
        最大出来高時計進行秒=float(max([0.]+delta[known&(delta>0)].tolist())),
        累計出来高増加の証明=False,受信時計として使用=False)


def run() -> None:
    """
    機能: 旧保存33packetとpaper66を一回ずつ読み、新方向cacheを準備する。
    引数: なし。
    返り値: None。新注文や旧E01の紙上計算は行わない。
    """
    started=time.monotonic();fixed=common.read(common.HERE/'入力事前固定.json')
    assert not (common.HERE/'全33場の待機取消準備.json').exists() and not (common.HERE/'入力失敗.json').exists()
    assert all(common.digest(common.ROOT/p)==h for p,h in fixed['source_SHA256'].items())
    assert all(common.digest(common.ROOT/p)==h for p,h in fixed['証跡SHA256'].items())
    qspec=fixed['quotes'];saved=(common.ROOT/qspec['path']).read_bytes()
    assert hashlib.sha256(saved).hexdigest()==qspec['SHA256'];quotes=pickle.loads(saved);del saved
    oldentry=common.read(common.ROOT/'work/wave_v106/e01_pair_filter/入口状態と保存損益の分類.json')
    caches={};checks=[];volume_cases={}
    try:
        for session in fixed['sessions']:
            packet=checked(fixed['packets'][session])
            if 'peer' in packet:
                packet=packet['peer']
            prepared={s:prices.windows(packet['raw'][s],packet['peer_features'][s]['public'],
                float(packet['items'][s]['tick']),packet['policy'],
                float(packet['normal'][s]['record']['start']),float(packet['normal'][s]['record']['end']))
                for s in ('TOPIX','NK225')}
            result=dict(schema_version=1,session=session,accounts={})
            for symbol in ('TOPIX','NK225'):
                q=quotes[session,symbol];normal=packet['normal'][symbol]['record']
                for name in ('seq','time_s','bid','ask','quote_valid'):
                    np.testing.assert_array_equal(q[name],normal[name],err_msg=name)
                relative=f'paper/{session}_{symbol}.pkl.gz'
                paper=checked(dict(path=(common.REFERENCE/relative).relative_to(common.ROOT).as_posix(),SHA256=fixed['paper'][relative]))
                assert paper['key']==(session,symbol)
                feed=paper['feed'];assert feed.shape[1]==10
                entries=feed[feed[:,7]==1]
                assert np.all(entries[:,4]==(5 if symbol=='TOPIX' else 10))
                for o in entries:
                    assert o[5]==normal['price'][int(o[0])]
                quiet=quiet_module.features(dict(time_s=q['time_s'],last=normal['price']),'U')
                value=prices.account(packet,symbol,prepared)
                value.update(feed=feed,quiet=quiet['active'],quiet_force=quiet['force'],quiet_windows=quiet['windows'],
                    paper_SHA256=fixed['paper'][relative])
                result['accounts'][symbol]=value
                checks.append(dict(session=session,symbol=symbol,正常seq時刻価格気配資格一致=True,
                    紙上公開価格と原正常現在値一致=True,指値源ATR保存値のみ=True,紙上再生=0))
            # ----------------------------------------
            # 旧入口分類の879独立gapへ、時計の別系列事実だけを追加する。
            for entry in (e for e in oldentry['entries'] if e['session']==session):
                for stage,value in entry['stages'].items():
                    for window,measured in value['windows'].items():
                        for role,obs in measured.items():
                            if obs['source'] is None or obs['reference'] is None:
                                continue
                            market=entry['symbol'] if role=='own' else ('NK225' if entry['symbol']=='TOPIX' else 'TOPIX')
                            public=packet['peer_features'][market]['public'];rows=public['rows'];times=public['times']
                            first=int(np.searchsorted(rows,obs['reference']['raw_row'],side='left'))
                            last=int(np.searchsorted(rows,obs['source']['raw_row'],side='left'))
                            for index in range(first+1,last+1):
                                if times[index]-times[index-1]<=15.:
                                    continue
                                a,b=int(rows[index-1]),int(rows[index]);key=(session,market,a,b)
                                if key not in volume_cases:
                                    volume_cases[key]=dict(session=session,symbol=market,**volume_gap(packet['raw'][market],a,b))
            path=common.HERE/f'cache/{session}.pkl.gz';common.write(path,result)
            caches[session]=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=common.digest(path))
            print(session+' 待機価格窓・保存paper接続完了、金融0',flush=True)
            del packet,result,prepared,value
            gc.collect()
        assert len(checks)==66 and len(caches)==33
        assert all(common.digest(common.ROOT/p)==h for p,h in fixed['source_SHA256'].items())
        gaps=list(volume_cases.values());assert len(gaps)==879
        common.write(common.HERE/'価格公表gapと出来高時計の別系列監査.json',dict(全合格=True,
            独立gap数=len(gaps),出来高時計進行あり=sum(g['出来高時計進行回数']>0 for g in gaps),
            同価格時計中に出来高時計進行あり=sum(g['同価格時計中の出来高時計進行回数']>0 for g in gaps),
            出来高時計逆行あり=sum(g['出来高時計逆行回数']>0 for g in gaps),
            出来高時計不明あり=sum(g['出来高時計不明']>0 for g in gaps),gap=gaps,
            時計合成=0,金融=0,原本=0,受信時計転用=False))
        common.write(common.HERE/'全33場の待機取消準備.json',dict(全合格=True,sessions=fixed['sessions'],cache=caches,
            照合=checks,source_SHA256=fixed['source_SHA256'],実装開始終端一致=True,
            入力固定SHA256=common.digest(common.HERE/'入力事前固定.json'),旧104packet読取=33,
            保存paper読取=66,保存基準台帳読取=0,Qpickle読取=1,紙上再生=0,新金融=0,原本再読取=0,API=0,
            経過秒=time.monotonic()-started))
        print('全33場の待機指値入力準備完了。新金融0',flush=True)
    except Exception:
        common.write(common.HERE/'入力失敗.json',dict(全合格=False,原因=traceback.format_exc(),
            完成場=len(caches),新金融=0,自動再実行=False))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='保存E01の待機取消に必要な一回入力準備')
    parser.add_argument('--register-only',action='store_true')
    parser.add_argument('--root-pending-input-reviewed',action='store_true')
    args=parser.parse_args()
    if args.register_only:
        assert not args.root_pending_input_reviewed
        register()
    else:
        assert args.root_pending_input_reviewed,'根の入力source確認後に一度だけ準備'
        run()
