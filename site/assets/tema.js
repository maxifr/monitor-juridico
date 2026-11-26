// Aplica el tema guardado antes de pintar la página (evita el destello claro/oscuro).
(function () {
  try {
    var tema = localStorage.getItem("mj:tema");
    if (tema === "light" || tema === "dark") document.documentElement.setAttribute("data-theme", tema);
  } catch (e) { /* sin almacenamiento: se usa el tema del sistema */ }
})();
