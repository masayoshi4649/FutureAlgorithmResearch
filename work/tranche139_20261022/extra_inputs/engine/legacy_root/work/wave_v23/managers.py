"""結果を見る前に固定する、異なる注文・資金管理思想の比較条件。"""

from __future__ import annotations

BASE = {
    'initial_qty': 1, 'entry_atr': .25, 'stop_atr': 1., 'main_trail': 2.,
    'add_mode': 0, 'add_step': 1., 'add_qty': 0, 'hedge_ratio': 0.,
    'hedge_trigger': .75, 'cover_add': 0, 'cover_step': .5,
    'cover_trail': .5, 'reverse_mode': 0, 'lock_fraction': 0.,
    'split_target': 0., 'timeout_min': 360., 'neutral_min': 0.,
    'us_mode': 0, 'activation_atr': 1., 'tighten_atr': 0.,
    'tight_width': 1., 'breakeven_atr': 0., 'breakeven_floor': 0.,
    'failure_min': 0., 'failure_mfe': .5, 'failure_stop': .25,
    'cooldown_min': 5., 'ttl_seconds': 120., 'entry_mode': 0,
    'signal_exit': 0, 'after_open_factor': 1., 'entry_cutoff_min': 5.,
    'warmup_min': 20., 'max_same_losses': 0, 'rearm_atr': 1.,
    'session_budget_r': 0., 'risk_yen': 0., 'point_value': 1.,
    'session_budget_yen': 0., 'max_reversals': 3,
}


def manager_catalog() -> list[dict]:
    """機能: 性能を読む前に定めた２０種類の管理条件を返す。

    引数: なし。返り値: ID・日本語説明・基準差分の辞書配列 (list[dict])。
    数量は銘柄ごとの上限割合か共通の予定損失円額から決まり、未来統計は用いない。
    """
    rows = [
        ('G00', '基本の追跡返済', '１枚。１ATR損切り、１ATR順行で２ATR追跡。場末５分前まで新規可能。', {}),
        ('G01', '方向撤回で撤退', '反対方向が確定したら次の観測で全返済し、新しい方向で入り直す。', {'signal_exit': 1}),
        ('G02', '方向撤回で実反転', '反対方向が確定したら次の観測で返済と反転。反転は１セッション３回まで。', {'reverse_mode': 1}),
        ('G03', '早めの建値保護', '０.７５ATR順行したら組全体の損益ゼロを保護し、追跡幅を１.２５ATRとする。', {'breakeven_atr': .75, 'main_trail': 1.25}),
        ('G04', '利益の半分を保護', '含み益が当初損失予算に達したら、組の最高利益の半分を返済基準にする。', {'lock_fraction': .5, 'main_trail': 1.5}),
        ('G05', '伸びた後に追跡を短縮', '１ATRで建値を少し超えて保護。２ATR伸びたら追跡幅を０.７５ATRへ短縮する。', {'breakeven_atr': 1., 'breakeven_floor': .1, 'tighten_atr': 2., 'tight_width': .75}),
        ('G06', '伸びない玉を早期撤退', '１５分経っても０.５ATR伸びなければ、許容損失を０.４ATRに縮める。', {'failure_min': 15., 'failure_mfe': .5, 'failure_stop': .4}),
        ('G07', '同方向２連敗で停止', '同方向２連敗で再注文を止める。反対信号か、直近損切り値から１ATRの順行で再開する。', {'max_same_losses': 2}),
        ('G08', '連敗とセッション損失を制限', '２連敗停止に加え、開始時に定める初回予定損失３回分へ総損益が達したら当該セッションを終了する。', {'max_same_losses': 2, 'session_budget_r': 3.}),
        ('G09', '共通２万円リスク', '注文時ATRから損切り予定額が２万円以下になる整数枚数を決定。必要１枚分にも足りなければ見送る。', {'risk_yen': 20000.}),
        ('G10', '共通リスクと損失予算', '１取引の予定損失２万円以下、セッション全体６万円で停止。方向撤回返済と建値保護も使う。', {'risk_yen': 20000., 'session_budget_yen': 60000., 'signal_exit': 1, 'breakeven_atr': 1.}),
        ('G11', '利益がある時だけ増玉', '上限の１０％から始め、同方向１ATR進むごとに１０％を追加。利益中だけ追加し、当初損失予算を増やさない。', {'quantity_fraction': .1, 'add_fraction': .1, 'add_mode': 1, 'add_step': 1., 'lock_fraction': .5, 'signal_exit': 1}),
        ('G12', '半分利確して残りを追跡', '上限の半分で開始。１.５ATRで保有の半分を利確し、残りを２.５ATR幅で伸ばす。', {'quantity_fraction': .5, 'split_target': 1.5, 'main_trail': 2.5}),
        ('G13', '部分利確と建値保護', '上限の半分で開始。１ATRで半分利確し、組全体の収支を建値保護する。', {'quantity_fraction': .5, 'split_target': 1., 'breakeven_atr': .75, 'main_trail': 1.5}),
        ('G14', '限定カバーを併用', '上限の半分から始め、０.７５ATR逆行で主玉の半分を逆方向に保有。全玉合算の損失を１ATR予算内に制御する。', {'quantity_fraction': .5, 'hedge_ratio': .5, 'hedge_trigger': .75, 'cover_trail': .5, 'lock_fraction': .5}),
        ('G15', '米国開始後の利益保護', '方向撤回で返済し、米国開始後は追跡幅を通常の７０％に縮める。', {'signal_exit': 1, 'after_open_factor': .7}),
        ('G16', '新規も追跡して短く撤退', '新規は０.２５ATRの反発・反落を追跡。損切り０.７５ATR、追跡幅１ATR、最長９０分。', {'entry_mode': 1, 'stop_atr': .75, 'main_trail': 1., 'activation_atr': .5, 'timeout_min': 90., 'cooldown_min': 3.}),
        ('G17', '共通リスクと複合防御', '予定損失２万円以下、２連敗停止、６万円でセッション停止。反対信号返済と利益半分の保護を組み合わせる。', {'risk_yen': 20000., 'session_budget_yen': 60000., 'max_same_losses': 2, 'signal_exit': 1, 'breakeven_atr': 1., 'lock_fraction': .5}),
        ('G18', '方向確定の次観測で新規', '１枚。方向確定後の次観測価格で新規し、追加の値幅確認を要求しない。緩やかな一方向相場も対象にする。', {'entry_mode': 2}),
        ('G19', '小幅確認を長く待つ新規', '１枚。０.１ATRの順行を最長１０分待って入る。緩やかな動きでも注文を早く失効させない。', {'entry_atr': .1, 'ttl_seconds': 600.}),
    ]
    return [{'id': code, 'name': name, 'description': explanation, 'changes': changes}
            for code, name, explanation, changes in rows]


def make_config(spec: dict, symbol: str, ready: dict) -> dict:
    """機能: 管理条件を銘柄の同時保有上限・小型契約倍率へ具体化する。

    引数: spec (dict) は管理条件、symbol (str) は TOPIX/NK225、ready (dict) は再生入力。
    返り値: エンジンへ渡す固定設定 (dict)。ready の未来価格統計は一切参照しない。
    """
    if symbol not in ('TOPIX', 'NK225'):
        raise ValueError('対象銘柄は TOPIX または NK225 です')
    cap = 10 if symbol == 'TOPIX' else 20
    config = dict(BASE)
    config.update(spec.get('changes', {}))
    config['audit_cap'] = cap
    config['point_value'] = 1000. if symbol == 'TOPIX' else 10.
    if 'quantity_fraction' in config:
        config['initial_qty'] = max(1, int(cap * config.pop('quantity_fraction')))
    if 'add_fraction' in config:
        config['add_qty'] = max(1, int(cap * config.pop('add_fraction')))
    return config
