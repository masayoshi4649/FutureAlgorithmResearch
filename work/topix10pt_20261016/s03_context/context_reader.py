"""既S03予兆だけを保存出力から同定し、事後の四分類と因果二対照を集計する。"""

from io import BytesIO
from pathlib import Path
import argparse
import hashlib
import json

import numpy as np

import context_core as core


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
MANIFEST=HERE/'37出力目録の同bytes私有コピー.json'
V2=HERE.parent/'s03_review/根S03小射影v2の同bytes私有コピー.json'
MANIFEST_SHA='a7032ffe67de2de9152bd6b063322d350449d8fdcdbfc53e563085aa78c3a8b9'
V2_SHA='9e5adfa1a76b4af0994b284f5582cb30779f0153ae244ff0177bf1dbe3bb45e1'
PLAN=HERE/'四分類の事後理解と三十七保存出力の一読固定.json'
SOURCES=('context_core.py','artificial_context.py','context_reader.py')
FIELDS=('bars__t_s','bars__valid','bars__open','bars__high','bars__low','bars__close','bars__anchor',
    'bars__pub_raw_row','bars__pub_price_time_s','signals','eligible','target__common_lock_end','target__labels')
RISKS=(2.5,5.,10.)
COUNTS=('順先','逆先','窓末未決','EOF未決','基準不可','n','resolved','全候補順先率','解決内順先率','解決率')


def sha(raw: bytes) -> str:
    """
    機能: 同一読取bytesの指紋を得る。
    引数: raw(bytes)。
    返り値: str はSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


def sources() -> dict:
    """
    機能: この診断専用三源を指紋化する。
    引数: なし。
    返り値: dict[str,str]。原研究十源を変更しない。
    """
    return {name:sha((HERE/name).read_bytes()) for name in SOURCES}


def write(path: Path,value: dict) -> None:
    """
    機能: 所有域へ新規の有限JSONを保存する。
    引数: path(Path)、value(dict)。
    返り値: None。旧証跡・結果を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def small_inputs() -> tuple[dict,dict]:
    """
    機能: 根指定小目録と既読v2の私有コピーだけをSHA付きで読む。
    引数: なし。
    返り値: tuple[dict,dict]。元測定結果やprepared本文を隠れて読まない。
    """
    m=MANIFEST.read_bytes();v=V2.read_bytes()
    assert sha(m)==MANIFEST_SHA and sha(v)==V2_SHA
    return json.loads(m.decode('utf-8')),json.loads(v.decode('utf-8'))


def periods(manifest: dict) -> dict:
    """
    機能: 根の既定分割から指定された六期間だけを作る。
    引数: manifest(dict) は保存小目録。
    返り値: dict[str,list[str]]。成績による期間の選び直しをしない。
    """
    s=manifest['splits']
    assert list(s)==['学習','選択','時系列別枠','追加別枠'] and [len(v) for v in s.values()]==[21,6,6,4]
    whole=sum(s.values(),[]);assert len(set(whole))==37
    return dict(学習21=s['学習'],選択6=s['選択'],別枠6=s['時系列別枠'],追加4=s['追加別枠'],
        別枠10=s['時系列別枠']+s['追加別枠'],全37=whole)


def prepare() -> None:
    """
    機能: 実prepared読取前に目的・列・閾値・窓・読取予算・源を固定する。
    引数: なし。
    返り値: None。根の条件付き授権に従い、この後だけ一読実行できる。
    """
    manifest,v2=small_inputs();groups=periods(manifest)
    outputs=manifest['outputs'];assert len(outputs)==37
    assert [r['session'] for r in outputs]==groups['全37']==[r['session'] for r in v2['by_session']['S03']]
    specs=manifest['specifications'];index=[i for i,row in enumerate(specs) if row['id']=='S03']
    assert len(index)==1 and index[0]<32
    pure=HERE/'四分類と窓境界及び因果二方向の純人工.json'
    art=json.loads(pure.read_text(encoding='utf-8'))
    assert art['全合格'] and art['source_SHA256']=={k:sources()[k] for k in ('context_core.py','artificial_context.py')}
    connection=HERE/'集計と既予兆再同定の純接口人工.json'
    conn=json.loads(connection.read_text(encoding='utf-8'))
    assert conn['全合格'] and conn['source_SHA256']==sources()
    write(PLAN,dict(目的='既158件のS03が過去21場と後16場で変わった理由を事後に理解。新入口/再選択/金融0。',
        解釈='閾値は成績を見た後に立てた根指定の説明仮説。未知検証・独立な有効性証拠ではない。',
        条件=dict(A='当時確定t−19..tの20足high最大−low最小>=10pt',
            B='当時確定t−59..tの60足high最大−low最小>=20pt',
            C='t−20..t21足完備、S03方向×(close_t−close_t−20)>=2.5pt',
            D='S03方向×(公開anchor−当時までの最初valid足open)>=2.5pt。D途中空足では基準openをresetしない。'),
        未知='A/B/Cは全窓valid連続必須。Dは現在valid/anchor/最初openが既知必須。未知はfalseにしない。',
        因果対照='始値比sign(anchor−最初open)、20分差sign(close_t−close_t−20)。非零knownだけの同じS03群をsaved target両sideで比較。known zero/unknownは別に数える。',
        採用='保存signalsのS03/eligible/共通±10lockから元の同じ選択行だけ再構成し、37場全risk/買売/固定方向を既小射影へ完全照合。',
        期間=groups,逆行幅=list(RISKS),S03index=index[0],S03仕様=specs[index[0]],
        目録SHA256=MANIFEST_SHA,既v2私有copySHA256=V2_SHA,source_SHA256=sources(),純人工SHA256=sha(pure.read_bytes()),
        純接口人工SHA256=sha(connection.read_bytes()),
        必要配列=list(FIELDS),保存出力=outputs,
        読取予算=dict(新preparedNPZ='37件各一回。同bytes保全後必要13配列だけdecode。',元raw=0,
            元measurement結果=0,原event=0,新測定=0,金融=0,API=0),
        禁止='四条件は別々にtrue/false/unknown集計。AND/OR総当たり/最良条件選択/新戦略収支/元研究源変更なし。'))
    print(json.dumps(dict(準備合格=True,計画SHA256=sha(PLAN.read_bytes()),実prepared=0),ensure_ascii=False))


def selected(arrays: dict,index: int) -> tuple[np.ndarray,np.ndarray]:
    """
    機能: 保存された同一S03の共通lock選択だけを独立に再構成する。
    引数: arrays(dict)、index(int) は必要保存列とS03列。
    返り値: tuple[int64[K],int8[K]] は既予兆足と方向。新しい予兆は作らない。
    """
    signal=arrays['signals'][:,index];eligible=arrays['eligible'];pub=arrays['bars__pub_raw_row']
    lock=arrays['target__common_lock_end'];n=len(signal)
    assert arrays['signals'].dtype==np.int8 and arrays['signals'].shape==(n,32)
    assert eligible.dtype==bool and eligible.shape==pub.shape==lock.shape==(n,)
    assert pub.dtype==lock.dtype==np.int64 and np.isin(signal,(-1,0,1)).all()
    result=[];until=-1
    for row in range(n):
        if eligible[row] and signal[row]!=0 and pub[row]>until:
            assert pub[row]>=0 and lock[row]>=pub[row]
            result.append(row);until=int(lock[row])
    rows=np.array(result,np.int64)
    return rows,signal[rows].copy()


def verify_account(arrays: dict,rows: np.ndarray,sides: np.ndarray,saved: dict,index: int) -> None:
    """
    機能: 保存済み各場S03の三幅・方向・固定買売・候補数へ再構成行を照合する。
    引数: arrays(dict)、rows/sides(ndarray)、saved(dict)、index(int)。
    返り値: None。先着そのものは再計算しない。
    """
    target=arrays['target__labels'];n=len(arrays['bars__valid'])
    assert target.dtype==np.int8 and target.shape==(n,2,3)
    assert np.isin(target,(-2,-1,0,1,2)).all()
    side_index=(sides<0).astype(int)
    assert saved['採用予兆数']==len(rows) and saved['買い数']==int(np.count_nonzero(sides==1))
    assert saved['売り数']==int(np.count_nonzero(sides==-1))
    assert saved['公開候補数']==int(np.count_nonzero(arrays['eligible']&(arrays['signals'][:,index]!=0)))
    for ri,risk in enumerate(RISKS):
        own=target[rows,side_index,ri]
        for name,labels in (('全体',own),('買い',own[sides==1]),('売り',own[sides==-1]),
                           ('常時買い',target[rows,0,ri]),('常時売り',target[rows,1,ri])):
            expected=core.count(labels);actual=saved['risks'][ri] if name=='全体' else saved['risks'][ri][name]
            assert actual.get('逆行幅',risk)==risk
            assert all(expected[key]==actual[key] for key in COUNTS)


def aggregate(records: list[dict],sessions: list[str]) -> dict:
    """
    機能: 同じ既予兆の四独立分類と二因果対照を期間別に加算する。
    引数: records(list[dict]) は既158行の小観測、sessions(list[str]) は対象期間。
    返り値: dict は分子分母と未知/ゼロの除外内訳。欠測先着を補完しない。
    """
    own=[r for r in records if r['session'] in sessions]
    def rates(items: list[dict],field: str='labels') -> list[dict]:
        """
        機能: 同一群の三保存ラベルを幅別に加算する。
        引数: items(list[dict])、field(str)。
        返り値: list[dict] は三幅の件数/率。
        """
        return [dict(逆行幅=risk,**core.count(np.array([r[field][ri] for r in items],np.int8))) for ri,risk in enumerate(RISKS)]
    classes={}
    for condition in core.CONDITIONS:
        classes[condition]={}
        for state in ('true','false','unknown'):
            subset=[r for r in own if r['classes'][condition]==state]
            classes[condition][state]=dict(n=len(subset),買い数=sum(r['side']==1 for r in subset),
                売り数=sum(r['side']==-1 for r in subset),risks=rates(subset))
        assert sum(row['n'] for row in classes[condition].values())==len(own)
    comparisons={}
    for label,field in (('始値比方向','start'),('20分差方向','twenty')):
        usable=[r for r in own if r['controls'][field]['known'] and r['controls'][field]['side']!=0]
        zero=sum(r['controls'][field]['known'] and r['controls'][field]['side']==0 for r in own)
        unknown=sum(not r['controls'][field]['known'] for r in own)
        baseline=[dict(labels=r['controls'][field]['labels']) for r in usable]
        assert len(usable)+zero+unknown==len(own)
        comparisons[label]=dict(比較群n=len(usable),既知ゼロ方向除外=zero,未知除外=unknown,
            S03と同方向=sum(r['side']==r['controls'][field]['side'] for r in usable),
            S03と反対方向=sum(r['side']!=r['controls'][field]['side'] for r in usable),
            S03同群= rates(usable),対照同群=rates(baseline))
    return dict(場数=len(sessions),予兆数=len(own),S03= rates(own),条件=classes,因果対照=comparisons)


def run() -> None:
    """
    機能: 計画とpure検査の固定後、37保存出力各一読で既158件の事後理解を測る。
    引数: なし。
    返り値: None。元研究再測定や原入力・金融を使用しない。
    """
    fixed=json.loads(PLAN.read_text(encoding='utf-8'));assert fixed['source_SHA256']==sources()
    manifest,v2=small_inputs();assert manifest['outputs']==fixed['保存出力']
    original=v2['source']['source_SHA256']
    assert all(sha((ROOT/path).read_bytes())==hash_value for path,hash_value in original.items())
    saved={row['session']:row for row in v2['by_session']['S03']}
    records=[];read=[];final=HERE/'S03既158予兆の四分類と因果二対照の集計.json'
    assert not final.exists()
    for info in fixed['保存出力']:
        path=(ROOT/info['path']).resolve()
        assert path.is_relative_to((HERE.parent/'measurement/prepared').resolve())
        assert path.stat().st_size==info['bytes']
        raw=path.read_bytes();assert len(raw)==info['bytes'] and sha(raw)==info['SHA256']
        copy=HERE/'prepared_copies'/path.name;copy.parent.mkdir(exist_ok=True);assert not copy.exists();copy.write_bytes(raw)
        read.append(dict(session=info['session'],path=info['path'],SHA256=info['SHA256']))
        with (HERE/'保存出力の一読履歴.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps(read[-1],ensure_ascii=False)+'\n')
        with np.load(BytesIO(raw),allow_pickle=False) as archive:
            assert set(archive.files)==set(info['arrays']) and set(FIELDS).issubset(archive.files)
            arrays={name:archive[name] for name in FIELDS}
        for name,value in arrays.items():
            meta=info['arrays'][name];assert str(value.dtype)==meta['dtype'] and list(value.shape)==meta['shape']
        rows,sides=selected(arrays,fixed['S03index'])
        verify_account(arrays,rows,sides,saved[info['session']],fixed['S03index'])
        bars={name.removeprefix('bars__'):value for name,value in arrays.items() if name.startswith('bars__')}
        assert np.all(bars['valid'][rows]) and np.isfinite(bars['anchor'][rows]).all()
        contexts=core.classify(bars,rows,sides);target=arrays['target__labels']
        for i,(row,side) in enumerate(zip(rows,sides)):
            controls={}
            for field,k,d in (('start','start_known','control_start'),('twenty','twenty_known','control_twenty')):
                known=bool(contexts[k][i]);direction=int(contexts[d][i])
                controls[field]=dict(known=known,side=direction,
                    labels=target[row,0 if direction>0 else 1].tolist() if known and direction else None)
            records.append(dict(session=info['session'],bar_row=int(row),pub_raw_row=int(bars['pub_raw_row'][row]),
                t_s=float(bars['t_s'][row]),side=int(side),labels=target[row,0 if side>0 else 1].tolist(),
                classes={condition:core.STATE_NAMES[int(contexts['classes'][i,ci])] for ci,condition in enumerate(core.CONDITIONS)},
                values={condition:float(contexts['values'][i,ci]) if np.isfinite(contexts['values'][i,ci]) else None
                    for ci,condition in enumerate(core.CONDITIONS)},controls=controls))
        del arrays,raw
    assert len(read)==37 and len(records)==158
    summary={label:aggregate(records,sessions) for label,sessions in fixed['期間'].items()}
    assert all(sha((ROOT/path).read_bytes())==hash_value for path,hash_value in original.items())
    assert fixed['source_SHA256']==sources()
    write(final,dict(全合格=True,解析計画SHA256=sha(PLAN.read_bytes()),目録SHA256=MANIFEST_SHA,
        根小射影v2SHA256=V2_SHA,source_SHA256=sources(),研究十源不変更=original,
        読取=read,periods=summary,records=records,既S03予兆=158,
        prepared読取=37,元raw=0,元測定結果=0,新測定=0,金融=0,API=0,
        留保='結果後の説明仮説による既158行の内訳。四分類は独立集計でAND/最良探索0。因果対照も同時点の既予兆をsaved targetで比較しただけ。新戦略収支・未知有効性・完全価格テープの先着ではない。'))
    print(json.dumps(dict(全合格=True,SHA256=sha(final.read_bytes()),prepared読取=37,S03既予兆=158),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('prepare','run'));args=parser.parse_args()
    prepare() if args.mode=='prepare' else run()
