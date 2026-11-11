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

function showPage(doc, page, excerpt) {
  if (!(page in doc.pages)) return;
  $("#reader").hidden = false;
  $("#reader-location").textContent = doc.name + " · page " + page;
  $("#reader-pdf").href = "/api/pdf?doc=" + encodeURIComponent(doc.id) + "#page=" + page;
  $("#reader-text").textContent = excerpt || doc.pages[page];
  $("#reader-pages").replaceChildren(...Object.keys(doc.pages).map((number) => {
    const item = button("Page " + number, () => showPage(doc, number));
    item.setAttribute("aria-current", String(number) === String(page) ? "page" : "false");
    return item;
  }));
  $("#reader-title").focus({ preventScroll: true });
  $("#reader").scrollIntoView({ block: "nearest" });
}

function renderTree(nodes, doc) {
  const list = element("ul", undefined, "tree");
  for (const node of nodes) {
    const item = element("li");
    const section = element("details");
    const summary = element("summary");
    summary.append(element("span", node.title),
      element("small", node.start_index === node.end_index
        ? "p. " + node.start_index : "p. " + node.start_index + "–" + node.end_index));
    const content = element("div", undefined, "node-content");
    if (node.summary) content.append(element("p", node.summary));
    content.append(button("Lire la page " + node.start_index, () => showPage(doc, node.start_index)));
    if (node.nodes?.length) content.append(renderTree(node.nodes, doc));
    section.append(summary, content);
    item.append(section);
    list.append(item);
  }
  return list;
}

function renderDocuments(corpus) {
  let pages = 0;
  for (const doc of corpus.documents) {
    documents.set(doc.name, doc);
    const count = Object.keys(doc.pages).length;
    pages += count;
    const details = element("details", undefined, "document");
    details.open = doc.name === "incidents.pdf";
    const label = element("summary");
    label.append(element("span", doc.name), element("small", count + " p."));
    details.append(label, renderTree(doc.tree, doc));
    $("#documents").append(details);
  }
  $("#corpus-status").textContent = documents.size + " PDF · " + pages + " pages indexées";
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
  result.append(element("p", args.pages ? "Pages demandées · " + args.pages : "Lecture de la structure"));
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
  $("#sources").append(button(doc.name + " · p. " + page.page,
    () => showPage(doc, page.page, page.text)));
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
      call.result.append(button("Lire la page " + page.page, () => showPage(doc, page.page, page.text)));
    }
    if (sources.size) setStatus("Pages récupérées. Le modèle prépare la réponse…");
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
        reference.setAttribute("aria-label", "Citation " + match[1] + " · " + doc.name + ", page " + citation.page);
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
  setStatus(unresolvedCount
    ? "Certaines citations ne correspondent pas au corpus affiché. Vérifiez les sources."
    : valid ? "Réponse générée. Ouvrez les citations pour vérifier les sources."
    : "Réponse générée sans citation résolue.", valid && !unresolvedCount ? "ok" : "warn");
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
    const pages = sources.size ? " " + sources.size + " page(s) récupérée(s) restent consultables." : "";
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
