"""入口確認と元玉・保険の追跡幅を分離し、同じ保存板で比較する。"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np
import numba

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0,str(ROOT/'work/wave_v70'))
SPEC = importlib.util.spec_from_file_location('旧管理会計71',ROOT/'work/wave_v70/study.py')
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)
engine,net = OLD.engine,OLD.net
numba.config.CACHE_DIR = str(HERE/'numba_cache')
SOURCES,SYMBOLS,FIELDS = OLD.SOURCES,OLD.SYMBOLS,OLD.FIELDS
account,aggregate = OLD.account,OLD.aggregate


def load(path: Path) -> object:
    """機能: 今回又は既存の保存資料を読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix=='.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path, value: object) -> None:
    """機能: 新作業領域だけへ保存し、原本と過去成果を保護する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.suffix=='.pkl':
        path.write_bytes(pickle.dumps(value,protocol=pickle.HIGHEST_PROTOCOL))
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def catalog() -> list[dict]:
    """機能: 結果閲覧前に6入口・4確認・6幅・3管理の432設定を作る。

    引数: なし。返り値: 設定一覧(list[dict])。
    """
    original = next(c for c in OLD.catalog() if c['id']=='T2L0_H03')
    widths = [(8.,4.,8.,4.),(16.,4.,8.,4.),(8.,8.,8.,4.),
              (16.,8.,8.,4.),(24.,12.,8.,4.),(16.,8.,16.,8.)]
    width_names = ['従来幅','元玉だけ2倍','保険だけ2倍','両方2倍','両方3倍','両方2倍・開始も2倍']
    configs = []
    for i,source in enumerate(SOURCES):
        for gate in range(4):
            for width,(core,cover,active,ca) in enumerate(widths):
                prefix = f'{source}_G{gate}_W{width}'
                base = dict(original,source=source,source_index=i,gate_level=gate,entry_index=i*4+gate,
                            width_id=f'W{width}',width_name=width_names[width],trail=core,cover_trail=cover,
                            activation=active,cover_activation=ca,manager=f'G{gate}_W{width}')
                for method in ('H','N','D'):
                    c = dict(base,id=prefix+'_'+method,method=method,paired=method=='N',kind=0 if method=='D' else 1,
                             name={'H':'段階保険の両建て','N':'同判断の縮小復帰','D':'同条件の保険なし'}[method],
                             group={'H':'保険両建て','N':'縮小復帰','D':'無保険対照'}[method])
                    c['paired_manager'] = prefix+'_H'
                    configs.append(c)
    assert len(configs)==432
    return configs


def material() -> tuple:
    """機能: 既知28場と追加デイを別保存から接続する。

    引数: なし。返り値: 価格入力・板特徴(tuple[dict,dict])。
    """
    ready = load(ROOT/'work/wave_v69/prepared/inputs.pkl')
    features = load(ROOT/'work/wave_v69/prepared/features.pkl')
    extra = HERE/'prepared/extra_inputs.pkl'
    if extra.exists():
        r,f = load(extra),load(HERE/'prepared/extra_features.pkl')
        assert not set(r)&set(ready)
        ready.update(r);features.update(f)
    return ready,features


def freeze() -> None:
    """機能: 新損益の再生前に条件・入口・評価・追加場の分離を固定する。

    引数: なし。返り値: なし(None)。既存固定を上書きしない。
    """
    assert not (HERE/'事前固定.json').exists()
    old = load(ROOT/'work/wave_v70/事前固定.json')
    paths = [Path(__file__),HERE/'select.py',ROOT/'work/wave_v70/study.py',ROOT/'work/wave_v70/engine.py',ROOT/'work/wave_v70/net.py',
             HERE/'inputs/signals.pkl',HERE/'inputs/schedule.pkl',HERE/'inputs/入口確認の事前固定.json',
             HERE/'inputs/core.py',ROOT/'work/wave_v69/prepared/inputs.pkl',ROOT/'work/wave_v69/prepared/features.pkl']
    paths += sorted((HERE/'prepared').glob('extra_*.pkl'))
    save(HERE/'事前固定.json',dict(条件=catalog(),全セッション=old['全セッション'],前16=old['前16'],後12=old['後12'],
        追加追試=['2026-10-09_Day'],入口='6入口部品×4確認、source*4+gateの24系列。候補行だけで許可、後からの成功ラベルは使用しない。',
        比較='各source/Gで幅W0〜W5とH/N/Dは同じ初回列。G別は入口列が変わる。入口強化のみ・幅のみ・同時変更を対照で切り分ける。',
        枚数={'TOPIX':10,'NK225':20},幅単位={'TOPIX':.5,'NK225':10.},
        料金='TOPIXmini41.8円、NK225micro11円、片道1枚、注文合計切捨て。買ask売bid、次有効行fill。',
        入口診断='実新規気配から±8/16参照ラージ呼値の先着。60分holdでは打ち切らず場内返済期限まで。全件分母で未到達も別表示。未来ラベルは検証専用。',
        選定='前16のみ。Hの入口強化G1/G2＋幅拡大W1〜W5から両銘柄20組・8活動場以上、弱い銘柄の1組平均手数料後呼値を最大化。両黒字かつ両平均勝組／負組>1なら有望。最低数を満たすものがなければ、両銘柄1組以上の中で件数と非採用を明記した説明例だけを選ぶ。',
        相手同期='G3は約定時計における1秒遅延・同秒先頭観測・古さ5秒以内の参考比較。共通受信時計がないため受信順の完全同期は証明不能。主選定から除外する。',
        反実仮想='選定Hと同じsourceでG0_W0、選定G_W0（入口だけ）、G0_選定W（幅だけ）、選定G_選定W、およびN/Dを同時比較。',
        既知性='前28は既知。追加10/09デイは本作業の条件と選定に使わず全432へ固定適用する追試。未知の収益性を証明するものではない。',
        限界='ラージ気配をミニ/マイクロに代用。受信時刻でなく約定時計。通信・深さ・取消・実商品の板は未再現。',
        損失枠='元玉stop32・全玉損失枠32・最長60分・grid8・追加約25%は全条件固定。保険は利益限定の合計トレールで、保険単独stopを追加していない。',
        事前に変更しない='入口確認と幅を広げる効果だけを調べる。結果を見て閾値・保険stop・入口数閾値・選定を変更しない。',
        API取得=0,実注文=0,SHA256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}))


def arguments(config: dict, key: tuple, ready: dict, features: dict, signals: dict, schedule: dict) -> tuple:
    """機能: 24入口と既存エンジンを接続する。

    引数: config/ready/features/signals/schedule(dict)、key(tuple)。返り値: エンジン引数(tuple)。
    """
    r,f = ready[key],features[key]
    cap,value,fee = (10,1000.,41.8) if key[1]=='TOPIX' else (20,10.,11.)
    j = config['entry_index']
    return (r['time_s'],f['bid'],f['ask'],signals[key][j],schedule[key][j],r['tick'],r['limit'],cap,value,fee,
            *[config[name] for name in FIELDS])


def periods(rows: list[dict], fixed: dict) -> dict:
    """機能: 前半・後半・全既知28・追加追試を混ぜず集計する。

    引数: rows(list[dict])、fixed(dict)。返り値: 期間別会計(dict)。
    """
    return {p:{s:aggregate(rows,s,keys) for s in SYMBOLS} for p,keys in
            [('前16',fixed['前16']),('後12',fixed['後12']),('全28',fixed['全セッション']),('追加1',fixed['追加追試']),
             ('全29',fixed['全セッション']+fixed['追加追試'])]}


def run(source: str) -> None:
    """機能: 一つの入口のH/Dと同判断Nを全58口座で保存再生する。

    引数: source(str)、空なら全入口。返り値: なし(None)。
    """
    fixed = load(HERE/'事前固定.json')
    ready,features = material()
    signals,schedule = load(HERE/'inputs/signals.pkl'),load(HERE/'inputs/schedule.pkl')
    assert set(ready)==set(signals)==set(features)==set(schedule) and len(ready)==58
    for h in [c for c in fixed['条件'] if c['method']=='H' and (not source or c['source']==source)]:
        configs = [c for c in fixed['条件'] if c['id'].rsplit('_',1)[0]==h['id'].rsplit('_',1)[0]]
        if all((HERE/'results'/(c['id']+'.json')).exists() for c in configs):
            continue
        rows={m:[] for m in ('H','N','D')};ledgers={m:{} for m in rows}
        d = next(c for c in configs if c['method']=='D')
        for key in sorted(ready):
            args = arguments(h,key,ready,features,signals,schedule)
            orders,trades,curve,counters = engine.simulate(*args)
            rows['H'].append(account(key,ready,orders,trades,curve,counters))
            ledgers['H'][key]=dict(orders=orders,trades=trades,counters=counters,curve_hash=hashlib.sha256(curve.tobytes()).hexdigest(),paired_metadata=None)
            original = float(curve[-1])
            no,nt,nc,nm=net.pair(args[0],args[1],args[2],orders,args[7],args[8],args[9])
            assert abs(float(nc[-1])-original-nm['終了群の理論節約合計円'])<1e-5
            rows['N'].append(account(key,ready,no,nt,nc,nm))
            ledgers['N'][key]=dict(orders=no,trades=nt,counters=nm,curve_hash=hashlib.sha256(nc.tobytes()).hexdigest(),paired_metadata=nm)
            do,dt,dc,dk=engine.simulate(*arguments(d,key,ready,features,signals,schedule))
            rows['D'].append(account(key,ready,do,dt,dc,dk))
            ledgers['D'][key]=dict(orders=do,trades=dt,counters=dk,curve_hash=hashlib.sha256(dc.tobytes()).hexdigest(),paired_metadata=None)
        for c in configs:
            m=c['method'];path=HERE/'ledgers'/(c['id']+'.pkl');save(path,ledgers[m])
            save(HERE/'results'/(c['id']+'.json'),dict(config=c,rows=rows[m],periods=periods(rows[m],fixed),ledger_SHA256=hashlib.sha256(path.read_bytes()).hexdigest()))
        print(h['id'].rsplit('_',1)[0],'H/N/D・58口座完了',flush=True)


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存再生からの通信を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、RuntimeErrorを発生する。
    """
    raise RuntimeError('保存再生からの通信は禁止')


def main() -> None:
    """機能: 事前固定又は指定入口の再生を実行する。

    引数: --freeze(bool)、--source(str)。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--source',default='')
    args=parser.parse_args();socket.socket.connect=deny;socket.create_connection=deny
    if args.freeze:
        freeze();print('432条件と追加1場の分離を事前固定しました')
    else:
        run(args.source)


if __name__=='__main__':
    main()
