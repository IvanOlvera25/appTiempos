/* AD17 · gráficas
   Tema único de Chart.js y atajos para las formas que usa la app.
   Cárgalo después de Chart.js 4:
     <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
     <script src="{{ url_for('static', filename='js/charts.js') }}"></script>

   Paleta categórica validada para daltonismo (orden fijo, nunca ciclar):
   la serie 1 es azul; con más de 8 categorías el resto se agrupa en "Otros". */
(function () {
  'use strict';

  const T = {
    series: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
    otros: '#98a2b3',
    ink: '#101828',
    ink2: '#475467',
    muted: '#667085',
    grid: '#eef0f3',
    axis: '#d0d5dd',
    surface: '#ffffff',
    font: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
  };

  const nf1 = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 0 });
  const fmt = {
    horas: (v) => nf1.format(v || 0) + ' h',
    numero: (v) => nf0.format(v || 0),
    decimal: (v) => nf1.format(v || 0),
    minutos: (v) => {
      const m = Math.round(v || 0);
      return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
    },
  };

  if (!window.Chart) {
    console.warn('charts.js: Chart.js no está cargado');
    window.AD17Charts = null;
    return;
  }

  const D = Chart.defaults;
  D.font.family = T.font;
  D.font.size = 12;
  D.color = T.muted;
  D.borderColor = T.grid;
  D.maintainAspectRatio = false;
  D.responsive = true;
  D.animation.duration = 450;
  D.layout.padding = { top: 4, right: 8, bottom: 0, left: 0 };

  D.elements.bar.borderRadius = 4;
  D.elements.bar.borderSkipped = 'start';
  D.elements.bar.borderWidth = 0;
  D.elements.line.borderWidth = 2;
  D.elements.line.tension = 0.3;
  D.elements.point.radius = 0;
  D.elements.point.hoverRadius = 5;
  D.elements.point.hitRadius = 12;
  D.elements.point.hoverBorderWidth = 2;
  D.elements.point.hoverBorderColor = T.surface;
  D.elements.arc.borderWidth = 2;
  D.elements.arc.borderColor = T.surface;

  D.scale.grid.color = T.grid;
  D.scale.grid.drawTicks = false;
  D.scale.border.display = false;
  D.scale.ticks.padding = 8;
  D.scale.ticks.color = T.muted;

  const P = D.plugins;
  P.legend.display = false;
  P.legend.labels.usePointStyle = true;
  P.legend.labels.pointStyle = 'rectRounded';
  P.legend.labels.boxWidth = 10;
  P.legend.labels.boxHeight = 10;
  P.legend.labels.padding = 14;
  P.legend.labels.color = T.ink2;
  P.tooltip.backgroundColor = '#0c111d';
  P.tooltip.titleColor = '#fff';
  P.tooltip.bodyColor = '#e4e7ec';
  P.tooltip.padding = 10;
  P.tooltip.cornerRadius = 8;
  P.tooltip.titleFont = { weight: '600', size: 12 };
  P.tooltip.bodyFont = { size: 12 };
  P.tooltip.boxPadding = 4;
  P.tooltip.usePointStyle = true;
  P.tooltip.displayColors = true;
  P.tooltip.caretSize = 5;

  /* Etiquetas de valor al final de cada barra (solo donde se pidan):
     options.plugins.ad17Valores = { fmt: fn } */
  Chart.register({
    id: 'ad17Valores',
    afterDatasetsDraw(chart, _args, opts) {
      if (!opts || !opts.fmt) return;
      const { ctx } = chart;
      const horizontal = chart.options.indexAxis === 'y';
      ctx.save();
      ctx.font = `600 11px ${T.font}`;
      ctx.fillStyle = T.ink2;
      chart.data.datasets.forEach((ds, i) => {
        const meta = chart.getDatasetMeta(i);
        if (meta.hidden) return;
        meta.data.forEach((bar, j) => {
          const v = ds.data[j];
          if (v == null || v === 0) return;
          const txt = opts.fmt(v);
          if (horizontal) {
            ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
            ctx.fillText(txt, bar.x + 6, bar.y);
          } else {
            ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
            ctx.fillText(txt, bar.x, bar.y - 4);
          }
        });
      });
      ctx.restore();
    },
  });

  const registro = new Map();
  function montar(canvas, config) {
    const el = typeof canvas === 'string' ? document.getElementById(canvas) : canvas;
    if (!el) return null;
    registro.get(el)?.destroy();
    const c = new Chart(el, config);
    registro.set(el, c);
    return c;
  }

  /** Reemplaza el lienzo por un estado vacío legible. */
  function vacio(canvas, mensaje, icono = 'bi-bar-chart') {
    const el = typeof canvas === 'string' ? document.getElementById(canvas) : canvas;
    if (!el) return;
    registro.get(el)?.destroy();
    registro.delete(el);
    const caja = el.parentElement;
    let aviso = caja.querySelector('.empty');
    if (!aviso) {
      aviso = document.createElement('div');
      aviso.className = 'empty';
      caja.appendChild(aviso);
    }
    el.style.display = 'none';
    aviso.innerHTML = `<div class="empty-icon"><i class="bi ${icono}"></i></div><p>${mensaje}</p>`;
    aviso.style.display = '';
  }
  function mostrar(el) {
    el.style.display = '';
    const aviso = el.parentElement.querySelector('.empty');
    if (aviso) aviso.style.display = 'none';
  }

  /** De {etiqueta: valor} a las n mayores, con el resto sumado en "Otros". */
  function top(obj, n = 10, conOtros = true) {
    const pares = Object.entries(obj || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
    const cabeza = pares.slice(0, n);
    const cola = pares.slice(n);
    if (conOtros && cola.length) cabeza.push([`Otros (${cola.length})`, cola.reduce((s, [, v]) => s + v, 0)]);
    return { labels: cabeza.map((p) => p[0]), values: cabeza.map((p) => p[1]) };
  }

  const recortar = (s, n = 34) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s);

  // Recorta una etiqueta para que quepa en `px` pixeles (Chart.js limita el
  // ancho del eje y corta el texto por la izquierda si no cabe).
  const medidor = document.createElement('canvas').getContext('2d');
  function recortarPx(texto, px, tam = 12) {
    const s = String(texto == null ? '' : texto);
    medidor.font = `${tam}px ${T.font}`;
    if (medidor.measureText(s).width <= px) return s;
    let lo = 0, hi = s.length;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (medidor.measureText(s.slice(0, mid) + '…').width <= px) lo = mid; else hi = mid - 1;
    }
    return s.slice(0, lo).trimEnd() + '…';
  }

  /** Ranking horizontal: una sola serie, un solo color, valores al final. */
  function barrasH(canvas, labels, values, o = {}) {
    const el = typeof canvas === 'string' ? document.getElementById(canvas) : canvas;
    if (!el) return null;
    if (!labels.length) { vacio(el, o.vacio || 'Sin datos en este periodo.'); return null; }
    mostrar(el);
    const f = o.fmt || fmt.horas;
    const color = o.color || T.series[0];
    // o.colores: un color por barra (p. ej. el de cada área con colorArea)
    const colores = o.colores || labels.map((l) => (/^Otros \(/.test(l) ? T.otros : color));
    if (o.alto !== false) el.parentElement.style.height = Math.max(160, labels.length * (o.fila || 30) + 36) + 'px';
    return montar(el, {
      type: 'bar',
      data: { labels, datasets: [{ label: o.serie || 'Horas', data: values, backgroundColor: colores, hoverBackgroundColor: colores, maxBarThickness: 18, categoryPercentage: 0.8, barPercentage: 0.9 }] },
      options: {
        indexAxis: 'y',
        layout: { padding: { right: 56 } },
        scales: {
          x: { beginAtZero: true, grid: { color: T.grid }, ticks: { callback: (v) => f(v), maxTicksLimit: 5 } },
          y: { grid: { display: false }, ticks: { color: T.ink2, autoSkip: false, callback(v) { return recortarPx(this.getLabelForValue(v), Math.max(90, el.parentElement.clientWidth * 0.36)); } } },
        },
        plugins: {
          ad17Valores: { fmt: f },
          tooltip: { callbacks: { title: (it) => it[0].label, label: (it) => ` ${o.serie || 'Horas'}: ${f(it.raw)}` } },
        },
        onClick: o.onClick ? (_e, els) => { if (els.length) o.onClick(labels[els[0].index], els[0].index); } : undefined,
        onHover: o.onClick ? (e, els) => { e.native.target.style.cursor = els.length ? 'pointer' : 'default'; } : undefined,
      },
    });
  }

  /** Columnas verticales en el tiempo (una o varias series apiladas). */
  function columnas(canvas, labels, datasets, o = {}) {
    const el = typeof canvas === 'string' ? document.getElementById(canvas) : canvas;
    if (!el) return null;
    const total = datasets.reduce((s, d) => s + d.data.reduce((a, b) => a + (b || 0), 0), 0);
    if (!labels.length || !total) { vacio(el, o.vacio || 'Sin datos en este periodo.'); return null; }
    mostrar(el);
    const f = o.fmt || fmt.horas;
    const apilar = datasets.length > 1 && o.apilar !== false;
    return montar(el, {
      type: 'bar',
      data: {
        labels,
        datasets: datasets.map((d, i) => ({
          maxBarThickness: 28, categoryPercentage: 0.75, barPercentage: 0.9,
          backgroundColor: d.color || T.series[i % T.series.length],
          borderColor: T.surface, borderWidth: apilar ? { top: 2 } : 0,
          ...d,
        })),
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { stacked: apilar, grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, autoSkipPadding: 12 } },
          y: { stacked: apilar, beginAtZero: true, ticks: { callback: (v) => f(v), maxTicksLimit: 5 } },
        },
        plugins: {
          legend: { display: datasets.length > 1, position: 'top', align: 'end' },
          tooltip: {
            callbacks: {
              label: (it) => ` ${it.dataset.label}: ${f(it.raw)}`,
              footer: datasets.length > 1 ? (its) => 'Total: ' + f(its.reduce((s, x) => s + (x.raw || 0), 0)) : undefined,
            },
          },
        },
      },
    });
  }

  /** Línea en el tiempo con área sutil (una serie) o varias líneas. */
  function linea(canvas, labels, datasets, o = {}) {
    const el = typeof canvas === 'string' ? document.getElementById(canvas) : canvas;
    if (!el) return null;
    if (!labels.length) { vacio(el, o.vacio || 'Sin datos en este periodo.', 'bi-graph-up'); return null; }
    mostrar(el);
    const f = o.fmt || fmt.horas;
    return montar(el, {
      type: 'line',
      data: {
        labels,
        datasets: datasets.map((d, i) => {
          const color = d.color || T.series[i % T.series.length];
          return {
            borderColor: color, backgroundColor: color, pointBackgroundColor: color,
            fill: datasets.length === 1 ? { target: 'origin', above: color + '14' } : false,
            ...d,
          };
        }),
      },
      options: {
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, autoSkipPadding: 16 } },
          y: { beginAtZero: true, ticks: { callback: (v) => f(v), maxTicksLimit: 5 } },
        },
        plugins: {
          legend: { display: datasets.length > 1, position: 'top', align: 'end' },
          tooltip: { callbacks: { label: (it) => ` ${it.dataset.label}: ${f(it.raw)}` } },
        },
      },
    });
  }

  /** Dona para parte-del-todo: máximo 6 segmentos, el resto en "Otros". */
  function dona(canvas, obj, o = {}) {
    const el = typeof canvas === 'string' ? document.getElementById(canvas) : canvas;
    if (!el) return null;
    const { labels, values } = top(obj, o.max || 5, true);
    if (!labels.length) { vacio(el, o.vacio || 'Sin datos.', 'bi-pie-chart'); return null; }
    mostrar(el);
    const f = o.fmt || fmt.horas;
    const total = values.reduce((a, b) => a + b, 0);
    const colores = labels.map((l, i) => (/^Otros \(/.test(l) ? T.otros : T.series[i]));
    return montar(el, {
      type: 'doughnut',
      data: { labels, datasets: [{ data: values, backgroundColor: colores, hoverOffset: 4 }] },
      options: {
        cutout: '68%',
        plugins: {
          legend: { display: true, position: o.leyenda || 'right', labels: { generateLabels: (ch) => Chart.overrides.doughnut.plugins.legend.labels.generateLabels(ch).map((l, i) => ({ ...l, text: `${recortar(l.text, 26)}  ${Math.round((values[i] / total) * 100)}%` })) } },
          tooltip: { callbacks: { label: (it) => ` ${f(it.raw)} · ${Math.round((it.raw / total) * 100)}%` } },
        },
      },
    });
  }

  /** Color fijo de un área en toda la app: su posición en el orden configurado
      (Configuración → Áreas). Las que pasan de 8 o no están configuradas, en gris. */
  function colorArea(area, orden) {
    const lista = orden || window.AD17_AREAS || [];
    const i = lista.indexOf(area);
    return i >= 0 && i < T.series.length ? T.series[i] : T.otros;
  }

  window.AD17Charts = { T, fmt, top, barrasH, columnas, linea, dona, vacio, montar, recortar, recortarPx, colorArea };
})();
