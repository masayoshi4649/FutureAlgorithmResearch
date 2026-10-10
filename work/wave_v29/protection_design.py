"""第五反復の残玉保護を、入口と数量を変更せず結果前に固定する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import itertools
import json
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent


def catalog() -> list[dict]:
    """機能: 利益割合保護・追跡短縮の50通りを列挙する。

    引数: なし。返り値: 具体的な固定管理条件 (list[dict])。
    設計に損益、現在データ、全期間の最良値は読み込まない。
    """
    locks = [('割合保護なし', 0., 1.)]
    locks += [(f'{activation:g}R後に最高利益{fraction:.0%}を保護', fraction, activation)
              for activation, fraction in itertools.product((1., 2., 3.), (.25, .5, .75))]
    trails = [('追跡短縮なし', 0., 1.)]
    trails += [(f'{activation:g}ATR後に{width:g}ATR追跡', activation, width)
               for activation, width in itertools.product((2., 3.), (1.5, .75))]
    result = []
    for lock, trail in itertools.product(locks, trails):
        lock_name, fraction, activation_r = lock
        trail_name, threshold, width = trail
        residual = 0
        residual_name = '元の組予算を維持'
        changes = {'quantity_fraction': .5, 'entry_mode': 1, 'entry_atr': .25,
                   'ttl_seconds': 300., 'stop_atr': 1., 'split_target': 2.,
                   'main_trail': 3., 'activation_atr': 1.5, 'timeout_min': 360.,
                   'cooldown_min': 5., 'residual_risk_cap': residual,
                   'lock_fraction': fraction, 'lock_activation_r': activation_r,
                   'tighten_atr': threshold, 'tight_width': width}
        result.append({'id': f'K{len(result):03d}', 'name': '／'.join((residual_name, lock_name, trail_name)),
                       'family': '／'.join((residual_name, '割合保護あり' if fraction else '割合保護なし',
                                           '追跡短縮あり' if threshold else '追跡短縮なし')),
                       'description': '入口・初回枚数・初期損切り・部分利確を固定し、残玉と最高利益の返上だけを変える。',
                       'context_source': 'entry', 'residual_rule': residual_name,
                       'lock_rule': lock_name, 'trail_rule': trail_name, 'changes': changes})
    assert len(result) == 50
    assert len({json.dumps(row['changes'], sort_keys=True) for row in result}) == 50
    assert result[0]['id'] == 'K000'
    return result


def freeze() -> dict:
    """機能: 新しい機構の成績計算前に、範囲と反証の意味を保存する。

    引数: なし。返り値: 固定記録 (dict)。再実行ではコードと仕様の一致を要求する。
    """
    payload = {
        '固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        '目的': '方向判定で早期撤回する代わりに、最高利益の返上を直接制限する効果を切り分ける。割合保護は部分利確の前にも動作する。',
        '対象': '既知13セッション、v27凍結済み96入口。96×50＝4,800設定。独立した4,800市場仮説ではない。',
        '主比較': '同じ入口・同じTOPIXミニ5枚/NKマイクロ10枚のK000。K000はD273と全台帳一致を必須とする。',
        '固定部分': '入口0.25ATR追跡、有効300秒。初期1ATR、2ATRで整数半分利確。1.5ATRから3ATR追跡。最長360分、返済後5分休止、場内全返済。',
        '残玉制限の事前反証': '当初検討した残玉初回1ATR幅の維持は、2ATR利確時点で既存3ATR追跡が既に保護する水準と同じか緩い。既存追跡との包含関係を合成で調べ、カタログの軸から除外した。',
        '残玉制限の診断': '診断実装では、部分返済後の床を当組実現利益−残数量×初回ATR×初期損切り幅へ上げる。追加・カバー・反転との併用は拒否。探索では常に無効で、新機構の改善として数えない。',
        '割合保護': '当組の実現＋含み利益の最高額が初回予定損失1/2/3Rへ達した後、その最高額の25/50/75%を床とする。段階は初回R基準、床は緩めない。',
        '追跡短縮': '順行2/3ATRへ達した後、3ATRの追跡を1.5/0.75ATRへ縮める。初回ATR固定で、将来のボラは使わない。',
        '反例': '保護が早すぎれば一時的な戻りで本流から降りる。再エントリーで負けが増える。部分利確がある玉だけを見ると全体悪化を隠す。',
        '評価': '全口座の利益・損失・収支、決済枚数、含み損込みDD、指定波、同一入口K000との差を全件保存。部分利確に到達した勝ち玉だけの分析は採否へ使わない。',
        '数量対照': '数量を縮めれば収支とDDは概ね共に減るため、数量縮小を新優位と扱わない。全探索の初回はTOPIX5/NK10で統一し、同リスク・同数量の基準と比較する。',
        '棄却基準': '候補の反証と改善閾値は別ファイルで結果前固定。結果後に閾値を緩めず、反証用近傍を新候補へ昇格させない。',
        '新機構の執行': '現行の次行以降執行と価格優先順を保持。部分利確を見て変更した逆指値は次行から有効。指定水準が設定時に通過済みなら次観測価格で返済する。',
        '限界': '損失幅や利益の床は発注基準であり、価格の飛び・呼値・次行執行による超過を保証しない。',
        '現在データ': 'API追加取得なし。v27の9/29ナイト21:00保存物も探索・再試験・順位付けに使わない。',
        '来歴': '前三・第四反復と一回照合の結果を知って設計した既知期間の再探索。未知性能や正式な有意性を証明したとは呼ばない。',
        'managers': catalog(), 'コードSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    destination = HERE / '管理設計の固定.json'
    if destination.exists():
        old = json.loads(destination.read_text(encoding='utf-8'))
        assert {k: v for k, v in old.items() if k != '固定日時'} == {k: v for k, v in payload.items() if k != '固定日時'}
        return old
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


if __name__ == '__main__':
    print('管理設計を結果前固定:', len(freeze()['managers']), '条件', flush=True)
