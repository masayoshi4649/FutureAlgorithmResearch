"""数量四条件の八部品と固定入力、非金融人工及び実行許可guardを静的監査する。"""

from pathlib import Path
import ast
import hashlib
import json


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'work/wave_v106/e01_risk_sizing'
TRADE=ROOT/'work/wave_v106/e01_trade_gate'


def read(path: Path) -> dict:
    """
    機能: 凍結計画・小JSONだけを読取専用で取得する。
    引数: path(Path)は保存小資料の位置。
    返り値: dictは保存値。金融開始及びcache読取を行わない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path: Path) -> str:
    """
    機能: source・小資料の指紋を計算する。
    引数: path(Path)は小資料の位置。
    返り値: strはSHA256。大型input又は旧台帳に適用しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 八部品と固定33・四条件・人工証跡、登録先行と再開始禁止を静的照合する。
    引数: なし。根が正式登録する前の私有固定計画を確認する。
    返り値: Noneは最終接続証跡。金融又は未来データの評価を実行しない。
    """
    target=HERE/'risk_sizing_八部品固定33と人工及び許可接続の独立監査.json'; assert not target.exists()
    plan_path=SOURCE/'試行計画.json'; fixed_path=SOURCE/'金融事前固定.json'
    plan=read(plan_path); fixed=read(fixed_path); art_path=SOURCE/'予定リスク数量と累積部分返済及び旧同値の人工検査_v2.json'; art=read(art_path)
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))}
    assert set(plan['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
    assert plan['spec']['implementation']==fixed['source_SHA256']==art['source_SHA256']==sources
    assert fixed['計画SHA256']==digest(plan_path) and fixed['全合格'] and art['全合格']
    assert fixed['新金融']==fixed['大型input読取']==fixed['旧台帳読取']==fixed['原板']==fixed['原NPZ']==fixed['API']==0
    assert len(sources)==12
    proofs=[HERE/'risk_sizing_実数量影分離と実料金予約及び接頭の独立人工.json',
        HERE/'risk_sizing_P1P2停止と母採否及び次気配超過の独立人工.json',
        HERE/'risk_sizing_全299と代表10公開の独立小算術確認.json']
    for p in proofs:
        proof=read(p); assert proof['全合格']
        if p!=proofs[-1]:
            for name,sha in proof['source_SHA256'].items(): assert sources[name]==sha
    # ----------------------------------------
    # 旧sourceは同bytesの私有写し。旧源の関数/JITを直接実行していない。
    clones={}
    for new,old in (('common.py','common.py'),('daily.py','daily.py'),('order_kernel.py','order_kernel.py'),
                    ('policy.py','policy.py'),('baseline.py','engine.py')):
        assert (SOURCE/new).read_bytes()==(TRADE/old).read_bytes()
        clones[(TRADE/old).relative_to(ROOT).as_posix()]=digest(TRADE/old)
    assert plan['確認済みclone']==clones
    meta=read(TRADE/'全33場のE01取引更新準備.json')
    assert fixed['sessions']==plan['spec']['data']['sessions']==meta['sessions'] and len(fixed['sessions'])==33
    assert fixed['input_cache']==meta['cache'] and len(fixed['input_cache'])==33
    for value in fixed['input_cache'].values():
        assert value['path'].startswith('work/wave_v106/e01_trade_gate/input/') and len(value['SHA256'])==64
    configs=fixed['configs']; assert len(configs)==plan['spec']['entry']['condition_count']==4
    assert {(c['mode'],c['profit_ticks']) for c in configs}=={(m,p) for m in ('VETO','CONFIRM') for p in (1,2)}
    expected_thresholds={'TOPIX':{'P1':2500,'P2':5000,'L2':5000},'NK225':{'P1':1000,'P2':2000,'L2':2000}}
    assert plan['spec']['exit']['円閾値']==expected_thresholds
    assert plan['spec']['allocation']['base_quantity']=={'TOPIX':5,'NK225':10} and plan['spec']['allocation']['direction_cap']=={'TOPIX':10,'NK225':20}
    for c in configs:
        assert c['window_seconds']==60 and c['execution']=='D0' and c['offset_atr']==0 and c['risk_atr_multiple']==1 and c['loss_ticks']==2
        assert c['quantity']=={'TOPIX':5,'NK225':10} and c['cap']=={'TOPIX':10,'NK225':20}
        assert c['profit_goal_yen']=={s:v['P'+str(c['profit_ticks'])] for s,v in expected_thresholds.items()}
        assert c['loss_budget_yen']=={s:v['L2'] for s,v in expected_thresholds.items()}
        comparison=fixed['comparisons'][c['id']]
        for name,idkey in (('同額固定数量L2','baseline_id'),('旧P1L8','baseline8_id'),('旧GU','GU_id')):
            before=comparison[name]
            assert before['id']==c[idkey] and len(before['rows'])==len(before['ledgers'])==66
            assert set(before['ledgers'])=={r['session']+'|'+r['symbol'] for r in before['rows']}
    # 全4比較の保存参照が8 distinct IDs×66。ここでは旧台帳を開かない。
    distinct={r['id'] for refs in fixed['comparisons'].values() for r in refs.values()}
    assert len(distinct)==8
    assert plan['counts']=={'新GUengine':132,'新政策会計':264,'旧基準台帳一読':528,'既input一読':33,'元paper再計算':0}
    for item in plan['spec']['data']['input_manifests']:
        p=ROOT/item['path']; assert p.suffix=='.json' and digest(p)==item['sha256']
    # ----------------------------------------
    # 実行許可と最初の大型読取の先後はsourceの構文上順序で確認する。
    runner=(SOURCE/'runner.py').read_text(encoding='utf-8'); tree=ast.parse(runner)
    functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
    run=functions['run']; statements=run.body
    register=[i for i,s in enumerate(statements) if isinstance(s,ast.Assert) and 'found[0]' in ast.get_source_segment(runner,s)]
    not_started=[i for i,s in enumerate(statements) if isinstance(s,ast.Assert) and "'finance'" in ast.get_source_segment(runner,s)]
    start=[i for i,s in enumerate(statements) if "'finance/開始.json'" in ast.get_source_segment(runner,s)]
    loop=[i for i,s in enumerate(statements) if isinstance(s,ast.Try)]
    assert len(register)==len(not_started)==len(start)==len(loop)==1 and register[0]<not_started[0]<start[0]<loop[0]
    try_block=statements[loop[0]]
    loads=[n for n in ast.walk(try_block) if isinstance(n,ast.Call) and ast.unparse(n.func)=='data.load']
    assert len(loads)==2 and {'data.load(fixed[\'input_cache\'][session])','data.load(ref[\'ledgers\'][key])'}=={ast.unparse(n) for n in loads}
    assert "if ref['id'] not in before" in runner and 'mode.add_argument' in runner and '--root-trial-registered' in runner
    assert "finance/False.json" in runner and '自動再開始=False' in runner and 'assert not (common.HERE/\'finance\').exists()' in runner
    data=(SOURCE/'data.py').read_text(encoding='utf-8')
    assert data.count('path.read_bytes()')==1 and "hashlib.sha256(saved).hexdigest()==item['SHA256']" in data and 'pickle.loads(common.gzip.decompress(saved))' in data
    assert 'np.load' not in runner+data and 'requests' not in runner+data and 'urlopen' not in runner+data
    assert '損失枠L2は利益目標P1の2倍、P2と同額' in str(plan['limitations']) and 'P1対L2は2:1' not in str(plan['limitations'])
    assert '同枚数の完結親会計' not in (SOURCE/'storage.py').read_text(encoding='utf-8')
    assert 'GU suffix' in plan['spec']['exit']['条件共有']
    assert '保証' in plan['spec']['allocation']['尺度'] and '将来の勝率' in str(plan['limitations'])
    assert not (SOURCE/'finance').exists(), '独立監査時点で金融未開始を確認する'
    assert sources=={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(SOURCE.glob('*.py'))}
    registry=read(ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    registered=[r for r in registry['trials'] if r['id']==plan['id']]
    assert len(registered)<=1
    if registered: assert registered[0]['spec']==plan['spec']
    proof=dict(全合格=True,source_SHA256=sources,独立source_SHA256=digest(Path(__file__)),
        計画SHA256=digest(plan_path),事前固定SHA256=digest(fixed_path),所有人工SHA256=digest(art_path),
        独立人工={p.relative_to(ROOT).as_posix():digest(p) for p in proofs},八部品一覧=sorted(plan['spec']),
        固定場=33,新GU予定=132,政策会計予定=264,旧比較予定一読=528,旧比較distinctID=8,
        是正=['異数量比較を同枚数と呼んだstorageの引数説明を同paper親対応へ訂正。',
              'P1対L2を2:1と書いた説明を、損失枠がP1の2倍という正しい金額関係へ訂正。'],
        監査器の是正='初回の限定文言検査は「L2はP1の2倍」を要求し、正しい最終記述「損失枠L2は利益目標P1の2倍」を拒否した。金額と原文を確認して検査文字列のみ訂正。実装及び金融に変更なし。',
        静的確認=['全paper影保持と実数量当行確定','実注文料と清算から当時余力を得る',
            '実政策の停止後GU suffixは診断だけ','登録spec/hash同値の先行確認','開始/False/完成による自動再実行禁止',
            '原既packet33及び比較参照はメタデータ同値。大型bytesの再読証明は本監査に含めない。'],
        留保=['同額P2/L2でも実際の平均黒字補填は未測定。','予定リスクは次正常気配ギャップ等で超過し得る。',
              '無取引は勝ちではない。4条件は既知33場の比較。','実小型板や待ち順位は未測定。'],
        正式登録=bool(registered),金融未開始確認=True,原入力=0,原板=0,NPZ=0,API=0,金融=0,旧台帳読取=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,源数=len(sources),SHA256=digest(target)),ensure_ascii=False))


if __name__=='__main__': main()
