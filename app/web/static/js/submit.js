// The site's only JavaScript of its own (docs/design.md F25). One job: a pressed submit
// button shows it is working and cannot be pressed a second time. On a slow phone a
// second tap of «Зачувај го профилот», or of «Прифати и објави» in the admin, sent the
// form twice. HTMX could not do it: the admin does not load it, and the forms are plain
// POSTs that must work with JavaScript off (they still do; this only adds the state).
document.addEventListener("submit", (event) => {
  const button = event.submitter;
  if (!button || event.defaultPrevented) return;
  if (!button.dataset.busy) button.dataset.busy = "Се обработува";
  button.setAttribute("aria-busy", "true");
  // After the event, or the browser leaves the button's own name and value out of the form.
  setTimeout(() => { button.disabled = true; }, 0);
});

// Back to a page from the browser's cache: the button must work again.
window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  for (const button of document.querySelectorAll('[aria-busy="true"]')) {
    button.removeAttribute("aria-busy");
    button.disabled = false;
  }
});
