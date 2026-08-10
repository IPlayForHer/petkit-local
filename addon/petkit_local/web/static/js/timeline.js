import { BASE, api, esc } from './core.js';
import { onAction, onChange } from './delegate.js';
import { mediaThumbs, observeLazyVideos, _has } from './media.js';

// ---------------- Timeline ----------------
let TL_DATE = null,
  TL_FILTER = 'all',
  TL_DEVICE = '',
  TL_PET = '',
  TL_MULTIDEV = false;
// Debug state lives at module scope on purpose. #timelineView is re-rendered
// wholesale by loadTimeline(), including 400ms after any websocket media/event
// message, so anything held on an element is lost — but a global survives, and
// sessionCard() re-renders open panels straight from the cache. An event's
// content never changes after ingest, so caching it for the session is safe
// and means a live refresh costs no requests and shows no flicker.
let TL_DEBUG = false;
const TL_DBG_OPEN = new Set();
const TL_DBG_CACHE = new Map();
try {
  TL_DEBUG = localStorage.getItem('tlDebug') === '1';
} catch (_) {
  /* private mode */
}
// The server cuts a timeline day at LOCAL midnight, so "today" here must mean
// the same thing. toISOString() is UTC, so east of Greenwich it named
// tomorrow's date late in the evening and yesterday's just after midnight —
// the date picker and the data it fetched disagreed about which day it was.
function todayLocal() {
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// A pet filter chip, carrying the same mugshot the cards below it show — the
// first registered face, which is what `_pet_badge` uses server-side. A photo
// that fails to load hides itself rather than leaving a broken-image glyph in
// the middle of the chip.
function petChip(p) {
  const face = (p.faces || [])[0];
  return `<button class="chip-btn${String(p.id) === TL_PET ? ' on' : ''}" data-action="tl-pet" data-k="${esc(p.id)}">${
    face
      ? `<img class="chip-av hide-on-error" src="${BASE}${esc(face.url)}" alt="">`
      : '<span class="chip-av chip-av-none">🐾</span>'
  }${esc(p.name)}</button>`;
}

async function loadTimeline() {
  if (!TL_DATE) TL_DATE = todayLocal();
  const [ds, pd] = await Promise.all([api('devices'), api('pets').catch(() => ({}))]);
  const pets = pd.pets || [];
  // Only worth repeating the device name per-card when there's more than one.
  TL_MULTIDEV = ds.length > 1;
  // A pet that has been deleted must not keep filtering the view to nothing.
  if (TL_PET && !pets.some(p => String(p.id) === TL_PET)) TL_PET = '';
  const q = new URLSearchParams({ filter: TL_FILTER, date: TL_DATE });
  if (TL_DEVICE) q.set('device', TL_DEVICE);
  if (TL_PET) q.set('pet', TL_PET);
  const data = await api('timeline?' + q.toString());
  const v = document.getElementById('timelineView');
  const filters = [
    ['all', 'All'],
    ['pet', 'Pet'],
    ['toileting', 'Toileting'],
    ['health_alert', 'Health Alert'],
    ['fault', 'Faults'],
  ];
  v.innerHTML = `<div class="card">
    <div class="row" style="align-items:center;margin-bottom:10px">
      <button class="ghost act" data-action="tl-shift" data-n="-1">◂</button>
      <input type="date" id="tlDate" value="${esc(TL_DATE)}" data-change="tl-date" style="width:auto">
      <button class="ghost act" data-action="tl-shift" data-n="1" ${TL_DATE >= todayLocal() ? 'disabled' : ''}>▸</button>
      <select id="tlDevice" data-change="tl-device" style="width:auto">
        <option value="">All devices</option>
        ${ds.map(d => `<option value="${esc(d.id)}" ${String(d.id) === TL_DEVICE ? 'selected' : ''}>${esc(d.name)} #${esc(d.id)}</option>`).join('')}
      </select>
      <span class="grow"></span>
    </div>
    ${
      pets.length
        ? `<div class="row tl-filterbar" style="align-items:center">
      <div class="chips" role="group" aria-label="Filter by pet">
        <button class="chip-btn${TL_PET === '' ? ' on' : ''}" data-action="tl-pet" data-k="">All pets</button>
        ${pets.map(petChip).join('')}
      </div>
      <span class="grow"></span>
    </div>`
        : ''
    }
    <div class="row tl-filterbar" style="align-items:center">
      <div class="chips">
        ${filters.map(([k, label]) => `<button class="chip-btn${TL_FILTER === k ? ' on' : ''}" data-action="tl-filter" data-k="${k}">${esc(label)}<span class="chip-n">${esc(data.counts[k] ?? 0)}</span></button>`).join('')}
      </div>
      <span class="grow"></span>
      <label class="mut tl-dbgtog"><input type="checkbox" ${TL_DEBUG ? 'checked' : ''} data-change="tl-debug"> Debug info</label>
    </div>
  </div>
  ${data.sessions.length ? data.sessions.map(sessionCard).join('') : '<div class="card"><p class="mut">No activity on this day.</p></div>'}`;
  v.classList.toggle('dbg', TL_DEBUG);
  observeLazyVideos();
}
function tlShiftDay(n) {
  const d = new Date(TL_DATE + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  TL_DATE = d.toISOString().slice(0, 10);
  loadTimeline();
}
function tlSetDate(v) {
  TL_DATE = v;
  loadTimeline();
}
function tlSetFilter(k) {
  TL_FILTER = k;
  loadTimeline();
}
function tlSetDevice(v) {
  TL_DEVICE = v;
  loadTimeline();
}
onAction('tl-shift', el => tlShiftDay(Number(el.dataset.n)));
onAction('tl-filter', el => tlSetFilter(el.dataset.k));
onChange('tl-date', el => tlSetDate(el.value));
onChange('tl-device', el => tlSetDevice(el.value));
onAction('tl-pet', el => {
  TL_PET = el.dataset.k;
  loadTimeline();
});
onChange('tl-debug', el => {
  TL_DEBUG = el.checked;
  if (!TL_DEBUG) TL_DBG_OPEN.clear();
  try {
    localStorage.setItem('tlDebug', TL_DEBUG ? '1' : '0');
  } catch (_) {}
  loadTimeline();
});
onAction('tl-dbg', el => toggleDebug(Number(el.dataset.id)));

// Keyed by event_kind (NOT s.kind) — the chip is the thing the card is about.
const KIND_TAG = {
  toilet_visit: 'Toilet',
  pet: 'Appeared',
  motion: 'Motion',
  cleaning: 'Cleaning',
  error: 'Alert',
  feeding: 'Feeding',
  // A fountain's kinds. Without these the chip rendered the raw lowercase
  // string, so every W7H row was the one card on the page not in title case.
  drinking: 'Drinking',
  system: 'System',
};
const KIND_CLASS = { toilet_visit: 'visit', pet: 'pet', motion: 'pet', error: 'error' };
function hhmmss(ts) {
  return ts ? new Date(ts * 1000).toLocaleTimeString() : '';
}

// The timeline's time column is a FIXED grid track, and `toLocaleTimeString()`
// follows the viewer's locale — so "13:23:45" and "1:23:45 PM" have to share
// one width. They don't: a 12-hour time is 3-4 characters longer, and on the
// bold 13px anchor rows it ran past a 70px track by more than the 12px gutter,
// landing on top of the kind pill. `overflow-x: hidden` on <body> hid it.
//
// Widening unconditionally would waste a fifth of a 600px column for everyone
// on a 24-hour locale, and forcing `hour12: false` would override a preference
// that is the viewer's to make. So the track is sized once, from what the
// locale actually resolves to.
(function sizeTimeColumn() {
  let twelve = false;
  try {
    twelve = !!new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' }).resolvedOptions().hour12;
  } catch (_) {
    // Older engine with no resolved `hour12`: measure the rendered string
    // instead. 13:00 is unambiguous — a 12-hour locale renders it with a
    // suffix, a 24-hour one does not.
    twelve = /[AaPp]\.?[Mm]/.test(new Date(2020, 0, 1, 13, 0, 0).toLocaleTimeString());
  }
  if (twelve) document.documentElement.style.setProperty('--tl-time-w', '94px');
})();

// One row = a time in the left gutter + a title (+ optional media below it).
// In debug mode it also carries an "i" toggle, and the panel it opens is
// emitted as a SIBLING of the row: the row is a two-column grid, so a panel
// nested inside it would be trapped in the narrow content column.
function tlRow(ts, titleHtml, media, anchor, id) {
  const dbg = TL_DEBUG && id != null;
  return `<div class="tl-row${anchor ? ' anchor' : ''}">
    <div class="tl-t">${hhmmss(ts)}</div>
    <div>${titleHtml}${dbg ? ` <button class="tl-dbgbtn" data-action="tl-dbg" data-id="${esc(id)}" title="Show what the device actually reported">i</button>` : ''}${media && _has(media) ? `<div class="tl-media">${mediaThumbs(media)}</div>` : ''}</div>
  </div>${dbg ? `<div class="tl-dbg" data-dbg="${esc(id)}">${TL_DBG_OPEN.has(id) ? dbgBody(TL_DBG_CACHE.get(id)) : ''}</div>` : ''}`;
}

async function toggleDebug(id) {
  const box = document.querySelector(`[data-dbg="${CSS.escape(String(id))}"]`);
  if (!box) return;
  if (TL_DBG_OPEN.has(id)) {
    TL_DBG_OPEN.delete(id);
    box.innerHTML = '';
    return;
  }
  TL_DBG_OPEN.add(id);
  if (TL_DBG_CACHE.has(id)) {
    box.innerHTML = dbgBody(TL_DBG_CACHE.get(id));
    return;
  }
  box.innerHTML = '<p class="mut">loading…</p>';
  const d = await api('timeline/' + id);
  TL_DBG_CACHE.set(id, d);
  // The whole view may have been re-rendered while the request was in flight,
  // so re-find the container instead of writing into a detached node — and
  // check the panel is still meant to be open, in case it was toggled shut.
  const live = document.querySelector(`[data-dbg="${CSS.escape(String(id))}"]`);
  if (live && TL_DBG_OPEN.has(id)) live.innerHTML = dbgBody(d);
}

// A decoded field's grade is the honest part of this panel: it says whether we
// are reading a value we have confirmed, one we inferred from captures, one
// the firmware names but we have never seen, or one we are passing through
// without understanding it at all.
function dbgGrade(g) {
  return `<span class="tl-grade ${esc(g || 'unknown')}">${esc(g || 'unknown')}</span>`;
}

function dbgBody(d) {
  if (!d) return '<p class="mut">loading…</p>';
  if (d.error) return `<p class="mut">${esc(d.error)}</p>`;
  const e = d.event || {},
    c = d.code;

  const decoded = (d.decoded || [])
    .map(
      f =>
        `<tr>
      <td>${esc(f.label)}</td><td><b>${esc(f.text)}</b></td>
      <td class="mut"><code>${esc(JSON.stringify(f.raw))}</code></td>
      <td>${dbgGrade(f.grade)}</td></tr>` +
        (f.note
          ? `<tr class="tl-note"><td></td><td colspan="3" class="mut">${esc(f.note)}</td></tr>`
          : ''),
    )
    .join('');

  const meta = [
    ['Event id', e.id],
    ['Code', e.event_type],
    ['Kind', e.event_kind],
    ['Transport', e.source],
    ['Device', [e.device_id, e.device_type].filter(Boolean).join(' · ')],
    ['Received', e.ts ? new Date(e.ts * 1000).toLocaleString() : ''],
    ['Episode', e.related_event],
    ['Parent episode', e.parent_event],
    ['Dedup key', e.event_uid],
    // Reported vs resolved. A ref with no pet means the box is still matching
    // against faces cached from PetKit's cloud — bind it in the Pets tab.
    ['Reported pet id', e.pet_ref],
    ['Pet', e.pet_name || e.pet_id],
    ['Match score', e.score],
  ]
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td colspan="3"><code>${esc(v)}</code></td></tr>`)
    .join('');

  const codeBlock = c
    ? `<table class="tl-dbgt">
      <tr><td>Means</td><td colspan="2"><b>${esc(c.label)}</b></td><td>${dbgGrade(c.grade)}</td></tr>
      ${c.firmware ? `<tr><td>Firmware</td><td colspan="3"><code>${esc(c.firmware)}</code></td></tr>` : ''}
      ${c.note ? `<tr class="tl-note"><td></td><td colspan="3" class="mut">${esc(c.note)}</td></tr>` : ''}
    </table>`
    : '<p class="mut">This code is in no table yet — it will read as a bare "Event N".</p>';

  return `<div class="tl-dbgin">
    <h4>What this code means</h4>${codeBlock}
    <h4>Decoded payload</h4>${
      decoded
        ? `<table class="tl-dbgt">${decoded}</table>`
        : '<p class="mut">The device sent no content.</p>'
    }
    <h4>Event record</h4><table class="tl-dbgt">${meta}</table>
    <details class="adv"><summary>Raw content JSON</summary><pre>${esc(JSON.stringify(d.content || {}, null, 2))}</pre></details>
    <details class="adv"><summary>Raw state snapshot</summary><pre>${esc(JSON.stringify(d.state || {}, null, 2))}</pre></details>
  </div>`;
}

function sessionCard(s) {
  const tag = KIND_TAG[s.event_kind] || (s.event_kind || 'event').replace(/_/g, ' ');
  const cls = KIND_CLASS[s.event_kind] || '';
  // Every fact about the episode reads the same way: "label <b>value</b>",
  // separated by · and kept unbreakable — the line used to wrap between "2.07"
  // and "kg", which reads as two different numbers at a glance.
  //
  // The server-decoded facts (waste weight, litter level, yowling) used to be
  // pills instead, which made them look like a different KIND of thing from
  // the duration and weight beside them. They are not: they are all just what
  // this visit was. Anything less certain than these stays behind Debug.
  const facts = [];
  if (s.kind === 'visit') {
    if (s.duration_sec != null) facts.push(`spent <b>${Math.round(s.duration_sec)}s</b>`);
    if (s.weight != null) facts.push(`weighed <b>${(s.weight / 1000).toFixed(2)} kg</b>`);
  }
  for (const b of s.bits || []) {
    // "waste 42 g" / "litter 40%" / "yowled 12s" — bold from the first digit,
    // matching the pattern above. A bit with no number ("waste", "yowled")
    // has nothing to bold and is printed as-is.
    const m = String(b).match(/^(\D+?)\s+(\d.*)$/);
    facts.push(m ? `${esc(m[1])} <b>${esc(m[2])}</b>` : esc(b));
  }
  const factsHtml = facts.map(f => `<span class="tl-nb">${f}</span>`).join(' · ');

  let title;
  if (s.kind === 'visit') {
    title = factsHtml || '<span class="mut">toilet visit</span>';
  } else {
    title =
      `<span class="mut">${esc(s.label || tag)}</span>` + (factsHtml ? ' · ' + factsHtml : '');
  }
  // Who the device's NPU recognised. Absent when it recognised nobody, which
  // is normal for a passing glance — most "appeared" episodes have no match.
  const pet = s.pet_name
    ? `<span class="tl-pet">${s.pet_photo_url ? `<img src="${BASE}${esc(s.pet_photo_url)}" alt="">` : ''}${esc(s.pet_name)}</span>`
    : '';
  const head = `<span class="tl-kind ${cls}">${esc(tag)}</span>${pet}${title}`;
  const subs = s.sub_events || [];
  const primary = subs.filter(e => !e.detail),
    detail = subs.filter(e => e.detail);

  return `<div class="card tl-card">
    ${TL_MULTIDEV ? `<span class="tl-dev">${esc(s.device_name || '')}</span>` : ''}
    ${tlRow(s.display_ts ?? s.ts, head, s.media, true, s.id)}
    ${primary.map(e => tlRow(e.ts, esc(e.label || e.event_type || ''), e.media, false, e.id)).join('')}
    ${detail.length ? `<details class="tl-more"><summary>show ${detail.length} more step${detail.length > 1 ? 's' : ''}</summary>${detail.map(e => tlRow(e.ts, esc(e.label || e.event_type || ''), e.media, false, e.id)).join('')}</details>` : ''}
  </div>`;
}

let _timelineT = null;
function scheduleTimeline() {
  const tab = document.getElementById('tab-timeline');
  if (!tab || tab.classList.contains('hidden')) return; // not looking at it — nothing to refresh
  clearTimeout(_timelineT);
  _timelineT = setTimeout(loadTimeline, 400);
}

export { loadTimeline, scheduleTimeline };
