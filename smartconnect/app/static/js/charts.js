/* charts.js - thin helper around Chart.js (colours + re-use of canvases). */
(function () {
  "use strict";
  const SC = window.SC;
  const COLORS = ["#1557d6", "#1f9d55", "#f0a30a", "#d64545", "#6f42c1", "#17a2b8", "#7a8aa8"];
  const instances = {};
  SC.COLORS = COLORS;

  /** SC.chart("canvasId", {type, labels, datasets:[{label,data,color?}], options?}) */
  SC.chart = function (id, cfg) {
    const canvas = SC.$(id);
    if (!canvas || typeof Chart === "undefined") return null;
    if (instances[id]) instances[id].destroy();
    const isRound = cfg.type === "doughnut" || cfg.type === "pie";
    const datasets = cfg.datasets.map((d, i) => {
      const color = d.color || COLORS[i % COLORS.length];
      return Object.assign({
        backgroundColor: isRound ? COLORS : color + (cfg.type === "line" ? "33" : ""),
        borderColor: isRound ? "#fff" : color,
        borderWidth: isRound ? 2 : 2, tension: 0.3, fill: cfg.type === "line",
        pointRadius: cfg.type === "line" ? 2 : 0, borderRadius: cfg.type === "bar" ? 4 : 0,
      }, d);
    });
    const options = Object.assign({
      responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      plugins: { legend: { display: datasets.length > 1 || isRound, position: "bottom" } },
      scales: isRound ? {} : { y: { beginAtZero: true, ticks: { precision: 0 } }, x: { grid: { display: false } } },
    }, cfg.options || {});
    instances[id] = new Chart(canvas, { type: cfg.type, data: { labels: cfg.labels, datasets }, options });
    return instances[id];
  };
})();
