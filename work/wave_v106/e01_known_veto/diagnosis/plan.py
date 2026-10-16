"""小結果だけから P1L8 の変更場と必要資料を先に固定する。"""

import hashlib
import tools


def run() -> None:
    """
    機能: 全33場の五寄与又は会計が変わった場を、収支相殺も含めて選ぶ。
    引数: なし。保存された小結果と事前固定だけを読む。
    返り値: None。大型 cache と台帳を読む前に全対象を保存する。
    """
    result, result_sha = tools.read(tools.SOURCE / 'finance/結果.json')
    fixed, fixed_sha = tools.read(tools.SOURCE / '金融事前固定.json')
    assert result['全合格'] and result['sessions'] == fixed['sessions'] and len(result['sessions']) == 33
    cfg = next(c for c in result['configs'] if c['exit'] == 'P1L8'); cid = cfg['id']
    before = {(r['session'], r['symbol']): r for r in fixed['baseline'][cid]['rows']}
    after = {(r['session'], r['symbol']): r for r in result['results'][cid]['rows']}
    selected = []
    for delta in result['各場寄与'][cid]:
        key = delta['session'], delta['symbol']
        changed = any(abs(delta[k]) > 1e-6 for k in tools.FIVE) or before[key] != after[key]
        if changed:
            selected.append(dict(session=key[0], symbol=key[1], 寄与5={k: delta[k] for k in tools.FIVE},
                旧会計=before[key], 新会計=after[key], 純収支は同じ=abs(delta['収支変化']) < 1e-6))
    sessions = [s for s in result['sessions'] if any(x['session'] == s for x in selected)]
    newrefs = {v['session'] + '|' + v['symbol']: v for v in result['results'][cid]['ledgers']}
    plan = dict(目的='P1L8 の全変更場について公開時票・実 UID・場停止・後参加を説明する。'
        '収支が同じでも旧損失を別の損失へ置き換えた場を除外しない。',
        条件=cfg, 全場数=33, 選抜='五寄与のどれか又は小会計が変化。勝敗や日付を追加選別しない。',
        selected=selected, sessions=sessions, input_cache={s: fixed['input_cache'][s] for s in sessions},
        old_ledgers={x['session'] + '|' + x['symbol']: fixed['baseline'][cid]['ledgers'][x['session'] + '|' + x['symbol']] for x in selected},
        new_ledgers={x['session'] + '|' + x['symbol']: newrefs[x['session'] + '|' + x['symbol']] for x in selected},
        result_source=dict(path=(tools.SOURCE / 'finance/結果.json').relative_to(tools.ROOT).as_posix(), SHA256=result_sha),
        fixed_source=dict(path=(tools.SOURCE / '金融事前固定.json').relative_to(tools.ROOT).as_posix(), SHA256=fixed_sha),
        大型入力予定読取=len(sessions), 新旧台帳予定読取=2 * len(selected), 金融再生=0, 原板=0, 原NPZ=0, API=0,
        限界=['変更場の全数は保存五寄与及び小会計の変化を分母にする。未選抜場の全注文配列は再読しない。',
              '時刻は価格時計代理。真の受信時刻や発注通信遅延ではない。',
              '事後の値動きは原因診断だけに用い、新しい条件・金融を最適化しない。'])
    tools.write('P1L8変更場の読取前固定.json', plan)
    proof = dict(全合格=True, 条件=cid, symbols=result['results'][cid]['symbols'],
        全33の寄与5=result['diagnosis'][cid], 変更場数={s: sum(x['symbol'] == s for x in selected) for s in ('TOPIX', 'NK225')},
        純収支変更場数={s: sum(x['symbol'] == s and not x['純収支は同じ'] for x in selected) for s in ('TOPIX', 'NK225')},
        変更場=selected, source=plan['result_source'], 大型入力読取=0, 台帳読取=0, 金融再生=0, API=0)
    print(tools.write('P1L8の小結と全変更場.json', proof), flush=True)
    print('変更場 ' + str(proof['変更場数']) + ' 入力一読予定 ' + str(len(sessions)), flush=True)


if __name__ == '__main__': run()
