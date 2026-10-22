"""初回失敗の原因対照を八部品と実装指紋で固定する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
TRIAL = '119b_共同進行の失速復帰と事前価格保護の原因対照'


def digest(path: Path) -> str:
    """
    機能: 保存結果と実装をSHA256へ結び付ける。
    引数: path(Path) は対象ファイル。
    返り値: str。金融再生を伴わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    """
    機能: 事前計画を既存ファイルに重ねず保存する。
    引数: path(Path)、value(dict) は保存先と内容。
    返り値: None。UTF-8 JSONを新規作成する。
    """
    assert not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def prepare() -> None:
    """
    機能: 既所有の会計復元結果から入力cacheと比較対象を固定する。
    引数: なし。市場原本・保存NPZ本文を読まない。
    返り値: None。新しい経済的な勝ち候補の選択は行わない。
    """
    source = BASE / 'root_review/完成結果の同bytes参照.json'
    assert digest(source) == '13bdd30ecf5ad8dd12ce4d8f0aec96a025e7bd1bb36e33fa8b30bc02de0d2c15'
    result = json.loads(source.read_text(encoding='utf-8'))
    inputs = []
    for item in result['cache']:
        symbol, scene = item['symbol'], item['session']
        owned = BASE / 'audit_result119/recovered_owned/prepared' / symbol / (scene + '.npz')
        assert owned.stat().st_size == item['bytes']
        inputs.append(dict(session=scene, symbol=symbol, SHA256=item['SHA256'], bytes=item['bytes'],
                           source=item['path'], owned_path=owned.relative_to(ROOT).as_posix()))
    primary = {s: result['selection'][s]['chosen'][0] for s in ('TOPIX', 'NK225')}
    old_runs = [r for r in result['runs'] if r['method'] == primary[r['symbol']]]
    assert len(old_runs) == 80
    save(HERE / '入力目録.json', dict(sessions=result['sessions'], splits=result['splits'], inputs=inputs,
         old_primary=primary, old_main_runs=old_runs, old_specs=result['specs'],
         result_source=source.relative_to(ROOT).as_posix(), result_SHA256=digest(source),
         原市場追加読取=0, 入力cache本文読取=0,
         注意='全40場の初回失敗と損失親を見た後の開発対照。旧選択6/確認13等の名前は便宜的期間区分のみ。未見と主張しない。'))
    print('既所有入力80の目録を固定。原市場・保存NPZ本文の新読取0。')


def freeze() -> None:
    """
    機能: 二つの独立人工監査を確認し、経済再生前に正式照合・登録を行う。
    引数: なし。実装完成後にのみ実行する。
    返り値: None。原データ・API・金融実行は0。
    """
    meta = json.loads((HERE / '入力目録.json').read_text(encoding='utf-8'))
    # ----------------------------------------
    # 監査の完了と対象源は根agentが内容を確認した結合証跡で指定する。
    binding = json.loads((HERE / '人工監査の結合.json').read_text(encoding='utf-8'))
    assert binding['passed'] is True
    files = [HERE / name for name in ('plan_v2.py', 'run_v2.py', 'engine_v2.py', 'catalog_v2.py')]
    files += [BASE / 'engine119.py', BASE / 'catalog119.py']
    sources = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    for path, sha in binding['economic_sources'].items():
        assert sources[path] == sha
    manifest = dict(path=(HERE / '入力目録.json').relative_to(ROOT).as_posix(), sha256=digest(HERE / '入力目録.json'))
    save(HERE / '固定計画.json', dict(sources=sources, artificial_binding=binding, input_manifest=manifest))
    proposal = dict(id=TRIAL, name='失速復帰と執行保護の原因対照', purpose='条件比較',
        question='過去の共同進行の反転負けを、実際の復帰確認と事前価格保護で減らせるか',
        change='全玉教師の後追いを使わず、4入口×L20/40×2出口×2執行=32。旧主候補は入口を変えず4執行対照。',
        repeat_reason='初回は両市場の事前進行後に逆行し、方向損失が主因。単なる総収支反転ではなく、停止と復帰開始を事前固定した別政策を実行する。',
        compares_to=['119_全玉清算教師と異なる戦略から場内安定黒字を探す'],
        evidence=[dict(path='work/stability119_20261017/diagnosis/選択単体と三枠は何で負けたか.md'),
                  dict(path='アルゴリズム調査/共通/知見台帳/入口.md'),
                  dict(path='アルゴリズム調査/共通/知見台帳/売買の工夫.md')],
        spec=dict(
            entry=dict(規則='catalog_v2.pyの4入口×L20/40。A共同2R進行→両市場停止→.5R復帰・自己二本帯逆抜け、B安定中心2R乖離→.5R復帰＋相手反対初動、C共同2R即逆張り対照、D自己の失速復帰対照。',
                       尺度='既historical(L)。max(5観測tick,close×.0005,過去L絶対差中央値×sqrt(L)×2)。相手は自己より60秒以上前かつ公開時点過去。',
                       注文='0は次BBO成行。bit1有りは判断時の既知気配幅≤2観測tick・anchor距離≤2tickを審査しanchor±2tickの固定上限/下限で60秒待つ。発注後に悪気配を見て取消しない。'),
            management=dict(思想='停止だけで反転を仮定せず、実復帰を確認。同じ相手足の重複投票・同一波の毎分再入を防ぐ。entry0を撤回と呼ばない。',
                            選択='本試行は全36条件を報告。前40場は全て開発既知。未知確認の成功とはしない。無取引と未清算は成功へ含めない。',
                            共通事後順位='新32だけ対象。両net/median/利益上位3場除外netが正・未清算0を資格とし、少ない方の黒字場数、少ない方のmedian/全40平均絶対net、両商品の最悪赤字/平均黒字の大きい側が小、最後ID固定順。円額の銘柄横断合計は使わない。'),
            exit=dict(方式='新8入口には±1R対称又は−1R損切り・+1Rから.5R追尾、及び各入口の明示的反証。保有時間の強制固定なし。',
                      場予算='新政策は最初の有効R×数量倍率を円尺度とし、含み損と予定返済料込み清算資産が−2倍で返済停止、利益上限無し。旧対照は元の−3倍/+1.5倍。次約定で超過し得る。',
                      執行保護='bit2は返済判断Lastから不利2観測tickの固定指値。期限を延ばさず価格時計30秒以上最初quoteで成行。場末は保護待ちを中止し成行。常に次原row、EOF未返済は実返済に偽装しない。',
                      時間='Day15:00/Night05:20新規終了、Day15:20/Night05:40返済判断。'),
            allocation=dict(数量='比較尺度としてTOPIXmini10/NK225micro20。新規1建玉・同方向追加無し。数量削減で安定を捏造しない。',
                            固定比較='初回で当時選択したTOP/NK別の旧入口を保持した執行0/新規のみ1/返済のみ2/両方3の4対照。'),
            costs=dict(片道='TOPmini41.8円/NKmicro11円、注文全枚数で円未満切捨て、新規・全返済。',
                       気配='ラージの正常BBOを代理使用し、買ask/売bidの全差を負担。保護待ちでもBBO含み損と返済料を評価。'),
            execution=dict(順序='同rawrowは観測→公開。判断と厳密に別の後rowで約定。同価格時計の後rowは可。',
                           価格制限='実小型呼値TOPmini.25/NKmicro5へ丸める。保護指値は実反対気配crossが必要、capより有利なBBOではBBOで約定。数量待ち順位は未証明。',
                           時刻限界='価格時計しかなく真受信順・壁時計期限・実mini/micro板の再現は未証明。30秒の現実約定保証ではない。'),
            data=dict(input_manifests=[manifest],
                      sessions=meta['sessions'], 入力='会計監査で同bytes保全済みprepared80。各一読。市場原本と原cacheの追加読0。',
                      開発='全40の既知開発。旧期間分割を未知確認と呼ばない。'),
            implementation=sources))
    save(HERE / '試行計画.json', proposal)
    manager = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    for command, name in [('check', '正式照合'), ('register', '正式登録')]:
        process = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(manager), command, '--proposal', str(HERE / '試行計画.json')],
                                 cwd=ROOT, capture_output=True, encoding='utf-8')
        save(HERE / (name + 'の全出力.json'), dict(終了コード=process.returncode, stdout=process.stdout, stderr=process.stderr))
        assert process.returncode == 0, name
        if command == 'check':
            assert json.loads(process.stdout)['proposal_complete'] is True
        print(name + '完了', flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'freeze': freeze}[sys.argv[1]]()
