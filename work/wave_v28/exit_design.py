"""入口と保有撤回を分けた管理方法を、新しい損益の閲覧前に列挙する。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import itertools
import json
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent


def catalog() -> list[dict]:
    """機能: 損切り・新規追跡・部分利確・損失予算・主方向撤回の全288組を返す。

    引数: なし。返り値: 固定管理仕様 (list[dict])。損益や現在スナップショットを参照しない。
    """
    profiles = [
        ('全玉の長い追跡', 0., 3., 1.5),
        ('2ATRの部分利確と残玉追跡', 2., 3., 1.5),
        ('1.5ATRの部分利確と残玉追跡', 1.5, 2.5, 1.),
    ]
    guards = [('追加制限なし', 0, 0.), ('同方向2連敗と初回3R', 2, 3.),
              ('同方向3連敗と初回5R', 3, 5.), ('初回3Rだけ', 0, 3.)]
    contexts = [('価格注文だけで返済', 'entry', 0, 0.), ('中期方向の反転で返済', 'main', 1, 0.),
                ('中期方向の中立10分で返済', 'main', 0, 10.), ('中期反転又は中立10分で返済', 'main', 1, 10.)]
    rows = []
    for stop, entry, profile, guard, context in itertools.product((.75, 1., 1.5), (.25, .5), profiles, guards, contexts):
        profile_name, split, trail, activation = profile
        guard_name, losses, budget = guard
        context_name, source, signal_exit, neutral = context
        changes = {'quantity_fraction': .5, 'entry_mode': 1, 'entry_atr': entry, 'ttl_seconds': 300.,
                   'stop_atr': stop, 'split_target': split, 'main_trail': trail, 'activation_atr': activation,
                   'max_same_losses': losses, 'session_budget_r': budget, 'signal_exit': signal_exit,
                   'neutral_min': neutral, 'timeout_min': 360., 'cooldown_min': 5.}
        rows.append({'id': f'J{len(rows):03d}', 'name': f'{profile_name}／損切り{stop:g}ATR／新規追跡{entry:g}ATR／{guard_name}／{context_name}',
                     'family': profile_name + '／' + guard_name + '／' + context_name,
                     'description': '上限の半分で新規。全玉の損失を計上し、部分利確・主方向撤回・連敗と場全体の予算を組み合わせる。',
                     'context_source': source, 'profile': profile_name, 'guard': guard_name,
                     'context_rule': context_name, 'changes': changes})
    assert len(rows) == 288
    assert len({json.dumps([r['changes'], r['context_source']], sort_keys=True) for r in rows}) == 288
    return rows


def freeze() -> dict:
    """機能: 第四反復の仮説・操作範囲・禁止事項と管理条件を結果前に固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    record = {'固定日時': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
              '仮説': '短期の新規条件が消えただけでは主方向を撤回しない。一方、中期の反転や中立長期化では保有を撤回し、連敗/場の損失予算で往復損失を制限する。',
              '反例': '早い損失制限が後続の本流を逃す。中期方向の遅れが逆行玉を長く保持する。主方向中立化で追跡利幅を縮め過ぎる。利益玉だけの決済で敗戦を隠す。',
              '発見入力': 'v27と同じ保存済み13セッション26入力。v27の96入口方向と24固有中期許可方向。',
              '使用しないデータ': '21:00に一回取得した現在スナップショットは第四反復の探索・順位・再生に一切使わない。追加API取得もしない。',
              '解釈': '第三反復と現在照合の失敗を知った後の仮説修正。同じ既知13セッションへの再探索であり、未知性能の証拠とは呼ばない。',
              '規模': '96入口×288管理＝27,648条件。条件の数は独立した市場仮説の数ではない。',
              '新規': 'TOPIXミニ5枚/NKマイクロ10枚。追跡幅0.25又は0.5ATR、有効300秒。返済後5分待機。',
              '損切り': '新規準備時の因果ATR（最低2呼値）の0.75/1/1.5倍と初期枚数を掛けた組全体の損失予算。部分返済後も全玉合算。',
              '損失予算': '制限ありでは当該セッション初回準備時に定めた予定損失の3倍又は5倍。実現＋含みで監視。連敗解除は既存仕様の入口反対方向又は損切り値から1ATRの順行。',
              '二入力': '新規/未約定取消/連敗解除は入口state。保有中の方向撤回/中立10分は別context。中期許可方向は相手確認も含むv27 main_directions。',
              '不使用機能': '本288管理は増玉・両建て・反転新規を使わない。過去の大規模探索では別に比較済み。汎用エンジンの反転補充は保有反転の例外として残る。',
              '共通': '費用0・指定価格約定、片方向TOPIX10/NK20以内、全玉場内返済。時間上限360分。日15:35/夜05:50の条件から次の観測で返済。',
              'managers': catalog(), 'コードSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    destination = HERE / '管理設計の固定.json'
    if destination.exists():
        old = json.loads(destination.read_text(encoding='utf-8'))
        assert {k: v for k, v in old.items() if k != '固定日時'} == {k: v for k, v in record.items() if k != '固定日時'}
        return old
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record


if __name__ == '__main__':
    print('管理設計を結果前固定:', len(freeze()['managers']), '条件', flush=True)
