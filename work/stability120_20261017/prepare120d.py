"""中値で生じた合図を最終約定値基準と分ける対照源を新規準備する。"""

from pathlib import Path


def main() -> None:
    """
    機能: cの数量・出口・費用を保ち、待機極値と新規の基準だけを変える。
    引数: なし。
    返り値: None。実入力数値と金融結果を読まない。
    """
    base=Path(__file__).resolve().parent
    source=base/'recovery_c'
    target=base/'recovery_d'
    target.mkdir(exist_ok=False)
    text=(source/'engine120c.py').read_text(encoding='utf-8')
    text=text.replace('mid = (bid[i] + ask[i]) * .5', 'mid = (bid[i] + ask[i]) * .5\n        reference = last[i]')
    replacements=(
        ('anchor[:, :] = mid','anchor[:, :] = reference'),
        ('previous_mid = mid','previous_mid = reference'),
        ('anchor[s, j] = mid','anchor[s, j] = reference'),
        ('state[s, j], anchor[s, j] = 0, mid','state[s, j], anchor[s, j] = 0, reference'),
        ('state[other, k], anchor[other, k] = 0, mid','state[other, k], anchor[other, k] = 0, reference'),
        ('move = mid - previous_mid','move = reference - previous_mid'),
        ('min(anchor[s, j], mid) if side == 1 else max(anchor[s, j], mid)',
         'min(anchor[s, j], reference) if side == 1 else max(anchor[s, j], reference)'),
        ('crossed = mid >= line and move > 0. if side == 1 else mid <= line and move < 0.',
         'crossed = reference >= line and move > 0. if side == 1 else reference <= line and move < 0.'),
    )
    for before,after in replacements:
        assert before in text,before
        text=text.replace(before,after)
    (target/'engine120d.py').write_text(text,encoding='utf-8')
    text=(source/'run120c.py').read_text(encoding='utf-8')
    for before,after in (('catalog120c','catalog120d'),('engine120c','engine120d'),('runtime120c','runtime120d'),
        ('利益条件付き段階追加と全四十場.json','約定値基準の利益条件付き段階追加と全四十場.json')):
        text=text.replace(before,after)
    (target/'run120d.py').write_text(text,encoding='utf-8')
    text=(source/'runtime120c.py').read_text(encoding='utf-8').replace('engine120c','engine120d')
    (target/'runtime120d.py').write_text(text,encoding='utf-8')
    text=(source/'catalog120c.py').read_text(encoding='utf-8').replace('中値','最終約定値')
    assert "f'{tag}_S" in text
    text=text.replace("f'{tag}_S","f'{tag}_LAST_S")
    (target/'catalog120d.py').write_text(text,encoding='utf-8')
    (target/'入力目録.json').write_bytes((source/'入力目録.json').read_bytes())
    print('追尾新規の基準だけを最終約定値へ切り替えた別源を準備しました。金融0。')


if __name__=='__main__':
    main()
