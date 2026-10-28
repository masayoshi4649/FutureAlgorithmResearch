"""再生条件と入力を凍結して、共通試行履歴へ金融再生前に登録する。"""

from pathlib import Path
import hashlib
import importlib.util
import json
import zipfile
from datetime import datetime, timezone, timedelta

from configs import CONFIGS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def fingerprint(path):
    """ファイルのSHA256を取得する。

    引数: path(Path)は実在する入力または実装。
    返り値: strは内容指紋。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    """条件・コードの固定後に既存試行と照合して登録する。

    引数: なし。
    返り値: None。登録成功時だけ受領ファイルを出力する。
    """
    frozen = HERE / '再生前実装148.zip'
    with zipfile.ZipFile(frozen, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ('engine.py', 'configs.py', 'accounting.py', 'run148.py', 'prepare_inputs.py', 'prepare_current.py'):
            archive.write(HERE / name, name)
    manifests = [HERE / '入力目録148.json', HERE / 'current_manifest.json']
    plan = dict(id='148_米国開始前の勢い入口と利益追跡', name='米国開始前の勢い入口と利益追跡16条件', purpose='新仮説',
        question='米国現物開始前だけ勢いで参加し、赤字の方向反証と黒字の追跡利確を分けるとD07の取り逃しを減らし安定性を改善できるか',
        change='価格の確定分足OLS傾きによる新入口、玉別初期stopと含み益発動後trail。米国前のみを変更。D07の後段通知は独立仮想運転のものを再利用。',
        repeat_reason='00147で現D07が三波を見送り、傾き変化を条件に使わないことを確認した。今回は新たな売買条件16種を全25夜へ検証する。過去の同時加速という名称の価格差条件とは異なる。',
        compares_to=['147_三波の現D07再生と傾き変化の利用監査'],
        spec=dict(entry=dict(method='確定済み正常気配中値の3/5/10/20本OLS、順方向速度、持続確認、加速条件の有無', configurations=[dict(c, add_gain_points=c['add_gain_points'] or '追加なし') for c in CONFIGS]),
                  management=dict(method='買売対称。初期5+5、10一括、2+3+5。追撃後も各玉の固定初期stopを維持。返済判断後は同じ親へ再追加しない。欠測中は確認時計を進めない。'),
                  exit=dict(method='100又は140pt初期損切り。未保護かつ非黒字玉だけ反対方向の支持継続で返済。60/100/160pt順行後から40/80/120ptの玉別トレール。US-15分全返済。現在途中は終端精算なし。'),
                  allocation=dict(product='NK225mini', max_per_side=10, switching='US-15まで新前段。US+15以後は17時から継続する独立仮想D07。新前段実現損益を仮想D07の予算へ注入しない。'),
                  costs=dict(fee=0, point_value=100, spread='売買気配差を全額計上'),
                  execution=dict(price='判断後の次正常ラージBuy1/Sell1気配。現在の実mini板の約定保証ではない。',clock='保存原価格時計順。同じ時計は原行順。実受信時計欠測。',verification='未来改変・prefix不変・正負反転・欠測・上限・次行約定の人工試験後に再生'),
                  data=dict(sessions=[p.stem for p in sorted((HERE / 'inputs').glob('*_Night.pkl'))],
                            input_manifests=[dict(path=p.relative_to(ROOT).as_posix(), sha256=fingerprint(p)) for p in manifests],
                            range='2026-09-21〜10-23の保存25夜。10月26日17:00〜21:13:52未満は説明用途中場として別集計。全て既知資料で完全未見検証ではない。'),
                  implementation={frozen.relative_to(ROOT).as_posix(): fingerprint(frozen)}))
    (HERE / '再生計画148.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    source = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    spec = importlib.util.spec_from_file_location('trial148', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.analyzer().analyze(plan, [])['proposal_complete']
    record = module.store_trial(plan)
    (HERE / '事前照合148.json').write_text(json.dumps(record['preflight'], ensure_ascii=False, indent=2), encoding='utf-8')
    receipt = dict(returncode=0, id=plan['id'], created=datetime.now(timezone(timedelta(hours=9))).isoformat(),
                   plan_sha256=fingerprint(HERE / '再生計画148.json'), implementation_sha256=fingerprint(frozen))
    (HERE / '登録受領.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print('148登録完了', flush=True)


if __name__ == '__main__':
    main()
