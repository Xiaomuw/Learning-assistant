/**
 * request.js — 小程序统一请求工具
 *
 * 鉴权说明：
 *   后端通过 HttpOnly Cookie（la_access_token / la_refresh_token）鉴权。
 *   微信小程序 wx.request 不会自动处理 Set-Cookie，因此：
 *   1. 登录/注册后，从响应 header 的 Set-Cookie 中手动提取 token 值并存入 Storage。
 *   2. 后续请求在 header 中手动携带 Cookie: la_access_token=xxx（FastAPI Cookie() 依赖
 *      从 HTTP Cookie 请求头解析，与浏览器行为一致，因此能正常被识别）。
 *   3. 当请求返回 401 时，自动尝试调用 POST /auth/refresh 刷新 token，成功后重试。
 */

const getApiBase = () => {
  try {
    const app = getApp();
    return (app && app.globalData && app.globalData.apiBase) || 'http://localhost:8000/api';
  } catch (e) {
    return 'http://localhost:8000/api';
  }
};

/**
 * 从 Set-Cookie 响应头中提取指定 cookie 的值
 * wx.request 的 success 回调 header 里 Set-Cookie 可能是字符串或数组
 */
export function extractCookieFromHeader(header, cookieName) {
  if (!header) return null;

  // 获取 Set-Cookie（大小写不敏感）
  let setCookieRaw = null;
  for (const key of Object.keys(header)) {
    if (key.toLowerCase() === 'set-cookie') {
      setCookieRaw = header[key];
      break;
    }
  }
  if (!setCookieRaw) return null;

  // 可能是字符串（单个）或数组（多个）
  const setCookieList = Array.isArray(setCookieRaw) ? setCookieRaw : [setCookieRaw];

  for (const cookieStr of setCookieList) {
    // 格式: "la_access_token=xxx; Path=/; HttpOnly; ..."
    const parts = cookieStr.split(';');
    for (const part of parts) {
      const [rawKey, ...rawValParts] = part.trim().split('=');
      if (rawKey.trim() === cookieName) {
        return rawValParts.join('=').trim();
      }
    }
  }
  return null;
}

/**
 * 在登录/注册成功后，解析并持久化两个 token
 */
export function persistAuthTokensFromHeader(header) {
  const accessToken = extractCookieFromHeader(header, 'la_access_token');
  const refreshToken = extractCookieFromHeader(header, 'la_refresh_token');
  if (accessToken) {
    wx.setStorageSync('la_access_token', accessToken);
  }
  if (refreshToken) {
    wx.setStorageSync('la_refresh_token', refreshToken);
  }
  return { accessToken, refreshToken };
}

/**
 * 构建带鉴权 Cookie 的请求头
 */
function buildAuthHeader(extraHeader = {}) {
  const header = {
    'Content-Type': 'application/json',
    ...extraHeader
  };
  const token = wx.getStorageSync('la_access_token');
  if (token) {
    // 后端 FastAPI 通过 Cookie() 依赖解析此 header
    header['Cookie'] = `la_access_token=${token}`;
  }
  return header;
}

let _isRefreshing = false;
let _refreshQueue = [];

/**
 * 尝试用 refresh_token 刷新 access_token
 * 返回 true 表示刷新成功
 */
function tryRefreshToken() {
  if (_isRefreshing) {
    // 已经在刷新中，返回同一个 Promise
    return new Promise((resolve) => {
      _refreshQueue.push(resolve);
    });
  }

  _isRefreshing = true;
  const refreshToken = wx.getStorageSync('la_refresh_token');

  return new Promise((resolve) => {
    wx.request({
      url: `${getApiBase()}/auth/refresh`,
      method: 'POST',
      header: {
        'Content-Type': 'application/json',
        'Cookie': refreshToken ? `la_refresh_token=${refreshToken}` : ''
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          persistAuthTokensFromHeader(res.header);
          _refreshQueue.forEach(cb => cb(true));
          resolve(true);
        } else {
          _refreshQueue.forEach(cb => cb(false));
          resolve(false);
        }
      },
      fail() {
        _refreshQueue.forEach(cb => cb(false));
        resolve(false);
      },
      complete() {
        _isRefreshing = false;
        _refreshQueue = [];
      }
    });
  });
}

/**
 * 核心请求函数，支持 401 自动 token 刷新重试
 */
export const request = (url, options = {}, _isRetry = false) => {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getApiBase()}${url}`,
      method: options.method || 'GET',
      data: options.data,
      header: buildAuthHeader(options.header),
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          // 顺手更新 token（如果响应包含新 token）
          persistAuthTokensFromHeader(res.header);
          resolve(res.data);
        } else if (res.statusCode === 401 && !_isRetry) {
          // 尝试刷新 token 后重试一次
          tryRefreshToken().then((ok) => {
            if (ok) {
              request(url, options, true).then(resolve).catch(reject);
            } else {
              // 刷新失败，清除 token，跳转登录
              wx.removeStorageSync('la_access_token');
              wx.removeStorageSync('la_refresh_token');
              wx.reLaunch({ url: '/pages/login/login' });
              reject(new Error('登录已过期，请重新登录'));
            }
          });
        } else {
          const errMsg =
            (res.data && (res.data.detail || res.data.error || res.data.message)) ||
            `请求失败 (${res.statusCode})`;
          reject(new Error(errMsg));
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || '网络请求失败'));
      }
    });
  });
};

/**
 * SSE 流式请求 — 使用 enableChunked: true
 * 返回 wx.request 的 requestTask，调用方通过 requestTask.onChunkReceived 监听数据块
 */
export const requestChunked = (url, options = {}) => {
  return wx.request({
    url: `${getApiBase()}${url}`,
    method: options.method || 'POST',
    data: options.data,
    header: buildAuthHeader(options.header),
    enableChunked: true
  });
};
