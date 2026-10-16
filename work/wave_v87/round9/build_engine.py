"""前段の保険入口を保持し、初期停止の基準だけを予約前の極値へ替える。"""
from pathlib import Path

HERE=Path(__file__).resolve().parent


def replace_once(text,before,after):
    """
    機能: 凍結した生成元の想定断片を一度だけ置き換える。
    引数: text/before/after(str)。
    返り値: str。予期しない旧実装変更を拒否する。
    """
    assert text.count(before)==1,before[:100]
    return text.replace(before,after)


def build():
    """
    機能: 同じ保険入口と追尾管理に、初期停止基準の四対照を加える。
    引数: なし。
    返り値: None。旧ファイルは変更しない。
    """
    source=(HERE.parent/'round8/engine.py').read_text(encoding='utf-8')
    source=replace_once(source,'"""順行極値からの逆行と公開済み反対支持で、独立保険を一度だけ建てる。"""',
        '"""逆行保険の初期停止だけを、新規前の極値又は実建値から定める。"""')
    source=replace_once(source,'seq,own_value,own_valid,peer_value,peer_valid,own_release_seq,peer_release_time):',
        'seq,own_value,own_valid,peer_value,peer_valid,own_release_seq,peer_release_time,stop_mode):')
    source=replace_once(source,'end/cutoff/tick/各幅(float)、relation/confirm(int)、observed(bool)、',
        'end/cutoff/tick/各幅(float)、relation/confirm/stop_mode(int)、observed(bool)、')
    before='''                width=max(tick,stop_atr*atr)
                child=rounded(entry-sat_side*width,tick,-sat_side)
                child_row=i;child_reason=81;child_market=-sat_side*(p-child)>=-1e-9'''
    after='''                width=max(tick,(.5 if stop_mode==3 else stop_atr)*atr)
                if stop_mode==0 or stop_mode==3:
                    child=rounded(entry-sat_side*width,tick,-sat_side)
                else:
                    assert stop_mode==1 or stop_mode==2
                    assert 0<=extreme_row<i
                    child=rounded(core_extreme+core_side*(tick if stop_mode==2 else 0.),tick,-sat_side)
                child_row=i;child_reason=81;child_market=-sat_side*(p-child)>=-1e-9'''
    source=replace_once(source,before,after)
    (HERE/'engine.py').write_text(source,encoding='utf-8')


if __name__=='__main__':build()
