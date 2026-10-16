"""公開表示の全セル検査と別に、金融区分と固定参考の意味を確認する。"""

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from bs4 import BeautifulSoup

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
ACCOUNT_SHA = 'e543125b8ec2a8f625885aaf912a2f7c441d0a151153fe8d2af0f47a21bc4e27'
HTML_SHA = '9449d627c2faef048e2be1baf6e318978fb3193589e6b4974ede2eaa60542d3c'
REPORT_SHA = 'c1ad6ca7865f96b5996e6223dee7f4386853e717c9a5d7e7c74c11c97f430db7'


def main() -> None:
    """
    機能: 公開297/99/396区分、NK異なる9設定、固定参考と最高平均の差を確認する。
    引数: なし。指定SHAの公開HTML/会計だけを、この別表示目的で各一読する。
    返り値: None。金融/原結果/入力/実台帳/API/Chromeは読まず再実行しない。
    """
    public = ROOT/'アルゴリズム調査/00111_少ない価格票で注文価格を追わない検証'
    ap = public/'価格票の最低数別E01の全場会計.json'
    hp = public/'少ない価格票で注文価格を追わないE01と全セッション損益.html'
    assert ap.stat().st_size <= 40_000_000 and hp.stat().st_size <= 20_000_000
    ab, hb = ap.read_bytes(), hp.read_bytes()
    assert hashlib.sha256(ab).hexdigest() == ACCOUNT_SHA and hashlib.sha256(hb).hexdigest() == HTML_SHA
    data = json.loads(ab.decode('utf-8'))
    text = BeautifulSoup(hb.decode('utf-8'), 'html.parser').get_text()
    assert data['new_count'] == data['reused_count'] == 6 and data['comparison_count'] == 12
    assert data['sources']['display_source'] == REPORT_SHA
    assert data['sources']['selection_plan'] == '5e3b191f5e6d41f7448cfe8f28600745fc0c08f8070594afb9f1a4cd45845551'
    roles = Counter(p['execution_kind'] for c in data['cases'].values() for p in c['parameters'].values())
    assert roles == Counter(新金融=9, 旧110経済同値保存=12, 内部同値保存再利用=3)
    assert len(data['sessions']) == 33 and 9*33 == 297 and 12*33 == 396 and 3*33 == 99
    symbols = ('TOPIX', 'NK225')
    unique = {s: [c for c in data['cases'].values() if s == 'TOPIX' or c['parameters'][s]['entry_id'] != 'VOL25'] for s in symbols}
    assert len(unique['TOPIX']) == 12 and len(unique['NK225']) == 9
    passed = {s: sum(c['metrics'][s]['full']['primary_pass'] for c in unique[s]) for s in symbols}
    assert '異なる設定での主合格はTOPIX '+str(passed['TOPIX'])+'/12・日経 '+str(passed['NK225'])+'/9。' in text
    assert '新唯一金融297・旧経済同値保存396・同運転NK同値引用99で792会計を比較。' in text
    assert '不足' not in data['selection']['TOPIX']['固定単位']
    for exit_id in ('TARGET', 'TIGHT_TRAIL', 'WIDE_TRAIL'):
        left, right = data['cases']['E01_EVID_VOL_SELECTED_'+exit_id], data['cases']['E01_EVID_VOL25_'+exit_id]
        assert left['metrics']['NK225'] == right['metrics']['NK225']
        assert left['directions']['NK225'] == right['directions']['NK225']
    source = BASE/'report_check/report.py'
    assert hashlib.sha256(source.read_bytes()).hexdigest() == REPORT_SHA
    spec = importlib.util.spec_from_file_location('表示だけの事前選定確認', source)
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    selected = {s: report.select(data['cases'], s)[0] for s in symbols}
    assert selected == data['pair']['selected']
    maximum = {s: max(data['cases'], key=lambda cid: data['cases'][cid]['metrics'][s]['full']['mean_session_net']) for s in symbols}
    assert selected['TOPIX'] == 'E01_EVID_VOL_SELECTED_TIGHT_TRAIL'
    assert maximum['TOPIX'] == 'E01_EVID_VOL_SELECTED_TARGET'
    assert selected['TOPIX'] != maximum['TOPIX']
    assert '806.8円' in text and '352.2' in text
    assert '比較用の参考で、推奨候補ではありません' in text
    assert not any(c['metrics'][s]['full']['primary_pass'] for c in data['cases'].values() for s in symbols)
    assert data['criteria']['TOPIX全場平均net円'] == 100000 and data['criteria']['NK225円額床'] is None
    assert '公開価格を限度に一回だけ試します' in text and '各2票以上' in text
    proof = dict(全合格=True, 公開会計_SHA256=ACCOUNT_SHA, 公開HTML_SHA256=HTML_SHA,
        表示source_SHA256=REPORT_SHA, 金融区分=dict(新唯一=297, 内部同値=99, 旧経済同値=396, 掲載=792),
        異なる設定数={s: len(unique[s]) for s in symbols}, 主合格設定数=passed,
        事前順位の固定参考=selected, 最高場平均設定=maximum,
        TOPIX参考平均=data['pair']['metrics']['TOPIX']['full']['mean_session_net'],
        TOPIX最高平均=data['cases'][maximum['TOPIX']]['metrics']['TOPIX']['full']['mean_session_net'],
        金融=0, 原結果=0, input=0, ledger=0, API=0, Chrome=0,
        公開各一読='全セルQAと別目的の保存再利用metadata及び事前選定照合。追加効能証拠0。')
    output = HERE/'金融再利用区分と固定参考及び最高平均の表示確認.json'
    assert not output.exists()
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, metadata_SHA256=hashlib.sha256(output.read_bytes()).hexdigest(),
        区分=proof['金融区分'], 異なる設定数=proof['異なる設定数'], selected=selected, maximum=maximum,
        金融=0, 原結果=0, input=0, ledger=0, API=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
