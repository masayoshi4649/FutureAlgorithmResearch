"""実成績を参照せず、架空データだけで両テンプレートの表示切替を検査する。"""

import importlib.util
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'work/wave_v52/review/verify_report.py'
spec = importlib.util.spec_from_file_location('管理テンプレートのブラウザ検査', SOURCE)
browser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser)
browser.OUT = HERE
browser.VISUAL = HERE / 'visual'


def fake() -> dict:
    """機能: 市場成績と無関係の架空表示値を作る。

    引数: なし。返り値: 共通表示データ(dict)。
    """
    row = dict(campaign_profit=1000, campaign_loss=1200, net=-200, campaigns=3,
        campaign_wins=1, campaign_losses=2, campaign_win_rate=1/3, campaign_payoff=5/3,
        drawdown=1600, max_long=10, max_short=5, profit=2000, loss=2200,
        winning_lots=10, losing_lots=20, core_net=-300, cover_net=100, fees=100)
    session = '2026-01-01_Day'
    periods = {p: {s: row.copy() for s in ('TOPIX', 'NK225')} for p in ('前16', '後12', '全28')}
    methods = []
    for index, manager in enumerate(('H03', 'N03', 'R01')):
        config = dict(source='T2L0', group='保険両建て' if index==0 else '縮小復帰' if index==1 else '利益固定',
                      manager=manager, name='架空表示検査')
        method = dict(id='T2L0_'+manager, config=config, configText='架空データ・実成績ではありません',
            explanation='テンプレートの表示を検査する架空の説明です。', periods=periods,
            baseline=dict(periods=periods), control=dict(periods=periods),
            rows=[dict(row, session=session, symbol=s) for s in ('TOPIX', 'NK225')],
            weeks={s:[dict(row,label='架空の週')] for s in ('TOPIX', 'NK225')},
            orders={session+'|'+s:[[2,1,0,1,10,100,10,1,0,1000],
                                  [4,3,0,-1,2,99,7,1,1,1600],
                                  [6,5,0,1,2,98,8,0,1,2200],
                                  [8,7,0,-1,10,101,2,0,0,2800]] for s in ('TOPIX','NK225')})
        methods.append(method)
    return dict(title='架空データによる表示検査', sessions=[session], methods=methods,
                bars={session+'|'+s:[[900,100,102,98,101],[1200,101,103,97,99],
                                    [1500,99,102,97,100],[1800,100,102,98,101],
                                    [2100,101,104,99,102],[2400,102,103,99,101],
                                    [2700,101,104,99,103]] for s in ('TOPIX','NK225')},
                notes=['架空データです。実成績と区別します。'],sourceNotes=['入力検査用'],
                conclusion='架空データでの表示検査です。',selectedIds=['T2L0_H03'], mainUrl='template.html')


def main() -> None:
    """機能: JavaScript構文と主・全一覧の広狭画面切替を検査する。

    引数: なし。返り値: なし(None)。実際の損益ファイルは開かない。
    """
    data = fake()
    results = []
    for name in ('template.html', 'all_template.html'):
        template = (HERE / name).read_text(encoding='utf8')
        assert template.count('__DATA__') == 1
        code = template.split('<script>')[1].split('</script>')[0]
        syntax = subprocess.run(['node','--check'],input=code,text=True,capture_output=True)
        assert syntax.returncode == 0, syntax.stderr
        if name=='template.html':
            probe = '''const q=window.reportTest;for(let i=0;i<q.D.methods.length;i++){for(const s of ['TOPIX','NK225'])for(const p of ['前16','後12','全28']){q.STATE.get(i).symbol=s;q.STATE.get(i).period=p;q.updateMethod(i);const root=document.getElementById('method-'+i);if(root.querySelector('.comparison tbody').rows.length!==3)throw Error('無保険対照行');if(root.querySelectorAll('.chart svg circle').length!==2)throw Error('新規丸');if(root.querySelectorAll('.chart svg path').length!==2)throw Error('返済菱形');if(/NaN|undefined|Infinity/.test(root.innerHTML))throw Error('欠測表示');}}'''
        else:
            data['methods'][2]['control'] = True
            probe = '''const q=window.reportTest;if(q.D.methods.length!==3)throw Error('条件件数');for(const m of q.D.methods){q.selectMethod(m.id);for(const s of ['TOPIX','NK225']){q.STATE.symbol=s;q.renderCondition();if(document.querySelector('#session-table tbody').rows.length!==2)throw Error('セッション表');if(/undefined|NaN|Infinity/.test(document.body.innerText))throw Error('未定義表示');}}if(!document.querySelector('#summary').innerText.includes('診断・選定外'))throw Error('診断タグ');q.STATE.source='T2L0';q.STATE.group='保険両建て';q.renderList();if(document.querySelector('#summary tbody').rows.length!==1)throw Error('系統フィルタ');'''
        browser.PROBE = '<script>try{'+probe+'''if(document.documentElement.scrollWidth>innerWidth+2)throw Error('横溢れ');document.body.dataset.check=JSON.stringify({全合格:true,架空データ:true,文書幅:document.documentElement.scrollWidth,画面幅:innerWidth});}catch(e){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(e),stack:e.stack});}</script>'''
        html = template.replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('<','\\u003c'))
        for width in (1360,500):
            results.append(browser.render(html,name.split('.')[0]+str(width),width,1300))
    (HERE / '架空データ表示検査.json').write_text(json.dumps(dict(全合格=True,実成績参照=False,結果=results),
        ensure_ascii=False,indent=2),encoding='utf8')
    print('架空データのみのJavaScript構文・主3章・全一覧・広狭画面表示が合格しました')


if __name__ == '__main__':
    main()
