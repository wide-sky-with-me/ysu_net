import shutil
import subprocess
from pathlib import Path

from helpers import OfflineTestCase


ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        subprocess.run(['git', '-c', 'init.templateDir=', 'init', '-q', str(self.tmp)], check=True)
        shutil.copyfile(ROOT / '.gitignore', self.tmp / '.gitignore')

    def ignored(self, paths):
        result = subprocess.run(
            ['git', '-c', 'core.excludesFile=/dev/null', 'check-ignore', '--no-index', '--stdin'],
            cwd=self.tmp, input='\n'.join(paths) + '\n',
            capture_output=True, text=True, check=False,
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return set(result.stdout.splitlines())

    def test_private_artifacts_are_ignored(self):
        paths = {
            '.env', '.env.local', '.env.production', 'config.json',
            'config.json.lock', 'config.json.write.lock',
            'private.key', 'private.pem', 'client.p12', 'client.pfx',
            'session.har', 'debug.log', 'cookies.json', 'cookies_cas.json',
            'cas_login.html', 'cas_postdata.txt', 'offline_resp.txt', 'captcha.png',
        }
        self.assertEqual(self.ignored(paths), paths)

    def test_examples_lockfile_and_source_remain_trackable(self):
        self.assertEqual(self.ignored({
            '.env.example', '.env.sample', 'uv.lock',
            'src/ysu_net/auth/account.py', 'docs/security.md',
        }), set())
