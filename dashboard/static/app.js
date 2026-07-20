// Painel de parede — busca os dados do próprio servidor e redesenha sozinho.
// Nenhuma chamada externa sai daqui: o backend é quem fala com clima e RSS.

const ICONES = {
  sol: '☀️', 'nuvem-sol': '⛅', nuvem: '☁️', chuva: '🌧️',
  tempestade: '⛈️', neve: '❄️', neblina: '🌫️',
};

const $ = (id) => document.getElementById(id);

async function json(url, opcoes) {
  const r = await fetch(url, opcoes);
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

// -------------------------------------------------------------------- clima

async function clima() {
  try {
    const c = await json('/api/clima');
    const prev = c.proximos.map((p) => {
      const dia = new Date(p.data + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'short' });
      return `<div>
                <div class="dia">${dia.replace('.', '')}</div>
                <div>${ICONES[p.icone] || '☁️'}</div>
                <div><span class="mx">${p.max}°</span> ${p.min}°</div>
              </div>`;
    }).join('');

    $('clima').innerHTML = `
      <div class="clima-topo">
        <div class="clima-icone">${ICONES[c.icone] || '☁️'}</div>
        <div>
          <div class="clima-temp">${c.temperatura}°</div>
        </div>
      </div>
      <div class="clima-desc">${c.descricao}</div>
      <div class="clima-meta">
        ${c.cidade} · máx ${c.maxima}° / mín ${c.minima}° ·
        sensação ${c.sensacao}° · umidade ${c.umidade}%
      </div>
      <div class="clima-prev">${prev}</div>`;
  } catch (e) {
    $('clima').innerHTML = '<div class="carregando">clima indisponível</div>';
  }
}

// ------------------------------------------------------------------ tarefas

function desenharTarefas(itens) {
  const lista = $('lista-tarefas');
  lista.innerHTML = '';
  $('tarefas-vazio').style.display = itens.length ? 'none' : 'block';

  // Pendentes primeiro; concluídas descem para o fim.
  const ordenadas = [...itens].sort((a, b) => Number(a.feita) - Number(b.feita));

  for (const t of ordenadas) {
    const li = document.createElement('li');
    li.className = t.feita ? 'feita' : '';
    li.innerHTML = `
      <div class="caixa" role="checkbox" aria-checked="${t.feita}" tabindex="0">✓</div>
      <span class="rotulo"></span>
      <button class="apagar" aria-label="Remover">×</button>`;
    // textContent, e não innerHTML: o texto vem do usuário.
    li.querySelector('.rotulo').textContent = t.texto;

    li.querySelector('.caixa').onclick = async () => {
      const r = await json(`/api/tarefas/${t.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feita: !t.feita }),
      });
      desenharTarefas(r.itens);
    };

    li.querySelector('.apagar').onclick = async () => {
      const r = await json(`/api/tarefas/${t.id}`, { method: 'DELETE' });
      desenharTarefas(r.itens);
    };

    lista.appendChild(li);
  }
}

async function tarefas() {
  try {
    desenharTarefas((await json('/api/tarefas')).itens);
  } catch (e) { /* mantém o que já está na tela */ }
}

$('form-tarefa').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const campo = $('entrada-tarefa');
  const texto = campo.value.trim();
  if (!texto) return;
  campo.value = '';
  const r = await json('/api/tarefas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto }),
  });
  desenharTarefas(r.itens);
});

// --------------------------------------------------------- e-mail e agenda

async function integracoes() {
  try {
    const d = await json('/api/integracoes');
    if (!d.email.configurado) {
      $('agenda').innerHTML = `
        <h2>E-mail e agenda</h2>
        <p class="pendente">
          <strong>Ainda não conectado.</strong><br>
          Precisa de uma credencial OAuth do Google para ler Gmail,
          Tarefas e Agenda. Depois de criá-la, rode
          <code>jarvis connect gdrive</code> e este bloco passa a
          mostrar não lidos e próximos compromissos.
        </p>`;
    }
  } catch (e) { /* silencioso: bloco opcional */ }
}

// ------------------------------------------------------------------ notícias

async function noticias() {
  try {
    const d = await json('/api/noticias');
    const lista = $('lista-noticias');
    lista.innerHTML = '';
    if (!d.itens.length) {
      lista.innerHTML = '<li class="carregando">sem notícias agora</li>';
      return;
    }
    for (const n of d.itens) {
      const li = document.createElement('li');
      const titulo = document.createElement('div');
      titulo.textContent = n.titulo;
      const fonte = document.createElement('span');
      fonte.className = 'fonte';
      fonte.textContent = n.fonte;
      li.append(titulo, fonte);
      lista.appendChild(li);
    }
  } catch (e) {
    $('lista-noticias').innerHTML = '<li class="carregando">notícias indisponíveis</li>';
  }
}

// --------------------------------------------------------------------- rede

function desdeQuando(iso) {
  if (!iso) return '';
  const minutos = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (minutos < 2) return 'agora';
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `há ${horas} h`;
  return `há ${Math.floor(horas / 24)} d`;
}

async function redeLocal() {
  try {
    const d = await json('/api/rede');
    // Sem DNS, ausência de app significa "não estou medindo" — e não
    // "ninguém está usando". A tela precisa dizer qual dos dois é.
    $('rede-contagem').textContent =
      (d.total ? `${d.online}/${d.total}` : '') + (d.dns ? '' : ' · sem dns');

    const lista = $('lista-rede');
    lista.innerHTML = '';

    if (!d.itens.length) {
      lista.innerHTML = '<li class="carregando">nenhum aparelho ainda</li>';
      return;
    }

    for (const a of d.itens) {
      const li = document.createElement('li');
      li.className = a.online ? 'no-ar' : 'fora';

      const nome = document.createElement('span');
      nome.className = 'aparelho';
      // Nome do aparelho vem da rede: sempre textContent, nunca innerHTML.
      nome.textContent = a.nome || a.fabricante || a.mac;

      const detalhe = document.createElement('span');
      detalhe.className = 'detalhe';

      // O app em uso vale mais que o IP: é a informação que se procura aqui.
      if (a.online && a.app_agora) {
        detalhe.classList.add('usando');
        detalhe.textContent = a.app_agora;
      } else {
        detalhe.textContent = a.online
          ? (a.eu ? 'este PC' : a.ip)
          : desdeQuando(a.visto_em);
      }

      li.append(nome, detalhe);
      lista.appendChild(li);
    }
  } catch (e) {
    $('lista-rede').innerHTML = '<li class="carregando">rede indisponível</li>';
  }
}

// -------------------------------------------------------------------- ciclo

relogio();
setInterval(relogio, 1000);

clima();
setInterval(clima, 15 * 60 * 1000);

noticias();
setInterval(noticias, 30 * 60 * 1000);

tarefas();
setInterval(tarefas, 60 * 1000);

integracoes();

redeLocal();
setInterval(redeLocal, 60 * 1000);
