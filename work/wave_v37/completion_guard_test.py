"""完備資料の欠落・改変を人工的に作り、正式判定への混入を拒否する。"""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch
import completion_guard as guard


def main() -> None:
    """機能: 実物が完備した状態と、メモリ上の破損24種類を検査する。

    引数: なし。返り値: なし (None)。保存資料や売買結果は変更しない。
    """
    runner=guard.runner
    original_read, original_digest=runner.read,runner.digest
    cache={}
    def cached_digest(path):
        """機能: 人工改変試験内だけで不変の実物指紋を再利用する。

        引数: path (Path)。返り値: 実体SHA256 (str)。本番完備検査は毎回実物を読む。
        """
        if path not in cache: cache[path]=original_digest(path)
        return cache[path]
    with patch.object(runner,'digest',cached_digest): guard.verify()
    cases=('主件数不足','集約ID欠落','集約値だけ改変','セッション重複','会計不合格','因果件数不足',
        '波件数不足','会計根拠の脱落','指定波数改変','暫定合否改変','個別仕様改変','主会計記録重複',
        '波v2改訂未完','波v2参照1欠落','波旧SHA集合1欠落','波旧SHA改変',
        '波旧規則破壊','波旧参照継承欠落','波AST関数脱落','波AST証跡SHA欠落',
        '波失敗記録指紋改変','波成績変更true','波header旧版混在','波detail旧版混在')
    records=[]
    for case in cases:
        def changed(path):
            """機能: 一種類の破損だけを読取結果へ加える。

            引数: path (Path)。返り値: 人工破損した保存内容 (object)。
            """
            value=deepcopy(original_read(path))
            if case=='主件数不足' and path==runner.HERE/'主再生の完了.json': value['全条件数']-=1
            if path==runner.HERE/'全条件の期間集計.json.gz':
                if case=='集約ID欠落': value.pop()
                if case=='集約値だけ改変': value[0]['all_symbols']['TOPIX']['net_yen']+=1
            if case=='セッション重複' and path.parent.name=='sessions': value[0]=deepcopy(value[1])
            if path==runner.HERE/'partial_accounting_audit.json':
                if case=='会計不合格': value['全監査合格']=False
                if case=='主会計記録重複': value['条件'][0]=deepcopy(value['条件'][1])
            if case=='因果件数不足' and path==runner.HERE/'partial_causality_audit.json': value['future数']-=1
            if case=='波件数不足' and path==runner.HERE/'partial_wave_audit.json': value['波数']-=1
            if case=='会計根拠の脱落' and path.parent.name=='partial_accounting_details': value['保存資料SHA256'].pop(next(iter(value['保存資料SHA256'])))
            if case=='指定波数改変' and path.parent.name=='summaries': value['wave_passes']=0
            if case=='個別仕様改変' and path.parent.name=='summaries': value['spec']['primary']=not value['spec']['primary']
            if case=='暫定合否改変' and path==runner.HERE/'暫定判定.json': value['経済目安合格']=not value['経済目安合格']
            # ----------------------------------------
            # 元コード・保存成果を変更せず、波v2の改訂経路だけに欠落又は矛盾を作る。
            if path==runner.HERE/'partial_wave_revision.json':
                if case=='波v2改訂未完': value['改訂完了']=False
                if case=='波v2参照1欠落': value['参照SHA256'].pop(next(iter(value['参照SHA256'])))
                if case=='波成績変更true': value['成績変更']=True
            if path==runner.HERE/'partial_wave_revision_plan.json':
                if case=='波旧SHA集合1欠落': value['旧監査SHA256'].pop(next(iter(value['旧監査SHA256'])))
                if case=='波旧SHA改変': value['旧監査SHA256'][next(iter(value['旧監査SHA256']))]='0'*64
                if case=='波失敗記録指紋改変': value['失敗記録SHA256']='0'*64
            if path==runner.HERE/'partial_wave_fixed_v2.json':
                if case=='波旧規則破壊': value['規則']['全波数']-=1
                if case=='波旧参照継承欠落':
                    old=original_read(runner.HERE/'partial_wave_fixed.json')
                    value['SHA256'].pop(next(iter(old['SHA256'])))
            if path==runner.HERE/'partial_wave_revision_checks.json':
                if case=='波AST関数脱落': value['数値関数AST同一'].pop()
                if case=='波AST証跡SHA欠落': value['SHA256'].pop('partial_wave_revision_check.py')
            if case=='波header旧版混在' and path==runner.HERE/'partial_wave_audit.json': value['監査版']=1
            if case=='波detail旧版混在' and path.parent.name=='partial_wave_details': value['監査版']=1
            return value
        rejected=False
        with patch.object(runner,'read',changed),patch.object(runner,'digest',cached_digest):
            try: guard.verify()
            except (AssertionError,KeyError): rejected=True
        assert rejected,case
        records.append(dict(破損=case,拒否=True))
    runner.save(runner.HERE/'completion_guard_test.json',dict(全合格=True,破損拒否数=len(records),検査=records,
        ガードSHA256=original_digest(runner.HERE/'completion_guard.py'),試験SHA256=original_digest(runner.HERE/'completion_guard_test.py'),
        売買再生=False,保存資料変更=False))
    print('完備ガードの人工破損'+str(len(records))+'種類を拒否。',flush=True)


if __name__=='__main__':main()
