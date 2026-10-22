"""小試行・順行追加を、単純な枚数縮小と区別して実測前に登録する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
TRIAL = '119c_小試行と当初リスクを増やさない順行追加の対照'


def digest(path: Path) -> str:
    """
    機能: 実装と入力目録の指紋を求める。
    引数: path(Path) はファイル位置。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 保存済みの私有JSONを読み込む。
    引数: path(Path) はUTF-8 JSON。
    返り値: dict。市場原本を読まない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 初回の計画や結果を上書きせず新規保存する。
    引数: path(Path)、value(dict) は場所と内容。
    返り値: None。原市場に書き込まない。
    """
    assert not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def prepare() -> None:
    """
    機能: 既存六入口を再利用するための160保存入力を固定する。
    引数: なし。価格本文や保存NPZを再読しない。
    返り値: None。過去に選んだ候補を未見成功へ置き換えない。
    """
    old = read(BASE / 'v2/入力目録.json')
    source = BASE / 'v2/root_owned/復帰確認と執行保護の全四十場.json'
    assert digest(source) == '7c56485d4b168928bd432cdb9644037ad2c4d733c19b3fc0168786a928b0586f'
    second = read(source)
    inputs = []
    lookup = {(Path(i['path']).stem, Path(i['path']).parent.name): i for i in second['cache']}
    for item in old['inputs']:
        v2 = lookup[item['session'], item['symbol']]
        inputs.append(dict(session=item['session'], symbol=item['symbol'],
                           old_owned_path=item['owned_path'], old_SHA256=item['SHA256'],
                           v2_path=v2['path'], v2_SHA256=v2['SHA256']))
    old_ids = [f'{family}_L20_X0_E0_G0' for family in ('COMMON', 'OPEN', 'CENTER', 'FAIL')]
    second_ids = [f'{family}_L20_X5_P0' for family in ('A', 'D')]
    old_indexes = [next(k for k, s in enumerate(old['old_specs']) if s['id'] == name) for name in old_ids]
    second_indexes = [next(k for k, s in enumerate(second['specs']) if s['id'] == name) for name in second_ids]
    save(HERE / '入力目録.json', dict(inputs=inputs, sessions=old['sessions'], splits=old['splits'],
         old_ids=old_ids, v2_ids=second_ids, old_indexes=old_indexes, v2_indexes=second_indexes,
         注意='二回の初回失敗を見た後の既知全40場の配分対照。正しい方向を後から選んでいない。',
         原市場追加読取=0, 金融追加実行=0))
    print('既存六入口と160保存入力を固定しました。')


def freeze() -> None:
    """
    機能: 金融前に独立人工監査と源を結合し、八部品を正式登録する。
    引数: なし。
    返り値: None。登録完了するまで実測を始めない。
    """
    meta = read(HERE / '入力目録.json')
    binding = read(HERE / '人工監査の結合.json')
    assert binding['passed'] is True
    paths = [HERE / p for p in ('plan_v3.py', 'run_v3.py', 'engine_v3.py')]
    paths += [BASE / 'engine119.py']
    paths += [BASE / 'v2' / p for p in ('run_v2.py', 'engine_v2.py', 'catalog_v2.py')]
    paths += [BASE / 'catalog119.py']
    sources = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    assert all(sources[path] == sha for path, sha in binding['economic_sources'].items())
    manifest = dict(path=(HERE / '入力目録.json').relative_to(ROOT).as_posix(), sha256=digest(HERE / '入力目録.json'))
    save(HERE / '固定計画.json', dict(sources=sources, input_manifest=manifest, artificial_binding=binding))
    proposal = dict(id=TRIAL, name='小試行と当初円リスクを増やさない順行追加', purpose='条件比較',
        question='入口変更では両商品に安定が残らない時、順行した波だけへ量を移すことで損失と収益の関係を改善できるか',
        change='既知六入口を固定し、少量20%固定/全量固定/20→40→70→100%順行追加を比較。追加後も当初円損失予算を拡大しない。',
        repeat_reason='思想自体は00097/98で既検証で、予算維持だけでは反復負けを解消しなかった。今回は旧支持源・8/16枚・倍増・余裕閾値から、異なる6入口・10/20上限・原建値0.5/1/1.5R・累計20/40/70/100%・1R後全費用後建値保護・次原rowへ変更し、31/32から全40へ拡張。旧保存済み結果と同仕様ではない。新発明や独立未知成功とは呼ばない。',
        compares_to=['119_全玉清算教師と異なる戦略から場内安定黒字を探す', '119b_共同進行の失速復帰と事前価格保護の原因対照', '研究_wave_v101', '研究_wave_v102'],
        evidence=[dict(path='アルゴリズム調査/共通/知見台帳/売買の工夫.md'),
                  dict(path='work/stability119_20261017/diagnosis/選択単体と三枠は何で負けたか.md'),
                  dict(path='work/stability119_20261017/v2/root_owned/全条件の事後比較と損失親.json'),
                  dict(path='アルゴリズム調査/00097_初回小枚数と利益で支える増玉の安定性/README.md'),
                  dict(path='アルゴリズム調査/00098_増玉の停止余裕と線保全の再検証/README.md')],
        spec=dict(
            entry=dict(規則='保存済COMMON/OPEN/CENTER/FAILのL20とv2 A/DのL20、計6。成績で各場の入口を切替えず、全6に同じ張り方を比較。',
                       初回='判断より厳密に後の原row正常BBOで成行。60価格秒以内・新規締切前。反対entryだけで過去注文を遡及取消しない。'),
            management=dict(追加='原実建値から反対気配が0.5/1/1.5固定R順行した時、到達済み最大段階40/70/100%まで不足数を1発注。各段階1回、60秒失効しても同段階再予約なし。',
                            競合='追加予約の後、悪い次気配でも追加を約定してからstop再判定、さらに後rowで全返済。発注後の都合よい取消なし。',
                            評価='全残玉の実反対気配評価と予定一括返済料を含む清算資産。取引しなかった場を黒字にしない。'),
            exit=dict(基本='初回当時の幅Rを固定。各初回枚数×R×倍率＋往復料を親損失予算とする。各追加後WAC/実entryfee/予定全数量closefeeから同予算以内のhardstopへ有利側だけ更新。',
                      利益保護='初回実建値から1R順行後は、全玉費用後建値と追跡最高値から0.5R又は1R戻りをstopへ反映し、緩めない。',
                      撤回='各保存入口の明示反証又は場末は次row全返済。保有時間固定無し。Day15:00/Night05:20新規/追加終了、20分後返済。',
                      場予算='全3配分に同じ円リスクを置く。最初有効R×上限20%のscout数量2/4×倍率を円尺度とし清算資産−2倍で当場終了、利益上限無し。全量固定は通常1Rstopより先に当場budgetが働き得る。価格飛び超過やEOF未返済はそのまま残す。'),
            allocation=dict(上限='TOPmini10/NKmicro20。少量20%は2/4枚、全量は10/20枚、追加は累計2→4→7→10/4→8→14→20。対照は6×3×2=36。',
                            順位='v2と同じ共通無次元事後順位、両net/median/上位3黒字除外net正・未返済0を資格とし少ない側黒字数、少ない側median/平均絶対net、悪い側最悪赤字/平均黒字、最後ID。全40既知で未知成功と呼ばない。'),
            costs=dict(注文料='TOPmini片道41.8/NKmicro11円、初回・各追加・全数量一括返済の各注文で円未満切捨て。両建てや利益部分だけの会計なし。',
                       気配差='全新規追加はask買/bid売、全返済は反対気配。予定stop価格で約定したと仮定しない。'),
            execution=dict(順序='既engine119.market_eventsの原row順。同row気配→足公開、同時計の後row可、判断rowfill不可。追加とcloseの同rowも不可。',
                           限界='ラージBBOによる小型契約代理。真受信順・壁時計・実mini/micro板・待ち順位未証明。指値保護は使わず新規条件差を混ぜない。',
                           証跡='全注文ログ、親WAC/全fee/net、初回予算/固定幅/最大数量、公開資産/保有方向、最大下落。初回20%の単なる縮小と追加効果を区別。'),
            data=dict(input_manifests=[manifest], sessions=meta['sessions'],
                      入力='第一試行の既所有prepared80と第二試行の保存政策80。原市場追加読0、各160保存入力を目的別一読。',
                      分割='旧40期間区分は参考のみ。全て既知の開発資料。'),
            implementation=sources))
    save(HERE / '試行計画.json', proposal)
    manager = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    for command, name in [('check', '正式照合'), ('register', '正式登録')]:
        process = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(manager), command, '--proposal', str(HERE / '試行計画.json')],
                                 cwd=ROOT, capture_output=True, encoding='utf-8')
        save(HERE / (name + 'の全出力.json'), dict(終了コード=process.returncode, stdout=process.stdout, stderr=process.stderr))
        assert process.returncode == 0
        if command == 'check':
            assert json.loads(process.stdout)['proposal_complete'] is True
        print(name + '完了', flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'freeze': freeze}[sys.argv[1]]()
