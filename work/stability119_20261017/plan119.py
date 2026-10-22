"""数値目標を必須にせず、費用後のセッション安定性を優先する探索の事前固定。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00119_戦略の自動選択と場内黒字の再探索'
TRIAL = '119_全玉清算教師と異なる戦略から場内安定黒字を探す'
SOURCE_NAMES = ('plan119.py', 'input119.py', 'engine119.py', 'catalog119.py', 'run119.py', 'design/selector119.py')


def read(path: Path) -> dict:
    """
    機能: 計画と保存済みの小集計を読み込む。
    引数: path(Path) はUTF-8 JSONの位置。
    返り値: dict。市場取得や再生を伴わない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: ソースや保存証跡の同一性を検査する。
    引数: path(Path) はファイル位置。
    返り値: str。SHA256の16進表現。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    """
    機能: 所有する新規JSONを保存し、旧結果の上書きを防ぐ。
    引数: path(Path)、value(dict) は有限値だけのJSONデータ。
    返り値: None。市場フォルダへは書き込まない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def sources() -> dict:
    """
    機能: 本番六源と再利用する既存入力源を結び付ける。
    引数: なし。
    返り値: dict[str,str]。ルート相対pathとSHA256。
    """
    paths = [HERE / name for name in SOURCE_NAMES] + [ROOT / 'work/topix10pt_20261016/input.py']
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}


def prepare() -> None:
    """
    機能: ファイル名・statだけで40場と80入力を固定する。
    引数: なし。00118の旧入力目録を再利用する。
    返り値: None。原NPZ・JSONL・ローソク足本文を読まない。
    """
    old = read(ROOT / 'work/topix10pt_20261016/入力目録と時系列分割.json')
    names = {s: sorted(p.stem for p in (ROOT / 'candle_1min' / s).glob('*.csv')) for s in ('TOPIX', 'NK225')}
    assert names['TOPIX'] == names['NK225'] and len(names['TOPIX']) == 40
    sessions = names['TOPIX']
    assert sessions[:37] == old['sessions']
    assert sessions[37:] == ['2026-10-15_Night', '2026-10-16_Day', '2026-10-16_Night']
    inputs = list(old['inputs'])
    for scene in sessions[37:]:
        day = datetime.fromisoformat(scene.split('_')[0]).replace(tzinfo=timezone(timedelta(hours=9)))
        start = day + (timedelta(hours=8, minutes=45) if scene.endswith('_Day') else timedelta(hours=17))
        end = day + (timedelta(hours=15, minutes=40) if scene.endswith('_Day') else timedelta(days=1, hours=5, minutes=55))
        for symbol in ('TOPIX', 'NK225'):
            p = ROOT / 'book' / symbol / (scene + '.jsonl')
            st = p.stat()
            inputs.append(dict(session=scene, symbol=symbol, path=p.relative_to(ROOT).as_posix(),
                               bytes=st.st_size, mtime_ns=st.st_mtime_ns, bounds=[start.timestamp(), end.timestamp()], kind='jsonl'))
    for item in inputs:
        st = (ROOT / item['path']).stat()
        assert st.st_size == item['bytes'] and st.st_mtime_ns == item['mtime_ns'], item['path']
    write(HERE / '入力と時系列分割.json', dict(sessions=sessions, inputs=inputs,
        splits={'設計参照21': sessions[:21], '選択6': sessions[21:27], '既知確認10': sessions[27:37],
                '追加確認3': sessions[37:], '確認13': sessions[27:], '全40': sessions},
        原入力本文読取=0, API=0, 注意='既知37は過去研究あり。追加3も全履歴での完全未見を保証せず、本研究の選択から分離。'))
    print('40場80入力のファイル名・statと時系列分割を固定しました。', flush=True)


def freeze() -> None:
    """
    機能: 完成ソースと人工検査を固定し、八部品の正式計画を生成する。
    引数: なし。実測前にのみ実行する。
    返り値: None。市場データを読み始めない。
    """
    inventory = read(HERE / '入力と時系列分割.json')
    source = sources()
    write(HERE / '正式固定.json', dict(source_SHA256=source, 原入力=0, 金融=0))
    proposal = dict(id=TRIAL, name='戦略の自動選択と場内黒字の再探索', purpose='条件比較',
        question='手法と利益額の固定条件を外し、異なる戦略と全玉清算教師の選択で、費用後の黒字頻度と損失規模を両立できるか',
        change='過去の完了取引教師を未決済を含む清算資産教師へ変更。6思想×3尺度と現実的次BBO、静的三枠分散・選択6場固定を比較。',
        repeat_reason='既存保存結果は今回の未決済清算教師、三尺度の組合せ、追加3場、選択と実数量三枠の再実行を含まない。',
        compares_to=['118_TOPIX十ポイントの予兆を多尺度と異情報で探索'],
        evidence=[dict(path='アルゴリズム調査/共通/知見台帳/' + p) for p in ('入口.md', '継続.md', '出口.md', '売買の工夫.md')],
        spec=dict(
            entry=dict(規則='catalog119.pyの18規則。共同追従/開始帯離脱/加重戻り/失敗離脱/相手遅行/直前観測終値乖離。L10/20/40。',
                注文='成行又は公開anchorから0.2幅有利な指値。買は下/売は上に実商品刻みTOPmini0.25/NKmicro5へ丸める。新規60秒/指値180秒で失効。'),
            management=dict(教師='成行・予算停止なしの18×3出口=54。返済費用込み含み評価を毎公開足で記録。',
                選択='H20/60/120の資産差−0.5最大下落。往復料2倍超。単一又は異family上位2一致。新規2連続、反対退出3連続。',
                無取引='黒字に数えない。未返済も合格扱いしない。'),
            exit=dict(方式=['0.8幅利確/1.2幅損切り', '1幅順行から1幅追尾/1幅損切り', '1幅半減・1.5幅から1.25幅追尾/1幅損切り'],
                反証退出='各familyの仮説が崩れた時。中立消失だけでは返済しない。',
                場末='Day15:20/Night翌05:40で返済判断し次正常BBO。新規は20分前停止。EOF残玉は評価だけで実清算にしない。',
                予算='無し/当該政策最初の既知幅×全数量倍率をR円とし−3R又は＋1.5Rで当場終了、超過約定を許す。'),
            allocation=dict(単体='TOPIXmini10/NK225micro20。同一商品内比較。資金利回りではない。',
                固定三枠='選択6場で正収支かつ活動3場以上・親5件以上の上位異family最大3。実枚数TOP4/3/3、NK8/6/6で再実行。',
                選択順位='黒字場率、下位25%収支、収支中央値、最悪赤字の黒字平均比、合計収支の順。後13場を選択へ戻さない。'),
            costs=dict(片道='TOPIXmini41.8円/NK225micro11円、各発注枚数合計を円未満切捨て。新規返済双方。',
                気配差='別途bid/askで負担。実小型板・待ち順位は未観測。'),
            execution=dict(模型='採用Last時計正常かつ正常ラージBBOの原row。判断rowより厳密に後の正常BBO。成行買ask/売bid、指値は反対気配到達。',
                時刻='原順と価格時計を使用。真受信時計・二市場共通受信順の証明なし。相手は60秒以上遅らせ、公開時計も未来拒否。',
                明細='新規から全返済の親netでP/L。部分利確だけを勝ちにしない。全残玉を含む清算資産も別記。'),
            data=dict(input_manifests=[dict(path='work/stability119_20261017/入力と時系列分割.json', sha256=digest(HERE / '入力と時系列分割.json'))],
                sessions=inventory['sessions'], 入力80=inventory['inputs'], 分割=inventory['splits'], API=0,
                再利用='旧NPZ66と新JSONL14を各一読。同じ市場cacheによる数量再実行を独立標本に数えない。'),
            implementation=source))
    write(HERE / '試行計画.json', proposal)
    manager = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    for command, name in [('check', '正式照合'), ('register', '正式登録')]:
        p = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(manager), command, '--proposal', str(HERE / '試行計画.json')],
                           cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        write(HERE / (name + 'の全出力.json'), dict(終了コード=p.returncode, stdout=p.stdout, stderr=p.stderr, 新金融=0))
        assert p.returncode == 0
        if command == 'check':
            assert json.loads(p.stdout)['proposal_complete'] is True
        print(name + '終了コード0', flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'freeze': freeze}[sys.argv[1]]()
