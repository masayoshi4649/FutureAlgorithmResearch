"""相対乖離の実復帰二確認と、二退出の既知差分を金融前に固定する。"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
TRIAL = '119i_相対乖離の実際の復帰確認と残差追尾の対照'


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
            (HERE / 'plan_v8.py', HERE / 'run_v8.py', HERE / 'engine_v8.py')}


def prepare() -> None:
    """
    機能: v5の小目録だけから既所有四十場八十入力の参照を固定する。
    引数: なし。
    返り値: None。実cache本文・原市場・金融・登録を実行しない。
    """
    import run_v8 as runner
    origin = BASE / 'v5/入力目録.json'
    payload = origin.read_bytes()
    old = json.loads(payload.decode('utf8'))
    inputs = [{k: v[k] for k in ('session', 'symbol', 'SHA256', 'bytes', 'owned_path')} for v in old['inputs']]
    assert len(old['sessions']) == len(set(old['sessions'])) == 40 and len(inputs) == 80
    assert {(v['session'], v['symbol']) for v in inputs} == {(s, k) for s in old['sessions'] for k in ('NK225', 'TOPIX')}
    for item in inputs:
        assert (ROOT / item['owned_path']).resolve().is_relative_to(BASE.resolve())
        assert len(item['SHA256']) == 64 and item['bytes'] > 0
    save(HERE / '入力目録.json', dict(sessions=old['sessions'], splits=old['splits'], inputs=inputs,
        specs=runner.make_specs(), inherited_manifest=dict(path=origin.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(payload).hexdigest()),
        order_leg_column='leg', leg_codes=dict(NK225=0, TOPIX=1),
        読取予定='既所有prepared80のbars/quotesだけ一読。元policy又は過去の損益では選別しない。',
        保存予定='八条件320組会計・40組cache・80脚cache・46列親と21列準備。未予約準備も保存する。',
        原市場追加読取=0, 保存cache本文読取=0, 新金融実行=0,
        留保='全40場は既知開発。v2の戻り確認及び過去NTと発想が重なる。新発明・独立八収益源・未知成功と呼ばない。'))
    print('v8小目録だけ準備完了。市場cache本文/正式金融/登録0。', flush=True)


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
        BASE / 'v5/plan_v5.py', BASE / 'v7/plan_v7.py', HERE / '相対復帰二確認と固定極値及び二脚の純人工.json',
        HERE / '復帰確認八仕様と準備記録及び組脚保存の接続人工.json', HERE / '人工監査の結合.json']
    evidence = [dict(path=p.relative_to(ROOT).as_posix(), sha256=digest(p)) for p in paths]
    save(HERE / '固定計画.json', dict(sources=sources, input_manifest=manifest, artificial_binding=binding))
    proposal = dict(id=TRIAL, name='相対乖離の実復帰二確認と極値撤回又は残差追尾', purpose='条件比較',
        question='二標準偏差の乖離そのものでは入らず、固定モデルの実際の中心向き復帰を二価格時計で確認すれば、場内の損失を減らせるか',
        change='ratio/OLS×30/60分×極値撤回/残差追尾の固定8条件。準備は分timer、復帰は共同normal価格clockで確認。',
        repeat_reason='00009/00011のNT相対回帰、v5の二脚執行、v2の実戻り確認と思想は重なる。v5の乖離即参加から、同じ過去モデルを準備時固定し、0.5σの復帰を別clock2回確認する入口へ変更。全史に未整理があり完全な重複なしとは主張しない。既知40場での開発である。',
        compares_to=['119e_両脚の費用と時間差を含む相対乖離の場内回帰',
            '119g_相対的な強さの継続と残差追尾の場内対照',
            '119b_共同進行の失速復帰と事前価格保護の原因対照'], evidence=evidence,
        spec=dict(
            entry=dict(モデル='ratio_mrは対数比β1、ols_mrは過去対数価格OLSでβ0.2〜5を要求。過去30/60の確定足が判断分timerまで公表済みの時だけ準備できる。',
                準備='中心から2σ以上の乖離を分timerで観測したらβ/center/σ/prepareδを固定し1波を消費。準備後は固定モデルの資格付き共同snapshot観測極値だけを追う。',
                確認='観測極値から中心へ0.5σ以上戻り、元と同符号で残差1σ以上、両quoteが5価格秒以内の共同normal clockを連続2回。閾値割れ・極値更新・資格不明なら確認数0。同clock中間値は不使用。',
                予約='別clock2回確認の後だけ、当時Lastと固定βで整数qを選ぶ。中心までの予定粗益が往復明示料＋両spreadの3倍以上。乖離が先にcenterへ戻れば未予約準備を取消。'),
            management=dict(固定='β/center/σは準備時、極値stop・数量・cashloss予算・参照価格は実予約時に固定し、後の気配でqを選び直さない。',
                一波='準備でarmを消費し、予約失効又は決済後も同モデルcenter帰還を共同正常価格で確認するまで新規準備なし。未予約準備は締切で取消。',
                現金予算='正の(準備観測極値−予約残差の方向付き幅)×予約時NK元本＋予定両脚往復の明示手数料。spreadは予算へ加算しない。実料金の別徴収と二重課金しない。',
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
            data=dict(input_manifests=[manifest], sessions=meta['sessions'],
                入力='v5小目録に固定された既所有prepared80のbars/quotesだけ各一読。原市場/API追加0。',
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
