---
doc_type: claims_guide
product_code: ALL
title: Claims Handling Guide
version: "1.0"
---

# Claims Handling Guide

## 1. Purpose and scope

This guide tells claims handlers how to decide an incoming home-insurance claim. It applies to
all three products: HOME-BASIC, HOME-STD and HOME-PLUS.

What each product covers, its limits, deductibles and exclusions are set out in the policy
wording for that product. Always use the wording of the product shown on the policy. Never use
the wording of another product to decide a claim.

Every claim ends with exactly one decision, one payout amount and one reason code.

## 2. Decisions

| Decision | When to use it | Payout | Human approval |
|---|---|---|---|
| `approve` | Covered claim, loss above the deductible and within the limit. | Loss minus deductible | Required |
| `partial` | Covered claim, loss above the limit. | Limit minus deductible | Required |
| `deny` | Policy not in force, peril not covered, exclusion applies, or loss not above the deductible. | €0 | Not required |
| `escalate` | A fraud indicator is present. The claim goes to the Special Investigations Unit. | €0 | Not required |
| `request_info` | Required information is missing, or the policy cannot be found. | €0 | Not required |

`escalate` and `request_info` are not final outcomes for the customer. They pause the claim
until someone else acts. The payout is €0 because no payment can be recommended yet.

## 3. Order of checks

Run the checks in this order. **Stop at the first check that gives a decision.** Do not skip a
check because a later one looks more relevant.

1. **Required information** (section 4). Anything missing → `request_info`.
2. **Policy lookup** (section 5). Policy not found → `request_info`.
3. **Policy in force** (section 6). Not in force on the loss date → `deny`.
4. **Peril covered** (section 7). Peril not covered by the product → `deny`.
5. **Exclusions** (section 8). An exclusion in the policy wording applies → `deny`.
6. **Fraud indicators** (section 9). Any indicator present → `escalate`.
7. **Payout** (section 10). Work out the amount and decide between `approve`, `partial` and
   `deny`.

## 4. Required information

A claim can only be assessed when it includes:

- the policy number;
- the loss date (the date the damage, loss or theft happened);
- the peril, or a description clear enough to identify it;
- the claimed amount in euro.

If the loss date or the claimed amount is missing, the decision is `request_info`. Ask the
customer for what is missing. Never guess a date or an amount, and never use the reported date
as the loss date.

| Missing | Reason code |
|---|---|
| Loss date only | `missing_loss_date` |
| Claimed amount only | `missing_claimed_amount` |
| Both loss date and claimed amount | `missing_loss_date_and_amount` |

## 5. Policy lookup

Look up the policy number in the policy system. If no policy exists with that number, the
decision is `request_info` with reason `policy_not_found`. Ask the customer to confirm the
policy number.

Never assume a product, a start date or a coverage for a policy that was not found.

## 6. Policy in force

A policy is in force on the loss date when:

- the loss date is on or after the policy start date, **and**
- the loss date is before the policy end date, **and**
- if the policy was cancelled, the loss date is before the cancellation date.

Use the loss date, not the reported date. A policy with status `lapsed` or `cancelled` may
still have been in force on the loss date, so always compare the dates.

If the policy was not in force on the loss date, the decision is `deny` with reason
`policy_not_in_force`.

## 7. Peril covered

Check that the peril of the claim is one of the perils covered by the policy (the coverages
recorded for the policy, which match the schedule of cover in the product's policy wording).

If the peril is not covered, the decision is `deny` with reason `peril_not_covered`. For
example, HOME-BASIC does not cover water damage or accidental damage, and HOME-STD does not
cover accidental damage.

Base the peril on what actually happened, as described by the customer. If the description
clearly points to a different peril than the one reported, use the peril the description
supports.

## 8. Exclusions

Even when the peril is covered, the policy wording may exclude the loss. Read the exclusions
section of the wording for the policy's product, and the "We do not cover" list of the peril
section, and compare them with the claim description.

The most common exclusion is **gradual damage**. Water damage is covered only when the water
escaped **suddenly**. If the description shows that the damage built up over time, the gradual
damage exclusion applies.

| Sudden: covered (if water damage is on the policy) | Gradual: excluded |
|---|---|
| Pipe burst overnight | Slow leak under a sink |
| Washing machine hose split | Dripping for several months |
| Frozen pipe cracked | Swollen floorboards, mould, damp, rot |
| Water came through the ceiling at once | Worn seals or grouting around a shower |

If the gradual damage exclusion applies, the decision is `deny` with reason
`exclusion_gradual_damage`.

## 9. Fraud indicators

Some patterns are known to be linked with fraudulent claims. A fraud indicator does not prove
fraud, so the handler must not deny the claim because of it. Instead, the decision is
`escalate` and the claim is passed to the Special Investigations Unit with €0 payout.

| Indicator | Rule | Reason code |
|---|---|---|
| Early claim | The loss date is fewer than **30 days** after the policy start date. | `fraud_signal_early_claim` |
| Claim frequency | The policy has **3 or more** previous claims with a loss date in the **12 months** before the new claim was reported. | `fraud_signal_claim_frequency` |

Notes:

- Early claim: compare the **loss date** with the policy **start date**. A loss 29 days after
  the start date is an early claim; a loss 30 days after it is not.
- Claim frequency: check the claims history of the policy. Count every previous claim, whatever
  its outcome (`paid`, `partial` or `denied`). Do not count the new claim itself.
- If both indicators are present, use `fraud_signal_early_claim`.

## 10. Payout

Look up the limit and the deductible for the peril on the policy. Then:

```
payout = max(min(claimed_amount, limit) - deductible, 0)
```

Round the payout to two decimal places (euro and cent).

| Situation | Decision | Payout | Reason code |
|---|---|---|---|
| Claimed amount is less than or equal to the deductible | `deny` | €0 | `below_deductible` |
| Claimed amount is above the deductible and less than or equal to the limit | `approve` | claimed amount − deductible | `covered_within_limit` |
| Claimed amount is above the limit | `partial` | limit − deductible | `exceeds_limit` |

Examples:

- HOME-PLUS, storm, claimed €200. The deductible is €250, so the claimed amount does not exceed
  it. Decision `deny`, payout €0, reason `below_deductible`.
- HOME-PLUS, accidental damage, claimed €2,000. Limit €15,000, deductible €150. Decision
  `approve`, payout €1,850, reason `covered_within_limit`.
- HOME-STD, storm, claimed €120,000. Limit €100,000, deductible €350. Decision `partial`,
  payout €99,650, reason `exceeds_limit`.

The payout is always calculated with the formula above. Never estimate or round it differently.

## 11. Human approval

A claims handler, or an automated assistant, may only **recommend** a payment. Every `approve`
or `partial` recommendation must be approved by a senior handler before any money is paid. The
senior handler can accept the recommendation, reject it, or change it.

`deny`, `escalate` and `request_info` decisions do not need this approval, because they do not
pay anything.

## 12. Reason codes

| Reason code | Decision | Meaning |
|---|---|---|
| `covered_within_limit` | `approve` | Covered loss, above the deductible and within the limit. |
| `exceeds_limit` | `partial` | Covered loss above the limit; the limit is paid, minus the deductible. |
| `below_deductible` | `deny` | Loss not above the deductible. |
| `policy_not_in_force` | `deny` | The policy was not in force on the loss date. |
| `peril_not_covered` | `deny` | The product does not cover the peril. |
| `exclusion_gradual_damage` | `deny` | The damage built up gradually and is excluded by the wording. |
| `fraud_signal_early_claim` | `escalate` | Loss fewer than 30 days after the policy start date. |
| `fraud_signal_claim_frequency` | `escalate` | 3 or more previous claims in the last 12 months. |
| `missing_loss_date` | `request_info` | The loss date is missing. |
| `missing_claimed_amount` | `request_info` | The claimed amount is missing. |
| `missing_loss_date_and_amount` | `request_info` | Both the loss date and the claimed amount are missing. |
| `policy_not_found` | `request_info` | No policy exists with the given number. |

## 13. Recording the decision

For every claim, record:

- the decision, the payout and the reason code;
- the policy data used (status, dates, product, coverage limit and deductible);
- the sections of the policy wording and of this guide that support the decision, for example
  "HOME-STD policy wording, 10.1 Gradual damage" or "Claims handling guide, 9. Fraud
  indicators";
- a short explanation in plain English.
