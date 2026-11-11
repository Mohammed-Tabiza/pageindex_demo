"""Offline checks of the OKF v0.2 reader, validator and PageIndex adapter."""
import datetime as dt
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

import okf

ROOT = Path(__file__).resolve().parent
NOW = dt.datetime(2026, 11, 11, 12, tzinfo=dt.timezone.utc)


def write(root, path, text):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


class BundleTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def messages(self, bundle, level):
        return [f"{i.path}: {i.message}" for i in bundle.issues if i.level == level]


class ConformanceTests(BundleTestCase):
    def test_demo_bundle_is_conformant_without_warnings(self):
        bundle = okf.load_bundle(ROOT / "bundle")
        self.assertTrue(bundle.conformant, bundle.errors)
        self.assertEqual(self.messages(bundle, "warning"), [])
        self.assertEqual(bundle.version, "0.2")

    def test_section_11_failures_are_errors(self):
        write(self.root, "no-frontmatter.md", "# Titre\n")
        write(self.root, "no-type.md", "---\ntitle: Sans type\n---\n# Titre\n")
        write(self.root, "broken-yaml.md", "---\ntype: [oops\n---\n")
        write(self.root, "sub/index.md", "---\ntitle: interdit\n---\n# Liste\n* [A](a.md) - a\n")
        write(self.root, "log.md", "---\ntype: Log\n---\n# Journal\n\n## 11/11/2026\n* **Update**: x\n")
        bundle = okf.load_bundle(self.root)
        self.assertFalse(bundle.conformant)
        errors = "\n".join(self.messages(bundle, "error"))
        for expected in ("no-frontmatter.md", "no-type.md", "broken-yaml.md", "sub/index.md", "log.md"):
            self.assertIn(expected, errors)
        self.assertEqual(bundle.concepts, {})

    def test_soft_constraints_never_reject_a_concept(self):
        # §11: unknown types, unknown keys, broken links and missing indexes are tolerated.
        write(self.root, "a.md", """
            ---
            type: Something Unheard Of
            custom_key: { nested: true }
            ---
            # Section
            See [missing](/nowhere.md) and [b](b.md#absent).
            """)
        write(self.root, "b.md", "---\ntype: Reference\n---\n# Only\n")
        bundle = okf.load_bundle(self.root)
        self.assertTrue(bundle.conformant)
        self.assertEqual(set(bundle.concepts), {"a", "b"})
        warnings = "\n".join(self.messages(bundle, "warning"))
        self.assertIn("/nowhere.md", warnings)
        self.assertIn("b.md#absent", warnings)

    def test_trust_lifecycle_and_actor_warnings(self):
        write(self.root, "c.md", """
            ---
            type: Metric
            status: archived
            generated: { at: 2026-01-01T00:00:00 }
            verified: { by: alice, at: 2026-01-02 }
            sources:
              - id: s1
            ---
            # Section
            Claim.[^s1] Other.[^s2]

            [^s1]: Source one
            [^s3]: Orphan
            """)
        warnings = "\n".join(self.messages(okf.load_bundle(self.root), "warning"))
        for expected in ("status inconnu", "generated.by", "fuseau", "acteur non conforme",
                         "requiert resource", "[^s3]", "[^s2]"):
            self.assertIn(expected, warnings)

    def test_hidden_directories_are_ignored(self):
        write(self.root, ".git/notes.md", "no frontmatter")
        write(self.root, "ok.md", "---\ntype: Reference\n---\n")
        self.assertTrue(okf.load_bundle(self.root).conformant)


class ConceptTests(BundleTestCase):
    def concept(self, frontmatter, body="# A\n"):
        write(self.root, "x.md", "---\n" + textwrap.dedent(frontmatter).strip() + "\n---\n" + body)
        return okf.load_bundle(self.root).concepts["x"]

    def test_trust_tiers_from_verified(self):
        self.assertEqual(self.concept("type: T").trust_tier, "unverified")
        self.assertEqual(self.concept("type: T\nverified: { by: process:nightly, at: 2026-01-01T00:00:00Z }").trust_tier,
                         "machine-confirmed")
        concept = self.concept("""
            type: T
            verified:
              - { by: process:nightly, at: 2026-01-01T00:00:00Z }
              - { by: human:alice, at: 2026-02-01T00:00:00Z }
            """)
        self.assertEqual(concept.trust_tier, "human-reviewed")
        self.assertEqual(concept.last_verified, "2026-02-01T00:00:00Z")

    def test_status_defaults_and_staleness(self):
        concept = self.concept("type: T\nstale_after: 2026-09-30T00:00:00Z")
        self.assertEqual(concept.status, "stable")
        self.assertTrue(concept.is_stale(NOW))
        self.assertFalse(concept.is_stale(dt.datetime(2026, 9, 29, tzinfo=dt.timezone.utc)))
        self.assertEqual(concept.lifecycle_flags(NOW), ["stale", "unverified"])

    def test_v01_timestamp_fallback(self):
        concept = self.concept("type: T\ntimestamp: '2026-05-28T22:53:05+00:00'")
        self.assertEqual(concept.generated["at"], "2026-05-28T22:53:05Z")

    def test_sections_anchors_and_code_fences(self):
        concept = self.concept("type: T\ntitle: Titre", textwrap.dedent("""
            Préambule sans titre.

            # Première étape
            Texte.
            ```
            # pas un titre
            ```
            ## Détail
            # Première étape
            """))
        self.assertEqual([s.title for s in concept.sections], ["Titre", "Première étape", "Détail", "Première étape"])
        self.assertEqual([s.anchor for s in concept.sections], ["titre", "première-étape", "détail", "première-étape-1"])
        tree = okf.tree(concept)
        self.assertEqual([n["title"] for n in tree], ["Titre", "Première étape", "Première étape"])
        self.assertEqual((tree[1]["start_index"], tree[1]["end_index"]), (2, 3))
        self.assertEqual(tree[1]["nodes"][0]["title"], "Détail")

    def test_link_resolution(self):
        self.assertEqual(okf.resolve_href("a/b/c.md", "../d.md#x"), ("a/d.md", "x"))
        self.assertEqual(okf.resolve_href("a/b/c.md", "/e/f.md"), ("e/f.md", None))
        self.assertEqual(okf.resolve_href("a/c.md", "#local"), ("a/c.md", "local"))
        self.assertEqual(okf.resolve_href("a/c.md", "https://example.com"), (None, None))
        self.assertEqual(okf.resolve_href("a/c.md", "sub/"), ("a/sub/", None))


class DemoBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = okf.load_bundle(ROOT / "bundle")

    def link(self, concept, href):
        return next(l for l in self.bundle.concepts[concept].links if l.href == href)

    def test_referrals_are_distinguished_from_mentions(self):
        referral = self.link("procedures/incident-p1", "/procedures/astreinte-relais.md#relais")
        self.assertTrue(referral.referral)
        self.assertEqual((referral.target, referral.target_page), ("procedures/astreinte-relais", 2))
        mention = self.link("procedures/incident-p1", "/procedures/communication-crise.md#canaux")
        self.assertFalse(mention.referral)
        self.assertTrue(self.link("procedures/escalade-p1-v1", "/procedures/astreinte-relais.md#relais").referral)

    def test_agent_page_carries_lifecycle_links_and_sources(self):
        deprecated = self.bundle.concepts["procedures/escalade-p1-v1"]
        page = okf.agent_page(self.bundle, deprecated, deprecated.sections[0], NOW)
        self.assertIn("OBSOLÈTE, remplacé par procedures.astreinte-relais.md", page.splitlines()[0])
        self.assertIn("https://wiki.exemple.invalid/ops/notes/escalade-2025", page)
        incident = self.bundle.concepts["procedures/incident-p1"]
        page = okf.agent_page(self.bundle, incident, incident.sections[1], NOW)
        self.assertIn("{→ procedures.astreinte-relais.md, page 2}", page)
        stale = self.bundle.concepts["procedures/communication-crise"]
        self.assertIn("PÉRIMÉ depuis le 2026-09-30", okf.agent_page(self.bundle, stale, stale.sections[0], NOW))

    def test_metadata_is_flat_for_the_agent(self):
        concept = self.bundle.concepts["procedures/changement-urgent"]
        metadata = okf.metadata(self.bundle, concept, NOW)
        self.assertTrue(all(isinstance(v, (str, int, float, bool)) for v in metadata.values()))
        self.assertEqual((metadata["status"], metadata["trust_tier"]), ("draft", "unverified"))
        self.assertTrue(okf.description(self.bundle, concept, NOW).startswith("[BROUILLON]"))


class StoreTests(BundleTestCase):
    def test_incremental_sync_and_sdk_round_trip(self):
        shutil.copytree(ROOT / "bundle", self.root / "bundle")
        storage = self.root / ".pageindex"
        bundle = okf.load_bundle(self.root / "bundle")
        first = okf.sync(bundle, storage, NOW)
        self.assertEqual(len(first["changed"]), 11)
        self.assertEqual(okf.sync(bundle, storage, NOW)["changed"], [])
        # Crossing stale_after changes what the agent reads, so the concept is rewritten.
        later = dt.datetime(2027, 4, 1, tzinfo=dt.timezone.utc)
        self.assertIn("procedures/incident-p1", okf.sync(bundle, storage, later)["changed"])
        (self.root / "bundle" / "roles" / "animateur-exercice.md").unlink()
        removed = okf.sync(okf.load_bundle(self.root / "bundle"), storage, NOW)
        self.assertEqual(removed["removed"], 1)

        from pageindex import PageIndexClient
        from pageindex import agent_tools
        client = PageIndexClient(index={"model": "openai/none", "storage_path": str(storage)},
                                 chat={"model": "openai/none"})
        ids = frozenset(d["doc_id"] for d in removed["docs"])
        structure, _ = agent_tools._get_document_structure(client, "procedures.incident-p1.md", _allowed_ids=ids)
        self.assertEqual([n["title"] for n in structure["structure"]],
                         ["Qualification", "Première escalade", "Communication", "Clôture"])
        relais = bundle.concepts["procedures/astreinte-relais"].doc_id
        page = client.get_page_content(relais, "2")[0]["markdown"]
        self.assertIn("coordinateur de crise", page)
        info, _ = agent_tools._get_document(client, "procedures.escalade-p1-v1.md", _allowed_ids=ids)
        self.assertEqual(info["metadata"]["superseded_by"], "procedures.astreinte-relais.md")
        resolved = client.resolve_citations('Réponse <cite doc="procedures.astreinte-relais.md" page="2"/>.', doc_id=list(ids))
        self.assertEqual(resolved["citations"][0]["doc_id"], relais)

    def test_non_conformant_bundle_is_not_indexed(self):
        write(self.root, "bad.md", "# no frontmatter\n")
        with self.assertRaisesRegex(ValueError, "non conforme"):
            okf.sync(okf.load_bundle(self.root), self.root / ".pageindex", NOW)

    def test_demo_now_override(self):
        with patch.dict("os.environ", {"DEMO_NOW": "2026-01-01T00:00:00Z"}):
            self.assertEqual(okf.now_utc().year, 2026)


if __name__ == "__main__":
    unittest.main()
