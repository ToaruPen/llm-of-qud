# .vulture_whitelist.py — llm-of-qud
# Entries here silence vulture false-positives for names that are "used"
# by external systems (pytest fixtures, Pydantic validators, CoQ callbacks).
#
# Format: add an attribute access or call to each name you want to keep.
# See: https://github.com/jendrikseipp/vulture#whitelists
#
# Example:
#   _.my_fixture        # pytest fixture consumed by test functions via injection
#   _.model_validator   # Pydantic validator called by Pydantic, not direct code

# Populate as dead-code warnings are confirmed to be false positives.
