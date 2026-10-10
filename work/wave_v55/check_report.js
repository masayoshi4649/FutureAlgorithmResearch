/**
 * 保存HTMLの表示関数を全手法・全セッションへ適用し、例外と行数を検査する。
 *
 * 引数: コマンドライン引数なし。
 * 返り値: なし。検査結果JSONを保存する。
 * DOM代替は関数実行の検査専用であり、ブラウザーの見た目の検査ではない。
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const filename = path.resolve(__dirname, '../../アルゴリズム調査/00052_ATRを使わない単純手法/ATRなし20条件の説明と損益.html');
const html = fs.readFileSync(filename, 'utf8');
const payload = html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const data = JSON.parse(payload);
const nodes = new Map();
/**
 * 表示対象の代替要素を返す。
 * @param {string} id 要素名。
 * @returns {Object} 値とHTMLを保持する要素。
 */
function node(id) {
    if (!nodes.has(id)) nodes.set(id, {value: id === 'symbol' ? 'TOPIX' : id === 'sort' ? 'fixed' : '', textContent: id === 'data' ? payload : '', innerHTML: '', addEventListener() {}, scrollIntoView() {}});
    return nodes.get(id);
}
const context = vm.createContext({document: {getElementById: node, addEventListener() {}}, console});
vm.runInContext(script, context, {timeout: 20000});
assert.equal((node('all-methods').innerHTML.match(/<tr/g)||[]).length, 21);
assert.equal((node('width-comparison').innerHTML.match(/<tr/g)||[]).length, 5);
let accounts = 0;
let orders = 0;
for (const method of data.results.methods) {
    node('method').value = method.id;
    for (const symbol of ['TOPIX', 'NK225']) {
        node('symbol').value = symbol;
        context.render();
        assert.equal((node('sessions').innerHTML.match(/<tr/g)||[]).length, 24);
        assert(!/NaN|undefined|Infinity/.test(node('metrics').innerHTML));
        for (const account of method.accounts.filter(a => a.symbol === symbol)) {
            node('session').value = account.session;
            context.renderSession();
            assert(node('chart').innerHTML.includes('<svg'));
            assert(!/NaN|undefined|Infinity/.test(node('chart').innerHTML));
            assert.equal((node('orders').innerHTML.match(/<tr/g)||[]).length, account.orders.length + 1);
            assert.equal((node('intervals').innerHTML.match(/<tr/g)||[]).length, account.intervals.length + 1);
            assert.equal((node('width-groups').innerHTML.match(/<tr/g)||[]).length, account.width_groups.length + 1);
            accounts += 1;
            orders += account.orders.length;
        }
    }
}
// ----------------------------------------
// 固定順を両銘柄で例外なく表示し、埋込データの注文数を照合する。
for (const symbol of ['TOPIX', 'NK225']) {
    node('symbol').value = symbol;
    context.renderComparison();
    assert.equal((node('all-methods').innerHTML.match(/<tr/g)||[]).length, 21);
}
const result = {表示関数検査: '合格', 手法数: data.results.methods.length, セッション数: data.results.sessions.length, 口座数: accounts, 全注文数: orders, 検査: ['五つの入口と各四つの幅の固定順表示', '両銘柄の固定順', '全920口座の図・注文数・区間数', '表示値にNaN・未定義・無限大なし'], 注記: 'DOM代替による表示関数検査。見た目は独立したブラウザー確認を参照。'};
fs.writeFileSync(path.join(__dirname, '表示関数監査.json'), JSON.stringify(result, null, 2), 'utf8');
console.log(JSON.stringify(result));