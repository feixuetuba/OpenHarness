let openCadInitialized = false;
let openCadRenderTimer = null;
let openCadScene = null;
let openCadInteractionScene = null;
let openCadCamera = null;
let openCadRenderer = null;
let openCadModelRoot = null;
let openCadInteractionRoot = null;
let openCadWireframe = false;
let openCadRenderSeq = 0;
let openCadWasmFactoryPromise = null;
let openCadWasmUnavailable = false;
let openCadLastStl = null;
let openCadControls = {
  theta: Math.PI / 4,
  phi: Math.PI / 3,
  radius: 120,
  target: null,
  mode: '',
  lastX: 0,
  lastY: 0,
  raycaster: null,
  pointer: null,
  dragPlane: null,
  dragOffset: null,
  dragStartRootPosition: null,
  dragObject: null,
  dragStartObjectPosition: null,
  dragSourceIndex: null,
  guiDragStartPoint: null,
  guiDragCurrentPoint: null,
  guiDragObject: null,
  guiDragObjectStartPosition: null,
  guiDragObjectStartRotation: null,
  guiDragObjectStartScale: null,
  guiDragStartX: 0,
  guiDragStartY: 0,
  guiDragDeltaX: 0,
  guiDragDeltaY: 0,
};
let openCadFiles = [];
let openCadActiveFileId = '';
let openCadFilePanelCollapsed = false;
let openCadChatSessionId = 'opencad_' + Date.now();
let openCadChatStreaming = false;
let openCadWorkspaceLoadPromise = null;
let openCadWorkspaceLoaded = false;
let openCadWorkspaceSaveTimer = null;
let openCadWasmMessages = [];
let openCadOverlayStickyError = false;
let openCadLibraryFilesPromise = null;
let openCadEditorShortcutsInstalled = false;
let openCadHasUnrenderedChanges = false;
let openCadEditor = null;
let openCadEditorModels = new Map();
let openCadMonacoPromise = null;
let openCadMonacoMarkersOwner = 'openharness-opencad';
let openCadEditorSaveTimer = null;
let openCadAutoRender = false;
let openCadRenderWorker = null;
let openCadRenderWorkerBusy = false;
let openCadRenderWorkerReject = null;
let openCadWorkerRequestSeq = 0;
let openCadRenderInProgress = false;
let openCadRenderStatusProtectedUntil = 0;
let openCadDiffEditor = null;
let openCadDiffModels = [];
let openCadLibrarySymbolFiles = [];
let openCadLibrarySymbolsLoading = false;
let openCadLibrarySymbolsPromise = null;
let openCadGuiRefreshTimer = null;
let openCadSelectedGuiObjectId = '';
let openCadGuiMouseTool = '';
let openCadGuiTransformAxis = 'free';
let openCadGuiInteractionBusy = false;
let openCadGuiDebugLines = [];
let openCadGuiDebugExpanded = false;
const OPENSCAD_WASM_MODULE_PATHS = [
  '/static/vendor/openscad/openscad.js',
  '/static/openscad/openscad.js',
];
const OPENSCAD_FILES_STORAGE_KEY = 'openharness.opencad.files';
const OPENSCAD_ACTIVE_FILE_STORAGE_KEY = 'openharness.opencad.active_file';
const OPENSCAD_CHAT_AGENT_STORAGE_KEY = 'openharness.opencad.chat_agent';
const OPENSCAD_AUTO_RENDER_STORAGE_KEY = 'openharness.opencad.auto_render';
const OPENSCAD_DRAG_TRANSLATE_MARKER = '// OpenHarness transform: drag-offset';
const OPENSCAD_WORKER_RENDER_TIMEOUT_MS = 90000;
const OPENSCAD_SIGNATURES = {
  cube: { label: 'cube(size = [x, y, z], center = false)', parameters: ['size', 'center'] },
  sphere: { label: 'sphere(r = 1, d, $fn)', parameters: ['r', 'd', '$fn'] },
  cylinder: { label: 'cylinder(h = 1, r, r1, r2, d, d1, d2, center = false, $fn)', parameters: ['h', 'r', 'r1', 'r2', 'd', 'd1', 'd2', 'center', '$fn'] },
  translate: { label: 'translate(v = [x, y, z]) child', parameters: ['v'] },
  rotate: { label: 'rotate(a = [x, y, z], v) child', parameters: ['a', 'v'] },
  scale: { label: 'scale(v = [x, y, z]) child', parameters: ['v'] },
  color: { label: 'color(c, alpha = 1.0) child', parameters: ['c', 'alpha'] },
  linear_extrude: { label: 'linear_extrude(height, center = false, convexity, twist, slices, scale) child', parameters: ['height', 'center', 'convexity', 'twist', 'slices', 'scale'] },
  rotate_extrude: { label: 'rotate_extrude(angle = 360, convexity, $fn) child', parameters: ['angle', 'convexity', '$fn'] },
  gear: { label: 'gear(number_of_teeth, circular_pitch, diametral_pitch, pressure_angle, clearance, backlash, twist, involute_facets, flat, bore_diameter, gear_thickness, rim_thickness, hub_thickness, hub_diameter)', parameters: ['number_of_teeth', 'circular_pitch', 'diametral_pitch', 'pressure_angle', 'clearance', 'backlash', 'twist', 'involute_facets', 'flat', 'bore_diameter', 'gear_thickness', 'rim_thickness', 'hub_thickness', 'hub_diameter'] },
};
const OPENSCAD_GUI_PRIMITIVE_SNIPPETS = {
  cube: 'translate([0, 0, 0])\\nrotate([0, 0, 0])\\ncube([20, 20, 20], center=true);',
  cylinder: 'translate([0, 0, 0])\\nrotate([0, 0, 0])\\ncylinder(h=30, r=10, center=true);',
  sphere: 'translate([0, 0, 0])\\nrotate([0, 0, 0])\\nsphere(r=12);',
};
const OPENSCAD_GUI_BOOLEAN_SNIPPETS = {
  union: 'union() {\\n  cube([20, 20, 20], center=true);\\n  translate([12, 0, 0]) sphere(r=10);\\n}',
  difference: 'difference() {\\n  cube([30, 30, 20], center=true);\\n  cylinder(h=40, r=8, center=true);\\n}',
  intersection: 'intersection() {\\n  cube([28, 28, 28], center=true);\\n  sphere(r=18);\\n}',
};
const OPENSCAD_SAMPLE = `// OpenSCAD model generated in OpenHarness
$fn = 48;

color("steelblue")
difference() {
  union() {
cube([50, 36, 8], center=true);
translate([0, 0, 10]) cylinder(h=20, r=13, center=true);
translate([-18, 0, 8]) sphere(r=7);
translate([18, 0, 8]) sphere(r=7);
  }
  translate([0, 0, 11]) cylinder(h=24, r=6, center=true);
}`;

async function initOpenCad() {
  if (!window.THREE) {
    setOpenCadStatus('Three.js 未加载，无法渲染', true);
    return;
  }
  await loadOpenCadFiles();
  renderOpenCadFileTabs();
  populateOpenCadChatOptions();
  await initOpenCadEditor();
  setOpenCadEditorFile(getActiveOpenCadFile());
  installOpenCadEditorShortcuts();
  loadOpenCadAutoRenderPreference();
  renderOpenCadAutoRenderState();
  renderOpenCadGuiPanel();
  installOpenCadGuiDebugInterceptors();
  if (!openCadInitialized) {
    const viewport = document.getElementById('openCadViewport');
    openCadScene = new THREE.Scene();
    openCadScene.background = new THREE.Color(0x0b1020);
    openCadInteractionScene = new THREE.Scene();
    openCadCamera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    openCadControls.target = new THREE.Vector3(0, 0, 0);
    openCadControls.raycaster = new THREE.Raycaster();
    openCadControls.pointer = new THREE.Vector2();
    openCadControls.dragPlane = new THREE.Plane();
    openCadControls.dragOffset = new THREE.Vector3();
    openCadRenderer = new THREE.WebGLRenderer({ antialias: true });
    openCadRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    openCadRenderer.autoClear = false;
    openCadRenderer.domElement.style.display = 'block';
    openCadRenderer.domElement.style.width = '100%';
    openCadRenderer.domElement.style.height = '100%';
    viewport.innerHTML = '';
    viewport.appendChild(openCadRenderer.domElement);

    const ambient = new THREE.AmbientLight(0xffffff, 0.55);
    const key = new THREE.DirectionalLight(0xffffff, 0.85);
    key.position.set(60, 80, 100);
    const fill = new THREE.DirectionalLight(0x7dd3fc, 0.25);
    fill.position.set(-80, -50, 60);
    openCadScene.add(ambient, key, fill);
    openCadInteractionScene.add(ambient.clone(), key.clone(), fill.clone());
    openCadScene.add(new THREE.GridHelper(160, 16, 0x335066, 0x1b2a3d));
    openCadScene.add(new THREE.AxesHelper(55));

    installOpenCadControls(viewport);
    installOpenCadLayoutSplitter();
    window.addEventListener('resize', resizeOpenCadViewport);
    openCadInitialized = true;
  }
  resizeOpenCadViewport();
  renderOpenCad();
  animateOpenCad();
}

function installOpenCadGuiDebugInterceptors() {
  const el = document.getElementById('openCadGuiDebugShell');
  if (!el || el.dataset.openCadDebugInterceptors === '1') return;
  el.dataset.openCadDebugInterceptors = '1';
  const stop = event => event.stopPropagation();
  ['pointerdown', 'pointermove', 'pointerup', 'mousedown', 'mousemove', 'mouseup', 'click', 'dblclick', 'wheel', 'contextmenu']
    .forEach(type => el.addEventListener(type, stop));
}

async function loadOpenCadFiles() {
  if (openCadWorkspaceLoaded && openCadFiles.length) return;
  if (openCadWorkspaceLoadPromise) return openCadWorkspaceLoadPromise;
  openCadWorkspaceLoadPromise = (async () => {
    try {
      const res = await fetch('/api/opencad/workspace');
      if (res.ok) {
        const data = await res.json();
        applyOpenCadWorkspacePayload(data);
      }
    } catch (error) {
      console.warn('Failed to load OpenCAD workspace from server:', error);
    }
    if (!openCadFiles.length) {
      loadOpenCadFilesFromLocalStorage();
      saveOpenCadFiles({ remote: true, immediate: true });
    }
    openCadWorkspaceLoaded = true;
  })();
  try {
    return await openCadWorkspaceLoadPromise;
  } finally {
    openCadWorkspaceLoadPromise = null;
  }
}

function applyOpenCadWorkspacePayload(data, options = {}) {
  const files = Array.isArray(data?.files) ? data.files : [];
  if (!files.length) return;
  resetOpenCadLibrarySymbolIndex();
  const currentById = new Map(openCadFiles.map(file => [file.id, file]));
  openCadFiles = files
    .filter(file => file && file.name)
    .map(file => {
      const id = file.id || makeOpenCadFileId();
      const savedCode = unwrapOpenCadDragTranslateWrapper(String(file.code || ''));
      const current = currentById.get(id);
      return {
        id,
        name: sanitizeOpenCadFileName(file.name),
        code: options.preserveCurrentCode && current ? current.code || '' : savedCode,
        savedCode,
        localPath: file.local_path || file.localPath || '',
      };
    });
  const activeId = data?.active_file_id || '';
  openCadActiveFileId = openCadFiles.some(file => file.id === activeId) ? activeId : openCadFiles[0].id;
  saveOpenCadFiles({ remote: false });
}

function loadOpenCadFilesFromLocalStorage() {
  try {
    const saved = JSON.parse(localStorage.getItem(OPENSCAD_FILES_STORAGE_KEY) || '[]');
    if (Array.isArray(saved) && saved.length) {
      openCadFiles = saved
        .filter(file => file && file.name)
        .map(file => ({
          id: file.id || makeOpenCadFileId(),
          name: sanitizeOpenCadFileName(file.name),
          code: unwrapOpenCadDragTranslateWrapper(String(file.code || '')),
          savedCode: unwrapOpenCadDragTranslateWrapper(String(file.savedCode ?? file.code ?? '')),
          localPath: file.localPath || '',
        }));
    }
  } catch (error) {
    console.warn('Failed to load OpenCAD files:', error);
  }
  if (!openCadFiles.length) {
    openCadFiles = [{
      id: makeOpenCadFileId(),
      name: 'main.scad',
      code: localStorage.getItem('openharness.opencad.code') || OPENSCAD_SAMPLE,
      savedCode: localStorage.getItem('openharness.opencad.code') || OPENSCAD_SAMPLE,
    }];
  }
  const savedActiveId = localStorage.getItem(OPENSCAD_ACTIVE_FILE_STORAGE_KEY) || '';
  openCadActiveFileId = openCadFiles.some(file => file.id === savedActiveId) ? savedActiveId : openCadFiles[0].id;
  saveOpenCadFiles({ remote: false });
}

function saveOpenCadFiles(options = {}) {
  localStorage.setItem(OPENSCAD_FILES_STORAGE_KEY, JSON.stringify(openCadFiles));
  localStorage.setItem(OPENSCAD_ACTIVE_FILE_STORAGE_KEY, openCadActiveFileId);
  if (options.remote !== false) {
    scheduleOpenCadWorkspaceSave(Boolean(options.immediate));
  }
}

function scheduleOpenCadWorkspaceSave(immediate = false) {
  clearTimeout(openCadWorkspaceSaveTimer);
  openCadWorkspaceSaveTimer = setTimeout(saveOpenCadWorkspaceToServer, immediate ? 0 : 600);
}

async function saveOpenCadWorkspaceToServer() {
  try {
    const res = await fetch('/api/opencad/workspace', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        files: openCadFiles.map(file => ({
          id: file.id,
          name: file.name,
          code: file.code || '',
        })),
        active_file_id: openCadActiveFileId,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    const data = await res.json();
    resetOpenCadLibrarySymbolIndex();
    applyOpenCadWorkspacePayload(data, { preserveCurrentCode: true });
    renderOpenCadFileTabs();
    refreshOpenCadDiffIfOpen();
    if (!openCadRenderInProgress && Date.now() > openCadRenderStatusProtectedUntil) {
      setOpenCadStatus('已保存到服务端');
    }
  } catch (error) {
    console.warn('Failed to save OpenCAD workspace:', error);
    setOpenCadStatus(`服务端保存失败：${formatOpenCadError(error)}`, true);
  }
}

function makeOpenCadFileId() {
  return 'file_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
}

function sanitizeOpenCadFileName(name) {
  const cleaned = String(name || '').trim().replace(/[\\/:*?"<>|]/g, '_');
  return cleaned.endsWith('.scad') ? cleaned : `${cleaned || 'part'}.scad`;
}

function getActiveOpenCadFile() {
  return openCadFiles.find(file => file.id === openCadActiveFileId) || openCadFiles[0] || null;
}

async function initOpenCadEditor() {
  const fallback = document.getElementById('openCadCode');
  const container = document.getElementById('openCadEditorContainer');
  if (!container || openCadEditor) return;
  try {
    const monaco = await loadOpenCadMonaco();
    registerOpenCadMonacoLanguage(monaco);
    openCadEditor = monaco.editor.create(container, {
      automaticLayout: true,
      fontFamily: 'JetBrains Mono, Menlo, Monaco, Consolas, monospace',
      fontSize: 13,
      lineHeight: 20,
      minimap: { enabled: false },
      model: null,
      padding: { top: 12, bottom: 12 },
      renderLineHighlight: 'all',
      roundedSelection: false,
      scrollBeyondLastLine: false,
      tabSize: 2,
      theme: 'openharness-opencad-dark',
      wordWrap: 'off',
    });
    openCadEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => renderOpenCad());
    openCadEditor.addCommand(monaco.KeyCode.F5, () => renderOpenCad());
    openCadEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      syncOpenCadEditorToActiveFile();
      saveOpenCadFiles({ immediate: true });
      if (!openCadRenderInProgress) setOpenCadStatus('已保存到服务端');
    });
    ensureOpenCadLibrarySymbolsLoaded();
    if (fallback) fallback.classList.add('hidden');
  } catch (error) {
    console.warn('Failed to initialize Monaco editor:', error);
    if (container) container.classList.add('hidden');
    if (fallback) {
      fallback.classList.remove('hidden');
      fallback.value = getActiveOpenCadFile()?.code || '';
    }
    setOpenCadStatus('Monaco 编辑器加载失败，已使用基础编辑器', true);
  }
}

function loadOpenCadMonaco() {
  if (window.monaco?.editor) return Promise.resolve(window.monaco);
  if (openCadMonacoPromise) return openCadMonacoPromise;
  openCadMonacoPromise = new Promise((resolve, reject) => {
    if (!window.require) {
      reject(new Error('Monaco loader is not available'));
      return;
    }
    window.require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.49.0/min/vs' } });
    window.require(['vs/editor/editor.main'], () => resolve(window.monaco), reject);
  });
  return openCadMonacoPromise;
}

function registerOpenCadMonacoLanguage(monaco) {
  if (monaco.languages.getLanguages().some(lang => lang.id === 'openscad')) return;
  monaco.languages.register({ id: 'openscad', extensions: ['.scad'], aliases: ['OpenSCAD', 'openscad', 'scad'] });
  monaco.languages.setLanguageConfiguration('openscad', {
    comments: {
      lineComment: '//',
      blockComment: ['/*', '*/'],
    },
    brackets: [['{', '}'], ['[', ']'], ['(', ')']],
    autoClosingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '"', close: '"' },
      { open: "'", close: "'" },
    ],
    surroundingPairs: [
      { open: '{', close: '}' },
      { open: '[', close: ']' },
      { open: '(', close: ')' },
      { open: '"', close: '"' },
      { open: "'", close: "'" },
    ],
  });
  monaco.languages.setMonarchTokensProvider('openscad', {
    defaultToken: '',
    keywords: [
      'module', 'function', 'if', 'else', 'for', 'let', 'assert', 'echo', 'use', 'include', 'true', 'false',
      'undef', 'each', 'intersection_for',
    ],
    builtins: [
      'cube', 'sphere', 'cylinder', 'polyhedron', 'circle', 'square', 'polygon', 'text', 'translate', 'rotate',
      'scale', 'resize', 'mirror', 'multmatrix', 'color', 'offset', 'hull', 'minkowski', 'union', 'difference',
      'intersection', 'linear_extrude', 'rotate_extrude', 'surface', 'import', 'projection', 'children',
      'gear', 'rack', 'bevel_gear', 'bevel_gear_pair', 'worm', 'worm_gear',
      'abs', 'acos', 'asin', 'atan', 'atan2', 'ceil', 'cos', 'exp', 'floor', 'ln', 'log', 'max', 'min', 'pow',
      'rands', 'round', 'sign', 'sin', 'sqrt', 'tan', 'len', 'str', 'chr', 'concat', 'lookup', 'search',
      'version', 'version_num',
    ],
    operators: ['=', '>', '<', '!', '~', '?', ':', '==', '<=', '>=', '!=', '&&', '||', '+', '-', '*', '/', '%'],
    tokenizer: {
      root: [
        [/\/\*/, 'comment', '@comment'],
        [/\/\/.*$/, 'comment'],
        [/[a-zA-Z_$][\w$]*/, { cases: { '@keywords': 'keyword', '@builtins': 'type.identifier', '@default': 'identifier' } }],
        [/[{}()[\]]/, '@brackets'],
        [/[<>](?!@symbols)/, '@brackets'],
        [/@symbols/, { cases: { '@operators': 'operator', '@default': '' } }],
        [/\d*\.\d+([eE][+-]?\d+)?/, 'number.float'],
        [/0[xX][0-9a-fA-F]+/, 'number.hex'],
        [/\d+/, 'number'],
        [/[;,.]/, 'delimiter'],
        [/".*?"/, 'string'],
        [/'.*?'/, 'string'],
      ],
      comment: [
        [/[^/*]+/, 'comment'],
        [/\*\//, 'comment', '@pop'],
        [/[/*]/, 'comment'],
      ],
    },
    symbols: /[=><!~?:&|+\-*/%]+/,
  });
  monaco.editor.defineTheme('openharness-opencad-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'keyword', foreground: '34d399', fontStyle: 'bold' },
      { token: 'type.identifier', foreground: '60a5fa' },
      { token: 'number', foreground: 'fbbf24' },
      { token: 'string', foreground: 'a7f3d0' },
      { token: 'comment', foreground: '22c55e', fontStyle: 'italic' },
    ],
    colors: {
      'editor.background': '#0f172a',
      'editor.foreground': '#e2e8f0',
      'editorLineNumber.foreground': '#475569',
      'editorLineNumber.activeForeground': '#94a3b8',
      'editorCursor.foreground': '#34d399',
      'editor.selectionBackground': '#2563eb66',
      'editor.lineHighlightBackground': '#1e293b66',
      'editorGutter.background': '#0f172a',
    },
  });
  monaco.languages.registerCompletionItemProvider('openscad', {
    triggerCharacters: ['<', '"', '(', '.', '$', '_'],
    provideCompletionItems: async (model, position) => ({
      suggestions: await buildOpenCadCompletionItems(monaco, model, position),
    }),
  });
  monaco.languages.registerSignatureHelpProvider('openscad', {
    signatureHelpTriggerCharacters: ['(', ','],
    signatureHelpRetriggerCharacters: [','],
    provideSignatureHelp: (model, position) => ({
      value: buildOpenCadSignatureHelp(model, position),
      dispose: () => {},
    }),
  });
}

function getOpenCadModelForFile(file) {
  if (!window.monaco?.editor || !file) return null;
  if (openCadEditorModels.has(file.id)) return openCadEditorModels.get(file.id);
  const uri = window.monaco.Uri.parse(`inmemory://openharness-opencad/${encodeURIComponent(file.name)}`);
  const model = window.monaco.editor.createModel(file.code || '', 'openscad', uri);
  model.updateOptions({ tabSize: 2, insertSpaces: true });
  model.onDidChangeContent(() => handleOpenCadCodeInput());
  openCadEditorModels.set(file.id, model);
  return model;
}

function refreshOpenCadEditorModel(file) {
  if (!file || !window.monaco?.editor) return;
  const wasActive = file.id === openCadActiveFileId;
  const oldModel = openCadEditorModels.get(file.id);
  if (oldModel) {
    file.code = oldModel.getValue();
    oldModel.dispose();
    openCadEditorModels.delete(file.id);
  }
  if (wasActive) setOpenCadEditorFile(file);
}

function disposeOpenCadEditorModel(fileId) {
  const model = openCadEditorModels.get(fileId);
  if (model) model.dispose();
  openCadEditorModels.delete(fileId);
}

function setOpenCadEditorFile(file) {
  const fallback = document.getElementById('openCadCode');
  if (!file) return;
  if (openCadEditor) {
    const model = getOpenCadModelForFile(file);
    if (model && openCadEditor.getModel() !== model) openCadEditor.setModel(model);
    openCadEditor.focus();
  } else if (fallback) {
    fallback.value = file.code || '';
  }
  renderOpenCadGuiPanel();
}

function getOpenCadEditorValue() {
  if (openCadEditor) return openCadEditor.getValue();
  return document.getElementById('openCadCode')?.value || '';
}

function setOpenCadEditorValue(value, file = getActiveOpenCadFile()) {
  const nextValue = String(value || '');
  if (file) file.code = nextValue;
  if (openCadEditor && file) {
    const model = getOpenCadModelForFile(file);
    if (model && model.getValue() !== nextValue) model.setValue(nextValue);
    if (model && openCadEditor.getModel() !== model) openCadEditor.setModel(model);
  }
  const fallback = document.getElementById('openCadCode');
  if (fallback) fallback.value = nextValue;
}

function setOpenCadFileCode(file, value) {
  if (!file) return;
  const nextValue = String(value || '');
  file.code = nextValue;
  const model = openCadEditorModels.get(file.id);
  if (model && model.getValue() !== nextValue) model.setValue(nextValue);
}

function syncOpenCadEditorToActiveFile() {
  const file = getActiveOpenCadFile();
  if (!file) return '';
  file.code = getOpenCadEditorValue();
  return file.code;
}

function getOpenCadSavedCode(file) {
  return String(file?.savedCode ?? '');
}

function isOpenCadFileDirty(file) {
  if (!file) return false;
  return String(file.code || '') !== getOpenCadSavedCode(file);
}

async function showOpenCadDiff() {
  syncOpenCadEditorToActiveFile();
  const file = getActiveOpenCadFile();
  if (!file) return;
  const modal = document.getElementById('openCadDiffModal');
  const container = document.getElementById('openCadDiffContainer');
  const title = document.getElementById('openCadDiffTitle');
  const summary = document.getElementById('openCadDiffSummary');
  if (!modal || !container) return;
  try {
    const monaco = await loadOpenCadMonaco();
    registerOpenCadMonacoLanguage(monaco);
    modal.classList.remove('hidden');
    if (!openCadDiffEditor) {
      openCadDiffEditor = monaco.editor.createDiffEditor(container, {
        automaticLayout: true,
        fontFamily: 'JetBrains Mono, Menlo, Monaco, Consolas, monospace',
        fontSize: 13,
        lineHeight: 20,
        minimap: { enabled: false },
        originalEditable: false,
        renderSideBySide: true,
        scrollBeyondLastLine: false,
        theme: 'openharness-opencad-dark',
        wordWrap: 'off',
      });
    }
    setOpenCadDiffModels(file);
    if (title) title.textContent = `${file.name} 的代码改动`;
    if (summary) {
      summary.textContent = isOpenCadFileDirty(file)
        ? '左侧是服务端保存版本，右侧是当前编辑器内容'
        : '当前编辑器内容与服务端保存版本一致';
    }
    setTimeout(() => openCadDiffEditor?.layout(), 0);
  } catch (error) {
    console.warn('Failed to open OpenCAD diff:', error);
    setOpenCadStatus(`打开改动视图失败：${formatOpenCadError(error)}`, true);
  }
}

function setOpenCadDiffModels(file = getActiveOpenCadFile()) {
  if (!window.monaco?.editor || !openCadDiffEditor || !file) return;
  disposeOpenCadDiffModels();
  const stamp = Date.now().toString(36);
  const original = window.monaco.editor.createModel(
    getOpenCadSavedCode(file),
    'openscad',
    window.monaco.Uri.parse(`inmemory://openharness-opencad-diff/${encodeURIComponent(file.name)}.${stamp}.saved.scad`),
  );
  const modified = window.monaco.editor.createModel(
    String(file.code || ''),
    'openscad',
    window.monaco.Uri.parse(`inmemory://openharness-opencad-diff/${encodeURIComponent(file.name)}.${stamp}.current.scad`),
  );
  openCadDiffModels = [original, modified];
  openCadDiffEditor.setModel({ original, modified });
}

function refreshOpenCadDiffIfOpen() {
  const modal = document.getElementById('openCadDiffModal');
  if (!modal || modal.classList.contains('hidden') || !openCadDiffEditor) return;
  const file = getActiveOpenCadFile();
  if (!file) return;
  setOpenCadDiffModels(file);
  const summary = document.getElementById('openCadDiffSummary');
  if (summary) {
    summary.textContent = isOpenCadFileDirty(file)
      ? '左侧是服务端保存版本，右侧是当前编辑器内容'
      : '当前编辑器内容与服务端保存版本一致';
  }
}

function closeOpenCadDiff() {
  const modal = document.getElementById('openCadDiffModal');
  if (modal) modal.classList.add('hidden');
  disposeOpenCadDiffModels();
}

function disposeOpenCadDiffModels() {
  for (const model of openCadDiffModels) {
    try {
      model.dispose();
    } catch (error) {
      console.debug('OpenCAD diff model dispose skipped:', error);
    }
  }
  openCadDiffModels = [];
}

async function buildOpenCadCompletionItems(monaco, model, position) {
  const importPathContext = getOpenCadImportPathContext(model, position);
  await ensureOpenCadLibrarySymbolsLoaded();
  if (importPathContext) return buildOpenCadFileCompletionItems(monaco, position, importPathContext);
  const range = model.getWordUntilPosition(position);
  const replaceRange = {
    startLineNumber: position.lineNumber,
    endLineNumber: position.lineNumber,
    startColumn: range.startColumn,
    endColumn: range.endColumn,
  };
  const indexed = getOpenCadSymbolIndex(model);
  const callContext = getOpenCadCallContext(model, position);
  if (callContext) {
    return [
      ...buildOpenCadArgumentCompletionItems(monaco, position, callContext.name, replaceRange),
      ...buildOpenCadSymbolCompletionItems(monaco, replaceRange, indexed, { includeCallables: false }),
    ];
  }
  const snippet = monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet;
  const suggestions = [
    ['cube', 'cube([${1:10}, ${2:10}, ${3:10}], center=${4:true});'],
    ['cylinder', 'cylinder(h=${1:10}, d=${2:5}, $fn=${3:64});'],
    ['sphere', 'sphere(r=${1:10}, $fn=${2:64});'],
    ['translate', 'translate([${1:0}, ${2:0}, ${3:0}]) {\n  ${0}\n}'],
    ['rotate', 'rotate([${1:0}, ${2:0}, ${3:90}]) {\n  ${0}\n}'],
    ['color', 'color("${1:Silver}") {\n  ${0}\n}'],
    ['difference', 'difference() {\n  ${1:// base}\n  ${2:// cutout}\n}'],
    ['union', 'union() {\n  ${0}\n}'],
    ['module', 'module ${1:name}(${2:args}) {\n  ${0}\n}'],
    ['function', 'function ${1:name}(${2:args}) = ${0};'],
    ['use', 'use <${1:MCAD/gears.scad}>'],
    ['include', 'include <${1:MCAD/constants.scad}>'],
    ['gear', 'gear(number_of_teeth=${1:12}, circular_pitch=${2:500}, gear_thickness=${3:6}, bore_diameter=${4:5});'],
  ].map(([label, insertText]) => ({
    label,
    kind: monaco.languages.CompletionItemKind.Snippet,
    insertText,
    insertTextRules: snippet,
    range: replaceRange,
  }));
  const activeCode = model.getValue();
  for (const name of extractOpenCadNames(activeCode, /\b(?:module|function)\s+([A-Za-z_]\w*)\s*\(/g)) {
    suggestions.push({
      label: name,
      kind: monaco.languages.CompletionItemKind.Function,
      insertText: `${name}($0);`,
      insertTextRules: snippet,
      range: replaceRange,
    });
  }
  suggestions.push(...buildOpenCadSymbolCompletionItems(monaco, replaceRange, indexed, {
    existingLabels: new Set(suggestions.map(item => String(item.label))),
  }));
  return suggestions;
}

function buildOpenCadSymbolCompletionItems(monaco, replaceRange, indexed, options = {}) {
  const includeCallables = options.includeCallables !== false;
  const includeVariables = options.includeVariables !== false;
  const existingLabels = options.existingLabels || new Set();
  const snippet = monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet;
  const suggestions = [];
  if (includeCallables) {
    for (const symbol of indexed.callables) {
      if (existingLabels.has(symbol.name)) continue;
      existingLabels.add(symbol.name);
      const params = symbol.parameters.map(param => param.name).filter(Boolean);
      suggestions.push({
        label: symbol.name,
        kind: symbol.kind === 'module' ? monaco.languages.CompletionItemKind.Function : monaco.languages.CompletionItemKind.Method,
        insertText: `${symbol.name}(${params.map((param, index) => `${param}=\${${index + 1}}`).join(', ')});`,
        insertTextRules: snippet,
        detail: `${symbol.kind} from ${symbol.source}`,
        documentation: symbol.label,
        range: replaceRange,
      });
    }
  }
  if (includeVariables) {
    for (const variable of indexed.variables) {
      if (existingLabels.has(variable.name)) continue;
      existingLabels.add(variable.name);
      suggestions.push({
        label: variable.name,
        kind: monaco.languages.CompletionItemKind.Variable,
        insertText: variable.name,
        detail: `variable from ${variable.source}`,
        range: replaceRange,
      });
    }
  }
  return suggestions;
}

function buildOpenCadFileCompletionItems(monaco, position, context) {
  const replaceRange = {
    startLineNumber: position.lineNumber,
    endLineNumber: position.lineNumber,
    startColumn: context.startColumn,
    endColumn: position.column,
  };
  const suggestions = openCadFiles.map(file => ({
    label: file.name,
    kind: monaco.languages.CompletionItemKind.File,
    insertText: file.name,
    range: replaceRange,
  }));
  const libraryPaths = getOpenCadLibraryCompletionPaths();
  for (const path of libraryPaths) {
    suggestions.push({
      label: path,
      kind: monaco.languages.CompletionItemKind.File,
      insertText: path,
      range: replaceRange,
    });
  }
  return suggestions;
}

function buildOpenCadArgumentCompletionItems(monaco, position, functionName, fallbackRange = null) {
  const signature = getOpenCadSignature(functionName);
  if (!signature?.parameters?.length) return [];
  const model = openCadEditor?.getModel();
  const wordRange = model?.getWordUntilPosition(position);
  const currentWord = model ? model.getValueInRange({
    startLineNumber: position.lineNumber,
    endLineNumber: position.lineNumber,
    startColumn: wordRange?.startColumn || position.column,
    endColumn: position.column,
  }).trim() : '';
  if (!currentWord && !fallbackRange) return [];
  const replaceRange = {
    startLineNumber: position.lineNumber,
    endLineNumber: position.lineNumber,
    startColumn: wordRange?.startColumn || fallbackRange?.startColumn || position.column,
    endColumn: wordRange?.endColumn || fallbackRange?.endColumn || position.column,
  };
  return signature.parameters.map(param => ({
    label: `${param}=`,
    kind: monaco.languages.CompletionItemKind.Property,
    insertText: `${param} = \${1}`,
    insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
    range: replaceRange,
  }));
}

function buildOpenCadSignatureHelp(model, position) {
  const context = getOpenCadCallContext(model, position);
  const signature = getOpenCadSignature(context?.name || '');
  if (!signature) {
    return { signatures: [], activeSignature: 0, activeParameter: 0 };
  }
  return {
    signatures: [{
      label: signature.label,
      documentation: signature.documentation || '',
      parameters: signature.parameters.map(param => ({ label: param })),
    }],
    activeSignature: 0,
    activeParameter: Math.min(context.parameterIndex, Math.max(0, signature.parameters.length - 1)),
  };
}

function getOpenCadSignature(name) {
  const rawName = String(name || '');
  const key = rawName.toLowerCase();
  if (OPENSCAD_SIGNATURES[key]) return OPENSCAD_SIGNATURES[key];
  const symbol = getOpenCadSymbolIndex(openCadEditor?.getModel()).callables
    .find(item => item.name.toLowerCase() === key);
  if (!symbol) return null;
  return {
    label: symbol.label,
    documentation: symbol.source ? `Defined in ${symbol.source}` : '',
    parameters: symbol.parameters.map(param => param.name).filter(Boolean),
  };
}

function getOpenCadImportPathContext(model, position) {
  const prefix = model.getLineContent(position.lineNumber).slice(0, position.column - 1);
  const match = prefix.match(/\b(?:use|include)\s*[<"]([^>"]*)$/i);
  if (!match) return null;
  return {
    query: match[1],
    startColumn: position.column - match[1].length,
  };
}

function getOpenCadCallContext(model, position) {
  const offset = model.getOffsetAt(position);
  const text = model.getValue().slice(0, offset);
  let depth = 0;
  for (let index = text.length - 1; index >= 0; index -= 1) {
    const ch = text[index];
    if (ch === ')') depth += 1;
    if (ch === '(') {
      if (depth > 0) {
        depth -= 1;
        continue;
      }
      const before = text.slice(0, index).match(/([A-Za-z_]\w*)\s*$/);
      if (!before) return null;
      const args = text.slice(index + 1);
      return {
        name: before[1],
        parameterIndex: countOpenCadTopLevelCommas(args),
      };
    }
  }
  return null;
}

function countOpenCadTopLevelCommas(text) {
  let depth = 0;
  let count = 0;
  let quote = '';
  for (const ch of String(text || '')) {
    if (quote) {
      if (ch === quote) quote = '';
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '(' || ch === '[' || ch === '{') depth += 1;
    if (ch === ')' || ch === ']' || ch === '}') depth = Math.max(0, depth - 1);
    if (ch === ',' && depth === 0) count += 1;
  }
  return count;
}

function escapeOpenCadRegex(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function getOpenCadSymbolIndex(model = openCadEditor?.getModel()) {
  const files = openCadFiles.map(file => {
    const isActive = file.id === openCadActiveFileId;
    const activeModel = isActive ? model : openCadEditorModels.get(file.id);
    return {
      name: file.name,
      code: activeModel ? activeModel.getValue() : String(file.code || ''),
      kind: 'workspace',
    };
  });
  files.push(...openCadLibrarySymbolFiles);
  const callables = [];
  const variables = [];
  const seenCallables = new Set();
  const seenVariables = new Set();

  for (const file of files) {
    const symbols = parseOpenCadSymbols(file.code, file.name, file.kind);
    for (const symbol of symbols.callables) {
      const key = `${symbol.name.toLowerCase()}:${symbol.source}`;
      if (seenCallables.has(key)) continue;
      seenCallables.add(key);
      callables.push(symbol);
    }
    for (const variable of symbols.variables) {
      const key = `${variable.name}:${variable.source}`;
      if (seenVariables.has(key)) continue;
      seenVariables.add(key);
      variables.push(variable);
    }
  }
  return { callables, variables };
}

function parseOpenCadSymbols(code, source = '', sourceKind = 'workspace') {
  const cleaned = stripOpenCadComments(code);
  const callables = [];
  const variables = [];
  const callableRegex = /\b(module|function)\s+([A-Za-z_]\w*)\s*\(([^)]*)\)/g;
  let match;
  while ((match = callableRegex.exec(cleaned))) {
    const params = parseOpenCadParameterList(match[3]);
    callables.push({
      kind: match[1],
      name: match[2],
      source,
      sourceKind,
      parameters: params,
      label: `${match[2]}(${params.map(param => param.label).join(', ')})`,
    });
  }

  let depth = 0;
  for (const line of cleaned.split('\n')) {
    const startDepth = depth;
    const variableMatch = startDepth === 0 ? line.match(/^\s*([$A-Za-z_][\w$]*)\s*=/) : null;
    if (variableMatch && !['module', 'function'].includes(variableMatch[1])) {
      variables.push({ name: variableMatch[1], source, sourceKind });
    }
    depth = updateOpenCadBraceDepth(depth, line);
  }

  return { callables, variables };
}

function stripOpenCadComments(code) {
  return String(code || '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');
}

function parseOpenCadParameterList(paramText) {
  return splitOpenCadTopLevel(paramText, ',')
    .map(part => part.trim())
    .filter(Boolean)
    .map(part => {
      const equalsIndex = findOpenCadTopLevelChar(part, '=');
      const label = part.trim();
      const name = (equalsIndex >= 0 ? part.slice(0, equalsIndex) : part).trim();
      return { name, label };
    })
    .filter(param => /^[$A-Za-z_][\w$]*$/.test(param.name));
}

function splitOpenCadTopLevel(text, delimiter = ',') {
  const parts = [];
  let depth = 0;
  let quote = '';
  let start = 0;
  const value = String(text || '');
  for (let index = 0; index < value.length; index += 1) {
    const ch = value[index];
    if (quote) {
      if (ch === quote && value[index - 1] !== '\\') quote = '';
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '(' || ch === '[' || ch === '{') depth += 1;
    if (ch === ')' || ch === ']' || ch === '}') depth = Math.max(0, depth - 1);
    if (ch === delimiter && depth === 0) {
      parts.push(value.slice(start, index));
      start = index + 1;
    }
  }
  parts.push(value.slice(start));
  return parts;
}

function findOpenCadTopLevelChar(text, target) {
  let depth = 0;
  let quote = '';
  const value = String(text || '');
  for (let index = 0; index < value.length; index += 1) {
    const ch = value[index];
    if (quote) {
      if (ch === quote && value[index - 1] !== '\\') quote = '';
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '(' || ch === '[' || ch === '{') depth += 1;
    if (ch === ')' || ch === ']' || ch === '}') depth = Math.max(0, depth - 1);
    if (ch === target && depth === 0) return index;
  }
  return -1;
}

function updateOpenCadBraceDepth(depth, line) {
  let nextDepth = depth;
  let quote = '';
  for (const ch of String(line || '')) {
    if (quote) {
      if (ch === quote) quote = '';
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '{') nextDepth += 1;
    if (ch === '}') nextDepth = Math.max(0, nextDepth - 1);
  }
  return nextDepth;
}

async function ensureOpenCadLibrarySymbolsLoaded() {
  if (openCadLibrarySymbolFiles.length) return;
  if (openCadLibrarySymbolsPromise) return openCadLibrarySymbolsPromise;
  openCadLibrarySymbolsLoading = true;
  openCadLibrarySymbolsPromise = loadOpenCadLibraryFiles()
    .then(files => {
      openCadLibrarySymbolFiles = files
        .map(file => ({
          name: sanitizeOpenCadLibraryPath(file.path),
          code: String(file.content || ''),
          kind: 'library',
        }))
        .filter(file => file.name);
    })
    .finally(() => {
      openCadLibrarySymbolsLoading = false;
      openCadLibrarySymbolsPromise = null;
    });
  return openCadLibrarySymbolsPromise;
}

function resetOpenCadLibrarySymbolIndex() {
  openCadLibraryFilesPromise = null;
  openCadLibrarySymbolFiles = [];
  openCadLibrarySymbolsPromise = null;
  openCadLibrarySymbolsLoading = false;
}

function getOpenCadLibraryCompletionPaths() {
  const paths = openCadLibrarySymbolFiles.map(file => file.name).filter(Boolean);
  if (paths.length) return paths;
  return [
    'MCAD/gears.scad',
    'MCAD/boxes.scad',
    'MCAD/constants.scad',
    'MCAD/bearing.scad',
    'MCAD/stepper.scad',
    'MCAD/servos.scad',
    'MCAD/nuts_and_bolts.scad',
  ];
}

function clearOpenCadEditorMarkers() {
  if (!window.monaco?.editor) return;
  for (const model of openCadEditorModels.values()) {
    window.monaco.editor.setModelMarkers(model, openCadMonacoMarkersOwner, []);
  }
}

function setOpenCadEditorMarkers(message) {
  if (!window.monaco?.editor) return;
  clearOpenCadEditorMarkers();
  const parsed = parseOpenCadErrorLocation(message);
  const file = parsed.file ? openCadFiles.find(item => `/${item.name}` === parsed.file || item.name === parsed.file.replace(/^\//, '')) : getActiveOpenCadFile();
  const targetFile = file || getActiveOpenCadFile();
  const model = getOpenCadModelForFile(targetFile);
  if (!model) return;
  const lineNumber = Math.max(1, Math.min(parsed.line || 1, model.getLineCount()));
  const maxColumn = model.getLineMaxColumn(lineNumber);
  window.monaco.editor.setModelMarkers(model, openCadMonacoMarkersOwner, [{
    severity: window.monaco.MarkerSeverity.Error,
    message: String(message || 'OpenSCAD 渲染失败'),
    startLineNumber: lineNumber,
    endLineNumber: lineNumber,
    startColumn: 1,
    endColumn: maxColumn,
  }]);
}

function parseOpenCadErrorLocation(message) {
  const text = String(message || '');
  const match = text.match(/file\s+([^,\n]+),\s*line\s+(\d+)/i) || text.match(/([^:\s]+\.scad):(\d+)/i);
  if (!match) return { file: '', line: 1 };
  return {
    file: match[1],
    line: Number(match[2]) || 1,
  };
}

function handleOpenCadCodeInput() {
  const file = getActiveOpenCadFile();
  if (!file) return;
  file.code = getOpenCadEditorValue();
  renderOpenCadFileTabs();
  scheduleOpenCadGuiRefresh();
  refreshOpenCadDiffIfOpen();
  scheduleOpenCadEditorSave();
  markOpenCadCodeDirty();
}

function scheduleOpenCadGuiRefresh() {
  clearTimeout(openCadGuiRefreshTimer);
  openCadGuiRefreshTimer = setTimeout(renderOpenCadGuiPanel, 180);
}

function loadOpenCadAutoRenderPreference() {
  openCadAutoRender = localStorage.getItem(OPENSCAD_AUTO_RENDER_STORAGE_KEY) === '1';
}

function toggleOpenCadAutoRender(enabled) {
  openCadAutoRender = Boolean(enabled);
  localStorage.setItem(OPENSCAD_AUTO_RENDER_STORAGE_KEY, openCadAutoRender ? '1' : '0');
  renderOpenCadAutoRenderState();
  clearTimeout(openCadRenderTimer);
  if (openCadAutoRender) {
    setOpenCadStatus('自动渲染已开启，修改代码后会自动更新 3D 预览');
    if (openCadHasUnrenderedChanges) {
      openCadRenderTimer = setTimeout(() => renderOpenCad({ preserveCamera: true }), 250);
    }
  } else {
    setOpenCadStatus(openCadHasUnrenderedChanges
      ? '自动渲染已关闭，有未渲染修改，点击“渲染”更新 3D 预览'
      : '自动渲染已关闭');
  }
}

function renderOpenCadAutoRenderState() {
  const toggle = document.getElementById('openCadAutoRenderToggle');
  if (toggle) toggle.checked = Boolean(openCadAutoRender);
}

function markOpenCadCodeDirty() {
  clearTimeout(openCadRenderTimer);
  if (openCadAutoRender) {
    openCadHasUnrenderedChanges = true;
    setOpenCadStatus('自动渲染已开启，等待输入停止后更新 3D 预览...');
    openCadRenderTimer = setTimeout(() => renderOpenCad({ preserveCamera: true }), 900);
    return;
  }
  if (openCadHasUnrenderedChanges) return;
  openCadHasUnrenderedChanges = true;
  setOpenCadStatus('有未渲染修改，点击“渲染”更新 3D 预览');
}

function scheduleOpenCadEditorSave() {
  clearTimeout(openCadEditorSaveTimer);
  openCadEditorSaveTimer = setTimeout(() => {
    const file = getActiveOpenCadFile();
    if (file) localStorage.setItem('openharness.opencad.code', file.code || '');
    saveOpenCadFiles();
  }, 1200);
}

function installOpenCadEditorShortcuts() {
  if (openCadEditorShortcutsInstalled) return;
  if (openCadEditor) {
    openCadEditorShortcutsInstalled = true;
    return;
  }
  const textarea = document.getElementById('openCadCode');
  if (!textarea) return;
  textarea.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    event.preventDefault();
    handleOpenCadEditorTab(textarea, event.shiftKey);
    handleOpenCadCodeInput();
  });
  openCadEditorShortcutsInstalled = true;
}

function handleOpenCadEditorTab(textarea, outdent = false) {
  const value = textarea.value;
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
  if (start !== end || value.slice(start, end).includes('\n')) {
    const before = value.slice(0, lineStart);
    const selected = value.slice(lineStart, end);
    const lines = selected.split('\n');
    const nextLines = lines.map(line => {
      if (!outdent) return line ? `  ${line}` : line;
      if (line.startsWith('  ')) return line.slice(2);
      if (line.startsWith('\t')) return line.slice(1);
      return line;
    });
    const nextSelected = nextLines.join('\n');
    textarea.value = before + nextSelected + value.slice(end);
    textarea.selectionStart = lineStart;
    textarea.selectionEnd = lineStart + nextSelected.length;
    return;
  }
  if (outdent) {
    const prefix = value.slice(lineStart, start);
    if (prefix.endsWith('  ')) {
      textarea.value = value.slice(0, start - 2) + value.slice(start);
      textarea.selectionStart = textarea.selectionEnd = start - 2;
    }
    return;
  }
  textarea.value = value.slice(0, start) + '  ' + value.slice(end);
  textarea.selectionStart = textarea.selectionEnd = start + 2;
}

function renderOpenCadFileTabs() {
  const container = document.getElementById('openCadFileTabs');
  if (!container) return;
  container.innerHTML = openCadFiles.map(file => {
    const dirty = isOpenCadFileDirty(file);
    return `
    <button type="button" onclick="switchOpenCadFile('${file.id}')" class="open-cad-file-tab ${file.id === openCadActiveFileId ? 'active' : ''}" title="${openCadEscapeHtml(file.name)}">
      <span class="w-1.5 h-1.5 rounded-full ${file.id === openCadActiveFileId ? 'bg-accent-green' : 'bg-text-muted'} shrink-0"></span>
      <span class="open-cad-file-tab-name">${openCadEscapeHtml(file.name)}</span>
      ${dirty ? '<span class="open-cad-file-dirty" title="有未保存到服务端的改动">•</span>' : ''}
    </button>
  `;
  }).join('');
  const panel = document.getElementById('openCadFilePanel');
  const collapsed = document.getElementById('openCadFilePanelCollapsed');
  if (panel && collapsed) {
    panel.classList.toggle('hidden', openCadFilePanelCollapsed);
    collapsed.classList.toggle('hidden', !openCadFilePanelCollapsed);
  }
}

function switchOpenCadFile(fileId) {
  const current = getActiveOpenCadFile();
  if (current) current.code = getOpenCadEditorValue();
  if (!openCadFiles.some(file => file.id === fileId)) return;
  openCadActiveFileId = fileId;
  const next = getActiveOpenCadFile();
  setOpenCadEditorFile(next);
  saveOpenCadFiles();
  renderOpenCadFileTabs();
  renderOpenCadGuiPanel();
  renderOpenCad();
}

function addOpenCadFile() {
  const name = sanitizeOpenCadFileName(prompt('新文件名', `part-${openCadFiles.length + 1}.scad`) || '');
  if (!name) return;
  const existingNames = new Set(openCadFiles.map(file => file.name));
  let finalName = name;
  let counter = 1;
  while (existingNames.has(finalName)) {
    finalName = name.replace(/\.scad$/i, `-${counter}.scad`);
    counter += 1;
  }
  const file = { id: makeOpenCadFileId(), name: finalName, code: '$fn = 48;\n\n', savedCode: '' };
  openCadFiles.push(file);
  switchOpenCadFile(file.id);
}

function renderOpenCadGuiPanel() {
  const tree = document.getElementById('openCadGuiTree');
  const modules = document.getElementById('openCadGuiModules');
  const moduleSelect = document.getElementById('openCadGuiModuleSelect');
  const objectSelect = document.getElementById('openCadGuiObjectSelect');
  if (!tree && !modules && !moduleSelect && !objectSelect) return;
  const code = getOpenCadEditorValue();
  if (tree) tree.innerHTML = renderOpenCadGuiTreeHtml(code);
  if (modules) modules.innerHTML = renderOpenCadGuiModulesHtml();
  if (moduleSelect) renderOpenCadGuiModuleSelect(moduleSelect);
  if (objectSelect) renderOpenCadGuiObjectSelect(objectSelect, code);
  renderOpenCadGuiAxisState();
  renderOpenCadGuiToolState();
  if (!openCadLibrarySymbolFiles.length && !openCadLibrarySymbolsLoading) {
    ensureOpenCadLibrarySymbolsLoaded().then(renderOpenCadGuiPanel).catch(error => {
      console.warn('Failed to refresh OpenCAD GUI module index:', error);
    });
  }
}

function renderOpenCadGuiObjectSelect(container, code = getOpenCadEditorValue()) {
  const objects = getOpenCadGuiObjects(code);
  if (!objects.some(object => object.id === openCadSelectedGuiObjectId)) {
    openCadSelectedGuiObjectId = objects[0]?.id || '';
  }
  const title = '<div class="open-cad-object-rail-title">对象</div>';
  if (!objects.length) {
    container.innerHTML = `${title}<span class="open-cad-gui-empty">暂无可选对象</span>`;
    return;
  }
  container.innerHTML = title + objects.map(object => `
    <label class="open-cad-gui-object-option ${object.id === openCadSelectedGuiObjectId ? 'active' : ''}" title="${openCadEscapeHtml(object.id)}">
      <input type="radio" name="openCadGuiObject" value="${openCadEscapeHtml(object.id)}" ${object.id === openCadSelectedGuiObjectId ? 'checked' : ''} onchange="selectOpenCadGuiObject('${openCadEscapeHtml(object.id)}')">
      <span>${openCadEscapeHtml(object.label)}</span>
    </label>
  `).join('');
}

function setOpenCadGuiTransformAxis(axis) {
  openCadGuiTransformAxis = ['x', 'y', 'z'].includes(axis) ? axis : 'free';
  renderOpenCadGuiAxisState();
  setOpenCadStatus(`变换轴：${getOpenCadGuiAxisLabel()}`);
}

function renderOpenCadGuiAxisState() {
  const entries = [
    ['free', 'openCadAxisFree'],
    ['x', 'openCadAxisX'],
    ['y', 'openCadAxisY'],
    ['z', 'openCadAxisZ'],
  ];
  for (const [axis, id] of entries) {
    document.getElementById(id)?.classList.toggle('active', openCadGuiTransformAxis === axis);
  }
}

function getOpenCadGuiAxisLabel() {
  return openCadGuiTransformAxis === 'free' ? '自由' : openCadGuiTransformAxis.toUpperCase();
}

function renderOpenCadGuiToolState() {
  const entries = [
    ['translate', 'openCadToolTranslate'],
    ['rotate', 'openCadToolRotate'],
    ['scale', 'openCadToolScale'],
  ];
  for (const [tool, id] of entries) {
    document.getElementById(id)?.classList.toggle('active', openCadGuiMouseTool === tool);
  }
}

function clearOpenCadGuiMouseTool() {
  openCadGuiMouseTool = '';
  openCadGuiInteractionBusy = false;
  renderOpenCadGuiToolState();
}

function debugOpenCadGui(message, details = null) {
  const stamp = new Date().toLocaleTimeString();
  let line = `[${stamp}] ${String(message || '')}`;
  if (details !== null && details !== undefined) {
    try {
      line += ` ${typeof details === 'string' ? details : JSON.stringify(details)}`;
    } catch (error) {
      line += ` ${String(details)}`;
    }
  }
  openCadGuiDebugLines.push(line);
  openCadGuiDebugLines = openCadGuiDebugLines.slice(-8);
  console.debug('[OpenCAD GUI]', message, details || '');
  renderOpenCadGuiDebug();
}

function toggleOpenCadGuiDebug() {
  openCadGuiDebugExpanded = !openCadGuiDebugExpanded;
  renderOpenCadGuiDebug();
}

function renderOpenCadGuiDebug() {
  const shell = document.getElementById('openCadGuiDebugShell');
  const el = document.getElementById('openCadGuiDebug');
  const toggle = document.getElementById('openCadGuiDebugToggle');
  if (shell) shell.classList.toggle('hidden', !openCadGuiDebugLines.length);
  if (toggle) {
    toggle.classList.toggle('active', openCadGuiDebugExpanded);
    toggle.textContent = openCadGuiDebugExpanded
      ? 'Debug 收起'
      : `Debug ${openCadGuiDebugLines.length || ''}`.trim();
  }
  if (!el) return;
  el.classList.toggle('hidden', !openCadGuiDebugExpanded);
  el.textContent = openCadGuiDebugLines.join('\n');
}

function selectOpenCadGuiObject(objectId) {
  openCadSelectedGuiObjectId = String(objectId || '');
  renderOpenCadGuiPanel();
  debugOpenCadGui('select object', { objectId: openCadSelectedGuiObjectId });
  setOpenCadStatus(openCadSelectedGuiObjectId ? `已选择对象 ${openCadSelectedGuiObjectId}` : '未选择对象');
}

function getOpenCadGuiObjects(code = getOpenCadEditorValue()) {
  const objects = [];
  const text = String(code || '');
  const regex = /^\s*\/\/\s*@(cad|oh):id=([A-Za-z0-9_:-]+)([^\n]*)/gm;
  let match;
  while ((match = regex.exec(text))) {
    const namespace = match[1];
    const id = match[2];
    const meta = match[3] || '';
    const type = (meta.match(/\btype=([^\s]+)/) || [])[1] || 'object';
    objects.push({
      id,
      namespace,
      type,
      label: `${type}:${id.replace(/^[A-Za-z]+_/, '').slice(0, 10)}`,
      anchorStart: match.index,
      bodyStart: regex.lastIndex,
    });
  }
  return objects;
}

function renderOpenCadGuiTreeHtml(code) {
  try {
    const nodes = parseOpenScadForGui(code);
    if (!nodes.length) return '<div class="open-cad-gui-empty">当前文件暂无可视化对象</div>';
    return nodes.map(node => renderOpenCadGuiNodeHtml(node, 0)).join('');
  } catch (error) {
    return `<div class="open-cad-gui-empty">对象树解析失败：${openCadEscapeHtml(error.message || String(error))}</div>`;
  }
}

function parseOpenScadForGui(code) {
  const guiCode = stripOpenCadTopLevelDefinitions(stripOpenCadReferences(code || ''));
  return parseOpenScad(guiCode);
}

function stripOpenCadReferences(code) {
  return String(code || '').replace(/^\s*(?:use|include)\s*[<"][^>"]+[>"]\s*;?\s*$/gm, '');
}

function stripOpenCadTopLevelDefinitions(code) {
  const lines = String(code || '').split('\n');
  const kept = [];
  let skipping = false;
  let depth = 0;
  for (const line of lines) {
    if (!skipping && /^\s*(?:module|function)\s+[A-Za-z_]\w*\s*\(/.test(line)) {
      skipping = true;
      depth = updateOpenCadBraceDepth(0, line);
      if (depth === 0 && /;\s*$/.test(line)) skipping = false;
      continue;
    }
    if (skipping) {
      depth = updateOpenCadBraceDepth(depth, line);
      if (depth === 0) skipping = false;
      continue;
    }
    kept.push(line);
  }
  return kept.join('\n');
}

function renderOpenCadGuiNodeHtml(node, depth = 0) {
  const name = String(node?.name || 'node');
  const args = summarizeOpenCadGuiArgs(node);
  const pad = Math.min(depth, 6) * 12;
  const children = (node.children || []).map(child => renderOpenCadGuiNodeHtml(child, depth + 1)).join('');
  return `
    <div class="open-cad-gui-node" style="margin-left:${pad}px" title="${openCadEscapeHtml(args)}">
      <span class="text-text-primary">${openCadEscapeHtml(name)}</span>${args ? ` <span>${openCadEscapeHtml(args)}</span>` : ''}
    </div>
    ${children}
  `;
}

function summarizeOpenCadGuiArgs(node) {
  const args = (node?.args || []).slice(0, 3).map(arg => {
    const value = formatOpenCadGuiValue(arg.value);
    return arg.name ? `${arg.name}=${value}` : value;
  });
  const suffix = (node?.args || []).length > 3 ? ', ...' : '';
  return args.length ? `(${args.join(', ')}${suffix})` : '';
}

function formatOpenCadGuiValue(value) {
  if (Array.isArray(value)) return `[${value.map(formatOpenCadGuiValue).join(', ')}]`;
  if (typeof value === 'string') return value.length > 18 ? `${value.slice(0, 18)}...` : value;
  return String(value);
}

function renderOpenCadGuiModulesHtml() {
  const modules = getOpenCadGuiModules().slice(0, 24);
  if (!modules.length) return '<div class="open-cad-gui-empty">未发现 workspace module</div>';
  return modules.map(symbol => `
    <div class="open-cad-gui-module" title="${openCadEscapeHtml(symbol.label)}">
      <div class="text-text-primary">${openCadEscapeHtml(symbol.name)}</div>
      <div>${openCadEscapeHtml(symbol.source || 'workspace')}</div>
    </div>
  `).join('');
}

function renderOpenCadGuiModuleSelect(select) {
  const modules = getOpenCadGuiModules();
  const previous = select.value;
  select.innerHTML = modules.length
    ? modules.map((symbol, index) => `<option value="${index}">${openCadEscapeHtml(symbol.name)} · ${openCadEscapeHtml(symbol.source || 'workspace')}</option>`).join('')
    : '<option value="">暂无 module</option>';
  if (previous && [...select.options].some(option => option.value === previous)) select.value = previous;
}

function getOpenCadGuiModules() {
  const index = getOpenCadSymbolIndex();
  const active = getActiveOpenCadFile();
  const referenced = getOpenCadReferencedModuleSources(getOpenCadEditorValue());
  return index.callables
    .filter(symbol => symbol.kind === 'module')
    .filter(symbol => {
      if (symbol.source === active?.name) return true;
      if (symbol.sourceKind === 'workspace') return true;
      return referenced.has(symbol.source);
    });
}

function getOpenCadReferencedModuleSources(code) {
  const sources = new Set();
  const regex = /^\s*(?:use|include)\s*[<"]([^>"]+)[>"]\s*;?\s*$/gm;
  let match;
  while ((match = regex.exec(String(code || '')))) {
    const source = sanitizeOpenCadLibraryPath(match[1]);
    if (source) sources.add(source);
  }
  return sources;
}

function insertOpenCadGuiPrimitive(kind) {
  const body = buildOpenCadGuiPrimitiveSnippet(kind);
  if (!body) return;
  const nodeId = makeOpenCadGuiNodeId(kind);
  openCadSelectedGuiObjectId = nodeId;
  insertOpenCadSnippetAtCursor(`\n// @cad:id=${nodeId} type=${kind}\n${body}\n`);
}

function insertOpenCadGuiBoolean(kind) {
  const body = OPENSCAD_GUI_BOOLEAN_SNIPPETS[kind];
  if (!body) return;
  const nodeId = makeOpenCadGuiNodeId(kind);
  openCadSelectedGuiObjectId = nodeId;
  insertOpenCadSnippetAtCursor(`\n// @cad:id=${nodeId} type=${kind}\n${body.replace(/\\n/g, '\n')}\n`);
}

function insertOpenCadGuiTransform(kind) {
  const defaults = kind === 'scale' ? [1, 1, 1] : [0, 0, 0];
  debugOpenCadGui('transform button', {
    kind,
    selected: openCadSelectedGuiObjectId || '(none)',
    axis: openCadGuiTransformAxis,
  });
  if (['translate', 'rotate', 'scale'].includes(kind) && openCadSelectedGuiObjectId) {
    openCadGuiMouseTool = kind;
    renderOpenCadGuiToolState();
    const label = kind === 'translate' ? '平移' : kind === 'rotate' ? '旋转' : '缩放';
    showOpenCadGuiInteractionObject(openCadSelectedGuiObjectId, label);
    return;
  }
  const value = promptOpenCadGuiVector(`${kind} 参数`, defaults);
  if (!value) return;
  if (openCadSelectedGuiObjectId && applyOpenCadGuiTransformToSelected(kind, value)) return;
  const child = kind === 'scale' ? 'cube([20, 20, 20], center=true);' : '// child\ncube([20, 20, 20], center=true);';
  const nodeId = makeOpenCadGuiNodeId(kind);
  openCadSelectedGuiObjectId = nodeId;
  insertOpenCadSnippetAtCursor(`\n// @cad:id=${nodeId} type=${kind}\n${kind}(${value}) {\n  ${child.replace(/\n/g, '\n  ')}\n}\n`);
}

function insertSelectedOpenCadGuiModule() {
  const select = document.getElementById('openCadGuiModuleSelect');
  const modules = getOpenCadGuiModules();
  const symbol = modules[Number(select?.value)];
  if (!symbol) {
    alert('暂无可插入的 module');
    return;
  }
  const args = [];
  for (const param of symbol.parameters || []) {
    const defaultValue = getOpenCadGuiParamDefault(param.label);
    const value = prompt(`参数 ${symbol.name}.${param.name}`, defaultValue);
    if (value === null) return;
    if (String(value).trim()) args.push(`${param.name}=${String(value).trim()}`);
  }
  ensureOpenCadGuiUseStatement(symbol);
  const nodeId = makeOpenCadGuiNodeId(symbol.name);
  openCadSelectedGuiObjectId = nodeId;
  insertOpenCadSnippetAtCursor(`\n// @cad:id=${nodeId} type=module source=${symbol.source || 'current'}\ntranslate([0, 0, 0])\nrotate([0, 0, 0])\nscale([1, 1, 1])\n${symbol.name}(${args.join(', ')});\n`);
}

function applyOpenCadGuiTransformToSelected(kind, value, options = {}) {
  const file = getActiveOpenCadFile();
  const code = syncOpenCadEditorToActiveFile();
  const range = findOpenCadGuiObjectRange(code, openCadSelectedGuiObjectId);
  if (!file || !range) return false;
  const block = code.slice(range.start, range.end);
  const nextBlock = upsertOpenCadGuiTransform(block, kind, value);
  setOpenCadEditorValue(code.slice(0, range.start) + nextBlock + code.slice(range.end), file);
  handleOpenCadCodeInput();
  renderOpenCad({ preserveCamera: Boolean(options.preserveCamera) });
  setOpenCadStatus(`对象 ${openCadSelectedGuiObjectId} 已更新 ${kind}()`);
  return true;
}

function getOpenCadSelectedTransformValue(kind, delta) {
  const code = syncOpenCadEditorToActiveFile();
  const range = findOpenCadGuiObjectRange(code, openCadSelectedGuiObjectId);
  if (!range) return '';
  const block = code.slice(range.start, range.end);
  const current = readOpenCadGuiTransformVector(block, kind, kind === 'scale' ? [1, 1, 1] : [0, 0, 0]);
  if (kind === 'translate') {
    return `[${[
      current[0] + delta.x,
      current[1] + delta.y,
      current[2] + delta.z,
    ].map(formatOpenCadNumber).join(', ')}]`;
  }
  if (kind === 'rotate' && Array.isArray(delta)) {
    return `[${[
      current[0] + delta[0],
      current[1] + delta[1],
      current[2] + delta[2],
    ].map(formatOpenCadNumber).join(', ')}]`;
  }
  if (kind === 'scale' && Array.isArray(delta)) {
    return `[${[
      current[0] * delta[0],
      current[1] * delta[1],
      current[2] * delta[2],
    ].map(formatOpenCadNumber).join(', ')}]`;
  }
  return `[${current.map(formatOpenCadNumber).join(', ')}]`;
}

function readOpenCadGuiTransformVector(block, kind, fallback) {
  const escaped = escapeOpenCadRegex(kind);
  const match = String(block || '').match(new RegExp(`^\\s*${escaped}\\s*\\(\\s*\\[([^\\]]+)\\]`, 'm'));
  if (!match) return fallback;
  const values = match[1].split(',').map(value => Number(value.trim()));
  if (values.length < 3 || values.some(value => !Number.isFinite(value))) return fallback;
  return [values[0], values[1], values[2]];
}

function findOpenCadGuiObjectRange(code, objectId) {
  const text = String(code || '');
  const escaped = escapeOpenCadRegex(objectId);
  const anchorRegex = new RegExp(`^\\s*//\\s*@(cad|oh):id=${escaped}[^\\n]*`, 'm');
  const match = anchorRegex.exec(text);
  if (!match) return null;
  const nextAnchor = /^\s*\/\/\s*@(cad|oh):id=/gm;
  nextAnchor.lastIndex = match.index + match[0].length;
  const next = nextAnchor.exec(text);
  return { start: match.index, end: next ? next.index : text.length };
}

function upsertOpenCadGuiTransform(block, kind, value) {
  const lines = String(block || '').replace(/\s+$/g, '').split('\n');
  const transformRegex = new RegExp(`^(\\s*)${escapeOpenCadRegex(kind)}\\s*\\([^\\n]*\\)\\s*(?:;)?\\s*$`);
  const replacement = `${kind}(${value})`;
  for (let index = 1; index < lines.length; index += 1) {
    if (transformRegex.test(lines[index])) {
      lines[index] = lines[index].replace(transformRegex, `$1${replacement}`);
      return lines.join('\n') + '\n';
    }
  }
  const insertAt = Math.min(1, lines.length);
  lines.splice(insertAt, 0, replacement);
  return lines.join('\n') + '\n';
}

function buildOpenCadGuiPrimitiveSnippet(kind) {
  if (kind === 'cube') {
    const size = promptOpenCadGuiVector('立方体尺寸 [x, y, z]', [20, 20, 20]);
    if (!size) return '';
    return `translate([0, 0, 0])\nrotate([0, 0, 0])\ncube(${size}, center=true);`;
  }
  if (kind === 'cylinder') {
    const height = prompt('圆柱体高度 h', '30');
    if (height === null) return '';
    const radius = prompt('圆柱体半径 r', '10');
    if (radius === null) return '';
    return `translate([0, 0, 0])\nrotate([0, 0, 0])\ncylinder(h=${height || 30}, r=${radius || 10}, center=true);`;
  }
  if (kind === 'sphere') {
    const radius = prompt('球体半径 r', '12');
    if (radius === null) return '';
    return `translate([0, 0, 0])\nrotate([0, 0, 0])\nsphere(r=${radius || 12});`;
  }
  return (OPENSCAD_GUI_PRIMITIVE_SNIPPETS[kind] || '').replace(/\\n/g, '\n');
}

function promptOpenCadGuiVector(title, defaults) {
  const value = prompt(title, `[${defaults.join(', ')}]`);
  if (value === null) return '';
  const trimmed = String(value).trim();
  if (!trimmed) return `[${defaults.join(', ')}]`;
  return trimmed.startsWith('[') ? trimmed : `[${trimmed}]`;
}

function getOpenCadGuiParamDefault(label) {
  const equalsIndex = findOpenCadTopLevelChar(label || '', '=');
  if (equalsIndex < 0) return '';
  return String(label).slice(equalsIndex + 1).trim();
}

function ensureOpenCadGuiUseStatement(symbol) {
  const active = getActiveOpenCadFile();
  const source = sanitizeOpenCadLibraryPath(symbol?.source || '');
  if (!active || !source || source === active.name) return;
  const current = getOpenCadEditorValue();
  const escaped = escapeOpenCadRegex(source);
  const hasReference = new RegExp(`^\\s*(?:use|include)\\s*[<"]${escaped}[>"]`, 'm').test(current);
  if (hasReference) return;
  setOpenCadEditorValue(`use <${source}>;\n${current}`, active);
  handleOpenCadCodeInput();
}

function makeOpenCadGuiNodeId(prefix = 'node') {
  return `${String(prefix || 'node').replace(/[^A-Za-z0-9_]/g, '_')}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function insertOpenCadSnippetAtCursor(text) {
  const snippet = String(text || '');
  const file = getActiveOpenCadFile();
  if (!file) return;
  if (openCadEditor) {
    const selection = openCadEditor.getSelection();
    openCadEditor.executeEdits('opencad-gui', [{ range: selection, text: snippet, forceMoveMarkers: true }]);
    openCadEditor.focus();
    finishOpenCadGuiInsertion();
    return;
  }
  const fallback = document.getElementById('openCadCode');
  if (!fallback) return;
  const start = fallback.selectionStart ?? fallback.value.length;
  const end = fallback.selectionEnd ?? start;
  fallback.value = fallback.value.slice(0, start) + snippet + fallback.value.slice(end);
  fallback.selectionStart = fallback.selectionEnd = start + snippet.length;
  handleOpenCadCodeInput();
  finishOpenCadGuiInsertion();
}

function finishOpenCadGuiInsertion() {
  setTimeout(() => {
    syncOpenCadEditorToActiveFile();
    renderOpenCadGuiPanel();
    saveOpenCadFiles();
    renderOpenCad({ preserveCamera: true });
  }, 0);
}

function renameOpenCadFile() {
  const file = getActiveOpenCadFile();
  if (!file) return;
  const name = sanitizeOpenCadFileName(prompt('重命名文件', file.name) || '');
  if (!name) return;
  if (openCadFiles.some(item => item.id !== file.id && item.name === name)) {
    alert('文件名已存在');
    return;
  }
  file.name = name;
  refreshOpenCadEditorModel(file);
  saveOpenCadFiles();
  renderOpenCadFileTabs();
}

function deleteOpenCadFile() {
  if (openCadFiles.length <= 1) {
    alert('至少保留一个 OpenSCAD 文件');
    return;
  }
  const file = getActiveOpenCadFile();
  if (!file || !confirm(`删除 ${file.name}?`)) return;
  openCadFiles = openCadFiles.filter(item => item.id !== file.id);
  disposeOpenCadEditorModel(file.id);
  openCadActiveFileId = openCadFiles[0].id;
  setOpenCadEditorFile(openCadFiles[0]);
  saveOpenCadFiles();
  renderOpenCadFileTabs();
  renderOpenCad();
}

function toggleOpenCadFilePanel() {
  openCadFilePanelCollapsed = !openCadFilePanelCollapsed;
  renderOpenCadFileTabs();
  setTimeout(resizeOpenCadViewport, 0);
}

function installOpenCadControls(viewport) {
  viewport.addEventListener('pointerdown', (event) => {
    openCadControls.lastX = event.clientX;
    openCadControls.lastY = event.clientY;
    if (openCadGuiMouseTool && openCadSelectedGuiObjectId) {
      if (openCadGuiInteractionBusy || !openCadInteractionRoot) {
        setOpenCadStatus(openCadGuiInteractionBusy ? '交互预览生成中，请稍等...' : '交互预览尚未就绪，请重新点击变换工具');
        return;
      }
      if (startOpenCadGuiTransformDrag(event)) {
        viewport.setPointerCapture(event.pointerId);
        return;
      }
    }
    const hit = getOpenCadModelHit(event);
    if (hit && openCadModelRoot) {
      const dragObject = findOpenCadDraggableObject(hit.object);
      openCadControls.mode = 'move-model';
      openCadControls.dragObject = dragObject || openCadModelRoot;
      openCadControls.dragSourceIndex = Number.isInteger(openCadControls.dragObject.userData.openCadSourceIndex)
        ? openCadControls.dragObject.userData.openCadSourceIndex
        : null;
      openCadControls.dragStartObjectPosition = openCadControls.dragObject.position.clone();
      openCadControls.dragStartRootPosition = openCadModelRoot.position.clone();
      const normal = openCadCamera.position.clone().sub(hit.point).normalize();
      openCadControls.dragPlane.setFromNormalAndCoplanarPoint(normal, hit.point);
      openCadControls.dragOffset.copy(openCadControls.dragObject.position).sub(hit.point);
      setOpenCadStatus(openCadControls.dragSourceIndex === null ? '拖动整体模型' : `拖动对象 #${openCadControls.dragSourceIndex + 1}`);
    } else {
      openCadControls.mode = 'orbit';
      openCadControls.dragStartRootPosition = null;
      openCadControls.dragObject = null;
      openCadControls.dragStartObjectPosition = null;
      openCadControls.dragSourceIndex = null;
    }
    viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener('pointerup', (event) => {
    if (openCadControls.mode === 'move-model') {
      commitOpenCadModelDrag();
    } else if (openCadControls.mode.startsWith('gui-')) {
      commitOpenCadGuiTransformDrag();
    }
    openCadControls.mode = '';
    openCadControls.dragStartRootPosition = null;
    openCadControls.dragObject = null;
    openCadControls.dragStartObjectPosition = null;
    openCadControls.dragSourceIndex = null;
    openCadControls.guiDragStartPoint = null;
    openCadControls.guiDragCurrentPoint = null;
    openCadControls.guiDragObject = null;
    openCadControls.guiDragObjectStartPosition = null;
    openCadControls.guiDragObjectStartRotation = null;
    openCadControls.guiDragObjectStartScale = null;
    if (viewport.hasPointerCapture(event.pointerId)) {
      viewport.releasePointerCapture(event.pointerId);
    }
  });
  viewport.addEventListener('pointercancel', () => {
    openCadControls.mode = '';
    openCadControls.dragStartRootPosition = null;
    openCadControls.dragObject = null;
    openCadControls.dragStartObjectPosition = null;
    openCadControls.dragSourceIndex = null;
    openCadControls.guiDragStartPoint = null;
    openCadControls.guiDragCurrentPoint = null;
    openCadControls.guiDragObject = null;
    openCadControls.guiDragObjectStartPosition = null;
    openCadControls.guiDragObjectStartRotation = null;
    openCadControls.guiDragObjectStartScale = null;
    clearOpenCadGuiMouseTool();
    clearOpenCadInteractionLayer();
  });
  viewport.addEventListener('pointermove', (event) => {
    if (!openCadControls.mode) return;
    const dx = event.clientX - openCadControls.lastX;
    const dy = event.clientY - openCadControls.lastY;
    openCadControls.lastX = event.clientX;
    openCadControls.lastY = event.clientY;
    if (openCadControls.mode === 'move-model') {
      moveOpenCadModelToPointer(event);
    } else if (openCadControls.mode.startsWith('gui-')) {
      moveOpenCadGuiTransformToPointer(event);
    } else {
      openCadControls.theta -= dx * 0.008;
      openCadControls.phi = Math.max(0.15, Math.min(Math.PI - 0.15, openCadControls.phi + dy * 0.008));
      updateOpenCadCamera();
    }
  });
  viewport.addEventListener('wheel', (event) => {
    event.preventDefault();
    openCadControls.radius = Math.max(12, Math.min(1200, openCadControls.radius * (event.deltaY > 0 ? 1.08 : 0.92)));
    updateOpenCadCamera();
  }, { passive: false });
}

function getOpenCadModelHit(event) {
  if (!openCadModelRoot || !openCadCamera || !openCadControls.raycaster || !openCadControls.pointer) return null;
  const rect = openCadRenderer.domElement.getBoundingClientRect();
  openCadControls.pointer.x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * 2 - 1;
  openCadControls.pointer.y = -(((event.clientY - rect.top) / Math.max(1, rect.height)) * 2 - 1);
  openCadControls.raycaster.setFromCamera(openCadControls.pointer, openCadCamera);
  const hits = openCadControls.raycaster.intersectObject(openCadModelRoot, true)
    .filter(hit => hit.object?.isMesh && !hit.object.userData.previewSubtractor);
  return hits[0] || null;
}

function findOpenCadDraggableObject(object) {
  let current = object;
  let candidate = null;
  while (current && current !== openCadModelRoot) {
    if (Number.isInteger(current.userData.openCadSourceIndex)) candidate = current;
    current = current.parent;
  }
  return candidate;
}

function moveOpenCadModelToPointer(event) {
  const target = openCadControls.dragObject || openCadModelRoot;
  if (!target || !openCadCamera || !openCadControls.raycaster || !openCadControls.pointer) return;
  const rect = openCadRenderer.domElement.getBoundingClientRect();
  openCadControls.pointer.x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * 2 - 1;
  openCadControls.pointer.y = -(((event.clientY - rect.top) / Math.max(1, rect.height)) * 2 - 1);
  openCadControls.raycaster.setFromCamera(openCadControls.pointer, openCadCamera);
  const point = new THREE.Vector3();
  if (openCadControls.raycaster.ray.intersectPlane(openCadControls.dragPlane, point)) {
    target.position.copy(point.add(openCadControls.dragOffset));
  }
}

function startOpenCadGuiTransformDrag(event) {
  const object = findOpenCadGuiObject3d(openCadSelectedGuiObjectId);
  if (!object) {
    setOpenCadStatus('选中对象暂不支持鼠标操作', true);
    return false;
  }
  openCadControls.mode = `gui-${openCadGuiMouseTool}`;
  openCadControls.guiDragObject = object;
  openCadControls.guiDragObjectStartPosition = object?.position?.clone() || null;
  openCadControls.guiDragObjectStartRotation = object?.rotation?.clone() || null;
  openCadControls.guiDragObjectStartScale = object?.scale?.clone() || null;
  openCadControls.guiDragStartX = event.clientX;
  openCadControls.guiDragStartY = event.clientY;
  openCadControls.guiDragDeltaX = 0;
  openCadControls.guiDragDeltaY = 0;
  if (openCadGuiMouseTool === 'translate' && openCadGuiTransformAxis === 'free') {
    const point = getOpenCadPointerPlanePoint(event, getOpenCadGuiDragPlanePoint(event));
    if (!point) return false;
    openCadControls.guiDragStartPoint = point.clone();
    openCadControls.guiDragCurrentPoint = point.clone();
  }
  const label = openCadGuiMouseTool === 'translate' ? '平移' : openCadGuiMouseTool === 'rotate' ? '旋转' : '缩放';
  setOpenCadStatus(`拖动以${label}对象 ${openCadSelectedGuiObjectId} · ${getOpenCadGuiAxisLabel()}轴`);
  return true;
}

function moveOpenCadGuiTransformToPointer(event) {
  openCadControls.guiDragDeltaX = event.clientX - openCadControls.guiDragStartX;
  openCadControls.guiDragDeltaY = event.clientY - openCadControls.guiDragStartY;
  if (openCadControls.mode === 'gui-translate') {
    const delta = getOpenCadMouseTranslateDelta(event);
    if (openCadControls.guiDragObject && openCadControls.guiDragObjectStartPosition) {
      openCadControls.guiDragObject.position.copy(openCadControls.guiDragObjectStartPosition.clone().add(delta));
    }
    setOpenCadStatus(`平移预览：translate += [${[delta.x, delta.y, delta.z].map(formatOpenCadNumber).join(', ')}]`);
    return;
  }
  if (openCadControls.mode === 'gui-rotate') {
    const delta = getOpenCadMouseRotateDelta();
    if (openCadControls.guiDragObject && openCadControls.guiDragObjectStartRotation) {
      openCadControls.guiDragObject.rotation.set(
        openCadControls.guiDragObjectStartRotation.x + delta[0] * Math.PI / 180,
        openCadControls.guiDragObjectStartRotation.y + delta[1] * Math.PI / 180,
        openCadControls.guiDragObjectStartRotation.z + delta[2] * Math.PI / 180
      );
    }
    setOpenCadStatus(`旋转预览：rotate += [${delta.map(formatOpenCadNumber).join(', ')}]`);
    return;
  }
  if (openCadControls.mode === 'gui-scale') {
    const scale = getOpenCadMouseScaleVector();
    if (openCadControls.guiDragObject && openCadControls.guiDragObjectStartScale) {
      openCadControls.guiDragObject.scale.set(
        openCadControls.guiDragObjectStartScale.x * scale[0],
        openCadControls.guiDragObjectStartScale.y * scale[1],
        openCadControls.guiDragObjectStartScale.z * scale[2]
      );
    }
    setOpenCadStatus(`缩放预览：scale × [${scale.map(formatOpenCadNumber).join(', ')}]`);
  }
}

function commitOpenCadGuiTransformDrag() {
  if (!openCadSelectedGuiObjectId) return;
  const kind = openCadControls.mode.replace(/^gui-/, '');
  let nextValue = '';
  if (kind === 'translate') {
    const delta = getOpenCadMouseTranslateDelta();
    if (delta.length() < 0.001) {
      setOpenCadStatus(`已选择对象 ${openCadSelectedGuiObjectId}`);
      clearOpenCadInteractionLayer();
      clearOpenCadGuiMouseTool();
      return;
    }
    nextValue = getOpenCadSelectedTransformValue('translate', delta);
  } else if (kind === 'rotate') {
    const delta = getOpenCadMouseRotateDelta();
    if (Math.abs(delta[0]) + Math.abs(delta[1]) + Math.abs(delta[2]) < 0.1) {
      setOpenCadStatus(`已选择对象 ${openCadSelectedGuiObjectId}`);
      clearOpenCadInteractionLayer();
      clearOpenCadGuiMouseTool();
      return;
    }
    nextValue = getOpenCadSelectedTransformValue('rotate', delta);
  } else if (kind === 'scale') {
    const scale = getOpenCadMouseScaleVector();
    if (Math.abs(scale[0] - 1) + Math.abs(scale[1] - 1) + Math.abs(scale[2] - 1) < 0.002) {
      setOpenCadStatus(`已选择对象 ${openCadSelectedGuiObjectId}`);
      clearOpenCadInteractionLayer();
      clearOpenCadGuiMouseTool();
      return;
    }
    nextValue = getOpenCadSelectedTransformValue('scale', scale);
  }
  if (!nextValue || !applyOpenCadGuiTransformToSelected(kind, nextValue, { preserveCamera: true })) {
    setOpenCadStatus(`${kind} 失败：未找到可编辑的选中对象`, true);
    return;
  }
  clearOpenCadInteractionLayer();
  clearOpenCadGuiMouseTool();
}

function getOpenCadMouseRotateDelta() {
  const amount = openCadControls.guiDragDeltaX * 0.8;
  if (openCadGuiTransformAxis === 'x') return [amount, 0, 0];
  if (openCadGuiTransformAxis === 'y') return [0, amount, 0];
  if (openCadGuiTransformAxis === 'z') return [0, 0, amount];
  return [
    openCadControls.guiDragDeltaY * 0.8,
    0,
    openCadControls.guiDragDeltaX * 0.8,
  ];
}

function getOpenCadMouseTranslateDelta(event = null) {
  if (openCadGuiTransformAxis !== 'free') {
    return openCadAxisVector(openCadControls.guiDragDeltaX * 0.12);
  }
  if (event) {
    const point = getOpenCadPointerPlanePoint(event, openCadControls.guiDragStartPoint || getOpenCadGuiDragPlanePoint(event));
    if (point && openCadControls.guiDragStartPoint) {
      openCadControls.guiDragCurrentPoint = point.clone();
    }
  }
  if (!openCadControls.guiDragStartPoint || !openCadControls.guiDragCurrentPoint) return new THREE.Vector3(0, 0, 0);
  return openCadControls.guiDragCurrentPoint.clone().sub(openCadControls.guiDragStartPoint);
}

function getOpenCadMouseScaleFactor() {
  return Math.max(0.05, Math.min(20, Math.exp((-openCadControls.guiDragDeltaY + openCadControls.guiDragDeltaX * 0.35) * 0.01)));
}

function getOpenCadMouseScaleVector() {
  const factor = getOpenCadMouseScaleFactor();
  if (openCadGuiTransformAxis === 'x') return [factor, 1, 1];
  if (openCadGuiTransformAxis === 'y') return [1, factor, 1];
  if (openCadGuiTransformAxis === 'z') return [1, 1, factor];
  return [factor, factor, factor];
}

function openCadAxisVector(amount) {
  if (openCadGuiTransformAxis === 'x') return new THREE.Vector3(amount, 0, 0);
  if (openCadGuiTransformAxis === 'y') return new THREE.Vector3(0, amount, 0);
  if (openCadGuiTransformAxis === 'z') return new THREE.Vector3(0, 0, amount);
  return new THREE.Vector3(0, 0, 0);
}

function findOpenCadGuiObject3d(objectId) {
  const root = openCadInteractionRoot || openCadModelRoot;
  if (!root || !objectId) return null;
  let found = null;
  root.traverse(object => {
    if (!found && object.userData?.openCadGuiObjectId === objectId && object.parent === root) {
      found = object;
    }
  });
  if (found) return found;
  root.traverse(object => {
    if (!found && object.userData?.openCadGuiObjectId === objectId) found = object;
  });
  return found;
}

function showOpenCadGuiInteractionObject(objectId, label = '') {
  clearOpenCadInteractionLayer();
  const block = getOpenCadGuiObjectBlock(getOpenCadEditorValue(), objectId);
  debugOpenCadGui('interaction start', {
    objectId,
    tool: openCadGuiMouseTool || '(none)',
    blockChars: block.length,
    label,
  });
  if (!block) {
    debugOpenCadGui('interaction abort: block not found', { objectId });
    setOpenCadStatus('未找到可拖动的选中对象', true);
    return;
  }
  try {
    const ast = parseOpenScad(getOpenCadPreviewRenderableCode(block));
    debugOpenCadGui('frontend parse ok', { nodes: ast.length });
    openCadInteractionRoot = new THREE.Group();
    const warnings = [];
    ast.forEach(node => {
      const obj = buildOpenScadObject(node, null, warnings);
      if (!obj) return;
      tagOpenCadGuiObject(obj, objectId);
      makeOpenCadObjectPreviewMaterial(obj);
      openCadInteractionRoot.add(obj);
    });
    debugOpenCadGui('frontend objects built', {
      children: openCadInteractionRoot.children.length,
      warnings: warnings.length,
      hasMesh: hasOpenCadMesh(openCadInteractionRoot),
      warningText: warnings.slice(0, 3).join(' | '),
    });
    if (!openCadInteractionRoot.children.length || !hasOpenCadMesh(openCadInteractionRoot)) {
      clearOpenCadInteractionLayer();
      debugOpenCadGui('fallback to WASM preview', {
        reason: openCadInteractionRoot.children.length ? 'frontend object has no mesh' : 'no frontend objects',
        warnings: warnings.slice(0, 3),
      });
      renderOpenCadGuiInteractionObjectWithWasm(objectId, block, label);
      return;
    }
    openCadInteractionScene.add(openCadInteractionRoot);
    openCadGuiInteractionBusy = false;
    setOpenCadStatus(`已进入鼠标${label || '变换'}模式 · ${getOpenCadGuiAxisLabel()}轴：拖动预览区以调整 ${objectId}`);
  } catch (error) {
    clearOpenCadInteractionLayer();
    debugOpenCadGui('fallback to WASM preview', { reason: formatOpenCadError(error) });
    renderOpenCadGuiInteractionObjectWithWasm(objectId, block, label);
  }
}

async function renderOpenCadGuiInteractionObjectWithWasm(objectId, block, label = '') {
  try {
    openCadGuiInteractionBusy = true;
    setOpenCadStatus(`正在生成 ${objectId} 的交互预览，请稍等...`);
    const code = buildOpenCadGuiInteractionRenderCode(block);
    debugOpenCadGui('WASM preview start', {
      objectId,
      codeChars: code.length,
      head: code.split('\n').slice(0, 5).join(' | '),
    });
    const result = await renderOpenCadWithWasm(code, {
      interactionPreview: true,
      dedicatedWorker: true,
      activeFileName: '__openharness_interaction_preview.scad',
    });
    debugOpenCadGui('WASM preview result', {
      objectId,
      offBytes: result?.off?.byteLength || 0,
      stlBytes: result?.stl?.byteLength || 0,
    });
    if (objectId !== openCadSelectedGuiObjectId || !openCadGuiMouseTool) return;
    const object = result?.off?.byteLength
      ? buildOpenCadOffObject(result.off)
      : buildOpenCadStlObject(result?.stl || result);
    if (!object) throw new Error('OpenSCAD WASM 返回了空交互预览');
    tagOpenCadGuiObject(object, objectId);
    makeOpenCadObjectPreviewMaterial(object);
    clearOpenCadInteractionLayer();
    openCadInteractionRoot = new THREE.Group();
    openCadInteractionRoot.add(object);
    openCadInteractionScene.add(openCadInteractionRoot);
    openCadGuiInteractionBusy = false;
    setOpenCadStatus(`交互预览已生成。已进入鼠标${label || (openCadGuiMouseTool === 'translate' ? '平移' : openCadGuiMouseTool === 'rotate' ? '旋转' : '缩放')}模式 · ${getOpenCadGuiAxisLabel()}轴：现在可以拖动`);
  } catch (error) {
    openCadGuiInteractionBusy = false;
    clearOpenCadInteractionLayer();
    debugOpenCadGui('WASM preview failed', formatOpenCadError(error));
    setOpenCadStatus(`选中对象交互预览失败：${formatOpenCadError(error)}`, true);
  }
}

function buildOpenCadGuiInteractionRenderCode(block) {
  const source = (String(block || '').match(/\bsource=([^\s]+)/) || [])[1] || '';
  const refs = [];
  const activeFile = getActiveOpenCadFile();
  if (source === 'current' && activeFile?.name) {
    refs.push(`use <${sanitizeOpenCadFileName(activeFile.name)}>;`);
  } else if (source) {
    refs.push(`use <${source}>;`);
  }
  const currentCode = getOpenCadEditorValue();
  const existingRefs = currentCode.match(/^\s*(?:use|include)\s*[<"][^>"]+[>"]\s*;?\s*$/gm) || [];
  refs.push(...existingRefs);
  return `${[...new Set(refs)].join('\n')}\n\n${block}`;
}

function clearOpenCadInteractionLayer() {
  if (openCadInteractionRoot && openCadInteractionScene) openCadInteractionScene.remove(openCadInteractionRoot);
  openCadInteractionRoot = null;
  openCadGuiInteractionBusy = false;
  openCadControls.guiDragObject = null;
  openCadControls.guiDragObjectStartPosition = null;
}

function getOpenCadGuiObjectBlock(code, objectId) {
  const range = findOpenCadGuiObjectRange(String(code || ''), objectId);
  return range ? String(code || '').slice(range.start, range.end) : '';
}

function hasOpenCadMesh(object) {
  let found = false;
  object?.traverse?.(child => {
    if (child.isMesh) found = true;
  });
  return found;
}

function makeOpenCadObjectPreviewMaterial(object) {
  object.traverse(child => {
    if (!child.isMesh || !child.material) return;
    const source = Array.isArray(child.material) ? child.material : [child.material];
    const previewMaterials = source.map(material => {
      const next = material.clone();
      next.color = new THREE.Color(0x34d399);
      next.opacity = 0.48;
      next.transparent = true;
      next.depthTest = false;
      next.depthWrite = false;
      next.side = THREE.DoubleSide;
      next.metalness = 0.02;
      next.roughness = 0.45;
      return next;
    });
    child.material = Array.isArray(child.material) ? previewMaterials : previewMaterials[0];
    child.renderOrder = 1000;
  });
}


function getOpenCadPointerPlanePoint(event, planePoint) {
  if (!openCadCamera || !openCadControls.raycaster || !openCadControls.pointer || !planePoint) return null;
  const rect = openCadRenderer.domElement.getBoundingClientRect();
  openCadControls.pointer.x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * 2 - 1;
  openCadControls.pointer.y = -(((event.clientY - rect.top) / Math.max(1, rect.height)) * 2 - 1);
  openCadControls.raycaster.setFromCamera(openCadControls.pointer, openCadCamera);
  const normal = openCadCamera.position.clone().sub(planePoint).normalize();
  openCadControls.dragPlane.setFromNormalAndCoplanarPoint(normal, planePoint);
  const point = new THREE.Vector3();
  return openCadControls.raycaster.ray.intersectPlane(openCadControls.dragPlane, point) ? point : null;
}

function getOpenCadGuiDragPlanePoint(event) {
  const hit = getOpenCadModelHit(event);
  if (hit?.point) return hit.point.clone();
  if (openCadControls.target) return openCadControls.target.clone();
  return new THREE.Vector3(0, 0, 0);
}

function commitOpenCadModelDrag() {
  const target = openCadControls.dragObject || openCadModelRoot;
  const start = openCadControls.dragStartObjectPosition || openCadControls.dragStartRootPosition;
  if (!target || !start) return;
  const delta = target.position.clone().sub(start);
  if (delta.length() < 0.001) return;
  if (Number.isInteger(openCadControls.dragSourceIndex)) {
    const file = getActiveOpenCadFile();
    const currentCode = syncOpenCadEditorToActiveFile();
    const nextCode = applyOpenCadTranslateToCode(currentCode, delta, openCadControls.dragSourceIndex);
    setOpenCadEditorValue(nextCode, file);
    handleOpenCadCodeInput();
    renderOpenCad();
    setOpenCadStatus(`对象 #${openCadControls.dragSourceIndex + 1} 已移动并同步到 translate()`);
    return;
  }
  setOpenCadStatus(
    `${openCadControls.dragSourceIndex === null ? '整体模型' : `对象 #${openCadControls.dragSourceIndex + 1}`} 已临时移动；源码未自动改写`
  );
}

function applyOpenCadTranslateToCode(code, delta, sourceIndex = null) {
  if (Number.isInteger(sourceIndex)) {
    const parts = splitOpenCadTopLevelStatements(code);
    if (parts[sourceIndex]) {
      const part = parts[sourceIndex];
      const translated = applyOpenCadTranslateToStatement(part.text, delta);
      return code.slice(0, part.start) + translated + code.slice(part.end);
    }
  }
  return applyOpenCadTranslateToStatement(code, delta);
}

function applyOpenCadTranslateToStatement(code, delta) {
  const parsed = parseOpenCadDragTranslateWrapper(code);
  const offset = parsed
    ? [parsed.offset[0] + delta.x, parsed.offset[1] + delta.y, parsed.offset[2] + delta.z]
    : [delta.x, delta.y, delta.z];
  const body = parsed ? parsed.body : code.trim();
  const indentedBody = indentOpenCadCode(body || '// empty model');
  return `${OPENSCAD_DRAG_TRANSLATE_MARKER}\ntranslate([${offset.map(formatOpenCadNumber).join(', ')}]) {\n${indentedBody}\n}`;
}

function unwrapOpenCadDragTranslateWrapper(code) {
  const parsed = parseOpenCadDragTranslateWrapper(code);
  return parsed ? parsed.body : code;
}

function parseOpenCadDragTranslateWrapper(code) {
  const text = String(code || '').trim();
  if (!text.startsWith(OPENSCAD_DRAG_TRANSLATE_MARKER)) return null;
  const match = text.match(/^\/\/ OpenHarness transform: drag-offset\s*\ntranslate\s*\(\s*\[\s*([^\]]+)\s*\]\s*\)\s*\{\n([\s\S]*)\n\}\s*$/);
  if (!match) return null;
  const values = match[1].split(',').map(value => Number(value.trim()));
  if (values.length < 3 || values.some(value => !Number.isFinite(value))) return null;
  return {
    offset: [values[0], values[1], values[2]],
    body: unindentOpenCadCode(match[2]),
  };
}

function indentOpenCadCode(code) {
  return String(code || '')
    .trim()
    .split('\n')
    .map(line => line ? `  ${line}` : '')
    .join('\n');
}

function unindentOpenCadCode(code) {
  return String(code || '')
    .split('\n')
    .map(line => line.startsWith('  ') ? line.slice(2) : line)
    .join('\n')
    .trim();
}

function formatOpenCadNumber(value) {
  if (Math.abs(value) < 0.0005) return '0';
  return Number(value.toFixed(3)).toString();
}

function splitOpenCadTopLevelStatements(code) {
  const text = String(code || '');
  const parts = [];
  let start = 0;
  let depth = 0;
  let inString = false;
  let stringQuote = '';
  let inLineComment = false;
  let inBlockComment = false;

  const pushPart = (end) => {
    const raw = text.slice(start, end);
    const leading = raw.search(/\S/);
    if (leading !== -1) {
      const trailing = raw.search(/\s*$/);
      const cleanStart = start + leading;
      const cleanEnd = trailing === -1 ? end : start + trailing;
      if (cleanEnd > cleanStart) {
        parts.push({ start: cleanStart, end: cleanEnd, text: text.slice(cleanStart, cleanEnd) });
      }
    }
    start = end;
  };

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];

    if (inLineComment) {
      if (ch === '\n') inLineComment = false;
      continue;
    }
    if (inBlockComment) {
      if (ch === '*' && next === '/') {
        inBlockComment = false;
        i += 1;
      }
      continue;
    }
    if (inString) {
      if (ch === '\\') {
        i += 1;
      } else if (ch === stringQuote) {
        inString = false;
        stringQuote = '';
      }
      continue;
    }
    if (ch === '/' && next === '/') {
      inLineComment = true;
      i += 1;
      continue;
    }
    if (ch === '/' && next === '*') {
      inBlockComment = true;
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      inString = true;
      stringQuote = ch;
      continue;
    }
    if (ch === '{') {
      depth += 1;
      continue;
    }
    if (ch === '}') {
      depth = Math.max(0, depth - 1);
      if (depth === 0) pushPart(i + 1);
      continue;
    }
    if (ch === ';' && depth === 0) {
      pushPart(i + 1);
    }
  }
  pushPart(text.length);
  return parts;
}

function isOpenCadRenderableStatement(statement) {
  const text = String(statement || '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '')
    .trim();
  if (!text) return false;
  if (/^(?:module|function)\s+/.test(text)) return false;
  if (/^\$?[A-Za-z_]\w*\s*=/.test(text)) return false;
  return /^[A-Za-z_]\w*\s*(?:\(|\{)/.test(text);
}

function installOpenCadLayoutSplitter() {
  const splitter = document.getElementById('openCadMainSplitter');
  const panel = document.getElementById('openCadWorkPanel');
  const layout = document.getElementById('openCadWorkspaceLayout');
  if (!splitter || !panel || !layout || splitter.dataset.ready === 'true') return;
  splitter.dataset.ready = 'true';

  const onMove = (event) => {
    if (splitter.dataset.dragging !== 'true') return;
    const rect = layout.getBoundingClientRect();
    const minWidth = 420;
    const maxWidth = Math.max(minWidth, rect.width - 340);
    const nextWidth = Math.max(minWidth, Math.min(maxWidth, event.clientX - rect.left));
    panel.style.width = `${nextWidth}px`;
    resizeOpenCadViewport();
  };
  const stopDrag = () => {
    splitter.dataset.dragging = 'false';
    splitter.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', stopDrag);
  };

  splitter.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    splitter.dataset.dragging = 'true';
    splitter.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', stopDrag);
  });
}

function resizeOpenCadViewport() {
  if (!openCadRenderer || !openCadCamera) return;
  const viewport = document.getElementById('openCadViewport');
  const width = Math.max(1, viewport.clientWidth);
  const height = Math.max(1, viewport.clientHeight);
  openCadCamera.aspect = width / height;
  openCadCamera.updateProjectionMatrix();
  openCadRenderer.setSize(width, height, true);
  updateOpenCadCamera();
}

function updateOpenCadCamera() {
  if (!openCadCamera || !openCadControls.target) return;
  const r = openCadControls.radius;
  const t = openCadControls.target;
  openCadCamera.position.set(
    t.x + r * Math.sin(openCadControls.phi) * Math.cos(openCadControls.theta),
    t.y + r * Math.sin(openCadControls.phi) * Math.sin(openCadControls.theta),
    t.z + r * Math.cos(openCadControls.phi)
  );
  openCadCamera.up.set(0, 0, 1);
  openCadCamera.lookAt(t);
  updateOpenCadViewGizmo();
}

function updateOpenCadViewGizmo() {
  if (!openCadCamera) return;
  const axes = [
    { key: 'X', vector: new THREE.Vector3(1, 0, 0) },
    { key: 'Y', vector: new THREE.Vector3(0, 1, 0) },
    { key: 'Z', vector: new THREE.Vector3(0, 0, 1) },
  ];
  const origin = { x: 56, y: 56 };
  const length = 34;
  const cameraRotation = openCadCamera.matrixWorld.clone().invert();
  axes.forEach(axis => {
    const dir = axis.vector.clone().transformDirection(cameraRotation).normalize();
    const end = {
      x: origin.x + dir.x * length,
      y: origin.y - dir.y * length,
    };
    setOpenCadSvgAxisPosition(`openCadGizmo${axis.key}Line`, origin, end);
    setOpenCadSvgPoint(`openCadGizmo${axis.key}Dot`, end);
    setOpenCadSvgText(`openCadGizmo${axis.key}Text`, {
      x: end.x + dir.x * 15,
      y: end.y - dir.y * 15,
    });
  });
}

function setOpenCadSvgAxisPosition(id, origin, end) {
  const el = document.getElementById(id);
  if (!el) return;
  el.setAttribute('x1', formatOpenCadNumber(origin.x));
  el.setAttribute('y1', formatOpenCadNumber(origin.y));
  el.setAttribute('x2', formatOpenCadNumber(end.x));
  el.setAttribute('y2', formatOpenCadNumber(end.y));
}

function setOpenCadSvgPoint(id, point) {
  const el = document.getElementById(id);
  if (!el) return;
  el.setAttribute('cx', formatOpenCadNumber(point.x));
  el.setAttribute('cy', formatOpenCadNumber(point.y));
}

function setOpenCadSvgText(id, point) {
  const el = document.getElementById(id);
  if (!el) return;
  el.setAttribute('x', formatOpenCadNumber(clampOpenCadGizmoCoord(point.x)));
  el.setAttribute('y', formatOpenCadNumber(clampOpenCadGizmoCoord(point.y) + 4));
}

function clampOpenCadGizmoCoord(value) {
  return Math.max(12, Math.min(100, Number(value) || 0));
}

function setOpenCadAxisView(axis, direction = 1) {
  const sign = direction >= 0 ? 1 : -1;
  if (axis === 'x') {
    openCadControls.theta = sign > 0 ? 0 : Math.PI;
    openCadControls.phi = Math.PI / 2;
  } else if (axis === 'y') {
    openCadControls.theta = sign > 0 ? Math.PI / 2 : -Math.PI / 2;
    openCadControls.phi = Math.PI / 2;
  } else if (axis === 'z') {
    openCadControls.theta = Math.PI / 4;
    openCadControls.phi = sign > 0 ? 0.0001 : Math.PI - 0.0001;
  }
  updateOpenCadCamera();
  setOpenCadStatus(`${sign > 0 ? '+' : '-'}${String(axis || '').toUpperCase()} 视图`);
}

function animateOpenCad() {
  if (!openCadInitialized) return;
  requestAnimationFrame(animateOpenCad);
  if (openCadRenderer && openCadScene && openCadCamera) {
    openCadRenderer.clear(true, true, true);
    openCadRenderer.render(openCadScene, openCadCamera);
    if (openCadInteractionScene && openCadInteractionRoot?.children?.length) {
      openCadRenderer.clearDepth();
      openCadRenderer.render(openCadInteractionScene, openCadCamera);
    }
  }
}

function scheduleOpenCadRender() {
  clearTimeout(openCadRenderTimer);
  openCadRenderTimer = setTimeout(markOpenCadCodeDirty, 350);
}

async function renderOpenCad(options = {}) {
  if (!openCadInitialized || !openCadScene) return;
  clearOpenCadInteractionLayer();
  clearTimeout(openCadRenderTimer);
  clearTimeout(openCadEditorSaveTimer);
  openCadHasUnrenderedChanges = false;
  const file = getActiveOpenCadFile();
  const code = getOpenCadEditorValue() || file?.code || '';
  if (file) file.code = code;
  localStorage.setItem('openharness.opencad.code', code);
  saveOpenCadFiles();
  const renderSeq = ++openCadRenderSeq;
  openCadRenderInProgress = true;
  openCadRenderStatusProtectedUntil = Date.now() + 8000;
  setOpenCadStatus(openCadWasmUnavailable ? '使用浏览器预览器渲染...' : 'OpenSCAD WASM 后台渲染中...');
  try {
    const renderResult = await renderOpenCadWithWasm(code);
    if (renderSeq !== openCadRenderSeq) return;
    const off = renderResult?.off;
    const stl = renderResult?.stl || (renderResult instanceof Uint8Array ? renderResult : null);
    if (!off?.byteLength && !stl?.byteLength) throw new Error('OpenSCAD WASM 返回了空网格');
    const stlColorInfo = getOpenCadStlPreviewColor(code);
    const stlStats = off?.byteLength
      ? showOpenCadOff(off, { preserveCamera: Boolean(options.preserveCamera) })
      : showOpenCadStl(stl, { color: stlColorInfo?.color, preserveCamera: Boolean(options.preserveCamera) });
    clearOpenCadEditorMarkers();
    openCadRenderStatusProtectedUntil = Date.now() + 8000;
    openCadRenderInProgress = false;
    setOpenCadStatus(`OpenSCAD WASM 渲染完成：${formatOpenCadBytes(stlStats.bytes || off?.byteLength || stl?.byteLength)}，${stlStats.triangles} 个三角面${getOpenCadColorNotice(stlColorInfo, stlStats)}`, false, { clearError: true });
    return;
  } catch (error) {
    if (!isOpenCadWasmLoadError(error)) {
      console.error('OpenSCAD WASM render failed:', error);
      if (renderSeq === openCadRenderSeq) {
        const message = formatOpenCadError(error);
        setOpenCadEditorMarkers(message);
        openCadRenderInProgress = false;
        openCadRenderStatusProtectedUntil = Date.now() + 8000;
        setOpenCadStatus(`OpenSCAD WASM 渲染失败：${message}`, true);
      }
      return;
    }
    openCadWasmUnavailable = true;
    console.info('OpenSCAD WASM unavailable, using preview renderer:', error);
  }
  if (renderSeq !== openCadRenderSeq) return;
  renderOpenCadPreview(code, { preserveCamera: Boolean(options.preserveCamera) });
  openCadRenderStatusProtectedUntil = Date.now() + 8000;
  openCadRenderInProgress = false;
}

async function loadOpenCadWasm() {
  if (openCadWasmUnavailable) {
    throw createOpenCadWasmLoadError('OpenSCAD WASM module is unavailable');
  }
  if (openCadWasmFactoryPromise) return openCadWasmFactoryPromise;
  openCadWasmFactoryPromise = (async () => {
    let lastError = null;
    for (const modulePath of OPENSCAD_WASM_MODULE_PATHS) {
      try {
        const mod = await import(modulePath);
        if (typeof mod.createOpenSCAD === 'function') {
          return () => mod.createOpenSCAD(makeOpenCadWasmOptions());
        }
        const factory = mod.default || mod.OpenSCAD;
        if (typeof factory === 'function') {
          return async () => ({
            getInstance: () => null,
            instance: await factory(makeOpenCadWasmOptions()),
          });
        }
        throw new Error(`${modulePath} did not export createOpenSCAD or an OpenSCAD factory`);
      } catch (error) {
        lastError = error;
      }
    }
    throw createOpenCadWasmLoadError('OpenSCAD WASM module not found', lastError);
  })();
  try {
    return await openCadWasmFactoryPromise;
  } catch (error) {
    openCadWasmFactoryPromise = null;
    throw error;
  }
}

function makeOpenCadWasmOptions() {
  return {
    noInitialRun: true,
    print: text => {
      openCadWasmMessages.push(String(text || ''));
      console.log('[OpenSCAD]', text);
    },
    printErr: text => {
      openCadWasmMessages.push(String(text || ''));
      console.warn('[OpenSCAD]', text);
    },
  };
}

function createOpenCadWasmLoadError(message, cause = null) {
  const error = new Error(cause?.message ? `${message}: ${cause.message}` : message);
  error.name = 'OpenCadWasmLoadError';
  error.openCadWasmLoadError = true;
  if (cause) error.cause = cause;
  return error;
}

function isOpenCadWasmLoadError(error) {
  return Boolean(error?.openCadWasmLoadError || error?.name === 'OpenCadWasmLoadError');
}

function formatOpenCadError(error) {
  const message = error?.message || String(error || '未知错误');
  const cleaned = message.replace(/^Aborted\\((.*)\\)\\. Build with .*/s, '$1');
  return cleaned === '[object Object]' ? JSON.stringify(error) : cleaned;
}

async function renderOpenCadWithWorker(code, options = {}) {
  if (!window.Worker) {
    throw createOpenCadWasmLoadError('Web Worker is not supported');
  }
  const dedicatedWorker = Boolean(options.dedicatedWorker);
  debugOpenCadGui(options.interactionPreview ? 'worker request' : 'main render worker request', {
    dedicatedWorker,
    activeFileName: options.activeFileName || getActiveOpenCadFile()?.name || 'input.scad',
    codeChars: String(code || '').length,
  });
  if (!dedicatedWorker && openCadRenderWorkerBusy && openCadRenderWorker) {
    if (openCadRenderWorkerReject) openCadRenderWorkerReject(new Error('OpenSCAD render canceled'));
    openCadRenderWorker.terminate();
    openCadRenderWorker = null;
    openCadRenderWorkerBusy = false;
    openCadRenderWorkerReject = null;
  }
  const worker = dedicatedWorker
    ? new Worker('/static/js/opencad.worker.js?v=20260612-off-colors', { type: 'module' })
    : getOpenCadRenderWorker();
  const activeFile = getActiveOpenCadFile();
  if (activeFile) activeFile.code = getOpenCadEditorValue() || activeFile.code || '';
  setOpenCadStatus(options.interactionPreview ? '正在生成交互预览：加载库文件...' : 'OpenSCAD WASM 后台渲染中：加载库文件...');
  const libraries = await loadOpenCadLibraryFiles();
  const requestId = ++openCadWorkerRequestSeq;
  if (!dedicatedWorker) openCadRenderWorkerBusy = true;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup();
      if (dedicatedWorker) {
        worker.terminate();
      } else if (openCadRenderWorker === worker) {
        worker.terminate();
        openCadRenderWorker = null;
        openCadRenderWorkerBusy = false;
        openCadRenderWorkerReject = null;
      }
      reject(new Error(`OpenSCAD WASM 后台渲染超时（${Math.round(OPENSCAD_WORKER_RENDER_TIMEOUT_MS / 1000)} 秒），已终止本次渲染`));
    }, OPENSCAD_WORKER_RENDER_TIMEOUT_MS);
    const cleanup = () => {
      clearTimeout(timeout);
      worker.removeEventListener('message', onMessage);
      worker.removeEventListener('error', onError);
      if (dedicatedWorker) {
        worker.terminate();
      } else if (openCadRenderWorker === worker) {
        openCadRenderWorkerBusy = false;
        openCadRenderWorkerReject = null;
      }
    };
    const onMessage = event => {
      const data = event.data || {};
      if (data.id !== requestId) return;
      if (data.type === 'progress') {
        if (options.interactionPreview) debugOpenCadGui('worker progress', data.message || '处理中');
        setOpenCadStatus(options.interactionPreview
          ? `正在生成交互预览：${data.message || '处理中'}...`
          : `OpenSCAD WASM 后台渲染中：${data.message || '处理中'}...`);
        return;
      }
      cleanup();
      if (data.type === 'result') {
        const stl = data.stl instanceof Uint8Array ? data.stl : new Uint8Array(data.stl || []);
        const off = data.off instanceof Uint8Array ? data.off : new Uint8Array(data.off || []);
        if (options.interactionPreview) {
          debugOpenCadGui('worker result received', { offBytes: off.byteLength, stlBytes: stl.byteLength });
        }
        if (stl.byteLength) openCadLastStl = stl;
        resolve({ stl, off });
      } else {
        if (options.interactionPreview) debugOpenCadGui('worker error message', data.message || 'unknown');
        reject(new Error(data.message || 'OpenSCAD WASM worker render failed'));
      }
    };
    const onError = error => {
      cleanup();
      if (!dedicatedWorker && openCadRenderWorker === worker) {
        worker.terminate();
        openCadRenderWorker = null;
      }
      if (options.interactionPreview) debugOpenCadGui('worker error event', error.message || 'OpenSCAD WASM worker failed');
      reject(createOpenCadWasmLoadError(error.message || 'OpenSCAD WASM worker failed', error));
    };
    if (!dedicatedWorker) openCadRenderWorkerReject = reject;
    worker.addEventListener('message', onMessage);
    worker.addEventListener('error', onError);
    worker.postMessage({
      type: 'render',
      id: requestId,
      code,
      activeFileName: options.activeFileName || activeFile?.name || 'input.scad',
      files: openCadFiles.map(file => ({ name: file.name, code: file.code || '' })),
      libraries,
      outputFormat: options.outputFormat === 'stl' ? 'stl' : 'off',
    });
  });
}

function getOpenCadRenderWorker() {
  if (openCadRenderWorker) return openCadRenderWorker;
  openCadRenderWorker = new Worker('/static/js/opencad.worker.js?v=20260612-off-colors', { type: 'module' });
  return openCadRenderWorker;
}

async function renderOpenCadWithWasm(code, options = {}) {
  try {
    return await renderOpenCadWithWorker(code, options);
  } catch (error) {
    if (!isOpenCadWasmLoadError(error)) throw error;
    console.warn('OpenSCAD worker unavailable, falling back to main thread WASM:', error);
  }
  const createOpenScadInstance = await loadOpenCadWasm();
  const openscad = await createOpenScadInstance();
  const instance = typeof openscad.getInstance === 'function' ? openscad.getInstance() : openscad.instance || openscad;
  if (!instance?.FS || typeof instance.callMain !== 'function') {
    if (typeof openscad.renderToStl === 'function') {
      const stl = await openscad.renderToStl(code);
      openCadLastStl = stringToOpenCadBytes(stl);
      return { stl: openCadLastStl };
    }
    throw new Error('OpenSCAD WASM instance is missing FS/callMain');
  }
  const activeFile = getActiveOpenCadFile();
  openCadWasmMessages = [];
  const outputFormat = options.outputFormat === 'stl' ? 'stl' : 'off';
  const outputPath = `/output.${outputFormat}`;
  cleanupOpenCadWasmFile(instance, outputPath);
  await writeOpenCadLibrariesToWasm(instance);
  for (const file of openCadFiles) {
    const filePath = '/' + sanitizeOpenCadFileName(file.name);
    cleanupOpenCadWasmFile(instance, filePath);
    instance.FS.writeFile(filePath, file.code || '');
  }
  const inputPath = '/' + sanitizeOpenCadFileName(options.activeFileName || activeFile?.name || 'input.scad');
  instance.FS.writeFile(inputPath, code);
  let exitCode = 0;
  try {
    const exportFormat = outputFormat === 'stl' ? 'binstl' : 'off';
    exitCode = instance.callMain([inputPath, '--backend=manifold', '--export-format=' + exportFormat, '-o', outputPath]);
  } catch (error) {
    if (!instance.FS.analyzePath(outputPath).exists) {
      throw new Error(openCadWasmMessages.filter(Boolean).join('\n') || formatOpenCadError(error));
    }
  }
  if (exitCode && exitCode !== 0 && !instance.FS.analyzePath(outputPath).exists) {
    throw new Error(openCadWasmMessages.filter(Boolean).join('\n') || `OpenSCAD WASM exited with code ${exitCode}`);
  }
  const output = instance.FS.readFile(outputPath);
  const bytes = output instanceof Uint8Array ? output : stringToOpenCadBytes(output);
  if (outputFormat === 'stl') {
    openCadLastStl = bytes;
    return { stl: bytes };
  }
  return { off: bytes };
}

async function loadOpenCadLibraryFiles() {
  if (openCadLibraryFilesPromise) return openCadLibraryFilesPromise;
  openCadLibraryFilesPromise = fetch('/api/opencad/libraries')
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      return res.json();
    })
    .then(data => Array.isArray(data.files) ? data.files : [])
    .catch(error => {
      console.warn('Failed to load OpenCAD libraries:', error);
      return [];
    });
  return openCadLibraryFilesPromise;
}

async function writeOpenCadLibrariesToWasm(instance) {
  const files = await loadOpenCadLibraryFiles();
  for (const file of files) {
    const relPath = sanitizeOpenCadLibraryPath(file.path);
    if (!relPath) continue;
    const wasmPath = `/${relPath}`;
    ensureOpenCadWasmDirectory(instance, wasmPath.split('/').slice(0, -1).join('/') || '/');
    instance.FS.writeFile(wasmPath, String(file.content || ''));
  }
}

function sanitizeOpenCadLibraryPath(path) {
  const clean = String(path || '').replace(/\\/g, '/').split('/')
    .filter(part => part && part !== '.' && part !== '..')
    .join('/');
  return clean.endsWith('.scad') ? clean : '';
}

function ensureOpenCadWasmDirectory(instance, dirPath) {
  const parts = String(dirPath || '/').split('/').filter(Boolean);
  let current = '';
  for (const part of parts) {
    current += `/${part}`;
    try {
      if (!instance.FS.analyzePath(current).exists) {
        instance.FS.mkdir(current);
      }
    } catch (error) {
      console.warn('Failed to create OpenSCAD library directory:', current, error);
    }
  }
}

function cleanupOpenCadWasmFile(instance, path) {
  try {
    if (instance.FS.analyzePath(path).exists) {
      instance.FS.unlink(path);
    }
  } catch (error) {
    console.debug('OpenSCAD FS cleanup skipped:', path, error);
  }
}

function stringToOpenCadBytes(value) {
  return new TextEncoder().encode(String(value || ''));
}

function renderOpenCadPreview(code, options = {}) {
  try {
    const previewCode = getOpenCadPreviewRenderableCode(code);
    const ast = parseOpenScad(previewCode);
    const sourceParts = splitOpenCadTopLevelStatements(previewCode);
    const renderableSourceParts = sourceParts
      .map((part, index) => ({ ...part, sourcePartIndex: index }))
      .filter(part => isOpenCadRenderableStatement(part.text));
    if (openCadModelRoot) openCadScene.remove(openCadModelRoot);
    openCadModelRoot = new THREE.Group();
    const warnings = [];
    ast.forEach((node, index) => {
      const obj = buildOpenScadObject(node, null, warnings);
      if (obj) {
        if (renderableSourceParts[index]) {
          tagOpenCadSourceObject(obj, renderableSourceParts[index].sourcePartIndex);
          const guiObjectId = extractOpenCadGuiObjectId(renderableSourceParts[index].text);
          if (guiObjectId) tagOpenCadGuiObject(obj, guiObjectId);
        }
        openCadModelRoot.add(obj);
      }
    });
    openCadScene.add(openCadModelRoot);
    applyOpenCadWireframe();
    if (!options.preserveCamera) fitOpenCadCamera();
    setOpenCadStatus(warnings.length ? warnings.join(' · ') : '渲染完成', false, { clearError: true });
  } catch (error) {
    setOpenCadStatus(error.message || String(error), true);
  }
}

function getOpenCadPreviewRenderableCode(code) {
  return splitOpenCadTopLevelStatements(code)
    .filter(part => isOpenCadRenderableStatement(part.text))
    .map(part => part.text)
    .join('\n\n');
}

function extractOpenCadGuiObjectId(text) {
  const match = String(text || '').match(/^\s*\/\/\s*@(cad|oh):id=([A-Za-z0-9_:-]+)/m);
  return match ? match[2] : '';
}

function tagOpenCadSourceObject(object, sourceIndex) {
  object.userData.openCadSourceIndex = sourceIndex;
  object.traverse(child => {
    child.userData.openCadSourceIndex = sourceIndex;
  });
}

function tagOpenCadGuiObject(object, objectId) {
  object.userData.openCadGuiObjectId = objectId;
  object.traverse(child => {
    child.userData.openCadGuiObjectId = objectId;
  });
}

function buildOpenCadStlObject(bytes, options = {}) {
  if (!bytes?.byteLength) return null;
  const geometry = parseOpenCadStl(bytes);
  geometry.computeBoundingSphere();
  const triangles = Math.floor((geometry.getAttribute('position')?.count || 0) / 3);
  if (!triangles) return null;
  const material = new THREE.MeshStandardMaterial({
    color: options.color || 0x60a5fa,
    roughness: 0.55,
    metalness: options.color ? 0.12 : 0.05,
  });
  const group = new THREE.Group();
  group.add(new THREE.Mesh(geometry, material));
  group.userData.openCadStats = { triangles, bytes: bytes.byteLength || 0, coloredParts: 0 };
  return group;
}

function buildOpenCadOffObject(bytes) {
  if (!bytes?.byteLength) return null;
  const parsed = parseOpenCadOff(bytes);
  const group = new THREE.Group();
  let triangles = 0;
  for (const part of parsed.parts) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(part.positions), 3));
    geometry.computeVertexNormals();
    const color = new THREE.Color(part.color[0], part.color[1], part.color[2]);
    const alpha = Number.isFinite(part.color[3]) ? part.color[3] : 1;
    const material = new THREE.MeshStandardMaterial({
      color,
      roughness: 0.55,
      metalness: 0.08,
      opacity: alpha,
      transparent: alpha < 1,
    });
    triangles += part.positions.length / 9;
    group.add(new THREE.Mesh(geometry, material));
  }
  if (!triangles) return null;
  group.userData.openCadStats = {
    triangles,
    bytes: bytes.byteLength || 0,
    coloredParts: parsed.parts.length,
    coloredFormat: 'off',
  };
  return group;
}

function showOpenCadStl(bytes, options = {}) {
  if (openCadModelRoot) openCadScene.remove(openCadModelRoot);
  openCadModelRoot = buildOpenCadStlObject(bytes, options);
  if (!openCadModelRoot) throw new Error('STL 中没有可显示的三角面');
  openCadScene.add(openCadModelRoot);
  applyOpenCadWireframe();
  if (!options.preserveCamera) fitOpenCadCamera();
  return openCadModelRoot.userData.openCadStats;
}

function formatOpenCadBytes(bytes) {
  const size = Number(bytes || 0);
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

function showOpenCadOff(bytes, options = {}) {
  if (openCadModelRoot) openCadScene.remove(openCadModelRoot);
  openCadModelRoot = buildOpenCadOffObject(bytes);
  if (!openCadModelRoot) throw new Error('OFF 中没有可显示的三角面');
  openCadScene.add(openCadModelRoot);
  applyOpenCadWireframe();
  if (!options.preserveCamera) fitOpenCadCamera();
  return openCadModelRoot.userData.openCadStats;
}

function parseOpenCadOff(bytes) {
  const text = new TextDecoder().decode(bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes));
  const lines = text.split(/\r?\n/)
    .map(line => line.trim())
    .filter(line => line && !line.startsWith('#'));
  if (!lines.length) throw new Error('OFF 文件为空');
  let cursor = 0;
  let countsLine = '';
  if (/^OFF(?:\s|$)/i.test(lines[cursor])) {
    countsLine = lines[cursor].replace(/^OFF/i, '').trim();
    cursor += 1;
  } else {
    throw new Error('OFF 文件缺少 OFF 头');
  }
  if (!countsLine) {
    countsLine = lines[cursor] || '';
    cursor += 1;
  }
  const [vertexCount, faceCount] = countsLine.split(/\s+/).map(Number);
  if (!Number.isFinite(vertexCount) || !Number.isFinite(faceCount)) {
    throw new Error('OFF 顶点/面数量无效');
  }
  const vertices = [];
  for (let index = 0; index < vertexCount; index += 1) {
    const values = (lines[cursor + index] || '').split(/\s+/).map(Number);
    if (values.length < 3 || values.slice(0, 3).some(value => !Number.isFinite(value))) {
      throw new Error(`OFF 顶点无效：第 ${cursor + index + 1} 行`);
    }
    vertices.push([values[0], values[1], values[2]]);
  }
  cursor += vertexCount;
  const groups = new Map();
  for (let index = 0; index < faceCount; index += 1) {
    const values = (lines[cursor + index] || '').split(/\s+/).map(Number);
    const count = values[0];
    if (!Number.isFinite(count) || count < 3) continue;
    const faceVertices = values.slice(1, count + 1);
    const color = normalizeOpenCadOffColor(values.slice(count + 1));
    const key = color.map(value => value.toFixed(4)).join(',');
    if (!groups.has(key)) groups.set(key, { color, positions: [] });
    const group = groups.get(key);
    for (let tri = 1; tri < faceVertices.length - 1; tri += 1) {
      for (const vertexIndex of [faceVertices[0], faceVertices[tri], faceVertices[tri + 1]]) {
        const vertex = vertices[vertexIndex];
        if (!vertex) continue;
        group.positions.push(vertex[0], vertex[1], vertex[2]);
      }
    }
  }
  return { parts: [...groups.values()].filter(part => part.positions.length >= 9) };
}

function normalizeOpenCadOffColor(values) {
  if (!values || values.length < 3 || values.slice(0, 3).some(value => !Number.isFinite(value))) {
    return [0xf9 / 255, 0xd7 / 255, 0x2c / 255, 1];
  }
  const rgbScale = values.slice(0, 3).some(value => value > 1) ? 255 : 1;
  const alphaScale = Number.isFinite(values[3]) && values[3] > 1 ? 255 : 1;
  const color = [
    Math.max(0, Math.min(1, values[0] / rgbScale)),
    Math.max(0, Math.min(1, values[1] / rgbScale)),
    Math.max(0, Math.min(1, values[2] / rgbScale)),
    Number.isFinite(values[3]) ? Math.max(0, Math.min(1, values[3] / alphaScale)) : 1,
  ];
  return color;
}

function getOpenCadStlPreviewColor(code) {
  const source = stripOpenCadComments(code);
  const matches = [...source.matchAll(/\bcolor\s*\(\s*(?:"([^"]+)"|'([^']+)'|\[([^\]]+)\])/gi)];
  if (!matches.length) return null;
  const first = matches[0];
  const rawValue = first[1] || first[2] || first[3] || '';
  const color = parseOpenCadColorValue(rawValue, Boolean(first[3]));
  return { color, count: matches.length };
}

function getOpenCadColorNotice(colorInfo, stats = {}) {
  if (stats.coloredFormat === 'off') return `；已按 OFF 面颜色显示 ${stats.coloredParts} 个材质分组`;
  if (!colorInfo) return '';
  if (colorInfo.count > 1) return '；STL 预览仅使用第一个 color()，多色材质不会写入 STL';
  return '；STL 预览已应用 color()，但材质不会写入 STL';
}

function stripOpenCadComments(code) {
  return String(code || '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');
}

function parseOpenCadColorValue(value, isVector = false) {
  if (isVector) {
    const parts = String(value || '').split(',').map(part => Number(part.trim())).filter(Number.isFinite);
    if (parts.length >= 3) return new THREE.Color(parts[0], parts[1], parts[2]);
  }
  return new THREE.Color(openCadNamedColorValue(value));
}

function openCadNamedColorValue(value) {
  const named = {
    red: 0xef4444, green: 0x22c55e, blue: 0x3b82f6, yellow: 0xeab308,
    orange: 0xf97316, purple: 0xa855f7, white: 0xf8fafc, black: 0x111827,
    gray: 0x94a3b8, grey: 0x94a3b8, silver: 0xc0c0c0, steelblue: 0x4682b4,
  };
  const key = String(value || '').trim().toLowerCase();
  return named[key] ?? key;
}

function parseOpenCadStl(bytes) {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const headerText = new TextDecoder().decode(data.slice(0, Math.min(data.length, 256)));
  if (/^solid\b/i.test(headerText) && /facet\s+normal/i.test(headerText)) {
    return parseOpenCadAsciiStl(new TextDecoder().decode(data));
  }
  return parseOpenCadBinaryStl(data);
}

function parseOpenCadBinaryStl(data) {
  if (data.length < 84) throw new Error('STL 数据不完整');
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const triangles = view.getUint32(80, true);
  const expectedLength = 84 + triangles * 50;
  if (data.length < expectedLength) throw new Error('STL 三角面数据不完整');
  const positions = new Float32Array(triangles * 9);
  const normals = new Float32Array(triangles * 9);
  let sourceOffset = 84;
  let targetOffset = 0;
  for (let i = 0; i < triangles; i += 1) {
    const nx = view.getFloat32(sourceOffset, true);
    const ny = view.getFloat32(sourceOffset + 4, true);
    const nz = view.getFloat32(sourceOffset + 8, true);
    sourceOffset += 12;
    for (let v = 0; v < 3; v += 1) {
      positions[targetOffset] = view.getFloat32(sourceOffset, true);
      positions[targetOffset + 1] = view.getFloat32(sourceOffset + 4, true);
      positions[targetOffset + 2] = view.getFloat32(sourceOffset + 8, true);
      normals[targetOffset] = nx;
      normals[targetOffset + 1] = ny;
      normals[targetOffset + 2] = nz;
      sourceOffset += 12;
      targetOffset += 3;
    }
    sourceOffset += 2;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
  return geometry;
}

function parseOpenCadAsciiStl(text) {
  const values = [];
  const regex = /vertex\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)/ig;
  let match;
  while ((match = regex.exec(text))) {
    values.push(Number(match[1]), Number(match[2]), Number(match[3]));
  }
  if (!values.length) throw new Error('无法解析 ASCII STL');
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(values), 3));
  geometry.computeVertexNormals();
  return geometry;
}

function fitOpenCadCamera() {
  if (!openCadModelRoot || !openCadControls.target) {
    updateOpenCadCamera();
    return;
  }
  openCadModelRoot.position.set(0, 0, 0);
  openCadModelRoot.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(openCadModelRoot);
  if (box.isEmpty()) {
    openCadControls.target.set(0, 0, 0);
    openCadControls.radius = 120;
  } else {
    const center = new THREE.Vector3();
    const size = new THREE.Vector3();
    box.getCenter(center);
    box.getSize(size);
    openCadControls.target.copy(center);
    openCadControls.radius = Math.max(30, size.length() * 1.4);
  }
  updateOpenCadCamera();
}

function toggleOpenCadWireframe() {
  openCadWireframe = !openCadWireframe;
  applyOpenCadWireframe();
}

function applyOpenCadWireframe() {
  if (!openCadModelRoot) return;
  openCadModelRoot.traverse(obj => {
    if (obj.isMesh && obj.material) {
      obj.material.wireframe = openCadWireframe || Boolean(obj.userData.previewSubtractor);
      obj.material.needsUpdate = true;
    }
  });
}

function setOpenCadStatus(text, isError = false, options = {}) {
  const message = String(text || '');
  const el = document.getElementById('openCadStatus');
  if (el) {
    el.textContent = compactOpenCadStatus(message);
    el.title = message;
    el.className = isError ? 'open-cad-status error' : 'open-cad-status';
  }
  if (isError) {
    openCadOverlayStickyError = true;
  } else if (openCadOverlayStickyError && !options.clearError) {
    return;
  } else if (options.clearError) {
    openCadOverlayStickyError = false;
  }
  const overlay = document.getElementById('openCadOverlay');
  const overlayTitle = document.getElementById('openCadOverlayTitle');
  const overlayMessage = document.getElementById('openCadOverlayMessage');
  if (overlay) overlay.classList.toggle('error', Boolean(isError));
  if (overlayTitle) overlayTitle.textContent = isError ? 'OpenSCAD 错误' : '渲染状态';
  if (overlayMessage) overlayMessage.textContent = message || '准备就绪';
}

function compactOpenCadStatus(text) {
  const firstLine = String(text || '准备就绪').split('\n').find(line => line.trim()) || '准备就绪';
  return firstLine.length > 42 ? `${firstLine.slice(0, 39)}...` : firstLine;
}

function resetOpenCadCode() {
  const file = getActiveOpenCadFile();
  setOpenCadEditorValue(OPENSCAD_SAMPLE, file);
  saveOpenCadFiles();
  renderOpenCad();
}

async function copyOpenCadCode() {
  syncOpenCadEditorToActiveFile();
  const code = getOpenCadEditorValue();
  await navigator.clipboard.writeText(code);
  setOpenCadStatus('已复制');
}

function downloadOpenCadCode() {
  const file = getActiveOpenCadFile();
  syncOpenCadEditorToActiveFile();
  const code = getOpenCadEditorValue() || file?.code || '';
  const blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = sanitizeOpenCadFileName(file?.name || 'openharness-model.scad');
  link.click();
  URL.revokeObjectURL(link.href);
}

async function downloadOpenCadStl() {
  syncOpenCadEditorToActiveFile();
  const file = getActiveOpenCadFile();
  const code = getOpenCadEditorValue() || file?.code || '';
  try {
    setOpenCadStatus('OpenSCAD WASM 后台导出 STL...');
    const result = await renderOpenCadWithWasm(code, { outputFormat: 'stl' });
    const stl = result?.stl || result;
    if (!stl?.byteLength) throw new Error('OpenSCAD WASM 返回了空 STL');
    openCadLastStl = stl;
    const blob = new Blob([openCadLastStl], { type: 'model/stl' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = sanitizeOpenCadFileName(file?.name || 'openharness-model.scad').replace(/\.scad$/i, '.stl');
    link.click();
    URL.revokeObjectURL(link.href);
    setOpenCadStatus('STL 已导出', false, { clearError: true });
  } catch (error) {
    const message = formatOpenCadError(error);
    setOpenCadEditorMarkers(message);
    setOpenCadStatus(`OpenSCAD WASM 导出 STL 失败：${message}`, true);
  }
}

function askAgentForOpenCad() {
  switchPrimaryNav('opencad');
  const input = document.getElementById('openCadChatInput');
  input.value = '请帮我创建一个 OpenSCAD 3D 模型，输出完整代码，并使用 ```openscad 代码块包裹。';
  input.focus();
}

function applyOpenScadCode(code, fileName = '') {
  switchPrimaryNav('opencad');
  const file = getOrCreateOpenCadFileForApply(fileName);
  openCadActiveFileId = file.id;
  setOpenCadEditorValue(code.trim(), file);
  saveOpenCadFiles();
  renderOpenCadFileTabs();
  renderOpenCad();
}

function applyOpenScadBlocks(encodedBlocks) {
  const blocks = JSON.parse(decodeURIComponent(encodedBlocks));
  let lastFile = null;
  blocks.forEach(block => {
    const file = getOrCreateOpenCadFileForApply(block.fileName || '');
    setOpenCadFileCode(file, String(block.code || '').trim());
    lastFile = file;
  });
  if (lastFile) {
    openCadActiveFileId = lastFile.id;
    setOpenCadEditorValue(lastFile.code, lastFile);
  }
  saveOpenCadFiles();
  renderOpenCadFileTabs();
  renderOpenCad();
}

function getOrCreateOpenCadFileForApply(fileName = '') {
  const targetName = fileName ? sanitizeOpenCadFileName(fileName) : '';
  if (!targetName) return getActiveOpenCadFile() || openCadFiles[0];
  let file = openCadFiles.find(item => item.name === targetName);
  if (!file) {
    file = { id: makeOpenCadFileId(), name: targetName, code: '' };
    openCadFiles.push(file);
  }
  return file;
}

function extractOpenScadBlocks(text) {
  const blocks = [];
  const fenceRegex = /```([^\n`]*)\n([\s\S]*?)```/g;
  let match;
  while ((match = fenceRegex.exec(text || ''))) {
    const info = String(match[1] || '').trim();
    const code = String(match[2] || '').trim();
    if (!/(^|\s)(openscad|scad)(\s|:|$)/i.test(info) && !looksLikeOpenScadCode(code)) continue;
    blocks.push({
      fileName: extractOpenScadFilename(text, match.index, info),
      code,
    });
  }
  if (blocks.length) return blocks;
  const generic = text.match(/```\s*([\s\S]*?(?:cube|sphere|cylinder|translate|rotate|difference|union)[\s\S]*?)```/i);
  return generic ? [{ fileName: '', code: generic[1].trim() }] : [];
}

function extractOpenScadCode(text) {
  return extractOpenScadBlocks(text)[0]?.code || '';
}

function extractOpenScadFilename(fullText, fenceIndex, info) {
  const infoMatch = String(info || '').match(/(?:^|\s|:)([A-Za-z0-9_.-]+\.scad)\b/i);
  if (infoMatch) return infoMatch[1];
  const before = String(fullText || '').slice(Math.max(0, fenceIndex - 220), fenceIndex);
  const headingMatch = before.match(/(?:^|\n)\s*(?:#{1,6}\s*)?(?:文件|file|filename|path)?\s*[:：]?\s*`?([A-Za-z0-9_.-]+\.scad)`?\s*$/i);
  return headingMatch ? headingMatch[1] : '';
}

function looksLikeOpenScadCode(code) {
  return /\b(cube|sphere|cylinder|translate|rotate|difference|union|module|function|use|include)\b/i.test(code || '');
}

function renderOpenScadAction(text) {
  const blocks = extractOpenScadBlocks(text || '');
  if (!blocks.length) return '';
  const buttons = blocks.map((block, index) => {
    const code = encodeURIComponent(block.code);
    const fileName = encodeURIComponent(block.fileName || '');
    const label = block.fileName ? `应用到 ${openCadEscapeHtml(block.fileName)}` : '应用到当前文件';
    return `<button class="btn-secondary text-xs px-3 py-1.5" onclick="applyOpenScadCode(decodeURIComponent('${code.replace(/'/g, '%27')}'), decodeURIComponent('${fileName.replace(/'/g, '%27')}'))">${label}${blocks.length > 1 ? ` #${index + 1}` : ''}</button>`;
  }).join('');
  const all = blocks.length > 1
    ? `<button class="btn-primary text-xs px-3 py-1.5" onclick="applyOpenScadBlocks('${encodeURIComponent(JSON.stringify(blocks)).replace(/'/g, '%27')}')">应用全部代码块</button>`
    : '';
  return `<div class="mt-3 pt-3 border-t border-dark-border flex flex-wrap gap-2">${all}${buttons}</div>`;
}

async function populateOpenCadChatOptions() {
  const agentSelect = document.getElementById('openCadChatAgent');
  if (!agentSelect) return;
  const currentAgent = agentSelect.value || localStorage.getItem(OPENSCAD_CHAT_AGENT_STORAGE_KEY) || '';
  let availableAgents = typeof agents !== 'undefined' ? (agents || []) : [];
  let activeId = typeof activeAgentId !== 'undefined' ? activeAgentId : null;
  if (!availableAgents.length) {
    try {
      const res = await fetch('/api/agents');
      if (res.ok) {
        const data = await res.json();
        availableAgents = data.agents || [];
        activeId = data.active_agent_id || activeId;
      }
    } catch (error) {
      console.warn('Failed to load OpenCAD chat agents:', error);
    }
  }
  const defaultLabel = activeId
    ? `当前默认 Agent${availableAgents.find(agent => agent.id === activeId)?.name ? ` · ${availableAgents.find(agent => agent.id === activeId).name}` : ''}`
    : '当前默认 Agent';
  agentSelect.innerHTML = `<option value="">${openCadEscapeHtml(defaultLabel)}</option>` + availableAgents.map(agent => {
    const meta = [
      agent.profile ? `供应商: ${agent.profile}` : '默认供应商',
      agent.model ? `模型: ${agent.model}` : '',
    ].filter(Boolean).join(' · ');
    const label = `${agent.name || agent.id}${meta ? ` (${meta})` : ''}`;
    return `<option value="${openCadEscapeHtml(agent.id)}">${openCadEscapeHtml(label)}</option>`;
  }).join('');
  agentSelect.value = availableAgents.some(agent => agent.id === currentAgent) ? currentAgent : '';
}

function onOpenCadChatAgentChange() {
  const agentId = document.getElementById('openCadChatAgent')?.value || '';
  if (agentId) {
    localStorage.setItem(OPENSCAD_CHAT_AGENT_STORAGE_KEY, agentId);
  } else {
    localStorage.removeItem(OPENSCAD_CHAT_AGENT_STORAGE_KEY);
  }
}

function clearOpenCadChat() {
  openCadChatSessionId = 'opencad_' + Date.now();
  const container = document.getElementById('openCadChatMessages');
  if (container) {
    container.innerHTML = '<div class="text-center text-text-muted text-xs py-6">描述你想要的零件或修改，Agent 会返回 OpenSCAD 代码。</div>';
  }
}

async function sendOpenCadChatMessage() {
  const input = document.getElementById('openCadChatInput');
  const rawMessage = input?.value.trim() || '';
  if (!rawMessage || openCadChatStreaming) return;
  const container = document.getElementById('openCadChatMessages');
  if (!container) return;
  if (container.querySelector('.text-center')) container.innerHTML = '';

  container.innerHTML += `
    <div class="flex justify-end animate-fade-in">
      <div class="open-cad-chat-user">${openCadEscapeHtml(rawMessage)}</div>
    </div>
  `;
  input.value = '';
  container.scrollTop = container.scrollHeight;

  const assistantId = 'opencad-assistant-' + Date.now();
  container.innerHTML += `
    <div class="flex justify-start animate-slide-up">
      <div id="${assistantId}" class="open-cad-chat-assistant">
        <span class="text-text-muted animate-pulse">建模中...</span>
      </div>
    </div>
  `;
  container.scrollTop = container.scrollHeight;

  const assistantEl = document.getElementById(assistantId);
  let assistantText = '';
  openCadChatStreaming = true;

  try {
    const selectedAgentId = document.getElementById('openCadChatAgent')?.value || '';
    const selectedAgent = getOpenCadSelectedAgent(selectedAgentId);
    const prompt = buildOpenCadChatPrompt(rawMessage, selectedAgent);
    const response = await fetch('/api/chat/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: prompt,
        session_id: openCadChatSessionId,
        agent_id: selectedAgentId || (typeof activeAgentId !== 'undefined' ? activeAgentId : null),
      }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let currentEventType = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
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
          continue;
        }
        if (!trimmed.startsWith('data: ') || !currentEventType) continue;
        const data = JSON.parse(trimmed.slice(6));
        if (currentEventType === 'text') {
          assistantText += data.text || '';
          assistantEl.innerHTML = marked.parse(assistantText) + renderOpenScadAction(assistantText);
          container.scrollTop = container.scrollHeight;
        } else if (currentEventType === 'error') {
          assistantEl.innerHTML += `<div class="mt-2 text-red-400">${openCadEscapeHtml(data.message || '执行失败')}</div>`;
        }
      }
    }
    if (!assistantText.trim()) {
      assistantEl.innerHTML = '<span class="text-text-muted">响应完成，但没有文本输出。</span>';
    }
  } catch (error) {
    if (assistantEl) assistantEl.innerHTML = `<span class="text-red-400">错误: ${openCadEscapeHtml(error.message || String(error))}</span>`;
  } finally {
    openCadChatStreaming = false;
    container.scrollTop = container.scrollHeight;
  }
}

function getOpenCadSelectedAgent(agentId) {
  if (typeof agents === 'undefined') return null;
  const resolvedAgentId = agentId || (typeof activeAgentId !== 'undefined' ? activeAgentId : '');
  if (!resolvedAgentId) return null;
  return (agents || []).find(agent => agent.id === resolvedAgentId) || null;
}

function buildOpenCadChatPrompt(message, selectedAgent) {
  const activeFile = getActiveOpenCadFile();
  const apiBase = window.location.origin;
  const fileContext = openCadFiles.map(file => summarizeOpenCadFileForPrompt(file, file.id === activeFile?.id, apiBase)).join('\n');
  return [
    '你正在 OpenHarness 的 OpenSCAD 建模工作台中协助用户进行 3D 建模。',
    '默认不要假设你已经拿到了完整 .scad 源码；下面只提供文件摘要。',
    '如果确实需要查看源码，请按需读取单个文件，而不是要求一次性加载所有文件。',
    '优先使用文件摘要中的 local_path，通过文件读取工具读取源码；URL 只作为同网络环境下的备用方式。',
    'OpenSCAD 库也会物化在同一个文件目录下；例如 MCAD/gears.scad 位于当前文件目录的 MCAD/gears.scad。',
    `可用的按需读取接口：GET ${apiBase}/api/opencad/workspace/summary，以及 GET ${apiBase}/api/opencad/workspace/files/<文件名或文件ID>。`,
    '文件名可能包含点号或路径字符；优先使用下方摘要中的 direct_url 精确读取。',
    '请优先输出可直接运行的 OpenSCAD 代码；如果要修改文件，请输出完整文件内容。',
    '每个代码块都要在 fence info 或代码块前一行标明目标文件名，例如 ```openscad gear.scad。',
    '可以建议把不同零件拆到不同 .scad 文件中；如果需要新增文件，请明确给出文件名和完整代码。',
    selectedAgent ? `当前建模 Agent: ${selectedAgent.name || selectedAgent.id}` : '',
    `当前活动文件: ${activeFile?.name || 'main.scad'}`,
    '',
    '当前打开的文件摘要：',
    fileContext,
    '',
    '用户需求：',
    message,
  ].filter(Boolean).join('\n');
}

function summarizeOpenCadFileForPrompt(file, active = false, apiBase = '') {
  const code = String(file?.code || '');
  const modules = extractOpenCadNames(code, /\bmodule\s+([A-Za-z_]\w*)\s*\(/g);
  const functions = extractOpenCadNames(code, /\bfunction\s+([A-Za-z_]\w*)\s*\(/g);
  const assignments = extractOpenCadNames(code, /^\s*([A-Za-z_]\w*)\s*=/gm).slice(0, 12);
  const lines = code ? code.split('\n').length : 0;
  const parts = [
    `- ${active ? '[active] ' : ''}${file.name} (id: ${file.id}, ${lines} 行, ${code.length} 字符)`,
    file.localPath ? `local_path: ${file.localPath}` : '',
    apiBase ? `direct_url: ${apiBase}/api/opencad/workspace/files/${encodeURIComponent(file.name)}` : '',
    modules.length ? `modules: ${modules.join(', ')}` : '',
    functions.length ? `functions: ${functions.join(', ')}` : '',
    assignments.length ? `parameters: ${assignments.join(', ')}` : '',
  ].filter(Boolean);
  return parts.join(' | ');
}

function extractOpenCadNames(code, regex) {
  const names = [];
  let match;
  while ((match = regex.exec(code))) {
    if (match[1] && !names.includes(match[1])) names.push(match[1]);
    if (names.length >= 16) break;
  }
  return names;
}

function openCadEscapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function parseOpenScad(code) {
  const cleaned = code
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '')
    .replace(/\$fn\s*=\s*[^;]+;/g, '');
  const tokens = [];
  const regex = /([A-Za-z_]\w*)|(-?\d*\.?\d+(?:e[+-]?\d+)?)|("(?:[^"\\]|\\.)*")|([{}\[\](),;:=])/ig;
  let match;
  while ((match = regex.exec(cleaned))) {
    tokens.push(match[0]);
  }
  let pos = 0;
  const peek = () => tokens[pos];
  const take = () => tokens[pos++];
  const expect = value => {
    if (take() !== value) throw new Error(`OpenSCAD 解析错误：需要 ${value}`);
  };

  function parseProgram(stopToken = null) {
    const nodes = [];
    while (pos < tokens.length && peek() !== stopToken) {
      const node = parseStatement();
      if (node) nodes.push(node);
    }
    return nodes;
  }

  function parseStatement() {
    if (peek() === ';') { take(); return null; }
    if (peek() === '}') return null;
    const name = take();
    if (!/^[A-Za-z_]/.test(name || '')) throw new Error(`OpenSCAD 解析错误：无法识别 ${name || 'EOF'}`);
    const args = peek() === '(' ? parseArgs() : [];
    const node = { name, args, children: [] };
    if (peek() === '{') {
      take();
      node.children = parseProgram('}');
      expect('}');
    } else if (peek() === ';') {
      take();
    } else if (/^[A-Za-z_]/.test(peek() || '')) {
      const child = parseStatement();
      if (child) node.children = [child];
    }
    return node;
  }

  function parseArgs() {
    const args = [];
    expect('(');
    while (pos < tokens.length && peek() !== ')') {
      if (peek() === ',') { take(); continue; }
      let name = null;
      if (/^[A-Za-z_]/.test(peek() || '') && tokens[pos + 1] === '=') {
        name = take();
        expect('=');
      }
      const value = parseValue();
      args.push({ name, value });
      if (peek() === ',') take();
    }
    expect(')');
    return args;
  }

  function parseValue() {
    const token = peek();
    if (token === '[') {
      take();
      const values = [];
      while (pos < tokens.length && peek() !== ']') {
        if (peek() === ',') { take(); continue; }
        values.push(parseValue());
        if (peek() === ',') take();
      }
      expect(']');
      return values;
    }
    const raw = take();
    if (/^-?\d/.test(raw)) return Number(raw);
    if (raw && raw.startsWith('"')) return raw.slice(1, -1);
    if (raw === 'true') return true;
    if (raw === 'false') return false;
    return raw;
  }

  return parseProgram();
}

function buildOpenScadObject(node, inheritedMaterial, warnings) {
  const name = String(node.name || '').toLowerCase();
  const material = inheritedMaterial || new THREE.MeshStandardMaterial({ color: 0x60a5fa, roughness: 0.55, metalness: 0.08 });
  const group = new THREE.Group();
  const childObjects = () => (node.children || []).map(child => buildOpenScadObject(child, material, warnings)).filter(Boolean);

  if (name === 'translate' || name === 'rotate' || name === 'scale' || name === 'color') {
    const nextMaterial = name === 'color' ? materialFromColor(getArg(node, null, 0, 'steelblue'), material) : material;
    childObjects().forEach(obj => group.add(obj));
    if (name === 'translate') {
      const v = asVec3(getArg(node, null, 0, [0, 0, 0]), [0, 0, 0]);
      group.position.set(v[0], v[1], v[2]);
    } else if (name === 'rotate') {
      const v = asVec3(getArg(node, null, 0, [0, 0, 0]), [0, 0, 0]).map(deg => deg * Math.PI / 180);
      group.rotation.set(v[0], v[1], v[2]);
    } else if (name === 'scale') {
      const v = asVec3(getArg(node, null, 0, [1, 1, 1]), [1, 1, 1]);
      group.scale.set(v[0], v[1], v[2]);
    } else {
      group.clear();
      (node.children || []).map(child => buildOpenScadObject(child, nextMaterial, warnings)).filter(Boolean).forEach(obj => group.add(obj));
    }
    return group;
  }

  if (name === 'union' || name === 'group') {
    childObjects().forEach(obj => group.add(obj));
    return group;
  }
  if (name === 'difference') {
    warnings.push('difference() 当前为预览模式，红色线框表示被减对象');
    (node.children || []).forEach((child, index) => {
      const mat = index === 0 ? material : new THREE.MeshStandardMaterial({ color: 0xef4444, transparent: true, opacity: 0.28 });
      const obj = buildOpenScadObject(child, mat, warnings);
      if (obj) {
        if (index > 0) obj.traverse(item => { if (item.isMesh) item.userData.previewSubtractor = true; });
        group.add(obj);
      }
    });
    return group;
  }

  let geometry = null;
  if (name === 'cube') {
    const size = getArg(node, 'size', 0, 1);
    const dims = Array.isArray(size) ? asVec3(size, [1, 1, 1]) : [Number(size) || 1, Number(size) || 1, Number(size) || 1];
    geometry = new THREE.BoxGeometry(dims[0], dims[1], dims[2]);
    const mesh = new THREE.Mesh(geometry, material.clone());
    if (!Boolean(getArg(node, 'center', 1, false))) mesh.position.set(dims[0] / 2, dims[1] / 2, dims[2] / 2);
    return mesh;
  }
  if (name === 'sphere') {
    const r = Number(getArg(node, 'r', 0, 0)) || Number(getArg(node, 'd', 0, 2)) / 2 || 1;
    geometry = new THREE.SphereGeometry(r, 48, 24);
    return new THREE.Mesh(geometry, material.clone());
  }
  if (name === 'cylinder') {
    const h = Number(getArg(node, 'h', 0, 1)) || 1;
    const r = Number(getArg(node, 'r', 1, 0)) || Number(getArg(node, 'd', 1, 2)) / 2 || 1;
    const r1 = Number(getArg(node, 'r1', null, r)) || r;
    const r2 = Number(getArg(node, 'r2', null, r)) || r;
    geometry = new THREE.CylinderGeometry(r2, r1, h, 64);
    geometry.rotateX(Math.PI / 2);
    const mesh = new THREE.Mesh(geometry, material.clone());
    if (!Boolean(getArg(node, 'center', null, false))) mesh.position.z = h / 2;
    return mesh;
  }
  warnings.push(`暂不支持 ${node.name}()`);
  return null;
}

function getArg(node, name, index, fallback) {
  if (name) {
    const named = (node.args || []).find(arg => arg.name === name);
    if (named) return named.value;
  }
  if (index !== null && index !== undefined) {
    const positional = (node.args || []).filter(arg => !arg.name);
    if (positional[index]) return positional[index].value;
  }
  return fallback;
}

function asVec3(value, fallback) {
  if (Array.isArray(value)) {
    return [Number(value[0] ?? fallback[0]), Number(value[1] ?? fallback[1]), Number(value[2] ?? fallback[2])];
  }
  const n = Number(value);
  return Number.isFinite(n) ? [n, n, n] : fallback;
}

function materialFromColor(value, base) {
  let color = openCadNamedColorValue(value);
  if (Array.isArray(value)) {
    color = new THREE.Color(Number(value[0] || 0), Number(value[1] || 0), Number(value[2] || 0));
  }
  const mat = base.clone();
  mat.color = color instanceof THREE.Color ? color : new THREE.Color(color);
  return mat;
}
