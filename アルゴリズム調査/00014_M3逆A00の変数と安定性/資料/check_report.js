/**
 * M3変数レポートの全表示枚数を検査する。
 *
 * 引数: なし。保存済みHTMLを読み込む。
 * 返り値: なし。結果を表示倍率検査.jsonへ保存する。
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const work = __dirname;
const root = path.resolve(work, '..', '..');
const folder = path.join(root, 'アルゴリズム調査', '00014_M3逆A00の変数と安定性');
const file = path.join(folder, 'M3逆A00の変数と安定性.html');
const source = fs.readFileSync(file, 'utf8');

/**
 * HTML属性を単純な辞書へ読み込む。
 *
 * @param {string} text - 開始タグに含まれる属性。
 * @returns {Object<string,string>} 属性名と値。
 */
function attributes(text) {
  const output = {};
  for (const match of text.matchAll(/([\w-]+)="([^"]*)"/g)) output[match[1]] = match[2];
  return output;
}

/**
 * 表示倍率検査に必要な最小限の要素を作る。
 *
 * @param {Object<string,string>} attrs - 要素の属性。
 * @param {string} text - 元の表示文字。
 * @returns {Object} 文書APIの模擬要素。
 */
function element(attrs, text = '') {
  const dataset = {};
  for (const [name, value] of Object.entries(attrs)) {
    if (name.startsWith('data-')) dataset[name.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = value;
  }
  const classes = new Set((attrs.class || '').split(/\s+/).filter(Boolean));
  return {dataset, value: '1', textContent: text, classes,
    classList: {toggle(name, enable) {if (enable) classes.add(name); else classes.delete(name);}},
    addEventListener(name, action) {assert.equal(name, 'change'); this.change = action;}};
}

// ----------------------------------------
const values = [];
for (const match of source.matchAll(/<span\b([^>]*)>([^<]*)<\/span>/g)) {
  const attrs = attributes(match[1]);
  if (attrs['data-base'] !== undefined) values.push(element(attrs, match[2]));
}
assert(values.length > 0, '表示倍率の対象がない');
const controls = [];
for (const match of source.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)) {
  const attrs = attributes(match[1]);
  if (attrs['data-scale-for']) controls.push(element(attrs));
}
assert.deepEqual(controls.map(control => control.dataset.scaleFor).sort(), ['NK225', 'TOPIX']);
const document = {
  querySelector(selector) {
    const found = selector.match(/^\[data-scale-for="(TOPIX|NK225)"\]$/);
    assert(found, selector);
    return controls.find(control => control.dataset.scaleFor === found[1]);
  },
  querySelectorAll(selector) {
    if (selector === '[data-scale-for]') return controls;
    const found = selector.match(/^\[data-symbol="(TOPIX|NK225)"\]\[data-base\]$/);
    assert(found, selector);
    return values.filter(value => value.dataset.symbol === found[1]);
  }
};
const scripts = [...source.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length, 1);
const context = {document, Math, Number, String};
vm.createContext(context);
vm.runInContext(scripts[0][1], context);

/**
 * 表示文字に含まれる金額または枚数を整数として読む。
 *
 * @param {string} value - 表示文字。
 * @returns {number} 円額または枚数。
 */
function numeric(value) {return Number(value.replace(/約|円|枚|,/g, ''));}

// ----------------------------------------
let checks = 0;
for (let topix = 1; topix <= 10; topix++) {
  for (let nikkei = 1; nikkei <= 20; nikkei++) {
    controls.find(item => item.dataset.scaleFor === 'TOPIX').value = String(topix);
    controls.find(item => item.dataset.scaleFor === 'NK225').value = String(nikkei);
    context.updateQuantity('TOPIX');
    context.updateQuantity('NK225');
    for (const value of values) {
      const quantity = value.dataset.symbol === 'TOPIX' ? topix : nikkei;
      const expected = Math.round(Number(value.dataset.base) * quantity);
      assert.equal(numeric(value.textContent), expected, JSON.stringify(value.dataset));
      assert(value.textContent.endsWith(value.dataset.kind.endsWith('units') ? '枚' : '円'));
      if (value.dataset.tone === 'sign' && value.dataset.kind.endsWith('money')) {
        assert.equal(value.classes.has('positive'), Number(value.dataset.base) >= 0);
        assert.equal(value.classes.has('negative'), Number(value.dataset.base) < 0);
      }
      checks++;
    }
  }
}
for (const control of controls) {
  control.value = '-7';
  assert.equal(context.updateQuantity(control.dataset.scaleFor), 1);
  control.value = '999';
  assert.equal(context.updateQuantity(control.dataset.scaleFor), control.dataset.scaleFor === 'TOPIX' ? 10 : 20);
  control.value = '1';
  control.change();
}
const result = {合格: true, 表示組合せ数: 200, 基準値の表示要素数: values.length, 表示数値照合数: checks,
  検査: 'TOPIX1〜10枚×NK2251〜20枚、金額・累計枚数・符号色・上限補正・変更イベント'};
const output = path.join(work, '表示倍率検査.json');
fs.writeFileSync(output, JSON.stringify(result, null, 2), 'utf8');
fs.mkdirSync(path.join(folder, '資料'), {recursive: true});
for (const name of ['check_report.js', '表示倍率検査.json']) fs.copyFileSync(path.join(work, name), path.join(folder, '資料', name));
console.log(JSON.stringify(result));
