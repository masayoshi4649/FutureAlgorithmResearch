"""完成小資料から、今回の判断に必要な活動・方向票・途中逆行をまとめる。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path: Path) -> tuple[dict, str]:
    """
    機能: 完成済みJSONを指紋付きで読み、追加の金融再生を行わない。
    引数: path(Path) は正式会計又は16実親の診断射影。
    返り値: tuple[dict,str] は保存内容とSHA256。
    """
    saved = path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')), hashlib.sha256(saved).hexdigest()


def main() -> None:
    """
    機能: 昼夜の活動偏りと少数票・途中逆行を、分母と事後用途を明示して保存する。
    引数: なし。既知33場と指定16実親の小資料だけを読む。
    返り値: None。未見成功率や変更後の架空収支を計算しない。
    """
    result, result_sha = read(HERE/'engine/finance/結果.json')
    projection, projection_sha = read(HERE/'entry_diagnosis/実公開票と事後逆行の追加射影.json')
    assert result['全合格'] and projection['全合格']
    assert projection['保存結果SHA256'] == result_sha
    sessions = result['sessions']
    totals = {tag: sum(s.endswith('_'+tag) for s in sessions) for tag in ('Day', 'Night')}
    cases = {}
    for ident in ('E01_CROSS_B01', 'E01_CROSS_B03'):
        case = result['results'][ident]
        groups = {}
        for symbol in ('TOPIX', 'NK225'):
            groups[symbol] = {}
            for tag in ('Day', 'Night'):
                rows = [r for r in case['rows'] if r['symbol'] == symbol and r['session'].endswith('_'+tag)]
                assert len(rows) == totals[tag]
                groups[symbol][tag] = dict(全場=len(rows), 活動場=sum(r['親数'] > 0 for r in rows),
                    黒字場=sum(r['収支'] > 0 for r in rows), 赤字場=sum(r['収支'] < 0 for r in rows),
                    無取引場=sum(r['親数'] == 0 for r in rows), 収支=sum(r['収支'] for r in rows))
        cases[ident] = groups

    # ----------------------------------------
    # 少数票と事後最大逆行は、最終的に黒字だった親だけの限定診断。
    actual = [p for p in projection['parent_projections'] if p['case_id'] == 'E01_CROSS_B03']
    assert len(actual) == 15 and all(p['actual_net_yen'] > 0 for p in actual)
    sample = {}
    for symbol in ('TOPIX', 'NK225'):
        own = [p for p in actual if p['symbol'] == symbol]
        worst = max(own, key=lambda p: p['risk']['fee_liquidation_MAE_yen'])
        sample[symbol] = dict(実親数=len(own), 二票親数=sum(p['publication']['direction_votes'] == 2 for p in own),
            釣合い一の親数=sum(p['publication']['balance'] == 1 for p in own),
            最大事後清算逆行円=worst['risk']['fee_liquidation_MAE_yen'],
            その場=worst['session'], その公開時計=worst['publication']['価格代理時計JST'],
            その実返済net=worst['actual_net_yen'], 許容損失円=worst['risk']['hard_loss_yen'])
    data = dict(全合格=True, 正式結果SHA256=result_sha, 診断射影SHA256=projection_sha,
        昼夜場数=totals, 昼夜比較=cases, B03標本診断=sample,
        B03実親数=15, B03二票親数=sum(p['publication']['direction_votes'] == 2 for p in actual),
        B03ナイト親数=sum(p['session'].endswith('_Night') for p in actual),
        制限='同じ既知33場の事後集計。無取引は勝ちでない。清算逆行は事後診断で新しい出口の実現損失ではない。',
        金融再生=0, 大型入力=0, 実台帳=0, API=0)
    (HERE/'判断に必要な昼夜活動と少数票及び途中逆行.json').write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(全合格=True, 昼夜場数=totals, B03二票親数=data['B03二票親数'],
        B03ナイト親数=data['B03ナイト親数'], 金融再生=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
