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

    def test_referral_verbs_ignore_look_alike_words(self):
        for sentence in ("Appliquer la section Relais.", "Suivez la procédure.", "Voir la fiche.",
                         "Elle est remplacée par la section.", "See the playbook.", "This refers to the runbook."):
            with self.subTest(sentence=sentence):
                self.assertTrue(okf.REFERRAL.search(sentence))
        for sentence in ("Le point suivant décrit le service.", "Le suivi est assuré par l'équipe.",
                         "Le rapport mensuel liste les incidents.", "La consultation du tableau est libre.",
                         "Le pouvoir de décision appartient au pilote.", "The following roles exist."):
            with self.subTest(sentence=sentence):
                self.assertIsNone(okf.REFERRAL.search(sentence))

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

    def test_replacement_announces_the_obsolete_rule_it_replaces(self):
        relais = self.bundle.concepts["procedures/astreinte-relais"]
        self.assertEqual([c.id for c in okf.replaced(self.bundle, relais)], ["procedures/escalade-p1-v1"])
        line = okf.agent_page(self.bundle, relais, relais.sections[1], NOW).splitlines()[0]
        self.assertIn("remplace procedures.escalade-p1-v1.md, OBSOLÈTE", line)
        self.assertIn("15 minutes", line)
        self.assertIn("directeur des opérations", line)
        self.assertIn("remplace procedures.escalade-p1-v1.md", okf.description(self.bundle, relais, NOW))
        self.assertEqual(okf.metadata(self.bundle, relais, NOW)["supersedes"], "procedures.escalade-p1-v1.md")
        incident = self.bundle.concepts["procedures/incident-p1"]
        self.assertEqual(okf.replaced(self.bundle, incident), [])
        self.assertNotIn("remplace", okf.agent_page(self.bundle, incident, incident.sections[0], NOW).splitlines()[0])

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

    def two_bundles(self):
        """Two copies of the demo bundle sharing every concept path; 'rh' has no services."""
        for name in ("ops", "rh"):
            shutil.copytree(ROOT / "bundle", self.root / name)
        shutil.rmtree(self.root / "rh" / "services")
        return [self.root / "ops", self.root / "rh"]

    def test_several_bundles_are_namespaced_and_keep_links_inside(self):
        ops, rh = okf.load_bundles(self.two_bundles())
        incident_ops, incident_rh = ops.concepts["procedures/incident-p1"], rh.concepts["procedures/incident-p1"]
        self.assertEqual((incident_ops.doc_name, incident_ops.key), ("ops.procedures.incident-p1.md", "ops:procedures/incident-p1"))
        self.assertNotEqual(incident_ops.doc_id, incident_rh.doc_id)
        page = okf.agent_page(ops, incident_ops, incident_ops.sections[1], NOW)
        self.assertIn("{→ ops.procedures.astreinte-relais.md, page 2}", page)
        # rh has no services/orion.md: the link is broken there, never resolved into ops.
        orion = next(l for l in incident_rh.links if l.href == "/services/orion.md")
        self.assertTrue(orion.broken)
        self.assertFalse(next(l for l in incident_ops.links if l.href == "/services/orion.md").broken)
        report = okf.report([ops, rh], NOW)
        self.assertEqual(report["concepts"], 21)
        self.assertTrue(any(w["path"].startswith("rh/") for w in report["warnings"]))
        text = okf.full_text([ops, rh], rendered=True, now=NOW)
        self.assertIn("DOCUMENT ops.procedures.incident-p1.md", text)
        self.assertIn("DOCUMENT rh.procedures.incident-p1.md", text)
        # A single bundle keeps unprefixed names: the evaluated scenario is unchanged.
        alone = okf.load_bundles([self.root / "ops"])[0].concepts["procedures/incident-p1"]
        self.assertEqual((alone.doc_name, alone.key), ("procedures.incident-p1.md", "procedures/incident-p1"))

    def test_security_bundle_scenario(self):
        """The shipped two-bundle scenario: conformant bundles, resolvable questions,
        and the contradicting draft flagged as such to the agent."""
        import json
        import demo
        bundles = okf.load_bundles([ROOT / "bundle", ROOT / "securite"])
        for bundle in bundles:
            self.assertTrue(bundle.conformant, bundle.errors)
            self.assertEqual(self.messages(bundle, "warning"), [], bundle.name)
        questions = json.loads((ROOT / "questions-multi.json").read_text(encoding="utf-8"))
        self.assertEqual([q["id"] for q in questions], ["croise", "fuite", "contradiction", "premisse", "secret"])
        for question in questions:
            for source in question["sources"]:
                demo.resolve_source(bundles, source)
        securite = bundles[1]
        draft, rule = securite.concepts["procedures/acces-urgence-astreinte"], securite.concepts["procedures/acces-urgence"]
        self.assertEqual((draft.status, draft.trust_tier), ("draft", "unverified"))
        self.assertEqual((rule.status, rule.trust_tier), ("stable", "human-reviewed"))
        self.assertIn("BROUILLON", okf.agent_page(securite, draft, draft.sections[0], NOW))
        self.assertIn("{→ securite.procedures.acces-urgence.md, page 1}", okf.agent_page(securite, draft, draft.sections[0], NOW))
        # The security procedure hands the P1 frequency over to the operations bundle.
        incident = securite.concepts["procedures/incident-securite"]
        link = next(l for l in incident.links if l.href.endswith("#communication"))
        self.assertEqual((link.bundle, link.target, link.target_page, link.referral), ("bundle", "procedures/incident-p1", 3, True))

        # A cited draft that rewrites a rule in force ("modifierait…", not a referral
        # verb) must still send the agent to that rule before it may answer.
        import web
        documents = [web.document(b, c, NOW) for b in bundles for c in b.concepts.values()]
        by_concept = {d["concept"]: d for d in documents}
        fake, in_force = by_concept["securite:procedures/acces-urgence-astreinte"], by_concept["securite:procedures/acces-urgence"]
        self.assertEqual(web.followups(documents, {(fake["id"], 1)}), {(fake["id"], in_force["id"]): {1}})
        resolved = {"citations": [{"doc_id": fake["id"], "page": 1}]}
        evidence = {(fake["id"], 1): {}}
        issues = web.answer_issues(resolved, documents, evidence)
        self.assertTrue(any("brouillon non validé" in i and in_force["stored_name"] in i for i in issues), issues)
        both = {"citations": [*resolved["citations"], {"doc_id": in_force["id"], "page": 1}]}
        self.assertEqual(web.answer_issues(both, documents, {**evidence, (in_force["id"], 1): {}}), [])
        # The operations draft only names a role: no extra reading is required,
        # so the evaluated 'brouillon' question is unchanged.
        urgent = by_concept["bundle:procedures/changement-urgent"]
        self.assertEqual(web.followups(documents, {(urgent["id"], 1)}), {})
        # Nothing in either bundle gives the emergency secret away.
        self.assertNotRegex(okf.full_text(bundles), r"(?i)mot de passe\s*:")

    def test_both_scenarios_together_without_bundle_prefix(self):
        """The 8 operations questions and the 5 security ones over both bundles:
        unprefixed sources resolve to the only bundle holding the concept."""
        import os
        import demo
        bundles = okf.load_bundles([ROOT / "bundle", ROOT / "securite"])
        concept, section = demo.resolve_source(bundles, "procedures/incident-p1#communication")
        self.assertEqual((concept.key, section.page), ("bundle:procedures/incident-p1", 3))
        concept, _ = demo.resolve_source(bundles, "procedures/acces-urgence#activation")
        self.assertEqual(concept.key, "securite:procedures/acces-urgence")
        files = os.pathsep.join(["questions.json", "questions-multi.json"])
        with patch.dict(os.environ, {"DEMO_QUESTIONS": files}):
            questions = demo.load_questions()
        self.assertEqual(len(questions), 13)
        for question in questions:
            for source in question["sources"]:
                demo.resolve_source(bundles, source)
        with patch.dict(os.environ, {"DEMO_QUESTIONS": os.pathsep.join(["questions.json", "questions.json"])}), \
             self.assertRaisesRegex(ValueError, "en double"):
            demo.load_questions()

    def test_links_between_bundles_are_explicit_and_followed_only_when_loaded(self):
        ops, rh = self.two_bundles()
        write(rh, "procedures/securite.md", """
            ---
            type: Playbook
            title: Sécurité
            ---
            # Alerte

            Pour la fréquence, appliquer la section Communication de la
            [procédure P1](ops:/procedures/incident-p1.md#communication).
            Mentions : [inconnue](ops:/procedures/inexistante.md), le [même bundle](rh:/roles/coordinateur-crise.md)
            et [https](https://wiki.exemple.invalid/x).
            """)
        bundle_ops, bundle_rh = okf.load_bundles([ops, rh])
        concept = bundle_rh.concepts["procedures/securite"]
        cross, unknown, same = concept.links
        target = bundle_ops.concepts["procedures/incident-p1"]
        self.assertEqual((cross.bundle, cross.target, cross.target_page, cross.referral, cross.broken),
                         ("ops", "procedures/incident-p1", 3, True, False))
        self.assertIs(cross.concept, target)
        self.assertTrue(unknown.broken)
        self.assertFalse(unknown.referral)
        self.assertIs(same.concept, bundle_rh.concepts["roles/coordinateur-crise"])
        self.assertEqual(len(concept.links), 3)    # the https link stays external
        messages = self.messages(bundle_rh, "warning")
        self.assertIn("procedures/securite.md: lien sans cible dans le bundle « ops » : ops:/procedures/inexistante.md", messages)
        page = okf.agent_page(bundle_rh, concept, concept.sections[0], NOW)
        self.assertIn("{→ ops.procedures.incident-p1.md, page 3}", page)
        self.assertIn("[OKF rh:procedures/securite ·", page)

        # The web layer resolves the target to the other bundle's document,
        # so the source checks require reading it once the section is cited.
        import web
        documents = [web.document(b, c, NOW) for b in (bundle_ops, bundle_rh) for c in b.concepts.values()]
        securite = next(d for d in documents if d["concept"] == "rh:procedures/securite")
        self.assertEqual(securite["links"][0]["target_doc"], target.doc_id)
        self.assertEqual(web.followups(documents, {(securite["id"], 1)}), {(securite["id"], target.doc_id): {3}})

        # Alone, the other bundle is not loaded: the link is reported and never followed.
        alone = okf.load_bundle(rh)
        link = alone.concepts["procedures/securite"].links[0]
        self.assertTrue(link.broken)
        self.assertIsNone(link.concept)
        self.assertTrue(any("non chargé" in m for m in self.messages(alone, "warning")))
        page = okf.agent_page(alone, alone.concepts["procedures/securite"], alone.concepts["procedures/securite"].sections[0], NOW)
        self.assertNotIn("{→", page.split("procédure P1")[1].split("\n")[0])

    def test_bundle_names_must_be_distinct(self):
        for parent in ("a", "b"):
            shutil.copytree(ROOT / "bundle", self.root / parent / "bundle")
        with self.assertRaisesRegex(ValueError, "même nom"):
            okf.load_bundles([self.root / "a" / "bundle", self.root / "b" / "bundle"])

    def test_sync_of_one_bundle_never_touches_another(self):
        from pageindex.local_store import DocStore
        paths = self.two_bundles()
        storage = self.root / ".pageindex"
        both = okf.sync(okf.load_bundles(paths), storage, NOW)
        self.assertEqual((len(both["docs"]), len(both["changed"])), (21, 21))
        alone = okf.sync(okf.load_bundles(paths[:1]), storage, NOW)
        self.assertEqual((len(alone["changed"]), alone["removed"]), (11, 0))     # names lose their prefix
        metas = DocStore(str(storage)).list_metas()
        self.assertEqual(len(metas), 21)
        self.assertEqual(sum(m["name"].startswith("rh.") for m in metas), 10)
        from pageindex import PageIndexClient
        client = PageIndexClient(index={"model": "openai/none", "storage_path": str(storage)},
                                 chat={"model": "openai/none"})
        # Same unprefixed name in the store for ops, resolved within the queried ids only.
        resolved = client.resolve_citations('<cite doc="procedures.astreinte-relais.md" page="2"/>',
                                            doc_id=[d["doc_id"] for d in alone["docs"]])
        self.assertEqual(resolved["citations"][0]["doc_id"], next(d["doc_id"] for d in alone["docs"]
                                                                 if d["concept"] == "procedures/astreinte-relais"))

    def test_legacy_documents_without_bundle_are_replaced(self):
        from pageindex.local_store import DocStore
        shutil.copytree(ROOT / "bundle", self.root / "bundle")
        storage = self.root / ".pageindex"
        store = DocStore(str(storage))
        with store.lock():
            # Written before bundles were recorded: same name, no okf_bundle, an id no concept has now.
            store.save_document("okf-legacy", {"id": "okf-legacy", "name": "procedures.incident-p1.md",
                                               "description": None, "status": "completed", "createdAt": "2026-11-01Z",
                                               "pageNum": 1, "folderId": None, "mode": "okf",
                                               "metadata": {"okf_fingerprint": "x"}},
                                [], [{"page_index": 1, "markdown": "# Ancien"}])
            self.assertIn("okf-legacy", {m["id"] for m in store.list_metas()})
        result = okf.sync(okf.load_bundle(self.root / "bundle"), storage, NOW)
        self.assertEqual(result["removed"], 1)
        self.assertNotIn("okf-legacy", {m["id"] for m in store.list_metas()})

    def test_non_conformant_bundle_is_not_indexed(self):
        write(self.root, "bad.md", "# no frontmatter\n")
        with self.assertRaisesRegex(ValueError, "non conforme"):
            okf.sync(okf.load_bundle(self.root), self.root / ".pageindex", NOW)

    def test_demo_now_override(self):
        with patch.dict("os.environ", {"DEMO_NOW": "2026-01-01T00:00:00Z"}):
            self.assertEqual(okf.now_utc().year, 2026)


if __name__ == "__main__":
    unittest.main()
