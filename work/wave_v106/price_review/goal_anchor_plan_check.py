"""正式15sourceの八部品・登録guardと独立アンカー人工を小metadataだけで接続する。"""

from pathlib import Path
import ast
import copy
import hashlib
import json
import sys


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_size_goal_anchor'
OLD=ROOT/'work/wave_v106/e01_risk_sizing'
sys.dont_write_bytecode=True
sys.path.insert(0,str(SOURCE))
import runner


def read(path: Path) -> dict:
    """
    機能: 計画・固定・人工小JSONだけを読取専用で取得する。
    引数: path(Path)は小metadata。
    返り値: dictは保存値。正式金融結果・packet・ledgerを読まない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: source又は小metadataの指紋を取得する。
    引数: path(Path)はsource・小metadata。
    返り値: strはSHA256。正式金融結果のファイルには使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 最終15sourceと八部品、初回受理人工、登録・私有JITguardを独立固定する。
    引数: なし。正式金融結果は既独立証跡のSHA参照に限定する。
    返り値: Noneは最終接続証跡。正式金融の実行はrootへ留保する。
    """
    target=HERE/'goal_anchor_最終15源八部品と登録及び受理人工の独立接続.json'; assert not target.exists()
    plan_path=SOURCE/'試行計画.json'; fixed_path=SOURCE/'金融事前固定.json'; artificial_path=SOURCE/'初回受理目標と未約定取消及び旧数量同値の人工検査_v3.json'
    prepared=read(plan_path); fixed=read(fixed_path); artificial=read(artificial_path)
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))}
    assert len(sources)==15 and sources==prepared['spec']['implementation']==fixed['source_SHA256']==artificial['source_SHA256']
    assert prepared['正式freeze'] and fixed['全合格'] and artificial['全合格'] and fixed['計画SHA256']==digest(plan_path)
    assert set(prepared['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
    independent_path=HERE/'goal_anchor_最初受理と取消保持及び接頭停止の独立人工.json'; independent=read(independent_path)
    assert independent['全合格']
    for p,sha in independent['source_SHA256'].items(): assert sources[p]==sha
    # ----------------------------------------
    # 固定値だけで旧入力33と旧数量4比較へ束縛。正式結果JSONや台帳bytesは再読しない。
    old_fixed=read(OLD/'金融事前固定.json')
    old_audit=read(HERE/'risk_sizing_全264小会計と792寄与及び最新三基準の独立検算.json')
    old_finance_name='work/wave_v106/e01_risk_sizing/finance/結果.json'
    old_sha=old_audit['source_SHA256'][old_finance_name]
    assert fixed['sessions']==prepared['spec']['data']['sessions']==old_fixed['sessions'] and len(fixed['sessions'])==33
    assert fixed['input_cache']==old_fixed['input_cache']==prepared['spec']['data']['保存input33の指紋']
    assert len(fixed['input_cache'])==33 and all(v['path'].startswith('work/wave_v106/e01_trade_gate/input/') for v in fixed['input_cache'].values())
    assert prepared['counts']==dict(新GUengine=132,新政策会計=264,旧数量台帳一読=264,既input一読=33,旧fullP1L8台帳読取=0,元paper再計算=0)
    clones={}
    for new,old in (('common.py','common.py'),('daily.py','daily.py'),('order_kernel.py','order_kernel.py'),
                    ('policy.py','policy.py'),('engine.py','engine.py'),('baseline.py','baseline.py'),
                    ('data.py','data.py'),('storage.py','storage.py'),('fixed_goal_interface.py','interface.py')):
        assert (SOURCE/new).read_bytes()==(OLD/old).read_bytes()
        clones[(OLD/old).relative_to(ROOT).as_posix()]=digest(OLD/old)
    assert prepared['同bytesコピー']==clones
    configs=fixed['configs']; assert configs==prepared['spec']['entry']['conditions'] and len(configs)==4
    assert {(c['mode'],c['profit_ticks']) for c in configs}=={(mode,profit) for mode in ('CONFIRM','VETO') for profit in (1,2)}
    hashes={}
    for config in configs:
        assert config['window_seconds']==60 and config['execution']=='D0' and config['offset_atr']==0 and config['risk_atr_multiple']==1 and config['loss_ticks']==2
        assert config['quantity']=={'TOPIX':5,'NK225':10} and config['cap']=={'TOPIX':10,'NK225':20}
        assert config['profit_goal_yen']=={'TOPIX':2500.*config['profit_ticks'],'NK225':1000.*config['profit_ticks']}
        assert config['loss_budget_yen']=={'TOPIX':5000.,'NK225':2000.}
        material=json.dumps(config,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
        hashes[config['id']]=hashlib.sha256(material).hexdigest()
        ref=fixed['comparisons'][config['id']]
        assert ref['id']==config['baseline_id'] and ref['source']==old_finance_name and ref['SHA256']==old_sha
        assert ref['row_count']==ref['ledger_count']==len(ref['rows'])==len(ref['ledgers'])==66
        assert set(ref['ledgers'])=={r['session']+'|'+r['symbol'] for r in ref['rows']}
        assert prepared['spec']['data']['保存比較264の指紋'][config['id']]==ref['ledgers']
    assert hashes==fixed['case_SHA256']
    for mode,ref in fixed['旧fullP1L8参考rows'].items():
        old_id=next(c['baseline_id'] for c in configs if c['mode']==mode and c['profit_ticks']==1)
        old_ref=old_fixed['comparisons'][old_id]['旧P1L8']
        assert ref['id']==old_ref['id'] and ref['rows']==old_ref['rows'] and ref['symbols']==old_ref['symbols']
        assert '台帳読取・金融再生無し' in ref['利用範囲']
    skipped=[]
    for item in prepared['spec']['data']['input_manifests']:
        if item['path']==old_finance_name:
            assert item['sha256']==old_sha; skipped.append(item['path'])
        else: assert digest(ROOT/item['path'])==item['sha256']
    assert skipped==[old_finance_name]
    # ----------------------------------------
    # 実guardに合成登録を渡す。源・catalog・全項目指紋の不一致はinputを読む前に拒否する。
    found=[dict(id=prepared['id'],spec=prepared['spec'])]
    runner.registry_guard(found,fixed,prepared); runner.source_scope_guard(); rejects=[]
    variants=[]
    variants.append(('登録無し',[],fixed,prepared)); variants.append(('重複登録',found+found,fixed,prepared))
    wrong=copy.deepcopy(found); wrong[0]['id']='旧trial'; variants.append(('旧trial',wrong,fixed,prepared))
    wrong=copy.deepcopy(found); wrong[0]['spec']['management']['固定']='後qへ再選択'; variants.append(('spec不一致',wrong,fixed,prepared))
    changed=copy.deepcopy(fixed); changed['configs'][0]['risk_atr_multiple']=.75; variants.append(('固定条件変更',found,changed,prepared))
    changed=copy.deepcopy(fixed); changed['case_SHA256'][configs[0]['id']]='0'*64; variants.append(('条件指紋変更',found,changed,prepared))
    changed=copy.deepcopy(fixed); changed['source_SHA256'][next(iter(sources))]='0'*64; variants.append(('源指紋変更',found,changed,prepared))
    for label,candidates,stored,plan in variants:
        try: runner.registry_guard(candidates,stored,plan)
        except AssertionError: rejects.append(label)
        else: raise AssertionError('guardが拒否しない:'+label)
    assert len(rejects)==7
    text=(SOURCE/'runner.py').read_text(encoding='utf-8'); tree=ast.parse(text); run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    statements=run.body
    guard=next(i for i,n in enumerate(statements) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='registry_guard')
    private=next(i for i,n in enumerate(statements) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='source_scope_guard')
    denial=next(i for i,n in enumerate(statements) if isinstance(n,ast.Assert) and "'finance'" in ast.get_source_segment(text,n))
    start=next(i for i,n in enumerate(statements) if 'finance/開始.json' in ast.get_source_segment(text,n))
    execute=next(i for i,n in enumerate(statements) if isinstance(n,ast.Try))
    assert guard<private<denial<start<execute
    calls=[n for n in ast.walk(statements[execute]) if isinstance(n,ast.Call) and ast.unparse(n.func)=='data.load']
    assert len(calls)==2 and {ast.unparse(n) for n in calls}=={"data.load(fixed['input_cache'][session])","data.load(fixed['comparisons'][cid]['ledgers'][key])"}
    assert '旧fullP1L8台帳読取・金融再生0' in text and 'finance/False.json' in text and '自動再開始=False' in text
    assert '各条件全字段' not in text and '各条件の全項目' in text
    assert prepared['spec']['exit']['分母']=={'TOPIX':5,'NK225':10} and prepared['spec']['exit']['損失不変']=={'TOPIX':5000,'NK225':2000}
    assert '約定無し' in prepared['spec']['management']['アンカー'] and 'actual_pending==1' in prepared['spec']['management']['系譜']
    assert prepared['登録']==prepared['金融']==prepared['大型cache読取']==prepared['原板']==prepared['NPZ']==prepared['API']==0
    assert fixed['正式金融']==fixed['大型input読取']==fixed['旧数量台帳読取']==fixed['旧fullP1L8台帳読取']==0
    assert not (SOURCE/'finance').exists()
    assert sources=={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))}
    proof=dict(全合格=True,source_SHA256=sources,独立source_SHA256=digest(Path(__file__)),
        計画SHA256=digest(plan_path),事前固定SHA256=digest(fixed_path),所有人工v3SHA256=digest(artificial_path),独立人工SHA256=digest(independent_path),
        八部品一覧=sorted(prepared['spec']),同bytes複写=clones,登録guard拒否反例=rejects,
        固定場=33,GU共有予定=132,政策会計予定=264,旧数量比較予定=264,旧fullP1L8台帳予定=0,
        比較元結果SHA取得='以前の独立264小監査に保存したSHAで束縛。今回正式金融結果JSONは開かない。',
        表記是正='非日本語の全字段を全項目に訂正したv3/最終源だけに束縛。経済9源は独立人工と同SHA。',
        留保=['初回受理は初回実約定と異なる。取消後も目標を保持する仕様を確認済み。',
              '比例目標は損失を保証せず、黒字平均低下による補填力悪化も次の金融で測る。',
              'GU suffixは診断だけで、停止後を実政策の利益へ足さない。'],
        正式金融未開始=True,正式金融結果読取=0,packet=0,ledger=0,原板=0,NPZ=0,API=0,金融=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,源=15,guard反例=7,SHA256=digest(target)),ensure_ascii=False))


if __name__=='__main__': main()
