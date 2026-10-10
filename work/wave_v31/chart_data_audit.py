"""出力HTMLの全910図が固定台帳と同じか、表示データを独立に確認する。"""

from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import chart_report as chart


class Parser(HTMLParser):
    """機能: HTMLのリンク・ID・埋込データを取り出す小さな検査器。"""

    def __init__(self) -> None:
        """機能: 抽出先を初期化する。

        引数: なし。返り値: なし (None)。
        """
        super().__init__()
        self.identifiers, self.links, self.chunks, self.in_data = set(), [], [], False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """機能: 一意ID・リンクとデータscriptの開始を記録する。

        引数: tag (str)、attrs (list[tuple])。返り値: なし (None)。
        """
        props = dict(attrs)
        if props.get('id'):
            assert props['id'] not in self.identifiers
            self.identifiers.add(props['id'])
        if tag == 'a' and props.get('href'):
            self.links.append(props['href'])
        if tag == 'script':
            assert not props.get('src'), '外部スクリプト参照'
            self.in_data = props.get('id') == 'chart-data'

    def handle_endtag(self, tag: str) -> None:
        """機能: 埋込データscriptの終端を記録する。

        引数: tag (str)。返り値: なし (None)。
        """
        if tag == 'script':
            self.in_data = False

    def handle_data(self, data: str) -> None:
        """機能: 表示用の埋込JSONだけを抽出する。

        引数: data (str)。返り値: なし (None)。
        """
        if self.in_data:
            self.chunks.append(data)


def main() -> None:
    """機能: 全表示台帳・三方向帯・件数・ファイルリンクを照合する。

    引数: なし。返り値: なし (None)。通信や注文再生はしない。
    """
    chart.episode.deny_network()
    source = chart.OUT / '５分足と売買.html'
    parser = Parser()
    parser.feed(source.read_text(encoding='utf-8'))
    payload = json.loads(''.join(parser.chunks))
    frozen = chart.runner.read(chart.HERE / 'chart_fixed.json')
    records = chart.runner.read(chart.HERE / 'episode_participation_details' / 'H019.json.gz')['図示用']
    assert set(payload['methods']) == set(frozen['手法']) and len(payload['methods']) == 35
    assert len(payload['candles']) == 26 and len(payload['sessions']) == 13
    assert len(payload['trades']) == len(payload['states']) == len(records) == 910
    trade_count = 0
    for record in records:
        key = '|'.join([record['method'], record['session'], record['symbol']])
        assert payload['states'][key] == record['状態']
        expected = []
        for row in record['全返済']:
            expected.append([datetime.fromisoformat(row['新規時刻']).timestamp(), datetime.fromisoformat(row['返済時刻']).timestamp(),
                             row['direction'], row['枚数'], row['新規価格'], row['返済価格'], row['損益円'],
                             chart.runner.engine.REASONS[row['返済理由番号']], '主玉' if row['役割番号'] == 0 else 'カバー'])
        assert payload['trades'][key] == expected
        trade_count += len(expected)
    for href in parser.links:
        reference = urlsplit(href)
        assert not reference.scheme and not reference.netloc
        target = source.parent / unquote(reference.path)
        assert target.is_file(), str(target)
        if reference.fragment:
            linked = Parser()
            linked.feed(target.read_text(encoding='utf-8'))
            assert unquote(reference.fragment) in linked.identifiers
    audit = {'全図示数': 910, '図示条件数': 35, '全返済数': trade_count, '全返済と三帯一致': True,
             'リンク数': len(parser.links), '全リンク有効': True, 'HTML_SHA256': chart.runner.digest(source),
             '固定SHA256': chart.runner.digest(chart.HERE / 'chart_fixed.json'), 'API取得数': 0}
    chart.runner.save(chart.HERE / 'chart_data_audit.json', audit)
    print('表示JSON全910図・全返済・三方向帯・リンク一致:', trade_count, '返済', flush=True)


if __name__ == '__main__':
    main()
