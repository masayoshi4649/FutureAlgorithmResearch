"""追加4条件と独立Goコピーを追加金融再生前に凍結する。"""

from pathlib import Path
import json
from engine_freeze149 import reference

HERE=Path(__file__).resolve().parent


def main():
    """追加条件・実装の指紋と第一巡からの変更有無を保存する。

    引数: なし。返り値: None。元研究器は書き換えない。
    """
    files=[HERE/'configs_round2.json',HERE/'engine追加仕様149.md',Path(__file__)]
    files+=sorted((HERE/'engine_go_round2').rglob('*.go'))
    files += [HERE/'engine_go_round2'/name for name in ('go.mod','go.sum','NK225_D07.toml')]
    records=[]
    for path in files:
        value=reference(path)
        if path.is_relative_to(HERE/'engine_go_round2'):
            prior=HERE/'engine_go'/path.relative_to(HERE/'engine_go_round2')
            if prior.exists():
                value['round1']=reference(prior)
                value['same_as_round1']=value['sha256']==value['round1']['sha256']
        records.append(value)
    with (HERE/'engine指紋149_round2.json').open('x',encoding='utf-8') as stream:
        json.dump(dict(files=records,financial_replays=0,artificial_tests_passed=19,
                       change='特徴保持の選択と後半22/30分時計の復元だけ。旧金融結果は再利用。'),stream,ensure_ascii=False,indent=2)


if __name__=='__main__':main()
