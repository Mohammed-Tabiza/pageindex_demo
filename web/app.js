const $ = (selector) => document.querySelector(selector);
const runButton = $("#run");
const archiveButton = $("#archive");
const questionSelect = $("#question-select");
const questions = new Map();
let archives = {};
const documents = new Map();
const calls = new Map();
const sources = new Map();
let running = false;
let ready = false;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, action, className = "chip") {
  const node = element("button", text, className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

async function fetchData(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("Impossible de joindre le serveur de démonstration.");
  }
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.message);
  }
  return response;
}

function setStatus(text, state = "") {
  $("#status").textContent = text;
  $("#status").className = "notice" + (state ? " " + state : "");
}

const FLAGS = {
  deprecated: ["Obsolète", "bad"],
  stale: ["Périmé", "warn"],
  draft: ["Brouillon", "warn"],
  unverified: ["Non vérifié", "warn"],
};
const TRUST = {
  "human-reviewed": ["Revu par un humain", "ok"],
  "machine-confirmed": ["Confirmé par un processus", "info"],
  unverified: ["Non vérifié", "warn"],
};
let current = null;
let agentView = false;

function badge(text, tone = "") {
  return element("span", text, "badge" + (tone ? " " + tone : ""));
}

function badges(doc, compact = false) {
  const list = [];
  if (!compact) list.push(badge(doc.type, "type"));
  for (const flag of doc.flags) {
    if (compact && flag === "unverified" && doc.flags.length > 1) continue;
    list.push(badge(...FLAGS[flag]));
  }
  if (!compact) {
    if (!doc.flags.includes("unverified")) list.push(badge(...TRUST[doc.trust_tier]));
    for (const tag of doc.tags) list.push(badge("#" + tag, "tag"));
  }
  return list;
}

function date(value) {
  return value ? value.slice(0, 10) : "—";
}

function linkTarget(doc, page, href) {
  const link = doc.links.find((item) => item.href === href && item.section === Number(page));
  return link?.target_doc ? [findDocument(undefined, link.target_doc), link.target_page || 1] : null;
}

// Minimal, DOM-only markdown rendering: no HTML from documents is ever interpreted.
function inline(text, doc, page) {
  const fragment = document.createDocumentFragment();
  const tokens = /\[\^([^\]\s]+)\]|\[([^\]]*)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let offset = 0;
  for (const match of text.matchAll(tokens)) {
    fragment.append(document.createTextNode(text.slice(offset, match.index)));
    if (match[1]) {
      fragment.append(element("sup", "[" + match[1] + "]", "footnote-ref"));
    } else if (match[3] !== undefined) {
      const target = linkTarget(doc, page, match[3]);
      if (target?.[0]) {
        const link = button(match[2], () => showPage(target[0], target[1]), "inline-link");
        link.title = target[0].concept + " · section " + target[1];
        fragment.append(link);
      } else if (/^https?:\/\//.test(match[3])) {
        const link = element("a", match[2]);
        link.href = match[3];
        link.target = "_blank";
        link.rel = "noopener";
        fragment.append(link);
      } else {
        fragment.append(element("span", match[2], "broken-link"));
      }
    } else if (match[4]) {
      fragment.append(element("strong", match[4]));
    } else {
      fragment.append(element("code", match[5]));
    }
    offset = match.index + match[0].length;
  }
  fragment.append(document.createTextNode(text.slice(offset)));
  return fragment;
}

function markdown(text, doc, page) {
  const root = document.createDocumentFragment();
  const lines = text.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      root.append(element("h" + Math.min(heading[1].length + 2, 6), heading[2]));
      i++;
    } else if (/^\s*(```|~~~)/.test(line)) {
      const block = [];
      i++;
      while (i < lines.length && !/^\s*(```|~~~)/.test(lines[i])) block.push(lines[i++]);
      i++;
      root.append(element("pre", block.join("\n")));
    } else if (line.trim().startsWith("|")) {
      const table = element("table");
      for (; i < lines.length && lines[i].trim().startsWith("|"); i++) {
        if (/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) continue;
        const row = element("tr");
        for (const cell of lines[i].trim().replace(/^\||\|$/g, "").split("|")) {
          const node = element(table.rows.length ? "td" : "th");
          node.append(inline(cell.trim(), doc, page));
          row.append(node);
        }
        table.append(row);
      }
      const wrap = element("div", undefined, "table-wrap");
      wrap.append(table);
      root.append(wrap);
    } else if (/^\s*([*-]|\d+\.)\s+/.test(line)) {
      const list = element(/^\s*\d+\./.test(line) ? "ol" : "ul");
      for (; i < lines.length && /^\s*([*-]|\d+\.)\s+/.test(lines[i]); i++) {
        const item = element("li");
        item.append(inline(lines[i].replace(/^\s*([*-]|\d+\.)\s+/, ""), doc, page));
        list.append(item);
      }
      root.append(list);
    } else {
      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*\||\s*([*-]|\d+\.)\s|\s*```)/.test(lines[i])) paragraph.push(lines[i++]);
      const node = element("p");
      node.append(inline(paragraph.join(" "), doc, page));
      root.append(node);
    }
  }
  return root;
}

function metaRow(list, term, value) {
  if (value === undefined || value === null || value === "") return;
  list.append(element("dt", term));
  const detail = element("dd");
  detail.append(value instanceof Node ? value : document.createTextNode(String(value)));
  list.append(detail);
}

function renderSources(doc, section) {
  const used = new Set(section.footnotes);
  const list = element("ul", undefined, "sources");
  for (const source of doc.sources) {
    const item = element("li");
    if (source.id && used.has(source.id)) item.className = "cited";
    const label = source.title || source.resource;
    if (/^https?:\/\//.test(source.resource || "")) {
      const link = element("a", label);
      link.href = source.resource;
      link.target = "_blank";
      link.rel = "noopener";
      item.append(link);
    } else {
      item.append(element("span", label));
    }
    const facts = [source.id && "[^" + source.id + "]", source.author,
      source.usage_count !== undefined && source.usage_count + " usages",
      source.last_modified && "modifiée le " + date(source.last_modified)].filter(Boolean);
    if (facts.length) item.append(element("small", " · " + facts.join(" · ")));
    list.append(item);
  }
  return doc.sources.length ? list : "aucune source déclarée";
}

function showPage(doc, page) {
  const section = doc?.sections.find((item) => String(item.page) === String(page));
  if (!section) return;
  current = { doc, page: section.page };
  $("#reader").hidden = false;
  $("#reader-title").textContent = doc.title;
  $("#reader-location").textContent = doc.path + " · section " + section.page + " « " + section.title + " »";
  $("#reader-source").href = "/api/concept?doc=" + encodeURIComponent(doc.id);
  $("#reader-badges").replaceChildren(...badges(doc));
  const meta = $("#reader-meta");
  meta.replaceChildren();
  metaRow(meta, "Description", doc.description);
  metaRow(meta, "Statut", doc.status + (doc.superseded_by ? " · remplacé par " + findDocument(undefined, doc.superseded_by)?.concept : ""));
  metaRow(meta, "Confiance", doc.trust_tier + (doc.last_verified ? " · vérifié le " + date(doc.last_verified) : ""));
  metaRow(meta, "Fraîcheur", doc.stale_after ? (doc.stale ? "périmé depuis le " : "valable jusqu’au ") + date(doc.stale_after) : "sans échéance");
  metaRow(meta, "Rédaction", doc.generated?.by ? doc.generated.by + " · " + date(doc.generated.at) : undefined);
  metaRow(meta, "Ressource", doc.resource);
  metaRow(meta, "Sources", renderSources(doc, section));
  const text = $("#reader-text");
  text.replaceChildren(markdown(section.markdown, doc, section.page));
  const notes = section.footnotes.filter((label) => doc.footnotes[label]);
  if (notes.length) {
    const list = element("ol", undefined, "footnotes");
    for (const label of notes) list.append(element("li", "[" + label + "] " + doc.footnotes[label]));
    text.append(list);
  }
  $("#reader-agent").textContent = doc.pages[section.page];
  $("#reader-agent").hidden = !agentView;
  text.hidden = agentView;
  $("#reader-pages").replaceChildren(...doc.sections.map((item) => {
    const chip = button(item.page + ". " + item.title, () => showPage(doc, item.page));
    chip.setAttribute("aria-current", item.page === section.page ? "page" : "false");
    return chip;
  }));
  $("#reader-title").focus({ preventScroll: true });
  $("#reader").scrollIntoView({ block: "nearest" });
}

function toggleAgentView() {
  agentView = !agentView;
  $("#reader-view").setAttribute("aria-pressed", String(agentView));
  if (current) showPage(current.doc, current.page);
}

function renderTree(nodes, doc) {
  const list = element("ul", undefined, "tree");
  for (const node of nodes) {
    const item = element("li");
    const section = element("details");
    const summary = element("summary");
    summary.append(element("span", node.title), element("small", "§ " + node.start_index));
    const content = element("div", undefined, "node-content");
    if (node.summary) content.append(element("p", node.summary));
    content.append(button("Lire la section " + node.start_index, () => showPage(doc, node.start_index)));
    if (node.nodes?.length) content.append(renderTree(node.nodes, doc));
    section.append(summary, content);
    item.append(section);
    list.append(item);
  }
  return list;
}

function renderSummary(bundle) {
  const report = bundle.report;
  const box = $("#bundle-summary");
  const conformance = report.conformant
    ? badge("Conforme OKF v" + bundle.okf_version, "ok") : badge("Non conforme", "bad");
  const facts = element("p", report.concepts + " concepts · " + report.sections + " sections · " + report.links + " liens");
  const trust = element("div", undefined, "badges");
  trust.append(conformance,
    badge(report.trust["human-reviewed"] + " revus", "ok"),
    badge(report.trust["machine-confirmed"] + " confirmés", "info"),
    badge(report.trust.unverified + " non vérifiés", "warn"));
  const life = element("div", undefined, "badges");
  life.append(badge(report.status.deprecated + " obsolète(s)", "bad"),
    badge(report.stale + " périmé(s)", "warn"), badge(report.status.draft + " brouillon(s)", "warn"));
  box.replaceChildren(facts, trust, life);
  if (report.warnings.length) {
    const details = element("details", undefined, "lint");
    details.append(element("summary", report.warnings.length + " avertissement(s) OKF"));
    const list = element("ul");
    for (const issue of report.warnings) list.append(element("li", issue.path + " : " + issue.message));
    details.append(list);
    box.append(details);
  }
  box.hidden = false;
}

function renderDocuments(corpus) {
  const groups = new Map();
  for (const doc of corpus.documents) {
    documents.set(doc.name, doc);
    if (!groups.has(doc.folder)) groups.set(doc.folder, []);
    groups.get(doc.folder).push(doc);
  }
  for (const [folder, docs] of groups) {
    const group = element("section", undefined, "folder");
    group.append(element("h3", corpus.bundle.folders[folder] || folder));
    for (const doc of docs) {
      const details = element("details", undefined, "document" + (doc.flags.includes("deprecated") ? " muted" : ""));
      details.open = doc.concept === "procedures/incident-p1";
      const label = element("summary");
      const name = element("span", doc.title);
      const marks = element("div", undefined, "badges");
      marks.append(...badges(doc, true), element("small", doc.sections.length + " §"));
      label.append(name, marks);
      details.append(label, renderTree(doc.tree, doc));
      group.append(details);
    }
    $("#documents").append(group);
  }
  renderSummary(corpus.bundle);
  $("#corpus-status").textContent = "OKF v" + corpus.bundle.okf_version + " · indexé sans LLM le " + date(corpus.bundle.indexed_at);
  for (const question of corpus.questions) questions.set(question.id, question);
  archives = corpus.archives || {};
  questionSelect.replaceChildren(...[...questions.values()].map((question) => {
    const option = element("option", question.label);
    option.value = question.id;
    return option;
  }));
  questionSelect.value = corpus.default_case;
  questionSelect.disabled = false;
  selectQuestion();
}

function selectQuestion() {
  const question = questions.get(questionSelect.value);
  if (!question) return;
  $("#question").textContent = question.question;
  resetRun("En attente d’une recherche");
  $("#reader").hidden = true;
  archiveButton.hidden = !archives[question.id];
  setStatus("Question sélectionnée. Lancez la recherche pour consulter les sources.");
}

function findDocument(name, id) {
  if (id) return [...documents.values()].find((doc) => doc.id === id);
  return documents.get(name) || [...documents.values()].find((doc) => doc.stored_name === name);
}

function resetRun(label) {
  calls.clear();
  sources.clear();
  $("#trace-list").replaceChildren();
  $("#trace-empty").hidden = false;
  $("#trace-count").textContent = "En attente d’un appel";
  $("#answer").replaceChildren();
  $("#answer").hidden = true;
  $("#sources").replaceChildren();
  $("#source-list").hidden = true;
  $("#warnings").replaceChildren();
  $("#warnings").hidden = true;
  $("#run-mode").textContent = label;
}

function makeCall(event) {
  $("#trace-empty").hidden = true;
  const item = element("li", undefined, "trace-item");
  const detail = element("details");
  const summary = element("summary", undefined, "trace-summary");
  const args = event.arguments || {};
  const name = args.doc_name || event.result?.doc_name;
  const subject = element("div", undefined, "call-subject");
  subject.append(element("strong", name || "Document"),
    element("code", event.name));
  const state = element("span", "En cours", "call-state");
  const result = element("div", undefined, "call-detail");
  if (event.origin === "source_check") result.append(element("p", "Lecture des pages demandée par l’application pour vérifier les sources."));
  if (event.origin === "source_check") result.firstChild.textContent = "Lecture demandée par l’application : sections citées et renvois OKF.";
  result.append(element("p", args.pages ? "Sections demandées · " + args.pages : "Lecture de l’arbre des sections"));
  summary.append(subject, state);
  detail.append(summary, result);
  item.append(detail);
  $("#trace-list").append(item);
  const call = { result, state, name, finished: false };
  calls.set(event.call_id || item, call);
  return call;
}

function addSource(doc, page) {
  const key = doc.name + ":" + page.page;
  if (sources.has(key) || !(page.page in doc.pages)) return;
  sources.set(key, page.text);
  $("#source-list").hidden = false;
  const section = doc.sections.find((item) => item.page === page.page);
  const chip = button(doc.concept + " § " + (section ? section.title : page.page), () => showPage(doc, page.page));
  if (doc.flags.length) chip.classList.add("flagged");
  $("#sources").append(chip);
}

function finishCall(event) {
  const call = calls.get(event.call_id) || makeCall(event);
  const output = event.result;
  call.finished = true;
  if (!output || output.success !== true) {
    call.state.textContent = output?.success === false ? "Échec" : "Incomplet";
    call.state.classList.add("warning");
    call.result.append(element("p", output?.success === false
      ? "L’outil a signalé un échec." : "Le résultat complet est indisponible dans cette trace."));
    return;
  }
  call.state.textContent = "Reçu";
  call.state.classList.add("success");
  const doc = findDocument(output.doc_name || call.name);
  if (Array.isArray(output.structure) && doc) {
    call.result.append(renderTree(output.structure, doc));
  }
  if (Array.isArray(output.content) && doc) {
    for (const page of output.content) {
      addSource(doc, page);
      call.result.append(button("Lire la section " + page.page, () => showPage(doc, page.page)));
    }
    if (sources.size) setStatus("Sections récupérées. Le modèle prépare la réponse…");
  }
}

function renderAnswer(event) {
  const target = $("#answer");
  target.replaceChildren();
  const citations = new Map(event.citations.map((citation) => [citation.anchor, citation]));
  let valid = 0;
  let unresolvedCount = 0;
  const tokens = /\[\[(\d+)\]\]\(#(pageindex-citation-\d+)\)|\*\*([^*\n]+)\*\*/g;
  let offset = 0;
  for (const match of event.answer.matchAll(tokens)) {
    target.append(document.createTextNode(event.answer.slice(offset, match.index)));
    if (match[3]) {
      target.append(element("strong", match[3]));
    } else {
      const citation = citations.get(match[2]);
      const doc = citation && findDocument(citation.document, citation.doc_id);
      const label = "[" + match[1] + "]";
      if (doc?.id === citation?.doc_id && doc && citation.page in doc.pages) {
        const reference = button(label, () => showPage(doc, citation.page), "citation");
        reference.setAttribute("aria-label", "Citation " + match[1] + " · " + doc.concept + ", section " + citation.page);
        if (doc.flags.length) reference.classList.add("flagged");
        target.append(reference);
        valid++;
      } else {
        const unresolved = element("span", label + " (source introuvable)", "unresolved");
        target.append(unresolved);
        unresolvedCount++;
      }
    }
    offset = match.index + match[0].length;
  }
  target.append(document.createTextNode(event.answer.slice(offset)));
  target.hidden = false;
  const warnings = event.warnings || [];
  $("#warnings").replaceChildren(...warnings.map((warning) => {
    const item = element("li");
    item.append(badge(...FLAGS[warning.flag]), document.createTextNode(" " + warning.message));
    return item;
  }));
  $("#warnings").hidden = !warnings.length;
  setStatus(warnings.length && !unresolvedCount
    ? "Réponse générée. Certaines sources citées sont obsolètes, périmées ou non validées : vérifiez les avertissements OKF."
    : unresolvedCount
    ? "Certaines citations ne correspondent pas au corpus affiché. Vérifiez les sources."
    : valid ? "Réponse générée. Ouvrez les citations pour vérifier les sources."
    : "Réponse générée sans citation résolue.", valid && !unresolvedCount && !warnings.length ? "ok" : "warn");
}

function renderEvent(event) {
  if (event.type === "status") setStatus(event.message);
  if (event.type === "start" && event.model) {
    $("#run-mode").textContent = "En direct · " + event.model
      + (event.reasoning_disabled ? " · raisonnement désactivé" : "");
  }
  if (event.type === "tool_call") makeCall(event);
  if (event.type === "tool_result") finishCall(event);
  if (event.type === "tool_call" || event.type === "tool_result") {
    const received = [...calls.values()].filter((call) => call.finished).length;
    $("#trace-count").textContent = received + " résultat(s) · " + calls.size + " appel(s)";
  }
  if (event.type === "answer") renderAnswer(event);
  if (event.type === "error") {
    const pages = sources.size ? " " + sources.size + " section(s) récupérée(s) restent consultables." : "";
    const reason = event.diagnostic?.finish_reason;
    setStatus(event.message + (reason ? " (" + reason + ")" : "") + pages, "warn");
  }
}

async function readLive() {
  const response = await fetchData("/api/query", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ case: questionSelect.value }),
  });
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let pending = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    pending += value;
    const lines = pending.split("\n");
    pending = lines.pop();
    for (const line of lines) {
      if (line) renderEvent(JSON.parse(line));
    }
  }
  if (pending.trim()) renderEvent(JSON.parse(pending));
}

async function launch(useArchive) {
  if (running) return;
  running = true;
  runButton.disabled = true;
  archiveButton.disabled = true;
  questionSelect.disabled = true;
  resetRun(useArchive ? "Trace CLI archivée" : "En direct");
  setStatus(useArchive ? "Lecture de la trace archivée…" : "Le modèle explore le corpus…");
  try {
    if (useArchive) {
      const response = await fetchData("/api/archive?case=" + encodeURIComponent(questionSelect.value));
      const archive = await response.json();
      $("#run-mode").textContent = "Trace CLI archivée · " + archive.run;
      archive.events.forEach(renderEvent);
    } else {
      await readLive();
    }
  } catch (error) {
    setStatus(error.message || "Impossible de joindre le serveur de démonstration.", "warn");
  } finally {
    running = false;
    runButton.disabled = !ready;
    archiveButton.disabled = false;
    questionSelect.disabled = !ready;
  }
}

runButton.addEventListener("click", () => launch(false));
archiveButton.addEventListener("click", () => launch(true));
questionSelect.addEventListener("change", selectQuestion);
$("#reader-view").addEventListener("click", toggleAgentView);

async function initialize() {
  try {
    const response = await fetchData("/api/corpus");
    renderDocuments(await response.json());
    ready = true;
    runButton.disabled = false;
  } catch (error) {
    $("#corpus-status").textContent = "Index indisponible";
    $("#question").textContent = "Les questions seront disponibles après l’indexation du corpus.";
    setStatus(error.message || "Impossible de charger le corpus.", "warn");
  }
}

initialize();
