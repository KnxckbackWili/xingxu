"""Real local Git/signature tests for host-owned update authorization.

All repositories and signing keys are temporary test fixtures. The local test
adapter changes only fetch transport; Git object checks and verify-tag execute
unchanged. No application data, real trust configuration or deployment is used.
"""
import importlib.util
import base64
import json
import os
import shutil
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4


SPEC = importlib.util.spec_from_file_location('update_trust', Path(__file__).with_name('update-trust.py'))
trust = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trust)
REPOSITORY = 'https://git.example.invalid/team/workflow'
OTHER_REPOSITORY = 'https://other.example.invalid/team/workflow'


class LocalVerifier(trust.Verifier):
    """Use local fixture repositories ONLY for the real Git fetch invocation."""
    def __init__(self, policy, work, repositories):
        super().__init__(policy, work)
        self.repositories = repositories
        self.fetches = []
        self.git_calls = []
        self.signing_homes = []

    def _git(self, repo, args, env, *, limit=2 * 1024 * 1024):
        options = list(args)
        self.git_calls.append((list(options), env.get('GIT_CONFIG_KEY_0'), env.get('GIT_CONFIG_VALUE_0')))
        keyring = Path(env['GNUPGHOME'])
        if 'verify-tag' in options and keyring.is_dir():
            self.signing_homes.append((keyring.resolve(), stat.S_IMODE(keyring.stat().st_mode), stat.S_IMODE((keyring / 'gpg.conf').stat().st_mode)))
        if options and options[0] == 'fetch':
            matches = [index for index, value in enumerate(options) if value in self.repositories]
            if len(matches) != 1:
                raise AssertionError('A fetch must use one explicitly mapped fixture origin')
            origin = options[matches[0]]
            self.fetches.append(origin)
            options[matches[0]] = str(self.repositories[origin])
            env = {**env, 'GIT_ALLOW_PROTOCOL': 'file'}
        return super()._git(repo, options, env, limit=limit)


class UpdateTrustTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='agv-update-trust-test-', dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.work = self.root / 'runner-state'
        self.work.mkdir(mode=0o700)
        self.policy = self.root / 'host-trust.json'
        self.repo = self.root / 'source'
        self.repo.mkdir(mode=0o700)
        self.environment = {key: value for key, value in os.environ.items()
                            if not key.startswith('GIT_') and key not in {'GNUPGHOME', 'SSH_AUTH_SOCK', 'GPG_AGENT_INFO'}}
        self.environment.update(HOME=str(self.root), GIT_CONFIG_NOSYSTEM='1',
                                GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                                GIT_TERMINAL_PROMPT='0', GIT_ALLOW_PROTOCOL='file', LC_ALL='C')
        self.key = self.make_key('release-key')
        self.other_key = self.make_key('untrusted-key')
        self.signers = self.root / 'host-allowed-signers'
        self.write_signers(self.signers, self.key)
        self.git(self.repo, 'init', '--quiet', '--initial-branch=main')
        self.git(self.repo, 'config', 'user.name', 'Update Trust Test')
        self.git(self.repo, 'config', 'user.email', 'release-test@example.invalid')
        self.git(self.repo, 'config', 'gpg.format', 'ssh')
        self.git(self.repo, 'config', 'user.signingKey', str(self.key))
        (self.repo / 'frontend').mkdir()
        (self.repo / 'frontend/package.json').write_text(json.dumps({'name': 'agv-pm-frontend', 'version': '9.1.0'}))
        (self.repo / 'docker').mkdir()
        (self.repo / 'docker/update-protocol.json').write_text('{"application":"xingxu-workbench","protocol":1}')
        (self.repo / 'docker/Dockerfile').write_text('FROM scratch\n')
        self.git(self.repo, 'add', '.')
        self.git(self.repo, 'commit', '--quiet', '-m', 'test-only release source')
        self.commit = self.git(self.repo, 'rev-parse', 'HEAD').strip()
        self.candidate = {'check_id': str(uuid4()), 'source_id': 'default-gitea', 'source_revision': 7,
                          'repository_url': REPOSITORY, 'ref': 'v9.1.0', 'commit': self.commit, 'version': '9.1.0'}
        self.repositories = {REPOSITORY: self.repo}

    def command(self, *arguments):
        result = subprocess.run(arguments, env=self.environment, capture_output=True, text=True, timeout=30)
        if result.returncode:
            self.fail('Fixture command failed: ' + arguments[0] + '\n' + result.stderr[-1500:])
        return result.stdout

    def git(self, directory, *arguments):
        return self.command('git', '-C', str(directory), *arguments)

    def make_key(self, name):
        key = self.root / name
        self.command('ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'test-only-release-key', '-f', str(key))
        key.chmod(0o600)
        return key

    @staticmethod
    def write_signers(destination, key):
        destination.write_text('release-test@example.invalid ' + key.with_suffix('.pub').read_text().strip() + '\n')
        destination.chmod(0o600)

    def write_policy(self, entries=None):
        if entries is None:
            entries = [{'repository_url': REPOSITORY, 'ssh_allowed_signers': str(self.signers)}]
        self.policy.write_text(json.dumps({'version': 1, 'repositories': entries}, indent=2) + '\n')
        self.policy.chmod(0o600)
        return LocalVerifier(self.policy, self.work, self.repositories)

    def signed_tag(self, name='v9.1.0', *, key=None, force=False):
        options = ['-c', 'user.signingKey=' + str(key or self.key), 'tag', '-s']
        if force:
            options.append('--force')
        self.git(self.repo, *options, name, '-m', 'test-only signed release')

    def rejected(self, verifier, candidate=None):
        with self.assertRaises(trust.TrustError) as caught:
            with verifier.verified(candidate or self.candidate):
                self.fail('An unauthorized source reached the verified context')
        # Public reasons must not expose host paths, private signing material,
        # process arguments or the source's supplied authentication token.
        self.assertNotIn(str(self.root), str(caught.exception))
        self.assertIn(caught.exception.reason, trust.PUBLIC_REASONS)
        return caught.exception.reason

    def test_signed_annotated_tag_verifies_and_exports_only_verified_git_objects(self):
        self.signed_tag()
        verifier = self.write_policy()
        (self.repo / 'untracked-attacker-file').write_text('must not enter build source')
        destination = self.root / 'verified-source.tar.gz'
        with verifier.verified(self.candidate) as (repository, environment, metadata):
            self.assertEqual(metadata['method'], 'signed_tag')
            self.assertRegex(metadata['policy_digest'], r'^[a-f0-9]{64}$')
            self.assertEqual(metadata['tree'], self.git(self.repo, 'rev-parse', self.commit + '^{tree}').strip())
            self.assertEqual(environment['GIT_ALLOW_PROTOCOL'], 'https:http')
            verifier.export(repository, environment, self.commit, destination)
            with tarfile.open(destination, 'r:gz') as archive:
                self.assertEqual(json.load(archive.extractfile('repository/frontend/package.json'))['version'], '9.1.0')
                self.assertIn('repository/docker/Dockerfile', archive.getnames())
                self.assertNotIn('repository/untracked-attacker-file', archive.getnames())
        self.assertFalse(repository.exists())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(verifier.fetches, [REPOSITORY])

    def test_unsigned_annotated_tag_is_rejected(self):
        self.git(self.repo, '-c', 'tag.gpgSign=false', 'tag', '-a', 'v9.1.0', '-m', 'unsigned test release')
        self.rejected(self.write_policy())

    def test_lightweight_tag_is_rejected(self):
        self.git(self.repo, '-c', 'tag.gpgSign=false', 'tag', 'v9.1.0')
        self.rejected(self.write_policy())

    def test_signature_from_a_different_public_key_is_rejected(self):
        self.signed_tag(key=self.other_key)
        self.rejected(self.write_policy())

    def test_incorrect_host_public_key_rejects_a_genuinely_signed_tag(self):
        self.signed_tag()
        self.write_signers(self.signers, self.other_key)
        self.rejected(self.write_policy())

    def test_tag_moved_to_another_commit_is_rejected_even_when_its_new_signature_is_valid(self):
        self.signed_tag()
        verifier = self.write_policy()
        with verifier.verified(self.candidate):
            pass
        (self.repo / 'changed').write_text('new commit must require a new check')
        self.git(self.repo, 'add', 'changed')
        self.git(self.repo, 'commit', '--quiet', '-m', 'test-only changed release')
        self.signed_tag(force=True)
        self.rejected(verifier)

    def test_an_explicit_full_commit_can_be_authorized_without_a_signed_tag(self):
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        with verifier.verified({**self.candidate, 'ref': 'main'}) as (_, _, metadata):
            self.assertEqual(metadata['method'], 'commit')

    def test_identical_commit_in_an_unapproved_repository_is_not_globally_authorized(self):
        other = self.root / 'other-source'
        self.command('git', 'clone', '--quiet', '--no-hardlinks', str(self.repo), str(other))
        self.assertEqual(self.git(other, 'rev-parse', 'HEAD').strip(), self.commit)
        self.repositories[OTHER_REPOSITORY] = other
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        self.rejected(verifier, {**self.candidate, 'repository_url': OTHER_REPOSITORY})
        self.assertEqual(verifier.fetches, [])

    def test_repository_entries_do_not_share_their_allowed_commit_sets(self):
        verifier = self.write_policy([
            {'repository_url': REPOSITORY, 'allowed_commits': [self.commit]},
            {'repository_url': OTHER_REPOSITORY, 'allowed_commits': ['0' * 40]},
        ])
        self.repositories[OTHER_REPOSITORY] = self.repo
        self.rejected(verifier, {**self.candidate, 'repository_url': OTHER_REPOSITORY, 'ref': 'main'})

    def test_equivalent_repository_spellings_have_one_canonical_binding(self):
        verifier = self.write_policy([{'repository_url': 'https://GIT.EXAMPLE.invalid:443/team/workflow.git/', 'allowed_commits': [self.commit]}])
        with verifier.verified(self.candidate) as (_, _, metadata):
            self.assertEqual(metadata['method'], 'commit')

    def test_short_or_noncanonical_commit_ids_are_rejected_in_candidates_and_policy(self):
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        for invalid in (self.commit[:12], self.commit.upper(), '', '--help', None):
            with self.subTest(candidate_commit=invalid):
                self.rejected(verifier, {**self.candidate, 'commit': invalid})
        for invalid in (self.commit[:12], self.commit.upper(), '--help'):
            with self.subTest(policy_commit=invalid):
                verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [invalid]}])
                self.assertFalse(verifier.configured())

    def test_unapproved_branch_or_missing_tag_does_not_fall_back_to_its_commit(self):
        self.signed_tag()
        verifier = self.write_policy()
        for name in ('main', 'missing-release'):
            with self.subTest(ref=name):
                self.rejected(verifier, {**self.candidate, 'ref': name})

    def test_boolean_update_protocol_cannot_masquerade_as_integer_one(self):
        (self.repo / 'docker/update-protocol.json').write_text('{"application":"xingxu-workbench","protocol":true}')
        self.git(self.repo, 'add', '.')
        self.git(self.repo, 'commit', '--quiet', '-m', 'test-only invalid protocol type')
        self.candidate['commit'] = self.git(self.repo, 'rev-parse', 'HEAD').strip()
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.candidate['commit']]}])
        self.assertEqual(self.rejected(verifier), 'target_changed')

    def test_candidate_version_and_application_marker_must_match_git_contents(self):
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        self.rejected(verifier, {**self.candidate, 'version': '9.2.0'})
        (self.repo / 'docker/update-protocol.json').write_text('{"application":"another-product","protocol":1}')
        self.git(self.repo, 'add', '.')
        self.git(self.repo, 'commit', '--quiet', '-m', 'test-only wrong product marker')
        changed = self.git(self.repo, 'rev-parse', 'HEAD').strip()
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [changed]}])
        self.rejected(verifier, {**self.candidate, 'commit': changed})

    def test_group_or_world_writable_policy_and_parent_are_rejected(self):
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        for mode in (0o660, 0o666):
            with self.subTest(mode=oct(mode)):
                self.policy.chmod(mode)
                self.assertFalse(verifier.configured())
        self.policy.chmod(0o600)
        self.root.chmod(0o770)
        try:
            self.assertFalse(verifier.configured())
        finally:
            self.root.chmod(0o700)
        self.assertTrue(verifier.configured())

    def test_symlink_policy_or_signer_file_is_not_a_trust_root(self):
        verifier = self.write_policy()
        link = self.root / 'policy-link.json'; link.symlink_to(self.policy)
        self.assertFalse(LocalVerifier(link, self.work, self.repositories).configured())
        key_link = self.root / 'signers-link'; key_link.symlink_to(self.signers)
        self.assertFalse(self.write_policy([{'repository_url': REPOSITORY, 'ssh_allowed_signers': str(key_link)}]).configured())

    def test_writable_signers_file_is_rejected_before_fetch(self):
        verifier = self.write_policy()
        self.signers.chmod(0o666)
        self.rejected(verifier)
        self.assertEqual(verifier.fetches, [])

    def test_policy_or_keys_supplied_in_a_downloaded_job_directory_are_rejected(self):
        packaged = self.work / str(uuid4()) / 'source'
        packaged.mkdir(mode=0o700, parents=True)
        packaged_policy = packaged / 'update-trust.json'
        packaged_policy.write_text(json.dumps({'version': 1, 'repositories': [{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}]}))
        packaged_policy.chmod(0o600)
        self.assertFalse(LocalVerifier(packaged_policy, self.work, self.repositories).configured())
        packaged_signers = packaged / 'allowed-signers'
        self.write_signers(packaged_signers, self.key)
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'ssh_allowed_signers': str(packaged_signers)}])
        self.assertFalse(verifier.configured())

    def test_relative_work_directory_cannot_bypass_downloaded_package_boundary(self):
        packaged = self.work / str(uuid4()) / 'source'
        packaged.mkdir(mode=0o700, parents=True)
        packaged_policy = packaged / 'update-trust.json'
        packaged_policy.write_text(json.dumps({'version': 1, 'repositories': [{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}]}))
        packaged_policy.chmod(0o600)
        previous = Path.cwd()
        os.chdir(self.root)
        try:
            verifier = LocalVerifier(packaged_policy, Path('runner-state'), self.repositories)
            self.assertFalse(verifier.configured())
        finally:
            os.chdir(previous)

    def test_explicit_source_boundary_rejects_a_root_outside_the_normal_job_layout(self):
        verifier = self.write_policy()
        verifier.forbidden = [self.root]
        self.assertFalse(verifier.configured())

    def test_policy_and_key_revocation_invalidate_the_verified_digest(self):
        self.signed_tag()
        verifier = self.write_policy()
        with verifier.verified(self.candidate) as (_, _, metadata):
            self.write_signers(self.signers, self.other_key)
            with self.assertRaises(trust.TrustError):
                verifier.assert_policy(metadata['policy_digest'])
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        with verifier.verified(self.candidate) as (_, _, metadata):
            self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': ['0' * 40]}])
            with self.assertRaises(trust.TrustError):
                verifier.assert_policy(metadata['policy_digest'])
        self.rejected(verifier, {**self.candidate, 'ref': 'main'})

    def test_production_environment_ignores_git_and_signing_overrides(self):
        injected = {'GIT_ALLOW_PROTOCOL': 'file', 'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'gpg.ssh.program',
                    'GIT_CONFIG_VALUE_0': '/untrusted/program', 'GIT_SSH_COMMAND': '/untrusted/ssh',
                    'SSH_AUTH_SOCK': '/untrusted/agent', 'GNUPGHOME': '/untrusted/keyring'}
        with patch.dict(os.environ, injected):
            environment = trust.Verifier._environment(self.root, '')
        self.assertEqual(environment['GIT_ALLOW_PROTOCOL'], 'https:http')
        self.assertEqual(environment['GIT_CONFIG_GLOBAL'], os.devnull)
        self.assertNotIn('GIT_CONFIG_COUNT', environment)
        self.assertNotIn('GIT_SSH_COMMAND', environment)
        self.assertNotIn('SSH_AUTH_SOCK', environment)
        self.assertEqual(environment['GNUPGHOME'], str(self.root / 'gnupg'))

    def test_source_fingerprint_frames_file_lengths_and_tracks_content_and_execute_bits(self):
        source = self.root / 'build-context'; source.mkdir()
        first, second = source / 'a', source / 'b'
        first.write_bytes(b'prefix'); second.write_bytes(b'payload')
        first.chmod(0o600); second.chmod(0o600)
        original = trust.source_fingerprint(source)
        # Without a file length/end boundary, this second tree encodes the
        # next file's record inside a's body and collides with the first tree.
        second.unlink()
        first.write_bytes(b'prefix' + (1).to_bytes(4, 'big') + b'bfile\x00payload')
        self.assertNotEqual(trust.source_fingerprint(source), original)
        first.write_bytes(b'prefix'); second.write_bytes(b'payload'); second.chmod(0o600)
        self.assertEqual(trust.source_fingerprint(source), original)
        first.chmod(0o700)
        self.assertNotEqual(trust.source_fingerprint(source), original)
        first.chmod(0o600); second.write_bytes(b'changed')
        self.assertNotEqual(trust.source_fingerprint(source), original)

    def test_source_fingerprint_rejects_links_and_special_files(self):
        source = self.root / 'unsafe-context'; source.mkdir()
        outside = self.root / 'outside'; outside.write_text('retained')
        link = source / 'link'; link.symlink_to(outside)
        with self.assertRaises(trust.TrustError):
            trust.source_fingerprint(source)
        link.unlink()
        os.mkfifo(source / 'pipe')
        with self.assertRaises(trust.TrustError):
            trust.source_fingerprint(source)
        self.assertEqual(outside.read_text(), 'retained')

    def test_archive_export_never_overwrites_existing_file_or_follows_a_symlink(self):
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        existing = self.root / 'retained-source.tar.gz'; existing.write_bytes(b'retained')
        link = self.root / 'source-link.tar.gz'; link.symlink_to(existing)
        with verifier.verified(self.candidate) as (repository, environment, _):
            for destination in (existing, link):
                with self.subTest(destination=destination.name), self.assertRaises(trust.TrustError):
                    verifier.export(repository, environment, self.commit, destination)
        self.assertEqual(existing.read_bytes(), b'retained')
        self.assertTrue(link.is_symlink())

    def test_candidate_cannot_supply_its_own_trust_or_git_option(self):
        verifier = self.write_policy()
        self.rejected(verifier, {**self.candidate, 'ref': 'main', 'allowed_commits': [self.commit],
                                  'ssh_allowed_signers': str(self.signers), 'trust': {'status': 'trusted'}})
        for ref in ('--upload-pack=untrusted', '../v9.1.0', 'v9.1.0^{commit}', 'v9.1.0:docker/Dockerfile'):
            with self.subTest(ref=ref):
                self.rejected(verifier, {**self.candidate, 'ref': ref})

    def openpgp_key(self, name):
        home = self.root / name; home.mkdir(mode=0o700)
        gpg = shutil.which('gpg')
        gpgconf = shutil.which('gpgconf')
        self.addCleanup(lambda: subprocess.run([gpgconf, '--homedir', str(home), '--kill', 'gpg-agent'],
                                               capture_output=True, timeout=10))
        environment = {**self.environment, 'GNUPGHOME': str(home)}
        uid = name + ' <release-test@example.invalid>'
        command = [gpg, '--no-options', '--batch', '--homedir', str(home)]
        generated = subprocess.run([*command, '--pinentry-mode', 'loopback', '--passphrase', '',
                                    '--quick-generate-key', uid, 'ed25519', 'sign', '0'],
                                   env=environment, capture_output=True, timeout=30)
        self.assertEqual(generated.returncode, 0, 'Isolated OpenPGP test key generation failed: ' + generated.stderr.decode(errors='replace')[-1200:])
        listing = subprocess.run([*command, '--with-colons', '--list-keys', uid], env=environment,
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(listing.returncode, 0)
        fingerprint = next(line.split(':')[9] for line in listing.stdout.splitlines() if line.startswith('fpr:'))
        exported = subprocess.run([*command, '--armor', '--export', fingerprint], env=environment,
                                  capture_output=True, timeout=10)
        self.assertEqual(exported.returncode, 0)
        public = self.root / (name + '.public.asc'); public.write_bytes(exported.stdout); public.chmod(0o600)
        return home, fingerprint, public

    def openpgp_tag(self, home, fingerprint):
        environment = {**self.environment, 'GNUPGHOME': str(home)}
        command = ['git', '-C', str(self.repo), '-c', 'gpg.format=openpgp',
                   '-c', 'gpg.program=' + shutil.which('gpg'), '-c', 'user.signingKey=' + fingerprint,
                   'tag', '-s', 'v9.1.0', '-m', 'test-only OpenPGP release']
        result = subprocess.run(command, env=environment, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, 'Isolated OpenPGP tag signing failed')

    @unittest.skipUnless(shutil.which('gpg') and shutil.which('gpgconf'), 'OpenPGP tools unavailable; no tool download attempted')
    def test_openpgp_tag_is_verified_using_only_the_configured_public_key(self):
        home, fingerprint, public = self.openpgp_key('gpg-release-test')
        self.openpgp_tag(home, fingerprint)
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'openpgp_public_keys': [str(public)]}])
        with verifier.verified(self.candidate) as (_, environment, metadata):
            self.assertEqual(metadata['method'], 'signed_tag')
            self.assertNotEqual(environment['GNUPGHOME'], str(home))
            keyring = Path(environment['GNUPGHOME']).resolve()
            self.assertNotEqual(keyring, Path.home() / '.gnupg')
            self.assertEqual(verifier.signing_homes, [(keyring, 0o700, 0o600)])
        self.assertFalse(keyring.exists())

    @unittest.skipUnless(shutil.which('gpg') and shutil.which('gpgconf'), 'OpenPGP tools unavailable; no tool download attempted')
    def test_openpgp_tag_signed_by_a_different_key_is_rejected(self):
        home, fingerprint, _ = self.openpgp_key('gpg-signer-test')
        _, _, wrong_public = self.openpgp_key('gpg-wrong-public-test')
        self.openpgp_tag(home, fingerprint)
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'openpgp_public_keys': [str(wrong_public)]}])
        self.rejected(verifier)

    @staticmethod
    def load_runner():
        spec = importlib.util.spec_from_file_location('update_runner_export_test', Path(__file__).with_name('update-runner.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def export_substitution_fixture(self, message, *, marker_ignored=False):
        package = {'name': 'agv-pm-frontend', 'version': '9.1.0', 'note': '$Format:%s$'}
        (self.repo / 'frontend/package.json').write_text(json.dumps(package))
        attributes = 'frontend/package.json export-subst\n'
        if marker_ignored:
            attributes += 'docker/update-protocol.json export-ignore\n'
        (self.repo / '.gitattributes').write_text(attributes)
        self.git(self.repo, 'add', '.')
        self.git(self.repo, 'commit', '--quiet', '-m', message)
        commit = self.git(self.repo, 'rev-parse', 'HEAD').strip()
        candidate = {**self.candidate, 'commit': commit}
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [commit]}])
        destination = self.root / 'export-substitution.tar.gz'
        with verifier.verified(candidate) as (repository, environment, _):
            verifier.export(repository, environment, commit, destination)
        return destination

    def test_legitimate_git_export_substitution_retains_the_version_and_protocol_binding(self):
        destination = self.export_substitution_fixture('legitimate test release note')
        with tarfile.open(destination, 'r:gz') as archive:
            package = json.load(archive.extractfile('repository/frontend/package.json'))
            self.assertEqual(package['note'], 'legitimate test release note')
            self.assertEqual(package['version'], self.candidate['version'])
        runner = self.load_runner()
        source = runner.extract_source(destination, self.root / 'benign-source', self.candidate['version'])
        self.assertEqual(json.loads((source / 'frontend/package.json').read_text())['version'], '9.1.0')

    def test_git_export_substitution_cannot_change_the_version_used_for_installation(self):
        # The Git blob is valid 9.1.0 JSON, but export-subst inserts the commit
        # subject unescaped and adds a different final JSON version field.
        destination = self.export_substitution_fixture('release", "version":"666.0.0", "comment":"injected')
        with tarfile.open(destination, 'r:gz') as archive:
            package = json.load(archive.extractfile('repository/frontend/package.json'))
            self.assertEqual(package['version'], '666.0.0')
        runner = self.load_runner()
        with self.assertRaises(runner.UpdateError):
            runner.extract_source(destination, self.root / 'malicious-source', self.candidate['version'])

    def test_git_export_ignore_cannot_remove_the_required_update_protocol(self):
        destination = self.export_substitution_fixture('test release note', marker_ignored=True)
        with tarfile.open(destination, 'r:gz') as archive:
            self.assertNotIn('repository/docker/update-protocol.json', archive.getnames())
        runner = self.load_runner()
        with self.assertRaises(runner.UpdateError):
            runner.extract_source(destination, self.root / 'missing-protocol-source', self.candidate['version'])

    @unittest.skipUnless(shutil.which('gpg') and shutil.which('gpgconf'), 'OpenPGP tools unavailable; no tool download attempted')
    def test_openpgp_public_verification_in_a_long_private_work_directory(self):
        home, fingerprint, public = self.openpgp_key('gpg-long-work-test')
        self.openpgp_tag(home, fingerprint)
        self.write_policy([{'repository_url': REPOSITORY, 'openpgp_public_keys': [str(public)]}])
        long_work = self.root / ('state-' + 'long-path-' * 16)
        verifier = LocalVerifier(self.policy, long_work, self.repositories)
        original_run = subprocess.run
        public_import_errors = []
        def observe_run(command, *args, **kwargs):
            result = original_run(command, *args, **kwargs)
            if Path(command[0]).name == 'gpg' and '--import' in command:
                public_import_errors.append(result.stderr.decode(errors='replace'))
            return result
        try:
            with patch.object(trust.subprocess, 'run', observe_run):
                with verifier.verified(self.candidate) as (_, environment, metadata):
                    self.assertEqual(metadata['method'], 'signed_tag')
                    self.assertGreater(len(str(verifier.work)), 180)
                    self.assertNotEqual(environment['GNUPGHOME'], str(home))
        except trust.TrustError as error:
            self.fail(str(error) + '\n' + '\n'.join(public_import_errors)[-1200:])

    @unittest.skipUnless(shutil.which('gpg') and shutil.which('gpgconf'), 'OpenPGP tools unavailable; no tool download attempted')
    def test_openpgp_verifier_program_works_when_the_work_path_contains_spaces(self):
        home, fingerprint, public = self.openpgp_key('gpg-spaced-work-test')
        self.openpgp_tag(home, fingerprint)
        self.write_policy([{'repository_url': REPOSITORY, 'openpgp_public_keys': [str(public)]}])
        verifier = LocalVerifier(self.policy, self.root / 'runner work with spaces', self.repositories)
        with verifier.verified(self.candidate) as (_, environment, metadata):
            self.assertEqual(metadata['method'], 'signed_tag')
            self.assertIn(' ', str(verifier.work))
        self.assertTrue(any(argument.startswith('gpg.program=') and str(verifier.work) in argument
                            for argv, _, _ in verifier.git_calls for argument in argv))

    def trust_cli(self, path, *arguments):
        return subprocess.run([sys.executable, str(Path(__file__).with_name('update-trust.py')), '--trust-file', str(path), *arguments],
                              env=self.environment, capture_output=True, text=True, timeout=30)

    def test_host_cli_registers_a_commit_for_one_canonical_repository_idempotently(self):
        policy = self.root / 'host-enrollment' / 'trust.json'
        result = self.trust_cli(policy, 'allow-commit', '--repository', REPOSITORY, '--commit', self.commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        original = policy.read_bytes()
        expected = {'version': 1, 'repositories': [{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}]}
        self.assertEqual(json.loads(original), expected)
        self.assertEqual(stat.S_IMODE(policy.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(policy.parent.stat().st_mode), 0o700)
        repeated = self.trust_cli(policy, 'allow-commit', '--repository', 'https://GIT.EXAMPLE.invalid:443/team/workflow.git/', '--commit', self.commit)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(policy.read_bytes(), original)
        verifier = LocalVerifier(policy, self.work, self.repositories)
        self.rejected(verifier, {**self.candidate, 'repository_url': OTHER_REPOSITORY})
        self.assertEqual(self.trust_cli(policy, 'verify-policy').returncode, 0)

    def test_host_cli_preserves_existing_repositories_and_signing_keys_and_rejects_bad_inputs(self):
        self.write_policy([{'repository_url': REPOSITORY, 'ssh_allowed_signers': str(self.signers)},
                           {'repository_url': OTHER_REPOSITORY, 'allowed_commits': ['0' * 40]}])
        result = self.trust_cli(self.policy, 'allow-commit', '--repository', REPOSITORY, '--commit', self.commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = json.loads(self.policy.read_bytes())
        entries = {entry['repository_url']: entry for entry in policy['repositories']}
        self.assertEqual(entries[REPOSITORY]['ssh_allowed_signers'], str(self.signers))
        self.assertEqual(entries[REPOSITORY]['allowed_commits'], [self.commit])
        self.assertEqual(entries[OTHER_REPOSITORY]['allowed_commits'], ['0' * 40])
        before = self.policy.read_bytes()
        for repository, commit in [(REPOSITORY, self.commit[:12]), (REPOSITORY, 'A' * 40),
                                   ('file:///untrusted/repository', self.commit),
                                   ('https://test-only-secret@git.example.invalid/team/workflow', self.commit)]:
            with self.subTest(repository=repository, commit=commit):
                rejected = self.trust_cli(self.policy, 'allow-commit', '--repository', repository, '--commit', commit)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual(self.policy.read_bytes(), before)
                self.assertNotIn('test-only-secret', rejected.stdout + rejected.stderr)
        self.assertFalse(list(self.policy.parent.glob('.trust-policy-*')))

    def test_host_cli_refuses_to_replace_malformed_writable_or_symlinked_existing_policy(self):
        self.policy.write_bytes(b'{"version":1,broken')
        self.policy.chmod(0o600)
        before = self.policy.read_bytes()
        arguments = ('allow-commit', '--repository', REPOSITORY, '--commit', self.commit)
        self.assertNotEqual(self.trust_cli(self.policy, *arguments).returncode, 0)
        self.assertEqual(self.policy.read_bytes(), before)
        self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        before = self.policy.read_bytes()
        self.policy.chmod(0o666)
        self.assertNotEqual(self.trust_cli(self.policy, *arguments).returncode, 0)
        self.assertEqual(self.policy.read_bytes(), before)
        self.policy.chmod(0o600)
        link = self.root / 'enrollment-link.json'; link.symlink_to(self.policy)
        self.assertNotEqual(self.trust_cli(link, *arguments).returncode, 0)
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.policy.read_bytes(), before)

    def test_concurrent_host_cli_registrations_do_not_lose_other_repository_entries(self):
        self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        commands = [(REPOSITORY, '0' * 40), (OTHER_REPOSITORY, '1' * 40)]
        processes = [subprocess.Popen([sys.executable, str(Path(__file__).with_name('update-trust.py')),
                                      '--trust-file', str(self.policy), 'allow-commit', '--repository', repository, '--commit', commit],
                                     env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for repository, commit in commands]
        for process in processes:
            _, error = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, error)
        entries = {entry['repository_url']: set(entry['allowed_commits']) for entry in json.loads(self.policy.read_bytes())['repositories']}
        self.assertEqual(entries[REPOSITORY], {self.commit, '0' * 40})
        self.assertEqual(entries[OTHER_REPOSITORY], {'1' * 40})

    def test_private_git_auth_uses_only_repository_scoped_basic_environment_not_argv_or_config(self):
        token = 'test-only-Gitea-PAT'
        verifier = self.write_policy([{'repository_url': REPOSITORY, 'allowed_commits': [self.commit]}])
        encoded = base64.b64encode(('git:' + token).encode()).decode()
        with verifier.verified(self.candidate, token) as (repository, environment, _):
            self.assertEqual(environment['GIT_CONFIG_COUNT'], '1')
            self.assertEqual(environment['GIT_CONFIG_KEY_0'], 'http.' + REPOSITORY + '.extraHeader')
            self.assertEqual(environment['GIT_CONFIG_VALUE_0'], 'Authorization: Basic ' + encoded)
            self.assertNotIn(token, (repository / 'config').read_text())
            self.assertNotIn(encoded, (repository / 'config').read_text())
        for argv, scope, authorization in verifier.git_calls:
            self.assertNotIn(token, '\x00'.join(argv))
            self.assertNotIn(encoded, '\x00'.join(argv))
            self.assertEqual(scope, 'http.' + REPOSITORY + '.extraHeader')
            self.assertEqual(authorization, 'Authorization: Basic ' + encoded)


if __name__ == '__main__':
    unittest.main()
