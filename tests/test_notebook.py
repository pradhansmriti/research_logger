import json
import pathlib
import tempfile
import unittest
import notebook


class NotebookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = pathlib.Path(self.tmp.name)
        (self.repo / 'experiments').mkdir()
        (self.repo / 'outputs').mkdir()
        (self.repo / 'README.md').write_text('# Research\n## Q01 — Can we reproduce it?\n')
        (self.repo / 'TODO.md').write_text('- [ ] Q01 — Can we reproduce it?\n- [x] E00 — Baseline\n')
        (self.repo / 'outputs/plot.png').write_bytes(b'image')
        (self.repo / 'experiments/E00.md').write_text('# E00 — Baseline\n- **Status:** complete\n- **Question:** Q01 — reproduction\n- **Follow-up:** E01 — next\n- **Evidence:** [Plot](../outputs/plot.png)\n\n**Result:** Observed value.\n')
        (self.repo / 'experiments/E01.md').write_text('# E01 — Follow-up\n- **Depends on:** E00 — prerequisite\n')

    def test_read_and_refresh_explicit_fields(self):
        data = notebook.notebook_data(self.repo)
        nodes = {n['id']: n for n in data['nodes']}
        self.assertEqual(nodes['Q01']['status'], 'Open')
        self.assertEqual(nodes['E00']['status'], 'complete')
        self.assertEqual(nodes['E01']['status'], 'Unknown')
        self.assertEqual(nodes['E00']['figure'], 'outputs/plot.png')
        self.assertEqual(nodes['E00']['summary'], 'Observed value.')
        self.assertIn(('E01', 'E00', 'depends on'), {(e['from'], e['to'], e['relation']) for e in data['edges']})
        (self.repo / 'TODO.md').write_text('- [x] Q01 — Can we reproduce it?\n')
        self.assertEqual(notebook.notebook_data(self.repo)['nodes'][0]['status'], 'Complete')

    def test_missing_and_qualified_references_are_not_invented(self):
        (self.repo / 'experiments/E02.md').write_text('# E02\n- **Question:** Q99 — missing\n- **Depends on:** other/repo#E04\n')
        data = notebook.notebook_data(self.repo)
        self.assertTrue(any('missing Q99' in x for x in data['warnings']))
        self.assertTrue(any('unresolved depends on' in x for x in data['warnings']))
        self.assertFalse(any(e['to'] == 'E04' for e in data['edges']))

    def test_one_experiment_can_investigate_multiple_questions(self):
        with (self.repo / 'README.md').open('a') as f:
            f.write('## Q02 — A second question?\n')
        path = self.repo / 'experiments/E00.md'
        path.write_text(path.read_text().replace('Q01 — reproduction', 'Q01 — reproduction; Q02 — second question'))
        data = notebook.notebook_data(self.repo)
        targets = {e['to'] for e in data['edges'] if e['from'] == 'E00' and e['relation'] == 'investigates'}
        self.assertEqual(targets, {'Q01', 'Q02'})

    def test_subexperiment_sections_keep_separate_results_and_figures(self):
        (self.repo / 'outputs/second.png').write_bytes(b'second')
        path = self.repo / 'experiments/E00.md'
        path.write_text(path.read_text() + '\n## Internal\n- **Status:** complete\n- **Evidence:** [Plot](../outputs/plot.png)\n\n**Result:** Internal result.\n\n## External\n- **Status:** complete\n- **Evidence:** [Plot](../outputs/second.png)\n\n**Result:** External result.\n')
        node = next(n for n in notebook.notebook_data(self.repo)['nodes'] if n['id'] == 'E00')
        self.assertEqual([s['summary'] for s in node['sections']], ['Internal result.', 'External result.'])
        self.assertEqual([s['figures'][0]['path'] for s in node['sections']], ['outputs/plot.png', 'outputs/second.png'])
        self.assertEqual(node['status'], 'complete')
        handler = notebook.make_handler(self.repo)
        h = object.__new__(handler); h.path = '/figure?path=outputs%2Fsecond.png'; h.valid_host = lambda: True; result = {}
        h.respond = lambda status, data, content_type: result.update(status=status, data=data)
        h.do_GET()
        self.assertEqual(result['data'], b'second')

    def test_project_url_validation_and_heading_candidates(self):
        self.assertEqual(notebook.normalize_github_url('https://github.com/user/project.git'), 'https://github.com/user/project')
        for bad in ['https://github.com/user/project/extra', 'https://evil.example/user/repo', 'https://github.com/user/../../secret']:
            with self.assertRaises(ValueError): notebook.normalize_github_url(bad)
        (self.repo / 'notes.md').write_text('# Work\n## What changes?\nThe outcome is not stated.\n')
        self.assertIn({'question': 'What changes?', 'path': 'notes.md'}, notebook.question_candidates(self.repo))

    def test_project_registry_keeps_repositories_separate(self):
        import unittest.mock
        root = self.repo / 'registry'; p = notebook.Projects(self.repo, root / 'projects.json', root / 'repos')
        def clone(args, **kwargs):
            destination = pathlib.Path(args[-1]); destination.mkdir(parents=True)
            (destination / 'README.md').write_text('# Other project')
        with unittest.mock.patch('notebook.github_url', return_value=None), unittest.mock.patch('notebook.subprocess.run', side_effect=clone):
            entry = p.add('https://github.com/example/other')
        self.assertEqual(p.get(entry['id']).name, 'example--other')
        self.assertEqual(p.get('default'), self.repo.resolve())
        self.assertEqual(p.add('https://github.com/example/other')['id'], entry['id'])
        self.assertIsNone(p.get('../../secret'))

    def test_drafts_are_separate_and_detect_source_conflicts(self):
        root = self.repo / 'registry'
        projects = notebook.Projects(self.repo, root / 'projects.json', root / 'repos')
        path = 'experiments/E00.md'
        original = (self.repo / path).read_text()
        notebook.write_draft(projects, 'default', path, original + '\nDraft edit.\n')
        self.assertEqual((self.repo / path).read_text(), original)
        review = notebook.review_drafts(projects, 'default')
        self.assertIn('+Draft edit.', review[0]['diff'])
        self.assertFalse(review[0]['conflict'])
        (self.repo / path).write_text(original + '\nConcurrent change.\n')
        self.assertTrue(notebook.review_drafts(projects, 'default')[0]['conflict'])
        with self.assertRaises(ValueError): notebook.write_draft(projects, 'default', '../outside.md', 'bad')

    def test_comments_are_drafts_not_source_mutations(self):
        root = self.repo / 'registry'
        projects = notebook.Projects(self.repo, root / 'projects.json', root / 'repos')
        notebook.write_draft(projects, 'default', 'research-notebook/COMMENTS.md', '# Comments\n')
        self.assertFalse((self.repo / 'research-notebook/COMMENTS.md').exists())
        self.assertEqual(notebook.review_drafts(projects, 'default')[0]['content'], '# Comments\n')
        with self.assertRaises(ValueError): notebook.sync_drafts(projects, 'default', 'not-the-reviewed-hash')

    def test_organization_proposal_is_reviewable_and_preserves_sources(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            repo = pathlib.Path(d) / 'source'; repo.mkdir()
            original = '# Study\n## Does treatment help?\n### Experiment: Compare groups\nDetails are in the source.\n'
            (repo / 'README.md').write_text(original)
            projects = notebook.Projects(repo, pathlib.Path(d) / 'state/projects.json', pathlib.Path(d) / 'state/repos')
            result = notebook.propose_organization(projects, 'default')
            self.assertEqual((result['questions'], result['experiments']), (1, 1))
            self.assertEqual((repo / 'README.md').read_text(), original)
            self.assertFalse((repo / 'experiments').exists())
            drafts = notebook.review_drafts(projects, 'default')
            self.assertEqual(len(drafts), 3)
            with self.assertRaises(ValueError): notebook.propose_organization(projects, 'default')
            for draft in drafts:
                path = repo / draft['path']; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(draft['content'])
            nodes, edges, warnings = notebook.parse_notebook(repo)
            self.assertEqual({n['id'] for n in nodes}, {'Q00', 'E00'})
            self.assertEqual(edges[0]['to'], 'Q00')
            self.assertEqual(next(n for n in nodes if n['id']=='E00')['status'], 'unknown')
            self.assertEqual(warnings, [])

    def test_handler_only_serves_linked_local_files(self):
        handler = notebook.make_handler(self.repo)
        def get(path):
            h = object.__new__(handler); h.path = path; h.valid_host = lambda: True; result = {}
            h.respond = lambda status, data, content_type: result.update(status=status, data=data)
            h.do_GET(); return result
        self.assertEqual(get('/figure?path=outputs%2Fplot.png')['data'], b'image')
        self.assertEqual(get('/source?path=README.md')['status'], 200)
        self.assertEqual(get('/source?path=..%2Fsecret.md')['status'], 404)
        self.assertEqual(json.loads(get('/api/notebook')['data'])['nodes'][0]['id'], 'Q01')

if __name__ == '__main__':
    unittest.main()
