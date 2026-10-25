"""入口を固定し、相手市場の不一致と自市場の方向撤回を分離する。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'wave_v27'))
import hierarchy_signals


def signals() -> tuple[list[dict], dict[str, dict]]:
    """機能: 成績を参照せず、短期価格確認を使う12入口と自己contextを選ぶ。

    引数: なし。返り値: 元の入口仕様と自己仕様の対応 (tuple[list, dict])。
    """
    catalog = hierarchy_signals.catalog()
    selected = [s for s in catalog if s['params']['entry_kind'] == 'short_price'
                and s['params']['peer_confirm']
                and all(s['params'][k] == 1 for k in
                        ('clock_multiplier', 'peer_multiplier', 'confirmation_multiplier'))]
    selected.sort(key=lambda s: s['id'])
    assert [s['id'] for s in selected] == [f'H{i:03d}' for i in range(3, 92, 8)]
    own = {}
    for spec in selected:
        params = dict(spec['params'], peer_confirm=False)
        matches = [s for s in catalog if s['params'] == params]
        assert len(matches) == 1
        own[spec['id']] = deepcopy(matches[0])
        assert int(matches[0]['id'][1:]) == int(spec['id'][1:]) - 1
    return selected, own


def catalog() -> list[dict]:
    """機能: 固定価格管理D273に7通りの保有撤回規則を対応させる。

    引数: なし。返り値: 管理ID・説明・実設定 (list[dict])。
    """
    common = {'quantity_fraction': .5, 'entry_mode': 1, 'entry_atr': .25,
              'ttl_seconds': 300., 'stop_atr': 1., 'split_target': 2.,
              'main_trail': 3., 'activation_atr': 1.5, 'timeout_min': 360.,
              'cooldown_min': 5.}
    rows = [('B0・価格注文のみ', 'entry', 0, 0., '基準'),
            ('C反転・両市場が反対', 'main', 1, 0., '反転'),
            ('S反転・自市場が反対', 'own', 1, 0., '反転'),
            ('C中立・両確認の消失10分', 'main', 0, 10., '中立'),
            ('S中立・自己方向の消失10分', 'own', 0, 10., '中立'),
            ('C併用・両確認の反転又は消失', 'main', 1, 10., '併用'),
            ('S併用・自己方向の反転又は消失', 'own', 1, 10., '併用')]
    result = []
    for i, (name, source, signal_exit, neutral, family) in enumerate(rows):
        result.append({'id': f'L{i:03d}', 'name': name, 'family': family,
                       'description': '入口の相手確認は維持し、保有中の撤回だけを比較する。',
                       'context_source': source,
                       'changes': dict(common, signal_exit=signal_exit, neutral_min=neutral)})
    return result


def freeze() -> dict:
    """機能: 損益を読む前に診断範囲と棄却時の解釈を固定する。

    引数: なし。返り値: 固定記録 (dict)。再実行では日時以外の一致を要求する。
    """
    entry, own = signals()
    payload = {
        '日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        '目的': '相手だけの不一致で中立返済する悪影響と、自市場の反転を早く認める効果を分離する。',
        '件数': '12入口×7管理=84。EMA二種は近縁であり独立12仮説とは扱わない。',
        '入口': '全管理で同じv27保存配列。短期価格確認・相手60秒遅延・確定足公開遅延を変更しない。',
        '保有判断': 'Cは自己と相手が一致した方向。Sは同じ仕様の自己方向のみ。B0は保有方向撤回を使わない。',
        '固定管理': '初回TOPIXミニ5枚/NKマイクロ10枚、上限10/20枚。初期1ATR損切り、2ATRで整数半分利確、1.5ATR後3ATR追跡、最長360分、返済後5分休止。追加・両建て・ドテンなし。',
        '執行': '既存engine_contextを無改変で使用。判断は次原本行以降。費用0、指定価格約定。全玉場内返済。',
        '全件反証': '最低基準や利益順位で絞らず全84を一次反証、64seed×2乱数対照、指定8波へ送る。',
        '主比較': '12入口それぞれのS−C、S−B0、C−B0。反転・中立・併用を分ける。全12とEMAを統合した5思想で等重み比較。',
        '解釈': 'SがCより良くてもB0より悪いなら改善達成としない。B0と同じ台帳なら追加撤回を無効化しただけ。参加減は保有時間・枚数時間・利益で示す。',
        '帰属': '中立0が続く区間の原因交代を記録。返済行だけに全区間を帰属させない。最初の台帳分岐以降の組番号を無理に対応させない。',
        '研究候補': '旧H019D273と同入口B0の両方に対し、両銘柄収支75%以上かつ最大下落80%以下。従来最低基準・全反証・乱数・指定波も必須。結果後に基準を緩めない。',
        '止め方': '自己方向だけでも利点が残らなければ、今回の機構診断を終了。窓や停止条件を後付けしない。',
        '既知と未知': '既知13セッションの第6反復。未知性能の検証ではない。現在API追加取得もv27現在保存物の再生も禁止。',
        'signals': entry, 'own_signals': own, 'managers': catalog(),
        'コードSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        '設計案SHA256': hashlib.sha256((HERE.parent / 'wave_v29/相手不一致と保有撤回の設計案.md').read_bytes()).hexdigest(),
    }
    path = HERE / '管理設計の固定.json'
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        assert {k: v for k, v in old.items() if k != '日時'} == {k: v for k, v in payload.items() if k != '日時'}
        return old
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


if __name__ == '__main__':
    print('保有撤回の分離設計を固定:', len(freeze()['managers']), '管理', flush=True)
