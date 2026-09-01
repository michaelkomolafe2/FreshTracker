import http from "k6/http"
import { check, fail } from "k6"

const BASE_URL = (__ENV.BASE_URL || "http://localhost:5000").replace(/\/$/, "")
const ORIGIN = __ENV.ORIGIN || "http://localhost:5173"
const BENCHMARK_EMAIL = __ENV.BENCHMARK_EMAIL || "benchmark@example.com"
const BENCHMARK_PASSWORD =
  __ENV.BENCHMARK_PASSWORD || "Benchmark-Password-1234"

export const options = {
  vus: 50,
  duration: "30s",
}

export function setup() {
  const response = http.post(
    `${BASE_URL}/auth/login`,
    JSON.stringify({
      email: BENCHMARK_EMAIL,
      password: BENCHMARK_PASSWORD,
    }),
    { headers: { "Content-Type": "application/json", Origin: ORIGIN } },
  )

  if (
    !check(response, {
      "benchmark login succeeded": (result) => result.status === 200,
    })
  ) {
    fail(`Benchmark login failed with HTTP ${response.status}`)
  }

  const sessionCookie = response.cookies.freshtracker_session?.[0]?.value
  if (!sessionCookie) {
    fail("Benchmark login did not return freshtracker_session")
  }

  return { sessionCookie }
}

export default function ({ sessionCookie }) {
  const response = http.get(`${BASE_URL}/items`, {
    cookies: { freshtracker_session: sessionCookie },
    tags: { endpoint: "GET /items" },
  })

  check(response, {
    "GET /items returns 200": (result) => result.status === 200,
    "GET /items returns JSON": (result) =>
      result.headers["Content-Type"]?.includes("application/json") ?? false,
  })
}
