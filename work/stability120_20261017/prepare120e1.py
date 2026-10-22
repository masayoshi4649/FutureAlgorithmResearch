"""未実行eの経済源を変えず、空でない実行前検査へ修正して別実装を準備する。"""

from pathlib import Path


def main() -> None:
    """
    機能: 凍結eを保持し、同bytesの経済源と非空runtimeを別フォルダへ用意する。
    引数: なし。
    返り値: None。市場入力も金融も実行しない。
    """
    base=Path(__file__).resolve().parent
    old=base/'recovery_e'
    new=base/'recovery_e1'
    new.mkdir(exist_ok=False)
    for original,target in (('engine120e.py','engine120e1.py'),('catalog120e.py','catalog120e1.py')):
        (new/target).write_bytes((old/original).read_bytes())
    for original,target in (('run120e.py','run120e1.py'),('runtime120e.py','runtime120e1.py'),('register120e.py','register120e1.py')):
        text=(old/original).read_text(encoding='utf-8')
        for before,after in (('engine120e','engine120e1'),('catalog120e','catalog120e1'),('runtime120e','runtime120e1'),
                             ('register120e','register120e1'),('run120e.py','run120e1.py')):
            text=text.replace(before,after)
        if original.startswith('runtime'):
            assert 'x,x-10,x+10' in text
            text=text.replace('x,x-10,x+10','x,x,x+10')
            text=text.replace('entry=o[o[:,1]==1]',"entry=o[o[:,1]==1]\n            assert len(entry)>0, (cap,mode,'金融前人工が空です')")
        if original.startswith('register'):
            text=text.replace('120e_逆側カバーを外さず組全体回収まで維持する段階追尾',
                              '120e1_十八条件の実行時人工を非空にして金融前に再固定')
            text=text.replace("purpose='条件比較'","purpose='不具合修正'")
            text=text.replace("compares_to=['120d_","compares_to=['120e_逆側カバーを外さず組全体回収まで維持する段階追尾','120d_")
            text=text.replace('ユーザーが逆側追加がカバーして追い越す意図を再確認し、',
                'eは事前登録済みだが、実行前runtimeの人工BBO幅がunitを超えて全modeの新規ゼロとなる空同値guardを発見し、金融未実行0で中止。engine/catalogの経済bodyは同bytesのまま、runtimeの人工だけtick整合したbid=x/ask=x+10とし全caseentries>0を追加して別登録する。ユーザーが逆側追加がカバーして追い越す意図を再確認し、')
        (new/target).write_text(text,encoding='utf-8')
    (new/'入力目録.json').write_bytes((old/'入力目録.json').read_bytes())
    print('e源は不変、同bytes経済源のe1を非空guardで新規準備。金融0。')


if __name__=='__main__':
    main()
