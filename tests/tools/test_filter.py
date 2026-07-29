"""
Unit tests for text filter
"""

import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock, patch

# tools/ reaches sys.path via conftest.py in this directory, so importing
# this module has no side effects of its own.
from filter_all_words import (
    FilterConfig, TextFilter, WordListManager, 
    FilterStats, FilterApplication
)

class TestWordListManager(unittest.TestCase):
    """Test word list management"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = WordListManager(cache_dir=self.temp_dir)
        
    def test_load_word_list(self):
        """Test loading word list from file"""
        # Create temporary word list
        word_file = Path(self.temp_dir) / "test_words.txt"
        words = ["test", "word", "list"]
        word_file.write_text("\n".join(words))
        
        # Load words
        loaded = self.manager.load_word_list("test", str(word_file))
        self.assertEqual(loaded, {"test", "word", "list"})
        
    def test_compile_pattern(self):
        """Test pattern compilation"""
        words = {"hello", "world"}
        pattern = self.manager.compile_pattern("test", words)
        
        self.assertIsNotNone(pattern)
        self.assertTrue(pattern.search("hello world"))
        self.assertFalse(pattern.search("helloworld"))
        
    def test_a_cache_hit_still_reports_what_it_replaced(self):
        """It returned an empty count dict on a hit.

        Every repeated message was then recorded as having had nothing
        replaced. The filtering was right and the report about it was wrong,
        which is the worse of the two.
        """

        import re
        config = FilterConfig(
            input_path="in.json", output_path="out.json",
            replacements={"test": "heck"},
            options={"cache_enabled": True},
        )
        text_filter = TextFilter(config)
        text_filter.patterns["test"] = re.compile(r"\bbad\b", re.IGNORECASE)

        first_text, first_counts = text_filter.filter_text("a bad word")
        second_text, second_counts = text_filter.filter_text("a bad word")

        self.assertEqual(text_filter.stats.cache_hits, 1)
        self.assertEqual(second_text, first_text)
        self.assertEqual(second_counts, first_counts)
        self.assertEqual(second_counts, {"test": 1})

    def test_building_the_manager_creates_no_directory(self):
        """It used to mkdir on construction, into the current directory."""

        target = Path(self.temp_dir) / "not_yet"
        WordListManager(cache_dir=str(target))

        self.assertFalse(target.exists())

    def test_cache_functionality(self):
        """Test caching mechanism"""
        word_file = Path(self.temp_dir) / "cache_test.txt"
        word_file.write_text("cached\nwords")
        
        # First load - should cache
        loaded1 = self.manager.load_word_list("test", str(word_file))
        
        # Second load - should use cache
        loaded2 = self.manager.load_word_list("test", str(word_file))
        
        self.assertEqual(loaded1, loaded2)

class TestTextFilter(unittest.TestCase):
    """Test text filtering functionality"""
    
    def setUp(self):
        self.config = FilterConfig(
            input_path="test.json",
            output_path="filtered.json",
            replacements={"test": "[REMOVED]"},
            options={"preserve_capitalization": True}
        )
        self.filter = TextFilter(self.config)
        
    def test_filter_text_basic(self):
        """Test basic text filtering"""
        # Mock pattern
        import re
        self.filter.patterns["test"] = re.compile(r"\bbad\b", re.IGNORECASE)
        
        text = "This is a bad word"
        filtered, counts = self.filter.filter_text(text)
        
        self.assertEqual(filtered, "This is a [REMOVED] word")
        self.assertEqual(counts["test"], 1)
        
    def test_preserve_capitalization(self):
        """Test capitalization preservation.

        The replacement has to be a word for this to mean anything. With the
        "[REMOVED]" sentinel this test used, it contradicted
        test_filter_text_basic: both filter a lowercase match with the same
        config, and they expected different output. The real configured
        replacements are words ("heck"), which is what is exercised here.
        """

        import re
        self.filter.patterns["test"] = re.compile(r"\bbad\b", re.IGNORECASE)
        self.filter.config.replacements["test"] = "heck"

        test_cases = [
            ("bad word", "heck word"),
            ("Bad word", "Heck word"),
            ("BAD word", "HECK word"),
        ]

        for original, expected in test_cases:
            filtered, _ = self.filter.filter_text(original)
            self.assertEqual(filtered, expected)

    def test_a_sentinel_replacement_is_left_alone(self):
        """"$p$" and "[REMOVED]" have no capitalisation to preserve."""

        import re
        self.filter.patterns["test"] = re.compile(r"\bbad\b", re.IGNORECASE)

        for original in ("bad word", "Bad word", "BAD word"):
            filtered, _ = self.filter.filter_text(original)
            self.assertIn("[REMOVED]", filtered)
            
    def test_process_single_message(self):
        """Test single message processing"""
        message = {
            "id": 1,
            "message": "Test message",
            "timestamp": "2024-01-01"
        }
        
        # Process message
        result = self.filter._process_single_message(message)
        
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["message"], "Test message")
        self.assertEqual(self.filter.stats.total_messages, 1)

class TestFilterApplication(unittest.TestCase):
    """Test main application functionality"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.input_file = Path(self.temp_dir) / "input.json"
        self.output_file = Path(self.temp_dir) / "output.json"
        
        # Create test data
        test_messages = [
            {"id": 1, "message": "Hello world"},
            {"id": 2, "message": "Bad word here"}
        ]
        self.input_file.write_text(json.dumps(test_messages))
        
        self.config = FilterConfig(
            input_path=str(self.input_file),
            output_path=str(self.output_file)
        )
        
    def test_load_messages(self):
        """Test message loading"""
        app = FilterApplication(self.config)
        messages = app._load_messages()
        
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["message"], "Hello world")
        
    def test_save_messages(self):
        """Test message saving"""
        app = FilterApplication(self.config)
        messages = [{"id": 1, "message": "Filtered"}]
        
        app._save_messages(messages)
        
        self.assertTrue(self.output_file.exists())
        saved = json.loads(self.output_file.read_text())
        self.assertEqual(saved[0]["message"], "Filtered")
        
    @patch('filter_all_words.logger')
    def test_run_application(self, mock_logger):
        """Test full application run"""
        app = FilterApplication(self.config)
        
        # Mock filter initialization
        app.filter.initialize = Mock()
        app.filter.process_messages = Mock(return_value=[
            {"id": 1, "message": "Filtered message"}
        ])
        
        app.run()
        
        self.assertTrue(self.output_file.exists())
        app.filter.initialize.assert_called_once()
        app.filter.process_messages.assert_called_once()

class TestFilterStats(unittest.TestCase):
    """Test statistics tracking"""
    
    def test_stats_tracking(self):
        """Test statistics accumulation"""
        stats = FilterStats()
        
        stats.total_messages = 100
        stats.filtered_messages = 25
        stats.replacements_by_category["profanity"] = 10
        stats.replacements_by_category["names"] = 15
        
        stats_dict = stats.to_dict()
        
        self.assertEqual(stats_dict["total_messages"], 100)
        self.assertEqual(stats_dict["filtered_messages"], 25)
        self.assertEqual(stats_dict["replacements_by_category"]["profanity"], 10)

if __name__ == '__main__':
    unittest.main()