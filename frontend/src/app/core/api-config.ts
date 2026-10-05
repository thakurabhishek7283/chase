/**
 * Relative on purpose: the API is always reached on the page's own origin.
 *
 * - `npm start` proxies `/api` to the backend on :8000 (see `proxy.conf.json`).
 * - The Docker image's nginx proxies `/api` to the backend container.
 *
 * Same-origin means no CORS preflight on every request, and one build runs
 * unchanged on localhost, a LAN address, or a real domain.
 */
export const API_BASE_URL = '/api/v1';
