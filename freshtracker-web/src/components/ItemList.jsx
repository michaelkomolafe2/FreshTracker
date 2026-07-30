import { CalendarDays, CircleCheck, PackageOpen, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

function formatDate(value) {
  if (!value) {
    return "No date"
  }

  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(`${value}T00:00:00`))
}

function expiryPresentation(expiryDate) {
  const today = new Date()
  const todayAtMidnight = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const target = new Date(`${expiryDate}T00:00:00`)
  const daysUntilExpiry = Math.ceil((target - todayAtMidnight) / 86_400_000)

  if (daysUntilExpiry <= 3) {
    return { label: "Use soon", className: "border-red-300 bg-red-50 text-red-800" }
  }

  if (daysUntilExpiry <= 7) {
    return { label: "Plan this week", className: "border-amber-300 bg-amber-50 text-amber-900" }
  }

  return { label: "Fresh", className: "border-emerald-300 bg-emerald-50 text-emerald-900" }
}

export function ItemList({ items, isLoading, onUpdateStatus }) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className="h-20 animate-pulse rounded-md border border-border bg-card"
          />
        ))}
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="flex min-h-[360px] items-center justify-center rounded-md border border-dashed border-border bg-harvest-paper px-6 py-12">
        <div className="max-w-md text-left">
          <div className="mb-6 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <PackageOpen className="h-6 w-6" />
          </div>
          <h3 className="font-display text-3xl font-semibold text-foreground">
            The shelves are quiet.
          </h3>
          <p className="mt-3 text-base leading-7 text-muted-foreground">
            Add the first thing you unpacked. Milk, cilantro, yesterday&apos;s
            very optimistic kale. We&apos;ll keep it tidy from there.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {items.map((item, index) => (
        <article
          key={item.id}
          className={cn(
            "grid gap-4 rounded-md border border-border bg-card px-4 py-4 transition-colors duration-200 ease-out hover:border-primary/40 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:px-5",
            index === 0 && "border-primary/30",
          )}
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate font-display text-2xl font-semibold leading-tight text-foreground">
                {item.name}
              </h3>
              <span className="rounded-full border border-border bg-secondary px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.12em] text-secondary-foreground">
                {item.category || "Unsorted"}
              </span>
              {(() => {
                const expiry = expiryPresentation(item.expiry_date)
                return (
                  <span className={cn("rounded-full border px-2.5 py-1 text-xs font-semibold", expiry.className)}>
                    {expiry.label}
                  </span>
                )
              })()}
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              {item.quantity} {item.unit}
            </p>
          </div>

          <div className="space-y-3 sm:text-right">
            <div className="flex items-center gap-2 text-sm text-muted-foreground sm:justify-end">
              <CalendarDays className="h-4 w-4 text-primary" />
              <span>{formatDate(item.expiry_date)}</span>
            </div>
            <div className="flex flex-wrap gap-2 sm:justify-end">
              <Button
                type="button"
                size="sm"
                onClick={() => onUpdateStatus(item, "used")}
                aria-label={`Mark ${item.name} as used`}
              >
                <CircleCheck className="h-4 w-4" />
                Used
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="border-harvest-clay/40 text-harvest-clay hover:bg-harvest-clay hover:text-harvest-paper"
                onClick={() => onUpdateStatus(item, "wasted")}
                aria-label={`Mark ${item.name} as wasted`}
              >
                <Trash2 className="h-4 w-4" />
                Wasted
              </Button>
            </div>
          </div>
        </article>
      ))}
    </div>
  )
}
