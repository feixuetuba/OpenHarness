const OPENSCAD_WASM_MODULE_PATHS = [
  '/static/vendor/openscad/openscad.js',
  '/static/openscad/openscad.js',
];

self.addEventListener('message', event => {
  const data = event.data || {};
  if (data.type !== 'render') return;
  renderOpenCad(data).catch(error => {
    self.postMessage({
      type: 'error',
      id: data.id,
      message: formatOpenCadWorkerError(error),
    });
  });
});

async function renderOpenCad(request) {
  const messages = [];
  reportOpenCadProgress(request.id, '加载 OpenSCAD WASM');
  const createOpenScad = await loadOpenCadWasmFactory();
  reportOpenCadProgress(request.id, '初始化 OpenSCAD 实例');
  const openscad = await createOpenScad(makeOpenCadWorkerOptions(messages));
  const instance = getOpenCadWasmInstance(openscad);
  if (!instance?.FS || typeof instance.callMain !== 'function') {
    if (typeof openscad.renderToStl === 'function') {
      reportOpenCadProgress(request.id, '调用 renderToStl');
      const stl = stringToOpenCadBytes(await openscad.renderToStl(request.code || ''));
      self.postMessage({ type: 'result', id: request.id, stl }, [stl.buffer]);
      return;
    }
    throw new Error('OpenSCAD WASM instance is missing FS/callMain');
  }

  reportOpenCadProgress(request.id, `写入库文件 ${Number(request.libraries?.length || 0)} 个`);
  await writeOpenCadRequestFiles(instance, request);

  const inputPath = '/' + sanitizeOpenCadFileName(request.activeFileName || 'input.scad');
  const outputFormat = request.outputFormat === 'stl' ? 'stl' : 'off';
  const outputPath = `/output.${outputFormat}`;
  cleanupOpenCadWasmFile(instance, outputPath);
  instance.FS.writeFile(inputPath, String(request.code || ''));

  let exitCode = 0;
  try {
    reportOpenCadProgress(request.id, `OpenSCAD Manifold 编译 ${outputFormat.toUpperCase()}`);
    const exportFormat = outputFormat === 'stl' ? 'binstl' : 'off';
    exitCode = instance.callMain([inputPath, '--backend=manifold', '--export-format=' + exportFormat, '-o', outputPath]);
  } catch (error) {
    if (!instance.FS.analyzePath(outputPath).exists) {
      throw new Error(messages.filter(Boolean).join('\n') || formatOpenCadWorkerError(error));
    }
  }
  if (exitCode && exitCode !== 0 && !instance.FS.analyzePath(outputPath).exists) {
    throw new Error(messages.filter(Boolean).join('\n') || `OpenSCAD WASM exited with code ${exitCode}`);
  }

  reportOpenCadProgress(request.id, `读取 ${outputFormat.toUpperCase()} 网格`);
  const output = instance.FS.readFile(outputPath);
  const bytes = output instanceof Uint8Array ? output.slice() : stringToOpenCadBytes(output);
  if (outputFormat === 'stl') {
    self.postMessage({ type: 'result', id: request.id, stl: bytes }, [bytes.buffer]);
    return;
  }
  self.postMessage({ type: 'result', id: request.id, off: bytes }, [bytes.buffer]);
}

function reportOpenCadProgress(id, message) {
  self.postMessage({ type: 'progress', id, message });
}

function makeOpenCadWorkerOptions(messages) {
  return {
    noInitialRun: true,
    print: text => messages.push(String(text || '')),
    printErr: text => messages.push(String(text || '')),
  };
}

function getOpenCadWasmInstance(openscad) {
  return typeof openscad.getInstance === 'function' ? openscad.getInstance() : openscad.instance || openscad;
}

async function writeOpenCadRequestFiles(instance, request) {
  await writeOpenCadLibrariesToWasm(instance, request.libraries || []);
  for (const file of request.files || []) {
    const filePath = '/' + sanitizeOpenCadFileName(file.name);
    cleanupOpenCadWasmFile(instance, filePath);
    instance.FS.writeFile(filePath, String(file.code || ''));
  }
}

async function loadOpenCadWasmFactory() {
  let lastError = null;
  for (const modulePath of OPENSCAD_WASM_MODULE_PATHS) {
    try {
      const mod = await import(modulePath);
      if (typeof mod.createOpenSCAD === 'function') {
        return options => mod.createOpenSCAD(options);
      }
      const factory = mod.default || mod.OpenSCAD;
      if (typeof factory === 'function') {
        return async options => ({
          getInstance: () => null,
          instance: await factory(options),
        });
      }
      throw new Error(`${modulePath} did not export createOpenSCAD or an OpenSCAD factory`);
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(`OpenSCAD WASM module not found: ${formatOpenCadWorkerError(lastError)}`);
}

async function writeOpenCadLibrariesToWasm(instance, files) {
  for (const file of files) {
    const relPath = sanitizeOpenCadLibraryPath(file.path);
    if (!relPath) continue;
    const wasmPath = `/${relPath}`;
    ensureOpenCadWasmDirectory(instance, wasmPath.split('/').slice(0, -1).join('/') || '/');
    instance.FS.writeFile(wasmPath, String(file.content || ''));
  }
}

function sanitizeOpenCadFileName(name) {
  const cleaned = String(name || '').trim().replace(/[\\/:*?"<>|]/g, '_');
  return cleaned.endsWith('.scad') ? cleaned : `${cleaned || 'part'}.scad`;
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
      if (!instance.FS.analyzePath(current).exists) instance.FS.mkdir(current);
    } catch (error) {
      // Directory creation is best effort; OpenSCAD will surface a useful FS error if it matters.
    }
  }
}

function cleanupOpenCadWasmFile(instance, path) {
  try {
    if (instance.FS.analyzePath(path).exists) instance.FS.unlink(path);
  } catch (error) {
    // Cleanup is best effort.
  }
}

function stringToOpenCadBytes(value) {
  return new TextEncoder().encode(String(value || ''));
}

function formatOpenCadWorkerError(error) {
  const message = error?.message || String(error || '未知错误');
  const cleaned = message.replace(/^Aborted\\((.*)\\)\\. Build with .*/s, '$1');
  return cleaned === '[object Object]' ? JSON.stringify(error) : cleaned;
}
