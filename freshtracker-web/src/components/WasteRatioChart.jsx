import { useMemo } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

function OutcomeTooltip({ active, label, payload }) {
  if (!active || !payload?.length) {
    return null
  }

  const category = payload[0].payload

  return (
    <div className="rounded-md border border-border bg-harvest-paper px-3 py-2 shadow-panel">
      <p className="font-semibold text-harvest-ink">{label}</p>
      <p className="mt-1 text-sm text-harvest-forest">
        Used: {category.used} ({Math.round(category.usedRatio)}%)
      </p>
      <p className="text-sm text-harvest-clay">
        Wasted: {category.wasted} ({Math.round(category.wastedRatio)}%)
      </p>
    </div>
  )
}

export function WasteRatioChart({ categories, isLoading }) {
  const chartData = useMemo(
    () =>
      categories
        .map(({ category, used = 0, wasted = 0 }) => {
          const total = used + wasted

          return {
            category: category || "Unsorted",
            total,
            used,
            wasted,
            usedRatio: total === 0 ? 0 : (used / total) * 100,
            wastedRatio: total === 0 ? 0 : (wasted / total) * 100,
          }
        })
        .sort(
          (left, right) =>
            right.total - left.total ||
            left.category.localeCompare(right.category),
        ),
    [categories],
  )

  const chartHeight = Math.max(260, chartData.length * 58)

  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Logged outcomes
          </p>
          <CardTitle className="mt-2">Used vs wasted by category</CardTitle>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Each bar shows the share of completed item logs, not food quantity
            or weight.
          </p>
        </div>
        <div className="flex items-center gap-4 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          <span className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm bg-harvest-forest" />
            Used
          </span>
          <span className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm bg-harvest-clay" />
            Wasted
          </span>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div
            className="h-64 animate-pulse rounded-md bg-harvest-oat/60"
            aria-label="Loading outcome chart"
          />
        ) : chartData.length === 0 ? (
          <div className="flex min-h-52 items-center rounded-md border border-dashed border-border bg-harvest-paper px-5 py-8">
            <div>
              <p className="font-display text-xl font-semibold text-harvest-ink">
                No outcomes logged yet.
              </p>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Mark an inventory item as used or wasted to begin the comparison.
              </p>
            </div>
          </div>
        ) : (
          <div
            className="w-full"
            style={{ height: chartHeight }}
            aria-label="Used versus wasted outcome ratio by category"
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 8, right: 8, bottom: 8, left: 8 }}
                accessibilityLayer
              >
                <CartesianGrid
                  horizontal={false}
                  stroke="hsl(var(--border))"
                  strokeDasharray="3 3"
                />
                <XAxis
                  type="number"
                  domain={[0, 100]}
                  ticks={[0, 25, 50, 75, 100]}
                  tickFormatter={(value) => `${value}%`}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
                />
                <YAxis
                  type="category"
                  dataKey="category"
                  width={84}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "hsl(var(--foreground))", fontSize: 12 }}
                />
                <Tooltip
                  content={<OutcomeTooltip />}
                  cursor={{ fill: "hsl(var(--muted))", fillOpacity: 0.45 }}
                />
                <Bar
                  dataKey="usedRatio"
                  name="Used"
                  stackId="outcomes"
                  className="fill-harvest-forest"
                  radius={[4, 0, 0, 4]}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="wastedRatio"
                  name="Wasted"
                  stackId="outcomes"
                  className="fill-harvest-clay"
                  radius={[0, 4, 4, 0]}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
