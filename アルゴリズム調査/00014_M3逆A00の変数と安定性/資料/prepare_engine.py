"""前作業の約定順序を維持して、固定枚数型の変数を追加する。"""

from pathlib import Path


def main() -> None:
    """機能: 既存エンジンを読み取り、今回専用の拡張版を生成する。

    引数: なし。返り値: なし (None)。旧コードは変更しない。
    """
    root = Path(__file__).resolve().parent
    source = (root.parent / 'wave_v18/audit_engine_scaled.py').read_text(encoding='utf-8')
    changes = [
        ("'timeout_min','neutral_min','us_mode']", "'timeout_min','neutral_min','us_mode','activation_atr','tighten_atr',\n          'tight_width','breakeven_atr','breakeven_floor','failure_min','failure_mfe',\n          'failure_stop','cooldown_min','ttl_seconds','entry_mode','signal_exit',\n          'after_open_factor']"),
        ("11:'合算利益保護',12:'米国開始帯の縮小'}", "11:'合算利益保護',12:'米国開始帯の縮小',13:'方向状態の撤回'}"),
        ('cycle_gross=0.;cycle_net=0.;max_error=0.;min_equity=0.;max_equity=0.',
         'cycle_gross=0.;cycle_net=0.;max_error=0.;min_equity=0.;max_equity=0.\n    protected_floor=-1e100;main_floor=np.nan;pending_extreme=0.'),
        ('int(par[17])>0', 'int(par[17]) in (1,2)'),
        ('base=realized;peak=0.;anchor=pending_level;extreme=anchor',
         'base=realized;peak=0.;anchor=pending_level;extreme=anchor\n            protected_floor=-risk;main_floor=np.nan'),
        ('if abs(inv[2])>.5:\n                stop_level=',
         'mfe=d*((max(extreme,p) if d>0 else min(extreme,p))-anchor)/a\n            if par[21]>0 and mfe>=par[21]:\n                floor=max(floor,par[0]*par[22]*a)\n            if par[23]>0 and t-entry_t>=par[23]*60 and mfe<par[24]:\n                floor=max(floor,-par[0]*par[25]*a)\n            protected_floor=max(protected_floor,floor)\n            floor=protected_floor\n            if abs(inv[2])>.5:\n                stop_level='),
        ('if np.isfinite(par[3]) and d*(extreme-anchor)>=a:\n                main_level=rounded(extreme-d*par[3]*a,tick,-d)',
         'if np.isfinite(par[3]) and d*(extreme-anchor)>=par[18]*a:\n                width=par[3]\n                if par[19]>0 and d*(extreme-anchor)>=par[19]*a:\n                    width=min(width,par[20])\n                if t>=us_open:\n                    width*=par[30]\n                planned_main=rounded(extreme-d*width*a,tick,-d)\n                if not np.isfinite(main_floor) or d*(planned_main-main_floor)>0:\n                    main_floor=planned_main\n                main_level=main_floor'),
        ('elif state[i]==-d and int(par[12])>0',
         'elif state[i]==-d and par[29]>0:\n                pending_action=13;action_row=i\n            elif state[i]==-d and int(par[12])>0'),
        ('t>=last_exit+300', 't>=last_exit+par[26]*60'),
        ('pending_until=t+120;pending_row=i', 'pending_until=t+par[27];pending_row=i;pending_extreme=p'),
        ('paused=int(par[17]) in (1,2)',
         'if pending_d and int(par[28])==1:\n                pending_extreme=min(pending_extreme,p) if pending_d>0 else max(pending_extreme,p)\n                changed=rounded(pending_extreme+pending_d*par[1]*pending_atr,tick,pending_d)\n                if changed!=pending_level:\n                    pending_level=changed;pending_row=i\n            paused=int(par[17]) in (1,2)'),
    ]
    for old, new in changes:
        assert old in source, old
        source = source.replace(old, new)
    source = source.replace('"""主方向・カバー・増玉・反転を原本行の順に動かす、費用ゼロの状態機械。"""',
                            '"""M3逆A00の入口・出口を、元と同じ原本行順で比較する状態機械。"""')
    (root / 'engine.py').write_text(source, encoding='utf-8')


if __name__ == '__main__':
    main()
