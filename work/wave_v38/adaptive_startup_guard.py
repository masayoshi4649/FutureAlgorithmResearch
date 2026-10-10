"""独立監査の事前固定が揃うまで、新しい実相場損益の再生を許可しない。"""

from __future__ import annotations

import argparse
from pathlib import Path
import adaptive_runner as runner


def validate() -> dict:
    """機能: 全条件・入力・実装・人工反例の内容と指紋を結合する。

    引数: なし。返り値: 実体を確認した参照指紋 (dict[str,str])。
    """
    reference={}
    def bind(path: Path, sha: str|None=None) -> None:
        """機能: 参照実体を読み直して欠落と変更を拒否する。

        引数: path (Path)、sha (str|None)。返り値: なし (None)。
        """
        actual=runner.digest(path)
        if sha is not None:assert actual==sha,str(path)
        reference[path.relative_to(runner.ROOT).as_posix()]=actual
    def manifest(name: str, field: str) -> dict:
        """機能: 事前証跡と内包する全参照を確認する。

        引数: name/field (str)。返り値: 確認済み記録 (dict)。
        """
        path=runner.HERE/name;record=runner.read(path);bind(path)
        assert record[field],name
        for relative,sha in record[field].items():
            target=Path(relative)
            bind(target if target.is_absolute() else runner.ROOT/target,sha)
        return record
    main=runner.design.catalog();extra=runner.design.supplementary()
    assert len(main)==206 and len(extra)==768
    identifiers={s['id'] for s in main+extra}
    assert len(identifiers)==974 and sum(s['primary'] for s in main+extra)==1
    design=runner.read(runner.HERE/'adaptive_design_fixed.json')
    assert design['conditions']==main and design['supplementary_conditions']==extra
    assert design['rules']==runner.design.rules() and design['新売買損益読取'] is False
    bind(runner.HERE/'adaptive_design.py',design['実装SHA256'])
    bind(runner.HERE/'adaptive_design_fixed.json')
    # ----------------------------------------
    # 入力は既存原本、窓変更、役割別乱数、実行窓口の全証跡へ接続する。
    material=manifest('branch_input_runtime_fixed.json','SHA256')
    assert material['全入力監査合格'] and material['再利用列入力数']==520 and material['新窓入力数']==156
    assert material['方向乱数入力数']==13312 and material['分岐乱数入力数']==4992
    assert not material['新損益読取'] and not material['売買再生'] and material['API取得数']==0
    assert material['現在保存物使用'] is False and len(material['原本78SHA256'])==78
    for relative,sha in material['原本78SHA256'].items():bind(runner.ROOT/relative,sha)
    engine=manifest('engine_audit.json','ソースSHA256')
    assert engine['全合格'] and engine['人工件数']==len(engine['結果']) and engine['人工件数']>=58
    assert engine['旧A0一致入力数']==26 and engine['旧原本不変']
    assert engine['新実相場損益'] is False and engine['API取得数']==0
    delay=manifest('delay_snapshot_review.json','SHA256')
    assert delay['全合格'] and delay['人工検査数']==7 and delay['現契約との具体的不整合検出'] is False
    assert not delay['新実相場再生'] and not delay['新損益読取'] and delay['API取得数']==0
    slots=manifest('adaptive_slot_fixed.json','参照SHA256')
    assert slots['全合格'] and slots['主人工数']==824 and slots['補助人工数']==768
    assert slots['破損拒否数']==13 and slots['固定乱数人工再生数']==1024
    assert not slots['新実相場損益'] and slots['API取得数']==0
    assert {'adaptive_slot_audit.py','adaptive_shadow_oracle.py','adaptive_slot_selftest.py',
        'adaptive_slot_random_selftest.py','adaptive_slot_random_selftest.json'} <= {
            Path(k).name for k in slots['参照SHA256']}
    # ----------------------------------------
    # 全条件の接続と人工会計、異常な人工経路でも成立することを要求する。
    for name,total_field,total in (('adaptive_runner_synthetic.json','人工会計数',824),
            ('random_path_audit.json','人工再生数',1024)):
        record=runner.read(runner.HERE/name);bind(runner.HERE/name)
        assert record['全合格'] and record[total_field]==total
        assert not record['新実相場損益' if name=='random_path_audit.json' else '新実データ損益']
        for filename,sha in record['SHA256'].items():bind(runner.HERE/filename,sha)
        if name=='adaptive_runner_synthetic.json':assert record['全条件接続数']==974
        else:assert record['人工比較数']==512
    # ----------------------------------------
    # 基礎候補・頑健性・方式選択の価値を、結果を見る前に別判定へ固定する。
    assessment=manifest('adaptive_assessment_fixed.json','参照SHA256')
    assert not assessment['新損益読取'] and not assessment['売買再生'] and assessment['API取得数']==0
    assert assessment['規則']['主仮説']==runner.design.PRIMARY_ID and assessment['規則']['全条件数']==974
    revision=manifest('adaptive_assessment_revision.json','参照SHA256')
    assert revision['改訂完了'] and revision['旧規則と新規則同一'] and revision['採否版']==assessment['採否版']==2
    assert revision['人工検査数']==48 and revision['実エンジン人工接続数']==8
    for field in ('新損益読取','売買方式変更','採否閾値変更','対象変更','現在保存物使用'):
        assert revision[field] is False,field
    assert revision['API取得数']==0
    bind(runner.HERE/'adaptive_assessment_fixed.json',revision['新固定SHA256'])
    assert runner.read(runner.HERE/'adaptive_assessment_fixed_v1.json')['規則']==assessment['規則']
    proof=runner.read(runner.HERE/'adaptive_assessment_test.json');bind(runner.HERE/'adaptive_assessment_test.json')
    assert proof['全合格'] and proof['人工検査数']>=48 and not proof['新実相場損益']
    bind(runner.HERE/'adaptive_assessment.py',proof['実装SHA256'])
    bind(runner.HERE/'adaptive_assessment_test.py',proof['検査SHA256'])
    bind(runner.HERE/'adaptive_design.py',proof['設計SHA256'])
    # ----------------------------------------
    # 実相場で検査する因果・指定波・独立会計の対象全体を要求する。
    causal=manifest('adaptive_causality_fixed.json','SHA256')
    wave=manifest('adaptive_wave_fixed.json','SHA256')
    cash=manifest('adaptive_accounting_fixed.json','参照SHA256')
    assert causal['合成検査合格'] and causal['規則']['全検査入力数']==3918
    assert causal['規則']['主検査入力数']==846 and causal['規則']['補助検査入力数']==3072
    assert causal['規則']['主案全26']==runner.design.PRIMARY_ID
    assert causal['規則']['新実相場損益未読'] and causal['新実相場損益'] is False
    assert len(causal['規則']['全条件ID'])==974 and set(causal['規則']['全条件ID'])==identifiers
    assert wave['全合格'] and wave['合成検査合格'] and not wave['新実相場損益']
    assert wave['規則']['全波数']==7792 and wave['規則']['全境界数']==15584
    assert set(wave['規則']['主条件ID'])=={s['id'] for s in main}
    assert set(wave['規則']['補助条件ID'])=={s['id'] for s in extra}
    assert len(wave['規則']['主条件ID'])==206 and len(wave['規則']['補助条件ID'])==768
    assert cash['全条件数']==974 and cash['全入力数']==25324 and not cash['新実データ損益']
    assert cash['主対象']==main and cash['補助対象']==extra
    audit=cash['人工検査']
    assert audit['全合格'] and audit['人工入力検査数']==3896 and audit['全974条件両銘柄活動無取引']
    assert audit['独立統計破損拒否数']>=208 and audit['破損欠落拒否数']>=4
    coverage={(s['budget_enabled'],s['min_delay_seconds'],s['branch_mode'],inactive)
        for s in main+extra for inactive in (False,True)}
    assert len(audit['条件被覆'])==len(coverage) and {tuple(v) for v in audit['条件被覆']}==coverage
    assert cash['原本78SHA256']==material['原本78SHA256']
    for record,field,names in (
        (causal,'SHA256',('adaptive_causality_audit.py','adaptive_runner.py','engine_partial_restore.py','engine_shadow_plan.py')),
        (wave,'SHA256',('adaptive_wave_audit.py','adaptive_runner.py','engine_partial_restore.py')),
        (cash,'参照SHA256',('adaptive_accounting_audit.py','adaptive_slot_audit.py','adaptive_shadow_oracle.py',
            'adaptive_independent_statistics.py','adaptive_runner.py','engine_partial_restore.py','engine_shadow_plan.py'))):
        required={(runner.HERE/name).relative_to(runner.ROOT).as_posix() for name in names}
        assert required <= set(record[field]),required-set(record[field])
    for name,count_key,count,bad in (('adaptive_causality_selftest.json','人工条件数',974,9),
            ('adaptive_wave_selftest.json','合成検査数',6,7)):
        proof=runner.read(runner.HERE/name);bind(runner.HERE/name)
        assert proof['全合格'] and proof[count_key]==count and proof['負例拒否数']==bad
        assert not proof['新実相場損益']
        if name=='adaptive_causality_selftest.json':
            assert proof['分岐分類検査数']==12 and len(proof['分岐分類検査'])==12
            assert {(p['分類'],p['方式']) for p in proof['分岐分類検査']}=={
                (label,mode) for label in ('逆','順','中立','欠測') for mode in ('adverse_signal','reverse','random')}
            for row in proof['分岐分類検査']:
                assert all(row[k] is True for k in ('prefix一致','future一致','reflection一致'))
                assert row['影新規再生成数']==4
    for relative,sha in reference.items():assert runner.digest(runner.ROOT/relative)==sha,relative
    return reference


def main() -> None:
    """機能: 事前検査に不備がなければ実行許可証跡を一度だけ保存する。

    引数: --check (bool)。返り値: なし (None)。新実相場の損益は再生しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    reference=validate()
    proof=runner.read(runner.HERE/'adaptive_startup_guard_test.json')
    assert proof['全合格'] and proof['破損拒否数']>=12
    assert proof['ガードSHA256']==runner.digest(Path(__file__))
    for name in ('adaptive_startup_guard.py','adaptive_startup_guard_test.py','adaptive_startup_guard_test.json'):
        reference[(runner.HERE/name).relative_to(runner.ROOT).as_posix()]=runner.digest(runner.HERE/name)
    fixed=runner.prepare()
    assert fixed['conditions']==runner.design.catalog() and fixed['supplementary_conditions']==runner.design.supplementary()
    value=dict(実行可能=True,全条件数=206,補助条件数=768,全入力数=5356,補助入力数=19968,
        主仮説=runner.design.PRIMARY_ID,探索固定SHA256=runner.digest(runner.HERE/'探索条件の固定.json'),
        API取得数=0,新実データ損益=False,SHA256=reference)
    path=runner.HERE/'起動前監査.json'
    if args.check or path.exists():assert runner.read(path)==value,'起動固定後の変更'
    else:runner.save(path,value)
    print('主206・補助768の結果前検査が一致。新実損益なし。',flush=True)


if __name__=='__main__':main()
