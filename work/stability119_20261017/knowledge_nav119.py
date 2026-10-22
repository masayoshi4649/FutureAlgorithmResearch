"""00119の分類別知見へ、既存Markdown冒頭から直接移動できるようにする。"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / 'アルゴリズム調査/共通/知見台帳'


def main() -> None:
    """
    機能: 追記済み法則への目次リンクだけを不足分追加する。
    引数: なし。
    返り値: None。本文・実測数値・元の出典を変更しない。
    """
    added = 0
    for name in ('入口', '継続', '出口', '売買の工夫'):
        path = COMMON / (name + '.md')
        text = path.read_text(encoding='utf-8')
        head, tail = text.split('<a id=', 1)
        rows = re.findall(r'<a id="(00119_[^"]+)"></a>\s*\n\s*## ([^\n]+)', text)
        links = []
        for anchor, title in rows:
            if '](' + '#' + anchor + ')' not in head:
                links.append(f'- [{title}](#{anchor})')
        if links:
            path.write_text(head.rstrip() + '\n' + '\n'.join(links) + '\n\n<a id=' + tail, encoding='utf-8')
            added += len(links)
    print(f'00119の法則への目次リンクを{added}件追加しました。')


if __name__ == '__main__':
    main()
