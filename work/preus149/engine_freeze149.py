"""研究149のGoコピーと元アプリの差分指紋を金融再生前に保存する。"""

from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def reference(path):
    """ファイルの内容をSHA256と位置へ結び付ける。

    引数: path(Path)は存在する資料。
    返り値: dictはpath、bytes、sha256。
    """
    raw = path.read_bytes()
    return dict(path=path.relative_to(ROOT).as_posix(), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def main():
    """実行系と人工検査・計画を同じ版へ固定する。

    引数: なし。
    返り値: None。金融再生・ネットワーク通信は行わない。
    """
    records = []
    files = [HERE / 'configs149.json', HERE / 'engine仕様149.md', Path(__file__)]
    files += sorted((HERE / 'engine_go').rglob('*.go'))
    files += [HERE / 'engine_go/go.mod', HERE / 'engine_go/go.sum', HERE / 'engine_go/NK225_D07.toml']
    for path in files:
        record = reference(path)
        if path.is_relative_to(HERE / 'engine_go/internal'):
            origin = ROOT / 'App/SessionTrader' / path.relative_to(HERE / 'engine_go')
            if origin.exists():
                record['original'] = reference(origin)
                record['unchanged_from_app'] = record['sha256'] == record['original']['sha256']
            else:
                record['research_only'] = True
        records.append(record)
    target = HERE / 'engine指紋149.json'
    with target.open('x', encoding='utf-8') as stream:
        json.dump(dict(files=records, financial_replays=0, real_orders=0,
                       artificial_tests_passed=16,
                       modifications='主担当と補完の解禁時計、静観幅、担当分離だけ。コピー元App変更なし。'),
                  stream, ensure_ascii=False, indent=2)
    print(target)


if __name__ == '__main__':
    main()
