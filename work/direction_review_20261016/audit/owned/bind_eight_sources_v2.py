"""非金融方向採点の八源を、独立oracleとmain代替接続へ束縛する。"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import traceback

import numpy as np

from independent_oracle import fixture

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]
ROOT=BASE.parents[1]
CHECKS=0


def check(value: bool,detail: object) -> None:
    """
    機能: SOURCE_ONLYの判定を数える。
    引数: value(bool)、detail(object)。
    返り値: None。
    """
    global CHECKS
    CHECKS+=1
    assert value,detail


def sha(path: Path) -> str:
    """
    機能: 小sourceと監査証跡だけの指紋を求める。
    引数: path(Path)。
    返り値: str SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str,path: Path):
    """
    機能: 自動実行しない純sourceを読む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def extract(name: str,namespace: dict) -> object:
    """
    機能: measureの関数だけを人工依存へ接続する。
    引数: name(str)、namespace(dict)。
    返り値: object 関数。実moduleのmainを勝手に起動しない。
    """
    node=next(n for n in ast.parse((BASE/'measure.py').read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(BASE/'measure.py'),'exec'),namespace)
    return namespace[name]


def aggregate_check(engine,aggregate) -> None:
    """
    機能: 六状態分母・方向対照・率の再加算を独立に検算する。
    引数: engine/aggregate(module)。
    返り値: None。
    """
    status={1:'favorable_first',-1:'adverse_first',0:'price_cut',2:'eof',3:'window_end',-2:'entry_unavailable'}
    for symbol in ('TOPIX','NK225'):
        for side in (1,-1):
            a,s,p=fixture(symbol,side,[0,0,2,2,4,4,8,8,12,12],(1,3,5,9))
            measured=engine.measure(a,s,symbol,0.,2000.,.5 if symbol=='TOPIX' else 10.,p)
            account=aggregate.account(symbol,'合成_Day',measured)
            check(len(account['cells'])==108 and len(account['profiles'])==36,'十八条件の参考群/方向切分け')
            for cell in account['cells']:
                ri=('A','B','C').index(cell['rule']);wi=(.0005,.001,.002).index(cell['width_fraction'])
                oi=('公開mid','次行新規・費用後気配').index(cell['origin'])
                chosen=measured['eligible'][:,ri] if cell['group']=='全候補' else measured['nonoverlap'][:,ri]
                direction=s['events'][:,s['fields'].index('d')]
                if cell['direction']!='全体':chosen=chosen&(direction==(1 if cell['direction']=='買い' else -1))
                values=measured['labels'][chosen,wi,oi]
                counts={name:sum(int(v)==code for v in values) for code,name in status.items()}
                check(all(cell[k]==v for k,v in counts.items()) and cell['n']==len(values),'六状態の分母')
                solved=counts['favorable_first']+counts['adverse_first']
                check(cell['resolved']==solved and cell['favorable_rate_resolved']==(counts['favorable_first']/solved if solved else None),'解決分母の率')
                check(cell['favorable_rate_all']==(counts['favorable_first']/len(values) if len(values) else None),'未解決を含む全分母の率')
                if oi==0:
                    physical=[int(v)*int(d) if abs(int(v))==1 else int(v) for v,d in zip(values,direction[chosen])]
                    for label,sign in (('常時買い',1),('常時売り',-1)):
                        lab=[sign*v if abs(v)==1 else v for v in physical]
                        check(all(cell['baseline'][label][name]==sum(v==code for v in lab) for code,name in status.items()),'同経路の固定方向対照')
                else:check(cell['baseline'] is None,'清算気配の対照をmid符号で捏造しない')
    check(aggregate.PRIMARY==dict(rule='C',group='非重複',width_fraction=.001,origin='公開mid',direction='全体'),'主評価を後選択しない')


def freeze_and_guard(plan,fixed: dict,source: dict) -> None:
    """
    機能: 八部品builderと登録前guardを合成metadataだけへ接続する。
    引数: plan(module)、fixed/source(dict)。
    返り値: None。正式固定・登録は行わない。
    """
    audit=dict(全合格=True,新金融=0,source_SHA256=source,evidence=[]);generated={}
    def write(path: Path,value: dict) -> None:
        """
        機能: builderのJSONをメモリへ捕捉する。
        引数: path(Path)、value(dict)。
        返り値: None。
        """
        generated[path.name]=json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))
    ns=dict(HERE=BASE,ROOT=ROOT,TRIAL=plan.TRIAL,WIDTHS=plan.WIDTHS,RULES=plan.RULES,PRIMARY=plan.PRIMARY,
        CAP=plan.CAP,MULTIPLIER=plan.MULTIPLIER,FEE=plan.FEE,read=lambda p:fixed if p.name=='入力と保存公開の固定.json' else audit,
        sources=lambda:source,digest=lambda p:'1'*64,write=write,registration_inputs=plan.registration_inputs,json=json)
    node=next(n for n in ast.parse((BASE/'plan.py').read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='freeze')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(BASE/'plan.py'),'exec'),ns);ns['freeze']()
    proposal=generated['試行計画.json'];frozen=generated['実測前の正式固定.json']
    check(proposal['spec']['entry']['rules']==['A','B','C'] and proposal['spec']['exit']['幅率']==[.0005,.001,.002],'3×3×2十八条件')
    check(proposal['spec']['management']['主評価']==plan.PRIMARY==proposal['主評価'],'主評価の内外一致')
    check(proposal['spec']['implementation']==source and len(source)==8,'八sourceのflatmap')
    check('quiet/force' in proposal['spec']['execution']['非金融参照'],'次行価格参照は実取引取消と別で固定')
    duplicate=load('方向採点の既存checker純呼出',ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py')
    check(duplicate.analyze(proposal,[])['proposal_complete'] is True,'既存checkerへ十八条件の完備')
    table={'実測前の正式固定.json':frozen,'試行計画.json':proposal,'実測前の人工と独立監査.json':audit,'入力と保存公開の固定.json':fixed,
           '正式照合の全出力.json':dict(終了コード=0,stdout=json.dumps({'proposal_complete':True})),
           '正式登録の全出力.json':dict(終了コード=0),'trials.json':dict(trials=[dict(id=plan.TRIAL,spec=copy.deepcopy(proposal['spec']))])}
    stub=SimpleNamespace(HERE=BASE,ROOT=ROOT,TRIAL=plan.TRIAL,WIDTHS=plan.WIDTHS,RULES=plan.RULES,PRIMARY=plan.PRIMARY,CAP=plan.CAP,
        sources=lambda:source,read=lambda p:table[p.name],digest=lambda p:'1'*64,registration_inputs=plan.registration_inputs)
    gn=dict(OUT=SimpleNamespace(exists=lambda:False),plan=stub,json=json)
    guard=extract('guard',gn);check(guard()[0] is fixed,'原入力前の合成guard完了')
    original=copy.deepcopy(table)
    for label,mutate in (
        ('対象session違い',lambda t:t['試行計画.json']['spec']['data'].update(sessions=[])),
        ('三幅違い',lambda t:t['試行計画.json']['spec']['exit'].update(幅率=[.1])),
        ('rule違い',lambda t:t['試行計画.json']['spec']['entry'].update(rules=['C'])),
        ('主評価の違い',lambda t:t['試行計画.json'].update(主評価={})),
        ('不完備照合',lambda t:t['正式照合の全出力.json'].update(stdout=json.dumps({'proposal_complete':False}))),
        ('登録終了1',lambda t:t['正式登録の全出力.json'].update(終了コード=1)),
        ('源違い',lambda t:t['実測前の正式固定.json'].update(source_SHA256={})),
    ):
        table.clear();table.update(copy.deepcopy(original));mutate(table)
        table['trials.json']['trials'][0]['spec']=copy.deepcopy(table['試行計画.json']['spec'])
        failed=False
        try:guard()
        except AssertionError:failed=True
        check(failed,label)


def main_wiring(plan,engine,aggregate,contract) -> None:
    """
    機能: 実mainを66人工配列へ通し、rules/origins接口と一回読取を確認する。
    引数: plan/engine/aggregate/contract(module)。
    返り値: None。rootの実入力・registry・measurement出力はアクセスしない。
    """
    oldroot=ROOT/'work/quantity_execution_20261015/audit/root'
    sys.path.insert(0,str(oldroot))
    from check_contract_plan_v2 import make_source_fixture
    producer=load('方向診断の人工producer',oldroot/'指定二源と生成元の私有複製/producer.py')
    schema,raw,fields,events,start,end=make_source_fixture(producer);end+=3600.
    sessions=[f'合成{i:02d}_'+('Day' if i%2==0 else 'Night') for i in range(33)]
    inputs=[dict(raw=dict(session=s,symbol=y,path=s+y,bounds=[start,end]),events=dict(path=s+y+'event',n=2),fields=fields,raw_rows=6,
        time_policy=dict(entry_start_s=start,entry_end_s=end-600,force_start_s=end-300,quiet_windows=[])) for s in sessions for y in ('TOPIX','NK225')]
    fixed=dict(inputs=inputs,schema=schema,sessions=sessions,観測T=dict(TOPIX=.5,NK225=10.))
    expected=dict(原NPZ=66,保存eventNPZ=66,非金融測定口座=66,新金融=0,原板=0,API=0)
    loaded=[];saved=[];captured={};calls=[]
    class Out:
        """実ファイルへ接続しない出力位置。"""
        def __init__(self,name='人工measurement'):
            """
            機能: 合成名を保持する。
            引数: name(str)。
            返り値: None。
            """
            self.name=name
        def __truediv__(self,name):
            """
            機能: 合成子位置を返す。
            引数: name(str)。
            返り値: Out。
            """
            return Out(self.name+'/'+name)
        def mkdir(self):
            """
            機能: 実書込をしない。
            引数: self(Out)。
            返り値: None。
            """
            return None
    def loader(info,counts,label,keys=None):
        """
        機能: 原本の代わりにproducer人工配列だけを一回返す。
        引数: info/counts(dict)、label(str)、keys(tuple|None)。
        返り値: dict 人工配列。
        """
        check(keys is None if label=='原NPZ' else keys==('events',),'未来配列をdecodeしない呼出')
        loaded.append((info['path'],label));counts[label]+=1
        return {k:v.copy() for k,v in raw.items()} if label=='原NPZ' else dict(events=events.copy())
    def measure(*args):
        """
        機能: 極小の人工経路だけを実engineへ渡す。
        引数: args(tuple) 人工のmeasure引数。
        返り値: dict 純採点。実市場の測定ではない。
        """
        calls.append(args[2]);check(set(args[1])=={'events','fields','price_valid_mask'},'未来ラベル無しのengine引数')
        return engine.measure(*args)
    def save(value,path):
        """
        機能: 保存予定を数え、実NPZを作らない。
        引数: value(dict)、path(Out)。
        返り値: dict 合成目録。
        """
        check(value['labels'].shape==(2,3,2),'十八条件接口')
        saved.append(path.name);return dict(path=path.name,SHA256='1'*64,bytes=1)
    ns=dict(plan=SimpleNamespace(sources=plan.sources,write=lambda p,v:captured.update({p.name:v}),WIDTHS=plan.WIDTHS,RULES=plan.RULES,PRIMARY=plan.PRIMARY,TRIAL=plan.TRIAL),
        OUT=Out(),guard=lambda:(fixed,dict(実行予定=expected,source_SHA256=plan.sources())),load_once=loader,input_contract=contract,
        engine=SimpleNamespace(measure=measure),aggregate=aggregate,save_observations=save,np=np,json=json,print=lambda *a,**k:None)
    extract('main',ns)()
    result=captured['人工measurement/方向予測の採点結果.json']
    check(len(loaded)==len(set(loaded))==132 and len(calls)==len(saved)==66,'66原+66event/66人工口座/金融0の全main接口')
    check(result['counts']==expected and len(result['accounts'])==66 and len(result['metadata'])==66,'保存metadataまで到達')
    for symbol in ('TOPIX','NK225'):
        full=result['combined']['symbols'][symbol]['periods']['全33']['primary']
        accounts=[a for a in result['accounts'] if a['symbol']==symbol]
        for key in ('favorable_first','adverse_first','price_cut','eof','window_end','entry_unavailable','n','resolved'):
            check(full[key]==sum(a['primary'][key] for a in accounts),'場率平均でなく分子分母を加算')
    json.dumps(result,ensure_ascii=False,allow_nan=False);check(True,'全main payloadがJSON原始型へ保存可能')


def main() -> None:
    """
    機能: 八源と独立証跡を一つの署名へ束縛する。
    引数: なし。
    返り値: None。原NPZ/event/金融/大registry本文は読まない。
    """
    output=HERE/'独立_source監査.json';proof=dict(全合格=False,実入力本文=0,原NPZ=0,保存event本文=0,新金融=0,旧金融=0,API=0)
    try:
        plan=load('八源の計画定義',BASE/'plan.py');source=plan.sources();check(len(source)==8,'八源集合')
        private=HERE/'八源接続の私有複製';private.mkdir(exist_ok=True)
        for name in plan.SOURCE_NAMES:(private/name).write_bytes((BASE/name).read_bytes())
        sys.path.insert(0,str(private));import engine,aggregate,input_contract
        prior_path=HERE/'三幅二起点と共通非重複の独立逐行oracle.json'
        prior=json.loads(prior_path.read_text(encoding='utf-8'));check(prior['全合格'],'逐行oracle合格')
        for name,digest in prior['source_SHA256'].items():check(source[(BASE/name).relative_to(ROOT).as_posix()]==digest,'完成二源不変')
        check(sha(BASE/'input_contract.py')==sha(plan.OLD/'input_contract.py'),'旧115入力契約を同bytes継承')
        fixed=json.loads((BASE/'入力と保存公開の固定.json').read_text(encoding='utf-8'))
        check(sha(BASE/'入力と保存公開の固定.json')==sha(plan.OLD/'入力と保存公開の固定.json'),'旧33小目録を同bytes再利用')
        aggregate_check(engine,aggregate);freeze_and_guard(plan,fixed,source);main_wiring(plan,engine,aggregate,input_contract)
        evidence=[]
        for path in (prior_path,BASE/'三値幅二起点と共通非重複及び保存統合の人工検査.json',BASE/'方向採点の分母と非重複及び固定方向対照の純人工_v2.json',BASE/'結線の人工検証.json'):
            value=json.loads(path.read_text(encoding='utf-8'));check(value['全合格'],'現完成証拠')
            mapping=value.get('source_SHA256',value.get('対象指紋',{}))
            for name,digest in mapping.items():
                key=name if '/' in name else (BASE/name).relative_to(ROOT).as_posix()
                check(source[key]==digest,('証拠の現八源接続',name))
            evidence.append(dict(path=path.relative_to(ROOT).as_posix(),SHA256=sha(path)))
        check(source==plan.sources(),'監査中の八源不変更')
        proof.update(全合格=True,source_SHA256=source,接続確認数=CHECKS,独立逐行確認数=prior['確認数'],独立素材数=48,独立接頭数=144,evidence=evidence,
            独立源_SHA256=sha(Path(__file__)),
            契約修正='測定前にrule_names/origin_namesへmain接口を統一し、登録sessions/rules/幅/主評価のguardを追加。実市場本文読取前の修正。',
            判定上の留保='①公開midと②次行仮参照は別。②はquiet/force取消を再現せず実新規可否/勝率ではない。MFEは事後、幅/rule/方向/参考群を独立標本に数えない。',
            正式経路='合成fixed/登録でのguardとメモリbuilderは確認。実際のfreeze/check/register/市場測定はrootの後続で、この監査は実施0。',
            checker訂正='初版はexecution.非金融参照をmanagement下にあると誤認したKeyError。archive/留保文の部品位置を誤認したcheckerFalseへ源とFalseを保全し、参照先だけを訂正。市場の源8不変更。')
    except BaseException:
        proof.update(接続確認数=CHECKS,失敗=traceback.format_exc());raise
    finally:
        output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps({k:proof.get(k) for k in ('全合格','接続確認数','失敗')},ensure_ascii=False))


if __name__=='__main__':main()
