# Unit Tests
set -e
mkdir -p test-results
python -m pytest test/ --junit-xml=test-results/results.xml -v
