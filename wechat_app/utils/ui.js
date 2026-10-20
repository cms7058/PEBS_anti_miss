const api = require('./api');
function requireLogin() {
  if (api.session().loggedIn) return true;
  wx.reLaunch({ url: '/pages/login/login' }); return false;
}
async function run(page, action) {
  if (page.data.busy) return;
  page.setData({ busy: true, error: '' });
  try { await action(); } catch (error) {
    page.setData({ error: error.message || '操作失败，请重试' });
    if (error.status === 401) { wx.reLaunch({ url: '/pages/login/login' }); }
  } finally { page.setData({ busy: false }); }
}
function confirm(content) {
  return new Promise(resolve => wx.showModal({ title: '操作确认', content, success: result => resolve(result.confirm), fail: () => resolve(false) }));
}
function copy(value) { wx.setClipboardData({ data: value }); }
module.exports = { requireLogin, run, confirm, copy };
