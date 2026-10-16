"""一読保全した二資料だけから、四分類と事後診断の分母・主張を確認する。"""

import hashlib
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
CHECKS = []
STATES = ('true', 'false', 'unknown')
COUNTS = {1: '順先', -1: '逆先', 0: '窓末未決', 2: 'EOF未決', -2: '基準不可'}


def check(name: str, condition: bool) -> None:
    """
    機能: 限定資料の一致を記録し、不成立を停止する。
    引数: name(str)、condition(bool) は内容と成否。
    返り値: None。既結果や公開文書を編集しない。
    """
    CHECKS.append(dict(項目=name, 合格=bool(condition)))
    assert condition, name


def metric(saved: dict, labels: list[int], name: str) -> None:
    """
    機能: 五状態と未決込みの率を158行の保存ラベルから再加算する。
    引数: saved(dict)、labels(list[int])、name(str) は保存集計・ラベル・名称。
    返り値: None。新しい先着や入口は作らない。
    """
    n = len(labels)
    check(name + '分母', saved['n'] == n)
    for code, key in COUNTS.items():
        check(name + key, saved[key] == labels.count(code))
    resolved = labels.count(1) + labels.count(-1)
    check(name + '解決数', saved['resolved'] == resolved)
    for key, wanted in (('全候補順先率', labels.count(1) / n if n else None),
                        ('解決内順先率', labels.count(1) / resolved if resolved else None),
                        ('解決率', resolved / n if n else None)):
        check(name + key, saved[key] is None if wanted is None else math.isclose(saved[key], wanted, abs_tol=1e-12))


def display(saved: dict) -> str:
    """
    機能: MDと同じ丸めで順先の分子分母を文字列へ変換する。
    引数: saved(dict) は小集計。
    返り値: str は未知を未定義とした比率文字列。
    """
    n, won = saved['n'], saved['順先']
    return f'{won}/{n} ({100 * won / n:.2f}%)' if n else '0/0（未定義）'


def main() -> None:
    """
    機能: 保存二資料の閾値・期間分母・全表示表・留保を確認し最終証跡を保存する。
    引数: なし。
    返り値: None。HTML・公開JSON・凍結源・原入力・prepared・金融を読まない。
    """
    copied = HERE / 'copies'
    md_path = copied / 'S03の値幅と方向の条件別診断.md'
    small_path = copied / 'S03既158予兆の四分類と因果二対照の集計.json'
    md = md_path.read_text(encoding='utf-8')
    small = json.loads(small_path.read_text(encoding='utf-8'))
    check('完成した限定射影', small['全合格'] and small['既S03予兆'] == len(small['records']) == 158)
    check('読取scope', small['prepared読取'] == 37 and all(small[key] == 0 for key in ('元raw', '元測定結果', '新測定', '金融', 'API')))
    sessions = [item['session'] for item in small['読取']]
    check('37場の一意順', len(sessions) == len(set(sessions)) == 37 and sessions == sorted(sessions))
    periods = {'学習21': sessions[:21], '選択6': sessions[21:27], '別枠6': sessions[27:33],
               '追加4': sessions[33:], '別枠10': sessions[27:], '全37': sessions}
    records = small['records']
    check('158予兆の一意', len({(row['session'], row['pub_raw_row']) for row in records}) == 158)
    for row in records:
        for label, threshold in (('A', 10.), ('B', 20.), ('C', 2.5), ('D', 2.5)):
            value, state = row['values'][label], row['classes'][label]
            wanted = 'unknown' if value is None else 'true' if value >= threshold else 'false'
            check('保存値から閾値分類' + label, state == wanted)
        for label, control in (('C', 'twenty'), ('D', 'start')):
            value, measured = row['values'][label], row['controls'][control]
            check('当時差と対照の既知', measured['known'] == (value is not None))
            if value is not None:
                expected = (1 if value > 0 else -1 if value < 0 else 0) * row['side']
                check('当時差と対照の符号', measured['side'] == expected)
                if expected == row['side']:
                    check('同方向対照のラベル', measured['labels'] == row['labels'])
    for name, selected_sessions in periods.items():
        saved = small['periods'][name]
        rows = [row for row in records if row['session'] in selected_sessions]
        check('期間の場数と予兆数', saved['場数'] == len(selected_sessions) and saved['予兆数'] == len(rows))
        for ri in range(3):
            metric(saved['S03'][ri], [row['labels'][ri] for row in rows], name)
        for label in ('A', 'B', 'C', 'D'):
            check('独立分類を合算しない', sum(saved['条件'][label][state]['n'] for state in STATES) == len(rows))
            for state in STATES:
                group = [row for row in rows if row['classes'][label] == state]
                item = saved['条件'][label][state]
                check('群の買売と件数', item['n'] == item['買い数'] + item['売り数'] == len(group))
                for ri in range(3):
                    metric(item['risks'][ri], [row['labels'][ri] for row in group], name + label + state)
        for title, key in (('始値比方向', 'start'), ('20分差方向', 'twenty')):
            compared = saved['因果対照'][title]
            known = [row for row in rows if row['controls'][key]['known']]
            nonzero = [row for row in known if row['controls'][key]['side'] != 0]
            check('対照群とゼロ未知の分母', compared['比較群n'] == len(nonzero) and
                  compared['既知ゼロ方向除外'] == len(known) - len(nonzero) and compared['未知除外'] == len(rows) - len(known))
            for ri in range(3):
                metric(compared['S03同群'][ri], [row['labels'][ri] for row in nonzero], title + 'S03同群')
                metric(compared['対照同群'][ri], [row['controls'][key]['labels'][ri] for row in nonzero], title + '対照同群')
    early = small['periods']['学習21']
    later = [row for row in records if row['session'] in sessions[21:]]
    check('早期後期の分母差', early['予兆数'] == 89 and len(later) == 69 and
          early['S03'][2]['順先'] == 35 and sum(row['labels'][2] == 1 for row in later) == 41)
    reweighted = {}
    for label in ('A', 'B', 'C', 'D'):
        value = 0.
        for state in STATES:
            n = sum(row['classes'][label] == state for row in later)
            train = early['条件'][label][state]['risks'][2]
            check('再加重で欠群を0救済しない', n == 0 or train['n'] > 0)
            if n:
                value += n / len(later) * train['順先'] / train['n']
        reweighted[label] = value
        expected_line = f'| {label} | {value * 100:.2f}% | {100 * 41 / 69:.2f}% |'
        check('MDの参考再加重' + label, expected_line in md)
    rows_in_md = [[cell.strip() for cell in line.strip().strip('|').split('|')] for line in md.splitlines() if line.startswith('|')]
    table = [parts for parts in rows_in_md if len(parts) == 8 and parts[0] in periods and parts[1] in ('A', 'B', 'C', 'D') and parts[2] in STATES]
    check('MD72群行', len(table) == 72)
    for parts in table:
        saved = small['periods'][parts[0]]['条件'][parts[1]][parts[2]]['risks']
        check('MDの三逆行幅セル', parts[3:6] == [display(cell) for cell in saved])
        check('MDの逆先未決セル', parts[6] == str(saved[2]['逆先']) and parts[7] == str(saved[2]['窓末未決'] + saved[2]['EOF未決']))
    for expected in (
        't−19..tの20本高安幅≧10pt', 't−59..tの60本高安幅≧20pt',
        'close[t]−close[t−20]', 't−20..tの21本が全てvalid', '最初valid足open',
        '途中空足でも始点をresetしない', 'unknownをfalse・失敗・成功へ補完しない',
        '理由を特定できなかった', '今回の内訳を採用フィルタへ変換していない',
        '新しい入口生成、閾値探索、AND組合せ、新収支計算は0',
        '同じS03予兆群', '因果効果を同定したという意味ではない',
        '因果分解や再加重による戦略収益ではない', '未知検証ではない'):
        check('定義と主張の留保', expected in md)
    proof = dict(全合格=True, 検査数=len(CHECKS), 検査=CHECKS,
        evidence={md_path.name: hashlib.sha256(md_path.read_bytes()).hexdigest(), small_path.name: hashlib.sha256(small_path.read_bytes()).hexdigest()},
        早期=dict(場=21, 予兆=89, 順先=35), 後期=dict(場=16, 予兆=69, 順先=41),
        参考再加重=reweighted, 主張判定='四つの当時特性の構成変化では差を特定できないとの限定的診断。新政策・未知成功・因果効果を主張していない。',
        限界='既158行の保存特性値・ラベルと文書の整合だけ。過去窓を原価格から再構築せず、保存列が原データから正しく計算されたとの新独立証明は追加しない。',
        原資料二本文読取各1=True, HTML=0, 公開JSON=0, 凍結10source=0, 原入力=0, prepared=0, 金融=0, API=0)
    destination = HERE / '四分類MDと既158予兆の分母及び事後限定の最終整合.json'
    assert not destination.exists()
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=len(CHECKS), 参考再加重=reweighted, 不整合=0, 追加市場読取=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
