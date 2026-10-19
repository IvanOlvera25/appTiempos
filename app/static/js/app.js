/* AD17 · comportamiento común de todas las páginas
   - Barra lateral (contraer, panel móvil)
   - Notificaciones (mensajes flash)
   - Paleta de comandos (Ctrl/⌘ + K) con búsqueda remota
   - Herramientas de tabla: <table data-buscable> agrega buscador y orden
   - AD17Loader: indicador de carga que usan las vistas de registro */
(function () {
  'use strict';

  const esMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  const norm = (s) => (s || '').toString().normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const esc = (s) => (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* modo privado */ } };

  document.querySelectorAll('[data-kbd-mod]').forEach((el) => { el.textContent = esMac ? '⌘K' : 'Ctrl K'; });

  /* ───────────── Barra lateral ─────────────
     Escritorio (≥992 px): el botón de la barra superior oculta o muestra el
     menú y se recuerda. En tableta vertical y celular el menú es un panel que
     se abre encima y se cierra con la X, tocando fuera, con Esc o deslizando. */
  const body = document.body;
  const sidebar = document.getElementById('appSidebar');
  const esEscritorio = window.matchMedia('(min-width: 992px)');

  function sincronizarAria() {
    const visible = esEscritorio.matches ? !body.classList.contains('sidebar-hidden') : body.classList.contains('sidebar-open');
    document.querySelectorAll('[data-sidebar-toggle]').forEach((b) => b.setAttribute('aria-expanded', String(visible)));
  }
  function abrirPanel() {
    body.classList.add('sidebar-open');
    sincronizarAria();
    setTimeout(() => (sidebar?.querySelector('.side-link.active') || sidebar?.querySelector('.side-link'))?.focus({ preventScroll: true }), 50);
  }
  function cerrarPanel() {
    if (!body.classList.contains('sidebar-open')) return;
    body.classList.remove('sidebar-open');
    sincronizarAria();
  }
  function alternarMenu() {
    if (esEscritorio.matches) {
      body.classList.toggle('sidebar-hidden');
      const estado = body.classList.contains('sidebar-hidden') ? 'hidden' : (body.classList.contains('sidebar-mini') ? 'mini' : 'full');
      guardar('ad17.sidebar', estado);
      sincronizarAria();
    } else if (body.classList.contains('sidebar-open')) {
      cerrarPanel();
    } else {
      abrirPanel();
    }
  }
  document.querySelectorAll('[data-sidebar-toggle]').forEach((b) => b.addEventListener('click', alternarMenu));
  document.querySelectorAll('[data-sidebar-mini]').forEach((b) => b.addEventListener('click', () => {
    body.classList.remove('sidebar-hidden');
    body.classList.toggle('sidebar-mini');
    guardar('ad17.sidebar', body.classList.contains('sidebar-mini') ? 'mini' : 'full');
    sincronizarAria();
  }));
  document.querySelectorAll('[data-sidebar-open]').forEach((b) => b.addEventListener('click', abrirPanel));
  document.querySelectorAll('[data-sidebar-close]').forEach((b) => b.addEventListener('click', cerrarPanel));
  esEscritorio.addEventListener('change', () => { cerrarPanel(); sincronizarAria(); });
  sincronizarAria();

  // Deslizar el panel hacia la izquierda lo cierra
  if (sidebar) {
    let x0 = null, y0 = null;
    sidebar.addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
    sidebar.addEventListener('touchend', (e) => {
      if (x0 == null) return;
      const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
      if (dx < -60 && Math.abs(dy) < 50) cerrarPanel();
      x0 = y0 = null;
    }, { passive: true });
  }
  const activo = document.querySelector('.side-link.active');
  if (activo) activo.scrollIntoView({ block: 'nearest' });

  /* ───────────── Reloj de la barra superior ───────────── */
  const reloj = document.getElementById('topbarClock');
  if (reloj) {
    const fmt = new Intl.DateTimeFormat('es-MX', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'America/Mexico_City' });
    const tick = () => { reloj.textContent = fmt.format(new Date()); };
    tick(); setInterval(tick, 20000);
  }

  /* ───────────── Notificaciones ───────────── */
  function cerrarToast(t) {
    if (!t || t.classList.contains('leaving')) return;
    t.classList.add('leaving');
    setTimeout(() => t.remove(), 200);
  }
  function armarToast(t) {
    const ms = parseInt(t.dataset.autohide, 10);
    if (ms > 0) {
      const barra = document.createElement('span');
      barra.className = 't-bar';
      barra.style.animationDuration = ms + 'ms';
      t.appendChild(barra);
      let timer = setTimeout(() => cerrarToast(t), ms);
      t.addEventListener('mouseenter', () => { clearTimeout(timer); barra.style.animationPlayState = 'paused'; });
      t.addEventListener('mouseleave', () => { barra.style.animationPlayState = 'running'; timer = setTimeout(() => cerrarToast(t), 2500); });
    }
    t.querySelector('[data-toast-close]')?.addEventListener('click', () => cerrarToast(t));
  }
  document.querySelectorAll('.ad-toast').forEach(armarToast);

  /** Muestra una notificación desde JS: AD17.toast('Guardado', 'success') */
  function toast(mensaje, tipo = 'info', ms) {
    const stack = document.getElementById('toastStack');
    if (!stack) return;
    const iconos = { success: 'bi-check-lg', danger: 'bi-x-octagon', warning: 'bi-exclamation-triangle', info: 'bi-info-circle' };
    const t = document.createElement('div');
    t.className = 'ad-toast ' + tipo;
    t.dataset.autohide = ms != null ? ms : (tipo === 'danger' || tipo === 'warning' ? 9000 : 5000);
    t.innerHTML = `<span class="t-icon"><i class="bi ${iconos[tipo] || iconos.info}"></i></span><div class="t-body">${esc(mensaje)}</div><button type="button" class="btn-close" aria-label="Cerrar" data-toast-close></button>`;
    stack.appendChild(t);
    armarToast(t);
  }

  /* ───────────── Paleta de comandos ───────────── */
  const cmdk = document.getElementById('cmdk');
  const entrada = document.getElementById('cmdkInput');
  const lista = document.getElementById('cmdkList');
  let datos = { paginas: [], secciones: [], acciones: [], remoto: null };
  try { datos = JSON.parse(document.getElementById('cmdkData').textContent); } catch (e) { /* sin datos */ }

  const paginas = [];
  (datos.paginas || []).forEach((items, i) => {
    const seccion = (datos.secciones || [])[i] || 'General';
    (items || []).forEach((it) => paginas.push({ ...it, sub: seccion, group: 'Páginas' }));
  });
  const acciones = (datos.acciones || []).map((a) => ({ ...a, group: 'Acciones' }));

  let resultados = [];
  let sel = 0;
  let remotos = [];
  let ultimaConsulta = '';
  let temporizador = null;
  let controlador = null;

  function puntuar(texto, q) {
    const t = norm(texto);
    if (!q) return 1;
    if (t.startsWith(q)) return 3;
    if (t.split(/\s+/).some((w) => w.startsWith(q))) return 2;
    if (t.includes(q)) return 1;
    // coincidencia difusa: todas las letras en orden
    let i = 0;
    for (const c of t) if (c === q[i]) i++;
    return i === q.length ? 0.5 : 0;
  }

  function resaltar(texto, q) {
    const s = esc(texto);
    if (!q) return s;
    const idx = norm(texto).indexOf(q);
    if (idx < 0) return s;
    const crudo = String(texto);
    return esc(crudo.slice(0, idx)) + '<mark>' + esc(crudo.slice(idx, idx + q.length)) + '</mark>' + esc(crudo.slice(idx + q.length));
  }

  function pintar() {
    const q = norm(entrada.value.trim());
    const locales = [...paginas, ...acciones]
      .map((it) => ({ it, s: Math.max(puntuar(it.label, q), puntuar(it.sub, q) * 0.6) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .map((x) => x.it);
    const limiteLocal = q ? 8 : 40;
    resultados = [...locales.slice(0, limiteLocal), ...remotos];

    if (!resultados.length) {
      const cargando = cmdk.classList.contains('searching');
      lista.innerHTML = `<div class="cmdk-empty">${cargando ? 'Buscando…' : 'Sin resultados para <strong>' + esc(entrada.value) + '</strong>'}</div>`;
      return;
    }
    if (sel >= resultados.length) sel = resultados.length - 1;

    let html = '';
    let grupo = null;
    resultados.forEach((r, i) => {
      if (r.group !== grupo) { grupo = r.group; html += `<div class="cmdk-group">${esc(grupo)}</div>`; }
      const titulo = r.title || r.label;
      html += `<a class="cmdk-item ${i === sel ? 'selected' : ''}" href="${esc(r.url)}" data-i="${i}">
        <span class="ci-icon"><i class="bi ${esc(r.icon || 'bi-arrow-right')}"></i></span>
        <span class="ci-main"><span class="ci-title">${resaltar(titulo, q)}</span>${r.sub ? `<span class="ci-sub">${esc(r.sub)}</span>` : ''}</span>
        <span class="ci-hint">${i === sel ? 'Abrir ↵' : ''}</span></a>`;
    });
    lista.innerHTML = html;
    lista.querySelector('.cmdk-item.selected')?.scrollIntoView({ block: 'nearest' });
  }

  function buscarRemoto() {
    const q = entrada.value.trim();
    if (!datos.remoto || q.length < 2) { remotos = []; cmdk.classList.remove('searching'); pintar(); return; }
    if (q === ultimaConsulta) return;
    ultimaConsulta = q;
    controlador?.abort();
    controlador = new AbortController();
    cmdk.classList.add('searching');
    fetch(datos.remoto + '?q=' + encodeURIComponent(q), { signal: controlador.signal, headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : { resultados: [] }))
      .then((j) => { if (entrada.value.trim() === q) { remotos = j.resultados || []; pintar(); } })
      .catch(() => {})
      .finally(() => { if (entrada.value.trim() === q) { cmdk.classList.remove('searching'); pintar(); } });
  }

  function abrirPaleta() {
    if (!cmdk) return;
    cmdk.classList.add('open');
    cerrarPanel();
    entrada.value = '';
    remotos = []; ultimaConsulta = ''; sel = 0;
    pintar();
    setTimeout(() => entrada.focus(), 10);
  }
  function cerrarPaleta() { cmdk?.classList.remove('open'); }

  document.querySelectorAll('[data-cmdk-open]').forEach((b) => b.addEventListener('click', (e) => { e.preventDefault(); abrirPaleta(); }));
  document.querySelectorAll('[data-cmdk-close]').forEach((b) => b.addEventListener('click', cerrarPaleta));
  if (entrada) {
    entrada.addEventListener('input', () => {
      sel = 0;
      if (entrada.value.trim().length < 2) { remotos = []; ultimaConsulta = ''; }
      pintar();
      clearTimeout(temporizador);
      temporizador = setTimeout(buscarRemoto, 180);
    });
    entrada.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, resultados.length - 1); pintar(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); pintar(); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        const r = resultados[sel];
        if (r) { cerrarPaleta(); window.location.href = r.url; }
      }
    });
    lista.addEventListener('mousemove', (e) => {
      const a = e.target.closest('.cmdk-item');
      if (a && +a.dataset.i !== sel) { sel = +a.dataset.i; pintar(); }
    });
  }

  document.addEventListener('keydown', (e) => {
    const enCampo = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); cmdk?.classList.contains('open') ? cerrarPaleta() : abrirPaleta(); }
    else if (e.key === 'Escape' && cmdk?.classList.contains('open')) cerrarPaleta();
    else if (e.key === 'Escape' && body.classList.contains('sidebar-open')) cerrarPanel();
    else if (e.key === '/' && !enCampo && cmdk && !cmdk.classList.contains('open') && sidebar) { e.preventDefault(); abrirPaleta(); }
    else if (e.key === '[' && !enCampo && sidebar && !e.metaKey && !e.ctrlKey) alternarMenu();
  });

  /* ───────────── Herramientas de tabla ─────────────
     <table data-buscable>                 buscador + orden por columna
     <table data-buscable="Buscar FP…">    con texto de ayuda propio
     <th data-nosort>                      columna sin orden
     <td data-valor="123">                 valor para ordenar distinto al texto */
  function valorCelda(td) {
    if (!td) return '';
    if (td.dataset.valor != null) return td.dataset.valor;
    return td.textContent.trim();
  }
  function comparar(a, b) {
    const na = parseFloat(String(a).replace(/[^0-9.\-]/g, ''));
    const nb = parseFloat(String(b).replace(/[^0-9.\-]/g, ''));
    const fa = /^\d{1,2}\/\d{1,2}\/\d{2,4}/.exec(a); const fb = /^\d{1,2}\/\d{1,2}\/\d{2,4}/.exec(b);
    if (fa && fb) {
      const p = (s) => { const [d, m, y] = s.split(/[\/\s:]/); return new Date(+(y.length === 2 ? '20' + y : y), m - 1, +d).getTime(); };
      return p(a) - p(b);
    }
    if (!isNaN(na) && !isNaN(nb) && /^[\s$#\-]*[\d.,]+/.test(a) && /^[\s$#\-]*[\d.,]+/.test(b)) return na - nb;
    return norm(a).localeCompare(norm(b), 'es', { numeric: true });
  }

  function mejorarTabla(tabla) {
    if (tabla.dataset.mejorada) return;
    tabla.dataset.mejorada = '1';
    const tbody = tabla.tBodies[0];
    if (!tbody) return;
    const filas = () => Array.from(tbody.rows).filter((r) => !r.classList.contains('no-matches') && r.cells.length > 1);

    // Buscador
    const contenedor = tabla.closest('.table-responsive') || tabla;
    const barra = document.createElement('div');
    barra.className = 'table-tools';
    barra.innerHTML = `<div class="search-field"><i class="bi bi-search"></i><input type="search" class="form-control form-control-sm" placeholder="${esc(tabla.dataset.buscable && tabla.dataset.buscable !== '1' ? tabla.dataset.buscable : 'Buscar en la tabla…')}"></div><span class="count"></span>`;
    const card = contenedor.closest('.card');
    if (!card) barra.classList.add('standalone');
    contenedor.parentNode.insertBefore(barra, contenedor);
    const campo = barra.querySelector('input');
    const contador = barra.querySelector('.count');
    const total = filas().length;
    const actualizarConteo = (n) => { contador.textContent = n === total ? `${total} ${total === 1 ? 'registro' : 'registros'}` : `${n} de ${total}`; };
    actualizarConteo(total);

    let vacia = null;
    campo.addEventListener('input', () => {
      const terminos = norm(campo.value.trim()).split(/\s+/).filter(Boolean);
      let visibles = 0;
      filas().forEach((r) => {
        const t = norm(r.textContent);
        const ok = terminos.every((w) => t.includes(w));
        r.classList.toggle('row-hidden', !ok);
        if (ok) visibles++;
      });
      actualizarConteo(visibles);
      if (!visibles && !vacia) {
        vacia = document.createElement('tr');
        vacia.className = 'no-matches';
        vacia.innerHTML = `<td colspan="${tabla.tHead?.rows[0]?.cells.length || 1}">Ninguna fila coincide con “${esc(campo.value)}”.</td>`;
        tbody.appendChild(vacia);
      } else if (visibles && vacia) { vacia.remove(); vacia = null; }
      if (vacia) vacia.cells[0].textContent = `Ninguna fila coincide con “${campo.value}”.`;
    });

    // Orden por columna
    const encabezados = tabla.tHead ? Array.from(tabla.tHead.rows[tabla.tHead.rows.length - 1].cells) : [];
    encabezados.forEach((th, idx) => {
      if (th.hasAttribute('data-nosort') || !th.textContent.trim()) return;
      th.setAttribute('data-sort', '');
      th.setAttribute('role', 'button');
      th.title = 'Ordenar';
      th.addEventListener('click', () => {
        const dir = th.getAttribute('data-sort') === 'asc' ? 'desc' : 'asc';
        encabezados.forEach((o) => o.hasAttribute('data-sort') && o.setAttribute('data-sort', ''));
        th.setAttribute('data-sort', dir);
        const orden = filas().sort((a, b) => comparar(valorCelda(a.cells[idx]), valorCelda(b.cells[idx])) * (dir === 'asc' ? 1 : -1));
        orden.forEach((r) => tbody.appendChild(r));
        if (vacia) tbody.appendChild(vacia);
      });
    });
  }
  document.querySelectorAll('table[data-buscable]').forEach(mejorarTabla);

  /* ───────────── Tablas como tarjetas en celular ─────────────
     En pantallas angostas, cada fila se muestra como una tarjeta y cada dato
     con la etiqueta de su columna. Aplica a <table data-buscable> y a
     <table data-tarjetas>; se excluye una con data-tarjetas="no".
       <th data-titulo>        esa columna es el título de la tarjeta (va primero, sin etiqueta)
       <th data-movil-oculto>  esa columna no se muestra en la tarjeta */
  function etiquetar(tabla) {
    const cab = tabla.tHead ? Array.from(tabla.tHead.rows[tabla.tHead.rows.length - 1].cells) : [];
    const cols = [];  // por columna: etiqueta y papel en la tarjeta
    cab.forEach((th) => {
      const n = th.colSpan || 1;
      for (let k = 0; k < n; k++) {
        cols.push({
          texto: th.textContent.trim(),
          titulo: th.hasAttribute('data-titulo'),
          oculto: th.hasAttribute('data-movil-oculto'),
        });
      }
    });
    Array.from(tabla.tBodies).forEach((tb) => Array.from(tb.rows).forEach((tr) => {
      let i = 0;
      Array.from(tr.cells).forEach((td) => {
        const c = cols[i] || {};
        if (!td.hasAttribute('data-label') && td.colSpan < 2) td.setAttribute('data-label', c.titulo ? '' : (c.texto || ''));
        if (c.titulo) td.classList.add('td-titulo');
        if (c.oculto) td.classList.add('td-oculto');
        if (td.colSpan > 1) td.classList.add('td-span');
        i += td.colSpan || 1;
      });
    }));
  }
  function tarjetas(tabla) {
    if (tabla.dataset.tarjetas === 'no' || tabla.classList.contains('tabla-tarjetas')) return;
    tabla.classList.add('tabla-tarjetas');
    etiquetar(tabla);
    Array.from(tabla.tBodies).forEach((tb) => new MutationObserver(() => etiquetar(tabla)).observe(tb, { childList: true }));
  }
  document.querySelectorAll('table[data-buscable], table[data-tarjetas]').forEach(tarjetas);

  /* Filtro en vivo para listas que no son tabla:
     <input data-filtra="#lista"> filtra los hijos directos de #lista
     (o los elementos con [data-filtrable] dentro de ella). */
  document.querySelectorAll('input[data-filtra]').forEach((campo) => {
    const destino = document.querySelector(campo.dataset.filtra);
    if (!destino) return;
    const vacio = campo.dataset.vacio ? document.querySelector(campo.dataset.vacio) : null;
    const contador = campo.dataset.contador ? document.querySelector(campo.dataset.contador) : null;
    campo.addEventListener('input', () => {
      const terminos = norm(campo.value.trim()).split(/\s+/).filter(Boolean);
      const items = destino.querySelectorAll('[data-filtrable]').length ? destino.querySelectorAll('[data-filtrable]') : destino.children;
      let n = 0;
      Array.from(items).forEach((el) => {
        const t = norm(el.dataset.filtrable || el.textContent);
        const ok = terminos.every((w) => t.includes(w));
        el.classList.toggle('d-none', !ok);
        if (ok) n++;
      });
      if (vacio) vacio.classList.toggle('d-none', n > 0);
      if (contador) contador.textContent = n;
    });
  });

  /* Tooltips de Bootstrap donde se pidan */
  if (window.bootstrap) document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => new bootstrap.Tooltip(el));

  /* ───────────── Indicador de carga (API usada por las vistas) ───────────── */
  window.AD17Loader = {
    overlay: null, textEl: null, subtextEl: null, progressBar: null, isShowing: false,
    init() {
      this.overlay = document.getElementById('loaderOverlay');
      this.textEl = document.getElementById('loaderText');
      this.subtextEl = document.getElementById('loaderSubtext');
      this.progressBar = document.getElementById('loaderProgressBar');
    },
    show(text, subtext) {
      if (this.isShowing) return;
      if (!this.overlay) this.init();
      this.isShowing = true;
      this.textEl.textContent = text || 'Procesando...';
      this.subtextEl.textContent = subtext || 'Por favor espere';
      this.progressBar.style.animation = 'none';
      void this.progressBar.offsetHeight;
      this.progressBar.style.animation = 'loaderProgress 3.5s ease-out forwards';
      this.overlay.classList.add('active');
      document.body.style.overflow = 'hidden';
    },
    hide() {
      if (!this.overlay) this.init();
      this.isShowing = false;
      this.overlay.classList.remove('active');
      document.body.style.overflow = '';
    },
    showTimeStart() { this.show('Iniciando registro...', 'Registrando tu tiempo de trabajo'); },
    showTimeEnd() { this.show('Finalizando registro...', 'Guardando tu tiempo trabajado'); },
    showProjectAdd() { this.show('Agregando proyecto...', 'Guardando información del proyecto'); },
  };
  window.AD17Loader.init();
  // Si el navegador regresa con "atrás" desde la caché, no dejar el indicador colgado
  window.addEventListener('pageshow', (e) => { if (e.persisted) window.AD17Loader.hide(); });

  window.AD17 = { toast, normalizar: norm, escapar: esc, mejorarTabla, tarjetas, abrirBusqueda: abrirPaleta, alternarMenu };
})();
