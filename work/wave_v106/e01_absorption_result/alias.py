"""追加拒否ゼロの固定入口部品を、同一会計の再利用として記録する。金融再生はしない。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREP = ROOT / 'work/wave_v106/e01_absorption_gate'
SOURCE = ROOT / 'work/wave_v106/e01_known_veto/finance/結果.json'
PROOF = ROOT / 'work/wave_v106/price_review/absorption_全公開mask同値と保存66会計再利用の独立確認.json'
OLD_ID = 'E01_TRADE_W60_KNOWN_VETO_D0_P1L8'
NEW_ID = 'E01_TRADE_W60_KNOWN_VETO_ABSORB_D0_P1L8'
TRIALS = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json'


def read(path: Path) -> dict:
    """
    機能: UTF-8の保存小根拠を読む。
    引数: path（Path）読み込むJSON。
    返り値: dict。元JSONの内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path: Path) -> str:
    """
    機能: 保存ファイルのSHA256を求める。
    引数: path（Path）対象ファイル。
    返り値: str。ファイル全体の指紋。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    """
    機能: 未存在の小記録を日本語UTF-8で保存する。
    引数: path（Path）保存先、value（dict）有限のJSON値。
    返り値: None。既存結果を上書きしない。
    """
    assert not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                    encoding='utf-8', newline='\n')


def freeze() -> None:
    """
    機能: 既に測った固定部品の同値証明と同じ保存会計を、台帳用八部品へ結び付ける。
    引数: なし。前固定計画・準備小結・独立証明・保存完成会計だけを読む。
    返り値: None。根登録用の計画を保存し、新金融・大型入力を読まない。
    """
    old_plan = read(PREP / '八部品と非金融測定の計画.json')
    meta = read(PREP / '全33場の表示維持公開観測の準備.json')
    proof, before = read(PROOF), read(SOURCE)
    assert meta['全合格'] and proof['全合格'] and before['全合格']
    spec = old_plan['spec']
    spec['exit']['今回'] = '全追加mask及び理由が基準と同じ。独立同値確認のため保存済み66会計を再利用し、金融再生0。'
    spec['costs']['扱い'] = '新規・返済・UID・FIFO・注文別切捨ては基準と同じ。同じ保存済み料金を再利用。'
    manifests = [dict(path=ROOT.joinpath(m['path']).relative_to(ROOT).as_posix(), sha256=m['SHA256'])
                 for m in spec['data']['input_manifests']]
    paths = (PREP/'全33場の表示維持公開観測の準備.json', PROOF, SOURCE,
             PREP/'diagnosis/全299公開の表示維持観測と条件交差.json',
             ROOT/'work/wave_v106/price_review/absorption_全299小観測と全成分交差の独立検算.json')
    manifests.extend(dict(path=p.relative_to(ROOT).as_posix(), sha256=sha(p)) for p in paths)
    spec['data']['input_manifests'] = manifests
    spec['data']['今回の読込'] = '登録と同値記録は小JSONだけ。原板・NPZ・input33・ledger66・API追加読込0。'
    # ----------------------------------------
    # 元の測定前実装を保持し、同値記録用sourceだけ別領域で追加する。
    spec['implementation'][Path(__file__).relative_to(ROOT).as_posix()] = sha(Path(__file__))
    plan = dict(old_plan, purpose='新仮説', spec=spec,
                name='同価格逆板の表示維持反復入口の介入ゼロと保存結果再利用',
                repeat_reason='当初非金融測定の固定条件を変えず、追加拒否0と全mask同値が確認されたので金融を繰り返さず記録する。',
                記録の段階='非金融の測定前固定は元計画を保持。この八部品は測定後の同値会計再利用を登録するもので、事前金融登録ではない。',
                金融再生=0, 追加介入=0)
    write(HERE/'保存会計再利用の試行計画.json', plan)
    print('介入ゼロの保存結果再利用計画を固定。新金融0。')


def record() -> None:
    """
    機能: 根が照合登録した同値計画に、保存済み66場会計と明示した限界を結ぶ。
    引数: なし。根台帳と計画指紋を検査する。
    返り値: None。同値記録を保存して完了状態を更新し、旧台帳を履歴に保持する。
    """
    plan = read(HERE/'保存会計再利用の試行計画.json')
    previous = TRIALS.read_bytes()
    table = json.loads(previous.decode('utf-8-sig'))
    registered = [r for r in table['trials'] if r['id'] == plan['id']]
    assert len(registered) == 1 and registered[0]['spec'] == plan['spec']
    for item in plan['spec']['data']['input_manifests']:
        assert sha(ROOT/item['path']) == item['sha256']
    for path, expected in plan['spec']['implementation'].items():
        assert sha(ROOT/path) == expected
    source = read(SOURCE)
    old = source['results'][OLD_ID]
    assert source['全合格'] and len(old['rows']) == len(old['ledgers']) == 66
    result = dict(全合格=True, 基準ID=OLD_ID, 候補ID=NEW_ID,
        結果種別='保存結果再利用（介入0）', 新金融再生=0,
        説明='固定部品の追加拒否0。全mask同値の独立確認と不変執行・会計sourceに基づく。新しい収益性の証拠ではない。',
        rows=old['rows'], symbols=old['symbols'], 保存元ledger=old['ledgers'],
        inputs=plan['spec']['data']['input_manifests'], source_sha256=sha(Path(__file__)),
        元金融SHA256=sha(SOURCE), 同値証明SHA256=sha(PROOF))
    path = HERE/'介入ゼロの保存66会計再利用.json'
    write(path, result)
    row = registered[0]
    row['status'] = '保存結果再利用（介入0）'
    row['result'] = '固定表示維持部品は追加拒否0。保存KNOWN_VETO P1L8と同値。新金融・追加有効性確認は0。'
    row['completed_result'] = dict(path=path.relative_to(ROOT).as_posix(), label='介入ゼロの同値会計', sha256=sha(path))
    row['completion_limitations'] = '全33場のE01公開候補窓での追加介入0。市場全体に吸収現象がないという結論ではない。'
    row.setdefault('evidence', []).append(row['completed_result'])
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    history = TRIALS.parent/'history'/('trials_'+hashlib.sha256(previous).hexdigest()+'.json')
    if not history.exists():
        history.write_bytes(previous)
    temporary = TRIALS.with_name('trials_absorption_alias.tmp')
    temporary.write_text(json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    temporary.replace(TRIALS)
    write(HERE/'同値再利用の完了登録.json', dict(全合格=True, 登録ID=plan['id'],
        元台帳SHA256=hashlib.sha256(previous).hexdigest(), 更新台帳SHA256=sha(TRIALS), 新金融再生=0))
    print('保存66会計を介入0として登録。新金融0・大型読込0。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('freeze', 'record'))
    args = parser.parse_args()
    freeze() if args.action == 'freeze' else record()
