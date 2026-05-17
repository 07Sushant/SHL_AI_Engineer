import unittest

from app.agent import answer
from app.catalog import Product


def product(name, url, test_type="K", keys=("Knowledge & Skills",), description="Catalog item."):
    return Product(
        entity_id=name,
        name=name,
        url=url,
        test_type=test_type,
        keys=keys,
        duration="10 minutes",
        languages=("English (USA)",),
        job_levels=("Mid-Professional",),
        description=description,
    )


class FakeCatalog:
    def __init__(self):
        self.items = [
            product("Core Java (Advanced Level) (New)", "https://www.shl.com/products/product-catalog/view/core-java-advanced-level-new/"),
            product("Spring (New)", "https://www.shl.com/products/product-catalog/view/spring-new/"),
            product("RESTful Web Services (New)", "https://www.shl.com/products/product-catalog/view/restful-web-services-new/"),
            product("SQL (New)", "https://www.shl.com/products/product-catalog/view/sql-new/"),
            product("Amazon Web Services (AWS) Development (New)", "https://www.shl.com/products/product-catalog/view/amazon-web-services-aws-development-new/"),
            product("Docker (New)", "https://www.shl.com/products/product-catalog/view/docker-new/"),
            product("Python (New)", "https://www.shl.com/products/product-catalog/view/python-new/"),
            product("SHL Verify Interactive G+", "https://www.shl.com/products/product-catalog/view/shl-verify-interactive-g/", "A", ("Ability & Aptitude",)),
            product("Occupational Personality Questionnaire OPQ32r", "https://www.shl.com/products/product-catalog/view/occupational-personality-questionnaire-opq32r/", "P", ("Personality & Behavior",)),
            product("Global Skills Assessment", "https://www.shl.com/products/product-catalog/view/global-skills-assessment/", "K", ("Knowledge & Skills",)),
        ]

    def get_products(self):
        return self.items

    def find_by_name(self, name):
        name_norm = name.lower().strip()
        for item in self.items:
            if item.name.lower().strip() == name_norm:
                return item
        for item in self.items:
            if name_norm and (name_norm in item.name.lower() or item.name.lower() in name_norm):
                return item
        return None

    def products_by_names(self, names):
        found = []
        seen = set()
        for name in names:
            item = self.find_by_name(name)
            if item and item.url not in seen:
                found.append(item)
                seen.add(item.url)
        return found


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FakeCatalog()

    def test_vague_query_clarifies(self):
        response = answer([{"role": "user", "content": "I need an assessment"}], self.catalog)
        self.assertEqual(response.recommendations, [])
        self.assertFalse(response.end_of_conversation)

    def test_legal_question_refuses(self):
        response = answer([{"role": "user", "content": "Are we legally required to test staff?"}], self.catalog)
        self.assertEqual(response.recommendations, [])
        self.assertIn("legal", response.reply.lower())

    def test_java_recommendation_uses_catalog_urls(self):
        response = answer(
            [{"role": "user", "content": "Hiring a senior Java engineer with Spring SQL AWS Docker."}],
            self.catalog,
        )
        names = [item.name for item in response.recommendations]
        self.assertIn("Core Java (Advanced Level) (New)", names)
        self.assertTrue(all(item.url.startswith("https://www.shl.com/products/product-catalog/view/") for item in response.recommendations))

    def test_refinement_drops_rest(self):
        first = answer(
            [{"role": "user", "content": "Hiring a senior Java engineer with Spring SQL REST AWS Docker."}],
            self.catalog,
        )
        second = answer(
            [
                {"role": "user", "content": "Hiring a senior Java engineer with Spring SQL REST AWS Docker."},
                {"role": "assistant", "content": first.reply},
                {"role": "user", "content": "Drop REST."},
            ],
            self.catalog,
        )
        names = [item.name for item in second.recommendations]
        self.assertNotIn("RESTful Web Services (New)", names)

    def test_scratch_java_switches_to_python(self):
        first = answer(
            [{"role": "user", "content": "Hiring a senior Java engineer."}],
            self.catalog,
        )
        second = answer(
            [
                {"role": "user", "content": "Hiring a senior Java engineer."},
                {"role": "assistant", "content": first.reply},
                {
                    "role": "user",
                    "content": "Actually, scratch the Java stuff, my boss says we need a Python guy who is good at talking to clients, maybe a personality test?",
                },
            ],
            self.catalog,
        )
        names = [item.name for item in second.recommendations]
        self.assertIn("Python (New)", names)
        self.assertIn("Occupational Personality Questionnaire OPQ32r", names)
        self.assertNotIn("Core Java (Advanced Level) (New)", names)

    def test_comparison_opq32r_vs_gsa(self):
        response = answer(
            [{"role": "user", "content": "What is the difference between the OPQ32r and the GSA?"}],
            self.catalog,
        )
        names = [item.name for item in response.recommendations]
        self.assertIn("Occupational Personality Questionnaire OPQ32r", names)
        self.assertIn("Global Skills Assessment", names)
        self.assertNotIn("What role are you hiring for", response.reply)


if __name__ == "__main__":
    unittest.main()
