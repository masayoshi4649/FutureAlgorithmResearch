"""保存した四分類小集計だけから、全内訳と事後理解の短い説明を作る。"""

from fractions import Fraction
import hashlib
import json
from pathlib import Path

import context_reader


HERE=Path(__file__).resolve().parent


def rate(row: dict) -> str:
    """
    機能: 順先の分子/全候補分母を表示する。
    引数: row(dict) は同じ逆行幅のcount。
    返り値: str。分母0は未定義。
    """
    if not row['n']:return '0/0（未定義）'
    assert row['全候補順先率']==float(Fraction(row['順先'],row['n']))
    return f"{row['順先']}/{row['n']} ({100*row['順先']/row['n']:.2f}%)"


def main() -> None:
    """
    機能: 結果後の説明を全分類の表と分解算術へ結び付けて保存する。
    引数: なし。
    返り値: None。原preparedや元測定結果を再読しない。
    """
    source=HERE/'S03既158予兆の四分類と因果二対照の集計.json'
    raw=source.read_bytes();data=json.loads(raw.decode('utf-8'));assert data['全合格']
    before=data['periods']['学習21']
    # 実在予兆がない場はrecordsに出ないため、期間の根拠は事前固定の37場分割を使う。
    plan=json.loads((HERE/'四分類の事後理解と三十七保存出力の一読固定.json').read_text(encoding='utf-8'))
    after=context_reader.aggregate(data['records'],plan['期間']['選択6']+plan['期間']['別枠10'])
    assert before['予兆数']==89 and after['予兆数']==69
    assert before['S03'][2]['順先']==35 and after['S03'][2]['順先']==41
    p0=Fraction(35,89);p1=Fraction(41,69)
    decomposition={}
    for condition in ('A','B','C','D'):
        reweighted=Fraction(0)
        for state in ('true','false','unknown'):
            g0=before['条件'][condition][state];g1=after['条件'][condition][state]
            if g1['n']:
                assert g0['n']>0
                reweighted+=Fraction(g1['n'],69)*Fraction(g0['risks'][2]['順先'],g0['n'])
        decomposition[condition]=dict(学習率=float(p0),後16率=float(p1),
            学習群内率を後16の群比率で重み直した率=float(reweighted),
            群比率の算術差=float(reweighted-p0),群内率変化を含む残差=float(p1-reweighted),
            留保='粗い事後三群での算術再加重。因果分解・新予測・フィルタ成績ではない。')
    lines=['# S03の成績変化と当時価格特性の事後診断','',
        '**指定の四分類では、学習21場の39.33%から後16場の59.42%へ変わった理由を特定できなかった。** 大きな過去値幅や既存方向が強い群へ移った、という単純な説明ではない。同じ粗い分類の中でも後期の率が上がっており、今回の内訳を採用フィルタへ変換していない。',
        '',
        '対象は元のS03既158予兆のみ。37保存出力を各一回読み、公開候補数・共通±10pt非重複行・三逆行幅・買売・常時買売を各場で既存小射影と完全照合した。新しい入口生成、閾値探索、AND組合せ、新収支計算は0。',
        '',
        '## 固定した四条件','',
        '- A：当時の確定足t−19..tの20本高安幅≧10pt。',
        '- B：t−59..tの60本高安幅≧20pt。',
        '- C：S03方向×(close[t]−close[t−20])≧2.5pt。t−20..tの21本が全てvalid。',
        '- D：S03方向×(公開anchor−当時までの最初valid足open)≧2.5pt。途中空足でも始点をresetしない。',
        '',
        'A/B/Cの必要窓に欠足や履歴不足があればunknown。Dは現在anchorと始点が既知の時だけ判定。unknownをfalse・失敗・成功へ補完しない。各条件は別々の分類であり、四表を合算して予兆数を増やさない。',
        '', '## 全体の変化は分類比率だけでは説明できない','',
        '| 分類 | 学習群内の順先率を固定し、群比率だけ後16へ替えた率 | 実際の後16 |',
        '|---|---:|---:|']
    for c,d in decomposition.items():
        lines.append(f"| {c} | {100*d['学習群内率を後16の群比率で重み直した率']:.2f}% | {float(100*p1):.2f}% |")
    lines+=['',
        '学習は35/89＝39.33%。群の比率だけを替えた算術は約39～40%に留まる。四つの粗い特性の構成変化だけで約20％ポイントの上昇を説明できず、残りを特定の市場原理の効果とも認定できない。これは事後の算術整理で、因果分解や再加重による戦略収益ではない。',
        '', '## 別枠10・順行10pt対逆行10pt','',
        '| 分類 | true | false | unknown |',
        '|---|---:|---:|---:|']
    held=data['periods']['別枠10']
    for c,groups in held['条件'].items():
        lines.append('| '+c+' | '+' | '.join(rate(groups[state]['risks'][2]) for state in ('true','false','unknown'))+' |')
    lines+=['',
        'Cはtrue/falseとも60%。Aもtrue側が高い形ではない。BやDに差はあるが、小標本・期間ごとの変動を残す。ここで一番良い群を採用する選択はしていない。',
        '', '## 同時点の因果方向を使う対照','',
        '「始値比方向」はsign(anchor−最初open)、「20分差方向」はsign(close[t]−close[t−20])。いずれも当時分かる非零方向だけの**同じS03予兆群**で比較し、ゼロ方向と未知は別に除外した。因果とは未来を使わない時点関係を意味し、因果効果を同定したという意味ではない。',
        '',
        '| 期間 | 対照 | 比較n | S03（逆行10） | 対照（逆行10） | 既知ゼロ除外 | 未知除外 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for name,p in data['periods'].items():
        for control,c in p['因果対照'].items():
            lines.append(f"| {name} | {control} | {c['比較群n']} | {rate(c['S03同群'][2])} | {rate(c['対照同群'][2])} | {c['既知ゼロ方向除外']} | {c['未知除外']} |")
    lines+=['',
        '学習側では始値方向に35/88対36/88、20分差方向に33/84対33/84。別枠10では24/40対19/40、24/39対18/39。単純な当時方向より後期S03が良いという内訳はあるが、期間を通じた安定した差は未確認。前の診断で示した「別枠6では常時買い、追加4では常時売りとS03が同率」という反証も残る。異なる対照が違う側面を測るため、一つだけを選んで優位を主張しない。',
        '', '<details><summary>全六期間・四分類・true/false/unknown・三逆行幅の全内訳</summary>','',
        '全欄の分母は未決も含む各群の既予兆数。逆先・未決は逆行10ptの内訳を併記。',
        '',
        '| 期間 | 条件 | 群 | 順先10対逆行2.5 | 順先10対逆行5 | 順先10対逆行10 | 逆先10 | 未決10 |',
        '|---|---|---|---:|---:|---:|---:|---:|']
    for name,p in data['periods'].items():
        for c,groups in p['条件'].items():
            for state,g in groups.items():
                risks=g['risks'];last=risks[2];pending=sum(last[k] for k in ('窓末未決','EOF未決','基準不可'))
                lines.append(f"| {name} | {c} | {state} | {rate(risks[0])} | {rate(risks[1])} | {rate(last)} | {last['逆先']} | {pending} |")
    lines+=['','</details>','',
        '## 限界と次に残る問い','',
        'この診断はS03の成績を見た後に立てた説明仮説で、未知検証ではない。20/60分幅・20分方向・始値位置の四条件で原因が分からなかったことを、板やテクニカル全体の無価値ともしない。後期の良い結果が持続するかは、S03本体と評価幅を固定した今後の期間で確かめる必要がある。注文・供給の主体、ニュース、観測されなかった価格、費用後利益は今回測っていない。',
        '',
        '[全数値と158行の小射影](S03既158予兆の四分類と因果二対照の集計.json) · [実読前の計画](四分類の事後理解と三十七保存出力の一読固定.json) · [分類pure検査](四分類と窓境界及び因果二方向の純人工.json)','']
    md=HERE/'S03の前後差と四つの当時特性の事後診断.md';assert not md.exists()
    md.write_text('\n'.join(lines),encoding='utf-8')
    public=HERE.parents[2]/'アルゴリズム調査/00118_TOPIX十ポイントの予兆と多尺度方向予測/S03の値幅と方向の条件別診断.md'
    assert public.parent.is_dir() and not public.exists()
    content=md.read_text(encoding='utf-8')
    for name in ('S03既158予兆の四分類と因果二対照の集計.json','四分類の事後理解と三十七保存出力の一読固定.json','四分類と窓境界及び因果二方向の純人工.json'):
        content=content.replace(']('+name+')','](../../work/topix10pt_20261016/s03_context/'+name+')')
    public.write_text(content,encoding='utf-8')
    proof=dict(全合格=True,元集計SHA256=hashlib.sha256(raw).hexdigest(),本文SHA256=hashlib.sha256(md.read_bytes()).hexdigest(),
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),三群比率の算術再加重=decomposition,
        公開新規MD=public.relative_to(HERE.parents[2]).as_posix(),公開MD_SHA256=hashlib.sha256(public.read_bytes()).hexdigest(),
        本文全内訳行=72,各群幅セル=216,因果対照表=12,
        原prepared追加読取=0,元結果=0,金融=0,新閾値=0,条件組合せ=0,最良条件選択=0)
    target=HERE/'四分類説明と全内訳及び事後再加重の算術確認.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,MD_SHA256=proof['本文SHA256'],算術再加重=decomposition),ensure_ascii=False))


if __name__=='__main__':main()
