# Evaluation report (full)

Run on 2026-10-31T04:39:24+00:00 with openai/gpt-oss-20b / openai/gpt-oss-120b, min confidence 0.7.

| Metric | Value |
|---|---|
| Seeded bugs caught | **41 of 42** (98%) |
| False-positive rate | **9%** (4 of 45 comments) |
| Clean PRs with any comment | 3 of 10 |
| Average review time | 7.3 s |
| Average cost per PR | ₹0.017 |
| LLM failures | 0 |

| Case | Bugs | Caught | Comments | False alarms | Risk | Model |
|---|---|---|---|---|---|---|
| auth-sql-injection | 1 | 1 | 1 | 0 | high | gpt-oss-120b |
| auth-password-length-inverted | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| auth-timing-compare | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| auth-login-skips-password-check | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| auth-session-expiry-inverted | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| auth-admin-check-bypass | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| auth-hardcoded-key | 1 | 1 | 1 | 0 | high | gpt-oss-120b |
| auth-logs-password | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| auth-md5-passwords | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| auth-predictable-token | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| cart-float-money | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| cart-allows-zero-quantity | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| cart-off-by-one-limit | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| cart-overwrites-quantity | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| cart-subtotal-ignores-quantity | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| payments-verify-false | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| payments-refund-swallows-error | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| payments-zero-charge | 1 | 1 | 2 | 0 | medium | gpt-oss-20b |
| payments-logs-key | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| payments-rupees-float | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| inventory-search-injection | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| inventory-race-condition | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| inventory-last-item | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| inventory-release-subtracts | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| inventory-unknown-product-zero | 1 | 0 | 0 | 0 | low | gpt-oss-20b |
| utils-paginate-off-by-one | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| utils-parse-int-returns-input | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| utils-format-rupees-float | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| utils-chunk-skips-items | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| utils-parse-int-eval | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| orders-swallows-failure | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| orders-idor | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| orders-cancel-paid | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| orders-ignores-discount | 1 | 1 | 1 | 0 | medium | gpt-oss-20b |
| db-missing-commit | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| db-string-formatting | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| new-reports-module | 2 | 2 | 3 | 1 | high | gpt-oss-20b |
| new-config-loader | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| new-admin-delete-user | 1 | 1 | 1 | 0 | high | gpt-oss-20b |
| new-notifications | 2 | 2 | 1 | 0 | medium | gpt-oss-20b |
| clean-docstring | 0 | 0 | 1 | 1 | medium | gpt-oss-20b |
| clean-rename | 0 | 0 | 0 | 0 | low | gpt-oss-20b |
| clean-clamp | 0 | 0 | 1 | 1 | medium | gpt-oss-20b |
| clean-inventory-tests | 0 | 0 | 0 | 0 | low | gpt-oss-20b |
| clean-cancel-logging | 0 | 0 | 0 | 0 | low | gpt-oss-20b |
| clean-count-products | 0 | 0 | 1 | 1 | high | gpt-oss-20b |
| clean-cart-clear | 0 | 0 | 0 | 0 | low | gpt-oss-20b |
| clean-readme | 0 | 0 | 0 | 0 | low | gpt-oss-20b |
| clean-negative-rupees | 0 | 0 | 0 | 0 | low | gpt-oss-20b |
| clean-item-count-test | 0 | 0 | 0 | 0 | low | gpt-oss-20b |
