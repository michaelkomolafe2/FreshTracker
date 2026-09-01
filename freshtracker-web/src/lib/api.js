const API_BASE = "/api"
const SERVER_ERROR_MESSAGE =
  "FreshTracker couldn't complete that request. Please try again."

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

function readCookie(name) {
  const match = document.cookie
    .split("; ")
    .find((cookie) => cookie.startsWith(`${encodeURIComponent(name)}=`))

  if (!match) {
    return ""
  }

  return decodeURIComponent(match.split("=").slice(1).join("="))
}

export async function requestJSON(path, options = {}) {
  const method = (options.method ?? "GET").toUpperCase()
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(method !== "GET" && method !== "HEAD"
        ? { "X-CSRF-Token": readCookie("freshtracker_csrf") }
        : {}),
      ...(options.headers ?? {}),
    },
    ...options,
  })

  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message =
      response.status >= 500
        ? SERVER_ERROR_MESSAGE
        : payload.error ?? "Something went wrong."
    throw new ApiError(message, response.status)
  }

  return payload
}
