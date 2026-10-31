"""The schema editors read must name every key the engine reads, and accept every plan the engine accepts."""
import json
import re
import unittest

from helpers import EXAMPLE, ROOT
from gitdone import plan as plan_module
from gitdone.scaffold import plan_data

SCHEMA = json.loads((ROOT / "schema" / "plan.schema.json").read_text(encoding="utf-8"))
SOURCE = (ROOT / "gitdone" / "plan.py").read_text(encoding="utf-8")


class Keys(unittest.TestCase):
    def test_every_key_the_plan_reads_is_in_the_schema(self):
        read = set(re.findall(r'data(?:\.get\(|\[)"(\w+)"', SOURCE))
        read |= set(re.findall(r'_typed\(data, "(\w+)"', SOURCE))
        self.assertGreater(len(read), 10)
        self.assertEqual(sorted(read - set(SCHEMA["properties"])), [])

    def test_the_section_types_agree(self):
        schema_types = SCHEMA["properties"]["sections"]["items"]["properties"]["type"]["enum"]
        self.assertEqual(sorted(schema_types), sorted(plan_module.SECTION_TYPES))

    def test_the_evidence_rules_agree(self):
        kinds = SCHEMA["properties"]["kinds"]["items"]["properties"]["evidence"]["enum"]
        self.assertEqual(set(kinds), set(plan_module.EVIDENCE_RULES))

    def test_a_new_plan_names_the_schema(self):
        self.assertEqual(plan_data("x", True, "main")["$schema"], SCHEMA["$id"])

    def test_every_key_of_the_example_is_known_or_a_list_the_sections_read(self):
        example = json.loads((EXAMPLE / "plan.json").read_text(encoding="utf-8"))
        read_by_sections = {s.get("from") for s in example["sections"]}
        self.assertEqual(sorted(set(example) - set(SCHEMA["properties"]) - read_by_sections), [])


if __name__ == "__main__":
    unittest.main()
