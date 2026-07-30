import { lazy, Suspense, useEffect, useMemo, useState } from "react"
import {
  AlertCircle,
  ClipboardList,
  LogOut,
  RefreshCcw,
  Search,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { ItemForm } from "@/components/ItemForm"
import { ItemList } from "@/components/ItemList"
import { RecipeSuggestions } from "@/components/RecipeSuggestions"

const API_BASE = "/api"
const ALL_CATEGORIES = "all"
const UNCATEGORIZED = "uncategorized"
const WasteRatioChart = lazy(() =>
  import("@/components/WasteRatioChart").then((module) => ({
    default: module.WasteRatioChart,
  })),
)

const initialAuthValues = {
  email: "",
  password: "",
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

function mergeUpdatedItems(currentItems, changedItems) {
  const itemsById = new Map(currentItems.map((item) => [item.id, item]))

  changedItems.forEach((item) => itemsById.set(item.id, item))

  return [...itemsById.values()].sort(
    (left, right) =>
      left.expiry_date.localeCompare(right.expiry_date) || left.id - right.id,
  )
}

function inventoryCategoryValue(item) {
  const category = item.category?.trim()
  return category ? `category:${category}` : UNCATEGORIZED
}

function inventoryCategoryLabel(value) {
  return value === UNCATEGORIZED ? "Unsorted" : value.slice("category:".length)
}

function WasteRatioChartFallback() {
  return (
    <Card aria-label="Loading outcome chart">
      <CardHeader>
        <div className="h-3 w-32 animate-pulse rounded bg-harvest-oat" />
        <div className="h-8 w-64 max-w-full animate-pulse rounded bg-harvest-oat/70" />
      </CardHeader>
      <CardContent>
        <div className="h-64 animate-pulse rounded-md bg-harvest-oat/60" />
      </CardContent>
    </Card>
  )
}

function App() {
  const [user, setUser] = useState(null)
  const [items, setItems] = useState([])
  const [wasteCategories, setWasteCategories] = useState([])
  const [recipes, setRecipes] = useState([])
  const [recipeIngredients, setRecipeIngredients] = useState([])
  const [priorityRecipeIngredients, setPriorityRecipeIngredients] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [isWasteSummaryLoading, setIsWasteSummaryLoading] = useState(true)
  const [isRecipeLoading, setIsRecipeLoading] = useState(true)
  const [isAdding, setIsAdding] = useState(false)
  const [pendingItemActions, setPendingItemActions] = useState([])
  const [authMode, setAuthMode] = useState("login")
  const [authValues, setAuthValues] = useState(initialAuthValues)
  const [authBusy, setAuthBusy] = useState(false)
  const [error, setError] = useState("")
  const [recipeError, setRecipeError] = useState("")
  const [authError, setAuthError] = useState("")
  const [categoryFilter, setCategoryFilter] = useState(ALL_CATEGORIES)
  const [expirySort, setExpirySort] = useState("soonest")
  const [itemQuery, setItemQuery] = useState("")

  async function requestJSON(path, options = {}) {
    const method = (options.method ?? "GET").toUpperCase()
    const response = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(method !== "GET" && method !== "HEAD"
          ? {
              "X-CSRF-Token": readCookie("freshtracker_csrf"),
            }
          : {}),
        ...(options.headers ?? {}),
      },
      ...options,
    })

    const payload = await response.json().catch(() => ({}))
    if (!response.ok) {
      const error = new Error(payload.error ?? "Something went wrong.")
      error.status = response.status
      throw error
    }

    return payload
  }

  async function fetchSession() {
    const payload = await requestJSON("/auth/me", { method: "GET", headers: {} })
    setUser(payload.user)
    if (payload.session_expired) {
      setAuthMode("login")
      setAuthError("Your session expired. Please sign in again to keep using FreshTracker.")
    }
    return payload.user
  }

  async function fetchItems() {
    setIsLoading(true)
    setError("")

    try {
      const payload = await requestJSON("/items", { method: "GET", headers: {} })
      setItems(payload.items ?? [])
    } catch (requestError) {
      if (requestError.status === 401) {
        setUser(null)
        setAuthMode("login")
        setAuthError("Your session expired. Please sign in again to keep using FreshTracker.")
        setItems([])
      } else {
        setError(requestError.message)
      }
    } finally {
      setIsLoading(false)
    }
  }

  async function fetchWasteSummary() {
    setIsWasteSummaryLoading(true)

    try {
      const payload = await requestJSON("/waste-logs/category-summary", {
        method: "GET",
        headers: {},
      })
      setWasteCategories(payload.categories ?? [])
    } catch (requestError) {
      if (requestError.status === 401) {
        setUser(null)
        setAuthMode("login")
        setAuthError("Your session expired. Please sign in again to keep using FreshTracker.")
        setWasteCategories([])
      } else {
        setError(requestError.message)
      }
    } finally {
      setIsWasteSummaryLoading(false)
    }
  }

  async function fetchRecipeSuggestions() {
    setIsRecipeLoading(true)
    setRecipeError("")

    try {
      const payload = await requestJSON("/recipe-suggestions", {
        method: "GET",
        headers: {},
      })
      setRecipes(payload.recipes ?? [])
      setRecipeIngredients(payload.ingredients ?? [])
      setPriorityRecipeIngredients(payload.priority_ingredients ?? [])
    } catch (requestError) {
      if (requestError.status === 401) {
        setUser(null)
        setAuthMode("login")
        setAuthError(
          "Your session expired. Please sign in again to keep using FreshTracker.",
        )
        setRecipes([])
        setRecipeIngredients([])
        setPriorityRecipeIngredients([])
      } else {
        setRecipeError(requestError.message)
      }
    } finally {
      setIsRecipeLoading(false)
    }
  }

  async function fetchDashboard() {
    setError("")
    await Promise.all([
      fetchItems(),
      fetchWasteSummary(),
      fetchRecipeSuggestions(),
    ])
  }

  async function handleAuthSubmit(event) {
    event.preventDefault()
    setAuthBusy(true)
    setAuthError("")

    try {
      const path = authMode === "register" ? "/auth/register" : "/auth/login"
      const payload = await requestJSON(path, {
        method: "POST",
        body: JSON.stringify(authValues),
      })

      setUser(payload.user)
      setAuthValues(initialAuthValues)
      await fetchDashboard()
    } catch (requestError) {
      setAuthError(requestError.message)
    } finally {
      setAuthBusy(false)
    }
  }

  async function handleLogout() {
    setAuthBusy(true)
    setError("")

    try {
      await requestJSON("/auth/logout", { method: "POST", body: JSON.stringify({}) })
      setUser(null)
      setItems([])
      setWasteCategories([])
      setRecipes([])
      setRecipeIngredients([])
      setPriorityRecipeIngredients([])
      setAuthMode("login")
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setAuthBusy(false)
    }
  }

  async function addItem(formValues) {
    setIsAdding(true)
    setError("")

    try {
      const payload = await requestJSON("/items", {
        method: "POST",
        body: JSON.stringify(formValues),
      })

      // The API may have filled an existing stack instead of creating a new row.
      // Merge by database id so the client cannot render a duplicate stack.
      setItems((currentItems) =>
        mergeUpdatedItems(currentItems, payload.stacked_items ?? [payload.item]),
      )
      void fetchRecipeSuggestions()
    } catch (requestError) {
      setError(requestError.message)
      throw requestError
    } finally {
      setIsAdding(false)
    }
  }

  async function updateItemStatus(item, status) {
    setError("")
    setPendingItemActions((currentIds) => [...currentIds, item.id])
    setItems((currentItems) =>
      currentItems.filter((currentItem) => currentItem.id !== item.id),
    )

    try {
      await requestJSON(`/items/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      })
      await fetchWasteSummary()
      void fetchRecipeSuggestions()
    } catch (requestError) {
      setItems((currentItems) => mergeUpdatedItems(currentItems, [item]))
      setError(
        `Could not mark ${item.name} as ${status}. ${requestError.message}`,
      )
    } finally {
      setPendingItemActions((currentIds) =>
        currentIds.filter((itemId) => itemId !== item.id),
      )
    }
  }

  useEffect(() => {
    ;(async () => {
      try {
        const sessionUser = await fetchSession()
        if (sessionUser) {
          await fetchDashboard()
        }
      } catch {
        setUser(null)
      } finally {
        setIsLoading(false)
      }
    })()
  }, [])

  const categoryOptions = useMemo(
    () =>
      [...new Set(items.map(inventoryCategoryValue))].sort((left, right) => {
        if (left === UNCATEGORIZED) {
          return 1
        }

        if (right === UNCATEGORIZED) {
          return -1
        }

        return inventoryCategoryLabel(left).localeCompare(
          inventoryCategoryLabel(right),
        )
      }),
    [items],
  )

  useEffect(() => {
    if (
      categoryFilter !== ALL_CATEGORIES &&
      !categoryOptions.includes(categoryFilter)
    ) {
      setCategoryFilter(ALL_CATEGORIES)
    }
  }, [categoryFilter, categoryOptions])

  const filteredAndSortedItems = useMemo(() => {
    const normalizedQuery = itemQuery.trim().toLocaleLowerCase()
    const matchingItems = items.filter((item) => {
      const matchesCategory =
        categoryFilter === ALL_CATEGORIES ||
        inventoryCategoryValue(item) === categoryFilter
      const matchesQuery =
        normalizedQuery === "" ||
        String(item.name).toLocaleLowerCase().includes(normalizedQuery)

      return matchesCategory && matchesQuery
    })

    // Filtering is O(n) and sorting is O(n log n), which is fine for household
    // inventories; a commercial/shared fridge with thousands needs server-side queries.
    return [...matchingItems].sort((left, right) => {
      const leftExpiry = left.expiry_date || ""
      const rightExpiry = right.expiry_date || ""

      if (!leftExpiry || !rightExpiry) {
        if (!leftExpiry && !rightExpiry) {
          return left.id - right.id
        }

        return leftExpiry ? -1 : 1
      }

      const dateComparison = leftExpiry.localeCompare(rightExpiry)
      const directedComparison =
        expirySort === "soonest" ? dateComparison : -dateComparison

      return (
        directedComparison ||
        String(left.name).localeCompare(String(right.name)) ||
        left.id - right.id
      )
    })
  }, [items, categoryFilter, expirySort, itemQuery])

  const hasInventoryFilters =
    categoryFilter !== ALL_CATEGORIES || itemQuery.trim() !== ""
  const hasCustomInventoryView =
    hasInventoryFilters || expirySort !== "soonest"

  const itemCountLabel = useMemo(() => {
    if (filteredAndSortedItems.length !== items.length) {
      return `${filteredAndSortedItems.length} of ${items.length} items shown`
    }

    if (items.length === 1) {
      return "1 item being watched"
    }

    return `${items.length} items being watched`
  }, [filteredAndSortedItems.length, items.length])

  if (!user) {
    return (
      <main className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(130,170,125,0.22),_transparent_32%),linear-gradient(180deg,_#f7f2e7_0%,_#f3eadb_100%)] px-5 py-10 text-slate-900 sm:px-8">
        <div className="mx-auto grid min-h-[calc(100vh-5rem)] w-full max-w-6xl items-center gap-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(20rem,0.9fr)]">
          <section className="space-y-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white/70 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-600 backdrop-blur">
              <span className="h-2 w-2 rounded-full bg-emerald-700" />
              FreshTracker
            </div>
            <div className="max-w-2xl space-y-4">
              <h1 className="font-display text-5xl font-semibold leading-[0.95] sm:text-6xl lg:text-7xl">
                Track groceries without losing the thread.
              </h1>
              <p className="max-w-xl text-lg leading-8 text-slate-700">
                Create an account or sign in to manage your kitchen inventory.
                Your session is stored server-side and the list stays private to
                your browser.
              </p>
              {authError ? (
                <div
                  className="max-w-xl rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950"
                  role="alert"
                  aria-live="polite"
                >
                  {authError}
                </div>
              ) : null}
            </div>
          </section>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-[0_30px_90px_rgba(15,23,42,0.12)] sm:p-8">
            <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <h2 className="text-2xl font-semibold tracking-tight">
                  {authMode === "register" ? "Create account" : "Sign in"}
                </h2>
                <p className="mt-1 text-sm text-slate-600">
                  {authMode === "register"
                    ? "Register to start tracking what’s in the fridge."
                    : "Use your existing account to continue."}
                </p>
              </div>
              <div className="rounded-full bg-slate-100 p-2 text-slate-700">
                <ClipboardList className="h-5 w-5" />
              </div>
            </div>

            <div className="mb-4 grid grid-cols-2 rounded-full bg-slate-100 p-1">
              <button
                type="button"
                onClick={() => setAuthMode("login")}
                className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                  authMode === "login"
                    ? "bg-white text-slate-900 shadow-sm"
                    : "text-slate-600"
                }`}
              >
                Sign in
              </button>
              <button
                type="button"
                onClick={() => setAuthMode("register")}
                className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                  authMode === "register"
                    ? "bg-white text-slate-900 shadow-sm"
                    : "text-slate-600"
                }`}
              >
                Register
              </button>
            </div>

            {authError ? (
              <div
                className="mb-4 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950"
                role="alert"
                aria-live="polite"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <p>{authError}</p>
              </div>
            ) : null}

            <form className="space-y-4" onSubmit={handleAuthSubmit}>
              <div>
                <label htmlFor="email" className="mb-1 block text-sm font-medium text-slate-700">
                  Email address
                </label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  required
                  maxLength={254}
                  value={authValues.email}
                  onChange={(event) =>
                    setAuthValues((currentValues) => ({
                      ...currentValues,
                      email: event.target.value,
                    }))
                  }
                  placeholder="you@example.com"
                />
              </div>

              <div>
                <label
                  htmlFor="password"
                  className="mb-1 block text-sm font-medium text-slate-700"
                >
                  Password
                </label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete={authMode === "register" ? "new-password" : "current-password"}
                  required
                  minLength={12}
                  maxLength={128}
                  value={authValues.password}
                  onChange={(event) =>
                    setAuthValues((currentValues) => ({
                      ...currentValues,
                      password: event.target.value,
                    }))
                  }
                  placeholder="Use at least 12 characters"
                />
              </div>

              <Button type="submit" className="w-full" disabled={authBusy}>
                {authBusy ? "Working..." : authMode === "register" ? "Create account" : "Sign in"}
              </Button>
            </form>
          </section>
        </div>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto grid min-h-screen w-full max-w-[1440px] grid-cols-1 xl:grid-cols-[minmax(320px,380px)_minmax(0,1fr)] 2xl:grid-cols-[410px_minmax(0,1fr)]">
        <aside className="border-b border-border bg-harvest-paper px-5 py-6 sm:px-8 xl:sticky xl:top-0 xl:h-screen xl:overflow-y-auto xl:border-b-0 xl:border-r xl:px-10 xl:py-10">
          <div className="flex h-full flex-col justify-between gap-10">
            <div className="space-y-9 md:grid md:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)] md:items-start md:gap-8 md:space-y-0 xl:block xl:space-y-9">
              <div className="space-y-5">
                <div className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  <span className="h-2 w-2 rounded-full bg-primary" />
                  FreshTracker
                </div>

                <div className="space-y-4">
                  <h1 className="max-w-[10ch] font-display text-5xl font-semibold leading-[0.95] text-foreground sm:text-6xl lg:text-7xl">
                    Keep food moving.
                  </h1>
                  <p className="max-w-sm text-base leading-7 text-muted-foreground">
                    Add what came home from the shop. FreshTracker will sort it
                    into a category when you leave that part blank.
                  </p>
                </div>
              </div>

              <div className="space-y-4">
                <div className="rounded-2xl border border-border bg-card px-4 py-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                    Signed in as
                  </p>
                  <p className="mt-2 break-words text-sm font-semibold text-foreground">
                    {user.email}
                  </p>
                </div>
                <ItemForm onAddItem={addItem} isAdding={isAdding} />
                <Button
                  type="button"
                  variant="secondary"
                  className="w-full justify-start"
                  onClick={handleLogout}
                  disabled={authBusy}
                >
                  <LogOut className="h-4 w-4" />
                  {authBusy ? "Signing out..." : "Log out"}
                </Button>
              </div>
            </div>

            <div className="hidden max-w-xs border-t border-border pt-5 text-sm leading-6 text-muted-foreground xl:block">
              <p>
                Today&apos;s rhythm: log it while unpacking, check it before
                dinner, waste less without turning the kitchen into admin.
              </p>
            </div>
          </div>
        </aside>

        <section className="min-w-0 px-5 py-7 sm:px-8 lg:px-12 lg:py-10">
          <div className="mx-auto max-w-5xl space-y-8">
            <header className="flex flex-wrap items-end justify-between gap-5 border-b border-border pb-7">
              <div className="min-w-0 flex-1 space-y-3">
                <p className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  Kitchen inventory
                </p>
                <div className="flex flex-wrap items-end gap-4">
                  <h2 className="font-display text-4xl font-semibold leading-none text-foreground sm:text-5xl">
                    The current shelf
                  </h2>
                  <ClipboardList className="mb-1 hidden h-7 w-7 text-primary sm:block" />
                </div>
              </div>

              <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-3 sm:w-auto">
                <p className="flex min-h-11 items-center rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-muted-foreground sm:rounded-full">
                  {itemCountLabel}
                </p>
                <Button
                  type="button"
                  variant="secondary"
                  className="w-full justify-start sm:w-auto"
                  onClick={fetchDashboard}
                  disabled={
                    isLoading ||
                    isWasteSummaryLoading ||
                    isRecipeLoading ||
                    pendingItemActions.length > 0
                  }
                >
                  <RefreshCcw className="h-4 w-4" />
                  Refresh
                </Button>
              </div>
            </header>

            {error ? (
              <div className="flex items-start gap-3 rounded-md border border-destructive/35 bg-harvest-paper px-4 py-4 text-sm text-destructive">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <p className="font-semibold">Something needs attention.</p>
                  <p className="mt-1 text-destructive/85">{error}</p>
                </div>
              </div>
            ) : null}

            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,22rem),1fr))] items-start gap-6">
              <Suspense fallback={<WasteRatioChartFallback />}>
                <WasteRatioChart
                  categories={wasteCategories}
                  isLoading={isWasteSummaryLoading}
                />
              </Suspense>
              <RecipeSuggestions
                recipes={recipes}
                ingredients={recipeIngredients}
                priorityIngredients={priorityRecipeIngredients}
                isLoading={isRecipeLoading}
                error={recipeError}
                onRefresh={fetchRecipeSuggestions}
              />
            </div>

            <Card className="bg-harvest-paper">
              <CardContent className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))] items-end gap-4 px-4 pb-4 pt-4">
                <div className="min-w-0 space-y-2">
                  <label
                    htmlFor="inventory-search"
                    className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground"
                  >
                    Search items
                  </label>
                  <div className="relative">
                    <Search
                      className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-primary"
                      aria-hidden="true"
                    />
                    <Input
                      id="inventory-search"
                      type="search"
                      value={itemQuery}
                      onChange={(event) => setItemQuery(event.target.value)}
                      placeholder="Search by item name"
                      className="bg-card pl-10"
                    />
                  </div>
                </div>

                <div className="min-w-0 space-y-2">
                  <label
                    htmlFor="inventory-category"
                    className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground"
                  >
                    Category
                  </label>
                  <Select value={categoryFilter} onValueChange={setCategoryFilter}>
                    <SelectTrigger id="inventory-category" className="bg-card">
                      <SelectValue placeholder="All categories" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL_CATEGORIES}>All categories</SelectItem>
                      {categoryOptions.map((category) => (
                        <SelectItem key={category} value={category}>
                          {inventoryCategoryLabel(category)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="min-w-0 space-y-2">
                  <label
                    htmlFor="inventory-sort"
                    className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground"
                  >
                    Expiry date
                  </label>
                  <Select value={expirySort} onValueChange={setExpirySort}>
                    <SelectTrigger id="inventory-sort" className="bg-card">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="soonest">Soonest first</SelectItem>
                      <SelectItem value="latest">Latest first</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Button
                  type="button"
                  variant="secondary"
                  className="w-full"
                  onClick={() => {
                    setCategoryFilter(ALL_CATEGORIES)
                    setExpirySort("soonest")
                    setItemQuery("")
                  }}
                  disabled={!hasCustomInventoryView}
                >
                  Reset
                </Button>
              </CardContent>
            </Card>

            <ItemList
              items={filteredAndSortedItems}
              isLoading={isLoading}
              onUpdateStatus={updateItemStatus}
              emptyState={hasInventoryFilters ? "filtered" : "inventory"}
            />
          </div>
        </section>
      </div>
    </main>
  )
}

export default App
