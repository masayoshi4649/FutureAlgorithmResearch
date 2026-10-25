"""複数ロールの仮説を事前登録し、既知47場と保留3場を分けて比較する。"""

import argparse
import copy
import hashlib
import importlib.util
import json
import pickle
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'work/tranche139_20261022'
PUBLIC = ROOT/'アルゴリズム調査/00140_参加機会の拡大と商品別戦略の再検証'
sys.path.insert(0,str(OLD))
import common139 as common
import prepare_extra139 as sources
import active140
import reentry140


def read(path):
    """
    機能: UTF-8の保存資料を読む。
    引数: path(Path)は読取位置。
    返り値: dict/listは保存内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    """
    機能: 今回作業の証跡を新規保存する。
    引数: path(Path)、value(dict/list)は保存先と内容。
    返り値: None。既存結果は上書きしない。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)


def ref(path):
    """
    機能: 内容指紋とリポジトリ内の相対位置を結ぶ。
    引数: path(Path)は既存資料。
    返り値: dictはpathとsha256。
    """
    path=Path(path)
    with path.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=digest)


def settings():
    """
    機能: 利確後再参加の対照を事前固定する。
    引数: なし。
    返り値: list[dict]は12条件。
    """
    changes=[('押し戻り確認・2枚',{}),('待ち時間だけの対照',dict(entry_mode='delay')),
        ('浅い押し戻り',dict(pullback_r=.25)),('深い押し戻り',dict(pullback_r=1.)),
        ('支持30秒',dict(support_hold_seconds=30.)),('準備2時間',dict(expiry_seconds=7200.)),
        ('同一利益後に最大2回',dict(max_reentries=2)),('利益追尾を早める',dict(trail_start_r=1.,trail_width_r=.5)),
        ('1枚で参加',dict(quantity=1)),('5枚で参加',dict(quantity=5)),
        ('停止を広げる',dict(stop_r=1.5,quantity=1)),('補完利益後も再参加',dict(core_only=False))]
    out=[]
    for name,change in changes:
        c=reentry140.defaults();c.update(change);c.update(id=f'R{len(out)+1:02d}',name=name);out.append(c)
    return out


def prepare():
    """
    機能: 入口から会計までの仕様と全入力を金融再生前に登録する。
    引数: なし。
    返り値: None。既存の試行照合ツールを使い、結果は小さい要約へ保存する。
    """
    known=read(HERE/'known_manifest140.json');new=read(HERE/'inputs/input_manifest.json')
    implementation=sources.source_fingerprints()
    for path in [HERE/'active140.py',HERE/'reentry140.py',Path(__file__),OLD/'common139.py',OLD/'engine139.py',
                 OLD/'early139.py',ROOT/'work/visual_pdca129_20261020/features129.py']:
        item=ref(path);implementation[item['path']]=item['sha256']
    configs=dict(active=active140.configurations(),reentry=settings())
    plan=dict(id='140_商品別の参加拡大と利益後再参加',name='時間禁止と内部波待機を分離する参加改善',purpose='条件比較',
        question='時間を短くするだけでなく、新たな需要供給の証拠と実利益完結から再参加すれば、活動と安定性を両立できるか。',
        change='旧139の短ATRと固定新規通知を主改善対象とせず、広い過去帯を基準に6機構を実玉の停止・追尾・再準備まで逐次計算。利益後再参加も別状態として検証。',
        repeat_reason='旧139は朝と米前の機構が異なり、早期の追加玉が悪化源。旧135の利確後の内部波待機を、利益後の新しい押戻りで解除する機構は未測。商品専用を許可。',
        compares_to=['139_朝と米国前の早期参加','139_複数追撃と初回待機と再追加'],configs=configs,
        spec=dict(entry={'積極担当':configs['active'],'再参加':configs['reentry'],
            '公開':'確定一分終値の60秒後、相手原行は厳密過去15秒以内。未確定足は不使用。'},
            management={'実玉':'停止・利益追尾・追加・連続負け時待機を原行ごと更新。',
                '併用':'両担当の仮想状態を独立に進め、判断時に他親を実保有していれば新規親ごと見送り。未来の通常新規を見て早めに返済しない。',
                '既存':'B5は旧139保存通知を再利用。Go本体との全行同値検証ではない。'},
            exit={'場内':'limitで判断し次正常BBO。保留3場の終端不成立はゼロへ補完せず失敗とする。',
                '幅':'準備時Rを固定。現行当時5分ATR/過去帯半幅/8呼値の最大。追加は初回の固定リスク予算内。'},
            allocation={'商品':['NK225mini','TOPIXmini'],'片方向上限':10,'通常初回':5,'積極初回':2,
                '積極上限':[2,5],'研究の目的':'活動量・損失の深さ・黒字場・大勝ち依存を銘柄別に比較。'},
            costs={'片道十倍手数料':{'NK225mini':385,'TOPIXmini':418},'倍率':{'NK225mini':100,'TOPIXmini':1000},'丸め':'各約定注文単位1円未満切捨て'},
            execution={'模型':'判断後の次正常ラージBBO。買ask/売bid、ミニ実約定と区別。','最大枚数':'新規予約と保有を逐次拘束。'},
            data={'sessions':known['sessions']+new['sessions'],
                'input_manifests':[ref(HERE/'known_manifest140.json'),ref(HERE/'inputs/input_manifest.json'),ref(HERE/'moved_materials140.json')],
                '選択':'旧47場で候補固定。新3場は固定候補のみ一回採点、結果後の変更は別開発とする。'},
            implementation=implementation),evidence=[ref(HERE/'オプション保存資格140.json')])
    save(HERE/'試行計画140.json',plan)
    manager=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec=importlib.util.spec_from_file_location('manager140',manager);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    checked=mod.check(plan)
    save(HERE/'照合140.json',dict(proposal_complete=checked['proposal_complete'],matches=[{k:v for k,v in x.items() if k in ('id','kind','name')} for x in checked['matches']]))
    assert checked['proposal_complete']
    registered=mod.store_trial(plan)
    save(HERE/'登録140.json',dict(returncode=0,id=registered['id'],plan=ref(HERE/'試行計画140.json')))
    print('事前登録完了',flush=True)


def joined(base, addon):
    """
    機能: 各担当の仮想判断を進めたまま、空き時点で先着した親を実玉として採用する。
    引数: base/addon(ndarray)は因果的に生成した十列通知。
    返り値: ndarrayは十列実約定。先の退出時刻は当時の保有状態を判定する以外に使わない。
    """
    queue=[];active_until=-1;out=[]
    for role,orders in enumerate((base,addon)):
        for pid in np.unique(orders[:,2]) if len(orders) else []:
            rows=orders[orders[:,2]==pid].copy()
            if role:rows[:,2]+=3_000_000
            queue.append((int(rows[0,1]),role,rows))
    for decision,role,rows in sorted(queue,key=lambda x:(x[0],x[1])):
        if decision < active_until:
            continue
        out.append(rows);active_until=int(rows[-1,0])
    orders=np.concatenate(out) if out else np.empty((0,10))
    return orders[np.argsort(orders[:,0],kind='stable')] if len(orders) else orders


def account(orders,packet,symbol,method,split):
    """
    機能: 約定から利益損失と活動量を独立再集計する。
    引数: orders(ndarray)、packet(dict)、symbol/method/split(str)は原行・対象・検証区分。
    返り値: dictは場別金額・初回時刻・保有時間・数量。未清算は例外。
    """
    key=packet['session'],symbol;r=packet['inputs'][key];q=packet['quotes'][key];t=r['time_s']
    result=common.account(orders,t,q,method,key[0],symbol)
    result.pop('parents');result['split']=split
    entry=orders[orders[:,7]==1]
    result['first_minutes']=float((t[int(entry[0,0])]-r['start'])/60.) if len(entry) else None
    elapsed=0.;held=0;previous=float(t[0]);peak=0.;cash=0.;dd=0.
    for row in orders:
        now=float(t[int(row[0])]);elapsed+=(now-previous) if held else 0.
        held+=int(row[4]) if row[7] else -int(row[4]);previous=now
    assert held==0
    result['held_minutes']=elapsed/60.
    valid=q['quote_valid'] & np.isfinite(q['bid']) & np.isfinite(q['ask']) & (q['ask']>q['bid'])
    indexes=np.flatnonzero(valid)
    mid=(q['bid']+q['ask'])/2.
    result['market_change']=float(mid[indexes[-1]]-mid[indexes[0]])
    return result


def baseline(packet, symbol, cache):
    """
    機能: 旧結果を再利用し、追加場のみ元の金融核で通常担当を生成する。
    引数: packet(dict)、symbol(str)、cache(dict)は原入力と既存会計目録。
    返り値: ndarrayはmini5枚を基準としたB5の十列通知。
    """
    key=packet['session'],symbol
    if key in cache:
        item=cache[key]
        assert ref(ROOT/item['path'])['sha256']==item['sha256']
        with np.load(ROOT/item['path']) as f:return f['B5'].copy()
    original=sources.source_orders(packet,symbol)
    inputs=common.features129.prices_for(packet,'mid');markets=common.features129.markets(inputs)
    config=next(c for c in common.configs() if c['id']=='B5')
    return common.replay(inputs[key],packet['quotes'][key],markets[key],common.phases(inputs[key]),
                         original['core_orders'],original['extra_orders'],config,symbol)[0]


def run(additional=False):
    """
    機能: 旧47場で比較し、保留3場は選択済み固定候補だけを採点する。
    引数: additional(bool)は保留3場の指定。
    返り値: None。各約定と会計を所有域へ保存し、現在APIは使わない。
    """
    plan=read(HERE/'試行計画140.json');assert read(HERE/'登録140.json')['returncode']==0
    for path,sha in plan['spec']['implementation'].items():assert ref(ROOT/path)['sha256']==sha,path
    cache={(x['session'],x['symbol']):x for folder in ('results','extra_results') for x in read(OLD/folder/'結果.json')['cache']}
    manifest=read(HERE/('inputs/input_manifest.json' if additional else 'known_manifest140.json'))
    selected=read(HERE/'固定候補140.json') if additional else None
    if additional:sources.authorize_sources(HERE/'試行計画140.json',HERE/'登録140.json')
    folder=HERE/('new' if additional else 'known');rows=[];files=[]
    for item in manifest['packets']:
        path=Path(item['path']);path=path if path.is_absolute() else ROOT/path
        assert ref(path)['sha256']==item['sha256']
        packet=pickle.loads(path.read_bytes());scene=packet['session'];arrays={s:{} for s in ('NK225','TOPIX')}
        for symbol in arrays:arrays[symbol]['B5']=baseline(packet,symbol,cache)
        inp=common.features129.prices_for(packet,'mid');market=common.features129.markets(inp)
        for config in plan['configs']['reentry']:
            for symbol in arrays:
                if additional and config['id'] not in selected[symbol]:continue
                key=scene,symbol;r=packet['inputs'][key]
                c=dict(config,**common.product(symbol))
                orders,notes=reentry140.replay(r['time_s'],packet['quotes'][key],r['atr'],market[key],arrays[symbol]['B5'],r['limit'],c)
                arrays[symbol][c['id']]=orders
        for window in (10,20,40):
            configs=[c for c in plan['configs']['active'] if c['window']==window]
            if additional and not any(c['id'] in selected[s] or 'C'+c['id'][1:] in selected[s] for c in configs for s in arrays):continue
            prepared=active140.prepare(packet,window)
            for c in configs:
                for symbol in arrays:
                    combination='C'+c['id'][1:]
                    if additional and c['id'] not in selected[symbol] and combination not in selected[symbol]:continue
                    orders,curve=active140.replay(prepared[symbol],c)
                    arrays[symbol][c['id']]=orders
                    arrays[symbol][combination]=joined(arrays[symbol]['B5'],orders)
        for symbol,content in arrays.items():
            if additional:content={k:v for k,v in content.items() if k=='B5' or k in selected[symbol]}
            for method,orders in content.items():rows.append(account(orders,packet,symbol,method,'保留3場' if additional else '既知47場'))
            dest=folder/'measurement'/f'{symbol}_{scene}.npz';dest.parent.mkdir(parents=True,exist_ok=True)
            assert not dest.exists();np.savez_compressed(dest,**content);files.append(dict(session=scene,symbol=symbol,**ref(dest)))
        print(scene,'完了',flush=True)
    save(folder/'結果140.json',dict(rows=rows,cache=files,plan=ref(HERE/'試行計画140.json'),API=0,real_orders=0))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','known','new']);args=p.parse_args()
    prepare() if args.stage=='prepare' else run(args.stage=='new')
