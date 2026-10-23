const config = require('../config');
let base = config.server;
let token = '';
let account = '';
let generation = 0;
class ApiError extends Error {
  constructor(message, status, kind = 'http') { super(message); this.status = status; this.kind = kind; }
}
function session() { return { loggedIn: !!token, name: account, server: base }; }
function validateServer(value) {
  const address = value.trim().replace(/\/+$/, '');
  if (!/^https:\/\/[a-zA-Z0-9.-]+(?::[0-9]{1,5})?$/.test(address)) {
    let testing = false;
    try { testing = ['develop', 'trial'].includes(wx.getAccountInfoSync().miniProgram.envVersion); } catch (_) {}
    if (!(testing && address === 'http://121.4.117.45:8087')) {
      throw new Error('请填写 HTTPS 服务域名；当前 HTTP 地址仅限开发版或体验版调试');
    }
  }
  return address;
}
function clear() { token = ''; account = ''; generation++; }
function configure(value) {
  const next = validateServer(value);
  if (next !== base) { clear(); base = next; }
}
function request(path, method = 'GET', data, authenticated = true) {
  const current = generation;
  let server;
  try { server = validateServer(base); } catch (error) { return Promise.reject(error); }
  return new Promise((resolve, reject) => {
    const header = { 'Content-Type': 'application/json' };
    if (authenticated && token) header.Authorization = `Bearer ${token}`;
    wx.request({ url: server + path, method, data, header, timeout: 20000,
      success(response) {
        if (current !== generation) return reject(new ApiError('登录状态已改变，请重试', 0));
        const body = response.data;
        if (response.statusCode < 200 || response.statusCode >= 300) {
          if (authenticated && response.statusCode === 401) clear();
          return reject(new ApiError(body && body.error || `请求失败（${response.statusCode}）`, response.statusCode));
        }
        if (!body || typeof body !== 'object') return reject(new ApiError('后台响应格式无效', 0));
        resolve(body);
      },
      fail(error) {
        if(current!==generation)return reject(new ApiError('登录状态已改变，请重试',0));
        const message=error&&error.errMsg||'';
        if(/timeout/i.test(message))return reject(new ApiError('后台连接超时，尚未确认定位结果，请稍后重试',0,'network'));
        if(/domain|url not|ssl|certificate/i.test(message))return reject(new ApiError('微信拦截了服务地址或证书。HTTP 体验版请开启调试并重新进入；HTTPS 请检查合法域名和证书',0,'network'));
        reject(new ApiError('连接后台失败，请检查手机网络和后台服务；此提示不代表老人手机定位超时',0,'network'));
      }
    });
  });
}
async function login(name, password, register) {
  clear();
  const result = await request(register ? '/auth/register' : '/auth/login', 'POST', { name: name.trim(), password }, false);
  if (typeof result.token !== 'string' || !result.token) throw new Error('后台未返回有效登录信息');
  token = result.token; account = result.name;
}
async function logout() {
  try { await request('/auth/logout', 'POST', {}); } finally { clear(); }
}
function elderPath(id, suffix = '') { return `/elders/${encodeURIComponent(id)}${suffix}`; }
module.exports = { ApiError, session, configure, clear, request, login, logout, elderPath, validateServer };
