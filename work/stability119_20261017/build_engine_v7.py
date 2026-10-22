"""既に閉鎖した二脚核心へ、相対継続の方向と二出口だけを加える。"""

import hashlib
import json
from pathlib import Path


def main() -> None:
    """
    機能: 数値差分を明示して新しい未固定sourceを作る。
    引数: なし。
    返り値: None。市場・金融・既存核心へは触れない。
    """
    base = Path(__file__).resolve().parent
    source = base / 'v5/engine_v5.py'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == 'b510af94ddc5cf1cc8f8800ca18b64f8d62bd0055a1a61a1a071b5d7ea9331cb'
    text = source.read_text(encoding='utf-8')
    changes = [
        ("'expected_center_gross',", "'cash_loss_budget',"),
        ("3: '組清算時価の円損失', 4: '未約定脚の六十価格秒期限', 5: '場末返済'}", "3: '組清算時価の円損失', 4: '未約定脚の六十価格秒期限', 5: '場末返済',\n           6: '入口残差から逆一標準偏差', 7: '順行残差ピークから一標準偏差後退'}"),
        ('nr, nt, nb, na, nl, tr, tt, tb, ta, tl, entry_end, force_time):', 'nr, nt, nb, na, nl, tr, tt, tb, ta, tl, entry_end, force_time, exit_mode):'),
        ('previous_time, peak, maxdd, mfe, mae = np.nan, 0., 0., 0., 0.', 'previous_time, peak, maxdd, mfe, mae = np.nan, 0., 0., 0., 0.\n    residual_peak = 0.'),
        ('entry_sign = -side', 'entry_sign = 1 if delta > 0. else -1'),
        ('candidate = -1 if current_delta > 0 else 1', 'candidate = 1 if current_delta > 0 else -1'),
        ('goal = abs(current_delta) * qn * 10. * last[0]', 'goal = (abs(current_delta) if exit_mode == 0 else 2. * sd) * qn * 10. * last[0]'),
        ('order_time, expected, cost, close_time, reason = now, goal, estimated, np.nan, 0', 'order_time, expected, cost, close_time, reason = now, (goal if exit_mode == 0 else goal / 2.), estimated, np.nan, 0'),
        ('arm_beta, arm_center, arm_sign = beta, center, -side', 'arm_beta, arm_center, arm_sign = beta, center, 1 if delta > 0. else -1\n                    residual_peak = 0.'),
        ("method, lookback = settings['method'], int(settings['lookback'])", "method, lookback = settings['method'], int(settings['lookback'])\n    exit_mode = int(settings['exit_mode'])\n    assert exit_mode in (0, 1)"),
        ("top_quotes['row'], top_quotes['time'], top_quotes['bid'], top_quotes['ask'], top_quotes['last'], entry_end, force_time)", "top_quotes['row'], top_quotes['time'], top_quotes['bid'], top_quotes['ask'], top_quotes['last'], entry_end, force_time, exit_mode)"),
    ]
    for before, after in changes:
        assert before in text, before
        text = text.replace(before, after)
    before = '''                if entry_sign * residual <= 0.:
                    why = 1
                elif entry_sign * residual >= abs(delta) + 2. * sigma:
                    why = 2
                elif parent_net <= -expected:
                    why = 3'''
    after = '''                if exit_mode == 0:
                    if entry_sign * residual <= 0.:
                        why = 1
                    elif entry_sign * residual >= abs(delta) + 2. * sigma:
                        why = 2
                else:
                    progress = side * (residual - delta)
                    residual_peak = max(residual_peak, progress)
                    if progress <= -sigma:
                        why = 6
                    elif residual_peak >= 2. * sigma and progress <= residual_peak - sigma:
                        why = 7
                if why == 0 and parent_net <= -expected:
                    why = 3'''
    assert before in text
    text = text.replace(before, after)
    text = text.replace("'quantity_top', 'hedge_error', 'cash_loss_budget',", "'quantity_top', 'hedge_error', 'qualification_move_gross',")
    text = text.replace('公表済みの局所相対価格モデルを固定し、二脚の個別約定と費用を運転する。',
                        '相対的な強さを追い、固定残差の順行と追尾を二脚の実約定へ結ぶ。')
    text = text.replace('四つの固定NT仮説のうち一つを、保存入力又は人工入力から完全に因果運転する。',
                        '四つの局所モデルと二出口の一つを、保存又は人工入力の価格時計模型で運転する。')
    text = text.replace('entry_end/force_time(float)は当場の既知締切。',
                        'entry_end/force_time(float)は既知締切、exit_mode(int)は0固定線又は1残差追尾。')
    text = text.replace('settings(dict)は仮説と当場締切。',
                        'settings(dict)は仮説・当場締切・exit_mode整数。')
    destination = base / 'v7/engine_v7.py'
    destination.parent.mkdir(exist_ok=True)
    assert not destination.exists()
    destination.write_text(text, encoding='utf-8')
    note = dict(source=source.relative_to(base).as_posix(),
                source_SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
                新方向='入口δ符号の強さ側を買い、弱い側を売る。残差の基準符号を売買sideから分離。',
                exit0='中心又は外2σ又は現金absδ*A。元MRと同じ参照面の対立方向。',
                exit1='コスト資格2σA>=3cost、現金σA、逆σ停止、順2σ後peakから1σ戻り追尾。',
                不変='モデル推定、数量探索、個別fill、60秒孤立期限、同clock共同snapshot、料金、場末、EOF未清算',
                金融=0)
    (destination.parent / 'v5からの核心差分方針.json').write_text(json.dumps(note, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('v7核心草稿を作成。市場0・金融0・登録0。')


if __name__ == '__main__':
    main()
