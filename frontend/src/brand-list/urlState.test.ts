import { pageItems } from "./Pagination";
import { readQuery, toSearch } from "./urlState";

describe("readQuery", () => {
  it("reads the three parameters", () => {
    expect(readQuery("?industry=telecom&ordering=review_count&page=3")).toEqual({
      industry: "telecom", ordering: "review_count", page: 3,
    });
  });

  it("uses defaults for missing or invalid values", () => {
    expect(readQuery("")).toEqual({ industry: "", ordering: "-average_rating", page: 1 });
    for (const bad of ["ordering=name", "page=0", "page=-2", "page=1.5", "page=abc"]) {
      const q = readQuery(`?${bad}`);
      expect([q.ordering, q.page]).toEqual(["-average_rating", 1]);
    }
  });
});

describe("toSearch", () => {
  it("leaves out defaults so the plain page has a plain URL", () => {
    expect(toSearch({ industry: "", ordering: "-average_rating", page: 1 })).toBe("");
    expect(toSearch({ industry: "finance", ordering: "-review_count", page: 2 })).toBe(
      "?industry=finance&ordering=-review_count&page=2",
    );
  });

  it("round-trips through readQuery", () => {
    const query = { industry: "home-services", ordering: "average_rating" as const, page: 4 };
    expect(readQuery(toSearch(query))).toEqual(query);
  });
});

describe("pageItems", () => {
  it("lists every page when there are few", () => {
    expect(pageItems(1, 1)).toEqual([1]);
    expect(pageItems(3, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("shows first, last and neighbours with gaps when there are many", () => {
    expect(pageItems(1, 10)).toEqual([1, 2, null, 10]);
    expect(pageItems(5, 10)).toEqual([1, null, 4, 5, 6, null, 10]);
    expect(pageItems(10, 10)).toEqual([1, null, 9, 10]);
    expect(pageItems(3, 10)).toEqual([1, 2, 3, 4, null, 10]);
  });
});
