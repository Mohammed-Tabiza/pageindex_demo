"""Open Knowledge Format (OKF v0.2) bundles for the PageIndex demonstrator.

The module reads a bundle (a directory of markdown concepts with YAML
frontmatter), checks it against the conformance rules of the specification
(§11), derives the trust tier, lifecycle and freshness of each concept (§5),
resolves cross-links (§6) and stores every concept in the local PageIndex
document store without any LLM call:

* one PageIndex document per concept, named after its concept ID;
* one PageIndex "page" per markdown section, so a citation designates a
  section rather than an arbitrary chunk;
* a tree built from the heading hierarchy, with deterministic summaries;
* the flat OKF signals exposed as document metadata, which the PageIndex
  agent sees when it browses the library.

Specification: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

SPEC_VERSION = "0.2"
INDEXER = "okf-pageindex/1"
RESERVED = {"index.md", "log.md"}
STATUSES = {"draft", "stable", "deprecated"}
DOC_PREFIX = "okf-"

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(```|~~~)")
_FOOTNOTE_DEF = re.compile(r"^\[\^([^\]\s]+)\]:[ \t]*(.*)$")
_FOOTNOTE_REF = re.compile(r"\[\^([^\]\s]+)\](?!:)")
_LINK = re.compile(r"(?<!!)\[([^\]\n]*)\]\(<?([^)\s>]+)>?(?:[ \t]+\"[^\"]*\")?\)")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
_ACTOR = re.compile(r"^(human:\S+|process:\S+|team:\S+|[^\s/:]+/\S+)$")
_DATE_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$")
_INDEX_ENTRY = re.compile(r"^[ \t]*[*-][ \t]+\[[^\]]+\]\([^)]+\)")
# A link sentence that hands the reader over to another concept, rather than
# merely mentioning it. Only these links make the target part of the answer.
REFERRAL = re.compile(
    r"\b(appliqu\w*|suiv\w*|report\w*|voir|consult\w*|cf\b|remplac\w*|conformément|"
    r"apply|follow|see|refer\w*|superseded|replaced)", re.I)


@dataclass
class Issue:
    level: str          # "error" breaks conformance (§11); "warning" is soft guidance.
    path: str
    message: str

    def as_dict(self):
        return {"level": self.level, "path": self.path, "message": self.message}


@dataclass
class Link:
    text: str
    href: str
    section: int                 # page (section) holding the link
    target: str | None = None    # resolved concept ID
    anchor: str | None = None
    target_page: int | None = None
    referral: bool = False
    broken: bool = False

    def as_dict(self):
        return {key: getattr(self, key) for key in
                ("text", "href", "section", "target", "anchor", "target_page", "referral", "broken")}


@dataclass
class Section:
    page: int
    level: int
    title: str
    anchor: str
    markdown: str        # original markdown, heading included
    footnotes: list[str] = field(default_factory=list)


@dataclass
class Concept:
    id: str
    path: str
    sha256: str
    frontmatter: dict
    body: str
    sections: list[Section] = field(default_factory=list)
    footnotes: dict[str, str] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)

    # ── §4.1 recommended fields ──
    @property
    def type(self) -> str:
        return str(self.frontmatter.get("type") or "").strip()

    @property
    def title(self) -> str:
        title = self.frontmatter.get("title")
        return str(title).strip() if title else PurePosixPath(self.id).name.replace("-", " ").capitalize()

    @property
    def description(self) -> str:
        return str(self.frontmatter.get("description") or "").strip()

    @property
    def tags(self) -> list[str]:
        tags = self.frontmatter.get("tags") or []
        return [str(tag) for tag in tags] if isinstance(tags, list) else [str(tags)]

    @property
    def doc_name(self) -> str:
        """PageIndex document name: '/' is not allowed in SDK file names."""
        return self.id.replace("/", ".") + ".md"

    @property
    def doc_id(self) -> str:
        return DOC_PREFIX + hashlib.sha256(self.id.encode()).hexdigest()[:24]

    # ── §5 provenance, trust, lifecycle ──
    @property
    def status(self) -> str:
        status = str(self.frontmatter.get("status") or "stable").strip().lower()
        return status if status in STATUSES else "stable"

    @property
    def verified(self) -> list[dict]:
        value = self.frontmatter.get("verified")
        if isinstance(value, dict):          # §5.2: a bare mapping is a one-element list.
            value = [value]
        return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []

    @property
    def trust_tier(self) -> str:
        actors = [str(v.get("by", "")) for v in self.verified]
        if not actors:
            return "unverified"
        return "human-reviewed" if any(a.startswith("human:") for a in actors) else "machine-confirmed"

    @property
    def last_verified(self) -> str | None:
        dates = [iso(v.get("at")) for v in self.verified if v.get("at") is not None]
        return max(dates) if dates else None

    @property
    def generated(self) -> dict:
        value = self.frontmatter.get("generated")
        if isinstance(value, dict):
            return {"by": value.get("by"), "at": iso(value.get("at"))}
        legacy = self.frontmatter.get("timestamp")    # §13.1 fallback for v0.1 concepts.
        return {"by": None, "at": iso(legacy)} if legacy else {}

    @property
    def stale_after(self) -> str | None:
        value = self.frontmatter.get("stale_after")
        return iso(value) if value else None

    def is_stale(self, now: dt.datetime) -> bool:
        limit = parse_time(self.frontmatter.get("stale_after"))
        return limit is not None and now >= limit

    @property
    def sources(self) -> list[dict]:
        value = self.frontmatter.get("sources")
        return [s for s in value if isinstance(s, dict)] if isinstance(value, list) else []

    @property
    def superseded_by(self) -> str | None:
        """Producer-defined extension key used by this bundle; OKF allows it (§4.1)."""
        value = self.frontmatter.get("superseded_by")
        return str(value) if value else None

    def section_for(self, anchor: str | None) -> Section | None:
        if not anchor:
            return None
        anchor = slug(anchor)
        return next((s for s in self.sections if s.anchor == anchor), None)

    def lifecycle_flags(self, now: dt.datetime) -> list[str]:
        flags = []
        if self.status == "deprecated":
            flags.append("deprecated")
        if self.status == "draft":
            flags.append("draft")
        if self.is_stale(now):
            flags.append("stale")
        if self.trust_tier == "unverified":
            flags.append("unverified")
        return flags


@dataclass
class Bundle:
    root: Path
    version: str | None
    concepts: dict[str, Concept]
    indexes: dict[str, str]          # directory → index.md body
    logs: dict[str, str]
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def conformant(self) -> bool:
        return not self.errors

    def by_doc_id(self) -> dict[str, Concept]:
        return {c.doc_id: c for c in self.concepts.values()}


# ── helpers ──

def now_utc() -> dt.datetime:
    """Current instant, overridable with DEMO_NOW for reproducible demos and tests."""
    forced = os.getenv("DEMO_NOW", "").strip()
    return parse_time(forced) or dt.datetime.now(dt.timezone.utc)


def parse_time(value) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    return None


def iso(value) -> str | None:
    parsed = parse_time(value)
    if parsed is None:
        return str(value) if value is not None else None
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def has_offset(value) -> bool:
    if isinstance(value, dt.datetime):
        return value.tzinfo is not None
    if isinstance(value, str):
        return bool(re.search(r"(Z|[+-]\d{2}:?\d{2})$", value.strip()))
    return False


def slug(text: str) -> str:
    """GitHub-style heading anchor, accents kept."""
    text = re.sub(r"[`*_~\[\]()]", "", text.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def split_frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    """Return (frontmatter, body, error). frontmatter is None when absent."""
    text = text.lstrip("﻿")
    match = _FRONTMATTER.match(text)
    if not match:
        return None, text, None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as error:
        return None, text[match.end():], f"frontmatter YAML illisible ({error.__class__.__name__})"
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, text[match.end():], "le frontmatter doit être un dictionnaire YAML"
    return data, text[match.end():], None


def plain(markdown: str) -> str:
    text = _FOOTNOTE_REF.sub("", markdown)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = re.sub(r"^#{1,6}[ \t]+", "", text, flags=re.M)
    text = re.sub(r"[*_`|>]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def summarize(markdown: str, limit: int = 220) -> str:
    text = plain("\n".join(markdown.splitlines()[1:]) if markdown.startswith("#") else markdown)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


# ── parsing ──

def parse_sections(concept: Concept) -> None:
    """Split the body into sections (one PageIndex page each) and footnotes."""
    lines = concept.body.splitlines()
    sections: list[tuple[int, str, list[str]]] = []
    preamble: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE.match(line):
            in_fence = not in_fence
        footnote = None if in_fence else _FOOTNOTE_DEF.match(line)
        if footnote:
            concept.footnotes[footnote.group(1)] = footnote.group(2).strip()
            continue
        heading = None if in_fence else _HEADING.match(line)
        if heading:
            sections.append((len(heading.group(1)), heading.group(2).strip(), [line]))
        elif sections:
            sections[-1][2].append(line)
        else:
            preamble.append(line)
    if "\n".join(preamble).strip():
        sections.insert(0, (1, concept.title, ["# " + concept.title, *preamble]))
    if not sections:
        sections = [(1, concept.title, ["# " + concept.title])]
    used: dict[str, int] = {}
    for page, (level, title, body) in enumerate(sections, 1):
        anchor = slug(title)
        if anchor in used:                      # GitHub suffixes duplicate anchors.
            used[anchor] += 1
            anchor = f"{anchor}-{used[anchor]}"
        else:
            used[anchor] = 0
        markdown = "\n".join(body).strip()
        refs = list(dict.fromkeys(_FOOTNOTE_REF.findall(markdown)))
        concept.sections.append(Section(page, level, title, anchor, markdown, refs))


def resolve_href(concept_path: str, href: str) -> tuple[str | None, str | None]:
    """Resolve a markdown link (§6.1) to (bundle path, anchor); None for external links."""
    if _SCHEME.match(href) or href.startswith("//"):
        return None, None
    path, _, anchor = href.partition("#")
    if not path:
        return concept_path, anchor or None
    if path.startswith("/"):
        target = PurePosixPath(path.lstrip("/"))
    else:
        target = PurePosixPath(concept_path).parent / path
    parts: list[str] = []
    for part in target.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    resolved = "/".join(parts)
    if path.endswith("/"):
        resolved += "/"
    return resolved, anchor or None


def sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(mark, 0, start) for mark in (". ", "\n\n", ": ", "; "))
    rights = [p for p in (text.find(mark, end) for mark in (". ", ".\n", "\n\n")) if p != -1]
    return text[max(left, 0):min(rights) if rights else len(text)]


def resolve_links(bundle: Bundle) -> None:
    for concept in bundle.concepts.values():
        for section in concept.sections:
            for match in _LINK.finditer(section.markdown):
                text, href = match.group(1), match.group(2)
                path, anchor = resolve_href(concept.path, href)
                if path is None:
                    continue
                link = Link(text=text, href=href, section=section.page, anchor=anchor)
                if path.endswith("/") or PurePosixPath(path).name in RESERVED:
                    continue    # directory listings are navigation, not concepts.
                target = bundle.concepts.get(path.removesuffix(".md")) if path.endswith(".md") else None
                if target is None:
                    link.broken = True
                    # §6.1 / §11: broken links are tolerated, only reported.
                    bundle.issues.append(Issue("warning", concept.path, f"lien sans cible dans le bundle : {href}"))
                else:
                    link.target = target.id
                    target_section = target.section_for(anchor)
                    if anchor and target_section is None:
                        bundle.issues.append(Issue("warning", concept.path, f"ancre introuvable : {href}"))
                    link.target_page = target_section.page if target_section else None
                    link.referral = bool(REFERRAL.search(sentence_around(section.markdown, match.start(), match.end())))
                concept.links.append(link)


def check_concept(concept: Concept, issues: list[Issue]) -> None:
    """Soft checks from §5 to §7; only §11 failures are errors."""
    fm, path = concept.frontmatter, concept.path

    def warn(message):
        issues.append(Issue("warning", path, message))

    status = fm.get("status")
    if status is not None and str(status).lower() not in STATUSES:
        warn(f"status inconnu « {status} » (draft | stable | deprecated) ; traité comme stable")
    generated = fm.get("generated")
    if generated is not None:
        if not isinstance(generated, dict) or not generated.get("by"):
            warn("generated.by est requis dans generated (§5.2)")
        elif not _ACTOR.match(str(generated["by"])):
            warn(f"acteur non conforme dans generated.by : {generated['by']} (§7)")
        if isinstance(generated, dict) and generated.get("at") is not None and not has_offset(generated["at"]):
            warn("generated.at doit porter un fuseau explicite, par exemple Z (§5)")
    if "timestamp" in fm and generated is None:
        warn("timestamp est un champ v0.1 : utilisez generated.at (§13.1)")
    raw_verified = fm.get("verified")
    if raw_verified is not None and not concept.verified:
        warn("verified doit être une liste ou un dictionnaire { by, at } (§5.2)")
    for entry in concept.verified:
        if not entry.get("by") or not _ACTOR.match(str(entry["by"])):
            warn(f"acteur non conforme dans verified : {entry.get('by')} (§7)")
        if entry.get("at") is None or not has_offset(entry["at"]):
            warn("verified[].at doit être une date ISO 8601 avec fuseau (§5)")
    if fm.get("stale_after") is not None and (parse_time(fm["stale_after"]) is None or not has_offset(fm["stale_after"])):
        warn("stale_after doit être un instant ISO 8601 avec fuseau (§5.5)")
    ids = set()
    raw_sources = fm.get("sources")
    if raw_sources is not None and not isinstance(raw_sources, list):
        warn("sources doit être une liste (§5.1)")
    for source in concept.sources:
        if not source.get("resource"):
            warn("chaque entrée de sources requiert resource (§5.1)")
        if source.get("id"):
            ids.add(str(source["id"]))
    for label in concept.footnotes:
        if label not in ids:
            warn(f"note [^{label}] sans entrée sources correspondante (§5.1)")
    for section in concept.sections:
        for label in section.footnotes:
            if label not in concept.footnotes:
                warn(f"note [^{label}] citée mais non définie")
    if concept.type == "Attested Computation" and not fm.get("runtime"):
        warn("runtime est requis pour une Attested Computation (§10.2)")


def check_index(path: str, text: str, is_root: bool, issues: list[Issue]) -> tuple[str, str | None]:
    frontmatter, body, error = split_frontmatter(text)
    version = None
    if error:
        issues.append(Issue("error", path, error))
    elif frontmatter is not None:
        extra = set(frontmatter) - {"okf_version"}
        if not is_root or extra:
            issues.append(Issue("error", path, "index.md ne porte pas de frontmatter, sauf okf_version à la racine (§8)"))
        version = frontmatter.get("okf_version")
        version = str(version) if version is not None else None
    if not any(_INDEX_ENTRY.match(line) for line in body.splitlines()):
        issues.append(Issue("warning", path, "index.md sans entrée « * [Titre](lien) - description » (§8)"))
    return body, version


def check_log(path: str, text: str, issues: list[Issue]) -> str:
    # §9 says nothing about frontmatter in log.md (§8 forbids it only in index.md):
    # the official acme_retail sample carries one, so it is tolerated.
    _, body, _ = split_frontmatter(text)
    dates = []
    for line in body.splitlines():
        match = _DATE_HEADING.match(line)
        if not match:
            continue
        try:
            dates.append(dt.date.fromisoformat(match.group(1)))
        except ValueError:
            issues.append(Issue("error", path, f"titre de date non ISO 8601 (YYYY-MM-DD) : {match.group(1)} (§9)"))
    if dates != sorted(dates, reverse=True):
        issues.append(Issue("warning", path, "les entrées du journal doivent aller de la plus récente à la plus ancienne (§9)"))
    return body


def load_bundle(root: Path | str) -> Bundle:
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Bundle OKF introuvable : {root}")
    bundle = Bundle(root, None, {}, {}, {}, [])
    for file in sorted(root.rglob("*.md")):
        relative = file.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        path = relative.as_posix()
        data = file.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            bundle.issues.append(Issue("error", path, "le fichier doit être encodé en UTF-8 (§4)"))
            continue
        directory = relative.parent.as_posix()
        if file.name == "index.md":
            body, version = check_index(path, text, directory == ".", bundle.issues)
            bundle.indexes[directory] = body
            if directory == ".":
                bundle.version = version
            continue
        if file.name == "log.md":
            bundle.logs[directory] = check_log(path, text, bundle.issues)
            continue
        frontmatter, body, error = split_frontmatter(text)
        if error or frontmatter is None:
            bundle.issues.append(Issue("error", path, error or "frontmatter YAML absent (§11.1)"))
            continue
        concept = Concept(path.removesuffix(".md"), path, hashlib.sha256(data).hexdigest(), frontmatter, body)
        if not concept.type:
            bundle.issues.append(Issue("error", path, "champ type absent ou vide (§11.2)"))
            continue
        parse_sections(concept)
        check_concept(concept, bundle.issues)
        bundle.concepts[concept.id] = concept
    if bundle.version is not None and bundle.version.split(".")[0] != SPEC_VERSION.split(".")[0]:
        bundle.issues.append(Issue("warning", "index.md", f"okf_version {bundle.version} : lecture au mieux (§12)"))
    for concept in bundle.concepts.values():
        if concept.superseded_by:
            path, _ = resolve_href(concept.path, concept.superseded_by)
            if not path or path.removesuffix(".md") not in bundle.concepts:
                bundle.issues.append(Issue("warning", concept.path, f"superseded_by sans cible : {concept.superseded_by}"))
    resolve_links(bundle)
    return bundle


def replacement(bundle: Bundle, concept: Concept) -> Concept | None:
    if not concept.superseded_by:
        return None
    path, _ = resolve_href(concept.path, concept.superseded_by)
    return bundle.concepts.get(path.removesuffix(".md")) if path else None


# ── PageIndex adapter ──

def lifecycle_line(bundle: Bundle, concept: Concept, now: dt.datetime) -> str:
    """One line that travels with every page the agent reads."""
    parts = [f"OKF {concept.id}", concept.type, f"statut {concept.status}"]
    tier = concept.trust_tier
    if concept.last_verified:
        tier += f", vérifié le {concept.last_verified[:10]}"
    parts.append(f"confiance {tier}")
    if concept.is_stale(now):
        parts.append(f"PÉRIMÉ depuis le {concept.stale_after[:10]}")
    elif concept.stale_after:
        parts.append(f"valable jusqu'au {concept.stale_after[:10]}")
    target = replacement(bundle, concept)
    if concept.status == "deprecated":
        parts.append("OBSOLÈTE" + (f", remplacé par {target.doc_name}" if target else ""))
    if concept.status == "draft":
        parts.append("BROUILLON non validé")
    return "[" + " · ".join(parts) + "]"


def agent_page(bundle: Bundle, concept: Concept, section: Section, now: dt.datetime) -> str:
    """Page text given to the agent: links resolved to PageIndex names and pages,
    and footnotes resolved to their `sources` entry (§5.1 per-claim attribution)."""
    def annotate(match):
        path, anchor = resolve_href(concept.path, match.group(2))
        if path is None:
            return match.group(0)
        target = bundle.concepts.get(path.removesuffix(".md"))
        if target is None:
            return match.group(0)
        target_section = target.section_for(anchor)
        count = len(target.sections)
        where = f"page {target_section.page}" if target_section else ("page 1" if count == 1 else f"pages 1-{count}")
        return f"{match.group(0)} {{→ {target.doc_name}, {where}}}"

    text = _LINK.sub(annotate, section.markdown)
    sources = {str(s.get("id")): s for s in concept.sources if s.get("id")}
    notes = []
    for label in section.footnotes:
        source = sources.get(label, {})
        detail = [concept.footnotes.get(label) or source.get("title") or label]
        if source.get("resource"):
            detail.append(str(source["resource"]))
        if source.get("author"):
            detail.append(f"auteur {source['author']}")
        if source.get("last_modified"):
            detail.append(f"modifiée le {iso(source['last_modified'])[:10]}")
        notes.append(f"[^{label}]: " + " — ".join(detail))
    return "\n\n".join(filter(None, [lifecycle_line(bundle, concept, now), text, "\n".join(notes)]))


def tree(concept: Concept) -> list[dict]:
    """Nest sections by heading level; each node spans its own page and its children's."""
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for number, section in enumerate(concept.sections, 1):
        node = {"title": section.title, "node_id": f"{number:04d}", "start_index": section.page,
                "end_index": section.page, "summary": summarize(section.markdown)}
        while stack and stack[-1][0] >= section.level:
            stack.pop()
        if stack:
            stack[-1][1].setdefault("nodes", []).append(node)
        else:
            roots.append(node)
        for _, parent in stack:
            parent["end_index"] = section.page
        stack.append((section.level, node))
    return roots


def description(bundle: Bundle, concept: Concept, now: dt.datetime) -> str:
    flags = []
    if concept.status == "deprecated":
        target = replacement(bundle, concept)
        flags.append("OBSOLÈTE" + (f" — remplacé par {target.doc_name}" if target else ""))
    if concept.status == "draft":
        flags.append("BROUILLON")
    if concept.is_stale(now):
        flags.append(f"PÉRIMÉ depuis le {concept.stale_after[:10]}")
    prefix = "[" + " · ".join(flags) + "] " if flags else ""
    return prefix + f"{concept.type} · {concept.title}" + (f" — {concept.description}" if concept.description else "")


def metadata(bundle: Bundle, concept: Concept, now: dt.datetime) -> dict:
    """Flat values only: the SDK hides nested metadata from the agent."""
    target = replacement(bundle, concept)
    values = {
        "okf_concept": concept.id,
        "okf_type": concept.type,
        "title": concept.title,
        "status": concept.status,
        "trust_tier": concept.trust_tier,
        "last_verified": concept.last_verified,
        "generated_by": concept.generated.get("by"),
        "generated_at": concept.generated.get("at"),
        "stale_after": concept.stale_after,
        "stale": concept.is_stale(now),
        "tags": ", ".join(concept.tags) or None,
        "sources": len(concept.sources),
        "superseded_by": target.doc_name if target else None,
        "resource": concept.frontmatter.get("resource"),
    }
    return {key: value for key, value in values.items() if value is not None and value != ""}


def rendered(bundle: Bundle, concept: Concept, now: dt.datetime) -> dict:
    return {
        "description": description(bundle, concept, now),
        "metadata": metadata(bundle, concept, now),
        "tree": tree(concept),
        "pages": [{"page_index": s.page, "markdown": agent_page(bundle, concept, s, now)} for s in concept.sections],
    }


def sync(bundle: Bundle, storage_path: Path | str, now: dt.datetime | None = None) -> dict:
    """Mirror the bundle into the local PageIndex store, incrementally.

    Unchanged concepts keep their document; changed concepts (content or a
    freshness flip such as crossing `stale_after`) are rewritten in place, and
    concepts removed from the bundle are deleted. No LLM call is made.
    """
    from pageindex.local_store import DocStore

    if not bundle.conformant:
        raise ValueError("Bundle OKF non conforme : corrigez les erreurs signalées par « demo.py lint ».")
    now = now or now_utc()
    store = DocStore(str(storage_path))
    stamp = now.isoformat().replace("+00:00", "Z")
    docs, changed = [], []
    with store.lock():
        existing = {m["id"]: m for m in store.list_metas() if str(m.get("id", "")).startswith(DOC_PREFIX)}
        for concept in sorted(bundle.concepts.values(), key=lambda c: c.id):
            data = rendered(bundle, concept, now)
            fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            current = existing.pop(concept.doc_id, None)
            if not current or (current.get("metadata") or {}).get("okf_fingerprint") != fingerprint:
                meta = {
                    "id": concept.doc_id, "name": concept.doc_name, "description": data["description"],
                    "status": "completed", "createdAt": stamp, "pageNum": len(data["pages"]),
                    "folderId": None, "mode": "okf",
                    "metadata": {**data["metadata"], "okf_fingerprint": fingerprint},
                }
                store.save_document(concept.doc_id, meta, data["tree"], data["pages"])
                changed.append(concept.id)
            docs.append({"concept": concept.id, "file": concept.path, "doc_id": concept.doc_id,
                         "name": concept.doc_name, "sha256": concept.sha256, "fingerprint": fingerprint})
        for doc_id in existing:
            store.delete_document(doc_id)
    return {"format": "okf", "okf_version": bundle.version or SPEC_VERSION, "indexer": INDEXER,
            "bundle": str(bundle.root), "indexed_at": stamp, "docs": docs,
            "changed": changed, "removed": len(existing),
            "warnings": len(bundle.issues) - len(bundle.errors)}


def full_text(bundle: Bundle) -> str:
    """Whole bundle as raw markdown, for the full-context baseline."""
    return "\n\n".join(f"SOURCE {c.doc_name}\n" + (bundle.root / c.path).read_text(encoding="utf-8")
                       for c in sorted(bundle.concepts.values(), key=lambda c: c.id))


def report(bundle: Bundle, now: dt.datetime | None = None) -> dict:
    now = now or now_utc()
    concepts = bundle.concepts.values()
    count = lambda predicate: sum(1 for c in concepts if predicate(c))
    return {
        "bundle": str(bundle.root), "okf_version": bundle.version, "conformant": bundle.conformant,
        "concepts": len(bundle.concepts),
        "sections": sum(len(c.sections) for c in concepts),
        "links": sum(len(c.links) for c in concepts),
        "types": dict(sorted({c.type: count(lambda x, t=c.type: x.type == t) for c in concepts}.items())),
        "trust": {tier: count(lambda c, t=tier: c.trust_tier == t)
                  for tier in ("human-reviewed", "machine-confirmed", "unverified")},
        "status": {status: count(lambda c, s=status: c.status == s) for status in ("stable", "draft", "deprecated")},
        "stale": count(lambda c: c.is_stale(now)),
        "errors": [i.as_dict() for i in bundle.errors],
        "warnings": [i.as_dict() for i in bundle.issues if i.level == "warning"],
    }
