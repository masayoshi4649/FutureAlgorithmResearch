"""公開表の数値QAと別に、金融再利用区分と比較選定の表示だけを検算する。"""

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
ACCOUNT_SHA = '481f58915def42d729963119c0f852767921c369bee94e25852efc6382ca6a7f'
HTML_SHA = '7a09eba50544f950d1572880bfe8016dc04c89970e1f573b6995a7a6e7e16353'
REPORT_SHA = '35468313dad4d2c3858dcf70d510b6d80f3e56eba8a55d23dd62f996f6b894f3'


def main() -> None:
    """
    機能: 公開495/99/198区分、NK異なる9設定、固定選定と最大平均の差を確認する。
    引数: なし。指定SHAの公開HTML/会計だけを、この別表示目的で各一読する。
    返り値: None。金融/原結果/入力/実台帳/API/Chromeは読まず再実行しない。
    """
    public = ROOT/'アルゴリズム調査/00110_価格票と出来高代理票の入口切り分け'
    ap, hp = public/'入口情報別E01の全場会計.json', public/'価格票と出来高代理票で入口を切り分けるE01と全セッション損益.html'
    assert ap.stat().st_size <= 40_000_000 and hp.stat().st_size <= 20_000_000
    ab, hb = ap.read_bytes(), hp.read_bytes()
    assert hashlib.sha256(ab).hexdigest() == ACCOUNT_SHA and hashlib.sha256(hb).hexdigest() == HTML_SHA
    data = json.loads(ab.decode('utf-8'))
    text = BeautifulSoup(hb.decode('utf-8'), 'html.parser').get_text()
    assert data['new_count'] == 9 and data['reused_count'] == 3 and data['comparison_count'] == 12
    assert data['sources']['display_source'] == REPORT_SHA
    assert data['sources']['selection_plan'] == '44fd12b37414a74654921c7908e31709661834deb760255cd93052ea9aaee352'
    roles = Counter(p['execution_kind'] for c in data['cases'].values() for p in c['parameters'].values())
    assert roles == Counter(新金融=15, 保存PRICE=6, 内部同値保存再利用=3)
    assert len(data['sessions']) == 33 and 15*33 == 495 and 6*33 == 198 and 3*33 == 99
    symbols = ('TOPIX', 'NK225')
    unique = {s: [c for c in data['cases'].values() if s == 'TOPIX' or c['parameters'][s]['entry_id'] != 'VOL25'] for s in symbols}
    assert len(unique['TOPIX']) == 12 and len(unique['NK225']) == 9
    passed = {s: sum(c['metrics'][s]['full']['primary_pass'] for c in unique[s]) for s in symbols}
    assert '異なる設定での主合格はTOPIX '+str(passed['TOPIX'])+'/12・日経 '+str(passed['NK225'])+'/9。' in text
    assert '新唯一金融495・旧PRICE保存198・同運転NK同値引用99で792会計を比較。' in text
    for exit_id in ('TARGET', 'TIGHT_TRAIL', 'WIDE_TRAIL'):
        left, right = data['cases']['E01_INFO_VOL_SELECTED_'+exit_id], data['cases']['E01_INFO_VOL25_'+exit_id]
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
    assert '比較用の参考で、推奨候補ではありません' in text
    assert not any(c['metrics'][s]['full']['primary_pass'] for c in data['cases'].values() for s in symbols)
    proof = dict(全合格=True, 公開会計_SHA256=ACCOUNT_SHA, 公開HTML_SHA256=HTML_SHA,
        表示source_SHA256=REPORT_SHA, 金融区分=dict(新唯一=495, 内部同値=99, 旧PRICE=198, 掲載=792),
        異なる設定数={s: len(unique[s]) for s in symbols}, 主合格設定数=passed,
        事前順位の固定参考=selected, 最高場平均設定=maximum,
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
