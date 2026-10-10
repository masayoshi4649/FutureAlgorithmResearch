"""候補と取得実装を固定してから、一度だけ現在原本を取得し固定手法を確認する。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
SOURCE_NAMES = ('driver.py', 'fetch_once.go', 'parse_snapshot.py', 'medium_replay.py')


def digest(path: Path) -> str:
    """機能: ファイルを分割読込して SHA256 を作る。

    引数: path(Path) は固定対象ファイル。
    返り値: SHA256文字列(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            result.update(block)
    return result.hexdigest()


def save(path: Path, value: dict) -> None:
    """機能: 取得前の固定内容または失敗内容を日本語 JSON に保存する。

    引数: path(Path)、value(dict)。
    返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare() -> None:
    """機能: 既知契約の照合情報と取得バイナリを準備する。外部アクセスは行わない。

    引数: なし。
    返り値: なし(None)。Go の外部依存取得も無効化して標準ライブラリだけを使う。
    """
    if (HERE / '取得開始.json').exists():
        raise RuntimeError('既に一回取得を開始済みのため準備を変更できません')
    import parse_snapshot
    parse_snapshot.save_baseline()
    env = dict(os.environ, GOTOOLCHAIN='local', GOWORK='off', GOPROXY='off', GOSUMDB='off')
    executable = HERE / ('fetch_once.exe' if os.name == 'nt' else 'fetch_once')
    subprocess.run(['go', 'build', '-o', str(executable), str(HERE / 'fetch_once.go')], check=True, env=env)
    record = {'準備時刻': datetime.now(timezone.utc).isoformat(), 'ネットワーク取得回数': 0,
              '取得実装SHA256': {name: digest(HERE / name) for name in SOURCE_NAMES},
              '取得バイナリ': executable.name, '取得バイナリSHA256': digest(executable),
              '契約照合基準SHA256': digest(HERE / '契約照合基準.json'),
              '計画SHA256': digest(WORK / '現在セッション確認計画.json')}
    save(HERE / '取得実装固定.json', record)
    print('外部アクセスなしで取得実装を固定しました。候補固定と親GOを待ちます。')


def fetch_and_replay() -> None:
    """機能: 親GO後に固定情報を照合し、再試行なしの一回取得と中期の途中会計を実行する。

    引数: なし。
    返り値: なし(None)。取得失敗時は記録して中断し、条件を変えた再取得をしない。
    """
    frozen = json.loads((HERE / '取得実装固定.json').read_text(encoding='utf-8'))
    for name, expected in frozen['取得実装SHA256'].items():
        assert digest(HERE / name) == expected, f'取得実装変更: {name}'
    assert digest(HERE / '契約照合基準.json') == frozen['契約照合基準SHA256']
    assert digest(WORK / '現在セッション確認計画.json') == frozen['計画SHA256']
    binary = HERE / frozen['取得バイナリ']
    assert digest(binary) == frozen['取得バイナリSHA256']
    selection_path = HERE / '確認候補固定.json'
    selection = json.loads(selection_path.read_text(encoding='utf-8'))
    assert set(selection['selected']) == {'medium', 'grid'} and selection['frozen_at']
    assert digest(WORK / 'medium/売買結果.json') == selection['source_sha256']['medium']
    assert digest(WORK / 'grid/売買結果.json') == selection['source_sha256']['grid']
    if (HERE / '取得開始.json').exists():
        raise RuntimeError('一回取得は既に開始済みです。再取得しません。')
    save(HERE / '取得直前の照合.json', {'候補固定SHA256': digest(selection_path),
                                    '取得実装固定SHA256': digest(HERE / '取得実装固定.json'),
                                    '親GO後': True, '取得前の元結果SHA一致': True})
    try:
        subprocess.run([str(binary), '-authorized', '-directory', str(HERE)], check=True)
        assert digest(selection_path) == json.loads((HERE / '取得直前の照合.json').read_text(encoding='utf-8'))['候補固定SHA256']
        subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'parse_snapshot.py')], check=True)
        subprocess.run([sys.executable, '-X', 'utf8', str(HERE / 'medium_replay.py')], check=True)
    except Exception as error:
        save(HERE / '現在確認の停止記録.json', {'取得又は検証の失敗': str(error), '再取得しない': True,
                                          '保存検証の結果を変更しない': True})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true', help='ネットワークなしで準備する')
    parser.add_argument('--authorized-fetch', action='store_true', help='候補固定と親GO後の一回取得')
    args = parser.parse_args()
    if args.prepare == args.authorized_fetch:
        raise SystemExit('準備又は親GO後の取得のどちらか一つを指定してください')
    prepare() if args.prepare else fetch_and_replay()
