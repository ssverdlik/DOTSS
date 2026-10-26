const ICONS = {
  dts: (size = 20) => `<svg class="dts-icon" style="width:${size}px;height:${size}px;filter:drop-shadow(0 0 4px rgba(255,204,68,0.4));" viewBox="0 0 100 100"><circle cx="50" cy="50" r="32" stroke="#ffcc44" stroke-width="8" fill="none"/><line x1="12" y1="36" x2="88" y2="36" stroke="#ffffff" stroke-width="4" stroke-linecap="round"/><line x1="12" y1="64" x2="88" y2="64" stroke="#ffffff" stroke-width="4" stroke-linecap="round"/><text x="50" y="61" font-size="36" font-family="Arial, sans-serif" font-weight="900" fill="#ffcc44" text-anchor="middle" letter-spacing="1">DTs</text></svg>`,

  ai: (size = 16) => `<svg class="ai-icon" style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><rect x="20" y="30" width="60" height="50" rx="10" stroke="#9ec0ff" stroke-width="8"/><circle cx="35" cy="50" r="5" fill="#9ec0ff"/><circle cx="65" cy="50" r="5" fill="#9ec0ff"/><path d="M40 70 L60 70" stroke="#9ec0ff" stroke-width="6" stroke-linecap="round"/><path d="M50 30 L50 10" stroke="#9ec0ff" stroke-width="6" stroke-linecap="round"/><circle cx="50" cy="10" r="5" fill="#9ec0ff"/></svg>`,

  player: (size = 16) => `<svg class="player-icon" style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><circle cx="50" cy="30" r="15" stroke="#e6e6e6" stroke-width="8"/><path d="M20 80 Q20 60 50 60 Q80 60 80 80" stroke="#e6e6e6" stroke-width="8" stroke-linecap="round"/></svg>`,

  energy: (size = 20) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="#55ff55"><path d="M55 5 L15 55 L45 55 L35 95 L85 40 L55 40 Z"/></svg>`,

  trophy: (size = 20) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><path d="M30 20 H70 V50 Q70 70 50 70 Q30 70 30 50 Z" stroke="#ffcc44" stroke-width="6" fill="rgba(255,204,68,0.2)"/><path d="M30 30 H15 V40 Q15 55 30 55" stroke="#ffcc44" stroke-width="6"/><path d="M70 30 H85 V40 Q85 55 70 55" stroke="#ffcc44" stroke-width="6"/><path d="M50 70 V85 M35 85 H65" stroke="#ffcc44" stroke-width="6" stroke-linecap="round"/></svg>`,

  list: (size = 20) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><rect x="20" y="20" width="60" height="70" rx="8" stroke="#9eb8ff" stroke-width="6"/><rect x="35" y="10" width="30" height="20" rx="4" fill="#17171f" stroke="#9eb8ff" stroke-width="6"/><line x1="35" y1="45" x2="65" y2="45" stroke="#9eb8ff" stroke-width="6" stroke-linecap="round"/><line x1="35" y1="60" x2="65" y2="60" stroke="#9eb8ff" stroke-width="6" stroke-linecap="round"/><line x1="35" y1="75" x2="55" y2="75" stroke="#9eb8ff" stroke-width="6" stroke-linecap="round"/></svg>`,

  flag: (size = 20) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><path d="M30 15 V85" stroke="#ff8888" stroke-width="8" stroke-linecap="round"/><path d="M30 20 L75 35 L30 50 Z" fill="rgba(255,136,136,0.3)" stroke="#ff8888" stroke-width="6" stroke-linejoin="round"/></svg>`,

  target: (size = 24) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><circle cx="50" cy="50" r="35" stroke="#e6e6e6" stroke-width="6"/><circle cx="50" cy="50" r="15" fill="#e6e6e6"/><line x1="50" y1="5" x2="50" y2="20" stroke="#e6e6e6" stroke-width="6"/><line x1="50" y1="80" x2="50" y2="95" stroke="#e6e6e6" stroke-width="6"/><line x1="5" y1="50" x2="20" y2="50" stroke="#e6e6e6" stroke-width="6"/><line x1="80" y1="50" x2="95" y2="50" stroke="#e6e6e6" stroke-width="6"/></svg>`,

  sound_on: (size = 20) => `<svg style="width:${size}px;height:${size}px;" viewBox="0 0 100 100" fill="none"><path d="M20 35 H40 L60 15 V85 L40 65 H20 Z" stroke="#e6e6e6" stroke-width="6" stroke-linejoin="round"/><path d="M70 35 Q85 50 70 65" stroke="#e6e6e6" stroke-width="6" stroke-linecap="round"/><path d="M80 20 Q105 50 80 80" stroke="#e6e6e6" stroke-width="6" stroke-linecap="round"/></svg>`,

  sound_off: (size = 20) => `<svg style="width:${size}px;height:${size}px;" viewBox="0 0 100 100" fill="none"><path d="M20 35 H40 L60 15 V85 L40 65 H20 Z" stroke="#e6e6e6" stroke-width="6" stroke-linejoin="round"/><line x1="70" y1="35" x2="95" y2="65" stroke="#ff6666" stroke-width="6" stroke-linecap="round"/><line x1="95" y1="35" x2="70" y2="65" stroke="#ff6666" stroke-width="6" stroke-linecap="round"/></svg>`,

  help: (size = 20) => `<svg style="width:${size}px;height:${size}px;" viewBox="0 0 100 100" fill="none"><circle cx="50" cy="50" r="40" stroke="#9eb8ff" stroke-width="6"/><path d="M35 40 Q35 25 50 25 Q65 25 65 40 Q65 50 50 55 V65" stroke="#9eb8ff" stroke-width="8" stroke-linecap="round" fill="none"/><circle cx="50" cy="80" r="6" fill="#9eb8ff"/></svg>`,

  cross: (size = 20) => `<svg style="width:${size}px;height:${size}px;" viewBox="0 0 100 100" fill="none"><line x1="20" y1="20" x2="80" y2="80" stroke="#ff4444" stroke-width="12" stroke-linecap="round"/><line x1="80" y1="20" x2="20" y2="80" stroke="#ff4444" stroke-width="12" stroke-linecap="round"/></svg>`,

  refresh: (size = 20) => `<svg style="width:${size}px;height:${size}px;" viewBox="0 0 100 100" fill="none"><path d="M30 30 A30 30 0 1 1 20 60" stroke="#9eff9e" stroke-width="8" stroke-linecap="round" fill="none"/><polyline points="20,40 20,60 40,60" stroke="#9eff9e" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>`,

  warning: (size = 20) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><path d="M50 10 L90 85 H10 Z" stroke="#ffaa44" stroke-width="8" stroke-linejoin="round" fill="rgba(255,170,68,0.2)"/><line x1="50" y1="35" x2="50" y2="60" stroke="#ffaa44" stroke-width="8" stroke-linecap="round"/><circle cx="50" cy="75" r="5" fill="#ffaa44"/></svg>`,

  sword: (size = 20) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><path d="M80 20 L30 70" stroke="#ff8866" stroke-width="8" stroke-linecap="round"/><path d="M20 80 L30 70 L40 80 Z" fill="#ff8866"/><path d="M25 65 L35 75" stroke="#ff8866" stroke-width="6" stroke-linecap="round"/><path d="M20 80 L30 70 L40 80 Z" fill="#ff8866"/></svg>`,

  check: (size = 20) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><polyline points="20,50 40,70 80,30" stroke="#55ff55" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"/></svg>`,

  hourglass: (size = 16) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><path d="M25 20 H75 L50 50 L75 80 H25 L50 50 Z" stroke="#ffaa44" stroke-width="8" stroke-linejoin="round"/></svg>`,

  stop: (size = 16) => `<svg style="width:${size}px;height:${size}px;vertical-align:middle;" viewBox="0 0 100 100" fill="none"><circle cx="50" cy="50" r="40" stroke="#ffaa44" stroke-width="8"/><line x1="25" y1="25" x2="75" y2="75" stroke="#ffaa44" stroke-width="8"/></svg>`,

  map: (size = 20) => `<svg style="width:${size}px;height:${size}px;" viewBox="0 0 100 100" fill="none"><path d="M15 25 L35 15 L65 25 L85 15 V75 L65 85 L35 75 L15 85 Z" stroke="#9eb8ff" stroke-width="6" stroke-linejoin="round"/><line x1="35" y1="15" x2="35" y2="75" stroke="#9eb8ff" stroke-width="6"/><line x1="65" y1="25" x2="65" y2="85" stroke="#9eb8ff" stroke-width="6"/></svg>`,

  clock: (size = 20) => `<svg style="width:${size}px;height:${size}px;" viewBox="0 0 100 100" fill="none"><circle cx="50" cy="50" r="40" stroke="#9eb8ff" stroke-width="6"/><polyline points="50,25 50,50 65,65" stroke="#9eb8ff" stroke-width="8" stroke-linecap="round" fill="none"/></svg>`,

  mouse: (size = 20) => `<svg style="width:${size}px;height:${size}px;" viewBox="0 0 100 100" fill="none"><rect x="30" y="20" width="40" height="60" rx="20" stroke="#9eb8ff" stroke-width="6"/><line x1="50" y1="20" x2="50" y2="40" stroke="#9eb8ff" stroke-width="6"/></svg>`
};

// Функция для вставки иконок в статический HTML при загрузке
function initStaticIcons() {
  document.getElementById('coin-icon').innerHTML = ICONS.dts(32);
  document.getElementById('prize-icon').innerHTML = ICONS.trophy(24);
  document.getElementById('energy-icon').innerHTML = ICONS.energy(24);
  document.getElementById('fee-icon').innerHTML = ICONS.dts(20);

  document.getElementById('btn-help').innerHTML = `${ICONS.help(18)} КАК ИГРАТЬ`;
  document.getElementById('btn-leave-lobby').innerHTML = `${ICONS.list(18)} В Лобби`;
  document.getElementById('btn-back-to-games').innerHTML = `${ICONS.list(18)} В лобби`;
  document.getElementById('btn-surrender').innerHTML = `${ICONS.flag(18)} Сдаться`;

  document.getElementById('ai-label-icon').innerHTML = `${ICONS.ai(18)} Разрешить ИИ-игрока`;
  document.getElementById('fee-label-icon').innerHTML = `${ICONS.dts(18)} Игра с призовым фондом`;

  document.getElementById('help-goal-icon').innerHTML = `${ICONS.target(18)} Цель`;
  document.getElementById('help-map-icon').innerHTML = `${ICONS.map(18)} Размер`;
  document.getElementById('help-time-icon').innerHTML = `${ICONS.clock(18)} Туры`;
  document.getElementById('help-actions-icon').innerHTML = `${ICONS.sword(18)} Действия`;
  document.getElementById('help-capture-icon').innerHTML = `${ICONS.check(18)} Захват окружением`;
  document.getElementById('help-economy-icon').innerHTML = `${ICONS.dts(18)} Экономика`;
  document.getElementById('help-surrender-icon').innerHTML = `${ICONS.flag(18)} Сдаться`;
  document.getElementById('help-control-icon').innerHTML = `${ICONS.mouse(18)} Управление`;

  document.querySelectorAll('.dts-inline').forEach(el => {
    el.innerHTML = ICONS.dts(18);
  });

  const lbHeader = document.querySelector('#games-screen .panel:nth-child(3) p');
  if (lbHeader) lbHeader.innerHTML = `Топ-20 по ${ICONS.dts(16)}`;
}