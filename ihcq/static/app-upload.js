/* IHCq · upload queue, whole-slide jobs, demo fields
   Classic scripts loaded in order; top-level declarations are shared across files. */
"use strict";
/* ---------- upload queue ---------- */
const drop = $("#drop"), file = $("#file"), queue = $("#queue");
drop.onclick = () => file.click(); drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } };
file.onchange = () => { enqueue([...file.files]); file.value = ""; };
["dragenter", "dragover"].forEach(ev => document.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => document.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
document.addEventListener("drop", e => enqueue([...e.dataTransfer.files].filter(f => f.type.startsWith("image/") || /\.tiff?$/i.test(f.name))));
let running = false; const pending = [];
function enqueue(files) { for (const f of files) { const li = document.createElement("li"); li.innerHTML = `<span class="nm">${f.name}</span><span class="st">queued</span>`; queue.prepend(li); pending.push({ f, li }); } pump(); }
async function pump() {
  if (running) return; running = true;
  while (pending.length) {
    const { f, li } = pending.shift(); const st = $(".st", li); st.textContent = $("#backend").value === "watershed" ? "scoring" : "scoring · model"; st.className = "st busy";
    try { let j = null;
      if (/\.(svs|ndpi|scn|btf)$/i.test(f.name) || (/\.tiff?$/i.test(f.name) && f.size > 30e6)) j = await scoreSlide(f, st);
      if (!j) { const r = await fetch("/api/score?" + settingsQuery(f.name), { method: "POST", body: f }); j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); }
      st.textContent = "H " + fmt(j.summary.h_score, 0); st.className = "st done"; li.onclick = () => show(j.id); li.dataset.id = j.id; add(j); show(j.id); }
    catch (err) { st.textContent = "failed"; st.className = "st err"; li.title = err.message; toast(f.name + ": " + err.message, true); }
  }
  running = false;
}
async function scoreSlide(f, st) {
  st.textContent = `uploading ${(f.size / 1e6).toFixed(0)} MB`;
  const r = await fetch("/api/slide?" + settingsQuery(f.name), { method: "POST", body: f }); const d = await r.json();
  if (!r.ok) { if (/not a tiled/.test(d.error || "")) return null; throw new Error(d.error || r.statusText); }
  for (;;) { await new Promise(z => setTimeout(z, 1000)); const jr = await (await fetch("/api/job?id=" + d.job)).json();
    if (jr.state === "error") throw new Error(jr.error); if (jr.state === "done") return jr.result;
    st.textContent = jr.total ? `tile ${jr.done} / ${jr.total}` : jr.stage; }
}
/* demo menu */
const menu = $("#demo-menu"); $("#demo").onclick = e => { e.stopPropagation(); menu.hidden = !menu.hidden; }; document.addEventListener("click", () => menu.hidden = true);
$("#demo").ondblclick = () => $$("button", menu)[0].click();
$$("button", menu).forEach(b => b.onclick = async () => { menu.hidden = true; if (b.dataset.kind === "real" && $("#preset").value !== "membrane" && $("#preset").value !== "her2") { $("#preset").value = "membrane"; $("#preset").dispatchEvent(new Event("change")); toast("Preset switched to Membrane marker for this stain"); }
  if (b.dataset.kind !== "real" && $("#preset").value !== "nuclear") { $("#preset").value = "nuclear"; $("#preset").dispatchEvent(new Event("change")); toast("Preset switched to Nuclear marker — the synthetic fields are nuclear-stained"); } const li = document.createElement("li"); li.innerHTML = `<span class="nm">demo · ${b.textContent}</span><span class="st busy">scoring</span>`; queue.prepend(li); try { const r = await fetch(`/api/demo?kind=${b.dataset.kind}&` + settingsQuery()); const j = await r.json(); if (!r.ok) throw new Error(j.error); $(".st", li).textContent = "H " + fmt(j.summary.h_score, 0); $(".st", li).className = "st done"; li.onclick = () => show(j.id); li.dataset.id = j.id; add(j); show(j.id); } catch (err) { $(".st", li).textContent = "failed"; $(".st", li).className = "st err"; toast(err.message, true); } });
/* quit completely when the window closes: hold a presence stream open, say goodbye on the way out (a reload reconnects in time) */
const presence = new EventSource("/api/presence");
addEventListener("pagehide", e => { if (!e.persisted) navigator.sendBeacon("/api/closing"); });
$("#quit").onclick = async () => { presence.close(); await fetch("/api/quit", { method: "POST" }); document.body.innerHTML = '<p style="padding:40px;font:15px system-ui">IHCq stopped. You can close this tab.</p>'; };

/* a reload keeps the session: the server still holds every result, so rebuild the list, badge and charts from it */
addEventListener("DOMContentLoaded", async () => { try { const r = await fetch("/api/session?full=1"); const d = await r.json(); if (!r.ok || !d.results || !d.results.length) return;
  for (const j of d.results) { add(j); if (j.summary.roi_polygons) state.rois[j.id] = j.summary.roi_polygons;
    if (j.measure_regions) { state.measure[j.id] = { regions: j.measure_regions.map((g, i) => ({ ...g, color: MCOL[i % MCOL.length] })), sel: 0 }; if (j.measure) state.mres[j.id] = { ...j.measure, byName: Object.fromEntries(j.measure.regions.map(g => [g.name, g])) }; }
    const li = document.createElement("li"); li.innerHTML = `<span class="nm"></span><span class="st done">H ${fmt(j.summary.h_score, 0)}</span>`; $(".nm", li).textContent = j.summary.image; li.dataset.id = j.id; li.onclick = () => show(j.id); queue.prepend(li); }
  show(d.results[d.results.length - 1].id); } catch (e) { /* a fresh start has nothing to restore */ } });
