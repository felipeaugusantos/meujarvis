// FACE — cockpit do Jarvis.
//
// Consome as mesmas rotas do painel. Cada bloco falha sozinho: se o clima cair,
// os sinais vitais continuam. Numa tela que fica ligada sem ninguém por perto,
// um erro não pode apagar o resto.

const ICONES = {
  sol: '☀️', 'nuvem-sol': '⛅', nuvem: '☁️', chuva: '🌧️',
  tempestade: '⛈️', neve: '❄️', neblina: '🌫️',
};

const $ = (id) => document.getElementById(id);

async function json(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} devolveu ${r.status}`);
  return r.json();
}

// ------------------------------------------------------------------ relógio

function relogio() {
  const agora = new Date();
  $('hora').textContent = agora.toLocaleTimeString('pt-BR', {
    hour: '2-digit', minute: '2-digit',
  });
  $('data').textContent = agora.toLocaleDateString('pt-BR', {
    weekday: 'long', day: 'numeric', month: 'long',
  });
}

// ------------------------------------------------------------ sinais vitais

function medidor(rotulo, valor, sufixo = '%') {
  const quente = valor !== null && valor >= 85;
  const pct = valor === null ? 0 : Math.max(0, Math.min(100, valor));
  return `
    <div class="medidor ${quente ? 'quente' : ''}">
      <div class="topo">
        <span>${rotulo}</span>
        <span class="valor">${valor === null ? '—' : valor + sufixo}</span>
      </div>
      <div class="barra"><i style="transform: scaleX(${pct / 100})"></i></div>
    </div>`;
}

async function vitais() {
  try {
    const s = await json('/api/sistema');

    $('medidores').innerHTML =
      medidor('Processador', s.cpu === null ? null : Math.round(s.cpu)) +
      medidor('Memória', s.ram === null ? null : Math.round(s.ram)) +
      medidor('GPU', s.gpu) +
      medidor('VRAM', s.vram);

    const estado = $('estado');
    if (s.modelo === 'online') {
      estado.textContent = 'sistemas nominais';
      estado.classList.remove('caido');
    } else {
      estado.textContent = 'modelo offline';
      estado.classList.add('caido');
    }

    // O núcleo acelera quando a máquina está trabalhando de verdade.
    document.querySelector('.nucleo')
      .classList.toggle('ativo', (s.gpu || 0) > 45 || (s.cpu || 0) > 65);
  } catch (e) {
    $('estado').textContent = 'sem telemetria';
  }
}

// ----------------------------------------------------------------- ambiente

async function ambiente() {
  try {
    const c = await json('/api/clima');
    $('ambiente').innerHTML = `
      <div class="ambiente-topo">
        <div class="ambiente-icone">${ICONES[c.icone] || '☁️'}</div>
        <div class="ambiente-temp">${c.temperatura}°</div>
      </div>
      <div class="ambiente-meta">
        ${c.descricao} · ${c.cidade}<br>
        máx ${c.maxima}° / mín ${c.minima}° · umidade ${c.umidade}%
      </div>`;
  } catch (e) {
    $('ambiente').innerHTML = '<div class="carregando">clima indisponível</div>';
  }
}

// ------------------------------------------------------------------ tarefas

async function tarefas() {
  try {
    const d = await json('/api/tarefas');
    const lista = $('tarefas');
    lista.innerHTML = '';

    const pendentes = d.itens.filter((t) => !t.feita);
    const mostrar = (pendentes.length ? pendentes : d.itens).slice(0, 6);

    if (!mostrar.length) {
      lista.innerHTML = '<li class="carregando">nada pendente</li>';
      return;
    }

    for (const t of mostrar) {
      const li = document.createElement('li');
      if (t.feita) li.className = 'feita';
      li.textContent = t.texto;   // texto do usuário: nunca via innerHTML
      lista.appendChild(li);
    }
  } catch (e) { /* mantém o que já está na tela */ }
}

// ------------------------------------------------------------------- agenda

async function agenda() {
  try {
    const d = await json('/api/integracoes');
    $('agenda').innerHTML = d.agenda.configurado
      ? '<div class="carregando">sem compromissos</div>'
      : '<div class="carregando">Google não conectado</div>';
  } catch (e) { /* bloco opcional */ }
}

// ----------------------------------------------------------------- notícias

async function noticias() {
  try {
    const d = await json('/api/noticias');
    if (!d.itens.length) return;

    const texto = d.itens.map((n) => n.titulo).join('<span>◆</span>');
    // Duplicado porque a animação desliza -50%: a emenda fica invisível.
    $('trilho').innerHTML = texto + '<span>◆</span>' + texto;
  } catch (e) {
    $('trilho').textContent = 'notícias indisponíveis';
  }
}

// -------------------------------------------------------------------- globo

// Globo de arame: paralelos e meridianos projetados à mão. Uma biblioteca 3D
// custaria centenas de kB para desenhar meia dúzia de elipses.
function globo() {
  const tela = $('globo');
  const ctx = tela.getContext('2d');
  const L = tela.width;
  const meio = L / 2;
  const raio = L * 0.42;
  let giro = 0;

  function quadro() {
    ctx.clearRect(0, 0, L, L);
    ctx.lineWidth = 1;

    // Contorno
    ctx.strokeStyle = 'rgba(94, 234, 255, 0.55)';
    ctx.beginPath();
    ctx.arc(meio, meio, raio, 0, Math.PI * 2);
    ctx.stroke();

    // Paralelos: elipses achatadas conforme a latitude.
    ctx.strokeStyle = 'rgba(94, 234, 255, 0.26)';
    for (let i = 1; i < 6; i++) {
      const lat = (i / 6) * Math.PI - Math.PI / 2;
      const y = meio + Math.sin(lat) * raio;
      const rx = Math.cos(lat) * raio;
      ctx.beginPath();
      ctx.ellipse(meio, y, rx, rx * 0.22, 0, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Meridianos: a largura acompanha o giro, dando a volta.
    ctx.strokeStyle = 'rgba(167, 139, 250, 0.32)';
    for (let i = 0; i < 6; i++) {
      const fase = giro + (i / 6) * Math.PI;
      const rx = Math.abs(Math.cos(fase)) * raio;
      if (rx < 1) continue;
      ctx.beginPath();
      ctx.ellipse(meio, meio, rx, raio, 0, 0, Math.PI * 2);
      ctx.stroke();
    }

    giro += 0.0045;
    requestAnimationFrame(quadro);
  }

  // Respeita quem pediu menos movimento: desenha uma vez e para.
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    quadro = quadro.bind(null);
    ctx.clearRect(0, 0, L, L);
  }
  requestAnimationFrame(quadro);
}

// -------------------------------------------------------------------- ciclo

relogio();
setInterval(relogio, 1000);

vitais();
setInterval(vitais, 3000);

ambiente();
setInterval(ambiente, 15 * 60 * 1000);

tarefas();
setInterval(tarefas, 30 * 1000);

noticias();
setInterval(noticias, 30 * 60 * 1000);

agenda();
globo();

// Toque em qualquer lugar entra em tela cheia — o quiosque não tem teclado.
document.body.addEventListener('dblclick', () => {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen();
  else document.exitFullscreen();
});
