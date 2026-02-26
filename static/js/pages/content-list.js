(function () {
  "use strict";

  function filterContentGrid() {
    const query = (document.getElementById("searchInput")?.value || "").toLowerCase().trim();
    const selectedGenre = (document.getElementById("genreFilter")?.value || "").toLowerCase().trim();
    const items = document.querySelectorAll(".content-item");

    items.forEach(function (item) {
      const title = item.getAttribute("data-title") || "";
      const artist = item.getAttribute("data-artist") || "";
      const genre = item.getAttribute("data-genre") || "";

      const matchesSearch = !query || title.includes(query) || artist.includes(query);
      const matchesGenre = !selectedGenre || genre === selectedGenre;
      item.style.display = matchesSearch && matchesGenre ? "" : "none";
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    const searchInput = document.getElementById("searchInput");
    const genreFilter = document.getElementById("genreFilter");

    if (searchInput) {
      searchInput.addEventListener("input", filterContentGrid);
    }

    if (genreFilter) {
      genreFilter.addEventListener("change", filterContentGrid);
    }
  });
})();
