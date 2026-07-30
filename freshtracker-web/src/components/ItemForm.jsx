import { useState } from "react"
import { Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const UNIT_OPTIONS = [
  "item",
  "bag",
  "bunch",
  "box",
  "bottle",
  "can",
  "carton",
  "loaf",
  "pack",
  "pound",
]

function localDateInputValue() {
  const today = new Date()
  const timezoneOffset = today.getTimezoneOffset() * 60_000
  return new Date(today.getTime() - timezoneOffset).toISOString().slice(0, 10)
}

function initialValues() {
  return {
    name: "",
    quantity: "1",
    unit: "item",
    expiry_date: localDateInputValue(),
  }
}

export function ItemForm({ onAddItem, isAdding }) {
  const [formValues, setFormValues] = useState(initialValues)
  const [localError, setLocalError] = useState("")

  function updateField(field, value) {
    setFormValues((currentValues) => ({
      ...currentValues,
      [field]: value,
    }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setLocalError("")

    const trimmedName = formValues.name.trim()
    const quantity = Number(formValues.quantity)

    if (!trimmedName) {
      setLocalError("Give the item a name first.")
      return
    }

    if (!Number.isFinite(quantity) || quantity <= 0) {
      setLocalError("Quantity needs to be greater than zero.")
      return
    }

    try {
      await onAddItem({
        name: trimmedName,
        quantity,
        unit: formValues.unit,
        expiry_date: formValues.expiry_date,
      })
      setFormValues(initialValues())
    } catch {
      // The parent renders the API error.
    }
  }

  return (
    <Card className="border-harvest-ink/10 bg-background shadow-panel">
      <CardHeader className="pb-4">
        <CardTitle>Add groceries</CardTitle>
        <p className="text-sm leading-6 text-muted-foreground">
          Category can stay blank. The model will make the call.
        </p>
      </CardHeader>
      <CardContent>
        <form className="space-y-5" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <label className="text-sm font-semibold" htmlFor="item-name">
              Item name
            </label>
            <Input
              id="item-name"
              value={formValues.name}
              onChange={(event) => updateField("name", event.target.value)}
              placeholder="e.g. cherry tomatoes"
              autoComplete="off"
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-semibold" htmlFor="expiry-date">
              Use-by date
            </label>
            <Input
              id="expiry-date"
              type="date"
              required
              value={formValues.expiry_date}
              onChange={(event) => updateField("expiry_date", event.target.value)}
            />
          </div>

          <div className="grid grid-cols-[1fr_1.25fr] gap-3">
            <div className="space-y-2">
              <label className="text-sm font-semibold" htmlFor="quantity">
                Quantity
              </label>
              <Input
                id="quantity"
                type="number"
                min="0"
                step="0.25"
                value={formValues.quantity}
                onChange={(event) => updateField("quantity", event.target.value)}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-semibold">Unit</label>
              <Select
                value={formValues.unit}
                onValueChange={(value) => updateField("unit", value)}
              >
                <SelectTrigger aria-label="Unit">
                  <SelectValue placeholder="Choose unit" />
                </SelectTrigger>
                <SelectContent>
                  {UNIT_OPTIONS.map((unit) => (
                    <SelectItem key={unit} value={unit}>
                      {unit}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {localError ? (
            <p className="rounded-md border border-destructive/30 bg-harvest-paper px-3 py-2 text-sm text-destructive">
              {localError}
            </p>
          ) : null}

          <Button type="submit" className="w-full" disabled={isAdding}>
            <Plus className="h-4 w-4" />
            {isAdding ? "Adding..." : "Add to list"}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
