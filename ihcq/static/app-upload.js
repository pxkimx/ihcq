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
$$("button", menu).forEach(b => b.onclick = async () => { menu.hidden = true; if (b.dataset.kind === "real" && $("#preset").value !== "membrane" && $("#preset").value !== "her2") { $("#preset").value = "membrane"; $("#preset").dispatchEvent(new Event("change")); toast("Preset switched to Membrane marker for this stain"); } const li = document.createElement("li"); li.innerHTML = `<span class="nm">demo · ${b.textContent}</span><span class="st busy">scoring</span>`; queue.prepend(li); try { const r = await fetch(`/api/demo?kind=${b.dataset.kind}&` + settingsQuery()); const j = await r.json(); if (!r.ok) throw new Error(j.error); $(".st", li).textContent = "H " + fmt(j.summary.h_score, 0); $(".st", li).className = "st done"; li.onclick = () => show(j.id); li.dataset.id = j.id; add(j); show(j.id); } catch (err) { $(".st", li).textContent = "failed"; $(".st", li).className = "st err"; toast(err.message, true); } });
$("#quit").onclick = async () => { await fetch("/api/quit", { method: "POST" }); document.body.innerHTML = '<p style="padding:40px;font:15px system-ui">IHCq stopped. You can close this tab.</p>'; };
