import { useEffect, useMemo, useState } from "react"
import { AlertCircle, ClipboardList, RefreshCcw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { ItemForm } from "@/components/ItemForm"
import { ItemList } from "@/components/ItemList"

const API_BASE = "/api"

function App() {
  const [items, setItems] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [isAdding, setIsAdding] = useState(false)
  const [error, setError] = useState("")

  async function fetchItems() {
    setIsLoading(true)
    setError("")

    try {
      const response = await fetch(`${API_BASE}/items`)
      if (!response.ok) {
        throw new Error("FreshTracker could not load your grocery list.")
      }

      const payload = await response.json()
      setItems(payload.items ?? [])
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setIsLoading(false)
    }
  }

  async function addItem(formValues) {
    setIsAdding(true)
    setError("")

    try {
      const response = await fetch(`${API_BASE}/items`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(formValues),
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload.error ?? "That item could not be added.")
      }

      const payload = await response.json()
      setItems((currentItems) => [payload.item, ...currentItems])
    } catch (requestError) {
      setError(requestError.message)
      throw requestError
    } finally {
      setIsAdding(false)
    }
  }

  useEffect(() => {
    fetchItems()
  }, [])

  const itemCountLabel = useMemo(() => {
    if (items.length === 1) {
      return "1 item being watched"
    }

    return `${items.length} items being watched`
  }, [items.length])

  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto grid min-h-screen w-full max-w-[1440px] grid-cols-1 lg:grid-cols-[410px_minmax(0,1fr)]">
        <aside className="border-b border-border bg-harvest-paper px-5 py-6 sm:px-8 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r lg:px-10 lg:py-10">
          <div className="flex h-full flex-col justify-between gap-10">
            <div className="space-y-9">
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

              <ItemForm onAddItem={addItem} isAdding={isAdding} />
            </div>

            <div className="hidden max-w-xs border-t border-border pt-5 text-sm leading-6 text-muted-foreground lg:block">
              <p>
                Today&apos;s rhythm: log it while unpacking, check it before
                dinner, waste less without turning the kitchen into admin.
              </p>
            </div>
          </div>
        </aside>

        <section className="px-5 py-7 sm:px-8 lg:px-12 lg:py-10">
          <div className="mx-auto max-w-5xl space-y-8">
            <header className="flex flex-col gap-5 border-b border-border pb-7 md:flex-row md:items-end md:justify-between">
              <div className="space-y-3">
                <p className="text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  Kitchen inventory
                </p>
                <div className="flex items-end gap-4">
                  <h2 className="font-display text-4xl font-semibold leading-none text-foreground sm:text-5xl">
                    The current shelf
                  </h2>
                  <ClipboardList className="mb-1 hidden h-7 w-7 text-primary sm:block" />
                </div>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <p className="rounded-full border border-border bg-card px-4 py-2 text-sm font-medium text-muted-foreground">
                  {itemCountLabel}
                </p>
                <Button
                  type="button"
                  variant="secondary"
                  className="justify-start"
                  onClick={fetchItems}
                  disabled={isLoading}
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

            <ItemList items={items} isLoading={isLoading} />
          </div>
        </section>
      </div>
    </main>
  )
}

export default App
