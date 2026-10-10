"""会計の限定改訂と、旧158条件・新974条件の同一性を追跡する。"""

from pathlib import Path
import adaptive_runner as runner

HERE=runner.HERE


def legacy() -> dict:
    """機能: 旧ファイルの写像で初回固定と158条件を改変なく検証する。

    引数: なし。返り値: 旧退避計画 (dict)。
    """
    plan=runner.read(HERE/'adaptive_cash_revision_plan.json')
    assert plan['旧保存条件数']==len(set(plan['旧保存ID']))==158
    assert plan['旧主条件数']==206 and plan['旧補助保存数']==0
    assert plan['全974再計算必須'] and plan['旧158数値同値必須'] and plan['全台帳指紋一致必須']
    assert plan['新旧比較の除外']==['summaries.経過秒','summaries.探索固定SHA256']
    for field in ('新方式追加','成績による条件除外','主仮説差替'):assert plan[field] is False
    assert plan['API取得数']==0
    mapping=plan['旧資料']
    for old,row in mapping.items():
        target=(runner.ROOT/row['保存先']).resolve()
        assert target.is_relative_to((HERE/'cash_revision_v1').resolve())
        assert runner.digest(target)==row['SHA256'],old
    for name in ('探索条件の固定.json','起動前監査.json'):
        record=runner.read(HERE/'cash_revision_v1'/name)
        for old,sha in record['SHA256'].items():
            target=runner.ROOT/(mapping[old]['保存先'] if old in mapping else old)
            assert runner.digest(target)==sha,old
    return plan


def preserved_results() -> dict:
    """機能: 再計算済み158条件の全台帳・全経済数値を旧版と照合する。

    引数: なし。返り値: 一致証跡 (dict)。未完了や条件除外は拒否する。
    """
    plan=legacy()
    old=runner.read(HERE/'cash_revision_v1/探索条件の固定.json')
    new=runner.read(HERE/'探索条件の固定.json')
    for field in ('conditions','supplementary_conditions','manager','全セッション','後半7セッション','指定波','主仮説'):
        assert old[field]==new[field],field
    references={}
    for name in ('adaptive_runner.py','adaptive_design.py','adaptive_assessment.py','engine_partial_restore.py',
            'engine_shadow_plan.py','branch_inputs.py','branch_inputs_runtime.py','adaptive_slot_audit.py','adaptive_shadow_oracle.py'):
        assert runner.digest(HERE/name)==runner.digest(HERE/'cash_revision_v1'/name),name
    count=0
    for identifier in plan['旧保存ID']:
        for folder,suffix in (('ledgers','.json.gz'),('sessions','.json.gz'),('waves','.json.gz'),('accounting','.json.gz'),('summaries','.json')):
            before=HERE/'cash_revision_v1'/folder/(identifier+suffix)
            after=HERE/folder/(identifier+suffix)
            if folder=='summaries':
                a,b=runner.read(before),runner.read(after)
                assert a['探索固定SHA256']==runner.digest(HERE/'cash_revision_v1/探索条件の固定.json')
                assert b['探索固定SHA256']==runner.digest(HERE/'探索条件の固定.json')
                for row in (a,b):
                    row.pop('経過秒');row.pop('探索固定SHA256')
                assert a==b,identifier
            else:
                assert runner.digest(before)==runner.digest(after),(identifier,folder)
            references[after.relative_to(runner.ROOT).as_posix()]=runner.digest(after)
            count+=1
    assert count==790
    proof=dict(全合格=True,旧条件数=158,旧入力数=4108,一致保存資料数=count,全数値一致=True,
        注文エンジンと入力と採否不変=True,現在API取得数=0,旧計画SHA256=runner.digest(HERE/'adaptive_cash_revision_plan.json'),
        新固定SHA256=runner.digest(HERE/'探索条件の固定.json'),参照SHA256=references)
    runner.save(HERE/'adaptive_cash_revision_results.json',proof)
    return proof


if __name__=='__main__':
    value=preserved_results()
    print('旧158条件の790資料を再計算と照合。全経済値・全台帳一致。')
