#!/usr/bin/env python3
"""
Diagnostic Configuration Validator

This script validates the diagnostic-parameters.yml configuration file
and provides helpful feedback about the configuration structure.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from jenkins_mcp_enterprise.diagnostic_config import (
        get_diagnostic_config,
        reload_diagnostic_config,
    )
except ImportError:
    print(
        "❌ Cannot import diagnostic config module. Make sure you're running from the project root."
    )
    sys.exit(1)


def validate_yaml_syntax(config_path: Path) -> bool:
    """Validate YAML syntax"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            yaml.safe_load(f)
        print(f"✅ YAML syntax valid: {config_path}")
        return True
    except yaml.YAMLError as e:
        print(f"❌ YAML syntax error in {config_path}: {e}")
        return False
    except FileNotFoundError:
        print(f"❌ Configuration file not found: {config_path}")
        return False
    except Exception as e:
        print(f"❌ Error reading {config_path}: {e}")
        return False


def validate_required_sections(config_data: Dict[str, Any]) -> bool:
    """Validate that required configuration sections exist"""
    required_sections = [
        "semantic_search",
        "failure_patterns",
        "recommendations",
        "build_processing",
        "summary",
        "context",
    ]

    missing_sections = []
    for section in required_sections:
        if section not in config_data:
            missing_sections.append(section)

    if missing_sections:
        print(f"❌ Missing required sections: {', '.join(missing_sections)}")
        return False

    print("✅ All required sections present")
    return True


def validate_semantic_search(config: Dict[str, Any]) -> bool:
    """Validate semantic search configuration"""
    semantic = config.get("semantic_search", {})
    issues = []

    # Check search queries
    queries = semantic.get("search_queries", [])
    if not queries:
        issues.append("No search queries defined")
    elif len(queries) < 3:
        issues.append(f"Only {len(queries)} search queries (recommend at least 3)")

    # Check score threshold
    score = semantic.get("min_diagnostic_score", 0.6)
    if not 0.0 <= score <= 1.0:
        issues.append(f"min_diagnostic_score {score} should be between 0.0 and 1.0")

    # Check limits
    max_results = semantic.get("max_results_per_query", 2)
    if max_results < 1:
        issues.append("max_results_per_query should be at least 1")

    if issues:
        print(f"⚠️  Semantic search issues: {'; '.join(issues)}")
        return False

    print(f"✅ Semantic search: {len(queries)} queries, score threshold {score}")
    return True


def validate_recommendations(config: Dict[str, Any]) -> bool:
    """Validate recommendations configuration"""
    recommendations = config.get("recommendations", {})
    patterns = recommendations.get("patterns", {})

    if not patterns:
        print("⚠️  No recommendation patterns defined")
        return False

    issues = []
    for name, pattern_config in patterns.items():
        if "conditions" not in pattern_config:
            issues.append(f"Pattern '{name}' missing conditions")
        if "message" not in pattern_config:
            issues.append(f"Pattern '{name}' missing message")

    if issues:
        print(f"❌ Recommendation issues: {'; '.join(issues)}")
        return False

    print(f"✅ Recommendations: {len(patterns)} patterns defined")
    return True


def validate_performance_settings(config: Dict[str, Any]) -> bool:
    """Validate performance-related settings"""
    build_proc = config.get("build_processing", {})
    parallel = build_proc.get("parallel", {})
    context = config.get("context", {})

    issues = []

    # Check parallel settings
    max_workers = parallel.get("max_workers", 5)
    max_batch = parallel.get("max_batch_size", 5)

    if max_workers > 20:
        issues.append(f"max_workers {max_workers} may be too high (recommend ≤ 20)")
    if max_batch > max_workers:
        issues.append(f"max_batch_size {max_batch} > max_workers {max_workers}")

    # Check token limits
    max_tokens = context.get("max_tokens_total", 10000)
    truncation = context.get("truncation_threshold", 8000)

    if truncation >= max_tokens:
        issues.append(
            f"truncation_threshold {truncation} >= max_tokens_total {max_tokens}"
        )

    if issues:
        print(f"⚠️  Performance issues: {'; '.join(issues)}")
        return False

    print(f"✅ Performance: {max_workers} workers, {max_tokens} tokens")
    return True


def test_config_loading() -> bool:
    """Test loading configuration through the actual system"""
    try:
        config = get_diagnostic_config()

        # Test key methods
        queries = config.get_semantic_search_queries()
        patterns = config.get_failure_patterns()
        recommendations = config.get_pattern_recommendations()

        print(
            f"✅ Configuration loading: {len(queries)} search queries, "
            f"{len(patterns)} failure patterns, {len(recommendations)} recommendations"
        )
        return True

    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return False


def find_config_files() -> List[Path]:
    """Find all potential configuration files"""
    config_files = []

    # Environment variable
    env_config = os.getenv("JENKINS_MCP_DIAGNOSTIC_CONFIG")
    if env_config:
        config_files.append(Path(env_config))

    # User override
    user_config = project_root / "config" / "diagnostic-parameters.yml"
    if user_config.exists():
        config_files.append(user_config)

    # Default bundled
    bundled_config = (
        project_root
        / "jenkins_mcp_enterprise"
        / "diagnostic_config"
        / "diagnostic-parameters.yml"
    )
    if bundled_config.exists():
        config_files.append(bundled_config)

    return config_files


def main():
    print("🔍 Jenkins MCP Diagnostic Configuration Validator")
    print("=" * 50)

    # Find configuration files
    config_files = find_config_files()

    if not config_files:
        print("❌ No configuration files found")
        return False

    print(f"📁 Found {len(config_files)} configuration file(s):")
    for i, config_file in enumerate(config_files, 1):
        status = "✅ exists" if config_file.exists() else "❌ missing"
        print(f"  {i}. {config_file} ({status})")

    print()

    # Validate each config file
    all_valid = True

    for config_file in config_files:
        if not config_file.exists():
            continue

        print(f"🔧 Validating: {config_file}")
        print("-" * 40)

        # YAML syntax
        if not validate_yaml_syntax(config_file):
            all_valid = False
            continue

        # Load config data
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
        except Exception as e:
            print(f"❌ Failed to load {config_file}: {e}")
            all_valid = False
            continue

        # Validate sections
        if not validate_required_sections(config_data):
            all_valid = False

        if not validate_semantic_search(config_data):
            all_valid = False

        if not validate_recommendations(config_data):
            all_valid = False

        if not validate_performance_settings(config_data):
            all_valid = False

        print()

    # Test system loading
    print("🎯 Testing System Integration")
    print("-" * 40)

    if not test_config_loading():
        all_valid = False

    # Summary
    print()
    print("📊 Validation Summary")
    print("=" * 50)

    if all_valid:
        print("✅ All validations passed!")
        print("🚀 Configuration is ready for use")

        # Provide next steps
        print("\n💡 Next Steps:")
        print(
            "1. Review the quick reference: config/diagnostic-parameters-quick-reference.md"
        )
        print("2. Customize for your environment using the complete guide")
        print("3. Test with a real Jenkins build diagnosis")

        return True
    else:
        print("❌ Some validations failed")
        print("📖 Check the diagnostic-parameters-guide.md for help")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
