"""旧因果監査と補正済み波監査を、新しい復元分岐の契約へ複写する。"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent/'wave_v37'


def replace(text: str, old: str, new: str) -> str:
    """機能: 想定した旧本文だけを一度置換する。

    引数: text/old/new (str)。返り値: 新本文 (str)。
    """
    assert text.count(old) == 1, old[:120]
    return text.replace(old,new)


def causal() -> str:
    """機能: 旧全列因果検査へ分岐列・伝達遅延・実行計画を加える。

    引数: なし。返り値: 新監査ソース (str)。実データの売買は実行しない。
    """
    text = (PRIOR/'partial_causality_audit.py').read_text(encoding='utf-8')
    text = text.replace('partial_causality','adaptive_causality')
    text = text.replace('partial_runner','adaptive_runner').replace('partial_design','adaptive_design')
    text = text.replace('partial_input_fixed','branch_input_runtime_fixed').replace('partial_inputs','branch_inputs_runtime')
    text = replace(text,'import partial_engine_audit as fixtures','assert Path(runner.engine.__file__).resolve().parent == HERE\nassert Path(runner.engine.shadow_engine.__file__).resolve().parent == HERE')
    text = replace(text,"CURVES = ('curve', 'atr_curve', 'control_curve', 'slot_curve')","CURVES = ('curve', 'atr_curve', 'control_curve', 'slot_curve', 'branch_curve')")
    text = replace(text,'slot_events=0, adjustment_events=0, budget_events=0)','slot_events=0, adjustment_events=0, budget_events=0, branch_events=0)')
    text = replace(text,"SHADOW_FIELDS = engine.FIELDS + ('plans', 'prepare_events', 'entry_preparations')","SHADOW_FIELDS = engine.FIELDS + ('plans', 'execution_plans', 'prepare_events', 'entry_preparations')")
    text = replace(text,"SHADOW_FIELDS = engine.FIELDS + ('plans', 'execution_plans', 'prepare_events', 'entry_preparations')", "SHADOW_FIELDS = engine.FIELDS + ('plans', 'execution_plans', 'prepare_events', 'entry_preparations')\nassert set(CURVES) | set(EVENTS) | {'stats'} == set(runner.FIELDS)\nassert len(runner.FIELDS) == 15 and len(SHADOW_FIELDS) == 10")
    text = replace(text,"    state, bad, bad_source, good, good_source, valid = columns\n    shadow = engine.make_shadow(ready, state, config, spec['observed_fill'])\n    return engine.run(ready, state, config, bad, bad_source, good, good_source, spec['policy'],\n        observed_fill=spec['observed_fill'], detail=True, shadow=shadow, good_valid=valid)","""    state, bad, bad_source, good, good_source, valid, branch, branch_source, branch_valid, choice = columns
    shadow = engine.make_shadow(ready, state, config, spec['observed_fill'], spec['min_delay_seconds'])
    return engine.run(ready, state, config, bad, bad_source, good, good_source, spec['policy'],
        observed_fill=spec['observed_fill'], detail=True, shadow=shadow, good_valid=valid,
        budget_enabled=spec['budget_enabled'], min_delay_seconds=spec['min_delay_seconds'],
        branch_direction=branch, branch_source=branch_source, branch_valid=branch_valid,
        branch_mode=spec['branch_mode'], branch_choice=choice, branch_seed=spec['branch_seed'])""")
    text = replace(text,"    for field in ('curve', 'atr_curve', 'plans'):","    for field in ('curve', 'atr_curve', 'plans', 'execution_plans'):")
    text = replace(text,"        close(mirror['budget_events'], actual['budget_events'], '反射/予算')","""        close(mirror['budget_events'], actual['budget_events'], '反射/予算')
        expected = actual['branch_events'].copy(); expected[:, 4] *= -1
        close(mirror['branch_events'], expected, '反射/分岐イベント')
        exact(mirror['branch_curve'], actual['branch_curve'], '反射/分岐状態')""")
    start = text.index("        a, b = actual['plans'], mirror['plans']")
    end = text.index('\n\ndef audit_one',start)
    text = text[:start]+'''        P = {name: i for i, name in enumerate(engine.PLAN_COLUMNS)}
        signed = ('direction', 'pending_direction')
        prices = ('anchor', 'extreme', 'stop_level', 'trail_level', 'split_level', 'pending_level')
        for field in ('plans', 'execution_plans'):
            a, b = actual[field], mirror[field]
            for name, index in P.items():
                if name in signed:
                    close(b[:, index], -a[:, index], '影/' + field + '/' + name)
                elif name in prices:
                    direction = a[:, P['pending_direction']] if name == 'pending_level' else a[:, P['direction']]
                    active = np.isfinite(direction) & (direction != 0)
                    close(b[active, index], center - a[active, index], '影/' + field + '/' + name)
                else:
                    close(b[:, index], a[:, index], '影/' + field + '/' + name)
''' + text[end:]
    text = replace(text,'for index in (0, 1, 3):','for index in (0, 1, 3, 6):')
    text = replace(text,'for index in (2, 4):','for index in (2, 4, 7):')
    text = replace(text,'    alternate[5][future_cut:] = ~alternate[5][future_cut:]','    for index in (5, 8):\n        alternate[index][future_cut:] = ~alternate[index][future_cut:]\n    alternate[9][future_cut:] = 1 - alternate[9][future_cut:]')
    text = replace(text,'-v if i in (0, 1, 3) else v.copy()','-v if i in (0, 1, 3, 6) else v.copy()')
    start = text.index('def synthetic()')
    end = text.index('\ndef source_paths()',start)
    text = text[:start]+SYNTHETIC+text[end:]
    text = replace(text,"HERE / 'adaptive_runner.py', HERE / 'adaptive_design.py', HERE / 'partial_engine_audit.py',","HERE / 'adaptive_runner.py', HERE / 'adaptive_design.py', HERE / 'build_adaptive_audits.py',")
    text = replace(text,"HERE / 'engine_partial_restore.py', HERE / 'engine_shadow_plan.py', HERE / 'branch_inputs_runtime.py',","HERE / 'engine_partial_restore.py', HERE / 'engine_shadow_plan.py', HERE / 'branch_inputs_runtime.py',\n             HERE / 'engine_audit.py', HERE / 'engine_audit.json',")
    text = replace(text,"             HERE / 'engine_audit.py', HERE / 'engine_audit.json',", "             HERE / 'engine_audit.py', HERE / 'engine_audit.json',\n             HERE / 'adaptive_audit_build_check.py', HERE / 'adaptive_audit_build_check.json',")
    text = text.replace('主条件数=363, 補助条件数=64, 全検査入力数=427 * 4 + 22','主条件数=206, 補助条件数=768, 全検査入力数=974 * 4 + 22')
    text = text.replace('主検査入力数=363 * 4 + 22, 補助検査入力数=64 * 4','主検査入力数=206 * 4 + 22, 補助検査入力数=768 * 4')
    text = text.replace('価格/ATR/入口/悪化/回復/根拠行/公開品質を変更する。','価格/ATR/入口/悪化/回復/分岐方向/根拠行/公開品質/分岐選択を変更する。')
    text = text.replace('入口/悪化/回復すべて反転。元方向×乱数符号も同じ公開元のまま反射。','入口/悪化/回復/分岐方向すべて反転。分岐choiceは不変。元方向×乱数符号も同じ公開元のまま反射。')
    text = text.replace('独立影計画。切断stats','独立影計画と成熟実行計画・分岐状態/イベント。切断stats')
    text = text.replace('基準の全FIELDSと影9配列','基準の全15配列と影10配列')
    text = replace(text,"        全条件波別監査=", "        実配列項目=list(runner.FIELDS), 影配列項目=list(SHADOW_FIELDS),\n        全条件波別監査=")
    text = text.replace('partial_wave_audit.pyで全427×8','adaptive_wave_audit.pyで全974×8')
    text = text.replace('427人工条件と負例を通過。因果監査対象1730入力','974人工条件と負例を通過。因果監査対象3918入力')
    text = replace(text,'count == (256 if args.supplementary else 1474)','count == (3072 if args.supplementary else 846)')
    text = replace(text,'    fixed = dict(規則=rules, 合成検査合格=True,','    fixed = dict(規則=rules, 全合格=True, 合成検査合格=True, 新実相場損益=False,')
    return text


SYNTHETIC = '''def fixture(prices: list[float], bad_rows: tuple=(), good_rows: tuple=(), spacing: float=30.) -> tuple:
    """機能: 遅延が成立し、場末返済の別行を持つ人工入力を作る。

    引数: prices (list[float])、bad_rows/good_rows (tuple)、spacing (float)。返り値: 入力等7要素 (tuple)。
    """
    count = len(prices)
    ready = dict(time_s=np.r_[np.arange(count)*spacing, 10000., 10030.],
        last=np.array(prices+[prices[-1]]*2,dtype=float), atr=np.full(count+2,4.),
        start=-1200.,limit=10000.,us_open=np.inf,tick=1.,seq=np.arange(count+2),
        session='人工',symbol='TOPIX')
    state=np.ones(count+2,np.int8)
    manager=read(HERE.parent/'wave_v35/探索条件の固定.json')['manager']
    config=runner.base.managers.make_config(manager,'TOPIX',ready)
    bad=np.zeros(count+2,np.int8);good=bad.copy()
    bad[list(bad_rows)]=-1;good[list(good_rows)]=1
    source=np.arange(count+2,dtype=np.int64)
    return ready,state,config,bad,source,good,source.copy()


def artificial_columns(args: tuple, spec: dict) -> tuple:
    """機能: 全方針の役割別乱数を人工公開元へ割り当てる。

    引数: args (tuple)、spec (dict)。返り値: 原本対応10列 (tuple)。
    """
    ready,state,_,bad,source,good,good_source=args
    key=('人工','TOPIX'); n=len(state)
    valid=np.ones(n,bool); branch=np.resize(np.array([-1,1,0,-1],np.int8),n)
    branch_source=source.copy();branch_valid=np.ones(n,bool)
    branch_source[0]=-1;branch_valid[0]=False;branch[0]=0
    choice=np.zeros(n,np.int8)
    if spec['bad_seed'] is not None:
        bad=api.random_direction(bad,source,ready,key,spec['bad_seed'],'bad')
    if spec['good_seed'] is not None:
        good=api.random_direction(good,good_source,ready,key,spec['good_seed'],'good')
    if spec['branch_seed'] is not None:
        choice=api.source_bits(branch_source,ready,key,spec['branch_seed'],'branch')
    return state,bad,source,good,good_source,valid,branch,branch_source,branch_valid,choice


def synthetic() -> dict:
    """機能: 全974方針と分岐四分類を同じ因果検査へ通し、全追加列の破損を拒否する。

    引数: なし。返り値: 人工検査証跡 (dict)。実相場の新損益は読まない。
    """
    specs=design.catalog()+design.supplementary()
    assert len(design.catalog())==206 and len(design.supplementary())==768
    args=fixture([100,101,103,100,103,104,100,99,101,104,100,98,95],(2,6,10),(4,8))
    ready,state,config,bad,source,good,good_source=args
    ready['time_s'][10]=ready['time_s'][9]
    checks=[]
    for spec in specs:
        columns=artificial_columns(args,spec)
        checked,_=audit_one(ready,columns,config,spec)
        checks.append(dict(id=spec['id'],**checked))
    # ----------------------------------------
    # 分岐は減量の約定時点で選び、上下反射しても肯定/否定の関係を保つ。
    primary=next(s for s in specs if s['primary'])
    args=fixture([100,101,102,102,102,102,102,102,95],(2,),(6,))
    args[0]['time_s'][:9]=[0,1,2,3,122,123,124,125,126]
    branches=[]
    for direction,is_valid,label in ((-1,True,'逆'),(1,True,'順'),(0,True,'中立'),(0,False,'欠測')):
        for mode in ('adverse_signal','reverse','random'):
            spec=dict(primary,branch_mode=mode,branch_seed=3 if mode=='random' else None)
            columns=list(artificial_columns(args,spec));n=len(columns[0])
            columns[6]=np.full(n,direction,np.int8);columns[8]=np.full(n,is_valid,bool)
            columns[7]=np.arange(n,dtype=np.int64) if is_valid else np.full(n,-1,np.int64)
            columns[9]=np.ones(n,np.int8)
            checked,result=audit_one(args[0],tuple(columns),args[2],spec)
            assert len(result['branch_events'])==1
            event=result['branch_events'][0]
            assert event[0]==3 and event[5]==(3 if is_valid else -1)
            assert event[6]==int(is_valid)
            assert event[7]==({'逆':3,'順':2,'中立':1,'欠測':0}[label])
            predicate=is_valid and direction==-1
            signal=predicate if mode=='adverse_signal' else not predicate if mode=='reverse' else True
            assert event[3]==(1 if signal else 2)
            branches.append(dict(分類=label,方式=mode,**checked))
    # ----------------------------------------
    # 新しい枝と成熟計画を落とした比較器が合格しないことを直接確かめる。
    ready,state,config,bad,source,good,good_source=args
    columns=artificial_columns(args,primary)
    reference=replay(ready,columns,config,primary)
    rejected=[]
    for field,column in (('control_curve',0),('branch_curve',0)):
        corrupt=deepcopy(reference);corrupt[field][1,column]+=1
        try:prefix(reference,corrupt,4)
        except AssertionError:rejected.append('過去'+field+'改変')
        else:raise AssertionError(field+'の改変を見逃した')
    for field in ('plans','execution_plans'):
        corrupt=deepcopy(reference);corrupt['shadow'][field][1,33]=999
        try:prefix(reference,corrupt,4)
        except AssertionError:rejected.append('過去影'+field+'改変')
        else:raise AssertionError(field+'の改変を見逃した')
    assert len(reference['branch_events'])>0
    corrupt=deepcopy(reference);corrupt['branch_events'][0,3]+=1
    try:prefix(reference,corrupt,len(state))
    except AssertionError:rejected.append('過去分岐イベント改変')
    else:raise AssertionError('分岐イベントの改変を見逃した')
    changed=dict(ready,last=ready['last']+1.)
    try:
        engine.run(changed,state,config,bad,source,good,good_source,primary['policy'],
            shadow=reference['shadow'],good_valid=columns[5])
    except ValueError:rejected.append('変形入力への旧影流用')
    else:raise AssertionError('旧影キャッシュを受理した')
    for index in (2,4,7):
        altered=list(columns);altered[index]=columns[index].copy();altered[index][2]=3
        try:replay(ready,tuple(altered),config,primary)
        except ValueError:rejected.append('未来公開行参照'+str(index))
        else:raise AssertionError('未来根拠を受理した')
    return dict(全合格=True,人工条件数=len(checks),検査=checks,分岐分類検査数=len(branches),
        分岐分類検査=branches,負例拒否数=len(rejected),負例=rejected,新実相場損益=False)

'''


def wave() -> str:
    """機能: 管理方向二項目を含む旧v2全波監査を今回の全条件へ接続する。

    引数: なし。返り値: 新監査ソース (str)。波の独立数式は変えない。
    """
    text=(PRIOR/'partial_wave_audit_v2.py').read_text(encoding='utf-8')
    text=text.replace('partial_causality','adaptive_causality')
    text=text.replace('partial_wave_fixed_v2','adaptive_wave_fixed').replace('partial_wave_selftest_v2','adaptive_wave_selftest')
    text=text.replace('partial_wave_details','adaptive_wave_details').replace('partial_wave_audit.json','adaptive_wave_audit.json')
    text=text.replace('partial_design','adaptive_design').replace('partial_runner','adaptive_runner')
    text=text.replace('partial_input_fixed','branch_input_runtime_fixed').replace('partial_inputs','branch_inputs_runtime')
    text=text.replace('全427条件','全974条件').replace('主波数=363*8, 補助波数=64*8, 全波数=427*8','主波数=206*8, 補助波数=768*8, 全波数=974*8').replace('全境界数=427*16','全境界数=974*16')
    old="""    paths.update(HERE/name for name in ('partial_wave_audit.py', 'partial_wave_fixed.json', 'partial_wave_selftest.json',
        'partial_wave_failure_v1.json', 'partial_wave_revision_plan.json', 'build_wave_audit_v2.py'))"""
    text=replace(text,old,"    paths.update((HERE/'build_adaptive_audits.py', HERE.parent/'wave_v37/partial_wave_audit_v2.py'))")
    text=replace(text,"    paths.update((HERE/'build_adaptive_audits.py', HERE.parent/'wave_v37/partial_wave_audit_v2.py'))", "    paths.update((HERE/'build_adaptive_audits.py', HERE.parent/'wave_v37/partial_wave_audit_v2.py'))\n    paths.update((HERE/'adaptive_audit_build_check.py', HERE/'adaptive_audit_build_check.json'))")
    text=text.replace('監査版=2','監査版=1')
    return text


def main() -> None:
    """機能: v38だけへ監査コードを生成する。

    引数: なし。返り値: なし (None)。旧実装・既存成果は変更しない。
    """
    for name,content in (('adaptive_causality_audit.py',causal()),('adaptive_wave_audit.py',wave())):
        target=HERE/name
        assert not target.exists(), target
        target.write_text(content,encoding='utf-8')
    print('因果全15＋影10列と補正済み8波の監査コードを生成しました。')


if __name__=='__main__':
    main()
