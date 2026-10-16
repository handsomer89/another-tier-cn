import {createCollectionStore, COLLECTION_STORAGE_KEY, MAX_IMPORT_BYTES} from './collection-data.js?v=4314887c04fa';
import {displayName, filterOptions, emptyFilters, matchesCharacter, readPublicFilters, publicFilterSearch} from './collection-filter.js?v=02ee76bdf270';
import {exportCollectionImage, imageSources} from './collection-export.js?v=c9ade8320e3e';
import {loadCollectionCatalog} from './collection-catalog.js?v=b51f7f5dd12e';
import {installImageFallback} from './image-fallback.js?v=28160b2b55e8';

const $ = id => document.getElementById(id);
const labels = {unowned:'未拥有',owned:'拥有（未星导）',awakened:'已星导'};
const dimensions = {elements:'属性',weapons:'武器',roles:'定位',personalities:'个性'};
let catalog, store, preview, selectedCharacter, lastStoreResult;
let filters = readPublicFilters(location.search);
let toastTimer, imageURL, imageController, catalogController, imageBusy = false;
let importGeneration = 0;
const cards = new Map();
const openers = new WeakMap();
const pendingWrites = new Map();
installImageFallback();
const userAgent = navigator.userAgent.toLowerCase();
const platform = /iphone|ipad|ipod/.test(userAgent) ? 'ios' : /macintosh|macintel|macppc|mac68k|macos/.test(userAgent) ? 'macos'
  : /win32|win64|windows|wince/.test(userAgent) ? 'windows' : /android/.test(userAgent) ? 'android' : /linux/.test(userAgent) ? 'linux' : null;
if (platform) document.documentElement.classList.add(platform);

function notify(message) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').hidden = false;
  toastTimer = setTimeout(() => {$('toast').hidden = true;}, 4500);
}
function notice(element, message) { element.textContent = message ?? ''; element.hidden = !message; }
function showStoreResult(result) {
  lastStoreResult = result;
  notice($('storage-alert'), [result.warning,result.error?.message].filter(Boolean).join(' '));
}
function showDialog(dialog) {
  openers.set(dialog, document.activeElement);
  dialog.showModal();
  document.body.style.overflow = 'hidden';
}
async function saveWithLock(dialog, action) {
  if (pendingWrites.has(dialog)) return null;
  const controller = new AbortController();
  pendingWrites.set(dialog,controller);
  const buttons = [...dialog.querySelectorAll('[data-set-status], #confirm-import')];
  const disabled = buttons.map(button => button.disabled);
  buttons.forEach(button => {button.disabled = true;});
  dialog.setAttribute('aria-busy','true');
  const save = () => controller.signal.aborted || !dialog.open ? null : action();
  try {
    if (navigator.locks?.request) {
      return await navigator.locks.request(COLLECTION_STORAGE_KEY,{mode:'exclusive',signal:controller.signal},save);
    }
    return save();
  } catch (error) {
    if (error.name === 'AbortError') return null;
    return {...lastStoreResult,ok:false,error:new Error('保存失败，请重试：'+error.message)};
  } finally {
    pendingWrites.delete(dialog);
    buttons.forEach((button,index) => {button.disabled = disabled[index];});
    dialog.removeAttribute('aria-busy');
  }
}
for (const dialog of document.querySelectorAll('dialog')) {
  const focusable = () => [...dialog.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), [tabindex="0"]')]
    .filter(element => element.getClientRects().length > 0);
  dialog.addEventListener('keydown',event => {
    if (event.key !== 'Tab') return;
    const targets = focusable();
    if (!targets.length) {event.preventDefault();dialog.focus();return;}
    const first = targets[0], last = targets[targets.length-1];
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
      event.preventDefault();last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
      event.preventDefault();first.focus();
    }
  });
  dialog.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click',() => dialog.close()));
  dialog.addEventListener('click',event => {
    const rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  });
  dialog.addEventListener('close',() => {
    pendingWrites.get(dialog)?.abort();
    document.body.style.overflow = '';
    let opener = openers.get(dialog);
    if (dialog === $('state-dialog') && selectedCharacter) opener = cards.get(selectedCharacter.slug);
    if (opener?.isConnected && !opener.hidden) opener.focus({preventScroll:true});
    else $('keyword').focus({preventScroll:true});
    if (dialog === $('import-dialog')) {preview = undefined;importGeneration++;}
    if (dialog === $('image-dialog')) {
      imageController?.abort();
      releaseImage();
    }
  });
}

let theme = 'auto';
try { const saved = localStorage.getItem('theme'); if (['light','dark','auto'].includes(saved)) theme = saved; } catch { /* System preference remains available. */ }
const media = matchMedia('(prefers-color-scheme: dark)');
function applyTheme() {
  const dark = theme === 'dark' || (theme === 'auto' && media.matches);
  document.documentElement.classList.toggle('dark',dark);
  document.documentElement.classList.toggle('light',!dark);
  document.documentElement.classList.toggle('auto',theme === 'auto');
  document.querySelector('meta[name="theme-color"]').content = dark ? '#111827' : '#f9fafb';
  const themeLabel = `主题：${{auto:'自动',light:'浅色',dark:'深色'}[theme]}，切换明暗主题`;
  $('theme-toggle').setAttribute('aria-label',themeLabel);
  $('theme-toggle').title = themeLabel;
}
$('theme-toggle').addEventListener('click',() => {
  theme = {auto:'light',light:'dark',dark:'auto'}[theme];
  try {localStorage.setItem('theme',theme);} catch { /* Theme is still usable for this visit. */ }
  applyTheme();
});
media.addEventListener('change',applyTheme);
applyTheme();

function portrait(character,status) {
  const wrap = document.createElement('span');
  wrap.className = 'portrait-wrap relative isolate';
  const image = document.createElement('img');
  image.className = 'portrait aspect-square w-full object-cover';
  image.alt = '';
  image.width = image.height = 80;
  image.loading = 'lazy';
  image.src = imageSources(character.slug)[1];
  wrap.append(image);
  if (character.canSA === true) {
    const star = document.createElement('img');
    star.className = 'sa-mark';
    star.width = star.height = 24;
    star.alt = status === 'awakened' ? '已星导' : '未星导';
    star.src = imageSources('__stellar__')[1];
    wrap.append(star);
  }
  return wrap;
}
function characterIcons(character) {
  const row = document.createElement('span');
  row.className = 'character-icons -mx-0.5 flex items-center';
  const addIcon = (group, value, size, alt, className = '') => {
    if (!value) return;
    const image = document.createElement('img');
    image.src = `https://res.cloudinary.com/ryanditjia/image/upload/dpr_2.0/c_lfill,h_${size},w_${size}/q_auto:low/f_auto/v1/another-eden/${group}/${encodeURIComponent(value)}`;
    image.width = image.height = size;
    image.loading = 'lazy';
    image.alt = alt;
    image.className = className;
    row.append(image);
  };
  const elements = character.elements ?? [];
  const crowded = elements.length > 2;
  elements.forEach((element,index) => addIcon('elements',element,18,`${element} element`,index ? (crowded ? '-ml-2.25' : '-ml-1') : ''));
  addIcon('light-shadow',character.lightShadow,16,character.lightShadow);
  addIcon('weapons',character.weapon,18,character.weapon,crowded ? '-ml-px' : '');
  addIcon('armors',character.armor,18,character.armor,crowded ? '-ml-0.5' : '');
  return row;
}
function buildCards() {
  cards.clear();
  for (const character of catalog.characters) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'character-card';
    card.dataset.slug = character.slug;
    card.append(portrait(character,store.getStatus(character.slug)));
    const name = document.createElement('span');
    name.className = 'character-name text-sm'; name.textContent = displayName(character);
    card.append(name,characterIcons(character));
    card.addEventListener('click',() => openCharacter(character));
    cards.set(character.slug,card);
  }
}
function render() {
  const stats = store.getStats();
  $('owned-count').textContent = stats.owned;
  $('total-count').textContent = stats.total;
  $('awakened-count').textContent = stats.awakened;
  $('sa-count').textContent = stats.canSA;
  const fragment = document.createDocumentFragment();
  let count = 0;
  for (const character of catalog.characters) {
    const status = store.getStatus(character.slug);
    const card = cards.get(character.slug);
    card.dataset.status = status;
    card.setAttribute('aria-label',`${displayName(character)}，${labels[status]}，设置状态`);
    const star = card.querySelector('.sa-mark');
    if (star) star.alt = status === 'awakened' ? '已星导' : '未星导';
    if (matchesCharacter(character,filters,status)) {fragment.append(card);count++;}
  }
  $('character-grid').replaceChildren(fragment);
  $('character-grid').setAttribute('aria-busy','false');
  $('empty-state').hidden = count !== 0;
  document.querySelectorAll('[data-status-filter]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.statusFilter === filters.status)));
  $('keyword').value = filters.keyword;
  const active = Boolean(filters.keyword || filters.status !== 'all' || filters.rolesMatch !== 'all' || filters.personalitiesMatch !== 'all' || Object.keys(dimensions).some(key => filters[key].length));
  $('clear-filters').classList.toggle('opacity-0',!active);
  $('clear-filters').classList.toggle('pointer-events-none',!active);
  $('clear-filters').tabIndex = active ? 0 : -1;
  $('clear-keyword').classList.toggle('opacity-0',!filters.keyword);
  for (const key of Object.keys(dimensions)) {
    const detail = document.querySelector(`[data-dimension="${key}"]`);
    detail.querySelector('.filter-count').textContent = filters[key].length;
    detail.querySelector('.filter-count').hidden = !filters[key].length;
    detail.querySelectorAll('.filter-options input[type=checkbox]').forEach(input => {input.checked = filters[key].includes(input.value);});
    const match = detail.querySelector('[data-match-mode]');
    if (match) {
      match.checked = filters[key+'Match'] === 'all';
      detail.querySelector('.match-description').textContent = match.checked ? '且（全部满足）' : '或（满足任一）';
    }
  }
  document.querySelectorAll('.filter-dimension[open]').forEach(positionFilterPanel);
}
function updateURL() {
  const search = publicFilterSearch(filters);
  try {history.replaceState(null,'',location.pathname+(search ? '?'+search : '')+location.hash);} catch { /* Filtering still works when history is restricted. */ }
}
function changed() { updateURL(); render(); }
function buildFilters() {
  const options = filterOptions(catalog.characters);
  const host = $('dimension-filters'); host.replaceChildren();
  const buttonClass = 'group inline-flex cursor-pointer items-center justify-center rounded-md p-2 text-sm font-medium text-gray-700 outline-hidden transition-colors duration-100 ease-in-out hover:bg-gray-200 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-900 dark:hover:text-gray-100';
  const checkboxClass = 'col-start-1 row-start-1 cursor-pointer appearance-none rounded-sm border border-gray-300 bg-white checked:border-gray-600 checked:bg-gray-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-600 dark:border-gray-600 dark:bg-gray-700 dark:checked:border-gray-400 dark:checked:bg-gray-400 dark:focus-visible:outline-gray-400 forced-colors:appearance-auto';
  for (const [key,title] of Object.entries(dimensions)) {
    const detail = document.createElement('details'); detail.className = 'filter-dimension relative inline-block text-left'; detail.dataset.dimension = key;
    const summary = document.createElement('summary'); summary.className = buttonClass;
    const name = document.createElement('span');name.textContent = title;
    const count = document.createElement('span');count.className = 'filter-count ml-1.5 rounded-sm bg-gray-200 px-1.5 py-0.5 text-xs font-semibold text-gray-700 tabular-nums dark:bg-gray-700 dark:text-gray-200';count.hidden = true;
    summary.append(name,count);
    summary.insertAdjacentHTML('beforeend','<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-chevron-down -mr-1 ml-1 shrink-0 text-gray-400 group-hover:text-gray-500 dark:text-gray-500 dark:group-hover:text-gray-400" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>');
    const panel = document.createElement('div'); panel.className = 'filter-panel absolute z-20 mt-2 mr-2 rounded-md bg-white p-2 shadow-lg ring-1 ring-gray-200 focus:outline-hidden dark:bg-gray-800 dark:ring-white/10'; panel.setAttribute('aria-label',title+'筛选');
    if (key === 'roles' || key === 'personalities') {
      const modeLabel = document.createElement('label'); modeLabel.className = 'match-mode';
      const text = document.createElement('span');
      const label = document.createElement('span');label.className = 'match-label';label.textContent = '匹配全部？';
      const description = document.createElement('small');description.className = 'match-description';
      text.append(label,description);
      const control = document.createElement('span');control.className = 'match-switch';
      const input = document.createElement('input');input.type = 'checkbox';input.name = key+'Match';input.dataset.matchMode = key;input.setAttribute('role','switch');input.setAttribute('aria-label',title+'匹配全部');
      const track = document.createElement('span');track.className = 'match-track';control.append(input,track);
      input.addEventListener('change',() => {filters[key+'Match'] = input.checked ? 'all' : 'any';changed();});
      modeLabel.append(text,control);panel.append(modeLabel);
    }
    const optionList = document.createElement('div');optionList.className = 'filter-options';
    for (const option of options[key]) {
      const label = document.createElement('label');label.className = 'flex cursor-pointer items-center rounded-md bg-transparent p-2 transition-colors duration-100 ease-in-out hover:bg-gray-100 dark:hover:bg-gray-900';
      const checkWrap = document.createElement('span');checkWrap.className = 'filter-checkbox group grid size-4 shrink-0 grid-cols-1';
      const input = document.createElement('input');input.type='checkbox';input.name=key;input.value=option.value;input.className = checkboxClass;
      checkWrap.append(input);
      checkWrap.insertAdjacentHTML('beforeend','<svg fill="none" viewBox="0 0 14 14" class="pointer-events-none col-start-1 row-start-1 size-3.5 self-center justify-self-center stroke-white dark:stroke-gray-900" aria-hidden="true"><path d="M3 8L6 11L11 3.5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="opacity-0 group-has-checked:opacity-100"></path></svg>');
      const text = document.createElement('span');text.className = 'w-full pr-6 pl-3 font-light whitespace-nowrap text-gray-900 select-none md:text-sm dark:text-gray-100';
      if (key === 'elements' || key === 'weapons') {
        const icon = document.createElement('img');icon.width=icon.height=18;icon.alt='';icon.src=`https://res.cloudinary.com/ryanditjia/image/upload/dpr_2.0/c_lfill,h_18,w_18/q_auto:low/f_auto/v1/another-eden/${key}/${encodeURIComponent(option.value)}`;
        text.classList.add('flex','items-center','gap-1');text.append(icon);
      }
      text.append(option.label);label.append(checkWrap,text);
      input.addEventListener('change',() => {filters[key] = input.checked ? [...filters[key],input.value] : filters[key].filter(value => value !== input.value);changed();});
      optionList.append(label);
    }
    panel.append(optionList);detail.append(summary,panel);
    detail.addEventListener('toggle',() => {
      summary.setAttribute('aria-expanded',String(detail.open));
      if (detail.open) {host.querySelectorAll('details').forEach(other => {if (other !== detail) other.open=false;});positionFilterPanel(detail);}
    });
    summary.setAttribute('aria-expanded','false');
    host.append(detail);
  }
}
function positionFilterPanel(detail) {
  const panel = detail.querySelector('.filter-panel');
  panel.style.transform = '';
  const rect = panel.getBoundingClientRect();
  const shift = rect.left < 12 ? 12-rect.left : rect.right > innerWidth-12 ? innerWidth-12-rect.right : 0;
  if (shift) panel.style.transform = `translateX(${shift}px)`;
}
window.addEventListener('resize',() => document.querySelectorAll('.filter-dimension[open]').forEach(positionFilterPanel));
document.addEventListener('click',event => {if (!event.target.closest('.filter-dimension')) document.querySelectorAll('.filter-dimension[open]').forEach(detail => {detail.open=false;});});
document.addEventListener('keydown',event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !document.querySelector('dialog[open]')) {event.preventDefault();$('keyword').focus();}
  if (event.key === 'Escape' && !document.querySelector('dialog[open]')) document.querySelectorAll('.filter-dimension[open]').forEach(detail => {detail.open=false;detail.querySelector('summary').focus();});
});
$('keyword').addEventListener('input',() => {filters.keyword = $('keyword').value;if(store) changed();});
function clearFilters() {filters=emptyFilters();if(store) changed();}
$('clear-filters').addEventListener('click',clearFilters);$('clear-empty').addEventListener('click',clearFilters);
document.querySelectorAll('[data-status-filter]').forEach(button => button.addEventListener('click',() => {filters.status=button.dataset.statusFilter;if(store) changed();}));
$('clear-keyword').addEventListener('click',() => {filters.keyword='';if(store) changed();$('keyword').focus();});
window.addEventListener('popstate',() => {const personal = {status:filters.status};filters={...readPublicFilters(location.search),...personal};if(store) render();});

function refreshStateDialog() {
  const character = selectedCharacter, status = store.getStatus(character.slug);
  $('state-title').textContent = `${displayName(character)} · ${character.style || 'NS'}`;
  $('state-avatar').replaceChildren(portrait(character,status));
  $('state-avatar').dataset.status = status;
  $('state-current').textContent = `当前状态：${labels[status]}`;
  $('sa-unavailable').hidden = character.canSA === true;
  for (const button of document.querySelectorAll('[data-set-status]')) {
    button.disabled = pendingWrites.has($('state-dialog')) || (button.dataset.setStatus === 'awakened' && character.canSA !== true);
    button.setAttribute('aria-pressed',String(status === button.dataset.setStatus));
    if (button.dataset.setStatus === 'awakened') {
      if (button.disabled) button.setAttribute('aria-describedby','sa-unavailable');else button.removeAttribute('aria-describedby');
    }
    if (button.dataset.setStatus === 'owned') button.querySelector('small').textContent = character.canSA === true ? '已拥有，尚未星导' : '已拥有该角色形态';
  }
}
function openCharacter(character) {
  selectedCharacter = character;notice($('state-error'),'');refreshStateDialog();showDialog($('state-dialog'));
  const current = $('state-dialog').querySelector('[aria-pressed="true"]');current?.focus();
}
document.querySelectorAll('[data-set-status]').forEach(button => button.addEventListener('click',async () => {
  const slug = selectedCharacter.slug, status = button.dataset.setStatus;
  const result = await saveWithLock($('state-dialog'),() => store.setStatus(slug,status));
  if (!result) return;
  if (!result.ok) {showStoreResult(result);notice($('state-error'),result.error?.message || '保存失败，请重试。');return;}
  showStoreResult(result);render();$('state-dialog').close();notify('角色状态已保存');
}));
window.addEventListener('storage',event => {
  if (event.key === 'theme') {theme = ['light','dark','auto'].includes(event.newValue) ? event.newValue : 'auto';applyTheme();}
  if (store && (event.key === COLLECTION_STORAGE_KEY || event.key === null)) {
    // Storage events can queue behind a newer local write. Read the current
    // record instead of adopting an event's potentially stale snapshot.
    const result = store.load();showStoreResult(result);render();
    if ($('state-dialog').open) refreshStateDialog();
    if (result.ok) notify('已同步其他标签页的记录');
  }
});

function dataFilename() {
  const date = new Date(), pad = value => String(value).padStart(2,'0');
  return `another-tier-图鉴数据-${date.getFullYear()}${pad(date.getMonth()+1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}.json`;
}
function downloadBlob(blob,filename) {
  const url = URL.createObjectURL(blob), link = document.createElement('a');
  link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();
  setTimeout(() => URL.revokeObjectURL(url),30000);
}
$('export-data').addEventListener('click',() => {
  try {
    const raw = lastStoreResult?.blocked ? store.getRecoverableRaw() : null;
    const text = raw ?? JSON.stringify(store.exportSnapshot(),null,2);
    downloadBlob(new Blob([text],{type:'application/json;charset=utf-8'}),dataFilename());
    notify(raw !== null ? '已导出保留的原始记录，请妥善保存' : '图鉴数据已导出');
  } catch (error) {notify('导出失败：'+error.message);}
});
$('import-data').addEventListener('click',() => {$('import-file').value='';$('import-file').click();});
$('import-file').addEventListener('change',async () => {
  const file = $('import-file').files?.[0];if(!file) return;
  const generation = ++importGeneration;
  preview=undefined;notice($('import-error'),'');$('import-summary').replaceChildren();$('confirm-import').disabled=true;
  showDialog($('import-dialog'));
  try {
    if(file.size>MAX_IMPORT_BYTES) throw new Error('数据文件不能超过 2 MiB。');
    const text=await file.text();if(!$('import-dialog').open || generation !== importGeneration) return;
    preview=store.prepareImport(text);
    const {summary,corrections}=preview;
    const rows=[`有效角色记录：${summary.importedKnownCount} 个（当前目录 ${summary.knownCount} 个）`,`已星导 ${summary.counts.awakened} · 拥有 ${summary.counts.owned} · 未拥有 ${summary.counts.unowned}`,`未识别角色：${summary.unknownCount} 个，将保留在备份中`];
    if (summary.importedKnownCount<summary.knownCount) rows.push(`缺少的 ${summary.knownCount-summary.importedKnownCount} 个当前角色将设为未拥有。`);
    if(corrections.length) rows.push(`${corrections.length} 个未开放星导的形态将从“已星导”修正为“拥有”。`);
    if(preview.sourceCatalogVersion!==catalog.catalogVersion) rows.push('备份与当前目录版本不同，将按角色标识恢复记录。');
    for(const text of rows){const p=document.createElement('p');p.textContent=text;$('import-summary').append(p);}
    $('confirm-import').disabled=false;
  }catch(error){if(generation === importGeneration && $('import-dialog').open) notice($('import-error'),error.message);}
});
$('confirm-import').addEventListener('click',async () => {
  if(!preview) return;
  const confirmedPreview = preview;
  const result=await saveWithLock($('import-dialog'),() => store.commitImport(confirmedPreview));
  if(!result) return;
  if(!result.ok){showStoreResult(result);notice($('import-error'),result.error?.message || '保存失败，原记录保持不变。');return;}
  showStoreResult(result);render();$('import-dialog').close();notify('图鉴数据已覆盖导入');
});
function releaseImage() {
  $('image-preview').removeAttribute('src');$('image-download').removeAttribute('href');
  if(imageURL){URL.revokeObjectURL(imageURL);imageURL=undefined;}
}
async function runImageExport() {
  if(imageBusy) return;
  const statusFilter=filters.status;
  const scope={all:'完整图鉴',owned:'已拥有角色图鉴',unowned:'未拥有角色图鉴'}[statusFilter];
  const range={all:'全部角色',owned:'全部已拥有角色（含已星导）',unowned:'全部未拥有角色'}[statusFilter];
  $('image-title').textContent=`导出${scope}`;
  $('image-description').textContent=`包含${range}，不受搜索、属性等筛选影响。图片比例为 9:21。`;
  $('image-preview').alt=`${scope}预览`;
  imageBusy=true;$('export-image').disabled=true;$('retry-image').hidden=true;$('image-result').hidden=true;releaseImage();
  notice($('image-error'),'');$('image-progress-bar').hidden=false;$('image-progress-bar').value=0;
  $('image-progress').textContent=`正在准备${range}…`;imageController=new AbortController();
  const controller=imageController;
  const statuses=Object.fromEntries(catalog.characters.map(character => [character.slug,store.getStatus(character.slug)]));
  try{
    const result=await exportCollectionImage({characters:catalog.characters,statuses,statusFilter,signal:controller.signal,onProgress:progress=>{
      if(controller.signal.aborted) return;
      $('image-progress').textContent=progress.message;$('image-progress-bar').value=progress.percent;
    }});
    if(controller.signal.aborted||!$('image-dialog').open) return;
    imageURL=URL.createObjectURL(result.blob);$('image-preview').src=imageURL;$('image-download').href=imageURL;$('image-download').download=result.filename;
    $('image-result').hidden=false;$('image-progress').textContent=`${scope}已生成 · ${result.count} 个形态 · ${result.width} × ${result.height}`;$('image-progress-bar').hidden=true;
    $('image-download').click();
  }catch(error){
    if(controller.signal.aborted) return;
    notice($('image-error'),error.message || '图片生成失败，请重试。');$('image-progress').textContent='图片未生成，角色记录保持不变。';$('image-progress-bar').hidden=true;$('retry-image').hidden=false;
  }finally{
    imageBusy=false;$('export-image').disabled=false;
  }
}
$('export-image').addEventListener('click',() => {showDialog($('image-dialog'));runImageExport();});
$('retry-image').addEventListener('click',runImageExport);
window.addEventListener('pagehide',() => {catalogController?.abort();imageController?.abort();releaseImage();});

async function initialize() {
  catalogController?.abort();
  const controller = catalogController = new AbortController();
  $('catalog-error').hidden=true;
  try{
    const result = await loadCollectionCatalog({signal:controller.signal});
    if (controller.signal.aborted) return;
    catalog=result.catalog;
    store=createCollectionStore(catalog);showStoreResult(store.load());
    buildFilters();buildCards();render();
    for(const id of ['export-data','import-data','export-image']) $(id).disabled=false;
  }catch(error){
    if (controller.signal.aborted) return;
    $('catalog-error').hidden=false;$('character-grid').setAttribute('aria-busy','false');
    $('catalog-error').querySelector('p').textContent='角色目录加载失败：'+error.message+'。请重新加载。';
  }
}
$('reload-catalog').addEventListener('click',initialize);
window.addEventListener('pageshow',event => {if(event.persisted && !catalog) initialize();});
initialize();
