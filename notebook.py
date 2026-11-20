#!/usr/bin/env python3
"""Local, read-only research notebook. Run with Python 3.9+."""
import argparse
import difflib
import hashlib
import tempfile
import http.server
import json
import mimetypes
import os
import secrets
import threading
import pathlib
import re
import subprocess
import urllib.parse
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent
BINDING_URL = 'https://github.com/pradhansmriti/binding_affinity_v2'
ID = r'[EQ]\d+'
REGISTRY = ROOT / '.local' / 'projects.json'
CHECKOUTS = ROOT / '.local' / 'repositories'



def git(repo, *args):
    try:
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def safe_file(repo, name):
    path = (repo / name).resolve()
    if not path.is_relative_to(repo.resolve()) or not path.is_file():
        return None
    return path


def github_url(repo):
    remote = git(repo, 'remote', 'get-url', 'origin') or ''
    match = re.fullmatch(r'(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?', remote)
    return 'https://github.com/' + match.group(1) if match else None


def local_links(repo, markdown_path, text):
    links = []
    for label, target in re.findall(r'\[([^\]]+)\]\(([^)]+)\)', text):
        target = target.split('#', 1)[0]
        if not target or urllib.parse.urlsplit(target).scheme or target.startswith('/'):
            continue
        candidate = (markdown_path.parent / urllib.parse.unquote(target)).resolve()
        if candidate.is_relative_to(repo.resolve()) and candidate.is_file():
            links.append((label, candidate.relative_to(repo.resolve()).as_posix()))
    return links


def parse_notebook(repo):
    """Read explicit fields only; never infer a relationship or outcome."""
    nodes, edges, warnings = [], [], []
    readme = safe_file(repo, 'README.md')
    if readme:
        for line in readme.read_text(encoding='utf-8', errors='replace').splitlines():
            match = re.match(r'^#{2,6}\s+(Q\d+)\s*[—:–-]\s*(.+?)\s*$', line)
            if match:
                key, title = match.groups()
                nodes.append({'id': key, 'type': 'Question', 'title': key + ' — ' + title, 'summary': title, 'status': 'Unknown', 'sources': [{'path': 'README.md', 'label': 'Research question'}]})
    todo_status = {}
    todo = safe_file(repo, 'TODO.md')
    if todo:
        for line in todo.read_text(encoding='utf-8', errors='replace').splitlines():
            match = re.match(r'^\s*-\s*\[([ xX])\]\s*([EQ]\d+)\s*[—:–-]\s*(.+?)\s*$', line)
            if match:
                check, key, title = match.groups()
                status = 'Complete' if check.lower() == 'x' else 'Open'
                if key.startswith('E'):
                    todo_status[key] = status
                else:
                    existing = next((n for n in nodes if n['id'] == key), None)
                    if existing:
                        existing['status'] = status
                        existing['sources'].append({'path': 'TODO.md', 'label': 'Question status in TODO'})
                    else:
                        nodes.append({'id': key, 'type': 'Question', 'title': key + ' — ' + title, 'summary': title, 'status': status, 'sources': [{'path': 'TODO.md', 'label': 'Question in TODO'}]})
    files = sorted(list(repo.glob('experiments/E[0-9]*.md')) + list(repo.glob('E[0-9]*.md')))
    for file in files:
        if not safe_file(repo, file.relative_to(repo).as_posix()):
            continue
        match = re.fullmatch(r'(E\d+)\.md', file.name, re.I)
        if not match:
            continue
        key = match.group(1).upper()
        if any(n['id'] == key for n in nodes):
            warnings.append('Duplicate experiment ID: ' + key + ' (' + str(file.relative_to(repo)) + ')')
            continue
        text = file.read_text(encoding='utf-8', errors='replace')
        heading = re.search(r'^#\s+(.+)$', text, re.M)
        parts = re.split(r'^##\s+', text, flags=re.M)
        fields = {}
        for line in parts[0].splitlines():
            field = re.match(r'^\s*(?:-\s*)?\*\*([^*]+?):\*\*\s*(.*)$', line)
            if field:
                fields[field.group(1).strip().lower()] = field.group(2).strip()
        summary = ' '.join(fields[k] for k in ('what and why', 'result', 'next') if fields.get(k)) or 'Summary not provided.'
        path = file.relative_to(repo).as_posix()
        node = {'id': key, 'type': 'Experiment', 'title': heading.group(1) if heading else key, 'summary': summary, 'status': fields.get('status', todo_status.get(key, 'Unknown')), 'sources': [{'path': path, 'label': 'Experiment summary'}]}
        for label, target in local_links(repo, file, fields.get('evidence', '')):
            if pathlib.Path(target).suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp'} and 'figure' not in node:
                node['figure'] = target
            node['sources'].append({'path': target, 'label': label})
        node['sections'] = []
        for part in parts[1:]:
            lines = part.splitlines()
            if not lines:
                continue
            section_fields = {}
            for line in lines[1:]:
                field = re.match(r'^\s*(?:-\s*)?\*\*([^*]+?):\*\*\s*(.*)$', line)
                if field:
                    section_fields[field.group(1).strip().lower()] = field.group(2).strip()
            section = {'title': lines[0].strip(), 'status': section_fields.get('status', 'Unknown'),
                       'summary': ' '.join(section_fields[k] for k in ('what and why', 'result', 'next') if section_fields.get(k)) or 'Summary not provided.', 'result': section_fields.get('result', ''), 'next': section_fields.get('next', ''), 'sources': []}
            for label, target in local_links(repo, file, section_fields.get('evidence', '')):
                if pathlib.Path(target).suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}:
                    section.setdefault('figures', []).append({'path': target, 'label': label})
                else:
                    section['sources'].append({'path': target, 'label': label})
            node['sections'].append(section)
        if key in todo_status:
            node['sources'].append({'path': 'TODO.md', 'label': 'Experiment in TODO'})
            if fields.get('status') and ((fields['status'].lower() == 'complete') != (todo_status[key] == 'Complete')):
                warnings.append(key + ': TODO checkbox and experiment status may disagree')
        nodes.append(node)
        for field, relation, reverse in [('question','investigates',False), ('depends on','depends on',False), ('follow-up','followed by',False), ('follows up','follows up',False), ('compares with','compares with',False)]:
            value = fields.get(field, '')
            # Accept a leading local ID; qualified cross-repository references remain unresolved.
            for reference in filter(None, (part.strip() for part in value.split(';'))):
                target = re.match(r'^(' + ID + r')\b', reference, re.I)
                if target:
                    target_id = target.group(1).upper()
                    edges.append({'from': key, 'to': target_id, 'relation': relation})
                else:
                    warnings.append(key + ': unresolved ' + field + ' reference: ' + reference)
    known = {n['id'] for n in nodes}
    for edge in edges:
        if edge['to'] not in known:
            warnings.append(edge['from'] + ': ' + edge['relation'] + ' references missing ' + edge['to'])
    return nodes, edges, warnings


def notebook_data(repo):
    sha, url = git(repo, 'rev-parse', 'HEAD'), github_url(repo)
    nodes, edges, warnings = parse_notebook(repo)
    if not nodes and (url == BINDING_URL or repo.name == 'binding_affinity_v2'):
        data = json.loads((ROOT / 'graph.json').read_text())
        data['mode'] = 'Curated E00 example; not synced from experiment files.'
        url = url or BINDING_URL
    else:
        data = {'title': repo.name, 'subtitle': 'Research questions and experiments', 'nodes': nodes, 'edges': edges, 'mode': 'Read from local Markdown.'}
    data['warnings'] = warnings
    data['repository'] = {'path': str(repo), 'commit': sha, 'url': url}
    for node in data['nodes']:
        for source in node.get('sources', []) + [s for section in node.get('sections', []) for s in section.get('sources', [])]:
            source['available'] = bool(safe_file(repo, source['path']))
            source['url'] = (url + '/blob/' + (sha or 'main') + '/' + urllib.parse.quote(source['path'])) if url else None
            source['local_url'] = '/source?path=' + urllib.parse.quote(source['path'])
    return data



def question_candidates(repo):
    """Suggest verbatim question headings only; do not claim scientific findings."""
    candidates = []
    paths = sorted([p for p in repo.glob('*.md') if p.is_file()])[:50]
    for path in paths:
        if not safe_file(repo, path.name):
            continue
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            match = re.match(r'^#{1,4}\s+(.+?\?)\s*$', line)
            if match:
                candidates.append({'question': match.group(1), 'path': path.name})
                if len(candidates) >= 30:
                    return candidates
    return candidates


def normalize_github_url(url):
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]+?)(?:\.git)?/?', url.strip())
    if not match or match.group(2) in ('.', '..'):
        raise ValueError('Enter a GitHub repository URL such as https://github.com/owner/repository')
    return 'https://github.com/' + match.group(1) + '/' + match.group(2)


class Projects:
    def __init__(self, initial, registry=REGISTRY, checkouts=CHECKOUTS):
        self.initial = initial.resolve()
        self.registry = registry
        self.checkouts = checkouts
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)

    def list(self):
        entries = [{'id': 'default', 'name': self.initial.name, 'path': str(self.initial), 'url': github_url(self.initial)}]
        try:
            saved = json.loads(self.registry.read_text())
            if isinstance(saved, list):
                entries.extend(item for item in saved if isinstance(item, dict) and all(isinstance(item.get(k), str) for k in ('id', 'name', 'path', 'url')))
        except (OSError, ValueError):
            pass
        return entries

    def get(self, key):
        return next((pathlib.Path(p['path']) for p in self.list() if p['id'] == key), None)

    def add(self, url):
        url = normalize_github_url(url)
        with self.lock:
            entries = self.list()
            existing = next((p for p in entries if (p.get('url') or '').lower() == url.lower()), None)
            if existing:
                return existing
            owner, name = url.removeprefix('https://github.com/').split('/')
            key = owner.lower() + '--' + name.lower()
            if any(p['id'] == key for p in entries):
                raise ValueError('A project with this ID is already registered.')
            self.checkouts.mkdir(parents=True, exist_ok=True)
            destination = self.checkouts / key
            if destination.exists():
                raise ValueError('A local checkout already exists at this destination; it was not changed.')
            env = os.environ.copy()
            env['GIT_TERMINAL_PROMPT'] = '0'
            try:
                subprocess.run(['git', 'clone', '--', url + '.git', str(destination)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120, env=env)
            except (OSError, subprocess.SubprocessError) as exc:
                raise ValueError('Could not clone the repository. Check that it exists, network access is available, and Git credentials are configured.') from exc
            if not (destination / 'README.md').is_file():
                raise ValueError('The clone has no README.md. It remains on disk but was not added.')
            entry = {'id': key, 'name': owner + '/' + name, 'path': str(destination), 'url': url}
            self.registry.parent.mkdir(parents=True, exist_ok=True)
            self.registry.write_text(json.dumps(entries[1:] + [entry], indent=2) + '\n')
            return entry


def draft_path(projects, project_id):
    key = hashlib.sha256(str(projects.get(project_id).resolve()).encode()).hexdigest()
    return projects.registry.parent / 'drafts' / (key + '.json')


def read_drafts(projects, project_id):
    path = draft_path(projects, project_id)
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {'files': {}}


def write_draft(projects, project_id, path, content):
    repo = projects.get(project_id)
    if repo is None:
        raise ValueError('Project not found.')
    if not isinstance(content, str) or len(content.encode('utf-8')) > 200000:
        raise ValueError('Draft must be UTF-8 text under 200 KB.')
    data = notebook_data(repo)
    allowed = {source['path'] for node in data['nodes'] for source in node.get('sources', []) + [x for section in node.get('sections', []) for x in section.get('sources', [])] if source['path'].lower().endswith('.md')}
    comment_path = 'research-notebook/COMMENTS.md'
    if path != comment_path and path not in allowed:
        raise ValueError('Only linked Markdown evidence can be edited.')
    resolved = (repo / path).resolve()
    if not resolved.is_relative_to(repo.resolve()):
        raise ValueError('Invalid path.')
    file = safe_file(repo, path)
    existing = file.read_text(encoding='utf-8') if file else ''
    drafts = read_drafts(projects, project_id)
    old = drafts['files'].get(path)
    if old and old['base'] != existing:
        raise ValueError('The source changed since the draft began. Review it before continuing.')
    drafts['files'][path] = {'base': existing, 'content': content}
    out = draft_path(projects, project_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(drafts, indent=2, ensure_ascii=False) + '\n')


def review_drafts(projects, project_id):
    repo = projects.get(project_id)
    drafts = read_drafts(projects, project_id)
    files = []
    for path, draft in drafts['files'].items():
        file = safe_file(repo, path)
        current = file.read_text(encoding='utf-8') if file else ''
        diff = ''.join(difflib.unified_diff(draft['base'].splitlines(keepends=True), draft['content'].splitlines(keepends=True), fromfile='a/'+path, tofile='b/'+path))
        files.append({'path': path, 'content': draft['content'], 'diff': diff, 'conflict': current != draft['base']})
    return files



def propose_organization(projects, project_id):
    """Create a conservative, reviewable proposal from explicit Markdown headings."""
    repo = projects.get(project_id)
    if repo is None:
        raise ValueError('Project not found.')
    if read_drafts(projects, project_id)['files']:
        raise ValueError('Review existing drafts before creating an organization proposal.')
    current_nodes, _, _ = parse_notebook(repo)
    if any(node['type'] == 'Question' for node in current_nodes):
        raise ValueError('This repository already has structured questions. Existing organization was not changed.')
    candidates = question_candidates(repo)
    unique = []
    for candidate in candidates:
        if candidate['question'] not in {x['question'] for x in unique}:
            unique.append(candidate)
    if not unique:
        raise ValueError('No explicit question headings found. Add a question heading to the Markdown or ask an agent to prepare a proposal.')
    unique = unique[:20]
    source_readme = (repo / 'README.md').read_text(encoding='utf-8', errors='replace')
    proposed_readme = source_readme.rstrip() + '\n\n## Research notebook questions (proposed)\n\n'
    for i, question in enumerate(unique):
        proposed_readme += '### Q%02d — %s\n\nSource: [%s](%s)\n\n' % (i, question['question'], question['path'], urllib.parse.quote(question['path']))
    generated = {'README.md': proposed_readme}
    todo_file = safe_file(repo, 'TODO.md')
    todo = todo_file.read_text(encoding='utf-8', errors='replace') if todo_file else '# Research TODO\n'
    todo += '\n## Research notebook review\n\nThese questions were copied from source headings for review; their status has not been established.\n\n'
    for i, question in enumerate(unique):
        todo += '- Q%02d — %s ([source](%s))\n' % (i, question['question'], urllib.parse.quote(question['path']))
    generated['TODO.md'] = todo
    # Only link explicitly titled experiment headings nested beneath the source question.
    experiment_no = 0
    occupied = {p.stem.upper() for p in list(repo.glob('experiments/E*.md')) + list(repo.glob('E*.md'))}
    for q_index, question in enumerate(unique):
        source = (repo / question['path']).read_text(encoding='utf-8', errors='replace')
        active = False
        parent_level = 0
        for line in source.splitlines():
            heading = re.match(r'^(#{1,6})\s+(.+?)\s*$', line)
            if not heading:
                continue
            level, title = len(heading.group(1)), heading.group(2)
            if title == question['question']:
                active, parent_level = True, level
                continue
            if active and level <= parent_level:
                active = False
            match = re.match(r'(?i)^experiment(?:\s*[:—–-]\s*|\s+)(.+)$', title)
            if not active or not match:
                continue
            while 'E%02d' % experiment_no in occupied:
                experiment_no += 1
            exp_id = 'E%02d' % experiment_no
            occupied.add(exp_id); experiment_no += 1
            if experiment_no > 99:
                break
            file_path = 'experiments/' + exp_id + '.md'
            if (repo / file_path).exists():
                continue
            source_link = '../' + urllib.parse.quote(question['path'])
            generated[file_path] = ('# %s — %s\n\n- **Status:** unknown\n- **Question:** Q%02d — %s\n- **Evidence:** [Original Markdown](%s)\n\n**What and why:** Not yet summarized; review the source.\n\n**Result:** Not established by this proposal.\n\n**Next:** Review the source and fill in the experiment details.\n' % (exp_id, match.group(1), q_index, question['question'], source_link))
    drafts = {'files': {}}
    for path, content in generated.items():
        file = safe_file(repo, path)
        base = file.read_text(encoding='utf-8', errors='replace') if file else ''
        drafts['files'][path] = {'base': base, 'content': content}
    out = draft_path(projects, project_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(drafts, indent=2, ensure_ascii=False) + '\n')
    return {'questions': len(unique), 'experiments': sum(path.startswith('experiments/') for path in generated), 'files': list(generated)}

def sync_drafts(projects, project_id, review_hash):
    repo = projects.get(project_id)
    if repo is None:
        raise ValueError('Project not found.')
    files = review_drafts(projects, project_id)
    actual_hash = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    if not files or review_hash != actual_hash or any(f['conflict'] for f in files):
        raise ValueError('Drafts changed or conflict with local files. Review them again.')
    remote = github_url(repo)
    head = git(repo, 'rev-parse', 'HEAD')
    branch = git(repo, 'symbolic-ref', '--short', 'HEAD')
    if not remote or not head or not branch:
        raise ValueError('A GitHub origin and a checked-out Git branch are required.')
    for file in files:
        path = file['path']
        try:
            tracked = subprocess.check_output(['git', '-C', str(repo), 'show', 'HEAD:'+path], stderr=subprocess.DEVNULL).decode('utf-8')
        except subprocess.CalledProcessError:
            tracked = ''
        if tracked != read_drafts(projects, project_id)['files'][path]['base']:
            raise ValueError('The local file differs from HEAD: '+path+'. Commit or reconcile it before syncing.')
    env = os.environ.copy(); env['GIT_TERMINAL_PROMPT'] = '0'
    def run(args, cwd=None):
        try:
            return subprocess.check_output(args, cwd=cwd, stderr=subprocess.STDOUT, text=True, timeout=120, env=env).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('Git operation failed. Check network, credentials, Git identity, and repository permissions; drafts were retained.') from exc
    refs = run(['git', 'ls-remote', remote, 'refs/heads/'+branch]).split()
    if not refs or refs[0] != head:
        raise ValueError('The GitHub branch differs from this checkout. Update the checkout and review again.')
    new_branch = 'research-notebook/' + secrets.token_hex(6)
    with tempfile.TemporaryDirectory(prefix='research-notebook-') as tmp:
        run(['git', 'clone', '--no-hardlinks', '--', str(repo), tmp])
        run(['git', 'checkout', '-b', new_branch, head], cwd=tmp)
        for file in files:
            dest = pathlib.Path(tmp) / file['path']
            if not dest.resolve().is_relative_to(pathlib.Path(tmp).resolve()):
                raise ValueError('Draft path escapes the temporary checkout.')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(file['content'], encoding='utf-8')
        run(['git', 'add', '--'] + [f['path'] for f in files], cwd=tmp)
        run(['git', 'commit', '-m', 'Update research notebook notes'], cwd=tmp)
        run(['git', 'push', '--', remote, 'HEAD:refs/heads/'+new_branch], cwd=tmp)
    draft_path(projects, project_id).unlink()
    return {'branch': new_branch, 'url': remote + '/compare/' + urllib.parse.quote(branch, safe='') + '...' + urllib.parse.quote(new_branch, safe='/') + '?expand=1'}

def make_handler(repo, projects=None):
    projects = projects or Projects(repo)
    class Handler(http.server.BaseHTTPRequestHandler):
        def respond(self, status, data, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get('Host', '') in ('127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port))

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, b'Forbidden', 'text/plain')
            url = urllib.parse.urlsplit(self.path)
            if url.path == '/':
                return self.respond(200, (ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            if url.path == '/api/projects':
                entries = [{'id': p['id'], 'name': p['name'], 'url': p.get('url')} for p in projects.list()]
                return self.respond(200, json.dumps({'projects': entries, 'token': projects.token}).encode(), 'application/json; charset=utf-8')
            query = urllib.parse.parse_qs(url.query)
            project_id = query.get('project', ['default'])[0]
            repo = projects.get(project_id)
            if repo is None or not (repo / 'README.md').is_file():
                return self.respond(404, b'Project not found', 'text/plain')
            if url.path == '/api/drafts':
                files = review_drafts(projects, project_id)
                review_hash = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
                return self.respond(200, json.dumps({'files': files, 'review_hash': review_hash}).encode(), 'application/json; charset=utf-8')
            data = notebook_data(repo)
            data['candidates'] = question_candidates(repo) if not data['nodes'] else []
            for node in data['nodes']:
                for source in node.get('sources', []) + [s for section in node.get('sections', []) for s in section.get('sources', [])]:
                    source['local_url'] += '&project=' + urllib.parse.quote(project_id)
            if url.path == '/api/notebook':
                return self.respond(200, json.dumps(data).encode(), 'application/json; charset=utf-8')
            if url.path in ('/figure', '/source'):
                name = urllib.parse.parse_qs(url.query).get('path', [''])[0]
                allowed = ({n.get('figure') for n in data['nodes']} | {f['path'] for n in data['nodes'] for section in n.get('sections', []) for f in section.get('figures', [])}) if url.path == '/figure' else ({s['path'] for n in data['nodes'] for s in n.get('sources', []) + [s for section in n.get('sections', []) for s in section.get('sources', [])]} | {c['path'] for c in data['candidates']} | {'research-notebook/COMMENTS.md'})
                file = safe_file(repo, name) if name in allowed else None
                extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp'} if url.path == '/figure' else {'.md'}
                if file and file.suffix.lower() in extensions:
                    return self.respond(200, file.read_bytes(), (mimetypes.guess_type(file.name)[0] or 'text/plain') + ('; charset=utf-8' if url.path == '/source' else ''))
            self.respond(404, b'Not found', 'text/plain')

        def do_POST(self):
            if not self.valid_host() or self.path not in ('/api/projects', '/api/draft', '/api/sync', '/api/proposal') or self.headers.get('X-Notebook-Token') != projects.token:
                return self.respond(403, b'Forbidden', 'text/plain')
            origin = self.headers.get('Origin', '')
            if origin not in ('http://127.0.0.1:' + str(self.server.server_port), 'http://localhost:' + str(self.server.server_port)):
                return self.respond(403, b'Forbidden', 'text/plain')
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 250000:
                    raise ValueError('Invalid request size.')
                payload = json.loads(self.rfile.read(length))
                if self.path == '/api/projects':
                    entry = projects.add(payload.get('url', ''))
                    result = {'id': entry['id'], 'name': entry['name']}
                elif self.path == '/api/draft':
                    write_draft(projects, payload.get('project', ''), payload.get('path', ''), payload.get('content'))
                    result = {'saved': True}
                elif self.path == '/api/proposal':
                    result = propose_organization(projects, payload.get('project', ''))
                else:
                    result = sync_drafts(projects, payload.get('project', ''), payload.get('review_hash', ''))
                return self.respond(200, json.dumps(result).encode(), 'application/json; charset=utf-8')
            except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
                return self.respond(400, json.dumps({'error': str(exc)}).encode(), 'application/json; charset=utf-8')
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=pathlib.Path, required=True, help='Path to a local research repository')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    repo = args.repo.expanduser().resolve()
    if not (repo / 'README.md').is_file():
        parser.error(f'No README.md found in {repo}; supply the path to a local clone')
    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(repo))
    url = f'http://127.0.0.1:{server.server_port}/'
    print(f'Research notebook: {url}\nReading: {repo}\nPress Ctrl-C to stop.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
