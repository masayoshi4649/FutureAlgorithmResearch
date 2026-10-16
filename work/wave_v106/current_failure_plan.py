"""現在ナイトの固定三政策が入力条件で停止した事実を、金融未測定として登録する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGET = HERE / 'current_session/現在入力停止の試行計画.json'


def evidence(path: Path) -> dict:
    """
    機能: 保存済み小証跡の位置と内容指紋を計画へ結び付ける。
    引数: path(Path)は取得・失敗・非金融診断のJSON。
    返り値: dictはルート相対位置とSHA256。原板や金融は再生しない。
    """
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def main() -> None:
    """
    機能: 取得前固定の三条件を保持して、入力不適合の終端だけを記録する。
    引数: なし。旧草案と今回一回取得の完了・停止・診断を利用する。
    返り値: None。売買仕様を変えず、金融未測定を無取引勝ちへ補完しない。
    """
    assert not TARGET.exists()
    draft = HERE / 'current_session/現在ナイト三政策の試行計画草案.json'
    value = json.loads(draft.read_text(encoding='utf8'))
    capture = HERE / 'current_capture/取得完了.json'
    failure = HERE / 'current_session/現ナイト入力準備False.json'
    diagnosis = HERE / 'current_capture/価格時計逆行による入力停止の非金融診断.json'
    assert json.loads(capture.read_text(encoding='utf8'))['全合格']
    assert not json.loads(failure.read_text(encoding='utf8'))['全合格']
    assert json.loads(diagnosis.read_text(encoding='utf8'))['新金融再生'] == 0
    value['状態'] = '一回取得は成功。価格時計逆行で固定consumerの入力検査停止。金融は未測定。'
    value['change'] += ' 取得条件と三政策は不変更。原行の価格時計逆行を補完せず入力不適合として記録。'
    value['repeat_reason'] += ' 金融再生に至らなかった試行を残し、無取引・利益0・赤字と誤認しないため。'
    value['spec']['data']['input_manifests'] += [evidence(p) for p in (capture, failure, diagnosis)]
    value['spec']['data']['actual_end'] = '入力停止。prepared及び金融結果は存在しない。E01も未見金融0。'
    value['spec']['data']['source_diagnosis'] = '診断目的で取得済み本文を各一読取。並べ替え・日付補完・再取得0。'
    value['evidence'] += [evidence(p) for p in (draft, capture, failure, diagnosis)]
    value['sacrifices'] += ['現在ナイトは固定入力契約に不適合。現在成績を算出できず、未知での有効性は未確認。']
    TARGET.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    print('取得前固定三条件の入力不適合を保存。金融0・条件変更0。')


if __name__ == '__main__':
    main()
