"""新しい三基準と全33場表示を広狭画面で保存会計へ照合する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

import report


def main() -> None:
    """
    機能: 四比較の切替・全場と総計・三基準の表示・暗色と横幅を確認する。
    引数: なし。完成HTMLと公開小会計だけを利用する。
    返り値: None。照合証跡と画面画像を保存し、金融・APIを利用しない。
    """
    source = (report.PUBLIC/(report.TITLE+'.html')).read_text(encoding='utf-8')
    data = json.loads((report.PUBLIC/'65基準の公開会計.json').read_text(encoding='utf-8'))
    tables, metrics = {}, {}
    for key, pair in data['pairs'].items():
        indices = {s: {r['session']: r for r in data['cases'][i]['symbols'][s]['rows']} for s, i in pair['ids'].items()}
        sessions = sorted(indices['TOPIX'])
        tables[key] = [[indices[s][session][f]*(-1 if f == 'loss' else 1)
                        for s in ('TOPIX','NK225') for f in ('profit','loss','net')] for session in sessions]
        tables[key].append([data['cases'][pair['ids'][s]]['symbols'][s]['full'][f]*(-1 if f == 'loss' else 1)
                            for s in ('TOPIX','NK225') for f in ('profit','loss','net')])
        metrics[key] = []
        for symbol, ident in pair['ids'].items():
            full = data['cases'][ident]['symbols'][symbol]['full']
            tail = data['cases'][ident]['symbols'][symbol]['without_top3']
            metrics[key].append([
                report.percent(full['profit_share']), report.percent(tail['profit_share']),
                f'{full["red"]}/{full["sessions"]}（{report.percent(full["red_all"])}）',
                f'{full["red"]}/{full["active"]}（{report.percent(full["red_active"])}）',
                report.money(full['mean_green']), report.money(full['worst_red']),
                f'{full["green"]}/{full["red"]}/{full["no_trade"]}',
                ' ／ '.join('○' if v else '×' for v in full['tests'].values()),
            ])
    # ----------------------------------------
    # 共通の隔離Chromeで表示だけを実行する。
    spec = importlib.util.spec_from_file_location('新三基準の表示だけの隔離Chrome',report.ROOT/'work/wave_v52/review/verify_report.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    output = report.HERE/'review'
    output.mkdir(parents=True, exist_ok=True)
    renderer.OUT, renderer.VISUAL = output, output/'visual'
    payload = json.dumps(dict(tables=tables, metrics=metrics), ensure_ascii=False).replace('</','<\\/')
    renderer.PROBE = '''<script>
/**
 * 保存会計に対して四比較の全場・総計・基準表示を検査する。
 * @returns {object} 数値・表示件数と画面幅の確認結果。
 */
function verifyDisplay(){
 const data=__PAYLOAD__,first=document.getElementById('pair').value;let values=0,labels=0;
 for(const [key,expected] of Object.entries(data.tables)){
  showPair(key);const visible=[...document.querySelectorAll('[data-pair]')].filter(n=>!n.hidden);
  if(visible.length!==1||visible[0].dataset.pair!==key)throw Error('条件切替');
  const section=visible[0],rows=section.querySelector('table.sessions tbody').rows;
  if(rows.length!==34)throw Error('全33場と総計');
  for(let i=0;i<34;i++)for(let j=0;j<6;j++){
   const number=Number(rows[i].cells[j+1].textContent.replaceAll(',',''));
   if(Math.abs(number-expected[i][j])>.500001)throw Error('円額差');values++;
  }
  const stats=section.querySelector('table.metrics tbody').rows;if(stats.length!==2)throw Error('2商品');
  for(let i=0;i<2;i++)for(let j=0;j<8;j++){
   if(stats[i].cells[j+1].textContent!==data.metrics[key][i][j])throw Error('基準表示差');labels++;
  }
 }
 showPair(first);if(document.documentElement.scrollWidth>innerWidth+2)throw Error('本文横溢れ');
 if(getComputedStyle(document.body).backgroundColor!=='rgb(11, 17, 32)')throw Error('暗色背景');
 if(/undefined|NaN|Infinity/.test(document.body.innerText))throw Error('数値欠測の表示');
 return {全合格:true,比較数:4,会計円額照合:values,三基準表示照合:labels,画面幅:innerWidth,文書幅:document.documentElement.scrollWidth,金融再生:0};
}
try{document.body.dataset.check=JSON.stringify(verifyDisplay());}catch(error){document.body.dataset.check=JSON.stringify({全合格:false,理由:String(error)});}
</script>'''.replace('__PAYLOAD__',payload)
    screens = [renderer.render(source, '新三基準'+str(width), width, 1200) for width in (1450,520)]
    proof = dict(全合格=True, 画面=screens, HTML_SHA256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
                 金融再生=0, API取得=0, 根目視確認=False)
    (output/'変更後三基準と全場表の広狭確認.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__ == '__main__':
    main()
