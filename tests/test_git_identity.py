"""Exercise both dependency commit paths with conflicting runner identities."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GitIdentityTests(unittest.TestCase):
    def test_dependency_updates_use_the_bot_for_author_and_committer(self):
        for specialized in (False, True):
            for configured in (False, True):
                with self.subTest(specialized=specialized, configured=configured):
                    self.check_identity(specialized, configured)

    def check_identity(self, specialized, configured):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            environment = dict(os.environ)
            for key in ('WODBOT_GIT_NAME', 'WODBOT_GIT_EMAIL'):
                environment.pop(key, None)
            environment.update({
                'GIT_CONFIG_GLOBAL': str(path / 'global.gitconfig'),
                'GIT_CONFIG_NOSYSTEM': '1',
                'GIT_AUTHOR_NAME': 'Inherited author',
                'GIT_AUTHOR_EMAIL': 'author@example.invalid',
                'GIT_COMMITTER_NAME': 'Inherited committer',
                'GIT_COMMITTER_EMAIL': 'committer@example.invalid',
                'UPDATER_ROOT': str(ROOT),
                'BOILERPLATE_UPDATE_PUSH': '0',
            })
            if configured:
                environment.update(WODBOT_GIT_NAME='Configured Bot',
                                   WODBOT_GIT_EMAIL='configured@example.invalid')

            def git(*args):
                return subprocess.check_output(
                    ['git', *args], cwd=path, env=environment, text=True).strip()

            git('init', '-q')
            git('config', '--global', 'user.name', 'Runner')
            git('config', '--global', 'user.email', 'runner@example.invalid')
            git('config', '--local', 'user.name', 'Previous checkout')
            git('config', '--local', 'user.email', 'checkout@example.invalid')
            git('config', 'commit.gpgsign', 'false')
            (path / 'fixture').write_text('updated\n')
            if specialized:
                script = '''
                    source "$UPDATER_ROOT/scripts/update-specialized.sh"
                    _commit_and_publish "$PWD" wodby/fixture 'Update fixture'
                '''
            else:
                script = '''
                    source "$UPDATER_ROOT/scripts/update-dependencies.sh"
                    _git_commit "$PWD" 'Update fixture'
                '''
            result = subprocess.run(['bash', '-euc', script], cwd=path, env=environment,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            name = environment.get('WODBOT_GIT_NAME', 'Wodby Robot')
            email = environment.get('WODBOT_GIT_EMAIL', 'robot@wodby.com')
            self.assertEqual(git('log', '-1', '--format=%an <%ae>|%cn <%ce>'),
                             f'{name} <{email}>|{name} <{email}>')
            self.assertEqual(git('config', '--global', 'user.name'), 'Runner')
            self.assertEqual(git('config', '--global', 'user.email'), 'runner@example.invalid')
