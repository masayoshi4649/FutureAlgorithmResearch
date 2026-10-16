"""根授権の110公開十二caseを一目的だけ読み、旧金融本文を読まず比較元を保存する。"""

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
PUBLIC=ROOT/'アルゴリズム調査/00110_価格票と出来高代理票の入口切り分け/入口情報別E01の全場会計.json'
EXPECTED='481f58915def42d729963119c0f852767921c369bee94e25852efc6382ca6a7f'


def run() -> None:
    """
    機能: 必要十二caseの正規場表/集計/条件と保存説明だけを一読射影する。
    引数: なし。
    返り値: None。旧親/時刻経路をコピー又は未測値で補完せず、再実行を拒否する。
    """
    plan=HERE/'110公開十二条件の一読射影計画.json';target=HERE/'110十二比較の保存公開会計.json'
    assert not plan.exists() and not target.exists()
    plan.write_text(json.dumps(dict(目的='111prepared比較元12caseをまとめて一読。6条件396会計は経済同値再利用、残6条件は元母比較。',
        source=dict(path=PUBLIC.relative_to(ROOT).as_posix(),SHA256=EXPECTED),
        generator_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        予定=dict(公開110一目的読取=1,金融本文=0,input=0,台帳=0,API=0,新金融=0)),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    saved=PUBLIC.read_bytes();assert hashlib.sha256(saved).hexdigest()==EXPECTED
    original=json.loads(saved.decode('utf-8-sig'));assert len(original['cases'])==12
    names=('rows','metrics','parameters','risk','capacity','directions','actual_legs','direction_quantities')
    cases={cid:{name:c[name] for name in names if name in c} for cid,c in original['cases'].items()}
    assert all(len(c['rows'])==66 for c in cases.values())
    value=dict(全合格=True,source=dict(path=PUBLIC.relative_to(ROOT).as_posix(),SHA256=EXPECTED),cases=cases,
        source_metadata=original.get('sources',{}),
        scope='正規場P/L/net/qと集計/条件だけ。個別親/原seq/時刻経路は未コピーで未測。',
        読取=dict(公開110一目的読取=1,金融本文=0,input=0,台帳=0,API=0,新金融=0))
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('110十二case一読射影 SHA '+hashlib.sha256(target.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':run()
