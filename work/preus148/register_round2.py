"""第一巡の失敗に対する第二巡の変更を、追加再生前に記録する。"""

import json
import zipfile
import importlib.util
from pathlib import Path
from datetime import datetime, timezone, timedelta
from verify_frozen import digest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    """第二巡8条件を凍結・照合・登録する。

    引数: なし。
    返り値: None。登録完了前に金融再生は行わない。
    """
    folder = HERE / 'round2'
    folder.mkdir(exist_ok=True)
    plan = json.loads((HERE / '再生計画148.json').read_text(encoding='utf-8'))
    plan.update(id='148_第二巡_確認時計と押戻り入口', name='確認時計と押戻り入口の改善8条件', purpose='条件比較',
        question='確認時計の5秒リセットを120秒へ変更し、短期の勢い追随に押戻りと再反発を加えると損失が減るか',
        change='Q01〜Q05は確認時計と速度・窓だけ。Q06〜Q08は方向一致後40pt押し・30pt反発、15分期限。買売対称。',
        repeat_reason='第一巡16条件は前段25夜全て赤字。P01前段−180万円、P06−22万円。現在場の下落波に未参加、価格時計5秒のリセットが頻発。三時間帯すべてで負けており特定時刻を除外するだけでは解決しない。',
        compares_to=['148_米国開始前の勢い入口と利益追跡'])
    configs = json.loads((HERE / 'configs_round2.json').read_text(encoding='utf-8'))
    plan['spec']['entry']['configurations'] = configs
    plan['spec']['entry']['method'] += '。第二巡は上記configurationsを優先。押戻り候補は長窓の方向反証・未知・15分期限で解除。'
    frozen = folder / '再生前実装.zip'
    with zipfile.ZipFile(frozen, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ('engine_round2.py', 'configs_round2.json', 'accounting.py', 'run148.py', 'run_round2.py', 'verify_round2.py'):
            archive.write(HERE / name, name)
    plan['spec']['implementation'] = {frozen.relative_to(ROOT).as_posix(): digest(frozen)}
    path = folder / '計画.json'
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    source = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec = importlib.util.spec_from_file_location('trial148second', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.analyzer().analyze(plan, [])['proposal_complete']
    record = module.store_trial(plan)
    (folder / '照合.json').write_text(json.dumps(record['preflight'], ensure_ascii=False, indent=2), encoding='utf-8')
    receipt = dict(returncode=0, id=plan['id'], implementation_sha256=digest(frozen),
                   created=datetime.now(timezone(timedelta(hours=9))).isoformat())
    (folder / '登録受領.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print('第二巡登録完了', flush=True)


if __name__ == '__main__':
    main()
