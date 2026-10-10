"""事前監査の改変・欠落が実相場再生へ進まないことを検査する。"""

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import adaptive_startup_guard as guard


def main() -> None:
    """機能: 実物の合格とメモリ上の37破損拒否を確認する。

    引数: なし。返り値: なし (None)。保存証跡や売買を改変しない。
    """
    runner=guard.runner;original_read=runner.read;original_digest=runner.digest;cache={}
    def digest(path: Path) -> str:
        """機能: 人工試験内だけ実体指紋の重複読取を省く。

        引数: path (Path)。返り値: SHA256 (str)。本番ガードは毎回実物を読む。
        """
        if path not in cache:cache[path]=original_digest(path)
        return cache[path]
    with patch.object(runner,'digest',digest):guard.validate()
    cases=('設計条件欠落','入力件数不足','入力で新損益読取','旧A0照合不足','注文人工不合格',
        '接続件数不足','接続実装変更','乱数経路不合格','乱数経路数不足','主仮説差替え',
        '採否閾値変更','旧採否規則変更','因果入力不足','因果ID重複','因果必須SHA欠落',
        '波境界不足','波ID欠落','波人工不合格','会計件数不足','会計被覆重複',
        '会計人工不合格','統計破損拒否不足','会計必須SHA欠落','波破損検査不足',
        '因果分岐検査不足','採否接続検査不足','設計実装変更','現在保存物参照',
        '分岐件数キー欠落','分岐分類重複','因果主案差替え','分岐未来改変不一致','因果新損益既読','因果主件数不足',
        '独立枠不合格','独立乱数経路不足','独立枠ソース欠落')
    records=[]
    for case in cases:
        def changed(path: Path) -> object:
            """機能: 一種類だけ人工的な欠落又は矛盾を作る。

            引数: path (Path)。返り値: 改変した読取結果 (object)。
            """
            value=deepcopy(original_read(path));name=path.name
            if name=='adaptive_design_fixed.json':
                if case=='設計条件欠落':value['conditions'].pop()
                if case=='設計実装変更':value['実装SHA256']='0'*64
            if name=='branch_input_runtime_fixed.json':
                if case=='入力件数不足':value['新窓入力数']-=1
                if case=='入力で新損益読取':value['新損益読取']=True
                if case=='現在保存物参照':value['現在保存物使用']=True
            if name=='engine_audit.json':
                if case=='旧A0照合不足':value['旧A0一致入力数']-=1
                if case=='注文人工不合格':value['全合格']=False
            if name=='adaptive_runner_synthetic.json':
                if case=='接続件数不足':value['全条件接続数']-=1
                if case=='接続実装変更':value['SHA256']['adaptive_runner.py']='0'*64
            if name=='random_path_audit.json':
                if case=='乱数経路不合格':value['全合格']=False
                if case=='乱数経路数不足':value['人工再生数']-=1
            if name=='adaptive_slot_fixed.json':
                if case=='独立枠不合格':value['全合格']=False
                if case=='独立乱数経路不足':value['固定乱数人工再生数']-=1
                if case=='独立枠ソース欠落':
                    value['参照SHA256'].pop(next(k for k in value['参照SHA256'] if Path(k).name=='adaptive_shadow_oracle.py'))
            if name=='adaptive_assessment_fixed.json' and case=='主仮説差替え':value['規則']['主仮説']='A0'
            if name=='adaptive_assessment_revision.json' and case=='採否閾値変更':value['採否閾値変更']=True
            if name=='adaptive_assessment_fixed_v1.json' and case=='旧採否規則変更':value['規則']['主仮説']='A0'
            if name=='adaptive_causality_fixed.json':
                if case=='因果入力不足':value['規則']['全検査入力数']-=1
                if case=='因果ID重複':value['規則']['全条件ID'].append(value['規則']['全条件ID'][0])
                if case=='因果必須SHA欠落':value['SHA256'].pop('work/wave_v38/adaptive_causality_audit.py')
                if case=='因果主案差替え':value['規則']['主案全26']='A0'
                if case=='因果新損益既読':value['新実相場損益']=True
                if case=='因果主件数不足':value['規則']['主検査入力数']-=1
            if name=='adaptive_wave_fixed.json':
                if case=='波境界不足':value['規則']['全境界数']-=1
                if case=='波ID欠落':value['規則']['補助条件ID'].pop()
                if case=='波人工不合格':value['合成検査合格']=False
            if name=='adaptive_accounting_fixed.json':
                if case=='会計件数不足':value['全入力数']-=1
                if case=='会計被覆重複':value['人工検査']['条件被覆'][0]=deepcopy(value['人工検査']['条件被覆'][1])
                if case=='会計人工不合格':value['人工検査']['全合格']=False
                if case=='統計破損拒否不足':value['人工検査']['独立統計破損拒否数']=207
                if case=='会計必須SHA欠落':value['参照SHA256'].pop('work/wave_v38/adaptive_slot_audit.py')
            if name=='adaptive_wave_selftest.json' and case=='波破損検査不足':value['負例拒否数']-=1
            if name=='adaptive_causality_selftest.json' and case=='因果分岐検査不足':value['分岐分類検査数']-=1
            if name=='adaptive_causality_selftest.json':
                if case=='分岐件数キー欠落':value.pop('分岐分類検査数')
                if case=='分岐分類重複':value['分岐分類検査'][0]=deepcopy(value['分岐分類検査'][1])
                if case=='分岐未来改変不一致':value['分岐分類検査'][0]['future一致']=False
            if name=='adaptive_assessment_test.json' and case=='採否接続検査不足':value['人工検査数']=47
            return value
        refused=False
        with patch.object(runner,'read',changed),patch.object(runner,'digest',digest):
            try:guard.validate()
            except (AssertionError,KeyError):refused=True
        assert refused,case
        records.append(dict(破損=case,拒否=True))
    runner.save(runner.HERE/'adaptive_startup_guard_test.json',dict(全合格=True,破損拒否数=len(records),検査=records,
        ガードSHA256=original_digest(runner.HERE/'adaptive_startup_guard.py'),
        試験SHA256=original_digest(Path(__file__)),新実相場損益=False,保存資料変更=False))
    print('起動ガードの37人工破損を拒否。',flush=True)


if __name__=='__main__':main()
