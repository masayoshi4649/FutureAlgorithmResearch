"""根が指定した00107参考一条件だけを公開会計から一読し、候補外比較を保存する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'アルゴリズム調査/00107_保有容量と一取引利益の再検証/容量別E01の一場平均と全場会計.json'
SOURCE_SHA = '2ef11847719b78edc0506ee6d1905a825e09211135370a493763947b2a15a6ae'
CASE = 'E01_SCALE_SELECTED_RISK_GU'


def main() -> None:
    """
    機能: 指定公開会計を一目的一読し、参考一条件のfull/trim3/数量を保存する。
    引数: なし。根が指定したCASE(str)だけを比較用に射影する。
    返り値: None。旧金融の再計算・旧入力・旧台帳・新結果・APIは0。
    """
    output = HERE/'107固定参考RISK_GUの候補外小射影.json'
    assert not output.exists()
    raw = SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA
    data = json.loads(raw.decode('utf-8-sig'))
    assert data['全合格'] and data['new_count'] == 14
    item = data['cases'][CASE]
    fields = ('profit', 'loss', 'net', 'profit_share', 'sessions', 'positive', 'negative',
        'active', 'no_trade', 'red_all', 'mean_positive_session_net', 'worst_session_loss',
        'campaigns', 'winning_campaigns', 'losing_campaigns', 'winning_lots', 'losing_lots',
        'mean_parent_net', 'mean_session_net', 'pass_all', 'primary_pass')
    symbols = {}
    for s in ('TOPIX', 'NK225'):
        full, trim = item['metrics'][s]['full'], item['metrics'][s]['top3']
        assert not full['primary_pass'] and not full['pass_all']
        symbols[s] = dict(full={k: full[k] for k in fields}, top3={k: trim[k] for k in fields},
            capacity={k: item['capacity'][s][k] for k in ('mean_initial_quantity', 'mean_initial_capacity_fraction',
                'maximum_same_side_holding', 'maximum_holding_capacity_fraction')})
        symbols[s]['top3']['removed_sessions'] = trim['removed_sessions']
    value = dict(全合格=True, id=CASE, source=SOURCE.relative_to(ROOT).as_posix(), source_SHA256=SOURCE_SHA,
        symbols=symbols, 推奨=False, 新候補へ不算入=True, 新独立標本=0,
        引用範囲='事前固定した107参考RISK_GU一条件だけ。TOP/NK full・trim3・q・親数・黒赤無。',
        公開会計読取=1, 旧金融=0, 旧入力=0, 旧台帳=0, 新金融=0, 新結果=0, API=0)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, path=output.relative_to(ROOT).as_posix(),
        SHA256=hashlib.sha256(output.read_bytes()).hexdigest(), 公開会計読取=1, 新金融=0, 新結果=0, 入力=0, 台帳=0, API=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
