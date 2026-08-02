const state = {
  plan: null,
  deferredInstallPrompt: null,
  apiKey: localStorage.getItem('actionHubApiKey') || '',
  pendingPlanId: sessionStorage.getItem('actionHubPendingPlanId') || '',
};

const $ = (id) => document.getElementById(id);
const inputText = $('inputText');

function toast(message, error = false) {
  const el = $('toast');
  el.textContent = message;
  el.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.className = 'toast'; }, 3200);
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.apiKey) headers['X-Action-Hub-Key'] = state.apiKey;
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get('content-type') || '';
  const body = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === 'object' ? body.detail || JSON.stringify(body) : body;
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return body;
}

function toLocalInput(value) {
  if (!value) return '';
  const parts = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date(value));
  const get = (type) => parts.find((part) => part.type === type)?.value || '';
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`;
}

function fromLocalInput(value) {
  return value ? new Date(`${value}:00+09:00`).toISOString() : null;
}

function formatWhen(value) {
  if (!value) return '날짜 없음';
  return new Intl.DateTimeFormat('ko-KR', {
    month: 'short', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit',
    timeZone: 'Asia/Seoul',
  }).format(new Date(value));
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));
}

function destinationLabel(value) {
  return ({ todoist: 'Todoist', github: 'GitHub', google_calendar: 'Google Calendar', local_ics: 'ICS 일정', none: '로컬 메모' })[value] || value;
}

function typeLabel(value) {
  return ({ event: '일정', todo: '할 일', project_task: '프로젝트 작업', reminder: '알림', note: '메모' })[value] || value;
}

async function downloadExport(path) {
  try {
    const headers = state.apiKey ? { 'X-Action-Hub-Key': state.apiKey } : {};
    const response = await fetch(path, { headers });
    if (!response.ok) {
      const body = await response.text();
      throw new Error(body || `다운로드 실패 (${response.status})`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = path.split('/').pop() || 'event.ics';
    anchor.target = '_blank';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (error) {
    toast(error.message, true);
  }
}

function renderPlan(plan) {
  state.plan = plan;
  $('planArea').hidden = false;
  $('planSummary').textContent = plan.summary;
  $('planStatus').textContent = plan.status;
  $('planStatus').className = `badge ${plan.status === 'completed' ? 'success' : plan.status === 'failed' ? 'failed' : ''}`;
  const container = $('itemsContainer');
  if (!plan.items.length) {
    container.innerHTML = '<div class="empty">실행 항목을 찾지 못했습니다. 문장을 조금 더 구체적으로 입력하세요.</div>';
    return;
  }
  container.innerHTML = plan.items.map((item) => `
    <article class="item-card ${item.needs_review ? 'review-required' : ''}" data-item-id="${item.id}">
      <div class="item-top">
        <input class="item-select" type="checkbox" ${['completed','rejected','skipped_duplicate','cancelled'].includes(item.state) ? '' : 'checked'} aria-label="항목 선택">
        <div>
          <div class="item-type">${escapeHtml(typeLabel(item.item_type))} → ${escapeHtml(destinationLabel(item.destination))}</div>
          <strong>${escapeHtml(item.title)}</strong>
        </div>
        <span class="badge ${item.needs_review ? 'review' : item.state === 'completed' ? 'success' : item.state === 'failed' ? 'failed' : ''}">${escapeHtml(item.needs_review ? '검토 필요' : item.state)}</span>
      </div>
      <div class="item-grid">
        <label>유형
          <select data-field="item_type">
            ${['event','todo','project_task','reminder','note'].map(x => `<option value="${x}" ${x === item.item_type ? 'selected' : ''}>${typeLabel(x)}</option>`).join('')}
          </select>
        </label>
        <label>보낼 곳
          <select data-field="destination">
            ${['todoist','github','google_calendar','local_ics','none'].map(x => `<option value="${x}" ${x === item.destination ? 'selected' : ''}>${destinationLabel(x)}</option>`).join('')}
          </select>
        </label>
        <label class="wide">제목
          <input data-field="title" value="${escapeHtml(item.title)}">
        </label>
        <label class="wide">설명
          <textarea data-field="description">${escapeHtml(item.description || '')}</textarea>
        </label>
        <label>시작
          <input data-field="start_at" type="datetime-local" value="${toLocalInput(item.start_at)}">
        </label>
        <label>종료
          <input data-field="end_at" type="datetime-local" value="${toLocalInput(item.end_at)}">
        </label>
        <label>예정일
          <input data-field="due_at" type="datetime-local" value="${toLocalInput(item.due_at)}">
        </label>
        <label>최종 마감
          <input data-field="deadline_at" type="datetime-local" value="${toLocalInput(item.deadline_at)}">
        </label>
        <label>프로젝트
          <input data-field="project" value="${escapeHtml(item.project || '')}" placeholder="#프로젝트">
        </label>
        <label>GitHub 저장소
          <input data-field="repository" value="${escapeHtml(item.repository || '')}" placeholder="owner/repo">
        </label>
        <label>담당자
          <input data-field="assignee" value="${escapeHtml(item.assignee || '')}" placeholder="username">
        </label>
        <label>우선순위
          <select data-field="priority">
            ${[4,3,2,1].map(x => `<option value="${x}" ${x === item.priority ? 'selected' : ''}>${x === 4 ? '긴급' : x === 3 ? '높음' : x === 2 ? '보통' : '낮음'}</option>`).join('')}
          </select>
        </label>
        <label>예상 소요시간(분)
          <input data-field="estimated_minutes" type="number" min="1" max="10080" value="${item.estimated_minutes || ''}" placeholder="30">
        </label>
        <label>실행 주체
          <select data-field="executor">
            ${[['human','사람'],['ai','AI'],['hybrid','사람+AI'],['external','외부 응답']].map(([value,label]) => `<option value="${value}" ${value === item.executor ? 'selected' : ''}>${label}</option>`).join('')}
          </select>
        </label>
        <label>선호 AI Worker
          <select data-field="preferred_worker">
            ${['','codex','claude','copilot','orca','hermes','master-worker'].map(value => `<option value="${value}" ${value === (item.preferred_worker || '') ? 'selected' : ''}>${value || '지정 안 함'}</option>`).join('')}
          </select>
        </label>
        <label>업무 모드
          <select data-field="work_mode">
            ${[['unspecified','미지정'],['deep','집중'],['shallow','가벼운 업무'],['admin','관리'],['call','통화'],['meeting','회의'],['errand','외근']].map(([value,label]) => `<option value="${value}" ${value === item.work_mode ? 'selected' : ''}>${label}</option>`).join('')}
          </select>
        </label>
        <label>응답 대기 대상
          <input data-field="waiting_for" value="${escapeHtml(item.waiting_for || '')}" placeholder="고객·협력사·담당자">
        </label>
        <label>후속 확인 시각
          <input data-field="follow_up_at" type="datetime-local" value="${toLocalInput(item.follow_up_at)}">
        </label>
        <label class="checkbox-label">종일 일정
          <input data-field="is_all_day" type="checkbox" ${item.is_all_day ? 'checked' : ''}>
        </label>
      </div>
      <div class="item-meta">
        <p>신뢰도 ${Math.round(item.confidence * 100)}%${item.review_reason ? ` · ${escapeHtml(item.review_reason)}` : ''}</p>
        <div class="item-actions">
          ${['ai','hybrid'].includes(item.executor) ? `<button class="secondary small dispatch-item" data-worker="${escapeHtml(item.preferred_worker || 'codex')}">${escapeHtml(item.preferred_worker || 'codex')} 위임</button>` : ''}
          <button class="ghost small save-item">수정 저장</button>
        </div>
      </div>
      ${item.external_states?.length ? `<p class="helper">외부 상태: ${item.external_states.map(x => `${escapeHtml(x.provider)}=${escapeHtml(x.state)}`).join(' · ')}</p>` : ''}
      ${item.worker_executions?.length ? `<p class="helper">AI 실행: ${item.worker_executions.map(x => `${escapeHtml(x.worker)}=${escapeHtml(x.state)}`).join(' · ')}</p>` : ''}
      ${item.followups?.length ? `<p class="helper">응답 대기: ${item.followups.map(x => `${escapeHtml(x.waiting_for)}=${escapeHtml(x.state)}`).join(' · ')}</p>` : ''}
      ${item.external_url ? (item.external_url.startsWith('/api/v1/exports/')
        ? `<p class="helper">결과: <button class="ghost small download-export" data-export-url="${escapeHtml(item.external_url)}">캘린더 파일 열기</button></p>`
        : `<p class="helper">결과: <a href="${escapeHtml(item.external_url)}" target="_blank" rel="noreferrer">열기</a></p>`) : ''}
      ${item.execution_error ? `<p class="helper" style="color:var(--danger)">${escapeHtml(item.execution_error)}</p>` : ''}
    </article>
  `).join('');

  container.querySelectorAll('.save-item').forEach(button => {
    button.addEventListener('click', async (event) => {
      const card = event.target.closest('.item-card');
      await saveCard(card);
    });
  });
  container.querySelectorAll('.download-export').forEach(button => {
    button.addEventListener('click', () => downloadExport(button.dataset.exportUrl));
  });
  container.querySelectorAll('.dispatch-item').forEach(button => {
    button.addEventListener('click', async (event) => {
      const card = event.target.closest('.item-card');
      await dispatchAction(card.dataset.itemId, button.dataset.worker);
      const refreshed = await api(`/api/v1/plans/${state.plan.id}`);
      renderPlan(refreshed);
    });
  });
  $('planArea').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function cardPayload(card) {
  const get = (field) => card.querySelector(`[data-field="${field}"]`).value;
  return {
    item_type: get('item_type'),
    destination: get('destination'),
    title: get('title').trim(),
    description: get('description').trim(),
    start_at: fromLocalInput(get('start_at')),
    end_at: fromLocalInput(get('end_at')),
    due_at: fromLocalInput(get('due_at')),
    deadline_at: fromLocalInput(get('deadline_at')),
    project: get('project').trim() || null,
    repository: get('repository').trim() || null,
    assignee: get('assignee').trim() || null,
    priority: Number(get('priority')),
    estimated_minutes: Number(get('estimated_minutes')) || null,
    executor: get('executor'),
    preferred_worker: get('preferred_worker') || null,
    work_mode: get('work_mode'),
    waiting_for: get('waiting_for').trim() || null,
    follow_up_at: fromLocalInput(get('follow_up_at')),
    is_all_day: card.querySelector('[data-field="is_all_day"]').checked,
    needs_review: false,
    review_reason: null,
  };
}

async function saveCard(card, silent = false) {
  const itemId = card.dataset.itemId;
  const plan = await api(`/api/v1/plans/${state.plan.id}/items/${itemId}`, {
    method: 'PATCH', body: JSON.stringify(cardPayload(card)),
  });
  state.plan = plan;
  if (!silent) {
    renderPlan(plan);
    toast('수정 내용을 저장했습니다.');
  }
  return plan;
}

async function saveSelectedCards() {
  const cards = [...document.querySelectorAll('.item-card')].filter(card => card.querySelector('.item-select').checked);
  for (const card of cards) await saveCard(card, true);
}

function selectedIds() {
  return [...document.querySelectorAll('.item-card')]
    .filter(card => card.querySelector('.item-select').checked)
    .map(card => card.dataset.itemId);
}

async function parseInput() {
  const text = inputText.value.trim();
  if (!text) return toast('등록할 내용을 입력하세요.', true);
  $('parseButton').disabled = true;
  $('parseButton').textContent = '분석 중…';
  try {
    const plan = await api('/api/v1/inbox/parse', {
      method: 'POST',
      body: JSON.stringify({
        text,
        source: $('sourceSelect').value,
        timezone: 'Asia/Seoul',
      }),
    });
    renderPlan(plan);
    toast(`${plan.items.length}개 항목을 만들었습니다.`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    $('parseButton').disabled = false;
    $('parseButton').textContent = '실행 항목 만들기';
  }
}

async function approveSelected() {
  if (!state.plan) return;
  const ids = selectedIds();
  if (!ids.length) return toast('승인할 항목을 선택하세요.', true);
  try {
    await saveSelectedCards();
    const plan = await api(`/api/v1/plans/${state.plan.id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ item_ids: ids, force_review_items: $('forceReview').checked }),
    });
    renderPlan(plan);
    toast('선택 항목을 승인했습니다.');
  } catch (error) { toast(error.message, true); }
}

async function rejectSelected() {
  if (!state.plan) return;
  const ids = selectedIds();
  if (!ids.length) return toast('제외할 항목을 선택하세요.', true);
  try {
    const plan = await api(`/api/v1/plans/${state.plan.id}/reject`, {
      method: 'POST', body: JSON.stringify({ item_ids: ids, reason: '사용자가 검토 화면에서 제외' }),
    });
    renderPlan(plan);
    toast('선택 항목을 제외했습니다.');
  } catch (error) { toast(error.message, true); }
}

async function executeApproved() {
  if (!state.plan) return;
  $('executeButton').disabled = true;
  $('executeButton').textContent = '실행 중…';
  try {
    const result = await api(`/api/v1/plans/${state.plan.id}/execute`, {
      method: 'POST', body: JSON.stringify({ retry_failed: true }),
    });
    state.plan = { ...state.plan, status: result.plan_status, items: result.items };
    renderPlan(state.plan);
    toast(`등록 ${result.registered} · 실제 완료 ${result.action_completed} · 대기열 ${result.queued} · 실패 ${result.failed}`);
  } catch (error) { toast(error.message, true); }
  finally {
    $('executeButton').disabled = false;
    $('executeButton').textContent = '승인 항목 실행';
  }
}

async function loadBrief() {
  $('briefSummary').textContent = '불러오는 중…';
  try {
    const brief = await api('/api/v1/brief/today');
    $('briefSummary').textContent = brief.summary;
    const groups = [
      ['오늘 일정', brief.events], ['오늘 마감', brief.due_tasks], ['지연 업무', brief.overdue],
      ['검토 필요', brief.needs_review], ['응답 대기', brief.waiting], ['AI 위임 후보', brief.ai_ready],
    ];
    $('briefSections').innerHTML = groups.map(([title, items]) => `
      <div class="brief-group"><h3>${title} · ${items.length}</h3>
      ${items.length ? items.map(item => `<div class="brief-card"><div class="brief-row"><div><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(typeLabel(item.item_type))} · ${formatWhen(item.when)} · ${escapeHtml(item.state)}${item.estimated_minutes ? ` · ${item.estimated_minutes}분` : ''}</p></div>${title === 'AI 위임 후보' ? `<button class="secondary small brief-dispatch" data-item-id="${item.id}" data-worker="${escapeHtml(item.preferred_worker || 'codex')}">${escapeHtml(item.preferred_worker || 'codex')} 위임</button>` : ''}</div></div>`).join('') : '<div class="empty">없음</div>'}
      </div>`).join('');
    document.querySelectorAll('.brief-dispatch').forEach(button => button.addEventListener('click', async () => {
      await dispatchAction(button.dataset.itemId, button.dataset.worker);
      await Promise.all([loadBrief(), loadDecision()]);
    }));
  } catch (error) {
    $('briefSummary').textContent = error.message;
  }
}

async function dispatchAction(itemId, worker = 'codex') {
  try {
    const execution = await api(`/api/v1/items/${encodeURIComponent(itemId)}/dispatch`, {
      method: 'POST', body: JSON.stringify({ worker, actor: 'pwa' }),
    });
    toast(`${execution.worker} 실행을 ${execution.state} 상태로 등록했습니다.`);
    return execution;
  } catch (error) {
    toast(error.message, true);
    throw error;
  }
}

function decisionCard(item, includeDispatch = false) {
  const reasons = (item.reasons || []).map(escapeHtml).join(' · ');
  return `<div class="brief-card decision-card"><div class="brief-row"><div><strong>${escapeHtml(item.title)}</strong><p>${item.estimated_minutes}분 · 점수 ${item.score} · ${reasons}</p></div>${includeDispatch ? `<button class="secondary small decision-dispatch" data-item-id="${item.action_item_id}" data-worker="${escapeHtml(item.preferred_worker || 'codex')}">${escapeHtml(item.preferred_worker || 'codex')} 위임</button>` : ''}</div></div>`;
}

async function loadDecision() {
  const available = Number($('availableMinutes')?.value || 480);
  try {
    const decision = await api('/api/v1/planning/decision', {
      method: 'POST', body: JSON.stringify({ available_minutes: available, max_items: 12, include_ai: true }),
    });
    $('decisionPanel').hidden = false;
    $('decisionSummary').textContent = decision.summary;
    $('decisionNumbers').innerHTML = [
      ['가용시간', `${decision.available_minutes}분`],
      ['계획시간', `${decision.planned_minutes}분`],
      ['보호 버퍼', `${decision.buffer_minutes}분`],
      ['초과 업무', `${decision.overload_minutes}분`],
    ].map(([label,value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join('');
    $('decisionRisks').innerHTML = decision.risks.length ? `<div class="risk-list">${decision.risks.map(x => `<span class="risk-chip">${escapeHtml(x)}</span>`).join('')}</div>` : '';
    $('decisionTop').innerHTML = `<div class="brief-group"><h3>오늘 우선 실행 · ${decision.top_items.length}</h3>${decision.top_items.length ? decision.top_items.map(x => decisionCard(x)).join('') : '<div class="empty">가용시간에 배치할 업무가 없습니다.</div>'}</div>`;
    $('decisionAi').innerHTML = `<div class="brief-group"><h3>AI 위임 가능 · ${decision.ai_delegation_candidates.length}</h3>${decision.ai_delegation_candidates.length ? decision.ai_delegation_candidates.map(x => decisionCard(x, true)).join('') : '<div class="empty">AI 위임 후보가 없습니다.</div>'}</div>`;
    document.querySelectorAll('.decision-dispatch').forEach(button => button.addEventListener('click', async () => {
      await dispatchAction(button.dataset.itemId, button.dataset.worker);
      await Promise.all([loadDecision(), loadBrief()]);
    }));
  } catch (error) {
    $('decisionPanel').hidden = false;
    $('decisionSummary').textContent = error.message;
  }
}

async function resolveFollowup(followupId, nextState) {
  try {
    await api(`/api/v1/followups/${encodeURIComponent(followupId)}/resolve`, {
      method: 'POST', body: JSON.stringify({ state: nextState, actor: 'pwa' }),
    });
    toast(nextState === 'response_received' ? '응답 도착으로 표시했습니다.' : '후속 연락 후 다음 확인일을 잡았습니다.');
    await Promise.all([loadDueFollowups(), loadBrief(), loadDecision()]);
  } catch (error) { toast(error.message, true); }
}

async function loadDueFollowups() {
  const container = $('dueFollowups');
  try {
    await api('/api/v1/followups/process-due', { method: 'POST', body: '{}' });
    const rows = await api('/api/v1/followups/due');
    container.innerHTML = rows.length ? rows.map(row => `<div class="brief-card"><div class="brief-row"><div><strong>${escapeHtml(row.action_title || row.waiting_for)}</strong><p>${escapeHtml(row.waiting_for)} 응답 대기 · ${formatWhen(row.follow_up_at)} · 알림 ${row.reminder_count}회</p></div><div class="inline-buttons"><button class="secondary small followup-response" data-id="${row.id}">응답 도착</button><button class="ghost small followup-sent" data-id="${row.id}">후속 연락함</button></div></div></div>`).join('') : '<div class="empty">지금 확인할 응답 대기가 없습니다.</div>';
    container.querySelectorAll('.followup-response').forEach(button => button.addEventListener('click', () => resolveFollowup(button.dataset.id, 'response_received')));
    container.querySelectorAll('.followup-sent').forEach(button => button.addEventListener('click', () => resolveFollowup(button.dataset.id, 'followed_up')));
  } catch (error) { container.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; }
}

async function loadRecent() {
  const container = $('recentPlans');
  container.innerHTML = '<div class="empty">불러오는 중…</div>';
  try {
    const plans = await api('/api/v1/plans?limit=20');
    container.innerHTML = plans.length ? plans.map(plan => `
      <article class="recent-card" data-plan-id="${plan.id}">
        <h3>${escapeHtml((plan.inbox?.raw_text || '입력 내용').slice(0, 90))}</h3>
        <p>${escapeHtml(plan.summary)} · ${escapeHtml(plan.status)} · ${formatWhen(plan.created_at)}</p>
      </article>`).join('') : '<div class="empty">아직 입력 기록이 없습니다.</div>';
    container.querySelectorAll('.recent-card').forEach(card => card.addEventListener('click', async () => {
      const plan = await api(`/api/v1/plans/${card.dataset.planId}`);
      inputText.value = plan.inbox?.raw_text || '';
      switchView('capture');
      renderPlan(plan);
    }));
  } catch (error) { container.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; }
}

async function loadConnectorStatus() {
  try {
    const statuses = await api('/api/v1/connectors/status?probe=true');
    $('connectorStatuses').innerHTML = statuses.map(item => {
      const label = item.healthy === false ? '오류' : item.configured ? '정상' : item.healthy === true ? 'DRY-RUN' : '미설정';
      const badgeClass = item.healthy === false ? 'failed' : item.configured || item.healthy === true ? 'success' : 'review';
      return `<div class="connector-row"><div><strong>${escapeHtml(destinationLabel(item.name))}</strong><small>${escapeHtml(item.detail)}</small></div><span class="badge ${badgeClass}">${label}</span></div>`;
    }).join('');
    const workers = await api('/api/v1/workers/status');
    $('workerStatuses').innerHTML = workers.map(item => `<div class="connector-row"><div><strong>${escapeHtml(item.name)}</strong><small>${item.configured ? escapeHtml(item.route.repository || 'Workflow route') : '기존 GitHub Workflow 경로 미설정'}</small></div><span class="badge ${item.configured ? 'success' : 'review'}">${item.configured ? '연결됨' : '선택 설정'}</span></div>`).join('');
    $('executionBadge').textContent = statuses[0]?.execution_mode === 'dry_run' ? 'DRY-RUN' : 'LIVE';
    $('executionBadge').className = `badge ${statuses[0]?.execution_mode === 'live' ? 'success' : 'review'}`;
  } catch (error) { $('connectorStatuses').textContent = error.message; }
}

function switchView(name) {
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.toggle('active', el.dataset.view === name));
  $(`${name}View`).classList.add('active');
  if (name === 'today') Promise.all([loadBrief(), loadDecision(), loadDueFollowups()]);
  if (name === 'recent') loadRecent();
  if (name === 'settings') loadConnectorStatus();
}

function startVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    toast('이 브라우저는 음성 인식을 지원하지 않습니다. iPhone 키보드의 받아쓰기를 사용하세요.', true);
    inputText.focus();
    return;
  }
  const recognition = new Recognition();
  recognition.lang = 'ko-KR';
  recognition.interimResults = true;
  recognition.continuous = true;
  let base = inputText.value.trim();
  recognition.onresult = (event) => {
    let transcript = '';
    for (let i = event.resultIndex; i < event.results.length; i++) transcript += event.results[i][0].transcript;
    inputText.value = `${base}${base ? '\n' : ''}${transcript}`;
  };
  recognition.onerror = (event) => toast(`음성 입력 오류: ${event.error}`, true);
  recognition.onend = () => { $('voiceButton').textContent = '음성 입력'; };
  $('voiceButton').textContent = '듣는 중…';
  $('sourceSelect').value = 'voice';
  recognition.start();
}

async function openPendingPlan() {
  if (!state.pendingPlanId || !state.apiKey) return;
  try {
    const plan = await api(`/api/v1/plans/${encodeURIComponent(state.pendingPlanId)}`);
    inputText.value = plan.inbox?.raw_text || '';
    renderPlan(plan);
    state.pendingPlanId = '';
    sessionStorage.removeItem('actionHubPendingPlanId');
    toast('공유한 내용을 검토 화면으로 불러왔습니다.');
  } catch (error) {
    toast(`공유 계획을 불러오지 못했습니다: ${error.message}`, true);
  }
}

async function init() {
  $('apiKeyInput').value = state.apiKey;
  const params = new URLSearchParams(location.search);
  const shared = sessionStorage.getItem('actionHubSharedText');
  const linkedPlanId = params.get('plan_id');
  if (shared) {
    inputText.value = shared;
    $('sourceSelect').value = 'share';
    sessionStorage.removeItem('actionHubSharedText');
  }
  if (linkedPlanId) {
    state.pendingPlanId = linkedPlanId;
    sessionStorage.setItem('actionHubPendingPlanId', linkedPlanId);
  }
  if (shared || linkedPlanId) history.replaceState({}, '', '/');
  try {
    await fetch('/health').then(response => { if (!response.ok) throw new Error(); });
    $('serviceStatus').classList.add('online');
    await loadConnectorStatus();
    await openPendingPlan();
  } catch {
    $('serviceStatus').classList.add('offline');
  }
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
}

document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => switchView(tab.dataset.view)));
$('parseButton').addEventListener('click', parseInput);
$('approveButton').addEventListener('click', approveSelected);
$('rejectButton').addEventListener('click', rejectSelected);
$('executeButton').addEventListener('click', executeApproved);
$('refreshBrief').addEventListener('click', () => Promise.all([loadBrief(), loadDecision(), loadDueFollowups()]));
$('buildDecision').addEventListener('click', loadDecision);
$('refreshFollowups').addEventListener('click', loadDueFollowups);
$('refreshRecent').addEventListener('click', loadRecent);
$('runControlLoop').addEventListener('click', async () => {
  try {
    const result = await api('/api/v1/control/run-once?reconcile=true', { method: 'POST', body: '{}' });
    toast(`대기열 ${result.outbox_processed} · 웹훅 ${result.webhooks_processed} · 동기화 ${result.reconciled}`);
    await loadConnectorStatus();
  } catch (error) { toast(error.message, true); }
});
$('voiceButton').addEventListener('click', startVoice);
$('clearButton').addEventListener('click', () => { inputText.value = ''; inputText.focus(); });
$('pasteButton').addEventListener('click', async () => {
  try { inputText.value = await navigator.clipboard.readText(); $('sourceSelect').value = 'paste'; }
  catch { toast('클립보드 권한이 없어 입력창을 길게 눌러 붙여넣으세요.', true); inputText.focus(); }
});
$('saveSettings').addEventListener('click', () => {
  state.apiKey = $('apiKeyInput').value.trim();
  localStorage.setItem('actionHubApiKey', state.apiKey);
  toast('이 기기에 설정을 저장했습니다.');
  loadConnectorStatus();
  openPendingPlan();
});
window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault(); state.deferredInstallPrompt = event; $('installButton').hidden = false;
});
$('installButton').addEventListener('click', async () => {
  if (!state.deferredInstallPrompt) return;
  state.deferredInstallPrompt.prompt();
  await state.deferredInstallPrompt.userChoice;
  state.deferredInstallPrompt = null;
  $('installButton').hidden = true;
});

init();
