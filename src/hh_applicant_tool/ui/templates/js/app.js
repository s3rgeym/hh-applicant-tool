const _sectionLoaders = {
    dashboard: loadDashboard,
    resumes: loadResumes,
    negotiations: loadNegotiations,
    statistics: loadStatistics,
    settings: loadConfig,
};

function navigate(sectionId) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.sidebar-link').forEach(l => l.classList.remove('active'));

    const section = document.getElementById(sectionId);
    if (section) section.classList.add('active');

    const link = document.querySelector(`[data-section="${sectionId}"]`);
    if (link) link.classList.add('active');

    const loader = _sectionLoaders[sectionId];
    if (loader) loader();
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast ' + type + ' show';
    setTimeout(() => toast.classList.remove('show'), 3500);
}

let _authInProgress = false;

function _setAuthButtons({ authorized, authRunning }) {
    const btnLogin = document.getElementById('btn-login');
    const btnRelogin = document.getElementById('btn-relogin');
    const btnLogout = document.getElementById('btn-logout');
    const btnRefresh = document.getElementById('btn-refresh-status');

    [btnLogin, btnRelogin, btnLogout, btnRefresh].forEach(b => b && b.classList.add('hidden'));
    if (authRunning) {
        if (btnRefresh) btnRefresh.classList.remove('hidden');
        return;
    }
    if (authorized) {
        if (btnRelogin) btnRelogin.classList.remove('hidden');
        if (btnLogout) btnLogout.classList.remove('hidden');
    } else {
        if (btnLogin) btnLogin.classList.remove('hidden');
    }
}

function _renderAuthError(reason, errMsg) {
    const errEl = document.getElementById('auth-error');
    if (!errEl) return;
    if (!reason || reason === 'no_token') {
        errEl.classList.add('hidden');
        errEl.textContent = '';
        return;
    }
    let text = '';
    if (reason === 'token_invalid') {
        text = 'Сохранённый токен недействителен и был удалён. Войдите заново.';
    } else if (reason === 'error') {
        text = 'Ошибка проверки авторизации: ' + (errMsg || 'неизвестная');
    }
    if (text) {
        errEl.textContent = text;
        errEl.classList.remove('hidden');
    } else {
        errEl.classList.add('hidden');
    }
}

async function loadDashboard() {
    const dot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const userName = document.getElementById('user-name');

    try {
        const status = await pywebview.api.get_status();
        _authInProgress = !!status.auth_running;

        if (status.auth_running) {
            dot.className = 'status-dot offline';
            statusText.textContent = 'Авторизация...';
            userName.textContent = 'Войдите в окне браузера';
            _renderAuthError(null);
            _setAuthButtons({ authorized: false, authRunning: true });
            return;
        }

        if (status.authorized) {
            dot.className = 'status-dot online';
            statusText.textContent = 'Авторизован';
            const u = status.user;
            userName.textContent = [u.last_name, u.first_name].filter(Boolean).join(' ') || 'Пользователь';
            _renderAuthError(null);
            _setAuthButtons({ authorized: true, authRunning: false });
        } else {
            dot.className = 'status-dot offline';
            statusText.textContent = 'Не авторизован';
            userName.textContent = 'Войдите через hh.ru';
            _renderAuthError(status.reason, status.error);
            _setAuthButtons({ authorized: false, authRunning: false });
        }
    } catch (e) {
        console.error('loadDashboard error:', e);
        if (statusText) statusText.textContent = 'Не удалось проверить статус';
        _setAuthButtons({ authorized: false, authRunning: false });
    }
}

async function startLogin() {
    if (_authInProgress) {
        showToast('Авторизация уже выполняется', 'info');
        return;
    }
    _authInProgress = true;
    _setAuthButtons({ authorized: false, authRunning: true });
    const statusText = document.getElementById('status-text');
    const userName = document.getElementById('user-name');
    if (statusText) statusText.textContent = 'Запуск браузера...';
    if (userName) userName.textContent = 'Войдите в hh.ru в открывшемся окне';

    try {
        const result = await pywebview.api.start_login();
        if (result.status !== 'started') {
            _authInProgress = false;
            showToast(result.message || 'Не удалось запустить авторизацию', 'error');
            const errEl = document.getElementById('auth-error');
            if (errEl && result.message) {
                errEl.textContent = result.message;
                errEl.classList.remove('hidden');
            }
            await loadDashboard();
        }
    } catch (e) {
        _authInProgress = false;
        showToast('Ошибка запуска авторизации', 'error');
        await loadDashboard();
    }
}

async function logout() {
    if (!confirm('Выйти из аккаунта? Токен будет удалён.')) return;
    try {
        await pywebview.api.logout();
        showToast('Вы вышли из аккаунта', 'info');
    } catch (e) {
        showToast('Ошибка выхода', 'error');
    }
    await loadDashboard();
    await loadResumes();
}

function onAuthEvent(event, message) {
    if (event === 'started') {
        _authInProgress = true;
        const statusText = document.getElementById('status-text');
        const userName = document.getElementById('user-name');
        if (statusText) statusText.textContent = 'Авторизация...';
        if (userName) userName.textContent = message || 'Войдите в hh.ru в открывшемся окне';
        _setAuthButtons({ authorized: false, authRunning: true });
    } else if (event === 'done') {
        _authInProgress = false;
        showToast(message || 'Авторизация прошла успешно', 'success');
        loadDashboard();
        loadResumes();
    } else if (event === 'error') {
        _authInProgress = false;
        showToast(message || 'Ошибка авторизации', 'error');
        const errEl = document.getElementById('auth-error');
        if (errEl) {
            errEl.textContent = message || 'Ошибка авторизации';
            errEl.classList.remove('hidden');
        }
        loadDashboard();
    }
}

// ========== Резюме ==========

async function loadResumes() {
    const grid = document.getElementById('resumes-grid');
    grid.innerHTML = '<div class="card text-center text-gray-400 text-sm col-span-2"><div class="spinner mx-auto mb-2"></div>Загрузка резюме...</div>';

    try {
        const resumes = await pywebview.api.get_resumes();
        if (!resumes || resumes.length === 0) {
            grid.innerHTML = '<div class="card text-center text-gray-400 text-sm col-span-2">Нет резюме</div>';
            return;
        }
        grid.innerHTML = resumes.map(r => {
            const status = r.status ? r.status.id : 'not_published';
            const statusName = r.status ? r.status.name : 'не опубликовано';
            const counters = r.counters || {};
            const views = (counters.total_views || 0);
            const newViews = (counters.new_views || 0);
            const invites = (counters.invitations || 0);
            const url = safeUrl(r.alternate_url || r.url || '');
            return `<div class="resume-card">
                <div class="flex items-start justify-between gap-2">
                    <div class="resume-card-title">${escapeHtml(r.title || 'Без названия')}</div>
                    <span class="resume-badge ${escapeHtml(status)}">${escapeHtml(statusName)}</span>
                </div>
                <div class="resume-card-meta">
                    <span class="resume-counter">&#128065; ${views} просмотров${newViews > 0 ? ` <span style="color:#2563eb">(+${newViews} новых)</span>` : ''}</span>
                    <span class="resume-counter">&#128231; ${invites} приглашений</span>
                </div>
                <div class="flex items-center justify-between mt-1">
                    <span class="text-xs text-gray-400">ID: ${escapeHtml(r.id)}</span>
                    ${url !== '#' ? `<a href="${url}" target="_blank" rel="noopener noreferrer" class="text-xs text-blue-500 hover:text-blue-700">Открыть на hh.ru ↗</a>` : ''}
                </div>
            </div>`;
        }).join('');

        // Заполняем select выбора резюме в форме поиска
        const sel = document.getElementById('resume-id-select');
        if (sel) {
            const selectedResumeId = sel.value;
            sel.innerHTML = '<option value="">Автовыбор (первое опубликованное)</option>';
            resumes.forEach(r => {
                const opt = document.createElement('option');
                opt.value = r.id;
                opt.textContent = (r.title || 'Без названия') + ' — ' + (r.status ? r.status.name : '');
                sel.appendChild(opt);
            });
            if (selectedResumeId) {
                const hasSelectedOption = Array.from(sel.options).some(
                    opt => opt.value === selectedResumeId
                );
                if (hasSelectedOption) {
                    sel.value = selectedResumeId;
                }
            }
        }
    } catch (e) {
        grid.innerHTML = '<div class="card text-center text-red-400 text-sm col-span-2">Ошибка загрузки резюме</div>';
    }
}

function _getDeep(obj, path) {
    return path.split('.').reduce((o, k) => (o != null ? o[k] : undefined), obj);
}

function _setDeep(target, path, value) {
    const keys = path.split('.').filter(Boolean);
    let cursor = target;
    keys.forEach((key, index) => {
        if (index === keys.length - 1) {
            cursor[key] = value;
            return;
        }
        if (!cursor[key] || typeof cursor[key] !== 'object' || Array.isArray(cursor[key])) {
            cursor[key] = {};
        }
        cursor = cursor[key];
    });
}

function _parseConfigValue(input) {
    const type = input.dataset.configType || 'string';
    if (type === 'boolean') return input.checked;
    if (type === 'number') {
        const num = Number(input.value);
        return Number.isNaN(num) ? input.value : num;
    }
    if (type === 'null') {
        const value = input.value.trim().toLowerCase();
        return value === '' || value === 'null' ? null : input.value;
    }
    if (type === 'array') {
        const raw = input.value.trim();
        if (raw === '') return [];
        try {
            return JSON.parse(raw);
        } catch (_) {
            return raw.split(',').map(item => item.trim()).filter(Boolean);
        }
    }
    return input.value;
}

async function loadConfig() {
    try {
        const config = await pywebview.api.get_config();
        document.querySelectorAll('#config-fields [data-config-key]').forEach(input => {
            const val = _getDeep(config, input.dataset.configKey);
            if (val === undefined || val === null) return;
            if (val === '***') {
                input.placeholder = '● установлен (введите новый для изменения)';
                return;
            }
            if (input.type === 'checkbox') {
                input.checked = Boolean(val);
            } else {
                input.value = String(val);
            }
        });
    } catch (e) {
        showToast('Ошибка загрузки конфигурации', 'error');
    }
}

async function saveConfig() {
    const inputs = document.querySelectorAll('#config-fields [data-config-key]:not([disabled])');
    const updates = {};
    inputs.forEach(input => {
        const isSecret = input.dataset.configSecret === 'true';
        const isEmpty = input.type === 'checkbox' ? false : input.value.trim() === '';
        if (isSecret && isEmpty) return;
        if (isEmpty) return;
        _setDeep(updates, input.dataset.configKey, _parseConfigValue(input));
    });
    try {
        const result = await pywebview.api.save_config(updates);
        if (result.status === 'ok') {
            showToast('Настройки сохранены', 'success');
        } else {
            showToast('Ошибка: ' + (result.message || 'неизвестная'), 'error');
        }
    } catch (e) {
        showToast('Ошибка сохранения', 'error');
    }
}

async function loadPresetsList() {
    try {
        const names = await pywebview.api.list_presets();
        const select = document.getElementById('preset-select');
        select.innerHTML = '<option value="">— Пресет —</option>';
        names.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('loadPresetsList error:', e);
    }
}

async function loadSelectedPreset() {
    const name = document.getElementById('preset-select').value;
    if (!name) return;
    try {
        const params = await pywebview.api.load_preset(name);
        if (params) {
            fillSearchForm(params);
            showToast('Пресет «' + name + '» загружен', 'info');
        }
    } catch (e) {
        showToast('Ошибка загрузки пресета', 'error');
    }
}

async function savePreset() {
    const name = prompt('Имя пресета:');
    if (!name) return;
    const params = collectSearchParams();
    try {
        const result = await pywebview.api.save_preset(name, params);
        if (result && result.status === 'ok') {
            await loadPresetsList();
            showToast('Пресет «' + name + '» сохранён', 'success');
        } else {
            const msg = (result && result.message) || 'Ошибка сохранения пресета';
            showToast(msg, 'error');
        }
    } catch (e) {
        showToast('Ошибка сохранения пресета', 'error');
    }
}

async function deleteSelectedPreset() {
    const name = document.getElementById('preset-select').value;
    if (!name) return;
    if (!confirm('Удалить пресет «' + name + '»?')) return;
    try {
        await pywebview.api.delete_preset(name);
        await loadPresetsList();
        showToast('Пресет удалён', 'success');
    } catch (e) {
        showToast('Ошибка удаления пресета', 'error');
    }
}

async function loadLastUsed() {
    try {
        const params = await pywebview.api.get_last_used_params();
        if (params) fillSearchForm(params);
    } catch (e) {}
}

function collectSearchParams() {
    const form = document.getElementById('search-form');
    const params = {};

    form.querySelectorAll('[data-param]').forEach(el => {
        const key = el.dataset.param;
        if (el.type === 'checkbox') {
            if (el.checked) params[key] = true;
        } else if (el.type === 'number') {
            const num = Number(el.value);
            if (el.value !== '' && !isNaN(num)) params[key] = num;
        } else if (el.dataset.type === 'json-array') {
        } else if (el.tagName === 'SELECT' || el.type === 'text' || el.type === 'date') {
            if (el.value !== '') params[key] = el.value;
        } else if (el.tagName === 'TEXTAREA') {
            if (el.value.trim() !== '') {
                if (el.dataset.multi === 'true') {
                    const vals = el.value.split('\n').map(s => s.trim()).filter(Boolean);
                    if (vals.length > 0) params[key] = vals;
                } else {
                    params[key] = el.value.trim();
                }
            }
        }
    });

    const multiGroups = {};
    form.querySelectorAll('[data-multi-param]').forEach(el => {
        const key = el.dataset.multiParam;
        if (!multiGroups[key]) multiGroups[key] = [];
        if (el.checked) multiGroups[key].push(el.value);
    });
    Object.entries(multiGroups).forEach(([key, vals]) => {
        if (vals.length > 0) params[key] = vals;
    });

    form.querySelectorAll('input[data-param][data-type="json-array"]').forEach(el => {
        const key = el.dataset.param;
        try {
            const val = JSON.parse(el.value || '[]');
            if (val.length > 0) params[key] = val;
        } catch (_) {}
    });

    const hiddenExcl = form.querySelector('[data-param="excluded_filter"]');
    if (hiddenExcl && hiddenExcl.value) {
        params['excluded_filter'] = hiddenExcl.value;
    }

    return params;
}

function fillSearchForm(params) {
    const form = document.getElementById('search-form');

    form.querySelectorAll('[data-param]').forEach(el => {
        if (el.type === 'checkbox') el.checked = false;
        else el.value = '';
    });
    form.querySelectorAll('[data-multi-param]').forEach(el => { el.checked = false; });
    form.querySelectorAll('.lookup-tags').forEach(el => { el.innerHTML = ''; });
    if (_reloadTags) _reloadTags('');

    for (const [key, value] of Object.entries(params)) {
        const multiCbs = form.querySelectorAll(`[data-multi-param="${key}"]`);
        if (multiCbs.length > 0) {
            const vals = Array.isArray(value) ? value : [value];
            multiCbs.forEach(cb => { cb.checked = vals.includes(cb.value); });
            continue;
        }

        const lookupHidden = form.querySelector(`input[data-param="${key}"][data-type="json-array"]`);
        if (lookupHidden && Array.isArray(value)) {
            try {
                const parsed = Array.isArray(value) ? value : JSON.parse(value);
                lookupHidden.value = JSON.stringify(parsed);
                // Найдём lookup container и перерисуем теги
                const lookupId = key === 'area' ? 'area-lookup'
                    : key === 'professional_role' ? 'role-lookup'
                    : key === 'industry' ? 'industry-lookup' : null;
                if (lookupId) {
                    const tagsEl = document.getElementById(lookupId)?.querySelector('.lookup-tags');
                    if (tagsEl) {
                        tagsEl.innerHTML = '';
                        parsed.forEach(item => {
                            if (item && item.id) _addLookupTag(tagsEl, lookupHidden, item.id, item.name || item.id);
                        });
                    }
                }
            } catch (_) {}
            continue;
        }

        const el = form.querySelector(`[data-param="${key}"]`);
        if (!el) continue;
        if (el.type === 'checkbox') {
            el.checked = !!value;
        } else if (Array.isArray(value) && el.tagName === 'TEXTAREA') {
            el.value = value.join('\n');
        } else if (el.dataset.param !== 'excluded_filter') {
            el.value = String(value);
        }
    }

    if (params.excluded_filter && _reloadTags) _reloadTags(params.excluded_filter);
}

function updateProgress(current, total, message) {
    const bar = document.getElementById('progress-fill');
    const text = document.getElementById('progress-text');
    const log = document.getElementById('progress-log');

    if (bar && total > 0) bar.style.width = Math.round((current / total) * 100) + '%';
    if (text) {
        text.textContent = total > 0
            ? `${current} / ${total}` + (message ? ' — ' + message : '')
            : message || '';
    }
    if (log && message) {
        const line = document.createElement('div');
        line.textContent = message;
        log.appendChild(line);
        while (log.children.length > 300) log.removeChild(log.firstChild);
        log.scrollTop = log.scrollHeight;
    }
}

function resetProgress() {
    const bar = document.getElementById('progress-fill');
    const text = document.getElementById('progress-text');
    const log = document.getElementById('progress-log');
    if (bar) bar.style.width = '0%';
    if (text) text.textContent = '';
    if (log) log.innerHTML = '';
}

async function startApply() {
    const btn = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');
    const progressSection = document.getElementById('progress-section');

    btn.disabled = true;
    btn.textContent = 'Выполняется...';
    btnStop.classList.remove('hidden');
    progressSection.classList.remove('hidden');
    resetProgress();

    const params = collectSearchParams();

    try {
        const result = await pywebview.api.apply_vacancies(params);
        if (result.status === 'ok') {
            showToast('Поиск завершён успешно', 'success');
        } else if (result.status === 'cancelled') {
            showToast('Операция остановлена', 'info');
        } else {
            showToast('Ошибка: ' + (result.message || 'неизвестная'), 'error');
        }
    } catch (e) {
        showToast('Ошибка выполнения: ' + e, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '▶ Запустить поиск и отклики';
        btnStop.classList.add('hidden');
    }
}

async function cancelApply() {
    try {
        await pywebview.api.cancel_apply();
        showToast('Отправлен сигнал остановки...', 'info');
    } catch (e) {
        console.error('cancelApply error:', e);
    }
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function safeUrl(url) {
    const s = String(url || '').trim();
    return /^https?:\/\//i.test(s) ? s : '#';
}

const STATE_LABELS = {
    active: 'Активный',
    response: 'Ответ работодателя',
    invitation: 'Приглашение',
    discard: 'Отказ',
};

function stateClass(state) {
    return state in STATE_LABELS ? 'state-' + state : '';
}

async function loadNegotiations() {
    const tbody = document.getElementById('negotiations-tbody');
    tbody.innerHTML = '<tr><td colspan="4" class="text-center py-6"><div class="spinner mx-auto"></div></td></tr>';

    try {
        const items = await pywebview.api.get_negotiations_from_db();
        const filter = document.getElementById('neg-status-filter').value;
        const filtered = filter ? items.filter(n => n.state === filter) : items;

        if (filtered.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center py-8 text-gray-400 text-sm">Нет откликов. Нажмите «Синхронизировать с hh.ru» для загрузки.</td></tr>';
            return;
        }
        tbody.innerHTML = filtered.map(n => {
            const date = n.created_at ? n.created_at.substring(0, 10) : '—';
            const name = escapeHtml(n.vacancy_name || '—');
            const link = n.vacancy_url
                ? `<a href="${escapeHtml(safeUrl(n.vacancy_url))}" target="_blank" rel="noopener noreferrer">${name}</a>`
                : name;
            const label = STATE_LABELS[n.state] || n.state;
            return `<tr>
                <td class="whitespace-nowrap">${date}</td>
                <td>${link}</td>
                <td>${escapeHtml(n.employer_name || '—')}</td>
                <td><span class="state-badge ${stateClass(n.state)}">${escapeHtml(label)}</span></td>
            </tr>`;
        }).join('');
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center py-6 text-red-400 text-sm">Ошибка загрузки</td></tr>';
    }
}

async function refreshNegotiations() {
    showToast('Синхронизация с hh.ru...', 'info');
    try {
        const status = document.getElementById('neg-status-filter').value || 'active';
        const result = await pywebview.api.refresh_negotiations(status);
        if (result.status === 'ok') {
            showToast(`Загружено ${result.count} откликов`, 'success');
        } else {
            showToast('Ошибка: ' + (result.message || 'неизвестная'), 'error');
        }
    } catch (e) {
        showToast('Ошибка обновления откликов', 'error');
    }
    await loadNegotiations();
}

const REASON_LABELS = {
    ai_rejected: 'Отклонено AI-фильтром',
    excluded_filter: 'Фильтр исключений',
    blocked: 'Заблокирован',
};

async function loadStatistics() {
    try {
        const stats = await pywebview.api.get_statistics();
        if (!stats || Object.keys(stats).length === 0) {
            document.getElementById('stats-cards').innerHTML =
                '<p class="text-gray-400 text-sm col-span-4">Нет данных. Сначала выполните поиск или синхронизируйте отклики.</p>';
            return;
        }
        renderStatCards(stats);
        renderSkippedBars(stats.skipped_by_reason || {});
        renderDailyTable(stats.daily_negotiations || {}, stats.daily_skipped || {});
    } catch (e) {
        console.error('loadStatistics error:', e);
    }
}

function renderStatCards(stats) {
    const cards = document.getElementById('stats-cards');
    const byState = stats.by_state || {};
    const items = [
        { label: 'Всего откликов', value: stats.total_negotiations || 0, color: '#2563eb' },
        { label: 'Всего пропущено', value: stats.total_skipped || 0, color: '#9ca3af' },
        { label: 'Активных', value: byState.active || 0, color: '#2563eb' },
        { label: 'Приглашений', value: byState.invitation || 0, color: '#a16207' },
        { label: 'Ответов', value: byState.response || 0, color: '#16a34a' },
        { label: 'Отказов', value: byState.discard || 0, color: '#dc2626' },
    ];
    cards.innerHTML = items.map(i => `
        <div class="stat-card">
            <div class="stat-value" style="color:${i.color}">${i.value}</div>
            <div class="stat-label">${i.label}</div>
        </div>
    `).join('');
}

function renderSkippedBars(byReason) {
    const container = document.getElementById('stats-skipped-bars');
    const entries = Object.entries(byReason);
    if (entries.length === 0) {
        container.innerHTML = '<p class="text-gray-400 text-sm">Нет данных</p>';
        return;
    }
    const max = Math.max(...entries.map(e => e[1]));
    container.innerHTML = entries.map(([reason, count]) => {
        const label = REASON_LABELS[reason] || reason;
        const pct = max > 0 ? Math.round((count / max) * 100) : 0;
        return `<div class="bar-row">
            <span class="bar-label">${escapeHtml(label)}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
            <span class="bar-count">${count}</span>
        </div>`;
    }).join('');
}

function renderDailyTable(dailyNeg, dailySkipped) {
    const container = document.getElementById('stats-daily-table');
    const allDays = new Set([...Object.keys(dailyNeg), ...Object.keys(dailySkipped)]);
    const sorted = [...allDays].sort().reverse();

    if (sorted.length === 0) {
        container.innerHTML = '<p class="text-gray-400 text-sm">Нет данных</p>';
        return;
    }

    let html = '<table class="data-table w-full"><thead><tr><th>Дата</th><th>Откликов</th><th>Пропущено</th></tr></thead><tbody>';
    for (const day of sorted) {
        const neg = Number(dailyNeg[day]) || 0;
        const skip = Number(dailySkipped[day]) || 0;
        html += `<tr><td>${escapeHtml(day)}</td><td>${neg}</td><td>${skip}</td></tr>`;
    }
    html += '</tbody></table>';
    container.innerHTML = html;
}

function initTagInput() {
    const wrap = document.getElementById('excluded-filter-tags');
    if (!wrap) return;
    const input = wrap.querySelector('.tag-input-field');
    const hidden = document.querySelector('[data-param="excluded_filter"]');

    function syncHidden() {
        const pills = wrap.querySelectorAll('.tag-pill');
        hidden.value = Array.from(pills).map(p => p.dataset.value).join('|');
    }

    function addTag(word) {
        word = word.trim();
        if (!word) return;
        const existing = wrap.querySelectorAll('.tag-pill');
        for (const p of existing) if (p.dataset.value === word) return;
        const pill = document.createElement('span');
        pill.className = 'tag-pill';
        pill.dataset.value = word;
        pill.innerHTML = `${escapeHtml(word)}<button type="button">&times;</button>`;
        pill.querySelector('button').onclick = () => { pill.remove(); syncHidden(); };
        wrap.insertBefore(pill, input);
        syncHidden();
    }

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            addTag(input.value);
            input.value = '';
        }
        if (e.key === 'Backspace' && input.value === '') {
            const pills = wrap.querySelectorAll('.tag-pill');
            if (pills.length > 0) { pills[pills.length - 1].remove(); syncHidden(); }
        }
    });

    return function loadTagsFromValue(val) {
        wrap.querySelectorAll('.tag-pill').forEach(p => p.remove());
        const v = val !== undefined ? val : hidden.value;
        if (v) v.split('|').forEach(w => addTag(w));
    };
}

let _reloadTags = null;

const _lookupCache = {};

function _addLookupTag(tagsEl, hiddenEl, id, name) {
    for (const t of tagsEl.querySelectorAll('.tag-pill')) {
        if (t.dataset.value === String(id)) return;
    }
    const pill = document.createElement('span');
    pill.className = 'tag-pill';
    pill.dataset.value = String(id);
    pill.title = name;
    pill.innerHTML = `${escapeHtml(name.trim())}<button type="button">&times;</button>`;
    pill.querySelector('button').onclick = () => {
        pill.remove();
        _syncLookupHidden(tagsEl, hiddenEl);
    };
    tagsEl.appendChild(pill);
    _syncLookupHidden(tagsEl, hiddenEl);
}

function _syncLookupHidden(tagsEl, hiddenEl) {
    const items = Array.from(tagsEl.querySelectorAll('.tag-pill')).map(p => ({
        id: p.dataset.value,
        name: p.title,
    }));
    hiddenEl.value = JSON.stringify(items);
}

function initLookup(lookupId, tagsId, hiddenParam, apiMethod) {
    const container = document.getElementById(lookupId);
    if (!container) return;
    const searchInput = container.querySelector('.lookup-search');
    const tagsEl = document.getElementById(tagsId);
    const dropdown = container.querySelector('.lookup-dropdown');
    const hiddenEl = document.querySelector(`input[data-param="${hiddenParam}"]`);
    if (!searchInput || !tagsEl || !dropdown || !hiddenEl) return;

    let _loaded = false;
    let _all = [];

    async function ensureLoaded() {
        if (_loaded) return;
        if (_lookupCache[apiMethod]) {
            _all = _lookupCache[apiMethod];
            _loaded = true;
            return;
        }
        dropdown.innerHTML = '<div class="lookup-loading"><div class="spinner"></div> Загрузка из hh.ru...</div>';
        dropdown.classList.remove('hidden');
        try {
            const data = await pywebview.api[apiMethod]();
            _all = data || [];
            _lookupCache[apiMethod] = _all;
            _loaded = true;
        } catch (e) {
            dropdown.innerHTML = '<div class="lookup-loading" style="color:#dc2626">Ошибка загрузки</div>';
        }
    }

    function renderDropdown(query) {
        const q = query.toLowerCase().trim();
        const matches = q
            ? _all.filter(item => item.name.toLowerCase().includes(q)).slice(0, 50)
            : _all.slice(0, 80);

        if (matches.length === 0) {
            dropdown.innerHTML = '<div class="lookup-loading">Не найдено</div>';
            return;
        }
        const selectedIds = new Set(
            Array.from(tagsEl.querySelectorAll('.tag-pill')).map(p => p.dataset.value)
        );
        dropdown.innerHTML = matches.map(item => {
            const sel = selectedIds.has(String(item.id)) ? ' selected' : '';
            return `<div class="lookup-option${sel}" data-id="${escapeHtml(String(item.id))}" data-name="${escapeHtml(item.name.trim())}">${escapeHtml(item.name)}</div>`;
        }).join('');
        dropdown.querySelectorAll('.lookup-option').forEach(opt => {
            opt.addEventListener('mousedown', (e) => {
                e.preventDefault();
                const id = opt.dataset.id;
                const name = opt.dataset.name;
                if (opt.classList.contains('selected')) {
                    const existing = tagsEl.querySelector(`[data-value="${id}"]`);
                    if (existing) { existing.remove(); _syncLookupHidden(tagsEl, hiddenEl); }
                } else {
                    _addLookupTag(tagsEl, hiddenEl, id, name);
                }
                renderDropdown(searchInput.value);
            });
        });
    }

    searchInput.addEventListener('focus', async () => {
        await ensureLoaded();
        if (_loaded) {
            renderDropdown(searchInput.value);
            dropdown.classList.remove('hidden');
        }
    });

    searchInput.addEventListener('input', () => {
        if (_loaded) renderDropdown(searchInput.value);
    });

    searchInput.addEventListener('blur', () => {
        setTimeout(() => dropdown.classList.add('hidden'), 150);
    });
}

window.addEventListener('pywebviewready', () => {
    _reloadTags = initTagInput();
    initLookup('area-lookup', 'area-tags', 'area', 'get_areas');
    initLookup('role-lookup', 'role-tags', 'professional_role', 'get_professional_roles');
    initLookup('industry-lookup', 'industry-tags', 'industry', 'get_industries');
    loadDashboard();
    loadResumes();
    loadPresetsList();
    loadLastUsed();
});
