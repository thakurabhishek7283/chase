/**
 * `detail` is usually a plain string, but the LaTeX validate/parse/compile
 * path (upload, review creation, preview) sends `{code, message}` instead —
 * `code` is `invalid_latex` or `unsupported_latex`, so a caller could branch
 * on *why* instead of only displaying the sentence. Nothing reads `code` yet;
 * this just keeps the message extraction from silently falling back to the
 * generic string when `detail` stopped being one.
 */
function messageFrom(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail;
  const message = (detail as { message?: unknown })?.message;
  return typeof message === 'string' ? message : undefined;
}

/**
 * Pull the API's `detail` out of an error, including from a blob response.
 *
 * The PDF endpoints are requested with `responseType: 'blob'`, and Angular
 * applies that to the *error* body too — so a 409 arrives as a Blob and the
 * usual `err.error.detail` is `undefined`. Without this, every failed preview
 * reads "Something went wrong" instead of the message the API took care to
 * write, which on the stale-edit path is the one that tells the user what to do.
 */
export async function detailFrom(error: unknown, fallback: string): Promise<string> {
  const body = (error as { error?: unknown })?.error;

  if (body instanceof Blob) {
    try {
      const parsed = JSON.parse(await body.text());
      return messageFrom(parsed?.detail) ?? fallback;
    } catch {
      return fallback;
    }
  }
  const detail = (body as { detail?: unknown })?.detail;
  return messageFrom(detail) ?? fallback;
}

/** HTTP status of an error response, or 0 when it never reached the server. */
export function statusOf(error: unknown): number {
  return (error as { status?: number })?.status ?? 0;
}
