from pathlib import Path
from validator import combine_results, validate_excel_file

sample = Path('/mnt/data/Anthea Y - Noon Report.xlsx')
with sample.open('rb') as f:
    result = validate_excel_file(f, file_name=sample.name)
combined = combine_results([result])
print(combined['portfolio_summary'])
print(combined['by_rule'].sort_values('count', ascending=False).head(20))
print('Errors:', len(combined['errors']))
print('Rows with issues:', (combined['checked_rows']['issue_count'] > 0).sum())
