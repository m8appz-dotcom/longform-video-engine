import { runEngine, engineAction, showEngineResult } from "./engine-client.js";
import {
  $,
  $$,
  esc,
  load,
  save,
  draw,
  modal,
  notify,
  download,
  words,
  sha256,
  access,
  wireAccess,
} from "./core.js";
import { film } from "./data.js";
const blank = {
  title: film.title,
  chapters: structuredClone(film.chapters),
  locked: false,
  hash: null,
  wpm: 145,
};
const valid = (s) =>
  s &&
  typeof s.title === "string" &&
  s.title.length <= 200 &&
  Array.isArray(s.chapters) &&
  s.chapters.length === 2 &&
  s.chapters.every(
    (c, i) =>
      c.id === `C0${i + 1}` &&
      typeof c.title === "string" &&
      c.title.length <= 150 &&
      typeof c.spoken_text === "string" &&
      c.spoken_text.length <= 20000,
  ) &&
  Number.isFinite(s.wpm) &&
  s.wpm >= 105 &&
  s.wpm <= 200 &&
  typeof s.locked === "boolean" &&
  (!s.locked || /^[a-f0-9]{64}$/.test(s.hash));
let state = load("film", blank, valid),
  chapter = 0,
  view = "frame";
const canonical = () =>
  state.chapters
    .map((c) => c.spoken_text.trim())
    .join("\n\n")
    .trim();
const engineInput = () => ({
  title: state.title,
  chapters: structuredClone(state.chapters),
  wpm: state.wpm,
});
function change(field, value) {
  state.chapters[chapter][field] = value;
  state.locked = false;
  state.hash = null;
  save("film", state);
}
function duration(ch) {
  return Math.ceil((words(ch.spoken_text) / state.wpm) * 60);
}
function time(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
function render() {
  const c = state.chapters[chapter],
    total = state.chapters.reduce((sum, ch) => sum + duration(ch), 0);
  const stage =
    view === "frame"
      ? `<div class="film-original"><img src="assets/render-frame.png" alt="Original test frame reading Keep the script locked"><p>Original test frame · C01. No finished video or narration is included.</p></div>`
      : view === "edit"
        ? `<form class="film-editor" id="film-editor"><label for="chapter-title">Chapter title</label><input id="chapter-title" maxlength="150" value="${esc(c.title)}"><label for="chapter-script">Spoken script</label><textarea id="chapter-script" maxlength="20000">${esc(c.spoken_text)}</textarea><p class="film-edit-status">${words(c.spoken_text)} words · ${state.locked ? "Script locked" : "Changes need a new script lock"}</p><div class="action-row"><button class="film-action" type="submit">Save chapter</button><button class="text-button" type="button" data-restore>Restore English example</button></div></form>`
        : view === "shots"
          ? `<div class="film-shot-plan"><h1>${esc(c.title)}</h1><p>${time(duration(c))} estimated narration at ${state.wpm} words/minute.</p>${c.spoken_text
              .split(/\n\n/)
              .filter(Boolean)
              .map(
                (p, i) =>
                  `<article><span class="mono">${c.id} / SHOT 0${i + 1}</span><h2>${i === 0 ? "Show the working example." : "Keep the evidence visible."}</h2><p>${esc(p)}</p><span class="quiet">Footage not selected</span></article>`,
              )
              .join(
                "",
              )}<p>Shot suggestions organize this example. They do not generate or select footage.</p></div>`
          : `<div class="film-reading"><h1>${esc(c.title)}</h1>${c.spoken_text
              .split(/\n\n/)
              .map((p) => `<p>${esc(p)}</p>`)
              .join("")}</div>`;
  draw(
    `<main id="main" class="film-shell"><header class="film-header"><strong>LONGFORM</strong><span>${esc(state.title)}</span>${access()}</header><div class="film-workspace"><nav class="film-index" aria-label="Chapters"><span class="film-index-title">Chapter index</span>${state.chapters.map((ch, i) => `<button data-chapter="${i}" aria-current="${i === chapter ? "page" : "false"}"><span class="mono">0${i + 1}</span><span>${esc(ch.title)}</span></button>`).join("")}<div class="film-index-bottom"><span>${state.locked ? "Script locked" : "Working script"} · ${time(total)} estimated</span><button data-full>Read full script ↗</button><label class="reading-speed">Reading pace<select id="reading-speed" aria-label="Reading pace">${[120, 145, 170].map((n) => `<option value="${n}" ${state.wpm === n ? "selected" : ""}>${n} words / min</option>`).join("")}</select></label><button class="film-action" data-lock ${state.locked ? "disabled" : ""}>${state.locked ? "Script locked" : "Lock script revision"}</button><button data-contract ${!state.locked ? "disabled" : ""}>Export locked script ↓</button><button data-engine-render ${!state.locked ? "disabled" : ""}>Render chapter preview</button></div></nav><section class="film-preview" aria-label="Chapter workspace"><div class="film-preview-head"><span>${{ frame: "Original test frame · C01", read: "Script", edit: "Edit chapter", shots: "Shot plan" }[view]}</span><span class="mono">${view === "frame" ? "C01" : c.id} / 02</span></div>${stage}<nav class="film-view-switch" aria-label="Chapter views">${[
      ["frame", "Original frame"],
      ["read", "Read"],
      ["edit", "Edit script"],
      ["shots", "Shot plan"],
    ]
      .map(
        ([id, title]) =>
          `<button data-view="${id}" aria-pressed="${view === id}">${title}</button>`,
      )
      .join(
        "",
      )}</nav></section></div><footer class="film-footer"><span>English example · saved in this browser</span><span>Narration and selected footage remain outside this demo.</span><button data-export>Export draft ↓</button></footer></main>`,
    () => {
      $$("[data-chapter]").forEach(
        (b) =>
          (b.onclick = () => {
            chapter = Number(b.dataset.chapter);
            view = "read";
            render();
          }),
      );
      $$("[data-view]").forEach(
        (b) =>
          (b.onclick = () => {
            view = b.dataset.view;
            render();
          }),
      );
      $("#reading-speed").onchange = (e) => {
        state.wpm = Number(e.target.value);
        save("film", state);
        render();
      };
      $("[data-full]").onclick = () =>
        modal(
          state.title,
          state.chapters
            .map(
              (ch) =>
                `<h2>${esc(ch.title)}</h2>${ch.spoken_text
                  .split(/\n\n/)
                  .map((p) => `<p>${esc(p)}</p>`)
                  .join("")}<br>`,
            )
            .join(""),
        );
      $("#chapter-title")?.addEventListener("input", (e) => {
        change("title", e.target.value);
        $(".film-edit-status").textContent =
          "Changes saved locally · script lock reset";
        $("[data-lock]").disabled = false;
        $("[data-lock]").textContent = "Lock script revision";
        $("[data-contract]").disabled = true;
      });
      $("#chapter-script")?.addEventListener("input", (e) => {
        change("spoken_text", e.target.value);
        $(".film-edit-status").textContent =
          `${words(e.target.value)} words · saved locally · script lock reset`;
        $("[data-lock]").disabled = false;
        $("[data-lock]").textContent = "Lock script revision";
        $("[data-contract]").disabled = true;
      });
      $("#film-editor")?.addEventListener("submit", (e) => {
        e.preventDefault();
        if (!c.title.trim() || !c.spoken_text.trim()) {
          notify("Add a chapter title and script before saving.", true);
          return;
        }
        if (save("film", state)) {
          view = "read";
          render();
          notify("Chapter saved in this browser.");
        }
      });
      $("[data-restore]")?.addEventListener("click", () => {
        state.chapters[chapter] = structuredClone(film.chapters[chapter]);
        state.locked = false;
        state.hash = null;
        save("film", state);
        view = "read";
        render();
        notify("English example restored.");
      });
      $("[data-lock]").onclick = async (e) => {
        const text = canonical(),
          snapshot = JSON.stringify(engineInput());
        const job = await engineAction(
          e.currentTarget,
          "validate",
          engineInput(),
          () => {},
        );
        if (
          !job ||
          text !== canonical() ||
          snapshot !== JSON.stringify(engineInput())
        )
          return;
        state.hash = job.result.contract.script_hash;
        state.locked = true;
        if (save("film", state)) {
          render();
          notify(
            "Script validated and locked by the engine. Editing resets this lock.",
          );
        }
      };
      $("[data-contract]").onclick = (e) =>
        engineAction(e.currentTarget, "validate", engineInput(), (job) => {
          if (!state.locked || job.result.contract.script_hash !== state.hash) {
            notify("The script changed. Lock this revision again.", true);
            return;
          }
          showEngineResult(
            "Locked script contract",
            job,
            `<p>${esc(job.result.scope)}</p>`,
          );
        });
      $("[data-engine-render]").onclick = (e) =>
        engineAction(
          e.currentTarget,
          "render",
          { ...engineInput(), scriptHash: state.hash },
          (job) => {
            const movie = job.files.find((f) => f.mime === "video/mp4");
            showEngineResult(
              "Chapter preview",
              job,
              `<p>${esc(job.result.preview.scope)}</p><video controls playsinline preload="metadata" aria-label="Rendered chapter preview" src="${esc(movie.url)}" class="engine-video"></video>`,
            );
          },
        );
      $("[data-export]").onclick = () =>
        download("longform-draft.json", {
          kind: "authored-english-demo",
          language: "en",
          ...state,
        });
      wireAccess(
        "film",
        () => state,
        (data) => {
          if (!valid(data))
            throw new Error(
              "That workspace is not a compatible longform script.",
            );
          state = data;
          save("film", state);
          render();
        },
      );
    },
  );
}
// A cached lock is rechecked against its content, never trusted solely from a flag.
if (
  state.locked &&
  (await sha256(new TextEncoder().encode(canonical()))) !== state.hash
) {
  state.locked = false;
  state.hash = null;
  save("film", state);
}
render();
