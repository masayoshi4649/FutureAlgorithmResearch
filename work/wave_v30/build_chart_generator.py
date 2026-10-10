"""既存の暗色５分足表示器を、第6反復の全84条件・三方向表示へ派生する。"""

from pathlib import Path

HERE = Path(__file__).resolve().parent


def replace_one(text: str, old: str, new: str) -> str:
    """機能: 一意な置換元だけを変更し、予期しない既存変更を拒否する。

    引数: text/old/new (str)。返り値: 置換後本文 (str)。
    """
    assert text.count(old) == 1, old
    return text.replace(old, new)


def main() -> None:
    """機能: 第5反復の表示実装を読取り、第6反復内に別ファイルを作る。

    引数: なし。返り値: なし (None)。過去の表示器・結果は変更しない。
    """
    text = (HERE.parent / 'wave_v29/chart_report.py').read_text(encoding='utf-8')
    text = text.replace('第五反復の固定候補', '第六反復の全84条件')
    text = text.replace('import protection_runner as runner', 'import context_split_runner as runner')
    text = text.replace('00024_部分利確と最高利益の保護', '00025_相手不一致と保有撤回の分離')
    begin = text.index("    decision = runner.read(HERE / '研究候補の固定.json')")
    end = text.index('    specifications = ', begin)
    text = text[:begin] + "    picked = [s['id'] + '__' + m['id'] for s in fixed['signals'] for m in fixed['managers']]\n    assert len(picked) == 84\n    accepted = False\n" + text[end:]
    text = replace_one(text, "contexts_used[identifier] = management['context_source'] == 'main'", "contexts_used[identifier] = management['context_source']")
    text = replace_one(text, "        contexts = np.load(HERE / 'contexts' / f'{signal_id}.npz')", "        contexts = np.load(HERE / 'contexts' / f'{signal_id}.npz')\n        own_contexts = np.load(HERE / 'contexts_own' / f'{signal_id}.npz')")
    text = replace_one(text, "            state, context = directions[f'{session}|{symbol}'], contexts[f'{session}|{symbol}']", "            state, main, own = directions[f'{session}|{symbol}'], contexts[f'{session}|{symbol}'], own_contexts[f'{session}|{symbol}']\n            context = {'entry': None, 'main': main, 'own': own}[management['context_source']]")
    text = replace_one(text, "context=context if management['context_source'] == 'main' else None", "context=context")
    text = replace_one(text, "(context[1:] != context[:-1])", "(main[1:] != main[:-1]) | (own[1:] != own[:-1])")
    text = replace_one(text, 'int(state[i]), int(context[i])', 'int(state[i]), int(main[i]), int(own[i])')
    text = text.replace('bottom = h - 82', 'bottom = h - 98')
    text = replace_one(text, "{'-1':'#8964ab','0':'#172637','1':'#427bbe'}]", "{'-1':'#8964ab','0':'#172637','1':'#427bbe'},{'-1':'#be774c','0':'#172637','1':'#53a9ad'}]")
    text = replace_one(text, 'row<2', 'row<3')
    text = replace_one(text, "row===0?'入口':'中期方向'", "['入口','両市場C','自己S'][row]")
    text = replace_one(text, "data.contexts_used[method.value] ? ' 中期方向を保有撤回にも使用します。' : ' この手法では中期方向の帯は参考表示で、退出の判定には使いません。'", "({'entry':' 退出は価格注文のみ。C/S帯は参考表示。','main':' 保有撤回には両市場Cを使用。','own':' 保有撤回には自己Sを使用。'}[data.contexts_used[method.value]])")
    begin = text.index("    note = ")
    end = text.index("    html = ", begin)
    text = text[:begin] + "    note = '成績順で絞らず、全84条件を表示しています。採用・推奨を意味しません。入口は共通でも、早期返済で次のエントリーは変わります。'\n" + text[end:]
    text = text.replace('部分利確と最高利益の保護：', '相手不一致と保有撤回：').replace('部分利確と利益保護.html', '相手不一致と保有撤回.html')
    text = text.replace('下の帯は、上段が入口条件、下段が中期方向。緑・青は買い向き、赤・紫は売り向き、暗色は中立です。', '下の三帯は、入口・両市場C・自己S。緑・青・水色は買い向き、赤・紫・茶色は売り向き、暗色は中立です。')
    text = text.replace('二入力', '入口と二つの保有方向').replace('中期方向を別の帯', '二つの中期方向を別の帯')
    (HERE / 'chart_report.py').write_text(text, encoding='utf-8')
    qa = (HERE.parent / 'wave_v29/html_visual_check.py').read_text(encoding='utf-8').replace('00024_部分利確と最高利益の保護', '00025_相手不一致と保有撤回の分離')
    (HERE / 'html_visual_check.py').write_text(qa, encoding='utf-8')


if __name__ == '__main__':
    main()
