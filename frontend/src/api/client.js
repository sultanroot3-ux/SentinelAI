const TOKEN_KEY = 'sentinel_token';
const REFRESH_KEY = 'sentinel_refresh_token';

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

export const getRefreshToken = () => localStorage.getItem(REFRESH_KEY);
export const setRefreshToken = (t) => localStorage.setItem(REFRESH_KEY, t);
export const clearRefreshToken = () => localStorage.removeItem(REFRESH_KEY);

export const setTokens = ({ access_token, refresh_token }) => {
  setToken(access_token);
  setRefreshToken(refresh_token);
};

export const clearTokens = () => {
  clearToken();
  clearRefreshToken();
};

/* Endpoints whose own 401s must never trigger a token refresh. */
const NO_REFRESH_PATHS = ['/api/auth/login', '/api/auth/refresh'];

/* Shared in-flight refresh so concurrent 401s don't stampede the endpoint. */
let refreshPromise = null;

function refreshTokens() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refresh_token = getRefreshToken();
      if (!refresh_token) throw new Error('No refresh token');
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token }),
      });
      if (!res.ok) throw new Error(`Refresh failed (${res.status})`);
      const data = await res.json();
      setTokens(data); // rotation is single-use: keep BOTH new tokens
      return data;
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

function buildQuery(params) {
  if (!params) return '';
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== ''
  );
  if (!entries.length) return '';
  const qs = new URLSearchParams();
  entries.forEach(([k, v]) => qs.append(k, String(v)));
  return `?${qs.toString()}`;
}

async function request(path, { method = 'GET', body, params, raw = false } = {}) {
  const doFetch = () => {
    const headers = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    let payload;
    if (body instanceof FormData) {
      payload = body; // browser sets multipart boundary
    } else if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      payload = JSON.stringify(body);
    }

    return fetch(path + buildQuery(params), { method, headers, body: payload });
  };

  let res = await doFetch();

  if (res.status === 401 && !NO_REFRESH_PATHS.includes(path)) {
    try {
      await refreshTokens();
    } catch {
      clearTokens();
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login');
      }
      throw new Error('Session expired — please sign in again');
    }
    res = await doFetch(); // retry the original request once with fresh tokens
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data && data.detail) {
        detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      /* non-JSON error body */
    }
    const err = new Error(detail);
    err.status = res.status;
    const retryAfter = res.headers.get('Retry-After');
    if (retryAfter) err.retryAfter = retryAfter;
    throw err;
  }

  if (raw) return res;
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export const api = {
  get: (path, params) => request(path, { params }),
  post: (path, body) => request(path, { method: 'POST', body }),
  put: (path, body) => request(path, { method: 'PUT', body }),
  del: (path) => request(path, { method: 'DELETE' }),
  upload: (path, file, field = 'file') => {
    const fd = new FormData();
    fd.append(field, file);
    return request(path, { method: 'POST', body: fd });
  },
  raw: (path, params) => request(path, { params, raw: true }),
};

/** Tolerates both bare-array and {items,total,page} paginated responses. */
export function asPage(data) {
  if (Array.isArray(data)) return { items: data, total: data.length, page: 1 };
  return {
    items: data?.items ?? [],
    total: data?.total ?? (data?.items?.length || 0),
    page: data?.page ?? 1,
  };
}
