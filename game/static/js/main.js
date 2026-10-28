const state = {
  token: localStorage.getItem('dots_token'),
  me: null, playerId: null, gameId: null, gameName: null,
  mapSize: 100, grid: new Map(), players: {},
  turn: 0, turnEndsAt: 0, selected: null,
  validTargets: [], hoveredTarget: null, ws: null,
  gameOver: false, reconnectPending: false, reconnectAttempts: 0,
  disconnected: {}, sprites: new Map(), badges: new Map(),
  strengthMap: new Map(), lobbyGameInfo: null,
  muted: localStorage.getItem('dots_muted') === '1',
  warned10Sec: false, warned20Pct: false, lastAdTurn: 0,
  iClickedThisTurn: false,
};

// Перехват URL-параметров (после OAuth-редиректа)
const _urlParams = new URLSearchParams(window.location.search);
const _yandexToken = _urlParams.get('yandex_token');
const _yandexLinked = _urlParams.get('yandex_linked');
const _yandexError = _urlParams.get('yandex_error');

if (_yandexToken) {
  state.token = _yandexToken;
  localStorage.setItem('dots_token', _yandexToken);
  window.history.replaceState({}, '', '/');
}

const POWERUP_COST = 1;
const winReasons = {
  'dominance_70': 'Захвачено 70% площади карты',
  'opponents_dead_or_surrendered': 'Все противники уничтожены или сдались',
  'last_player_with_cells': 'Остался единственным игроком на карте',
  'opponent_surrendered': 'Соперник сдался',
  '1v1_absent_5': 'Соперник пропустил 5 туров подряд (1v1)',
  'both_absent_5': 'Оба игрока пропустили 5 туров (ничья)',
  'stuck_opponents': 'Соперник полностью заблокирован (не может ходить)',
  'both_stuck': 'Оба игрока заблокированы (ничья)',
  'all_surrendered': 'Все игроки сдались (ничья)',
  'no_cells_left': 'На карте не осталось клеток'
};

const $ = id => document.getElementById(id);
const escape = s => String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));

/* === AVATARS === */
const _FALLBACK_AVATAR = 'data:image/svg+xml;utf8,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none"><circle cx="50" cy="30" r="15" stroke="#e6e6e6" stroke-width="8"/><path d="M20 80 Q20 60 50 60 Q80 60 80 80" stroke="#e6e6e6" stroke-width="8" stroke-linecap="round"/></svg>'
);

function renderAvatar(url, size = 24) {
  if (url) {
    return `<img src="${url}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;vertical-align:middle;margin-right:6px;background:#2a2a38;flex-shrink:0;" onerror="this.onerror=null; this.src='${_FALLBACK_AVATAR}';" alt="">`;
  }
  return `<img src="${_FALLBACK_AVATAR}" style="width:${size}px;height:${size}px;border-radius:50%;vertical-align:middle;margin-right:6px;background:#2a2a38;flex-shrink:0;" alt="">`;
}

/* === POLLING === */
let gamesPollTimer = null;
function startGamesPolling() {
  stopGamesPolling();
  gamesPollTimer = setInterval(() => {
    if ($('games-screen').classList.contains('active')) refreshGames();
  }, 3000);
}
function stopGamesPolling() {
  if (gamesPollTimer) { clearInterval(gamesPollTimer); gamesPollTimer = null; }
}

function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  $(id).classList.add('active');
  document.body.classList.toggle('in-game', id === 'game-screen');
  if (id === 'game-screen') setTimeout(() => resizePixi(), 0);
  if (id === 'games-screen') startGamesPolling();
  else stopGamesPolling();
}

function showModal(title, bodyHtml) {
  $('modal-title').textContent = title;
  $('modal-body').innerHTML = bodyHtml;
  $('modal-bg').classList.add('show');
}
$('modal-close').onclick = () => $('modal-bg').classList.remove('show');

let confirmCallback = null;
function customConfirm(title, body, onYes) {
  $('confirm-title').textContent = title;
  $('confirm-body').innerHTML = body;
  confirmCallback = onYes;
  $('confirm-modal').classList.add('show');
}
$('confirm-yes').onclick = () => { $('confirm-modal').classList.remove('show'); if (confirmCallback) confirmCallback(); confirmCallback = null; };
$('confirm-no').onclick = () => { $('confirm-modal').classList.remove('show'); confirmCallback = null; };

/* === AUTH === */
let authMode = 'login';
$('tab-login').onclick = () => { authMode = 'login'; $('tab-login').classList.add('active'); $('tab-register').classList.remove('active'); $('btn-auth').textContent = 'Войти'; };
$('tab-register').onclick = () => { authMode = 'register'; $('tab-register').classList.add('active'); $('tab-login').classList.remove('active'); $('btn-auth').textContent = 'Создать аккаунт'; };

$('btn-auth').onclick = async () => {
  const username = $('in-username').value.trim();
  const password = $('in-password').value;
  $('auth-err').textContent = '';
  try {
    const res = await api('/api/' + authMode, { method: 'POST', body: JSON.stringify({ username, password }) });
    state.token = res.token;
    localStorage.setItem('dots_token', res.token);
    await enterMenu();
  } catch (e) { $('auth-err').textContent = e.message; }
};

$('btn-logout').onclick = () => {
  customConfirm('Выйти?', 'Вы выйдете из аккаунта.', () => doLogout());
};

function doLogout() {
  state.token = null; localStorage.removeItem('dots_token');
  if (state.ws) { state.ws.close(); state.ws = null; }
  stopGamesPolling();
  showScreen('auth-screen');
}

async function enterMenu() {
  try { state.me = await api('/api/me'); }
  catch { state.token = null; localStorage.removeItem('dots_token'); return showScreen('auth-screen'); }
  document.cookie = `dots_uid=${state.me.user_id}; path=/; SameSite=Lax`;
  renderProfile(); refreshLeaderboard(); refreshTournaments();

  // Уведомления после OAuth-привязки
  if (_yandexLinked === '1') {
    setTimeout(() => showModal('Готово', 'Яндекс успешно привязан к вашему аккаунту.'), 200);
    window.history.replaceState({}, '', '/');
  } else if (_yandexError === 'already_linked') {
    setTimeout(() => showModal('Ошибка', 'Этот Яндекс уже привязан к другому аккаунту.'), 200);
    window.history.replaceState({}, '', '/');
  } else if (_yandexError === 'need_login') {
    setTimeout(() => showModal('Ошибка', 'Сначала войдите в аккаунт, затем привязывайте Яндекс.'), 200);
    window.history.replaceState({}, '', '/');
  }

  await showGamesScreen();
}

function renderProfile() {
  const m = state.me;
  $('my-elo').textContent = m.elo; $('my-name').textContent = m.username;
  $('my-dts').innerHTML = `${ICONS.dts(32)} ${m.global_dts || 0}`;
  $('my-wins').textContent = m.games_won; $('my-played').textContent = m.games_played;
}

/* === LEADERBOARD === */
async function refreshLeaderboard() {
  try {
    const data = await api('/api/leaderboard');
    const rows = data.top || data;
    const renderInto = (el) => {
      if (!el) return;
      el.innerHTML = '';
      rows.forEach((r, i) => {
        const d = document.createElement('div');
        d.className = 'lb-row';
        if (state.me && r.username === state.me.username) d.classList.add('lb-you');

        d.innerHTML = `<span class="lb-pos">${i + 1}.</span>
          <span class="lb-name" style="display:flex; align-items:center; gap:2px;">
            <a href="javascript:void(0)" onclick="openPublicProfile(${r.user_id})"
               style="display:flex; align-items:center; gap:2px; color:inherit; text-decoration:none; cursor:pointer; flex:1; overflow:hidden;"
               title="Профиль ${escape(r.username)}">
              ${renderAvatar(r.avatar_url, 26)}
              <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escape(r.username)}</span>
            </a>
          </span>
          <span class="lb-games">${ICONS.trophy(32)} ${r.games_won || 0}</span>
          <span class="lb-dts">${ICONS.dts(32)}${r.global_dts || 0}</span>`;
        el.appendChild(d);
      });
    };
    renderInto($('leaderboard'));
    renderInto($('leaderboard-games'));

    const pinnedEl = $('my-rank-pinned');
    const myRankRowEl = $('my-rank-row');

    if (data.is_in_top === false && state.me) {
        const d = document.createElement('div');
        d.className = 'lb-row lb-you';
        d.innerHTML = `<span class="lb-pos">${data.my_rank}.</span>
          <span class="lb-name" style="display:flex; align-items:center; gap:2px;">
            ${renderAvatar(state.me.avatar_url, 26)}
            ${escape(state.me.username)}
          </span>
          <span class="lb-games">${ICONS.trophy(32)} ${state.me.games_won || 0}</span>
          <span class="lb-dts">${ICONS.dts(32)}${state.me.global_dts || 0}</span>`;
        myRankRowEl.innerHTML = '';
        myRankRowEl.appendChild(d);
        pinnedEl.classList.add('show');
    } else {
        pinnedEl.classList.remove('show');
    }
  } catch (e) { console.error(e); }
}

/* === PROFILE MODAL (свой) === */
async function openProfileModal() {
  if (!state.me) return;
  const m = state.me;
  $('prof-name').textContent = m.username;
  $('prof-elo').textContent = m.elo;
  $('prof-dts').innerHTML = `${ICONS.dts(24)} ${m.global_dts || 0}`;
  $('prof-played').textContent = m.games_played || 0;
  $('prof-wins').textContent = m.games_won || 0;
  const wr = m.games_played > 0 ? ((m.games_won / m.games_played) * 100).toFixed(1) : '0.0';
  $('prof-winrate').textContent = `${wr}%`;
  $('prof-avatar-wrap').innerHTML = renderAvatar(m.avatar_url, 36);
  $('prof-username-hidden').value = m.username;

  const panel = $('prof-account-panel');
  if (panel) panel.style.display = 'block';

  const hasPass = !!m.has_password;
  $('password-status').textContent = hasPass
    ? '✓ Пароль установлен. Можно изменить ниже.'
    : 'Вход только через Яндекс. Вы можете задать пароль для входа по логину.';
  $('prof-old-pass').style.display = hasPass ? 'block' : 'none';
  $('prof-pass-err').textContent = '';
  $('prof-pass-err').style.color = '';
  $('prof-old-pass').value = '';
  $('prof-new-pass').value = '';
  $('prof-new-pass2').value = '';

  // Блок привязки Яндекса
  const hasYandex = !!m.yandex_linked;
  $('yandex-link-status').textContent = hasYandex
    ? '✓ Яндекс привязан. Вы можете входить через Яндекс на экране авторизации.'
    : 'Привяжите Яндекс, чтобы входить в игру в один клик.';
  $('btn-yandex-link').style.display = hasYandex ? 'none' : 'inline-flex';
  $('btn-yandex-unlink').style.display = hasYandex ? 'block' : 'none';

  if (state.token) {
    $('btn-yandex-link').href = `/api/auth/yandex?link=1&token=${encodeURIComponent(state.token)}`;
  }

  if (hasYandex && !m.has_password) {
    $('btn-yandex-unlink').disabled = true;
    $('btn-yandex-unlink').textContent = 'Отвязать (сначала задайте пароль)';
  } else {
    $('btn-yandex-unlink').disabled = false;
    $('btn-yandex-unlink').textContent = 'Отвязать Яндекс';
  }

  $('profile-modal').classList.add('show');
  loadMyMatches();
}
window.openProfileModal = openProfileModal;

function closeProfileModal() {
  $('profile-modal').classList.remove('show');
}
window.closeProfileModal = closeProfileModal;

/* === PROFILE MODAL (чужой) === */
async function openPublicProfile(userId) {
  if (!userId) return;
  if (state.me && state.me.user_id === userId) {
    openProfileModal();
    return;
  }
  try {
    const u = await api('/api/user_profile/' + userId);
    $('prof-name').textContent = u.username;
    $('prof-elo').textContent = u.elo;
    $('prof-dts').innerHTML = `${ICONS.dts(24)} ${u.global_dts || 0}`;
    $('prof-played').textContent = u.games_played || 0;
    $('prof-wins').textContent = u.games_won || 0;
    const wr = u.games_played > 0 ? ((u.games_won / u.games_played) * 100).toFixed(1) : '0.0';
    $('prof-winrate').textContent = `${wr}%`;
    $('prof-avatar-wrap').innerHTML = renderAvatar(u.avatar_url, 36);

    const panel = $('prof-account-panel');
    if (panel) panel.style.display = 'none';

    $('profile-modal').classList.add('show');
    loadUserMatches(userId);
  } catch (e) {
    showModal('Ошибка', escape(e.message));
  }
}
window.openPublicProfile = openPublicProfile;

/* === MATCHES LIST === */
function _renderMatchesInto(tbody, matches) {
  tbody.innerHTML = '';
  if (!matches || !matches.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="games-empty">Нет завершённых матчей</td></tr>';
    return;
  }
  for (const match of matches) {
    const tr = document.createElement('tr');
    const d = new Date(match.date * 1000);
    const dateStr = d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    const resText = match.is_winner
      ? '<span style="color:#55ff55; font-weight:bold;">🏆 Победа</span>'
      : '<span style="color:#8b8b9b;">Поражение</span>';
    tr.innerHTML = `
      <td style="font-size:11px; color:#8b8b9b;">${dateStr}</td>
      <td><span class="size-badge">${match.size}</span></td>
      <td style="color:#9eb8ff; font-weight:bold;">${match.my_cells}</td>
      <td>${resText}</td>`;
    tbody.appendChild(tr);
  }
}

async function loadMyMatches() {
  const tbody = $('prof-history-body');
  tbody.innerHTML = '<tr><td colspan="4" class="games-empty">Загрузка...</td></tr>';
  try {
    const data = await api('/api/my_matches');
    _renderMatchesInto(tbody, data.matches);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="games-empty" style="color:#ff6666;">Ошибка: ${escape(e.message)}</td></tr>`;
  }
}

async function loadUserMatches(userId) {
  const tbody = $('prof-history-body');
  tbody.innerHTML = '<tr><td colspan="4" class="games-empty">Загрузка...</td></tr>';
  try {
    const data = await api('/api/user_matches/' + userId);
    _renderMatchesInto(tbody, data.matches);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="games-empty" style="color:#ff6666;">Ошибка: ${escape(e.message)}</td></tr>`;
  }
}
window.loadUserMatches = loadUserMatches;

/* === CHANGE PASSWORD === */
async function changePassword() {
  const oldPass = $('prof-old-pass').value;
  const newPass = $('prof-new-pass').value;
  const newPass2 = $('prof-new-pass2').value;
  $('prof-pass-err').textContent = '';
  $('prof-pass-err').style.color = '';

  if (!newPass) { $('prof-pass-err').textContent = 'Введите новый пароль'; return; }
  if (newPass !== newPass2) { $('prof-pass-err').textContent = 'Пароли не совпадают'; return; }
  if (newPass.length < 4) { $('prof-pass-err').textContent = 'Пароль должен быть не менее 4 символов'; return; }

  try {
    await api('/api/change_password', {
      method: 'POST',
      body: JSON.stringify({ old_password: oldPass, new_password: newPass }),
    });
    state.me = await api('/api/me');
    $('prof-pass-err').style.color = '#55ff55';
    $('prof-pass-err').textContent = '✓ Пароль обновлён';
    $('password-status').textContent = '✓ Пароль установлен. Можно изменить ниже.';
    $('prof-old-pass').value = '';
    $('prof-new-pass').value = '';
    $('prof-new-pass2').value = '';
    $('prof-old-pass').style.display = 'block';
    setTimeout(() => {
      $('prof-pass-err').style.color = '';
      $('prof-pass-err').textContent = '';
    }, 3000);
  } catch (e) {
    $('prof-pass-err').textContent = e.message;
  }
}
window.changePassword = changePassword;

async function unlinkYandex() {
  customConfirm(
    'Отвязать Яндекс?',
    'Вы больше не сможете входить через Яндекс. Вход останется по логину и паролю.',
    async () => {
      try {
        await api('/api/unlink_yandex', { method: 'POST' });
        state.me = await api('/api/me');
        openProfileModal(); // перерисовать профиль с обновлёнными данными
      } catch (e) {
        showModal('Ошибка', escape(e.message));
      }
    }
  );
}
window.unlinkYandex = unlinkYandex;

function logoutFromProfile() {
  customConfirm('Выйти?', 'Вы выйдете из аккаунта.', () => {
    closeProfileModal();
    doLogout();
  });
}
window.logoutFromProfile = logoutFromProfile;

/* === GAMES SCREEN === */
async function showGamesScreen() {
  showScreen('games-screen');
  await refreshGames();
  await refreshLeaderboard();
}

async function refreshGames() {
  try {
    const data = await api('/api/games');
    renderActiveGames(data.active || []);
    renderHistoryGames(data.history || []);
    updateCreateButton(data.active || []);
  } catch (e) { console.error(e); }
}

function myActiveGame(activeGames) {
  const myId = state.me?.user_id;
  if (!myId) return null;
  return activeGames.find(g => (g.players || []).some(p => p.user_id === myId)) || null;
}

function updateCreateButton(activeGames) {
  const btn = $('btn-create-game');
  const wrapper = $('create-btn-wrapper');
  const mine = myActiveGame(activeGames);
  if (mine) {
    btn.disabled = true; btn.textContent = '⚠ У вас есть активная игра';
    wrapper.title = 'У вас может быть только 1 активная игра';
  } else {
    btn.disabled = false; btn.textContent = '+ Создать игру'; wrapper.title = '';
  }
}

async function deleteGame(gameId) {
  customConfirm('Удалить игру?', 'Игра будет удалена, а ставка (если есть) вернётся на баланс.', async () => {
    try {
      await api(`/api/games/${gameId}/delete/`, { method: 'POST' });
      refreshGames();
      state.me = await api('/api/me');
      renderProfile();
    } catch (e) { showModal('Ошибка', escape(e.message)); }
  });
}
window.deleteGame = deleteGame;

function renderActiveGames(games) {
  const tbody = $('active-games-body');
  if (!games.length) { tbody.innerHTML = '<tr><td colspan="5" class="games-empty">Нет активных игр</td></tr>'; return; }
  tbody.innerHTML = '';
  const myId = state.me?.user_id;
  const myCurrentGame = games.find(g => (g.players || []).some(p => p.user_id === myId));

  for (const g of games) {
    const tr = document.createElement('tr');
    const statusBadge = g.status === 'waiting' ? '<span class="status-badge status-waiting">Открыта</span>'
      : g.status === 'playing' ? '<span class="status-badge status-playing">В игре</span>'
      : g.status === 'ending' ? '<span class="status-badge status-ending">Заверш.</span>'
      : `<span class="status-badge status-finished">${g.status}</span>`;
    const isMyGame = myCurrentGame && g.game_id === myCurrentGame.game_id;
    const freeSlots = g.max_players - g.players_count;
    let action = '';
    if (isMyGame) {
      action = `<div style="display:flex; gap:6px; align-items:center;">
        <button class="return-btn" onclick="returnToGame()">${ICONS.refresh(16)} Вернуться</button>
        ${g.players_count === 1 ? `<span style="cursor:pointer; display:flex;" onclick="deleteGame('${g.game_id}')" title="Удалить игру">${ICONS.cross(18)}</span>` : ''}
      </div>`;
    } else if (!myCurrentGame && (g.status === 'waiting' || (g.status === 'playing' && freeSlots > 0))) {
      const myDts = state.me?.global_dts || 0;
      if (g.entry_fee > myDts) {
        action = `<button class="ghost" style="padding:5px 10px;font-size:12px; opacity:0.4; cursor:not-allowed;" disabled title="Не хватает DTs">Присоединиться</button>`;
      } else {
        action = `<button class="ghost" style="padding:5px 10px;font-size:12px;" onclick="joinGame('${g.game_id}')">Присоединиться</button>`;
      }
    }
    const pct = typeof g.occupied_pct === 'number' ? g.occupied_pct : 0;
    let nameHtml = g.name ? `<span class="game-name">${escape(g.name)}</span>` : '';
    let feeHtml = g.entry_fee > 0 ? `<span class="game-fee">${ICONS.dts(20)} Взнос: ${g.entry_fee} / Банк: ${g.prize_pool || 0}</span>` : '';
    tr.innerHTML = `
      <td><span class="size-badge">${g.size_code}</span>${nameHtml}${feeHtml}</td>
      <td>${g.players_count}/${g.max_players}</td>
      <td>${statusBadge}</td>
      <td><span class="field-pct">${pct.toFixed(0)}%</span></td>
      <td>${action}</td>`;
    tbody.appendChild(tr);
  }
}

function renderHistoryGames(games) {
  const tbody = $('history-games-body');
  if (!games.length) { tbody.innerHTML = '<tr><td colspan="5" class="games-empty">Нет завершённых игр</td></tr>'; return; }
  tbody.innerHTML = '';
  const displayGames = games.slice(0, 15);
  for (const g of displayGames) {
    const tr = document.createElement('tr');
    let date = '—';
    if (g.ended_at) {
      const d = new Date(g.ended_at * 1000);
      date = d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    }
    tr.innerHTML = `
      <td><span class="size-badge">${g.size_code}</span></td>
      <td>${g.players_count}</td>
      <td style="font-weight:bold; color:#9eb8ff;">${g.turns || 0}</td>
      <td>${g.winner_name ? escape(g.winner_name) : '—'}</td>
      <td style="font-size:11px;color:#8b8b9b;">${date}</td>`;
    tbody.appendChild(tr);
  }
}

async function joinGame(gameId) {
  try {
    await api(`/api/games/${gameId}/join`, { method: 'POST' });
    state.me = await api('/api/me');
    renderProfile();
    state.disconnected = {};
    state.iClickedThisTurn = false;
    if (state.ws) { state.ws.close(); state.ws = null; }
    connectWS();
  } catch (e) { showModal('Ошибка', escape(e.message)); }
}
window.joinGame = joinGame;

async function returnToGame() {
  try {
    const data = await api('/api/games');
    const myId = state.me.user_id;
    const mine = (data.active || []).find(g => (g.players || []).some(p => p.user_id === myId));
    if (!mine) { showModal('Игра недоступна', 'Твоя игра уже завершилась или была удалена.'); await refreshGames(); return; }
    if (state.ws) { state.ws.close(); state.ws = null; }
    connectWS();
  } catch (e) { showModal('Ошибка', escape(e.message)); }
}
window.returnToGame = returnToGame;

/* === SURROUND BUTTONS === */
$('btn-help').onclick = () => $('help-modal').classList.add('show');
$('help-close').onclick = () => $('help-modal').classList.remove('show');

$('btn-surrender').onclick = () => {
  if (state.gameOver) return;
  const me = state.players[state.playerId];
  if (!me || me.surrendered) return;
  customConfirm('Сдаться?', `Клетки останутся на поле (полупрозрачные), другие смогут их захватить.<br>Ты получишь набранные ${ICONS.dts(20)}.`, () => {
    playSound('surrender');
    sendAction({ action: 'surrender' });
  });
};

function updateSoundBtn() {
  const btn = $('btn-sound');
  if (!btn) return;
  btn.innerHTML = state.muted ? ICONS.sound_off(20) : ICONS.sound_on(20);
  btn.title = state.muted ? 'Включить звук' : 'Отключить звук';
  btn.classList.toggle('muted', state.muted);
}
$('btn-sound').onclick = () => { state.muted = !state.muted; localStorage.setItem('dots_muted', state.muted ? '1' : '0'); updateSoundBtn(); };

/* === CREATE MODAL === */
let selectedSize = 'M';
document.querySelectorAll('.size-option').forEach(opt => {
  opt.addEventListener('click', (e) => {
    if (e.target.tagName === 'INPUT') {
      document.querySelectorAll('.size-option').forEach(o => o.classList.remove('selected'));
      opt.classList.add('selected'); selectedSize = opt.dataset.size; return;
    }
    e.preventDefault();
    document.querySelectorAll('.size-option').forEach(o => o.classList.remove('selected'));
    opt.classList.add('selected'); opt.querySelector('input').checked = true; selectedSize = opt.dataset.size;
  });
});

$('fee-toggle').onchange = (e) => {
  $('fee-container').style.display = e.target.checked ? 'block' : 'none';
  if (e.target.checked) {
    const maxFee = Math.floor((state.me?.global_dts || 0) * 0.5);
    const range = $('fee-range');
    range.min = 1;
    range.max = Math.max(1, maxFee);
    range.value = 1;
    $('fee-value').textContent = range.value;
    $('fee-max-val').textContent = range.max;
  }
};
$('fee-range').addEventListener('input', (e) => { $('fee-value').textContent = e.target.value; });
$('fee-range').addEventListener('change', (e) => { $('fee-value').textContent = e.target.value; });

$('btn-create-game').onclick = () => {
  $('create-err').textContent = '';
  $('ai-toggle').checked = false;
  $('fee-toggle').checked = false;
  $('fee-container').style.display = 'none';
  $('game-name-input').value = '';

  const dts = state.me?.global_dts || 0;

  // Показываем возможность игры с призовым фондом только если баланс от 5 DTs
  if (dts >= 5) {
    $('fee-toggle-wrapper').style.display = 'flex';
  } else {
    $('fee-toggle-wrapper').style.display = 'none';
  }

  $('create-modal').classList.add('show');
};
$('btn-cancel-create').onclick = () => $('create-modal').classList.remove('show');
$('btn-confirm-create').onclick = async () => {
  $('create-err').textContent = '';
  const allowAi = $('ai-toggle').checked;
  const name = $('game-name-input').value.trim() || null;
  const entryFee = $('fee-toggle').checked ? parseInt($('fee-range').value) : 0;
  try {
    await api('/api/games/create', { method: 'POST', body: JSON.stringify({ size: selectedSize, allow_ai: allowAi, name, entry_fee: entryFee }) });
    $('create-modal').classList.remove('show');
    if (state.ws) { state.ws.close(); state.ws = null; }
    connectWS();
  } catch (e) { $('create-err').textContent = e.message; }
};

/* === TOURNAMENTS === */
async function refreshTournaments() {
  try {
    const list = await api('/api/tournaments');
    const el = $('tourn-list'); el.innerHTML = '';
    if (!list.length) el.innerHTML = '<p style="color:#8b8b9b;font-size:13px;">Нет активных турниров</p>';
    list.forEach(t => {
      const row = document.createElement('div');
      row.className = 'tourn-item';
      const badge = t.status === 'registration' ? `<span class="badge open">открыт</span>` : `<span class="badge run">идёт</span>`;
      const btn = t.status === 'registration' ? `<button class="ghost" onclick="joinTournament(${t.id})">Войти</button>` : '';
      row.innerHTML = `<span>Турнир #${t.id} · ${t.cnt}/4</span>${badge}${btn}`;
      el.appendChild(row);
    });
  } catch (e) { console.error(e); }
}
async function joinTournament(id) {
  try {
    await api(`/api/tournaments/${id}/join`, { method: 'POST' });
    await refreshTournaments(); await showTournamentDetail(id);
    state.me = await api('/api/me');
  } catch (e) { showModal('Ошибка', escape(e.message)); }
}
window.joinTournament = joinTournament;

$('btn-create-tourn').onclick = async () => {
  try {
    const r = await api('/api/tournaments', { method: 'POST' });
    await refreshTournaments(); await showTournamentDetail(r.tournament_id);
    state.me = await api('/api/me');
  } catch (e) { showModal('Ошибка', escape(e.message)); }
};

async function showTournamentDetail(id) {
  try {
    const t = await api('/api/tournaments/' + id);
    const el = $('tourn-detail');
    let html = `<h3>Турнир #${t.id} — ${t.status}</h3>`;
    html += '<div style="font-size:13px;margin-bottom:8px;">';
    html += t.participants.map(p => `${escape(p.username)} (${p.elo})`).join(', ') + '</div>';
    const byRound = {};
    for (const m of t.matches) {
      if (!byRound[m.round]) byRound[m.round] = [];
      byRound[m.round].push(m);
    }
    for (const rnd of Object.keys(byRound).sort((a, b) => a - b)) {
      const name = rnd == 1 ? 'Полуфинал' : rnd == 2 ? 'Финал' : 'Раунд ' + rnd;
      html += `<div style="font-size:13px;color:#8b8b9b;margin-top:8px;">${name}</div>`;
      for (const m of byRound[rnd]) {
        const w = m.winner_name ? ` → 🏆 ${escape(m.winner_name)}` : '';
        html += `<div style="font-size:13px;padding:4px 0;">${escape(m.p1_name || '?')} vs ${escape(m.p2_name || '?')}${w}</div>`;
      }
    }
    el.innerHTML = html;
  } catch (e) { console.error(e); }
}

/* === WS === */
function setReconnectOverlay(show) { $('reconnect-overlay').classList.toggle('show', show); }
function connectWS() {
  if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws?token=${state.token}`);
  state.ws = ws;
  state.reconnectPending = false;
  let messageQueue = Promise.resolve();
  ws.onopen = () => {
    state.reconnectAttempts = 0; state.reconnectPending = false; setReconnectOverlay(false);
    ws.send(JSON.stringify({ type: 'join' }));
  };
  ws.onmessage = e => {
    try {
      const msg = JSON.parse(e.data);
      messageQueue = messageQueue.then(() => handleMessage(msg)).catch(err => console.error(err));
    } catch (err) { console.error("WS parse error", err); }
  };
  ws.onclose = () => {
    if (state.gameOver) return;
    if (state.ws !== ws) return;
    state.reconnectPending = true; state.reconnectAttempts++; setReconnectOverlay(true);
    const delay = Math.min(5000, 1000 * state.reconnectAttempts);
    setTimeout(() => { if (state.reconnectPending && !state.gameOver) connectWS(); }, delay);
  };
}

async function handleMessage(msg) {
  switch (msg.type) {
    case 'no_active_game':
      state.playerId = null; state.gameId = null;
      if ($('games-screen').classList.contains('active')) refreshGames(); else showGamesScreen();
      break;
    case 'joined':
      if (state.gameId && state.gameId !== msg.game_id) {
        const logEl = $('log'); if (logEl) logEl.innerHTML = ''; state.lastAdTurn = 0;
      }
      state.playerId = msg.player_id; state.gameId = msg.game_id;
      break;
    case 'lobby':
      renderLobby(msg.players, msg.game_info);
      showScreen('lobby-screen');
      break;
    case 'countdown':
      showScreen('lobby-screen');
      log(`Старт через ${msg.seconds}с`);
      break;
    case 'state':
      await enterGameWithPreloader(msg);
      break;
    case 'changes':
      applyChanges(msg);
      if (msg.actor && msg.players[msg.actor]) log(`${msg.players[msg.actor].name} сделал ход`);
      break;
    case 'game_ending':
      showFieldMessage('⚠ Игра завершается — мало свободных клеток', 'warn');
      log(`⚠ ${msg.message}`);
      break;
    case 'player_joined':
      state.players = msg.players; renderAll();
      if (msg.prize_pool !== undefined) {
          const prizeEl = $('field-prize');
          const prizeVal = $('prize-val');
          if (msg.prize_pool > 0) { prizeEl.style.display = 'flex'; prizeVal.innerHTML = `${ICONS.dts(28)} ${msg.prize_pool}`; }
          else { prizeEl.style.display = 'none'; }
      }
      showFieldMessage(`${msg.player_name || 'Игрок'} присоединился`, 'info');
      log(`${msg.player_name || 'Игрок'} присоединился`);
      break;
    case 'player_surrendered':
      state.players = msg.players;
      log(`${ICONS.flag(14)} ${msg.player_name} сдался`);
      showFieldMessage(`${ICONS.flag(18)} ${msg.player_name} сдался`, 'warn');
      if (msg.player_id) refreshPlayerCells(msg.player_id);
      redrawMasses();
      if (msg.player_id === state.playerId) {
        showModal('Ты сдался', `Игра продолжается без тебя.<br><br>Твои клетки остались на поле (полупрозрачные), другие могут их захватить.<br>Твои ${ICONS.dts(18)} будут зачислены в глобальный баланс.`);
        state.selected = null; clearTargets();
      }
      renderAll();
      break;
    case 'turn_end':
      playSound('turn_end');
      state.turn = msg.turn;
      if (msg.time_left !== undefined) state.turnEndsAt = Date.now() + msg.time_left * 1000;
      else state.turnEndsAt = Date.now() + Math.max(0, Math.min(60, msg.turn_ends_at - Date.now() / 1000)) * 1000;
      state.warned10Sec = false; state.iClickedThisTurn = false;
      if (msg.players) state.players = msg.players;
      for (const c of state.grid.values()) c.acted = false;
      for (const [key, c] of state.grid) updateSprite(key, c);
      if (state.selected) updateTargets();
      redrawMasses(); log(`— Тур ${msg.turn} —`); renderAll();
      if (msg.turn > 0 && msg.turn % 20 === 0 && state.lastAdTurn !== msg.turn) {
        state.lastAdTurn = msg.turn; $('ad-modal').classList.add('show');
      }
      break;
    case 'player_disconnected': {
      const p = state.players[msg.player_id];
      if (p && p.surrendered) { if (msg.players) state.players = msg.players; renderAll(); break; }
      state.disconnected[msg.player_id] = Date.now();
      if (msg.players) state.players = msg.players;
      renderAll();
      showFieldMessage(`${ICONS.hourglass(18)} ${msg.player_name || 'Игрок'} отошел`, 'warn');
      log(`${msg.player_name || 'Игрок'} отошел`);
      break;
    }
    case 'player_reconnected': {
      const p = state.players[msg.player_id];
      if (p && p.surrendered) { if (msg.players) state.players = msg.players; renderAll(); break; }
      delete state.disconnected[msg.player_id];
      if (msg.players) state.players = msg.players;
      renderAll();
      showFieldMessage(`${msg.player_name || 'Игрок'} вернулся`, 'success');
      log(`${msg.player_name || 'Игрок'} вернулся`);
      break;
    }
    case 'player_left':
      state.players = msg.players;
      delete state.disconnected[msg.player_id];
      renderAll();
      break;
    case 'game_over': {
      state.gameOver = true; state.turnEndsAt = 0;
      const timerEl = $('field-timer'); if (timerEl) timerEl.textContent = '0:00';
      const w = state.players[msg.winner];
      const myId = state.players[state.playerId]?.user_id;
      const iWon = w && state.players[state.playerId] && w.user_id === state.players[state.playerId].user_id;
      playSound(iWon ? 'win' : 'lose');
      const reasonText = winReasons[msg.win_reason] || 'Игра завершена';
      let body = '';
      if (msg.dts && myId && msg.dts[myId]) {
        const d = msg.dts[myId];
        if (iWon) body = `🏆 Вы победили!<br><br>Причина: ${reasonText}.<br><br>Вы получаете <b>+${d.earned}</b> ${ICONS.dts(24)} в глобальный баланс.`;
        else if (w) body = `Игру выиграл <b>${escape(w.name)}</b>.<br><br>Причина: ${reasonText}.<br><br>Вы получаете <b>+${d.earned}</b> ${ICONS.dts(24)}.`;
        else body = `Игра окончена вничью.<br><br>Причина: ${reasonText}.<br><br>Вы получаете <b>+${d.earned}</b> ${ICONS.dts(24)}.`;
      } else {
        if (iWon) body = `🏆 Вы победили!<br><br>Причина: ${reasonText}.`;
        else if (w) body = `Игру выиграл <b>${escape(w.name)}</b>.<br><br>Причина: ${reasonText}.`;
        else body = `Игра окончена вничью.<br><br>Причина: ${reasonText}.`;
      }
      showModal(w ? `🏆 ${w.name} побеждает!` : 'Игра окончена', body);
      setReconnectOverlay(false); renderAll();
      break;
    }
    case 'error':
      playSound('error'); log(`⚠ ${msg.message}`);
      if (msg.message === 'Не твоя точка') {
        state.selected = null; clearTargets();
        if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify({ type: 'join' }));
      }
      break;
  }
}

function renderLobby(players, gameInfo) {
  state.lobbyGameInfo = gameInfo;
  const infoEl = $('lobby-game-info');
  if (gameInfo) {
    const nameHtml = gameInfo.name ? `<b>${escape(gameInfo.name)}</b> · ` : '';
    let feeHtml = gameInfo.entry_fee > 0 ? ` · <span style="color:#ffcc44; display:flex; align-items:center; gap:4px;">${ICONS.trophy(18)} Призовой фонд: ${gameInfo.prize_pool} ${ICONS.dts(18)}</span>` : '';
    infoEl.innerHTML = `${nameHtml}Размер: <b>${gameInfo.size_code}</b> (${gameInfo.map_size}×${gameInfo.map_size}) · Макс. игроков: <b>${gameInfo.max_players}</b> · AI: ${gameInfo.allow_ai ? '✅' : '❌'}${feeHtml}`;
  }
  const el = $('lobby-players'); el.innerHTML = '';
  for (const pid in players) {
    const p = players[pid];
    const aiBadge = p.is_ai ? ICONS.ai(18) : ICONS.player(18);
    const row = document.createElement('div');
    row.className = 'player-row';
    row.innerHTML = `<div class="player-dot" style="background:${p.color}"></div><div class="player-name">${escape(p.name)} ${aiBadge}</div>`;
    el.appendChild(row);
  }
  const count = Object.keys(players).length;
  const wrapper = $('lobby-btn-wrapper');
  const hint = $('lobby-hint');
  if (count > 1) {
    wrapper.innerHTML = `<span style="color: #9eb8ff; font-weight: bold; font-size: 14px; animation: pulse 1.5s infinite;">Игра запускается...</span>`;
    hint.textContent = "Подготовка поля...";
  } else {
    wrapper.innerHTML = `<button class="ghost" id="btn-leave-lobby" style="width:auto;" onclick="showGamesScreen()">${ICONS.list(18)} В Лобби</button>`;
    hint.textContent = "Игра начнётся автоматически при наборе 2+ игроков";
  }
}

$('btn-back-to-games').onclick = () => {
  if (state.gameOver) { showGamesScreen(); return; }
  const me = state.players[state.playerId];
  if (me && me.surrendered) { showGamesScreen(); return; }
  customConfirm('Выйти в лобби?', 'Ты будешь отмечен как отсутствующий после 3 пропущенных туров.<br>Вернуться в игру можно из списка игр — твоё состояние сохранится.', () => {
    if (state.ws) { state.ws.close(); state.ws = null; }
    showGamesScreen();
  });
};

function sendAction(a) { if (state.ws && state.ws.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify({ type: 'action', ...a })); }
function log(msg) {
  const el = $('log'); if (!el) return;
  const d = document.createElement('div'); d.innerHTML = msg;
  el.insertBefore(d, el.firstChild);
  while (el.children.length > 12) el.removeChild(el.lastChild);
}

function renderAll() {
  renderPlayers(); renderActions(); renderSelection(); renderScoreboard();
  renderFieldOverlay();
  const me = state.players[state.playerId];
  if (me && $('zoom-btn-dot')) $('zoom-btn-dot').style.background = me.color;
}

function renderFieldOverlay() {
  const me = state.players[state.playerId];
  const coins = me?.dts || 0;
  const moves = (me && me.surrendered) ? 0 : computeMovesLeft();
  const coinsEl = $('coins-val'); if (coinsEl) coinsEl.textContent = coins;
  const movesEl = $('moves-val'); if (movesEl) movesEl.textContent = moves;
  const movesWrap = $('field-moves'); if (movesWrap) movesWrap.classList.toggle('empty', moves === 0);
  const turnEl = $('field-turn-num'); if (turnEl) turnEl.textContent = state.turn;
}

function renderScoreboard() {
  const el = $('scoreboard'); if (!el) return;
  const total = MAP_SIZE * MAP_SIZE;
  const sorted = Object.values(state.players).sort((a, b) => b.count - a.count);
  el.innerHTML = '';
  for (const p of sorted) {
    const pct = ((p.count / total) * 100).toFixed(1);
    const div = document.createElement('div');
    div.className = 'score-item' + (p.id === state.playerId ? ' my-score' : '') + (p.surrendered ? ' surrendered' : '') + (p.absent ? ' absent' : '');
    div.innerHTML = `<div class="score-dot" style="background:${p.color}"></div><span>${p.count}</span><span style="font-size:11px;opacity:0.7;">${pct}%</span> ${p.surrendered ? ICONS.flag(12) : ''}`;
    el.appendChild(div);
  }
}

function renderPlayers() {
  const el = $('player-list'); el.innerHTML = '';
  const sorted = Object.values(state.players).sort((a, b) => b.count - a.count);
  for (const p of sorted) {
    const you = p.id === state.playerId ? ' (ты)' : '';
    const isDc = !!state.disconnected[p.id] || p.disconnected;
    const row = document.createElement('div');
    row.className = 'player-row' + (isDc ? ' dc' : '') + (p.surrendered ? ' surr' : '');
    const typeIcon = p.is_ai ? ICONS.ai(16) : ICONS.player(16);
    const surrBadge = p.surrendered ? `<span class="surr-badge">${ICONS.flag(12)}</span>` : '';
    let statusBadge = '';
    if (!p.surrendered) {
        if (p.absent) {
            statusBadge = `<span class="absent-badge" style="background: #4a1a1a; color: #ff8888;">${ICONS.stop(12)} отсутствует</span>`;
        } else if (isDc || p.missed_turns > 0) {
            if (!(p.id === state.playerId && state.iClickedThisTurn)) {
                statusBadge = `<span class="absent-badge">${ICONS.warning(12)} отошел</span>`;
            }
        }
    }
    row.innerHTML = `
      <div class="player-dot" style="background:${p.color}"></div>
      <div class="player-name">${escape(p.name)}${you} ${typeIcon} ${surrBadge}${statusBadge}</div>
      <div class="player-count">${p.count}</div>
      <div class="player-dts">${ICONS.dts(20)}${p.dts || 0}</div>`;
    el.appendChild(row);
  }
}

function renderActions() {
  const me = state.players[state.playerId];
  const movesLeft = (me && me.surrendered) ? 0 : computeMovesLeft();
  const dts = me?.dts || 0;
  const surrenderBtn = $('btn-surrender');
  if (surrenderBtn) surrenderBtn.disabled = !me || me.surrendered || state.gameOver;
  updateSelectedInfo();
  const actions = $('actions'); actions.innerHTML = '';
  if (state.gameOver || !state.selected || (me && me.surrendered)) return;
  const [x, y] = state.selected;
  const cell = state.grid.get(`${x},${y}`);
  if (!cell || cell.owner !== state.playerId || movesLeft <= 0 || cell.acted) return;
  const canAfford = dts >= POWERUP_COST;
  const b = document.createElement('button');
  b.className = 'action-btn';
  if (canAfford) {
    b.innerHTML = `⬆ Усилиться (+1) — ${POWERUP_COST} ${ICONS.dts(18)}`;
    b.onclick = () => { playSound('powerup'); sendAction({ action: 'powerup', from: [x, y] }); state.selected = null; clearTargets(); renderAll(); };
  } else {
    b.innerHTML = `⬆ Нужно ${POWERUP_COST} ${ICONS.dts(18)}`;
    b.style.opacity = '0.4'; b.style.pointerEvents = 'none';
  }
  actions.appendChild(b);
}

function handleCellClick(x, y) {
  if (state.gameOver) return;
  const me = state.players[state.playerId];
  if (!me || me.surrendered) return;
  ensureAudio();
  if (state.selected) {
    const target = state.validTargets.find(t => t.x === x && t.y === y);
    if (target) {
      const [sx, sy] = state.selected;
      if (target.type === 'expand') { playSound('expand'); sendAction({ action: 'expand', from: [sx, sy], to: [x, y] }); burstParticles(x, y, state.players[state.playerId].color); }
      else { playSound('attack'); sendAction({ action: 'attack', from: [sx, sy], to: [x, y] }); burstParticles(x, y, '#ffdddd'); }
      state.selected = null; clearTargets(); renderAll(); return;
    }
  }
  const cell = state.grid.get(`${x},${y}`);
  const movesLeft = computeMovesLeft();
  if (cell && cell.owner === state.playerId) {
    if (cell.acted || movesLeft <= 0) { state.selected = null; clearTargets(); renderAll(); return; }
    if (!state.iClickedThisTurn) {
        state.iClickedThisTurn = true;
        if (me.missed_turns > 0) me.missed_turns = 0;
        renderPlayers();
    }
    playSound('select'); state.selected = [x, y]; updateTargets(); renderAll(); return;
  }
  state.selected = null; clearTargets(); renderAll();
}

function updateSelectedInfo() {
  const info = $('selected-info'); if (!info) return;
  if (state.gameOver) { info.innerHTML = 'Игра окончена'; return; }
  const me = state.players[state.playerId];
  if (me && me.surrendered) { info.innerHTML = 'Ты сдался — наблюдение'; return; }
  if (!state.selected) { info.innerHTML = 'Кликни по своей точке'; return; }
  const [x, y] = state.selected;
  const cell = state.grid.get(`${x},${y}`);
  if (!cell || cell.owner !== state.playerId) { info.innerHTML = ''; return; }
  if (state.hoveredTarget && state.hoveredTarget.type === 'attack') {
    const enemy = state.grid.get(`${state.hoveredTarget.x},${state.hoveredTarget.y}`);
    if (enemy) {
      const { myNew, enemyNew, captured } = calcAttackOutcome(cell.strength, enemy.strength);
      const enemyPlayer = state.players[enemy.owner];
      const surrNote = enemyPlayer && enemyPlayer.surrendered ? `<br><span style="color:#ff8888;font-size:10px;">${ICONS.warning(12)} Сдался</span>` : '';
      info.innerHTML = `<div class="preview-box"><div class="preview-title">${ICONS.sword(14)} Атака → (${state.hoveredTarget.x}, ${state.hoveredTarget.y})</div><div class="row"><span>Ты:</span><span><b>${cell.strength}</b> → <b class="val-down">${myNew}</b></span></div><div class="row"><span>Враг:</span><span><b>${enemy.strength}</b> → <b class="val-down">${enemyNew}</b></span></div><div class="${captured ? 'captured' : 'not-captured'}">${captured ? ICONS.check(16) + ' Захват!' : 'Захвата нет'}</div>${surrNote}</div>`;
      return;
    }
  }
  const movesLeft = computeMovesLeft();
  const inner = isInner(x, y, state.playerId);
  let hint = '';
  if (cell.acted) hint = '<br><span style="color:#f66;">— уже ходила</span>';
  else if (movesLeft <= 0) hint = '<br><span style="color:#f66;">— ходы кончились</span>';
  else if (state.validTargets.length > 0) hint = '<br><span style="color:#8b8b9b;">Наведи на соседнюю</span>';
  else if (inner) hint = '<br><span style="color:#8b8b9b;">— внутренняя, только усилить</span>';
  else hint = '<br><span style="color:#8b8b9b;">Нет соседей</span>';
  info.innerHTML = `Позиция: <b>(${x}, ${y})</b><br>Сила: <b>${cell.strength}</b>${hint}`;
}

function computeMovesLeft() {
  const me = state.players[state.playerId]; if (!me) return 0;
  if (me.surrendered) return 0;
  const moveBudget = 3 - me.moves_used;
  let active = 0;
  for (const c of state.grid.values()) if (c.owner === state.playerId && !c.acted) active++;
  return Math.min(moveBudget, active);
}
function calcAttackOutcome(myStr, enemyStr) {
  const defenderWasStronger = enemyStr > myStr;
  const enemyNew = enemyStr - 1;
  const myNew = defenderWasStronger ? Math.max(1, myStr - 1) : myStr;
  return { myNew, enemyNew, captured: enemyNew <= 0, defenderWasStronger };
}

let messageTimeout = null;
function showFieldMessage(text, kind = 'info') {
  const el = $('field-message'); if (!el) return;
  el.innerHTML = text;
  el.style.color = kind === 'warn' ? '#ffaa44' : kind === 'danger' ? '#ff6666' : kind === 'success' ? '#88ff88' : '#fff';
  el.classList.remove('hidden'); void el.offsetWidth; el.classList.add('show');
  clearTimeout(messageTimeout);
  messageTimeout = setTimeout(() => { el.classList.remove('show'); setTimeout(() => { if (!el.classList.contains('show')) el.classList.add('hidden'); }, 400); }, 4000);
}

function checkFieldThresholds() {
  if (state.warned20Pct) return;
  const total = Object.values(state.players).reduce((s, p) => s + p.count, 0);
  const totalField = MAP_SIZE * MAP_SIZE;
  if (total > 0 && total / totalField >= 0.80) {
    state.warned20Pct = true;
    showFieldMessage(`${ICONS.warning(18)} Осталось менее 20% свободного поля`, 'warn');
  }
}

$('btn-zoom-my').onclick = () => zoomToMyDots(true);
$('btn-close-ad').onclick = () => $('ad-modal').classList.remove('show');
$('modal-close').addEventListener('click', () => {
  $('modal-bg').classList.remove('show');
  if (state.gameOver) {
    state.gameOver = false;
    if (state.ws) { state.ws.close(); state.ws = null; }
    enterMenu();
  }
});

setInterval(() => {
  if (state.gameOver || !state.turnEndsAt) return;
  const left = Math.max(0, Math.ceil((state.turnEndsAt - Date.now()) / 1000));
  const timerEl = $('field-timer'); if (timerEl) timerEl.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
  const turnEl = $('field-turn-num'); if (turnEl) turnEl.textContent = state.turn;
  if (left <= 10 && left > 0 && !state.warned10Sec) {
    const me = state.players[state.playerId];
    if (me && !me.surrendered && me.moves_used < 3) {
      showFieldMessage(`${ICONS.clock(18)} Мало времени! Осталось ${left}с — сделай ход`, 'warn');
      state.warned10Sec = true;
    }
  }
}, 250);

(async () => {
  initStaticIcons();
  updateSoundBtn();
  if (state.token) {
    try { await enterMenu(); } catch { showScreen('auth-screen'); }
  } else {
    showScreen('auth-screen');
  }
})();