import React from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import App from "@/App"
import { ApiError, requestJSON } from "@/lib/api"

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, requestJSON: vi.fn() }
})

vi.mock("@/components/WasteRatioChart", () => ({
  WasteRatioChart: () => <div>Outcome chart</div>,
}))

vi.mock("@/components/RecipeSuggestions", () => ({
  RecipeSuggestions: () => <div>Recipe suggestions</div>,
}))

const inventoryItems = [
  {
    id: 1,
    name: "Whole milk",
    category: "Dairy",
    quantity: 1,
    unit: "carton",
    expiry_date: "2026-08-22",
    days_until_expiry: 1,
    expiry_status: "expiring_soon",
    status: "active",
  },
  {
    id: 2,
    name: "Sourdough bread",
    category: "Bakery",
    quantity: 1,
    unit: "loaf",
    expiry_date: "2026-08-25",
    days_until_expiry: 4,
    expiry_status: "expiring_soon",
    status: "active",
  },
]

function dashboardResponse(path) {
  if (path === "/items") return { items: inventoryItems }
  if (path === "/waste-logs/category-summary") return { categories: [] }
  if (path === "/recipe-suggestions") {
    return { recipes: [], ingredients: [], priority_ingredients: [] }
  }
  throw new Error(`Unexpected API request: ${path}`)
}

describe("FreshTracker frontend reliability", () => {
  beforeEach(() => {
    requestJSON.mockReset()
  })

  it("validates empty login fields and submits valid credentials successfully", async () => {
    const user = userEvent.setup()
    requestJSON.mockImplementation(async (path, options = {}) => {
      if (path === "/auth/me") return { authenticated: false, user: null }
      if (path === "/auth/login" && options.method === "POST") {
        return { user: { id: 7, email: "cook@example.com" } }
      }
      return dashboardResponse(path)
    })

    render(<App />)

    const email = await screen.findByLabelText("Email address")
    const password = screen.getByLabelText("Password")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    expect(email).toBeInvalid()
    expect(password).toBeInvalid()
    expect(requestJSON).not.toHaveBeenCalledWith(
      "/auth/login",
      expect.anything(),
    )

    await user.type(email, "cook@example.com")
    await user.type(password, "Password-1234")
    await user.click(screen.getByRole("button", { name: "Sign in" }))

    expect(await screen.findByText("cook@example.com")).toBeInTheDocument()
    expect(requestJSON).toHaveBeenCalledWith("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: "cook@example.com",
        password: "Password-1234",
      }),
    })
  })

  it("filters inventory when search and category controls change", async () => {
    const user = userEvent.setup()
    requestJSON.mockImplementation(async (path) => {
      if (path === "/auth/me") {
        return { authenticated: true, user: { id: 7, email: "cook@example.com" } }
      }
      return dashboardResponse(path)
    })

    render(<App />)

    expect(await screen.findByText("Whole milk")).toBeInTheDocument()
    expect(screen.getByText("Sourdough bread")).toBeInTheDocument()

    await user.type(screen.getByLabelText("Search items"), "milk")
    expect(screen.getByText("Whole milk")).toBeInTheDocument()
    expect(screen.queryByText("Sourdough bread")).not.toBeInTheDocument()

    await user.clear(screen.getByLabelText("Search items"))
    await user.click(screen.getByLabelText("Category"))
    await user.click(screen.getByRole("option", { name: "Bakery" }))

    expect(screen.getByText("Sourdough bread")).toBeInTheDocument()
    expect(screen.queryByText("Whole milk")).not.toBeInTheDocument()
  })

  it("shows a user-friendly alert when the inventory API returns 500", async () => {
    requestJSON.mockImplementation(async (path) => {
      if (path === "/auth/me") {
        return { authenticated: true, user: { id: 7, email: "cook@example.com" } }
      }
      if (path === "/items") {
        throw new ApiError(
          "FreshTracker couldn't complete that request. Please try again.",
          500,
        )
      }
      return dashboardResponse(path)
    })

    render(<App />)

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("Something needs attention.")
    expect(alert).toHaveTextContent(
      "FreshTracker couldn't complete that request. Please try again.",
    )
    await waitFor(() => expect(requestJSON).toHaveBeenCalledWith("/items", {
      method: "GET",
      headers: {},
    }))
  })
})
