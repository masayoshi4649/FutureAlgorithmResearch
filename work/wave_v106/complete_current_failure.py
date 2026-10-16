"""現在場の取得成功と入力不適合を、金融未測定のまま共通試行履歴へ結ぶ。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data'


def main() -> None:
    """
    機能: 登録した固定三政策の試行を、現在損益未測定として終端記録する。
    引数: なし。完成金融として扱わず、取得・入力停止・診断・独立検査を結ぶ。
    返り値: None。旧台帳を指紋付きで保持し、同じ入力の無断再実行を防ぐ。
    """
    path = DATA / 'trials.json'
    previous = path.read_bytes()
    value = json.loads(previous)
    plan = json.loads((HERE / 'current_session/現在入力停止の試行計画.json').read_text(encoding='utf8'))
    matches = [r for r in value['trials'] if r['id'] == plan['id']]
    assert len(matches) == 1 and matches[0]['spec'] == plan['spec']
    row = matches[0]
    assert row['status'] == '未実行'
    assert not (HERE / 'current_session/finance/結果.json').exists()
    proof_path = HERE / 'price_review/current_取得完結と逆時計入力失敗の独立確認.json'
    proof = json.loads(proof_path.read_text(encoding='utf8'))
    assert proof['全合格']
    evidence = dict(path=proof_path.relative_to(ROOT).as_posix(),
                    label='現在一回取得の入力停止を独立確認・金融未測定',
                    sha256=hashlib.sha256(proof_path.read_bytes()).hexdigest())
    row['status'] = '未測定（入力不適合）'
    row['result'] = '両商品各一回の取得は成功。価格時計の日付逆行で固定入力準備が停止。現在金融0、条件変更0、実注文0。'
    row['completion_limitations'] = '未見1ナイトの金融確認は未成立。無取引・利益0・赤字・未知成功のいずれにも数えない。原順維持、価格時計補完と再取得は行わない。'
    row.setdefault('evidence', []).append(evidence)
    value['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    digest = hashlib.sha256(previous).hexdigest()
    backup = DATA / 'history' / ('trials_' + digest + '.json')
    backup.parent.mkdir(exist_ok=True)
    if not backup.exists():
        backup.write_bytes(previous)
    temporary = DATA / 'trials_current_failure.tmp'
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    temporary.replace(path)
    record = dict(全合格=True, 登録ID=plan['id'], 状態=row['status'],
                  旧台帳SHA256=digest, 更新台帳SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  新金融再生=0, 現在金融='未測定')
    (HERE / 'current_session/入力不適合の終端登録.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print('現在一回取得の入力不適合を登録。金融未測定、無取引勝ちへ補完0。')


if __name__ == '__main__':
    main()
