"""米国前の時刻制限と前後独立運転の条件を金融再生前に凍結・登録する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile
from datetime import datetime, timezone, timedelta

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRIAL_ID = '149_米国前の時刻制限と米国後の全初期化'


def digest(path):
    """既存ファイルのSHA256を計算する。

    引数: path(Path)はローカルファイル。
    返り値: strは小文字SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def reference(path):
    """入力又は実装を内容指紋付き相対パスで示す。

    引数: path(Path)はプロジェクト内の実在ファイル。
    返り値: dictはpath/sha256/bytes。
    """
    assert path.resolve().is_relative_to(ROOT)
    return dict(path=path.relative_to(ROOT).as_posix(),sha256=digest(path),bytes=path.stat().st_size)


def main():
    """全16条件と隔離Go実装・原資料目録を凍結し、既存管理器で照合・登録する。

    引数: なし。
    返り値: None。成功時だけ登録受領149.jsonを発行する。
    """
    receipt_path=HERE/'登録受領149.json'
    assert not receipt_path.exists(), '同じ試行を再登録しない'
    manifest_path=HERE/'data/原資料一覧149.json'
    configs=json.loads((HERE/'configs149.json').read_text(encoding='utf-8-sig'))
    manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    assert len(configs)==16 and len(set(c['id'] for c in configs))==16
    engine=HERE/'engine_go'
    sources=sorted(p for p in engine.rglob('*') if p.is_file() and (p.suffix in ('.go','.toml') or p.name in ('go.mod','go.sum')))
    sources += [HERE/'configs149.json', HERE/'engine仕様149.md']
    frozen=HERE/'再生前実装149.zip'
    with zipfile.ZipFile(frozen,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path,path.relative_to(HERE).as_posix())
    refs=[reference(p) for p in sources]
    fixed_configs=[dict(c,owners=c.get('owners') or '全担当') for c in configs]
    plan=dict(id=TRIAL_ID,name='米国前の時刻制限と前後独立運転16対照',purpose='条件比較',
              question='現GoD07の制限だけを解除した時と、米国前全返済・米国開始から全状態再準備を行った時に、前半と全夜の赤字頻度・深さは改善するか',
              change='隔離した現GoD07へ時計と担当の対照を導入。R系列はUS-n分で全返済し、USから特徴・始値・ATR・予算・売買状態を全初期化する。',
              repeat_reason='初期旧入口には米国後限定で損失減の対照があるが、改良後D07での時計制限だけの効果は未検証。00148は価格傾き系列の新入口であり、今回の同一D07機構の対照とは異なる。',
              compares_to=['148_米国開始前の勢い入口と利益追跡','148_第二巡_確認時計と押戻り入口'],
              spec=dict(entry=dict(method='現GoD07の価格条件・ルール式を固定し、主担当開始時刻・補完時刻・有効担当だけ変更。',configurations=fixed_configs),
                        management=dict(method='D07の担当別利益回収・再参加・反証を固定。三担当5/3/2枚。担当除外対照では除外分を再配分しない。R後半は独立FeaturesとPortfolioでUS前の指標を使わない。'),
                        exit=dict(method='D07の損切り・利確幅を固定。R前半はUS5/15/30分前で新規停止・残玉全返済。後半は保存場末返済。境界未解消なら次区間新規禁止。途中場は評価損益を分離する。'),
                        allocation=dict(product='NK225mini',cap=10,point_value=100,method='主担当5枚、追加3枚、別入口2枚。C06〜08/R06/R07の前半は指定担当だけ。R後半は全担当へ戻す。'),
                        costs=dict(fee=0,spread='売買両側のラージ最良気配差を計上。実miniの約定保証ではない。'),
                        execution=dict(price='判断後の次の正常な日経原行の買ask/売bid。自己所有ID・枚数・現金を照合。',
                                       clock='CurrentPriceTime順、同一時計は各市場の原行順。二市場同時計を未来参照しない。独立受信時計は保存されていない。',
                                       baseline='現Go実装を同じ約定模型で再生したC00を主対照。既存Python145保存会計との一致は別監査し、同値と偽らない。'),
                        data=dict(sessions=[s['session'] for s in manifest['sessions']],input_manifests=[reference(manifest_path)],
                                  range='保存25夜。取得済み10月26日の21:13までの途中場は別集計。既知開発群であり完全な未見検証ではない。'),
                        implementation={frozen.relative_to(ROOT).as_posix():digest(frozen)}))
    plan_path=HERE/'再生計画149.json'
    plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (HERE/'凍結ソース149.json').write_text(json.dumps(refs,ensure_ascii=False,indent=2),encoding='utf-8')
    manager_path=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec=importlib.util.spec_from_file_location('研究149試行管理',manager_path)
    manager=importlib.util.module_from_spec(spec);spec.loader.exec_module(manager)
    preflight=manager.analyzer().analyze(plan,[])
    assert preflight['proposal_complete'], preflight
    print('条件・実装・原資料目録を凍結。既存試行との照合・登録を開始します。',flush=True)
    record=manager.store_trial(plan)
    (HERE/'事前照合149.json').write_text(json.dumps(record['preflight'],ensure_ascii=False,indent=2),encoding='utf-8')
    receipt=dict(id=TRIAL_ID,returncode=0,registered=True,created_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
                 plan=reference(plan_path),implementation=reference(frozen),inputs=reference(manifest_path),sources=refs)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print('研究149の登録完了。受領と指紋確認後だけ金融再生できます。',flush=True)


if __name__=='__main__':
    main()
