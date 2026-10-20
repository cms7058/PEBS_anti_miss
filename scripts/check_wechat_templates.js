// Run with the Node bundled in WeChat DevTools, or another ABI-compatible Node.
// Optional argv[2]: fullcompiler/trans/wcc/lib in a different DevTools installation.
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '../wechat_app');
const compilerRoot = process.argv[2] || '/Applications/wechatwebdevtools.app/Contents/Resources/package.nw/js/common/miniprogram-builder/modules/fullcompiler/trans/wcc/lib';
async function main() {
  const pages = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8')).pages;
  const wcc = require(path.join(compilerRoot, 'wcc'));
  const wcsc = require(path.join(compilerRoot, 'wcsc'));
  const templates = await wcc({ cwd: root, files: pages.map(page => page + '.wxml') });
  const styles = await wcsc({ cwd: root, files: ['app.wxss'], pageCount: 0 });
  if (!templates || !styles) throw new Error('Compiler returned empty output');
  console.log(`PASS: official WeChat compiler, ${pages.length} WXML pages and shared WXSS`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
