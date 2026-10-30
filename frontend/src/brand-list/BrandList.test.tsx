import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { apiResponse, deferred, mockFetch, requestedSearches } from "../test/fakeApi";
import { BrandList } from "./BrandList";

const API = "/api/brands/";

function renderAt(url: string) {
  window.history.replaceState(null, "", url);
  const user = userEvent.setup();
  render(<BrandList apiUrl={API} />);
  return user;
}

const cardNames = () =>
  within(screen.getByRole("region")).queryAllByRole("heading", { level: 3 }).map((h) => h.textContent);

const heading = () => screen.getByRole("heading", { level: 2 });

/** Wait for the results heading to read `text` (it's also in the status message). */
const showing = (text: string) => screen.findByRole("heading", { level: 2, name: text });

describe("loading data", () => {
  it("shows a loading state, then the brand cards", async () => {
    const response = deferred<ReturnType<typeof apiResponse>>();
    const fetchMock = mockFetch(() => response.promise);
    renderAt("/brand/");

    expect(heading()).toHaveTextContent("Loading brands…");
    expect(screen.getByRole("status")).toHaveTextContent("Loading brands…");
    expect(screen.getByRole("region")).toHaveAttribute("aria-busy", "true");

    await act(async () => response.resolve(apiResponse(API)));

    expect(heading()).toHaveTextContent("Showing 1–12 of 14 brands");
    expect(screen.getByRole("status")).toHaveTextContent("Showing 1–12 of 14 brands");
    expect(screen.getByRole("region")).toHaveAttribute("aria-busy", "false");
    expect(cardNames()).toHaveLength(12);
    expect(requestedSearches(fetchMock)).toEqual([""]);
    expect(fetchMock.mock.calls[0]![0]).toBe(API);
  });

  it("renders everything a card needs", async () => {
    mockFetch();
    renderAt("/brand/");
    const card = (await screen.findByRole("heading", { name: "Brand 00" })).closest("article")!;

    expect(within(card).getByRole("link", { name: "Brand 00" })).toHaveAttribute("href", "/brand/brand-0/");
    expect(within(card).getByText("Insurance")).toHaveClass("badge");
    expect(within(card).getByRole("img", { name: "Rated 5.0 out of 5" })).toBeInTheDocument();
    expect(within(card).getByText("(0 reviews)")).toBeInTheDocument();
    expect(within(card).getByText("Hartford, CT")).toBeInTheDocument();
    expect(within(card).getByText("Description of brand 0.")).toBeInTheDocument();
    expect(within(card).getByText("“Snippet for brand 0”")).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: "Rated 5 out of 5" })).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Great service 0" })).toHaveAttribute("href", "/review/review-0/");
  });

  it("offers the industries from the API as filter options", async () => {
    mockFetch();
    renderAt("/brand/");
    const select = screen.getByRole("combobox", { name: "Industry" });
    await waitFor(() =>
      expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
        "All industries", "Finance", "Insurance", "Telecom",
      ]),
    );
  });
});

describe("filtering", () => {
  it("fetches the chosen industry, puts it in the URL and starts at page 1", async () => {
    const fetchMock = mockFetch();
    const user = renderAt("/brand/?page=2");
    await showing("Showing 13–14 of 14 brands");

    await user.selectOptions(screen.getByRole("combobox", { name: "Industry" }), "finance");

    await showing("Showing 4 brands");
    expect(window.location.search).toBe("?industry=finance");
    expect(requestedSearches(fetchMock).at(-1)).toBe("?industry=finance");
    expect(cardNames()).toEqual(["Brand 10", "Brand 11", "Brand 12", "Brand 13"]);
  });

  it("shows an empty state with a way back to all industries", async () => {
    mockFetch();
    const user = renderAt("/brand/?industry=telecom");

    expect(await screen.findByText("No brands match this filter.")).toBeInTheDocument();
    expect(heading()).toHaveTextContent("No brands found");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show all industries" }));
    await showing("Showing 1–12 of 14 brands");
    expect(window.location.search).toBe("");
  });
});

describe("sorting", () => {
  it("fetches the chosen order and puts it in the URL", async () => {
    const fetchMock = mockFetch();
    const user = renderAt("/brand/");
    await showing("Showing 1–12 of 14 brands");

    await user.selectOptions(screen.getByRole("combobox", { name: "Sort by" }), "Lowest rated");

    await waitFor(() => expect(cardNames()[0]).toBe("Brand 13"));
    expect(window.location.search).toBe("?ordering=average_rating");
    expect(requestedSearches(fetchMock).at(-1)).toBe("?ordering=average_rating");
  });

  it("offers the four orderings with readable labels", () => {
    mockFetch();
    renderAt("/brand/");
    const options = within(screen.getByRole("combobox", { name: "Sort by" })).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "Highest rated", "Lowest rated", "Most reviewed", "Fewest reviewed",
    ]);
  });
});

describe("pagination", () => {
  it("moves between pages with real links and focuses the results", async () => {
    const fetchMock = mockFetch();
    const user = renderAt("/brand/?ordering=-review_count");
    await showing("Showing 1–12 of 14 brands");

    const nav = screen.getByRole("navigation", { name: "Pagination" });
    expect(within(nav).getByRole("link", { name: "Page 1" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: /Next/ })).toHaveAttribute(
      "href", "/brand/?ordering=-review_count&page=2",
    );
    expect(within(nav).queryByRole("link", { name: /Previous/ })).not.toBeInTheDocument();

    await user.click(within(nav).getByRole("link", { name: /Next/ }));

    await showing("Showing 13–14 of 14 brands");
    expect(window.location.search).toBe("?ordering=-review_count&page=2");
    expect(requestedSearches(fetchMock).at(-1)).toBe("?ordering=-review_count&page=2");
    expect(heading()).toHaveFocus();
    expect(screen.getByRole("link", { name: "Page 2" })).toHaveAttribute("aria-current", "page");

    await user.click(screen.getByRole("link", { name: /Previous/ }));
    await showing("Showing 1–12 of 14 brands");
    expect(window.location.search).toBe("?ordering=-review_count");
  });

  it("is hidden when everything fits on one page", async () => {
    mockFetch();
    renderAt("/brand/?industry=finance");
    await showing("Showing 4 brands");
    expect(screen.queryByRole("navigation", { name: "Pagination" })).not.toBeInTheDocument();
  });

  it("keeps the old cards visible (busy) while the next page loads", async () => {
    const page2 = deferred<ReturnType<typeof apiResponse>>();
    mockFetch((url) => (url.includes("page=2") ? page2.promise : apiResponse(url)));
    const user = renderAt("/brand/");
    await showing("Showing 1–12 of 14 brands");

    await user.click(screen.getByRole("link", { name: /Next/ }));

    expect(screen.getByRole("region")).toHaveAttribute("aria-busy", "true");
    expect(cardNames()).toHaveLength(12);
    await act(async () => page2.resolve(apiResponse(`${API}?page=2`)));
    expect(cardNames()).toEqual(["Brand 12", "Brand 13"]);
  });
});

describe("URL state", () => {
  it("starts from the filters in the URL", async () => {
    const fetchMock = mockFetch();
    renderAt("/brand/?industry=insurance&ordering=review_count");

    await showing("Showing 10 brands");
    expect(requestedSearches(fetchMock)).toEqual(["?industry=insurance&ordering=review_count"]);
    expect(screen.getByRole("combobox", { name: "Industry" })).toHaveValue("insurance");
    expect(screen.getByRole("combobox", { name: "Sort by" })).toHaveValue("review_count");
  });

  it("follows the browser's Back and Forward buttons", async () => {
    mockFetch();
    const user = renderAt("/brand/");
    await showing("Showing 1–12 of 14 brands");
    await user.selectOptions(screen.getByRole("combobox", { name: "Industry" }), "finance");
    await showing("Showing 4 brands");

    act(() => window.history.back());
    await showing("Showing 1–12 of 14 brands");
    expect(window.location.search).toBe("");
    expect(screen.getByRole("combobox", { name: "Industry" })).toHaveValue("");

    act(() => window.history.forward());
    await showing("Showing 4 brands");
    expect(screen.getByRole("combobox", { name: "Industry" })).toHaveValue("finance");
  });

  it("cleans up values the controls can't show", async () => {
    const fetchMock = mockFetch();
    renderAt("/brand/?ordering=bogus&page=abc");
    await showing("Showing 1–12 of 14 brands");
    expect(window.location.search).toBe("");
    expect(requestedSearches(fetchMock)).toEqual([""]);
  });

  it("does not add a history entry when nothing changes", async () => {
    mockFetch();
    const user = renderAt("/brand/");
    await showing("Showing 1–12 of 14 brands");
    const length = window.history.length;
    await user.selectOptions(screen.getByRole("combobox", { name: "Industry" }), "");
    expect(window.history.length).toBe(length);
  });
});

describe("cancelling requests", () => {
  it("aborts the old request when the filter changes, so a late response can't win", async () => {
    const slow = deferred<ReturnType<typeof apiResponse>>();
    const fetchMock = mockFetch((url) => (url.includes("insurance") ? slow.promise : apiResponse(url)));
    const user = renderAt("/brand/");
    await showing("Showing 1–12 of 14 brands");

    const industry = screen.getByRole("combobox", { name: "Industry" });
    await user.selectOptions(industry, "insurance");
    await user.selectOptions(industry, "finance");
    await showing("Showing 4 brands");

    const insuranceCall = fetchMock.mock.calls.find(([url]) => String(url).includes("insurance"))!;
    expect((insuranceCall[1] as RequestInit).signal!.aborted).toBe(true);

    await act(async () => slow.resolve(apiResponse(`${API}?industry=insurance`)));
    expect(heading()).toHaveTextContent("Showing 4 brands");
    expect(cardNames()).toEqual(["Brand 10", "Brand 11", "Brand 12", "Brand 13"]);
  });
});

describe("errors", () => {
  it("offers to try again after a server error", async () => {
    let fail = true;
    mockFetch((url) => (fail ? { status: 500 } : apiResponse(url)));
    const user = renderAt("/brand/");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Brands couldn't be loaded.");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    await showing("Showing 1–12 of 14 brands");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("treats a network failure like a server error", async () => {
    mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    renderAt("/brand/");
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again");
  });

  it("offers a reset for an unknown industry in the URL (400)", async () => {
    mockFetch();
    const user = renderAt("/brand/?industry=nope");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The filters in this address aren't valid.");

    await user.click(within(alert).getByRole("button", { name: "Reset filters" }));
    await showing("Showing 1–12 of 14 brands");
    expect(window.location.search).toBe("");
    expect(heading()).toHaveFocus();
  });

  it("offers the first page for a page past the end (404)", async () => {
    mockFetch();
    const user = renderAt("/brand/?page=9");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That page of results doesn't exist.");
    await user.click(within(alert).getByRole("button", { name: "Go to the first page" }));
    await showing("Showing 1–12 of 14 brands");
  });
});

describe("keyboard and labels", () => {
  it("reaches the filters and pagination with Tab, in order", async () => {
    mockFetch();
    const user = renderAt("/brand/");
    await showing("Showing 1–12 of 14 brands");

    await user.tab();
    expect(screen.getByRole("combobox", { name: "Industry" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("combobox", { name: "Sort by" })).toHaveFocus();

    const nextLink = screen.getByRole("link", { name: /Next/ });
    while (document.activeElement !== nextLink) await user.tab();
    await user.keyboard("{Enter}");
    await showing("Showing 13–14 of 14 brands");
  });
});
