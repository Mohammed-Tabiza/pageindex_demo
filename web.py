"""Serve the PageIndex demonstrator for an OKF bundle on the loopback interface."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import okf
from demo import (QUERY_INSTRUCTIONS, ROOT, configuration, endpoint_error, ensure_index, load_bundles,
                  load_questions, pageindex_client)

TIMEOUT = 120
QUERY_LOCK = threading.Lock()
TOOLS = {"get_document_structure", "get_page_content"}
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
FLAG_MESSAGES = {
    "deprecated": "est obsolète (status: deprecated)",
    "stale": "est périmé (stale_after dépassé)",
    "draft": "est un brouillon (status: draft)",
    "unverified": "n’a jamais été vérifié (aucun verified)",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def questions():
    return [{"id": q["id"], "label": q.get("label", q["id"]), "question": q["question"]}
            for q in load_questions()]


def default_case():
    """'renvoi' for the bundled questions, else the first one of a custom DEMO_QUESTIONS file."""
    ids = [q["id"] for q in questions()]
    return "renvoi" if "renvoi" in ids or not ids else ids[0]


_DEFAULT = object()


def selected_question(case=_DEFAULT):
    case = default_case() if case is _DEFAULT else case
    if not isinstance(case, str):
        raise ValueError("Question inconnue.")
    question = next((q for q in questions() if q["id"] == case), None)
    if question is None:
        raise ValueError("Question inconnue.")
    return question["question"]


def document(bundle, concept, now):
    """Everything the interface and the source checks need about one concept."""
    data = okf.rendered(bundle, concept, now)
    target = okf.replacement(bundle, concept)
    links = []
    for link in concept.links:
        item = link.as_dict()
        # The target may live in another bundle (`other:/path.md`): it is resolved already.
        item["target_doc"] = link.concept.doc_id if link.concept else None
        links.append(item)
    return {
        "id": concept.doc_id,
        "name": concept.doc_name,
        "stored_name": concept.doc_name,
        "concept": concept.key,
        "bundle": bundle.name,
        "path": concept.path,
        "folder": "/".join(filter(None, [concept.namespace, Path(concept.path).parent.as_posix().strip(".")])) or ".",
        "type": concept.type,
        "title": concept.title,
        "description": concept.description,
        "status": concept.status,
        "trust_tier": concept.trust_tier,
        "last_verified": concept.last_verified,
        "generated": concept.generated,
        "stale": concept.is_stale(now),
        "stale_after": concept.stale_after,
        "flags": concept.lifecycle_flags(now),
        "tags": concept.tags,
        "resource": concept.frontmatter.get("resource"),
        "sources": [{key: okf.iso(value) if key == "last_modified" else value
                     for key, value in source.items()} for source in concept.sources],
        "superseded_by": target.doc_id if target else None,
        "supersedes": [c.doc_id for c in okf.replaced(bundle, concept)],
        "tree": data["tree"],
        "pages": {page["page_index"]: page["markdown"] for page in data["pages"]},
        "sections": [{"page": s.page, "level": s.level, "title": s.title, "anchor": s.anchor,
                      "markdown": s.markdown, "footnotes": s.footnotes} for s in concept.sections],
        "footnotes": concept.footnotes,
        "links": links,
    }


def corpus():
    bundles, manifest = ensure_index()
    now = okf.now_utc()
    report = okf.report(bundles, now)
    several = len(bundles) > 1
    # Group labels come from the index.md entries that list each directory (§8),
    # prefixed with the bundle name when several bundles are queried together.
    folders = {}
    for bundle in bundles:
        for directory, body in bundle.indexes.items():
            for title, href in re.findall(r"^\s*[*-]\s+\[([^\]]+)\]\(([^)\s]+/)\)", body, re.M):
                path = (Path(directory) / href).as_posix().strip("/").removeprefix("./")
                folders.setdefault(f"{bundle.name}/{path}" if several else path,
                                   f"{bundle.name} · {title}" if several else title)
    documents = [document(bundle, concept, now) for bundle in bundles
                 for concept in sorted(bundle.concepts.values(), key=lambda c: c.id)]
    return {"documents": documents, "question": selected_question(), "questions": questions(),
            "default_case": default_case(),
            "bundle": {"okf_version": manifest["okf_version"], "indexer": manifest["indexer"],
                       "indexed_at": manifest["indexed_at"], "folders": folders,
                       "names": [bundle.name for bundle in bundles],
                       "report": {key: report[key] for key in ("conformant", "concepts", "sections", "links",
                                                               "trust", "status", "stale", "errors", "warnings")}}}


def error_event(error, stage):
    """Keep only whitelisted diagnostics from provider exceptions."""
    status = getattr(error, "status_code", None)
    match = re.search(r"""finish_reason ['"]([a-z_]+)['"]""", str(error))
    finish = match.group(1) if match else None
    diagnostic = {"exception": type(error).__name__}
    if isinstance(status, int) and 100 <= status <= 599:
        diagnostic["http_status"] = status
    if status == 402:
        message = ("Le fournisseur du modèle refuse la requête : paiement requis (HTTP 402). "
                   "Vérifiez les crédits ou l’abonnement du compte utilisé pour le modèle cloud.")
    elif finish in {"length", "max_tokens", "model_context_window_exceeded"}:
        diagnostic["finish_reason"] = finish
        message = "Le modèle a atteint sa limite de génération avant de terminer la réponse."
    elif finish in {"content_filter", "refusal"}:
        diagnostic["finish_reason"] = finish
        message = "Le modèle a interrompu la réponse."
    elif stage == "configuration":
        message = "Vérifiez DEMO_CHAT_MODEL (ou DEMO_MODEL), OPENAI_API_KEY et OPENAI_BASE_URL dans le fichier .env."
    elif stage == "index":
        message = "Bundle OKF non conforme ou illisible : lancez uv run .\\demo.py lint."
    elif stage == "citations":
        message = "Les citations de la réponse n’ont pas pu être résolues."
    elif status == 429:
        message = "Le serveur du modèle a atteint sa limite de requêtes. Réessayez plus tard."
    else:
        message = "La réponse du modèle a été interrompue. Vérifiez le modèle et son serveur."
    usage = getattr(error, "usage", None)
    entries = usage.get("request_usage_entries") if isinstance(usage, dict) else None
    if entries:
        diagnostic["last_request"] = {
            key: entries[-1][key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if isinstance(entries[-1].get(key), int)
        }
        last = diagnostic["last_request"]
        if finish in {"length", "max_tokens", "model_context_window_exceeded"}:
            if "prompt_tokens" in last and "completion_tokens" in last:
                message += (f' Dernier appel : {last["prompt_tokens"]} jetons d’entrée et '
                            f'{last["completion_tokens"]} jetons de sortie.')
            message += " Vérifiez la taille du contexte du modèle et son plafond de sortie."
    return {"type": "error", "stage": stage, "message": message, "diagnostic": diagnostic}


def clean_result(output):
    # The SDK returns either serialized JSON or a structured text item.
    if isinstance(output, dict) and output.get("type") == "text":
        output = output.get("text")
    if isinstance(output, list) and len(output) == 1:
        return clean_result(output[0])
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            return None
    if not isinstance(output, dict):
        return None
    keys = ("success", "doc_name", "requested_pages", "returned_pages", "structure", "content")
    return {key: output[key] for key in keys if key in output}




def followups(documents, cited, handed=frozenset()):
    """Pages a cited section hands over to, from OKF links and supersession.

    Only links whose sentence is a referral ("appliquer la section Relais de
    [x](...)") count; a passing mention of another concept does not. A cited
    deprecated concept always hands over to its replacement, and a cited draft
    or unverified concept to the rules in force it links to (see challenges).
    `handed`: pages the check itself delivered as referral targets and the model
    never opened; their own referrals are not followed further, so a page pulled
    in by a whole-document referral cannot chain obligations the question never
    asked for. Supersession and drafts still apply to them.
    Returns {(source_doc_id, target_doc_id): set of target pages}.
    """
    by_id = {doc["id"]: doc for doc in documents}
    pairs = {}
    for doc_id, page in cited:
        doc = by_id.get(doc_id)
        if doc is None:
            continue
        for link in doc.get("links", []):
            target = by_id.get(link.get("target_doc"))
            if link.get("section") != page or target is None or target["id"] == doc_id:
                continue
            if not (challenges(doc, target) or (link.get("referral") and (doc_id, page) not in handed)):
                continue
            pages = {link["target_page"]} if link.get("target_page") else set(target["pages"])
            pairs.setdefault((doc_id, target["id"]), set()).update(pages)
        replacement = by_id.get(doc.get("superseded_by"))
        if replacement is not None:
            anchored = {link["target_page"] for link in doc.get("links", [])
                        if link.get("target_doc") == replacement["id"] and link.get("target_page")}
            pairs.setdefault((doc_id, replacement["id"]), set()).update(anchored or set(replacement["pages"]))
    return pairs


def unsettled(doc):
    return doc.get("status") == "draft" or doc.get("trust_tier") == "unverified"


def challenges(doc, target):
    """A draft or unverified concept that links to a reviewed concept of the same
    type may be rewriting that rule ("cette proposition modifierait la section…"):
    the rule in force must be read too, whatever verb the link sentence uses.
    Same type only, so the roles a draft merely names are not required."""
    return (unsettled(doc) and not unsettled(target) and target.get("status") != "deprecated"
            and target.get("type") == doc.get("type"))


def cited_pages(resolved):
    return {(c.get("doc_id"), c.get("page")) for c in resolved.get("citations", [])}


def retrieve_sources(client, resolved, documents, evidence, attempt, handed=None):
    """Read cited pages and the sections they hand over to, through the real SDK.
    Pages fetched only as referral targets (not cited by the model) go into `handed`."""
    handed = set() if handed is None else handed
    by_id = {doc["id"]: doc for doc in documents}
    attempted = set(evidence)
    added = False
    cited = cited_pages(resolved)
    while True:
        requested = set(cited)
        for (_, target_id), pages in followups(documents, cited & set(evidence), handed).items():
            targets = {(target_id, page) for page in pages}
            handed.update(targets - cited - set(evidence))
            requested.update(targets)
        pending = {}
        for doc_id, page in requested - attempted:
            doc = by_id.get(doc_id)
            if doc and page in doc["pages"]:
                pending.setdefault(doc_id, set()).add(page)
        if not pending:
            return added
        for doc_id, pages in sorted(pending.items()):
            doc = by_id[doc_id]
            attempted.update((doc_id, page) for page in pages)
            spec = ",".join(map(str, sorted(pages)))
            call_id = f"{attempt}:source-check:{doc_id}:{spec}"
            yield {"type": "tool_call", "name": "get_page_content", "call_id": call_id,
                   "origin": "source_check", "arguments": {"doc_name": doc["stored_name"], "pages": spec}}
            content = [{"page": page["page_index"], "text": page["markdown"]}
                       for page in client.get_page_content(doc_id, spec) if page["page_index"] in pages]
            for page in content:
                evidence[(doc_id, page["page"])] = {"doc_name": doc["stored_name"], **page}
                added = True
            yield {"type": "tool_result", "name": "get_page_content", "call_id": call_id,
                   "origin": "source_check", "result": {"success": True, "doc_name": doc["stored_name"], "content": content}}


def answer_issues(resolved, documents, evidence, seen=None, handed=frozenset()):
    """Check source coverage and OKF lifecycle, not semantic truth or the reference answer."""
    issues = []
    by_id = {doc["id"]: doc for doc in documents}
    cited = set()
    if not evidence:
        issues.append("Lisez les pages sources avec les outils avant de conclure.")
    elif seen is not None and not seen:
        issues.append("Vous n’avez lu aucune section : appelez get_document_structure puis get_page_content avant de répondre.")
    if not resolved.get("citations"):
        issues.append('Citez les pages lues avec <cite doc="nom exact du document" page="N"/>.')
    for citation in resolved.get("citations", []):
        doc = by_id.get(citation.get("doc_id"))
        page = citation.get("page")
        if doc is None or page not in doc["pages"]:
            issues.append("Une citation ne correspond pas à une page du corpus. Utilisez les noms exacts des documents accessibles.")
        elif (doc["id"], page) not in evidence or (seen is not None and (doc["id"], page) not in seen):
            # A page fetched only by the application's own check was never read by the model.
            issues.append(f'Lisez la page {page} de {doc["stored_name"]} avec get_page_content avant de la citer.')
        else:
            cited.add(doc["id"])
    for (source_id, target_id), _ in sorted(followups(documents, cited_pages(resolved), handed).items()):
        if target_id in cited or source_id not in cited:
            continue
        source, target = by_id[source_id], by_id[target_id]
        if source.get("superseded_by") == target_id:
            issues.append(f'{source["stored_name"]} est obsolète : n’appliquez pas sa règle, appuyez la réponse sur '
                          f'{target["stored_name"]} et citez-le.')
        elif challenges(source, target):
            issues.append(f'{source["stored_name"]} est un brouillon non validé : lisez la règle en vigueur dans '
                          f'{target["stored_name"]}, appuyez la réponse sur elle, citez-la et signalez le désaccord éventuel.')
        else:
            issues.append(f'Suivez le renvoi : lisez les pages pertinentes de {target["stored_name"]} et citez-les dans la réponse finale.')
    return list(dict.fromkeys(issues))


def okf_warnings(resolved, documents):
    """OKF §10.5 gate, advisory: surface the lifecycle of every cited concept."""
    by_id = {doc["id"]: doc for doc in documents}
    warnings = []
    for doc_id in dict.fromkeys(c.get("doc_id") for c in resolved.get("citations", [])):
        doc = by_id.get(doc_id)
        if doc is None:
            continue
        for flag in doc.get("flags", []):
            detail = f' depuis le {doc["stale_after"][:10]}' if flag == "stale" and doc.get("stale_after") else ""
            warnings.append({"doc_id": doc_id, "flag": flag,
                             "message": f'Le concept {doc["concept"]} {FLAG_MESSAGES[flag]}{detail}.'})
    return warnings


def query_events(case="renvoi", attempts=2, publish_unverified=False):
    """Stream one question. attempts=2 allows the bounded retry; publish_unverified
    keeps the last answer even when the checks refuse it, its issues attached
    (evaluation of the model alone, never used by the web interface)."""
    stream = None
    stage = "configuration"
    try:
        question = selected_question(case)
        index_model, model, key, url = configuration()
        problem = endpoint_error(url, key)
        if problem:
            yield {"type": "error", "stage": "connection", "message": problem}
            return
        stage = "index"
        data = corpus()
        documents = data["documents"]
        ids = [doc["id"] for doc in documents]
        by_name = {name: doc for doc in documents for name in (doc["name"], doc["stored_name"])}
        stage = "generation"
        client = pageindex_client(index_model, model, key, url)
        # DEMO_REASONING_EFFORT: empty or "default" = model default; none, low, medium, high are sent as is.
        # Small local models skip the tool calls far more often without reasoning, so
        # reasoning stays on unless the operator asks for speed.
        effort = os.getenv("DEMO_REASONING_EFFORT", "").strip().lower() or "default"
        options = {} if effort == "default" else {"reasoning_effort": effort}
        yield {"type": "start", "reasoning_disabled": effort == "none", "model": model, "case": case}
        messages = [{"role": "user", "content": question}]
        evidence = {}
        seen = set()   # pages the model actually had in front of it
        opened = set()   # pages the model fetched with its own tool calls
        handed = set()   # pages the check delivered as referral targets
        # One bounded continuation if the source trail is incomplete; never insert a reference answer.
        for attempt in range(attempts):
            stage = "generation"
            stream = client.chat(messages, doc_id=ids, citations=True, stream=True,
                                 max_turns=8, instructions=QUERY_INSTRUCTIONS, **options)
            parts = []
            for event in stream.events:
                kind = event["type"]
                if kind == "answer":
                    parts.append(event["delta"])
                elif kind == "tool_call":
                    # Text before another tool call is narration, not the final answer.
                    parts.clear()
                if kind in {"tool_call", "tool_result"} and event["name"] in TOOLS:
                    payload = {"type": kind, "name": event["name"], "call_id": f'{attempt}:{event["call_id"]}'}
                    if kind == "tool_call":
                        args = event["arguments"]
                        payload["arguments"] = {k: args[k] for k in ("doc_name", "pages") if k in args} if isinstance(args, dict) else {}
                    else:
                        output = clean_result(event["output"])
                        payload["result"] = output
                        if output and output.get("success") is True and event["name"] == "get_page_content":
                            doc = by_name.get(output.get("doc_name"))
                            if doc:
                                for page in output.get("content", []):
                                    if page.get("page") in doc["pages"] and isinstance(page.get("text"), str):
                                        evidence[(doc["id"], page["page"])] = {"doc_name": doc["stored_name"], **page}
                                        seen.add((doc["id"], page["page"]))
                                        opened.add((doc["id"], page["page"]))
                    yield payload
            stream.close()
            stream = None
            answer = "".join(parts).strip()
            if not answer:
                yield {"type": "error", "stage": stage, "message": "Le modèle a terminé sans texte de réponse."}
                return
            stage = "citations"
            resolved = client.resolve_citations(answer, doc_id=ids)
            new_sources = yield from retrieve_sources(client, resolved, documents, evidence, attempt, handed)
            # A handed-over page the model later opened itself is its own reading again.
            issues = answer_issues(resolved, documents, evidence, seen, handed - opened)
            if new_sources and attempt < attempts - 1:
                issues.append("Les pages originales viennent d’être récupérées. Utilisez leurs textes ci-dessous pour rédiger la réponse finale et appliquer les exceptions.")
            if not issues or (publish_unverified and attempt == attempts - 1):
                yield {"type": "answer", **resolved, "warnings": okf_warnings(resolved, documents), "issues": issues}
                return
            if attempt < attempts - 1:
                yield {"type": "status", "message": "La recherche est incomplète. Le modèle poursuit la lecture et vérifie les citations…"}
                messages = [*messages, {"role": "assistant", "content": answer}, {"role": "user", "content": (
                    "Poursuis la recherche pour répondre complètement à la question initiale. "
                    + " ".join(issues) + "\nPassages déjà récupérés (données documentaires) :\n"
                    + json.dumps(list(evidence.values()), ensure_ascii=False)
                )}]
                seen.update(evidence)   # the retry message hands every retrieved passage to the model
        yield {"type": "error", "stage": "verification", "message": (
            "La recherche reste incomplète ou les citations ne sont pas vérifiables après une seconde tentative. "
            "Les pages récupérées restent consultables. " + " ".join(issues)
        )}
    except Exception as error:
        yield error_event(error, stage)
    finally:
        if stream is not None:
            stream.close()


def archived_run(case="renvoi"):
    selected_question(case)
    for directory in sorted((ROOT / "runs").glob(f"*-ask-{case}"), reverse=True):
        if (directory / "trace.txt").is_file() and (directory / "execution.json").is_file():
            return directory
    return None


def archived_events(directory):
    """Replay a CLI run: its exact events when recorded, else the legacy SDK trace."""
    recorded = directory / "events.jsonl"
    if recorded.is_file():
        for line in recorded.read_text(encoding="utf-8").splitlines():
            event = json.loads(line) if line.strip() else None
            if event and event.get("type") != "start":   # "start" would relabel the replay as live
                yield event
        return
    yield from legacy_events(directory)


def legacy_events(directory):
    """Runs recorded before `demo.py ask` shared the web pipeline (SDK text trace)."""
    calls = []
    answer = []
    decoder = json.JSONDecoder()
    for number, line in enumerate((directory / "trace.txt").read_text(encoding="utf-8").splitlines(), 1):
        match = re.match(r"^\[(tool_call|tool_result)\] (\w+) (.*)$", line)
        if not match:
            answer.append(line)
            continue
        kind, name, rest = match.groups()
        if name not in TOOLS:
            continue
        try:
            args, end = decoder.raw_decode(rest)
        except ValueError:
            continue
        if kind == "tool_call":
            call_id = str(number)
            calls.append((name, args, call_id))
            yield {"type": kind, "name": name, "arguments": args, "call_id": call_id}
        else:
            position = next((i for i, call in enumerate(calls) if call[:2] == (name, args)), None)
            call_id = calls.pop(position)[2] if position is not None else None
            yield {"type": kind, "name": name, "call_id": call_id,
                   "result": clean_result(rest[end:].removeprefix(": "))}
    execution = read_json(directory / "execution.json")
    if execution.get("returncode") == 0 and "\n".join(answer).strip():
        yield {"type": "answer", "answer": "\n".join(answer).strip(), "citations": []}
    else:
        message = ("L’exécution archivée a dépassé le délai."
                   if execution.get("status") == "TIMEOUT"
                   else "L’exécution archivée s’est terminée sans réponse finale enregistrée.")
        yield {"type": "error", "stage": "archive", "message": message}


def worker_crash(returncode, errors):
    """'code N, ExceptionName' from a crashed worker's stderr, without the exception message."""
    errors.seek(0)
    lines = [line.strip() for line in errors.read()[-8192:].decode("utf-8", "replace").splitlines() if line.strip()]
    match = re.match(r"^([A-Za-z_][\w.]*)(?::|$)", lines[-1]) if lines else None
    return f"code {returncode}" + (f", {match.group(1)}" if match else "")


class Handler(BaseHTTPRequestHandler):
    def send_headers(self, status, content_type, size=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if size is not None:
            self.send_header("Content-Length", str(size))
        self.end_headers()

    def send_data(self, status, content_type, data):
        self.send_headers(status, content_type, len(data))
        self.wfile.write(data)

    def send_json(self, status, payload):
        self.send_data(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode())

    def local_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_GET(self):
        if not self.local_host():
            self.send_json(403, {"message": "Adresse locale requise."})
            return
        url = urlsplit(self.path)
        try:
            if url.path in STATIC:
                name, content_type = STATIC[url.path]
                self.send_data(200, content_type, (ROOT / "web" / name).read_bytes())
            elif url.path == "/favicon.ico":
                self.send_headers(204, "image/x-icon")
            elif url.path == "/api/corpus":
                data = corpus()
                archives = {q["id"]: archived_run(q["id"]) for q in data["questions"]}
                self.send_json(200, {**data, "archives": {case: path.name if path else None for case, path in archives.items()}})
            elif url.path == "/api/archive":
                case = parse_qs(url.query).get("case", [default_case()])[0]
                try:
                    selected_question(case)
                except ValueError as error:
                    self.send_json(400, {"message": str(error)})
                    return
                archive = archived_run(case)
                if archive is None:
                    self.send_json(404, {"message": "Aucune trace CLI archivée pour cette question."})
                else:
                    self.send_json(200, {"run": archive.name, "case": case, "events": list(archived_events(archive))})
            elif url.path == "/api/concept":
                # Raw OKF source (frontmatter included), served as plain text.
                doc_id = parse_qs(url.query).get("doc", [""])[0]
                found = next(((b, c) for b in load_bundles() if (c := b.by_doc_id().get(doc_id))), None)
                if found is None:
                    self.send_json(404, {"message": "Concept introuvable."})
                else:
                    bundle, concept = found
                    self.send_data(200, "text/plain; charset=utf-8", (bundle.root / concept.path).read_bytes())
            else:
                self.send_json(404, {"message": "Page introuvable."})
        except (OSError, ValueError, KeyError):
            self.send_json(409, {"message": "Bundle OKF illisible ou non conforme. Lancez uv run .\\demo.py lint, corrigez les erreurs, puis rechargez la page."})

    def do_POST(self):
        if not self.local_host() or self.headers.get("Origin") not in {None, f"http://{self.headers.get('Host')}"}:
            self.send_json(403, {"message": "Adresse locale requise."})
            return
        if self.path != "/api/query":
            self.send_json(404, {"message": "Page introuvable."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 1024:
                self.send_json(413, {"message": "Requête trop volumineuse."})
                return
            if length and self.headers.get_content_type() != "application/json":
                self.send_json(415, {"message": "Envoyez la question au format JSON."})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if not isinstance(payload, dict):
                raise ValueError("Requête de question invalide.")
            case = payload.get("case", default_case())
            selected_question(case)
        except ValueError:
            self.send_json(400, {"message": "Question inconnue ou requête invalide."})
            return
        if not QUERY_LOCK.acquire(blocking=False):
            self.send_json(409, {"message": "Une question est déjà en cours."})
            return
        try:
            self.stream_query(case)
        finally:
            QUERY_LOCK.release()

    def stream_query(self, case="renvoi"):
        self.send_headers(200, "application/x-ndjson; charset=utf-8")
        # stderr goes to a private temporary file: only the exception class of a crash is
        # logged, never its message, which may quote provider headers or secrets.
        with tempfile.TemporaryFile() as errors, subprocess.Popen(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--query-worker", "--case", case],
            stdout=subprocess.PIPE, stderr=errors,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        ) as worker:
            expired = threading.Event()

            def stop_at_deadline():
                if worker.poll() is None:
                    expired.set()
                    worker.kill()

            timer = threading.Timer(TIMEOUT, stop_at_deadline)
            timer.start()
            try:
                terminal_event = False
                for line in worker.stdout:
                    if not line.startswith(b"PAGEINDEX_EVENT "):
                        continue
                    data = line.removeprefix(b"PAGEINDEX_EVENT ")
                    event = json.loads(data)
                    terminal_event |= event["type"] in {"answer", "error"}
                    if event["type"] == "error":
                        self.log_message("Query diagnostic: %s", event.get("diagnostic", event["stage"]))
                    self.wfile.write(data)
                    self.wfile.flush()
                if expired.is_set() or not terminal_event:
                    message = ("Délai de 120 secondes dépassé. Les résultats reçus restent consultables."
                               if expired.is_set() else "Le processus PageIndex s’est arrêté avant de répondre.")
                    if not expired.is_set():
                        crash = worker_crash(worker.wait(), errors)
                        self.log_message("Query worker stopped: %s", crash)
                        message += f" ({crash})"
                    self.wfile.write((json.dumps({"type": "error", "stage": "generation", "message": message}) + "\n").encode())
            except (ConnectionError, TimeoutError):
                pass
            finally:
                timer.cancel()
                if worker.poll() is None:
                    worker.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--query-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--case", default=default_case(), choices=[q["id"] for q in questions()], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.query_worker:
        for event in query_events(args.case):
            print("PAGEINDEX_EVENT " + json.dumps(event, ensure_ascii=False, default=str), flush=True)
        return
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"PageIndex · http://127.0.0.1:{server.server_port} · Ctrl+C pour arrêter", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
