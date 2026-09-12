# Execution Scripts (Layer 3)

This directory contains deterministic Python scripts responsible for performing the actual work:
- API calls
- Data processing
- File operations
- Database interactions

## Guidelines
1. **Deterministic & Testable**: Keep scripts reliable, self-contained, and well-commented.
2. **Environment Variables**: Load secrets and configurations from `.env` (never hardcode).
3. **Intermediates**: Store temporary/scratch files in `.tmp/`.
4. **Self-Annealing**: When an issue is discovered or an API constraint is hit, update the script and update the corresponding directive in `directives/`.
