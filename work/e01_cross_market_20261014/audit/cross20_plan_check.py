"""正式20源・八部品・保存GU66及び四入口264の一回接続を金融前に静的確認する。"""

from pathlib import Path
import ast
import copy
import hashlib
import json
import sys


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=HERE.parent/'engine'
sys.dont_write_bytecode=True
sys.path.insert(0,str(SOURCE))
import runner


def read(path: Path) -> dict:
    """
    機能: 固定計画・人工・既独立監査の小JSONだけを取得する。
    引数: path(Path)は明示小metadata。
    返り値: dictは保存値。金融結果・packet・大台帳は開かない。
    """
    assert '/finance/' not in path.as_posix()
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: sourceと非金融小metadataの指紋を取得する。
    引数: path(Path)は小資料。
    返り値: strはSHA256。旧金融結果のbytesは再読しない。
    """
    assert '/finance/' not in path.as_posix()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 正式20源・十六条件・八部品と、登録/一読/旧同値/失敗保持の接続を独立確認する。
    引数: なし。根が金融を開始する前にだけ実行する。
    返り値: Noneは自所有小証跡。登録・新金融・共有資料の変更を行わない。
    """
    target=HERE/'正式20源八部品と一回1056会計及び登録guardの独立接続.json';assert not target.exists()
    plan_path=SOURCE/'試行計画.json';fixed_path=SOURCE/'金融事前固定.json'
    owner_path=SOURCE/'十六対照と実行前拒否及び表示会計の人工検査.json'
    prepared=read(plan_path);fixed=read(fixed_path);owner=read(owner_path)
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))}
    assert len(sources)==20 and sources==prepared['spec']['implementation']==fixed['source_SHA256']==owner['source_SHA256']
    assert prepared['正式freeze'] and fixed['全合格'] and owner['全合格'] and fixed['計画SHA256']==digest(plan_path)
    assert digest(owner_path)=='0bcefa429002e7b60781440cea6eb5c5b7089b69237507f53812546cbcb24f28'
    independent_path=HERE/'十六条件の純円尺度と五入口価格時計及び全feed数量の独立人工_v2.json'
    independent=read(independent_path);assert independent['全合格'] and independent['source_SHA256']==sources
    old_stats_path=HERE/'同一E01の両商品差と再利用及び事後選択の敵対監査.json'
    old_stats=read(old_stats_path);assert old_stats['全合格']
    old_result='work/wave_v106/e01_size_goal_anchor/finance/結果.json'
    old_sha=old_stats['source_SHA256'][old_result]
    cause_path=HERE.parent/'diagnosis/同母二商品差の診断固定計画.json';cause=read(cause_path)
    assert set(prepared['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
    assert len(fixed['configs'])==16 and fixed['configs']==prepared['spec']['entry']['conditions']
    assert fixed['sessions']==prepared['spec']['data']['sessions']==cause['sessions'] and len(fixed['sessions'])==33
    assert fixed['input_cache']==prepared['spec']['data']['input_cache']==cause['input_cache']
    assert fixed['baseline']['ledgers']==prepared['spec']['data']['baseline_ledger_manifest']
    assert len(fixed['baseline']['rows'])==len(fixed['baseline']['ledgers'])==66
    assert fixed['baseline']['id']==runner.catalog.BASELINE_ID==old_stats['条件']
    assert fixed['baseline']['source']==old_result and fixed['baseline']['SHA256']==old_sha
    assert set(fixed['baseline']['ledgers'])=={s+'|'+p for s in fixed['sessions'] for p in ('TOPIX','NK225')}
    for key,ref in cause['active_ledgers'].items():assert fixed['baseline']['ledgers'][key]==ref
    for symbol in ('TOPIX','NK225'):
        before=[r for r in fixed['baseline']['rows'] if r['symbol']==symbol]
        assert before==old_stats['保存全場'][symbol]
    expected=dict(新条件=16,保存GU再利用=66,新GUengine=264,新政策会計=1056,旧P1台帳一読=66,既input一読=33,旧基準経済同値確認=66)
    assert prepared['予定']==expected and runner.EXPECTED=={k:v for k,v in expected.items() if k!='新条件'}
    clones=runner.plan.clones();assert clones==prepared['同bytesコピー'] and len(clones)==7
    hashes=runner.case_hashes(fixed['configs']);assert hashes==fixed['case_SHA256']
    for path,sha in sources.items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
    for item in prepared['spec']['data']['input_manifests']:
        if item['path']==old_result:assert item['sha256']==old_sha
        else:assert digest(ROOT/item['path'])==item['sha256']
    # 同じ既知33の診断後に係数を選ぶ探索。未知の成功という読み替えを拒否する。
    assert '43親' in prepared['change'] and '原板/NPZ/現在API0' in prepared['spec']['data']['読取']
    assert '実現・発動前部分返済' in prepared['spec']['management']['清算'] and '親事後最大益を使わない' in prepared['spec']['management']['清算']
    assert '旧GU66は追加有効性証拠に数えず' in prepared['spec']['data']['再利用']
    assert '場の以後新規なし' in prepared['spec']['exit']['不変']
    assert 'peerend時計strict<t' in prepared['spec']['execution']['C端点'] and '最後normal' in prepared['spec']['execution']['C端点']
    assert '真受信時刻ではない' in prepared['spec']['execution']['限界']
    # ----------------------------------------
    found=[dict(id=prepared['id'],spec=prepared['spec'])]
    runner.registry_guard(found,fixed,prepared);runner.source_scope_guard();rejected=[]
    variants=[('未登録',[],fixed,prepared),('重複登録',found+found,fixed,prepared)]
    bad=copy.deepcopy(found);bad[0]['id']='旧trial';variants.append(('別trial',bad,fixed,prepared))
    bad=copy.deepcopy(found);bad[0]['spec']['management']['アンカー']='後のピークq';variants.append(('spec差',bad,fixed,prepared))
    bad=copy.deepcopy(fixed);bad['configs'][0]['target_multiple']=.3;variants.append(('catalog差',found,bad,prepared))
    bad=copy.deepcopy(fixed);bad['case_SHA256'][fixed['configs'][0]['id']]='0'*64;variants.append(('casehash差',found,bad,prepared))
    bad=copy.deepcopy(fixed);bad['source_SHA256'][next(iter(sources))]='0'*64;variants.append(('source差',found,bad,prepared))
    for label,registered,stored,plan in variants:
        try:runner.registry_guard(registered,stored,plan)
        except AssertionError:rejected.append(label)
        else:raise AssertionError('登録guard拒否漏れ:'+label)
    assert len(rejected)==7
    text=(SOURCE/'runner.py').read_text(encoding='utf-8');tree=ast.parse(text)
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run');body=run.body
    guard=next(i for i,n in enumerate(body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='registry_guard')
    private=next(i for i,n in enumerate(body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='source_scope_guard')
    denial=next(i for i,n in enumerate(body) if isinstance(n,ast.Assert) and "'finance'" in ast.get_source_segment(text,n))
    start=next(i for i,n in enumerate(body) if 'finance/開始.json' in ast.get_source_segment(text,n))
    execute=next(i for i,n in enumerate(body) if isinstance(n,ast.Try))
    assert guard<private<denial<start<execute
    calls=[n for n in ast.walk(body[execute]) if isinstance(n,ast.Call)]
    loads=[ast.unparse(n) for n in calls if ast.unparse(n.func)=='data.load']
    assert set(loads)=={"data.load(fixed['input_cache'][session])","data.load(fixed['baseline']['ledgers'][session + '|' + symbol])"} and len(loads)==2
    new_gu=[n for n in calls if ast.unparse(n.func)=='interface.execute'];assert len(new_gu)==1
    assert 'if route != catalog.BASE_ENTRY' in ast.unparse(body[execute])
    assert ast.unparse(new_gu[0])=='interface.execute(account, route, peer)'
    assert 'reuse.values(before, n)' in ast.unparse(body[execute]) and 'baseline_exact(before, interface.baseline(ctx), n)' in ast.unparse(body[execute])
    assert 'np.testing.assert_array_equal(gate[\'accepted\'], oldgate)' in ast.unparse(body[execute])
    assert '自動再開始=False' in text and '金融前False.json' in text and 'finance/False.json' in text
    # 33*2の保存GU、四mask*33*2の新GU、16*33*2政策。同値確認は成功試行ではない。
    assert 33*2==66 and 4*33*2==264 and 16*33*2==1056
    assert prepared['金融']==prepared['大型入力読取']==prepared['台帳読取']==prepared['原板']==prepared['NPZ']==prepared['API']==0
    assert fixed['正式金融']==fixed['大型入力']==fixed['台帳']==fixed['原板']==fixed['NPZ']==fixed['API']==0
    assert not (SOURCE/'finance').exists() and not (SOURCE/'金融前False.json').exists()
    assert sources=={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))}
    result=dict(全合格=True,source_SHA256=sources,正式計画SHA256=digest(plan_path),正式固定SHA256=digest(fixed_path),
        所有20源人工SHA256=digest(owner_path),独立十六人工SHA256=digest(independent_path),独立source_SHA256=digest(Path(__file__)),
        八部品=sorted(prepared['spec']),登録拒否反例=rejected,同bytes数学七部品=clones,予定=expected,
        旧結果SHA参照='以前の独立小会計から引用。今回旧finance結果JSONを再読しない。',
        留保=['43親と同じ既知33で診断後に選んだ係数。未知の汎用成功又は新しい独立標本を示した計画ではない。',
              'Cは自己とpeerの別対照。peerは同clock除外・最後normal・各age資格の端点模型で真受信先後未保証。',
              '旧基準66は保存GUから再会計の同値確認で、旧GU金融simulation0。追加の有効性証拠に数えない。',
              '新GU264は四入口の全feed再生。共有比較・同じ33価格経路の1056口座を独立標本1056件と扱わない。',
              '場停止後GU suffixは診断だけで、新たな救済利益へ加算しない。'],
        正式金融未開始=True,金融結果読取=0,原板=0,NPZ=0,packet=0,ledger=0,金融=0,API=0,source及び共有docs変更=0)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,源=20,条件=16,guard=7,予定=expected,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
