"""生成HTMLの埋込みデータを、保存した全売買・選択帯と照合する。"""

from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path

import numpy as np

import chart_report as chart


class Extractor(HTMLParser):
    """機能: HTMLから図示JSONとローカルリンクを抽出する。

    引数: HTML文字列はfeed(str)で指定。返り値: data/links属性 (str/list[str])。
    """

    def __init__(self) -> None:
        """機能: 収集先を初期化する。

        引数: なし。返り値: なし (None)。
        """
        super().__init__()
        self.active = False
        self.data = ''
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """機能: JSONブロック・要素ID・リンクを識別する。

        引数: tag (str)、attrs (list[tuple])。返り値: なし (None)。
        """
        values = dict(attrs)
        if values.get('id'):
            assert values['id'] not in self.ids
            self.ids.add(values['id'])
        if tag == 'script' and values.get('id') == 'chart-data':
            self.active = True
        if tag == 'a' and values.get('href'):
            self.links.append(values['href'])

    def handle_endtag(self, tag: str) -> None:
        """機能: JSON収集の終端を認識する。

        引数: tag (str)。返り値: なし (None)。
        """
        if tag == 'script':
            self.active = False

    def handle_data(self, value: str) -> None:
        """機能: JSONブロック内の文字を蓄積する。

        引数: value (str)。返り値: なし (None)。
        """
        if self.active:
            self.data += value


def main() -> None:
    """機能: 主6全156図の全返済と三帯がHTMLへ欠落なく移ったことを確認する。

    引数: なし。返り値: なし (None)。約定再生・通信・現在データ読取なし。
    """
    chart.episode.deny_network()
    path = chart.OUT / '５分足と売買.html'
    parser = Extractor()
    parser.feed(path.read_text(encoding='utf-8'))
    payload = json.loads(parser.data)
    frozen = chart.runner.read(chart.HERE / 'chart_fixed.json')
    assert sorted(payload['methods']) == frozen['手法']
    total_trades = total_open = count = 0
    for identifier in frozen['手法']:
        source = chart.runner.read(chart.HERE / 'selection_participation_details' / (identifier + '.json.gz'))
        for row in source['図示用']:
            key = identifier + '|' + row['session'] + '|' + row['symbol']
            saved = payload['trades'][key]
            assert len(saved) == len(row['全返済'])
            for actual, expected in zip(saved, row['全返済']):
                first, last = (datetime.fromisoformat(expected[name]).timestamp() for name in ('新規時刻', '返済時刻'))
                np.testing.assert_array_equal(actual[:7], [first, last, expected['direction'], expected['枚数'], expected['新規価格'], expected['返済価格'], expected['損益円']])
                assert actual[7] == chart.runner.engine_selector.REASONS[expected['返済理由番号']]
                names = {1: 'T', 2: 'R'}
                assert actual[8] == '所有' + names[expected['所有ID']] + '／入口' + names[expected['実入口源ID']]
                assert actual[9:] == [expected['新規行'], expected['返済行']]
            np.testing.assert_array_equal(payload['states'][key], row['状態'])
            orders = np.asarray(row['全約定']).reshape(-1, 8)
            assert {int(value) for value in orders[orders[:, 7] == 1, 0]} == {r[9] for r in saved}
            total_trades += len(saved)
            total_open += int(np.count_nonzero(orders[:, 7] == 1))
            count += 1
    assert count == len(payload['states']) == len(payload['trades']) == 156
    for href in parser.links:
        assert not href.startswith(('http:', 'https:')), href
        target = href.split('#', 1)[0]
        assert not target or (path.parent / target).exists(), href
    chart.runner.save(chart.HERE / 'chart_data_audit.json', {'全図示数': count, '全返済件数': total_trades, '全新規件数': total_open,
        '全返済一致': True, '全新規一致': True, '三帯一致': True, 'ローカルリンク全有効': True, 'API取得数': 0,
        '現在保存物使用': False, 'HTML_SHA256': chart.runner.digest(path), 'chart_fixed_SHA256': chart.runner.digest(chart.HERE / 'chart_fixed.json')})
    print('HTML全156図の全返済・全新規・三帯一致。リンク有効。')


if __name__ == '__main__':
    main()
