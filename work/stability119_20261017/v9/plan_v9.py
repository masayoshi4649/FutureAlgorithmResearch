"""相対乖離の実復帰二確認と、二退出の既知差分を金融前に固定する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
TRIAL = '119j_相対復帰の初期気配差を含む清算予算の対照'


def digest(path: Path) -> str:
    """
    機能: 小資料又はsourceの指紋を求める。
    引数: path(Path)は対象。
    返り値: strはSHA256。実市場の本文は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 既所有入力の小目録と独立人工の結合証跡を読む。
    引数: path(Path)はUTF-8の小JSON。
    返り値: dictは内容。金融又は市場本文は使わない。
    """
    return json.loads(path.read_text(encoding='utf8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 計画を既存成果へ重ねず保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。日本語UTF-8の有限JSONを新規作成する。
    """
    assert not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')


def economic_sources() -> dict:
    """
    機能: 復帰二確認の核心・driver・計画を同じ版へ結合する。
    引数: なし。
    返り値: dict[str,str]は三sourceのrepo相対位置とSHA。
    """
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in
            (HERE / 'plan_v9.py', HERE / 'run_v9.py', HERE / 'engine_v9.py')}


def prepare() -> None:
    """
    機能: v8小目録だけから同じ四十場八十入力と旧会計SHAの参照を固定する。
    引数: なし。
    返り値: None。実cache本文・原市場・金融・登録を実行しない。
    """
    import run_v9 as runner
    origin = BASE / 'v8/入力目録.json'
    payload = origin.read_bytes()
    old = json.loads(payload.decode('utf8'))
    inputs = [{k: v[k] for k in ('session', 'symbol', 'SHA256', 'bytes', 'owned_path')} for v in old['inputs']]
    assert len(old['sessions']) == len(set(old['sessions'])) == 40 and len(inputs) == 80
    assert {(v['session'], v['symbol']) for v in inputs} == {(s, k) for s in old['sessions'] for k in ('NK225', 'TOPIX')}
    for item in inputs:
        assert (ROOT / item['owned_path']).resolve().is_relative_to(BASE.resolve())
        assert len(item['SHA256']) == 64 and item['bytes'] > 0
    save(HERE / '入力目録.json', dict(sessions=old['sessions'], splits=old['splits'], inputs=inputs,
        specs=runner.make_specs(), saved_baseline=runner.BASELINE, inherited_manifest=dict(path=origin.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(payload).hexdigest()),
        order_leg_column='leg', leg_codes=dict(NK225=0, TOPIX=1),
        読取予定='既所有prepared80のbars/quotesだけ一読。元policy又は過去の損益では選別しない。',
        保存予定='新8条件320組と準備系譜、40組/80脚cache。旧v8の320行は保存引用のみで再運転0。',
        原市場追加読取=0, 保存cache本文読取=0, 新金融実行=0,
        留保='全40場は既知開発。v2の戻り確認及び過去NTと発想が重なる。新発明・独立八収益源・未知成功と呼ばない。v8からの設計原因対照で、会計バグ修正ではない。'))
    print('v9小目録だけ準備完了。市場cache本文/正式金融/登録0。', flush=True)


def freeze() -> None:
    """
    機能: 根担当が独立人工を結合した後に八部品を固定し、正式照合と登録を行う。
    引数: なし。根担当による後段実行専用。
    返り値: None。金融運転は別の根担当実行とする。
    """
    meta = read(HERE / '入力目録.json')
    binding = read(HERE / '人工監査の結合.json')
    assert binding['passed'] is True
    sources = economic_sources()
    assert binding['economic_sources'] == sources
    manifest = dict(path=(HERE / '入力目録.json').relative_to(ROOT).as_posix(), sha256=digest(HERE / '入力目録.json'))
    paths = [ROOT / 'アルゴリズム調査/00009_銘柄別の損小利大と建玉管理/README.md',
        ROOT / 'アルゴリズム調査/00011_一週間データでの再検証/README.md', BASE / 'v2/plan_v2.py',
        BASE / 'v5/plan_v5.py', BASE / 'v7/plan_v7.py', BASE / 'v8/plan_v8.py', HERE / '初期気配差予算と固定極値及び二脚の純人工.json',
        HERE / '費用包含予算八仕様と準備記録及び組脚保存の接続人工.json', HERE / '人工監査の結合.json']
    evidence = [dict(path=p.relative_to(ROOT).as_posix(), sha256=digest(p)) for p in paths]
    save(HERE / '固定計画.json', dict(sources=sources, input_manifest=manifest, artificial_binding=binding))
    proposal = dict(id=TRIAL, name='相対復帰の初期気配差を含む現金予算の一因子対照', purpose='条件比較',
        question='極値の価格撤回線は不変のまま、清算資産の損失予算へ予約時の初期両spreadを加えれば、開始費用だけによる即停止を減らせるか',
        change='核心のbudget末尾roundtrip_feeをestimated(往復料＋両spread)へ一箇所変更。入口/二確認/極値撤回/追尾/約定/料金はv8と同じ8条件。ID末尾_CB。',
        repeat_reason='v8の初期清算時価がfee+spreadなのにcash予算が極値幅+feeだけだった設計の原因対照。会計バグとは呼ばない。同じ既知40場・8条件を新予算で実行し、旧v8結果320は固定SHA保存引用で金融再run0。既存NT/v2思想との重複と旧全史未整理は保持し、完全重複なし又は未知成功と主張しない。',
        compares_to=['119i_相対乖離の実際の復帰確認と残差追尾の対照'], evidence=evidence,
        spec=dict(
            entry=dict(モデル='ratio_mrは対数比β1、ols_mrは過去対数価格OLSでβ0.2〜5を要求。過去30/60の確定足が判断分timerまで公表済みの時だけ準備できる。',
                準備='中心から2σ以上の乖離を分timerで観測したらβ/center/σ/prepareδを固定し1波を消費。準備後は固定モデルの資格付き共同snapshot観測極値だけを追う。',
                確認='観測極値から中心へ0.5σ以上戻り、元と同符号で残差1σ以上、両quoteが5価格秒以内の共同normal clockを連続2回。閾値割れ・極値更新・資格不明なら確認数0。同clock中間値は不使用。',
                予約='別clock2回確認の後だけ、当時Lastと固定βで整数qを選ぶ。中心までの予定粗益が往復明示料＋両spreadの3倍以上。乖離が先にcenterへ戻れば未予約準備を取消。'),
            management=dict(固定='β/center/σは準備時、極値stop・数量・cashloss予算・参照価格は実予約時に固定し、後の気配でqを選び直さない。',
                一波='準備でarmを消費し、予約失効又は決済後も同モデルcenter帰還を共同正常価格で確認するまで新規準備なし。未予約準備は締切で取消。',
                現金予算='正の(準備観測極値−予約残差の方向付き幅)×予約時NK元本＋予約時estimated(両脚往復の明示料と両spread)。初期気配差を含めるが、極値の価格撤回線を広げない。予約後に予算を更新しない。実料金の別徴収と二重課金しない。',
                記録='prepare時刻/δ/β/center/σ/観測極値、二確認clock、reserveδ/予算/q/参照価格を保存。未reserve準備も21列記録に残す。事後relative/common分解は判断へ戻さない。'),
            exit=dict(共通='両法とも固定center復帰、予約時に固定した準備後極値への逆戻り、費用後全玉清算時価のcashloss予算、場末で返済予約。元v5と厳密同一出口ではない。',
                極値撤回型='exit_mode0は共通停止のみ。極値までの撤回幅を後から広げない。',
                残差追尾型='exit_mode1は共通停止に加え、固定予約残差から1σ改善後、その最大改善から0.5σ戻りで返済。center条件を優先。',
                締切='既所有セッション内でDay15:00/Night05:20新規終了、Day15:20/Night05:40返済。EOF未清算は時価と実現を分け成功へ数えない。'),
            allocation=dict(整数='当時価格でβ元本誤差5%以内の整数組を選ぶv5規則を維持。NKmicro上限20枚/TOPmini上限10枚。',
                口座='一場一つの二脚組口座。個々の脚の損益と単脚失効も隠さず、独立した両商品成功と呼ばない。8件は同家族の条件対照。'),
            costs=dict(明示料='NKmicro片道11円/TOPmini41.8円。各脚各注文の枚数合計を円未満切捨て。',
                評価='全open脚を返済側BBOと残返済料で評価。実支払料と予定清算料を区別する。入口資格の予定費用やcash予算を実費用へ加算しない。'),
            execution=dict(共同時計='同clockの全正常quote/既予約fillの後だけ組残差・MTM/DD/極値・復帰を判断。瞬間の片側更新を共同状態と呼ばない。',
                注文='実reserve後の各脚time>判断clockで独立に買ask/売bid約定。60価格秒の取消優先と孤立脚次quote返済、場末をv5から維持。',
                限界='価格clock模型。真受信順・壁時計の2確認又は60秒・実小型板の待ち順位/全量約定は未証明。観測極値は真の市場最大値でない。'),
            data=dict(input_manifests=[manifest], sessions=meta['sessions'], saved_baseline=meta['saved_baseline'],
                入力='v8小目録の同じ既所有prepared80のbars/quotesだけ各一読。原市場/API追加0。v8指定SHAの保存320行を正式時一読引用、旧金融0。',
                範囲='全40場既知の事後開発。旧確認13/追加3も未知成功としない。未取引・未予約準備は勝ちに数えない。'),
            implementation=sources))
    save(HERE / '試行計画.json', proposal)
    manager = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    for command, name in (('check', '正式照合'), ('register', '正式登録')):
        process = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(manager), command, '--proposal', str(HERE / '試行計画.json')],
            cwd=ROOT, capture_output=True, encoding='utf8')
        save(HERE / (name + 'の全出力.json'), dict(終了コード=process.returncode, stdout=process.stdout, stderr=process.stderr))
        assert process.returncode == 0, name
        parsed = json.loads(process.stdout)
        if command == 'check':
            assert parsed['proposal_complete'] is True
        else:
            assert parsed['id'] == TRIAL and parsed['spec'] == proposal['spec']
        print(name + '完了。金融は別途根担当だけで実行。', flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'freeze': freeze}[sys.argv[1]]()
