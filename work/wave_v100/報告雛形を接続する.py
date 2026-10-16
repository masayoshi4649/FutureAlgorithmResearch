"""価格上限の正式結果を後で表示するため、暗色報告と検査雛形だけを準備する。"""

from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v99'
TITLE = '追いかける価格を制限した手法と全セッション損益.html'
NAME = '00096_元候補からの入口価格上限と安定性'


def main() -> None:
    """
    機能: 旧報告の会計表示を保持して、100の固定条件と00096へ接続する。
    引数: なし。
    返り値: None。新会計又はHTMLを生成せず、過去の公開資料を上書きしない。
    """
    (HERE / 'report').mkdir(exist_ok=True)
    names = ('build.py', 'main.js', 'template.html', 'style.css', 'probe.js', 'verify.py',
             'publish.py', 'static_check.py', 'check_rule.js', '目視記録を保存する.py')
    for name in names:
        path = HERE / 'report' / name
        assert not path.exists(), name
        text = (OLD / 'report' / name).read_text(encoding='utf-8')
        text = text.replace('現在方向の価格源を替えた手法と全セッション損益.html', TITLE)
        text = text.replace('00095_現在方向の価格源を分ける待機検証', NAME)
        text = text.replace('現在方向の価格源を分ける待機検証', '元候補からの入口価格上限と安定性')
        text = text.replace('現在方向の価格源を替える待機手法', '追いかける入口価格を制限する手法')
        text = text.replace('00095', '00096').replace('wave_v99', 'wave_v100')
        text = text.replace('L1_C1_A7_X3', 'P1_L1_C1_A1_X1')
        if name == 'build.py':
            text = re.sub(r"\+ \['L0_C1_A7_X3'.*?'A0_X3'\]\)\)",
                          "+ ['P0_L1_C1_A1_X1', 'P05_L1_C1_A1_X1', 'P2_L1_C1_A1_X1', 'P1_L0_C1_A1_X1', 'A0_X1']))", text)
        elif name == 'publish.py':
            text = text.replace('旧89から94', '旧89から95').replace('旧89から94全成果不変', '旧89から95全成果不変')
            text = text.replace('assert max(numbers) == 94', 'assert max(numbers) == 95')
            text = text.replace('(89, 90, 91, 92, 93, 94)', '(89, 90, 91, 92, 93, 94, 95)')
            text = text.replace('00094', '00095')
            text = text.replace('2現在支持源×4時計政策×2待機入口×2出口', '4判断価格上限×2現在支持源×2待機入口×2出口')
            text = text.replace('2現在支持源・4時計政策・2待機入口・2出口', '4判断価格上限・2現在支持源・2待機入口・2出口')
        elif name == 'static_check.py':
            text = text.replace('assert max(numbers) == 94', 'assert max(numbers) == 95')
            text = text.replace('(89, 90, 91, 92, 93, 94)', '(89, 90, 91, 92, 93, 94, 95)')
            text = text.replace('旧89から94', '旧89から95')
            text = text.replace("assert 'C2はC1に加え' in template and '共通の位相時刻後の証拠とは意味が違う' in template", "assert '元候補から不利方向' in template and '実約定価格の保証ではない' in template")
        elif name == 'template.html':
            text = text.replace('時計政策を改修した手法と全セッション損益', '追いかける価格を制限した手法と全セッション損益')
            text = text.replace('時計政策・細かな条件と検証範囲', '入口価格の上限・細かな条件と検証範囲')
            text = text.replace('C3の再準備にも選んだ支持が作用する。', '時計は待機32条件で同じC1に固定する。')
            start = text.index('<p><b>時計政策：</b>')
            end = text.index('<p><b>共通の受付：</b>', start)
            text = text[:start] + '<p><b>価格上限：</b>元候補から不利方向の差 side×(判断quote−元候補quote) を上限なし、半W、1W、2Wで比較。数学的上限を不利な呼値へ広げない。旧最終条件が成立した行にだけ追加する。上限外では予約せず、同じ候補・方向・幅・期限を保持する。判断の上限は実約定価格の保証ではない。次の正常気配が上限を超えても旧通り約定し、超過を別記録する。</p>\n<p><b>時計：</b>C1は10秒超の価格時計差だけで待機を取消しない。正常な現在支持・両気配進行・旧取消は保持する。即時A0には新しい価格上限や支持確認を追加しない。</p>\n' + text[end:]
        elif name == 'main.js':
            text = text.replace(" const entrance=`", " const cap=config.entry_price_cap_multiple==null?'判断価格の制限なし。':`元候補から不利方向への差が${config.entry_price_cap_multiple}W以内なら発注判断。判断上限は実約定価格の保証ではない。上限外は同じ候補と期限で再確認。`;\n const entrance=`")
            text = text.replace('Wは保存始値0.1%で出口幅と独立。', 'Wは保存始値0.1%で出口幅と独立。${cap}')
        elif name == 'probe.js':
            text = text.replace("['全34で元の旧J8候補を固定','C0は10秒超','C1はその取消だけ','C2はC1に加え','C3再準備','TOPIX8枚・日経16枚','運用区切り60秒前','損失後の反対方向禁止は追加しない']", "['全34で元の旧J8候補を固定','元候補から不利方向','実約定価格の保証ではない','C1は10秒超','TOPIX8枚・日経16枚','運用区切り60秒前','損失後の反対方向禁止は追加しない']")
        elif name == 'check_rule.js':
            text = text.replace("['C0','C1','C2','C3'].some(policy=>counts[policy]!==8)", "counts.C1!==32||counts.C0!==0||counts.C2!==0||counts.C3!==0")
            marker = " if(/undefined|NaN/.test(html))"
            text = text.replace(marker, " if(config.entry_wait_kind){const expected=config.entry_price_cap_multiple==null?'判断価格の制限なし':`${config.entry_price_cap_multiple}W以内なら発注判断`;if(!html.includes(expected))throw Error('価格上限の説明');}\n"+marker)
        path.write_text(text, encoding='utf-8')
    (HERE / '公式仕様の時計項目と保存原本の区別.json').write_bytes(
        (OLD / '公式仕様の時計項目と保存原本の区別.json').read_bytes())
    print('00096の暗色報告雛形を準備しました。新HTML生成・公開はまだ行っていません。', flush=True)


if __name__ == '__main__':
    main()
