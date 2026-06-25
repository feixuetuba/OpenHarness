// State
let currentNav = 'chat';
let currentSubView = 'agents';
let tracePanelCollapsed = true;
let activeProfileName = '';
let currentAuthSource = '';
let editingAgentId = null;
let agents = [];
let activeAgentId = null;
let providerPresets = [];
let profileMap = {};
let profileList = [];
// Navigation
function switchPrimaryNav(nav) {
  currentNav = nav;
  document.getElementById('navSettings').classList.toggle('active', nav === 'settings');
  document.getElementById('navChat').classList.toggle('active', nav === 'chat');
  document.getElementById('navBots').classList.toggle('active', nav === 'bots');
  document.getElementById('navOpenCAD').classList.toggle('active', nav === 'opencad');
  document.getElementById('subMenuSettings').classList.toggle('hidden', nav !== 'settings');
  document.getElementById('subMenuChat').classList.toggle('hidden', nav !== 'chat');
  document.getElementById('subSidebar').classList.toggle('hidden', nav === 'bots' || nav === 'opencad');
  document.getElementById('workspaceManagement').classList.toggle('hidden', nav !== 'settings');
  document.getElementById('workspaceChat').classList.toggle('hidden', nav !== 'chat');
  document.getElementById('workspaceBots').classList.toggle('hidden', nav !== 'bots');
  document.getElementById('workspaceOpenCAD').classList.toggle('hidden', nav !== 'opencad');
  if (nav === 'chat') {
    loadChatHistory();
    applyTracePanelState();
  }
  if (nav === 'bots') {
    loadBotChannels();
  }
  if (nav === 'opencad') {
    initOpenCad();
  }
}

function toggleTracePanel() {
  tracePanelCollapsed = !tracePanelCollapsed;
  applyTracePanelState();
}

function applyTracePanelState() {
  const panel = document.getElementById('tracePanel');
  const content = document.getElementById('tracePanelContent');
  const icon = document.getElementById('tracePanelToggleIcon');
  const toggleBtnIcon = document.getElementById('tracePanelToggleBtnIcon');

  if (tracePanelCollapsed) {
    panel.style.width = '0';
    panel.style.minWidth = '0';
    panel.style.overflow = 'hidden';
    content.style.display = 'none';
    icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7"/>';
    toggleBtnIcon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 5l7 7-7 7"/>';
  } else {
    panel.style.width = '30%';
    panel.style.minWidth = '280px';
    panel.style.overflow = '';
    content.style.display = '';
    icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7"/>';
    toggleBtnIcon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 19l-7-7 7-7m8 14l-7-7 7-7"/>';
  }
}

function switchSubView(view) {
  currentSubView = view;
  document.querySelectorAll('.sub-nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.subview === view);
  });
  document.getElementById('viewProviders').classList.toggle('hidden', view !== 'providers');
  document.getElementById('viewAgents').classList.toggle('hidden', view !== 'agents');
  document.getElementById('viewSkills').classList.toggle('hidden', view !== 'skills');
  document.getElementById('viewMemory').classList.toggle('hidden', view !== 'memory');
  document.getElementById('viewIntrospection').classList.toggle('hidden', view !== 'introspection');
  document.getElementById('viewSocial').classList.toggle('hidden', view !== 'social');
  document.getElementById('viewPlugins').classList.toggle('hidden', view !== 'plugins');
  document.getElementById('viewMcp').classList.toggle('hidden', view !== 'mcp');
  document.getElementById('viewSessions').classList.toggle('hidden', view !== 'sessions');
  document.getElementById('viewTasks').classList.toggle('hidden', view !== 'tasks');
  document.getElementById('viewWebsearch').classList.toggle('hidden', view !== 'websearch');
  document.getElementById('viewCron').classList.toggle('hidden', view !== 'cron');
  document.getElementById('viewTools').classList.toggle('hidden', view !== 'tools');
  if (view === 'agents') loadAgents();
  if (view === 'skills') loadSkills();
  if (view === 'social') loadSocialSettings();
  if (view === 'memory') loadMemorySettings();
  if (view === 'introspection') { loadIntrospectionSettings(); loadIntrospection(); }
  if (view === 'plugins') loadPlugins();
  if (view === 'mcp') loadMcpServers();
  if (view === 'sessions') loadSessions();
  if (view === 'tasks') loadTasks();
  if (view === 'websearch') loadWebSearchSettings();
  if (view === 'tools') loadTools();
  if (view === 'cron') loadCronJobs();
}

// Data Loading
async function loadSettings(preferredProfileName = '') {
  try {
    const res = await fetch('/api/settings');
    const data = await res.json();
    // Load agents
    agents = data.agents || [];
    activeAgentId = data.active_agent_id;
    const activeAgent = agents.find(a => a.id === activeAgentId);
    document.getElementById('agentName').textContent = activeAgent?.name || data.active_profile || 'Default Agent';

    // Load current profile settings
    profileList = data.profiles || [];
    profileMap = Object.fromEntries(profileList.map(p => [p.name, p]));
    if (data.profiles && data.profiles.length > 0) {
      const preferredProfile = preferredProfileName ? profileMap[preferredProfileName] : null;
      const activeProfile = data.profiles.find(p => p.active);
      const selectedProfile = preferredProfile || activeProfile || data.profiles[0];
      selectProfileForEdit(selectedProfile);
    } else {
      clearProfileEditor();
    }

    document.getElementById('memoryEnabled').value = data.memory_enabled.toString();
    document.getElementById('memoryMaxFiles').value = data.memory_max_files;
    renderProfiles(data.profiles);
    renderAgentProfileOptions();
    if (typeof populateOpenCadChatOptions === 'function') {
      populateOpenCadChatOptions();
    }
    await loadProviderPresets();
    updateStatus(data);
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
}

function renderProfiles(profiles) {
  const container = document.getElementById('profileList');
  if (!profiles || profiles.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无已配置 Profile。点击“添加 Profile”配置新的供应商。</div>';
    return;
  }
  container.innerHTML = profiles.map(p => `
    <div class="flex flex-wrap gap-3 items-center p-3.5 bg-dark-bg-secondary border border-dark-border rounded-lg ${p.active ? 'border-accent-green/50 shadow-glow' : ''} animate-fade-in">
      <div class="flex-1 min-w-[120px]">
        <span class="text-sm font-medium ${p.active ? 'text-accent-green' : 'text-text-primary'}">${p.name}</span>
        <span class="text-xs text-text-muted ml-2">${p.label || ''}</span>
      </div>
      <span class="text-xs px-2.5 py-1 bg-dark-border/50 rounded-md text-text-muted">${p.provider}</span>
      ${p.configured ? '<span class="text-xs text-accent-green">已配置</span>' : '<span class="text-xs text-accent-amber">待配置</span>'}
      ${p.active ? '<span class="text-xs text-accent-green font-medium flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-accent-green"></span>当前</span>' : ''}
      <div class="flex flex-wrap gap-2 items-center ml-auto">
        ${!p.active ? `<button onclick="useProfile('${p.name}')" class="btn-secondary text-xs px-2.5 py-1.5">使用</button>` : ''}
        <button onclick='editProfile(${JSON.stringify(p.name)})' class="btn-secondary text-xs px-2.5 py-1.5">编辑</button>
        ${!p.builtin ? `<button onclick="deleteProfile('${p.name}')" class="btn-danger text-xs px-2.5 py-1.5">删除</button>` : ''}
      </div>
    </div>
  `).join('');
}

function setProfileControlsEnabled(enabled) {
  ['profileDefaultModel', 'profileBaseUrl'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = !enabled;
  });
  const keyInput = document.getElementById('apiKeyInput');
  if (keyInput) keyInput.disabled = !enabled || keyInput.dataset.keyEditable === 'false';
  document.querySelectorAll('#viewProviders button').forEach(btn => {
    const action = btn.getAttribute('onclick') || '';
    if (action.includes('saveProfileSettings') || action.includes('saveApiKey') || action.includes('testConnection')) {
      const keyOnly = action.includes('saveApiKey') || action.includes('testConnection');
      const disabled = !enabled || (keyOnly && keyInput?.dataset.keyEditable === 'false');
      btn.disabled = disabled;
      btn.classList.toggle('opacity-50', disabled);
      btn.classList.toggle('cursor-not-allowed', disabled);
    }
  });
}

function clearProfileEditor() {
  activeProfileName = '';
  currentAuthSource = '';
  document.getElementById('profileSettingsTitle').textContent = 'Profile 设置';
  document.getElementById('profileSettingsHint').textContent = '选择一个供应商后编辑配置参数';
  document.getElementById('profileDefaultModel').value = '';
  document.getElementById('profileBaseUrl').value = '';
  const keyInput = document.getElementById('apiKeyInput');
  keyInput.value = '';
  keyInput.placeholder = 'sk-...';
  keyInput.dataset.keyEditable = 'true';
  document.getElementById('apiKeyHint').textContent = '选择一个供应商后配置认证密钥';
  setProfileControlsEnabled(false);
}

function selectProfileForEdit(profile) {
  if (!profile) {
    clearProfileEditor();
    return;
  }
  activeProfileName = profile.name || '';
  currentAuthSource = profile.auth_source || profile.name || '';
  const displayName = profile.label ? `${profile.name} · ${profile.label}` : profile.name;
  document.getElementById('profileSettingsTitle').textContent = displayName || 'Profile 设置';
  document.getElementById('profileSettingsHint').textContent = profile.active ? '当前正在使用的 Profile' : '正在编辑此 Profile，保存后不会自动切换为当前使用';
  document.getElementById('profileDefaultModel').value = profile.default_model || '';
  document.getElementById('profileBaseUrl').value = profile.base_url || '';
  const keyInput = document.getElementById('apiKeyInput');
  const usesApiKey = (currentAuthSource || '').endsWith('_api_key');
  keyInput.value = '';
  keyInput.dataset.keyEditable = usesApiKey ? 'true' : 'false';
  keyInput.placeholder = usesApiKey
    ? (profile.credential_configured ? '已配置，输入新 Key 可覆盖' : '未配置，请输入 API Key')
    : '此认证方式不使用 API Key';
  document.getElementById('apiKeyHint').textContent = usesApiKey
    ? `${currentAuthSource}${profile.credential_configured ? ' 已配置' : ' 未配置'}`
    : `${currentAuthSource || '当前认证方式'} 不需要在这里配置 API Key`;
  setProfileControlsEnabled(true);
}

function updateStatus(data) {
  const isOnline = data.permission_mode !== undefined;
  document.getElementById('statusDot').className = `status-dot ${isOnline ? 'status-online' : 'status-offline'}`;
  document.getElementById('statusText').textContent = isOnline ? '在线' : '离线';
  if (isOnline) {
    document.getElementById('statusText').parentElement.classList.add('text-accent-green');
    document.getElementById('statusText').parentElement.classList.remove('text-text-secondary');
  }
}

async function loadProviderPresets() {
  try {
    const res = await fetch('/api/providers');
    providerPresets = await res.json();
    const select = document.getElementById('newProfilePreset');
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="">自定义</option>' + providerPresets.map(p => `
      <option value="${p.name}">${p.label || p.name}</option>
    `).join('');
    select.value = current;
  } catch (e) {
    console.error('Failed to load provider presets:', e);
  }
}

function applyProviderPreset() {
  const presetName = document.getElementById('newProfilePreset').value;
  const preset = providerPresets.find(p => p.name === presetName);
  if (!preset) return;
  document.getElementById('newProfileName').value = preset.name || '';
  document.getElementById('newProfileLabel').value = preset.label || preset.name || '';
  document.getElementById('newProfileProvider').value = preset.provider || 'openai';
  document.getElementById('newProfileApiFormat').value = preset.api_format || 'openai';
  document.getElementById('newProfileModel').value = preset.default_model || '';
  document.getElementById('newProfileBaseUrl').value = preset.base_url || '';
}

// Profile Actions
async function useProfile(name) {
  try {
    const res = await fetch(`/api/profile/${name}/use`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      alert('切换失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadSettings();
  } catch (e) {
    alert('切换失败: ' + e.message);
  }
}

function showAddProfileForm() {
  document.getElementById('addProfileForm').classList.remove('hidden');
  loadProviderPresets();
}

function hideAddProfileForm() {
  document.getElementById('addProfileForm').classList.add('hidden');
}

async function addProfile() {
  const presetName = document.getElementById('newProfilePreset').value;
  const preset = providerPresets.find(p => p.name === presetName) || {};
  const data = {
    name: document.getElementById('newProfileName').value,
    label: document.getElementById('newProfileLabel').value,
    provider: document.getElementById('newProfileProvider').value,
    api_format: document.getElementById('newProfileApiFormat').value,
    auth_source: preset.auth_source || `${document.getElementById('newProfileProvider').value}_api_key`,
    credential_slot: document.getElementById('newProfileName').value,
    default_model: document.getElementById('newProfileModel').value,
    base_url: document.getElementById('newProfileBaseUrl').value,
  };
  try {
    const res = await fetch('/api/profile/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (res.ok) {
      hideAddProfileForm();
      const result = await res.json();
      await loadSettings(result.profile || data.name);
    } else {
      const err = await res.json();
      alert('添加失败: ' + err.detail);
    }
  } catch (e) {
    alert('添加失败: ' + e.message);
  }
}

async function deleteProfile(name) {
  if (!confirm(`确定删除 Profile "${name}"?`)) return;
  try {
    await fetch(`/api/profile/${name}`, { method: 'DELETE' });
    await loadSettings(name);
  } catch (e) {
    alert('删除失败: ' + e.message);
  }
}

function editProfile(name) {
  selectProfileForEdit(profileMap[name]);
}

async function saveProfileSettings() {
  if (!activeProfileName) {
    alert('请先添加或选择一个已配置 Profile');
    return;
  }
  const data = {
    default_model: document.getElementById('profileDefaultModel').value,
    base_url: document.getElementById('profileBaseUrl').value,
  };
  try {
    const editingName = activeProfileName;
    await fetch(`/api/profile/${editingName}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    await loadSettings(editingName);
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

async function saveApiKey() {
  const key = document.getElementById('apiKeyInput').value;
  if (document.getElementById('apiKeyInput').dataset.keyEditable === 'false') {
    alert('当前 Profile 不使用 API Key 认证');
    return;
  }
  if (!key || !currentAuthSource) {
    alert('请先添加或选择一个已配置 Profile');
    return;
  }
  try {
    const editingName = activeProfileName;
    const res = await fetch(`/api/profile/${editingName}/set-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: key })
    });
    if (!res.ok) {
      const err = await res.json();
      alert('保存失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    alert('API Key 已保存');
    document.getElementById('apiKeyInput').value = '';
    await loadSettings(editingName);
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

async function testConnection() {
  if (!activeProfileName) {
    alert('请先添加或选择一个已配置 Profile');
    return;
  }
  const baseUrl = document.getElementById('profileBaseUrl').value;
  const apiKey = document.getElementById('apiKeyInput').value;
  if (!baseUrl) {
    alert('请输入 Base URL');
    return;
  }
  const resultDiv = document.getElementById('testResult');
  resultDiv.classList.remove('hidden');
  resultDiv.textContent = '测试中...';
  resultDiv.className = 'text-sm text-text-secondary';
  try {
    const res = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: baseUrl,
        api_format: 'openai',
        api_key: apiKey || undefined,
        profile_name: activeProfileName
      })
    });
    const data = await res.json();
    if (data.success) {
      if (data.models && data.models.length > 0) {
        resultDiv.innerHTML = `
          <div class="space-y-2">
            <div class="text-accent-green">连接成功! 可用模型: ${data.models.length} 个</div>
            <div class="flex flex-col gap-1">
              <label class="form-label">选择模型</label>
              <select id="modelSelect" class="form-input" style="background-color: #0f1629; color: #f1f5f9;">
                <option value="">-- 请选择模型 --</option>
                ${data.models.map(m => `<option value="${m}">${m}</option>`).join('')}
              </select>
            </div>
            <button onclick="selectModel()" class="btn-primary text-xs px-3 py-1.5">确认选择</button>
          </div>
        `;
      } else {
        resultDiv.textContent = '连接成功! 但未获取到模型列表';
        resultDiv.className = 'text-sm text-accent-green';
      }
    } else {
      resultDiv.textContent = `连接失败: ${data.message}`;
      resultDiv.className = 'text-sm text-red-500';
    }
  } catch (e) {
    resultDiv.textContent = '测试失败: ' + e.message;
    resultDiv.className = 'text-sm text-red-500';
  }
}

async function selectModel() {
  const select = document.getElementById('modelSelect');
  const model = select ? select.value : '';
  if (!model) {
    alert('请选择一个模型');
    return;
  }
  document.getElementById('profileDefaultModel').value = model;
  const resultDiv = document.getElementById('testResult');
  resultDiv.innerHTML = `<div class="text-accent-green">已设为供应商默认模型: ${model}</div>`;
}

// Agent Management
async function loadAgents() {
  try {
    const res = await fetch('/api/agents');
    const data = await res.json();
    agents = data.agents || [];
    activeAgentId = data.active_agent_id;
    renderAgents();
    if (typeof populateOpenCadChatOptions === 'function') {
      populateOpenCadChatOptions();
    }
  } catch (e) {
    document.getElementById('agentList').innerHTML = '<div class="text-sm text-red-400">加载失败</div>';
  }
}

function renderAgents() {
  const container = document.getElementById('agentList');
  if (!agents || agents.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无 Agent 配置</div>';
    return;
  }
  container.innerHTML = agents.map(a => `
    <div class="flex flex-wrap gap-3 items-center p-3.5 bg-dark-bg-secondary border border-dark-border rounded-lg ${a.id === activeAgentId ? 'border-accent-green/50 shadow-glow' : ''} animate-fade-in">
      <div class="flex-1 min-w-[120px]">
        <span class="text-sm font-medium ${a.id === activeAgentId ? 'text-accent-green' : 'text-text-primary'}">${a.name}</span>
        <span class="text-xs text-text-muted ml-2">(${a.id})</span>
        <div class="text-xs text-text-muted mt-1">${a.profile ? `供应商: ${a.profile}` : '供应商: 当前默认'}${a.model ? ` · 模型: ${a.model}` : ''}</div>
        <div class="text-xs text-text-muted mt-1">${a.image_profile ? `图片: ${a.image_profile}/${a.image_model || '默认模型'}` : '图片: 未配置'} · ${a.audio_profile ? `音频: ${a.audio_profile}/${a.audio_model || '默认模型'}` : '音频: 未配置'}</div>
      </div>
      ${a.id === activeAgentId ? '<span class="text-xs text-accent-green font-medium flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-accent-green"></span>当前</span>' : ''}
      <div class="flex flex-wrap gap-2 items-center ml-auto">
        ${a.id !== activeAgentId ? `<button onclick='activateAgent(${JSON.stringify(a.id)})' class="btn-secondary text-xs px-2.5 py-1.5">使用</button>` : ''}
        <button onclick='editAgent(${JSON.stringify(a.id)})' class="btn-secondary text-xs px-2.5 py-1.5">编辑</button>
        <button onclick='deleteAgent(${JSON.stringify(a.id)})' class="btn-danger text-xs px-2.5 py-1.5">删除</button>
      </div>
    </div>
  `).join('');
}

function renderAgentProfileOptions(selected = '') {
  const select = document.getElementById('newAgentProfile');
  if (!select) return;
  const current = selected || select.value || '';
  select.innerHTML = '<option value="">使用当前默认供应商</option>' + profileList.map(p => `
    <option value="${p.name}">${p.name}${p.label ? ` · ${p.label}` : ''}${p.configured ? '' : '（未配置 Key）'}</option>
  `).join('');
  select.value = profileMap[current] ? current : '';
  updateAgentModelChoices();
}

function getSelectedAgentProfile() {
  const profileName = document.getElementById('newAgentProfile')?.value || '';
  return profileName ? profileMap[profileName] : null;
}

function setAgentModelOptions(models, selected = '') {
  const select = document.getElementById('newAgentModelSelect');
  if (!select) return;
  const unique = [...new Set((models || []).filter(Boolean))];
  select.innerHTML = '<option value="">使用所选供应商默认模型</option>' + unique.map(model => `
    <option value="${model}">${model}</option>
  `).join('');
  if (selected && !unique.includes(selected)) {
    select.innerHTML += `<option value="${selected}">${selected}</option>`;
  }
  select.value = selected || '';
}

async function updateAgentModelChoices(selected = '') {
  const profile = getSelectedAgentProfile();
  const models = [];
  if (profile) {
    if (Array.isArray(profile.allowed_models)) models.push(...profile.allowed_models);
    if (profile.last_model) models.push(profile.last_model);
    if (profile.default_model) models.push(profile.default_model);
  }
  setAgentModelOptions(models, selected || document.getElementById('newAgentModel')?.value || '');
  const hint = document.getElementById('agentModelHint');
  if (hint) {
    hint.textContent = profile
      ? `当前供应商: ${profile.name}${profile.base_url ? ` · ${profile.base_url}` : ''}`
      : '不指定供应商时，Agent 会使用系统当前默认供应商和默认模型。';
  }
  if (profile) {
    await refreshAgentModelList({ silent: true, selected });
  }
}

function syncAgentModelFromSelect() {
  document.getElementById('newAgentModel').value = document.getElementById('newAgentModelSelect').value || '';
}

function attachmentFieldId(kind, suffix) {
  const title = kind.charAt(0).toUpperCase() + kind.slice(1);
  return `newAgent${title}${suffix}`;
}

function attachmentProfileAllowed(kind, profile) {
  if (kind !== 'audio') return true;
  return profile.provider !== 'openai_codex' && ['openai', 'openai_compat', 'copilot'].includes(profile.api_format);
}

function renderAttachmentProfileOptions(kind, selected = '') {
  const select = document.getElementById(attachmentFieldId(kind, 'Profile'));
  if (!select) return;
  const current = selected || select.value || '';
  const profiles = profileList.filter(profile => attachmentProfileAllowed(kind, profile));
  select.innerHTML = `<option value="">不支持${kind === 'image' ? '图片' : '音频'}处理</option>` + profiles.map(profile => `
    <option value="${profile.name}">${profile.name}${profile.label ? ` · ${profile.label}` : ''}${profile.configured ? '' : '（未配置 Key）'}</option>
  `).join('');
  select.value = profiles.some(profile => profile.name === current) ? current : '';
  updateAttachmentModelChoices(kind);
}

async function updateAttachmentModelChoices(kind, selected = '') {
  const profileName = document.getElementById(attachmentFieldId(kind, 'Profile'))?.value || '';
  const profile = profileName ? profileMap[profileName] : null;
  const modelInput = document.getElementById(attachmentFieldId(kind, 'Model'));
  const modelSelect = document.getElementById(attachmentFieldId(kind, 'ModelSelect'));
  const models = [];
  if (profile) {
    if (Array.isArray(profile.allowed_models)) models.push(...profile.allowed_models);
    if (profile.last_model) models.push(profile.last_model);
    if (profile.default_model) models.push(profile.default_model);
  }
  const unique = [...new Set(models.filter(Boolean))];
  const chosen = selected || modelInput?.value || '';
  if (modelSelect) {
    modelSelect.innerHTML = '<option value="">使用所选供应商默认模型</option>' + unique.map(model => `<option value="${model}">${model}</option>`).join('');
    if (chosen && !unique.includes(chosen)) modelSelect.innerHTML += `<option value="${chosen}">${chosen}</option>`;
    modelSelect.value = chosen;
  }
  const hint = document.getElementById(`agent${kind.charAt(0).toUpperCase() + kind.slice(1)}ModelHint`);
  if (hint) hint.textContent = profile
    ? `处理请求将发送至 ${profile.name}/${chosen || profile.default_model || '默认模型'}`
    : `未配置时，Agent 不支持${kind === 'image' ? '图片' : '音频'}处理。`;
}

function syncAttachmentModelFromSelect(kind) {
  const select = document.getElementById(attachmentFieldId(kind, 'ModelSelect'));
  const input = document.getElementById(attachmentFieldId(kind, 'Model'));
  if (input) input.value = select?.value || '';
  updateAttachmentModelChoices(kind, input?.value || '');
}

async function refreshAttachmentModelList(kind, options = {}) {
  const profileName = document.getElementById(attachmentFieldId(kind, 'Profile'))?.value || '';
  const profile = profileName ? profileMap[profileName] : null;
  if (!profile) {
    if (!options.silent) alert('请先选择一个供应商/Profile');
    return;
  }
  const selected = options.selected || document.getElementById(attachmentFieldId(kind, 'Model'))?.value || '';
  const hint = document.getElementById(`agent${kind.charAt(0).toUpperCase() + kind.slice(1)}ModelHint`);
  if (hint) hint.textContent = '正在获取模型列表...';
  try {
    const res = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: profile.base_url,
        api_format: profile.api_format || 'openai',
        profile_name: profile.name
      })
    });
    const data = await res.json();
    if (!data.success) {
      if (hint) hint.textContent = `获取失败: ${data.message || '未知错误'}`;
      return;
    }
    profile.allowed_models = [...new Set([...(profile.allowed_models || []), ...(data.models || [])])];
    await updateAttachmentModelChoices(kind, selected);
  } catch (error) {
    if (hint) hint.textContent = `获取失败: ${error.message}`;
  }
}

async function refreshAgentModelList(options = {}) {
  const silent = Boolean(options.silent);
  const selected = options.selected || document.getElementById('newAgentModel').value.trim();
  const profile = getSelectedAgentProfile();
  if (!profile) {
    if (!silent) alert('请先选择一个供应商/Profile');
    return;
  }
  if (!profile.base_url) {
    if (!silent) alert('该 Profile 没有 Base URL，无法拉取模型列表');
    return;
  }
  const hint = document.getElementById('agentModelHint');
  if (hint) hint.textContent = '正在获取模型列表...';
  try {
    const res = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: profile.base_url,
        api_format: profile.api_format || 'openai',
        profile_name: profile.name
      })
    });
    const data = await res.json();
    if (!data.success) {
      if (hint) hint.textContent = `获取失败: ${data.message || '未知错误'}`;
      return;
    }
    const fetchedModels = data.models || [];
    if (!fetchedModels.includes(profile.default_model) && profile.default_model) {
      fetchedModels.unshift(profile.default_model);
    }
    setAgentModelOptions(fetchedModels, selected);
    if (hint) hint.textContent = `已获取 ${data.models?.length || 0} 个模型`;
  } catch (e) {
    if (hint) hint.textContent = `获取失败: ${e.message}`;
  }
}

function showAddAgentForm() {
  editingAgentId = null;
  document.getElementById('agentFormTitle').textContent = '添加 Agent';
  document.getElementById('newAgentId').value = '';
  document.getElementById('newAgentName').value = '';
  document.getElementById('newAgentSystemPrompt').value = '';
  renderAgentProfileOptions('');
  document.getElementById('newAgentModel').value = '';
  updateAgentModelChoices('');
  document.getElementById('newAgentMaxTurns').value = '';
  for (const kind of ['image', 'audio']) {
    document.getElementById(attachmentFieldId(kind, 'Model')).value = '';
    renderAttachmentProfileOptions(kind, '');
  }
  document.getElementById('newAgentId').disabled = false;
  document.getElementById('addAgentForm').classList.remove('hidden');
}

function hideAddAgentForm() {
  document.getElementById('addAgentForm').classList.add('hidden');
  editingAgentId = null;
}

function editAgent(id) {
  const agent = agents.find(a => a.id === id);
  if (!agent) return;

  editingAgentId = id;
  document.getElementById('agentFormTitle').textContent = '编辑 Agent';
  document.getElementById('newAgentId').value = agent.id;
  document.getElementById('newAgentId').disabled = true;
  document.getElementById('newAgentName').value = agent.name || '';
  document.getElementById('newAgentSystemPrompt').value = agent.system_prompt || '';
  renderAgentProfileOptions(agent.profile || '');
  document.getElementById('newAgentModel').value = agent.model || '';
  updateAgentModelChoices(agent.model || '');
  document.getElementById('newAgentMaxTurns').value = agent.max_turns || '';
  for (const kind of ['image', 'audio']) {
    const profile = agent[`${kind}_profile`] || '';
    const model = agent[`${kind}_model`] || '';
    document.getElementById(attachmentFieldId(kind, 'Model')).value = model;
    renderAttachmentProfileOptions(kind, profile);
    updateAttachmentModelChoices(kind, model);
  }
  document.getElementById('addAgentForm').classList.remove('hidden');
}

async function saveAgent() {
  const id = document.getElementById('newAgentId').value.trim();
  const name = document.getElementById('newAgentName').value.trim();
  const systemPrompt = document.getElementById('newAgentSystemPrompt').value;
  const profile = document.getElementById('newAgentProfile').value || null;
  const model = document.getElementById('newAgentModel').value.trim() || null;
  const maxTurns = document.getElementById('newAgentMaxTurns').value ? parseInt(document.getElementById('newAgentMaxTurns').value) : null;
  const imageProfile = document.getElementById('newAgentImageProfile').value || null;
  const imageModel = document.getElementById('newAgentImageModel').value.trim() || null;
  const audioProfile = document.getElementById('newAgentAudioProfile').value || null;
  const audioModel = document.getElementById('newAgentAudioModel').value.trim() || null;

  if (!id || !name) {
    alert('Agent ID 和显示名称为必填项');
    return;
  }

  const agentData = {
    id,
    name,
    system_prompt: systemPrompt,
    profile,
    model,
    max_turns: maxTurns,
    image_profile: imageProfile,
    image_model: imageProfile ? imageModel : null,
    audio_profile: audioProfile,
    audio_model: audioProfile ? audioModel : null,
  };

  try {
    let res;
    if (editingAgentId) {
      res = await fetch(`/api/agents/${editingAgentId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentData)
      });
    } else {
      res = await fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentData)
      });
    }

    if (res.ok) {
      hideAddAgentForm();
      await loadAgents();
    } else {
      const err = await res.json();
      alert('保存失败: ' + (err.detail || `HTTP ${res.status}`));
    }
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

async function activateAgent(id) {
  try {
    const res = await fetch(`/api/agents/${id}/activate`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      alert('切换失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadAgents();
    document.getElementById('agentName').textContent = agents.find(a => a.id === id)?.name || id;
  } catch (e) {
    alert('切换失败: ' + e.message);
  }
}

async function deleteAgent(id) {
  if (!confirm(`确定删除 Agent "${id}"?`)) return;
  try {
    const res = await fetch(`/api/agents/${id}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json();
      alert('删除失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadAgents();
    const activeAgent = agents.find(a => a.id === activeAgentId);
    document.getElementById('agentName').textContent = activeAgent?.name || 'Default Agent';
  } catch (e) {
    alert('删除失败: ' + e.message);
  }
}

// Skills
let allSkills = [];

async function loadSkills() {
  try {
    await loadSkillSettings();
    const res = await fetch('/api/skills');
    const data = await res.json();
    allSkills = Array.isArray(data) ? data : (data.skills || []);
    renderSkillsList(allSkills);
  } catch (e) {
    document.getElementById('skillList').innerHTML = '<div class="text-sm text-red-400">加载失败</div>';
  }
}

function renderSkillsList(skills) {
  const container = document.getElementById('skillList');
  if (!skills || skills.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无可用技能</div>';
    return;
  }
  container.innerHTML = skills.map(s => `
    <div class="flex flex-wrap gap-3 items-center p-3.5 bg-dark-bg-secondary border ${s.enabled === false ? 'border-amber-500/35 opacity-75' : 'border-dark-border'} rounded-lg animate-fade-in">
      <div class="flex-1 min-w-[150px]">
        <span class="text-sm font-medium text-text-primary">${escapeHtml(s.name)}</span>
        <span class="text-xs text-text-muted ml-2">${escapeHtml(s.source || '')}</span>
        <span class="text-[10px] ml-2 px-1.5 py-0.5 rounded ${s.enabled === false ? 'bg-amber-500/15 text-amber-300' : 'bg-accent-green/10 text-accent-green'}">${s.enabled === false ? '已禁用' : '已启用'}</span>
      </div>
      <div class="flex-1 min-w-[200px]">
        <span class="text-xs text-text-secondary truncate block">${escapeHtml(s.description || '')}</span>
      </div>
      <div class="flex flex-wrap gap-2 items-center ml-auto">
        <button onclick="toggleSkill('${encodeURIComponent(s.name)}', ${s.enabled === false ? 'true' : 'false'})" class="${s.enabled === false ? 'btn-primary' : 'btn-secondary'} text-xs px-2.5 py-1.5">${s.enabled === false ? '启用' : '禁用'}</button>
        <button onclick="toggleSkillAutoApprove('${encodeURIComponent(s.name)}', ${s.auto_approve ? 'false' : 'true'})" class="${s.auto_approve ? 'btn-primary' : 'btn-secondary'} text-xs px-2.5 py-1.5" title="机器人通道中，本轮已使用该 skill 后自动允许后续工具调用">${s.auto_approve ? '自动授权' : '询问授权'}</button>
        <button onclick="viewSkillDetails('${encodeURIComponent(s.name)}')" class="btn-secondary text-xs px-2.5 py-1.5">查看</button>
        ${s.source === 'user' ? `
          <button onclick="downloadSkill('${encodeURIComponent(s.name)}')" class="btn-secondary text-xs px-2.5 py-1.5" title="下载">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m0-8v8"/></svg>
          </button>
          <button onclick="deleteSkill('${encodeURIComponent(s.name)}')" class="btn-danger text-xs px-2.5 py-1.5" title="删除">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
          </button>
        ` : `
          <button onclick="downloadSkill('${encodeURIComponent(s.name)}')" class="btn-secondary text-xs px-2.5 py-1.5" title="下载">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m0-8v8"/></svg>
          </button>
        `}
      </div>
    </div>
  `).join('');
}

function filterSkills() {
  const search = document.getElementById('skillSearch').value.toLowerCase();
  if (!search) {
    renderSkillsList(allSkills);
    return;
  }
  const filtered = allSkills.filter(s =>
    s.name.toLowerCase().includes(search) ||
    (s.description && s.description.toLowerCase().includes(search)) ||
    (s.source && s.source.toLowerCase().includes(search))
  );
  renderSkillsList(filtered);
}

async function viewSkillDetails(name) {
  name = decodeURIComponent(name);
  try {
    const res = await fetch(`/api/skills/${encodeURIComponent(name)}`);
    const data = await res.json();
    document.getElementById('skillModalTitle').textContent = data.name;
    document.getElementById('skillModalSource').textContent = `来源: ${data.source || '未知'} | 路径: ${data.path || '无'}`;
    document.getElementById('skillModalDesc').textContent = data.description || '';
    document.getElementById('skillModalContent').textContent = data.content || '(无内容)';
    document.getElementById('skillModal').classList.remove('hidden');
  } catch (e) {
    alert('加载技能详情失败: ' + e.message);
  }
}

function closeSkillModal() {
  document.getElementById('skillModal').classList.add('hidden');
}

async function reloadSkills() {
  try {
    const res = await fetch('/api/skills/reload', { method: 'POST' });
    const data = await res.json();
    await loadSkills();
    alert(`已重新加载 ${data.count || 0} 个技能`);
  } catch (e) {
    alert('重新加载失败: ' + e.message);
  }
}

async function saveSkillSettings() {
  const aliases = {};
  document.querySelectorAll('#skillPathAliasRows [data-alias-row]').forEach(row => {
    const key = row.querySelector('[data-alias-key]')?.value.trim().replace(/^\$/, '') || '';
    const value = row.querySelector('[data-alias-value]')?.value.trim() || '';
    if (key && value) aliases[key] = value;
  });
  const data = {
    path_aliases: aliases
  };
  try {
    await fetch('/api/skill-management', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    alert('设置已保存');
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

async function loadSkillSettings() {
  try {
    const res = await fetch('/api/skill-management');
    if (!res.ok) return;
    const data = await res.json();
    const aliases = data.path_aliases || { USKILL: '~/.openharness/skills' };
    const container = document.getElementById('skillPathAliasRows');
    if (container && !container.querySelector('input:focus')) {
      container.innerHTML = '';
      Object.entries(aliases).forEach(([key, value]) => addPathAliasRow(key, value));
      if (!Object.keys(aliases).length) addPathAliasRow('USKILL', '~/.openharness/skills');
    }
  } catch (e) {
    console.warn('加载 Skill 设置失败', e);
  }
}

function addPathAliasRow(key = '', value = '') {
  const container = document.getElementById('skillPathAliasRows');
  if (!container) return;
  const row = document.createElement('div');
  row.dataset.aliasRow = 'true';
  row.className = 'grid grid-cols-[minmax(90px,160px)_1fr_auto] gap-2 items-center';
  row.innerHTML = `
    <input data-alias-key type="text" class="form-input text-xs font-mono" placeholder="USKILL" value="${escapeAttr(key)}">
    <input data-alias-value type="text" class="form-input text-xs font-mono" placeholder="~/.openharness/skills" value="${escapeAttr(value)}">
    <button type="button" class="btn-danger text-xs px-2.5 py-1.5" title="删除">删除</button>
  `;
  row.querySelector('button').addEventListener('click', () => row.remove());
  container.appendChild(row);
}

async function toggleSkill(name, enabled) {
  name = decodeURIComponent(name);
  try {
    const res = await fetch(`/api/skills/${encodeURIComponent(name)}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    const result = await res.json();
    if (!res.ok) {
      alert(`切换失败: ${result.detail || result.message || `HTTP ${res.status}`}`);
      return;
    }
    await loadSkills();
  } catch (e) {
    alert('切换失败: ' + e.message);
  }
}

async function toggleSkillAutoApprove(name, enabled) {
  name = decodeURIComponent(name);
  try {
    const res = await fetch(`/api/skills/${encodeURIComponent(name)}/auto-approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    const result = await res.json();
    if (!res.ok) {
      alert(`切换失败: ${result.detail || result.message || `HTTP ${res.status}`}`);
      return;
    }
    await loadSkills();
  } catch (e) {
    alert('切换失败: ' + e.message);
  }
}

let currentInstallTab = 'git';
let selectedZipFile = null;

function showInstallSkillModal() {
  document.getElementById('installSkillModal').classList.remove('hidden');
  resetInstallForm();
}

function closeInstallSkillModal() {
  document.getElementById('installSkillModal').classList.add('hidden');
  resetInstallForm();
}

function resetInstallForm() {
  document.getElementById('skillInstallGitUrl').value = '';
  document.getElementById('skillInstallHttpUrl').value = '';
  document.getElementById('skillInstallBranch').value = 'main';
  document.getElementById('skillInstallName').value = '';
  document.getElementById('skillInstallHttpName').value = '';
  document.getElementById('skillInstallZip').value = '';
  document.getElementById('zipFileInfo').classList.add('hidden');
  selectedZipFile = null;
  switchInstallTab('git');
}

function switchInstallTab(tab) {
  currentInstallTab = tab;
  document.getElementById('installTabGit').classList.toggle('active', tab === 'git');
  document.getElementById('installTabHttp').classList.toggle('active', tab === 'http');
  document.getElementById('installTabZip').classList.toggle('active', tab === 'zip');
  document.getElementById('installTabGit').setAttribute('aria-selected', tab === 'git' ? 'true' : 'false');
  document.getElementById('installTabHttp').setAttribute('aria-selected', tab === 'http' ? 'true' : 'false');
  document.getElementById('installTabZip').setAttribute('aria-selected', tab === 'zip' ? 'true' : 'false');
  document.getElementById('installFormGit').classList.toggle('hidden', tab !== 'git');
  document.getElementById('installFormHttp').classList.toggle('hidden', tab !== 'http');
  document.getElementById('installFormZip').classList.toggle('hidden', tab !== 'zip');
  document.getElementById('installSkillBtn').textContent = tab === 'zip' ? '上传并安装' : '安装';
}

function handleZipSelect(input) {
  if (input.files && input.files[0]) {
    selectedZipFile = input.files[0];
    document.getElementById('zipFileName').textContent = `文件: ${selectedZipFile.name}`;
    document.getElementById('zipFileSize').textContent = `大小: ${(selectedZipFile.size / 1024).toFixed(2)} KB`;
    document.getElementById('zipFileInfo').classList.remove('hidden');
  }
}

async function executeSkillInstall() {
  if (currentInstallTab === 'git') {
    await installSkillFromGit();
  } else if (currentInstallTab === 'http') {
    await installSkillFromHttp();
  } else {
    await installSkillFromZip();
  }
}

async function installSkillFromGit() {
  const url = document.getElementById('skillInstallGitUrl').value.trim();
  if (!url) {
    alert('请输入 Git 仓库 URL');
    return;
  }

  const data = {
    type: 'git',
    url: url,
    branch: document.getElementById('skillInstallBranch').value.trim() || 'main',
    name: document.getElementById('skillInstallName').value.trim() || undefined
  };

  try {
    document.getElementById('installSkillBtn').disabled = true;
    document.getElementById('installSkillBtn').textContent = '安装中...';

    const res = await fetch('/api/skills/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });

    const result = await res.json();

    if (res.ok) {
      alert(`安装成功: ${result.message}`);
      closeInstallSkillModal();
      await loadSkills();
    } else {
      alert(`安装失败: ${result.detail || result.message || `HTTP ${res.status}`}`);
    }
  } catch (e) {
    alert(`安装失败: ${e.message}`);
  } finally {
    document.getElementById('installSkillBtn').disabled = false;
    document.getElementById('installSkillBtn').textContent = '安装';
  }
}

async function installSkillFromHttp() {
  const url = document.getElementById('skillInstallHttpUrl').value.trim();
  if (!url) {
    alert('请输入 HTTP URL');
    return;
  }

  const data = {
    type: 'http',
    url: url,
    name: document.getElementById('skillInstallHttpName').value.trim() || undefined
  };

  try {
    document.getElementById('installSkillBtn').disabled = true;
    document.getElementById('installSkillBtn').textContent = '安装中...';

    const res = await fetch('/api/skills/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });

    const result = await res.json();

    if (res.ok) {
      alert(`安装成功: ${result.message}`);
      closeInstallSkillModal();
      await loadSkills();
    } else {
      alert(`安装失败: ${result.detail || result.message || `HTTP ${res.status}`}`);
    }
  } catch (e) {
    alert(`安装失败: ${e.message}`);
  } finally {
    document.getElementById('installSkillBtn').disabled = false;
    document.getElementById('installSkillBtn').textContent = '安装';
  }
}

async function installSkillFromZip() {
  if (!selectedZipFile) {
    alert('请选择 ZIP 文件');
    return;
  }

  const formData = new FormData();
  formData.append('file', selectedZipFile);

  try {
    document.getElementById('installSkillBtn').disabled = true;
    document.getElementById('installSkillBtn').textContent = '上传中...';

    const res = await fetch('/api/skills/upload-zip', {
      method: 'POST',
      body: formData
    });

    const result = await res.json();

    if (res.ok) {
      alert(`安装成功: ${result.message}`);
      closeInstallSkillModal();
      await loadSkills();
    } else {
      alert(`安装失败: ${result.detail || result.message || `HTTP ${res.status}`}`);
    }
  } catch (e) {
    alert(`安装失败: ${e.message}`);
  } finally {
    document.getElementById('installSkillBtn').disabled = false;
    document.getElementById('installSkillBtn').textContent = '上传并安装';
  }
}

async function downloadSkill(name) {
  name = decodeURIComponent(name);
  try {
    const link = document.createElement('a');
    link.href = `/api/skills/${encodeURIComponent(name)}/download`;
    link.download = `${name}.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } catch (e) {
    alert('下载失败: ' + e.message);
  }
}

async function deleteSkill(name) {
  name = decodeURIComponent(name);
  if (!confirm(`确定删除 Skill "${name}"? 此操作不可撤销。`)) {
    return;
  }

  try {
    const res = await fetch(`/api/skills/${encodeURIComponent(name)}`, {
      method: 'DELETE'
    });

    const result = await res.json();

    if (res.ok) {
      alert(`删除成功: ${result.message}`);
      await loadSkills();
    } else {
      alert(`删除失败: ${result.detail || result.message || `HTTP ${res.status}`}`);
    }
  } catch (e) {
    alert(`删除失败: ${e.message}`);
  }
}

// Memory
let memoryEntries = [];

async function loadMemorySettings() {
  try {
    const res = await fetch('/api/memory-settings');
    const data = await res.json();
    document.getElementById('memoryEnabled').value = data.enabled.toString();
    document.getElementById('memoryMaxFiles').value = data.max_files;
  } catch (e) {
    console.error('Failed to load memory settings:', e);
  }
}

async function saveMemorySettings() {
  const data = {
    enabled: document.getElementById('memoryEnabled').value === 'true',
    max_files: parseInt(document.getElementById('memoryMaxFiles').value)
  };
  try {
    await fetch('/api/memory-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    alert('记忆设置已保存');
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

async function loadMemoryEntries() {
  try {
    const res = await fetch('/api/memory/entries');
    const data = await res.json();
    memoryEntries = Array.isArray(data) ? data : (data.entries || []);
    renderMemoryEntries(memoryEntries);
  } catch (e) {
    document.getElementById('memoryEntriesList').innerHTML = '<div class="text-sm text-red-400">加载失败</div>';
  }
}

function renderMemoryEntries(entries) {
  const container = document.getElementById('memoryEntriesList');
  if (!entries || entries.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无记忆条目</div>';
    return;
  }
  container.innerHTML = entries.map(e => `
    <div class="flex flex-wrap gap-3 items-center p-3.5 bg-dark-bg-secondary border border-dark-border rounded-lg animate-fade-in">
      <div class="flex-1 min-w-[150px]">
        <span class="text-sm font-medium text-text-primary">${e.title || e.id}</span>
        <span class="text-xs text-text-muted ml-2">${e.type || ''}</span>
      </div>
      <div class="flex-1 min-w-[200px]">
        <span class="text-xs text-text-secondary truncate block">${e.description || ''}</span>
      </div>
      <div class="flex flex-wrap gap-2 items-center ml-auto">
        <button onclick="deleteMemoryEntry('${e.id}')" class="btn-danger text-xs px-2.5 py-1.5">删除</button>
      </div>
    </div>
  `).join('');
}

function searchMemoryEntries() {
  const search = document.getElementById('memorySearch').value.toLowerCase();
  if (!search) {
    renderMemoryEntries(memoryEntries);
    return;
  }
  const filtered = memoryEntries.filter(e =>
    (e.title && e.title.toLowerCase().includes(search)) ||
    (e.description && e.description.toLowerCase().includes(search)) ||
    (e.id && e.id.toLowerCase().includes(search))
  );
  renderMemoryEntries(filtered);
}

function showAddMemoryForm() {
  document.getElementById('newMemoryTitle').value = '';
  document.getElementById('newMemoryContent').value = '';
  document.getElementById('addMemoryModal').classList.remove('hidden');
}

function closeAddMemoryModal() {
  document.getElementById('addMemoryModal').classList.add('hidden');
}

async function addMemoryEntry() {
  const title = document.getElementById('newMemoryTitle').value.trim();
  const content = document.getElementById('newMemoryContent').value.trim();
  if (!title) {
    alert('请输入标题');
    return;
  }
  try {
    const res = await fetch('/api/memory/entries', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content })
    });
    if (!res.ok) {
      const err = await res.json();
      alert('添加失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    closeAddMemoryModal();
    await loadMemoryEntries();
    alert('记忆条目已添加');
  } catch (e) {
    alert('添加失败: ' + e.message);
  }
}

async function deleteMemoryEntry(id) {
  if (!confirm(`确定删除记忆条目 "${id}"?`)) return;
  try {
    const res = await fetch(`/api/memory/entries/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json();
      alert('删除失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadMemoryEntries();
    alert('记忆条目已删除');
  } catch (e) {
    alert('删除失败: ' + e.message);
  }
}

async function loadMemoryMd() {
  try {
    const res = await fetch('/api/memory/md');
    const data = await res.json();
    document.getElementById('memoryMdContent').value = data.content || '';
  } catch (e) {
    alert('加载失败: ' + e.message);
  }
}

async function saveMemoryMd() {
  const content = document.getElementById('memoryMdContent').value;
  try {
    const res = await fetch('/api/memory/md', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content })
    });
    if (!res.ok) {
      const err = await res.json();
      alert('保存失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    alert('MEMORY.md 已保存');
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

// Social
async function loadSocialSettings() {
  try {
    const res = await fetch('/api/social-platforms');
    const data = await res.json();
    const container = document.getElementById('socialSettings');
    container.innerHTML = `
      <div class="flex gap-2 mb-6 border-b border-dark-border pb-4">
        <button onclick="switchSocialTab('wechat')" id="socialTabWechat" class="social-tab-btn active">
          <span class="flex items-center gap-2">
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 01.213.665l-.39 1.48c-.019.07-.028.141-.028.213 0 .163.13.294.29.294a.326.326 0 00.167-.054l1.903-1.114a.864.864 0 01.717-.098 10.16 10.16 0 002.537.323c.277 0 .543-.027.811-.05-.857-2.578.157-4.972 1.934-6.444 1.739-1.438 4.078-2.173 6.522-1.995-.567-3.733-4.078-6.616-8.587-6.616zm-2.6 4.408c.567 0 1.026.46 1.026 1.028 0 .566-.46 1.026-1.026 1.026-.567 0-1.026-.46-1.026-1.026 0-.567.459-1.028 1.026-1.028zm5.194 0c.567 0 1.026.46 1.026 1.028 0 .566-.46 1.026-1.026 1.026-.567 0-1.026-.46-1.026-1.026 0-.567.46-1.028 1.026-1.028zm4.902 3.26c-2.322-.089-4.478.566-6.078 1.887-1.598 1.328-2.537 3.234-2.537 5.236 0 4.054 3.891 7.342 8.691 7.342a10.16 10.16 0 002.537-.323.864.864 0 01.717.098l1.903 1.114a.326.326 0 00.167.054c.16 0 .29-.131.29-.294 0-.072-.01-.143-.028-.213l-.39-1.48a.59.59 0 01.213-.665c1.832-1.347 3.002-3.338 3.002-5.55 0-3.77-3.36-6.92-7.76-7.206h-.727zm-2.59 3.77c.567 0 1.026.46 1.026 1.026 0 .567-.46 1.026-1.026 1.026-.567 0-1.026-.46-1.026-1.026 0-.566.46-1.026 1.026-1.026zm5.194 0c.567 0 1.026.46 1.026 1.026 0 .567-.46 1.026-1.026 1.026-.567 0-1.026-.46-1.026-1.026 0-.566.46-1.026 1.026-1.026z"/></svg>
            微信
          </span>
        </button>
        <button onclick="switchSocialTab('qq')" id="socialTabQq" class="social-tab-btn">
          <span class="flex items-center gap-2">
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 13.27c-.33.59-.89 1.12-1.59 1.52-.12.07-.24.13-.37.19-.18.08-.36.15-.54.21-.36.12-.73.2-1.11.25-.19.02-.38.04-.57.04-.19 0-.38-.01-.57-.04-.38-.05-.75-.13-1.11-.25-.18-.06-.36-.13-.54-.21-.13-.06-.25-.12-.37-.19-.7-.4-1.26-.93-1.59-1.52-.06-.11-.11-.22-.16-.34-.05-.12-.09-.24-.13-.37-.08-.25-.13-.51-.16-.78-.02-.13-.03-.27-.03-.41 0-.14.01-.28.03-.41.03-.27.08-.53.16-.78.04-.13.08-.25.13-.37.05-.12.1-.23.16-.34.33-.59.89-1.12 1.59-1.52.12-.07.24-.13.37-.19.18-.08.36-.15.54-.21.36-.12.73-.2 1.11-.25.19-.02.38-.04.57-.04.19 0 .38.01.57.04.38.05.75.13 1.11.25.18.06.36.13.54.21.13.06.25.12.37.19.7.4 1.26.93 1.59 1.52.06.11.11.22.16.34.05.12.09.24.13.37.08.25.13.51.16.78.02.13.03.27.03.41 0 .14-.01.28-.03.41-.03.27-.08.53-.16.78-.04.13-.08.25-.13.37-.05.12-.1.23-.16.34z"/></svg>
            QQ
          </span>
        </button>
        <button onclick="switchSocialTab('feishu')" id="socialTabFeishu" class="social-tab-btn">
          <span class="flex items-center gap-2">
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            飞书
          </span>
        </button>
      </div>

      <div class="form-section">
        <div class="form-item">
          <label class="form-label">工具授权策略</label>
          <select id="socialAutoApproveTools" class="form-input">
            <option value="false" ${!data.social_auto_approve_tools ? 'selected' : ''}>询问用户后执行</option>
            <option value="true" ${data.social_auto_approve_tools ? 'selected' : ''}>自动允许工具调用</option>
          </select>
        </div>
      </div>

      <div class="form-section">
        <div class="form-item">
          <label class="form-label">对话上下文</label>
          <select id="socialRetainContext" class="form-input">
            <option value="false" ${!data.social_retain_context ? 'selected' : ''}>不保留（每条消息清空）</option>
            <option value="true" ${data.social_retain_context ? 'selected' : ''}>保留同一会话的上下文</option>
          </select>
          <p class="text-xs text-text-muted mt-1">上下文按平台和会话隔离，不会在不同用户之间共享。</p>
        </div>
      </div>

      <div class="form-section">
        <div class="form-item">
          <label class="form-label">自动清空间隔 <span class="text-text-muted text-xs">（用户消息数，0 表示不自动清空）</span></label>
          <input type="number" min="0" step="1" id="socialContextMaxMessages" class="form-input" value="${Math.max(0, Number(data.social_context_max_messages) || 0)}">
        </div>
      </div>

      <div id="socialTabContentWechat" class="social-tab-content" style="display: block;">
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">启用微信集成</label>
            <select id="socialWechatEnabled" class="form-input">
              <option value="true" ${data.wechat_enabled ? 'selected' : ''}>启用</option>
              <option value="false" ${!data.wechat_enabled ? 'selected' : ''}>禁用</option>
            </select>
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 App ID <span class="text-red-400">*</span></label>
            <input type="text" id="socialWechatAppId" class="form-input" placeholder="微信开放平台App ID" value="${data.wechat_app_id || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 App Secret <span class="text-red-400">*</span></label>
            <input type="password" id="socialWechatAppSecret" class="form-input" placeholder="微信开放平台App Secret" value="${data.wechat_app_secret || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 API URL <span class="text-text-muted text-xs">(可选，默认使用官方API)</span></label>
            <input type="text" id="socialWechatApiUrl" class="form-input" placeholder="https://api.weixin.qq.com (可选)" value="${data.wechat_api_url || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 Token <span class="text-text-muted text-xs">(可选，用于服务器验证)</span></label>
            <input type="password" id="socialWechatToken" class="form-input" placeholder="微信服务器验证Token" value="${data.wechat_token || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 AES Key <span class="text-text-muted text-xs">(可选，用于消息加密)</span></label>
            <input type="password" id="socialWechatAesKey" class="form-input" placeholder="消息加密AES Key" value="${data.wechat_aes_key || ''}">
          </div>
        </div>
        <div class="form-section">
          <div id="wechatTestResult" class="hidden"></div>
          <button onclick="testSocialPlatform('wechat')" id="wechatTestBtn" class="btn-secondary">
            <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            测试连接
          </button>
        </div>
      </div>

      <div id="socialTabContentQq" class="social-tab-content" style="display: none;">
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">启用QQ集成</label>
            <select id="socialQqEnabled" class="form-input">
              <option value="true" ${data.qq_enabled ? 'selected' : ''}>启用</option>
              <option value="false" ${!data.qq_enabled ? 'selected' : ''}>禁用</option>
            </select>
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">QQ App ID <span class="text-red-400">*</span></label>
            <input type="text" id="socialQqAppId" class="form-input" placeholder="QQ开放平台App ID" value="${data.qq_app_id || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">QQ App Secret <span class="text-red-400">*</span></label>
            <input type="password" id="socialQqAppSecret" class="form-input" placeholder="QQ开放平台App Secret" value="${data.qq_app_secret || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">QQ API URL <span class="text-text-muted text-xs">(可选，默认使用官方API)</span></label>
            <input type="text" id="socialQqApiUrl" class="form-input" placeholder="https://bots.qq.com (可选)" value="${data.qq_api_url || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">允许的 QQ 用户 <span class="text-text-muted text-xs">(逗号分隔，* 表示所有人)</span></label>
            <input type="text" id="socialQqAllowFrom" class="form-input" placeholder="*" value="${(data.qq_allow_from || []).join(',')}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">QQ 沙箱模式</label>
            <select id="socialQqSandbox" class="form-input">
              <option value="false" ${!data.qq_sandbox ? 'selected' : ''}>关闭</option>
              <option value="true" ${data.qq_sandbox ? 'selected' : ''}>开启</option>
            </select>
          </div>
        </div>
        <div class="form-section">
          <div id="qqTestResult" class="hidden"></div>
          <button onclick="testSocialPlatform('qq')" id="qqTestBtn" class="btn-secondary">
            <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            测试连接
          </button>
        </div>
      </div>

      <div id="socialTabContentFeishu" class="social-tab-content" style="display: none;">
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">启用飞书集成</label>
            <select id="socialFeishuEnabled" class="form-input">
              <option value="true" ${data.feishu_enabled ? 'selected' : ''}>启用</option>
              <option value="false" ${!data.feishu_enabled ? 'selected' : ''}>禁用</option>
            </select>
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">飞书 App ID <span class="text-red-400">*</span></label>
            <input type="text" id="socialFeishuAppId" class="form-input" placeholder="飞书开放平台App ID" value="${data.feishu_app_id || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">飞书 App Secret <span class="text-red-400">*</span></label>
            <input type="password" id="socialFeishuAppSecret" class="form-input" placeholder="飞书开放平台App Secret" value="${data.feishu_app_secret || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">飞书 API URL <span class="text-text-muted text-xs">(可选，默认使用官方API)</span></label>
            <input type="text" id="socialFeishuApiUrl" class="form-input" placeholder="https://open.feishu.cn (可选)" value="${data.feishu_api_url || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">Encrypt Key <span class="text-text-muted text-xs">(可选，用于事件订阅加密)</span></label>
            <input type="password" id="socialFeishuEncryptKey" class="form-input" placeholder="飞书Encrypt Key" value="${data.feishu_encrypt_key || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">Verification Token <span class="text-text-muted text-xs">(可选，用于事件订阅验证)</span></label>
            <input type="password" id="socialFeishuVerificationToken" class="form-input" placeholder="飞书Verification Token" value="${data.feishu_verification_token || ''}">
          </div>
        </div>
        <div class="form-section">
          <div id="feishuTestResult" class="hidden"></div>
          <button onclick="testSocialPlatform('feishu')" id="feishuTestBtn" class="btn-secondary">
            <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            测试连接
          </button>
        </div>
      </div>

      <div class="flex flex-wrap gap-2 items-center pt-4 border-t border-dark-border">
        <button onclick="saveSocialSettings()" class="btn-primary">保存</button>
      </div>
    `;
  } catch (e) {
    document.getElementById('socialSettings').innerHTML = '<div class="text-sm text-red-500">加载失败</div>';
  }
}

// Plugins
let allPlugins = [];

async function loadPlugins() {
  try {
    const res = await fetch('/api/plugins');
    const data = await res.json();
    allPlugins = Array.isArray(data) ? data : [];
    renderPluginsList(allPlugins);
  } catch (e) {
    document.getElementById('pluginList').innerHTML = '<div class="text-sm text-red-400">加载失败</div>';
  }
}

function renderPluginsList(plugins) {
  const container = document.getElementById('pluginList');
  if (!plugins || plugins.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无插件</div>';
    return;
  }
  container.innerHTML = plugins.map(p => `
    <div class="flex flex-wrap gap-3 items-center p-3.5 bg-dark-bg-secondary border border-dark-border rounded-lg animate-fade-in">
      <div class="flex-1 min-w-[150px]">
        <span class="text-sm font-medium text-text-primary">${p.name}</span>
        <span class="text-xs text-text-muted ml-2">v${p.version || '0.0.0'}</span>
      </div>
      <div class="flex-1 min-w-[200px]">
        <span class="text-xs text-text-secondary truncate block">${p.description || ''}</span>
      </div>
      <div class="flex flex-wrap gap-2 items-center ml-auto">
        <span class="text-xs px-2 py-1 rounded ${p.enabled ? 'bg-accent-green/10 text-accent-green' : 'bg-text-muted/10 text-text-muted'}">${p.enabled ? '已启用' : '已禁用'}</span>
        <button onclick="togglePlugin('${p.name}')" class="btn-secondary text-xs px-2.5 py-1.5">${p.enabled ? '禁用' : '启用'}</button>
        <button onclick="uninstallPlugin('${p.name}')" class="btn-danger text-xs px-2.5 py-1.5">卸载</button>
      </div>
    </div>
  `).join('');
}

function showInstallPluginForm() {
  document.getElementById('newPluginPath').value = '';
  document.getElementById('installPluginModal').classList.remove('hidden');
}

function closeInstallPluginModal() {
  document.getElementById('installPluginModal').classList.add('hidden');
}

async function installPlugin() {
  const path = document.getElementById('newPluginPath').value.trim();
  if (!path) {
    alert('请输入插件路径');
    return;
  }
  try {
    const res = await fetch('/api/plugins/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    if (!res.ok) {
      const err = await res.json();
      alert('安装失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    closeInstallPluginModal();
    await loadPlugins();
    alert('插件已安装');
  } catch (e) {
    alert('安装失败: ' + e.message);
  }
}

async function togglePlugin(name) {
  try {
    const res = await fetch(`/api/plugins/${encodeURIComponent(name)}/toggle`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      alert('操作失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadPlugins();
  } catch (e) {
    alert('操作失败: ' + e.message);
  }
}

async function uninstallPlugin(name) {
  if (!confirm(`确定卸载插件 "${name}"?`)) return;
  try {
    const res = await fetch(`/api/plugins/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json();
      alert('卸载失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadPlugins();
    alert('插件已卸载');
  } catch (e) {
    alert('卸载失败: ' + e.message);
  }
}

// MCP Servers
let allMcpServers = [];

async function loadMcpServers() {
  try {
    const res = await fetch('/api/mcp/servers');
    const data = await res.json();
    allMcpServers = Array.isArray(data) ? data : [];
    renderMcpServersList(allMcpServers);
  } catch (e) {
    document.getElementById('mcpServerList').innerHTML = '<div class="text-sm text-red-400">加载失败</div>';
  }
}

function renderMcpServersList(servers) {
  const container = document.getElementById('mcpServerList');
  if (!servers || servers.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无 MCP 服务器</div>';
    return;
  }
  container.innerHTML = servers.map(s => `
    <div class="flex flex-wrap gap-3 items-center p-3.5 bg-dark-bg-secondary border border-dark-border rounded-lg animate-fade-in">
      <div class="flex-1 min-w-[150px]">
        <span class="text-sm font-medium text-text-primary">${s.name}</span>
      </div>
      <div class="flex-1 min-w-[200px]">
        <span class="text-xs text-text-secondary truncate block">${s.command || ''} ${(s.args || []).join(' ')}</span>
      </div>
      <div class="flex flex-wrap gap-2 items-center ml-auto">
        <span class="text-xs px-2 py-1 rounded ${s.enabled ? 'bg-accent-green/10 text-accent-green' : 'bg-text-muted/10 text-text-muted'}">${s.enabled ? '已启用' : '已禁用'}</span>
        <button onclick="toggleMcpServer('${s.name}')" class="btn-secondary text-xs px-2.5 py-1.5">${s.enabled ? '禁用' : '启用'}</button>
        <button onclick="deleteMcpServer('${s.name}')" class="btn-danger text-xs px-2.5 py-1.5">删除</button>
      </div>
    </div>
  `).join('');
}

function showAddMcpForm() {
  document.getElementById('newMcpName').value = '';
  document.getElementById('newMcpCommand').value = '';
  document.getElementById('newMcpArgs').value = '';
  document.getElementById('addMcpModal').classList.remove('hidden');
}

function closeAddMcpModal() {
  document.getElementById('addMcpModal').classList.add('hidden');
}

async function addMcpServer() {
  const name = document.getElementById('newMcpName').value.trim();
  const command = document.getElementById('newMcpCommand').value.trim();
  const argsStr = document.getElementById('newMcpArgs').value.trim();
  if (!name || !command) {
    alert('请输入服务器名称和命令');
    return;
  }
  let args = [];
  if (argsStr) {
    try {
      args = JSON.parse(argsStr);
    } catch (e) {
      alert('参数格式错误，请输入有效的JSON数组');
      return;
    }
  }
  try {
    const res = await fetch('/api/mcp/servers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, command, args })
    });
    if (!res.ok) {
      const err = await res.json();
      alert('添加失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    closeAddMcpModal();
    await loadMcpServers();
    alert('MCP 服务器已添加');
  } catch (e) {
    alert('添加失败: ' + e.message);
  }
}

async function toggleMcpServer(name) {
  try {
    const res = await fetch(`/api/mcp/servers/${encodeURIComponent(name)}/toggle`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      alert('操作失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadMcpServers();
  } catch (e) {
    alert('操作失败: ' + e.message);
  }
}

async function deleteMcpServer(name) {
  if (!confirm(`确定删除 MCP 服务器 "${name}"?`)) return;
  try {
    const res = await fetch(`/api/mcp/servers/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json();
      alert('删除失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadMcpServers();
    alert('MCP 服务器已删除');
  } catch (e) {
    alert('删除失败: ' + e.message);
  }
}

// Sessions
let allSessions = [];

async function loadSessions() {
  try {
    const res = await fetch('/api/sessions');
    const data = await res.json();
    allSessions = Array.isArray(data) ? data : [];
    renderSessionsList(allSessions);
  } catch (e) {
    document.getElementById('sessionList').innerHTML = '<div class="text-sm text-red-400">加载失败</div>';
  }
}

function renderSessionsList(sessions) {
  const container = document.getElementById('sessionList');
  if (!sessions || sessions.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无会话</div>';
    return;
  }
  container.innerHTML = sessions.map(s => {
    const sessionId = s.id || s.session_id || 'Unknown';
    const summary = s.summary || sessionId;
    const messageCount = s.message_count || 0;
    const forkedFrom = s.forked_from ? `<span class="text-xs text-accent-blue ml-2">[派生自 ${s.forked_from}]</span>` : '';
    return `
    <div class="flex flex-wrap gap-3 items-center p-3.5 bg-dark-bg-secondary border border-dark-border rounded-lg animate-fade-in">
      <div class="flex-1 min-w-[150px]">
        <span class="text-sm font-medium text-text-primary">${escapeHtml(summary)}</span>
        ${forkedFrom}
      </div>
      <div class="flex-1 min-w-[200px]">
        <span class="text-xs text-text-secondary">${sessionId}</span>
        <span class="text-xs text-text-muted ml-2">${messageCount} 条消息</span>
      </div>
      <div class="flex flex-wrap gap-2 items-center ml-auto">
        <button onclick="forkSessionFromList('${sessionId}')" class="btn-secondary text-xs px-2.5 py-1.5" title="从对话中派生">
          <svg class="w-3.5 h-3.5 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/>
          </svg>
          派生
        </button>
        <button onclick="deleteSession('${sessionId}')" class="btn-danger text-xs px-2.5 py-1.5">删除</button>
      </div>
    </div>
  `}).join('');
}

async function forkSessionFromList(sessionId) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/user-messages`);
    const data = await res.json();

    if (data.error || !data.user_messages || data.user_messages.length === 0) {
      alert('该会话中没有用户消息，无法派生');
      return;
    }

    const userMessages = data.user_messages;
    const messageOptions = userMessages.map((um, idx) => {
      return `<option value="${um.index}">[${um.index}] ${escapeHtml(um.preview)}</option>`;
    }).join('');

    const dialogHtml = `
      <div id="forkDialogOverlay" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 1000; display: flex; align-items: center; justify-content: center;">
        <div style="background: #1e1e2e; border: 1px solid #313244; border-radius: 8px; padding: 24px; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto;">
          <h3 style="color: #cdd6f4; margin: 0 0 16px 0; font-size: 18px;">从对话中派生新会话</h3>
          <p style="color: #a6adc8; font-size: 14px; margin-bottom: 16px;">选择要派生的用户消息位置：</p>
          <select id="forkMessageIndex" style="width: 100%; padding: 8px; background: #181825; border: 1px solid #313244; border-radius: 4px; color: #cdd6f4; margin-bottom: 16px;">
            ${messageOptions}
          </select>
          <div style="margin-bottom: 16px;">
            <label style="color: #a6adc8; font-size: 14px; display: block; margin-bottom: 8px;">新会话 ID（可选）：</label>
            <input type="text" id="forkNewSessionId" placeholder="留空将自动生成" style="width: 100%; padding: 8px; background: #181825; border: 1px solid #313244; border-radius: 4px; color: #cdd6f4;">
          </div>
          <div style="display: flex; gap: 12px; justify-content: flex-end;">
            <button onclick="closeForkDialog()" style="padding: 8px 16px; background: #313244; border: none; border-radius: 4px; color: #cdd6f4; cursor: pointer;">取消</button>
            <button onclick="executeForkFromList('${sessionId}')" style="padding: 8px 16px; background: #89b4fa; border: none; border-radius: 4px; color: #1e1e2e; cursor: pointer; font-weight: 500;">派生</button>
          </div>
        </div>
      </div>
    `;

    document.body.insertAdjacentHTML('beforeend', dialogHtml);
  } catch (e) {
    alert('加载用户消息失败: ' + e.message);
  }
}

async function executeForkFromList(sessionId) {
  const messageIndex = parseInt(document.getElementById('forkMessageIndex').value);
  const newSessionId = document.getElementById('forkNewSessionId').value.trim() || undefined;

  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/fork`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message_index: messageIndex,
        new_session_id: newSessionId,
      }),
    });

    const data = await res.json();
    if (data.error) {
      alert('派生失败: ' + data.error);
      return;
    }

    closeForkDialog();
    alert(`派生成功！\n新会话 ID: ${data.forked_session_id}\n从消息 ${data.forked_at_index} 处派生`);
    await loadSessions();
  } catch (e) {
    alert('派生失败: ' + e.message);
  }
}

async function deleteSession(id) {
  if (!confirm(`确定删除会话 "${id}"?`)) return;
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json();
      alert('删除失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadSessions();
    alert('会话已删除');
  } catch (e) {
    alert('删除失败: ' + e.message);
  }
}

// Tasks
let allTasks = [];

async function loadTasks() {
  try {
    const res = await fetch('/api/tasks');
    const data = await res.json();
    allTasks = Array.isArray(data) ? data : [];
    renderTasksList(allTasks);
  } catch (e) {
    document.getElementById('taskList').innerHTML = '<div class="text-sm text-red-400">加载失败</div>';
  }
}

function renderTasksList(tasks) {
  const container = document.getElementById('taskList');
  if (!tasks || tasks.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无任务</div>';
    return;
  }
  container.innerHTML = tasks.map(t => {
    const statusColor = t.status === 'completed' ? 'bg-accent-green/10 text-accent-green' :
                       t.status === 'running' ? 'bg-accent-blue/10 text-accent-blue' :
                       t.status === 'failed' ? 'bg-red-500/10 text-red-400' : 'bg-text-muted/10 text-text-muted';
    return `
    <div class="flex flex-wrap gap-3 items-center p-3.5 bg-dark-bg-secondary border border-dark-border rounded-lg animate-fade-in">
      <div class="flex-1 min-w-[150px]">
        <span class="text-sm font-medium text-text-primary">${t.id}</span>
        <span class="text-xs text-text-muted ml-2">${t.type || ''}</span>
      </div>
      <div class="flex-1 min-w-[200px]">
        <span class="text-xs text-text-secondary truncate block">${t.description || t.command || ''}</span>
      </div>
      <div class="flex flex-wrap gap-2 items-center ml-auto">
        <span class="text-xs px-2 py-1 rounded ${statusColor}">${t.status || 'unknown'}</span>
      </div>
    </div>
  `}).join('');
}

// Introspection Settings
let introProfilesCache = [];

async function loadIntrospectionSettings() {
  try {
    const [settingsRes, profilesRes] = await Promise.all([
      fetch('/api/introspection/settings'),
      fetch('/api/settings')
    ]);
    const settings = await settingsRes.json();
    const profilesData = await profilesRes.json();
    introProfilesCache = profilesData.profiles || [];

    document.getElementById('introEnabled').value = String(settings.enabled);
    document.getElementById('introAutoReflect').value = String(settings.auto_reflect);
    document.getElementById('introMinConfidence').value = settings.min_confidence_threshold;
    document.getElementById('introTopK').value = settings.top_k_experiences;
    document.getElementById('introTimeout').value = settings.reflection_timeout_seconds;
    document.getElementById('introInjectionMode').value = settings.injection_mode;
    document.getElementById('introMinToolCalls').value = settings.min_tool_calls_for_reflection;

    // Populate provider dropdown
    const providerSelect = document.getElementById('introReflectionProvider');
    providerSelect.innerHTML = '<option value="">（跟随当前 Agent）</option>';
    introProfilesCache.forEach(p => {
      if (p.configured) {
        const opt = document.createElement('option');
        opt.value = p.name;
        opt.textContent = `${p.label} (${p.name})`;
        providerSelect.appendChild(opt);
      }
    });
    providerSelect.value = settings.reflection_provider || '';

    // Load models for selected provider
    await onIntroProviderChange();
  } catch (e) {
    console.error('Failed to load introspection settings:', e);
  }

  // Restore saved reflection model after models are loaded
  const modelSelect = document.getElementById('introReflectionModel');
  if (modelSelect && settings.reflection_model) {
    modelSelect.value = settings.reflection_model;
  }
}

async function onIntroProviderChange() {
  const providerSelect = document.getElementById('introReflectionProvider');
  const modelSelect = document.getElementById('introReflectionModel');
  const provider = providerSelect ? providerSelect.value : '';
  if (!modelSelect) return;
  modelSelect.innerHTML = '<option value="">（使用供应商默认模型）</option>';

  if (!provider) return;

  try {
    const url = '/api/profile/' + encodeURIComponent(provider) + '/models';
    const res = await fetch(url);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const models = data.models || [];
    models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.textContent = m;
      modelSelect.appendChild(opt);
    });
    console.log('Introspection models loaded for ' + provider + ':', models);
  } catch (e) {
    console.error('Failed to fetch introspection models for ' + provider + ':', e);
  }
}

async function saveIntrospectionSettings() {
  const body = {
    enabled: document.getElementById('introEnabled').value === 'true',
    auto_reflect: document.getElementById('introAutoReflect').value === 'true',
    reflection_provider: document.getElementById('introReflectionProvider').value,
    reflection_model: document.getElementById('introReflectionModel').value,
    min_confidence_threshold: parseFloat(document.getElementById('introMinConfidence').value),
    top_k_experiences: parseInt(document.getElementById('introTopK').value),
    reflection_timeout_seconds: parseFloat(document.getElementById('introTimeout').value),
    injection_mode: document.getElementById('introInjectionMode').value,
    min_tool_calls_for_reflection: parseInt(document.getElementById('introMinToolCalls').value),
  };
  try {
    const res = await fetch('/api/introspection/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const result = await res.json();
    if (result.status === 'ok') {
      showToast('自省配置已保存', 'success');
    } else {
      showToast('保存失败', 'error');
    }
  } catch (e) {
    showToast('保存失败: ' + e.message, 'error');
  }
}

// Introspection
async function loadIntrospection() {
  const source = document.getElementById('introspectionSourceFilter')?.value || '';
  const query = source ? `?source_kind=${encodeURIComponent(source)}` : '';
  try {
    const [eventsRes, reflectionsRes] = await Promise.all([
      fetch('/api/introspection/events' + query),
      fetch('/api/introspection/reflections')
    ]);
    const eventsData = await eventsRes.json();
    const reflectionsData = await reflectionsRes.json();
    renderIntrospectionReflections(reflectionsData.reflections || []);
    renderIntrospectionEvents(eventsData.events || []);
  } catch (e) {
    document.getElementById('introspectionReflections').innerHTML = '<div class="text-sm text-red-400">加载失败</div>';
    document.getElementById('introspectionEvents').innerHTML = '';
  }
}

function renderIntrospectionReflections(reflections) {
  const container = document.getElementById('introspectionReflections');
  if (!reflections || reflections.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无自省运行</div>';
    return;
  }
  container.innerHTML = reflections.slice(0, 20).map(r => {
    const statusColor = r.status === 'completed' ? 'bg-accent-green/10 text-accent-green' :
                       r.status === 'running' ? 'bg-accent-blue/10 text-accent-blue' :
                       r.status === 'skipped' ? 'bg-text-muted/10 text-text-muted' :
                       'bg-red-500/10 text-red-400';
    return `
    <div class="p-3.5 bg-dark-bg-secondary border border-dark-border rounded-lg">
      <div class="flex flex-wrap gap-2 items-center">
        <span class="text-sm font-medium text-text-primary">${escapeHtml(r.reflection_id || '')}</span>
        <span class="text-xs px-2 py-1 rounded ${statusColor}">${escapeHtml(r.status || 'unknown')}</span>
        <span class="text-xs text-text-muted">${escapeHtml(r.source_kind || '')}</span>
        <span class="text-xs text-text-muted ml-auto">${escapeHtml(r.end_time || '')}</span>
      </div>
      <div class="text-xs text-text-secondary mt-2">${escapeHtml(r.summary || '')}</div>
      <div class="text-xs text-text-muted mt-1">memory: ${Number(r.memory_count || 0)} ${r.outcome ? ' · ' + escapeHtml(r.outcome) : ''}</div>
    </div>`;
  }).join('');
}

function renderIntrospectionEvents(events) {
  const container = document.getElementById('introspectionEvents');
  if (!events || events.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">暂无自省日志</div>';
    return;
  }
  container.innerHTML = events.slice(0, 200).map(e => {
    const levelColor = e.level === 'ERROR' ? 'text-red-400' :
                      e.level === 'WARNING' ? 'text-accent-amber' :
                      e.level === 'DEBUG' ? 'text-text-muted' : 'text-accent-blue';
    const text = e.display_text || e.summary || '';
    return `
    <div class="p-3 bg-dark-bg-secondary border border-dark-border rounded-lg">
      <div class="flex flex-wrap gap-2 items-center text-xs">
        <span class="${levelColor}">${escapeHtml(e.level || 'INFO')}</span>
        <span class="text-text-primary">${escapeHtml(e.event || '')}</span>
        <span class="text-text-muted">${escapeHtml(e.source_kind || '')}</span>
        <span class="text-text-muted ml-auto">${escapeHtml(e.timestamp || '')}</span>
      </div>
      ${text ? `<div class="text-xs text-text-secondary mt-2 leading-relaxed">${escapeHtml(text)}</div>` : ''}
      ${e.reflection_id ? `<div class="text-[11px] text-text-muted mt-1">${escapeHtml(e.reflection_id)}</div>` : ''}
    </div>`;
  }).join('');
}

// Social
async function loadSocialSettings() {
  try {
    const res = await fetch('/api/social-platforms');
    const data = await res.json();
    const container = document.getElementById('socialSettings');
    container.innerHTML = `
      <div class="flex gap-2 mb-6 border-b border-dark-border pb-4">
        <button onclick="switchSocialTab('wechat')" id="socialTabWechat" class="social-tab-btn active">
          <span class="flex items-center gap-2">
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 01.213.665l-.39 1.48c-.019.07-.028.141-.028.213 0 .163.13.294.29.294a.326.326 0 00.167-.054l1.903-1.114a.864.864 0 01.717-.098 10.16 10.16 0 002.537.323c.277 0 .543-.027.811-.05-.857-2.578.157-4.972 1.934-6.444 1.739-1.438 4.078-2.173 6.522-1.995-.567-3.733-4.078-6.616-8.587-6.616zm-2.6 4.408c.567 0 1.026.46 1.026 1.028 0 .566-.46 1.026-1.026 1.026-.567 0-1.026-.46-1.026-1.026 0-.567.459-1.028 1.026-1.028zm5.194 0c.567 0 1.026.46 1.026 1.028 0 .566-.46 1.026-1.026 1.026-.567 0-1.026-.46-1.026-1.026 0-.567.46-1.028 1.026-1.028zm4.902 3.26c-2.322-.089-4.478.566-6.078 1.887-1.598 1.328-2.537 3.234-2.537 5.236 0 4.054 3.891 7.342 8.691 7.342a10.16 10.16 0 002.537-.323.864.864 0 01.717.098l1.903 1.114a.326.326 0 00.167.054c.16 0 .29-.131.29-.294 0-.072-.01-.143-.028-.213l-.39-1.48a.59.59 0 01.213-.665c1.832-1.347 3.002-3.338 3.002-5.55 0-3.77-3.36-6.92-7.76-7.206h-.727zm-2.59 3.77c.567 0 1.026.46 1.026 1.026 0 .567-.46 1.026-1.026 1.026-.567 0-1.026-.46-1.026-1.026 0-.566.46-1.026 1.026-1.026zm5.194 0c.567 0 1.026.46 1.026 1.026 0 .567-.46 1.026-1.026 1.026-.567 0-1.026-.46-1.026-1.026 0-.566.46-1.026 1.026-1.026z"/></svg>
            微信
          </span>
        </button>
        <button onclick="switchSocialTab('qq')" id="socialTabQq" class="social-tab-btn">
          <span class="flex items-center gap-2">
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 13.27c-.33.59-.89 1.12-1.59 1.52-.12.07-.24.13-.37.19-.18.08-.36.15-.54.21-.36.12-.73.2-1.11.25-.19.02-.38.04-.57.04-.19 0-.38-.01-.57-.04-.38-.05-.75-.13-1.11-.25-.18-.06-.36-.13-.54-.21-.13-.06-.25-.12-.37-.19-.7-.4-1.26-.93-1.59-1.52-.06-.11-.11-.22-.16-.34-.05-.12-.09-.24-.13-.37-.08-.25-.13-.51-.16-.78-.02-.13-.03-.27-.03-.41 0-.14.01-.28.03-.41.03-.27.08-.53.16-.78.04-.13.08-.25.13-.37.05-.12.1-.23.16-.34.33-.59.89-1.12 1.59-1.52.12-.07.24-.13.37-.19.18-.08.36-.15.54-.21.36-.12.73-.2 1.11-.25.19-.02.38-.04.57-.04.19 0 .38.01.57.04.38.05.75.13 1.11.25.18.06.36.13.54.21.13.06.25.12.37.19.7.4 1.26.93 1.59 1.52.06.11.11.22.16.34.05.12.09.24.13.37.08.25.13.51.16.78.02.13.03.27.03.41 0 .14-.01.28-.03.41-.03.27-.08.53-.16.78-.04.13-.08.25-.13.37-.05.12-.1.23-.16.34z"/></svg>
            QQ
          </span>
        </button>
        <button onclick="switchSocialTab('feishu')" id="socialTabFeishu" class="social-tab-btn">
          <span class="flex items-center gap-2">
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            飞书
          </span>
        </button>
      </div>

      <div class="form-section">
        <div class="form-item">
          <label class="form-label">工具授权策略</label>
          <select id="socialAutoApproveTools" class="form-input">
            <option value="false" ${!data.social_auto_approve_tools ? 'selected' : ''}>询问用户后执行</option>
            <option value="true" ${data.social_auto_approve_tools ? 'selected' : ''}>自动允许工具调用</option>
          </select>
        </div>
      </div>

      <div class="form-section">
        <div class="form-item">
          <label class="form-label">对话上下文</label>
          <select id="socialRetainContext" class="form-input">
            <option value="false" ${!data.social_retain_context ? 'selected' : ''}>不保留（每条消息清空）</option>
            <option value="true" ${data.social_retain_context ? 'selected' : ''}>保留同一会话的上下文</option>
          </select>
          <p class="text-xs text-text-muted mt-1">上下文按平台和会话隔离，不会在不同用户之间共享。</p>
        </div>
      </div>

      <div class="form-section">
        <div class="form-item">
          <label class="form-label">自动清空间隔 <span class="text-text-muted text-xs">（用户消息数，0 表示不自动清空）</span></label>
          <input type="number" min="0" step="1" id="socialContextMaxMessages" class="form-input" value="${Math.max(0, Number(data.social_context_max_messages) || 0)}">
        </div>
      </div>

      <div id="socialTabContentWechat" class="social-tab-content" style="display: block;">
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">启用微信集成</label>
            <select id="socialWechatEnabled" class="form-input">
              <option value="true" ${data.wechat_enabled ? 'selected' : ''}>启用</option>
              <option value="false" ${!data.wechat_enabled ? 'selected' : ''}>禁用</option>
            </select>
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 App ID <span class="text-red-400">*</span></label>
            <input type="text" id="socialWechatAppId" class="form-input" placeholder="微信开放平台App ID" value="${data.wechat_app_id || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 App Secret <span class="text-red-400">*</span></label>
            <input type="password" id="socialWechatAppSecret" class="form-input" placeholder="微信开放平台App Secret" value="${data.wechat_app_secret || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 API URL <span class="text-text-muted text-xs">(可选，默认使用官方API)</span></label>
            <input type="text" id="socialWechatApiUrl" class="form-input" placeholder="https://api.weixin.qq.com (可选)" value="${data.wechat_api_url || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 Token <span class="text-text-muted text-xs">(可选，用于服务器验证)</span></label>
            <input type="password" id="socialWechatToken" class="form-input" placeholder="微信服务器验证Token" value="${data.wechat_token || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">微信 AES Key <span class="text-text-muted text-xs">(可选，用于消息加密)</span></label>
            <input type="password" id="socialWechatAesKey" class="form-input" placeholder="消息加密AES Key" value="${data.wechat_aes_key || ''}">
          </div>
        </div>
        <div class="form-section">
          <div id="wechatTestResult" class="hidden"></div>
          <button onclick="testSocialPlatform('wechat')" id="wechatTestBtn" class="btn-secondary">
            <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            测试连接
          </button>
        </div>
      </div>

      <div id="socialTabContentQq" class="social-tab-content" style="display: none;">
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">启用QQ集成</label>
            <select id="socialQqEnabled" class="form-input">
              <option value="true" ${data.qq_enabled ? 'selected' : ''}>启用</option>
              <option value="false" ${!data.qq_enabled ? 'selected' : ''}>禁用</option>
            </select>
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">QQ App ID <span class="text-red-400">*</span></label>
            <input type="text" id="socialQqAppId" class="form-input" placeholder="QQ开放平台App ID" value="${data.qq_app_id || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">QQ App Secret <span class="text-red-400">*</span></label>
            <input type="password" id="socialQqAppSecret" class="form-input" placeholder="QQ开放平台App Secret" value="${data.qq_app_secret || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">QQ API URL <span class="text-text-muted text-xs">(可选，默认使用官方API)</span></label>
            <input type="text" id="socialQqApiUrl" class="form-input" placeholder="https://bots.qq.com (可选)" value="${data.qq_api_url || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">允许的 QQ 用户 <span class="text-text-muted text-xs">(逗号分隔，* 表示所有人)</span></label>
            <input type="text" id="socialQqAllowFrom" class="form-input" placeholder="*" value="${(data.qq_allow_from || []).join(',')}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">QQ 沙箱模式</label>
            <select id="socialQqSandbox" class="form-input">
              <option value="false" ${!data.qq_sandbox ? 'selected' : ''}>关闭</option>
              <option value="true" ${data.qq_sandbox ? 'selected' : ''}>开启</option>
            </select>
          </div>
        </div>
        <div class="form-section">
          <div id="qqTestResult" class="hidden"></div>
          <button onclick="testSocialPlatform('qq')" id="qqTestBtn" class="btn-secondary">
            <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            测试连接
          </button>
        </div>
      </div>

      <div id="socialTabContentFeishu" class="social-tab-content" style="display: none;">
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">启用飞书集成</label>
            <select id="socialFeishuEnabled" class="form-input">
              <option value="true" ${data.feishu_enabled ? 'selected' : ''}>启用</option>
              <option value="false" ${!data.feishu_enabled ? 'selected' : ''}>禁用</option>
            </select>
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">飞书 App ID <span class="text-red-400">*</span></label>
            <input type="text" id="socialFeishuAppId" class="form-input" placeholder="飞书开放平台App ID" value="${data.feishu_app_id || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">飞书 App Secret <span class="text-red-400">*</span></label>
            <input type="password" id="socialFeishuAppSecret" class="form-input" placeholder="飞书开放平台App Secret" value="${data.feishu_app_secret || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">飞书 API URL <span class="text-text-muted text-xs">(可选，默认使用官方API)</span></label>
            <input type="text" id="socialFeishuApiUrl" class="form-input" placeholder="https://open.feishu.cn (可选)" value="${data.feishu_api_url || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">Encrypt Key <span class="text-text-muted text-xs">(可选，用于事件订阅加密)</span></label>
            <input type="password" id="socialFeishuEncryptKey" class="form-input" placeholder="飞书Encrypt Key" value="${data.feishu_encrypt_key || ''}">
          </div>
        </div>
        <div class="form-section">
          <div class="form-item">
            <label class="form-label">Verification Token <span class="text-text-muted text-xs">(可选，用于事件订阅验证)</span></label>
            <input type="password" id="socialFeishuVerificationToken" class="form-input" placeholder="飞书Verification Token" value="${data.feishu_verification_token || ''}">
          </div>
        </div>
        <div class="form-section">
          <div id="feishuTestResult" class="hidden"></div>
          <button onclick="testSocialPlatform('feishu')" id="feishuTestBtn" class="btn-secondary">
            <svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            测试连接
          </button>
        </div>
      </div>

      <div class="flex flex-wrap gap-2 items-center pt-4 border-t border-dark-border">
        <button onclick="saveSocialSettings()" class="btn-primary">保存</button>
      </div>
    `;
  } catch (e) {
    document.getElementById('socialSettings').innerHTML = '<div class="text-sm text-red-500">加载失败</div>';
  }
}

function switchSocialTab(tab) {
  document.querySelectorAll('.social-tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.social-tab-content').forEach(content => content.style.display = 'none');

  document.getElementById('socialTab' + tab.charAt(0).toUpperCase() + tab.slice(1)).classList.add('active');
  document.getElementById('socialTabContent' + tab.charAt(0).toUpperCase() + tab.slice(1)).style.display = 'block';
}

async function saveSocialSettings() {
  const contextMaxMessages = Number.parseInt(document.getElementById('socialContextMaxMessages').value, 10);
  const data = {
    social_auto_approve_tools: document.getElementById('socialAutoApproveTools').value === 'true',
    social_retain_context: document.getElementById('socialRetainContext').value === 'true',
    social_context_max_messages: Number.isFinite(contextMaxMessages) ? Math.max(0, contextMaxMessages) : 0,
    wechat_enabled: document.getElementById('socialWechatEnabled').value === 'true',
    wechat_api_url: document.getElementById('socialWechatApiUrl').value,
    wechat_app_id: document.getElementById('socialWechatAppId').value,
    wechat_app_secret: document.getElementById('socialWechatAppSecret').value,
    wechat_token: document.getElementById('socialWechatToken').value,
    wechat_aes_key: document.getElementById('socialWechatAesKey').value,
    qq_enabled: document.getElementById('socialQqEnabled').value === 'true',
    qq_api_url: document.getElementById('socialQqApiUrl').value,
    qq_app_id: document.getElementById('socialQqAppId').value,
    qq_app_secret: document.getElementById('socialQqAppSecret').value,
    qq_allow_from: document.getElementById('socialQqAllowFrom').value.split(',').map(s => s.trim()).filter(Boolean),
    qq_sandbox: document.getElementById('socialQqSandbox').value === 'true',
    feishu_enabled: document.getElementById('socialFeishuEnabled').value === 'true',
    feishu_api_url: document.getElementById('socialFeishuApiUrl').value,
    feishu_app_id: document.getElementById('socialFeishuAppId').value,
    feishu_app_secret: document.getElementById('socialFeishuAppSecret').value,
    feishu_encrypt_key: document.getElementById('socialFeishuEncryptKey').value,
    feishu_verification_token: document.getElementById('socialFeishuVerificationToken').value
  };
  try {
    const res = await fetch('/api/social-platforms', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert('保存失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    alert('社交设置已保存');
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

async function testSocialPlatform(platformName) {
  const btn = document.getElementById(platformName + 'TestBtn');
  const resultDiv = document.getElementById(platformName + 'TestResult');

  btn.disabled = true;
  btn.innerHTML = '<svg class="w-4 h-4 inline mr-1 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> 测试中...';
  resultDiv.className = 'test-result';
  resultDiv.innerHTML = '';

  let testData = {};
  if (platformName === 'wechat') {
    testData = {
      enabled: document.getElementById('socialWechatEnabled').value === 'true',
      api_url: document.getElementById('socialWechatApiUrl').value,
      app_id: document.getElementById('socialWechatAppId').value,
      app_secret: document.getElementById('socialWechatAppSecret').value,
      token: document.getElementById('socialWechatToken').value,
      aes_key: document.getElementById('socialWechatAesKey').value
    };
  } else if (platformName === 'qq') {
    testData = {
      enabled: document.getElementById('socialQqEnabled').value === 'true',
      api_url: document.getElementById('socialQqApiUrl').value,
      app_id: document.getElementById('socialQqAppId').value,
      app_secret: document.getElementById('socialQqAppSecret').value,
      allow_from: document.getElementById('socialQqAllowFrom').value.split(',').map(s => s.trim()).filter(Boolean),
      sandbox: document.getElementById('socialQqSandbox').value === 'true'
    };
  } else if (platformName === 'feishu') {
    testData = {
      enabled: document.getElementById('socialFeishuEnabled').value === 'true',
      api_url: document.getElementById('socialFeishuApiUrl').value,
      app_id: document.getElementById('socialFeishuAppId').value,
      app_secret: document.getElementById('socialFeishuAppSecret').value,
      encrypt_key: document.getElementById('socialFeishuEncryptKey').value,
      verification_token: document.getElementById('socialFeishuVerificationToken').value,
      domain: document.getElementById('socialFeishuApiUrl').value || 'https://open.feishu.cn'
    };
  }

  try {
    const res = await fetch(`/api/social-platforms/${platformName}/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(testData)
    });

    const result = await res.json();

    if (result.success) {
      resultDiv.className = 'test-result test-success';
      let detailsHtml = '';
      if (result.details && Object.keys(result.details).length > 0) {
        const details = result.details;
        detailsHtml = '<div class="mt-2 pt-2 border-t border-accent-green/20">';
        detailsHtml += '<div class="text-xs text-text-muted mb-1">详细信息：</div>';
        if (details.app_id) {
          detailsHtml += `<div class="text-xs text-text-muted">• App ID: ${details.app_id}</div>`;
        }
        if (details.expires_in) {
          detailsHtml += `<div class="text-xs text-text-muted">• Token有效期: ${details.expires_in}秒</div>`;
        }
        if (details.access_token) {
          detailsHtml += `<div class="text-xs text-text-muted">• 获取Token成功</div>`;
        }
        detailsHtml += '</div>';
      }

      resultDiv.innerHTML = `
        <div class="flex items-start gap-2">
          <svg class="w-5 h-5 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          <div class="flex-1">
            <div class="text-sm text-accent-green font-medium">${result.message}</div>
            ${detailsHtml}
          </div>
        </div>
      `;
    } else {
      resultDiv.className = 'test-result test-error';
      resultDiv.innerHTML = `
        <div class="flex items-start gap-2">
          <svg class="w-5 h-5 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          <div class="flex-1">
            <div class="text-sm text-red-400 font-medium">${result.message}</div>
            ${result.error ? `<div class="text-xs text-text-muted mt-1">${result.error}</div>` : ''}
          </div>
        </div>
      `;
    }
  } catch (e) {
    resultDiv.className = 'test-result test-error';
    resultDiv.innerHTML = `
      <div class="flex items-center gap-2 text-sm text-red-400">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        <span>测试失败: ${e.message}</span>
      </div>
    `;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg class="w-4 h-4 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg> 测试连接';
  }
}

// Chat
let chatSessionId = 'session_' + Date.now();
let isChatStreaming = false;
let chatHistorySessions = [];
let pendingAttachments = [];
let isRecordingVoice = false;
let mediaRecorder = null;
let voiceRecordChunks = [];

async function loadChatHistory() {
  try {
    const res = await fetch('/api/sessions');
    const data = await res.json();
    chatHistorySessions = Array.isArray(data) ? data : [];
    renderChatHistoryList(chatHistorySessions);
  } catch (e) {
    const container = document.getElementById('chatHistoryList');
    container.innerHTML = '<div class="px-4 py-3 text-xs text-red-400 text-center">加载失败</div>';
  }
}

function renderChatHistoryList(sessions) {
  const container = document.getElementById('chatHistoryList');
  if (!sessions || sessions.length === 0) {
    container.innerHTML = '<div class="px-4 py-3 text-xs text-text-muted text-center">暂无历史会话</div>';
    return;
  }
  container.innerHTML = sessions.map(s => {
    const sessionId = s.id || s.session_id || 'Unknown';
    const summary = s.summary || sessionId;
    const timeStr = s.created_at ? new Date(s.created_at * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
    return `
    <div class="group px-4 py-3 hover:bg-dark-bg-secondary cursor-pointer transition-colors duration-150 border-b border-dark-border/50" onclick="loadSession('${sessionId}')">
      <div class="flex items-start gap-2">
        <div class="flex-1 min-w-0">
          <div class="text-xs text-text-primary truncate">${escapeHtml(summary)}</div>
          <div class="text-xs text-text-muted/60 mt-1">${timeStr}</div>
        </div>
        <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
          <button onclick="event.stopPropagation(); showForkSessionDialog('${sessionId}')" class="p-1 hover:text-accent-blue transition-colors duration-150" title="从对话中派生">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/>
            </svg>
          </button>
          <button onclick="event.stopPropagation(); deleteChatSession('${sessionId}')" class="p-1 hover:text-red-400 transition-colors duration-150" title="删除会话">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  `}).join('');
}

async function showForkSessionDialog(sessionId) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/user-messages`);
    const data = await res.json();

    if (data.error || !data.user_messages || data.user_messages.length === 0) {
      alert('该会话中没有用户消息，无法派生');
      return;
    }

    const userMessages = data.user_messages;
    const messageOptions = userMessages.map((um, idx) => {
      return `<option value="${um.index}">[${um.index}] ${escapeHtml(um.preview)}</option>`;
    }).join('');

    const dialogHtml = `
      <div id="forkDialogOverlay" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 1000; display: flex; align-items: center; justify-content: center;">
        <div style="background: #1e1e2e; border: 1px solid #313244; border-radius: 8px; padding: 24px; max-width: 600px; width: 90%; max-height: 80vh; overflow-y: auto;">
          <h3 style="color: #cdd6f4; margin: 0 0 16px 0; font-size: 18px;">从对话中派生新会话</h3>
          <p style="color: #a6adc8; font-size: 14px; margin-bottom: 16px;">选择要派生的用户消息位置：</p>
          <select id="forkMessageIndex" style="width: 100%; padding: 8px; background: #181825; border: 1px solid #313244; border-radius: 4px; color: #cdd6f4; margin-bottom: 16px;">
            ${messageOptions}
          </select>
          <div style="margin-bottom: 16px;">
            <label style="color: #a6adc8; font-size: 14px; display: block; margin-bottom: 8px;">新会话 ID（可选）：</label>
            <input type="text" id="forkNewSessionId" placeholder="留空将自动生成" style="width: 100%; padding: 8px; background: #181825; border: 1px solid #313244; border-radius: 4px; color: #cdd6f4;">
          </div>
          <div style="display: flex; gap: 12px; justify-content: flex-end;">
            <button onclick="closeForkDialog()" style="padding: 8px 16px; background: #313244; border: none; border-radius: 4px; color: #cdd6f4; cursor: pointer;">取消</button>
            <button onclick="executeFork('${sessionId}')" style="padding: 8px 16px; background: #89b4fa; border: none; border-radius: 4px; color: #1e1e2e; cursor: pointer; font-weight: 500;">派生</button>
          </div>
        </div>
      </div>
    `;

    document.body.insertAdjacentHTML('beforeend', dialogHtml);
  } catch (e) {
    alert('加载用户消息失败: ' + e.message);
  }
}

function closeForkDialog() {
  const overlay = document.getElementById('forkDialogOverlay');
  if (overlay) {
    overlay.remove();
  }
}

async function executeFork(sessionId) {
  const messageIndex = parseInt(document.getElementById('forkMessageIndex').value);
  const newSessionId = document.getElementById('forkNewSessionId').value.trim() || undefined;

  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/fork`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message_index: messageIndex,
        new_session_id: newSessionId,
      }),
    });

    const data = await res.json();
    if (data.error) {
      alert('派生失败: ' + data.error);
      return;
    }

    closeForkDialog();
    alert(`派生成功！\n新会话 ID: ${data.forked_session_id}\n从消息 ${data.forked_at_index} 处派生`);
    await loadChatHistory();
  } catch (e) {
    alert('派生失败: ' + e.message);
  }
}

async function deleteChatSession(id) {
  if (!confirm(`确定删除会话 "${id}"?`)) return;
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json();
      alert('删除失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    if (chatSessionId === id) {
      chatSessionId = null;
      document.getElementById('chatMessages').innerHTML = '<div class="flex items-center justify-center h-full"><div class="text-center"><div class="text-6xl mb-4 opacity-30">💬</div><div class="text-text-muted text-sm">会话已删除</div></div></div>';
    }
    await loadChatHistory();
  } catch (e) {
    alert('删除失败: ' + e.message);
  }
}

async function loadSession(id) {
  chatSessionId = id;
  const container = document.getElementById('chatMessages');
  container.innerHTML = '<div class="text-center text-text-muted text-sm py-10">加载中...</div>';
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(id)}`);
    const data = await res.json();
    if (data && data.messages) {
      container.innerHTML = '';
      for (const msg of data.messages) {
        if (msg.role === 'user') {
          const text = msg.content?.map(c => c.text || '').join('') || '';
          if (text) {
            container.innerHTML += `
              <div class="flex justify-end animate-fade-in">
                <div class="chat-message-user">${escapeHtml(text)}</div>
              </div>
            `;
          }
        } else if (msg.role === 'assistant') {
          const text = msg.content?.map(c => c.text || '').join('') || '';
          if (text) {
            container.innerHTML += `
              <div class="flex justify-start animate-slide-up">
                <div class="chat-message-assistant">${marked.parse(text)}</div>
              </div>
            `;
          }
        }
      }
      container.scrollTop = container.scrollHeight;
    }
  } catch (e) {
    container.innerHTML = '<div class="text-center text-red-400 text-sm py-10">加载失败</div>';
  }
}

async function sendMessage() {
  const input = document.getElementById('chatInput');
  const msg = input.value.trim();
  if ((!msg && pendingAttachments.length === 0) || isChatStreaming) return;

  const container = document.getElementById('chatMessages');
  if (container.querySelector('.text-center')) {
    container.innerHTML = '';
  }

  const attachmentsToSend = [...pendingAttachments];
  pendingAttachments = [];
  renderAttachmentPreview();

  let userMessageHtml = '';
  if (msg) {
    userMessageHtml += `<div class="mb-2">${escapeHtml(msg)}</div>`;
  }
  
  attachmentsToSend.forEach(att => {
    if (att.type === 'image') {
      userMessageHtml += `<img src="${att.data}" class="max-w-xs rounded-lg mb-2" alt="${escapeHtml(att.name)}">`;
    } else if (att.type === 'voice') {
      userMessageHtml += `
        <div class="flex items-center gap-2 mb-2">
          <audio controls class="max-w-xs">
            <source src="${att.data}" type="audio/webm">
            您的浏览器不支持语音播放
          </audio>
        </div>
      `;
    } else {
      userMessageHtml += `
        <div class="flex items-center gap-2 p-2 bg-white/10 rounded-lg mb-2">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
          <div class="flex-1 min-w-0">
            <div class="text-xs truncate">${escapeHtml(att.name)}</div>
            <div class="text-xs opacity-75">${formatFileSize(att.size)}</div>
          </div>
          <a href="${att.data}" download="${escapeHtml(att.name)}" class="text-xs underline">下载</a>
        </div>
      `;
    }
  });

  container.innerHTML += `
    <div class="flex justify-end animate-fade-in">
      <div class="chat-message-user">${userMessageHtml}</div>
    </div>
  `;
  input.value = '';
  container.scrollTop = container.scrollHeight;

  addTraceLog(`[USER] ${msg}${attachmentsToSend.length > 0 ? ` (+${attachmentsToSend.length}个附件)` : ''}`);

  const assistantId = 'assistant-' + Date.now();
  container.innerHTML += `
    <div class="flex justify-start animate-slide-up">
      <div id="${assistantId}" class="chat-message-assistant">
        <span class="text-text-muted animate-pulse">思考中...</span>
      </div>
    </div>
  `;
  container.scrollTop = container.scrollHeight;

  isChatStreaming = true;
  let assistantText = '';
  const assistantEl = document.getElementById(assistantId);

  try {
    addTraceLog(`[DEBUG] 发送请求到 /api/chat/agent`);
    addTraceLog(`[DEBUG] 使用 Agent: ${activeAgentId || 'default'}`);
    
    const requestBody = {
      message: msg,
      session_id: chatSessionId,
      agent_id: activeAgentId
    };
    
    if (attachmentsToSend.length > 0) {
      requestBody.attachments = attachmentsToSend.map(att => ({
        type: att.type,
        name: att.name,
        data: att.data,
        mimeType: att.mimeType
      }));
    }
    
    const response = await fetch('/api/chat/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody)
    });

    addTraceLog(`[DEBUG] 收到响应, 状态码: ${response.status}`);

    if (!response.ok) {
      const errorText = await response.text();
      addTraceLog(`[DEBUG] 响应错误: ${errorText}`);
      throw new Error(`HTTP ${response.status}: ${errorText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let currentEventType = '';
    let eventCount = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        addTraceLog(`[DEBUG] 流结束, 共收到 ${eventCount} 个事件`);
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
          currentEventType = '';
          continue;
        }
        if (trimmed.startsWith('event: ')) {
          currentEventType = trimmed.slice(7).trim();
        } else if (trimmed.startsWith('data: ')) {
          if (!currentEventType) continue;
          try {
            const data = JSON.parse(trimmed.slice(6));
            eventCount++;
            if (currentEventType === 'text') {
              assistantText += data.text;
            }
            handleChatEvent(currentEventType, data, assistantEl, assistantId, assistantText);
          } catch (e) {
            addTraceLog(`[DEBUG] 解析数据失败: ${e.message}`);
          }
        }
      }
    }

    addTraceLog(`[DEBUG] assistantText 长度: ${assistantText.length}, 内容: ${assistantText.substring(0, 100)}`);

    if (!assistantText.trim()) {
      const lastToolError = assistantEl?.dataset?.lastToolError || '';
      const renderedFiles = assistantEl?.dataset?.fileHtml || '';
      if (renderedFiles) {
        assistantEl.innerHTML = (assistantEl.dataset.textHtml || '') + renderedFiles + (assistantEl.dataset.errorHtml || '');
      } else if (lastToolError) {
        assistantEl.innerHTML = marked.parse(lastToolError);
      } else {
        assistantEl.innerHTML = '<span class="text-text-muted">响应完成 (无文本输出)</span>';
      }
      addTraceLog(`[WARN] 没有收到任何文本内容`);
    }
    addTraceLog('[AGENT] 响应完成');

  } catch (e) {
    if (assistantEl) {
      assistantEl.innerHTML = `<span class="text-red-400">错误: ${escapeHtml(e.message)}</span>`;
    }
    addTraceLog(`[ERROR] ${e.message}`);
  } finally {
    isChatStreaming = false;
    container.scrollTop = container.scrollHeight;
    await loadChatHistory();
  }
}

function handleChatEvent(eventType, data, assistantEl, assistantId, currentText) {
  switch (eventType) {
    case 'text':
      if (assistantEl) {
        assistantEl.dataset.textHtml = marked.parse(stripOutboundMediaMarkers(currentText)) + renderOpenScadAction(currentText);
        assistantEl.innerHTML = assistantEl.dataset.textHtml + (assistantEl.dataset.fileHtml || '') + (assistantEl.dataset.errorHtml || '');
        const chatContainer = document.getElementById('chatMessages');
        chatContainer.scrollTop = chatContainer.scrollHeight;
      }
      break;
    case 'tool_start':
      addTraceLog(`[TOOL] 执行 ${data.tool}...`);
      break;
    case 'tool_complete':
      addTraceLog(`[TOOL] ${data.tool} 完成${data.is_error ? ' (失败)' : ''}`);
      if (data.is_error && assistantEl) {
        const output = String(data.output || '').trim();
        const clipped = output.length > 1200 ? output.slice(0, 1200).trimEnd() + '...' : output;
        const message = clipped
          ? `处理没有完成：\`${data.tool || 'tool'}\` 执行失败。\n\n最近错误：${clipped}`
          : `处理没有完成：\`${data.tool || 'tool'}\` 执行失败，但没有返回可用错误信息。`;
        assistantEl.dataset.lastToolError = message;
        if (!currentText.trim()) {
          assistantEl.innerHTML = marked.parse(message);
        }
      }
      break;
    case 'status':
      addTraceLog(`[STATUS] ${data.message}`);
      break;
    case 'error':
      addTraceLog(`[ERROR] ${data.message}`);
      if (assistantEl) {
        const errorHtml = `<div class="mt-2 text-red-400">错误: ${escapeHtml(data.message)}</div>`;
        if (assistantEl.dataset.fileHtml) {
          assistantEl.dataset.errorHtml = errorHtml;
          assistantEl.innerHTML = (assistantEl.dataset.textHtml || '') + assistantEl.dataset.fileHtml + errorHtml;
        } else {
          assistantEl.innerHTML = errorHtml;
        }
      }
      break;
    case 'file':
      addTraceLog(`[FILE] 收到文件: ${data.name}, type=${data.type}, size=${data.size}`);
      if (assistantEl) {
        const fileType = data.type || 'file';
        const fileName = data.name || 'unknown';
        const fileData = data.data || '';
        
        addTraceLog(`[FILE] 处理类型: ${fileType}, 是否为图片: ${['image', 'photo'].includes(fileType)}`);
        
        let fileHtml = '';
        if (['image', 'photo'].includes(fileType)) {
          fileHtml = `<div class="mt-2"><img src="data:image/jpeg;base64,${fileData}" alt="${escapeHtml(fileName)}" class="max-w-xs rounded-lg shadow-md" /></div>`;
        } else if (fileType === 'voice' || fileType === 'audio') {
          fileHtml = `<div class="mt-2"><audio controls class="w-full max-w-xs"><source src="data:audio/mpeg;base64,${fileData}"></audio><div class="text-xs text-text-muted mt-1">${escapeHtml(fileName)}</div></div>`;
        } else {
          fileHtml = `<div class="mt-2"><a href="data:application/octet-stream;base64,${fileData}" download="${escapeHtml(fileName)}" class="inline-flex items-center px-3 py-2 bg-primary/10 text-primary rounded-lg hover:bg-primary/20 transition-colors"><svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>${escapeHtml(fileName)}</a></div>`;
        }
        assistantEl.dataset.fileHtml = (assistantEl.dataset.fileHtml || '') + fileHtml;
        assistantEl.innerHTML = (assistantEl.dataset.textHtml || '') + assistantEl.dataset.fileHtml + (assistantEl.dataset.errorHtml || '');
        const chatContainer = document.getElementById('chatMessages');
        chatContainer.scrollTop = chatContainer.scrollHeight;
      }
      break;
    case 'done':
      break;
  }
}

function addTraceLog(log) {
  const container = document.getElementById('traceLogs');
  if (container.querySelector('.text-text-muted\\/50')) {
    container.innerHTML = '';
  }
  const time = new Date().toLocaleTimeString();
  const entry = document.createElement('div');
  entry.className = 'trace-log animate-fade-in';
  entry.innerHTML = `<span class="text-text-muted/40">[${time}]</span> ${escapeHtml(log)}`;
  container.appendChild(entry);
  container.scrollTop = container.scrollHeight;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function stripOutboundMediaMarkers(text) {
  return String(text || '')
    .replace(/\[(attachment|file|document|image|photo|video|audio|voice|audio-file|media):\s*[^\]\n]+?\s*\]/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function handleFileSelect(event) {
  const files = Array.from(event.target.files);
  files.forEach(file => {
    const reader = new FileReader();
    reader.onload = function(e) {
      pendingAttachments.push({
        type: 'file',
        name: file.name,
        size: file.size,
        data: e.target.result,
        mimeType: file.type
      });
      renderAttachmentPreview();
    };
    reader.readAsDataURL(file);
  });
  event.target.value = '';
}

function handleImageSelect(event) {
  const files = Array.from(event.target.files);
  files.forEach(file => {
    const reader = new FileReader();
    reader.onload = function(e) {
      pendingAttachments.push({
        type: 'image',
        name: file.name,
        size: file.size,
        data: e.target.result,
        mimeType: file.type
      });
      renderAttachmentPreview();
    };
    reader.readAsDataURL(file);
  });
  event.target.value = '';
}

function renderAttachmentPreview() {
  const preview = document.getElementById('attachmentPreview');
  const content = document.getElementById('attachmentPreviewContent');
  
  if (pendingAttachments.length === 0) {
    preview.classList.add('hidden');
    return;
  }
  
  preview.classList.remove('hidden');
  content.innerHTML = pendingAttachments.map((att, index) => {
    if (att.type === 'image') {
      return `
        <div class="relative group">
          <img src="${att.data}" class="w-20 h-20 object-cover rounded-lg border border-dark-border" alt="${escapeHtml(att.name)}">
          <button onclick="removeAttachment(${index})" class="absolute -top-2 -right-2 w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">×</button>
        </div>
      `;
    } else if (att.type === 'voice') {
      return `
        <div class="relative group flex items-center gap-2 px-3 py-2 bg-dark-card border border-accent-purple/30 rounded-lg">
          <svg class="w-4 h-4 text-accent-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"/></svg>
          <span class="text-xs text-text-primary">语音消息</span>
          <button onclick="removeAttachment(${index})" class="w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">×</button>
        </div>
      `;
    } else {
      return `
        <div class="relative group flex items-center gap-2 px-3 py-2 bg-dark-card border border-dark-border rounded-lg">
          <svg class="w-4 h-4 text-accent-green" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
          <div class="flex-1 min-w-0">
            <div class="text-xs text-text-primary truncate">${escapeHtml(att.name)}</div>
            <div class="text-xs text-text-muted">${formatFileSize(att.size)}</div>
          </div>
          <button onclick="removeAttachment(${index})" class="w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">×</button>
        </div>
      `;
    }
  }).join('');
}

function removeAttachment(index) {
  pendingAttachments.splice(index, 1);
  renderAttachmentPreview();
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

async function toggleVoiceRecording() {
  if (isRecordingVoice) {
    stopVoiceRecording();
  } else {
    await startVoiceRecording();
  }
}

async function startVoiceRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    voiceRecordChunks = [];
    
    mediaRecorder.ondataavailable = function(e) {
      voiceRecordChunks.push(e.data);
    };
    
    mediaRecorder.onstop = function() {
      const blob = new Blob(voiceRecordChunks, { type: 'audio/webm' });
      const reader = new FileReader();
      reader.onload = function(e) {
        pendingAttachments.push({
          type: 'voice',
          name: 'voice_message.webm',
          size: blob.size,
          data: e.target.result,
          mimeType: 'audio/webm'
        });
        renderAttachmentPreview();
      };
      reader.readAsDataURL(blob);
      
      stream.getTracks().forEach(track => track.stop());
    };
    
    mediaRecorder.start();
    isRecordingVoice = true;
    
    const btn = document.getElementById('voiceRecordBtn');
    btn.classList.add('bg-accent-purple/20', 'border-accent-purple');
    btn.classList.remove('text-text-muted');
    btn.classList.add('text-accent-purple');
    
    addTraceLog('[VOICE] 开始录音...');
  } catch (e) {
    console.error('Failed to start recording:', e);
    addTraceLog('[VOICE] 录音失败: ' + e.message);
  }
}

function stopVoiceRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  isRecordingVoice = false;
  
  const btn = document.getElementById('voiceRecordBtn');
  btn.classList.remove('bg-accent-purple/20', 'border-accent-purple', 'text-accent-purple');
  btn.classList.add('text-text-muted');
  
  addTraceLog('[VOICE] 录音完成');
}

// Web Search Configuration
async function loadWebSearchSettings() {
  try {
    const res = await fetch('/api/search-api');
    const data = await res.json();
    document.getElementById('webSearchEnabled').checked = data.enabled || false;
    document.getElementById('webSearchProvider').value = data.provider || 'tavily';
    document.getElementById('webSearchApiKey').value = data.api_key || '';
    document.getElementById('webSearchUseSdk').checked = data.use_sdk !== false;
    document.getElementById('webSearchBaseUrl').value = data.base_url || '';
    document.getElementById('webSearchMaxResults').value = data.max_results || 5;
    document.getElementById('webSearchCustomUrl').value = data.base_url || '';
    toggleWebSearchEnabled();
    onWebSearchProviderChange();
  } catch (e) {
    console.error('Failed to load web search settings:', e);
  }
}

function toggleWebSearchEnabled() {
  const enabled = document.getElementById('webSearchEnabled').checked;
  const config = document.getElementById('webSearchConfig');
  config.style.opacity = enabled ? '1' : '0.5';
  config.style.pointerEvents = enabled ? 'auto' : 'none';
}

function toggleApiKeyVisibility(inputId, button) {
  const input = document.getElementById(inputId);
  const icon = button.querySelector('.eye-icon');
  if (input.type === 'password') {
    input.type = 'text';
    icon.innerHTML = `
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"/>
    `;
  } else {
    input.type = 'password';
    icon.innerHTML = `
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
    `;
  }
}

function onWebSearchProviderChange() {
  const provider = document.getElementById('webSearchProvider').value;
  const apiKeyInput = document.getElementById('webSearchApiKey');
  const baseUrlInput = document.getElementById('webSearchBaseUrl');
  const customUrlInput = document.getElementById('webSearchCustomUrl');
  const sdkSection = document.getElementById('webSearchSdkSection');
  const baseUrlSection = document.getElementById('webSearchBaseUrlSection');

  apiKeyInput.placeholder = '输入搜索 API Key（如需要）';
  baseUrlInput.placeholder = 'https://api.example.com/search';
  customUrlInput.parentElement.style.display = 'none';
  sdkSection.style.display = 'block';
  baseUrlSection.style.display = 'block';

  switch(provider) {
    case 'duckduckgo':
      apiKeyInput.placeholder = 'DuckDuckGo 无需 API Key';
      sdkSection.style.display = 'none';
      baseUrlSection.style.display = 'none';
      break;
    case 'tavily':
      apiKeyInput.placeholder = 'tvly-...';
      baseUrlInput.placeholder = 'https://api.tavily.com/search (使用 HTTP 模式时)';
      break;
    case 'bing':
      apiKeyInput.placeholder = 'Bing Search API Key';
      baseUrlInput.placeholder = 'https://api.bing.microsoft.com/v7.0/search';
      break;
    case 'google':
      apiKeyInput.placeholder = 'Google Custom Search API Key';
      baseUrlInput.placeholder = 'https://www.googleapis.com/customsearch/v1';
      break;
    case 'custom':
      customUrlInput.parentElement.style.display = 'block';
      sdkSection.style.display = 'none';
      break;
  }
}

async function saveWebSearchSettings() {
  const enabled = document.getElementById('webSearchEnabled').checked;
  const provider = document.getElementById('webSearchProvider').value;
  const apiKey = document.getElementById('webSearchApiKey').value;
  const useSdk = document.getElementById('webSearchUseSdk').checked;
  const baseUrl = document.getElementById('webSearchBaseUrl').value;
  const maxResults = parseInt(document.getElementById('webSearchMaxResults').value) || 5;

  try {
    const res = await fetch('/api/search-api', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enabled,
        provider,
        api_key: apiKey,
        use_sdk: useSdk,
        base_url: baseUrl,
        max_results: maxResults
      })
    });

    if (res.ok) {
      showNotification('Web Search 设置已保存', 'success');
    } else {
      showNotification('保存失败', 'error');
    }
  } catch (e) {
    showNotification(`保存失败: ${e.message}`, 'error');
  }
}

async function testWebSearch() {
  const resultDiv = document.getElementById('webSearchTestResult');
  resultDiv.classList.remove('hidden');
  resultDiv.innerHTML = '<div class="text-text-muted">测试中...</div>';

  try {
    const res = await fetch('/api/search-api/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: 'OpenHarness AI agent' })
    });

    const data = await res.json();
    if (res.ok) {
      resultDiv.innerHTML = `
        <div class="text-accent-green mb-2">✓ 搜索测试成功</div>
        <div class="text-text-secondary text-xs whitespace-pre-wrap">${escapeHtml(data.output || 'No results')}</div>
      `;
    } else {
      resultDiv.innerHTML = `
        <div class="text-red-400 mb-2">✗ 搜索测试失败</div>
        <div class="text-text-secondary text-xs">${escapeHtml(data.detail || 'Unknown error')}</div>
      `;
    }
  } catch (e) {
    resultDiv.innerHTML = `
      <div class="text-red-400 mb-2">✗ 请求失败</div>
      <div class="text-text-secondary text-xs">${escapeHtml(e.message)}</div>
    `;
  }
}

function showNotification(message, type = 'info') {
  const colors = {
    success: 'bg-accent-green/10 text-accent-green border-accent-green/20',
    error: 'bg-red-500/10 text-red-400 border-red-500/20',
    info: 'bg-accent-blue/10 text-accent-blue border-accent-blue/20'
  };

  const notification = document.createElement('div');
  notification.className = `fixed top-20 right-5 z-50 px-4 py-3 rounded-lg border ${colors[type]} animate-slide-up`;
  notification.textContent = message;
  document.body.appendChild(notification);

  setTimeout(() => {
    notification.style.opacity = '0';
    notification.style.transition = 'opacity 0.3s';
    setTimeout(() => notification.remove(), 300);
  }, 3000);
}

function hotReload() {
  location.reload();
}

async function loadBotChannels() {
  try {
    const res = await fetch('/api/bots/channels');
    const data = await res.json();
    allBotChannels = data.channels || [];
    renderBotList(allBotChannels);
  } catch (e) {
    console.error('Failed to load bot channels:', e);
    document.getElementById('botList').innerHTML = '<div class="text-sm text-red-400 p-4 text-center">加载失败</div>';
  }
}

let allBotChannels = [];
let selectedBotChannel = null;
let selectedBotUser = null;

function renderBotList(channels) {
  const container = document.getElementById('botList');
  if (!channels || channels.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted p-4 text-center">暂无启用的机器人</div>';
    return;
  }
  container.innerHTML = channels.map(channel => `
    <div class="flex items-center justify-between p-2 rounded-lg cursor-pointer transition-colors ${selectedBotChannel === channel.name ? 'bg-accent-purple/10' : 'hover:bg-dark-bg-secondary'}" onclick="selectBotChannel('${channel.name}')">
      <div class="flex items-center gap-2 min-w-0 flex-1">
        <div class="w-8 h-8 rounded-lg bg-accent-purple/10 flex items-center justify-center flex-shrink-0">
          <svg class="w-4 h-4 text-accent-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 2a2 2 0 012 2v2h2a2 2 0 012 2v10a2 2 0 01-2 2H8a2 2 0 01-2-2V8a2 2 0 012-2h2V4a2 2 0 012-2z"/>
            <circle cx="9" cy="12" r="1" fill="currentColor"/>
            <circle cx="15" cy="12" r="1" fill="currentColor"/>
          </svg>
        </div>
        <div class="min-w-0">
          <div class="text-sm font-medium text-text-primary truncate">${channel.display_name || channel.name}</div>
          <div class="text-xs text-text-muted">${channel.type}</div>
        </div>
      </div>
      <button onclick="event.stopPropagation(); showBotConfig('${channel.name}')" class="p-1.5 hover:bg-dark-bg rounded transition-colors flex-shrink-0" title="配置">
        <svg class="w-4 h-4 text-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
      </button>
    </div>
  `).join('');
}

function selectBotChannel(channelName) {
  selectedBotChannel = channelName;
  selectedBotUser = null;
  renderBotList(allBotChannels);
  const channel = allBotChannels.find(c => c.name === channelName);
  renderBotUsers(channel ? channel.sessions || [] : []);
  document.getElementById('botChatMessages').innerHTML = `
    <div class="text-center text-text-muted text-sm py-10">
      <svg class="w-12 h-12 mx-auto mb-3 text-text-muted/30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
      </svg>
      <p class="font-medium">选择用户</p>
      <p class="text-xs mt-1 text-text-muted/60">点击左侧用户查看聊天内容</p>
    </div>
  `;
}

function renderBotUsers(sessions) {
  const container = document.getElementById('botUserList');
  if (!sessions || sessions.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted p-4 text-center">暂无用户</div>';
    return;
  }
  container.innerHTML = sessions.map(session => `
    <div class="p-2 rounded-lg cursor-pointer transition-colors ${selectedBotUser === session.sender_id ? 'bg-accent-green/10' : 'hover:bg-dark-bg-secondary'}" onclick="selectBotUser('${session.sender_id}')">
      <div class="text-sm font-medium text-text-primary truncate">${escapeHtml(session.sender_name || session.sender_id)}</div>
      <div class="text-xs text-text-muted truncate">${escapeHtml(session.last_message || '')}</div>
    </div>
  `).join('');
}

function selectBotUser(senderId) {
  selectedBotUser = senderId;
  const channel = allBotChannels.find(c => c.name === selectedBotChannel);
  renderBotUsers(channel ? channel.sessions || [] : []);
  loadBotChat(selectedBotChannel, senderId);
}

async function loadBotChat(channelName, senderId) {
  try {
    const res = await fetch(`/api/bots/${channelName}/chat/${senderId}`);
    const data = await res.json();
    renderBotChatMessages(channelName, senderId, data.messages || []);
  } catch (e) {
    console.error('Failed to load bot chat:', e);
    document.getElementById('botChatMessages').innerHTML = '<div class="text-sm text-red-400 p-4 text-center">加载失败</div>';
  }
}

function renderBotChatMessages(channelName, senderId, messages) {
  const channel = allBotChannels.find(c => c.name === channelName);
  const sender = channel ? (channel.sessions || []).find(s => s.sender_id === senderId) : null;
  const senderName = sender ? (sender.sender_name || senderId) : senderId;

  document.getElementById('botChatTitle').textContent = `${channelName} - ${senderName}`;
  document.getElementById('botChatSubtitle').textContent = `${messages.length} 条消息`;

  const container = document.getElementById('botChatMessages');
  if (!messages || messages.length === 0) {
    container.innerHTML = `
      <div class="text-center text-text-muted text-sm py-10">
        <p class="font-medium">暂无聊天记录</p>
      </div>
    `;
    return;
  }

  container.innerHTML = messages.map(msg => {
    if (msg.role === 'user') {
      return `
        <div class="flex justify-end">
          <div class="max-w-[70%] px-4 py-2 rounded-lg bg-accent-green/20 text-text-primary">
            <div class="text-xs text-text-muted mb-1 text-right">用户</div>
            <div class="text-sm whitespace-pre-wrap">${escapeHtml(msg.content)}</div>
          </div>
        </div>
      `;
    } else {
      const agentName = msg.agent_name || 'Agent';
      return `
        <div class="flex justify-start">
          <div class="max-w-[70%] px-4 py-2 rounded-lg bg-dark-bg-secondary text-text-primary">
            <div class="text-xs text-accent-purple mb-1">Agent-${escapeHtml(agentName)}</div>
            <div class="text-sm whitespace-pre-wrap">${escapeHtml(msg.content)}</div>
          </div>
        </div>
      `;
    }
  }).join('');

  container.scrollTop = container.scrollHeight;
}

function showBotConfig(channelName) {
  const channel = allBotChannels.find(c => c.name === channelName);
  if (!channel) return;

  const modal = document.createElement('div');
  modal.className = 'fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4';
  modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

  const type = channel.type || channelName;
  const configFields = getBotConfigFields(type, channel);

  modal.innerHTML = `
    <div class="bg-dark-card border border-dark-border rounded-xl w-full max-w-lg max-h-[80vh] flex flex-col shadow-soft">
      <div class="flex items-center justify-between p-5 border-b border-dark-border">
        <div>
          <h3 class="text-base font-semibold text-text-primary">${channel.display_name || channelName} 配置</h3>
          <p class="text-xs text-text-muted mt-1">${type}</p>
        </div>
        <button onclick="this.closest('.fixed').remove()" class="nav-icon-btn">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </div>
      <div class="flex-1 overflow-y-auto p-5 space-y-4">
        <div class="form-item">
          <label class="form-label">分配 Agent</label>
          <select id="botConfigAgent" class="form-input">
            <option value="">不分配（使用默认）</option>
          </select>
        </div>
        ${configFields}
      </div>
      <div class="p-5 border-t border-dark-border flex justify-end gap-2">
        <button onclick="this.closest('.fixed').remove()" class="btn-secondary">取消</button>
        <button onclick="saveBotConfig('${channelName}')" class="btn-primary">保存</button>
      </div>
    </div>
  `;

  document.body.appendChild(modal);

  loadAgentsForBotConfig(channelName);
}

async function loadAgentsForBotConfig(channelName) {
  try {
    const resp = await fetch('/api/agents');
    const data = await resp.json();
    const agents = data.agents || [];
    const channel = allBotChannels.find(c => c.name === channelName);
    const currentAgentId = channel ? channel.agent_id : null;

    const select = document.getElementById('botConfigAgent');
    if (!select) return;

    agents.forEach(agent => {
      const option = document.createElement('option');
      option.value = agent.id;
      option.textContent = agent.name || agent.id;
      if (agent.id === currentAgentId) {
        option.selected = true;
      }
      select.appendChild(option);
    });
  } catch (e) {
    console.error('Failed to load agents:', e);
  }
}

function getBotConfigFields(type, channel) {
  const fields = [];

  if (type === 'qq') {
    fields.push(`
      <div class="form-item">
        <label class="form-label">App ID <span class="text-red-400">*</span></label>
        <input type="text" id="botConfigAppId" class="form-input" placeholder="QQ开放平台App ID" value="${channel.app_id || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">App Secret <span class="text-red-400">*</span></label>
        <input type="password" id="botConfigAppSecret" class="form-input" placeholder="QQ开放平台App Secret" value="${channel.app_secret || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">API URL <span class="text-text-muted text-xs">(可选)</span></label>
        <input type="text" id="botConfigApiUrl" class="form-input" placeholder="https://bots.qq.com" value="${channel.api_url || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">允许的用户 <span class="text-text-muted text-xs">(逗号分隔，* 表示所有人)</span></label>
        <input type="text" id="botConfigAllowFrom" class="form-input" placeholder="*" value="${(channel.allow_from || []).join(',')}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">沙箱模式</label>
        <select id="botConfigSandbox" class="form-input">
          <option value="false" ${!channel.sandbox ? 'selected' : ''}>关闭</option>
          <option value="true" ${channel.sandbox ? 'selected' : ''}>开启</option>
        </select>
      </div>
    `);
  } else if (type === 'wechat') {
    fields.push(`
      <div class="form-item">
        <label class="form-label">App ID <span class="text-red-400">*</span></label>
        <input type="text" id="botConfigAppId" class="form-input" placeholder="微信开放平台App ID" value="${channel.app_id || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">App Secret <span class="text-red-400">*</span></label>
        <input type="password" id="botConfigAppSecret" class="form-input" placeholder="微信开放平台App Secret" value="${channel.app_secret || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">Token <span class="text-text-muted text-xs">(可选)</span></label>
        <input type="password" id="botConfigToken" class="form-input" placeholder="微信服务器验证Token" value="${channel.token || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">AES Key <span class="text-text-muted text-xs">(可选)</span></label>
        <input type="password" id="botConfigAesKey" class="form-input" placeholder="微信消息加密AES Key" value="${channel.aes_key || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">API URL <span class="text-text-muted text-xs">(可选)</span></label>
        <input type="text" id="botConfigApiUrl" class="form-input" placeholder="https://api.weixin.qq.com" value="${channel.api_url || ''}">
      </div>
    `);
  } else if (type === 'feishu') {
    fields.push(`
      <div class="form-item">
        <label class="form-label">App ID <span class="text-red-400">*</span></label>
        <input type="text" id="botConfigAppId" class="form-input" placeholder="飞书开放平台App ID" value="${channel.app_id || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">App Secret <span class="text-red-400">*</span></label>
        <input type="password" id="botConfigAppSecret" class="form-input" placeholder="飞书开放平台App Secret" value="${channel.app_secret || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">Encrypt Key <span class="text-text-muted text-xs">(可选)</span></label>
        <input type="password" id="botConfigEncryptKey" class="form-input" placeholder="飞书Encrypt Key" value="${channel.encrypt_key || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">Verification Token <span class="text-text-muted text-xs">(可选)</span></label>
        <input type="password" id="botConfigVerificationToken" class="form-input" placeholder="飞书Verification Token" value="${channel.verification_token || ''}">
      </div>
    `);
    fields.push(`
      <div class="form-item">
        <label class="form-label">API URL <span class="text-text-muted text-xs">(可选)</span></label>
        <input type="text" id="botConfigApiUrl" class="form-input" placeholder="https://open.feishu.cn" value="${channel.api_url || ''}">
      </div>
    `);
  } else {
    fields.push(`
      <div class="text-sm text-text-muted text-center py-4">该平台暂无可配置项</div>
    `);
  }

  return fields.join('');
}

async function saveBotConfig(channelName) {
  const channel = allBotChannels.find(c => c.name === channelName);
  if (!channel) return;

  const config = {};
  const appIdEl = document.getElementById('botConfigAppId');
  const appSecretEl = document.getElementById('botConfigAppSecret');
  const apiUrlEl = document.getElementById('botConfigApiUrl');

  if (appIdEl) config.app_id = appIdEl.value;
  if (appSecretEl && appSecretEl.value) config.app_secret = appSecretEl.value;
  if (apiUrlEl) config.api_url = apiUrlEl.value;

  const type = channel.type || channelName;
  if (type === 'qq') {
    const allowFromEl = document.getElementById('botConfigAllowFrom');
    const sandboxEl = document.getElementById('botConfigSandbox');
    if (allowFromEl) config.allow_from = allowFromEl.value.split(',').map(s => s.trim()).filter(Boolean);
    if (sandboxEl) config.sandbox = sandboxEl.value === 'true';
  } else if (type === 'wechat') {
    const tokenEl = document.getElementById('botConfigToken');
    const aesKeyEl = document.getElementById('botConfigAesKey');
    if (tokenEl && tokenEl.value) config.token = tokenEl.value;
    if (aesKeyEl && aesKeyEl.value) config.aes_key = aesKeyEl.value;
  } else if (type === 'feishu') {
    const encryptKeyEl = document.getElementById('botConfigEncryptKey');
    const verificationTokenEl = document.getElementById('botConfigVerificationToken');
    if (encryptKeyEl && encryptKeyEl.value) config.encrypt_key = encryptKeyEl.value;
    if (verificationTokenEl && verificationTokenEl.value) config.verification_token = verificationTokenEl.value;
  }

  try {
    const agentSelect = document.getElementById('botConfigAgent');
    const agentId = agentSelect ? agentSelect.value : null;

    const res = await fetch(`/api/bots/${channelName}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    });
    if (!res.ok) {
      const err = await res.json();
      showNotification(`保存失败: ${err.detail || '未知错误'}`, 'error');
      return;
    }

    const agentRes = await fetch(`/api/bots/${channelName}/agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: agentId || null })
    });
    if (!agentRes.ok) {
      const err = await agentRes.json();
      showNotification(`Agent分配失败: ${err.detail || '未知错误'}`, 'error');
      return;
    }

    showNotification('配置已保存', 'success');
    document.querySelector('.fixed').remove();
    loadBotChannels();
  } catch (e) {
    showNotification(`保存失败: ${e.message}`, 'error');
  }
}

// Tool Management
let allTools = [];

async function loadTools() {
  try {
    const res = await fetch('/api/tools');
    const data = await res.json();
    allTools = data.tools || [];
    renderTools();
  } catch (e) {
    document.getElementById('toolList').innerHTML = '<div class="text-sm text-red-400">加载失败: ' + e.message + '</div>';
  }
}

function renderTools() {
  const container = document.getElementById('toolList');
  const searchTerm = (document.getElementById('toolSearch')?.value || '').toLowerCase();
  
  let filtered = allTools;
  if (searchTerm) {
    filtered = allTools.filter(t => 
      t.name.toLowerCase().includes(searchTerm) || 
      t.description.toLowerCase().includes(searchTerm)
    );
  }

  if (filtered.length === 0) {
    container.innerHTML = '<div class="text-sm text-text-muted">' + (searchTerm ? '未找到匹配的工具' : '暂无工具') + '</div>';
    return;
  }

  container.innerHTML = filtered.map(tool => `
    <div class="p-4 bg-dark-bg-secondary border border-dark-border rounded-lg animate-fade-in" id="tool-${tool.name}">
      <div class="flex items-start justify-between gap-3 mb-3">
        <div class="flex-1">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-sm font-semibold text-text-primary">${tool.name}</span>
            ${tool.is_provider_tool ? '<span class="text-xs px-2 py-0.5 bg-accent-blue/10 text-accent-blue rounded">供应商依赖</span>' : ''}
          </div>
          <p class="text-xs text-text-secondary">${escapeHtml(tool.description || '')}</p>
        </div>
        <div class="flex items-center gap-2">
          <label class="relative inline-flex items-center cursor-pointer">
            <input type="checkbox" class="sr-only peer" ${tool.enabled ? 'checked' : ''} onchange="toggleTool('${tool.name}', this.checked)">
            <div class="w-9 h-5 bg-dark-border peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-accent-green/20 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-dark-border after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-accent-green"></div>
          </label>
        </div>
      </div>
      
	          ${tool.is_provider_tool ? `
      <div class="mt-3 pt-3 border-t border-dark-border/50">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-medium text-text-secondary">供应商配置</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
          ${renderProviderConfigFields(tool)}
        </div>
      </div>
	          ` : ''}

	          <div class="mt-3 pt-3 border-t border-dark-border/50">
	            <div class="flex items-center justify-between mb-2">
	              <span class="text-xs font-medium text-text-secondary">使用范围限制</span>
	              <span class="text-xs text-text-muted">${tool.has_custom_restrictions ? '已自定义' : '使用默认限制'}</span>
	            </div>
	            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
	              <div class="flex flex-col gap-1">
	                <label class="text-xs text-text-muted">限制关键词</label>
	                <textarea id="tool-restrictions-${tool.name}"
	                          class="form-input text-xs px-2 py-1.5 font-mono"
	                          rows="3"
	                          placeholder="每行一个关键词">${escapeHtml((tool.restricted_keywords || []).join('\n'))}</textarea>
	              </div>
	              <div class="flex flex-col gap-1">
	                <label class="text-xs text-text-muted">命中后提示</label>
	                <textarea id="tool-restriction-message-${tool.name}"
	                          class="form-input text-xs px-2 py-1.5"
	                          rows="3"
	                          placeholder="给 LLM/用户的错误说明">${escapeHtml(tool.restriction_message || '')}</textarea>
	              </div>
	            </div>
	            <div class="flex items-center justify-end gap-2 mt-2">
	              ${tool.has_custom_restrictions ? `<button onclick="resetToolRestrictions('${tool.name}')" class="btn-secondary text-xs px-2 py-1">恢复默认</button>` : ''}
	              <button onclick="saveToolRestrictions('${tool.name}')" class="btn-secondary text-xs px-2 py-1">保存限制</button>
	            </div>
	          </div>
	          
	          <div class="mt-3 pt-3 border-t border-dark-border/50 flex items-center justify-between">
        <span class="text-xs text-text-muted">${tool.has_custom_description ? '已自定义描述' : '使用默认描述'}</span>
        <div class="flex gap-2">
          ${tool.has_custom_description ? `<button onclick="resetToolDescription('${tool.name}')" class="btn-secondary text-xs px-2 py-1">重置描述</button>` : ''}
          <button onclick="editToolDescription('${tool.name}')" class="btn-secondary text-xs px-2 py-1">编辑描述</button>
        </div>
      </div>
    </div>
  `).join('');
}

function renderProviderConfigFields(tool) {
  if (!tool.provider_config) return '';
  if (['image_generation', 'image_to_text'].includes(tool.name)) {
    const selectedProfile = tool.provider_config.profile || '';
    const profileOptions = (tool.available_profiles || []).map(p =>
      `<option value="${p.name}" ${selectedProfile === p.name ? 'selected' : ''}>${p.name}${p.label ? ` · ${p.label}` : ''}</option>`
    ).join('');
    const modelOptions = (tool.model_options || []).map(m =>
      `<option value="${m}" ${tool.provider_config.model === m ? 'selected' : ''}>${m}</option>`
    ).join('');
    return `
      <div class="flex flex-col gap-1">
        <label class="text-xs text-text-muted">供应商</label>
        <select id="tool-config-${tool.name}-profile"
                class="form-input text-xs px-2 py-1.5"
                onchange="onToolProviderChange('${tool.name}', 'profile', this.value)">
          <option value="">选择已配置供应商</option>
          ${profileOptions}
        </select>
      </div>
      <div class="flex flex-col gap-1">
        <label class="text-xs text-text-muted">模型</label>
        <div class="flex gap-2">
          <select id="tool-config-${tool.name}-model"
                  class="form-input text-xs px-2 py-1.5 flex-1"
                  onchange="updateToolProviderConfig('${tool.name}', 'model', this.value)">
            <option value="">使用供应商默认模型</option>
            ${modelOptions}
          </select>
          <button onclick="refreshToolModelList('${tool.name}')" class="btn-secondary text-xs px-2 py-1.5" title="刷新模型列表">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
          </button>
        </div>
      </div>
    `;
  }
  
  const fields = {
    'api_key': { label: 'API Key', type: 'password', placeholder: '输入 API Key' },
    'base_url': { label: 'Base URL', type: 'text', placeholder: 'https://api.example.com' },
    'model': { label: '模型', type: 'select', placeholder: '选择模型' },
    'provider': { label: '供应商', type: 'select', placeholder: '选择已配置的供应商' },
    'codex_auth_token': { label: 'Codex Auth Token', type: 'password', placeholder: 'Codex 认证令牌' },
    'codex_base_url': { label: 'Codex Base URL', type: 'text', placeholder: 'Codex API 地址' },
    'codex_model': { label: 'Codex 模型', type: 'text', placeholder: '例如: gpt-5.4' },
    'engine': { label: '搜索引擎', type: 'text', placeholder: '搜索引擎名称' },
  };

  return Object.entries(tool.provider_config)
    .filter(([_, value]) => value !== undefined)
    .map(([key, value]) => {
      const field = fields[key] || { label: key, type: 'text', placeholder: '' };
      const displayValue = value ? (field.type === 'password' ? '••••••••' : value) : '';
      
      if (field.type === 'select' && key === 'provider') {
        const options = profileList.map(p => 
          `<option value="${p.name}" ${value === p.name ? 'selected' : ''}>${p.name} (${p.provider})</option>`
        ).join('');
        return `
          <div class="flex flex-col gap-1">
            <label class="text-xs text-text-muted">${field.label}</label>
            <select id="tool-config-${tool.name}-${key}" 
                    class="form-input text-xs px-2 py-1.5"
                    onchange="onToolProviderChange('${tool.name}', '${key}', this.value)">
              <option value="">选择供应商</option>
              ${options}
            </select>
          </div>
        `;
      }
      
      if (field.type === 'select' && key === 'model') {
        const models = tool._models || [];
        const options = models.map(m => 
          `<option value="${m}" ${value === m ? 'selected' : ''}>${m}</option>`
        ).join('');
        return `
          <div class="flex flex-col gap-1">
            <label class="text-xs text-text-muted">${field.label}</label>
            <div class="flex gap-2">
              <select id="tool-config-${tool.name}-${key}" 
                      class="form-input text-xs px-2 py-1.5 flex-1"
                      onchange="updateToolProviderConfig('${tool.name}', '${key}', this.value)">
                <option value="">选择模型</option>
                ${options}
              </select>
              <button onclick="refreshToolModelList('${tool.name}')" class="btn-secondary text-xs px-2 py-1.5" title="刷新模型列表">
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
              </button>
            </div>
          </div>
        `;
      }
      
      return `
        <div class="flex flex-col gap-1">
          <label class="text-xs text-text-muted">${field.label}</label>
          <input type="${field.type}" 
                 id="tool-config-${tool.name}-${key}" 
                 class="form-input text-xs px-2 py-1.5" 
                 placeholder="${field.placeholder}"
                 value="${value || ''}"
                 onchange="updateToolProviderConfig('${tool.name}', '${key}', this.value)">
        </div>
      `;
    }).join('');
}

async function onToolProviderChange(toolName, key, value) {
  const tool = allTools.find(t => t.name === toolName);
  if (!tool || !tool.provider_config) return;

  const providerConfig = { ...tool.provider_config, [key]: value };
  if (['image_generation', 'image_to_text'].includes(toolName)) {
    providerConfig.model = '';
  }
  
  // 如果选择了供应商，清空模型选择并获取模型列表
  if (value) {
    await saveToolProviderConfig(toolName, providerConfig);
    await refreshToolModelList(toolName);
  } else {
    await saveToolProviderConfig(toolName, providerConfig);
    renderTools();
  }
}

async function refreshToolModelList(toolName) {
  const tool = allTools.find(t => t.name === toolName);
  if (!tool || !tool.provider_config) return;
  
  const providerName = tool.provider_config.profile || tool.provider_config.provider;
  if (!providerName) {
    alert('请先选择一个供应商');
    return;
  }
  
  const profile = (tool.available_profiles || []).find(p => p.name === providerName) || profileList.find(p => p.name === providerName);
  if (!profile || !profile.base_url) {
    alert('该供应商没有 Base URL，无法获取模型列表');
    return;
  }

  // 显示加载状态
  const modelSelect = document.getElementById(`tool-config-${toolName}-model`);
  if (modelSelect) {
    modelSelect.innerHTML = '<option value="">加载中...</option>';
  }

  try {
    const res = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: profile.base_url,
        api_format: profile.api_format || 'openai',
        profile_name: profile.name
      })
    });
    const data = await res.json();
    if (!data.success) {
      alert('获取模型列表失败: ' + (data.message || '未知错误'));
      return;
    }
    
    const models = data.models || [];
    tool.model_options = models;
    renderTools();
  } catch (e) {
    alert('获取模型列表失败: ' + e.message);
  }
}

async function toggleTool(toolName, enabled) {
  try {
    const res = await fetch(`/api/tools/${toolName}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    if (!res.ok) {
      const err = await res.json();
      alert('操作失败: ' + (err.detail || `HTTP ${res.status}`));
      await loadTools();
      return;
    }
    await loadTools();
  } catch (e) {
    alert('操作失败: ' + e.message);
    await loadTools();
  }
}

async function editToolDescription(toolName) {
  const tool = allTools.find(t => t.name === toolName);
  if (!tool) return;
  
  // 创建模态框
  const modal = document.createElement('div');
  modal.className = 'fixed inset-0 bg-black/50 flex items-center justify-center z-50';
  modal.innerHTML = `
    <div class="bg-dark-bg-primary border border-dark-border rounded-lg p-6 w-full max-w-2xl mx-4 animate-fade-in">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-base font-semibold text-text-primary">编辑工具描述 - ${tool.name}</h3>
        <button onclick="this.closest('.fixed').remove()" class="text-text-muted hover:text-text-primary">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </div>
      <textarea id="toolDescEdit" class="form-input w-full p-3 font-mono text-sm" rows="8" style="min-height: 200px; resize: vertical;">${tool.description}</textarea>
      <div class="flex justify-end gap-2 mt-4">
        <button onclick="this.closest('.fixed').remove()" class="btn-secondary px-4 py-2">取消</button>
        <button onclick="saveToolDescription('${tool.name}')" class="btn-primary px-4 py-2">保存</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  
  // 自动聚焦
  setTimeout(() => {
    const textarea = document.getElementById('toolDescEdit');
    if (textarea) {
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    }
  }, 100);
}

async function saveToolDescription(toolName) {
  const textarea = document.getElementById('toolDescEdit');
  if (!textarea) return;
  
  const newDesc = textarea.value.trim();
  if (!newDesc) {
    alert('描述不能为空');
    return;
  }

  try {
    const res = await fetch(`/api/tools/${toolName}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: newDesc })
    });
    if (!res.ok) {
      const err = await res.json();
      alert('保存失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    // 关闭模态框
    const modal = document.querySelector('.fixed.inset-0.bg-black\\/50');
    if (modal) modal.remove();
    await loadTools();
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

async function resetToolDescription(toolName) {
  if (!confirm('确定要重置描述为默认值吗?')) return;
  
  try {
    const res = await fetch(`/api/tools/${toolName}/description`, {
      method: 'DELETE'
    });
    if (!res.ok) {
      const err = await res.json();
      alert('重置失败: ' + (err.detail || `HTTP ${res.status}`));
      return;
    }
    await loadTools();
  } catch (e) {
    alert('重置失败: ' + e.message);
  }
}

async function saveToolProviderConfig(toolName, providerConfig, options = {}) {
  const reload = options.reload !== false;
  
  try {
    const res = await fetch(`/api/tools/${toolName}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_config: providerConfig })
    });
    if (!res.ok) {
      const err = await res.json();
      alert('保存失败: ' + (err.detail || `HTTP ${res.status}`));
      if (reload) await loadTools();
      return false;
    }
    if (reload) await loadTools();
    return true;
  } catch (e) {
    alert('保存失败: ' + e.message);
    if (reload) await loadTools();
    return false;
  }
}

	    async function updateToolProviderConfig(toolName, key, value) {
	      const tool = allTools.find(t => t.name === toolName);
	      if (!tool || !tool.provider_config) return;

	      const providerConfig = { ...tool.provider_config, [key]: value };
	      await saveToolProviderConfig(toolName, providerConfig);
	    }

	    async function saveToolRestrictions(toolName) {
	      const keywordsEl = document.getElementById(`tool-restrictions-${toolName}`);
	      const messageEl = document.getElementById(`tool-restriction-message-${toolName}`);
	      if (!keywordsEl || !messageEl) return;

	      const restrictedKeywords = keywordsEl.value
	        .split(/[\n,]/)
	        .map(item => item.trim())
	        .filter(Boolean);

	      try {
	        const res = await fetch(`/api/tools/${toolName}`, {
	          method: 'PUT',
	          headers: { 'Content-Type': 'application/json' },
	          body: JSON.stringify({
	            restricted_keywords: Array.from(new Set(restrictedKeywords)),
	            restriction_message: messageEl.value.trim()
	          })
	        });
	        if (!res.ok) {
	          const err = await res.json();
	          alert('保存失败: ' + (err.detail || `HTTP ${res.status}`));
	          return;
	        }
	        await loadTools();
	      } catch (e) {
	        alert('保存失败: ' + e.message);
	      }
	    }

	    async function resetToolRestrictions(toolName) {
	      if (!confirm('确定要恢复默认限制吗?')) return;
	      try {
	        const res = await fetch(`/api/tools/${toolName}/restrictions`, {
	          method: 'DELETE'
	        });
	        if (!res.ok) {
	          const err = await res.json();
	          alert('恢复失败: ' + (err.detail || `HTTP ${res.status}`));
	          return;
	        }
	        await loadTools();
	      } catch (e) {
	        alert('恢复失败: ' + e.message);
	      }
	    }

	    function filterTools() {
	      renderTools();
	    }

// Cron Functions
async function loadCronJobs() {
  try {
    const [jobsRes, presetsRes] = await Promise.all([
      fetch('/api/cron/jobs'),
      fetch('/api/cron/presets')
    ]);
    const jobsData = await jobsRes.json();
    const presetsData = await presetsRes.json();

    // Update scheduler status
    const statusEl = document.getElementById('cronSchedulerStatus');
    const btnEl = document.getElementById('cronSchedulerBtn');
    if (jobsData.scheduler_running) {
      statusEl.innerHTML = '<span class="status-dot w-2 h-2 rounded-full bg-accent-green"></span><span class="text-accent-green">调度器运行中 (pid=' + jobsData.scheduler_pid + ')</span>';
      btnEl.textContent = '停止';
      btnEl.onclick = () => toggleCronScheduler();
    } else {
      statusEl.innerHTML = '<span class="status-dot w-2 h-2 rounded-full bg-red-500"></span><span class="text-text-muted">调度器未运行</span>';
      btnEl.textContent = '启动';
      btnEl.onclick = () => toggleCronScheduler();
    }

    // Populate presets
    const presetSelect = document.getElementById('cronPreset');
    presetSelect.innerHTML = '<option value="">常用预设</option>';
    (presetsData.presets || []).forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.value;
      opt.textContent = p.label;
      presetSelect.appendChild(opt);
    });

    // Render job list
    const listEl = document.getElementById('cronJobList');
    const jobs = jobsData.jobs || [];
    if (jobs.length === 0) {
      listEl.innerHTML = '<div class="text-sm text-text-muted">暂无定时任务，点击"新建任务"创建</div>';
      return;
    }

    listEl.innerHTML = jobs.map(job => {
      const enabled = job.enabled !== false;
      const schedule = job.schedule || '';
      const taskType = job.payload ? 'agent' : 'command';
      const taskDesc = job.payload ? (job.payload.message || '').substring(0, 60) : (job.command || '').substring(0, 60);
      const notify = job.notify;
      const notifyStr = notify ? ` | 推送: ${notify.type}` : '';
      const lastRun = job.last_run ? job.last_run.substring(0, 19).replace('T', ' ') : '从未';
      const lastStatus = job.last_status ? (job.last_status === 'success' ? '<span class="text-accent-green">成功</span>' : '<span class="text-red-400">失败</span>') : '';
      const nextRun = job.next_run ? job.next_run.substring(0, 19).replace('T', ' ') : '-';

      return '<div class="bg-dark-bg-secondary border border-dark-border rounded-lg p-4 hover:border-dark-border-light transition-colors">' +
        '<div class="flex items-center justify-between">' +
          '<div class="flex-1 min-w-0">' +
            '<div class="flex items-center gap-2 mb-1">' +
              '<span class="text-sm font-medium text-text-primary">' + escapeHtml(job.name) + '</span>' +
              '<span class="text-xs px-2 py-0.5 rounded ' + (enabled ? 'bg-accent-green/10 text-accent-green' : 'bg-dark-border text-text-muted') + '">' + (enabled ? '启用' : '禁用') + '</span>' +
              '<span class="text-xs px-2 py-0.5 rounded bg-accent-purple/10 text-accent-purple">' + (taskType === 'agent' ? 'AI Agent' : 'Shell') + '</span>' +
            '</div>' +
            '<div class="text-xs text-text-muted font-mono">' + escapeHtml(schedule) + notifyStr + '</div>' +
            '<div class="text-xs text-text-secondary mt-1 truncate">' + escapeHtml(taskDesc) + '</div>' +
          '</div>' +
          '<div class="flex items-center gap-1 ml-4 shrink-0">' +
            '<button onclick="runCronJobNow(\'' + escapeAttr(job.name) + '\')" class="nav-icon-btn" title="立即执行">' +
              '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>' +
            '</button>' +
            '<button onclick="editCronJob(\'' + escapeAttr(job.name) + '\')" class="nav-icon-btn" title="编辑">' +
              '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>' +
            '</button>' +
            '<button onclick="toggleCronJob(\'' + escapeAttr(job.name) + '\')" class="nav-icon-btn" title="' + (enabled ? '禁用' : '启用') + '">' +
              '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="' + (enabled ? 'M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636' : 'M18.364 5.636a9 9 0 010 12.728M5.636 18.364a9 9 0 010-12.728m12.728 12.728L5.636 5.636') + '"/></svg>' +
            '</button>' +
            '<button onclick="deleteCronJob(\'' + escapeAttr(job.name) + '\')" class="nav-icon-btn" title="删除">' +
              '<svg class="w-4 h-4 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>' +
            '</button>' +
          '</div>' +
        '</div>' +
        '<div class="flex gap-4 mt-2 text-xs text-text-muted">' +
          '<span>上次: ' + lastRun + ' ' + lastStatus + '</span>' +
          '<span>下次: ' + nextRun + '</span>' +
        '</div>' +
      '</div>';
    }).join('');

    // Load history too
    loadCronHistory();
  } catch (e) {
    document.getElementById('cronJobList').innerHTML = '<div class="text-sm text-red-400">加载失败: ' + escapeHtml(e.message) + '</div>';
  }
}

function showCronCreateForm() {
  document.getElementById('cronFormTitle').textContent = '新建任务';
  document.getElementById('cronEditName').value = '';
  document.getElementById('cronJobName').value = '';
  document.getElementById('cronJobName').disabled = false;
  document.getElementById('cronSchedule').value = '';
  document.getElementById('cronTimezone').value = '';
  document.getElementById('cronCwd').value = '';
  document.getElementById('cronCommand').value = '';
  document.getElementById('cronMessage').value = '';
  document.getElementById('cronProfile').value = '';
  document.getElementById('cronNotifyType').value = '';
  document.getElementById('cronNotifyTarget').value = '';
  document.querySelector('input[name="cronTaskType"][value="command"]').checked = true;
  toggleCronTaskType();
  toggleCronNotify();
  document.getElementById('cronFormCard').classList.remove('hidden');
}

function hideCronForm() {
  document.getElementById('cronFormCard').classList.add('hidden');
}

async function editCronJob(name) {
  try {
    const res = await fetch('/api/cron/jobs');
    const data = await res.json();
    const job = (data.jobs || []).find(j => j.name === name);
    if (!job) { alert('任务不存在'); return; }

    document.getElementById('cronFormTitle').textContent = '编辑任务';
    document.getElementById('cronEditName').value = name;
    document.getElementById('cronJobName').value = name;
    document.getElementById('cronJobName').disabled = true;
    document.getElementById('cronSchedule').value = job.schedule || '';
    document.getElementById('cronTimezone').value = job.timezone || '';
    document.getElementById('cronCwd').value = job.cwd || '';

    const isAgent = !!job.payload;
    document.querySelector('input[name="cronTaskType"][value="' + (isAgent ? 'agent' : 'command') + '"]').checked = true;
    toggleCronTaskType();

    if (isAgent) {
      document.getElementById('cronMessage').value = (job.payload.message) || '';
      document.getElementById('cronProfile').value = (job.payload.profile) || '';
    } else {
      document.getElementById('cronCommand').value = job.command || '';
    }

    const notify = job.notify || {};
    document.getElementById('cronNotifyType').value = notify.type || '';
    document.getElementById('cronNotifyTarget').value = notify.user_open_id || notify.open_id || notify.chat_id || '';
    toggleCronNotify();

    document.getElementById('cronFormCard').classList.remove('hidden');
  } catch (e) {
    alert('加载任务失败: ' + e.message);
  }
}

async function saveCronJob(e) {
  e.preventDefault();
  const editName = document.getElementById('cronEditName').value;
  const data = {
    name: document.getElementById('cronJobName').value,
    schedule: document.getElementById('cronSchedule').value,
    timezone: document.getElementById('cronTimezone').value,
    cwd: document.getElementById('cronCwd').value,
    task_type: document.querySelector('input[name="cronTaskType"]:checked').value,
    command: document.getElementById('cronCommand').value,
    message: document.getElementById('cronMessage').value,
    profile: document.getElementById('cronProfile').value,
    notify_type: document.getElementById('cronNotifyType').value,
    notify_target: document.getElementById('cronNotifyTarget').value,
  };

  try {
    const url = editName ? '/api/cron/jobs/' + encodeURIComponent(editName) : '/api/cron/jobs';
    const method = editName ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method: method,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    const result = await res.json();
    if (!res.ok) { alert('保存失败: ' + (result.detail || '未知错误')); return; }
    hideCronForm();
    loadCronJobs();
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

async function deleteCronJob(name) {
  if (!confirm('确定删除任务 "' + name + '" 吗?')) return;
  try {
    const res = await fetch('/api/cron/jobs/' + encodeURIComponent(name), {method: 'DELETE'});
    if (!res.ok) { const d = await res.json(); alert('删除失败: ' + (d.detail || '未知错误')); return; }
    loadCronJobs();
  } catch (e) {
    alert('删除失败: ' + e.message);
  }
}

async function toggleCronJob(name) {
  try {
    const res = await fetch('/api/cron/jobs/' + encodeURIComponent(name) + '/toggle', {method: 'POST'});
    if (!res.ok) { const d = await res.json(); alert('操作失败: ' + (d.detail || '未知错误')); return; }
    loadCronJobs();
  } catch (e) {
    alert('操作失败: ' + e.message);
  }
}

async function runCronJobNow(name) {
  if (!confirm('确定立即执行任务 "' + name + '" 吗?')) return;
  try {
    const res = await fetch('/api/cron/jobs/' + encodeURIComponent(name) + '/run', {method: 'POST'});
    const result = await res.json();
    if (!res.ok) { alert('执行失败: ' + (result.detail || '未知错误')); return; }
    alert('任务已执行，状态: ' + (result.result?.status || '未知'));
    loadCronJobs();
  } catch (e) {
    alert('执行失败: ' + e.message);
  }
}

async function toggleCronScheduler() {
  const statusEl = document.getElementById('cronSchedulerStatus');
  try {
    // Check current status first
    const res = await fetch('/api/cron/status');
    const status = await res.json();
    const isRunning = status.running;

    if (isRunning) {
      const stopRes = await fetch('/api/cron/scheduler/stop', {method: 'POST'});
      if (!stopRes.ok) { const d = await stopRes.json(); alert('停止失败: ' + (d.detail || '未知错误')); return; }
    } else {
      const startRes = await fetch('/api/cron/scheduler/start', {method: 'POST'});
      if (!startRes.ok) { const d = await startRes.json(); alert('启动失败: ' + (d.detail || '未知错误')); return; }
    }
    loadCronJobs();
  } catch (e) {
    alert('操作失败: ' + e.message);
  }
}

async function loadCronHistory() {
  try {
    const res = await fetch('/api/cron/history?limit=50');
    const data = await res.json();
    const listEl = document.getElementById('cronHistoryList');
    const history = data.history || [];
    if (history.length === 0) {
      listEl.innerHTML = '<div class="text-sm text-text-muted">暂无执行记录</div>';
      return;
    }
    listEl.innerHTML = history.map(entry => {
      const status = entry.status || '?';
      const statusColor = status === 'success' ? 'text-accent-green' : (status === 'timeout' ? 'text-accent-amber' : 'text-red-400');
      const time = (entry.started_at || '').substring(0, 19).replace('T', ' ');
      const duration = entry.started_at && entry.ended_at ?
        Math.round((new Date(entry.ended_at) - new Date(entry.started_at)) / 1000) + 's' : '';
      const output = (entry.stdout || entry.stderr || '').substring(0, 200);
      return '<div class="bg-dark-bg-secondary border border-dark-border rounded-lg p-3">' +
        '<div class="flex items-center gap-2 text-xs mb-1">' +
          '<span class="font-medium text-text-primary">' + escapeHtml(entry.name) + '</span>' +
          '<span class="' + statusColor + '">' + escapeHtml(status) + '</span>' +
          '<span class="text-text-muted">' + time + '</span>' +
          '<span class="text-text-muted">' + duration + '</span>' +
          '<span class="text-text-muted">rc=' + (entry.returncode ?? '?') + '</span>' +
        '</div>' +
        (output ? '<div class="text-xs text-text-muted font-mono truncate">' + escapeHtml(output) + '</div>' : '') +
      '</div>';
    }).join('');
  } catch (e) {
    document.getElementById('cronHistoryList').innerHTML = '<div class="text-sm text-red-400">加载失败: ' + escapeHtml(e.message) + '</div>';
  }
}

function applyCronPreset() {
  const val = document.getElementById('cronPreset').value;
  if (val) document.getElementById('cronSchedule').value = val;
}

function toggleCronTaskType() {
  const type = document.querySelector('input[name="cronTaskType"]:checked').value;
  document.getElementById('cronCommandGroup').classList.toggle('hidden', type !== 'command');
  document.getElementById('cronAgentGroup').classList.toggle('hidden', type !== 'agent');
}

function toggleCronNotify() {
  const val = document.getElementById('cronNotifyType').value;
  document.getElementById('cronNotifyTarget').parentElement.classList.toggle('hidden', !val);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function escapeAttr(str) {
  if (!str) return '';
  return String(str).replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// Init
document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  switchPrimaryNav('chat');
  switchSubView('agents');
  applyTracePanelState();
});
