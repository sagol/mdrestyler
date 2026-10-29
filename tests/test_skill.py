"""The skill's references keep the rules the procedure depends on. Static checks of the text: they say a rule is
written, not that an agent follows it."""
import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / 'skills/mdrestyler'


def text(name):
    return (SKILL / name).read_text(encoding='utf-8')


class RestyleTextTests(unittest.TestCase):
    def setUp(self):
        self.restyle = text('references/restyle.md')

    def test_resume_classifies_in_the_order_the_contract_sets(self):
        states = re.findall(r'^\d\. \*\*(\w+):\*\*', self.restyle, re.M)
        self.assertEqual(states, ['unknown', 'stale', 'done', 'promoted', 'pending', 'conflict'])
        self.assertIn('Only pending units continue to takes', self.restyle)
        self.assertIn('an unchanged no-restyle unit stays done while a needs-restyle unit resumes', self.restyle)

    def test_the_controls_the_contract_names_are_written(self):
        for rule in ('If no unit needs a restyle, the run ends', 'A rejected pilot changes the profile or the decision note, never the preservation rules',
                     "a no-restyle unit's bytes differ from its assessed hash", '**guard unavailable**, and that unit cannot be promoted',
                     'A meaning change with unchanged numbers is a failure', 'Never splice takes',
                     'Promotion never happens without the recorded acceptance', 'never swap it silently',
                     'with one, `check` it'):
            with self.subTest(rule=rule):
                self.assertIn(rule, self.restyle)

    def test_preservation_covers_meaning_knowledge_and_attribution(self):
        for item in ('speaker, act and meaning', 'what each character knows and when, and the order of reveals',
                     'negation, attribution, qualification and cited claim', 'preserve list and ending constraints'):
            with self.subTest(item=item):
                self.assertIn(item, self.restyle)


class SkillTextTests(unittest.TestCase):
    def test_every_reference_the_skill_names_exists(self):
        for link in re.findall(r'\]\((references/[^)#]+)', text('SKILL.md')):
            with self.subTest(link=link):
                self.assertTrue((SKILL / link).is_file())

    def test_no_file_in_the_repository_names_a_private_path_or_another_product(self):
        root = SKILL.parents[1]
        words = re.compile('|'.join(['md' + 'narra', 'md' + 'editorial', 'md' + 'bindery', '/run/' + 'media', '/ho' + 'me/']), re.I)
        for path in root.rglob('*'):
            if path.is_file() and '.git' not in path.parts and '__pycache__' not in path.parts:
                found = words.search(path.read_bytes().decode('utf-8', errors='replace'))
                with self.subTest(file=str(path.relative_to(root))):
                    self.assertIsNone(found, found and found.group(0))


if __name__ == '__main__':
    unittest.main()
