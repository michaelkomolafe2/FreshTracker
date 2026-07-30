import { ChefHat, RefreshCcw, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function RecipeSuggestions({
  recipes,
  ingredients,
  priorityIngredients,
  isLoading,
  error,
  onRefresh,
}) {
  return (
    <Card className="h-full border-harvest-forest/20 bg-harvest-paper shadow-panel">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-harvest-forest">
            <Sparkles className="h-4 w-4" />
            Waste-less recipes
          </p>
          <CardTitle className="mt-2">Cook what needs you first</CardTitle>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Ideas from your current shelf, led by food expiring within seven
            days.
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={onRefresh}
          disabled={isLoading}
          aria-label="Refresh recipe suggestions"
        >
          <RefreshCcw className="h-4 w-4" />
          {isLoading ? "Finding..." : "Refresh ideas"}
        </Button>
      </CardHeader>

      <CardContent className="space-y-5">
        {priorityIngredients.length > 0 ? (
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Use first
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {priorityIngredients.map((ingredient) => (
                <span
                  key={ingredient}
                  className="rounded-full border border-harvest-clay/35 bg-harvest-oat px-2.5 py-1 text-xs font-semibold text-harvest-ink"
                >
                  {ingredient}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {isLoading ? (
          <div className="space-y-3" aria-label="Loading recipe suggestions">
            {Array.from({ length: 3 }).map((_, index) => (
              <div
                key={index}
                className="h-20 animate-pulse rounded-md border border-border bg-card"
              />
            ))}
          </div>
        ) : error ? (
          <div
            className="rounded-md border border-harvest-clay/35 bg-card px-4 py-4 text-sm text-harvest-clay"
            role="alert"
          >
            {error}
          </div>
        ) : ingredients.length === 0 ? (
          <div className="rounded-md border border-dashed border-border bg-card px-4 py-6">
            <ChefHat className="h-6 w-6 text-harvest-forest" />
            <p className="mt-3 font-display text-xl font-semibold text-harvest-ink">
              Your recipe queue is empty.
            </p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Add a non-expired item and FreshTracker will build ideas from
              what is available.
            </p>
          </div>
        ) : recipes.length === 0 ? (
          <div className="rounded-md border border-dashed border-border bg-card px-4 py-6">
            <p className="font-display text-xl font-semibold text-harvest-ink">
              No close matches yet.
            </p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Try again after adding another ingredient to the shelf.
            </p>
          </div>
        ) : (
          <ol className="max-h-[32rem] space-y-3 overflow-y-auto pr-1">
            {recipes.map((recipe, index) => (
              <li
                key={recipe.id ?? `${recipe.title}-${index}`}
                className="rounded-md border border-border bg-card px-4 py-4"
              >
                <div className="flex items-start gap-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-harvest-forest font-display text-sm font-semibold text-harvest-paper">
                    {index + 1}
                  </span>
                  <div className="min-w-0">
                    <p className="font-display text-lg font-semibold leading-6 text-harvest-ink">
                      {recipe.title || "Untitled recipe"}
                    </p>
                    <p className="mt-1 text-xs font-medium text-muted-foreground">
                      Uses {recipe.usedIngredientCount ?? 0} shelf ingredient
                      {(recipe.usedIngredientCount ?? 0) === 1 ? "" : "s"}
                      {" · "}
                      Needs {recipe.missedIngredientCount ?? 0} more
                    </p>
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}
