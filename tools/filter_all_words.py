#!/usr/bin/env python3
"""
Professional Text Content Filter
A high-performance, configurable text filtering system for message sanitization.
"""

import os
import sys
import re
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, Set, List, Tuple, Optional, Union, Any
from dataclasses import dataclass, field
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

# Optional. Neither is needed to filter anything: yaml only loads an optional
# config file, and tqdm only draws a progress bar. Importing them at module
# level made the whole module — and its test suite — unimportable without two
# packages it does not need.
try:
    import yaml
except ImportError:                     # pragma: no cover - environment
    yaml = None

try:
    from tqdm import tqdm
except ImportError:                     # pragma: no cover - environment
    def tqdm(iterable, **_kwargs):
        return iterable

logger = logging.getLogger(__name__)


def configure_logging(level: str = 'INFO', log_file: str = 'filter_log.log'):
    """Set up logging. Called from main(), never on import.

    At import time this wrote filter_log.log into whatever directory happened
    to be current, including during a test run.
    """

    logging.basicConfig(
        level=getattr(logging, level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

@dataclass
class FilterConfig:
    """Configuration for text filtering"""
    input_path: str
    output_path: str
    word_lists: Dict[str, str] = field(default_factory=dict)
    replacements: Dict[str, str] = field(default_factory=dict)
    patterns: Dict[str, str] = field(default_factory=dict)
    options: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_yaml(cls, config_path: str) -> 'FilterConfig':
        """Load configuration from YAML file"""
        if yaml is None:
            raise RuntimeError(
                "--config needs PyYAML, which is not installed. Install it "
                "with 'pip install pyyaml', or pass --input and --output "
                "instead."
            )
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return cls(**data)
    
    @classmethod
    def from_args(cls, args: argparse.Namespace) -> 'FilterConfig':
        """Create configuration from command line arguments"""
        return cls(
            input_path=args.input,
            output_path=args.output,
            word_lists={
                'profanity': args.profanity_file,
                'problem': args.problem_file,
                'abc': args.abc_file,
                'name': args.name_file,
                'name2': args.name2_file
            },
            replacements={
                'profanity': args.profanity_replacement or 'heck',
                'problem': args.problem_replacement or '$p$',
                'abc': args.abc_replacement or '$a$',
                'name': args.name_replacement or '$n$',
                'name2': args.name2_replacement or '$n2$'
            },
            options={
                'case_sensitive': args.case_sensitive,
                'whole_words_only': args.whole_words,
                'preserve_capitalization': args.preserve_caps,
                'parallel_processing': args.parallel,
                'batch_size': args.batch_size,
                'cache_enabled': args.enable_cache
            }
        )

@dataclass
class FilterStats:
    """Statistics for filtering operation"""
    total_messages: int = 0
    filtered_messages: int = 0
    total_replacements: int = 0
    replacements_by_category: Dict[str, int] = field(default_factory=Counter)
    processing_time: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_messages': self.total_messages,
            'filtered_messages': self.filtered_messages,
            'total_replacements': self.total_replacements,
            'replacements_by_category': dict(self.replacements_by_category),
            'processing_time': f"{self.processing_time:.2f} seconds",
            'cache_efficiency': f"{(self.cache_hits / (self.cache_hits + self.cache_misses) * 100):.1f}%" if self.cache_hits + self.cache_misses > 0 else "N/A"
        }

class WordListManager:
    """Manages word lists with caching and optimization"""
    
    def __init__(self, cache_dir: str = ".filter_cache"):
        # The directory is created when something is written to it, not when
        # the object is built. Constructing this used to litter .filter_cache
        # into whatever directory was current, including during a test run.
        self.cache_dir = Path(cache_dir)
        self.word_lists: Dict[str, Set[str]] = {}
        self._compiled_patterns: Dict[str, re.Pattern] = {}
        
    def load_word_list(self, category: str, filepath: str, case_sensitive: bool = False) -> Set[str]:
        """Load word list with caching"""
        if not filepath or not os.path.exists(filepath):
            logger.warning(f"Word list file not found for {category}: {filepath}")
            return set()
            
        # Check cache
        cache_key = self._get_cache_key(filepath, case_sensitive)
        cached_data = self._load_from_cache(cache_key)
        if cached_data is not None:
            logger.info(f"Loaded {category} word list from cache")
            return cached_data
            
        # Load from file
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                words = set()
                for line in f:
                    word = line.strip()
                    if word:
                        words.add(word if case_sensitive else word.lower())
                        
            # Save to cache
            self._save_to_cache(cache_key, words)
            logger.info(f"Loaded {len(words)} words for {category} from {filepath}")
            return words
            
        except Exception as e:
            logger.error(f"Error loading word list {filepath}: {e}")
            return set()
    
    def compile_pattern(self, category: str, words: Set[str], whole_words_only: bool = True) -> Optional[re.Pattern]:
        """Compile optimized regex pattern for word matching"""
        if not words:
            return None
            
        # Sort by length (longest first) for better matching
        sorted_words = sorted(words, key=len, reverse=True)
        
        # Escape special regex characters
        escaped_words = [re.escape(word) for word in sorted_words]
        
        # Build pattern
        if whole_words_only:
            pattern = r'\b(' + '|'.join(escaped_words) + r')\b'
        else:
            pattern = '(' + '|'.join(escaped_words) + ')'
            
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            self._compiled_patterns[category] = compiled
            return compiled
        except Exception as e:
            logger.error(f"Error compiling pattern for {category}: {e}")
            return None
    
    def _get_cache_key(self, filepath: str, case_sensitive: bool) -> str:
        """Generate cache key for word list"""
        stat = os.stat(filepath)
        content = f"{filepath}:{stat.st_mtime}:{stat.st_size}:{case_sensitive}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _load_from_cache(self, cache_key: str) -> Optional[Set[str]]:
        """Load word list from cache.

        JSON, not pickle. Unpickling is arbitrary code execution, and this
        read a file from a directory created with default permissions whose
        name is derived from a path the caller supplied. A cache of words does
        not need a format that can run anything.
        """

        cache_file = self.cache_dir / f"{cache_key}.json"
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except (OSError, ValueError) as e:
            # Was a bare except, which also swallowed KeyboardInterrupt.
            logger.debug(f"Ignoring unreadable cache {cache_file}: {e}")
            return None

    def _save_to_cache(self, cache_key: str, data: Set[str]) -> None:
        """Save word list to cache"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self.cache_dir / f"{cache_key}.json"
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(sorted(data), f)
        except OSError as e:
            logger.warning(f"Failed to save cache: {e}")

class TextFilter:
    """Advanced text filtering with multiple strategies"""
    
    def __init__(self, config: FilterConfig):
        self.config = config
        self.word_manager = WordListManager()
        self.stats = FilterStats()
        self.patterns: Dict[str, re.Pattern] = {}
        self._filter_cache: Dict[str, str] = {}
        
    def initialize(self) -> None:
        """Initialize word lists and compile patterns"""
        logger.info("Initializing text filter...")
        
        for category, filepath in self.config.word_lists.items():
            if filepath:
                words = self.word_manager.load_word_list(
                    category, 
                    filepath, 
                    self.config.options.get('case_sensitive', False)
                )
                
                if words:
                    pattern = self.word_manager.compile_pattern(
                        category,
                        words,
                        self.config.options.get('whole_words_only', True)
                    )
                    if pattern:
                        self.patterns[category] = pattern
                        
        logger.info(f"Initialized {len(self.patterns)} filter patterns")
    
    # _filter_text_cached was removed: nothing called it, and lru_cache on an
    # instance method keys on self, which keeps every filter that ever ran
    # alive for the life of the process. filter_text does the caching.

    def filter_text(self, text: str) -> Tuple[str, Dict[str, int]]:
        """Filter text using all configured patterns"""
        if not text:
            return text, {}
            
        # The cache stores the counts as well as the text. It used to return
        # an empty dict on a hit, so every repeated message was recorded as
        # having had nothing replaced: the filtering was right and the report
        # about it was wrong, which is the worse of the two.
        cache_key = None
        if self.config.options.get('cache_enabled', True):
            cache_key = hashlib.md5(text.encode()).hexdigest()
            if cache_key in self._filter_cache:
                self.stats.cache_hits += 1
                return self._filter_cache[cache_key]
            self.stats.cache_misses += 1
        
        filtered_text = text
        replacement_counts = Counter()
        
        # Apply each filter pattern
        for category, pattern in self.patterns.items():
            if pattern:
                filtered_text, count = self._filter_text(
                    filtered_text,
                    pattern,
                    self.config.replacements.get(category, '[FILTERED]')
                )
                if count > 0:
                    replacement_counts[category] = count
                    
        result = (filtered_text, dict(replacement_counts))
        if cache_key is not None and len(self._filter_cache) < 10000:
            self._filter_cache[cache_key] = result

        return result
    
    def _filter_text(self, text: str, pattern: re.Pattern, replacement: str) -> Tuple[str, int]:
        """Apply single filter pattern to text"""
        if self.config.options.get('preserve_capitalization', True):
            matches = list(pattern.finditer(text))
            if not matches:
                return text, 0
                
            # Process matches in reverse order to maintain positions
            for match in reversed(matches):
                original = match.group(0)

                # Case is only preserved onto a replacement that is a word.
                # A sentinel like "[REMOVED]" or "$p$" has no capitalisation
                # to match, and the old code mangled it: "[REMOVED]" became
                # "[removed]" under a lowercase match, and the title-case
                # branch uppercased the bracket and lowercased the word.
                if not replacement.isalpha():
                    repl = replacement
                elif original.isupper():
                    repl = replacement.upper()
                elif original[0].isupper():
                    repl = replacement.capitalize()
                else:
                    repl = replacement.lower()


                text = text[:match.start()] + repl + text[match.end():]
                
            return text, len(matches)
        else:
            return pattern.subn(replacement, text)
    
    def process_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process a list of messages"""
        filtered_messages = []
        
        if self.config.options.get('parallel_processing', True) and len(messages) > 100:
            # Parallel processing for large datasets
            filtered_messages = self._process_parallel(messages)
        else:
            # Sequential processing
            for message in tqdm(messages, desc="Filtering messages"):
                filtered_messages.append(self._process_single_message(message))
                
        return filtered_messages
    
    def _process_parallel(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process messages across threads.

        Threads, not processes, and the work is regular-expression matching in
        Python, which holds the GIL. The wall-clock gain is small; the batching
        and the progress bar are the real benefit. Named honestly rather than
        replaced, because switching to processes would mean pickling the
        compiled patterns for every batch.
        """

        batch_size = self.config.options.get('batch_size', 1000)
        filtered_messages = [None] * len(messages)
        
        with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            # Submit batches
            futures = {}
            for i in range(0, len(messages), batch_size):
                batch = messages[i:i + batch_size]
                future = executor.submit(self._process_batch, batch)
                futures[future] = i
                
            # Collect results
            for future in tqdm(as_completed(futures), total=len(futures), desc="Processing batches"):
                start_idx = futures[future]
                batch_results = future.result()
                for j, result in enumerate(batch_results):
                    filtered_messages[start_idx + j] = result
                    
        return filtered_messages
    
    def _process_batch(self, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process a batch of messages"""
        return [self._process_single_message(msg) for msg in batch]
    
    def _process_single_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single message"""
        self.stats.total_messages += 1
        result = message.copy()
        
        if 'message' in result and result['message']:
            original_text = result['message']
            filtered_text, replacements = self.filter_text(original_text)
            
            if filtered_text != original_text:
                result['message'] = filtered_text
                result['_filtered'] = True
                result['_replacements'] = replacements
                
                self.stats.filtered_messages += 1
                for category, count in replacements.items():
                    self.stats.replacements_by_category[category] += count
                    self.stats.total_replacements += count
                    
        return result
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate filtering report"""
        return {
            'timestamp': datetime.now().isoformat(),
            'configuration': {
                'input': self.config.input_path,
                'output': self.config.output_path,
                'filters_active': list(self.patterns.keys()),
                'options': self.config.options
            },
            'statistics': self.stats.to_dict(),
            'top_filtered_categories': self.stats.replacements_by_category.most_common(5)
        }

class FilterApplication:
    """Main application class"""
    
    def __init__(self, config: FilterConfig):
        self.config = config
        self.filter = TextFilter(config)
        
    def run(self) -> None:
        """Run the filtering application"""
        start_time = datetime.now()
        
        try:
            # Initialize filter
            self.filter.initialize()
            
            # Load input data
            logger.info(f"Loading messages from {self.config.input_path}")
            messages = self._load_messages()
            
            if not messages:
                logger.error("No messages found in input file")
                return
                
            logger.info(f"Loaded {len(messages)} messages")
            
            # Process messages
            filtered_messages = self.filter.process_messages(messages)
            
            # Save results
            self._save_messages(filtered_messages)
            
            # Generate and save report
            self.filter.stats.processing_time = (datetime.now() - start_time).total_seconds()
            report = self.filter.generate_report()
            self._save_report(report)
            
            # Display summary
            self._display_summary(report)
            
        except Exception as e:
            logger.error(f"Error during filtering: {e}", exc_info=True)
            raise
    
    def _load_messages(self) -> List[Dict[str, Any]]:
        """Load messages from input file"""
        input_path = Path(self.config.input_path)
        
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
            
        if input_path.suffix == '.json':
            with open(input_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        elif input_path.suffix == '.jsonl':
            messages = []
            with open(input_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        messages.append(json.loads(line))
            return messages
        else:
            raise ValueError(f"Unsupported input format: {input_path.suffix}")
    
    def _save_messages(self, messages: List[Dict[str, Any]]) -> None:
        """Save filtered messages"""
        output_path = Path(self.config.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if output_path.suffix == '.json':
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(messages, f, indent=2, ensure_ascii=False)
        elif output_path.suffix == '.jsonl':
            with open(output_path, 'w', encoding='utf-8') as f:
                for msg in messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + '\n')
                    
        logger.info(f"Saved filtered messages to {output_path}")
    
    def _save_report(self, report: Dict[str, Any]) -> None:
        """Save filtering report"""
        report_path = Path(self.config.output_path).with_suffix('.report.json')
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
            
        logger.info(f"Saved report to {report_path}")
    
    def _display_summary(self, report: Dict[str, Any]) -> None:
        """Display filtering summary"""
        stats = report['statistics']
        
        print("\n" + "=" * 50)
        print("FILTERING SUMMARY")
        print("=" * 50)
        print(f"Total messages processed: {stats['total_messages']:,}")
        print(f"Messages with replacements: {stats['filtered_messages']:,}")
        print(f"Total replacements made: {stats['total_replacements']:,}")
        print(f"Processing time: {stats['processing_time']}")
        print(f"Cache efficiency: {stats['cache_efficiency']}")
        
        if report['top_filtered_categories']:
            print("\nTop filtered categories:")
            for category, count in report['top_filtered_categories']:
                print(f"  - {category}: {count:,} replacements")
                
        print("=" * 50 + "\n")

def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser"""
    parser = argparse.ArgumentParser(
        description="Professional text content filter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python filter_all_words.py -i messages.json -o filtered.json
  
  # With custom word lists
  python filter_all_words.py -i messages.json -o filtered.json \
    --profanity-file profanity.txt --problem-file problems.txt
  
  # With custom replacements
  python filter_all_words.py -i messages.json -o filtered.json \
    --profanity-replacement "[removed]" --preserve-caps
  
  # Using configuration file
  python filter_all_words.py --config filter_config.yaml
"""
    )
    
    # Input/Output
    parser.add_argument('-i', '--input', help='Input file path')
    parser.add_argument('-o', '--output', help='Output file path')
    parser.add_argument('-c', '--config', help='Configuration file (YAML)')
    
    # Word lists
    parser.add_argument('--profanity-file', help='Profanity word list')
    parser.add_argument('--problem-file', help='Problem words list')
    parser.add_argument('--abc-file', help='ABC words list')
    parser.add_argument('--name-file', help='Name words list')
    parser.add_argument('--name2-file', help='Name2 words list')
    
    # Replacements
    parser.add_argument('--profanity-replacement', help='Replacement for profanity')
    parser.add_argument('--problem-replacement', help='Replacement for problem words')
    parser.add_argument('--abc-replacement', help='Replacement for ABC words')
    parser.add_argument('--name-replacement', help='Replacement for names')
    parser.add_argument('--name2-replacement', help='Replacement for name2')
    
    # Options
    parser.add_argument('--case-sensitive', action='store_true', help='Case sensitive matching')
    parser.add_argument('--whole-words', action='store_true', default=True, help='Match whole words only')
    parser.add_argument('--preserve-caps', action='store_true', default=True, help='Preserve capitalization')
    parser.add_argument('--parallel', action='store_true', default=True, help='Enable parallel processing')
    parser.add_argument('--batch-size', type=int, default=1000, help='Batch size for parallel processing')
    parser.add_argument('--enable-cache', action='store_true', default=True, help='Enable caching')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default='INFO')
    
    return parser

def main():
    """Main entry point"""
    parser = create_parser()
    args = parser.parse_args()

    configure_logging(args.log_level)
    
    # Load configuration
    if args.config:
        config = FilterConfig.from_yaml(args.config)
    else:
        if not args.input or not args.output:
            parser.error("Either --config or both --input and --output are required")
        config = FilterConfig.from_args(args)
    
    # Run application
    app = FilterApplication(config)
    app.run()

if __name__ == "__main__":
    main()