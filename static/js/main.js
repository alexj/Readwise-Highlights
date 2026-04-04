// Highlights — main.js
// Minimal JS. Add interactivity here as needed.

// Sort select — navigate preserving the current type filter
const sortSelect = document.querySelector(".sort-select");
if (sortSelect) {
  sortSelect.addEventListener("change", function () {
    const url = new URL(window.location.href);
    url.searchParams.set("sort", this.value);
    window.location.href = url.toString();
  });
}
