# Unit Tests
set -e
mkdir -p test-results
# Both test/ and tests/ hold real suites (A2A protocol/integration/router tests
# live under tests/) — run both so CI doesn't silently skip either one.
python -m pytest test/ tests/ --junit-xml=test-results/results.xml -v
