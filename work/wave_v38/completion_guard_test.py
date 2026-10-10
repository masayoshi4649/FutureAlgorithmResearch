"""完備資料の欠落や改変が正式判定へ混入しないことを確認する。"""

from copy import deepcopy
from unittest.mock import patch
import completion_guard as guard


def main() -> None:
    """機能: 実物の完備とメモリ上の破損を検査する。

    引数: なし。返り値: なし (None)。保存資料・売買結果は改変しない。
    """
    runner=guard.runner
    original_read,original_digest=runner.read,runner.digest
    hashes={}

    def cached_digest(path):
        """機能: 人工改変試験中だけ不変の実物指紋を再利用する。

        引数: path (Path)。返り値: SHA256 (str)。
        """
        if path not in hashes:hashes[path]=original_digest(path)
        return hashes[path]

    with patch.object(runner,'digest',cached_digest):guard.verify()
    cases=('主件数不足','補助件数不足','集約ID欠落','集約値改変','セッション重複',
        '会計不合格','因果件数不足','波件数不足','会計根拠脱落','指定波数改変',
        '暫定採否改変','個別仕様改変','主会計重複','分岐監査不合格','成熟監査不合格',
        '全組R監査不合格','会計分岐詳細不合格','因果詳細不合格','波詳細版改変','会計実体SHA改変',
        '会計影成熟不合格','改訂未完了','旧結果同値不合格','旧結果1資料脱落')
    results=[]
    for case in cases:

        def changed(path):
            """機能: 読取結果に一種類の破損を作る。

            引数: path (Path)。返り値: 人工破損した内容 (object)。
            """
            value=deepcopy(original_read(path))
            if case=='主件数不足' and path==runner.HERE/'主再生の完了.json':value['全条件数']-=1
            if case=='補助件数不足' and path==runner.HERE/'supplementary/主再生の完了.json':value['全条件数']-=1
            if path==runner.HERE/'全条件の期間集計.json.gz':
                if case=='集約ID欠落':value.pop()
                if case=='集約値改変':value[0]['all_symbols']['TOPIX']['net_yen']+=1
            if case=='セッション重複' and path.parent.name=='sessions':value[0]=deepcopy(value[1])
            if path==runner.HERE/'adaptive_accounting_audit.json':
                if case=='会計不合格':value['全監査合格']=False
                if case=='主会計重複':value['条件'][0]=deepcopy(value['条件'][1])
                if case=='分岐監査不合格':value['全分岐独立一致']=False
                if case=='成熟監査不合格':value['全成熟注文独立一致']=False
                if case=='全組R監査不合格':value['全組R超過独立一致']=False
                if case=='会計実体SHA改変':value['条件'][0]['実体SHA256']='0'*64
            if case=='因果件数不足' and path==runner.HERE/'adaptive_causality_audit.json':value['future数']-=1
            if case=='波件数不足' and path==runner.HERE/'adaptive_wave_audit.json':value['波数']-=1
            if path.parent.name=='adaptive_accounting_details':
                if case=='会計根拠脱落':value['保存資料SHA256'].pop(next(iter(value['保存資料SHA256'])))
                if case=='会計分岐詳細不合格':value['検査'][0]['分岐集計独立一致']=False
                if case=='会計影成熟不合格':value['検査'][0]['影の独立公開と執行']['最新成熟計画一致']=False
            if case=='因果詳細不合格' and path.parent.name=='adaptive_causality_details':value['検査'][0]['future一致']=False
            if case=='波詳細版改変' and path.parent.name=='adaptive_wave_details':value['監査版']=0
            if case=='指定波数改変' and path.parent.name=='summaries':value['wave_passes']=-1
            if case=='個別仕様改変' and path.parent.name=='summaries':value['spec']['primary']=not value['spec']['primary']
            if case=='暫定採否改変' and path==runner.HERE/'暫定判定.json':value['経済目安合格']=not value['経済目安合格']
            if case=='改訂未完了' and path==runner.HERE/'adaptive_cash_revision_ready.json':value['再起動可能']=False
            if path==runner.HERE/'adaptive_cash_revision_results.json':
                if case=='旧結果同値不合格':value['全数値一致']=False
                if case=='旧結果1資料脱落':value['参照SHA256'].pop(next(iter(value['参照SHA256'])))
            return value

        rejected=False
        with patch.object(runner,'read',changed),patch.object(runner,'digest',cached_digest):
            try:guard.verify()
            except (AssertionError,KeyError):rejected=True
        assert rejected,case
        results.append(dict(破損=case,拒否=True))
    runner.save(runner.HERE/'completion_guard_test.json',dict(全合格=True,破損拒否数=len(results),検査=results,
        ガードSHA256=original_digest(runner.HERE/'completion_guard.py'),
        試験SHA256=original_digest(runner.HERE/'completion_guard_test.py'),売買再生=False,保存資料変更=False))
    print(f'完備ガードの破損{len(results)}種類を拒否。',flush=True)


if __name__=='__main__':main()
