"""PageIndex over an Open Knowledge Format (OKF v0.2) bundle of markdown concepts.

check     offline: conformance of the bundle and of the questions' references
lint      offline: every conformance error and warning of a bundle (--bundle PATH)
index     offline: mirror the bundle into the local PageIndex store (no LLM call)
ask       PageIndex agent over the indexed concepts (LLM endpoint required)
baseline  the same model with the whole bundle in context (LLM endpoint required)
"""
import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import okf

ROOT = Path(__file__).resolve().parent
INSTRUCTIONS = (
    "Réponds en français uniquement à partir des concepts du bundle OKF fictif fourni. "
    "Chaque document est un concept OKF ; chaque page est une section du concept. "
    "La première ligne de chaque page indique le statut, le niveau de confiance et la fraîcheur du concept. "
    "N'applique jamais une règle d'un concept OBSOLÈTE : suis son remplaçant et signale que l'ancienne règle n'est plus en vigueur. "
    "Si un concept est PÉRIMÉ ou en BROUILLON, donne l'information en avertissant explicitement l'utilisateur. "
    "Les liens annotés {→ document, page} indiquent où lire la suite : suis les renvois jusqu'à la règle applicable. "
    "Signale explicitement les informations absentes. Applique les exceptions. "
    "Ne demande pas à l'utilisateur de consulter à ta place un document accessible. "
    "Donne directement la réponse finale, sans annoncer tes recherches. "
    "Cite les pages justificatives. N'invente aucune coordonnée."
)


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def bundle_path():
    configured = os.getenv("DEMO_BUNDLE", "").strip()
    path = Path(configured) if configured else ROOT / "bundle"
    return path if path.is_absolute() else ROOT / path


def questions_path():
    configured = os.getenv("DEMO_QUESTIONS", "").strip()
    path = Path(configured) if configured else ROOT / "questions.json"
    return path if path.is_absolute() else ROOT / path


def load_questions():
    path = questions_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def storage_path():
    return ROOT / ".pageindex"


def resolve_source(bundle, reference):
    """'concept/id#anchor' → (concept, section); raises ValueError when unknown."""
    concept_id, _, anchor = reference.partition("#")
    concept = bundle.concepts.get(concept_id.removesuffix(".md"))
    if concept is None:
        raise ValueError(f"Concept inconnu : {reference}")
    section = concept.section_for(anchor) if anchor else concept.sections[0]
    if section is None:
        raise ValueError(f"Section inconnue : {reference}")
    return concept, section


def offline():
    bundle = okf.load_bundle(bundle_path())
    result = okf.report(bundle)
    questions = load_questions()
    for q in questions:
        for reference in q.get("sources", []):
            resolve_source(bundle, reference)
    if not bundle.conformant:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise ValueError("Bundle OKF non conforme : voir les erreurs ci-dessus.")
    if bundle_path() == ROOT / "bundle":
        # The bundled scenario relies on these facts; keep them from drifting silently.
        relais = resolve_source(bundle, "procedures/astreinte-relais#relais")[1].markdown
        assert "10 minutes" in relais and "animateur" in relais
        assert bundle.concepts["procedures/escalade-p1-v1"].status == "deprecated"
        assert bundle.concepts["procedures/changement-urgent"].status == "draft"
    summary = {key: result[key] for key in ("bundle", "okf_version", "conformant", "concepts", "sections",
                                            "links", "types", "trust", "status", "stale")}
    summary.update({"warnings": len(result["warnings"]), "questions": len(questions),
                    "pageindex_inference": "NON TESTÉ", "status_check": "PASS",
                    "python": sys.version.split()[0]})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def lint(path):
    bundle = okf.load_bundle(path)
    for issue in bundle.issues:
        print(f"{issue.level.upper():8} {issue.path}: {issue.message}")
    print(f"{len(bundle.concepts)} concept(s), {len(bundle.errors)} erreur(s), "
          f"{len(bundle.issues) - len(bundle.errors)} avertissement(s) — "
          + ("conforme OKF v" + okf.SPEC_VERSION if bundle.conformant else "NON CONFORME"))
    return 0 if bundle.conformant else 1


def ensure_index():
    """Load the bundle and bring the local PageIndex store up to date (no LLM call)."""
    bundle = okf.load_bundle(bundle_path())
    manifest = okf.sync(bundle, storage_path())
    manifest["pageindex"] = importlib.metadata.version("pageindex")
    write(ROOT / "index_manifest.json", manifest)
    return bundle, manifest


def configuration():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    fallback = os.getenv("DEMO_MODEL", "").strip()
    chat_model = os.getenv("DEMO_CHAT_MODEL", "").strip() or fallback
    # OKF indexing is deterministic; the index model only configures the SDK client.
    index_model = os.getenv("DEMO_INDEX_MODEL", "").strip() or chat_model
    key = os.getenv("OPENAI_API_KEY", "").strip()
    url = os.getenv("OPENAI_BASE_URL", "").strip()
    if not chat_model or not key or not url:
        raise ValueError("Renseignez DEMO_CHAT_MODEL (ou DEMO_MODEL), OPENAI_API_KEY et OPENAI_BASE_URL dans .env. Aucun appel effectué.")
    for model in (index_model, chat_model):
        if model.lower() in ("cloud", "local"):
            raise ValueError("Les modèles doivent être les noms des modèles servis, pas cloud/local.")
    return index_model, chat_model, key, url


def endpoint_error(url, key, timeout=5):
    """Fail fast when the model server cannot be reached at all.

    Any HTTP answer (even 401 or 404) proves the server is there; only a
    connection failure or a timeout is reported. Without this check, a
    firewall that silently drops packets makes every query wait for the
    global deadline. Returns None when reachable, else a message.
    """
    import socket
    import urllib.error
    import urllib.request
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    shown = f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")  # never echo credentials
    request = urllib.request.Request(url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"})
    try:
        urllib.request.urlopen(request, timeout=timeout).close()
    except urllib.error.HTTPError:
        return None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        kind = "délai dépassé" if isinstance(reason, (socket.timeout, TimeoutError)) else "connexion impossible"
        return (f"Serveur du modèle injoignable à {shown} ({kind} en {timeout} s). "
                "Vérifiez qu’il est lancé et accessible depuis cet environnement ; sous WSL en réseau NAT, "
                "le localhost de Windows n’est pas visible (voir README, Diagnostic).")
    return None


def pageindex_client(index_model, chat_model, key, url):
    # Disable SDK tracing; retain only observable tool events, not model thinking.
    os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
    from pageindex import PageIndexClient
    backend = {"api_key": key, "base_url": url}
    return PageIndexClient(index={"model": index_model, "backend": backend, "storage_path": str(storage_path())},
                           chat={"model": chat_model, "backend": backend}, instructions=INSTRUCTIONS)


def llm_completion(**kwargs):
    """Single full-context call for the baseline (isolated so tests can replace it)."""
    from litellm import completion
    return completion(**kwargs)


def index(output):
    start = time.monotonic()
    bundle, manifest = ensure_index()
    from pageindex.local_store import DocStore
    store = DocStore(str(storage_path()))
    output.mkdir(parents=True, exist_ok=True)
    for entry in manifest["docs"]:
        write(output / (entry["name"].removesuffix(".md") + "_tree.json"), store.get_tree(entry["doc_id"]))
    manifest["seconds"] = time.monotonic() - start
    write(output / "index_manifest.json", manifest)
    write(output / "okf_report.json", okf.report(bundle))
    print(f"{len(manifest['docs'])} concept(s) indexé(s), {len(manifest['changed'])} mis à jour, "
          f"{manifest['removed']} supprimé(s), {manifest['warnings']} avertissement(s) OKF. Aucun appel LLM.")


def worker(args):
    index_model, chat_model, key, url = configuration()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    bundle, manifest = ensure_index()
    q = next(q for q in load_questions() if q["id"] == args.case)
    start = time.monotonic()
    meta = {"case": q["id"], "question": q["question"], "model": chat_model, "indexer": manifest["indexer"],
            "okf_version": manifest["okf_version"], "mode": args.action,
            "pageindex": importlib.metadata.version("pageindex"), "expected": q.get("expected"),
            "expected_sources": q.get("sources", []), "verdict": "À ÉVALUER MANUELLEMENT"}
    write(out / "metadata.json", meta)
    if args.action == "ask":
        client = pageindex_client(index_model, chat_model, key, url)
        with (out / "trace.txt").open("w", encoding="utf-8") as f:
            for chunk in client.chat(q["question"], doc_id=[d["doc_id"] for d in manifest["docs"]],
                                     citations=True, stream=True, max_turns=8,
                                     show_process={"thinking": False, "tool_call": True, "tool_result": True, "max_chars": 4000}):
                text = str(chunk)
                print(text, end="", flush=True)
                f.write(text)
                f.flush()
        # Trace deliberately includes tool events: evaluate final answer separately by inspection.
    else:
        response = llm_completion(model=chat_model, api_key=key, api_base=url, timeout=60,
                              messages=[{"role": "system", "content": INSTRUCTIONS},
                                        {"role": "user", "content": okf.full_text(bundle) + "\nQUESTION : " + q["question"]}])
        answer = response.choices[0].message.content
        (out / "answer.txt").write_text(answer or "", encoding="utf-8")
        print(answer)
        meta["usage"] = response.usage.model_dump() if response.usage else None
    meta["seconds"] = time.monotonic() - start
    write(out / "metadata.json", meta)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["check", "lint", "index", "ask", "baseline"])
    p.add_argument("--case", default="renvoi", choices=[q["id"] for q in load_questions()] or None)
    p.add_argument("--bundle", help="bundle OKF à contrôler (lint) ou à utiliser (sinon DEMO_BUNDLE, puis ./bundle)")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--output", help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.bundle:
        os.environ["DEMO_BUNDLE"] = str(Path(args.bundle).resolve())
    if args.action == "check":
        offline()
        return
    if args.action == "lint":
        raise SystemExit(lint(bundle_path()))
    run = ROOT / "runs" / f'{time.strftime("%Y%m%d-%H%M%S")}-{time.time_ns() % 1000000}-{args.action}-{args.case}'
    if args.action == "index":
        index(run)
        return
    if args.worker:
        worker(args)
        return
    _, _, key, url = configuration()  # fail fast, before spawning or sending anything
    problem = endpoint_error(url, key)
    if problem:
        raise ValueError(problem)
    run.mkdir(parents=True)
    cmd = [sys.executable, str(Path(__file__).resolve()), args.action, "--case", args.case, "--worker", "--output", str(run)]
    try:
        result = subprocess.run(cmd, timeout=args.timeout)
        write(run / "execution.json", {"returncode": result.returncode, "timeout_seconds": args.timeout})
        raise SystemExit(result.returncode)
    except subprocess.TimeoutExpired:
        write(run / "execution.json", {"status": "TIMEOUT", "timeout_seconds": args.timeout})
        print("Délai dépassé : processus interrompu. Des appels déjà reçus peuvent rester facturés.", file=sys.stderr)
        raise SystemExit(124)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Do not dump backend exception strings: they may contain headers or secrets.
        print(f"Échec ({type(e).__name__}). Vérifiez configuration, accès réseau et traces locales.", file=sys.stderr)
        if isinstance(e, ValueError):
            print(str(e), file=sys.stderr)
        raise SystemExit(1)
