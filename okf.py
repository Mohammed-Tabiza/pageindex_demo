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
# Link to a concept of another bundle: `bundle-name:/path/concept.md#anchor`, the
# same form as question sources. The single slash keeps it apart from `https://`.
_CROSS = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):(/(?!/)\S*)$")
_ACTOR = re.compile(r"^(human:\S+|process:\S+|team:\S+|[^\s/:]+/\S+)$")
_DATE_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$")
_INDEX_ENTRY = re.compile(r"^[ \t]*[*-][ \t]+\[[^\]]+\]\([^)]+\)")
# A link sentence that hands the reader over to another concept, rather than
# merely mentioning it. Only these links make the target part of the answer.
# Verb forms are listed explicitly: a bare stem would also match "suivant",
# "suivi", "rapport…" or "consultation", which are not hand-overs.
REFERRAL = re.compile(
    r"\b(appliqu(?:er|ez|e|ent)|suiv(?:re|ez|ra|ront)|report(?:er|ez)|voir|consult(?:er|ez)|cf\b|"
    r"remplac(?:é|ée|és|ées|e|ent)|conformément|"
    r"apply|follow|follows|see|refer(?:s|red)?\s+to|superseded|replaced)\b", re.I)


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
    bundle: str | None = None    # other bundle named by a cross-bundle link
    concept: "Concept | None" = field(default=None, repr=False, compare=False)   # resolved target

    def as_dict(self):
        return {key: getattr(self, key) for key in
                ("text", "href", "section", "target", "anchor", "target_page", "referral", "broken", "bundle")}


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
    root: str = ""                  # bundle directory: keeps document ids distinct across bundles
    namespace: str | None = None    # bundle name, set when several bundles are queried together

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
        """PageIndex document name: '/' is not allowed in SDK file names.

        Prefixed with the bundle name only when several bundles are queried
        together: the SDK resolves names among the queried documents only."""
        prefix = f"{self.namespace}." if self.namespace else ""
        return prefix + self.id.replace("/", ".") + ".md"

    @property
    def key(self) -> str:
        """Reference used by question files: 'concept/id', or 'bundle:concept/id'."""
        return f"{self.namespace}:{self.id}" if self.namespace else self.id

    @property
    def doc_id(self) -> str:
        # The bundle directory takes part in the id, so that two bundles holding the
        # same concept path never overwrite each other in the shared store.
        return DOC_PREFIX + hashlib.sha256(f"{self.root}\n{self.id}".encode()).hexdigest()[:24]

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
    def name(self) -> str:
        return self.root.name

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


def _attach(bundle: Bundle, concept: Concept, link: Link, target: Concept | None, where: str) -> None:
    """Resolve `link` to `target` (a concept of `where`), or report it as broken."""
    if target is None:
        link.broken = True
        # §6.1 / §11: broken links are tolerated, only reported.
        bundle.issues.append(Issue("warning", concept.path, f"lien sans cible dans {where} : {link.href}"))
        return
    link.target, link.concept = target.id, target
    target_section = target.section_for(link.anchor)
    if link.anchor and target_section is None:
        bundle.issues.append(Issue("warning", concept.path, f"ancre introuvable : {link.href}"))
    link.target_page = target_section.page if target_section else None


def resolve_links(bundle: Bundle) -> None:
    """Links inside the bundle; cross-bundle links wait for resolve_cross_links."""
    for concept in bundle.concepts.values():
        for section in concept.sections:
            for match in _LINK.finditer(section.markdown):
                text, href = match.group(1), match.group(2)
                cross = _CROSS.match(href)
                path, anchor = resolve_href(concept.path, cross.group(2) if cross else href)
                if path is None or path.endswith("/") or PurePosixPath(path).name in RESERVED:
                    continue    # external links; directory listings are navigation, not concepts.
                link = Link(text=text, href=href, section=section.page, anchor=anchor,
                            referral=bool(REFERRAL.search(sentence_around(section.markdown, match.start(), match.end()))))
                if cross and cross.group(1) != bundle.name:
                    link.bundle = cross.group(1)
                else:
                    target = bundle.concepts.get(path.removesuffix(".md")) if path.endswith(".md") else None
                    _attach(bundle, concept, link, target, "le bundle")
                if link.broken:
                    link.referral = False
                concept.links.append(link)


def resolve_cross_links(bundles: list[Bundle]) -> None:
    """`other:/path.md` links, resolved only among the bundles queried together:
    a link to a bundle that is not loaded is reported and never followed."""
    by_name = {b.name: b for b in bundles}
    for bundle in bundles:
        for concept in bundle.concepts.values():
            for link in concept.links:
                if link.bundle is None:
                    continue
                other = by_name.get(link.bundle)
                if other is None:
                    link.broken, link.referral = True, False
                    bundle.issues.append(Issue("warning", concept.path,
                                               f"lien vers le bundle « {link.bundle} », non chargé : non suivi ({link.href})"))
                    continue
                path, _ = resolve_href("", _CROSS.match(link.href).group(2))
                target = other.concepts.get(path.removesuffix(".md")) if path and path.endswith(".md") else None
                _attach(bundle, concept, link, target, f"le bundle « {other.name} »")
                if link.broken:
                    link.referral = False


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
    bundle = _load_bundle(root)
    resolve_cross_links([bundle])
    return bundle


def _load_bundle(root: Path | str) -> Bundle:
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
        concept = Concept(path.removesuffix(".md"), path, hashlib.sha256(data).hexdigest(), frontmatter, body,
                          root=str(root))
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


def load_bundles(roots) -> list[Bundle]:
    """Several bundles queried together; concept names get the bundle name as prefix.

    OKF §6 paths are bundle-relative: `/procedures/x.md` always names a concept of
    the same bundle. Another bundle is named explicitly, `other:/procedures/x.md`,
    and is followed only when it is loaded too.
    """
    roots = list(dict.fromkeys(Path(r).resolve() for r in ([roots] if isinstance(roots, (str, Path)) else roots)))
    bundles = [_load_bundle(root) for root in roots]
    if len(bundles) > 1:
        names = [b.name for b in bundles]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError("Deux bundles portent le même nom de dossier : " + ", ".join(duplicates)
                             + ". Renommez l'un des dossiers.")
        for bundle in bundles:
            for concept in bundle.concepts.values():
                concept.namespace = bundle.name
    resolve_cross_links(bundles)
    return bundles


def _many(bundles) -> list[Bundle]:
    return [bundles] if isinstance(bundles, Bundle) else list(bundles)


def replacement(bundle: Bundle, concept: Concept) -> Concept | None:
    if not concept.superseded_by:
        return None
    path, _ = resolve_href(concept.path, concept.superseded_by)
    return bundle.concepts.get(path.removesuffix(".md")) if path else None


def replaced(bundle: Bundle, concept: Concept) -> list[Concept]:
    """Concepts whose superseded_by points at this one (the inverse link).

    Readers of the rule in force learn that an older, different rule exists,
    so a question quoting that older rule can be answered "no longer in force"
    rather than "not documented".
    """
    return sorted((c for c in bundle.concepts.values() if c is not concept
                   and (target := replacement(bundle, c)) is not None and target.id == concept.id),
                  key=lambda c: c.id)


# ── PageIndex adapter ──

def lifecycle_line(bundle: Bundle, concept: Concept, now: dt.datetime) -> str:
    """One line that travels with every page the agent reads."""
    parts = [f"OKF {concept.key}", concept.type, f"statut {concept.status}"]
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
    for old in replaced(bundle, concept):
        # Quote the old rule itself: small models do not open the deprecated concept on
        # their own, so without it they answer "not documented" instead of "no longer in force".
        parts.append(f"remplace {old.doc_name}, OBSOLÈTE, dont l'ancienne règle n'est plus en vigueur : "
                     f"« {summarize(old.sections[0].markdown, 160)} »")
    return "[" + " · ".join(parts) + "]"


def agent_page(bundle: Bundle, concept: Concept, section: Section, now: dt.datetime) -> str:
    """Page text given to the agent: links resolved to PageIndex names and pages,
    and footnotes resolved to their `sources` entry (§5.1 per-claim attribution)."""
    resolved = {link.href: link for link in concept.links if link.section == section.page}

    def annotate(match):
        link = resolved.get(match.group(2))
        target = link.concept if link else None
        if target is None:
            return match.group(0)
        target_section = target.section_for(link.anchor)
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
    olds = replaced(bundle, concept)
    suffix = f" (remplace {', '.join(c.doc_name for c in olds)}, obsolète)" if olds else ""
    return (prefix + f"{concept.type} · {concept.title}"
            + (f" — {concept.description}" if concept.description else "") + suffix)


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
        "supersedes": ", ".join(c.doc_name for c in replaced(bundle, concept)) or None,
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


def sync(bundles, storage_path: Path | str, now: dt.datetime | None = None) -> dict:
    """Mirror one or several bundles into the local PageIndex store, incrementally.

    Unchanged concepts keep their document; changed concepts (content or a
    freshness flip such as crossing `stale_after`) are rewritten in place, and
    concepts removed from a bundle are deleted. Each document records its
    bundle, so syncing one bundle never touches the documents of another.
    No LLM call is made.
    """
    from pageindex.local_store import DocStore

    bundles = _many(bundles)
    for bundle in bundles:
        if not bundle.conformant:
            raise ValueError(f"Bundle OKF non conforme ({bundle.root}) : corrigez les erreurs signalées par « demo.py lint ».")
    now = now or now_utc()
    store = DocStore(str(storage_path))
    stamp = now.isoformat().replace("+00:00", "Z")
    roots = {str(b.root) for b in bundles}
    docs, changed = [], []
    with store.lock():
        existing = {}
        for m in store.list_metas():
            owner = (m.get("metadata") or {}).get("okf_bundle")
            # Documents of the synced bundles, and legacy documents written before
            # bundles were recorded (their ids no longer match any concept).
            if str(m.get("id", "")).startswith(DOC_PREFIX) and (owner in roots or owner is None):
                existing[m["id"]] = m
        for bundle in bundles:
            for concept in sorted(bundle.concepts.values(), key=lambda c: c.id):
                data = rendered(bundle, concept, now)
                # The name takes part: it gains or loses its bundle prefix with the set of bundles.
                fingerprint = hashlib.sha256(json.dumps({"name": concept.doc_name, **data}, sort_keys=True,
                                                        ensure_ascii=False).encode()).hexdigest()
                current = existing.pop(concept.doc_id, None)
                if not current or (current.get("metadata") or {}).get("okf_fingerprint") != fingerprint:
                    meta = {
                        "id": concept.doc_id, "name": concept.doc_name, "description": data["description"],
                        "status": "completed", "createdAt": stamp, "pageNum": len(data["pages"]),
                        "folderId": None, "mode": "okf",
                        "metadata": {**data["metadata"], "okf_fingerprint": fingerprint, "okf_bundle": str(bundle.root)},
                    }
                    store.save_document(concept.doc_id, meta, data["tree"], data["pages"])
                    changed.append(concept.key)
                docs.append({"concept": concept.key, "bundle": bundle.name, "file": concept.path,
                             "doc_id": concept.doc_id, "name": concept.doc_name, "sha256": concept.sha256,
                             "fingerprint": fingerprint})
        for doc_id in existing:
            store.delete_document(doc_id)
    versions = sorted({b.version or SPEC_VERSION for b in bundles})
    return {"format": "okf", "okf_version": ", ".join(versions), "indexer": INDEXER,
            "bundle": ", ".join(str(b.root) for b in bundles), "bundles": [str(b.root) for b in bundles],
            "indexed_at": stamp, "docs": docs, "changed": changed, "removed": len(existing),
            "warnings": sum(len(b.issues) - len(b.errors) for b in bundles)}


def full_text(bundles, rendered: bool = False, now: dt.datetime | None = None) -> str:
    """Whole bundle in one text, for the full-context baselines.

    Each concept is a DOCUMENT named as in PageIndex and each section a numbered
    PAGE, so that the baselines cite with the same tags as the PageIndex agent.

    * raw: the YAML frontmatter and the section markdown as written;
    * rendered: exactly the pages the PageIndex agent reads (computed status
      line, annotated links, resolved sources), after the concept description.
    """
    now = now or now_utc()
    parts = []
    for bundle, c in ((b, c) for b in _many(bundles) for c in sorted(b.concepts.values(), key=lambda c: c.id)):
        if rendered:
            lines = [f"DOCUMENT {c.doc_name} — {description(bundle, c, now)}"]
            lines += [f"PAGE {s.page}\n{agent_page(bundle, c, s, now)}" for s in c.sections]
        else:
            text = (bundle.root / c.path).read_text(encoding="utf-8").lstrip("﻿")
            match = _FRONTMATTER.match(text)
            lines = [f"DOCUMENT {c.doc_name}", match.group(0).strip() if match else ""]
            lines += [f"PAGE {s.page}\n{s.markdown}" for s in c.sections]
            lines += [f"[^{label}]: {note}" for label, note in c.footnotes.items()]
        parts.append("\n\n".join(filter(None, lines)))
    return "\n\n".join(parts)


def report(bundles, now: dt.datetime | None = None) -> dict:
    """Conformance and lifecycle summary of one bundle, or of several queried together."""
    now = now or now_utc()
    bundles = _many(bundles)
    several = len(bundles) > 1
    concepts = [c for b in bundles for c in b.concepts.values()]
    count = lambda predicate: sum(1 for c in concepts if predicate(c))

    def issues(level):
        return [{**i.as_dict(), "path": f"{b.name}/{i.path}" if several else i.path}
                for b in bundles for i in b.issues if i.level == level]
    versions = sorted({str(b.version) for b in bundles})
    return {
        "bundle": ", ".join(str(b.root) for b in bundles),
        "okf_version": versions[0] if len(versions) == 1 else ", ".join(versions),
        "conformant": all(b.conformant for b in bundles),
        "concepts": len(concepts),
        "sections": sum(len(c.sections) for c in concepts),
        "links": sum(len(c.links) for c in concepts),
        "types": dict(sorted({c.type: count(lambda x, t=c.type: x.type == t) for c in concepts}.items())),
        "trust": {tier: count(lambda c, t=tier: c.trust_tier == t)
                  for tier in ("human-reviewed", "machine-confirmed", "unverified")},
        "status": {status: count(lambda c, s=status: c.status == s) for status in ("stable", "draft", "deprecated")},
        "stale": count(lambda c: c.is_stale(now)),
        "errors": issues("error"),
        "warnings": issues("warning"),
    }
