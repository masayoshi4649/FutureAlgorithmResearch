"""既知11条件を価格規則不変で引き継ぎ、新しいF50反証の実行前に固定する。"""

from __future__ import annotations

from pathlib import Path
import json
import sys

import runner

HERE, ROOT = runner.HERE, runner.ROOT
PRIOR = HERE.parent/'wave_v44'
FOLDERS = (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('audits', '.json.gz'),
           ('waves', '.json.gz'), ('causality', '.json'), ('gate_use', '.json'), ('summaries', '.json'))
REUSED_IDS = frozenset([f'{base}__{variant}' for base in ('A0','G000_F25_N1','G150_F25_N1')
                       for variant in ('V000','E080','E120')] +
                      ['G000_F50_N1__V000','G150_F50_N1__V000'])


def reuse_spec_check(current: dict, previous: dict) -> None:
    """機能: 主案表示と役割以外の条件変更を一つでも拒否する。

    引数: current/previous(dict)。返り値: なし(None)。数値条件の省略や追加も拒否する。
    """
    assert set(current)==set(previous)
    assert current['id']==previous['id'] and current['id'] in REUSED_IDS
    assert type(current['primary']) is bool and type(previous['primary']) is bool
    assert isinstance(current['role'],str) and isinstance(previous['role'],str)
    left={k:v for k,v in current.items() if k not in ('primary','role')}
    right={k:v for k,v in previous.items() if k not in ('primary','role')}
    assert json.dumps(left,sort_keys=True,allow_nan=False)==json.dumps(right,sort_keys=True,allow_nan=False)


def inheritance(specs: list[dict], previous: dict, proof: dict, old_sha: str) -> dict:
    """機能: 旧完備に結合された11条件の実物8資料と完全条件を固定する。

    引数: specs(list[dict])、previous/proof(dict)、old_sha(str)。返り値: 引継ぎ辞書(dict)。
    新しい売買は実行せず、旧成果の署名と条件だけを読む。
    """
    assert proof['全合格'] is True and proof['探索固定SHA256']==old_sha
    assert (proof['全条件数'],proof['全入力数'],proof['因果入力数'],proof['旧単一窓一致入力数'])==(163,4238,652,156)
    old_specs={s['id']:s for s in previous['conditions']+previous['supplementary']}
    selected=[s for s in specs if s['id'] in REUSED_IDS]
    assert len(selected)==11 and {s['id'] for s in selected}==REUSED_IDS
    output={}
    for spec in selected:
        identifier=spec['id']; prior=old_specs[identifier]
        reuse_spec_check(spec,prior)
        record_path=PRIOR/'completed'/(identifier+'.json')
        record=runner.read(record_path)
        paths={(PRIOR/folder/(identifier+suffix)).relative_to(ROOT).as_posix() for folder,suffix in FOLDERS}
        assert record['id']==identifier and record['全合格'] is True
        assert record['探索固定SHA256']==old_sha and (record['全入力数'],record['因果入力数'])==(26,4)
        assert set(record['出力SHA256'])==paths
        sources=dict(record['出力SHA256'])
        relative=record_path.relative_to(ROOT).as_posix()
        sources[relative]=runner.digest(record_path)
        assert len(sources)==8
        for name,digest in sources.items():
            assert proof['出力SHA256'][name]==digest,name
        runner.verify(sources)
        summary=runner.read(PRIOR/'summaries'/(identifier+'.json'))
        assert summary['spec']==prior and summary['探索固定SHA256']==old_sha
        output[identifier]=dict(spec=prior,completed=relative,出力SHA256=sources,旧探索固定SHA256=old_sha)
    return output


def prepare() -> dict:
    """機能: 全153条件と不変のゲート・注文・元資料を実行前に固定する。

    引数: なし。返り値: 探索固定資料(dict)。既知11以外の新損益は読まない。
    """
    path=HERE/'探索条件の固定.json'
    if path.exists():
        fixed=runner.read(path)
        assert fixed['conditions']==runner.design.catalog() and fixed['supplementary']==runner.design.supplementary()
        runner.verify(fixed['参照資料SHA256'])
        return fixed
    references={}

    def bind(values: dict) -> None:
        """機能: 異なる固定資料の同名指紋が競合した場合に停止する。

        引数: values(dict[str,str])。返り値: なし(None)。
        """
        for name,digest in values.items():
            assert name not in references or references[name]==digest,name
            references[name]=digest

    previous=runner.read(PRIOR/'探索条件の固定.json')
    previous_proof=runner.read(PRIOR/'完備監査.json')
    previous_sha=runner.digest(PRIOR/'探索条件の固定.json')
    assert previous_proof['参照資料SHA256']==previous['参照資料SHA256']
    bind(previous['参照資料SHA256'])
    # ----------------------------------------
    # 全旧完備を指紋確認する。新しい会計再生と旧確認済み結果を混同しない。
    runner.verify(previous_proof['出力SHA256'])
    bind(previous_proof['出力SHA256'])
    main=runner.design.catalog(); supplemental=runner.design.supplementary(); specs=main+supplemental
    assert len(main)==25 and len(supplemental)==128 and len({s['id'] for s in specs})==153
    reused=inheritance(specs,previous,previous_proof,previous_sha)
    gate=runner.read(PRIOR/'profit_gate_fixed.json')
    assert gate['全合格'] is True and gate['全入力監査合格'] is True
    assert (gate['全入力数'],gate['入力仕様数'],gate['全セル数'])==(26,16,416)
    assert gate['新戦略売買再生'] is False and gate['新損益資料読取'] is False
    for field in ('参照SHA256','旧入力参照SHA256'): bind(gate[field])
    assert Path(runner.gate.__file__).resolve()==PRIOR/'profit_gate.py'
    assert Path(runner.engine.__file__).resolve()==HERE.parent/'wave_v41/engine_partial_restore_corrected.py'
    assert Path(runner.audit.__file__).resolve()==HERE.parent/'wave_v38/adaptive_accounting_audit.py'
    for name in ('columns_for','quality_for','play','gate_prefix','causal_check',
                 'initial_identity','gate_record','legacy_id'):
        assert getattr(runner,name) is getattr(runner.legacy,name),name
    for name in ('check_runner.json','check_assessment.json','check_complete.json'):
        check=runner.read(HERE/name)
        assert check['全合格'] is True and check['新実相場損益'] is False,name
        bind(check['参照資料SHA256'])
    assessment=runner.read(HERE/'assessment_fixed.json')
    assert assessment['条件']==specs and assessment['旧関数構文全一致'] is True
    bind(assessment['SHA256'])
    counts={}
    rows=runner.read(PRIOR/'gate_input_audit.json')['結果']
    for row in rows:
        key=row['session']+'|'+row['symbol']
        assert key not in counts or counts[key]==row['原本行数']
        assert type(row['原本行数']) is int and row['原本行数']>0
        counts[key]=row['原本行数']
    assert len(rows)==416 and len(counts)==26 and counts==previous['原本行数']
    paths={HERE/name for name in ('design.py','runner.py','prepare.py','complete.py',
        'check_runner.py','check_runner.json','assessment.py','check_assessment.py',
        'check_assessment.json','assessment_fixed.json','check_complete.py','check_complete.json',
        '50パーセント版の反証案.md','反証計画.md')}
    paths.update(PRIOR/name for name in ('探索条件の固定.json','完備監査.json','profit_gate_fixed.json',
                                         'profit_gate.py','gate_input_audit.json'))
    for value in tuple(sys.modules.values()):
        name=getattr(value,'__file__',None)
        if name:
            source=Path(name).resolve()
            if source.is_relative_to(ROOT/'work') and source.suffix=='.py':paths.add(source)
    bind({p.relative_to(ROOT).as_posix():runner.digest(p) for p in paths})
    runner.verify(references)
    fixed=dict(conditions=main,supplementary=supplemental,rules=runner.design.rules(),
        主条件数=25,補助条件数=128,全条件数=153,全入力数=3978,因果入力数=612,
        旧単一窓一致入力数=156,必須出力数=1071,既知引継条件数=11,新規再生条件数=142,
        既知引継入力数=286,新規再生入力数=3692,既知引継因果入力数=44,新規因果入力数=568,
        既知再利用=reused,原本行数=counts,全セッション=previous['全セッション'],
        後半7セッション=previous['後半7セッション'],指定波=previous['指定波'],参照資料SHA256=references,
        旧ゲート不変更=True,旧注文器不変更=True,旧厳格会計不変更=True,
        現在API取得数=0,保存ライブ使用=False,新実相場損益確認前=True,
        既知11は事前に成績既知=True,全体目標達成=False)
    runner.save(path,fixed)
    return fixed


if __name__=='__main__':
    result=prepare()
    print(f"全{result['全条件数']}条件を固定。既知11を引継ぎ、新規142を再生。",flush=True)
