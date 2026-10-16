"""損失アンカー17源の八部品・登録guard・保存GU再利用を小metadataで独立接続する。"""

from pathlib import Path
import ast
import copy
import hashlib
import json
import sys


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_size_loss_anchor'
OLD=ROOT/'work/wave_v106/e01_size_goal_anchor'
sys.dont_write_bytecode=True
sys.path.insert(0,str(SOURCE))
import runner


def read(path: Path) -> dict:
    """
    機能: 事前計画・固定・人工小証跡だけを読取専用で取得する。
    引数: path(Path)は小metadata。
    返り値: dictは保存値。正式結果・packet・ledgerを開かない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: source又は小metadataの指紋を取得する。
    引数: path(Path)は小資料。
    返り値: strはSHA256。正式金融結果には使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(path: Path, name: str) -> ast.FunctionDef:
    """
    機能: 小sourceの対象関数だけを構文として取得する。
    引数: path(Path)、name(str)は小sourceと関数名。
    返り値: FunctionDefは静的構文。関数を金融として実行しない。
    """
    tree=ast.parse(path.read_text(encoding='utf-8'))
    return next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)


# ----------------------------------------
def main() -> None:
    """
    機能: 唯一の経済差・全固定指紋・入力前guard・GU再利用0再実行を独立確認する。
    引数: なし。旧正式結果のSHAは以前の独立監査から引用する。
    返り値: Noneは独立接続証跡。不合格はFalseを保持する。
    """
    target=HERE/'loss_anchor_17源八部品と登録及び保存GU再利用の独立接続.json'
    assert not target.exists()
    plan_path=SOURCE/'試行計画.json';fixed_path=SOURCE/'金融事前固定.json'
    artificial_path=SOURCE/'初回受理の比例損失と回復勝ち喪失及び旧GU同値の人工検査.json'
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))}
    try:
        prepared=read(plan_path);fixed=read(fixed_path);artificial=read(artificial_path)
        assert len(sources)==17 and sources==prepared['spec']['implementation']==fixed['source_SHA256']==artificial['source_SHA256']
        assert prepared['正式freeze'] and fixed['全合格'] and artificial['全合格']
        assert fixed['計画SHA256']==digest(plan_path)
        assert set(prepared['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
        independent_path=HERE/'loss_anchor_比例停止と取消保持及び保存GU復元の独立人工_v2.json'
        independent=read(independent_path);assert independent['全合格']
        for path,sha in independent['source_SHA256'].items():assert sources[path]==sha
        old_fixed=read(OLD/'金融事前固定.json')
        old_proof=read(HERE/'goal_anchor_全264小会計と寄与境界及び最新三基準の独立確認.json')
        old_result='work/wave_v106/e01_size_goal_anchor/finance/結果.json'
        old_sha=old_proof['source_SHA256'][old_result]
        assert old_proof['全合格'] and old_proof['source_SHA256']['work/wave_v106/e01_size_goal_anchor/金融事前固定.json']==digest(OLD/'金融事前固定.json')
        assert fixed['sessions']==prepared['spec']['data']['sessions']==old_fixed['sessions'] and len(fixed['sessions'])==33
        assert fixed['input_cache']==old_fixed['input_cache']==prepared['spec']['data']['保存input33の指紋']
        assert len(fixed['input_cache'])==33
        assert all(v['path'].startswith('work/wave_v106/e01_trade_gate/input/') for v in fixed['input_cache'].values())
        expected_counts=dict(新GUengine=0,保存GU再利用=132,新政策会計=264,旧利確アンカー台帳一読=264,
            既input一読=33,旧risk及びfull台帳読取=0,元paper再計算=0)
        assert prepared['counts']==expected_counts
        clones={}
        for new,old in (('common.py','common.py'),('daily.py','daily.py'),('order_kernel.py','order_kernel.py'),
                        ('policy.py','policy.py'),('engine.py','engine.py'),('baseline.py','baseline.py'),
                        ('data.py','data.py'),('storage.py','storage.py'),('fixed_goal_interface.py','fixed_goal_interface.py'),
                        ('fixed_loss_policy.py','goal_policy.py')):
            assert (SOURCE/new).read_bytes()==(OLD/old).read_bytes()
            clones[(OLD/old).relative_to(ROOT).as_posix()]=digest(OLD/old)
        assert clones==prepared['同bytesコピー']
        # 受理アンカー選択は元goalと構文同値。政策の経済差は損失線だけ。
        assert ast.dump(function(SOURCE/'goal_policy.py','observe_anchor'),include_attributes=False)==ast.dump(function(OLD/'goal_policy.py','observe_anchor'),include_attributes=False)
        apply=function(SOURCE/'goal_policy.py','apply')
        policies=[n for n in ast.walk(apply) if isinstance(n,ast.Call) and ast.unparse(n.func)=='daily.apply_policy']
        assert len(policies)==1
        kwargs=policies[0].args[2];assert isinstance(kwargs,ast.Call) and ast.unparse(kwargs.func)=='dict'
        assert {k.arg:ast.unparse(k.value) for k in kwargs.keywords}=={
            'profit_ticks':"anchor['利益目標円'] / unit",'loss_ticks':"2 * anchor['数量'] / anchor['通常全量']"}
        assert '損失予算=None' in (SOURCE/'goal_policy.py').read_text(encoding='utf-8')
        assert '数量選択へこの縮小線を戻さない' in prepared['spec']['exit']['損失停止線']
        assert prepared['spec']['exit']['新規数量選択予算円']=={'TOPIX':5000,'NK225':2000}
        assert prepared['spec']['exit']['分母']=={'TOPIX':5,'NK225':10}
        assert 'actual_pending==1' in prepared['spec']['management']['系譜'] and '約定無し' in prepared['spec']['management']['アンカー']
        assert '未使用の1/2/3/4槽はNone' in prepared['spec']['data']['GU再利用']
        assert '新engine実行0' in prepared['spec']['data']['GU再利用']
        # 四条件を同母同Pの旧goal台帳へ束縛する。risk/full台帳を比較へ混ぜない。
        configs=fixed['configs'];assert configs==prepared['spec']['entry']['conditions'] and len(configs)==4
        assert {(c['mode'],c['profit_ticks']) for c in configs}=={(m,p) for m in ('CONFIRM','VETO') for p in (1,2)}
        hashes={};all_ledgers=set()
        for config in configs:
            assert config['window_seconds']==60 and config['execution']=='D0' and config['offset_atr']==0
            assert config['risk_atr_multiple']==1 and config['loss_ticks']==2
            assert config['quantity']=={'TOPIX':5,'NK225':10} and config['cap']=={'TOPIX':10,'NK225':20}
            assert config['profit_goal_yen']=={'TOPIX':2500.*config['profit_ticks'],'NK225':1000.*config['profit_ticks']}
            assert config['quantity_selection_budget_yen']==config['loss_stop_base_yen']=={'TOPIX':5000.,'NK225':2000.}
            material=json.dumps(config,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
            hashes[config['id']]=hashlib.sha256(material).hexdigest()
            reference=fixed['comparisons'][config['id']]
            assert reference['id']==config['baseline_id']==f"E01_ANCHOR_W60_{config['mode']}_D0_P{config['profit_ticks']}_L2_A1"
            assert reference['source']==old_result and reference['SHA256']==old_sha
            assert reference['row_count']==reference['ledger_count']==len(reference['rows'])==len(reference['ledgers'])==66
            assert set(reference['ledgers'])=={s+'|'+t for s in fixed['sessions'] for t in ('TOPIX','NK225')}
            assert prepared['spec']['data']['保存比較264の指紋'][config['id']]==reference['ledgers']
            for key,item in reference['ledgers'].items():
                assert item['path'].startswith('work/wave_v106/e01_size_goal_anchor/finance/ledgers/'+config['baseline_id']+'/')
                assert key==item['session']+'|'+item['symbol'];all_ledgers.add(item['path'])
        assert len(all_ledgers)==264 and hashes==fixed['case_SHA256']
        for mode,reference in fixed['旧fullP1L8参考rows'].items():
            old=old_fixed['旧fullP1L8参考rows'][mode]
            assert reference['id']==old['id'] and reference['rows']==old['rows'] and reference['symbols']==old['symbols']
            assert '台帳読取・金融再生無し' in reference['利用範囲']
        for item in prepared['spec']['data']['input_manifests']:
            if item['path']==old_result:assert item['sha256']==old_sha
            else:assert digest(ROOT/item['path'])==item['sha256']
        # ----------------------------------------
        found=[dict(id=prepared['id'],spec=prepared['spec'])]
        runner.registry_guard(found,fixed,prepared);runner.source_scope_guard();variants=[]
        variants.append(('登録無し',[],fixed,prepared));variants.append(('重複登録',found+found,fixed,prepared))
        wrong=copy.deepcopy(found);wrong[0]['id']='旧trial';variants.append(('旧trial',wrong,fixed,prepared))
        wrong=copy.deepcopy(found);wrong[0]['spec']['management']['固定']='後qへ交換';variants.append(('spec不一致',wrong,fixed,prepared))
        changed=copy.deepcopy(fixed);changed['configs'][0]['risk_atr_multiple']=.75;variants.append(('固定条件変更',found,changed,prepared))
        changed=copy.deepcopy(fixed);changed['case_SHA256'][configs[0]['id']]='0'*64;variants.append(('条件指紋変更',found,changed,prepared))
        changed=copy.deepcopy(fixed);changed['source_SHA256'][next(iter(sources))]='0'*64;variants.append(('源指紋変更',found,changed,prepared))
        rejects=[]
        for label,registered,stored,plan in variants:
            try:runner.registry_guard(registered,stored,plan)
            except AssertionError:rejects.append(label)
            else:raise AssertionError('guardが拒否しない:'+label)
        assert len(rejects)==7
        text=(SOURCE/'runner.py').read_text(encoding='utf-8');run=function(SOURCE/'runner.py','run');statements=run.body
        guard=next(i for i,n in enumerate(statements) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='registry_guard')
        private=next(i for i,n in enumerate(statements) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='source_scope_guard')
        denial=next(i for i,n in enumerate(statements) if isinstance(n,ast.Assert) and "'finance'" in ast.get_source_segment(text,n))
        start=next(i for i,n in enumerate(statements) if 'finance/開始.json' in ast.get_source_segment(text,n))
        execute=next(i for i,n in enumerate(statements) if isinstance(n,ast.Try))
        assert guard<private<denial<start<execute
        calls=[n for n in ast.walk(statements[execute]) if isinstance(n,ast.Call)]
        loads=[ast.unparse(n) for n in calls if ast.unparse(n.func)=='data.load']
        assert len(loads)==2 and set(loads)=={"data.load(fixed['input_cache'][session])","data.load(fixed['comparisons'][cid]['ledgers'][key])"}
        assert not any(ast.unparse(n.func) in ('interface.execute','engine.simulate','fixed_goal_interface.execute') for n in calls)
        pairs=[n for n in calls if ast.unparse(n.func)=='reuse.pair'];outputs=[n for n in calls if ast.unparse(n.func)=='interface.account_output']
        assert len(pairs)==len(outputs)==1 and pairs[0].lineno<outputs[0].lineno
        assert ast.unparse(outputs[0].args[-1])=='values'
        reuse_body=function(SOURCE/'reuse.py','pair')
        assert "first['key'] == second['key']" in ast.unparse(reuse_body)
        assert 'np.testing.assert_array_equal(one[index], two[index])' in ast.unparse(reuse_body)
        assert "index in USED" in ast.unparse(reuse_body)
        assert 'finance/False.json' in text and '自動再開始=False' in text
        assert '旧fullP1L8台帳読取・金融再生0' in text
        assert prepared['登録']==prepared['金融']==prepared['大型cache読取']==prepared['原板']==prepared['NPZ']==prepared['API']==0
        assert fixed['正式金融']==fixed['大型input読取']==fixed['旧数量台帳読取']==fixed['旧fullP1L8台帳読取']==0
        assert not (SOURCE/'finance').exists()
        assert sources=={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))}
        proof=dict(全合格=True,source_SHA256=sources,独立source_SHA256=digest(Path(__file__)),
            計画SHA256=digest(plan_path),事前固定SHA256=digest(fixed_path),所有人工SHA256=digest(artificial_path),
            独立人工SHA256=digest(independent_path),八部品一覧=sorted(prepared['spec']),同bytes複写=clones,
            登録guard拒否反例=rejects,固定場=33,新GUengine予定=0,保存GU再利用予定=132,
            新政策会計予定=264,旧goal台帳一読予定=264,旧risk及びfull台帳予定=0,
            再利用範囲=[0,5,6,7,8,9,10],未使用槽=[1,2,3,4],
            再利用資格='同mode・同場・同商品P1/P2の七GU配列をnormal長束縛でexact復元。NaNは同欠測位置のみ同値。',
            比較元SHA取得='以前の独立goal264小会計に保存したSHA。今回旧正式結果JSON・台帳は開かない。',
            留保=['比例損失線は次正常気配の実現損失上限ではない。spreadと実料だけでも即切り得る。',
                  '受理取消保持・後続q変更で停止線の相対尺度が変わる。固定済みの仕様として測る。',
                  '保存GUの再利用は独立試行又は追加の有効性証拠へ数えない。',
                  '同既知33の対照であり、未知データ又は真の物理約定の検証ではない。'],
            正式金融未開始=True,正式金融結果読取=0,packet=0,ledger=0,原板=0,NPZ=0,API=0,金融=0)
        target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,源=17,guard反例=7,SHA256=digest(target)),ensure_ascii=False))
    except BaseException:
        import traceback
        failure=HERE/'loss_anchor_八部品接続False.json';assert not failure.exists()
        failure.write_text(json.dumps(dict(全合格=False,source_SHA256=sources,原因=traceback.format_exc(),
            正式結果=0,packet=0,ledger=0,API=0,金融=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
