const TOKEN_KEY = 'sentinel_token';

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

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

  const res = await fetch(path + buildQuery(params), { method, headers, body: payload });

  if (res.status === 401) {
    clearToken();
    if (!window.location.pathname.startsWith('/login')) {
      window.location.assign('/login');
    }
    throw new Error('Session expired — please sign in again');
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
    throw new Error(detail);
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
