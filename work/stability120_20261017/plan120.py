"""過去との違いと八部品を、段階トレーリング実測前に照合・登録する。"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import catalog120


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRIAL = '120_動く極値の段階追尾新規と利益玉の部分回転'
MANAGER = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def digest(path: Path) -> str:
    """
    機能: 小目録又は経済源の指紋を求める。
    引数: path(Path)は既存ファイル。
    返り値: strはSHA256。価格本文は読まない。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    """
    機能: 小さい事前計画と人工証跡を読む。
    引数: path(Path)はUTF-8 JSON。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 照合前の源と結果を新規保存する。
    引数: path(Path)、value(dict)は出力先と内容。
    返り値: None。既存結果・計画を上書きしない。
    """
    assert not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def prepare() -> None:
    """
    機能: 保存済み小目録から八十の価格配列参照だけを固定する。
    引数: なし。
    返り値: None。原市場・NPZ数値・金融再生は0。
    """
    oldpath = ROOT / 'work/stability119_20261017/v3/入力目録.json'
    assert digest(oldpath) == '86b8989e60b3f93461f27be3af08c80a7b3beffba9c7f07c4e3f583f15e49cdf'
    old = read(oldpath)
    inputs = [dict(symbol=item['symbol'], session=item['session'],
        path=item['old_owned_path'], sha256=item['old_SHA256']) for item in old['inputs']]
    assert len(inputs) == 80 and len(old['sessions']) == 40
    save(HERE / '入力目録.json', dict(inputs=inputs, sessions=old['sessions'],
        origin=dict(path=oldpath.relative_to(ROOT).as_posix(),sha256=digest(oldpath)),
        原市場追加読取=0,金融再生=0,注意='既知40場。新しい独立標本へ数えない。'))
    print('八十保存入力の参照を準備しました。数値読取・金融0。')


def freeze(auditpath: Path) -> None:
    """
    機能: 独立人工合格と四つの源を拘束し、八部品を正式登録する。
    引数: auditpath(Path)は人工データだけの完了証跡。
    返り値: None。登録完了後だけrun120を許す。
    """
    auditpath = auditpath.resolve()
    audit = read(auditpath)
    assert audit['passed'] is True
    assert audit['engine_sha256'] == digest(HERE / 'engine120.py')
    sources = {(HERE/name).relative_to(ROOT).as_posix():digest(HERE/name)
        for name in ('plan120.py','run120.py','engine120.py','catalog120.py')}
    meta = read(HERE / '入力目録.json')
    binding = dict(passed=True,path=auditpath.relative_to(ROOT).as_posix(),sha256=digest(auditpath))
    manifest = dict(path=(HERE/'入力目録.json').relative_to(ROOT).as_posix(),sha256=digest(HERE/'入力目録.json'))
    save(HERE / '固定計画.json', dict(sources=sources,input_manifest=manifest,
        artificial_audit=binding,specs=catalog120.specifications()))
    proposal = dict(id=TRIAL,name='動く極値からの段階新規と利益玉の個別追尾回転',purpose='条件比較',
        question='少量の反転試行から段階増加し、利益玉を部分回転すると全残玉を含む場内収支を安定させられるか',
        change='動く中値極値から3/4/5…単位の一枚新規、玉別純益追尾、返済枠再武装。八運用×三幅×二追尾。',
        repeat_reason='00012は準備水準固定、00057は固定段、00067は元玉と保険全体追尾。動く極値の新規、利益UID個別追尾、空き枠再準備の組合せとは同一と確認できない。既試行思想を新発明とせず、違いを一部品ずつ対照。未整理の全旧試行について重複なしとは主張しない。',
        compares_to=['119c_小試行と当初リスクを増やさない順行追加の対照',
            '119_全玉清算教師と異なる戦略から場内安定黒字を探す'],
        evidence=[dict(path=p) for p in (
            'アルゴリズム調査/共通/知見台帳/売買の工夫.md',
            'アルゴリズム調査/00012_状態切替と柔軟な建玉管理/README.md',
            'アルゴリズム調査/00057_中期売買と週内グリッドの手数料込み検証/README.md',
            'アルゴリズム調査/00067_両建て保険と途中管理/README.md',
            'work/stability120_20261017/diagnosis/追尾新規と利益玉回転の既試行差及び最小対照.md',
            'work/stability120_20261017/diagnosis/参考照合_00057_00067.md')],
        spec=dict(
            entry=dict(価格='正常BBO中値の追跡安値+3+j単位で一枚買い、高値-同幅で売り。上昇行だけ買い、下落行だけ売り。各枠独立。',
                単位='最初の当時中値×0.0125/0.025/0.05%を観測TOP0.5/NK10へ四捨五入、最小一刻み。場中固定、ATRなし。'),
            management=dict(枠='各方向TOP10/NK20の一枚枠。返済後当該枠だけ現在中値から再準備。固定段対照、再利用無し対照。',
                両方向='HEDGEと比較しNETは最悪反対一枚へ新規を写し、FLIPは旧方向全玉を予約。RECYCLEは累積確定純益>=最悪玉清算損2倍なら一枚整理。'),
            exit=dict(玉別='各玉の費用後清算益最高値が追尾幅+1単位に達したら起動。最高値から1又は3単位戻り、当時純益正なら返済予約。後続気配が赤字でも取り消さない。',
                対照='HARDは各玉費用後損失3単位で返済、ALLSIDEは利益追尾成立時同方向全玉返済。',
                時刻='Day15:00/Night05:20新規終了。15:20/05:40全玉返済を判断し次正常原行で実行。EOF時仮想約定を置かず残玉は別記。'),
            allocation=dict(数量='全て各注文1枚、片方向最大10mini/20micro。8運用×3幅×2追尾=48、40場×2商品=3840口座。',
                評価='両商品ごとnet/中央値/利益上位3場除外/黒赤無取引/最悪/保有中DDを比較。共通条件を優先。全場既知開発で将来成功とは呼ばない。'),
            costs=dict(料金='TOPmini41.8/NKmicro11円片道、一注文一枚で各floor=41/11。全入口・利確・損切・終端へ課金。',
                気配='新規買ask/売bid、返済逆側。中値での利益やトリガ水準の架空約定を主結果に使わない。'),
            execution=dict(先後='判断原行より厳密後の最初正常原行、同価格時計の後原行は可。返済予約を新規予約より先に実行。新規fill行の判断返済は更に後原行。',
                資格='原行順維持、価格時計の過去最大より古い/場外/非有限/逆転BBOを除外。日付補完や価格線での約定なし。',
                限界='ラージ気配の小型代理、真受信時計・注文待ち順・実小型板は未観測。5秒最悪遅延試験ではない。'),
            data=dict(input_manifests=[manifest],sessions=meta['sessions'],入力='119所有済み80NPZを各一読、quotes5列を全48で共有。原市場とAPI0。'),
            implementation=sources))
    for row in proposal['evidence']:
        assert (ROOT/row['path']).is_file(), row['path']
    save(HERE/'試行計画.json',proposal)
    for command,name in (('check','事前照合の全出力.json'),('register','正式登録の全出力.json')):
        process = subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),command,
            '--proposal',str(HERE/'試行計画.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/name,dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
        print(command,process.returncode,flush=True)
        assert process.returncode == 0, process.stderr[-2000:]


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=('prepare','freeze'))
    parser.add_argument('--audit',type=Path)
    args=parser.parse_args()
    if args.command=='prepare':
        prepare()
    else:
        assert args.audit
        freeze(args.audit)
