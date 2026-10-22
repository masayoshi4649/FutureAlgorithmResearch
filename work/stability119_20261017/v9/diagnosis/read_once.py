"""完成結果を指定指紋で一読保全し、所有コピーから原因診断を準備する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EXPECTED = '80bab7ec7f540e09bdfd31c9aa59318bcb448c24635086239dc98e4c3b47d814'
SOURCE = ROOT / 'work/stability119_20261017/v9/measurement/相対復帰の初期気配差込み予算と全四十場.json'


def main() -> None:
    """
    機能: 一読計画を先に固定し、指定完成結果を解析前に同bytes保全する。
    引数: なし。
    返り値: None。実結果一読以外の市場入力・台帳・金融計算へ接続しない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    plan = HERE / '初期気配差予算の即停止と改善悪化を読む計画.json'
    copy = HERE / '完成結果の同bytes保全.json'
    assert not plan.exists() and not copy.exists()
    data = {
        '全合格': True,
        'result': {'path': SOURCE.relative_to(ROOT).as_posix(), 'SHA256': EXPECTED},
        '結果原本読取予定': 1,
        'parse前同bytes保全': True,
        '比較元': 'v8/diagnosis の既所有コピーと診断集計。元v8結果の追加読取はしない。',
        '目的': '全八条件の即cash停止件数と群損益、旧条件差、同じ予約の共通親と再参加差を分離。改善と悪化を一例ずつ確認する。',
        '例の固定規則': 'OLS60X0改善とOLS30X0悪化から同一予約に対応する親のnet差最大を各一例。候補外の政策を選び直さない。',
        '必要quotes': '既v8診断の同bytes所有NPZのみ。今回原入力・原cache・新規金融は0。',
        '留保': '予算変更で退出と再参加が変わる。親番号単独で対応付けず予約時計・方向・固定モデル・準備時計・数量を照合する。即停止が減っても利益の成立とはしない。',
    }
    plan.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    raw = SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED
    copy.write_bytes(raw)
    value = json.loads(raw)
    assert value.get('全合格', True)
    metadata = {
        '全合格': True,
        '結果SHA256': EXPECTED,
        'bytes': len(raw),
        '原本読取': 1,
        '原市場読取': 0,
        '金融再生': 0,
        'keys': list(value),
        'columns': value.get('columns'),
        'episode_count': len(value.get('episodes', [])),
    }
    (HERE / '完成結果の一読保全記録.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8'
    )
    print(json.dumps({k: v for k, v in metadata.items() if k != 'columns'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
