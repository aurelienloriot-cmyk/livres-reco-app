// Pages protégées : ouverture et fermeture du panneau de filtres.
document.addEventListener("DOMContentLoaded", () => {
  const panel = document.getElementById("filters-panel");
  const overlay = document.querySelector(".filters-overlay");
  const button = document.querySelector("[data-filters-open][aria-controls]");
  if (!panel) return;

  function toggle(open) {
    panel.hidden = !open;
    overlay.hidden = !open;
    if (button) button.setAttribute("aria-expanded", String(open));
    if (open) panel.querySelector("input, button").focus();
  }

  document.querySelectorAll("[data-filters-open]").forEach((el) =>
    el.addEventListener("click", () => toggle(true)));
  document.querySelectorAll("[data-filters-close]").forEach((el) =>
    el.addEventListener("click", () => toggle(false)));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) toggle(false);
  });
});

// Page d'avis : valeur numérique de la note affichée à côté des cœurs.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-rating]").forEach((field) => {
    const output = field.querySelector("[data-rating-value]");
    field.addEventListener("change", (event) => {
      output.textContent = event.target.value ? `${event.target.value}/5` : "Sans note";
    });
  });
});

// Mobile : l'icône loupe de l'en-tête déplie ou replie le champ de recherche.
document.addEventListener("DOMContentLoaded", () => {
  const button = document.querySelector("[data-search-toggle]");
  if (!button) return;
  const topbar = button.closest(".topbar");
  button.addEventListener("click", () => {
    const open = topbar.classList.toggle("search-open");
    button.setAttribute("aria-expanded", String(open));
    if (open) topbar.querySelector(".search-bar input").focus();
  });
});
