// Questionnaire : options exclusives, bouton Continuer, champ « Autre ».
document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector(".survey-form");
  if (!form) return;
  const inputs = [...form.querySelectorAll('input[name="answer"]')];
  const button = form.querySelector(".btn-continue");
  const other = form.querySelector(".other-field");
  const otherInput = form.querySelector('input[name="answer"][value="autre"]');

  function refresh() {
    button.disabled = !inputs.some((input) => input.checked);
    if (other) other.hidden = !otherInput.checked;
  }

  inputs.forEach((input) => {
    input.addEventListener("change", () => {
      // L'option neutre (ou « aucun ») désélectionne les autres, et inversement.
      if (input.type === "checkbox" && input.checked) {
        const exclusive = "exclusive" in input.dataset;
        inputs.forEach((o) => {
          if (o !== input && (exclusive || "exclusive" in o.dataset)) o.checked = false;
        });
      }
      refresh();
    });
  });
  refresh();
});
