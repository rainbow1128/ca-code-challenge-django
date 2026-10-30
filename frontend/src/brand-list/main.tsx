// Entry point, built to main/static/js/brand-list.js and loaded by the Django
// /brand/ page, which provides <div id="brand-list" data-api-url="/api/brands/">.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { BrandList } from "./BrandList";

const root = document.getElementById("brand-list");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <BrandList apiUrl={root.dataset.apiUrl ?? "/api/brands/"} />
    </StrictMode>,
  );
}
